"""The model can query only the round and counterfactual selected by its host."""
from copy import deepcopy

from .decision_contract import MACRO_REVIEW, SUPPORT_LANE_REVIEW
from .damage_scenario import SCENARIO_PROPERTIES
from .player_action import actor_context, allied_paths
from .reasoning_frame import TOOLS, canonical, digest, lookup_reference
from .review_sightings import enemy_sightings
from .round_chain import _check_bundle, _source
from .round_options import compare_round_options
from .round_plan import review_round_plan
from .review_abilities import SLOTS, ability_damage, ability_parameters, pin_damage_profiles


def _definition(name, description, **properties):
    return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': list(properties),
                           'additionalProperties': False}}}


ROUND_TOOLS = [*TOOLS,
    _definition('get_ability_parameters',
                'Read one lineup champion’s patch-pinned spell, published ranges and base cooldowns by rank, and reviewed damage component names and formulas when available.',
                champion={'type':'string','minLength':1}, slot={'type':'string','enum':list(SLOTS)}),
    _definition('calculate_ability_damage',
                'For the selected player only. damage is spells alone. Read rune_damage for the equipped rune page, impact conditions, ranges and blockers. Begin with assumptions={}. For what-ifs specify target health immediately BEFORE each hit and effective resists. A failed proc at one hit leaves the others open; use other_hits_cannot_trigger only if explicitly assumed or verified. A sum does not validate cast order, item procs, shields, HP loss or kills.',
                target_id={'type':'string','minLength':1},
                hits={'type':'array','minItems':1,'maxItems':5,'items':{'type':'object','additionalProperties':False,
                      'required':['slot','component'],'properties':{'slot':{'type':'string','enum':list(SLOTS)},
                                                                   'component':{'type':'string','minLength':1}}}},
                assumptions={'type':'object','additionalProperties':False,'properties':{
                    'ranks':{'type':'object','additionalProperties':False,'properties':{
                        slot:{'type':'integer','minimum':1,'maximum':3 if slot=='R' else 5} for slot in SLOTS}},
                    **{key:{'type':'number','minimum':0} for key in ('ap','bonus_ad','bonus_health')},
                    'target_max_health':{'type':'number','exclusiveMinimum':0},
                    'effective_armor':{'type':'number'},'effective_magic_resist':{'type':'number'},
                    **SCENARIO_PROPERTIES}}),
    _definition('compare_round_options', 'Compare leaving now, helping then leaving, and clearing the current wave or jungle camp. Jungle camp proximity alone cannot establish a living monster. Times are conditional; null is unknown.'),
    _definition('compare_help_duration', 'Vary only the proposed seconds spent helping here. Check the delayed option against the same objective and return windows. This does not change the frozen decision or its default options.',
                help_seconds={'type': 'number', 'minimum': 0}),
    _definition('review_round_plan', 'Read the prior plan, changes, lane coverage, patch references and statistics. team_pings lists personal communications. Use get_reference with team_pings.team_channel_lookup.reference_id to read allied Smart Ping sends; personal receipt is unknown. For bottom support also compare pressure, carry exposure and conditional roams.'),
    _definition('enemy_sightings', 'Read what the selected player could learn from shared team vision at this time. Player camera and attention are unknown. Includes sample times and evidence IDs.'),
    _definition('read_history', 'Retrieve one historical record from the current plan catalog.',
                history_id={'type': 'string', 'minLength': 1})]


