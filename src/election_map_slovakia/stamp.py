"""Skip a pipeline step whose inputs are unchanged since it last succeeded.

A step records in ``data/build/<election day>/<step>.stamp.json`` (the
base map in ``data/build/base/<extract>/``), once its output is written,
the parts of its inputs (:data:`PARTS`) and a digest of that output
(:func:`outputs_digest`) with a digest of its files' sizes and
modification times (:func:`outputs_signature`). It runs again when an
input differs, when an output is missing or is not what it wrote, or when
asked to (``--force``), unless the output record says that its output is
up to date (:mod:`election_map_slovakia.record`). The stamp is removed
before the step runs, so a step that fails halfway is never taken as done.

The inputs are computed from what a commit holds, so that CI computes
them too (``ems record check``): a download by its pin, curated data by
its content, configuration by its values, the code by its source text,
the libraries by their versions in ``uv.lock`` and Python by its
``major.minor`` (:data:`PYTHON`); and the output of an upstream step it
reads by that output's digest. Under another ``major.minor`` every step
runs again.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import functools
import hashlib
import json
import os
import re
import sys
import time
import tomllib
from collections.abc import Generator, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import pyproj
import shapely

from election_map_slovakia import output
from election_map_slovakia.config import ConfigError

PACKAGE = Path(__file__).parent
# Pipeline glue (which inputs a step gets, how its output is written) lives
# in the CLI: a step's code includes the CLI definitions its own functions
# reach (:func:`glue`), not the rest of the CLI, so that a change to one
# step's wiring reruns that step alone. Not the package version (__init__),
# which every release changes: no step writes it (only `build`, which
# always runs).
CLI = "cli"
PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"
"""The Python a step's inputs name: ``major.minor`` of the running one."""
RUNTIME = (
    sys.version,
    orjson.__version__,
    np.__version__,
    shapely.__version__,
    shapely.geos_version_string,
    pyproj.__version__,
    pyproj.proj_version_str,
)
"""What computes a cached value besides our code, as it runs here: float
formatting and JSON encoding (Python), JSON decoding (orjson), geometry
(GEOS), reprojection (PROJ and its database). For the caches of this
machine alone; a step's inputs name Python and the libraries as a commit
does (:data:`PYTHON`, :func:`libraries`)."""
PARTS = ("code", "python", "libraries", "pins", "curated", "config", "upstream")
"""The parts of a step's inputs: its code (:func:`code_digest`), Python's
``major.minor``, the libraries of ``uv.lock`` (:func:`libraries`), input →
the digest of its configuration with its pin, curated file or directory →
the digest of its content, configuration value → its digest
(:func:`json_digest`), and ``<step> <election day or extract>`` → the
digest of the output of that upstream step it reads."""
SCANS_FILE = "imports.json"
"""In the directory of :func:`scans_kept`: what each module imports."""
# Of the project in uv.lock, whose dependencies are the libraries.
_PROJECT = "election-map-slovakia"


def file_digest(path: Path) -> str:
    """Return the sha256 of the content of *path*.

    Remembered for the rest of the process by the file's identity (device
    and inode), size and modification time: several steps of a run digest
    the same input files of hundreds of megabytes, which do not change
    meanwhile. Only once that time is :data:`_SETTLED` old, as git does: a
    file changed again within a tick of the clock of file times would keep
    its time.
    """
    now = time.time_ns()
    st = path.stat()
    key = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    digest = _DIGESTS.get(key)
    if digest is None:
        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        if now - st.st_mtime_ns > _SETTLED:
            _DIGESTS[key] = digest
    return digest


_DIGESTS: dict[tuple[int, int, int, int], str] = {}
_SETTLED = 2_000_000_000
"""Nanoseconds after which a file's modification time tells a change."""


