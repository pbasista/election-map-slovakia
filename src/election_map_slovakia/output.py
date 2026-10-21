"""Write pipeline output and measure it.

A step that writes a directory builds it beside the old one and swaps it in
only once it is complete (:func:`replacing`), so a failed or interrupted run
never leaves a half-written directory where the next step reads.
"""

from __future__ import annotations

import gzip
import json
import shutil
from collections.abc import Generator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from election_map_slovakia import progress


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


def gzip_size(data: bytes) -> int:
    """Return the size of *data* compressed with ``gzip -9``."""
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def gzip_sizes(blobs: Sequence[bytes]) -> list[int]:
    """Return :func:`gzip_size` of each of *blobs*, in order.

    zlib releases the GIL, so threads compress the files of a whole site
    several times faster than one.
    """
    with (
        progress.stage("measuring the gzip sizes", len(blobs)) as s,
        ThreadPoolExecutor() as pool,
    ):
        return list(s.track(pool.map(gzip_size, blobs)))


def format_size(size: int) -> str:
    """Return *size* in bytes as a short human-readable string."""
    if size < 1 << 10:
        return f"{size} B"
    if size < 1 << 20:
        return f"{size / (1 << 10):.1f} KiB"
    return f"{size / (1 << 20):.1f} MiB"
