"""The keys of the published data, and their lock ``data/published.toml``.

The site is deployed in parts, each a Cloudflare Pages project of its own
(docs/deploy.md): the app, a map bundle and a data bundle per election,
the cached copies of the pages research cites (sources) and the results.
Every part but the app has a key, a digest of everything in the
repository its content depends on, computed without building anything: a
part whose key is deployed already is neither built nor deployed again,
and the app names each election's bundles by the deployments that carry
their keys.

An election's map (``geo/``, ``base/``, ``addr/``: :func:`map_key`)
depends on that election alone:

- the inputs its steps read (``candidates``, ``geo``, ``basemap`` and
  ``addresses``; the contests and candidacies of ``candidates.json`` shape
  the map) as configured, their pins included: its candidate lists and
  the results its office holders come from, its boundaries, the countries
  around, its address register, territorial division and base map
  extract;
- what those steps read of its table of ``config/elections.toml`` and of
  ``config/overrides.toml``;
- its curated data (``data/curated/elections/<day>/``: an earlier
  election's rule sets reused from a later one are copies there);
- the code of those steps (:data:`MAP_MODULES` and what they import, and
  their part of the CLI, :data:`MAP_GLUE`) and the libraries it runs on.

An election's data (candidates, research, occupations, About) and the
results depend on every election (:func:`keys`): each election's persons
are linked to those of every other, with their candidacies and results
there; the research of the latest's candidates is reused for the earlier
ones; an election's results are compared with the polling districts,
addresses and results of the election before. So their keys share all of
it: every input but the base map extracts and the records of sources (an
election's records count for its own data only), what the steps read of
``config/elections.toml``, the other files of ``config/`` but
``site.toml``, all curated data, research and the translations of
occupations and research texts, and the code that makes the data
(:data:`DATA_MODULES` and what they import, and the CLI). A new research
finding, a corrected link or a new translation thus changes every data
key and no map key. The cached sources depend only on which pages the
research cites, the stylesheet they link and their response headers.

Code counts by its syntax tree (:func:`code_digest`): comments,
docstrings and the help texts of the command line change no key.

``ems data lock`` writes the keys to :data:`LOCK_FILE`, committed like
``uv.lock``; CI fails when the lock is not that of the commit
(``--check``), so that a release never mistakes changed data for
deployed.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import functools
import hashlib
import json
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from election_map_slovakia import bundle, geo, research, stamp, translate
from election_map_slovakia.config import Config, Election

LOCK_FILE = Path("data") / "published.toml"
"""Relative to the project root."""
KEY_DIGITS = 16
"""Hex digits of a key: 64 bits, so two different contents sharing a key
by chance is not a concern."""
DATA_MODULES = (
    "candidates",
    "links",
    "addresses",
    "geo",
    "basemap",
    "results",
    "bundle",
)
"""The modules that make the data: the steps of ``ems make`` before
``build``, and the bundles' own (:mod:`election_map_slovakia.bundle`)."""
MAP_MODULES = ("candidates", "statoffice", "geo", "basemap", "addresses", "okrsokrules")
"""The modules of the steps an election's map comes from: ``candidates``
(with ŠÚ SR's packages, :mod:`statoffice`), ``geo``, ``basemap`` and
``addresses`` (with the okrsok counts of :mod:`okrsokrules`). What they
import counts too, which reaches further than the map needs (statoffice
imports the results' code, okrsokrules the jobs'): a change of that code
rebuilds the maps as well."""
MAP_GLUE = (
    "_candidates",
    "_input",
    "_extract_gpkg",
    "_built_candidates",
    "_okrsky_files",
    "_geo",
    "_basemap",
    "_addresses",
)
"""The functions of the CLI that run those steps: what inputs each gets."""
# The fields of an election's table of elections.toml those steps read.
_MAP_FIELDS = ("day", "candidates", "incumbents", "units", "addresses", "zbgis", "osm")
WEB = Path("web")
NOT_FOUND = WEB / "part-404.html"
"""What the parts but the app answer a missing path with."""
PART_FILES = {
    "map": (WEB / "_headers-data", NOT_FOUND),
    "data": (WEB / "_headers-data", NOT_FOUND),
    "results": (WEB / "_headers-results", NOT_FOUND),
    "sources": (WEB / "cache.css", WEB / "_headers-sources", NOT_FOUND),
}
"""Part → the files of web/ it is made of besides its data: its response
headers (the same for both bundles of an election) and the page of a
missing path; the stylesheet the cached copies link."""
# The configuration files whose parsed content is hashed instead, without
# what only the app reads; site.toml is the app's alone.
_PARSED = frozenset({"site.toml", "elections.toml", "inputs.toml"})
# Read by the app only.
_APP_ONLY = frozenset({"polls_open", "polls_close", "live", "live_window"})
# Of the project in uv.lock, whose dependencies are the libraries.
_PROJECT = "election-map-slovakia"


