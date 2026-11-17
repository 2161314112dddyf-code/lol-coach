"""Project only evidenced, perspective-bound ping communications into a decision frame."""
from math import dist, isfinite

from .replay_pings import CHANNEL_REFERENCE, TEAM_CHANNEL_KINDS

PING_TYPES = {'assist_me': '协助我', 'on_my_way': '正在路上', 'enemy_missing': '敌人不见踪影',
              'all_in': '全力进攻', 'command': '常规指令标记', 'enemy_vision': '敌方视野',
              'get_back': '后撤提醒', 'need_vision': '需要视野', 'push': '推进', 'retreat': '撤退'}


def _time(value):
    return type(value) in (float, int) and isfinite(value) and value >= 0


def _add_observed_region(value, source, row, at):
    region = row.get('marker_region')
    if region is None:
        return
    end = region.get('observed_through_seconds')
    if not _time(end) or end < row['time_seconds'] or not row.get('marker_report_sha256'):
        raise ValueError('invalid_ping_region_provenance')
    if end <= at:
        value['marker_region'] = region.copy()
        source['hud_report_sha256'] = row['marker_report_sha256']


def add_player_pings(frame, references, library, audit, index, replay_sha256, window, add):
    from .reasoning_frame import digest

    decision = frame['decision']
    at, team, player = (decision[k] for k in ('at_seconds', 'observer_team_id', 'player_entity_id'))
    if (index.get('schema') != 'review-ping-index/v1'
            or not replay_sha256 or index.get('source_sha256') != replay_sha256):
        raise ValueError('ping_index_does_not_match_replay')
    if not _time(window):
        raise ValueError('invalid_ping_window_seconds')
    allies = {h['entity_id'] for h in frame['lineup'] if h['relation'] == 'ally'}
    start = max(0, at-window)
    fact_ids = []
    occurrences = {}
    channel_entries = []
    status = index.get('status')
    if status not in ('verified', 'unsupported_replay'):
        raise ValueError('invalid_ping_index_status')
    if status == 'unsupported_replay':
        frame['recent_team_pings'] = dict(window_start_seconds=start, fact_ids=[], coverage='unsupported_replay')
        return
    if index.get('build') != decision['build']:
        raise ValueError('ping_index_does_not_match_replay')
    for row in index.get('events', []):
        sent = row.get('time_seconds')
        sender = row.get('sender_entity_id')
        kind = row.get('kind')
        if (not _time(sent) or not start <= sent <= at or row.get('team_id') != team
                or sender not in allies or kind not in PING_TYPES):
            continue
        known_as = 'own_sent'
        available = sent
        if sender != player:
            delivery = row.get('delivery') or {}
            if delivery.get('scope') == 'player' and delivery.get('player_entity_id') == player:
                known_as = 'delivered_to_player'
            elif delivery.get('scope') == 'team' and delivery.get('team_id') == team:
                known_as = 'delivered_to_team'
            if known_as == 'own_sent' or (not _time(delivery.get('at_seconds'))
                    or not sent <= delivery['at_seconds'] <= at or not delivery.get('source')):
                if row.get('source') and kind in TEAM_CHANNEL_KINDS and row.get('channel') == 'team':
                    message = dict(sender_entity_id=sender, kind=kind, label=PING_TYPES[kind],
                                   sent_at_seconds=sent, age_seconds=at-sent, personal_receipt='unknown')
                    evidence = row['source'].copy()
                    _add_observed_region(message, evidence, row, at)
                    channel_entries.append((message, evidence))
                continue
            available = delivery['at_seconds']
        if not row.get('source'):
            continue
        value = dict(kind=kind, observer_team_id=team, known_as=known_as,
                     available_at_seconds=available)
        if known_as == 'delivered_to_player':
            value['recipient_entity_id'] = player
        point = row.get('marker_xz')
        if isinstance(point, list) and len(point) == 2 and all(type(v) in (float, int) and isfinite(v) for v in point):
            value['marker_xz'] = point
        source = {'send': row['source']}
        _add_observed_region(value, source, row, at)
        if sender != player:
            source['delivery'] = delivery['source']
        same_signal = (sender, kind, sent)
        occurrence = occurrences.get(same_signal, 0) + 1
        occurrences[same_signal] = occurrence
        if occurrence > 1:
            value['occurrence_at_tick'] = occurrence
        fid = add(sender, 'map_ping_sent', value, sent, 'communication_event', source=source)
        fact_ids.append(fid)
    frame['recent_team_pings'] = dict(window_start_seconds=start, fact_ids=fact_ids,
                                     coverage='verified_events_only')
    if channel_entries:
        channel_entries.sort(key=lambda pair: (pair[0]['sent_at_seconds'], pair[0]['sender_entity_id'], pair[0]['kind']))
        channel = dict(observer_team_id=team, player_entity_id=player, through_seconds=at,
                       window_start_seconds=start, events=[e for e, _ in channel_entries], player_attention='unknown',
                       channel_rules_source=CHANNEL_REFERENCE,
                       response_to_ping='unknown', scope='allied_team_channel_sends_only_personal_receipt_unknown')
        rid = 'team_channel_' + digest(channel)
        references[rid] = dict(kind='allied_channel_messages_personal_receipt_unknown', content_sha256=digest(channel))
        library[rid] = channel
        audit[rid] = dict(send_records_in_display_order=[source for _, source in channel_entries])
        frame['recent_team_pings']['channel_reference'] = rid


