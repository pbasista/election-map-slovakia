"""The ``obvod-rules`` job kind: transcribe how a municipality cuts its council.

An obec (or city district of Bratislava or Košice) that elects its council
in several obvody sets them in a resolution of its council, published on
its official notice board and website: which streets (house numbers), parts
of the obec or cadastral areas form each obvod, and how many councillors it
elects. Each item of a job is one such obec: its name, obvody, streets,
parts and k.ú. as the address register and ZBGIS have them, and how to find
the document. The agent finds the official document, reads it and writes
the rules (form: :mod:`election_map_slovakia.obvody`), or reports that it
found none.

``check`` (run by ``ems job ingest``) accepts an item only if

- the document is on the obec's official website: the agent names the
  website, a domain under :data:`OFFICIAL_TLDS` that must carry a word of
  the obec's name (``nitra.sk``, ``obecholumnica.sk``, ``dubnica.eu``)
  unless checked by hand (:data:`KNOWN_WEBSITES`); a document is on it if its host is
  in that domain, or on a host that publishes for many municipalities
  (:data:`SHARED_HOSTS`: the state's central notice board, and CMS hosts
  that keep each municipality's files under its domain in the path);
- the document can be fetched; it is kept, by sha256, for ``accept``;
- the rules are well formed, name only streets, parts and k.ú. the obec
  has, have the candidate lists' number of obvody, and place every address
  of the obec in exactly one obvod, each obvod with addresses.

Each checked item gets a review sheet, ``review/<obec>.html`` in the job
directory: its obvody drawn as ``geo`` will draw them, coloured, with every
address point and the rules. ``accept`` copies the documents to
``data/curated/cache/<sha256>.<ext>`` and writes the rule set to
``obvody/oz/<obec>.toml`` in the election's data
(:attr:`election_map_slovakia.config.Config.election_dir`); an obec
reported not found goes to ``obvody/oz-not-found.json`` there with the URLs
tried, and ``make`` leaves it out unless named with ``--only``.
"""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import shapely

from election_map_slovakia import addresses, candidates, fetch, geo, jobs, obvody
from election_map_slovakia.candidates import search_key
from election_map_slovakia.config import Config

NAME = "obvod-rules"
PRIORITY = "addresses"
"""The default order: the obce with the most addresses first."""
DEFAULT_SIZE = 1
CACHE_DIR = "cache"
"""Below ``data/curated/``: the official documents, by sha256."""
NOT_FOUND_FILE = "oz-not-found.json"
"""Below ``obvody/`` in :attr:`election_map_slovakia.config.Config.election_dir`."""
DOCUMENTS_DIR = "documents"
REVIEW_DIR = "review"
REVIEW_LEVEL = 1
"""ZBGIS level the review sheets draw."""
MAX_DOCUMENT = 20 << 20
"""Bytes a document may have."""
TIMEOUT = 60
SHARED_HOSTS = {
    # Centrálna úradná elektronická tabuľa: every obec publishes there.
    "cuet.slovensko.sk": False,
    # Municipal CMS hosts: the files of each municipality lie under its own
    # domain in the path (e.g. /data/uploads/staremesto.sk/...).
    "data.moderneobce.sk": True,
    "www.obce.info": True,
    # Civium: municipal websites built as script-only apps over its API,
    # whose files lie under a numeric institution id, not the domain.
    "app.civium.sk": False,
}
"""Hosts that publish for many municipalities → whether the path must name
the obec's website domain."""
OFFICIAL_TLDS = (".sk", ".eu", ".info", ".net")
"""Top-level domains of Slovak municipal websites (dubnica.eu, viglas.net,
rajecke-teplice.info)."""
KNOWN_WEBSITES = {
    # "BA Nové Mesto": the district calls banm.sk its official site and runs
    # its notice board there (checked by hand, 2026-10-19).
    "Bratislava-Nové Mesto": "banm.sk",
    # Obce whose own sites lie under .com or .org, where a site named after
    # an obec is as often a commercial guide to it (each calls itself the
    # obec's official site; checked by hand, 2026-10-24).
    "Kráľovský Chlmec": "kralovskychlmec.org",
    "Liptovská Osada": "liptovskaosada.com",
    "Tisovec": "tisovec.com",
    "Zázrivá": "zazriva.com",
}
"""Official domains checked by hand that carry no word of the obec's name
or lie outside :data:`OFFICIAL_TLDS`, by obec name."""
_MIN_WORD = 3
_URLS = re.compile(r"https?://\S+")
_SEARCH_TITLES = (
    "uznesenie o určení volebných obvodov",
    "oznámenie o utvorení volebných obvodov a o určení počtu poslancov",
    "určenie volebných obvodov a počtu poslancov",
)

RULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "description": "one rule; see prompt.md for the meaning of each field",
    "properties": {
        "street": {"type": "string", "minLength": 1},
        "part": {"type": "string", "minLength": 1},
        "ku": {"type": "string", "minLength": 1},
        "rest": {"const": True},
        "numbers": {"type": "string", "minLength": 1},
        "parity": {"enum": list(obvody.PARITIES)},
        "except": {"type": "string", "minLength": 1},
        "by": {"enum": [obvody.ORIENTACNE, obvody.SUPISNE]},
        "written": {"type": "string", "minLength": 1},
        "inferred": {"const": True},
        "note": {"type": "string", "minLength": 1},
    },
}
ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "status", "tried"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "the obec code of the input item"},
        "status": {"enum": ["found", "not_found"]},
        "tried": {
            "type": "array",
            "items": {"type": "string", "pattern": "^https?://"},
            "description": "every URL looked at, in order",
        },
        "website": {
            "type": "string",
            "pattern": "^https?://",
            "description": "the obec's official website (home page)",
        },
        "documents": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["url", "title"],
                "additionalProperties": False,
                "properties": {
                    "url": {"type": "string", "pattern": "^https?://"},
                    "title": {"type": "string", "minLength": 1},
                },
            },
        },
        "date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "date of the council's decision",
        },
        "fill_nearest": {"type": "boolean"},
        "note": {"type": "string", "minLength": 1},
        "obvody": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["number", "seats", "text", "rules"],
                "additionalProperties": False,
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "seats": {"type": "integer", "minimum": 1, "maximum": 12},
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "the document's text on this obvod, verbatim",
                    },
                    "rules": {
                        "type": "array",
                        "minItems": 1,
                        "items": RULE_SCHEMA,
                    },
                },
            },
        },
    },
}


# --- make ------------------------------------------------------------------------


def places_dir(cfg: Config) -> Path:
    """Return ``data/build/obvod-addresses``, written by ``ems addresses``."""
    return cfg.build_dir / addresses.OBVOD_DIR


def not_found_path(cfg: Config) -> Path:
    """Return the file of the obce whose document was not found."""
    return cfg.election_dir / obvody.DIRECTORY / NOT_FOUND_FILE


def load_not_found(cfg: Config) -> dict[str, Any]:
    """Return obec → what was tried, of the obce whose document was not found."""
    path = not_found_path(cfg)
    return json.loads(path.read_bytes()) if path.is_file() else {}


def candidate_data(cfg: Config) -> dict[str, Any]:
    """Return ``candidates.json``; fail if ``ems candidates`` has not run."""
    path = cfg.build_dir / candidates.OUTPUT_FILE
    if not path.is_file():
        raise jobs.JobError(f"{path} missing; run `ems candidates` first")
    return json.loads(path.read_bytes())


def make(cfg: Config, options: jobs.MakeOptions) -> list[jobs.Batch]:
    """Return the jobs for the obce with several council obvody and no rules.

    ``--only`` takes obec codes or names; it also brings back obce whose
    document was not found before.
    """
    data = candidate_data(cfg)
    names = {o["code"]: o for o in data["obce"]}
    okresy = {o["code"]: o["name"] for o in data["okresy"]}
    kraje = {k["code"]: k["name"] for k in data["kraje"]}
    candidacies_by_contest = Counter(c["contest"] for c in data["candidacies"])
    council = addresses.council_obvody(data["contests"])
    directory = places_dir(cfg)
    if not directory.is_dir():
        raise jobs.JobError(f"{directory} missing; run `ems addresses` first")
    curated = set(obvody.load_rule_sets(cfg.election_dir))
    not_found = load_not_found(cfg)
    pending = {i["id"] for j in options.pending for i in j.items}
    only = {search_key(x) for x in options.only}
    items = []
    for code, numbers in council.items():
        path = directory / f"{code}.json"
        if len(numbers) < 2 or not path.is_file():  # noqa: PLR2004 - several obvody
            continue
        obec = names[code]
        if only and not ({code, search_key(obec["name"])} & only):
            continue
        if code in curated or code in pending or (code in not_found and not only):
            continue
        p = obvody.load_places(path)
        items.append(
            _item(obec, okresy, kraje, numbers, candidacies_by_contest, p, data["obce"])
        )
    return batches(items, PROMPT, options.size, "council obvod rules")


def batches(
    items: list[dict[str, Any]], prompt: str, size: int, what: str
) -> list[jobs.Batch]:
    """Return *items* in batches of *size*, the obce with the most addresses first.

    Each batch is titled *what* "of" its obce.
    """
    items = sorted(items, key=lambda i: (-i["address_count"], i["id"]))
    out = []
    for start in range(0, len(items), size):
        chunk = items[start : start + size]
        title = f"{what} of " + ", ".join(f"{i['name']} ({i['id']})" for i in chunk)
        out.append(jobs.Batch(chunk, prompt, title))
    return out


