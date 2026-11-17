"""Patch references and explicitly conditional spell damage for the selected player's review."""
from copy import deepcopy

from .combat_inputs import combat_inputs
from .damage_scenario import (SCENARIO_PROPERTIES, armor_penetration, frozen_pack, impact_health_fractions,
                              personal_state, rune_damage, validate_scenario)
from .reasoning_frame import digest, lookup_reference, number
from .review_sightings import enemy_sightings
from .round_chain import _check_bundle, _source


SLOTS = ('Q', 'W', 'E', 'R')
REF_KEY = 'ability_damage_reference'


def _lineup_profiles(bundle):
    from .ability_damage_data import damage_profile
    frame = bundle['frame']
    published = (frozen_pack(bundle) or {}).get('ability_profiles', {})
    profiles = {}
    for hero in frame['lineup']:
        champion = hero['champion']
        if champion in published:
            for slot, profile in published[champion].items():
                if slot not in SLOTS or (profile['build'], profile['champion'], profile['slot']) != (
                        frame['decision']['build'], champion, slot):
                    raise ValueError('invalid_catalog_ability_formula_scope')
                profiles.setdefault(champion, {})[slot] = profile
            continue
        for slot in SLOTS:
            profile = damage_profile(frame['decision']['build'], champion, slot)
            if profile is not None:
                profiles.setdefault(champion, {})[slot] = profile
    return dict(build=frame['decision']['build'], champions=profiles)


def session_damage_profiles(bundles, previous=None):
    """Select one formula revision for a player's sequence before any frame is upgraded."""
    frozen = None
    scope = None
    for bundle in ([previous] if previous is not None else []) + list(bundles):
        frame = _check_bundle(bundle)
        decision = frame['decision']
        lineup = sorted((hero['entity_id'], hero['champion'], hero['relation']) for hero in frame['lineup'])
        binding = (_source(bundle), decision['build'], decision['observer_team_id'], decision['player_entity_id'], lineup)
        if scope is not None and binding != scope:
            raise ValueError('ability_formula_sequence_scope_mismatch')
        scope = binding
        if REF_KEY in frame['task']:
            ref = frame['task'][REF_KEY]
            content = lookup_reference(bundle, ref)
            if ref != 'ability_damage_' + digest(content) or content['build'] != decision['build']:
                raise ValueError('invalid_frozen_ability_formula_reference')
            if frozen is not None and content != frozen:
                raise ValueError('conflicting_frozen_ability_formulas')
            frozen = content
    return frozen if frozen is not None else _lineup_profiles(bundles[0])


def pin_damage_profiles(bundle, content=None):
    """Called on the host's new copy, before the frame ID is sealed."""
    frame = bundle['frame']
    if REF_KEY in frame['task']:
        frozen = lookup_reference(bundle, frame['task'][REF_KEY])
        if content is not None and content != frozen:
            raise ValueError('conflicting_frozen_ability_formulas')
        return False
    if content is None:
        content = _lineup_profiles(bundle)
    profiles = content['champions']
    if not profiles:
        return False
    fingerprint = digest(content)
    ref = 'ability_damage_' + fingerprint
    frame['task'][REF_KEY] = ref
    frame['references'][ref] = dict(kind='client_spell_calculations', content_sha256=fingerprint,
                                    champions={name:[slot for slot in SLOTS if slot in slots]
                                               for name,slots in profiles.items()})
    bundle['reference_library'][ref] = deepcopy(content)
    return True


def _profile(bundle, champion, slot):
    frame = bundle['frame']
    ref = frame['task'].get(REF_KEY)
    if not ref:
        return None
    archive = lookup_reference(bundle, ref)
    if archive['build'] != frame['decision']['build']:
        raise ValueError('ability_profile_build_mismatch')
    return archive['champions'].get(champion, {}).get(slot)