def player_ping_context(frame):
    observation = frame['recent_team_pings']
    team = frame['decision']['observer_team_id']
    player = frame['decision']['player_entity_id']
    at = frame['decision']['at_seconds']
    allies = {hero['entity_id'] for hero in frame['lineup'] if hero['relation'] == 'ally'}
    rows = []
    for fid in observation['fact_ids']:
        fact = frame['facts'][fid]
        value = fact['value']
        sender, known_as = fact['entity_id'], value['known_as']
        sent, available = fact['observed_at_seconds'], value['available_at_seconds']
        if (fact['field'] != 'map_ping_sent' or fact['temporal_scope'] != 'communication_event'
                or sender not in allies or value['observer_team_id'] != team or value['kind'] not in PING_TYPES
                or not observation['window_start_seconds'] <= sent <= available <= at
                or known_as not in ('own_sent', 'delivered_to_player', 'delivered_to_team')
                or known_as == 'own_sent' and sender != player
                or known_as == 'delivered_to_player' and value.get('recipient_entity_id') != player):
            raise ValueError('ping_outside_player_scope')
        rows.append(dict(fact_id=fid, sender_entity_id=fact['entity_id'], sent_at_seconds=fact['observed_at_seconds'],
                         age_seconds=fact['age_seconds'], label=PING_TYPES[value['kind']], **value))
    rows.sort(key=lambda r: (r['sent_at_seconds'], r['fact_id']))
    result = dict(window_start_seconds=observation['window_start_seconds'], through_seconds=frame['decision']['at_seconds'],
                coverage=observation['coverage'], events=rows, player_attention='unknown', response_to_ping='unknown',
                interpretation='信号记录发送者表达的意思。marker_region 是原版画面估出的标记区域。判断队友是否接应、敌人是否消失或本人是否注意到，须结合各自的局内证据。')
    if 'channel_reference' in observation:
        result['team_channel_lookup'] = dict(reference_id=observation['channel_reference'], tool='get_reference',
                                              scope='team_channel_sends_only_personal_receipt_unknown')
    return result


