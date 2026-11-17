"""Frozen patch rules and explicit impact-time hypotheses for a personal review."""
from math import fsum, isclose, nextafter
import re

from .damage_calculator import RESISTANCE_FIELD, calculate_damage
from .reasoning_frame import lookup_reference, number


FRACTION = {'type': 'number', 'minimum': 0, 'maximum': 1}
COMPONENT_KEY = '^[QWER]\\.[a-z_]+$'


def _trigger_schema(fields, required):
    return {'type': 'object', 'additionalProperties': False,
            'required': ['trigger_hit', 'ready', *required],
            'properties': {'trigger_hit': {'type': 'string', 'pattern': COMPONENT_KEY},
                           'ready': {'type': 'boolean'}, 'proc_target_health_fraction': FRACTION,
                           'proc_caster_health_fraction': FRACTION,
                           'other_hits_cannot_trigger': {'type': 'boolean', 'const': True}, **fields}}


SCENARIO_PROPERTIES = {
    'pre_hit_resistances': {'type':'object','minProperties':1,'additionalProperties':False,
        'patternProperties':{'^([QWER]\\.[a-z_]+|rune\\.[0-9]+)$':{
            'type':'object','minProperties':1,'additionalProperties':False,
            'properties':{k:{'type':'number'} for k in ('effective_armor','effective_magic_resist')}}}},
    'assume_constant_effective_armor': {'type':'boolean','const':True},
    'target_health_fraction': FRACTION,
    'pre_hit_health_fractions': {'type': 'object', 'patternProperties': {COMPONENT_KEY: FRACTION},
                                 'additionalProperties': False, 'minProperties': 1},
    'pre_hit_caster_health_fractions': {'type': 'object', 'patternProperties': {COMPONENT_KEY: FRACTION},
                                       'additionalProperties': False, 'minProperties': 1},
    'armor_after_reductions': {'type': 'number'},
    'total_percent_armor_penetration': {'type': 'number', 'minimum': 0, 'maximum': 100},
    'total_flat_armor_penetration': {'type': 'number', 'minimum': 0},
    'use_reviewed_armor_penetration': {'type': 'boolean', 'const': True},
    'pre_hit_offense': {'type': 'object', 'minProperties': 1, 'additionalProperties': False,
                        'patternProperties': {COMPONENT_KEY: {'type': 'object', 'minProperties': 1,
                            'additionalProperties': False, 'properties': {
                                k: {'type': 'number', 'minimum': 0} for k in ('bonus_ad', 'ap')}}}},
    'cheap_shot': _trigger_schema({'target_already_impaired': {'type': 'boolean'}}, ['target_already_impaired']),
    'scorch': _trigger_schema({'seconds_after_trigger': {'type': 'number', 'minimum': 0},
                               'target_still_damageable': {'type': 'boolean'}},
                              ['seconds_after_trigger', 'target_still_damageable']),
    'electrocute': _trigger_schema({
        'previous_distinct_sources_in_window': {'type': 'integer', 'minimum': 0, 'maximum': 2},
        'adaptive_damage_type': {'type': 'string', 'enum': ['physical','magic']}},
        ['previous_distinct_sources_in_window']),
    'dark_harvest': _trigger_schema({
        'souls_before_proc': {'type':'integer','minimum':0},
        'health_fraction_at_soul_check': FRACTION,
        'adaptive_damage_type': {'type':'string','enum':['physical','magic']}},
        ['souls_before_proc','health_fraction_at_soul_check']),
    'sudden_impact': _trigger_schema({'seconds_since_qualifying_mobility': {'type':'number','minimum':0}},
                                     ['seconds_since_qualifying_mobility']),
    'shield_scenario': {'type':'object', 'additionalProperties':False,
                        'required':['universal_shield','health_before'],
                        'properties':{'universal_shield':{'type':'number','minimum':0},
                                      'health_before':{'type':'number','exclusiveMinimum':0}}},
}
PENETRATION_KEYS = {'armor_after_reductions', 'total_percent_armor_penetration',
                    'total_flat_armor_penetration', 'use_reviewed_armor_penetration'}
