"""Read the worksheets of an XLSX workbook with the stdlib only.

Supports what the MV SR candidate lists use: shared strings (plain and rich
text), inline strings, numbers, booleans and cached formula results. Every
cell comes back as its text; numbers keep the text Excel stored (``"42"``,
``"0.5"``), dates are not converted. Styles are ignored.

A sheet is read by a tokenizer of the markup spreadsheets write (one
regular expression over the text, a token per cell or row), several times
faster than an XML parser building every element: ŠÚ SR's tables of the
votes per okrsok run to hundreds of MB of XML. It reads only well-formed
markup whose meaning it fully knows (the elements around the rows are
checked by the XML parser); at anything else, a comment or a formula, say,
the sheet is read again by the XML parser (:func:`_tree_rows`), from the
row reached, so both read every sheet alike.
"""

from __future__ import annotations

import codecs
import functools
import itertools
import posixpath
import re
import zipfile
from collections.abc import Callable, Generator, Iterator, Sequence
from pathlib import Path
from typing import IO
from xml.etree import ElementTree as ET

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS = f"{{{_MAIN}}}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_CELL_REF = re.compile(r"([A-Z]+)(\d+)")
_LETTERS = 26
_CHUNK = 1 << 20
"""Bytes of a sheet's XML decompressed and tokenized at a time."""
# Character data the tokenizer takes as is: no markup, reference or line
# break (which XML normalises), nothing XML forbids.
_CHARS = r"[^<>&\x00-\x1f\ufffe\uffff]*"
_TOKEN = re.compile(
    # A cell: its column, its type (either order with the style) and its
    # value or inline string, the only content it may have.
    r'<(?:c r="([A-Z]+)\d+"'
    r'(?: s="\d+"(?: t="(\w+)")?| t="(\w+)"(?: s="\d+")?)?'
    rf"(?:/>|>(?:<v>({_CHARS})</v>"
    rf'|<is><t(?: xml:space="preserve")?>({_CHARS})</t></is>)?</c>)'
    # A row: its number first, other attributes (checked by _row_attributes).
    rf'|row r="(\d+)"((?: [\w:.-]+="[^"<&\x00-\x1f]*")*)(/?)>'
    r"|(/)row>)"
    # Anything else but whitespace between them.
    r"|([^ \t\r\n])"
)
_ENCODING = re.compile(rb"""<\?xml[^>]*?\sencoding\s*=\s*["']([^"']*)""")


class _Unknown(Exception):
    """The sheet has markup the tokenizer does not read, or a fault.

    Either way the XML parser reads the sheet, and reports the fault (a
    cell out of order, say).
    """


class XlsxError(Exception):
    """The workbook is unreadable or not shaped as expected."""


def read_rows(path: Path | IO[bytes]) -> Iterator[list[str]]:
    """Yield the rows of the first worksheet of *path* as lists of strings.

    *path* may also be an open binary file, such as a workbook inside a zip.
    Empty rows inside the sheet are yielded as empty lists, so row positions
    match the sheet. Missing cells within a row are filled with ``""``;
    trailing empty cells are not added.
    """
    for _, rows in read_sheets(path, first_only=True):
        yield from rows


def read_sheets(
    path: Path | IO[bytes], *, first_only: bool = False
) -> Iterator[tuple[str, Iterator[list[str]]]]:
    """Yield (name, rows) of each worksheet of *path* in workbook order.

    Rows as :func:`read_rows` yields them; each sheet's rows are read while
    the workbook is open, so before the next sheet is asked for.
    """
    try:
        with zipfile.ZipFile(path) as z:
            shared = _shared_strings(z)
            for name, member in _sheets(z, first_only=first_only):
                with z.open(member) as f:
                    yield name, _parsed(_rows(f, shared), path)
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise XlsxError(f"{path}: {e}") from e