def _item(
    obec: Mapping[str, Any],
    okresy: Mapping[str, str],
    kraje: Mapping[str, str],
    numbers: Sequence[int],
    candidacies: Mapping[str, int],
    p: obvody.ObecPlaces,
    obce: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the input item of an obec."""
    code, name = obec["code"], obec["name"]
    city = next((o["name"] for o in obce if o["code"] == obec.get("city")), None)
    item: dict[str, Any] = {
        "id": code,
        "name": name,
        "okres": okresy.get(obec["okres"], obec["okres"]),
        "kraj": kraje.get(obec["kraj"], obec["kraj"]),
        "obvody": [
            {"number": n, "candidates": candidacies.get(f"oz:{code}/{n}", 0)}
            for n in numbers
        ],
        **address_fields(p),
        "search": [f'"{name}" {t} 2026' for t in _SEARCH_TITLES]
        + [f"{name} volebné obvody 2026 poslanci"],
    }
    if city:
        item["city"] = city
    return item


def address_fields(
    p: obvody.ObecPlaces, obvod_of: Sequence[int] | None = None
) -> dict[str, Any]:
    """Return the fields of an input item on the addresses of an obec.

    Its streets (with their parts and range of orientačné čísla), parts and
    k.ú. Given *obvod_of*, the obvod of each address, each street and part
    also lists the obvody of its addresses.
    """
    streets: dict[str, list[Any]] = {}
    parts: dict[str, list[Any]] = {}
    for i, x in enumerate(p.places):
        part = parts.setdefault(x.part, [x.part, 0, set()])
        part[1] += 1
        if obvod_of is not None:
            part[2].add(obvod_of[i])
        if not x.street:
            continue
        street = streets.setdefault(x.street, [x.street, 0, set(), [], set()])
        street[1] += 1
        street[2].add(x.part)
        if (n := obvody.house(x.orientacne)) is not None:
            street[3].append(n[0])
        if obvod_of is not None:
            street[4].add(obvod_of[i])
    by_obvod = obvod_of is not None
    return {
        "address_count": len(p.places),
        "without_street": sum(not x.street for x in p.places),
        "streets": [
            [s, n, sorted(ps), [min(h), max(h)] if h else None]
            + ([sorted(o)] if by_obvod else [])
            for s, n, ps, h, o in sorted(
                streets.values(), key=lambda e: (search_key(e[0]), e[0])
            )
        ],
        "parts": [
            [part, n] + ([sorted(o)] if by_obvod else [])
            for part, n, o in sorted(parts.values(), key=lambda e: e[0])
        ],
        "kus": p.ku_names,
    }


# --- check -----------------------------------------------------------------------


def official_problems(name: str, website: str, urls: Sequence[str]) -> list[str]:
    """Return why *urls* are not on the official website of the obec *name*.

    See the module doc. *website* is the website the agent names.
    """
    host = (urllib.parse.urlsplit(website).hostname or "").lower()
    domain = ".".join(host.split(".")[-2:])
    if KNOWN_WEBSITES.get(name) != domain:
        problem = _unofficial(name, domain)
        if problem:
            return [
                f"website {website!r}: {problem}, so it is not evidently the obec's own"
            ]
    return [
        f"document {url!r} is not on {domain} (the obec's website)"
        for url in urls
        if not _published_on(url, domain)
    ]


def _unofficial(name: str, domain: str) -> str | None:
    """Return why *domain* does not look like the obec *name*'s own, or None."""
    if not domain.endswith(OFFICIAL_TLDS):
        return f"{domain!r} is not under {', '.join(OFFICIAL_TLDS)}"
    label = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    key = search_key(name)
    words = [w for w in key.split() if len(w) >= _MIN_WORD]
    if key.replace(" ", "") in label or any(w in label for w in words):
        return None
    return f"its domain {domain!r} carries no word of {name!r}"


def _published_on(url: str, domain: str) -> bool:
    """Return whether *url* is on the website *domain* or a shared host for it."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == domain or host.endswith(f".{domain}"):
        return True
    if host not in SHARED_HOSTS:
        return False
    return not SHARED_HOSTS[host] or domain in urllib.parse.unquote(parts.path).lower()


def _download(cfg: Config, url: str) -> bytes:
    """Return the content at *url*; raise JobError if it cannot be had."""
    # Agents copy links as shown, with spaces and diacritics in the path.
    request = urllib.request.Request(
        urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~"),
        headers={"User-Agent": fetch.user_agent(cfg.inputs.contact)},
    )
    context = fetch.ssl_context(cfg.inputs.ca_certificates)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as r:
            data = r.read(MAX_DOCUMENT + 1)
            kind = r.headers.get_content_type()
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise jobs.JobError(f"cannot fetch {url}: {e}") from None
    if len(data) > MAX_DOCUMENT:
        raise jobs.JobError(f"{url}: larger than {MAX_DOCUMENT >> 20} MiB")
    if not data:
        raise jobs.JobError(f"{url}: empty ({kind})")
    return data


def _extension(url: str, data: bytes) -> str:
    """Return the file extension of document *data*, by its content first."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    head = data[:2048].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return "html"
    # Some obce publish Word files, behind download scripts (download.php).
    if data.startswith(b"PK\x03\x04") and b"word/document.xml" in data:
        return "docx"
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower().lstrip(".")
    return suffix if re.fullmatch(r"[a-z0-9]{1,5}", suffix) else "bin"


def documents_index(job: jobs.Job) -> dict[str, str]:
    """Return URL → file name of the documents a job's checks fetched."""
    path = job.path / DOCUMENTS_DIR / "index.json"
    return json.loads(path.read_bytes()) if path.is_file() else {}


def keep(cfg: Config, job: jobs.Job, url: str) -> str:
    """Fetch *url* into the job's documents (once); return its file name."""
    index = documents_index(job)
    if url in index and (job.path / DOCUMENTS_DIR / index[url]).is_file():
        return index[url]
    data = _download(cfg, url)
    name = f"{hashlib.sha256(data).hexdigest()}.{_extension(url, data)}"
    (job.path / DOCUMENTS_DIR).mkdir(parents=True, exist_ok=True)
    (job.path / DOCUMENTS_DIR / name).write_bytes(data)
    jobs.write_json(job.path / DOCUMENTS_DIR / "index.json", index | {url: name})
    return name


def sha256_of(name: str) -> str:
    """Return the sha256 of a document from its file name (:func:`keep`)."""
    return name.split(".")[0]


def fetch_documents(
    cfg: Config, job: jobs.Job, urls: Sequence[str]
) -> tuple[dict[str, str], list[str]]:
    """Fetch *urls* (:func:`keep`); return URL → sha256 and the failures."""
    shas, problems = {}, []
    for url in urls:
        try:
            shas[url] = sha256_of(keep(cfg, job, url))
        except jobs.JobError as e:
            problems.append(str(e))
    return shas, problems


def decision_date(out: Mapping[str, Any]) -> dt.date | None:
    """Return the ``date`` of output item *out*, None where it gives none."""
    if "date" not in out:
        return None
    try:
        return dt.date.fromisoformat(out["date"])
    except ValueError:
        raise obvody.ObvodyError("date: not a date") from None


def document_tables(
    out: Mapping[str, Any], shas: Mapping[str, str]
) -> list[dict[str, str]]:
    """Return the ``document`` tables of a rule set for the documents of *out*."""
    return [
        {"url": d["url"], "sha256": shas[d["url"]], "title": d["title"]}
        for d in out["documents"]
    ]


def place_name_problems(rules: obvody.RuleSet, p: obvody.ObecPlaces) -> list[str]:
    """Return :func:`election_map_slovakia.obvody.name_problems` against *p*."""
    return obvody.name_problems(
        rules,
        sorted({x.street for x in p.places if x.street}),
        sorted({x.part for x in p.places}),
        p.ku_names,
    )


def rule_set(
    item: Mapping[str, Any], out: Mapping[str, Any], shas: Mapping[str, str]
) -> obvody.RuleSet:
    """Return the rule set of output item *out*; *shas* maps URL → sha256.

    Raises :class:`election_map_slovakia.obvody.ObvodyError` if malformed.
    """
    numbers = [o["number"] for o in out["obvody"]]
    if len(set(numbers)) != len(numbers):
        raise obvody.ObvodyError("an obvod number is listed twice")
    data: dict[str, Any] = {"obec": item["id"], "name": item["name"]}
    date = decision_date(out)
    if date is not None:
        data["date"] = date
    data["document"] = document_tables(out, shas)
    data["obvod"] = {
        str(o["number"]): {"seats": o["seats"], "rules": o["rules"]}
        for o in out["obvody"]
    }
    if out.get("fill_nearest"):
        data["fill"] = obvody.FILL_NEAREST
    if out.get("note"):
        data["note"] = out["note"]
    return obvody.rule_set(data, f"obvod-rules {item['id']}")


def check(
    cfg: Config, job: jobs.Job, item: dict[str, Any], out: dict[str, Any]
) -> list[str]:
    """Return the problems of output item *out* for input *item*."""
    if out["status"] == "not_found":
        return [] if out["tried"] else ["not_found needs the URLs tried"]
    missing = [k for k in ("website", "documents", "obvody") if k not in out]
    if missing:
        return [f"status found needs {', '.join(missing)}"]
    urls = [d["url"] for d in out["documents"]]
    problems = official_problems(item["name"], out["website"], urls)
    if problems:
        return problems
    shas, problems = fetch_documents(cfg, job, urls)
    if problems:
        return problems
    try:
        rules = rule_set(item, out, shas)
    except obvody.ObvodyError as e:
        return [str(e)]
    p = obvody.load_places(places_dir(cfg) / f"{item['id']}.json")
    a = obvody.assign(rules, p.places, p.kus, p.planar())
    numbers = [o["number"] for o in item["obvody"]]
    problems = place_name_problems(rules, p) + addresses.check_assignment(
        rules, numbers, p, a
    )
    write_review(cfg, job, rules, p, a, out, problems)
    return problems


# --- review sheet -------------------------------------------------------------------

_COLOURS = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
    "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#393b79", "#ad494a",
)  # fmt: skip
_SHEET_WIDTH = 900


