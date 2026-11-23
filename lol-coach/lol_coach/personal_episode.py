"""Personal movement prefixes and independent, source-bound execution evidence."""
from bisect import bisect_right
from copy import deepcopy
from hashlib import sha256
from math import dist

from .movement_1622 import iter_path_samples
from .reasoning_frame import digest, number
from .replay_pings import PING_KINDS, TEAM_CHANNEL_KINDS
from .round_chain import _check_bundle, _source


ACTION_IDS = ('continue_action', 'change_action')


class PersonalPathIndex:
    def __init__(self, source, samples):
        self.source = source
        self.rows = {}
        for sample in samples:
            actor = hex(sample['entity_id'])
            self.rows.setdefault(actor, []).append(deepcopy(sample))
        self.times = {}
        for actor, rows in self.rows.items():
            rows.sort(key=lambda r: (r['time_seconds'], r['source']['chunk'],
                                    r['source']['offset'], r['source']['record_index']))
            self.times[actor] = [r['time_seconds'] for r in rows]

    @classmethod
    def from_replay(cls, raw):
        return cls(sha256(raw).hexdigest(), iter_path_samples(raw, streams=(1,)))

    def between(self, actor, start, end):
        if not number(start) or not number(end) or start > end:
            raise ValueError('invalid movement window')
        times = self.times.get(actor, [])
        return deepcopy(self.rows.get(actor, [])[bisect_right(times, start):bisect_right(times, end)])


def refresh_identity(bundle):
    frame = bundle['frame']
    frame.pop('frame_id', None)
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    return bundle


def attach_personal_history(bundle, index, window=12):
    frame = _check_bundle(bundle)
    if _source(bundle) != index.source or not number(window) or window <= 0:
        raise ValueError('personal history source or window mismatch')
    result = deepcopy(bundle)
    frame = result['frame']
    actor, at = frame['decision']['player_entity_id'], frame['decision']['at_seconds']
    for fid in frame.get('personal_history_fact_ids', []):
        frame['facts'].pop(fid, None)
        result['audit'].get('fact_sources', {}).pop(fid, None)
    rows = index.between(actor, at-window, at)
    # Bound model input, preserving temporal endpoints. Raw evidence stays in the audit.
    selected = rows if len(rows) <= 16 else [rows[round(i*(len(rows)-1)/15)] for i in range(16)]
    ids = []
    for row in selected:
        when = row['time_seconds']
        fact = dict(entity_id=actor, field='personal_movement_sample',
                    temporal_scope='historical_path_start_and_command', unit='map11_world_xz',
                    observed_at_seconds=when, available_at_seconds=when, age_seconds=at-when,
                    value=dict(start_xz=row['world_waypoints_xz'][0],
                               commanded_path_xz=row['world_waypoints_xz'], speed=row['speed']))
        fid = 'f_' + digest(fact)[:20]
        frame['facts'][fid] = fact
        result['audit'].setdefault('fact_sources', {})[fid] = deepcopy(row['source'])
        ids.append(fid)
    frame['personal_history_fact_ids'] = ids
    frame['task']['personal_history_window_seconds'] = window
    return refresh_identity(result)


def bind_personal_actions(bundle, *, team_coordination=False):
    _check_bundle(bundle)
    result = deepcopy(bundle)
    result['frame']['task']['personal_action_review'] = 'personal-actions/v1'
    if team_coordination:
        result['frame']['task']['team_coordination_review'] = 'team-coordination/v1'
    result['frame']['task']['question'] = (
        '你已经走到这一步，继续眼前行动还是改变行动？比较自己能替队友多做什么，'
        '离开后谁付代价，对手怎样回应。本人实际意图仍需证据。')
    return refresh_identity(result)


def bind_personal_checkpoint(bundle, previous=None):
    """Only open the coordination task when an event matters to this player."""
    from .team_coordination import coordination_trigger
    trigger = coordination_trigger(bundle, previous)
    result = bind_personal_actions(bundle, team_coordination=trigger['active'])
    task = result['frame']['task']
    task['team_coordination_trigger'] = trigger
    if not trigger['active']:
        task.pop('team_coordination_review', None)
        # A full support-roam assignment also asks the model to survey other lanes.
        # Keep the verified lane actors available for the player's ordinary matchup.
        task.pop('bottom_lane_review', None)
        task['question'] = '这一刻专注自己的兵线、站位、换血或手上的野怪。继续当前动作还是改选？'
    return refresh_identity(result)


