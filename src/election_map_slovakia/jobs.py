"""Agent jobs: batches of work for an AI agent, and ingesting its results.

Some inputs need judgement no code has: translating, reading a municipal
resolution. ``ems job make <kind>`` writes that work as self-contained job
directories which any agent tool can work through with nothing but the
directory (and the web); ``ems job ingest <dir>`` checks what the agent wrote
and merges what passes into ``data/curated/``, which is committed. Job
directories are scratch (git-ignored): reproducible from the inputs, and the
curated result is what counts.

A job directory ``data/jobs/<kind>-NNN/`` holds::

    input.json        {kind, job, <context of the kind>, items: [{id, ...}]}
    schema.json       JSON Schema of output.json: {items: [{id, ...}]}
    prompt.md         what to do with each item, from the kind
    README.md         how to run the job, the same for every kind
    output.json       written by the agent
    ingest-report.md  written by ingest: accepted, rejected with reasons,
                      missing

Ingest validates ``output.json`` against ``schema.json`` (:func:`validate`,
the subset of JSON Schema in :data:`KEYWORDS`); a problem inside one item
rejects that item, any other the whole output. Each valid item whose ``id``
is one of the job's runs through the kind's deterministic ``check``; the items
without problems go to the kind's ``accept``, which merges them into the
curated data. Ingesting the same output again changes nothing, so a job can
be re-ingested after its output is fixed. A job without a report is pending:
``make`` leaves its items to it (see :class:`Kind`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from election_map_slovakia import output
from election_map_slovakia.config import Config

INPUT = "input.json"
SCHEMA = "schema.json"
PROMPT = "prompt.md"
README = "README.md"
OUTPUT = "output.json"
REPORT = "ingest-report.md"
_RESERVED = frozenset({"kind", "job", "items"})
_NUMBER = 3
_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class JobError(Exception):
    """A job directory or a kind's input is unusable."""


class SchemaError(JobError):
    """A schema uses a keyword :func:`validate` does not implement."""


def jobs_dir(cfg: Config) -> Path:
    """Return ``data/jobs``, where job directories are written."""
    return cfg.root / "data" / "jobs"


def write_json(path: Path, content: object) -> None:
    """Write *content* to *path* as indented, key-sorted UTF-8 JSON.

    For files people read and diff: job files and curated data.
    """
    text = json.dumps(content, ensure_ascii=False, indent=1, sort_keys=True)
    output.write_file(path, (text + "\n").encode())


@dataclass(frozen=True)
class Batch:
    """One job for ``make`` to write."""

    items: list[dict[str, Any]]
    """The work, each with a unique string ``id``."""
    prompt: str
    """Contents of ``prompt.md``."""
    title: str
    """One line saying what the job is, for README.md and ``make``'s list."""
    context: dict[str, Any] = field(default_factory=dict)
    """More ``input.json`` fields, shared by the items (e.g. the language)."""


@dataclass(frozen=True)
class Job:
    """A job directory as ``make`` wrote it."""

    path: Path
    kind: str
    context: dict[str, Any]
    items: list[dict[str, Any]]

    @property
    def name(self) -> str:
        """Return the directory name, ``<kind>-NNN``."""
        return self.path.name

    @property
    def pending(self) -> bool:
        """Return whether the job has not been ingested yet."""
        return not (self.path / REPORT).is_file()


@dataclass(frozen=True)
class MakeOptions:
    """What ``ems job make`` asks a kind for."""

    size: int
    """Items per job, where the kind batches by count."""
    priority: str | None
    """One of the kind's ``priorities``, or None for its first (if any)."""
    only: tuple[str, ...]
    """Restrict to these; their meaning (codes, names) is the kind's."""
    pending: tuple[Job, ...]
    """Jobs of the kind not ingested yet, whose items not to make again."""


Accepted = tuple[dict[str, Any], dict[str, Any]]
"""An accepted item: (input item, output item)."""


@dataclass(frozen=True)
class Kind:
    """A kind of job and its hooks.

    ``make`` returns the batches to write, leaving out what is curated
    already or in ``options.pending``. ``check`` returns the problems of one
    schema-valid output item (empty: accepted) given its input item.
    ``accept`` merges the accepted items into ``data/curated/`` (idempotent)
    and returns lines for the report.
    """

    name: str
    summary: str
    """One line for ``ems job make --help``."""
    item_schema: dict[str, Any]
    """JSON Schema of one output item, an object with a string ``id``."""
    default_size: int
    make: Callable[[Config, MakeOptions], list[Batch]]
    check: Callable[[Config, Job, dict[str, Any], dict[str, Any]], list[str]]
    accept: Callable[[Config, Job, list[Accepted]], list[str]]
    priorities: tuple[str, ...] = ()
    """Orders ``make`` can put the items in, the default first."""


