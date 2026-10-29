"""Download the official inputs into ``data/raw/`` and record them in a manifest.

Each input lands in ``data/raw/<name>/<file>``. A download goes to a temporary
file next to its target and only replaces the previous file after passing its
integrity check, so a failed or corrupt download never destroys a good copy.
``data/raw/manifest.json`` records what is on disk: URL, sha256, size, when it
was retrieved, and the server's validators for the next conditional request.

A pinned input (its sha256 fixed in the config) is taken from the disk if
the manifest records it there with that digest, else from the input store
(``inputs.toml`` ``store``, a GitHub release holding every pinned file),
else from its source: a release thus depends neither on the sources being
up nor on their serving what they served when the input was pinned.
:func:`update` downloads an input from its source whatever its pin, for
``ems inputs update`` to pin what it got.

A RAR input's one member is unpacked beside it, ``data/raw/<name>/<member>``
(:func:`member_path`), for the steps to read: Python reads no RAR, so
``bsdtar`` (libarchive; Debian and Ubuntu package ``libarchive-tools``)
streams it out.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from election_map_slovakia import __version__, progress
from election_map_slovakia.config import Input, Inputs, Store
from election_map_slovakia.output import format_size

MANIFEST_FILE = "manifest.json"
# Seconds a connection may stall before the download is abandoned; the
# largest input is a few hundred MB, so a whole-transfer limit would not fit.
TIMEOUT = 60
# A larger share of vanished address rows means a broken bulk dump, which has
# happened before, not a real change.
MAX_ROW_DROP = 0.01
_CHUNK = 1 << 20
BSDTAR = "bsdtar"
"""The program that lists and unpacks RAR inputs (libarchive)."""
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

    *force* skips the conditional request and accepts a drop in row count
    (of an input not pinned). The manifest is rewritten after every input,
    so an interrupted run keeps what it already fetched.
    """
    manifest = _Manifest(raw_dir)
    context = ssl_context(inputs.ca_certificates)
    agent = user_agent(inputs.contact)
    for inp in inputs.inputs:
        if only and inp.name not in only:
            continue
        previous = manifest.entries.get(inp.name)
        with progress.stage(f"fetching {inp.name}"):
            try:
                if inp.sha256:
                    outcome, entry = _fetch_pinned(
                        inp, raw_dir, previous, inputs.store, context, agent
                    )
                else:
                    outcome, entry = _fetch_one(
                        inp, raw_dir, previous, force, context, agent
                    )
                if inp.kind == "rar":
                    unpack(inp, raw_dir / inp.name / inp.file)
            except FetchError as e:
                outcome = Outcome(inp.name, "failed", 0, str(e))
            else:
                manifest.record(inp.name, entry)
        yield outcome


def update(
    inputs: Inputs, raw_dir: Path, inp: Input, *, force: bool = False
) -> tuple[Outcome, dict[str, Any]]:
    """Download *inp* from its source whatever its pin; return what it did.

    Like an input without a pin: the file on disk is kept where the server
    reports it unchanged or sends the same content, and a CSV may not lose
    rows unless *force*. The manifest entry returned describes the file now
    on disk, whose digest becomes the pin. Raises :class:`FetchError`.
    """
    manifest = _Manifest(raw_dir)
    unpinned = dataclasses.replace(inp, sha256="", retrieved=None)
    with progress.stage(f"downloading {inp.name} from its source"):
        outcome, entry = _fetch_one(
            unpinned,
            raw_dir,
            manifest.entries.get(inp.name),
            force,
            ssl_context(inputs.ca_certificates),
            user_agent(inputs.contact),
        )
        if inp.kind == "rar":
            unpack(inp, raw_dir / inp.name / inp.file)
    manifest.record(inp.name, entry)
    return outcome, entry


class _Manifest:
    """``data/raw/manifest.json``: what is on disk, by input name."""

    def __init__(self, raw_dir: Path) -> None:
        self.path = raw_dir / MANIFEST_FILE
        self.entries = load_manifest(self.path)

    def record(self, name: str, entry: dict[str, Any]) -> None:
        """Record *entry* for input *name* and write the manifest."""
        self.entries[name] = entry
        _write_json(self.path, {"inputs": self.entries})


def member_path(raw_dir: Path, inp: Input) -> Path:
    """Return the file a step reads of *inp*: its download, a RAR's member."""
    directory = raw_dir / inp.name
    return directory / (inp.members[0] if inp.kind == "rar" else inp.file)