@functools.cache
def obce_and_kus(gpkg: Path) -> tuple[dict[str, Any], dict[str, list[geo.Ku]]]:
    """Return the obce and their k.ú. of a ZBGIS level, EPSG:5514."""
    obce = {c: g for c, (_, g) in geo.read_layer(gpkg, "obec", "IDN4", "NM4").items()}
    return obce, geo.read_kus(gpkg)


def write_review(
    cfg: Config,
    job: jobs.Job,
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    assignment: obvody.Assignment,
    out: Mapping[str, Any],
    problems: Sequence[str],
) -> Path:
    """Write ``review/<obec>.html`` of *job*; see the module doc."""
    gpkg = cfg.build_dir / f"USJ_hranice_{REVIEW_LEVEL}.gpkg"
    drawing = ""
    if gpkg.is_file() and not assignment.unassigned and not assignment.conflicts:
        obce, kus = obce_and_kus(gpkg)
        to_wgs84 = geo.transformer()
        split = geo.council_split(
            rules, places, assignment.units, kus.get(rules.obec, []), to_wgs84
        )
        obec = geo.to_grid(obce[rules.obec], to_wgs84, 10**geo.DECIMALS)
        pieces: list[tuple[int, Any]] = []
        try:
            pieces = geo.council_geometry(
                rules.obec, obce[rules.obec], split, kus.get(rules.obec, []), to_wgs84
            )
        except geo.GeoError as e:
            problems = [*problems, f"(review) {e}"]
        drawing = review_svg(obec, pieces, places, assignment, split.approximate)
    path = job.path / REVIEW_DIR / f"{rules.obec}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _page(rules, places, assignment, out, problems, drawing), encoding="utf-8"
    )
    return path