def kinds() -> dict[str, Kind]:
    """Return every job kind by name."""
    # Imported here: the kinds' modules build on this one.
    from election_map_slovakia import obvodrules, research, translate

    return {k.name: k for k in (translate.KIND, obvodrules.KIND, research.KIND)}


def output_schema(kind: Kind) -> dict[str, Any]:
    """Return the schema of a whole ``output.json`` of *kind*."""
    return {
        "$schema": _SCHEMA_DIALECT,
        "type": "object",
        "required": ["items"],
        "additionalProperties": False,
        "properties": {"items": {"type": "array", "items": kind.item_schema}},
    }


# --- validation -----------------------------------------------------------

KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
        "anyOf",
        "oneOf",
        "$ref",
        "$defs",
    }
)
"""The JSON Schema keywords :func:`validate` implements (draft 2020-12)."""
_ANNOTATIONS = frozenset(
    {"$schema", "$id", "$comment", "title", "description", "examples", "default"}
)
_TYPES: dict[str, Callable[[object], bool]] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_SUBSCHEMA_MAPS = ("properties", "$defs")
_SUBSCHEMA_LISTS = ("anyOf", "oneOf")
_REF = re.compile(r"#/\$defs/([^/]+)")

Problem = tuple[str, str]
"""(JSON Pointer of the value, what is wrong with it)."""


def check_schema(schema: Mapping[str, Any]) -> None:
    """Raise :class:`SchemaError` if *schema* uses what :func:`validate` lacks."""
    defs = schema.get("$defs", {})
    stack: list[tuple[object, str]] = [(schema, "")]
    while stack:
        s, where = stack.pop()
        if isinstance(s, bool):
            continue
        if not isinstance(s, Mapping):
            raise SchemaError(f"{where or '/'}: a schema must be an object")
        _check_keywords(s, where or "/", defs)
        stack.extend(_subschemas(s, where))


def _check_keywords(s: Mapping[str, Any], where: str, defs: Mapping[str, Any]) -> None:
    unknown = set(s) - KEYWORDS - _ANNOTATIONS
    if unknown:
        raise SchemaError(f"{where}: unsupported keywords {', '.join(sorted(unknown))}")
    types = [s["type"]] if isinstance(s.get("type"), str) else s.get("type", [])
    if any(t not in _TYPES for t in types):
        raise SchemaError(f"{where}: unknown type in {types}")
    if "$ref" in s:
        ref = _REF.fullmatch(s["$ref"])
        if not ref or ref.group(1) not in defs:
            raise SchemaError(f"{where}: $ref must name one of #/$defs/")


def _subschemas(s: Mapping[str, Any], where: str) -> Iterator[tuple[object, str]]:
    for key in _SUBSCHEMA_MAPS:
        for name, sub in s.get(key, {}).items():
            yield sub, f"{where}/{key}/{name}"
    for key in _SUBSCHEMA_LISTS:
        for i, sub in enumerate(s.get(key, [])):
            yield sub, f"{where}/{key}/{i}"
    for key in ("items", "additionalProperties"):
        if key in s:
            yield s[key], f"{where}/{key}"


def validate(instance: object, schema: Mapping[str, Any]) -> list[Problem]:
    """Return the problems of *instance* against *schema*; empty: valid.

    Implements the keywords in :data:`KEYWORDS`; run :func:`check_schema`
    on a schema first.
    """
    defs = schema.get("$defs", {})
    return list(_validate(instance, schema, "", defs))