PROC_IDS = {'cheap_shot': 8126, 'scorch': 8237, 'electrocute': 8112, 'dark_harvest':8128, 'sudden_impact':8143}
PROC_KINDS = {'conditional_true_damage','conditional_adaptive_damage','delayed_magic_damage',
              'dark_harvest','post_mobility_true_damage'}


def validate_scenario(values, labels):
    if 'pre_hit_resistances' in values:
        per_hit = values['pre_hit_resistances']
        rune_labels = {'rune.' + str(rid) for rid in PROC_IDS.values()}
        if (not isinstance(per_hit, dict) or not per_hit or not per_hit.keys() <= labels | rune_labels
                or any(not isinstance(row, dict) or not row
                       or not row.keys() <= {'effective_armor','effective_magic_resist'}
                       or not all(number(v) for v in row.values()) for row in per_hit.values())):
            raise ValueError('invalid_pre_hit_resistances')
    if 'assume_constant_effective_armor' in values:
        if values['assume_constant_effective_armor'] is not True:
            raise ValueError('constant_armor_requires_explicit_true')
        if any('effective_armor' in row for row in values.get('pre_hit_resistances', {}).values()):
            raise ValueError('choose_constant_or_per_hit_armor')
    for name in ('target_health_fraction', 'total_percent_armor_penetration', 'total_flat_armor_penetration',
                 'armor_after_reductions'):
        if name not in values:
            continue
        value = values[name]
        schema = SCENARIO_PROPERTIES[name]
        if not number(value) or value < schema.get('minimum', value) or value > schema.get('maximum', value):
            raise ValueError('invalid_' + name)
    if 'target_health_fraction' in values and (len(labels) != 1 or 'pre_hit_health_fractions' in values):
        raise ValueError('specify_health_immediately_before_each_hit')
    for name in ('pre_hit_health_fractions', 'pre_hit_caster_health_fractions'):
        if name not in values:
            continue
        health = values[name]
        if (not isinstance(health, dict) or not health or not health.keys() <= labels
                or not all(number(v) and 0 <= v <= 1 for v in health.values())):
            raise ValueError('invalid_' + name)
    if 'pre_hit_offense' in values:
        stats = values['pre_hit_offense']
        if (not isinstance(stats, dict) or not stats or not stats.keys() <= labels
                or any(not isinstance(s, dict) or not s or not s.keys() <= {'bonus_ad', 'ap'}
                       or any(not number(v) or v < 0 for v in s.values()) for s in stats.values())):
            raise ValueError('invalid_impact_offense')
    if 'shield_scenario' in values:
        shield = values['shield_scenario']
        if (not isinstance(shield, dict) or shield.keys() != {'universal_shield','health_before'}
                or not all(number(v) for v in shield.values()) or shield['universal_shield'] < 0
                or shield['health_before'] <= 0):
            raise ValueError('invalid_shield_scenario')
    for key in PROC_IDS.keys() & values.keys():
        proc = values[key]
        schema = SCENARIO_PROPERTIES[key]
        if (not isinstance(proc, dict) or not proc.keys() <= schema['properties'].keys()
                or not set(schema['required']) <= proc.keys()
                or not isinstance(proc['trigger_hit'], str) or proc['trigger_hit'] not in labels
                or type(proc['ready']) is not bool):
            raise ValueError('invalid_' + key + '_trigger')
        if 'other_hits_cannot_trigger' in proc and proc['other_hits_cannot_trigger'] is not True:
            raise ValueError('other_hits_cannot_trigger_must_be_explicitly_true')
        if key == 'cheap_shot' and type(proc['target_already_impaired']) is not bool:
            raise ValueError('invalid_cheap_shot_trigger')
        for field in ('proc_target_health_fraction', 'proc_caster_health_fraction'):
            if field in proc and (not number(proc[field]) or not 0 <= proc[field] <= 1):
                raise ValueError('invalid_' + field)
        if key == 'scorch' and (not number(proc['seconds_after_trigger']) or proc['seconds_after_trigger'] < 0
                                or type(proc['target_still_damageable']) is not bool):
            raise ValueError('invalid_scorch_trigger')
        if key == 'electrocute' and (type(proc['previous_distinct_sources_in_window']) is not int
                or not 0 <= proc['previous_distinct_sources_in_window'] <= 2
                or proc.get('adaptive_damage_type', 'physical') not in ('physical','magic')):
            raise ValueError('invalid_electrocute_trigger')
        if key == 'dark_harvest' and (type(proc['souls_before_proc']) is not int or proc['souls_before_proc'] < 0
                or not number(proc['souls_before_proc']) or not number(proc['health_fraction_at_soul_check'])
                or not 0 <= proc['health_fraction_at_soul_check'] <= 1
                or proc.get('adaptive_damage_type', 'physical') not in ('physical', 'magic')):
            raise ValueError('invalid_dark_harvest_trigger')
        if key == 'sudden_impact' and (not number(proc['seconds_since_qualifying_mobility'])
                                       or proc['seconds_since_qualifying_mobility'] < 0):
            raise ValueError('invalid_sudden_impact_trigger')
    keys = values.keys() & PENETRATION_KEYS
    if keys:
        explicit = PENETRATION_KEYS - {'use_reviewed_armor_penetration'}
        frozen = {'use_reviewed_armor_penetration', 'armor_after_reductions'}
        if ('effective_armor' in values or keys not in (explicit, frozen)
                or ('use_reviewed_armor_penetration' in keys and values['use_reviewed_armor_penetration'] is not True)):
            raise ValueError('specify_one_complete_armor_penetration_scenario')


