import zipfile
from pathlib import Path

import pytest

from election_map_slovakia import xlsx

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
WORKBOOK = (
    f"<workbook {NS}"
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Hárok1" sheetId="1" r:id="rId7"/></sheets></workbook>'
)
RELS = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId7" Type="worksheet" Target="worksheets/data.xml"/>'
    "</Relationships>"
)
SHARED = (
    f'<sst {NS}><si><t>Okres</t></si><si><t xml:space="preserve">Obec </t></si>'
    "<si><r><t>Bratislava</t></r><r><t> - Staré Mesto</t></r>"
    "<rPh><t>ignored</t></rPh></si></sst>"
)
SHEET = (
    f"<worksheet {NS}><sheetData>"
    '<row r="1"><c r="A1" t="inlineStr"><is><t>Zoznam kandidátov</t></is></c></row>'
    '<row r="3"><c r="A3" t="s"><v>0</v></c><c r="B3" t="s"><v>1</v></c>'
    '<c r="C3" t="inlineStr"><is><t>Vek</t></is></c></row>'
    '<row r="4"><c r="A4" t="s"><v>2</v></c><c r="C4"><v>42</v></c>'
    '<c r="D4" t="str"><f>A4</f><v>x</v></c><c r="E4"/></row>'
    '<row r="5"/>'
    '<row r="6"><c r="A6" t="inlineStr"><is><t>Poznámka</t></is></c></row>'
    "</sheetData></worksheet>"
)


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", RELS)
        z.writestr("xl/sharedStrings.xml", SHARED)
        z.writestr("xl/worksheets/data.xml", SHEET)
    return path


def test_rows_keep_positions_and_types(workbook: Path):
    assert list(xlsx.read_rows(workbook)) == [
        ["Zoznam kandidátov"],
        [],
        ["Okres", "Obec ", "Vek"],
        ["Bratislava - Staré Mesto", "", "42", "x"],
        [],
        ["Poznámka"],
    ]


def test_header_skips_titles_and_stops_at_footnotes(workbook: Path):
    header, rows = xlsx.find_header(xlsx.read_rows(workbook), "Okres")
    assert header == ["Okres", "Obec", "Vek"]
    assert list(rows) == [["Bratislava - Staré Mesto", "", "42", "x"]]


ROWS = [
    ["Okres", "Obec ", "", "Vek"],
    [],
    ["Bratislava - Staré Mesto", "42", "x"],
    [],
    ["", "", "Poznámka"],
]
# The rows above, as spreadsheets write them, and in markup the tokenizer
# leaves to the XML parser, at their start or after some rows.
PLAIN = (
    '<row r="1" spans="1:4"><c r="A1" s="1" t="s"><v>0</v></c>'
    '<c r="B1" t="s" s="2"><v>1</v></c><c r="C1" s="1"/>'
    '<c r="D1" t="inlineStr"><is><t>Vek</t></is></c></row>\n'
    '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3"><v>42</v></c>'
    '<c r="C3" t="str"><v>x</v></c></row><row r="4"/>'
    '<row r="5"><c r="C5" t="inlineStr"><is><t xml:space="preserve">Poznámka</t>'
    "</is></c></row>"
)


def sheet_of(rows: str) -> str:
    return f"<worksheet {NS}><sheetData>{rows}</sheetData></worksheet>"


SHEETS = {
    "plain": sheet_of(PLAIN),
    "comment": sheet_of(PLAIN.replace('<row r="3">', '<!-- x --><row r="3">')),
    "formula": sheet_of(PLAIN.replace('t="str">', 't="str"><f>A3</f>')),
    "entity": sheet_of(PLAIN.replace("Vek", "V&#101;k")),
    "prefixed": (
        f"<x:worksheet {NS.replace('xmlns', 'xmlns:x')}><x:sheetData>"
        + PLAIN.replace("<", "<x:").replace("<x:/", "</x:")
        + "</x:sheetData></x:worksheet>"
    ),
    # Rows of another namespace are none, before the end of the data or after.
    "other": (
        f"<worksheet {NS}><sheetData>"
        + PLAIN.replace('<row r="4"/>', '<row r="4" xmlns="urn:other"/>')
        + '<foo xmlns="urn:other"/></sheetData><x:row xmlns:x="urn:other"/>'
        "</worksheet>"
    ),
    "declared": (
        f'<?xml version="1.0" encoding="UTF-8"?><worksheet {NS}><sheetData>'
        + PLAIN.replace("<row", "\r\n  <row")
        + "</sheetData><pageMargins/></worksheet>"
    ),
}


@pytest.mark.parametrize("name", SHEETS)
def test_rows_alike_however_the_sheet_is_written(tmp_path: Path, monkeypatch, name):
    """The tokenizer and the XML parser it hands over to read the same rows."""
    # Small chunks, so that rows and characters are cut between them.
    monkeypatch.setattr(xlsx, "_CHUNK", 7)
    parsed = []
    tree_rows = xlsx._tree_rows
    monkeypatch.setattr(
        xlsx, "_tree_rows", lambda *a: parsed.append(1) or tree_rows(*a)
    )
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", RELS)
        z.writestr("xl/sharedStrings.xml", SHARED)
        z.writestr("xl/worksheets/data.xml", SHEETS[name])
    assert list(xlsx.read_rows(path)) == ROWS
    # What spreadsheets write is tokenized, the rest is left to the parser.
    assert bool(parsed) == (name not in {"plain", "declared"})


def test_cells_out_of_order_fail(tmp_path: Path):
    path = tmp_path / "book.xlsx"
    sheet = (
        f'<worksheet {NS}><sheetData><row r="1"><c r="B1"><v>1</v></c>'
        '<c r="A1"><v>2</v></c></row></sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", RELS)
        z.writestr("xl/worksheets/data.xml", sheet)
    with pytest.raises(xlsx.XlsxError, match="cell A1 out of order"):
        list(xlsx.read_rows(path))


def test_not_a_workbook(tmp_path: Path):
    path = tmp_path / "bad.xlsx"
    path.write_bytes(b"PK no zip")
    with pytest.raises(xlsx.XlsxError):
        list(xlsx.read_rows(path))
