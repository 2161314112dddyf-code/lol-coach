"""Reassess a linked decision using only observations on the frozen team's frame."""
from math import hypot

from .reasoning_frame import number
from .review_sightings import enemy_sightings
from .round_chain import _check_bundle
from .round_options import _checked_facts


def _visibility(value, field, team):
    if field == 'observer_visibility':
        if not isinstance(value, dict) or value.get('team_id') != team:
            raise ValueError('previous_visibility_team_mismatch')
        value = value.get('visible')
    if value is not None and type(value) is not bool:
        raise ValueError('invalid_visibility_state')
    return value


def _engagement(frame, sightings):
    """Compare one host-bound pair and target at the decision instant.

    Time intervals are seconds from this frame, conditional on executing the
    specified actions. A circular footprint tests coverage at the sampled
    positions. A hit is only reported by an explicit, observed cast resolution.
    """
    result = dict(first_effect_on_common_target_seconds=None, control_window_seconds=None,
                  support_window='unknown', shared_enemy_area_coverage=None,
                  shared_enemy_area_hit=None, fact_ids={}, missing_inputs=[])
    question = frame['task'].get('engagement_question')
    if not question:
        result['missing_inputs'] = ['ally_and_target', 'first_effect_and_control_window',
                                    'enemy_area_cast_and_actor_positions']
        return result
    me = frame['decision']['player_entity_id']
    ally, target = question['ally_id'], question['target_id']
    members = {h['entity_id']: h['relation'] for h in frame['lineup']}
    if ally == me or members.get(ally) != 'ally' or members.get(target) != 'enemy':
        raise ValueError('invalid_engagement_participants')
    participants = (me, ally)
    cast_id = question.get('enemy_area_cast_id')
    source = question.get('enemy_area_source_id')
    if cast_id is not None and (not isinstance(cast_id, str) or not cast_id or members.get(source) != 'enemy'):
        raise ValueError('invalid_enemy_area_cast')
    result.update(ally_id=ally, target_id=target, enemy_area_cast_id=cast_id,
                  enemy_area_source_id=source)
    at, team = sightings['at_seconds'], sightings['observer_team_id']
    seen_target = next(r for r in sightings['opponents'] if r['entity_id'] == target)
    target_visible = seen_target['visible'] is True
    if seen_target['fact_id']:
        result['fact_ids']['target_visibility'] = seen_target['fact_id']
    values = {}
    for fid, fact in _checked_facts(frame, 'engagement_fact_ids'):
        v = fact['value']
        if (fact['field'] != 'round_engagement_input' or not isinstance(v, dict)
                or v.get('observer_team_id') != team):
            raise ValueError('invalid_engagement_evidence_scope')
        if fact['observed_at_seconds'] != at:
            continue  # Older locations, available skills and resolutions apply at their original instant.
        actor, kind = fact['entity_id'], v['kind']
        if kind in ('first_effect', 'control_window'):
            if (not target_visible or v.get('target_id') != target
                    or fact['temporal_scope'] != 'conditional_engagement_at_decision'):
                continue
            if (kind == 'first_effect' and actor not in participants) or (kind == 'control_window' and actor != target):
                continue
            pair = v.get('interval_seconds')
            if (not isinstance(pair, list) or len(pair) != 2 or not all(number(n) for n in pair)
                    or not 0 <= pair[0] <= pair[1]):
                raise ValueError('invalid_engagement_interval')
            key = 'first_effect:' + actor if kind == 'first_effect' else kind
            value = list(pair)
        elif kind in ('actor_disc', 'cast_disc', 'cast_result'):
            if (cast_id is None or v.get('cast_id') != cast_id or v.get('source_id') != source
                    or fact['temporal_scope'] != 'observed_engagement_at_decision'):
                continue
            if (kind == 'actor_disc' and actor not in participants) or (kind != 'actor_disc' and actor != source):
                continue
            key = kind + ':' + actor if kind == 'actor_disc' else kind
            if kind == 'cast_result':
                outcomes = v.get('outcomes')
                if (not isinstance(outcomes, dict)
                        or any(val not in ('hit', 'miss') for val in outcomes.values())):
                    raise ValueError('invalid_observed_cast_result')
                value = {a: outcomes[a] for a in participants if a in outcomes}
            else:
                pos, radius = v.get('xz'), v.get('radius_world_units')
                if (not isinstance(pos, list) or len(pos) != 2 or not all(number(n) for n in pos)
                        or not number(radius) or radius < 0 or v.get('coordinate_space') != 'map_world_xz'):
                    raise ValueError('invalid_engagement_disc')
                value = (pos, radius)
        else:
            raise ValueError('invalid_engagement_input_kind')
        if key in values:
            raise ValueError('ambiguous_engagement_input')
        values[key] = value
        result['fact_ids'][key] = fid

    effects = {a:values['first_effect:' + a] for a in participants if 'first_effect:' + a in values}
    result['first_effect_on_common_target_seconds'] = effects or None
    window = result['control_window_seconds'] = values.get('control_window')
    if window is not None and len(effects) == 2:
        if all(window[0] <= low <= high <= window[1] for low, high in effects.values()):
            result['support_window'] = 'both_within_window'
        elif any(high < window[0] or low > window[1] for low, high in effects.values()):
            result['support_window'] = 'first_effect_outside_window'
        else:
            result['support_window'] = 'overlap_uncertain'
    if not target_visible:
        result['missing_inputs'].append('visible_common_target')
    for key in ['first_effect:' + a for a in participants] + ['control_window']:
        if key not in values:
            result['missing_inputs'].append(key)
    area_keys = ['actor_disc:' + a for a in participants] + ['cast_disc']
    if all(k in values for k in area_keys):
        center, radius = values['cast_disc']
        covered = []
        for actor in participants:
            pos, body = values['actor_disc:' + actor]
            if hypot(pos[0]-center[0], pos[1]-center[1]) <= radius + body:
                covered.append(actor)
        result['shared_enemy_area_coverage'] = dict(covered_actor_ids=covered, both=len(covered)==2)
    outcomes = values.get('cast_result', {})
    if len(outcomes) == 2:
        result['shared_enemy_area_hit'] = all(v == 'hit' for v in outcomes.values())
    missing = ['enemy_area_cast'] if cast_id is None else [k for k in area_keys if k not in values]
    result['missing_inputs'].extend(missing)
    if len(outcomes) < 2:
        result['missing_inputs'].append('observed_result_for_both_actors')
    return result


