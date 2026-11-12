import pytest

from lol_coach.movement_1622 import ORIGIN, WIRE_TO_PLAIN, decode_paths, reviewed_ward_sources


def test_ward_packet_matches_independently_registered_minimap_icon():
    # Native 143.101 replay packet and independently read blue-side ward icon.
    payload = bytes.fromhex('6d3b1e0893f32dc022bf065c97c0c071c0c0c0')
    ward, = decode_paths(payload)
    assert ward == dict(entity_id=0x40000392, speed=0.0, relative_waypoints_xz=[[-5254,898]])
    point = [coord + origin for coord, origin in zip(ward['relative_waypoints_xz'][0], ORIGIN)]
    assert point == [2104,8310]
    assert sum((a-b)**2 for a,b in zip(point, [2071.75,8325.11])) < 45**2


def test_hero_path_has_distinct_start_and_destination():
    payload = bytes.fromhex('7d71acd1b406c01fdd02c001c02e7115c02e34799ec0d2')
    hero, = decode_paths(payload)
    assert hero['entity_id'] == 0x400000ae
    assert hero['speed'] == 747.5
    assert hero['relative_waypoints_xz'] == [[-6740,-6764],[-6296,-5576]]
    for broken in (payload[:-1], payload + bytes([0]), b''):
        with pytest.raises(ValueError):
            decode_paths(broken)


def test_unknown_input_cannot_inherit_controlled_wards():
    assert len(set(WIRE_TO_PLAIN)) == len(WIRE_TO_PLAIN) == 256
    with pytest.raises(ValueError):
        reviewed_ward_sources(b'other replay')


def test_native_spawn_tail_distinguishes_six_lanes():
    from lol_coach.movement_1622 import minion_birth
    fixtures = {
        '0cffe95c988b73f5119b9e1e6b1e3dde':(100,'bottom'),
        '147fe85f988b73f5119b8e1e6b233dde':(100,'top'),
        '1ebf085a988b73f5119bfe1e0a3dde':(200,'middle'),
        '1f35485f988b73f5119bee1e6b0e3dde':(100,'middle'),
        '0e5f095e988b73f5119b5e1edf3dde':(200,'top'),
        '0cd50a5a988b73f5119b560eea3dde':(200,'bottom'),
    }
    for wire, expected in fixtures.items():
        assert minion_birth(bytes.fromhex(wire)) == expected
    assert minion_birth(bytes.fromhex('233dde')) is None
    assert minion_birth(bytes.fromhex('0cd50a5a988b73f5119b560eff3dde')) is None