def colour(n: int) -> str:
    """Return the review sheets' colour of obvod (or okrsok) *n*."""
    return _COLOURS[(n - 1) % len(_COLOURS)]


def review_svg(
    obec: Any,
    pieces: Sequence[tuple[int, Any]],
    places: obvody.ObecPlaces,
    assignment: obvody.Assignment,
    approximate: bool,
    outlines: Sequence[Any] = (),
) -> str:
    """Return the obec, its obvody (or okrsky) and its address points as SVG.

    *pieces* are (number, area) coloured by number, the address points by
    their unit in *assignment*; *outlines* are drawn over them as borders
    (the obvody, around the okrsky). All are in grid units (1/100,000
    degree), as the map rounds them; east is shrunk by the cosine of the
    latitude.
    """
    x0, y0, x1, y1 = obec.bounds
    east = np.cos(np.radians((y0 + y1) / 2 / 10**geo.DECIMALS))
    k = _SHEET_WIDTH / max((x1 - x0) * east, 1.0)
    height = round((y1 - y0) * k) + 2

    def point(x: float, y: float, sep: str = ",") -> str:
        return f"{(x - x0) * east * k:.1f}{sep}{(y1 - y) * k:.1f}"

    def path(g: Any) -> str:
        return "".join(
            "M" + " ".join(point(x, y) for x, y in shapely.get_coordinates(ring)) + "Z"
            for part in shapely.get_parts(g)
            for ring in (part.exterior, *part.interiors)
        )

    def dots(xy: np.ndarray, stroke: str, width: int) -> str:
        d = "".join(f"M{point(x, y, ' ')}h0" for x, y in xy)
        return (
            f'<path d="{d}" stroke="{stroke}" stroke-width="{width}"'
            ' stroke-linecap="round"/>'
        )

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_SHEET_WIDTH + 2}"'
        f' height="{height}" viewBox="-1 -1 {_SHEET_WIDTH + 2} {height}">'
    ]
    dash = ' stroke-dasharray="4 3"' if approximate else ""
    for n, g in pieces:
        out.append(
            f'<path d="{path(g)}" fill="{colour(n)}" fill-opacity="0.22"'
            f' stroke="{colour(n)}" stroke-width="1.5"{dash} fill-rule="evenodd"/>'
        )
    out += [
        f'<path d="{path(g)}" fill="none" stroke="#333" stroke-width="3"/>'
        for g in outlines
    ]
    out.append(f'<path d="{path(obec)}" fill="none" stroke="#000" stroke-width="2"/>')
    located = ~np.isnan(places.points[:, 0])
    xy = places.points[located]
    number = np.array(assignment.units)[located]
    for n in sorted(set(number.tolist())):
        out.append(dots(xy[number == n], colour(n) if n else "#000", 3))
    filled = np.isin(np.flatnonzero(located), assignment.filled)
    if filled.any():
        out.append(dots(xy[filled], "#000", 1))
    out.append("</svg>")
    return "\n".join(out)