def ability_parameters(bundle, champion, slot):
    frame = _check_bundle(bundle)
    if slot not in SLOTS or champion not in [h['champion'] for h in frame['lineup']]:
        raise ValueError('expected_lineup_champion_and_QWER_slot')
    ref = frame['task'].get('external_data_reference')
    record = lookup_reference(bundle, ref)['champions'].get(champion) if ref else None
    profile = _profile(bundle, champion, slot)
    spell = record['abilities'].get(slot) if record else None
    verified_range = None
    if profile:
        if profile.get('range_by_rank'):
            verified_range = dict(kind='cast_range', by_rank=deepcopy(profile['range_by_rank']))
        elif profile.get('hold_range_world') is not None:
            verified_range = dict(kind='charged_throw', world_units=profile['hold_range_world'])
    player = next(h for h in frame['lineup'] if h['entity_id'] == frame['decision']['player_entity_id'])
    personal = None
    if champion == player['champion']:
        observed = combat_inputs(bundle, None)
        rank = observed['ranks'].get(slot)
        personal = dict(rank=rank, rank_fact_id=observed['evidence'].get(slot),
                        reviewed_cast_range_world=None, base_cooldown_seconds=None)
        if rank and profile:
            for field, source in [('reviewed_cast_range_world', 'range_by_rank'),
                                  ('base_cooldown_seconds', 'base_cooldown_seconds')]:
                if rank <= len(profile[source]):
                    personal[field] = profile[source][rank - 1]
    return dict(frame_id=frame['frame_id'], build=frame['decision']['build'], champion=champion, slot=slot,
                personal_rank_parameters=personal,
                reviewed_range=verified_range,
                static_release=record['static_version'] if spell else None,
                published_spell=deepcopy(spell), static_source=deepcopy(record['source']) if spell else None,
                champion_combat_base_stats=deepcopy(record.get('combat_base_stats')) if record else None,
                champion_combat_base_stats_scope=record.get('combat_base_stats_scope') if record else None,
                client_combat_base_stats=deepcopy(record.get('client_combat_base_stats')) if record else None,
                reviewed_damage=deepcopy(profile), damage_reference_id=frame['task'].get(REF_KEY) if profile else None,
                scope='射程、基础冷却按等级列出。通用资料中的 range 有时是表现用字段，须按具体技能核实。'
                      '当前可施法状态、命中区域和实际剩余冷却须查当帧。')


def _scenario(assumptions, labels):
    known = {'ranks','ap','bonus_ad','target_max_health','bonus_health','effective_armor','effective_magic_resist'}
    if not isinstance(assumptions, dict) or assumptions.keys() - known - SCENARIO_PROPERTIES.keys():
        raise ValueError('unknown_damage_assumption')
    validate_scenario(assumptions, labels)
    ranks = assumptions.get('ranks', {})
    if not isinstance(ranks, dict) or any(k not in SLOTS or type(v) is not int or
            not 1 <= v <= (3 if k == 'R' else 5) for k,v in ranks.items()):
        raise ValueError('invalid_assumed_spell_rank')
    values = {k:v for k,v in assumptions.items() if k in known and k != 'ranks'}
    for k,v in values.items():
        if not number(v) or (not k.startswith('effective_') and v < 0):
            raise ValueError('invalid_damage_assumption')
    if values.get('target_max_health') == 0:
        raise ValueError('target_max_health_must_be_positive')
    return ranks, values


def _estimated_damage(parts, bounds, resistances, evidence, impact_resistances):
    """Evaluate both endpoints of linear bonus-AD terms and conditional spell branches."""
    from .damage_calculator import calculate_damage

    endpoints = []
    for index in (0, 1):
        projected = [dict(part, raw_damage=bounds[part['label']][index]) if part['label'] in bounds else part
                     for part in parts]
        endpoints.append(calculate_damage(projected, pre_hit_resistances=impact_resistances, **resistances))
    low, high = endpoints

    def interval(a, b):
        return [min(a, b), max(a, b)] if a is not None and b is not None else None

    return dict(bonus_attack_damage_estimate=deepcopy(evidence),
                parts=[dict(label=a['label'], damage_type=a['damage_type'],
                            raw_interval=interval(a['raw_damage'], b['raw_damage']),
                            after_resistance_interval=interval(a['after_resistance'], b['after_resistance']))
                       for a, b in zip(low['parts'], high['parts'])],
                raw_total_interval=interval(low['raw_total'], high['raw_total']),
                after_resistance_total_interval=interval(low['after_resistance_total'], high['after_resistance_total']))


