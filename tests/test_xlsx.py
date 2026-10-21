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


def test_not_a_workbook(tmp_path: Path):
    path = tmp_path / "bad.xlsx"
    path.write_bytes(b"PK no zip")
    with pytest.raises(xlsx.XlsxError):
        list(xlsx.read_rows(path))