REVIEW_STYLE = """\
body { font: 14px/1.4 system-ui, sans-serif; margin: 1.5em; }
table { border-collapse: collapse; } td, th { border: 1px solid #ccc; padding: .3em .5em; vertical-align: top; }
.key { display: inline-block; width: 1em; height: 1em; vertical-align: middle; }
.text { max-width: 40em; font-size: 12px; color: #444; } .problems { color: #b00; }
ul { margin: 0; padding-left: 1.2em; }"""
"""The CSS of the review sheets."""


def rule_items(rules: Iterable[obvody.Rule]) -> str:
    """Return *rules* as the HTML list items of a review sheet."""
    return "".join(
        f"<li>{html.escape(r.describe().split(': ', 1)[1])}"
        + (" <i>(inferred)</i>" if r.inferred else "")
        + (f" — {html.escape(r.note)}" if r.note else "")
        + "</li>"
        for r in rules
    )


def document_items(rules: obvody.RuleSet) -> str:
    """Return the documents of *rules* as the HTML list items of a review sheet."""
    return "".join(
        f'<li><a href="{html.escape(d.url)}">{html.escape(d.title)}</a>'
        f" <code>{d.sha256[:12]}</code></li>"
        for d in rules.documents
    )


def issues_html(problems: Sequence[str], unused: Iterable[obvody.Rule]) -> str:
    """Return the problems and unused rules of a review sheet as HTML."""
    issues = [*problems, *(f"unused rule: {r.describe()}" for r in unused)]
    if not issues:
        return "<p>No problems.</p>"
    items = "".join(f"<li>{html.escape(p)}</li>" for p in issues)
    return f'<ul class="problems">{items}</ul>'


def unit_cell(n: int) -> str:
    """Return the review sheet's table cell of obvod (or okrsok) *n*."""
    return (
        f'<td><span class="key" style="background:{colour(n)}"></span> <b>{n}</b></td>'
    )


def _page(
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    assignment: obvody.Assignment,
    out: Mapping[str, Any],
    problems: Sequence[str],
    drawing: str,
) -> str:
    """Return the review sheet: drawing, problems, obvody with their rules."""
    e = html.escape
    counts = Counter(assignment.units)
    filled = Counter(assignment.units[i] for i in assignment.filled)
    texts = {o["number"]: o["text"] for o in out["obvody"]}
    rows = []
    for n, seats in rules.seats.items():
        listed = rule_items(r for r in rules.rules if r.unit == n)
        rows.append(
            f"<tr>{unit_cell(n)}<td>{seats}</td><td>{counts[n]:,}"
            + (f" ({filled[n]:,} by the nearest)" if filled[n] else "")
            + f'</td><td><ul>{listed}</ul></td><td class="text">{e(texts.get(n, ""))}</td></tr>'
        )
    return f"""<!doctype html>
<html lang="sk"><head><meta charset="utf-8">
<title>{e(rules.name)} ({rules.obec}): council obvody</title>
<style>
{REVIEW_STYLE}
</style></head><body>
<h1>{e(rules.name)} ({rules.obec})</h1>
<p>{len(places.places):,} addresses; decision of {rules.date.isoformat() if rules.date else "an unstated date"}; documents:</p>
<ul>{document_items(rules)}</ul>
{f"<p>{e(rules.note)}</p>" if rules.note else ""}
{issues_html(problems, assignment.unused)}
{drawing or "<p>(no drawing: the addresses are not all placed, or ZBGIS level 1 is not extracted)</p>"}
<p>Polygons: as the map draws them (dashed: approximate, from the address points). Dots: addresses by obvod; black inner dots: placed by the nearest address.</p>
<table><tr><th>obvod</th><th>seats</th><th>addresses</th><th>rules</th><th>document text</th></tr>
{"".join(rows)}
</table>
</body></html>
"""


# --- accept --------------------------------------------------------------------------


OBVOD_TEXT = "  obvod "
"""How a rule set's header begins its quote of the document on an obvod."""


