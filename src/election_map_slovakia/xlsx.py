"""Read the first worksheet of an XLSX workbook with the stdlib only.

Supports what the MV SR candidate lists use: shared strings (plain and rich
text), inline strings, numbers, booleans and cached formula results. Every
cell comes back as its text; numbers keep the text Excel stored (``"42"``,
``"0.5"``), dates are not converted. Styles are ignored.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import IO
from xml.etree import ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_CELL_REF = re.compile(r"([A-Z]+)(\d+)")
_LETTERS = 26


class XlsxError(Exception):
    """The workbook is unreadable or not shaped as expected."""


def read_rows(path: Path | IO[bytes]) -> Iterator[list[str]]:
    """Yield the rows of the first worksheet of *path* as lists of strings.

    *path* may also be an open binary file, such as a workbook inside a zip.
    Empty rows inside the sheet are yielded as empty lists, so row positions
    match the sheet. Missing cells within a row are filled with ``""``;
    trailing empty cells are not added.
    """
    try:
        with zipfile.ZipFile(path) as z:
            shared = _shared_strings(z)
            with z.open(_first_sheet(z)) as f:
                yield from _rows(f, shared)
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise XlsxError(f"{path}: {e}") from e


def find_header(
    rows: Iterator[list[str]], first: str
) -> tuple[list[str], Iterator[list[str]]]:
    """Skip the title rows above the header row and return (header, data rows).

    The header row is the first one whose first cell is *first*; MV SR puts
    an election title and a subtitle above it. Data rows end at the first
    empty row, below which the files carry footnotes.
    """
    for row in rows:
        if row and row[0].strip() == first:
            header = [cell.strip() for cell in row]
            return header, _until_empty(rows)
    raise XlsxError(f"no header row starting with {first!r}")


def _until_empty(rows: Iterator[list[str]]) -> Iterator[list[str]]:
    for row in rows:
        if not any(cell.strip() for cell in row):
            return
        yield row


def _first_sheet(z: zipfile.ZipFile) -> str:
    """Return the zip member of the first sheet in workbook order."""
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    sheet = workbook.find(f"{_NS}sheets/{_NS}sheet")
    if sheet is None:
        raise XlsxError("workbook has no sheets")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid = sheet.get(_DOC_REL)
    for rel in rels.iter(f"{_REL_NS}Relationship"):
        if rel.get("Id") == rid:
            target = rel.get("Target", "")
            # Targets are relative to xl/ unless absolute within the package.
            if target.startswith("/"):
                return target[1:]
            return posixpath.normpath(posixpath.join("xl", target))
    raise XlsxError(f"workbook relationship {rid!r} not found")


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        data = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    return [_text(si) for si in ET.fromstring(data).iter(f"{_NS}si")]


def _text(element: ET.Element) -> str:
    """Return the text of a string item, joining rich-text runs.

    Phonetic runs (``rPh``) are annotations, not part of the value.
    """
    plain = element.find(f"{_NS}t")
    if plain is not None:
        return plain.text or ""
    return "".join(t.text or "" for t in element.iterfind(f"{_NS}r/{_NS}t"))


def _rows(f: IO[bytes], shared: Sequence[str]) -> Iterator[list[str]]:
    expected = 1
    for _, row in ET.iterparse(f, events=("end",)):
        if row.tag != f"{_NS}row":
            continue
        number = int(row.get("r", expected))
        # Rows without cells may be omitted from the XML altogether.
        for _ in range(expected, number):
            yield []
        expected = number + 1
        yield _cells(row, shared)
        row.clear()


def _cells(row: ET.Element, shared: Sequence[str]) -> list[str]:
    values: list[str] = []
    for c in row.iterfind(f"{_NS}c"):
        ref = c.get("r")
        if ref:
            m = _CELL_REF.fullmatch(ref)
            if not m:
                raise XlsxError(f"bad cell reference {ref!r}")
            column = _column_index(m.group(1))
            if column < len(values):
                raise XlsxError(f"cell {ref} out of order")
            values.extend([""] * (column - len(values)))
        values.append(_value(c, shared))
    while values and not values[-1]:
        values.pop()
    return values


def _column_index(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * _LETTERS + ord(ch) - ord("A") + 1
    return index - 1


def _value(c: ET.Element, shared: Sequence[str]) -> str:
    kind = c.get("t", "n")
    if kind == "inlineStr":
        inline = c.find(f"{_NS}is")
        return _text(inline) if inline is not None else ""
    v = c.find(f"{_NS}v")
    raw = (v.text or "") if v is not None else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError) as e:
            raise XlsxError(f"cell {c.get('r')}: bad shared string {raw!r}") from e
    return raw
