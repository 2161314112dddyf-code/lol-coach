"""Decide which actors to inspect from this player's recent, visible samples."""
from math import dist

from .reasoning_frame import digest, number
from .round_options import _checked_facts


def allied_paths(frame):
    team = frame['decision']['observer_team_id']
    allies = {h['entity_id'] for h in frame['lineup'] if h['relation'] == 'ally'}
    paths = {}
    for fid, fact in _checked_facts(frame, 'allied_path_fact_ids'):
        actor, value = fact['entity_id'], fact['value']
        if (actor not in allies or actor in paths or fact['field'] != 'allied_path_start_sample'
                or fact.get('unit') != 'map11_world_xz' or fact['temporal_scope'] != 'historical_path_start_sample'
                or value.get('observer_team_id') != team or not isinstance(value.get('xz'), list)
                or len(value['xz']) != 2 or not all(number(x) for x in value['xz'])):
            raise ValueError('invalid_allied_path_sample')
        paths[actor] = dict(xz=list(value['xz']), sampled_at=fact['observed_at_seconds'],
                            age_seconds=fact['age_seconds'], fact_id=fid)
    return paths


def ranked_samples(origin, candidates):
    if not origin or origin['age_seconds'] > 1:
        return []
    rows = []
    for entity, champion, sample in candidates:
        if sample and sample['age_seconds'] <= 1:
            rows.append(dict(entity_id=entity, champion=champion,
                             sampled_gap_world_units=round(dist(origin['xz'], sample['xz']), 1),
                             sampled_at_seconds=[origin['sampled_at'], sample['sampled_at']],
                             fact_refs=[origin['fact_id'], sample['fact_id']]))
    return sorted(rows, key=lambda r: (r['sampled_gap_world_units'], r['entity_id']))


def actor_context(frame, sightings, paths):
    me = frame['decision']['player_entity_id']
    at = frame['decision']['at_seconds']
    own = next(h for h in frame['lineup'] if h['entity_id'] == me)
    names = {h['entity_id']:h['champion'] for h in frame['lineup']}
    recent_deaths = {}
    public_kills = []
    for fid, fact in _checked_facts(frame, 'recent_public_combat_ids'):
        if fact['field'] != 'public_kill_feed':
            raise ValueError('invalid_public_kill_fact')
        victim = fact['value']['victim_entity_id']
        when = fact['observed_at_seconds']
        recent_deaths[victim] = max(recent_deaths.get(victim, -1), when)
        public_kills.append(dict(victim=names.get(victim),killer=names.get(fact['value']['killer_entity_id']),
                                 at_seconds=when,age_seconds=at-when,fact_id=fid))
    origin = paths.get(me)
    allies = [(h['entity_id'], h['champion'], paths.get(h['entity_id'])) for h in frame['lineup']
              if h['relation'] == 'ally' and h['entity_id'] != me]
    seen = [(r['entity_id'], r['champion'], dict(r['last_observed_path_start'], fact_id=r['fact_id']))
            for r in sightings['opponents'] if r['visible'] is True and r['last_observed_path_start']
            and r['last_observed_path_start']['sampled_at'] > recent_deaths.get(r['entity_id'], -1)]
    opponents = ranked_samples(origin, seen)
    teammates = ranked_samples(origin, allies)
    own_status = {}
    for fid in own.get('current_fact_ids', []):
        fact = frame['facts'][fid]
        field = fact['field']
        if field not in ('health', 'max_health', 'resource', 'max_resource', 'level', 'personal_hud_state',
                         'personal_client_state'):
            continue
        when = fact['observed_at_seconds']
        if (fid != 'f_' + digest(fact)[:20] or fact['entity_id'] != me or not number(when)
                or not 0 <= when <= fact.get('available_at_seconds', when) <= at):
            raise ValueError('invalid_player_state_source')
        if at - when <= 1 and fact['temporal_scope'] in ('observed_sample', 'personal_native_observation'):
            own_status[field] = dict(value=fact['value'], fact_id=fid, observed_at_seconds=when)
    native = own_status.get('personal_client_state')
    life = 'unknown'
    if native:
        life = 'dead_at_sample' if native['value']['is_dead'] else 'alive_at_sample'
    # A measured proximity query for local contact, never a skill range or a threat proof.
    search_radius = 1500
    close = next((r for r in opponents if r['sampled_gap_world_units'] <= search_radius), None)
    dead_now = (life == 'dead_at_sample' and native['observed_at_seconds'] == at)
    focus = close if not dead_now else None
    target = next((s for entity, _, s in seen if focus and entity == focus['entity_id']), None)
    return dict(self_state=own_status, self_path_sample=origin, recent_public_kills=public_kills,
                kill_feed_scope=('本局未接入公开击杀来源。空列表不能说明无人阵亡。'
                    if frame.get('unknowns',{}).get('recent_champion_kills') else
                    '只列本帧可引用的公开播报。追击对象被击杀后须重查，复活时刻另证。'),
                life_state=life, unverified=['QWE_remaining_cooldowns','summoner_remaining_cooldowns',
                                              'action_lock_or_crowd_control','route_and_ally_arrival'],
                local_search_radius_world_units=search_radius, local_contact_to_check=focus,
                immediate_action_gate='cannot_move_or_cast_while_dead' if dead_now else 'check_conditions',
                position_status=('missing' if origin is None else 'stale' if origin['age_seconds'] > 1 else 'recent'),
                opponents_by_sampled_gap=opponents, allies_by_sampled_gap=teammates,
                allies_by_gap_to_nearest_opponent=ranked_samples(target, allies),
                interpretation='先检查本人的血蓝、等级和关键技能。按一秒内可见起点间距筛查威胁和接应者。'
                               '阵亡时先看复活倒数与出门选择。血蓝条为像素估计区间；R 图标的冷却遮罩'
                               '不提供精确秒数。客户端补刀显示精度未经验证。距离仅供排序，施法与到场另查。')
