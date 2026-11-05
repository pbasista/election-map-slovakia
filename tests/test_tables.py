import csv
import datetime as dt
import io

import pytest

from election_map_slovakia import tables


@pytest.mark.parametrize(
    "text",
    [
        "",
        "a,b,c\n",
        "a,b,c\r\n1,2,3\r\n\r\n4,5\n6,7,8,9\n",
        '\n1,"x,y",3\n',
        "a,a,b\n1,2\n1,2,3\n",
    ],
)
def test_dict_rows_read_as_dict_reader(text):
    assert tables.dict_rows(text) == list(csv.DictReader(io.StringIO(text)))


def test_cells_read_as_rows_have_them(tmp_path):
    """Picked cells are the rows' cells: stripped, padded, data ending alike."""
    path = tmp_path / "X_tab07e.csv"
    path.write_text(
        "Title,\n"
        "Obec,Strana,Hlasy\n"
        ",,\n"
        " 500011 , 1 ,4\n"
        "528595,2\n"
        "500020,3,7,extra\n"
        "  , \t,\n"
        "Notes,below,\n"
    )
    package = tables.open_package([path], dt.UTC)
    rows = [[r[2], r[0]] for s in package.stream("tab07e") for r in s.rows()]
    cells = [c for s in package.stream("tab07e") for c in s.cells(2, 0)]
    assert cells == rows == [["4", "500011"], ["", "528595"], ["7", "500020"]]
