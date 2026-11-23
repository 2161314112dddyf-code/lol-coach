"""Selected player's native combat panel, sampled on the decision clock."""
from copy import deepcopy
import json
from pathlib import Path
import re

from .reasoning_frame import canonical, digest, number
from .review_data_store import client_combat_bases
from .review_sightings import enemy_sightings
from .round_chain import _check_bundle

PANEL_ROOT = Path(__file__).resolve().parents[1] / 'data/private/combat_panels'
OWN_STATS = ('ability_power', 'attack_damage', 'bonus_attack_damage', 'bonus_health')
DEFENSES = ('armor', 'magic_resist', 'effective_armor', 'effective_magic_resist', 'target_max_health')


def _bonus_ad_estimate(frame, owner, panel):
    """Derive an interval from the same-clock self display and the exact client character record."""
    decision = frame['decision']
    if ((decision['build'], owner['champion']) != ('16.22.836.1077', 'Pantheon')
            or panel['environment'] != {'map_number': 11, 'game_mode': 'CLASSIC'}):
        return None
    stats = panel['stats']
    displayed = stats.get('attack_damage')
    if stats.get('bonus_attack_damage') is not None or type(displayed) is not int:
        return None
    for fact_id in owner['current_fact_ids']:
        fact = frame['facts'][fact_id]
        if (fact['entity_id'] != owner['entity_id'] or fact['field'] != 'personal_client_state'
                or fact['observed_at_seconds'] != decision['at_seconds']):
            continue
        level = fact['value']['level']
        if type(level) is not int or not 1 <= level <= 18:
            raise ValueError('invalid champion level')
        character = client_combat_bases(decision['build']).get(owner['champion'])
        if character is None:
            return None
        attack = character['stats']['attack_damage']
        base, growth = attack['level_1'], attack['growth']
        multiplier = sum(0.65 + 0.035 * reached for reached in range(2, level + 1))
        base_at_level = base + multiplier * growth
        return dict(lower=displayed - 0.5 - base_at_level, upper=displayed + 0.5 - base_at_level,
                    unit='attack_damage', precision='estimated_from_integer_hud',
                    assumption='nearest_integer_total_ad_and_standard_unmodified_base_growth',
                    evidence_ids=[fact_id], level=level, base_attack_damage=base_at_level,
                    source=dict(build=decision['build'], asset=character['source']['asset'],
                                sha256=character['source']['sha256'],
                                baseDamageModifiable=base, damagePerLevelModifiable=growth,
                                input_precision='client_float32_normalized_to_five_decimal_places',
                                increment='growth * (0.65 + 0.035 * reached_level)'))
    return None


def attach_combat_inputs(bundle, root=PANEL_ROOT):
    """Freeze exact-clock, personally knowable readings before offering the bundle to MCP."""
    frame = _check_bundle(bundle)
    if 'native_combat_panel_ids' in frame:
        return bundle
    d = frame['decision']
    actor = d['player_entity_id']
    source = bundle['audit'].get('source_replay_sha256')
    if (not re.fullmatch('0x[0-9a-f]+', actor)
            or not isinstance(source, str) or not re.fullmatch('[0-9a-f]{64}', source)):
        return bundle
    path = root / source / (actor + '.json')
    if not path.is_file():
        return bundle
    record = json.loads(path.read_bytes())
    checksum = record.pop('checksum')
    scope = (record['source_sha256'], record['build'], record['own_entity_id'], record['team'])
    if (digest(record) != checksum or record['schema'] != 'own-combat-panel/v1'
            or scope != (source, d['build'], actor, d['observer_team_id'])):
        raise ValueError('combat panel scope mismatch')
    rows = [row for row in record['samples'] if row['at'] == d['at_seconds']]
    if not rows:
        return bundle
    if len(rows) != 1:
        raise ValueError('ambiguous combat panel at decision time')
    row, = rows
    stats = row['stats']
    ranks = row['ranks']
    if (row['environment'] != {'map_number': 11, 'game_mode': 'CLASSIC'}
            or not re.fullmatch('[0-9a-f]{64}', row['frame_sha256'])
            or stats.keys() - set(OWN_STATS)
            or any(not number(v) or v < 0 for v in stats.values())
            or ranks.keys() - set('QWER')
            or any(type(v) is not int or not 0 <= v <= 6 for v in ranks.values())):
        raise ValueError('invalid combat panel fields')
    result = deepcopy(bundle)
    frame = result['frame']
    owner, = [hero for hero in frame['lineup'] if hero['entity_id'] == actor]
    value = dict(ranks=ranks, stats=stats, environment=row['environment'])
    if 'remaining_cooldowns' in row:
        cooldowns = row['remaining_cooldowns']
        if (not isinstance(cooldowns, dict) or cooldowns.keys() - set('QWER')
                or any(not number(v) or v < 0 for v in cooldowns.values())):
            raise ValueError('invalid observed cooldowns')
        value['remaining_cooldowns_at_sample'] = dict(cooldowns)
    estimate = _bonus_ad_estimate(frame, owner, value)
    if estimate is not None:
        value['estimates'] = {'bonus_attack_damage': estimate}
    fact = dict(entity_id=actor, field='own_combat_panel', value=value,
                temporal_scope='displayed_native_personal_values_at_decision_clock',
                observed_at_seconds=row['at'], age_seconds=0)
    fid = 'f_' + digest(fact)[:20]
    frame['facts'][fid] = fact
    frame['native_combat_panel_ids'] = [fid]
    owner['current_fact_ids'].append(fid)
    result['audit']['fact_sources'][fid] = dict(
        source_sha256=source, frame_sha256=row['frame_sha256'], receipt=row['receipt'],
        record_checksum=checksum, basis='reviewed_native_selected_self_panel')
    frame.pop('frame_id')
    frame['frame_id'] = 'frame_' + digest(frame)[:24]
    result['audit']['frame_chars'] = len(canonical(frame))
    return result