def personal_context(frame):
    facts = {}
    at = frame['decision']['at_seconds']
    for fid in frame.get('personal_history_fact_ids', []):
        fact = frame['facts'][fid]
        if (fid != 'f_'+digest(fact)[:20] or fact['entity_id'] != frame['decision']['player_entity_id']
                or fact['field'] != 'personal_movement_sample'
                or not 0 <= fact['observed_at_seconds'] <= fact['available_at_seconds'] <= at):
            raise ValueError('invalid personal movement fact')
        facts[fid] = fact
    rows = list(facts.values())
    displacement = dist(rows[0]['value']['start_xz'], rows[-1]['value']['start_xz']) if rows else None
    result = dict(frame_id=frame['frame_id'], samples=facts,
                  displacement_between_observed_endpoints=displacement,
                  meaning='起点是各时刻采样，终点是指令。多个起点可支持已移动；意图、实际到达与施法另证。',
                  action_options=list(ACTION_IDS))
    states = {}
    for fid, fact in frame['facts'].items():
        if fact['entity_id'] != frame['decision']['player_entity_id'] or fact['field'] not in (
                'personal_client_state', 'personal_hud_state', 'last_observed_personal_build'):
            continue
        when = fact['observed_at_seconds']
        if fid != 'f_' + digest(fact)[:20] or not 0 <= when <= fact.get('available_at_seconds', when) <= at:
            raise ValueError('invalid personal status sample')
        states[fid] = fact
    if states:
        result['own_state_samples'] = states
        result['own_state_scope'] = '按各条采样时刻解释。旧等级和物品可供回顾，现有购买、存活、血量与技能就绪另查。'
    return result


def _coordination_followup(frame, index, recipient_ids, end, ping_index):
    decision = frame['decision']
    start = decision['at_seconds']
    actor = decision['player_entity_id']
    team = decision['observer_team_id']
    teammates = {row['entity_id'] for row in frame['lineup']
                 if row['relation'] == 'ally' and row['entity_id'] != actor}
    if not set(recipient_ids) <= teammates:
        raise ValueError('coordination recipient outside observer team')
    observations = []
    for ally_id in recipient_ids:
        rows = index.between(ally_id, start, end)
        # Two observed origins show displacement. Command destinations would only show orders.
        for row in (rows[:1] + rows[-1:] if len(rows) > 1 else rows):
            observations.append(dict(kind='ally_position_sample', actor_id=ally_id, at=row['time_seconds'],
                                     observed_xz=row['world_waypoints_xz'][0], source=row['source']))
    if ping_index is None:
        return observations, 'unavailable'
    if (ping_index.get('schema') != 'review-ping-index/v1' or ping_index.get('source_sha256') != index.source
            or ping_index.get('status') not in ('verified', 'unsupported_replay')):
        raise ValueError('coordination ping source mismatch')
    if ping_index['status'] == 'unsupported_replay':
        return observations, 'unsupported_replay'
    if ping_index['build'] != decision['build']:
        raise ValueError('coordination ping build mismatch')
    for event in ping_index['events']:
        when, sender, signal = event['time_seconds'], event['sender_entity_id'], event['kind']
        if not start < when <= end or event['team_id'] != team or signal not in PING_KINDS:
            continue
        if sender != actor and not (sender in recipient_ids and signal in TEAM_CHANNEL_KINDS
                                    and event.get('channel') == 'team'):
            continue
        observations.append(dict(kind='map_ping_sent', actor_id=sender, ping_kind=signal,
                                 at=when, source=deepcopy(event['source'])))
    return observations, 'verified_sends_only'


def execution_evidence(bundle, answer, index, end, public_events=(), *, ping_index=None, contact_index=None):
    frame = _check_bundle(bundle)
    if _source(bundle) != index.source or answer['frame_id'] != frame['frame_id']:
        raise ValueError('execution review source mismatch')
    at, actor = frame['decision']['at_seconds'], frame['decision']['player_entity_id']
    if not number(end) or end <= at:
        raise ValueError('execution review must follow the frozen decision')
    evidence = {}
    if contact_index is not None:
        if (contact_index['source_sha256'], contact_index['player_entity_id'], contact_index['team_id']) != (
                index.source, actor, frame['decision']['observer_team_id']):
            raise ValueError('execution contact perspective mismatch')
        for item in contact_index['events']:
            if at < item['at'] <= end:
                evidence['actual_'+digest(item)[:20]] = deepcopy(item)
    for row in index.between(actor, at, end):
        item = dict(kind='own_position_and_command', at=row['time_seconds'],
                    observed_xz=row['world_waypoints_xz'][0], command_xz=row['world_waypoints_xz'],
                    source=row['source'])
        evidence['actual_'+digest(item)[:20]] = item
    for event in public_events:
        if at < event['available_at_seconds'] <= end:
            item = dict(kind='public_kill', **event)
            evidence['actual_'+digest(item)[:20]] = item
    result = dict(schema='personal-execution/v1', frame_id=frame['frame_id'],
                source_sha256=index.source, player_entity_id=actor,
                nearby_contact_coverage=('team_visible_appearance_samples' if contact_index is not None
                                         else 'unavailable'),
                decision_at=at, observed_through=end, sealed_answer_sha256=digest(answer),
                actual=evidence, unknown=['cast_and_hit', 'intent', 'counterfactual_outcome',
                                          'wave_loss_unless_independently_observed'])
    if frame['task'].get('team_coordination_review') == 'team-coordination/v1':
        recipient = answer['team_coordination']['recipient_id']
        recipients = [recipient] if recipient is not None else []
        observations, coverage = _coordination_followup(frame, index, recipients, end, ping_index)
        for row in observations:
            evidence['actual_'+digest(row)[:20]] = row
        result['coordination_ping_coverage'] = coverage
        result['unknown'].extend(['ally_attention', 'agreement', 'reason_for_movement', 'voice_or_chat'])
    return result