def unpack(inp: Input, path: Path) -> None:
    """Unpack the member of the RAR input *inp* at *path* beside it.

    Unless it is there already, unpacked since the RAR last changed. The
    member goes to a temporary file first and replaces the previous one
    only once its header passed the check, as a download does.
    """
    member = path.parent / inp.members[0]
    if member.is_file() and member.stat().st_mtime >= path.stat().st_mtime:
        return
    fd, tmp = _temp_file(member)
    try:
        with progress.stage(f"unpacking {member.name}"), os.fdopen(fd, "wb") as f:
            done = _bsdtar(["-xOf", str(path), inp.members[0]], f)
        if done.returncode:
            raise FetchError(f"cannot unpack {inp.members[0]}: {done.stderr.strip()}")
        if inp.expect:
            _check_csv(inp, tmp)
        os.replace(tmp, member)
    finally:
        tmp.unlink(missing_ok=True)


def _bsdtar(
    args: list[str], stdout: Any = subprocess.PIPE
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [BSDTAR, *args],
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise FetchError(
            f"{BSDTAR} not found: RAR inputs need libarchive's bsdtar"
            " (package libarchive-tools)"
        ) from None


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


def _fetch_pinned(
    inp: Input,
    raw_dir: Path,
    previous: dict[str, Any] | None,
    store: Store | None,
    context: ssl.SSLContext,
    agent: str,
) -> tuple[Outcome, dict[str, Any]]:
    """Fetch pinned *inp*: from the disk, else the store, else its source.

    Its content is fixed, so the store's copy is what the source sent, and
    neither is asked while the disk holds it: as the manifest records it,
    or, where the manifest does not, as its digest proves it (a file
    copied in by hand, ``ems fetch`` run elsewhere).
    """
    target = raw_dir / inp.name / inp.file
    if (
        previous is not None
        and _on_disk(inp, previous, target)
        and previous["sha256"] == inp.sha256
    ):
        return _unchanged(inp, previous, "on disk"), previous
    if target.is_file() and _digest(target) == inp.sha256:
        with progress.stage(f"checking {inp.file}"):
            stats = check(inp, target)
        now = _now()
        entry = {
            "url": inp.url,
            "path": _manifest_path(inp),
            "sha256": inp.sha256,
            "bytes": target.stat().st_size,
            "retrieved_at": now,
            "checked_at": now,
            **stats,
        }
        status = "new" if previous is None else "updated"
        return Outcome(inp.name, status, entry["bytes"], "found on disk"), entry
    places = [("the store", store.url(inp))] if store is not None else []
    places.append(("the source", inp.url))
    problems = []
    for place, url in places:
        try:
            size, stats = _install(inp, url, target, agent, context)
        except FetchError as e:
            problems.append(f"{place}: {e}")
            continue
        now = _now()
        # No validators: the store's would not describe the source's file.
        entry = {
            "url": inp.url,
            "path": _manifest_path(inp),
            "sha256": inp.sha256,
            "bytes": size,
            "retrieved_at": now,
            "checked_at": now,
            **stats,
        }
        status = "new" if previous is None else "updated"
        return Outcome(inp.name, status, size, f"from {place}"), entry
    raise FetchError("; ".join(problems))


def _install(
    inp: Input, url: str, target: Path, agent: str, context: ssl.SSLContext
) -> tuple[int, dict[str, int]]:
    """Download pinned *inp* from *url* to *target*; return its size and statistics.

    Nothing replaces *target* unless the download has the pinned digest and
    passes its check.
    """
    response = _open(url, {"User-Agent": agent}, context)
    target.parent.mkdir(parents=True, exist_ok=True)
    with response:
        tmp, _, size = _download(response, target, inp.sha256)
    try:
        with progress.stage(f"checking {inp.file}"):
            stats = check(inp, tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return size, stats


def _open(
    url: str, headers: dict[str, str], context: ssl.SSLContext
) -> http.client.HTTPResponse:
    """Return the response to a GET of *url*; raise :class:`FetchError`."""
    request = urllib.request.Request(url, headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=TIMEOUT, context=context)
    except urllib.error.HTTPError as e:
        e.close()
        raise FetchError(f"HTTP {e.code} {e.reason}") from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"cannot connect: {e}") from e


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _fetch_one(
    inp: Input,
    raw_dir: Path,
    previous: dict[str, Any] | None,
    force: bool,
    context: ssl.SSLContext,
    agent: str,
) -> tuple[Outcome, dict[str, Any]]:
    """Fetch *inp*, which has no pin, from its source."""
    target = raw_dir / inp.name / inp.file
    if previous is not None and not _on_disk(inp, previous, target):
        previous = None
    headers = {"User-Agent": agent}
    if previous is not None and not force:
        headers |= _conditional(previous)
    now = _now()

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
        tmp, sha256, size = _download(response, target, "")
    old_rows = previous.get("rows") if previous is not None else None
    try:
        with progress.stage(f"checking {inp.file}"):
            stats = check(inp, tmp)
        if previous is not None and (
            sha256 == previous["sha256"] or _same_content(inp, tmp, target)
        ):
            # What is on disk stays, so the manifest keeps describing it.
            entry = {**previous, **validators, "checked_at": now}
            return _unchanged(inp, entry, "same content"), entry
        if inp.kind == "csv" and not force:
            _check_row_drop(stats.get("rows"), old_rows)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    entry = {
        "url": inp.url,
        "path": _manifest_path(inp),
        "sha256": sha256,
        "bytes": size,
        "retrieved_at": now,
        "checked_at": now,
        **validators,
        **stats,
    }
    status = "new" if previous is None else "updated"
    detail = _rows_detail(stats.get("rows"), old_rows)
    return Outcome(inp.name, status, size, detail), entry


def _manifest_path(inp: Input) -> str:
    """Return where *inp* lands, relative to ``data/raw/``."""
    return f"{inp.name}/{inp.file}"


def _on_disk(inp: Input, previous: dict[str, Any], target: Path) -> bool:
    """Return whether *previous* records *inp* as it is still on disk."""
    return (
        previous.get("url") == inp.url
        and previous.get("path") == _manifest_path(inp)
        and target.is_file()
        and target.stat().st_size == previous.get("bytes")
    )


def _digest(path: Path) -> str:
    """Return the sha256 of the content of *path*."""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _conditional(previous: dict[str, Any]) -> dict[str, str]:
    """Return the headers asking for the file only if it changed since *previous*."""
    headers = {}
    if previous.get("etag"):
        headers["If-None-Match"] = previous["etag"]
    if previous.get("last_modified"):
        headers["If-Modified-Since"] = previous["last_modified"]
    return headers


def _check_row_drop(rows: int | None, old_rows: int | None) -> None:
    """Raise if *rows* fell more than :data:`MAX_ROW_DROP` below *old_rows*."""
    if old_rows and rows is not None and rows < old_rows * (1 - MAX_ROW_DROP):
        raise FetchError(
            f"{rows:,} rows, down from {old_rows:,} (more than"
            f" {MAX_ROW_DROP:.0%}); kept the previous file, --force accepts it"
        )


def _temp_file(target: Path) -> tuple[int, Path]:
    """Create a hidden temporary file beside *target*; return its fd and path.

    Beside it, so that ``os.replace`` moves it into place atomically.
    """
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    return fd, Path(name)


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
    fd, tmp = _temp_file(target)
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
    sha256 = digest.hexdigest()
    if total is not None and total != size:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"truncated: got {size:,} of {total:,} bytes")
    if pinned and sha256 != pinned:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"sha256 {sha256}, but {pinned} is pinned")
    return tmp, sha256, size


