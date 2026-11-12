"""Attach allied lane observations and hero path starts from the same reviewed ROFL."""
from collections import Counter
from copy import deepcopy
import hashlib

from .movement_1622 import VERSION, iter_path_samples, lane_minion_positions_at
from .reasoning_frame import canonical, digest
from .round_chain import _check_bundle
from .round_wave_clock import allied_wave_clocks


def _attach_allied_path_starts(bundle, raw):
    frame = bundle['frame']
    team, at = frame['decision']['observer_team_id'], frame['decision']['at_seconds']
    actors = {}
    for hero in frame['lineup']:
        if hero['relation'] != 'ally':
            continue
        actor = hero['entity_id']
        identity = [frame['facts'][fid] for fid in hero['current_fact_ids']
                    if frame['facts'][fid]['field'] == 'identity']
        if (len(identity) != 1 or identity[0]['entity_id'] != actor
                or identity[0]['value']['team_id'] != team
                or not isinstance(actor, str) or not actor.startswith('0x')):
            raise ValueError('invalid_allied_path_identity')
        actors[int(actor, 16)] = actor

    latest = {}
    for row in iter_path_samples(raw, streams=(1,), at_seconds=at):
        actor = actors.get(row['entity_id'])
        if actor is None:
            continue
        ref = row['source']
        order = (row['time_seconds'], ref['chunk'], ref['offset'], ref['record_index'])
        if actor not in latest or order > latest[actor][0]:
            latest[actor] = (order, row)

    ids = []
    for actor, (_, row) in sorted(latest.items()):
        when = row['time_seconds']
        fact = dict(entity_id=actor, field='allied_path_start_sample',
                    value=dict(observer_team_id=team, xz=row['world_waypoints_xz'][0]),
                    unit='map11_world_xz', temporal_scope='historical_path_start_sample',
                    observed_at_seconds=when, age_seconds=at-when)
        fid = 'f_' + digest(fact)[:20]
        frame['facts'][fid] = fact
        bundle['audit']['fact_sources'][fid] = dict(basis='first_waypoint_of_last_allied_live_path',
                                                    source=row['source'], time_seconds=when)
        ids.append(fid)
    frame['allied_path_fact_ids'] = ids
    frame['input_policy'].append('己方英雄位置是最近一次移动包的起点。保留采样时间和年龄，不能确定现在的位置、正在赶来或在哪个地标。')


def attach_round_lanes(bundle, raw, *, max_chars=250000):
    frame = _check_bundle(bundle)
    if (bundle['audit'].get('source_replay_sha256') != hashlib.sha256(raw).hexdigest()
            or frame['decision']['build'] != VERSION):
        raise ValueError('round_lane_source_or_build_mismatch')
    if frame.get('lane_fact_ids'):
        raise ValueError('lane_evidence_already_attached')
    result = deepcopy(bundle)
    frame = result['frame']
    at = frame['decision']['at_seconds']
    team = frame['decision']['observer_team_id']
    rows = lane_minion_positions_at(raw, at)
    clocks = allied_wave_clocks(raw, at_seconds=at, observer_team_id=team)
    _attach_allied_path_starts(result, raw)
    lane_ids = []
    for lane, native in [('top', 'top'), ('mid', 'middle'), ('bot', 'bottom')]:
        units, sources = [], []
        for row in rows:
            if row['team_id'] != team or row['lane'] != native:
                continue
            pos = row['position']
            units.append(dict(entity_id=hex(row['entity_id']), kind=row['minion_class'] or 'unknown',
                              born_at=row['birth_seconds'], last_xz=pos['world_xz'] if pos else None,
                              sampled_at=pos['time_seconds'] if pos else None))
            sources.append(dict(entity_id=hex(row['entity_id']), birth=row['birth_source'],
                                last_position=pos['source'] if pos else None))
        counts = Counter(u['kind'] for u in units)
        value = dict(lane=lane, observer_team_id=team, count_scope='own_team_observed_live_only',
                     counts=[dict(team_id=team, kind=kind, count=n) for kind, n in sorted(counts.items())],
                     units=units, wave_spawn_clock=clocks[lane])
        fact = dict(entity_id='lane:'+lane, field='lane_current_units_and_groups', value=value,
                    observed_at_seconds=at, temporal_scope='queried_at_decision_time', age_seconds=0)
        fid = 'f_' + digest(fact)[:20]
        frame['facts'][fid] = fact
        result['audit']['fact_sources'][fid] = sources
        lane_ids.append(fid)
    frame['lane_fact_ids'] = lane_ids
    frame['unknowns']['waves'] = 'own_team_only_enemy_wave_and_clear_time_unknown'
    frame['input_policy'].append('兵线只列本队已出生且在截止前未记录移除的小兵。坐标仅为带时间的历史采样，不能推出敌兵、交战、清完时间、应得金币或进塔。')
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_'+digest(frame)[:24]
    size = len(canonical(frame))
    if size > max_chars:
        raise ValueError('round_lane_frame_exceeds_budget')
    result['audit']['frame_chars'] = size
    return result
