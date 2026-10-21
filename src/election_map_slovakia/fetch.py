"""Download the official inputs into ``data/raw/`` and record them in a manifest.

Each input lands in ``data/raw/<name>/<file>``. A download goes to a temporary
file next to its target and only replaces the previous file after passing its
integrity check, so a failed or corrupt download never destroys a good copy.
``data/raw/manifest.json`` records what is on disk: URL, sha256, size, when it
was retrieved, and the server's validators for the next conditional request.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from election_map_slovakia import __version__, progress
from election_map_slovakia.config import Input, Inputs
from election_map_slovakia.output import format_size

MANIFEST_FILE = "manifest.json"
# Seconds a connection may stall before the download is abandoned; the
# largest input is a few hundred MB, so a whole-transfer limit would not fit.
TIMEOUT = 60
# A larger share of vanished address rows means a broken bulk dump, which has
# happened before, not a real change.
MAX_ROW_DROP = 0.01
_CHUNK = 1 << 20
_XLSX_SHEETS = "xl/worksheets/"
_XLSX_ROW = re.compile(rb"<row[\s>/]")


class FetchError(Exception):
    """One input could not be downloaded or failed its integrity check."""


class ManifestError(Exception):
    """``manifest.json`` exists but cannot be read."""


@dataclass(frozen=True)
class Outcome:
    """What fetching one input did."""

    name: str
    status: str  # new, updated, unchanged or failed
    bytes: int
    detail: str


def user_agent(contact: str) -> str:
    """Return the User-Agent that names the project and a contact."""
    return f"election-map-slovakia/{__version__} (+{contact})"


def ssl_context(ca_certificates: Sequence[Path]) -> ssl.SSLContext:
    """Return the system TLS context extended with *ca_certificates*."""
    context = ssl.create_default_context()
    for cert in ca_certificates:
        context.load_verify_locations(cafile=cert)
    return context


def fetch(
    inputs: Inputs,
    raw_dir: Path,
    *,
    only: Sequence[str] = (),
    force: bool = False,
) -> Iterator[Outcome]:
    """Fetch the inputs named in *only* (default: all), yielding each outcome.

    *force* skips the conditional request and accepts a drop in row count.
    The manifest is rewritten after every input, so an interrupted run keeps
    what it already fetched.
    """
    manifest_path = raw_dir / MANIFEST_FILE
    manifest = load_manifest(manifest_path)
    configured = {inp.name for inp in inputs.inputs}
    manifest = {name: e for name, e in manifest.items() if name in configured}
    context = ssl_context(inputs.ca_certificates)
    agent = user_agent(inputs.contact)
    for inp in inputs.inputs:
        if only and inp.name not in only:
            continue
        previous = manifest.get(inp.name)
        with progress.stage(f"fetching {inp.name}"):
            try:
                outcome, entry = _fetch_one(
                    inp, raw_dir, previous, force, context, agent
                )
            except FetchError as e:
                outcome = Outcome(inp.name, "failed", 0, str(e))
            else:
                manifest[inp.name] = entry
                _write_json(manifest_path, {"inputs": manifest})
        yield outcome


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Return the entries of the manifest at *path*, or none if it is absent."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ManifestError(f"{path}: cannot read: {e}") from e
    entries = data.get("inputs") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        raise ManifestError(f"{path}: no 'inputs' table")
    return entries


def _fetch_one(
    inp: Input,
    raw_dir: Path,
    previous: dict[str, Any] | None,
    force: bool,
    context: ssl.SSLContext,
    agent: str,
) -> tuple[Outcome, dict[str, Any]]:
    target = raw_dir / inp.name / inp.file
    # The previous download only counts if it is the same resource and still
    # on disk as recorded.
    if not (
        previous is not None
        and previous.get("url") == inp.url
        and previous.get("path") == f"{inp.name}/{inp.file}"
        and target.is_file()
        and target.stat().st_size == previous.get("bytes")
    ):
        previous = None
    headers = {"User-Agent": agent}
    if previous is not None and not force:
        if previous.get("etag"):
            headers["If-None-Match"] = previous["etag"]
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = previous["last_modified"]
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    request = urllib.request.Request(inp.url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=TIMEOUT, context=context)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == http.client.NOT_MODIFIED and previous is not None:
            entry = {**previous, "checked_at": now}
            return _unchanged(inp, entry, "not modified"), entry
        raise FetchError(f"HTTP {e.code} {e.reason}") from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"cannot connect: {e}") from e

    target.parent.mkdir(parents=True, exist_ok=True)
    with response:
        validators = {
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }
        tmp, sha256, size = _download(response, target, inp.sha256)
    try:
        with progress.stage(f"checking {inp.file}"):
            stats = check(inp, tmp)
        if previous is not None and (
            sha256 == previous["sha256"] or _same_content(inp, tmp, target)
        ):
            # What is on disk stays, so the manifest keeps describing it.
            entry = {**previous, **validators, "checked_at": now}
            return _unchanged(inp, entry, "same content"), entry
        old_rows = previous.get("rows") if previous is not None else None
        rows = stats.get("rows")
        if (
            inp.kind == "csv"
            and not force
            and old_rows
            and rows is not None
            and rows < old_rows * (1 - MAX_ROW_DROP)
        ):
            raise FetchError(
                f"{rows:,} rows, down from {old_rows:,} (more than"
                f" {MAX_ROW_DROP:.0%}); kept the previous file, --force accepts it"
            )
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    entry = {
        "url": inp.url,
        "path": f"{inp.name}/{inp.file}",
        "sha256": sha256,
        "bytes": size,
        "retrieved_at": now,
        "checked_at": now,
        **validators,
        **stats,
    }
    detail = _rows_detail(rows, old_rows)
    return Outcome(
        inp.name, "new" if previous is None else "updated", size, detail
    ), entry


def _download(
    response: http.client.HTTPResponse, target: Path, pinned: str
) -> tuple[Path, str, int]:
    """Stream *response* into a temporary file beside *target*.

    Fails unless its sha256 is *pinned*, if that is set.
    """
    digest = hashlib.sha256()
    size = 0
    expected = response.headers.get("Content-Length")
    total = int(expected) if expected is not None and expected.isdigit() else None
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    tmp = Path(name)
    try:
        with (
            progress.stage(f"downloading {target.name}", total, format_size) as s,
            os.fdopen(fd, "wb") as f,
        ):
            while chunk := response.read(_CHUNK):
                f.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                s.update(size)
    except (OSError, http.client.HTTPException) as e:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"download interrupted: {e}") from e
    if total is not None and total != size:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"truncated: got {size:,} of {total:,} bytes")
    if pinned and digest.hexdigest() != pinned:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"sha256 {digest.hexdigest()}, but {pinned} is pinned")
    return tmp, digest.hexdigest(), size


def check(inp: Input, path: Path) -> dict[str, int]:
    """Check the downloaded *path* according to its kind; return its statistics.

    Raises :class:`FetchError` if the file is not what *inp* promises.
    """
    if inp.kind == "csv":
        return {"rows": _check_csv(inp, path)}
    if inp.kind == "xlsx":
        return {"rows": _check_xlsx(path)}
    if inp.kind == "zip":
        _check_zip(inp, path)
    elif inp.kind == "pdf":
        with path.open("rb") as f:
            if f.read(4) != b"%PDF":
                raise FetchError("not a PDF")
    elif inp.kind == "html":
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise FetchError(f"not UTF-8: {e}") from e
        if inp.expect not in text:
            raise FetchError(f"page does not contain {inp.expect!r}")
    elif inp.kind == "geojson":
        _check_geojson(path)
    return {}


def _check_geojson(path: Path) -> None:
    try:
        data = json.loads(path.read_bytes())
    except ValueError as e:
        raise FetchError(f"not JSON: {e}") from e
    if not (
        isinstance(data, dict)
        and data.get("type") == "FeatureCollection"
        and isinstance(data.get("features"), list)
        and data["features"]
    ):
        raise FetchError("not a GeoJSON FeatureCollection with features")


def _check_csv(inp: Input, path: Path) -> int:
    """Return the number of data rows (lines after the header)."""
    lines = 0
    last = b"\n"
    with path.open("rb") as f:
        header = f.readline()
        f.seek(0)
        while chunk := f.read(_CHUNK):
            lines += chunk.count(b"\n")
            last = chunk[-1:]
    if last != b"\n":
        lines += 1
    try:
        first = header.decode("utf-8-sig").rstrip("\r\n")
    except UnicodeDecodeError as e:
        raise FetchError(f"header is not UTF-8: {e}") from e
    if not first.startswith(inp.expect):
        raise FetchError(f"unexpected header {first[:120]!r}")
    return max(lines - 1, 0)


def _check_xlsx(path: Path) -> int:
    """Return the number of rows in all worksheets."""
    try:
        with zipfile.ZipFile(path) as z:
            sheets = [
                n
                for n in z.namelist()
                if n.startswith(_XLSX_SHEETS) and n.endswith(".xml")
            ]
            if not sheets:
                raise FetchError(f"no {_XLSX_SHEETS} in the workbook")
            rows = 0
            for sheet in sheets:
                rows += len(_XLSX_ROW.findall(z.read(sheet)))
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
        raise FetchError(f"not a valid XLSX: {e}") from e
    return rows


def _check_zip(inp: Input, path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            missing = sorted(set(inp.members) - set(z.namelist()))
            if missing:
                raise FetchError(f"zip lacks {', '.join(missing)}")
            # Reads every member: a CRC mismatch means a corrupt transfer.
            bad = z.testzip()
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
        raise FetchError(f"not a valid zip: {e}") from e
    if bad is not None:
        raise FetchError(f"corrupt zip member {bad}")


def _same_content(inp: Input, new: Path, old: Path) -> bool:
    """Return whether *new* equals *old* once the volatile parts are removed."""
    if inp.volatile is None:
        return False
    return inp.volatile.sub(b"", new.read_bytes()) == inp.volatile.sub(
        b"", old.read_bytes()
    )


def _unchanged(inp: Input, entry: dict[str, Any], how: str) -> Outcome:
    rows = _rows_detail(entry.get("rows"), None)
    detail = f"{how}, {rows}" if rows else how
    return Outcome(inp.name, "unchanged", entry["bytes"], detail)


def _rows_detail(rows: int | None, old_rows: int | None) -> str:
    if rows is None:
        return ""
    if old_rows is None or old_rows == rows:
        return f"{rows:,} rows"
    return f"{rows:,} rows (was {old_rows:,})"


def _write_json(path: Path, data: object) -> None:
    """Write *data* to *path* atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
