"""ŠÚ SR's tables of an election, read by table id with named columns.

ŠÚ SR publishes the candidate lists and results of the national elections
(volby.statistics.sk, volbysr.sk) as tables in files named
``<ELECTION><YEAR>[_kolo<n>]_SK_<table>.<csv|xlsx>`` (2019:
``PRE_2019_KOLO<n>_<table>.xlsx``): a CSV file has a header of full Slovak
column names, comma-separated and quoted; an XLSX file has the same columns
below a title and an empty row, and in 2019 another empty row below them;
the regional elections' of 2017 and the municipal ones' of 2018
(``OSK_2017_<table>.xlsx``, ``OSO_2018_<table>.xlsx``) are laid out alike,
some of their headers in two rows.
An input is one such file or a zip of many (the packages to download), and
an election's tables may come from several inputs: :func:`open_package`
finds them all, and a table is read only when asked for. Most are small
enough to hold (:meth:`Package.table`); the preference votes per obec and
okrsok are not (NR SR 2023's ``tab07e`` is 0.8 GB of CSV, ``tab07f`` 1.8
GB), so they are read row by row (:meth:`Package.stream`); the XLSX tables
of NR SR 2020 split them into a worksheet per ballot subject.

Column names are normalised (Excel's ``_x000D_`` and runs of whitespace become
one space) so that a column reads alike in either format. ŠÚ SR words the
same column differently from one table and election to the next, so readers
name a column by its aliases (:meth:`Table.column`); one that is missing
fails naming the table, the columns wanted and the columns found, which is
what a reader for another election needs to be told.
"""

from __future__ import annotations

import codecs
import contextlib
import csv
import datetime as dt
import functools
import io
import itertools
import operator
import re
import zipfile
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from election_map_slovakia import xlsx

_FILE = re.compile(r"_(tab\w+?)\.(csv|xlsx)$", re.IGNORECASE)
_SPACE = re.compile(r"(?:_x000D_|\s)+")
_DELIMITERS = ",;|\t"
# A CSV file of an older election is in the Windows code page.
_ENCODINGS = ("utf-8-sig", "cp1250")
_SNIFF = 1 << 16
"""Bytes of a streamed CSV file its encoding and delimiter are told by."""
_READ_ERRORS = (UnicodeDecodeError, csv.Error, xlsx.XlsxError)
"""What reading the rows of a file may raise: a :class:`TableError` naming it."""


class TableError(Exception):
    """A table is missing, unreadable or lacks a column read from it."""


def normalise(name: str) -> str:
    """Return column name *name* as tables are matched by it."""
    return _SPACE.sub(" ", name).strip()


@dataclass(frozen=True)
class Columns:
    """A table's name and header, by which its columns are found."""

    name: str
    """The file it was read from, for messages."""
    header: tuple[str, ...]

    def column(self, *aliases: str) -> str:
        """Return the first of *aliases* the table has; fail if none."""
        found = self.optional(*aliases)
        if found is None:
            wanted = " | ".join(repr(a) for a in aliases)
            raise TableError(
                f"{self.name}: no column {wanted}; it has {', '.join(self.header)}"
            )
        return found

    def optional(self, *aliases: str) -> str | None:
        """Return the first of *aliases* the table has, or None."""
        return _optional(self.header, aliases)

    def index(self, *aliases: str) -> int:
        """Return the position of the first of *aliases* the table has."""
        return self.header.index(self.column(*aliases))


# Readers look a column up by its aliases row after row.
@functools.cache
def _optional(header: tuple[str, ...], aliases: tuple[str, ...]) -> str | None:
    return next((a for a in map(normalise, aliases) if a in header), None)


@dataclass(frozen=True)
class Table(Columns):
    """One table: its rows as column name → cell text."""

    rows: list[dict[str, str]]


@dataclass(frozen=True)
class Stream(Columns):
    """One table (or a worksheet of it) read row by row.

    Its rows are read once, while the file is open (:meth:`Package.stream`):
    whole (:meth:`rows`) or, faster, only the cells read (:meth:`cells`).
    """

    sheet: str
    """The worksheet's name; empty for a CSV file."""
    below: Iterator[list[str]]
    """The rows below the header, as the file has them."""

    def rows(self) -> Iterator[list[str]]:
        """Yield the data rows: cell texts in the header's order (:func:`_split`)."""
        return _data(self.name, self.below, len(self.header))

    def cells(self, *columns: int) -> Iterator[list[str]]:
        """Yield the cells at positions *columns* of each data row, as :meth:`rows` has them.

        Only those are stripped: the preference tables run to millions of
        rows of 15 cells, 4 of them read.
        """
        return _picked(self.name, self.below, len(self.header), columns)