def _validate(  # noqa: C901, PLR0912 - one branch per keyword reads best
    value: object, s: object, at: str, defs: Mapping[str, Any]
) -> Iterator[Problem]:
    if s is True:
        return
    if s is False:
        yield at, "not allowed"
        return
    assert isinstance(s, Mapping)
    if "$ref" in s:
        yield from _validate(value, defs[s["$ref"].rsplit("/", 1)[1]], at, defs)
    if "type" in s:
        types = [s["type"]] if isinstance(s["type"], str) else s["type"]
        if not any(_TYPES[t](value) for t in types):
            yield at, f"expected {' or '.join(types)}, got {_type_name(value)}"
            return
    if "enum" in s and not any(_equal(value, e) for e in s["enum"]):
        yield at, f"{_short(value)} is not one of {_short(s['enum'])}"
    if "const" in s and not _equal(value, s["const"]):
        yield at, f"expected {_short(s['const'])}"
    if isinstance(value, str):
        yield from _validate_string(value, s, at)
    if _TYPES["number"](value):
        assert isinstance(value, int | float)
        if "minimum" in s and value < s["minimum"]:
            yield at, f"{value} is below the minimum {s['minimum']}"
        if "maximum" in s and value > s["maximum"]:
            yield at, f"{value} is above the maximum {s['maximum']}"
    if isinstance(value, list):
        yield from _validate_array(value, s, at, defs)
    if isinstance(value, dict):
        yield from _validate_object(value, s, at, defs)
    for key in _SUBSCHEMA_LISTS:
        if key not in s:
            continue
        matches = [not list(_validate(value, sub, at, defs)) for sub in s[key]]
        if not any(matches):
            yield at, f"matches none of the {key} alternatives"
        elif key == "oneOf" and sum(matches) > 1:
            yield at, "matches more than one oneOf alternative"


def _validate_string(value: str, s: Mapping[str, Any], at: str) -> Iterator[Problem]:
    if "minLength" in s and len(value) < s["minLength"]:
        yield at, f"shorter than {s['minLength']} characters"
    if "maxLength" in s and len(value) > s["maxLength"]:
        yield at, f"longer than {s['maxLength']} characters"
    if "pattern" in s and not re.search(s["pattern"], value):
        yield at, f"{_short(value)} does not match {s['pattern']}"


def _validate_array(
    value: list[Any], s: Mapping[str, Any], at: str, defs: Mapping[str, Any]
) -> Iterator[Problem]:
    if "minItems" in s and len(value) < s["minItems"]:
        yield at, f"fewer than {s['minItems']} items"
    if "maxItems" in s and len(value) > s["maxItems"]:
        yield at, f"more than {s['maxItems']} items"
    if s.get("uniqueItems"):
        seen = [json.dumps(v, sort_keys=True) for v in value]
        if len(set(seen)) < len(seen):
            yield at, "items are not unique"
    if "items" in s:
        for i, item in enumerate(value):
            yield from _validate(item, s["items"], f"{at}/{i}", defs)


def _validate_object(
    value: dict[str, Any], s: Mapping[str, Any], at: str, defs: Mapping[str, Any]
) -> Iterator[Problem]:
    for name in s.get("required", []):
        if name not in value:
            yield at, f"missing required property {name!r}"
    properties = s.get("properties", {})
    extra = s.get("additionalProperties", True)
    for name, item in value.items():
        where = f"{at}/{_pointer_token(name)}"
        if name in properties:
            yield from _validate(item, properties[name], where, defs)
        elif extra is False:
            yield at, f"unexpected property {name!r}"
        else:
            yield from _validate(item, extra, where, defs)


def _pointer_token(name: str) -> str:
    return name.replace("~", "~0").replace("/", "~1")


def _equal(a: object, b: object) -> bool:
    # JSON equality: true and 1 differ, 1 and 1.0 do not.
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _type_name(value: object) -> str:
    return next(
        (name for name, test in _TYPES.items() if test(value)), type(value).__name__
    )


