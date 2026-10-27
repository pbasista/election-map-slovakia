"""The ``okrsok-rules`` job kind: transcribe a municipality's okrsky.

For each election the mayor of every obec sets its okrsky (volebné okrsky:
the polling districts, each with its polling station and roll of voters) and
publishes them: which streets, house numbers or parts of the obec vote in
each, often grouped by council obvod, each okrsok lying within one. An item
of a job is an obec with several okrsky (ŠÚ SR's territorial division,
input ``units-oso2026``) of one of two kinds:

- an obec whose council obvody already have a rule set
  (:mod:`election_map_slovakia.obvodrules`): the item has its obvody with
  their streets and the documents they were transcribed from, which often
  list the okrsky too. The agent writes which okrsky make up each obvod
  and, for the obvody with several, rules that share the obvod's addresses
  among them; or, where no document lists the okrsky's streets, only which
  okrsky make up each obvod.
- an obec that elects its council in one obvod (no ``obvody`` in the item):
  the agent writes rules that share all its addresses among the okrsky.

Either way the agent finds the okrsky document and writes the rules in the
form of :mod:`election_map_slovakia.obvody`. ``check`` (run by ``ems job
ingest``) accepts an item only if

- its documents are on the obec's official website (as for
  :func:`election_map_slovakia.obvodrules.official_problems`), or linked
  from one of its documents that is, and can be fetched; they are kept, by
  sha256, for ``accept``;
- it numbers the okrsky 1..N for the N okrsky of the territorial division,
  giving every obvod of the rule set its okrsky, each in one obvod;
- its okrsok rules are well formed, name only streets, parts and k.ú. the
  obec has, place every address of each obvod with several okrsky (of the
  obec, with one obvod) in exactly one of them, give each such okrsok
  addresses, and none selects addresses of another obvod only; and the
  okrsky can be drawn: they tile their obvod
  (:func:`election_map_slovakia.geo.okrsky_split`);
- without okrsok rules (only where the obec has several obvody), it says
  in ``note`` why.

Each checked item gets a review sheet, ``review/<obec>.html``: the okrsky
drawn within the obvody, every address point coloured by okrsok, the rules
and the document's text. ``accept`` copies the documents to
``data/curated/cache/<sha256>.<ext>`` and adds the okrsky to the rule set,
``obvody/oz/<obec>.toml`` in the election's data
(:attr:`election_map_slovakia.config.Config.election_dir`), or writes them to
``okrsky/<obec>.toml`` there for an obec with one obvod; an obec reported
not found goes to ``okrsky/not-found.json`` there with the URLs tried, losing
any okrsky an earlier ingest gave it, and ``make`` leaves it out unless
named with ``--only``.
"""

from __future__ import annotations

import dataclasses
import html
import json
import tomllib
import urllib.parse
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from election_map_slovakia import addresses, geo, jobs, obvodrules, obvody, xlsx
from election_map_slovakia.candidates import search_key
from election_map_slovakia.config import Config

NAME = "okrsok-rules"
PRIORITY = "addresses"
"""The default order: the obce with the most addresses first."""
DEFAULT_SIZE = 1
UNITS_INPUT = "units-oso2026"
"""The territorial division of the election: okrsky per obec."""
NOT_FOUND_FILE = "not-found.json"
"""Below :data:`election_map_slovakia.obvody.OKRSKY_DIRECTORY` in
:attr:`election_map_slovakia.config.Config.election_dir`."""
_SEVERAL = 2
"""Okrsky of an obec that make it an item."""
_SEARCH_TITLES = (
    "utvorenie volebných okrskov a určenie volebných miestností",
    "zoznam volebných okrskov a volebných miestností",
)

_OKRSOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["number", "text", "rules"],
    "additionalProperties": False,
    "properties": {
        "number": {"type": "integer", "minimum": 1},
        "text": {
            "type": "string",
            "minLength": 1,
            "description": "the document's text on this okrsok, verbatim",
        },
        "rules": {
            "type": "array",
            "items": obvodrules.RULE_SCHEMA,
            "description": "empty for an okrsok alone in its obvod",
        },
        "addressless": {
            "const": True,
            "description": "the okrsok has no addresses: residents without one",
        },
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
            "description": "date of the decision that set the okrsky",
        },
        "fill_nearest": {"type": "boolean"},
        "note": {"type": "string", "minLength": 1},
        "obvody": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["number", "okrsky"],
                "additionalProperties": False,
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "okrsky": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "integer", "minimum": 1},
                    },
                },
            },
        },
        "okrsky": {"type": "array", "minItems": 2, "items": _OKRSOK_SCHEMA},
    },
}


# --- make ------------------------------------------------------------------------


