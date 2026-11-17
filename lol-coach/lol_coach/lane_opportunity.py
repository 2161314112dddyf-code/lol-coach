"""Compare pressure, a trade, and leaving bottom from the selected support's frame."""
import json
from math import dist
from pathlib import Path

from .movement_1622 import VERSION
from .reasoning_frame import digest, number
from .round_options import _checked_facts, _lane_observation, compare_round_options


_ROLES = {'support': 'ally', 'carry': 'ally', 'enemy_support': 'enemy', 'enemy_carry': 'enemy'}
_MATCHUP = {'support': 'Pantheon', 'carry': 'Caitlyn', 'enemy_support': 'TahmKench', 'enemy_carry': 'KogMaw'}
_ROAM_ROLES = {'ally_mid': 'ally', 'ally_top': 'ally', 'ally_jungle': 'ally',
               'enemy_mid': 'enemy', 'enemy_top': 'enemy', 'enemy_jungle': 'enemy'}
# Static marker extracted by minimap_assets from the 16.22 Map11 locator table.
_LOWER_RIVER = dict(locator='DragonEelCamp', xz=[10500, 5170], map_id=11, build=VERSION,
                    config_path='data/maps/shipping/map11/map11.bin',
                    config_sha256='cddcfa0a51b90ecfed85f6cc3ebaeb5efa99a449c93312c2017ce84e7945c684')
_MECHANICS = {
    'Pantheon': ('a6b29691bc47c346a8dcbf33cca25fb63e4aea8a0ca9af7e720fb386e74001f4',
                 'W 指向目标跃击并眩晕。资料标注施法距离 600。'),
    'Caitlyn': ('90fe7ba492c8b8f49cbe5f24a9499658b61ee329587d85ad9dcc3158c1cdd0d9',
                'W 夹子需要敌方英雄踩中，触发后束缚并提供强化爆头。'),
    'KogMaw': ('3bd9cfbbad307895c38f8249d2c1f69b498a15609a6eb680570511182827e612',
               'W 生效期间普攻获得额外射程，附带基于目标最大生命值的魔法伤害。'),
    'TahmKench': ('282564f1357433d85de1acf02758fe09b73b28b6a67cf1d27608ccaf92a0e474',
                  'Q 减速，命中已有三层被动的英雄时可晕眩。W 区域击飞。R 可吞入友方英雄并给盾。'),
}


def _actor_observations(frame, actors, heroes, sightings, allied_samples):
    seen = {r['entity_id']: r for r in sightings['opponents']}
    result = {}
    for role, actor in actors.items():
        sight = seen.get(actor)
        visible = True if heroes[actor]['relation'] == 'ally' else sight['visible']
        path = allied_samples.get(actor) if sight is None else sight['last_observed_path_start']
        if path and sight:
            path = dict(path, fact_id=sight['fact_id'])
        samples = {}
        if visible is True:
            for fid in heroes[actor]['current_fact_ids']:
                fact = frame['facts'][fid]
                if (fact['field'] in ('level', 'health', 'max_health', 'resource', 'max_resource')
                        and fact['temporal_scope'] == 'observed_sample' and fact['entity_id'] == actor):
                    when = fact['observed_at_seconds']
                    if (fid != 'f_' + digest(fact)[:20] or fact['field'] in samples or not number(fact['value'])
                            or not 0 <= when <= fact.get('available_at_seconds', when) <= sightings['at_seconds']):
                        raise ValueError('invalid_bottom_lane_stat_sample')
                    samples[fact['field']] = dict(value=fact['value'], sampled_at=when, fact_id=fid)
        result[role] = dict(visible=visible, visibility_fact_id=sight['fact_id'] if sight else None,
                            last_path_start=path, stat_samples=samples)
    return result


def _sample_gap(a, b):
    if not all(p['visible'] is True and p['last_path_start'] and p['last_path_start']['age_seconds'] <= 1
               for p in (a, b)):
        return None
    first, second = a['last_path_start'], b['last_path_start']
    return dict(sampled_gap_world_units=round(dist(first['xz'], second['xz']), 1),
                sampled_at_seconds=[first['sampled_at'], second['sampled_at']],
                fact_refs=[first['fact_id'], second['fact_id']])