def review_round_plan(bundle):
    """Return evidence to continue, revise or cancel a plan; the agent selects the action."""
    frame = _check_bundle(bundle)
    sightings = enemy_sightings(frame)
    facts = frame['facts']
    at = sightings['at_seconds']
    team = sightings['observer_team_id']
    task = frame['task']
    prior = task.get('previous_plan')
    card = prior['decision_card'] if prior else {}
    since = prior['previous_at_seconds'] if prior else None
    prior_id = prior['previous_frame_id'] if prior else None
    transition = task.get('round_transition', {})
    if prior and (transition.get('previous_frame_id') != prior_id or not 0 <= since < at):
        raise ValueError('invalid_previous_plan_binding')
    changes = {row['current_fact_id']: (key, row.get('historical_fact_id'))
               for key, row in transition.get('changes', {}).items()}

    allies = {}
    player = frame['decision']['player_entity_id']
    position_samples = {}
    allied_ids = {h['entity_id'] for h in frame['lineup'] if h['relation'] == 'ally'}
    for fid, fact in _checked_facts(frame, 'allied_path_fact_ids'):
        actor, value = fact['entity_id'], fact['value']
        if (actor not in allied_ids or actor in position_samples or fact['field'] != 'allied_path_start_sample'
                or fact.get('unit') != 'map11_world_xz' or fact['temporal_scope'] != 'historical_path_start_sample'
                or value.get('observer_team_id') != team or not isinstance(value.get('xz'), list)
                or len(value['xz']) != 2 or not all(number(x) for x in value['xz'])):
            raise ValueError('invalid_allied_path_sample')
        position_samples[actor] = dict(xz=list(value['xz']), sampled_at=fact['observed_at_seconds'],
                                       age_seconds=fact['age_seconds'], fact_id=fid)
    for hero in frame['lineup']:
        actor = hero['entity_id']
        if hero['relation'] != 'ally' or actor == frame['decision']['player_entity_id']:
            continue
        allies[actor] = dict(entity_id=actor, champion=hero['champion'],
                             last_observed_path_start=position_samples.get(actor),
                             requirements=[], observed_actions=[], commitment='unknown')
    options = card.get('options', [])
    for option in options:
        for requirement in option['ally_requirements']:
            allies[requirement['actor_id']]['requirements'].append(dict(
                option_id=option['id'], action_key=requirement.get('action_key'),
                required_action=requirement['required_action'], evidence_status='unconfirmed'))

    triggers = []
    def signal(kind, actor, fid, impact, option_ids=()):
        change_id, old = changes.get(fid, (None, None))
        triggers.append(dict(kind=kind, entity_id=actor, previous_fact_id=old,
                             current_fact_id=fid, change_id=change_id,
                             observed_at_seconds=facts[fid]['observed_at_seconds'],
                             impact=impact, option_ids=sorted(set(option_ids)),
                             scope='prior_options' if option_ids else 'general_review'))

    for row in sightings['opponents']:
        fid = row['fact_id']
        visible = row['visible']
        if not prior or fid not in changes:
            continue
        _, old_id = changes[fid]
        old = prior['historical_facts'].get(old_id)
        field = facts[fid]['field']
        if old and (old['previous_frame_id'] != prior_id or old['field'] != field
                    or old['entity_id'] != facts[fid]['entity_id']):
            raise ValueError('invalid_visibility_history')
        before = _visibility(old['value'], field, team) if old else None
        if visible is before:
            continue  # A refreshed path or age is not a visibility change.
        if visible is True and before is False:
            kind = 'enemy_reappeared'
        elif visible is False and before is True:
            kind = 'enemy_left_vision'
        else:
            kind = 'enemy_visibility_evidence_changed'
        # Recheck the options that relied on this sighting, including evidence
        # for an ally to follow up. If no option cited it, the new visibility
        # remains a general alert with no claimed option-specific attribution.
        affected = [o['id'] for o in options if old_id in o['fact_refs'] or any(
            old_id in need['fact_refs'] for need in o['ally_requirements'])]
        signal(kind, row['entity_id'], fid, 'recheck_enemy_response_and_route', affected)

    # New public kills can repeat with the same victim and killer. Scan the feed
    # itself: a value-only transition would miss that second event.
    latest_kill = {}
    for fid in frame.get('recent_public_combat_ids', []):
        fact = facts[fid]
        actor = fact['entity_id']
        if (actor not in allies or fact['field'] != 'public_kill_feed'
                or fact['temporal_scope'] != 'historical_event_not_current_death_state'
                or fact['value'].get('victim_entity_id') != actor
                or since is None or fact['observed_at_seconds'] <= since):
            continue
        latest_kill[actor] = max(latest_kill.get(actor, -1), fact['observed_at_seconds'])
        requirements = allies[actor]['requirements']
        if requirements:
            signal('required_ally_killed', actor, fid, 'withdraw_prior_followup_assumption',
                   [r['option_id'] for r in requirements])

    for fid, fact in facts.items():
        actor = fact['entity_id']
        value = fact['value']
        if (actor not in allies or fact['field'] != 'action_observation'
                or fact['temporal_scope'] != 'observed_action' or not isinstance(value, dict)
                or not isinstance(value.get('action_key'), str) or not value['action_key'].strip()
                or value.get('status') not in ('in_progress', 'completed')):
            continue
        allies[actor]['observed_actions'].append(dict(
            action_key=value['action_key'], observed_status=value['status'],
            observed_at_seconds=fact['observed_at_seconds'], fact_id=fid))

    for actor, ally in allies.items():
        ally['observed_actions'].sort(key=lambda row: (row['observed_at_seconds'], row['fact_id']))
        for need in ally['requirements']:
            death = latest_kill.get(actor)
            if death is not None:
                need['evidence_status'] = 'interrupted_recheck_availability'
            matches = [row for row in ally['observed_actions']
                       if row['action_key'] == need['action_key'] and row['observed_at_seconds'] > since
                       and (death is None or row['observed_at_seconds'] > death)]
            if matches:
                matched = matches[-1]
                need['evidence_status'] = 'matching_action_observed'
                need['fact_id'] = matched['fact_id']
                signal('required_action_observed', actor, matched['fact_id'],
                       'recheck_option_with_observed_response', [need['option_id']])

    if prior:
        # A public kill ends the live-objective window only for options which
        # actually depended on that objective in the preceding card.
        for fid, (change_id, old_id) in changes.items():
            fact = facts[fid]
            if fact['observed_at_seconds'] <= since:
                continue
            affected = []
            if fact['field'] == 'allied_dragon_kill':
                affected = [o['id'] for o in options if any(
                    prior['historical_facts'].get(hid, {}).get('field') == 'dragon_pit_observation'
                    for hid in o['fact_refs'])]
                if affected:
                    signal('objective_secured', fact['entity_id'], fid, 'close_prior_live_objective_window', affected)
            elif old_id and fact['field'] in ('tower_health','health') and fact['value'] == 0:
                old = prior['historical_facts'][old_id]
                affected = [o['id'] for o in options if old_id in o['fact_refs']]
                if affected and number(old['value']) and old['value'] > 0:
                    signal('referenced_health_reached_zero', fact['entity_id'], fid, 'recheck_target_or_actor_availability', affected)

    # An observed lane-composition change only reopens options relying on that
    # particular lane. Group IDs and predicted coordinates churn each frame.
    for fid, (change_id, old_id) in changes.items():
        fact = facts[fid]
        if fact['field'] != 'lane_current_units_and_groups' or old_id is None:
            continue
        old = prior['historical_facts'][old_id]
        affected = [option['id'] for option in options if old_id in option['fact_refs']]
        if not affected:
            continue
        def counts(value):
            return sorted((r['team_id'], r['kind'], r['count']) for r in value.get('counts', []))
        if counts(old['value']) != counts(fact['value']):
            signal('observed_lane_counts_changed', fact['entity_id'], fid,
                   'recheck_cost_of_leaving_lane', affected)

    preferred = card.get('recommendation', {}).get('preferred_option_id')
    reopens_preferred = any(not t['option_ids'] or preferred in t['option_ids'] or preferred is None
                            for t in triggers)
    triggers.sort(key=lambda t: (t['observed_at_seconds'], t['entity_id'], t['kind']))
    return dict(schema='round-plan-review/v1', frame_id=frame['frame_id'], at_seconds=at,
                observer_team_id=team, prior_frame_id=prior_id, goal=card.get('objective'),
                status=('no_previous_plan' if not prior else 'reopen' if reopens_preferred else 'monitor'),
                preferred_option_id=preferred, previous_action_execution='unknown',
                switch_conditions=list(card.get('recommendation', {}).get('switch_conditions', [])),
                triggers=triggers, player_last_observed_path_start=position_samples.get(player),
                allies=list(allies.values()), opponents=sightings['opponents'],
                engagement=_engagement(frame, sightings))