class LockError(Exception):
    """The keys cannot be computed, or the lock file is broken."""


@dataclass(frozen=True)
class Keys:
    """The key of each published part but the app."""

    maps: dict[str, str]
    """Election slug → the key of its map bundle."""
    data: dict[str, str]
    """Election slug → the key of its data bundle."""
    sources: str
    results: str


def keys(cfg: Config) -> Keys:
    """Return the keys of the parts the repository at ``cfg.root`` publishes."""
    unpinned = [inp.name for inp in cfg.inputs.inputs if not inp.sha256]
    if unpinned:
        raise LockError(
            f"config/inputs.toml: input(s) {', '.join(unpinned)} not pinned; run"
            " `ems inputs update` on them"
        )
    own = {e.slug: {e.osm, *e.records} for e in cfg.elections}
    owned = set().union(*own.values())
    inputs = {inp.name: inp for inp in cfg.inputs.inputs}
    libs = libraries(cfg.root / "uv.lock")
    common = _digest(
        {
            "code": code_digest(DATA_MODULES),
            "libraries": libs,
            "elections": [_election(e) for e in cfg.elections],
            "inputs": [
                _canonical(inp) for name, inp in inputs.items() if name not in owned
            ],
            "config": _files(
                p
                for p in sorted((cfg.root / "config").iterdir())
                if p.is_file() and p.name not in _PARSED
            ),
            "elections curated": stamp.tree_digest(cfg.curated_dir / "elections"),
            "research": stamp.tree_digest(cfg.curated_dir / research.CURATED_DIR),
            "translations": _translations(cfg),
        }
    )
    maps = {e.slug: map_key(cfg, e, libs) for e in cfg.elections}
    data = {
        e.slug: _key(
            "data",
            e.slug,
            common,
            [_canonical(inputs[name]) for name in sorted(set(e.records))],
            _part_files(cfg, "data"),
        )
        for e in cfg.elections
    }
    sources = _key("sources", sorted(bundle.cited(cfg)), _part_files(cfg, "sources"))
    return Keys(
        maps, data, sources, _key("results", common, _part_files(cfg, "results"))
    )


def map_inputs(e: Election) -> set[str]:
    """Return the names of the inputs election *e*'s map comes from."""
    return {
        *e.candidates.inputs.values(),
        *(e.incumbents.inputs if e.incumbents else ()),
        *e.zbgis,
        geo.NEIGHBOURS_INPUT,
        e.addresses,
        e.units.input,
        e.osm,
    }


def map_key(cfg: Config, e: Election, libs: Mapping[str, str]) -> str:
    """Return the key of election *e*'s map bundle; see the module doc.

    *libs* are the libraries' versions (:func:`libraries`).
    """
    inputs = {inp.name: inp for inp in cfg.inputs.inputs}
    curated = cfg.election_dir(e)
    return _key(
        "map",
        e.slug,
        {
            "code": code_digest(MAP_MODULES, MAP_GLUE),
            "libraries": libs,
            "election": {f: _canonical(getattr(e, f)) for f in _MAP_FIELDS},
            "inputs": [_canonical(inputs[name]) for name in sorted(map_inputs(e))],
            "overrides": _canonical(cfg.overrides[e.slug]),
            "curated": stamp.tree_digest(curated) if curated.is_dir() else None,
        },
        _part_files(cfg, "map"),
    )


def _part_files(cfg: Config, part: str) -> str:
    return _files(cfg.root / path for path in PART_FILES[part])


# The code does not change while it runs.
@functools.cache
def code_digest(modules: Sequence[str], glue: Sequence[str] | None = None) -> str:
    """Return a digest of the code of *modules* and the package modules they import.

    With the CLI that runs them: the functions of it named *glue*, or all
    of it (None). Each by its syntax tree without docstrings and the help
    texts of the command line, so that rewording them changes no key, and
    written out the same on every Python the project runs on
    (:func:`_plain`); not the package version, which every release
    changes, nor the versions of Python and the libraries, which differ
    between machines (:func:`libraries` names those of ``uv.lock``).
    """
    names = set().union(*(stamp.modules(m) for m in modules)) - {"cli"}
    trees = {name: _tree(name) for name in sorted(names)}
    cli = _tree("cli")
    if glue is None:
        trees["cli"] = cli
    else:
        functions = {
            node.name: node for node in cli.body if isinstance(node, ast.FunctionDef)
        }
        if missing := [name for name in glue if name not in functions]:
            raise LockError(f"cli.py: no function {missing[0]} (lock.MAP_GLUE)")
        trees["cli"] = ast.Module([functions[name] for name in glue], [])
    return _digest({name: _plain(tree) for name, tree in trees.items()})