def attach_own_assist_path(bundle):
    """Expose only the sender's own last order for a personal assist marker."""
    from .reasoning_frame import digest

    frame = bundle['frame']
    actor = frame['decision']['player_entity_id']
    facts = frame['facts']
    sends = (facts[fid] for fid in frame.get('recent_team_pings', {}).get('fact_ids', []))
    if not any(f['entity_id'] == actor and f['value'].get('kind') == 'assist_me'
               and f['value'].get('known_as') == 'own_sent' and f['value'].get('marker_region') for f in sends):
        return
    for fid in frame.get('allied_path_fact_ids', []):
        start = facts[fid]
        if start['entity_id'] != actor:
            continue
        source = bundle['audit']['fact_sources'][fid]
        packet = source.get('packet_path')
        if not packet:
            return
        fact = {**start, 'field': 'own_movement_order_sample',
                'value': dict(start_fact_id=fid, speed_world_per_second=packet['speed'], waypoints_xz=packet['xz']),
                'temporal_scope': 'historical_command_sample'}
        key = 'f_' + digest(fact)[:20]
        facts[key] = fact
        frame['own_assist_path_fact_ids'] = [key]
        bundle['audit']['fact_sources'][key] = dict(source=source['source'], basis='same_live_path_as_start')
        return


def _own_travel(frame, origin, centre, external, self_state):
    from .action_evidence import conditional_travel
    from .movement_1622 import VERSION
    from .round_options import _checked_facts

    decision = frame['decision']
    actor = decision['player_entity_id']
    hero = next(h for h in frame['lineup'] if h['entity_id'] == actor)
    patch = (external or {}).get('champions', {}).get(hero['champion'], {})
    result = dict(start_fact_id=origin['fact_id'], sampled_at_seconds=origin['sampled_at'],
                  sample_age_seconds=origin['age_seconds'], start_xz=origin['xz'],
                  start_evidence='recent_sample' if origin['age_seconds'] <= 1 else 'stale_sample',
                  target='estimated_marker_centre', guaranteed_arrival_seconds=None,
                  actual_route_to_marker=None, latest_order=None, walk_scenario=None)
    gap = dist(origin['xz'], centre)
    result['centre_distance_world_rounded_to_100'] = round(gap / 100) * 100
    rows = list(_checked_facts(frame, 'own_assist_path_fact_ids'))
    if len(rows) > 1:
        raise ValueError('ambiguous_personal_assist_order')
    speed = None
    if rows:
        fid, fact = rows[0]
        val = fact['value']
        points, speed = val['waypoints_xz'], val['speed_world_per_second']
        if (fact['entity_id'] != actor or fact['field'] != 'own_movement_order_sample'
                or fact['temporal_scope'] != 'historical_command_sample' or fact['unit'] != 'map11_world_xz'
                or val['start_fact_id'] != origin['fact_id'] or fact['observed_at_seconds'] != origin['sampled_at']
                or not isinstance(points, list) or not points or points[0] != origin['xz']
                or any(not isinstance(p, list) or len(p) != 2 or
                       any(type(n) not in (int, float) or not isfinite(n) for n in p) for p in points)
                or not _time(speed)):
            raise ValueError('invalid_personal_assist_order')
        order = dict(fact_id=fid, point_count=len(points), endpoint_xz=points[-1], packet_speed_world_per_second=speed,
                     endpoint_gap_to_marker_rounded_to_100=round(dist(points[-1], centre) / 100) * 100,
                     kind='ordered_waypoints' if len(points) > 1 else 'single_position_sample',
                     constant_speed_seconds_from_packet=None)
        if len(points) > 1 and speed > 0:
            order['constant_speed_seconds_from_packet'] = round(conditional_travel(points, speed)['duration_seconds'], 2)
        result['latest_order'] = order
    if speed and speed > 0:
        walk = conditional_travel([origin['xz'], centre], speed)
        result['walk_scenario'] = dict(seconds_from_sampled_start=round(walk['duration_seconds'], 1),
                                      speed_world_per_second=speed, speed_basis='own_packet_at_sample',
                                      requires='从采样起点直接走向估计圈心，沿途可通行、速度恒定，无位移、停顿或改令。')
    rank_ranges = patch.get('abilities', {}).get('R', {}).get('range_by_rank', [])
    if (hero['champion'] == 'Pantheon' and decision['build'] == VERSION and patch.get('static_version') == '16.22.1'
            and patch.get('abilities', {}).get('R', {}).get('id') == 'PantheonR'
            and len(rank_ranges) == 3 and all(_time(v) and v > 0 and v == rank_ranges[0] for v in rank_ranges)):
        radius = rank_ranges[0]
        shortfall = max(0, gap - radius)
        hud = self_state.get('personal_hud_state', {})
        indicator = hud.get('value', {}).get('R_indicator')
        client = self_state.get('personal_client_state', {})
        if client.get('observed_at_seconds') == decision['at_seconds'] and client['value']['is_dead']:
            gate = 'cannot_cast_while_dead'
        elif origin['age_seconds'] > 1:
            gate = 'refresh_own_position_before_range_check'
        elif indicator == 'cooldown_sweep_visible':
            gate = 'cooldown_overlay_at_hud_sample'
        elif indicator != 'lit_no_visible_cooldown_overlay':
            gate = 'verify_R_availability'
        elif shortfall:
            gate = 'approach_or_choose_nearer_landing'
        else:
            gate = 'check_legal_landing_channel_and_ally_followup'
        result['pantheon_R'] = dict(range_world=radius, static_version=patch['static_version'],
            range_source=patch.get('source'), hud_indicator=indicator, hud_fact_id=hud.get('fact_id'),
            decision_check=gate,
            centre_geometry_from_sample='inside' if gap <= radius else 'outside',
            minimum_approach_world_from_sample_rounded_to_100=round(shortfall / 100) * 100,
            ideal_walk_seconds_to_range_from_sample=round(shortfall / speed, 1) if speed and speed > 0 else None,
            cast_confirmed=None, channel_to_landing_seconds=None, landing_at_seconds=None,
            recheck='从本人当前位置重新选合法落点，核实能施法、能完成引导、落地时目标仍在且队友能接。')
    result['interpretation'] = ('直线算例与已下发的路径分别从包的起点计时。单点不给后续走法；'
                                '旧位置须重查。标点取整且有画面估读误差，实走和 R 落地时间未知。')
    return result