def _short(value: object, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- make -----------------------------------------------------------------


def load_job(path: Path) -> Job:
    """Return the job in directory *path*."""
    try:
        content = json.loads((path / INPUT).read_bytes())
    except (OSError, ValueError) as e:
        raise JobError(f"{path / INPUT}: {e}") from None
    if not isinstance(content, dict) or not isinstance(content.get("items"), list):
        raise JobError(f"{path / INPUT}: not a job input")
    context = {k: v for k, v in content.items() if k not in _RESERVED}
    return Job(path, str(content.get("kind")), context, content["items"])


def existing(cfg: Config, kind: Kind) -> list[Job]:
    """Return the jobs of *kind* in ``data/jobs/``, oldest first."""
    pattern = re.compile(rf"{re.escape(kind.name)}-\d{{{_NUMBER},}}")
    root = jobs_dir(cfg)
    if not root.is_dir():
        return []
    return [
        load_job(p)
        for p in sorted(root.iterdir(), key=lambda p: (len(p.name), p.name))
        if p.is_dir() and pattern.fullmatch(p.name)
    ]


def make(
    cfg: Config,
    kind: Kind,
    *,
    size: int | None = None,
    priority: str | None = None,
    only: Sequence[str] = (),
    limit: int | None = None,
) -> list[Job]:
    """Write the jobs of *kind* still to do, at most *limit*; return them.

    Numbering continues after the highest existing job of the kind.
    """
    if priority is not None and priority not in kind.priorities:
        choices = ", ".join(kind.priorities) or "none"
        raise JobError(
            f"{kind.name}: unknown priority {priority!r} (choices: {choices})"
        )
    schema = output_schema(kind)
    check_schema(schema)
    jobs = existing(cfg, kind)
    options = MakeOptions(
        size=size or kind.default_size,
        priority=priority or (kind.priorities[0] if kind.priorities else None),
        only=tuple(only),
        pending=tuple(j for j in jobs if j.pending),
    )
    batches = kind.make(cfg, options)[:limit]
    number = max((int(j.name.rsplit("-", 1)[1]) for j in jobs), default=0)
    written = []
    for batch in batches:
        _check_batch(kind, batch)
        number += 1
        path = jobs_dir(cfg) / f"{kind.name}-{number:0{_NUMBER}d}"
        if path.exists():
            raise JobError(f"{path} exists")
        content = {"kind": kind.name, "job": path.name} | batch.context
        write_json(path / INPUT, content | {"items": batch.items})
        write_json(path / SCHEMA, schema)
        output.write_file(path / PROMPT, batch.prompt.encode())
        output.write_file(path / README, readme(kind, path.name, batch).encode())
        written.append(Job(path, kind.name, batch.context, batch.items))
    return written


def _check_batch(kind: Kind, batch: Batch) -> None:
    ids = [item.get("id") for item in batch.items]
    if not ids or not all(isinstance(i, str) for i in ids) or len(set(ids)) < len(ids):
        raise JobError(f"{kind.name}: a batch needs items with unique string ids")
    if _RESERVED & set(batch.context):
        raise JobError(f"{kind.name}: context uses {', '.join(_RESERVED)}")


def readme(kind: Kind, name: str, batch: Batch) -> str:
    """Return README.md of a job: how to run it with any agent tool."""
    return f"""# Job {name}: {batch.title}

This directory is a self-contained job for an AI agent (any tool: a chat
with file access, a coding agent, a script around a model API). It needs
only this directory and, where `prompt.md` says so, web access.

## Files

- `prompt.md`: the instructions. Read them first and follow them exactly.
- `input.json`: the work, {len(batch.items)} items under `items`, each with
  an `id`. The other top-level fields are context shared by all items.
  Do not change this file.
- `schema.json`: the JSON Schema (draft 2020-12) that `output.json` must
  satisfy.
- `output.json`: you write it, in this directory.

## What to write

`output.json` is one JSON object, UTF-8, with a single key `items`: an
array with one object per input item you completed, each carrying the
`id` of its input item and the fields `schema.json` requires:

```json
{{"items": [{{"id": "<id from input.json>", "...": "..."}}]}}
```

- Cover every input item if you can; leave out an item you cannot do
  rather than guessing. Each `id` at most once.
- Write nothing else into the file (no comments, no Markdown fences).
- For a long job, writing `output.json` in parts is fine as long as the
  final file is one valid JSON object.

## Afterwards

The maintainer runs `ems job ingest data/jobs/{name}`. It checks the output
against `schema.json` and the deterministic checks of the `{kind.name}`
kind, merges what passes into `data/curated/` and writes `{REPORT}` here
with every rejected item and why. To fix rejected items, correct them in
`output.json` and ingest again; items that passed stay as they are.
"""


# --- ingest ---------------------------------------------------------------


@dataclass
class Report:
    """What :func:`ingest` did with one job."""

    job: str
    total: int
    accepted: int = 0
    rejected: dict[str, list[str]] = field(default_factory=dict)
    """Item id (or ``#<index>`` where it has none) → problems."""
    missing: list[str] = field(default_factory=list)
    """Input ids without an output item."""
    failure: str | None = None
    """Why the output as a whole was rejected."""
    curated: list[str] = field(default_factory=list)
    """What ``accept`` said it merged."""

    @property
    def ok(self) -> bool:
        """Return whether every item was accepted."""
        return self.failure is None and not self.rejected and not self.missing

    def summary(self) -> str:
        """Return a one-line summary."""
        if self.failure:
            return f"{self.job}: output rejected: {self.failure}"
        return (
            f"{self.job}: {self.accepted:,} of {self.total:,} accepted,"
            f" {len(self.rejected):,} rejected, {len(self.missing):,} missing"
        )

    def markdown(self) -> str:
        """Return ``ingest-report.md``."""
        lines = [f"# Ingest report: {self.job}", "", self.summary(), ""]
        sections: list[tuple[str, Iterable[str]]] = [
            (
                "Rejected",
                (
                    f"- `{key}`: {'; '.join(problems)}"
                    for key, problems in self.rejected.items()
                ),
            ),
            ("Missing", (f"- `{key}`" for key in self.missing)),
            ("Curated", (f"- {line}" for line in self.curated)),
        ]
        for title, rows in sections:
            rows = list(rows)
            if rows:
                lines += [f"## {title}", "", *rows, ""]
        return "\n".join(lines)


def ingest(cfg: Config, path: Path) -> Report:
    """Check ``output.json`` of the job in *path* and merge what passes.

    Writes ``ingest-report.md`` and returns the report.
    """
    job = load_job(path)
    all_kinds = kinds()
    if job.kind not in all_kinds:
        raise JobError(f"{path / INPUT}: unknown kind {job.kind!r}")
    try:
        schema = json.loads((path / SCHEMA).read_bytes())
    except (OSError, ValueError) as e:
        raise JobError(f"{path / SCHEMA}: {e}") from None
    check_schema(schema)
    # Not an ingest report: the job stays pending, so make leaves it be.
    if not (path / OUTPUT).is_file():
        raise JobError(f"no {OUTPUT} yet")
    kind = all_kinds[job.kind]
    report = Report(job.name, len(job.items))
    accepted = _accepted(cfg, kind, job, schema, report)
    if accepted:
        report.curated = kind.accept(cfg, job, accepted)
    output.write_file(path / REPORT, report.markdown().encode())
    return report


def _read_output(job: Job) -> object:
    """Return ``output.json`` of *job*; raise JobError if it is not JSON."""
    try:
        return json.loads((job.path / OUTPUT).read_bytes())
    except (OSError, ValueError) as e:
        raise JobError(f"{OUTPUT} is not JSON: {e}") from None


def _accepted(
    cfg: Config, kind: Kind, job: Job, schema: Mapping[str, Any], report: Report
) -> list[Accepted]:
    """Return the accepted items of *job*, filling in *report*."""
    try:
        content = _read_output(job)
        bad = _item_problems(validate(content, schema))
    except JobError as e:
        report.failure = str(e)
        report.missing = [item["id"] for item in job.items]
        return []
    assert isinstance(content, dict)
    inputs = {item["id"]: item for item in job.items}
    seen: set[str] = set()
    accepted = []
    for i, item in enumerate(content["items"]):
        key = item.get("id") if isinstance(item, dict) else None
        label = key if isinstance(key, str) else f"#{i}"
        problems = bad.get(i, [])
        if not problems:
            if key not in inputs:
                problems = ["not an id of input.json"]
            elif key in seen:
                problems = ["id repeated; the first is used"]
            else:
                problems = kind.check(cfg, job, inputs[key], item)
        if isinstance(key, str) and key in inputs:
            seen.add(key)
        if problems:
            report.rejected.setdefault(label, []).extend(problems)
        else:
            accepted.append((inputs[key], item))
    report.accepted = len(accepted)
    report.missing = [key for key in inputs if key not in seen]
    return accepted


def _item_problems(problems: Iterable[Problem]) -> dict[int, list[str]]:
    """Return item index → its schema problems; raise JobError for others."""
    bad: dict[int, list[str]] = {}
    for at, message in problems:
        parts = at.split("/")
        if len(parts) <= 2 or parts[1] != "items":  # noqa: PLR2004 - /items/<n>/…
            raise JobError(f"{at or '/'}: {message}")
        where = "/".join(parts[3:])
        bad.setdefault(int(parts[2]), []).append(
            f"{where}: {message}" if where else message
        )
    return bad