def okrsok_counts(cfg: Config) -> dict[str, int]:
    """Return obec → its number of okrsky in the election (:data:`UNITS_INPUT`)."""
    inp = next((i for i in cfg.inputs.inputs if i.name == UNITS_INPUT), None)
    if inp is None:
        raise jobs.JobError(f"config/inputs.toml: input {UNITS_INPUT!r} missing")
    path = cfg.raw_dir / UNITS_INPUT / inp.file
    if not path.is_file():
        raise jobs.JobError(f"{path} missing; run `ems fetch` first")
    try:
        header, rows = xlsx.find_header(xlsx.read_rows(path), "Kód kraja")
        code, count = header.index("Kód obce"), header.index("Počet okrskov")
        return {r[code]: int(r[count]) for r in rows}
    except (xlsx.XlsxError, ValueError, IndexError) as e:
        raise jobs.JobError(f"{path}: {e}") from None


def not_found_path(cfg: Config) -> Path:
    """Return the file of the obce whose okrsky document was not found."""
    return cfg.election_dir / obvody.OKRSKY_DIRECTORY / NOT_FOUND_FILE


def load_not_found(cfg: Config) -> dict[str, Any]:
    """Return obec → what was tried, of the obce whose document was not found."""
    path = not_found_path(cfg)
    return json.loads(path.read_bytes()) if path.is_file() else {}


def make(cfg: Config, options: jobs.MakeOptions) -> list[jobs.Batch]:
    """Return the jobs for the obce with several okrsky not yet known.

    Those with a rule set that lacks the okrsky, then those with one council
    obvod and no ``okrsky/<obec>.toml`` that are in the address register.
    ``--only`` takes obec codes or names; it also brings back obce whose
    document was not found before, and obce whose okrsky are known.
    """
    data = obvodrules.candidate_data(cfg)
    names = {o["code"]: o for o in data["obce"]}
    okresy = {o["code"]: o["name"] for o in data["okresy"]}
    kraje = {k["code"]: k["name"] for k in data["kraje"]}
    counts = okrsok_counts(cfg)
    directory = obvodrules.places_dir(cfg)
    not_found = load_not_found(cfg)
    pending = {i["id"] for j in options.pending for i in j.items}
    only = {search_key(x) for x in options.only}

    def wanted(code: str, known: bool) -> bool:
        if only:
            return bool({code, search_key(names[code]["name"])} & only)
        return not known and code not in not_found

    split, whole = [], []
    rule_sets = obvody.load_rule_sets(cfg.election_dir)
    for code, rules in rule_sets.items():
        if code in pending or not wanted(code, bool(rules.okrsky)):
            continue
        path = obvody.rules_path(cfg.election_dir, code)
        p = obvody.load_places(directory / f"{code}.json")
        a = obvody.assign(rules, p.places, p.kus, p.planar())
        split.append(
            _item(
                cfg,
                names[code],
                okresy,
                kraje,
                rules,
                path,
                counts[code],
                p,
                a.units,
                names,
            )
        )
    # An obec with several council obvody but no rule set yet gets its okrsky
    # with the obvody, not as a whole obec.
    council = addresses.council_obvody(data["contests"])
    for code, count in counts.items():
        # The city-wide rows of Bratislava and Košice are no obec of the
        # candidate data; an obec without addresses has no places file.
        places = directory / f"{code}.json"
        if (
            count < _SEVERAL
            or code in rule_sets
            or len(council.get(code, ())) >= _SEVERAL
            or code not in names
            or code in pending
            or not places.is_file()
        ):
            continue
        if wanted(code, obvody.okrsky_path(cfg.election_dir, code).is_file()):
            p = obvody.load_places(places)
            whole.append(_whole_item(names[code], okresy, kraje, count, p, names))
    return obvodrules.batches(
        split, PROMPT, options.size, "okrsky"
    ) + obvodrules.batches(whole, WHOLE_PROMPT, options.size, "okrsky")


def obvod_texts(path: Path) -> dict[int, str]:
    """Return obvod → the document's text on it, from the header of rule set *path*.

    The header :func:`election_map_slovakia.obvodrules.accept` wrote.
    """
    out = {}
    for line in header(path):
        if line.startswith(obvodrules.OBVOD_TEXT):
            number, _, text = line.removeprefix(obvodrules.OBVOD_TEXT).partition(": ")
            out[int(number)] = text
    return out


