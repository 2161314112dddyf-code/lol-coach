"""Synthetic exporter contract tests; no private replay or game data required.

Replication and movement framing are stubbed, while bounded health, compound
state, identity, and visibility decoders are exercised on synthetic bytes.
"""
import copy
import hashlib
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from lol_coach.lane_identity import decode_spawn
from lol_coach.replay_state import VERSION
from test_compound_inventory import packet as compound_packet


ROOT = Path(__file__).resolve().parents[1]
ACTOR = '0x40000031'
OTHER = '0x40000032'
SOURCE = dict(path='synthetic.rofl', sha256='a'*64)
# Publicly documented desensitized spawn fixture; surrounding packets synthetic.
SPAWN = bytes.fromhex('ae5c749c87732930392723ec4ead43')


@pytest.fixture
def exporter(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    spec = importlib.util.spec_from_file_location('synthetic_lane_export', ROOT/'scripts/export_lane_dynamics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity_bundle():
    row = dict(entity_id=ACTOR, time_seconds=20., identity=decode_spawn(SPAWN),
        source=dict(stream=1, chunk=1, decompressed_offset=10, opcode='0x005', payload_hex=SPAWN.hex()),
        first_health_witness=dict(time_seconds=90., health=500.),
        first_path_witness=dict(time_seconds=100., position=[1, 2]),
        class_crosscheck=dict(matched=True, witnessed_at=110.),
        witness_policy='retrospective')
    return dict(schema='lane-spawn-identities/v1', source=copy.deepcopy(SOURCE),
                version=VERSION, events=[row])


def packet(opcode, *, actor=ACTOR, payload=b'synthetic', time=21., stream=1, offset=123):
    return dict(opcode=opcode, param=int(actor, 16), payload=payload, time=time,
                stream=stream, chunk=2, offset=offset)


def build(exporter, packets, movement=None):
    identities, names = exporter.validate_identities(identity_bundle(), SOURCE, VERSION)
    spawn = dict(opcode=5, param=int(ACTOR, 16), payload=SPAWN, time=20.,
                 stream=1, chunk=1, offset=10)
    return exporter.build_evidence([spawn, *packets], identities, names, VERSION, movement, None, None)


@pytest.mark.parametrize('case', ['source', 'schema', 'bundle_version', 'source_version'])
def test_source_schema_and_build_mismatch_rejected(exporter, case):
    bundle = identity_bundle()
    version = VERSION
    if case == 'source':
        bundle['source']['sha256'] = 'b'*64
    elif case == 'schema':
        bundle['schema'] = 'unreviewed/v1'
    elif case == 'bundle_version':
        bundle['version'] = '16.21'
    else:
        version = '16.21'
    with pytest.raises(ValueError):
        exporter.validate_identities(bundle, SOURCE, version)


def test_prefix_identities_drop_retrospective_witness_objects(exporter):
    rows, names = exporter.validate_identities(identity_bundle(), SOURCE, VERSION)
    assert set(rows[0]) == {'entity_id', 'time_seconds', 'source', 'identity'}
    assert rows[0]['identity'] == decode_spawn(SPAWN)
    assert names[ACTOR] == decode_spawn(SPAWN)


def test_conflicting_identity_rejected(exporter):
    bundle = identity_bundle()
    other = copy.deepcopy(bundle['events'][0])
    other['identity']['team_id'] = 200
    bundle['events'].append(other)
    with pytest.raises(ValueError):
        exporter.validate_identities(bundle, SOURCE, VERSION)


@pytest.mark.parametrize('actor', ['0x80000031', '0x31', '0X40000031', 'invalid', None])
def test_noncanonical_or_wrong_class_actor_rejected(exporter, actor):
    bundle = identity_bundle()
    bundle['events'][0]['entity_id'] = actor
    with pytest.raises(ValueError):
        exporter.validate_identities(bundle, SOURCE, VERSION)


def test_identity_label_must_match_spawn_payload(exporter):
    bundle = identity_bundle()
    bundle['events'][0]['identity']['kind'] = 'ranged'
    with pytest.raises(ValueError):
        exporter.validate_identities(bundle, SOURCE, VERSION)


@pytest.mark.parametrize('mutation', ['missing', 'payload', 'offset', 'time', 'actor', 'stream'])
def test_original_spawn_anchor_must_match_before_bundle_created(exporter, mutation):
    identities, names = exporter.validate_identities(identity_bundle(), SOURCE, VERSION)
    spawn = dict(opcode=5, param=int(ACTOR, 16), payload=SPAWN, time=20.,
                 stream=1, chunk=1, offset=10)
    if mutation == 'payload':
        spawn['payload'] = SPAWN+b'\x00'
    elif mutation == 'offset':
        spawn['offset'] = 11
    elif mutation == 'time':
        spawn['time'] = 20.1
    elif mutation == 'actor':
        spawn['param'] = int(OTHER, 16)
    elif mutation == 'stream':
        spawn['stream'] = 2
    packets = [] if mutation == 'missing' else [spawn]
    with pytest.raises(ValueError):
        exporter.build_evidence(packets, identities, names, VERSION, None, None, None)


def test_health_uses_group8_record_actor_and_preserves_field_offsets(exporter, monkeypatch):
    group = dict(group=8, field_mask=3, payload_offset=27,
                 decoded_data_hex=(b'\xff'+struct.pack('<f', 500.)+b'\x7b').hex())
    wrong_group = dict(group, group=32, decoded_data_hex=struct.pack('<ff', 999., 999.).hex())
    records = [dict(entity_id=int(ACTOR, 16), payload_offset=12, groups=[wrong_group, group]),
               dict(entity_id=int(OTHER, 16), payload_offset=99, groups=[group])]
    monkeypatch.setattr(exporter, 'decode_payload', lambda *a, **k: dict(records=records))
    raw = packet(0x3df, actor=OTHER)
    result = build(exporter, [raw])
    assert result['rejected'] == []
    assert len(result['events']) == 1
    event = result['events'][0]
    assert event['entity_id'] == ACTOR
    assert event['values'] == dict(health=0., max_health=500.)
    assert event['fields']['health']['decoded_payload_offset'] == 27
    assert event['fields']['max_health']['decoded_payload_offset'] == 28
    assert event['source']['decoded_record_offset'] == 12
    assert event['source']['decoded_group_offset'] == 27
    assert event['source']['decompressed_offset'] == 123
    assert event['source']['payload_sha256'] == hashlib.sha256(raw['payload']).hexdigest()
    assert event['unparsed_suffix_hex'] == '7b'
    assert event['kind'] == 'health_sample'


def test_malformed_selected_health_is_rejected_without_partial_sample(exporter, monkeypatch):
    records = [dict(entity_id=int(ACTOR, 16), payload_offset=12, groups=[
        dict(group=8, field_mask=3, payload_offset=27, decoded_data_hex='ff00')])]
    monkeypatch.setattr(exporter, 'decode_payload', lambda *a, **k: dict(records=records))
    result = build(exporter, [packet(0x3df)])
    assert result['events'] == []
    assert len(result['rejected']) == 1
    assert result['rejected'][0]['layer'] == 'lane_health'


def movement_record(actor=ACTOR):
    return dict(entity_id=actor, decoded_offset=0, decoded_end=14,
        relative_waypoints=[[-50, 100]], speed=325., flags=2, extra_byte=None,
        map_waypoints_assuming_legacy_origin=[[7308, 7512]])


def test_movement_records_bind_inner_actor_and_keep_only_relative_coordinates(exporter):
    movement = SimpleNamespace(decode_packet=lambda *a: dict(data_start=5,
        records=[movement_record(), movement_record(OTHER)]))
    result = build(exporter, [packet(0xc9, actor=OTHER)], movement)
    assert len(result['events']) == 1
    event = result['events'][0]
    assert event['entity_id'] == ACTOR
    assert event['relative_waypoints'] == [[-50, 100]]
    assert event['source']['decoded_record_offset'] == 0
    assert event['source']['decoded_record_end'] == 14
    assert event['source']['encoded_array_offset'] == 5
    assert event['actual_arrival'] is None
    assert event['map_origin'] is None and event['current_map_position'] is None
    assert 'map_waypoints_assuming_legacy_origin' not in event


@pytest.mark.parametrize('kind', ['path', 'static'])
def test_compound_positions_preserve_decoded_offsets_without_map_origin(exporter, kind):
    prefix = bytes.fromhex('00000000000000000000803f0000000000000000000000000000')[:25]
    if kind == 'path':
        tail = prefix+b'\x02'+b'\x00'*4+struct.pack('<HIfhh', 2, int(ACTOR, 16), 325., -25, 50)
    else:
        tail = prefix+b'\x03'+b'\x00'*5+struct.pack('<4f', 7000., 4000., 1., 0.)
    movement = SimpleNamespace(parse_paths=lambda raw: [movement_record()])
    result = build(exporter, [packet(0x37d, payload=compound_packet(b'\x00'+tail))], movement)
    assert result['rejected'] == []
    event, = result['events']
    assert event['encoding'] == 'compound_state'
    assert event['actual_arrival'] is None and event['map_origin'] is None
    if kind == 'path':
        assert event['kind'] == 'path_command'
        assert event['decoded_path_offset'] == 31
        assert event['relative_waypoints'] == [[-50, 100]]
    else:
        assert event['kind'] == 'static_format_position_sample'
        assert event['decoded_position_offset'] == 32
        assert event['position_xz'] == [7000., 4000.]


def test_raw_167_and_removal_are_not_asserted_deaths(exporter):
    result = build(exporter, [packet(0x167), packet(0x490)])
    assert [e['kind'] for e in result['events']] == ['uninterpreted_167', 'terminal_removal_candidate']
    assert all(e['exact_death_time'] is None for e in result['events'])
    assert all('alive' not in e for e in result['events'])


def test_checkpoint_is_kept_separate_and_does_not_extend_live_recording_end(exporter):
    result = build(exporter, [packet(0x167, time=25., stream=1), packet(0x167, time=120., stream=2)])
    assert result['recording_end_seconds'] == 25.
    assert [e['source']['stream'] for e in result['events']] == [1, 2]
    assert result['summary']['event_counts'] == [
        dict(stream=1, kind='uninterpreted_167', count=1),
        dict(stream=2, kind='uninterpreted_167', count=1)]


def test_malformed_visibility_produces_unknown_barrier(exporter):
    result = build(exporter, [packet(0x484, payload=b'\x00')])
    event, = result['events']
    assert event['kind'] == 'visibility_unknown_barrier'
    assert event['observer_team_id'] is None and event['visible'] is None
    assert event['source']['opcode'] == '0x484'
    assert result['rejected'][0]['layer'] == 'visibility'
    assert result['decision_input_eligible'] is False