def assist_distances(pings, lineup, allied_positions, opponents, *, frame=None, external=None, self_state=None):
    """Distances to the latest observed personal assist ring, from current-side samples only."""
    event = next((row for row in reversed(pings['events']) if row['kind'] == 'assist_me'
                  and row['known_as'] == 'own_sent' and 'marker_region' in row), None)
    if event is None:
        return None
    centre = event['marker_region']['xz_rounded_to_100']
    by_actor = {row['entity_id']: (row['last_observed_path_start'], row['fact_id'])
                for row in opponents if row['visible'] is True}
    if frame:
        from .round_options import _checked_facts
        for _, fact in _checked_facts(frame, 'recent_public_combat_ids'):
            if fact['field'] == 'public_kill_feed':
                victim = fact['value']['victim_entity_id']
                sample, _ = by_actor.get(victim, (None, None))
                if sample and sample['sampled_at'] <= fact['observed_at_seconds']:
                    del by_actor[victim]
    for actor, sample in allied_positions.items():
        by_actor[actor] = (sample, sample['fact_id'])
    nearby = []
    for hero in lineup:
        actor = hero['entity_id']
        sample, fid = by_actor.get(actor, (None, None))
        if not sample or sample['age_seconds'] > 1:
            continue
        nearby.append(dict(champion=hero['champion'], relation=hero['relation'], entity_id=actor,
                           distance_world_rounded_to_100=round(dist(centre, sample['xz']) / 100)*100,
                           sampled_at=sample['sampled_at'], age_seconds=sample['age_seconds'], fact_id=fid))
    nearby.sort(key=lambda row: (row['distance_world_rounded_to_100'], row['entity_id']))
    result = dict(ping_fact_id=event['fact_id'], marker_region=event['marker_region'], actors=nearby,
                reference_time=pings['through_seconds'], maximum_position_age_seconds=1,
                interpretation='各人最近一秒的路径起点与标点的直线距离，单位取整到百。'
                               '只列本队和本队当前可见的对手；到场、意愿与能否出手另查。')
    if frame and event['marker_region'].get('map_id') == 11:
        origin = allied_positions.get(frame['decision']['player_entity_id'])
        if origin:
            result['personal_travel'] = _own_travel(frame, origin, centre, external, self_state or {})
    return result
