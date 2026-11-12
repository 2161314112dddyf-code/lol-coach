import numpy as np
import pytest

from lol_coach.vision_regions_1622 import decode_spatial_record
from scripts.research_fog_bitmap import compare_plane, substitution_bound


@pytest.mark.parametrize("wire,team,x,z", [
    ("17c2c24b01207c25c465719f0c530de7e0197f36047e623204", 100, 2104, 8310),
    ("17c2c24b01257c65c46571de8d3c3ccee07e12040419015004", 100, 12390, 6432),
    ("14c2c24b01257c85c4657789873ca0fa1219b496047e08d304", 200, 4678, 12016),
    ("10c2c29c01227c25846d77fe81c57eebd30419b07404", 200, 12186, 4518),
])
def test_recorded_centres_crosschecked_with_independent_paths(wire, team, x, z):
    row = decode_spatial_record(bytes.fromhex(wire))
    assert row["team_id"] == team
    assert row["center_xz"] == [x, z]


def test_unsupported_layout_side_and_infinite_coordinate():
    ward = bytearray.fromhex("17c2c24b01207c25c465719f0c530de7e0197f36047e623204")
    assert decode_spatial_record(ward[:-1]) is None
    ward[10] = 0
    assert decode_spatial_record(ward) is None
    ward[10] = 0x71
    from lol_coach.vision_regions_1622 import WIRE_TO_FLOAT_BYTE
    ward[17:21] = bytes(WIRE_TO_FLOAT_BYTE.index(i) for i in b"\x7f\x80\0\0")
    assert decode_spatial_record(ward) is None


def test_first_ward_and_keyframe_share_a_region_handle():
    live = bytes.fromhex("17c2c24b01207c25c465719f0c530de7e0197f36047e623204")
    frame = bytes.fromhex("14c2c24b01207cc5c465719f0ca08ff3e0197f36047e623204")
    assert decode_spatial_record(live)["region_handle"] == decode_spatial_record(frame)["region_handle"] == 0x394


def test_bitmap_search_recovers_synthetic_rotated_padded_plane():
    rng = np.random.default_rng(8165)
    labels = np.repeat(np.repeat(rng.integers(1, 3, (16, 16)), 8, axis=0), 8, axis=1)
    plane = np.packbits(np.fliplr(np.rot90(labels == 1)).ravel(), bitorder="little").tobytes()
    labels[:25, :37] = 0
    result = compare_plane(b"abc" + plane + b"xyz", labels)
    assert (result["balanced_accuracy"], result["start_bit"]) == (1, 24)
    transformed = bytes(byte ^ 0x76 for byte in plane)
    bound = substitution_bound(b"abc" + transformed + b"xyz", labels)
    assert (bound["upper_bound"], bound["start_byte"]) == (1, 3)