@dataclass(frozen=True)
class _File:
    """A table's file: a plain one, or a member of a zip."""

    name: str
    path: Path
    member: str | None

    def read(self) -> bytes:
        with self.open() as f:
            return f.read()

    @contextlib.contextmanager
    def open(self) -> Generator[IO[bytes]]:
        try:
            if self.member is None:
                with self.path.open("rb") as f:
                    yield f
            else:
                with zipfile.ZipFile(self.path) as z, z.open(self.member) as f:
                    yield f
        except (OSError, zipfile.BadZipFile) as e:
            raise TableError(f"{self.path}: {e}") from e


@dataclass
class Package:
    """The tables of one election, from one or more inputs."""

    files: dict[str, _File]
    """Table id (``tab03e``) → its file."""
    time: dt.datetime | None
    """The newest time of a file in a zip, None where all are plain files."""
    _parsed: dict[str, Table] = field(default_factory=dict, repr=False)

    def has(self, table: str) -> bool:
        """Return whether the package has table *table*."""
        return table in self.files

    def table(self, table: str) -> Table:
        """Return table *table*; fail if the package lacks it.

        Of an XLSX file with several worksheets, the first.
        """
        if table not in self._parsed:
            f = self._file(table)
            self._parsed[table] = parse(f.name, f.read())
        return self._parsed[table]

    def stream(self, table: str) -> Generator[Stream]:
        """Yield table *table* row by row: of an XLSX file each worksheet's.

        Each stream's rows are read before the next stream is asked for.
        """
        f = self._file(table)
        if f.name.lower().endswith(".xlsx"):
            try:
                for sheet, rows in xlsx.read_sheets(io.BytesIO(f.read())):
                    name = f"{f.name} [{sheet}]"
                    header, below = _split(name, rows)
                    yield Stream(name, header, sheet, below)
            except xlsx.XlsxError as e:
                raise TableError(f"{f.name}: {e}") from e
            return
        with f.open() as raw:
            head = raw.read(_SNIFF)
        encoding = _sniffed_encoding(f.name, head)
        first = head.decode(encoding, errors="replace").partition("\n")[0]
        delimiter = max(_DELIMITERS, key=first.count)
        with f.open() as raw, io.TextIOWrapper(raw, encoding, newline="") as text:
            rows = csv.reader(text, delimiter=delimiter)
            header, below = _split(f.name, rows)
            yield Stream(f.name, header, "", below)

    def _file(self, table: str) -> _File:
        if table not in self.files:
            names = ", ".join(sorted(self.files)) or "none"
            raise TableError(f"no table {table} (the tables found: {names})")
        return self.files[table]


def open_package(paths: Sequence[Path], tz: dt.tzinfo) -> Package:
    """Return the tables of the files, zips and directories *paths*.

    A later path's table replaces an earlier one's of the same id. Times in
    zips are local times, read as *tz*.
    """
    files: dict[str, _File] = {}
    newest: tuple[int, ...] | None = None
    for path in paths:
        for f, stamp in _members(path):
            m = _FILE.search(f.name)
            if m:
                files[m.group(1).lower()] = f
                if stamp is not None and (newest is None or stamp > newest):
                    newest = stamp
    time = None if newest is None else dt.datetime(*newest, tzinfo=tz)
    return Package(files, time)


def _members(path: Path) -> Iterator[tuple[_File, tuple[int, ...] | None]]:
    """Yield each file of *path* and its zip time (None for a plain file)."""
    try:
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    yield from _members(f)
        elif zipfile.is_zipfile(path) and path.suffix.lower() != ".xlsx":
            with zipfile.ZipFile(path) as z:
                infos = [i for i in z.infolist() if not i.is_dir()]
            for info in infos:
                yield _File(info.filename, path, info.filename), info.date_time
        else:
            yield _File(path.name, path, None), None
    except (OSError, zipfile.BadZipFile) as e:
        raise TableError(f"{path}: {e}") from e


def parse(name: str, content: bytes) -> Table:
    """Return the table in file *name* with *content* (CSV or XLSX)."""
    if name.lower().endswith(".xlsx"):
        try:
            rows = list(xlsx.read_rows(io.BytesIO(content)))
        except xlsx.XlsxError as e:
            raise TableError(f"{name}: {e}") from e
        return _table(name, rows)
    text = _decode(name, content)
    lines = text.splitlines()
    first = lines[0] if lines else ""
    delimiter = max(_DELIMITERS, key=first.count)
    return _table(name, list(csv.reader(io.StringIO(text), delimiter=delimiter)))


