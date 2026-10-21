"""Synthetic boundaries for research-only structural state; no live-game claims."""
import struct

import pytest

from lol_coach.structure_evidence import (
    health_candidates, is_initial_layout, prefix_evidence, state_observation,
)


def record(mask=3, data=None, group=4):
    return dict(group_mask=68, groups=[dict(group=group, field_mask=mask,
        decoded_data_hex=(struct.pack('<ff', 4000, 4000) if data is None else data).hex(),
        payload_offset=20)])


def test_only_complete_initial_class_layout_matches():
    r = record(4095)
    assert not is_initial_layout(r)
    r['groups'].append(dict(group=64, field_mask=3))
    assert is_initial_layout(r)
    r['group_mask'] = 12
    assert not is_initial_layout(r)


def test_health_uses_class_group_and_partial_mask():
    assert health_candidates(record(group=32)) == ({}, [])
    values, fields = health_candidates(record(2, struct.pack('<f', 5500)))
    assert values == {'max_health_candidate': 5500}
    assert fields[0]['decoded_payload_offset'] == 20


def test_zero_marker_and_escaped_float():
    values, fields = health_candidates(record(3, b'\xff\xfe'+struct.pack('<f', 4000)))
    assert values == {'health_candidate': 0, 'max_health_candidate': 4000}
    assert [f['byte_length'] for f in fields] == [1, 5]


@pytest.mark.parametrize('data', [b'', b'\xfe', struct.pack('<f', -1)])
def test_invalid_field_rejected(data):
    with pytest.raises(ValueError):
        health_candidates(record(1, data))


def test_unknown_enum_remains_unknown_and_no_authoritative_state():
    for raw in (0x8d, 0x9c, 0x9d, 0x00):
        result = state_observation(bytes([raw]))
        assert result['authoritative_state'] is None
        assert result['raw_code'] == raw
    assert state_observation(b'\x00')['research_correlation'] is None
    with pytest.raises(ValueError):
        state_observation(b'\x8d\x00')


def test_version_guard():
    with pytest.raises(ValueError):
        state_observation(b'\x8d', version='another-build')
    with pytest.raises(ValueError):
        health_candidates(record(), version='another-build')


def bundle():
    return dict(source={'test': 'synthetic'}, version='synthetic',
        discoveries=[dict(entity_id='x', time_seconds=1, order=2)],
        health_samples=[dict(entity_id='x', time_seconds=1, order=2,
            values={'health_candidate': 4000}, source={})],
        state_observations=[dict(entity_id='x', time_seconds=1, order=1, state={'raw_code': 141})])


def test_no_future_or_pre_discovery_backfill():
    b = bundle()
    assert prefix_evidence(b, 0)['objects'] == {}
    before = prefix_evidence(b, 1)
    b['health_samples'].append(dict(entity_id='x', time_seconds=3, order=4,
        values={'health_candidate': 0}, source={}))
    b['state_observations'].append(dict(entity_id='x', time_seconds=3, order=3, state={'raw_code': 156}))
    assert prefix_evidence(b, 1) == before
    assert before['objects']['x']['latest_state'] is None
    assert prefix_evidence(b, 3)['objects']['x']['latest_samples']['health_candidate']['value'] == 0
    assert not before['decision_input_eligible']
    assert before['objects']['x']['identity'] is None
    assert before['objects']['x']['team'] is None


@pytest.mark.parametrize('cutoff', [-1, float('nan'), float('inf')])
def test_invalid_prefix_rejected(cutoff):
    with pytest.raises(ValueError):
        prefix_evidence(bundle(), cutoff)
