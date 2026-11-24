"""Questions sealed with one decision and answered only from later same-POV observations."""
from math import dist

from .reasoning_frame import digest, number
from .round_chain import _check_bundle, _source


def _own_lane(frame, lane):
    for fid in frame.get('lane_fact_ids', []):
        fact = frame['facts'][fid]
        value = fact['value']
        if value.get('lane') != lane:
            continue
        if (fact['field'] != 'lane_current_units_and_groups' or fid != 'f_' + digest(fact)[:20]
                or value['observer_team_id'] != frame['decision']['observer_team_id']
                or value['count_scope'] != 'own_team_observed_live_only'):
            continue
        return fid, value
    return None, {}


def register_question(bundle, answer):
    """Accept only the current bundle/answer. No execution records or later clocks enter here."""
    frame = _check_bundle(bundle)
    if answer['frame_id'] != frame['frame_id']:
        raise ValueError('lesson answer belongs to another frame')
    decision = frame['decision']
    prior = frame.get('task', {}).get('previous_plan') or {}
    brief = answer.get('schema') == 'personal-brief/v1'
    macro = answer.get('macro_round', {})
    lane_plan = answer.get('lane_plan', {})
    dest = lane_plan.get('destination_choice', {}).get('preferred')
    plan = answer.get('follow_through', {}).get('steps', [])
    signals = answer.get('recommendation', {}).get('switch_conditions', [])
    question = dict(schema='lesson-question/v1', frame_id=frame['frame_id'], answer_sha256=digest(answer),
                    source_sha256=_source(bundle), build=decision.get('build'), team=decision['observer_team_id'],
                    actor=decision['player_entity_id'], at=decision['at_seconds'], brief=brief,
                    previous_frame_id=prior.get('previous_frame_id'), previous_answer_sha256=prior.get('previous_answer_sha256'),
                    intent=macro.get('intent'), destination=dest, transition=macro.get('transition'),
                    disposition=(answer.get('disposition') if brief else answer.get('continuation', {}).get('disposition')),
                    goal=answer.get('objective') or answer['immediate_action'],
                    watch_text=(answer['switch_if'] if brief else plan[0]['check_when'] if plan else next(iter(signals), None)),
                    observation=None)
    if brief:
        return question
    allies = {row['entity_id']: row['champion'] for row in frame.get('lineup', [])
              if row['relation'] == 'ally' and row['entity_id'] != question['actor']}
    recipient = (answer.get('team_coordination') or {}).get('recipient_id')
    if recipient in allies:
        question['observation'] = dict(kind='next_joint_position', ally_id=recipient, ally=allies[recipient])
        return question
    # Legacy personal answers contain a lane worksheet even during unrelated fights.
    # Register a wave watch only when the chosen action actually puts a wave at stake.
    best = next((o for o in answer.get('options', []) if o['id'] ==
                 answer.get('recommendation', {}).get('preferred_option_id')), {})
    stakes = ' '.join([question['goal'], answer['immediate_action'], *best.get('costs', []), *signals])
    wave_terms = ('接线', '接兵', '兵线', '下一波兵', '这波兵', '处理这波', '送线', '送塔', '兵送')
    carry = (frame['task'].get('bottom_lane_actors') or {}).get('carry')
    if lane_plan and carry in allies and any(term in stakes for term in wave_terms):
        fid, lane = _own_lane(frame, 'bot')
        markers = lane.get('wave_spawn_clock', {}).get('observed_starts', [])
        if markers and markers[-1] <= question['at']:
            question['observation'] = dict(kind='next_allied_wave', lane='bot', ally_id=carry,
                                           ally=allies[carry], anchor=markers[-1], fact_ref=fid)
    return question


