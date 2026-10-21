"""Synthetic fixtures test binary boundaries; they are not real game evidence."""
import json
import math
import struct

import pytest
import xxhash
import zstandard

from lol_coach.ngrid import parse_ngrid, parse_overlay, flag_category
from lol_coach.wad import WadReader
from lol_coach.http import EvidenceClient


@pytest.fixture
def synthetic_grid():
    header = struct.pack("<BH7fII", 7, 1, 10, -10, 20, 110, 10, 170, 50, 2, 3)
    cells = bytearray(6 * 48)
    for i in range(6):
        struct.pack_into("<hh", cells, i * 48 + 20, i % 2, i // 2)
    # Open, wall, brush, blue-only, uninterpreted bit, structure/transparent wall.
    flags = struct.pack("<6H", 0, 2, 1, 1024, 8, 70)
    heights = struct.pack("<IIff", 5, 7, 25, 25) + struct.pack("<35f", *range(35))
    return header + cells + flags + bytes(6 * 4 + 1056) + heights + bytes(900 * 3604)


def test_grid_mapping_and_unknown(synthetic_grid):
    grid = parse_ngrid(synthetic_grid)
    assert (grid.width, grid.height, grid.cell_size) == (2, 3, 50)
    assert grid.cell_at(10, 20)["raw_flags"] == 0
    assert grid.cell_at(60, 20)["raw_flags"] == 2
    assert grid.cell_at(59.999, 70)["raw_flags"] == 1
    assert grid.cell_at(60, 70)["category"] == "team_restricted"
    assert grid.cell_at(10, 120)["category"] == "unknown_flags"
    assert grid.cell_at(109.99, 169.99)["category"] == "static_blocked_candidate"
    assert grid.cell_at(10, 20)["actual_passability"] is None


@pytest.mark.parametrize("x,z", [(9.999, 20), (110, 20), (10, 19.99), (10, 170), (math.nan, 30), (30, math.inf)])
def test_grid_rejects_outside_and_nonfinite(synthetic_grid, x, z):
    with pytest.raises(ValueError):
        parse_ngrid(synthetic_grid).cell_at(x, z)


@pytest.mark.parametrize("change", ["version", "truncate", "extra", "cell_order", "dimensions", "nan_height"])
def test_bad_grid_fails_closed(synthetic_grid, change):
    raw = bytearray(synthetic_grid)
    if change == "version": raw[0] = 8
    if change == "truncate": raw = raw[:-1]
    if change == "extra": raw += b"\x00"
    if change == "cell_order": struct.pack_into("<h", raw, 39 + 20, 1)
    if change == "dimensions": struct.pack_into("<I", raw, 31, 99)
    if change == "nan_height": struct.pack_into("<f", raw, 39 + 6 * 54 + 1056 + 16, math.nan)
    with pytest.raises(ValueError):
        parse_ngrid(bytes(raw))


def overlay_fixture():
    # Version 1, TWO regions; second byte must not be interpreted as minor version.
    return b"\x01\x02" + struct.pack("<4I2H", 0, 0, 2, 1, 2, 0) + struct.pack("<4IH", 1, 0, 1, 1, 1) + b"\x01"


def test_multi_region_overlay_unknown_tail():
    result = parse_overlay(overlay_fixture(), 2, 3)
    assert result["region_count"] == 2
    assert result["covered_cell_count"] == 2
    assert result["overlapping_cell_writes"] == 1
    assert result["trailing_bytes_hex"] == "01"
    assert result["application_status"].startswith("not_applied")


@pytest.mark.parametrize("raw", [b"\x02\x00", b"\x01\x01", overlay_fixture() + b"extra",
                                 b"\x01\x01" + struct.pack("<4I", 2, 0, 1, 1) + b"\0\0"])
def test_bad_overlay_rejected(raw):
    with pytest.raises(ValueError):
        parse_overlay(raw, 2, 3)


def make_wad(tmp_path, *, kind=3, checksum_error=False, index_error=False):
    plain = b"synthetic map asset"
    packed = zstandard.ZstdCompressor().compress(plain) if kind == 3 else plain
    header = bytearray(272)
    header[:4] = b"RW\x03\x04"
    struct.pack_into("<I", header, 268, 1)
    entry = struct.pack("<QIIIBBHQ", xxhash.xxh64_intdigest(b"assets/synthetic"),
                        0 if index_error else 304, len(packed), len(plain), kind, 0, 0,
                        xxhash.xxh3_64_intdigest(packed) ^ checksum_error)
    path = tmp_path / "synthetic.wad.client"
    path.write_bytes(header + entry + packed)
    return path, plain


@pytest.mark.parametrize("kind", [0, 3])
def test_wad_extract_and_checksum(tmp_path, kind):
    path, plain = make_wad(tmp_path, kind=kind)
    result, evidence = WadReader(path).extract_bytes("ASSETS/Synthetic")
    assert result == plain
    assert evidence["checksum_status"] == "xxh3_64_verified"


def test_wad_corrupt_checksum(tmp_path):
    path, _ = make_wad(tmp_path, checksum_error=True)
    with pytest.raises(ValueError, match="checksum"):
        WadReader(path).extract_bytes("assets/synthetic")


def test_wad_index_outside(tmp_path):
    path, _ = make_wad(tmp_path, index_error=True)
    with pytest.raises(ValueError, match="out-of-bounds"):
        WadReader(path)


def test_wad_unsupported_and_limits(tmp_path):
    path, _ = make_wad(tmp_path, kind=4)
    wad = WadReader(path)
    with pytest.raises(ValueError, match="Unsupported"):
        wad.extract_bytes("assets/synthetic")
    with pytest.raises(ValueError, match="size limit"):
        wad.extract_bytes("assets/synthetic", max_bytes=1)
    with pytest.raises(ValueError, match="not found"):
        wad.extract_bytes("assets/missing")


def test_large_http_cap_not_success(tmp_path):
    from io import BytesIO
    class Fake(BytesIO):
        status = 200
        headers = {"Content-Length": "100", "Content-Type": "application/json"}
        def geturl(self): return "https://synthetic.example"
    client = EvidenceClient(tmp_path, max_bytes=10, retries=0, interval=0, opener=lambda *a, **kw: Fake(b"{}"))
    record, data = client.fetch("synthetic", "https://synthetic.example", expect_json=True)
    assert data is None and record["status"] == "network_error"
    assert record["evidence_path"] is None
