"""Detect changes to a player's nearby allied minions from observed positions and removals."""
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha256
from math import dist, floor

from .hero_sight import reviewed_heroes
from .movement_1622 import MAP11_REPLAYS, VERSION, _ref, minion_birth
from .personal_episode import refresh_identity
from .reasoning_frame import digest
from .replay_container import container_info, packets
from .round_wave_clock import LANE_NAMES


ARRIVAL = 'allied_wave_reached_player'
REMOVAL = 'local_wave_group_removed'
KINDS = {ARRIVAL, REMOVAL}
# Editorial sampling thresholds in seconds and map units. They have no combat or tower semantics.
GRID_SECONDS = 2
FRESH_SECONDS = 2
LOCAL_RADIUS = 850
FAR_RADIUS = 1450
MIN_UNITS = 3


def _sample(index, actor, at, born=0):
    latest = bisect_right(index.times.get(actor, ()), at) - 1
    if latest < 0:
        return None
    row = index.rows[actor][latest]
    when = row['time_seconds']
    if when < born or at - when > FRESH_SECONDS or not row['world_waypoints_xz']:
        return None
    return dict(at=when, xz=row['world_waypoints_xz'][0], source=row['source'])


def _lane_lifetimes(raw, team):
    events = []
    for packet in packets(raw):
        if packet['stream'] != 1:
            continue
        op = packet['opcode']
        if op == 0x456:
            spawn = minion_birth(packet['payload'])
            if not spawn or spawn[0] != team:
                continue
            lane = LANE_NAMES[spawn[1]]
        elif op == 0x2e7:
            lane = None
        else:
            continue
        events.append((packet['time'], hex(packet['param']), lane, _ref(packet)))
    return sorted(events, key=lambda row: row[0])


def _scan(index, team, player, end, events):
    live, last_far, recently_near, removed = {}, {}, {}, {}
    reported_arrivals = set()
    output = []
    offset = 0
    for at in range(0, floor(end) + 1, GRID_SECONDS):
        while offset < len(events) and events[offset][0] <= at:
            when, entity, lane, source = events[offset]
            offset += 1
            if lane is not None:
                live[entity] = dict(at=when, lane=lane, source=source)
                removed.pop(entity, None)
                last_far.pop(entity, None)
                reported_arrivals.discard(entity)
            elif entity in live:
                del live[entity]
                removed[entity] = dict(at=when, source=source)
                last_far.pop(entity, None)
        own = _sample(index, player, at)
        if not own:
            continue
        local = defaultdict(dict)
        arrivals = defaultdict(dict)
        for entity, birth in live.items():
            pos = _sample(index, entity, at, birth['at'])
            if not pos:
                continue
            gap = dist(own['xz'], pos['xz'])
            lane = birth['lane']
            if gap >= FAR_RADIUS:
                last_far[entity] = dict(owner=own, unit=pos)
            if gap > LOCAL_RADIUS:
                continue
            local[lane][entity] = dict(birth=birth, unit=pos)
            previous = last_far.get(entity)
            if (previous and entity not in reported_arrivals and at - previous['unit']['at'] <= 14
                    and dist(own['xz'], previous['owner']['xz']) <= 350
                    and dist(previous['unit']['xz'], pos['xz']) >= 500):
                arrivals[lane][entity] = dict(**local[lane][entity], previous=previous)

        def record(kind, lane, units, previous_owner=None):
            output.append(dict(kind=kind, at=at, source_sha256=index.source, observer_team_id=team,
                               player_entity_id=player, lane=lane, owner=own, units=units,
                               previous_owner=previous_owner))

        for lane, units in arrivals.items():
            if len(units) >= MIN_UNITS:
                record(ARRIVAL, lane, units)
                reported_arrivals.update(units)
        for lane in list(recently_near):
            prev_at, prev_owner, group = recently_near[lane]
            if at - prev_at > 20:
                del recently_near[lane]
            elif all(e in removed and removed[e]['at'] > prev_at for e in group):
                if (len(local[lane]) < MIN_UNITS and dist(own['xz'], prev_owner['xz']) <= 650
                        and at - max(removed[e]['at'] for e in group) <= GRID_SECONDS):
                    record(REMOVAL, lane, {e: dict(**unit, removed=removed[e]) for e, unit in group.items()},
                           previous_owner=prev_owner)
                del recently_near[lane]
        for lane, group in local.items():
            if len(group) >= MIN_UNITS:
                recently_near[lane] = at, own, group
    return output


def lane_opportunities(raw, index, team, player, end):
    source = sha256(raw).hexdigest()
    info = container_info(raw)
    hero = reviewed_heroes(source).get(int(player, 16), {})
    if (source != index.source or source not in MAP11_REPLAYS or info['version'] != VERSION
            or hero.get('team_id') != team or not 0 <= end <= info['metadata']['gameLength']/1000):
        raise ValueError('lane_opportunity_scope_mismatch')
    return _scan(index, team, player, end, _lane_lifetimes(raw, team))


def add_lane_candidates(selections, changes):
    by_time = {r['at']: {**r, 'triggers': list(r.get('triggers', []))} for r in selections}
    for change in changes:
        at, kind = change['at'], change['kind']
        row = by_time.setdefault(at, dict(at=at, selected_by=[], triggers=[]))
        row['selected_by'] = sorted(set(row['selected_by']) | {kind})
        row.setdefault('triggers', []).append(change)
    return [by_time[t] for t in sorted(by_time)]


def attach_lane_change(bundle, triggers):
    frame = bundle['frame']
    decision = frame['decision']
    for event in triggers:
        kind = event.get('kind')
        if kind not in KINDS:
            continue
        at = event['at']
        if (event['source_sha256'] != bundle['audit']['source_replay_sha256']
                or event['observer_team_id'] != decision['observer_team_id']
                or event['player_entity_id'] != decision['player_entity_id'] or at != decision['at_seconds']):
            raise ValueError('lane_change_frame_mismatch')
        samples = [event['owner']]
        if event['previous_owner'] is not None:
            samples.append(event['previous_owner'])
        for unit in event['units'].values():
            if unit['birth']['lane'] != event['lane']:
                raise ValueError('lane_change_receipt_mismatch')
            samples.extend([unit['birth'], unit['unit']])
            if kind == ARRIVAL:
                samples.extend([unit['previous']['owner'], unit['previous']['unit']])
            else:
                samples.append(unit['removed'])
        if len(event['units']) < MIN_UNITS or not all(0 <= s['at'] <= at and s['source'] for s in samples):
            raise ValueError('lane_change_receipt_mismatch')
        value = dict(kind=kind, lane=event['lane'], observer_team_id=event['observer_team_id'],
                     unit_ids=sorted(event['units']), sampled_nearby_radius=LOCAL_RADIUS,
                     meaning=('同一路的这些己方兵从较远采样位置接近了本人。'
                              if kind == ARRIVAL else '刚才在本人附近采到的这组己方兵均有移除记录。')
                             + '复查原来的走法。整波是否清完、敌兵、塔和队友意图仍需另证。')
        fact = dict(entity_id=event['player_entity_id'], field='personal_lane_opportunity_change',
                    value=value, unit=None, observed_at_seconds=at, available_at_seconds=at,
                    age_seconds=0, temporal_scope='observed_local_allied_minions')
        fid = 'f_' + digest(fact)[:20]
        frame['facts'][fid] = fact
        bundle['audit']['fact_sources'][fid] = event
    return refresh_identity(bundle)
