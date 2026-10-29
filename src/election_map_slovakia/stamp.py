"""Skip a pipeline step whose inputs are unchanged since it last succeeded.

A step records in ``data/build/<election day>/<step>.stamp.json``, once its
output is written, a digest of everything that output depends on: the
content of its input files and directories, the configuration values it is
given, and its code (:func:`code_digest`). It runs again when any digest
differs, when an output is missing, or when asked to (``--force``). The
stamp is removed before the step runs, so a step that fails halfway is
never taken as done. Output changed by hand is not noticed; ``--force``
rewrites it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np
import pyproj
import shapely

from election_map_slovakia import output

PACKAGE = Path(__file__).parent
# Pipeline glue (which inputs a step gets, how its output is written) lives
# in the CLI; the package version in __init__.
_ALWAYS = ("__init__", "cli")
# What computes the output besides our code: float formatting and JSON
# (Python), geometry (GEOS), reprojection (PROJ and its database).
_LIBRARIES = (
    sys.version,
    np.__version__,
    shapely.__version__,
    shapely.geos_version_string,
    pyproj.__version__,
    pyproj.proj_version_str,
)


def file_digest(path: Path) -> str:
    """Return the sha256 of the content of *path*."""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def tree_digest(directory: Path) -> str:
    """Return a sha256 over the names and contents of the files in *directory*."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        name = path.relative_to(directory).as_posix()
        digest.update(f"{name}\0{file_digest(path)}\n".encode())
    return digest.hexdigest()


def value_digest(value: object) -> str:
    """Return the sha256 of the ``repr`` of *value* (configuration dataclasses)."""
    return hashlib.sha256(repr(value).encode()).hexdigest()


def code_digest(module: str) -> str:
    """Return a sha256 of the code that computes the output of step *module*.

    That is the source of *module*, of every package module it imports,
    directly or not, of the CLI and the package version, and the versions of
    Python and the libraries.
    """
    digest = hashlib.sha256(repr(_LIBRARIES).encode())
    for name in sorted(modules(module) | set(_ALWAYS)):
        digest.update(f"{name}\0".encode() + (PACKAGE / f"{name}.py").read_bytes())
    return digest.hexdigest()


def modules(module: str) -> set[str]:
    """Return *module* and the package modules it imports, directly or not."""
    seen: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((PACKAGE / f"{name}.py").read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == PACKAGE.name:
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            elif isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            else:
                continue
            names = (path.removeprefix(f"{PACKAGE.name}.") for path in imported)
            # Only package modules have a file here; the rest are libraries.
            todo += [n for n in names if (PACKAGE / f"{n}.py").is_file()]
    return seen


class Stamp:
    """The record of one step's inputs, compared and written by the CLI."""

    def __init__(
        self, path: Path, inputs: Mapping[str, str], outputs: Sequence[Path]
    ) -> None:
        """Describe the step recorded in *path*: input name → digest, outputs."""
        self.path = path
        self.inputs = dict(inputs)
        self.outputs = outputs

    def changes(self) -> list[str]:
        """Return why the step must run: empty if its output is up to date."""
        missing = [f"{path.name} missing" for path in self.outputs if not path.exists()]
        if missing:
            return missing
        try:
            recorded = json.loads(self.path.read_bytes())
        except (OSError, ValueError):
            recorded = None
        if not isinstance(recorded, dict):
            return ["no record of a successful run"]
        names = sorted(recorded.keys() | self.inputs.keys())
        return [
            f"{name} changed"
            for name in names
            if recorded.get(name) != self.inputs.get(name)
        ]

    def forget(self) -> None:
        """Remove the record, before the step changes its output."""
        self.path.unlink(missing_ok=True)

    def record(self) -> None:
        """Record the inputs, once the step has written all its output."""
        data = json.dumps(self.inputs, indent=2, sort_keys=True) + "\n"
        output.write_file(self.path, data.encode())


def inputs(
    root: Path,
    step: str,
    files: Iterable[Path] = (),
    trees: Iterable[Path] = (),
    values: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Return the input digests of *step*; paths are named relative to *root*."""
    digests = {"code": code_digest(step)}
    digests |= {p.relative_to(root).as_posix(): file_digest(p) for p in files}
    digests |= {f"{p.relative_to(root).as_posix()}/": tree_digest(p) for p in trees}
    digests |= {name: value_digest(v) for name, v in (values or {}).items()}
    return digests
