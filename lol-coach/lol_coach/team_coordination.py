"""Evidence for deciding whom this player should coordinate with on this frame."""
from math import dist

from .player_action import actor_context, allied_paths, ranked_samples
from .reasoning_frame import lookup_reference, number
from .replay_pings import TEAM_CHANNEL_KINDS
from .review_pings import player_ping_context
from .review_sightings import enemy_sightings
from .round_chain import _check_bundle, _source


# Coaching presentation windows. Neither is a game mechanic or a signal cooldown.
SIGNAL_REVIEW_SECONDS = 8
CONTACT_COMPARISON_SECONDS = 30
# A routine vision or missing marker remains available to the main lane review.
COORDINATED_ACTION_PINGS = frozenset(('assist_me', 'on_my_way', 'retreat', 'push', 'all_in'))


def _scene(frame):
    sight = enemy_sightings(frame)
    paths = allied_paths(frame)
    context = actor_context(frame, sight, paths)
    kills = {}
    for row in context['recent_public_kills']:
        fid = row['fact_id']
        actor = frame['facts'][fid]['value']['victim_entity_id']
        kills[actor, row['at_seconds']] = fid
    opponents = {row['entity_id']: row for row in sight['opponents']}
    radius = context['local_search_radius_world_units']
    near_allies = {row['entity_id']: row for row in context['allies_by_sampled_gap']
                   if row['sampled_gap_world_units'] <= radius}
    opponent_gaps = {row['entity_id']: row for row in context['opponents_by_sampled_gap']}
    near_opponents = {actor: row for actor, row in opponent_gaps.items()
                      if row['sampled_gap_world_units'] <= radius}
    pings = player_ping_context(frame)['events'] if 'recent_team_pings' in frame else []
    return dict(near_allies=near_allies, near_opponents=near_opponents, opponents=opponents,
                radius=radius, paths=paths, kills=kills, pings=pings, opponent_gaps=opponent_gaps,
                action_gate=context['immediate_action_gate'])


def signal_point_at(event, cutoff):
    region = event.get('marker_region') or {}
    if event.get('marker_xz') is not None:
        return event['marker_xz']
    if region.get('observed_through_seconds', float('inf')) <= cutoff:
        return region.get('xz_rounded_to_100')
    return None


def novel_team_signal(history, sender, kind, when, point):
    """Collapse consecutive calls of one kind in one area, including interleaved types."""
    key = sender, kind
    previous = history.get(key)
    if previous and when < previous[0]:
        return False
    history[key] = when, point
    return (previous is None or when - previous[0] > SIGNAL_REVIEW_SECONDS
            or bool(point and previous[1] and dist(point, previous[1]) > 300))