def bind_round(bundle, lane, target, help_seconds, *, ally_id=None, enemy_id=None, upgrade_legacy=False,
               macro_review=False, require_objective_credit=False, review_origin=None, bottom_lane_actors=None,
               roam_actors=None, damage_profiles=None):
    _check_bundle(bundle)
    result = deepcopy(bundle)
    frame = result['frame']
    old_origin = frame['task'].get('review_origin')
    if review_origin is not None and review_origin.get('replay_sha256') != _source(result):
        raise ValueError('review_origin_replay_mismatch')
    if old_origin is not None and review_origin is not None and old_origin != review_origin:
        raise ValueError('round_already_bound_to_different_review_origin')
    player = frame['decision']['player_entity_id']
    old_duo = frame['task'].get('bottom_lane_actors')
    old_roam = frame['task'].get('roam_actors')
    if roam_actors is not None:
        duos = bottom_lane_actors or old_duo
        relations = {h['entity_id']: h['relation'] for h in frame['lineup']}
        if (lane != 'bot' or not duos or not isinstance(roam_actors, dict) or not roam_actors
                or not roam_actors.keys() <= {'ally_mid', 'ally_jungle', 'enemy_mid', 'enemy_jungle', 'ally_top', 'enemy_top'}
                or not all(isinstance(actor, str) for actor in roam_actors.values())
                or any(relations.get(actor) != key.split('_')[0] for key, actor in roam_actors.items())
                or len(set(roam_actors.values())) != len(roam_actors)
                or set(duos.values()).intersection(roam_actors.values())):
            raise ValueError('invalid_roam_actors')
        if old_roam is not None and any(roam_actors.get(k) != v for k, v in old_roam.items()):
            raise ValueError('round_already_bound_to_different_roam_actors')
    if bottom_lane_actors is not None:
        relations = {h['entity_id']: h['relation'] for h in frame['lineup']}
        required = {'support': 'ally', 'carry': 'ally', 'enemy_support': 'enemy', 'enemy_carry': 'enemy'}
        if (lane != 'bot' or set(bottom_lane_actors) != required.keys()
                or bottom_lane_actors['support'] != player or len(set(bottom_lane_actors.values())) != 4
                or any(relations.get(bottom_lane_actors[key]) != rel for key, rel in required.items())):
            raise ValueError('invalid_bottom_lane_actors')
        if old_duo is not None and old_duo != bottom_lane_actors:
            raise ValueError('round_already_bound_to_different_lane_actors')
    team = frame['decision']['observer_team_id']
    heroes = [h for h in frame['lineup'] if h['entity_id'] == player]
    if len(heroes) != 1 or heroes[0]['relation'] != 'ally':
        raise ValueError('round_requires_selected_own_team_player')
    champion = heroes[0]['champion']
    perspective = dict(player_entity_id=player, champion=champion, observer_team_id=team)
    for fact in frame['facts'].values():
        if fact['entity_id'] == player and fact['field'] == 'identity':
            identity = fact['value']
            if (not isinstance(identity, dict) or identity.get('team_id') != team
                    or identity.get('champion', champion) != champion):
                raise ValueError('round_player_roster_identity_mismatch')
    if 'player_perspective' in frame['task'] and frame['task']['player_perspective'] != perspective:
        raise ValueError('round_player_perspective_mismatch')
    args = dict(lane=lane, target=target, help_seconds=help_seconds)
    previous_engagement = frame['task'].get('engagement_question')
    engagement = previous_engagement
    bind_duo_target = bottom_lane_actors is not None and engagement is None and ally_id is None and enemy_id is None
    if bind_duo_target:
        ally_id, enemy_id = bottom_lane_actors['carry'], bottom_lane_actors['enemy_carry']
        paths = allied_paths(frame)
        if player in paths and paths[player]['age_seconds'] <= 1:
            nearby = actor_context(frame, enemy_sightings(frame), paths)
            if nearby['local_contact_to_check']:
                enemy_id = nearby['local_contact_to_check']['entity_id']
                if nearby['allies_by_gap_to_nearest_opponent']:
                    ally_id = nearby['allies_by_gap_to_nearest_opponent'][0]['entity_id']
            else:
                ally_id, enemy_id = None, None
    if ally_id is not None or enemy_id is not None:
        roster = {h['entity_id']:h['relation'] for h in frame['lineup']}
        if roster.get(ally_id) != 'ally' or ally_id == frame['decision']['player_entity_id'] or roster.get(enemy_id) != 'enemy':
            raise ValueError('expected_other_ally_and_opponent_in_frame')
        if not engagement or (engagement.get('ally_id'), engagement.get('target_id')) != (ally_id, enemy_id):
            engagement = dict(ally_id=ally_id, target_id=enemy_id)
    if 'round_comparison' in frame['task']:
        if frame['task']['round_comparison'] != args or (previous_engagement != engagement and not bind_duo_target):
            raise ValueError('round_already_bound_to_different_question')
        # Archived cards cite the original hash; only the host preparing a NEW
        # answer opts into a copy with an explicit point of view and a new ID.
        needs_perspective = upgrade_legacy and 'player_perspective' not in frame['task']
        needs_macro = macro_review and frame['task'].get('macro_round_review') != MACRO_REVIEW
        needs_credit = require_objective_credit and not frame['task'].get('require_objective_credit')
        needs_duo = bottom_lane_actors is not None and (old_duo is None or
                    frame['task'].get('bottom_lane_review') != SUPPORT_LANE_REVIEW)
        needs_roam = roam_actors is not None and old_roam != roam_actors
        if not any((needs_perspective, needs_macro, needs_credit, needs_duo, needs_roam, bind_duo_target)) and review_origin == old_origin:
            if not upgrade_legacy or not pin_damage_profiles(result, damage_profiles):
                return result
    else:
        comparison = compare_round_options(frame, **args)
        frame['task']['round_comparison'] = args
        clocks = comparison['clocks']
        for row in comparison['options']:
            immediate = row['action'] == 'leave_now' or row['depart_at'] == [comparison['at_seconds']]*2
            travel = clocks.get('immediate_route_duration') if immediate else None
            available = row['available_travel_seconds']
            budget = dict(travel_seconds=travel if travel is not None else clocks.get('route_duration'),
                          execution_seconds=clocks.get('target_work_duration'),
                          exit_seconds=clocks.get('return_to_camp_duration' if lane == 'jungle' else 'return_duration'),
                          window_seconds=[max(0, t) for t in available] if available is not None else None)
            if any(v is not None for v in budget.values()):
                entry = dict(option_id=row['action'], time_budget=budget, fact_ids=row['evidence_ids'])
                frame['calculations']['round_'+digest(entry)[:20]] = entry
    frame['task']['player_perspective'] = perspective
    if engagement:
        frame['task']['engagement_question'] = engagement
    if bottom_lane_actors is not None:
        frame['task']['bottom_lane_review'] = SUPPORT_LANE_REVIEW
        frame['task']['bottom_lane_actors'] = dict(bottom_lane_actors)
    if roam_actors is not None:
        frame['task']['roam_actors'] = dict(roam_actors)
    if macro_review:
        frame['task']['macro_round_review'] = MACRO_REVIEW
    if require_objective_credit:
        frame['task']['require_objective_credit'] = True
    if review_origin is not None:
        frame['task']['review_origin'] = deepcopy(review_origin)
    pin_damage_profiles(result, damage_profiles)
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
    if name == 'get_ability_parameters' and set(arguments) == {'champion','slot'}:
        return ability_parameters(bundle, **arguments)
    if name == 'calculate_ability_damage' and set(arguments) == {'hits','target_id','assumptions'}:
        return ability_damage(bundle, **arguments)
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
