"""Check the red Pantheon 07:28 scenario over stdio against independent arithmetic and cached originals."""
import argparse
import asyncio
from fractions import Fraction
import json
from math import isclose
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json, file_sha256
from lol_coach.reasoning_frame import digest
from lol_coach.review_data_store import DEFAULT_ROOT, _records
from scripts.round_review_mcp import query, round_client


def matches(interval, expected):
    return interval is not None and len(interval) == 2 and all(
        isclose(value, float(want), rel_tol=1e-7) for value, want in zip(interval, expected))


async def audit(bundle_path, root):
    bundle = json.loads(bundle_path.read_bytes())
    frame = bundle['frame']
    decision = frame['decision']
    if (decision['at_seconds'], decision['build'], decision['observer_team_id'],
            bundle['audit']['source_replay_sha256']) != (
            448, '16.22.836.1077', 200, '02fe29bdcd74eb69d182d5f22f2f2175f07a37a89df2cb44c83c6a5d3e0c744c'):
        raise ValueError('expected the red Pantheon 07:28 decision')
    enemy, = [h['entity_id'] for h in frame['lineup'] if h['relation'] == 'enemy' and h['champion'] == 'Jhin']
    checksum = file_sha256(bundle_path)
    rows = []
    async with round_client(bundle_path, checksum) as (client, protocol):
        plan = await query(client, 'review_round_plan', {})
        pin = plan['combat_preload']
        expected_perks = {8010, 9111, 9104, 8014, 8304, 8347}
        assert set(map(int, pin['runes'])) == expected_perks and pin['shard_ids'] == [5008,5008,5013]
        pack = next(row['combat_catalog'] for _, row in _records(root, '16.22')
                    if row.get('combat_catalog') and digest(row['combat_catalog']) == pin['catalog_sha256'])
        published = list(pack['sources'].values())
        for record in published:
            assert file_sha256(root/'evidence'/record['evidence_path']) == record['sha256']
        assets = pack['client_assets']
        for asset in assets:
            assert file_sha256(root/asset['local_file']) == asset['sha256']
        assert assets and {s['sha256'] for s in pack['rune_rules']['sources']} <= {a['sha256'] for a in assets}
        src = pack['sources']['runes']
        raw = json.loads((root/'evidence'/src['evidence_path']).read_bytes())
        coup, = [r for tree in raw for slot in tree['slots'] for r in slot['runes'] if r['id'] == 8014]
        assert '低于40%' in coup['longDesc'] and '8%' in coup['longDesc']

        normal = Fraction(300 * 100, 140)
        low = normal * Fraction(108, 100)
        base = {'effective_magic_resist': 40}
        cases = [
            ('actual_frame_inputs_only', {}, None, (300, 324)),
            ('unknown_pre_hit_health', base, (normal,low), (300,324)),
            ('full_health', {**base,'target_health_fraction':1}, (normal,normal), (300,300)),
            ('exactly_40_percent', {**base,'target_health_fraction':.4}, (normal,normal), (300,300)),
            ('below_40_percent', {**base,'target_health_fraction':.3999}, (low,low), (324,324)),
        ]
        for label, assumptions, after, raw_interval in cases:
            response = await query(client, 'calculate_ability_damage',
                dict(target_id=enemy,hits=[dict(slot='R',component='landing_center')],assumptions=assumptions))
            result = response['rune_damage']
            assert result['observed_hp_loss'] is None and not result['blockers']
            assert matches(result['raw_total_interval'], raw_interval)
            if after is None:
                assert result['after_resistance_total_interval'] is None
            else:
                assert matches(result['after_resistance_total_interval'], after)
            assert (result['after_resistance_total'] is None) == (after is None or after[0] != after[1])
            rows.append(dict(label=label, assumptions=assumptions, raw=result['raw_total_interval'],
                             after_resistance=result['after_resistance_total_interval']))

        # Assume each listed part hits. This tests two resistances and two independent pre-impact HP checks.
        assumptions = dict(armor_after_reductions=100, use_reviewed_armor_penetration=True,
                           effective_magic_resist=40, bonus_ad=50, pre_hit_health_fractions={
                               'R.spear':.6, 'R.landing_center':.37})
        combo = await query(client, 'calculate_ability_damage', dict(target_id=enemy,hits=[
            dict(slot='R',component='spear'), dict(slot='R',component='landing_center')], assumptions=assumptions))
        pen = combo['armor_penetration']
        assert pen['effective_armor'] == 80 and pen['total_flat_armor_penetration'] == 10
        spear = (130 + 50 * Fraction(115,100)) * Fraction(100,180)
        assert matches(combo['rune_damage']['after_resistance_total_interval'], (spear+low,spear+low))
        rows.append(dict(label='spear_then_center', assumptions=assumptions, armor=pen,
                         after_resistance=combo['rune_damage']['after_resistance_total_interval']))

        # Normal tap Q, rank three, under the same frozen loadout. The Q and rune
        # health thresholds both use this hit's pre-impact HP.
        ordinary = 130 + 50 * Fraction(115, 100)
        execute = 305 + 50 * Fraction(230, 100)
        amp = Fraction(108, 100)
        q_cases = [
                ('q_at_40_percent', .4, (ordinary, ordinary)),
                ('q_at_20_percent', .2, (ordinary*amp, ordinary*amp)),
                ('q_below_20_percent', .1999, (execute*amp, execute*amp)),
                ('q_unknown_health', None, (ordinary, execute*amp))]
        frozen_abilities = bundle['reference_library'][frame['task']['ability_damage_reference']]
        q_profile = frozen_abilities['champions']['Pantheon']['Q']
        for label, hp, expected in q_cases if 'low_health_rule' in q_profile else ():
            assumptions = dict(effective_armor=100, bonus_ad=50)
            if hp is not None:
                assumptions['target_health_fraction'] = hp
            reply = await query(client, 'calculate_ability_damage', dict(target_id=enemy,
                hits=[dict(slot='Q', component='tap')], assumptions=assumptions))
            outcome = reply['rune_damage']
            assert matches(outcome['raw_total_interval'], expected)
            assert matches(outcome['after_resistance_total_interval'], tuple(n/2 for n in expected))
            assert outcome['observed_hp_loss'] is None
            rows.append(dict(label=label, assumptions=assumptions, raw=outcome['raw_total_interval'],
                             after_resistance=outcome['after_resistance_total_interval']))
    return dict(status='PASS', schema='red-pantheon-rune-audit/v2', build=decision['build'],
                at_seconds=448, frame_id=frame['frame_id'], bundle_sha256=checksum, stdio_protocol=protocol,
                combat_catalog=pin, source_records=published, original_client_assets=len(assets),
                damage_queries=rows, scope='Actual player loadout and display; impact results are conditional arithmetic.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(audit(args.bundle, args.root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(result['status'], len(result['damage_queries']), args.output)


if __name__ == '__main__':
    main()
