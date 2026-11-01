"""Bounded lane-health serialization and identity-gate regression tests."""
import struct

import pytest

from lol_coach.lane_health import decode_health_prefix
from lol_coach.replay_state import VERSION


LANE = dict(team_id=100, kind='melee')


def decode(mask, data, *, identity=LANE, version=VERSION, **extra):
    group = dict(group=8, field_mask=mask, decoded_data_hex=data, **extra)
    return decode_health_prefix(group, version=version, identity=identity)


@pytest.mark.parametrize('mask,name', [(1, 'health'), (2, 'max_health')])
def test_sparse_health_fields_are_not_renumbered_or_filled(mask, name):
    result = decode(mask, '0000c842')  # independent float32 100
    assert result == dict(values={name: 100.},
        fields={name: dict(value=100., decoded_offset=0, encoded_hex='0000c842')},
        unparsed_suffix_hex='')


def test_full_observed_super_prefix_preserves_uninterpreted_class_fields():
    result = decode(0x3ffffff, '00a0524500a05245ffffffff00010000c842',
                    identity=dict(team_id=200, kind='super'))
    assert result['values'] == {'health': 3370., 'max_health': 3370.}
    assert result['fields']['max_health']['decoded_offset'] == 4
    assert result['unparsed_suffix_hex'] == 'ffffffff00010000c842'


def test_zero_marker_and_literal_ff_escape_keep_offsets_and_source_bytes():
    result = decode(3, 'fffeff000044')
    literal = struct.unpack('<f', bytes.fromhex('ff000044'))[0]
    assert result['values'] == {'health': 0., 'max_health': literal}
    assert result['fields']['health'] == dict(value=0., decoded_offset=0, encoded_hex='ff')
    assert result['fields']['max_health'] == dict(value=literal, decoded_offset=1,
                                                encoded_hex='feff000044')


def test_group_relative_offset_does_not_silently_include_packet_offset():
    result = decode(3, 'ff0000c842', payload_offset=289)
    assert result['fields']['max_health']['decoded_offset'] == 1


@pytest.mark.parametrize('mask,data', [(0, ''), (0, 'fe'), (4, 'ff80fe')])
def test_no_health_bits_do_not_consume_or_validate_unknown_suffix(mask, data):
    assert decode(mask, data) == dict(values={}, fields={}, unparsed_suffix_hex=data)


def test_health_with_unknown_suffix_does_not_apply_hero_float_layout():
    result = decode(0x1005, '0000c842fe')
    assert result['values'] == {'health': 100.}
    assert result['unparsed_suffix_hex'] == 'fe'


@pytest.mark.parametrize('mask,data', [(1, ''), (1, '00'), (1, 'fe'),
                                     (2, 'fe0000'), (3, '0000c842')])
def test_selected_truncated_fields_reject_whole_observation(mask, data):
    with pytest.raises(ValueError, match='Truncated'):
        decode(mask, data)


@pytest.mark.parametrize('mask,data', [(1, '000080bf'), (2, '000080bf'),
                                     (1, '0000807f'), (2, '0000c07f'),
                                     (3, '0000c842000080ff')])
def test_negative_and_nonfinite_values_are_rejected(mask, data):
    with pytest.raises(ValueError):
        decode(mask, data)


@pytest.mark.parametrize('identity', [None, {}, dict(team_id=100),
    dict(team_id=300, kind='melee'), dict(team_id=100, kind='ward'),
    dict(team_id=100., kind='melee'), dict(team_id=100, kind=['melee'])])
def test_unsupported_or_missing_identity_cannot_borrow_lane_layout(identity):
    with pytest.raises(ValueError, match='identity'):
        decode(1, 'ff', identity=identity)


@pytest.mark.parametrize('kind', ['melee', 'ranged', 'siege', 'super_candidate', 'super'])
def test_supported_identity_does_not_upgrade_candidate_classification(kind):
    identity = dict(team_id=200, kind=kind)
    assert decode(1, 'ff', identity=identity)['values'] == {'health': 0.}
    assert identity == dict(team_id=200, kind=kind)


@pytest.mark.parametrize('mask', [-1, True, 1., None, '1'])
def test_invalid_masks_rejected(mask):
    with pytest.raises(ValueError, match='mask'):
        decode(mask, 'ff')


@pytest.mark.parametrize('group', [None, {}, dict(group=32, field_mask=1, decoded_data_hex='ff'),
    dict(group=8., field_mask=1, decoded_data_hex='ff'),
    dict(group=8, field_mask=1, decoded_data_hex=None),
    dict(group=8, field_mask=1, decoded_data_hex='zz')])
def test_invalid_group_shape_or_hex_rejected(group):
    with pytest.raises(ValueError):
        decode_health_prefix(group, version=VERSION, identity=LANE)


def test_other_build_not_accepted_even_for_zero_marker():
    with pytest.raises(ValueError, match='build'):
        decode(1, 'ff', version='16.21')