def _component_at_health(profile, component, ranks, stats, ad_estimate, hp):
    from .ability_damage_data import raw_component

    def evaluate(low):
        part = raw_component(profile, component, ranks, stats, low_health=low)
        raw = part['raw_damage']
        interval = None if raw is None else [raw, raw]
        if part['missing'] == ['bonus_ad'] and ad_estimate:
            interval = [raw_component(profile, component, ranks, {**stats, 'bonus_ad': ad_estimate[key]},
                                      low_health=low)['raw_damage'] for key in ('lower', 'upper')]
        return part, interval

    rule = profile.get('low_health_rule')
    if not rule:
        part, interval = evaluate(False)
        if profile['champion'] == 'Pantheon' and profile['slot'] == 'Q':
            # Historical frozen snapshots can only attest to their ordinary Q formula.
            part['missing'].append('low_health_rule_not_in_frozen_profile')
            part['raw_damage'], interval = None, None
        return part, interval, None
    threshold = rule['target_health_fraction_below']
    active = None if hp is None else hp < threshold
    status = dict(threshold=threshold, pre_hit_health_fraction=hp,
                  branch='unresolved' if active is None else 'below' if active else 'at_or_above',
                  low_health_calculation=rule['calculation'])
    if active is not None:
        part, interval = evaluate(active)
        return part, interval, status
    high, high_range = evaluate(False)
    low, low_range = evaluate(True)
    status['raw_intervals'] = {'at_or_above':high_range, 'below':low_range}
    interval = (None if low_range is None or high_range is None else
                [min(low_range[0], high_range[0]), max(low_range[1], high_range[1])])
    high.update(raw_damage=None, missing=sorted(set(high['missing'] + low['missing'] + ['pre_hit_target_health_fraction'])))
    return high, interval, status