def accept(cfg: Config, job: jobs.Job, accepted: list[jobs.Accepted]) -> list[str]:
    """Write the accepted rule sets and documents into ``data/curated/``."""
    lines = []
    index = documents_index(job)
    not_found = load_not_found(cfg)
    for item, out in accepted:
        code = item["id"]
        if out["status"] == "not_found":
            lines.append(record_not_found(not_found, job, item, out))
            continue
        not_found.pop(code, None)
        rules = rule_set(item, out, cache_documents(cfg, job, index, out))
        path = obvody.rules_path(cfg.election_dir, code)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = [
            f"Council obvody of {item['name']} ({code}), {item['okres']}.",
            f"Transcribed by an AI agent in job {job.name} from the documents below;",
            "checked by `ems job ingest` against the address register. The document's",
            "text per obvod, verbatim:",
        ]
        header += [
            f"{OBVOD_TEXT}{o['number']}: " + " ".join(o["text"].split())
            for o in out["obvody"]
        ]
        path.write_text(obvody.dump(rules, header), encoding="utf-8")
        lines.append(f"{item['name']} ({code}): {path.relative_to(cfg.root)}")
    if not_found or not_found_path(cfg).is_file():
        jobs.write_json(not_found_path(cfg), dict(sorted(not_found.items())))
    return lines


def record_not_found(
    not_found: dict[str, Any],
    job: jobs.Job,
    item: Mapping[str, Any],
    out: Mapping[str, Any],
) -> str:
    """Add *item*, which *out* reports not found, to *not_found*.

    Returns the line of the ingest report.
    """
    not_found[item["id"]] = {
        "name": item["name"],
        "job": job.name,
        "tried": out["tried"],
        "note": out.get("note", ""),
    }
    return f"{item['name']} ({item['id']}): not found, {len(out['tried'])} URLs tried"


def cache_documents(
    cfg: Config, job: jobs.Job, index: Mapping[str, str], out: Mapping[str, Any]
) -> dict[str, str]:
    """Copy the documents of *out* into ``data/curated/cache/``; return URL → sha256.

    *index* is the job's :func:`documents_index`.
    """
    cache = cfg.curated_dir / CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    shas = {}
    for d in out["documents"]:
        name = index[d["url"]]
        target = cache / name
        if not target.is_file():
            target.write_bytes((job.path / DOCUMENTS_DIR / name).read_bytes())
        shas[d["url"]] = sha256_of(name)
    return shas