def coordination_trigger(bundle, previous_bundle=None):
    """Select meaningful changes for this player's card. Never open on lane counts or proximity alone."""
    frame = _check_bundle(bundle)
    d = frame['decision']
    at = d['at_seconds']
    prev = None
    since = -1
    if previous_bundle is not None:
        before = _check_bundle(previous_bundle)
        prior = before['decision']
        if (_source(previous_bundle) != _source(bundle)
                or any(prior[k] != d[k] for k in ('observer_team_id', 'player_entity_id', 'build'))
                or prior['at_seconds'] >= at):
            raise ValueError('coordination_trigger_previous_scope_mismatch')
        prev, since = _scene(before), prior['at_seconds']

    now = _scene(frame)
    reasons, refs = [], []
    def record(reason, fact_ids):
        if reason not in reasons:
            reasons.append(reason)
        for fid in fact_ids:
            if fid not in refs:
                refs.append(fid)

    previous_by_sender_and_kind = {}
    for event in ((prev['pings'] if prev else []) + now['pings']):
        when, sender = event['sent_at_seconds'], event['sender_entity_id']
        is_new = novel_team_signal(previous_by_sender_and_kind, sender, event['kind'], when,
                                   signal_point_at(event, at))
        if (not is_new or event['available_at_seconds'] <= since
                or at - when > SIGNAL_REVIEW_SECONDS):
            continue
        if event['kind'] in COORDINATED_ACTION_PINGS and event['known_as'] == 'own_sent':
            record('new_personal_team_signal', [event['fact_id']])
        elif (event['kind'] in ('assist_me', 'retreat') and event['known_as'] == 'delivered_to_player'
              and sender in now['near_allies']):
            record('nearby_ally_request_delivered', [event['fact_id'], *now['near_allies'][sender]['fact_refs']])

    # Filter by new membership in the readable feed. The event clock can precede the
    # previous pause while the public announcement first becomes readable on this one.
    close_previous = prev is not None and at - since <= SIGNAL_REVIEW_SECONDS
    for (victim, when), fid in now['kills'].items():
        if at - when > SIGNAL_REVIEW_SECONDS or (prev and (victim, when) in prev['kills']):
            continue
        local = now['near_allies'].get(victim)
        # Positions refreshed well after death can refer to the fountain.
        current_local = local and max(local['sampled_at_seconds']) <= when + 1
        prior_local = prev['near_allies'].get(victim) if close_previous else None
        if current_local or (prior_local and max(prior_local['sampled_at_seconds']) <= when + 1):
            record('local_ally_death_became_known', [fid, *(local['fact_refs'] if current_local else [])])

    if prev and at - since <= CONTACT_COMPARISON_SECONDS and now['action_gate'] == 'check_conditions':
        roles = frame['task'].get('roam_actors') or {}
        duel = frame['task'].get('bottom_lane_actors') or {}
        lane_opponents = {duel.get('enemy_support'), duel.get('enemy_carry')}
        for actor, row in now['near_opponents'].items():
            old = prev['opponents'].get(actor)
            if actor in prev['near_opponents'] or actor in lane_opponents or not old:
                continue
            if old['visible'] is not False and actor not in prev['opponent_gaps']:
                continue
            # A single opposing laner reappearing from brush is routine. Require an
            # identified incoming jungler, or an extra opponent beyond a duo.
            if (actor != roles.get('enemy_jungle') and not
                    (len(now['near_opponents']) >= 3 and len(now['near_opponents']) > len(prev['near_opponents']))):
                continue
            enemy_sample = now['opponents'][actor]['last_observed_path_start']
            for ally_id, ally in now['near_allies'].items():
                if any(victim == ally_id for victim, _ in now['kills']):
                    continue
                if dist(now['paths'][ally_id]['xz'], enemy_sample['xz']) <= now['radius']:
                    record('new_local_opponent_affects_ally', [*row['fact_refs'], *ally['fact_refs']])
                    break
    return dict(active=bool(reasons), reasons=reasons, fact_ids=refs)


def _recent_pings(bundle, plan):
    """Keep personal send/delivery facts separate from unconfirmed channel sends."""
    pings = plan.get('team_pings', {})
    events = pings.get('events', [])
    result = dict(coverage=pings.get('coverage', 'unavailable'),
                  window_start_seconds=pings.get('window_start_seconds'),
                  personal_event_count=len(events), personal_events=[], team_channel_sends=[],
                  channel_reference_id=None, team_channel_send_count=0)
    # Full personal events and marker regions remain in plan.team_pings.
    for row in events[-8:]:
        result['personal_events'].append({key: row[key] for key in
            ('fact_id', 'kind', 'sender_entity_id', 'known_as', 'sent_at_seconds', 'available_at_seconds')})
    lookup = pings.get('team_channel_lookup')
    if not lookup:
        return result
    rid = lookup['reference_id']
    body = lookup_reference(bundle, rid)
    at = plan['at_seconds']
    team = plan['observer_team_id']
    player = plan['player_entity_id']
    members = {ally['entity_id'] for ally in plan['allies']}
    if (body['observer_team_id'] != team or body['player_entity_id'] != player
            or body['through_seconds'] != at or body['window_start_seconds'] != pings['window_start_seconds']
            or body['scope'] != 'allied_team_channel_sends_only_personal_receipt_unknown'):
        raise ValueError('coordination_channel_scope_mismatch')
    for event in body['events']:
        when = event['sent_at_seconds']
        if (event['sender_entity_id'] not in members or event['kind'] not in TEAM_CHANNEL_KINDS
                or event['personal_receipt'] != 'unknown' or not number(when)
                or not body['window_start_seconds'] <= when <= at):
            raise ValueError('invalid_coordination_channel_event')
    result.update(channel_reference_id=rid, team_channel_send_count=len(body['events']),
                  team_channel_sends=[{key: event[key] for key in
                      ('sender_entity_id', 'sent_at_seconds', 'kind', 'personal_receipt')}
                      for event in body['events'][-8:]])
    return result