def continues_question(previous, current, *, last_full=None):
    if (any(previous[k] != current[k] for k in ('source_sha256', 'actor', 'team', 'build'))
            or current['at'] <= previous['at'] or current['previous_frame_id'] != previous['frame_id']
            or current['previous_answer_sha256'] != previous['answer_sha256']):
        return False
    if current['brief']:
        return current['disposition'] in ('retain', 'revise')
    topic = last_full if previous['brief'] else previous
    return bool(topic and current['transition'] == 'continue' and current['disposition'] == 'retain'
                and current['intent'] == topic['intent'] and current['destination'] is not None
                and current['destination'] == topic['destination'])


def _paths(frame, owner, ally):
    at = frame['decision']['at_seconds']
    paths = {}
    for fid in frame.get('allied_path_fact_ids', []):
        fact = frame['facts'][fid]
        actor = fact['entity_id']
        if actor not in (owner, ally):
            continue
        if (fact['field'] != 'allied_path_start_sample' or fid != 'f_' + digest(fact)[:20]
                or fact['value']['observer_team_id'] != frame['decision']['observer_team_id']):
            raise ValueError('invalid lesson position evidence')
        if 0 <= at - fact['observed_at_seconds'] <= 2:
            paths[actor] = (fid, fact)
    return paths


def resolve_question(question, later_bundles):
    """Only the sealed review stage calls this. Birth, proximity and actual farm remain distinct."""
    watch = question['observation']
    if not watch:
        return None
    origin = question['at']
    owner, ally = question['actor'], watch['ally_id']
    birth = None
    birth_frame = None
    previous_at = origin
    for bundle in later_bundles:
        frame = bundle['frame']  # write_player_review verifies the complete bundle before this pass.
        decision = frame['decision']
        if ((_source(bundle), decision['player_entity_id'], decision['observer_team_id'], decision.get('build'))
                != (question['source_sha256'], owner, question['team'], question['build'])):
            raise ValueError('lesson observation crosses replay, player, team or build')
        at = decision['at_seconds']
        if at <= previous_at:
            raise ValueError('lesson observation clocks must advance')
        previous_at = at
        paths = _paths(frame, owner, ally)
        if watch['kind'] == 'next_allied_wave':
            fid, lane = _own_lane(frame, watch['lane'])
            if not lane:
                continue
            starts = lane.get('wave_spawn_clock', {}).get('observed_starts', [])
            if birth is None and watch['anchor'] in starts:
                following = starts[starts.index(watch['anchor']) + 1:]
                if following and origin < following[0] <= at:
                    birth = following[0]
                    birth_frame = dict(frame_id=frame['frame_id'], available_at=at, lane_fact=fid, born_at=birth)
            if birth is None or birth not in starts or len(paths) != 2:
                continue
            later_starts = starts[starts.index(birth) + 1:]
            end = later_starts[0] if later_starts else float('inf')
            units = [u for u in lane.get('units', []) if birth <= u['born_at'] < end
                     and number(u.get('sampled_at')) and 0 <= at - u['sampled_at'] <= 2 and u.get('last_xz')]
            if not units:
                continue
            unit = min(units, key=lambda u: dist(u['last_xz'], paths[ally][1]['value']['xz']))
            ally_gap = dist(unit['last_xz'], paths[ally][1]['value']['xz'])
            if ally_gap > 1500:  # Nearby sampling for a coaching comparison, never a range or farm receipt.
                continue
            details = dict(birth_receipt=birth_frame, lane_fact=fid, minion=unit['entity_id'],
                           minion_observed_at=unit['sampled_at'], ally_to_minion=round(ally_gap))
        else:
            if len(paths) != 2:
                continue
            details = {}
        if min(f['observed_at_seconds'] for _, f in paths.values()) <= origin:
            continue
        return dict(status='position_sample', frame_id=frame['frame_id'], at=at,
                    own_to_ally=round(dist(paths[owner][1]['value']['xz'], paths[ally][1]['value']['xz'])),
                    position_refs=[paths[k][0] for k in (owner, ally)],
                    position_times=[paths[k][1]['observed_at_seconds'] for k in (owner, ally)], **details)
    return dict(status='birth_only' if birth_frame else 'unresolved', birth_receipt=birth_frame)
