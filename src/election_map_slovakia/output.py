"""Write pipeline output and measure it.

A step that writes a directory builds it beside the old one and swaps it in
only once it is complete (:func:`replacing`), or changes it in place under
another name (:func:`updating`), so a failed or interrupted run never
leaves a half-written directory where the next step reads. Nothing writes
into an existing file: a file is replaced whole, so that a hard link to it
(``build`` links ``dist/`` to ``data/build/``) keeps what it was.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import deflate
import orjson

from election_map_slovakia import progress

GZIP_MEMO_DIR = "gzip-sizes"
"""Below the build directory: the gzip sizes each step measured last
(:func:`gzip_sizes`), one file per step."""
GZIP = f"libdeflate -9 (deflate {deflate.__version__})"
"""What :func:`gzip_size` measures with: the sizes of a memo made with
another are measured again."""


def to_json(content: object, *, sort_keys: bool = False) -> bytes:
    """Return *content* as compact UTF-8 JSON."""
    return json.dumps(
        content, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys
    ).encode()


def write_file(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


@contextmanager
def replacing(directory: Path) -> Generator[Path]:
    """Yield an empty directory that replaces *directory* when the block ends.

    If the block raises, *directory* stays as it was.
    """
    tmp = directory.with_name(directory.name + ".part")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    yield tmp
    if directory.exists():
        with progress.stage(f"removing the previous {directory.name}/"):
            shutil.rmtree(directory)
    tmp.replace(directory)


@contextmanager
def updating(directory: Path) -> Generator[Path]:
    """Yield *directory* to be changed in place; empty if there is none.

    While the block runs it is ``<name>.part``, renamed back when it ends;
    if the block raises, *directory* is missing until a later call
    completes, which takes up the ``.part`` as it was left. Where most of
    the content stays, this spares writing it all again (:func:`replacing`).
    """
    tmp = directory.with_name(directory.name + ".part")
    if directory.exists():
        if tmp.exists():
            shutil.rmtree(tmp)  # left by replacing(), which *directory* outlived
        directory.replace(tmp)
    else:
        tmp.mkdir(parents=True, exist_ok=True)
    yield tmp
    tmp.replace(directory)


def gzip_size(data: bytes) -> int:
    """Return the size of *data* gzipped by libdeflate at level 9 (:data:`GZIP`).

    Not zlib's ``gzip -9``: on 2026's bundles (200 MB) libdeflate took
    10 CPU-s where zlib took 36, for 2.7 % fewer bytes. The sizes are only
    reported, for what a server sends gzipped.
    """
    return len(deflate.gzip_compress(data, 9))


def gzip_sizes(blobs: Sequence[bytes], memo: Path | None = None) -> list[int]:
    """Return :func:`gzip_size` of each of *blobs*, in order.

    libdeflate releases the GIL, so threads compress the files of a whole
    site several times faster than one. *memo*, a JSON file, keeps the sizes
    of the last call by the SHA-256 of each content, so that only contents
    not seen then are compressed: from one build to the next nearly all of
    the site's 2.6 GB are the same. Sizes measured with another compressor
    than :data:`GZIP` are not taken.
    """
    with ThreadPoolExecutor() as pool:
        digests = list(pool.map(lambda b: hashlib.sha256(b).hexdigest(), blobs))
    return gzip_sizes_by_digest(digests, blobs.__getitem__, memo)


def gzip_sizes_by_digest(
    digests: Sequence[str], content: Callable[[int], bytes], memo: Path | None
) -> list[int]:
    """Return :func:`gzip_size` of each content of SHA-256 *digests*, in order.

    As :func:`gzip_sizes`, for contents whose digests are known already:
    ``content(i)`` returns the *i*-th, asked only of those *memo* lacks.
    """
    known: dict[str, int] = {}
    if memo is not None:
        try:
            kept = orjson.loads(memo.read_bytes())
            if kept["compressor"] == GZIP:
                known = kept["sizes"]
        except (OSError, ValueError, TypeError, KeyError):
            pass  # none yet, broken or of another compressor: measured again
    missing = sorted({d: i for i, d in enumerate(digests) if d not in known}.items())
    with (
        ThreadPoolExecutor() as pool,
        progress.stage("measuring the gzip sizes", len(missing)) as s,
    ):
        measured = s.track(
            pool.map(lambda i: gzip_size(content(i)), (i for _, i in missing))
        )
        known |= dict(zip((d for d, _ in missing), measured, strict=True))
    if memo is not None:
        sizes = {d: known[d] for d in sorted(set(digests))}
        write_file(memo, to_json({"compressor": GZIP, "sizes": sizes}))
    return [known[d] for d in digests]


def format_size(size: int) -> str:
    """Return *size* in bytes as a short human-readable string."""
    if size < 1 << 10:
        return f"{size} B"
    if size < 1 << 20:
        return f"{size / (1 << 10):.1f} KiB"
    return f"{size / (1 << 20):.1f} MiB"