def _nearby_opponents(carry, sightings):
    measured = []
    missing = []
    for row in sightings['opponents']:
        sample = row['last_observed_path_start']
        gap = _sample_gap(carry, dict(visible=row['visible'], last_path_start=(
            dict(sample, fact_id=row['fact_id']) if sample else None)))
        if gap is None:
            missing.append(row['entity_id'])
        else:
            measured.append(dict(entity_id=row['entity_id'], champion=row['champion'], **gap))
    measured.sort(key=lambda r: (r['sampled_gap_world_units'], r['entity_id']))
    return dict(by_sampled_gap=measured, without_recent_pair=missing,
                interpretation='按与己方射手的可见路径起点间距排序。最近的可见对手可能来自其他路。是否已经出手需另查施法或伤害记录。')


def _matchup(at, build, champions, observations):
    if build != VERSION or champions != _MATCHUP:
        return None
    level = observations['enemy_support']['stat_samples'].get('level')
    phase = 'unknown'
    if level and level['sampled_at'] == at and type(level['value']) in (int, float) and level['value'] in range(1, 19):
        phase = 'below_six_observed' if level['value'] < 6 else 'six_or_higher_observed'
    sources = {champ: dict(url=f'https://ddragon.leagueoflegends.com/cdn/16.22.1/data/zh_CN/champion/{champ}.json',
                           sha256=sha, mechanism=mechanism) for champ, (sha, mechanism) in _MECHANICS.items()}
    return dict(build=build, static_version='16.22.1', sources=sources,
                tahm_level_phase=phase, tahm_level_fact_ref=level['fact_id'] if level else None,
                pre_six_plan='若确认塔姆还没到六，留住可用的 W 给大嘴压力。看他会不会为了补刀向前走，同时防塔姆 Q 减速、W 击飞。',
                from_six_plan='塔姆到六后再查吞人的角度、是否已学和能否使用。如果他能吞大嘴，要重算女警后续的输出时间。',
                cast_readiness=None, ally_trap_trigger=None, enemy_rescue_ready=None)


def _roam(comparison, wave):
    clock_refs = comparison['clock_evidence_ids'] if comparison else {}
    timing = []
    for row in comparison['options'] if comparison else []:
        option = {k: row[k] for k in ('action', 'depart_at', 'arrive_at', 'finish_target_at', 'return_to_lane_at',
                                      'target_window', 'next_wave_window', 'conditions', 'evidence_ids')}
        deadline = comparison['clocks'].get('next_wave_deadline')
        returned = option['return_to_lane_at']
        option['return_margin_seconds'] = ([deadline[0]-returned[1], deadline[1]-returned[0]]
                                           if deadline is not None and returned is not None else None)
        timing.append(option)
    return dict(destination=comparison['target'] if comparison else None, wave_number=None,
                wave_evidence_id=wave['fact_id'] if wave else None,
                clock_fact_refs=clock_refs, timing_options=timing,
                conditional_time_saved=comparison['additional_objective_contribution'] if comparison else None,
                wave_candidates=[
                    dict(window='当前波落点确认后', condition='若确认兵已送进敌塔，估敌方处理这波再推回的时间。若射手回城，估她回线的位置和时间。两种情况都要查敌方拦线、越塔及沿途威胁。'),
                    dict(window='留线处理后续波', condition='若当前推不进或搭档须前压接线，先留在接应距离。下一批交汇后重新看两边兵量、交汇点和搭档动向。')],
                short_play_if='只到能及时折返的河口探信息或布眼。先确认入口的风险，以及离开后能否及时接应搭档。',
                committed_play_if='继续深入前，确认具体目标仍在、队友能先到、本人到场确实能多做什么。分别估去程、办事和回线时间。',
                gain_if='指出要去的地点、接应的人或要控制的入口、能赶上什么，以及留在下路时队友能否独立完成。计划做视野还需有可用眼位。',
                carry_cost_if='独留射手时核对下一批兵在哪里接，敌方能否控线或越塔。分别比较可能漏的补刀、经验、塔血和被迫回城的代价。',
                return_if='目标提前结束、队友退走、对方下路重新压上或回线赶不上搭档接兵时，取消深入或提前回头。',
                timing_scope='回线余量为接兵期限减去预计回线时刻，负数表示可能赶晚。出生窗口只描述我方基地。清线耗时仅对其绑定的行动者适用。')


