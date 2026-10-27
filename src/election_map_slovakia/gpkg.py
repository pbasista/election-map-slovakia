"""Read GeoPackage files (SQLite) with the stdlib and shapely.

ZBGIS ships each level of detail as one ``.gpkg`` inside a zip;
:func:`extract` unpacks it once into ``data/build/``. :class:`GeoPackage`
finds the feature layers and reads their columns; :func:`geometry` decodes
the GeoPackage binary geometry blob of a feature.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import struct
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import TracebackType

import shapely

from election_map_slovakia import progress

# GeoPackage binary header (OGC 12-128r19 §2.1.3): "GP", version, flags,
# int32 srs_id, then an optional envelope of 4, 6, 6 or 8 doubles.
_MAGIC = b"GP"
_HEADER = 8
_FLAG_EXTENDED = 0x20
_FLAG_LITTLE_ENDIAN = 0x01
_ENVELOPE_DOUBLES = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}


class GpkgError(Exception):
    """The GeoPackage is missing, unreadable or lacks an expected layer."""


def _check_header(blob: bytes) -> None:
    if len(blob) < _HEADER or blob[:2] != _MAGIC:
        raise GpkgError("geometry blob lacks the GeoPackage 'GP' header")


def _wkb(blob: bytes) -> bytes:
    """Return the WKB part of a GeoPackage geometry *blob*.

    The envelope size comes from the flags byte; the WKB carries its own
    byte order, so the header's byte-order bit only matters for the header.
    """
    _check_header(blob)
    flags = blob[3]
    if flags & _FLAG_EXTENDED:
        raise GpkgError("extended GeoPackage geometry types are not supported")
    envelope = (flags >> 1) & 0x07
    if envelope not in _ENVELOPE_DOUBLES:
        raise GpkgError(f"geometry blob has invalid envelope code {envelope}")
    start = _HEADER + 8 * _ENVELOPE_DOUBLES[envelope]
    if len(blob) <= start:
        raise GpkgError("geometry blob ends inside its header")
    return blob[start:]


def srs_id(blob: bytes) -> int:
    """Return the spatial reference system id in a geometry *blob*'s header."""
    _check_header(blob)
    order = "<" if blob[3] & _FLAG_LITTLE_ENDIAN else ">"
    return struct.unpack_from(order + "i", blob, 4)[0]


def geometry(blob: bytes) -> shapely.Geometry:
    """Decode a GeoPackage geometry *blob* into a shapely geometry."""
    try:
        return shapely.from_wkb(_wkb(blob))
    except shapely.errors.GEOSException as e:
        raise GpkgError(f"invalid WKB in geometry blob: {e}") from e


def extract(archive: Path, member: str, directory: Path) -> Path:
    """Return *member* of *archive* unpacked into *directory*.

    The copy is reused while its size and modification time match the
    archive, so repeated runs do not unpack a large file again; ``fetch``
    replaces the archive with a new file whenever it changes.
    """
    try:
        with zipfile.ZipFile(archive) as z:
            info = z.getinfo(member)
            target = directory / Path(member).name
            mtime = archive.stat().st_mtime_ns
            st = target.stat() if target.exists() else None
            if st and st.st_size == info.file_size and st.st_mtime_ns == mtime:
                return target
            directory.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            with (
                progress.stage(f"unpacking {member} from {archive.name}"),
                z.open(info) as src,
                tmp.open("wb") as dst,
            ):
                shutil.copyfileobj(src, dst, 1 << 20)
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        raise GpkgError(f"{archive}: cannot extract {member}: {e}") from e
    os.utime(tmp, ns=(mtime, mtime))
    tmp.replace(target)
    return target


class GeoPackage:
    """A read-only GeoPackage; use as a context manager."""

    def __init__(self, path: Path) -> None:
        """Open *path* read-only."""
        if not path.is_file():
            raise GpkgError(f"{path}: no such file")
        self.path = path
        # immutable=1: no locking or journal, the file never changes under us.
        self._db = sqlite3.connect(f"{path.resolve().as_uri()}?immutable=1", uri=True)

    def __enter__(self) -> GeoPackage:
        """Return the open GeoPackage."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the database."""
        self._db.close()

    def _query(self, sql: str, parameters: Sequence[object] = ()) -> list[tuple]:
        try:
            return self._db.execute(sql, parameters).fetchall()
        except sqlite3.Error as e:
            raise GpkgError(f"{self.path}: {e}") from e

    def _layers(self) -> list[str]:
        """Return the names of the feature layers, sorted."""
        return [
            name
            for (name,) in self._query(
                "SELECT table_name FROM gpkg_contents"
                " WHERE data_type = 'features' ORDER BY table_name"
            )
        ]

    def layer(self, prefix: str) -> str:
        """Return the one layer named *prefix* plus a level suffix (``obec_0``)."""
        names = [n for n in self._layers() if n.rsplit("_", 1)[0] == prefix]
        if len(names) != 1:
            raise GpkgError(f"{self.path}: expected one {prefix} layer")
        return names[0]

    def geometry_column(self, layer: str) -> str:
        """Return the name of the geometry column of *layer*."""
        found = self._query(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
            (layer,),
        )
        if not found:
            raise GpkgError(f"{self.path}: layer {layer!r} has no geometry column")
        return found[0][0]

    def rows(self, layer: str, columns: Sequence[str]) -> Iterator[tuple]:
        """Yield the values of *columns* for every feature of *layer*."""
        if layer not in self._layers():
            raise GpkgError(f"{self.path}: no layer {layer!r}")
        available = {
            row[1] for row in self._query(f"PRAGMA table_info({_quote(layer)})")
        }
        missing = [c for c in columns if c not in available]
        if missing:
            raise GpkgError(
                f"{self.path}: layer {layer!r} has no column {missing[0]!r}"
            )
        select = ", ".join(map(_quote, columns))
        try:
            yield from self._db.execute(f"SELECT {select} FROM {_quote(layer)}")
        except sqlite3.Error as e:
            raise GpkgError(f"{self.path}: {layer}: {e}") from e


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