def header(path: Path) -> list[str]:
    """Return the comment lines heading rule set *path*, without ``# ``."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        lines.append(line[2:] if line.startswith("# ") else line[1:])
    return lines


def _copy(cfg: Config, sha256: str) -> str | None:
    """Return the path of the cached copy of a document, relative to the root."""
    found = sorted((cfg.curated_dir / obvodrules.CACHE_DIR).glob(f"{sha256}.*"))
    return str(found[0].relative_to(cfg.root)) if found else None


def _item(
    cfg: Config,
    obec: Mapping[str, Any],
    okresy: Mapping[str, str],
    kraje: Mapping[str, str],
    rules: obvody.RuleSet,
    path: Path,
    okrsky: int,
    p: obvody.ObecPlaces,
    assigned: Sequence[int],
    obce: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the input item of an obec with a rule set (at *path*)."""
    texts = obvod_texts(path)
    return (
        _identity(obec, okresy, kraje, okrsky, obce)
        | {
            "obvody": [
                {"number": n, "seats": s, "text": texts.get(n, "")}
                for n, s in rules.seats.items()
            ],
            "documents": [
                {"url": d.url, "title": d.title, "copy": _copy(cfg, d.sha256)}
                for d in rules.documents
            ],
            "note": rules.note or "",
        }
        | obvodrules.address_fields(p, assigned)
        | _search(obec)
    )