def dict_rows(text: str, delimiter: str = ",") -> list[dict[str, str]]:
    """Return the rows of CSV *text* by the names in its first row.

    As :class:`csv.DictReader` reads them (empty lines skipped, the missing
    cells of a short row None, the extra cells of a long one a list under
    None), several times faster: a results table has hundreds of thousands
    of rows.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None)
    if header is None:
        return []
    width = len(header)
    out: list[dict[Any, Any]] = []
    for row in reader:
        if len(row) == width and row:
            out.append(dict(zip(header, row)))
        elif row:
            d: dict[Any, Any] = dict(zip(header, row))
            if len(row) > width:
                d[None] = row[width:]
            else:
                d.update(dict.fromkeys(header[len(row) :]))
            out.append(d)
    return out


def _decode(name: str, content: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TableError(f"{name}: neither UTF-8 nor Windows-1250")


def _sniffed_encoding(name: str, head: bytes) -> str:
    """Return the encoding of a CSV file starting with *head*, of :data:`_ENCODINGS`."""
    for encoding in _ENCODINGS:
        try:
            # Not final: *head* may end inside a character.
            codecs.getincrementaldecoder(encoding)().decode(head, final=False)
        except UnicodeDecodeError:
            continue
        return encoding
    raise TableError(f"{name}: neither UTF-8 nor Windows-1250")


def _table(name: str, rows: list[list[str]]) -> Table:
    """Return the table of *rows* (:func:`_split`)."""
    header, below = _split(name, iter(rows))
    data = _data(name, below, len(header))
    return Table(name, header, [dict(zip(header, row, strict=True)) for row in data])


def _split(
    name: str, rows: Iterator[list[str]]
) -> tuple[tuple[str, ...], Iterator[list[str]]]:
    """Return the header of *rows*, the first row of several cells, and the rows below.

    The rows above it are a title; the data (:func:`_data`) start at the
    first row below that is not empty (the XLSX tables of 2019 leave one
    empty below the header) and end at the next empty one, below which XLSX
    tables carry notes. A header of two rows (:func:`_sub_header`) is read
    as one.
    """
    try:
        for row in rows:
            if sum(bool(cell.strip()) for cell in row) > 1:
                header = tuple(normalise(cell) for cell in row)
                break
        else:
            raise TableError(f"{name}: no header row")
        below = next(rows, None)
    except _READ_ERRORS as e:
        raise TableError(f"{name}: {e}") from e
    if below is not None:
        sub = _sub_header(header, below)
        if sub is None:
            rows = itertools.chain([below], rows)
        else:
            header = sub
    return header, rows


def _sub_header(header: tuple[str, ...], row: list[str]) -> tuple[str, ...] | None:
    """Return *header* completed by the row below it, if that is its second row.

    The regional tables of 2017 split a column over merged cells: ``Počet
    platných hlasovacích lístkov odovzdaných pre voľby`` above ``predsedu``
    and, under the empty cell beside it, ``do zastupiteľstva``. Such a row
    starts with an empty cell, as no data row does, and has a cell under an
    empty header cell (or past the header's end); each of its cells is
    joined to the nearest header cell at or left of it.
    """
    if not row or row[0].strip():
        return None
    if not any(
        cell.strip() and (j >= len(header) or not header[j])
        for j, cell in enumerate(row)
    ):
        return None
    out = []
    above = ""
    for j in range(max(len(header), len(row))):
        own = header[j] if j < len(header) else ""
        above = own or above
        sub = normalise(row[j]) if j < len(row) else ""
        out.append(normalise(f"{above} {sub}") if sub else own)
    return tuple(out)


def _data(name: str, rows: Iterator[list[str]], width: int) -> Iterator[list[str]]:
    """Yield the data *rows* below a header of *width* cells (:func:`_split`).

    Stripped and as long as the header.
    """
    started = False
    try:
        for row in rows:
            # Every cell stripped at once: the tables run to millions of rows.
            cells = [cell.strip() for cell in row]
            if not any(cells):
                if started:
                    return
                continue
            started = True
            if len(cells) != width:
                del cells[width:]
                cells += [""] * (width - len(cells))
            yield cells
    except _READ_ERRORS as e:
        raise TableError(f"{name}: {e}") from e


def _picked(
    name: str, rows: Iterator[list[str]], width: int, columns: Sequence[int]
) -> Iterator[list[str]]:
    """Yield the cells *columns* of the data *rows*, as :func:`_data` has them."""
    pick = operator.itemgetter(*columns)
    single = len(columns) == 1
    started = False
    try:
        for row in rows:
            # A row of empty cells, whitespace at most, is blank.
            joined = "".join(row)
            if not joined or joined.isspace():
                if started:
                    return
                continue
            started = True
            if len(row) < width:
                row = row + [""] * (width - len(row))
            yield [pick(row).strip()] if single else [c.strip() for c in pick(row)]
    except _READ_ERRORS as e:
        raise TableError(f"{name}: {e}") from e