def frozen_pack(bundle):
    frame = bundle['frame']
    ref = frame['task'].get('combat_reference')
    if ref is None:
        return None
    pack = lookup_reference(bundle, ref)
    if pack['build'] != frame['decision']['build']:
        raise ValueError('combat_reference_build_mismatch')
    return pack


def personal_state(frame):
    decision = frame['decision']
    for fact in frame['facts'].values():
        if (fact['entity_id'] == decision['player_entity_id'] and fact['field'] == 'personal_client_state'
                and fact['observed_at_seconds'] == decision['at_seconds']):
            return fact['value']
    return {}


def armor_penetration(values, pack, inventory, r_profile, rank):
    if 'armor_after_reductions' not in values:
        return None
    armor = values['armor_after_reductions']
    basis = 'explicit_totals'
    if values.get('use_reviewed_armor_penetration'):
        basis = 'scenario_only_reviewed_pantheon_R_and_inventory'
        if not pack or inventory is None or not r_profile or type(rank) is not int or not 0 <= rank <= 3:
            return dict(effective_armor=None, basis=basis, missing='frozen_inventory_or_r_rank_or_profile')
        percent = round(r_profile['passive_percent_armor_penetration_by_rank'][rank - 1] * 100, 5) if rank else 0
        flat = 0
        for entry in inventory:
            item = str(entry['item_id'])
            if item not in pack['items']:
                return dict(effective_armor=None, basis=basis, missing='inventory_item_not_preloaded')
            # Only this reviewed item set is accepted. The caller explicitly excludes
            # temporary/external penetration and other sources in this counterfactual.
            if item in {'3134', '6697'}:
                desc = pack['items'][item].get('raw_description') or pack['items'][item].get('description', '')
                lethality = 10 if item == '3134' else 18
                if not re.search(rf'<attention>{lethality}</attention>\s*穿甲', desc):
                    return dict(effective_armor=None, basis=basis, missing='unconfirmed_lethality_' + item)
                if entry['count'] != 1:
                    return dict(effective_armor=None, basis=basis, missing='unreviewed_stacking_' + item)
                flat += lethality
            elif item not in {'1028', '1036', '1102', '2422', '3071', '3111', '3133', '3364'}:
                return dict(effective_armor=None, basis=basis, missing='unreviewed_item_penetration_' + item)
    else:
        percent = values['total_percent_armor_penetration']
        flat = values['total_flat_armor_penetration']
    effective = max(0.0, armor * (1 - percent / 100) - flat) if armor > 0 else armor
    return dict(armor_after_reductions=armor, total_percent_armor_penetration=percent,
                total_flat_armor_penetration=flat, effective_armor=effective, basis=basis,
                order='target armor after reductions, then total percentage penetration, then flat penetration; '
                      'penetration cannot cause negative armor or change negative armor',
                flat_penetration_source='https://www.leagueoflegends.com/en-us/news/game-updates/patch-14-1-notes/')