def check(inp: Input, path: Path) -> dict[str, int]:
    """Check the downloaded *path* according to its kind; return its statistics.

    Raises :class:`FetchError` if the file is not what *inp* promises.
    """
    if inp.kind == "csv":
        return {"rows": _check_csv(inp, path)}
    if inp.kind == "xlsx":
        return {"rows": _check_xlsx(path)}
    if inp.kind in ("zip", "rar"):
        (_check_zip if inp.kind == "zip" else _check_rar)(inp, path)
    elif inp.kind in _SIGNATURES:
        offset, signature, problem = _SIGNATURES[inp.kind]
        with path.open("rb") as f:
            if f.read(offset + len(signature))[offset:] != signature:
                raise FetchError(problem)
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


_SIGNATURES = {
    "pdf": (0, b"%PDF", "not a PDF"),
    # An OSM PBF file's first BlobHeader, after its 4-byte length: field 1,
    # `type`, the 9-byte string "OSMHeader".
    "pbf": (4, b"\x0a\x09OSMHeader", "not an OSM PBF file (no OSMHeader block first)"),
}
"""Kind → (offset, bytes there, problem otherwise) of the files told by their start."""


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


def _check_rar(inp: Input, path: Path) -> None:
    """Check that *path* is an archive bsdtar reads, with *inp*'s member."""
    listed = _bsdtar(["-tf", str(path)])
    if listed.returncode:
        raise FetchError(f"not a readable RAR: {listed.stderr.strip()}")
    if inp.members[0] not in listed.stdout.splitlines():
        raise FetchError(f"RAR lacks {inp.members[0]}")


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
    fd, tmp = _temp_file(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