def _parsed(rows: Iterator[list[str]], path: object) -> Iterator[list[str]]:
    """Yield *rows*, a sheet's, failing as :func:`read_sheets` does."""
    try:
        yield from rows
    except (OSError, zipfile.BadZipFile, ET.ParseError) as e:
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


def _sheets(z: zipfile.ZipFile, *, first_only: bool) -> Iterator[tuple[str, str]]:
    """Yield (name, zip member) of the sheets (or the first) in workbook order."""
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = workbook.findall(f"{_NS}sheets/{_NS}sheet")
    if not sheets:
        raise XlsxError("workbook has no sheets")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.get("Id"): rel.get("Target", "")
        for rel in rels.iter(f"{_REL_NS}Relationship")
    }
    for sheet in sheets[:1] if first_only else sheets:
        rid = sheet.get(_DOC_REL)
        if rid not in targets:
            raise XlsxError(f"workbook relationship {rid!r} not found")
        target = targets[rid]
        # Targets are relative to xl/ unless absolute within the package.
        member = (
            target[1:]
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        yield sheet.get("name", ""), member


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
    """Yield the rows of sheet *f*: tokenized, else by the XML parser.

    The XML parser reads the sheet again from its start, its rows up to
    those the tokenizer yielded skipped.
    """
    done = 0
    try:
        for row in _token_rows(f, shared):
            yield row
            done += 1
        return
    except _Unknown:
        pass
    f.seek(0)
    yield from itertools.islice(_tree_rows(f, shared), done, None)


def _token_rows(f: IO[bytes], shared: Sequence[str]) -> Iterator[list[str]]:
    """Yield the rows of sheet *f* by :data:`_TOKEN`.

    Raise :class:`_Unknown` at what it does not read. The XML before the
    rows, up to ``<sheetData>``, and after them, from ``</sheetData>``, goes
    to the XML parser, which checks it and tells the namespaces; the rows
    may not change them.
    """
    parser, prefixes, rest = _head(f)
    attributes = functools.partial(_row_attributes, _declarations(prefixes))
    columns: dict[str, int] = {}
    decoder = codecs.getincrementaldecoder("utf-8")()
    text = _decoded(decoder, rest)
    values, expected = None, 1
    while (end := text.find("</sheetData>")) < 0:
        # Up to the last whole row; the rest comes with the next chunk.
        final = text.rfind("</row>")
        cut = final + len("</row>") if final >= 0 else 0
        values, expected = yield from _tokens(
            text[:cut], values, expected, shared, columns, attributes
        )
        chunk = f.read(_CHUNK)
        if not chunk:
            raise _Unknown
        text = text[cut:] + _decoded(decoder, chunk)
    values, _ = yield from _tokens(
        text[:end], values, expected, shared, columns, attributes
    )
    if values is not None:
        raise _Unknown
    # The bytes the decoder holds back (part of a character) come next.
    _tail(parser, text[end:].encode() + decoder.getstate()[0], f)


def _head(f: IO[bytes]) -> tuple[ET.XMLPullParser, dict[str, str], bytes]:
    """Return the parser of sheet *f* up to ``<sheetData>``, the root's namespaces, the rest read.

    Raise :class:`_Unknown` where the rows would not be tokenized.
    """
    head = b""
    while (at := head.find(b"<sheetData>")) < 0:
        chunk = f.read(_CHUNK)
        if not chunk:
            raise _Unknown
        head += chunk
    at += len(b"<sheetData>")
    if not _utf8(head[:at]):
        raise _Unknown
    parser = ET.XMLPullParser(events=("start", "end", "start-ns"))
    parser.feed(head[:at])
    prefixes, depth, tag = {}, 0, None
    for event in parser.read_events():
        match event:
            case ("start-ns", (str() as prefix, str() as uri)) if depth == 0:
                prefixes[prefix] = uri
            case ("start", ET.Element() as element):
                depth += 1
                tag = element.tag
            case ("end", _):
                depth -= 1
    # <sheetData> just started, a child of the root (depth 2), in the
    # namespace of the spreadsheets unprefixed.
    if (tag, depth, prefixes.get("")) != (f"{_NS}sheetData", 2, _MAIN):
        raise _Unknown
    return parser, prefixes, head[at:]


def _decoded(decoder: codecs.IncrementalDecoder, data: bytes) -> str:
    try:
        return decoder.decode(data)
    except UnicodeDecodeError:
        raise _Unknown from None


def _tokens(  # noqa: C901, PLR0912 - one loop over every cell, kept whole for speed
    text: str,
    values: list[str] | None,
    expected: int,
    shared: Sequence[str],
    columns: dict[str, int],
    attributes: Callable[[str], bool],
) -> Generator[list[str], None, tuple[list[str] | None, int]]:
    """Yield the rows *text* ends; return the cells of the row it leaves open and the row expected next.

    *values* are the cells of the row open before it (None between rows),
    *expected* the number of the row expected next, *columns* the column
    numbers by letters, *attributes* :func:`_row_attributes`.
    """
    for (
        letters,
        t1,
        t2,
        v,
        inline,
        number,
        attrs,
        empty,
        close,
        other,
    ) in _TOKEN.findall(text):
        if letters:
            if values is None:
                raise _Unknown
            column = columns.get(letters)
            if column is None:
                column = columns[letters] = _column_index(letters)
            if column != len(values):
                if column < len(values):
                    raise _Unknown
                values.extend([""] * (column - len(values)))
            kind = t1 or t2
            if kind == "s":
                try:
                    values.append(shared[int(v)])
                except (ValueError, IndexError):
                    raise _Unknown from None
            elif kind == "inlineStr":
                values.append(inline)
            else:
                values.append(v)
        elif close:
            if values is None:
                raise _Unknown
            while values and not values[-1]:
                values.pop()
            yield values
            values = None
        elif other or values is not None or not attributes(attrs):
            raise _Unknown
        else:
            row = int(number)
            # Rows without cells may be omitted from the XML altogether.
            for _ in range(expected, row):
                yield []
            expected = row + 1
            if empty:
                yield []
            else:
                values = []
    return values, expected


def _tail(parser: ET.XMLPullParser, data: bytes, f: IO[bytes]) -> None:
    """Give *parser* the sheet from ``</sheetData>``: *data*, then the rest of *f*.

    Raise :class:`_Unknown` at a row there, one all the same.
    """
    parser.feed(data)
    while chunk := f.read(_CHUNK):
        parser.feed(chunk)
    parser.close()
    for event in parser.read_events():
        match event:
            case ("end", ET.Element(tag=tag)) if tag == f"{_NS}row":
                raise _Unknown


def _utf8(head: bytes) -> bool:
    """Return whether the XML that starts with *head* is in UTF-8."""
    if head.startswith((codecs.BOM_UTF16_BE, codecs.BOM_UTF16_LE)):
        return False
    m = _ENCODING.match(head.removeprefix(codecs.BOM_UTF8))
    return m is None or m.group(1).lower() == b"utf-8"


def _declarations(prefixes: dict[str, str]) -> str:
    """Return the namespace declarations of *prefixes* as attributes."""
    return "".join(
        f' xmlns{":" if p else ""}{p}="{_escape(uri)}"' for p, uri in prefixes.items()
    )


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


@functools.cache
def _row_attributes(declarations: str, attrs: str) -> bool:
    """Return whether a row's *attrs* (but ``r``) leave it a row as the tokenizer reads it.

    Well-formed, its namespace that of its root (*declarations*): asked of
    the XML parser, once per text of the attributes (rows repeat them).
    """
    try:
        root = ET.fromstring(f'<w{declarations}><row r="1"{attrs}/></w>')
    except ET.ParseError:
        return False
    return root[0].tag == f"{_NS}row"


def _tree_rows(f: IO[bytes], shared: Sequence[str]) -> Iterator[list[str]]:
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