def _sum_interval(rows, field):
    intervals = [row[field] for row in rows]
    if any(pair is None for pair in intervals):
        return None
    return [fsum(pair[i] for pair in intervals) for i in (0, 1)]


def _evaluated_hit(part, raw, factors, resistances, health_amp=None, true_policy=None):
    label = part['label']
    if part['damage_type'] == 'true' and health_amp and factors[1] > 1 and (raw is None or raw[1] > 0):
        # Only verified QWER components can enter this tool through ability_damage.
        # Summoner spells, item / jungle pet damage and arbitrary proc types are outside that contract.
        source = 'champion_ability' if re.fullmatch(COMPONENT_KEY, label) else label
        if ('true' not in health_amp.get('validated_damage_types', ()) or
                source not in (true_policy or {}).get('evaluated_sources', ())):
            return dict(label=label, damage_type='true', raw_before_amplifier_interval=raw,
                        raw_interval=None, after_resistance_interval=None,
                        reason='health_amplifier_on_true_damage_unverified')
    interval = None if raw is None else [v * m for v, m in zip(raw, factors, strict=True)]
    after = None
    if interval is not None:
        endpoints = [calculate_damage([{**part, 'raw_damage': x}], **resistances)['after_resistance_total']
                     for x in interval]
        if None not in endpoints:
            after = endpoints
    return dict(label=part['label'], damage_type=part['damage_type'], multiplier_interval=factors,
                effective_resistance=resistances.get(RESISTANCE_FIELD[part['damage_type']]),
                raw_interval=interval, after_resistance_interval=after)


def _amp_interval(rule, fraction, caster_fraction=None):
    if rule is None:
        return [1.0, 1.0]
    if rule['kind'] == 'caster_low_health_amp':
        maximum = 1 + rule['max_bonus']
        if caster_fraction is None:
            return [1.0, maximum]
        if caster_fraction >= rule['below_health']:
            return [1.0, 1.0]
        if caster_fraction <= rule['max_at_health']:
            return [maximum, maximum]
        return [1 + rule['min_bonus'], maximum]
    if fraction is None:
        return [1.0, rule['multiplier']]
    if rule['kind'] == 'low_health_damage_amp':
        active = fraction < rule['target_health_fraction_below']
    else:
        active = fraction > rule['target_health_fraction_above']
    return [rule['multiplier'] if active else 1.0] * 2


def _proc_damage(key, rule, proc, level, stats):
    """A single proc per window. The caller chooses its trigger, never per-hit copies."""
    dtype = {'cheap_shot': 'true', 'scorch': 'magic', 'electrocute': None,
             'dark_harvest': None, 'sudden_impact':'true'}[key]
    active = None
    if proc:
        active = proc['ready']
        if key == 'cheap_shot':
            active = active and proc['target_already_impaired']
        elif key == 'scorch':
            active = active and proc['target_still_damageable'] and proc['seconds_after_trigger'] >= rule['delay_seconds']
        elif key == 'sudden_impact':
            elapsed = proc['seconds_since_qualifying_mobility']
            if active and elapsed == rule['armed_seconds']:
                active = None  # input time at expiry has no sub-tick order
            else:
                active = active and elapsed < rule['armed_seconds']
        elif key == 'dark_harvest':
            dtype = proc.get('adaptive_damage_type')
            active = active and proc['health_fraction_at_soul_check'] < rule['target_health_fraction_below']
        elif key == 'electrocute':
            dtype = proc.get('adaptive_damage_type')
            active = active and proc['previous_distinct_sources_in_window'] + 1 >= rule['required_distinct_attacks_or_abilities']
    if active is False:
        return dtype, [0, 0], active
    if key == 'dark_harvest':
        if not proc:
            return dtype, None, active
        amount = rule['base_damage'] + proc['souls_before_proc'] * rule['damage_per_soul']
    else:
        if type(level) is not int or not 1 <= level <= 18:
            return dtype, None, active
        amount = rule['damage_by_level'][level - 1]
    if key in ('electrocute', 'dark_harvest'):
        if stats.get('bonus_ad') is None or stats.get('ap') is None:
            return dtype, None, active
        amount += rule['bonus_ad_ratio'] * stats['bonus_ad'] + rule['ap_ratio'] * stats['ap']
    return dtype, [0 if active is None else amount, amount], active