def tree_digest(directory: Path) -> str:
    """Return a sha256 over the names and contents of the files in *directory*."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        name = path.relative_to(directory).as_posix()
        digest.update(f"{name}\0{file_digest(path)}\n".encode())
    return digest.hexdigest()


def value_digest(value: object) -> str:
    """Return the sha256 of the ``repr`` of *value*, for a cache of this machine.

    ``repr`` may change with the Python version: what a commit must give
    alike everywhere is :func:`json_digest`.
    """
    return hashlib.sha256(repr(value).encode()).hexdigest()


def json_digest(value: object) -> str:
    """Return the sha256 of *value* (configuration) as canonical JSON.

    The same under every Python (:func:`canonical`).
    """
    text = json.dumps(canonical(value), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def canonical(value: object) -> Any:
    """Return *value* (configuration) as plain JSON values, the same everywhere.

    Unlike ``repr``, which may change with the Python version.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: canonical(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(k): canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted(canonical(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, re.Pattern):
        return canonical(value.pattern)
    if isinstance(value, bytes):
        return value.decode()
    return value


def libraries(lock: Path) -> dict[str, str]:
    """Return name → version of the libraries the project runs on (``uv.lock``).

    Remembered by the file's content: every step of every election names
    them.
    """
    return dict(_libraries(lock, file_digest(lock)))


@functools.cache
def _libraries(lock: Path, _digest: str) -> tuple[tuple[str, str], ...]:
    try:
        packages = {p["name"]: p for p in tomllib.loads(lock.read_text())["package"]}
    except (OSError, tomllib.TOMLDecodeError, KeyError) as e:
        raise ConfigError(f"{lock}: cannot read the packages: {e}") from e
    versions: dict[str, str] = {}
    todo = [d["name"] for d in packages[_PROJECT].get("dependencies", [])]
    while todo:
        name = todo.pop()
        if name in versions:
            continue
        versions[name] = packages[name]["version"]
        todo += [d["name"] for d in packages[name].get("dependencies", [])]
    return tuple(sorted(versions.items()))


def pinned_python(root: Path) -> str:
    """Return ``major.minor`` of the Python ``.python-version`` in *root* pins."""
    path = root / ".python-version"
    try:
        version = path.read_text().split()[0]
    except (OSError, IndexError) as e:
        raise ConfigError(f"{path}: no Python version: {e}") from e
    return ".".join(version.split(".")[:2])


def code_digest(module: str) -> str:
    """Return a sha256 of the code that computes the output of step *module*.

    That is the source text of *module*, of every package module it
    imports, directly or not, of the CLI's glue of the step (:func:`glue`
    of ``_<module>`` and ``_run_<module>``) and the package modules that
    glue names: the same under every Python. Remembered for the rest of
    the process by the sources of the package (:func:`_package_digest`):
    every election's stamp of a step digests it, a few tens of
    milliseconds each.
    """
    return _code_digest(module, _package_digest())


@functools.cache
def _code_digest(module: str, _package: str) -> str:
    source, named = glue((f"_{module}", f"_run_{module}"))
    names = set().union(modules(module), *(modules(m) for m in named))
    digest = hashlib.sha256()
    for name in sorted(names - {CLI}):
        digest.update(f"{name}\0".encode() + (PACKAGE / f"{name}.py").read_bytes())
    digest.update(f"{CLI} glue\0".encode() + source.encode())
    return digest.hexdigest()


def _package_digest() -> str:
    """Return a sha256 over the names and sources of the package's modules."""
    digest = hashlib.sha256()
    for path in sorted(PACKAGE.glob("*.py")):
        digest.update(f"{path.name}\0".encode() + path.read_bytes())
    return digest.hexdigest()


def source_digest(module: str, *values: object) -> str:
    """Return a sha256 of the source of *module* alone, :data:`RUNTIME` and *values*.

    Not of what *module* imports, as :func:`code_digest`: for a cache of
    what one part of a module computes that would else be made again on
    every change of the modules it imports. *values* are what it takes of
    those (their ``repr``).
    """
    digest = hashlib.sha256(repr((RUNTIME, values)).encode())
    digest.update((PACKAGE / f"{module}.py").read_bytes())
    return digest.hexdigest()


def glue(roots: Iterable[str]) -> tuple[str, set[str]]:
    """Return the source of the CLI definitions *roots* reach, and the modules they name.

    Starting from the top-level definitions of ``cli.py`` named *roots*
    (those it has), every top-level function, class or assignment of it
    whose name they use, and so on: the source of each, decorators included,
    in the order of the file; and the package modules whose code they use
    (``geo.build`` names ``geo``; a constant, ``geo.OUTPUT_DIR``, computes
    nothing and names none).
    """
    text = (PACKAGE / f"{CLI}.py").read_text(encoding="utf-8")
    definitions, imported = _cli_definitions(text)
    reached: set[str] = set()
    named: set[str] = set()
    todo = [r for r in roots if r in definitions]
    while todo:
        name = todo.pop()
        if name in reached:
            continue
        reached.add(name)
        nodes = list(ast.walk(definitions[name][1]))
        constants = {
            id(n.value)
            for n in nodes
            if isinstance(n, ast.Attribute) and n.attr.isupper()
        }
        for node in nodes:
            if not isinstance(node, ast.Name):
                continue
            if node.id in definitions and node.id not in reached:
                todo.append(node.id)
            elif node.id in imported and id(node) not in constants:
                named.add(imported[node.id])
    nodes = sorted({definitions[n] for n in reached}, key=lambda d: d[0])
    return "\n".join(_segment(text, node) for _, node in nodes), named


@functools.cache
def _cli_definitions(
    text: str,
) -> tuple[dict[str, tuple[int, ast.stmt]], dict[str, str]]:
    """Return the CLI's top-level definitions and package imports.

    From its *text*: name → (position, definition), and name bound → module.
    """
    tree = ast.parse(text)
    definitions: dict[str, tuple[int, ast.stmt]] = {}
    imported: dict[str, str] = {}
    for i, node in enumerate(tree.body):
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, ast.ImportFrom) and node.module == PACKAGE.name:
            for alias in node.names:
                if (PACKAGE / f"{alias.name}.py").is_file():
                    imported[alias.asname or alias.name] = alias.name
        definitions |= {name: (i, node) for name in names}
    return definitions, imported


def _segment(text: str, node: ast.stmt) -> str:
    """Return the source of *node*, with its decorators."""
    parts = [
        ast.get_source_segment(text, d) or ""
        for d in getattr(node, "decorator_list", [])
    ]
    return "\n".join([*parts, ast.get_source_segment(text, node) or ""])


def modules(module: str) -> set[str]:
    """Return *module* and the package modules it imports, directly or not."""
    seen: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        source = (PACKAGE / f"{name}.py").read_bytes()
        key = _scan_key(source)
        names = _SCANS.get(key)
        if names is None:
            names = _SCANS[key] = _imports(source, PACKAGE.name)
        # Only package modules have a file here; the rest are libraries.
        todo += [n for n in names if (PACKAGE / f"{n}.py").is_file()]
    return seen


_SCANS: dict[str, tuple[str, ...]] = {}
""":func:`_scan_key` of a module → what it imports (:func:`_imports`).

Remembered for the rest of the process, and across runs within
:func:`scans_kept`: parsing the modules of a step takes a third of a
second, and a run digests the code of each step of each election.
"""


def _scan_key(source: bytes) -> str:
    """Return the key of the imports of a module of the package, of its *source*."""
    return hashlib.sha256(f"{PACKAGE.name}\0".encode() + source).hexdigest()


def _imports(source: bytes, package: str) -> tuple[str, ...]:
    """Return what the module of *source* imports, *package*'s modules by name."""
    imported = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == package:
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
    return tuple(path.removeprefix(f"{package}.") for path in imported)


@contextmanager
def scans_kept(directory: Path) -> Generator[None]:
    """Within, keep what :func:`modules` finds each module imports in *directory*.

    Every command that digests code (a step's stamp, ``check``'s memo,
    the data keys) would parse the modules again, which change far less
    often than commands run: their imports are read from
    :data:`SCANS_FILE` there, by the SHA-256 of each module's source
    (:func:`_scan_key`), and the file is written again when it is not
    those of the package's modules now, with theirs alone.
    """
    path = directory / SCANS_FILE
    try:
        kept = {k: tuple(names) for k, names in orjson.loads(path.read_bytes()).items()}
    except (OSError, ValueError, TypeError, AttributeError):
        kept = {}  # none yet, or broken: parsed again
    _SCANS.update(kept)
    try:
        yield
    finally:
        now = {_scan_key(p.read_bytes()) for p in PACKAGE.glob("*.py")}
        scans = {k: _SCANS[k] for k in sorted(now) if k in _SCANS}
        if scans != kept:
            output.write_file(path, output.to_json(scans))


def _listing(
    directory: Path, outputs: Sequence[Path]
) -> list[tuple[str, os.stat_result | None]]:
    """Return the name below *directory* and the status of each file of *outputs*.

    Sorted by name; a directory of *outputs* by its name with a ``/``
    (none if it is missing, so that an empty one is told from a missing
    one) and its files, at any depth; a missing output with no status.
    """
    found: list[tuple[str, os.stat_result | None]] = []
    for path in outputs:
        name = path.relative_to(directory).as_posix()
        if path.is_dir():
            found.append((f"{name}/", None))
            todo = [path]
            while todo:
                with os.scandir(todo.pop()) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            todo.append(Path(entry.path))
                        else:
                            rel = Path(entry.path).relative_to(directory).as_posix()
                            found.append((rel, entry.stat()))
        elif path.exists():
            found.append((name, path.stat()))
    return sorted(found, key=lambda f: f[0])


def outputs_digest(directory: Path, outputs: Sequence[Path]) -> str:
    """Return a sha256 over the names and contents of *outputs*.

    The files and directories a step writes, named below *directory* (the
    directory of its stamp), a directory's files at any depth: what the
    output record compares from one machine to another. The files are read
    by several threads, the hashing releasing the GIL.
    """
    listing = _listing(directory, outputs)
    files = [name for name, st in listing if st is not None]
    with ThreadPoolExecutor() as pool:
        digests = dict(
            zip(files, pool.map(file_digest, (directory / f for f in files)))
        )
    digest = hashlib.sha256()
    for name, _ in listing:
        digest.update(f"{name}\0{digests.get(name, '')}\n".encode())
    return digest.hexdigest()


def outputs_signature(directory: Path, outputs: Sequence[Path]) -> str | None:
    """Return a digest of the names, sizes and modification times of *outputs*.

    Their files as :func:`outputs_digest` lists them: while it is the
    same, so is their content, and a stamp's digest of it stands without
    reading them again, as git's index tells a changed file. None while a
    file was modified within :data:`_SETTLED`, as git does: a file changed
    again within a tick of the clock of file times would keep its time.
    """
    now = time.time_ns()
    digest = hashlib.sha256()
    for name, st in _listing(directory, outputs):
        if st is not None and now - st.st_mtime_ns <= _SETTLED:
            return None
        sized = "" if st is None else f"{st.st_size}\0{st.st_mtime_ns}"
        digest.update(f"{name}\0{sized}\n".encode())
    return digest.hexdigest()


def on_disk(
    directory: Path, outputs: Sequence[Path], recorded: Mapping[str, Any] | None
) -> tuple[str, str | None]:
    """Return the digest of *outputs* as they are, and their signature.

    *recorded* is what a stamp has of them (``digest`` and ``files``, the
    signature), whose digest stands where the signature is the same; else
    they are read (:func:`outputs_digest`).
    """
    signature = outputs_signature(directory, outputs)
    if signature is not None and recorded and recorded.get("files") == signature:
        return recorded["digest"], signature
    return outputs_digest(directory, outputs), signature


def recorded_outputs(path: Path) -> Mapping[str, Any] | None:
    """Return what the stamp *path* has of its outputs, None if nothing."""
    content = _load(path)
    return content["outputs"] if content else None


def _load(path: Path) -> dict[str, Any] | None:
    """Return the content of stamp *path*, None if it has none or another form."""
    try:
        content = orjson.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    if not (
        isinstance(content, dict)
        and isinstance(content.get("inputs"), dict)
        and isinstance(content.get("outputs"), dict)
        and isinstance(content["outputs"].get("digest"), str)
    ):
        return None  # none, broken, or of a version before the record
    return content


class Stamp:
    """The record of one step's inputs and output, compared and written by the CLI."""

    def __init__(
        self,
        path: Path,
        inputs: Mapping[str, Any],
        directory: Path,
        outputs: Sequence[Path],
    ) -> None:
        """Describe the step recorded in *path*: its inputs (:data:`PARTS`), outputs.

        *outputs* are named below *directory*, the stamp's.
        """
        self.path = path
        self.inputs = dict(inputs)
        self.directory = directory
        self.outputs = list(outputs)
        self._recorded = _load(path)
        self._on_disk: tuple[str, str | None] | None = None

    @property
    def digest(self) -> str:
        """Return the digest of the inputs, which the output record keeps."""
        return json_digest(self.inputs)

    def missing(self) -> list[str]:
        """Return what is missing of the output: empty if it is all there."""
        return [f"{path.name} missing" for path in self.outputs if not path.exists()]

    def changes(self) -> list[str]:
        """Return why the step must run: empty if its output is up to date.

        Up to date: the inputs are those recorded and the output is the one
        the step wrote then. Where only the file times of the output
        changed, the stamp takes them, so as not to read it again.
        """
        missing = self.missing()
        if missing:
            return missing
        if self._recorded is None:
            return ["no record of a successful run"]
        changed = _changes(self._recorded["inputs"], self.inputs)
        if changed:
            return changed
        digest, signature = self._outputs()
        if digest != self._recorded["outputs"]["digest"]:
            return ["its output changed since it was written"]
        if signature != self._recorded["outputs"].get("files"):
            self.record()
        return []

    def outputs_digest(self) -> str:
        """Return the digest of the output as it is (:func:`on_disk`)."""
        return self._outputs()[0]

    def _outputs(self) -> tuple[str, str | None]:
        if self._on_disk is None:
            recorded = self._recorded["outputs"] if self._recorded else None
            self._on_disk = on_disk(self.directory, self.outputs, recorded)
        return self._on_disk

    def forget(self) -> None:
        """Remove the record, before the step changes its output."""
        self.path.unlink(missing_ok=True)
        self._recorded = None
        self._on_disk = None

    def record(self) -> str:
        """Record the inputs and the output as it is; return the output's digest."""
        digest, signature = self._outputs()
        content = {
            "inputs": self.inputs,
            "outputs": {"digest": digest, "files": signature},
        }
        data = json.dumps(content, indent=2, sort_keys=True) + "\n"
        output.write_file(self.path, data.encode())
        self._recorded = content
        return digest


def _changes(recorded: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """Return what differs between the inputs *recorded* and *current*, by part."""
    out = []
    for part in PARTS:
        old, new = recorded.get(part), current.get(part)
        if old == new:
            continue
        if not isinstance(old, dict) or not isinstance(new, dict):
            out.append(f"{part} changed")
            continue
        for name in sorted(old.keys() | new.keys()):
            if old.get(name) != new.get(name):
                out.append(_change(part, name))
    return out


def _change(part: str, name: str) -> str:
    """Return how a change to *name* of input part *part* is reported."""
    if part == "pins":
        return f"input {name} changed"
    if part == "upstream":
        return f"output of {name} changed"
    if part == "config":
        return f"configuration {name} changed"
    return f"{name} changed"