def _river_context(frame, samples):
    # Allied path samples were validated as map11_world_xz by the caller.
    if frame['decision']['build'] != VERSION or not frame.get('allied_path_fact_ids'):
        return None
    gaps = {}
    for role in ('support', 'ally_jungle', 'enemy_jungle', 'enemy_mid'):
        row = samples.get(role)
        path = row['last_path_start'] if row and row['visible'] is True else None
        if path and path['age_seconds'] <= 1:
            gaps[role] = dict(sampled_gap_world_units=round(dist(path['xz'], _LOWER_RIVER['xz']), 1),
                              sampled_at=path['sampled_at'], fact_id=path['fact_id'])
    wards = []
    for fid, fact in _checked_facts(frame, 'vision_fact_ids'):
        if (fact['field'] == 'allied_ward_last_sample' and
                fact['temporal_scope'] == 'last_position_no_removal_observed_by_cutoff'):
            v = fact['value']
            pos = v.get('xz')
            if (not isinstance(pos, list) or len(pos) != 2 or not all(number(n) for n in pos)
                    or v.get('sampled_at') != fact['observed_at_seconds']):
                raise ValueError('invalid_roam_ward_sample')
            wards.append(dict(fact_id=fid, sampled_at=v['sampled_at'], xz=list(pos),
                              sampled_gap_world_units=round(dist(pos, _LOWER_RIVER['xz']), 1)))
    return dict(static_reference=dict(_LOWER_RIVER, xz=list(_LOWER_RIVER['xz'])), sample_distances=gaps,
                nearest_registered_ward=min(wards, key=lambda w: w['sampled_gap_world_units'], default=None),
                interpretation='到下河道河蟹静态地标的直线距离，只用作地图方位。眼的位置留有采样时间。入口能否看清、河蟹是否可争和队友去向仍须核实。')


def _destination_timing(frame, target, help_seconds):
    # Destination and lower-lane return are independently scoped. A clock for
    # "dragon" cannot be inherited just because the path also touches river.
    if not frame.get('timing_fact_ids'):
        return None
    comp = compare_round_options(frame, lane='bot', target=target, help_seconds=help_seconds)
    if not comp['clock_evidence_ids']:
        return None
    return dict(target=target, clock_fact_refs=comp['clock_evidence_ids'],
                leave_now={k:comp['options'][0][k] for k in
                           ('arrive_at','finish_target_at','return_to_lane_at','target_window','next_wave_window')},
                added_time_saved=comp['additional_objective_contribution'])


def _outer_tower_distances(frame, samples, lane):
    if frame['decision']['build'] != VERSION or not frame.get('allied_path_fact_ids'):
        return None
    profile = json.loads(Path(__file__).with_name('profiles').joinpath('turret_map11_16_22.json').read_bytes())
    lane_marker = {'mid':'_L1_', 'top':'_L2_'}[lane]
    anchors = [row for row in profile['towers'] if row['role'] == 'SR_Outer' and lane_marker in row['name']]
    distances = {}
    for role in ('ally_' + lane, 'enemy_' + lane, 'enemy_jungle', 'support'):
        row = samples.get(role)
        path = row['last_path_start'] if row and row['visible'] is True else None
        if path and path['age_seconds'] <= 1:
            distances[role] = dict(sampled_at=path['sampled_at'], fact_id=path['fact_id'],
                                   by_tower=[dict(team=t['team'], gap_world_units=round(dist(path['xz'], t['xz']), 1))
                                             for t in anchors])
    return dict(geometry_sha256=profile['geometry_sha256'],
                towers=[dict(team=t['team'], name=t['name'], xz=t['xz']) for t in anchors],
                sample_distances=distances,
                interpretation='本路双方一塔的静态位置供比较站位深浅，塔的存亡、塔下安全、路径与控制距离须另外核实。')