def ability_damage(bundle, target_id, hits, assumptions):
    from .damage_calculator import calculate_damage

    frame = _check_bundle(bundle)
    target = next((h for h in frame['lineup'] if h['entity_id']==target_id and h['relation']=='enemy'), None)
    if target is None:
        raise ValueError('expected_opponent_in_frozen_lineup')
    player = next(h for h in frame['lineup'] if h['entity_id']==frame['decision']['player_entity_id'])
    if not isinstance(hits, list) or not 1 <= len(hits) <= 5:
        raise ValueError('expected_one_to_five_spell_components')
    chosen = {}
    for hit in hits:
        if not isinstance(hit,dict) or hit.keys() != {'slot','component'} or hit['slot'] not in SLOTS or not isinstance(hit['component'],str):
            raise ValueError('invalid_spell_component')
        key = (hit['slot'],hit['component'])
        if key in chosen:
            raise ValueError('duplicate_hit_in_single_cast_scenario')
        chosen[key] = _profile(bundle,player['champion'],hit['slot'])
    assumed_ranks, values = _scenario(assumptions, {s + '.' + c for s, c in chosen})
    context = combat_inputs(bundle,target_id)
    env = context.get('environment') or {}
    known_modes = (env.get('game_mode'), env.get('map_number'))
    compatible = known_modes == ('CLASSIC',11)
    sight = next(row for row in enemy_sightings(frame)['opponents'] if row['entity_id']==target_id)
    output = dict(frame_id=frame['frame_id'], decision_seconds=frame['decision']['at_seconds'],
                  caster=player['champion'], target=target['champion'], target_id=target_id,
                  target_team_visible=sight['visible'], visibility_fact_id=sight['fact_id'],
                  observed_inputs=context, assumptions=deepcopy(assumptions), hits=deepcopy(hits),
                  map11_classic_confirmed=compatible,
                  damage_scope='selected_spell_components_only',
                  formula_reference=frame['task'].get(REF_KEY), observed_health_loss=None, kill_confirmed=None,
                  conditions=['假设各分段命中同一目标后求和；列表顺序不检验施法时序、可选中状态、距离或冷却。',
                              'damage 与 estimated_damage 只含技能本体。含施法者符文的条件计算见 rune_damage。'
                              '装备额外触发、目标护盾或减伤、其他增益和实际扣血需要单独证据。'])
    if (known_modes[0] not in (None,'CLASSIC') or known_modes[1] not in (None,11)):
        return dict(output, status='unsupported_map_or_mode', damage=None)
    if not all(chosen.values()):
        return dict(output, status='unreviewed_spell_formula', damage=None)
    # These conditions are bound to the same client tooltips as the component formulas.
    if (player['champion'], frame['decision']['build']) == ('Pantheon', '16.22.836.1077'):
        if ('W', 'vault') in chosen:
            visible = sight['visible']
            output['targeting'] = dict(
                slot='W', requires_visible_unit=True, in_cast_range_now=None,
                can_select_for_w_now=False if visible is False else None,
                condition={
                    False: '目标当前不可见，无法对它发起 W。伤害仅在目标重新可见、可选中且进入射程后适用。',
                    None: '目标可见性未知；须先确认可见、可选中且在射程内。',
                    True: '己方看得见目标。仍须检查是否可选中、距离、技能状态及其他施法条件。',
                }[visible],
                tooltip_key=chosen['W','vault']['source']['tooltip_keys']['W'])
        r_profile = next((profile for (slot,_),profile in chosen.items() if slot == 'R'), None)
        if r_profile and any(slot == 'Q' for slot,_ in chosen):
            output['cast_sequence'] = dict(
                immediate_normal_q_after_r='unsupported_empowered_q',
                condition='R 会充满被动。R 后立即施放 Q 会触发强化，当前普通 Q 分段不能用于这次紧接的 Q。'
                          '若相加，须在 R 前施放普通 Q，或在 R 后先耗掉强化并在普通状态下施放 Q。',
                tooltip_key=r_profile['source']['tooltip_keys']['R'])
    ranks = {**context['ranks'], **assumed_ranks}
    output['cast_ranks'] = {slot: ranks.get(slot) for slot, _ in chosen}
    if any(ranks.get(slot) == 0 for slot,_ in chosen):
        return dict(output, status='unlearned_spell', damage=None)
    observed = context['stats']
    stats = dict(ap=observed.get('ability_power'), bonus_ad=observed.get('bonus_attack_damage'),
                 bonus_health=observed.get('bonus_health'), target_max_health=context['defenses'].get('target_max_health'))
    stats.update(values)
    parts = []
    bounds = {}
    hp = impact_health_fractions(assumptions, [s+'.'+c for s,c in chosen], stats.get('target_max_health'))
    health_branches = {}
    bonus_ad_estimate = context.get('estimates', {}).get('bonus_attack_damage')
    missing, hit_conditions = {}, {}
    for (slot,component), profile in chosen.items():
        if component not in profile['components']:
            raise ValueError('component_not_in_reviewed_profile')
        same_slot = {name for other,name in chosen if other==slot}
        if any(len(same_slot.intersection(group))>1 for group in profile.get('mutually_exclusive', [])):
            raise ValueError('incompatible_components_for_one_cast')
        label = slot + '.' + component
        impact_stats = {**stats, **assumptions.get('pre_hit_offense', {}).get(label, {})}
        rank_slot = profile['components'][component]['rank_slot']
        # A learned spell can reference an unlearned spell. The profile
        # contains no reviewed rank-zero value for that dependency.
        part_ranks = {**ranks, rank_slot: None} if rank_slot != slot and ranks.get(rank_slot) == 0 else ranks
        part, interval, branch = _component_at_health(profile, component, part_ranks, impact_stats,
                                                     bonus_ad_estimate, hp.get(label))
        if branch:
            health_branches[label] = branch
        missing[label] = part['missing']
        hit_conditions[label] = profile['components'][component]['condition']
        parts.append(dict(label=label, damage_type=part['damage_type'], raw_damage=part['raw_damage']))
        if part['raw_damage'] is None and interval is not None:
            bounds[label] = interval
    if health_branches:
        output['spell_health_branches'] = health_branches
    defenses = {**context['defenses'], **{k:v for k,v in values.items() if k.startswith('effective_')}}
    resistances = {k: defenses.get(k) for k in ('effective_armor', 'effective_magic_resist')}
    pack = frozen_pack(bundle)
    state = personal_state(frame)
    if pack and pack.get('build') == '16.22.836.1077' and pack.get('inventory_observed'):
        items = pack['items']
        known = {'1028', '1036', '1102', '2422', '3071', '3111', '3133', '3134', '3364', '6697'}
        output['personal_item_effects'] = dict(
            items={i: row['name'] for i, row in items.items()},
            unreviewed_ids=sorted((set(items) - known) | set(pack.get('missing_items', []))),
            source=pack['sources']['items'], assumed_armor_is_after_all_reductions=True,
            notes=['面板已含装备属性。只有在明确指定穿透情景时才从装备另取穿甲。']
                  + (['狂妄的临时攻击力可能随击杀或到期而改变，使用命中时的面板。'] if '6697' in items else [])
                  + (['黑色切割者会改变目标护甲。若两次物理命中间层数有变化，'
                      '可在 pre_hit_resistances 中逐段给出结算时的有效护甲。'] if '3071' in items else []))
    if 'armor_after_reductions' in assumptions:
        r_profile = _profile(bundle, player['champion'], 'R') if player['champion'] == 'Pantheon' else None
        pen = armor_penetration(assumptions, pack, state.get('inventory'), r_profile, ranks.get('R'))
        resistances['effective_armor'] = pen['effective_armor']
        output['armor_penetration'] = pen
    page = None
    if pack is not None:
        from .replay_runes import player_runes
        page = player_runes(bundle)
    impact_resistances = deepcopy(assumptions.get('pre_hit_resistances', {}))
    spell_labels = {p['label'] for p in parts}
    rune_labels = set(impact_resistances) - spell_labels
    if rune_labels and (not page or not rune_labels <= {'rune.' + str(r) for r in page['perk_ids']}):
        raise ValueError('per_hit_resistance_on_unequipped_rune')
    inventory = state.get('inventory') or []
    cleaver = any(row.get('item_id') == 3071 and row.get('count', 0) > 0 for row in inventory)
    physical = [p['label'] for p in parts if p['damage_type'] == 'physical']
    if cleaver and physical and not assumptions.get('assume_constant_effective_armor'):
        # Hits in the caller's list need not be chronological. A global
        # starting armor cannot be assigned to an arbitrary physical hit.
        changing = list(physical) if len(physical) > 1 else []
        for key, rid in [('electrocute',8112), ('dark_harvest',8128)]:
            proc = assumptions.get(key, {})
            if (page and rid in page['perk_ids'] and proc.get('adaptive_damage_type') != 'magic'):
                changing.append('rune.' + str(rid))
        for label in changing:
            impact_resistances.setdefault(label, {}).setdefault('effective_armor', None)
        if changing:
            output['changing_armor'] = dict(item_id=3071, physical_hit_labels=changing,
                missing_pre_hit_armor=[k for k in changing if impact_resistances[k]['effective_armor'] is None],
                condition='己方持有黑色切割者。层数和叠层时机未还原。各段须给结算有效护甲，'
                          '或明确假设整段护甲固定并给出其值。')
    spell_overrides = {k: v for k, v in impact_resistances.items() if k in spell_labels}
    runes = rune_damage(page, pack, parts, bounds, resistances, assumptions, state.get('level'), stats,
                        champion=player['champion'], impact_resistances=impact_resistances, health_branches=health_branches)
    runes['combat_reference'] = frame['task'].get('combat_reference')
    damage = calculate_damage(parts, pre_hit_resistances=spell_overrides, **resistances)
    estimate = _estimated_damage(parts, bounds, resistances, bonus_ad_estimate, spell_overrides) if bounds else None
    legacy_status = 'conditional_damage' if damage['after_resistance_total'] is not None else 'missing_inputs'
    return dict(output, status=legacy_status, status_scope='legacy_spell_subtotal_only',
                primary_result='rune_damage', primary_status=runes['status'],
                missing_formula_inputs=missing, hit_conditions=hit_conditions, damage=damage, estimated_damage=estimate,
                rune_damage=runes)
