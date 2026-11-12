"""Synthetic packet-prefix and source/side boundary checks for the ally path view."""
import hashlib

import pytest

from lol_coach import movement_1622 as mv
from lol_coach import round_lane_evidence as binder
from lol_coach.reasoning_frame import digest
from lol_coach.round_plan import review_round_plan
from test_round_chain import bundle_at, freeze


@pytest.fixture
def setup_paths(monkeypatch):
    raw = b'synthetic ally positions'
    sha = hashlib.sha256(raw).hexdigest()
    bundle = bundle_at(20)
    frame = bundle['frame']
    frame['decision'].update(player_entity_id='0x400000ae', build=mv.VERSION)
    frame['lineup'] = []
    bundle['audit'].update(source_replay_sha256=sha, fact_sources={})
    for actor, side in [(0x400000ae, 100), (0x400000af, 100), (0x400000b0, 200)]:
        entity = hex(actor)
        identity = dict(entity_id=entity, field='identity', value={'team_id': side}, observed_at_seconds=0,
                        temporal_scope='roster', age_seconds=20)
        fid = 'f_' + digest(identity)[:20]
        frame['facts'][fid] = identity
        frame['lineup'].append(dict(entity_id=entity, relation='ally' if side == 100 else 'enemy',
                                    champion='C' + entity[-1], current_fact_ids=[fid], history_fact_ids=[]))
    freeze(bundle)
    monkeypatch.setattr(mv, 'container_info', lambda _: {'version': mv.VERSION})
    monkeypatch.setattr(mv, 'MAP11_REPLAYS', {sha})
    packets = []
    for stream, time, actor, byte in [(1, 19.5, 0x400000ae, 3), (1, 17, 0x400000ae, 1),
            (1, 20, 0x400000af, 6), (1, 20, 0x400000af, 7), (1, 20, 0x400000b0, 9),
            (1, 20.1, 0x400000ae, 255), (2, 20, 0x400000af, 255)]:
        packets.append(dict(stream=stream, time=time, opcode=mv.OPCODE, param=actor,
                            payload=bytes([byte]), offset=len(packets), chunk=0))
    monkeypatch.setattr(mv, 'packets', lambda _: iter(packets))

    def decode(payload):
        number, = payload
        assert number != 255, 'keyframe/future path was decoded'
        actor = next(p['param'] for p in packets if p['payload'] == payload)
        return [dict(entity_id=actor, relative_waypoints_xz=[[number, 0], [12345, 54321]], speed=4321)]

    monkeypatch.setattr(mv, 'decode_paths', decode)
    monkeypatch.setattr(binder, 'lane_minion_positions_at', lambda *args: [])
    monkeypatch.setattr(binder, 'allied_wave_clocks', lambda *args, **kwargs: dict(top={}, mid={}, bot={}))
    return bundle, raw, packets


def test_source_bound_last_allied_starts_only_and_indexed_historical_evidence(setup_paths):
    bundle, raw, _ = setup_paths
    prepared = binder.attach_round_lanes(bundle, raw)
    report = review_round_plan(prepared)
    sample = report['player_last_observed_path_start']
    assert sample['xz'] == [mv.ORIGIN[0] + 3, mv.ORIGIN[1]] and sample['age_seconds'] == 0.5
    ally, = report['allies']
    sample = ally['last_observed_path_start']
    assert sample == dict(xz=[mv.ORIGIN[0]+7, mv.ORIGIN[1]], sampled_at=20, age_seconds=0, fact_id=sample['fact_id'])
    assert ally['commitment'] == 'unknown'
    assert set(prepared['frame']['allied_path_fact_ids']) == {
        sample['fact_id'], report['player_last_observed_path_start']['fact_id']}
    assert prepared['audit']['fact_sources'][sample['fact_id']]['source']['offset'] == 3
    assert 'allied_path_fact_ids' not in bundle['frame']
    assert '12345' not in str(report['allies'])


def test_missing_ally_samples_remain_unknown(setup_paths):
    bundle, raw, packets = setup_paths
    packets[:] = [p for p in packets if p['param'] != 0x400000af]
    report = review_round_plan(binder.attach_round_lanes(bundle, raw))
    assert report['allies'][0]['last_observed_path_start'] is None


def test_mislabeled_enemy_and_wrong_replay_rejected(setup_paths):
    bundle, raw, _ = setup_paths
    with pytest.raises(ValueError, match='source_or_build_mismatch'):
        binder.attach_round_lanes(bundle, b'other')
    bundle['frame']['lineup'][-1]['relation'] = 'ally'
    with pytest.raises(ValueError, match='invalid_allied_path_identity'):
        binder.attach_round_lanes(freeze(bundle), raw)