def _destination_comparison(frame, heroes, actors, samples, sightings, allied_samples, wave, nearby, allies, triggers):
    role_ids = frame['task']['roam_actors']
    if (not isinstance(role_ids, dict) or not role_ids.keys() <= _ROAM_ROLES.keys()
            or not all(isinstance(v, str) for v in role_ids.values())
            or len(set(role_ids.values())) != len(role_ids) or set(role_ids.values()) & set(actors.values())
            or any(heroes.get(actor, {}).get('relation') != _ROAM_ROLES[k] for k, actor in role_ids.items())):
        raise ValueError('invalid_roam_actors')
    samples = {**samples, **_actor_observations(frame, role_ids, heroes, sightings, allied_samples)}
    squad = {**actors, **role_ids}
    roster = {role:dict(entity_id=actor, champion=heroes[actor]['champion'],
                        current_observation=samples[role]) for role, actor in squad.items()}
    def gap(a, b):
        return _sample_gap(samples[a], samples[b]) if a in samples and b in samples else None

    support_gap = gap('support', 'carry')
    nearest = next(iter(nearby['by_sampled_gap']), None)
    gate = dict(closest_sampled_opponent=nearest, support_to_carry=support_gap,
                opponent_sample_closer_than_support=(nearest['sampled_gap_world_units'] < support_gap['sampled_gap_world_units']
                                                     if support_gap and nearest else None),
                wave_fact_id=wave['fact_id'] if wave else None,
                leave_condition='射手能安全接线或撤出，先算她下次被迫上前的期限。敌方能先到她的位置时先核查是否需要回接。')
    river = _river_context(frame, samples)
    candidates = {}
    def candidate(key, roles, target_geometry, extra_refs, gain_if, cancel_if):
        ids = {role:squad[role] for role in roles if role in squad}
        refs = set(extra_refs)
        for role in ids:
            row = samples[role]
            if row['visibility_fact_id']:
                refs.add(row['visibility_fact_id'])
            if row['last_path_start']:
                refs.add(row['last_path_start']['fact_id'])
        role_changes = [dict(kind=t['kind'], actor_id=t['entity_id'], change_id=t['change_id'],
                             current_fact_id=t['current_fact_id'])
                        for t in triggers if t['entity_id'] in ids.values()]
        refs.update(c['current_fact_id'] for c in role_changes)
        actions = [dict(actor_id=ally['entity_id'], **a) for ally in allies if ally['entity_id'] in ids.values()
                   for a in ally['observed_actions']]
        refs.update(a['fact_id'] for a in actions)
        timing = (None if key == 'hold_bot' else
                  _destination_timing(frame, key, frame['task']['round_comparison']['help_seconds']))
        if timing:
            refs.update(timing['clock_fact_refs'].values())
        candidates[key] = dict(actor_ids=ids, unassigned_roles=[r for r in roles if r not in ids],
                               geometry=target_geometry, fact_refs=sorted(refs), changes=role_changes,
                               observed_ally_actions=actions, timing=timing,
                               marginal_gain_if=gain_if, cancel_if=cancel_if)

    bottom_refs = [wave['fact_id']] if wave else []
    if nearest:
        bottom_refs.extend(nearest['fact_refs'])
    candidate('hold_bot', ('support','carry','enemy_carry','enemy_support','enemy_jungle'),
              dict(support_to_carry=support_gap, closest_opponent=nearest), bottom_refs,
              '若射手需要前压吃兵，留下可换她的补刀、血量与一次安全回撤；对方打野来时可以先保护射手。',
              '线已处理好、射手能安全撤出或独自接线，且别处有自己赶得上的具体任务，再比较离线。')
    river_refs = []
    if river:
        river_refs.extend(g['fact_id'] for g in river['sample_distances'].values())
        if river['nearest_registered_ward']:
            river_refs.append(river['nearest_registered_ward']['fact_id'])
    candidate('river_jungle', ('support','ally_jungle','enemy_jungle','enemy_mid'),
              dict(support_to_ally_jungle=gap('support','ally_jungle'), lower_river=river), river_refs,
              '若己方打野确实要过下河道而入口无人照应，你可先露入口或护送他撤出，少让他独探一次。若他能独立通过，再看布眼是否还能补到信息。',
              '打野改路、入口已由队友控制，或下路将在你回来前受压，就放弃深入。')
    lanes = [('mid', '中')] + ([('top', '上')] if 'ally_top' in role_ids else [])
    for lane, label in lanes:
        ally, enemy = 'ally_' + lane, 'enemy_' + lane
        lane_wave = _lane_observation(frame, lane)
        lane_refs = [lane_wave['fact_id']] if lane_wave else []
        geometry = {'support_to_' + ally:gap('support', ally), lane + '_pair':gap(ally, enemy),
                    'enemy_jungle_to_' + ally:gap('enemy_jungle', ally), lane + '_wave':lane_wave,
                    lane + '_outer_towers':_outer_tower_distances(frame, samples, lane)}
        if (frame['decision']['build'] == VERSION and heroes[actors['support']]['champion'] == 'Pantheon'
                and frame.get('allied_path_fact_ids')):
            anchor = geometry['support_to_' + ally]
            sampled_distance = (dist(samples['support']['last_path_start']['xz'], samples[ally]['last_path_start']['xz'])
                                if anchor else None)
            geometry['pantheon_r_to_ally_sample'] = dict(
                static_range=5500, unit='map11_world_xz',
                ally_sample_within_range=(sampled_distance <= 5500 if anchor else None),
                fact_refs=anchor['fact_refs'] if anchor else [],
                source='https://ddragon.leagueoflegends.com/cdn/16.22.1/data/zh_CN/champion/Pantheon.json',
                source_sha256=_MECHANICS['Pantheon'][0], learned=None, ready=None, observed_cast=None,
                check='只比较本人与队友近期采样点和 R 标注距离。若已学且可用，再看敌人实际退路、'
                      '可选落点、引导及落地前局势。到队友采样点在范围内不能证明能封住对手、及时抵达或已经开大。')
        candidate(lane + '_lane', ('support',ally,enemy,'enemy_jungle'), geometry, lane_refs,
                  f'己方{label}单能留住前压的对手时，你补控制或伤害可能多逼一个召唤师技能。若对面威胁己方{label}单，反蹲、掩护撤出或送兵进塔也可能值得。',
                  f'若你到场前交战已经结束，先核对己方{label}单还有没有被反打或越塔风险。原任务已结束且没有安全的后续任务时折返。')
        candidates[lane + '_lane']['if_fight_ends_before_arrival'] = (
            f'重新向{label}路队友确认是否需要护送撤出或处理线；若上半区确有视野空白、有眼、有人照应且赶得及接下路，再比较顺路布眼与直接回线。'
            if lane == 'top' else
            '中路交战已结束时，可看队友是否仍需掩护回城；若下路先需要你或中单自己能安全送线，立即折返。')
    return dict(actors=roster, candidates=candidates, bottom_gate=gate,
                interpretation='对每个去处先看谁需要你，再问队友自己能否办成、你到时多换什么。只从该目的地绑定的时钟比较往返和接兵期限。')


