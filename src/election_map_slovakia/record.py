"""The output record ``data/outputs.toml``: what each step made of which inputs.

A step's stamp (:mod:`election_map_slovakia.stamp`) is of this machine:
after a pull of a commit that changes a step's code, every machine would
run the step again, though the change may leave its output as it was.
The record, committed, keeps for each step and election (for ``basemap``
each extract) the digest of its inputs (:attr:`Entry.inputs`) and of the
output the step made of them (:attr:`Entry.outputs`), so that ``ems
make`` skips a step whose inputs are those recorded and whose output on
disk is the one recorded, whoever ran it: the step that ran wrote its
entry, which is committed with the change.

Only the CLI writes it: a step that ran writes its entry where the inputs
are new (:func:`update`); where they are those recorded but the output
is not, it is a warning, the entry staying as it was. ``ems record
check`` (CI) computes every step's inputs from the commit alone, with the
digests of the upstream outputs as recorded, and fails where they are not
those recorded, naming the parts that differ (:attr:`Entry.parts`).
"""

from __future__ import annotations

import tomllib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from election_map_slovakia import output, stamp
from election_map_slovakia.config import ConfigError

RECORD_FILE = Path("data") / "outputs.toml"
"""Relative to the project root."""
PART_DIGITS = 16
"""Hex digits of the digest of each part of the inputs: enough to tell
which part differs, the whole being :attr:`Entry.inputs`."""

Key = tuple[str, str]
"""A step and its election's day, or extract."""


class RecordError(ConfigError):
    """The record is broken, or lacks an entry a step's inputs need."""


@dataclass(frozen=True)
class Entry:
    """What one step made of one election (or extract), and of which inputs."""

    inputs: str
    """The digest of its inputs (:attr:`election_map_slovakia.stamp.Stamp.digest`)."""
    outputs: str
    """The digest of its output (:func:`election_map_slovakia.stamp.outputs_digest`)."""
    parts: dict[str, str]
    """Each part of the inputs (:data:`election_map_slovakia.stamp.PARTS`) by
    the first :data:`PART_DIGITS` hex digits of its digest, Python by its
    version."""


def entry(inputs: Mapping[str, Any], outputs: str) -> Entry:
    """Return the entry of a step of *inputs* (by part) and output digest *outputs*."""
    parts = {
        part: value if part == "python" else stamp.json_digest(value)[:PART_DIGITS]
        for part, value in inputs.items()
        if value
    }
    return Entry(stamp.json_digest(inputs), outputs, parts)


def differing(recorded: Entry, current: Entry) -> list[str]:
    """Return the parts of the inputs of *current* that are not those *recorded*."""
    names = sorted(recorded.parts.keys() | current.parts.keys())
    return [n for n in names if recorded.parts.get(n) != current.parts.get(n)]


def read(path: Path) -> dict[Key, Entry]:
    """Return the entries of the record *path*; none if it is absent."""
    try:
        content = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise RecordError(f"{path}: broken: {e}") from e
    try:
        return {
            (step, key): Entry(e["inputs"], e["outputs"], dict(e["parts"]))
            for step, entries in content.items()
            for key, e in entries.items()
        }
    except (KeyError, TypeError, AttributeError) as e:
        raise RecordError(f"{path}: broken: {e!r}") from e


def render(entries: Mapping[Key, Entry]) -> str:
    """Return the text of :data:`RECORD_FILE` for *entries*, sorted."""
    lines = [
        "# What each step of `ems make` made, of which inputs, for each election",
        "# (src/election_map_slovakia/record.py), written by the steps; do not",
        "# edit. `ems make` skips a step whose inputs are those recorded and",
        "# whose output on disk is the one recorded; CI fails when the inputs",
        "# are not those of the commit (`ems record check`).",
    ]
    for (step, key), e in sorted(entries.items()):
        parts = ", ".join(
            f'{name} = "{value}"' for name, value in sorted(e.parts.items())
        )
        lines += [
            "",
            f'[{step}."{key}"]',
            f'inputs = "{e.inputs}"',
            f'outputs = "{e.outputs}"',
            f"parts = {{ {parts} }}",
        ]
    return "\n".join(lines) + "\n"


def update(path: Path, key: Key, new: Entry, keep: Collection[Key]) -> None:
    """Set the entry of *key* in the record *path* to *new*.

    The entries of steps and elections not in *keep* (an election no longer
    configured) go: those of the others are what a run reads.
    """
    entries = {k: e for k, e in read(path).items() if k in keep} | {key: new}
    output.write_file(path, render(entries).encode())