def team_coordination(bundle, plan, resource_windows):
    frame = bundle['frame']
    context = plan['player_action_context']
    recent_kills = {}
    for row in context['recent_public_kills']:
        fact = frame['facts'][row['fact_id']]
        victim = fact['value']['victim_entity_id']
        if victim not in recent_kills or row['at_seconds'] > recent_kills[victim]['at_seconds']:
            recent_kills[victim] = dict(at_seconds=row['at_seconds'], fact_id=row['fact_id'])

    def newer_than_kill(actor, sample):
        return sample and (actor not in recent_kills or sample['sampled_at'] > recent_kills[actor]['at_seconds'])

    # A recipient on the far side of the map may need a warning even when
    # the player cannot help in person. Rank threats from the recipient's origin.
    seen = []
    for opponent in plan['opponents']:
        actor = opponent['entity_id']
        sample = opponent['last_observed_path_start']
        if opponent['visible'] is True and newer_than_kill(actor, sample):
            seen.append((actor, opponent['champion'], dict(sample, fact_id=opponent['fact_id'])))

    me = plan['player_entity_id']
    self_sample = plan['player_last_observed_path_start']
    use_own_position = (newer_than_kill(me, self_sample)
                        and context['immediate_action_gate'] != 'cannot_move_or_cast_while_dead')
    own_gaps = {row['entity_id']: row for row in context['allies_by_sampled_gap']} if use_own_position else {}
    members = []
    for ally in plan['allies']:
        actor = ally['entity_id']
        sample = ally['last_observed_path_start']
        valid_sample = newer_than_kill(actor, sample)
        near = ranked_samples(sample, seen) if valid_sample else []
        contact = next((row for row in near if row['sampled_gap_world_units'] <=
                        context['local_search_radius_world_units']), None)
        if contact:
            contact['sample_age_seconds'] = [plan['at_seconds'] - t for t in contact['sampled_at_seconds']]
            contact['latest_public_death'] = recent_kills.get(contact['entity_id'])
        gap = own_gaps.get(actor) if valid_sample else None
        members.append(dict(entity_id=actor, champion=ally['champion'],
                            position_fact_id=sample['fact_id'] if sample else None,
                            position_age_seconds=sample['age_seconds'] if sample else None,
                            gap_to_player_world_units=gap['sampled_gap_world_units'] if gap else None,
                            gap_fact_refs=gap['fact_refs'] if gap else [],
                            visible_contact_near_ally=contact, latest_public_death=recent_kills.get(actor),
                            followup_availability='recheck_after_reported_death' if actor in recent_kills else 'unconfirmed',
                            latest_observed_action=next(reversed(ally['observed_actions']), None)))
    return dict(schema='team-coordination/v1', allies=members,
                player_physical_action_gate=context['immediate_action_gate'],
                recent_team_pings=_recent_pings(bundle, plan), resource_windows=resource_windows,
                response_status='unknown',
                decision_cues=[
                    '只在队友能改变这一手、需要提前避险、或你离开会让他失去接线或接应时考虑沟通。',
                    '只告诉受影响的人此刻可知的事实、你的计划和他需要做的一件事。查已有信号，再决定是否要补充地点或时机。',
                    '样点间距只用于发现该看谁。已播报阵亡的队友即使有后来坐标，仍需确认复活和可接应性。队伍显隐不能证明队友已经注意。',
                    '此前的信号和实际观察到的动作分别引用。按下一手不可撤销的时刻重查；未得到可用接应，执行本人能做的备选。'])
