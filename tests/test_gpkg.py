import struct

import pytest
import shapely

from election_map_slovakia import gpkg

POLYGON = shapely.Polygon(
    [(-570000, -1220000), (-569000, -1220000), (-569000, -1219000)]
)


def blob(
    envelope: int, little_endian: bool, srs: int = 5514, wkb_order: int = 1
) -> bytes:
    order = "<" if little_endian else ">"
    flags = envelope << 1 | int(little_endian)
    doubles = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}[envelope]
    header = b"GP" + bytes([0, flags]) + struct.pack(order + "i", srs)
    header += struct.pack(f"{order}{doubles}d", *range(doubles))
    return header + shapely.to_wkb(POLYGON, byte_order=wkb_order)


@pytest.mark.parametrize("envelope", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("little_endian", [True, False])
def test_header_variants(envelope: int, little_endian: bool):
    b = blob(envelope, little_endian, wkb_order=int(little_endian))
    assert gpkg.geometry(b).equals(POLYGON)
    assert gpkg.srs_id(b) == 5514


def test_header_byte_order_independent_of_wkb_byte_order():
    b = blob(1, little_endian=False, srs=4326, wkb_order=1)
    assert gpkg.srs_id(b) == 4326
    assert gpkg.geometry(b).equals(POLYGON)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"XX" + blob(0, True)[2:], "header"),
        (blob(0, True)[:3] + bytes([0b1011]) + blob(0, True)[4:], "envelope code 5"),
        (blob(0, True)[:3] + bytes([0x21]) + blob(0, True)[4:], "extended"),
        (blob(4, True)[:40], "ends inside"),
    ],
)
def test_malformed_blobs_rejected(data: bytes, message: str):
    with pytest.raises(gpkg.GpkgError, match=message):
        gpkg.geometry(data)