def impact_health_fractions(values, labels, max_hp):
    health = dict(values.get('pre_hit_health_fractions', {}))
    if 'target_health_fraction' in values:
        health[labels[0]] = values['target_health_fraction']
    shield = values.get('shield_scenario')
    if shield and max_hp is not None:
        if max_hp <= 0 or shield['health_before'] > max_hp:
            raise ValueError('shield_scenario_health_exceeds_target_max_health')
        if len(labels) == 1:
            label = labels[0]
            fraction = shield['health_before'] / max_hp
            if label in health and not isclose(health[label], fraction, rel_tol=1e-9):
                raise ValueError('conflicting_target_health_at_impact')
            health[label] = fraction
    return health


def _health_branch_damage(part, branches, threshold, amp, caster_fraction, resistances):
    """Choose reachable combinations of the spell formula and the rune multiplier."""
    rows = {}
    for branch, raw in branches.items():
        endpoints = (0, nextafter(threshold, 0)) if branch == 'below' else (threshold, 1)
        multipliers = [m for hp in endpoints for m in _amp_interval(amp, hp, caster_fraction)]
        rows[branch] = _evaluated_hit(part, raw, [min(multipliers), max(multipliers)], resistances)
    def envelope(field):
        values = [r[field] for r in rows.values()]
        return None if None in values else [min(v[0] for v in values), max(v[1] for v in values)]
    return dict(label=part['label'], damage_type=part['damage_type'], health_branches=rows,
                multiplier_interval=envelope('multiplier_interval'), raw_interval=envelope('raw_interval'),
                effective_resistance=resistances.get(RESISTANCE_FIELD[part['damage_type']]),
                after_resistance_interval=envelope('after_resistance_interval'))


