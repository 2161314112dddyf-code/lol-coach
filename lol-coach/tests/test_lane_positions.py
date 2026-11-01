"""Synthetic contracts only; private replay evidence is exported separately.

Movement parsing is stubbed here. The four original ROFL runs exercise the
reviewed movement reader and cross-packet agreement independently of pytest.
"""
import struct
from types import SimpleNamespace

import pytest

from lol_coach.compound_inventory import VERSION
from lol_coach.lane_positions import compound_lane_position
from test_compound_inventory import item, packet


ACTOR = '0x40000031'
PREFIX = bytes.fromhex('00000000000000000000803f0000000000000000000000000000')[:25]
PATH = struct.pack('<HIfhh', 2, int(ACTOR, 16), 325., -25, 50)


def path_record(**overrides):
    return dict(dict(entity_id=ACTOR, decoded_offset=0, decoded_end=len(PATH),
        speed=325., flags=2, extra_byte=None, relative_waypoints=[[-50, 100]],
        map_waypoints_assuming_legacy_origin=[[7308, 7512]]), **overrides)


def reader(records=None):
    def parse_paths(raw):
        assert raw == PATH
        return [path_record()] if records is None else records
    return SimpleNamespace(parse_paths=parse_paths)


def path_packet(tail=None):
    if tail is None:
        tail = PREFIX+b'\x02'+b'\x11\x22\x33\x44'+PATH
    return packet(b'\x00'+tail)


def static_packet(tail=None):
    if tail is None:
        tail = PREFIX+b'\x03'+b'\x11\x22\x33\x44\x00'+struct.pack('<4f', 7000., 4000., 1., 0.)
    return packet(b'\x00'+tail)


def test_synthetic_path_keeps_relative_values_and_unknown_arrival():
    result = compound_lane_position(path_packet(), ACTOR, reader(), version=VERSION)
    assert result['kind'] == 'embedded_path'
    assert result['relative_waypoints'] == [[-50, 100]]
    assert result['first_relative_point_candidate'] == [-50, 100]
    assert result['path_speed'] == 325.
    assert result['decoded_path_offset'] == 31
    assert result['opaque_path_metadata_hex'] == '11223344'
    assert result['actual_arrival'] is None and result['current_map_position'] is None
    assert 'map_waypoints_assuming_legacy_origin' not in result


def test_item_prefix_is_consumed_before_path_offset():
    tail = PREFIX+b'\x02'+b'\x00'*4+PATH
    raw = packet(b'\x01'+item(0, 1036)+tail)
    result = compound_lane_position(raw, ACTOR, reader(), version=VERSION)
    assert result['decoded_path_offset'] == 64


def test_synthetic_static_sample_is_not_continuous_current_position():
    result = compound_lane_position(static_packet(), ACTOR, None, version=VERSION)
    assert result['position_xz'] == [7000., 4000.]
    assert result['facing_xz'] == [1., 0.]
    assert result['decoded_position_offset'] == 32
    assert result['actual_arrival'] is None
    assert 'current-time semantics need separate review' in result['position_semantics']


@pytest.mark.parametrize('actor', [None, 0x40000031, '0x80000031', '0x31', 'invalid'])
def test_invalid_entity_binding_rejected(actor):
    with pytest.raises(ValueError, match='entity ID'):
        compound_lane_position(path_packet(), actor, reader(), version=VERSION)


def test_version_rejected_before_parsing():
    with pytest.raises(ValueError, match='exact build'):
        compound_lane_position(b'', ACTOR, None, version='16.21')


@pytest.mark.parametrize('records', [[], [path_record(), path_record()],
    [path_record(entity_id='0x40000032')]])
def test_multiple_or_wrong_inner_actor_rejected(records):
    with pytest.raises(ValueError, match='actor mismatch'):
        compound_lane_position(path_packet(), ACTOR, reader(records), version=VERSION)


@pytest.mark.parametrize('record', [path_record(decoded_offset=1),
    path_record(decoded_end=len(PATH)-1), path_record(relative_waypoints=[])])
def test_path_reader_must_consume_entire_nonempty_record(record):
    with pytest.raises(ValueError, match='Incomplete'):
        compound_lane_position(path_packet(), ACTOR, reader([record]), version=VERSION)


@pytest.mark.parametrize('tail', [b'', b'\x01'*25+b'\x02'+b'\x00'*18,
    PREFIX+b'\x04'+b'\x00'*18, PREFIX+b'\x02'+b'\x00'*17])
def test_unknown_or_short_position_layout_rejected(tail):
    with pytest.raises(ValueError):
        compound_lane_position(path_packet(tail), ACTOR, None, version=VERSION)


@pytest.mark.parametrize('raw', [path_packet()[:-1], path_packet()+b'\x00'])
def test_compound_outer_boundary_rejects_truncation_or_trailing_data(raw):
    with pytest.raises(ValueError, match='array boundary'):
        compound_lane_position(raw, ACTOR, None, version=VERSION)


@pytest.mark.parametrize('tail', [PREFIX+b'\x03'+b'\x00'*20,
    PREFIX+b'\x03'+b'\x00'*22,
    PREFIX+b'\x03'+b'\x00'*4+b'\x01'+struct.pack('<4f', 7000., 4000., 1., 0.)])
def test_static_layout_requires_exact_length_and_marker(tail):
    with pytest.raises(ValueError, match='stationary compound layout'):
        compound_lane_position(static_packet(tail), ACTOR, None, version=VERSION)


def test_static_sample_reuses_coordinate_validation():
    tail = PREFIX+b'\x03'+b'\x00'*5+struct.pack('<4f', 7000., 4000., 2., 0.)
    with pytest.raises(ValueError, match='facing vector'):
        compound_lane_position(static_packet(tail), ACTOR, None, version=VERSION)