def _plain(node: object) -> Any:
    """Return syntax tree *node* as plain JSON values, the same on every Python.

    Not ``ast.dump``, whose text differs between versions: 3.12 adds an
    empty ``type_params`` to every function and class, 3.13 leaves out
    fields at their defaults. A node is its type and its fields, those
    unset (None, an empty list) left out, as no version tells them apart.
    """
    if isinstance(node, ast.AST):
        fields = {}
        for name in node._fields:
            value = getattr(node, name, None)
            if value is not None and value != []:
                fields[name] = _plain(value)
        return [type(node).__name__, fields]
    if isinstance(node, list):
        return [_plain(item) for item in node]
    if isinstance(node, (bytes, complex)) or node is Ellipsis:
        return repr(node)
    return node


def _tree(module: str) -> ast.Module:
    """Return the syntax tree of package module *module*, without its prose."""
    tree = ast.parse((stamp.PACKAGE / f"{module}.py").read_bytes())
    return _Prose().visit(tree)


class _Prose(ast.NodeTransformer):
    """Drops docstrings and blanks the help texts of argparse calls."""

    _HELP = frozenset({"help", "description"})

    def generic_visit(self, node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
        return super().generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> ast.AST:
        if node.arg in self._HELP:
            node.value = ast.Constant("")
        return self.generic_visit(node)


def libraries(lock: Path) -> dict[str, str]:
    """Return name → version of the libraries the project runs on (``uv.lock``)."""
    try:
        packages = {p["name"]: p for p in tomllib.loads(lock.read_text())["package"]}
    except (OSError, tomllib.TOMLDecodeError, KeyError) as e:
        raise LockError(f"{lock}: cannot read the packages: {e}") from e
    versions: dict[str, str] = {}
    todo = [d["name"] for d in packages[_PROJECT].get("dependencies", [])]
    while todo:
        name = todo.pop()
        if name in versions:
            continue
        versions[name] = packages[name]["version"]
        todo += [d["name"] for d in packages[name].get("dependencies", [])]
    return dict(sorted(versions.items()))


def render(k: Keys) -> str:
    """Return the text of :data:`LOCK_FILE` for keys *k*."""
    lines = [
        "# The keys of the published data (src/election_map_slovakia/lock.py),",
        "# written by `ems data lock`; do not edit. CI fails when they are not",
        "# those of the commit, and a release builds and deploys a part only",
        "# when its key is not deployed yet (docs/deploy.md).",
        "",
        f'sources = "{k.sources}"',
        f'results = "{k.results}"',
        "",
        "[map]",
        *(f'{slug} = "{key}"' for slug, key in k.maps.items()),
        "",
        "[data]",
        *(f'{slug} = "{key}"' for slug, key in k.data.items()),
    ]
    return "\n".join(lines) + "\n"


def read(path: Path) -> Keys | None:
    """Return the keys in the lock *path*, or None if it is absent."""
    try:
        content = tomllib.loads(path.read_text(encoding="utf-8"))
        return Keys(
            {str(slug): key for slug, key in content["map"].items()},
            {str(slug): key for slug, key in content["data"].items()},
            content["sources"],
            content["results"],
        )
    except FileNotFoundError:
        return None
    except (OSError, tomllib.TOMLDecodeError, KeyError, AttributeError) as e:
        raise LockError(f"{path}: broken: {e}") from e


def _election(e: Election) -> dict[str, Any]:
    """Return what the steps read of election *e*'s configuration."""
    return {
        f.name: _canonical(getattr(e, f.name))
        for f in dataclasses.fields(e)
        if f.name not in _APP_ONLY
    }


def _translations(cfg: Config) -> dict[str, Any]:
    """Return language → its curated translations the data use.

    Its occupations and research texts; its UI strings are the app's.
    """
    out = {}
    for code in cfg.languages.codes:
        curated = translate.load(cfg, code)
        out[code] = [curated.occupations, curated.research]
    return out


def _files(paths: Iterable[Path]) -> str:
    """Return a digest of the names and contents of *paths*."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(f"{path.name}\0{stamp.file_digest(path)}\n".encode())
    return digest.hexdigest()


def _canonical(value: object) -> Any:
    """Return *value* (configuration) as plain JSON values, the same everywhere.

    Unlike ``repr``, which may change with the Python version.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _canonical(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, re.Pattern):
        return _canonical(value.pattern)
    if isinstance(value, bytes):
        return value.decode()
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _key(*parts: object) -> str:
    return _digest(list(parts))[:KEY_DIGITS]