def nearby_threat_observations(index, vision, actor, team, end, distance_limit=1600):
    """First current position after each enemy appearance, using only the team's view."""
    if vision['source_sha256'] != index.source:
        raise ValueError('visibility source mismatch')
    transitions = {}
    for row in vision['observations']:
        if row['team_id']==team and row['mode']=='transition':
            transitions.setdefault(row['subject'],[]).append(row)
    positions = {}
    for row in vision.get('enemy_positions_in_view',[]):
        if row['team_id']==team:
            positions.setdefault(row['subject'],[]).append(row)
    output=[]
    for subject, events in transitions.items():
        events=sorted(events,key=lambda r:r['time_seconds'])
        samples=sorted(positions.get(subject,[]),key=lambda r:r['time_seconds'])
        times=[s['time_seconds'] for s in samples]
        previous=None
        for i,event in enumerate(events):
            if event['time_seconds']>end:
                break
            if event['visible'] is True and previous is not True:
                # No remembered hidden position can substitute for a new visible sample.
                j=bisect_right(times,event['time_seconds']-1e-9)
                if j<len(samples):
                    observed=samples[j];at=observed['time_seconds']
                    interval_end=events[i+1]['time_seconds'] if i+1<len(events) else float('inf')
                    own=index.between(actor,at-2,at)
                    if at<=end and at-event['time_seconds']<=2 and at<interval_end and own:
                        position=own[-1]['world_waypoints_xz'][0]
                        if dist(position,observed['xz'])<=distance_limit:
                            output.append(dict(at=at,subject=subject,enemy_sample=observed,
                                               own_sample=own[-1],kind='nearby_enemy_became_visible'))
            previous=event['visible']
    return sorted(output,key=lambda r:r['at'])


def personal_contact_index(index, vision, actor, team):
    """Compact hindsight receipts, bound to the reviewed person and their team's native sight channel."""
    entities = vision['entities']
    if team not in (100, 200) or entities.get(actor, {}).get('team_id') != team:
        raise ValueError('contact index requires the bound own-team actor')
    events = []
    for match in nearby_threat_observations(index, vision, actor, team, vision['end_seconds']):
        enemy_id = match['subject'].removeprefix('entity:')
        opponent = entities.get(enemy_id, {})
        if opponent.get('team_id') != 300-team:
            continue
        own, seen = match['own_sample'], match['enemy_sample']
        item = dict(kind='nearby_opponent_seen_by_team', at=seen['time_seconds'],
                    opponent_id=enemy_id, champion=opponent['name'],
                    distance_world_units=round(dist(own['world_waypoints_xz'][0], seen['xz']), 1),
                    own_sample_at=own['time_seconds'], source=dict(own_path=own['source'],
                    visible_enemy_position=seen['source'], team_visibility=seen['visibility_record']))
        events.append(item)
    return dict(source_sha256=index.source, player_entity_id=actor, team_id=team, events=events)


def event_review_times(base, index, actor, end, public_events, minimum_gap=8, nearby_events=()):
    """Forward-only review candidates. A reversal is a command change, not an intention."""
    candidates = {r['at']:set(r['selected_by']) for r in base}
    triggers = {}
    def add(at,reason,evidence):
        candidates.setdefault(at,set()).add(reason)
        triggers.setdefault(at,[]).append(deepcopy(evidence))
    last = float('-inf')
    previous = None
    for row in index.rows.get(actor, []):
        at = row['time_seconds']
        if at > end:
            break
        points = row['world_waypoints_xz']
        direction = [points[-1][i]-points[0][i] for i in (0, 1)]
        if previous is not None and dist([0,0], direction) >= 150 and dist([0,0], previous) >= 150:
            dot = sum(a*b for a,b in zip(direction, previous))
            if dot < 0 and at-last >= minimum_gap:
                add(at,'own_command_reversed',dict(previous_command=prior_row,current_command=row))
                last = at
        previous = direction
        prior_row = row
    for event in public_events:
        at = event['available_at_seconds']
        if 0 <= at <= end:
            add(at,'public_kill_became_available',event)
    for event in nearby_events:
        if 0<=event['at']<=end:
            add(event['at'],'nearby_enemy_became_visible',event)
    return [dict(at=t, selected_by=sorted(why),triggers=triggers.get(t,[])) for t,why in sorted(candidates.items())]