PROMPT = """\
# Council obvody of Slovak municipalities

Each item of `input.json` is a Slovak municipality (obec, or a city
district of Bratislava or Košice) that elects its council (obecné / mestské
/ miestne zastupiteľstvo) in several electoral districts (volebné obvody) in
the elections of 24 October 2026. The council decided, in a resolution
(uznesenie) published on the municipality's official notice board and
website, which streets, house numbers, parts of the municipality (časti
obce) or cadastral areas (katastrálne územia, k.ú.) form each obvod and how
many councillors (poslanci) each elects. Your task: find that official
document, read it, and transcribe it exactly as rules a program can apply to
every address. You need web search and the ability to fetch web pages and
PDF text.

## Input

Each item has:

- `id`: the municipality code; `name`, `okres`, `kraj` (and `city` for a
  district of Bratislava or Košice: the document is the district's, not the
  city's).
- `obvody`: the obvod numbers the candidate lists have, with their number of
  candidates. Your rules must have exactly these obvody.
- `streets`: every street of the municipality in the official address
  register: `[name, addresses, [parts], [lowest, highest orientačné číslo]]`.
  Use these names in your rules.
- `parts`: the parts of the municipality (časti obce) with their address
  counts. Addresses without a street are numbered by súpisné číslo within
  their part.
- `kus`: the cadastral areas (k.ú.) of the municipality.
- `address_count`, `without_street`.
- `search`: queries that usually find the document.

## Finding the document

1. Find the municipality's official website (usually `<name>.sk`,
   `obec<name>.sk`, `<name>.eu`; city districts: e.g. `ruzinov.sk`). Note
   its home page URL as `website`.
2. On it, look for the 2026 elections page (Voľby, Voľby 2026, Voľby do
   orgánov samosprávy obcí 2026), the official notice board (úradná tabuľa),
   or the council's resolutions (uznesenia) of June–August 2026. Typical
   titles: "Uznesenie … o určení volebných obvodov a počtu poslancov",
   "Oznámenie o utvorení volebných obvodov a o určení počtu poslancov",
   "Určenie volebných obvodov". Web search with the queries in `search`
   helps. The state's central notice board `cuet.slovensko.sk` also counts
   as official.
3. Use the document for 2026 (not 2022 or earlier). Prefer the adopted
   resolution or the announcement over a draft (návrh); if only the
   council material with the draft resolution exists, use it and say so in
   `note`.
4. Only the municipality's own website (its domain or subdomains), the CMS
   host it publishes through with its domain in the path, or
   `cuet.slovensko.sk` are accepted as `documents`. News sites, Wikipedia,
   aggregators are not.
5. Read the text of the PDF or page. If the document is only a scan whose
   text you cannot read reliably, or you find no document after a fair
   search (website, notice board, elections page, two or three searches),
   report `"status": "not_found"` with every URL you tried in `tried` and a
   `note` on what you found (e.g. "only a scanned image",
   "website lists the 2022 obvody only"). Never guess the obvody.

## Writing the rules

For each obvod write `number`, `seats` (počet poslancov), `text` (the
document's words on this obvod, verbatim, as one string) and `rules`. A rule
is an object; it selects addresses by exactly one of:

- `"street": "<name as in input streets>"`: a street. If the document
  writes the name differently (abbreviated, old spelling, "ul."), use the
  register's name in `street` and the document's in `written`: the name
  only, never numbers or other words, and only on street rules. Where the
  two names are not plainly the same (a typo, initials such as "ČSA", a
  dropped "cesta"), add a `note` saying why they are the same street. A
  street the document names but the register lacks (no addresses) is left
  out.
- `"street"` plus `"part": "<part>"`: that street only within that part (when
  two parts have streets of the same name).
- `"part": "<name as in input parts>"`: a whole part of the municipality
  ("miestna časť", "časť obce").
- `"ku": "<name as in input kus>"`: a whole cadastral area, when the
  document defines obvody by k.ú.
- `"rest": true`: everything no other rule selects ("ostatné ulice",
  "zvyšok obce"). At most one such rule in the whole set.

and may narrow it to house numbers:

- `"numbers": "1-35, 40, 42A, 101-"`: single numbers (12 is 12 with any
  letter, 12A only 12A), ranges (`1-35`), open ranges (`101-` = 101 and up).
- `"parity": "odd"` or `"even"` (párne / nepárne čísla), alone or with
  `numbers`.
- `"except": "7, 9"`: numbers left out.
- In a street the numbers are orientačné (the number on the building, after
  the slash in 178/1); otherwise súpisné. If the document numbers a street
  by súpisné čísla, add `"by": "supisne"`.

The most specific rule wins: a number with a letter, then other numbers,
then a whole street, a whole part, a k.ú., the rest. So "Hlavná 1–20 is in
obvod 1, the rest of Hlavná in obvod 2" is `{"street": "Hlavná", "numbers":
"1-20"}` in obvod 1 and `{"street": "Hlavná"}` in obvod 2.

Every address of the municipality must end up in exactly one obvod. When the
document leaves streets out (new streets, streets it forgot):

- if the document says where they belong ("ostatné", "novovzniknuté
  ulice"), use `rest` or the rule it implies;
- otherwise place each by the streets around it (look at a map) as a rule
  with `"inferred": true` and a `note` saying why ("new street between
  X and Y, both in obvod 2");
- or, as a last resort, set `"fill_nearest": true`: addresses no rule
  selects then take the obvod of the nearest address that one did. Say in
  the item's `note` which streets that concerns.

Use `note` on any rule whose transcription needed judgement. Set `date` to
the date of the council's decision (YYYY-MM-DD). Only if no published
document states it (look at the resolution, the announcement and the
council's minutes), leave `date` out and say so in `note`; never guess it.

## Output

Write `output.json` as `README.md` says, one object per item:

```json
{"id": "508179", "status": "found",
 "website": "https://www.pezinok.sk/",
 "documents": [{"url": "https://www.pezinok.sk/content/files/.../Uznesenie 68_volebné obvody.pdf",
                "title": "Uznesenie MsZ č. 68/2026 zo dňa 25. 06. 2026"}],
 "date": "2026-06-25",
 "tried": ["https://www.pezinok.sk/stranka/volby-do-organov-uzemnej-samospravy-2026"],
 "obvody": [
   {"number": 1, "seats": 7, "text": "Bratislavská 1 - 102, Drevárska, …",
    "rules": [{"street": "Bratislavská", "numbers": "1-102"},
              {"street": "Drevárska"},
              {"street": "Ulica gen. Viesta", "written": "Ulica gen. Viesta"}]},
   {"number": 2, "seats": 2, "text": "…", "rules": [{"street": "Baba"}]}
 ]}
```

or `{"id": "…", "status": "not_found", "tried": ["…"], "note": "…"}`.

Roman obvod numbers (I, II, …) are written as 1, 2, …

## What the ingest checks

The maintainer's `ems job ingest` fetches every document URL (so it must be
the direct link to the PDF or page), checks that it is on the website you
named and that the website's domain carries the municipality's name, that
every street, part and k.ú. in your rules is in the input, that the obvod
numbers are those of `obvody`, and that every address of the municipality
lands in exactly one obvod. It draws a review sheet of the result. A rejected
item is listed with the reasons in `ingest-report.md`; fix it in
`output.json` and the maintainer ingests again.
"""

KIND = jobs.Kind(
    name=NAME,
    summary=(
        "council obvod rules (streets, numbers, parts, k.ú.) of the municipalities"
        " with several council obvody, from their official resolutions"
    ),
    item_schema=ITEM_SCHEMA,
    default_size=DEFAULT_SIZE,
    make=make,
    check=check,
    accept=accept,
    priorities=(PRIORITY,),
)