def support_lane_opportunity(frame, sightings, allied_samples, engagement, *, allies=(), triggers=(), player_context=None):
    """Host binds actual lane roles. Same-patch mechanics stay separate from replay evidence."""
    task = frame['task']
    actors = task.get('bottom_lane_actors')
    heroes = {h['entity_id']: h for h in frame['lineup']}
    if (not isinstance(actors, dict) or set(actors) != _ROLES.keys()
            or not all(isinstance(value, str) for value in actors.values()) or len(set(actors.values())) != 4
            or actors['support'] != frame['decision']['player_entity_id']
            or any(heroes.get(actors[r], {}).get('relation') != relation for r, relation in _ROLES.items())):
        raise ValueError('invalid_bottom_lane_actors')
    champions = {role: heroes[actor]['champion'] for role, actor in actors.items()}
    samples = _actor_observations(frame, actors, heroes, sightings, allied_samples)
    geometry = {f'{a}_to_{b}': _sample_gap(samples[a], samples[b]) for a, b in
                [('support', 'enemy_carry'), ('carry', 'enemy_carry'), ('support', 'carry'), ('enemy_support', 'enemy_carry')]}
    comparison_args = task.get('round_comparison')
    comparison = (compare_round_options(frame, **comparison_args)
                  if comparison_args and comparison_args['lane'] == 'bot' else None)
    wave = comparison['lane_observation'] if comparison else _lane_observation(frame, 'bot')
    d = frame['decision']
    matchup = _matchup(d['at_seconds'], d['build'], champions, samples)
    pair_matches = (engagement.get('ally_id'), engagement.get('target_id')) == (actors['carry'], actors['enemy_carry'])
    nearby = _nearby_opponents(samples['carry'], sightings)
    result = dict(schema='support-lane-opportunity/v1',
                actors={r: dict(entity_id=a, champion=champions[r]) for r, a in actors.items()},
                observations=dict(samples=samples, geometry=geometry, bottom_wave=wave,
                                  opponents_near_carry=nearby,
                                  geometry_scope='均为一秒内各自路径起点的直线间距。判断能否施法、能否补伤害及当前局部人数，须另核当时状态。'),
                matchup=matchup,
                engage=dict(target=actors['enemy_carry'], target_visible=samples['enemy_carry']['visible'],
                            common_target_window=engagement['support_window'] if pair_matches else 'unknown',
                            engagement_fact_refs=list(engagement['fact_ids'].values()) if pair_matches else [],
                            check='敌方射手为补刀走近时，查自己能用什么技能换血、搭档能否在同一目标上及时补伤害、敌辅能否救人或反开，以及换完怎么退。',
                            matchup_if=('大嘴给 W 角度且女警能接普攻或夹子，再比较打一轮后退出。若大嘴开 W 能持续追打，要把退路算进去。' if matchup else None)),
                hold=dict(check='敌方射手不进范围时，保留关键技能，站在搭档能接应处。比较压对方补刀、陪搭档处理线和防反开的收益。',
                          change_if='射手被迫向前、对方保护者露头或交出关键技能、搭档位置变了、敌兵进塔时重新判断。',
                          matchup_if=('大嘴退就守住女警能跟上的位置，让他下次补刀还要绕开 W。若他仍能用长手补刀，就重估压位的收益。若敌方转向女警，再比较留 W 接应她。' if matchup else None)),
                roam=_roam(comparison, wave))
    first = (player_context or {}).get('local_contact_to_check')
    if first:
        if first['entity_id'] != actors['enemy_carry']:
            recent_pair = (engagement.get('target_id') == first['entity_id'])
            result['engage'] = dict(target=first['entity_id'], target_visible=True, matchup_if=None,
                common_target_window=engagement['support_window'] if recent_pair else 'unknown',
                engagement_fact_refs=list(engagement['fact_ids'].values()) if recent_pair else [],
                sampled_gap=first, check='此人是本人最近可见的对手。先查是否直接威胁本人或队友，'
                                        '自己能否出手，附近队友能否接上，再决定先控、保护还是撤。')
    else:
        result['engage'].update(target=None, target_visible=None, common_target_window='unknown',
                                engagement_fact_refs=[], matchup_if=None,
                                check='暂缺本人可立即检查的近处交战对象，先核本人能否行动及可见对手距离。')
    if 'roam_actors' in task:
        result['destination_comparison'] = _destination_comparison(
            frame, heroes, actors, samples, sightings, allied_samples, wave, nearby, allies, triggers)
    return result