def rune_damage(page, pack, parts, bounds, resistances, values, level, stats, *, champion=None, impact_resistances=None,
                health_branches=None):
    """Calculate outgoing spell and reviewed rune contributions, before shields.

    All selected hits use the displayed/supplied impact attributes. No
    simulation of intervening casts, ticking cooldowns or stat changes.
    """
    impact_resistances = values.get('pre_hit_resistances', {}) if impact_resistances is None else impact_resistances
    result = dict(status='missing_inputs', page_fact_id=page.get('fact_id') if page else None,
                  runes=[], parts=[], blockers=[], missing_inputs={}, raw_total_interval=None,
                  after_resistance_total_interval=None, after_resistance_total=None, observed_hp_loss=None,
                  scope='仅所选技能分段与施法者符文。在每种符文最多触发一次的短窗口内，'
                        '以给定命中条件与逐段属性（缺省沿用面板）求值。单段的冷却、失效或延迟仅读为该段条件。'
                        '装备触发、目标防御性符文、护盾、额外增减伤、致死上限和客户端取整另计。')
    if not pack or not pack.get('rune_rules'):
        result['blockers'].append('rune_rules_not_preloaded')
    if not page or len(page.get('perk_ids', [])) != 6 or len(page.get('shard_ids', [])) != 3:
        result['blockers'].append('complete_personal_rune_page_missing')
    if result['blockers']:
        if PROC_IDS.keys() & values.keys():
            raise ValueError('proc_requires_frozen_rune_page_and_rules')
        return result
    profile = pack['rune_rules']
    if profile['build'] != pack['build']:
        raise ValueError('rune_rule_build_mismatch')
    ids = [*page['perk_ids'], *page['shard_ids']]
    for group in ({8014,8017,8299},{8010,8112,8128,8005,8369,8229},{8126,8143}):
        if len(group.intersection(ids)) > 1:
            raise ValueError('mutually_exclusive_rune_selection')
    catalog = pack.get('runes') or {}
    seen = set()
    for rid in page['perk_ids']:
        row = catalog.get(str(rid), {})
        if 'slot_index' in row:
            key = (row['tree_id'], row['slot_index'])
            if key in seen or (key[1] == 0 and key[0] != page['primary_style_id']):
                raise ValueError('mutually_exclusive_rune_selection')
            seen.add(key)
    for key in PROC_IDS.keys() & values.keys():
        if PROC_IDS[key] not in ids:
            raise ValueError(key + '_not_equipped')
    rules = profile['rules']
    amp = None
    axiom = None
    procs = {}
    for rid in dict.fromkeys(ids):
        rule = rules.get(str(rid), {})
        kind = rule.get('kind')
        row = dict(rune_id=rid, copies=ids.count(rid), kind=kind)
        if kind in ('low_health_damage_amp','high_health_damage_amp'):
            amp = rule
            row['effect'] = '按每段命中前目标生命比例判定'
        elif kind == 'caster_low_health_amp':
            amp = rule
            row['effect'] = '按每段命中前本人的生命比例判定；中间血量只给上下界'
        elif kind == 'ultimate_amplifier':
            axiom = rule
            row['effect'] = '按精确版本已核实的技能分段标签判定单体或范围大招增幅'
        elif rid in PROC_IDS.values() and kind in PROC_KINDS:
            key = next(k for k, v in PROC_IDS.items() if v == rid)
            procs[key] = rule
            row.update(effect='按给定触发条件仅计一次，CD是否转好由命中时刻证据或显式假设提供',
                       cooldown_seconds=rule['cooldown_seconds'])
            if 'window_seconds' in rule:
                row['prior_source_window_seconds'] = rule['window_seconds']
            if 'delay_seconds' in rule:
                row['delay_seconds'] = rule['delay_seconds']
        elif kind == 'target_block_after_initial_hit':
            row['effect'] = '施法者携带的防守符文，在本次对敌伤害中无直接附伤'
        elif kind in ('adaptive_stats_in_panel', 'no_separate_spell_hit'):
            row['effect'] = '按当前面板计算，不再额外加算符文伤害'
        else:
            prefix = 'unevaluated_rune_rule_' if rule else 'unreviewed_rune_'
            result['blockers'].append(prefix + str(rid))
            if rule.get('unreviewed'):
                row['unresolved'] = rule['unreviewed']
        result['runes'].append(row)
    health = impact_health_fractions(values, [p['label'] for p in parts], stats.get('target_max_health'))
    for part in parts:
        label = part['label']
        raw = part['raw_damage']
        interval = bounds.get(label) if raw is None else [raw, raw]
        fraction = health.get(label)
        caster_fraction = values.get('pre_hit_caster_health_fractions', {}).get(label)
        factors = _amp_interval(amp, fraction, caster_fraction)
        if axiom:
            tags = profile.get('ultimate_component_tags', {}).get(champion, {}).get('components', {})
            classification = tags.get(label)
            if classification not in ('non_ultimate', 'area_ultimate', 'single_target_ultimate'):
                reason = 'ultimate_component_damage_tag_unreviewed'
            elif classification != 'non_ultimate' and factors[1] > 1:
                reason = 'stacking_ultimate_and_health_amplifiers_unreviewed'
            else:
                reason = None
            if reason:
                result['blockers'].append(reason + ':' + label)
                result['parts'].append(dict(label=label, damage_type=part['damage_type'],
                                            raw_before_amplifier_interval=interval, raw_interval=None,
                                            after_resistance_interval=None, reason=reason))
                continue
            if classification != 'non_ultimate':
                bonus = axiom['aoe_bonus'] if classification == 'area_ultimate' else axiom['single_target_bonus']
                factors = [1 + bonus] * 2
        current = {**resistances, **impact_resistances.get(label, {})}
        if health_branches and label in health_branches and fraction is None:
            alternatives = health_branches[label]
            row = _health_branch_damage(part, alternatives['raw_intervals'], alternatives['threshold'],
                                        amp, caster_fraction, current)
        else:
            row = _evaluated_hit(part, interval, factors, current, amp, profile.get('true_damage_amplification'))
        row['target_health_fraction_before_hit'] = fraction
        if amp and amp['kind'] == 'caster_low_health_amp':
            row['caster_health_fraction_before_hit'] = caster_fraction
        if axiom:
            row['ultimate_damage_tag'] = classification
        result['parts'].append(row)
    for key, rule in procs.items():
        proc = values.get(key, {})
        at_hit = values.get('pre_hit_offense', {}).get(proc.get('trigger_hit'), {})
        dtype, raw, active = _proc_damage(key, rule, proc, level, {**stats, **at_hit})
        label = 'rune.' + str(PROC_IDS[key])
        if len(parts) > 1 and active is not True and not proc.get('other_hits_cannot_trigger'):
            # A negative or unresolved test at W (or a delayed proc not yet
            # applied at W's review horizon) cannot exclude a different hit.
            # Stats, HP and readiness at the other impact can all differ.
            result['blockers'].append('unresolved_alternative_trigger_' + key)
            result['parts'].append(dict(
                label=label, damage_type=dtype or 'adaptive_unknown', raw_interval=None,
                after_resistance_interval=None, checked_hit=proc.get('trigger_hit'),
                checked_hit_applies_by_horizon=active, checked_hit_raw_interval=raw if proc else None,
                unresolved_hits=[p['label'] for p in parts if p['label'] != proc.get('trigger_hit')]))
            continue
        # A separately applied proc can use a different pre-impact target HP.
        factors = _amp_interval(amp, proc.get('proc_target_health_fraction'), proc.get('proc_caster_health_fraction'))
        if dtype is None:
            after = [0, 0] if raw == [0, 0] else None
            result['parts'].append(dict(label=label, damage_type='adaptive_unknown',
                                        raw_interval=None if raw is None else [raw[0]*factors[0],raw[1]*factors[1]],
                                        after_resistance_interval=after))
        else:
            current = {**resistances, **impact_resistances.get(label, {})}
            result['parts'].append(_evaluated_hit(dict(label=label, damage_type=dtype), raw, factors, current,
                                                 amp, profile.get('true_damage_amplification')))
    if any(row.get('reason') == 'health_amplifier_on_true_damage_unverified' for row in result['parts']):
        result['blockers'].append('health_amplifier_on_true_damage_unverified')
    if result['blockers']:
        return result
    for row in result['parts']:
        needs = []
        if row['raw_interval'] is None:
            needs.append('raw_amount_or_proc_inputs')
        dtype = row['damage_type']
        if row['after_resistance_interval'] is None and dtype in ('physical','magic'):
            key = 'effective_armor' if dtype == 'physical' else 'effective_magic_resist'
            if impact_resistances.get(row['label'], {}).get(key, resistances.get(key)) is None:
                needs.append(key)
        if dtype == 'adaptive_unknown' and row['after_resistance_interval'] is None:
            needs.append('adaptive_damage_type')
        if needs:
            result['missing_inputs'][row['label']] = needs
    raw_total = _sum_interval(result['parts'], 'raw_interval')
    after = _sum_interval(result['parts'], 'after_resistance_interval')
    exact = after[0] if after is not None and after[0] == after[1] else None
    result.update(status='conditional_subtotal' if exact is not None else 'conditional_range' if after else 'missing_inputs',
                  raw_total_interval=raw_total, after_resistance_total_interval=after,
                  after_resistance_total=exact)
    if 8010 in ids and len(parts) > 1:
        result['conqueror_sequence'] = dict(
            distinct_spell_slots=len({p['label'].split('.')[0] for p in parts}),
            impact_overrides=sorted(values.get('pre_hit_offense', {})), stacks_simulated=False,
            condition='征服者与适应之力碎片已反映在面板。仅在输入属性适用于各次命中时成立。'
                      '跨技能若新增层数，请逐段传 pre_hit_offense；同一 R 的矛和冲击波不作为两次独立施法。')
    if 'shield_scenario' in values:
        shield = values['shield_scenario']
        result['conditional_hp_loss_interval'] = (None if after is None else [
            min(shield['health_before'], max(0, x - shield['universal_shield'])) for x in after])
        result['shield_condition'] = '仅给定的一层通用护盾，所有分段内无盾值变化、免疫、治疗、其他增减伤或并发伤害。'
    return result