def _whole_item(
    obec: Mapping[str, Any],
    okresy: Mapping[str, str],
    kraje: Mapping[str, str],
    okrsky: int,
    p: obvody.ObecPlaces,
    obce: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the input item of an obec with one council obvod."""
    return (
        _identity(obec, okresy, kraje, okrsky, obce)
        | obvodrules.address_fields(p)
        | _search(obec)
    )


def _identity(
    obec: Mapping[str, Any],
    okresy: Mapping[str, str],
    kraje: Mapping[str, str],
    okrsky: int,
    obce: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the fields of an item that name the obec, and its okrsok count.

    *obce* maps obec code → obec of the candidate data, for the name of the
    city of a city district.
    """
    out = {
        "id": obec["code"],
        "name": obec["name"],
        "okres": okresy.get(obec["okres"], obec["okres"]),
        "kraj": kraje.get(obec["kraj"], obec["kraj"]),
    }
    city = obce.get(obec.get("city") or "")
    if city:
        out["city"] = city["name"]
    return out | {"okrsky": okrsky}


def _search(obec: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return the ``search`` field of an item: queries that find the document."""
    name = obec["name"]
    return {
        "search": [f'"{name}" {t} 2026' for t in _SEARCH_TITLES]
        + [f"{name} volebné okrsky 2026 ulice"]
    }


# --- check -----------------------------------------------------------------------


def rule_set(
    current: obvody.RuleSet, out: Mapping[str, Any], shas: Mapping[str, str]
) -> obvody.RuleSet:
    """Return *current* with the okrsky of output item *out*.

    *shas* maps the URLs of its documents to their sha256. Raises
    :class:`election_map_slovakia.obvody.ObvodyError` if malformed.
    """
    data = tomllib.loads(obvody.dump(current))
    # Ingested again, the okrsky are replaced, not merged.
    for key in ("okrsok", "okrsky_date", "okrsky_fill", "okrsky_note"):
        data.pop(key, None)
    numbers = [o["number"] for o in out["obvody"]]
    if sorted(numbers) != list(current.seats):
        raise obvody.ObvodyError(
            f"obvody {', '.join(map(str, sorted(numbers)))} given, the rule set"
            f" has {', '.join(map(str, current.seats))}"
        )
    for o in out["obvody"]:
        data["obvod"][str(o["number"])]["okrsky"] = o["okrsky"]
    known = {d["url"] for d in data["document"]}
    data["document"] += [
        d for d in obvodrules.document_tables(out, shas) if d["url"] not in known
    ]
    _set_okrsky(data, out)
    # Without rules an okrsok is known only by its obvod: no table.
    data["okrsok"] = {n: t for n, t in data["okrsok"].items() if t}
    return obvody.rule_set(data, f"okrsok-rules {current.obec}")


def whole_rule_set(
    item: Mapping[str, Any], out: Mapping[str, Any], shas: Mapping[str, str]
) -> obvody.RuleSet:
    """Return the okrsky of output item *out* of an obec with one council obvod.

    As :func:`rule_set`, for ``okrsky/<obec>.toml``
    (:func:`election_map_slovakia.obvody.okrsky_set`).
    """
    data: dict[str, Any] = {
        "obec": item["id"],
        "name": item["name"],
        "document": obvodrules.document_tables(out, shas),
    }
    _set_okrsky(data, out)
    return obvody.okrsky_set(data, f"okrsok-rules {item['id']}")


def _set_okrsky(data: dict[str, Any], out: Mapping[str, Any]) -> None:
    """Set the okrsok tables and ``okrsky_*`` keys of rule set *data* from *out*."""
    data["okrsok"] = {str(k["number"]): _okrsok_table(k) for k in out.get("okrsky", [])}
    date = obvodrules.decision_date(out)
    if date is not None:
        data["okrsky_date"] = date
    if out.get("fill_nearest"):
        data["okrsky_fill"] = obvody.FILL_NEAREST
    if out.get("note"):
        data["okrsky_note"] = out["note"]


def _okrsok_table(okrsok: Mapping[str, Any]) -> dict[str, Any]:
    """Return the ``okrsok.<n>`` table of an okrsok of an output item."""
    if okrsok.get("addressless"):
        return {"addressless": True}
    # An empty table: the okrsok alone in its obvod, or with every address.
    return {"rules": okrsok["rules"]} if okrsok["rules"] else {}


def check(
    cfg: Config, job: jobs.Job, item: dict[str, Any], out: dict[str, Any]
) -> list[str]:
    """Return the problems of output item *out* for input *item*."""
    if out["status"] == "not_found":
        return [] if out["tried"] else ["not_found needs the URLs tried"]
    whole = "obvody" not in item
    needed = ("website", "documents", "okrsky" if whole else "obvody")
    missing = [k for k in needed if k not in out]
    if missing:
        return [f"status found needs {', '.join(missing)}"]
    if whole and "obvody" in out:
        return ["the municipality elects its council in one obvod: leave out obvody"]
    if "okrsky" not in out and "note" not in out:
        return ["okrsky without their rules need a note saying why"]
    shas, problems = _documents(cfg, job, item, out)
    if problems:
        return problems
    try:
        rules = (
            whole_rule_set(item, out, shas)
            if whole
            else rule_set(
                obvody.load_rule_sets(cfg.election_dir)[item["id"]], out, shas
            )
        )
    except obvody.ObvodyError as e:
        return [str(e)]
    count = sum(map(len, rules.okrsky.values()))
    if count != item["okrsky"]:
        return [f"{count} okrsky given, the territorial division has {item['okrsky']}"]
    texts = {k["number"] for k in out.get("okrsky", [])}
    if texts and texts != set(rules.okrsok_obvod):
        return ["okrsky must list every okrsok of the obvody, with its text"]
    p = obvody.load_places(obvodrules.places_dir(cfg) / f"{item['id']}.json")
    a = obvody.assign(rules, p.places, p.kus, p.planar())
    k, problems = (
        _okrsok_problems(rules, p, a.units) if rules.okrsok_areas else (None, [])
    )
    return write_review(cfg, job, rules, p, a, k, out, problems)


def _documents(
    cfg: Config, job: jobs.Job, item: Mapping[str, Any], out: Mapping[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """Return URL → sha256 of the documents of *out*, fetched; or the problems.

    A document off the obec's website is accepted where one on it, an HTML
    page, links to it: a CMS host that keeps the files under a number of
    its own (``obec.dobraobec.sk/files/128/…``) does not show whose they are.
    """
    name, website = item["name"], out["website"]
    problems = obvodrules.official_problems(name, website, [])
    if problems:
        return {}, problems
    urls = [d["url"] for d in out["documents"]]
    official = [u for u in urls if not obvodrules.official_problems(name, website, [u])]
    linked = [u for u in urls if u not in official]
    shas: dict[str, str] = {}
    # The official documents first: those are the pages that may link the rest.
    for url in [*official, *linked]:
        if url not in official and not _linked(job, official, url):
            problems += [
                f"{p}, nor linked from one of the documents there: list the"
                " official page that links it too"
                for p in obvodrules.official_problems(name, website, [url])
            ]
            continue
        try:
            shas[url] = obvodrules.sha256_of(obvodrules.keep(cfg, job, url))
        except jobs.JobError as e:
            problems.append(str(e))
    return shas, problems


def _linked(job: jobs.Job, pages: Sequence[str], url: str) -> bool:
    """Return whether one of the fetched HTML documents *pages* links to *url*."""
    index = obvodrules.documents_index(job)
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parts.path)
    for page in pages:
        name = index.get(page, "")
        if not name.endswith(".html"):
            continue
        text = (job.path / obvodrules.DOCUMENTS_DIR / name).read_text(errors="replace")
        text = urllib.parse.unquote(html.unescape(text))
        if parts.hostname and parts.hostname in text and path in text:
            return True
    return False


def _okrsok_problems(
    rules: obvody.RuleSet, p: obvody.ObecPlaces, obvody_of: Sequence[int]
) -> tuple[obvody.Assignment, list[str]]:
    """Return the okrsok of every address of *p* and why it is not acceptable.

    *obvody_of* is the obvod of each address.
    """
    k = obvody.assign_okrsky(rules, p.places, obvody_of, p.kus, p.planar())
    counts = Counter(k.units)
    problems = obvodrules.place_name_problems(rules, p) + k.problems(p.places)
    problems += [
        f"okrsok {n} has no address"
        for ks in rules.mapped.values()
        if len(ks) > 1
        for n in ks
        if not counts[n]
    ]
    return k, problems


# --- review sheet -------------------------------------------------------------------


def write_review(
    cfg: Config,
    job: jobs.Job,
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    obvod_assignment: obvody.Assignment,
    assignment: obvody.Assignment | None,
    out: Mapping[str, Any],
    problems: Sequence[str],
) -> list[str]:
    """Write ``review/<obec>.html`` of *job*; return *problems* and the drawing's.

    *assignment* gives the okrsok of each address (None: no okrsok rules).
    """
    gpkg = cfg.build_dir / f"USJ_hranice_{obvodrules.REVIEW_LEVEL}.gpkg"
    drawing = ""
    problems = list(problems)
    if (
        gpkg.is_file()
        and assignment is not None
        and not assignment.unassigned
        and not assignment.conflicts
    ):
        obce, kus = obvodrules.obce_and_kus(gpkg)
        mine = kus.get(rules.obec, [])
        to_wgs84 = geo.transformer()
        scale = 10**geo.DECIMALS
        split = (
            geo.whole_split(mine)
            if rules.whole
            else geo.council_split(
                rules, places, obvod_assignment.units, mine, to_wgs84
            )
        )
        obec = geo.to_grid(obce[rules.obec], to_wgs84, scale)
        try:
            okrsky = geo.okrsky_split(
                rules, places, assignment.units, split, mine, to_wgs84
            )
            grid = geo.to_grid(np.array([o.area for o in okrsky]), to_wgs84, scale)
            outlines = [
                g
                for _, g in geo.council_geometry(
                    rules.obec, obce[rules.obec], split, mine, to_wgs84
                )
            ]
            drawing = obvodrules.review_svg(
                obec,
                [(o.number, g) for o, g in zip(okrsky, grid, strict=True)],
                places,
                assignment,
                True,
                outlines,
            )
        except geo.GeoError as e:
            problems.append(f"(review) {e}")
    path = job.path / obvodrules.REVIEW_DIR / f"{rules.obec}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _page(rules, places, assignment, out, problems, drawing), encoding="utf-8"
    )
    return problems


def _page(
    rules: obvody.RuleSet,
    places: obvody.ObecPlaces,
    assignment: obvody.Assignment | None,
    out: Mapping[str, Any],
    problems: Sequence[str],
    drawing: str,
) -> str:
    """Return the review sheet: drawing, problems, okrsky with their rules."""
    e = html.escape
    counts = Counter(assignment.units) if assignment else Counter()
    filled = (
        Counter(assignment.units[i] for i in assignment.filled)
        if assignment
        else Counter()
    )
    texts = {k["number"]: k["text"] for k in out.get("okrsky", [])}
    rows = []
    for k, obvod in rules.okrsok_obvod.items():
        listed = obvodrules.rule_items(r for r in rules.okrsok_rules if r.unit == k)
        rows.append(
            f"<tr>{obvodrules.unit_cell(k)}"
            + ("" if rules.whole else f"<td>{obvod}</td>")
            + f"<td>{counts[k]:,}"
            + (f" ({filled[k]:,} by the nearest)" if filled[k] else "")
            + f'</td><td><ul>{listed}</ul></td><td class="text">{e(texts.get(k, ""))}</td></tr>'
        )
    unused = assignment.unused if assignment else []
    return f"""<!doctype html>
<html lang="sk"><head><meta charset="utf-8">
<title>{e(rules.name)} ({rules.obec}): okrsky</title>
<style>
{obvodrules.REVIEW_STYLE}
</style></head><body>
<h1>{e(rules.name)} ({rules.obec}): okrsky</h1>
<p>{len(places.places):,} addresses; okrsky decided {rules.okrsky_date.isoformat() if rules.okrsky_date else "on an unstated date"}; documents:</p>
<ul>{obvodrules.document_items(rules)}</ul>
{f"<p>{e(rules.okrsky_note)}</p>" if rules.okrsky_note else ""}
{obvodrules.issues_html(problems, unused)}
{drawing or "<p>(no drawing: no okrsok rules, the addresses are not all placed, or ZBGIS level 1 is not extracted)</p>"}
<p>Polygons: the okrsky as drawn from the address points; thick lines: the {"obec" if rules.whole else "council obvody"}. Dots: addresses by okrsok; black inner dots: placed by the nearest address.</p>
<table><tr><th>okrsok</th>{"" if rules.whole else "<th>obvod</th>"}<th>addresses</th><th>rules</th><th>document text</th></tr>
{"".join(rows)}
</table>
</body></html>
"""


# --- accept --------------------------------------------------------------------------


def accept(cfg: Config, job: jobs.Job, accepted: list[jobs.Accepted]) -> list[str]:
    """Add the accepted okrsky to their rule sets or files; keep their documents."""
    lines = []
    index = obvodrules.documents_index(job)
    not_found = load_not_found(cfg)
    rule_sets = obvody.load_rule_sets(cfg.election_dir)
    for item, out in accepted:
        code = item["id"]
        if out["status"] == "not_found":
            lines.append(obvodrules.record_not_found(not_found, job, item, out))
            lines += _drop_okrsky(cfg, item, rule_sets.get(code))
            continue
        not_found.pop(code, None)
        shas = obvodrules.cache_documents(cfg, job, index, out)
        if "obvody" in item:
            rules = rule_set(rule_sets[code], out, shas)
            path = obvody.rules_path(cfg.election_dir, code)
            comments, by = _obvod_header(path), _ADDED
        else:
            rules = whole_rule_set(item, out, shas)
            path = obvody.okrsky_path(cfg.election_dir, code)
            comments = []
            by = f"Okrsky of {item['name']}, transcribed by an AI agent in job"
        comments += [
            f"{by} {job.name} from the documents below;",
            "checked by `ems job ingest` against the address register. The document's",
            "text per okrsok, verbatim:",
            *(
                f"  okrsok {k['number']}: " + " ".join(k["text"].split())
                for k in sorted(out.get("okrsky", []), key=lambda k: k["number"])
            ),
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(obvody.dump(rules, comments), encoding="utf-8")
        lines.append(f"{item['name']} ({code}): {path.relative_to(cfg.root)}")
    if not_found or not_found_path(cfg).is_file():
        jobs.write_json(not_found_path(cfg), dict(sorted(not_found.items())))
    return lines


_ADDED = "Okrsky added by an AI agent in job"
"""How the header of a rule set begins the lines on its okrsky."""


def _obvod_header(path: Path) -> list[str]:
    """Return the header of rule set *path* without the lines on its okrsky."""
    lines = header(path)
    return lines[: next((i for i, h in enumerate(lines) if h.startswith(_ADDED)), None)]


def _drop_okrsky(
    cfg: Config, item: Mapping[str, Any], current: obvody.RuleSet | None
) -> list[str]:
    """Remove the okrsky an earlier ingest gave the obec of *item*; return report lines.

    *current* is its council rule set, None for an obec with one obvod.
    """
    code = item["id"]
    if current is None:
        path = obvody.okrsky_path(cfg.election_dir, code)
        if not path.is_file():
            return []
        path.unlink()
    elif current.okrsky:
        path = obvody.rules_path(cfg.election_dir, code)
        kept = _obvod_header(path)
        rules = dataclasses.replace(
            current,
            okrsky={},
            okrsok_rules=(),
            okrsky_fill=False,
            okrsky_date=None,
            okrsky_note=None,
            addressless=(),
        )
        path.write_text(obvody.dump(rules, kept), encoding="utf-8")
    else:
        return []
    return [f"{item['name']} ({code}): its earlier okrsky removed"]


_TASK = """\
# Okrsky of Slovak municipalities

Each item of `input.json` is a Slovak municipality (obec, or a city
district of Bratislava or Košice) that votes in several okrsky (volebné
okrsky: the polling districts, each with its polling station, volebná
miestnosť) in the elections of 24 October 2026. Its mayor set them and
published them: which streets, house numbers or parts of the municipality
vote in each okrsok.
"""

_INPUT = """\
## Input

Each item has:

- `id`: the municipality code; `name`, `okres`, `kraj` (and `city` for a
  district of Bratislava or Košice: the document is the district's).
- `okrsky`: how many okrsky the municipality has in these elections, per the
  Statistical Office. Number them 1..`okrsky` as the document does.
"""

_FINDING = """\
## Finding the document

On the municipality's official website, look at the 2026 elections page
(Voľby 2026, Voľby do orgánov samosprávy obcí a samosprávnych krajov 2026)
and the official notice board (úradná tabuľa) of July–August 2026. Typical
titles: "Utvorenie volebných okrskov a určenie volebných miestností",
"Oznámenie o utvorení volebných okrskov", "Zoznam volebných okrskov a
volebných miestností" (with "ulice", "zoznam ulíc"). Web search with the
queries in `search` helps.

- Use the document for the 24 October 2026 elections; one for the
  referendum of 4 July 2026 only if it says the okrsky stay the same, and
  say so in `note`.
- `documents` must be on the municipality's own website (its domain or
  subdomains), on `cuet.slovensko.sk`, or on a CMS host with the
  municipality's domain in the path. A file on a CMS host that does not
  name the municipality (`obec.dobraobec.sk/files/128/…`) is accepted when
  you also list the municipality's page that links it. List every document
  you used, and name the website in `website`.
- A scanned PDF has no text: render its pages (`uv run --with pypdfium2
  --with pillow python`, scale 3) and read the images, or OCR them (`uv
  run --with rapidocr-onnxruntime python`). A DOCX is a ZIP: its text is
  in `word/document.xml`.
- If you find nothing usable after a fair search, report `"status":
  "not_found"` with every URL you tried in `tried` and a `note`. Never
  guess.
"""

_TEXT = """\
`text` is the document's words on the okrsok, as one string: its streets or
the parts of the municipality it names, not the polling station's address.
You may rejoin words that a PDF's text layer splits. From a scan, write what
you read, with diacritics; where only OCR without diacritics is possible,
give its text with the misread letters you are sure of fixed, and say so in
`note`.
"""

_RULES = """\
A rule selects addresses by exactly one of:

- `"street": "<name as in input streets>"`: a street. Where the document
  writes it differently, `street` is the register's name and `written` the
  name exactly as the document writes it. Standard abbreviations (`nám.`,
  `nábr.`, `gen.`, `Čsl.`, initials of first names) and a left-out "ulica"
  read as the same name; any other difference (a typo, `SNP` for
  `Slovenského národného povstania`, another ending) needs a `note` saying
  why it is the same street. A street the document names but the register
  lacks is left out; say so in `note`.
- `"street"` plus `"part": "<part>"`: that street only within that part.
- `"part": "<name as in input parts>"`: a whole part of the municipality.
- `"ku": "<name as in input kus>"`: a whole cadastral area.
- `"rest": true`: the addresses no other rule selects.

and may narrow it to house numbers: `"numbers": "1-35, 40, 42A, 101-"`,
`"parity": "odd"` / `"even"`, `"except": "7, 9"`; in a street the numbers are
orientačné, otherwise súpisné; add `"by": "supisne"` where the document numbers
a street by súpisné čísla (and only split a street by numbers where the
document puts it in several okrsky). A range takes no letter: "20–34A" is
`"20-34, 34A"`, "12A–12J" the list `"12A, 12B, …, 12J"`. The most specific
rule wins: a number with a letter, other numbers, a whole street, a whole
part, a k.ú., the rest.

Where the document leaves streets out, place each by the streets around it
as a rule with `"inferred": true` and a `note`, or, as a last resort, set
`"fill_nearest": true`: an address no rule selects then takes the okrsok of
the nearest address a rule placed (by its map point; one without a point
takes the okrsok most of its street, else of its part, got). Say in `note`
which addresses that concerns.

Set `date` to the date of the decision that set the okrsky (YYYY-MM-DD):
usually the mayor's, sometimes a council resolution; leave it out if no
document states it.
"""

_CHECKS = """\
## What the ingest checks

The maintainer's `ems job ingest` fetches every document URL (so it must be
the direct link to the PDF or page), checks that it is on the website you
named, that the okrsky are numbered 1..`okrsky`, that every street, part and
k.ú. in your rules is in the input, that every address lands in exactly one
okrsok, each okrsok with addresses, and that the okrsky can be drawn. It
draws a review sheet, `review/<obec>.html` in the job directory, with its
problems at the top. Addresses without a street often have no rule but the
nearest address (`fill_nearest`); that is expected. A rejected item is
listed with the reasons in `ingest-report.md`; fix it in `output.json` and
ingest again.
"""

PROMPT = f"""\
{_TASK}This one elects its council in several electoral districts
(volebné obvody), which are already known; every okrsok lies within one
obvod. Your task: find the official document, read it, and write which
okrsky make up each obvod and, for the obvody with several okrsky, rules a
program can apply to every address of the obvod to find its okrsok. You
need web search and the ability to fetch web pages and PDFs.

{_INPUT}\
- `obvody`: the obvody with their seats and the text of the resolution that
  set them (`text`; often it already names the okrsky of each obvod).
- `documents`: the documents the obvody were transcribed from, with `copy`,
  a local copy (PDF or HTML) you may read instead of fetching. Read them
  first: they often list the okrsky with their streets, or the okrsky
  document is among them. List those you rely on in your `documents` too.
- `note`: what was noted when the obvody were transcribed.
- `streets`: every street in the official address register:
  `[name, addresses, [parts], [lowest, highest orientačné číslo], [obvody]]`,
  the last the obvody its addresses are in. Use these names in your rules.
- `parts`: the parts of the municipality (časti obce) with their address
  counts and obvody. Addresses without a street are numbered by súpisné
  číslo within their part.
- `kus`: the cadastral areas (k.ú.) of the municipality.
- `address_count`, `without_street`.
- `search`: queries that usually find the document.

{_FINDING}
If the documents say which okrsky make up each obvod but no published
document lists the streets of each okrsok, give `obvody` without `okrsky`
and say in `note` what you found.

## Writing the okrsky

`obvody`: for each obvod of the input its `number` and `okrsky`, the
numbers of its okrsky. Every okrsok 1..`okrsky` in exactly one obvod.

`okrsky`: for each okrsok its `number`, `text` and `rules`:

- an okrsok alone in its obvod: `"rules": []` (it is the whole obvod);
- an okrsok that holds only residents registered without an address ("bez
  ulice", "trvalý pobyt len na obec", homeless): `"rules": [],
  "addressless": true`; the other okrsky of its obvod share its addresses
  as if it were not there. An okrsok with addresses that also takes those
  residents is an ordinary one: leave the residents out of its rules;
- the okrsky of an obvod with several: rules that share the obvod's
  addresses among them. They see only the addresses of their obvod, so they
  need not repeat the obvod's limits: "the rest of the obvod" is
  `{{"rest": true}}` (at most once per obvod), and `fill_nearest` looks
  within the obvod.

{_TEXT}
{_RULES}
Every address of an obvod with several okrsky must end up in exactly one of
its okrsky. A street the document puts in an okrsok of another obvod than
the one the obvod rules put it in is a contradiction: say so in `note` and
follow the obvod (the rules of an okrsok must not select only addresses of
another obvod).

## Output

Write `output.json` as `README.md` says, one object per item:

```json
{{"id": "504203", "status": "found",
 "website": "https://senica.sk/",
 "documents": [{{"url": "https://senica.sk/data/component_file/100/6998/f2765.pdf",
                "title": "Zoznam volebných obvodov, okrskov a počty poslancov"}}],
 "date": "2026-07-20",
 "tried": ["https://senica.sk/volby-2026"],
 "obvody": [{{"number": 1, "okrsky": [1]}}, {{"number": 2, "okrsky": [2, 3]}}],
 "okrsky": [
   {{"number": 1, "text": "Bahenská, Beňovského, …", "rules": []}},
   {{"number": 2, "text": "Kalinčiakova, Tehelná, Železničná",
    "rules": [{{"street": "Kalinčiakova"}}, {{"street": "Tehelná"}},
              {{"street": "Železničná"}}]}},
   {{"number": 3, "text": "Hviezdoslavova 319/43, …, Kasárenská, Palárikova",
    "rules": [{{"rest": true}}]}}
 ]}}
```

or `{{"id": "…", "status": "not_found", "tried": ["…"], "note": "…"}}`.
`tried` is required either way: every URL you looked at, in order (empty if
the input's documents sufficed).

{_CHECKS}"""

WHOLE_PROMPT = f"""\
{_TASK}This one elects its council in one electoral district (volebný
obvod). Your task: find the official document, read it, and write rules a
program can apply to every address of the municipality to find its okrsok.
You need web search and the ability to fetch web pages and PDFs.

{_INPUT}\
- `streets`: every street in the official address register:
  `[name, addresses, [parts], [lowest, highest orientačné číslo]]`. Use
  these names in your rules.
- `parts`: the parts of the municipality (časti obce) with their address
  counts. Addresses without a street are numbered by súpisné číslo within
  their part.
- `kus`: the cadastral areas (k.ú.) of the municipality.
- `address_count`, `without_street`.
- `search`: queries that usually find the document.

{_FINDING}
## Writing the okrsky

`okrsky`: for each okrsok 1..`okrsky` its `number`, `text` and `rules`,
which choose among all the addresses of the municipality; `{{"rest":
true}}` (at most once) is every address no other rule selects. An okrsok
that holds only residents registered without an address ("bez ulice",
"trvalý pobyt len na obec", homeless) has `"rules": [], "addressless":
true`; the one okrsok with addresses beside such okrsky holds every
address: `"rules": []`. Every other okrsok needs rules. Give no `obvody`.
A `note` goes on the item or on a rule, never on an okrsok; `written` only
on a street rule, and a `written` name that differs beyond a standard
abbreviation needs a `note` on that rule.

Villages are usually split by their parts (časti obce, often former
villages: "okrsok č. 2: časť obce Horná Ves"): use `part` rules. A
settlement missing from `parts` may be a k.ú. in `kus`, or a street. Some
documents give each okrsok only its polling station: where the okrsky are
as many as the `parts` and each station lies in another part, give each
okrsok the part of its station, `"inferred": true` with a `note`; where
not, report not_found.

{_TEXT}
{_RULES}
## Output

Write `output.json` as `README.md` says, one object per item:

```json
{{"id": "512345", "status": "found",
 "website": "https://www.obecvzor.sk/",
 "documents": [{{"url": "https://www.obecvzor.sk/files/okrsky-2026.pdf",
                "title": "Utvorenie volebných okrskov a určenie volebných miestností"}}],
 "date": "2026-07-22",
 "tried": ["https://www.obecvzor.sk/volby-2026"],
 "okrsky": [
   {{"number": 1, "text": "časť obce Vzor", "rules": [{{"part": "Vzor"}}]}},
   {{"number": 2, "text": "časť obce Horná Ves", "rules": [{{"part": "Horná Ves"}}]}}
 ]}}
```

or `{{"id": "…", "status": "not_found", "tried": ["…"], "note": "…"}}`.
`tried` is required either way: every URL you looked at, in order.

{_CHECKS}"""

KIND = jobs.Kind(
    name=NAME,
    summary=(
        "okrsky (polling districts) of the municipalities with several, from"
        " the mayors' decisions: their streets and parts, and which okrsky make"
        " up each council obvod"
    ),
    item_schema=ITEM_SCHEMA,
    default_size=DEFAULT_SIZE,
    make=make,
    check=check,
    accept=accept,
    priorities=(PRIORITY,),
)
