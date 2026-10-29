"""The input store: a GitHub release holding every pinned input file.

The release is named by ``inputs.toml`` ``store``. Each pinned file is an
asset named ``<sha256>-<file>``
(:meth:`config.Store.asset`), uploaded once and never replaced: a new
version of an input is a new asset beside the old one, so every commit
that pins either can still be built. ``ems fetch`` downloads them by their
public URL, without logging in (:mod:`election_map_slovakia.fetch`);
:func:`publish` uploads those the release lacks with the GitHub CLI
(``gh``), as its logged-in user, creating the release first where there
is none. :func:`write_pin` records a new pin in
``inputs.toml``, as ``ems inputs update`` does after downloading an input
from its source.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

from election_map_slovakia import stamp
from election_map_slovakia.config import Input, Inputs, Store

GH = "gh"
"""The GitHub CLI, which uploads the assets."""
TITLE = "Raw inputs"
NOTES = (
    "The pinned raw input files of config/inputs.toml, each named by its"
    " sha256 and never replaced (docs/deploy.md, The input store)."
)
"""The title and notes of the release, where :func:`publish` creates it."""
_KEY = re.compile(r"[A-Za-z0-9_-]+\s*=")
_TABLE = re.compile(r"\s*\[")


class StoreError(Exception):
    """The store cannot be read or written, or a file is not the pinned one."""


def release(store: Store) -> bool | None:
    """Return whether the store's release is published; None if there is none.

    A draft is not: its assets are not public.
    """
    out = _gh(
        "release",
        "list",
        "--repo",
        store.repository,
        "--limit",
        "1000",
        "--json",
        "tagName,isDraft",
    )
    for r in json.loads(out or "[]"):
        if r["tagName"] == store.release:
            return not r["isDraft"]
    return None


def assets(store: Store) -> set[str]:
    """Return the names of the assets of the store's release."""
    out = _gh(
        "release",
        "view",
        store.release,
        "--repo",
        store.repository,
        "--json",
        "assets",
        "--jq",
        ".assets[].name",
    )
    return set(out.split())


def missing(store: Store, inputs: Sequence[Input], present: set[str]) -> list[Input]:
    """Return the pinned *inputs* whose file is not among the assets *present*."""
    return [inp for inp in inputs if inp.sha256 and store.asset(inp) not in present]


def publish(inputs: Inputs, raw_dir: Path) -> Iterator[Input]:
    """Upload every pinned file the store lacks; yield each input once done.

    The file is ``data/raw/<name>/<file>``, which must have the pinned
    digest: ``ems fetch`` puts it there, ``ems inputs update`` downloads it.
    Nothing already in the store is uploaded again or replaced. Where the
    release does not exist yet, it is created, once every file to upload
    is found to be the pinned one: a pre-release, so that it never shows
    as the repository's latest release, published, so that anyone may
    download its assets. Its tag (``inputs``) is no version, so creating it
    deploys nothing (release.yml runs on ``v*``).
    """
    store = inputs.store
    if store is None:
        raise StoreError("config/inputs.toml names no store")
    published = release(store)
    if published is False:
        raise StoreError(
            f"the release {store.release} of {store.repository} is a draft, whose"
            " assets nobody can download without logging in; publish it"
        )
    todo = missing(store, inputs.inputs, assets(store) if published else set())
    for inp in todo:
        path = raw_dir / inp.name / inp.file
        if not path.is_file():
            raise StoreError(f"{path} missing; run `ems fetch --only {inp.name}`")
        if stamp.file_digest(path) != inp.sha256:
            raise StoreError(
                f"{path} is not the pinned file; run `ems fetch --only {inp.name}`"
            )
    if published is None:
        _gh(
            "release",
            "create",
            store.release,
            "--repo",
            store.repository,
            "--prerelease",
            "--title",
            TITLE,
            "--notes",
            NOTES,
        )
    for inp in todo:
        # The GitHub CLI names an asset after the file it uploads.
        with tempfile.TemporaryDirectory(dir=raw_dir, prefix=".publish-") as tmp:
            link = Path(tmp) / store.asset(inp)
            os.symlink((raw_dir / inp.name / inp.file).resolve(), link)
            _gh(
                "release",
                "upload",
                store.release,
                str(link),
                "--repo",
                store.repository,
            )
        yield inp


def write_pin(path: Path, name: str, sha256: str, retrieved: dt.date) -> None:
    """Set ``sha256`` and ``retrieved`` of input *name* in ``inputs.toml`` *path*.

    The file is edited as text, so its comments and layout stay: each line
    is replaced where the input's table has it, else put after the one
    before (``sha256`` after ``kind``, which every input has on one line).
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    header = f"[input.{name}]"
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        raise StoreError(f"{path}: no {header}") from None
    end = next(
        (i for i in range(start + 1, len(lines)) if _TABLE.match(lines[i])),
        len(lines),
    )

    def find(key: str) -> int | None:
        return next(
            (
                i
                for i in range(start + 1, end)
                if _KEY.match(lines[i]) and lines[i].split("=")[0].strip() == key
            ),
            None,
        )

    anchor = find("kind")
    if anchor is None:
        raise StoreError(f"{path}: {header} has no kind")
    for key, value in (("sha256", f'"{sha256}"'), ("retrieved", str(retrieved))):
        at = find(key)
        if at is None:
            at = anchor + 1
            lines.insert(at, "")
            end += 1
        lines[at] = f"{key} = {value}\n"
        anchor = at
    path.write_text("".join(lines), encoding="utf-8")


def _gh(*args: str) -> str:
    """Run the GitHub CLI with *args*; return its output."""
    try:
        done = subprocess.run([GH, *args], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise StoreError(
            f"{GH} not found: the GitHub CLI uploads to the store"
            " (https://cli.github.com/), logged in with `gh auth login`"
        ) from None
    if done.returncode:
        raise StoreError(f"{GH} {' '.join(args[:2])}: {done.stderr.strip()}")
    return done.stdout