def combat_inputs(bundle, target_id):
    """Report only inputs in the supplied frozen frame. Effective resists need separate evidence."""
    frame = _check_bundle(bundle)
    d = frame['decision']
    result = dict(environment=None, ranks=dict.fromkeys('QWER'), stats=dict.fromkeys(OWN_STATS),
                  defenses=dict.fromkeys(DEFENSES), evidence={}, estimates={}, precision='native_displayed_values')
    for fid in frame.get('native_combat_panel_ids', []):
        fact = frame['facts'][fid]
        if (fid != 'f_' + digest(fact)[:20] or fact['field'] != 'own_combat_panel'
                or fact['entity_id'] != d['player_entity_id'] or fact['age_seconds'] != 0
                or fact['observed_at_seconds'] != d['at_seconds']):
            raise ValueError('combat panel is not bound to current player and clock')
        value = fact['value']
        result['environment'] = value['environment']
        result['evidence']['environment'] = fid
        for name, interval in value.get('estimates', {}).items():
            result['estimates'][name] = dict(interval, evidence_ids=[fid, *interval['evidence_ids']])
        for key in ('ranks', 'stats'):
            result[key].update(value[key])
            for field in value[key]:
                result['evidence'][field] = fid
    if target_id:
        target = next((hero for hero in frame['lineup']
                       if hero['entity_id'] == target_id and hero['relation'] == 'enemy'), None)
        visible = any(enemy['entity_id'] == target_id and enemy['visible'] is True
                      for enemy in enemy_sightings(frame)['opponents'])
        if target and visible:
            sampled_health = {}
            for fid in target['current_fact_ids']:
                fact = frame['facts'][fid]
                if (fact['entity_id'] == target_id and fact['field'] in ('health', 'max_health')
                        and fact['temporal_scope'] == 'observed_sample' and fact['observed_at_seconds'] == d['at_seconds']
                        and number(fact['value']) and fact['value'] >= 0):
                    sampled_health.setdefault(fact['field'], []).append((fact['value'], fid))
            maximum = sampled_health.get('max_health', [])
            current = sampled_health.get('health', [])
            if len(maximum) == 1 and maximum[0][0] > 0:
                result['defenses']['target_max_health'], result['evidence']['target_max_health'] = maximum[0]
                if len(current) == 1 and current[0][0] <= maximum[0][0]:
                    result['target_health_at_decision'] = dict(
                        fraction=current[0][0] / maximum[0][0], at_seconds=d['at_seconds'],
                        evidence_ids=[current[0][1], maximum[0][1]],
                        condition='本人队伍此刻可见的血线。飞行或引导结束时需要重新判定。')
    return result
