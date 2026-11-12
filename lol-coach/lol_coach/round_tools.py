"""The model can query only the round and counterfactual selected by its host."""
from copy import deepcopy

from .reasoning_frame import TOOLS, canonical, digest, lookup_reference
from .review_sightings import enemy_sightings
from .round_chain import _check_bundle
from .round_options import compare_round_options
from .round_plan import review_round_plan


def _definition(name, description, **properties):
    return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': list(properties),
                           'additionalProperties': False}}}


ROUND_TOOLS = [*TOOLS,
    _definition('compare_round_options', 'Compare leaving now, helping then leaving, and clearing the wave. Times are conditional; null is unknown.'),
    _definition('compare_help_duration', 'Vary only the proposed seconds spent helping here. Check the delayed option against the same objective and return windows. This does not change the frozen decision or its default options.',
                help_seconds={'type': 'number', 'minimum': 0}),
    _definition('review_round_plan', 'Check prior plan, changes, allies, opponent responses and whether the fight can be supported.'),
    _definition('enemy_sightings', 'Read last team-visible enemy samples, timestamps and evidence IDs.'),
    _definition('read_history', 'Retrieve one historical record from the current plan catalog.',
                history_id={'type': 'string', 'minLength': 1})]


def bind_round(bundle, lane, target, help_seconds, *, ally_id=None, enemy_id=None):
    _check_bundle(bundle)
    result = deepcopy(bundle)
    frame = result['frame']
    args = dict(lane=lane, target=target, help_seconds=help_seconds)
    engagement = frame['task'].get('engagement_question')
    if ally_id is not None or enemy_id is not None:
        roster = {h['entity_id']:h['relation'] for h in frame['lineup']}
        if roster.get(ally_id) != 'ally' or ally_id == frame['decision']['player_entity_id'] or roster.get(enemy_id) != 'enemy':
            raise ValueError('expected_other_ally_and_opponent_in_frame')
        if not engagement or (engagement.get('ally_id'), engagement.get('target_id')) != (ally_id, enemy_id):
            engagement = dict(ally_id=ally_id, target_id=enemy_id)
    if 'round_comparison' in frame['task']:
        if frame['task']['round_comparison'] != args or frame['task'].get('engagement_question') != engagement:
            raise ValueError('round_already_bound_to_different_question')
        return result
    comparison = compare_round_options(frame, **args)
    frame['task']['round_comparison'] = args
    if engagement:
        frame['task']['engagement_question'] = engagement
    clocks = comparison['clocks']
    for row in comparison['options']:
        immediate = row['action'] == 'leave_now' or row['depart_at'] == [comparison['at_seconds']]*2
        travel = clocks.get('immediate_route_duration') if immediate else None
        available = row['available_travel_seconds']
        budget = dict(travel_seconds=travel if travel is not None else clocks.get('route_duration'),
                      execution_seconds=clocks.get('target_work_duration'),
                      exit_seconds=clocks.get('return_duration'),
                      window_seconds=[max(0, t) for t in available] if available is not None else None)
        if any(v is not None for v in budget.values()):
            entry = dict(option_id=row['action'], time_budget=budget, fact_ids=row['evidence_ids'])
            frame['calculations']['round_'+digest(entry)[:20]] = entry
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_'+digest(frame)[:24]
    result['audit']['frame_chars'] = len(canonical(frame))
    return result


def history_catalog(frame):
    """An initial display view. History remains retrievable under the original frame ID."""
    display = deepcopy(frame)
    plan = display['task'].get('previous_plan')
    if plan:
        for hid, fact in plan['historical_facts'].items():
            plan['historical_facts'][hid] = {k:fact[k] for k in ('entity_id','field','observed_at_seconds')}
    return display


def round_call(bundle, name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError('expected_object_arguments')
    frame = bundle['frame']
    if name == 'get_reference' and set(arguments) == {'reference_id'}:
        return lookup_reference(bundle, arguments['reference_id'])
    if name == 'read_history' and set(arguments) == {'history_id'}:
        hid = arguments['history_id']
        plan = frame['task'].get('previous_plan')
        if not isinstance(hid, str) or not plan or hid not in plan['historical_facts']:
            raise ValueError('history_not_in_this_frame')
        return {'history_id': hid, 'historical_fact':deepcopy(plan['historical_facts'][hid])}
    if name == 'compare_help_duration' and set(arguments) == {'help_seconds'}:
        default = frame['task']['round_comparison']
        comparison = compare_round_options(frame, **{**default, **arguments})
        option = next(row for row in comparison['options'] if row['action'] == 'help_then_leave')
        return {**{key: comparison[key] for key in ('frame_id', 'at_seconds', 'observer_team_id', 'actor_id',
                 'lane', 'target', 'proposed_help_seconds', 'additional_objective_contribution')},
                'default_help_seconds': default['help_seconds'], 'option': option}
    if arguments:
        raise ValueError('round_scope_is_locked')
    if name == 'compare_round_options':
        return compare_round_options(frame, **frame['task']['round_comparison'])
    if name == 'review_round_plan':
        return review_round_plan(bundle)
    if name == 'enemy_sightings':
        return enemy_sightings(frame)
    raise ValueError('unknown_round_tool')
