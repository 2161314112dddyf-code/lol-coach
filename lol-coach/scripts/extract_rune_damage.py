"""Re-extract reviewed Map11 rune rules from two exact 16.22 client WAD members."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from lol_coach.prop_reader import Reader, fnv
from lol_coach.rune_damage_data import BUILD, PROFILE
from lol_coach.wad import WadReader
from scripts.extract_pantheon_ability_damage import tooltips


SOURCES = [
    dict(archive='DATA/FINAL/Global.wad.client', asset='perks', asset_hash='fe11209c1b2fb62e',
         sha256='b17c7331fb54215c998ed5288a5c77767df8ef3493cf20db990b97b5697bc26c'),
    dict(archive='DATA/FINAL/Localized/Global.en_US.wad.client', asset='data/menu/en_us/lol.stringtable',
         sha256='a66c16185f2b2e224564230014e1c178f513526e7633f43c64148afa6de64fc9'),
    dict(archive='DATA/FINAL/Champions/Pantheon.wad.client', asset='data/characters/pantheon/pantheon.bin',
         sha256='366f02ef3dee9859140fc9faedc120b58b41a913d20c3f23db78b422cceed9ac')]

# Paths are hashed again by the reader. Source names inside the tooltip template
# bind each numeric input to its field in the actual PerkScriptData.
RECORDS = {
    8014: 'Perks/Styles/Precision/CoupDeGrace', 8010: 'Perks/Styles/Precision/Conqueror',
    9111: 'Perks/Styles/Precision/Triumph', 9104: 'Perks/Styles/Precision/LegendAlacrity',
    8304: 'Perks/Styles/Inspiration/MagicalFootwear', 8347: 'Perks/Styles/Inspiration/CosmicInsight',
    5008: 'Perks/StatMods/Adaptive', 5013: 'Perks/StatMods/Tenacity',
    8126: 'Perks/Styles/Domination/CheapShot', 8112: 'Perks/Styles/Domination/Electrocute',
    8237: 'Perks/Styles/Sorcery/Scorch', 8128: 'Perks/Styles/Domination/DarkHarvest',
    8017: 'Perks/Styles/Precision/CutDown', 8143: 'Perks/Styles/Domination/SuddenImpact',
    8299: 'Perks/Styles/Precision/LastStand', 8005: 'Perks/Styles/Precision/PressTheAttack',
    8369: 'Perks/Styles/Inspiration/FirstStrike', 8229: 'Perks/Styles/Sorcery/ArcaneComet',
    8214: 'Perks/Styles/Sorcery/SummonAery', 8473: 'Perks/Styles/Resolve/BonePlating',
    8139: 'Perks/Styles/Domination/TasteOfBlood', 8140: 'Perks/Styles/Domination/GrislyMementos',
    8137: 'Perks/Styles/Domination/SixthSense', 8135: 'Perks/Styles/Domination/TreasureHunter',
    8105: 'Perks/Styles/Domination/RelentlessHunter', 8106: 'Perks/Styles/Domination/UltimateHunter',
    8009: 'Perks/Styles/Precision/PresenceOfMind', 8210: 'Perks/Styles/Sorcery/Transcendence',
    8226: 'Perks/Styles/Sorcery/ManaflowBand', 5001: 'Perks/StatMods/HealthScaling',
    5011: 'Perks/StatMods/Health', 5010: 'Perks/StatMods/MovementSpeed',
    5007: 'Perks/StatMods/CDRScaling', 5005: 'Perks/StatMods/AttackSpeed',
    8224: 'Perks/Styles/Sorcery/NullifyingOrb', 8234: 'Perks/Styles/Sorcery/Celerity',
    8230: 'Perks/Styles/Sorcery/PhaseRush', 8233: 'Perks/Styles/Sorcery/AbsoluteFocus',
    8236: 'Perks/Styles/Sorcery/GatheringStorm', 8439: 'Perks/Styles/Resolve/Aftershock',
    8463: 'Perks/Styles/Resolve/FontOfLife', 8242: 'Perks/Styles/Resolve/Unflinching',
    8453: 'Perks/Styles/Resolve/Revitalize', 8401: 'Perks/Styles/Resolve/ShieldBash',
    8429: 'Perks/Styles/Resolve/Conditioning', 8008: 'Perks/Styles/Precision/LethalTempo',
    9103: 'Perks/Styles/Precision/LegendBloodline', 9105: 'Perks/Styles/Precision/LegendHaste',
    8321: 'Perks/Styles/Inspiration/CashBack'}
NAMES = """Perk mPerkId mPerkName mLongDescLocalizationKey mDisplayNameLocalizationKey mScript mSpellScriptData mEffectAmount
mCalculations mFormulaParts mStartValue mEndValue mDataValue mStat mStatFormula
ByCharLevelInterpolationCalculationPart StatByNamedDataValueCalculationPart
DamageCalc TotalDamage BonusPercentDamage EnemyHealthPercentageThreshold MaxStacks BuffDuration
MinAdaptivePerStack MaxAdaptivePerStack HealingPercent RangedHealingPercent StatGain StatGain2
Cooldown BurnlockoutDuration WindowDuration DotDuration Damage DamageMax DamageBase DamageIncMin
DamageIncMax BonusADRatio APRatio AttackSpeedBase AttackSpeedPerStack MaxLegendStacks
ItemHaste SummonerHaste BonusGold MissingHealthRestored TriumphMaxHealthRestored
GiveBootsAtMinute SecondsSoonerPerTakedown AdditionalMovementSpeed NamedDataValueCalculationPart
HarvestThreshold DamagePerSoulEssence BaseDamage ADRatio CooldownResetValue
ArmedDuration MinDamageTooltip MaxDamageTooltip HealthThresholdStart HealthThresholdEnd
MinBonusDamagePercent MaxBonusDamagePercent HitsRequired MinDamage MaxDamage Duration DamageAmp
GraceWindow TooltipOnlyCooldownStartAmount TooltipOnlyCooldownEndAmount RechargeTime RechargeTimeMin
MaxDamageAmp MaxRange DamageAPRatio DamageADRatio BlockCount BlockBase BlockMax BlockDuration
AOEAmp UltimateRefundBase DelayBeforeBurst StartingBaseDamage MaxBaseDamage HealthRatio
FlatResists PercentBonusResist ProcBaseMin ProcBaseMax ProcDuration ShieldRatio BonusHealthRatio
TTMinNoteDamageMelee TTMaxNoteDamageMelee TTMinNoteDamageRanged TTMaxNoteDamageRanged""".split()


def rule(perk, text):
    perk_id = perk['mPerkId']
    script = perk['mScript']['mSpellScriptData']
    effects = dict(script['mEffectAmount'])

    def amount(key):
        if f'@{key.lower()}' not in text.lower():
            raise ValueError(f'{perk_id} tooltip does not use {key}')
        return round(effects[key], 7)

    # These tooltips were reviewed for one-hit contribution; in particular,
    # sustain and haste can still affect later casts, and shards modify stats.
    indirect = {
        8139: ('healing', 'Heal when you damage'),
        8140: ('trinket_haste', 'Trinket Haste'), 8137: ('ward_detection', 'sense a nearby'),
        8135: ('takedown_gold', 'gold</gold>'), 8105: ('out_of_combat_speed', 'out of combat'),
        8106: ('ultimate_haste', 'Your ultimate gains'), 8009: ('resource_restore', 'mana or'),
        8210: ('haste_and_basic_cooldown', 'remaining cooldown of basic abilities'),
        8226: ('maximum_mana_and_restore', 'maximum mana'),
        5001: ('health_in_panel', 'Health (based on level)'), 5011: ('health_in_panel', 'Health'),
        5010: ('move_speed_in_panel', 'Move Speed'), 5007: ('ability_haste_in_panel', 'Ability Haste'),
        5005: ('attack_speed_in_panel', 'Attack Speed'),
        8321: ('purchase_refund', 'Gold back'), 8234: ('move_speed_in_panel', 'movement bonuses'),
        8230: ('move_speed_and_slow_resist', 'Slow Resistance'), 8233: ('health_based_adaptive_stats_in_panel', 'AdaptiveForce'),
        8236: ('time_based_adaptive_stats_in_panel', 'gain AP or AD'), 8242: ('conditional_defenses', 'Armor and Magic Resist'),
        8429: ('defensive_stats_in_panel', 'perk_short_desc_Conditioning'), 8453: ('outgoing_and_incoming_sustain', 'Heal and Shield Power'),
        8463: ('self_and_ally_heal', 'lowest health nearby allied champion'), 9103: ('lifesteal_and_health_in_panel', 'Life Steal'),
        9105: ('basic_ability_haste', 'basic ability haste')}
    if perk_id in indirect:
        effect, binding = indirect[perk_id]
        if binding not in text:
            raise ValueError(f'unreviewed stat or utility effect for {perk_id}')
        return dict(kind='no_separate_spell_hit', effect=effect)

    # These rows modify movement, haste, attack cadence, personal stats, or
    # post-kill healing. They have no additional damage packet on Q/W/R impact.
    other = {
        9111: ('takedown_recovery_and_gold', ['MissingHealthRestored','TriumphMaxHealthRestored','BonusGold']),
        9104: ('attack_speed', ['AttackSpeedBase','AttackSpeedPerStack','MaxLegendStacks']),
        8304: ('boots', ['GiveBootsAtMinute','SecondsSoonerPerTakedown','AdditionalMovementSpeed']),
        8347: ('summoner_and_item_haste', ['SummonerHaste','ItemHaste']),
        5013: ('tenacity_and_slow_resist', ['StatGain']), 5008: ('adaptive_stats_in_panel', ['StatGain2'])}
    if perk_id in other:
        effect, keys = other[perk_id]
        return dict(kind='no_separate_spell_hit', effect=effect, parameters={k:amount(k) for k in keys})
    if perk_id == 8010:
        if 'grant 2 stacks' not in text or 'Ranged champions gain only 1 stack per basic attack' not in text:
            raise ValueError('Conqueror stack rule changed')
        return dict(kind='adaptive_stats_in_panel', max_stacks=int(amount('MaxStacks')),
                    duration_seconds=amount('BuffDuration'), spell_or_melee_attack_stacks=2,
                    ranged_basic_attack_stacks=1,
                    adaptive_force_per_stack_endpoints=[amount('MinAdaptivePerStack'), amount('MaxAdaptivePerStack')],
                    fully_stacked_melee_healing_fraction=amount('HealingPercent'),
                    fully_stacked_ranged_healing_fraction=amount('RangedHealingPercent'),
                    pre_hit_stacks='read stats at impact; a new stack can change later hits')
    if perk_id == 8014:
        if 'champions who have less than' not in text:
            raise ValueError('Coup de Grace threshold condition changed')
        return dict(kind='low_health_damage_amp', multiplier=1 + amount('BonusPercentDamage'),
                    target_health_fraction_below=amount('EnemyHealthPercentageThreshold'),
                    sample='target_before_each_hit', validated_damage_types=['physical', 'magic', 'true'])
    if perk_id == 8017:
        if 'champions who have more than' not in text:
            raise ValueError('Cut Down threshold condition changed')
        return dict(kind='high_health_damage_amp', multiplier=1 + amount('BonusPercentDamage'),
                    target_health_fraction_above=amount('EnemyHealthPercentageThreshold'),
                    sample='target_before_each_hit', validated_damage_types=['physical', 'magic', 'true'])
    if perk_id == 8128:
        if 'adaptive damage' not in text or 'on takedown' not in text or 'harvests their soul' not in text:
            raise ValueError('Dark Harvest trigger changed')
        return dict(kind='dark_harvest', target_health_fraction_below=amount('HarvestThreshold'),
                    base_damage=amount('BaseDamage'), damage_per_soul=amount('DamagePerSoulEssence'),
                    bonus_ad_ratio=amount('ADRatio'), ap_ratio=amount('APRatio'),
                    cooldown_seconds=amount('Cooldown'), takedown_reset_seconds=amount('CooldownResetValue'),
                    trigger='damaging a low-health champion; use pre-proc soul count and evidence of trigger')
    if perk_id == 8299:
        return dict(kind='caster_low_health_amp', min_bonus=amount('MinBonusDamagePercent'),
                    max_bonus=amount('MaxBonusDamagePercent'), below_health=amount('HealthThresholdStart'),
                    max_at_health=amount('HealthThresholdEnd'), unreviewed='intermediate health curve')
    if perk_id == 8005:
        return dict(kind='consecutive_attacks_and_amp', attacks=int(amount('HitsRequired')),
                    adaptive_level_endpoints=[amount('MinDamage'), amount('MaxDamage')],
                    multiplier=1+amount('BonusPercentDamage'),
                    trigger='consecutive basic attacks on one champion; amplification until leaving champion combat',
                    unreviewed='interaction between triggering hit, proc, subsequent hits and combat resets')
    if perk_id == 8369:
        return dict(kind='first_strike', grace_seconds=amount('GraceWindow'), duration_seconds=amount('Duration'),
                    extra_true_fraction=amount('DamageAmp'),
                    cooldown_endpoints=[amount('TooltipOnlyCooldownStartAmount'), amount('TooltipOnlyCooldownEndAmount')],
                    unreviewed='eligible damage basis, ordering, denial and nested proc exclusions')
    if perk_id == 8473:
        return dict(kind='target_block_after_initial_hit', hits=int(amount('BlockCount')),
                    block_level_endpoints=[amount('BlockBase'),amount('BlockMax')],
                    duration_seconds=amount('BlockDuration'), cooldown_seconds=amount('Cooldown'),
                    trigger='subsequent hits from the same champion', unreviewed='mitigation order and attack grouping')
    if perk_id == 8224:
        return dict(kind='ultimate_amplifier', single_target_bonus=amount('DamageAmp'),
                    aoe_bonus=amount('AOEAmp'), takedown_cooldown_reduction_percent=amount('UltimateRefundBase'),
                    unreviewed='per-component ultimate damage tag, single-target or area classification')
    if perk_id == 8439:
        return dict(kind='immobilize_resists_and_delayed_burst', delay_seconds=amount('DelayBeforeBurst'),
                    magic_damage_level_endpoints=[amount('StartingBaseDamage'),amount('MaxBaseDamage')],
                    bonus_health_ratio=amount('HealthRatio'), cooldown_seconds=amount('Cooldown'),
                    flat_resists=amount('FlatResists'), bonus_resist_ratio=amount('PercentBonusResist'),
                    unreviewed='actual immobilization, defense caps, delayed blast hit and additional mitigation')
    if perk_id == 8401:
        return dict(kind='new_shield_next_attack', damage_level_endpoints=[amount('ProcBaseMin'),amount('ProcBaseMax')],
                    bonus_health_percent=amount('BonusHealthRatio'), new_shield_percent=amount('ShieldRatio'),
                    window_after_shield_ends_seconds=amount('ProcDuration'),
                    unreviewed='new shield, shield amount and empowered attack consumption')
    if perk_id == 8008:
        return dict(kind='stacked_attack_speed_and_on_attack', max_stacks=int(amount('MaxStacks')),
                    duration_seconds=amount('Duration'),
                    melee_level_endpoints=[amount('TTMinNoteDamageMelee'),amount('TTMaxNoteDamageMelee')],
                    ranged_level_endpoints=[amount('TTMinNoteDamageRanged'),amount('TTMaxNoteDamageRanged')],
                    unreviewed='pre-attack stacks, attack-speed contribution and on-attack eligibility')

    calc_name = {8112:'TotalDamage', 8143:'BaseDamage'}.get(perk_id, 'DamageCalc')
    parts = dict(script['mCalculations'])[calc_name]['mFormulaParts']
    level = parts[0]
    if set(level) != {'__type','mStartValue','mEndValue'} or level['__type'] != 'ByCharLevelInterpolationCalculationPart':
        raise ValueError('unreviewed level curve')
    # The default curve interpolates over levels 1..18; reject alternate switches above.
    start, end = level['mStartValue'], level['mEndValue']
    by_level = [start + (end-start) * n/17 for n in range(18)]
    if perk_id == 8229:
        return dict(kind='comet_distance_damage', damage_by_level=by_level, bonus_ad_ratio=amount('ADRatio'),
                    ap_ratio=amount('APRatio'), max_distance=amount('MaxRange'), max_bonus=amount('MaxDamageAmp'),
                    cooldown_endpoints=[amount('RechargeTime'),amount('RechargeTimeMin')],
                    unreviewed='distance sampled at cast or impact, distance curve, cooldown reductions and hit')
    if perk_id == 8214:
        return dict(kind='aery_damage_or_shield', damage_by_level=by_level, bonus_ad_ratio=amount('DamageADRatio'),
                    ap_ratio=amount('DamageAPRatio'), trigger='ready once Aery returns; share readiness with ally shields',
                    unreviewed='travel, return, target and branch')
    if perk_id == 8143:
        if (len(parts) != 1 or 'True Damage' not in text or 'dash, leap, blink, teleport' not in text
                or [start,end] != [amount('MinDamageTooltip'),amount('MaxDamageTooltip')]):
            raise ValueError('Sudden Impact trigger or damage changed')
        return dict(kind='post_mobility_true_damage', damage_by_level=by_level,
                    armed_seconds=amount('ArmedDuration'), cooldown_seconds=amount('Cooldown'),
                    trigger='damaging attack or ability on champion after dash/leap/blink/teleport or leaving stealth')
    if perk_id == 8126:
        if (len(parts) != 1 or 'after the impairment' not in text or 'bonus true damage' not in text
                or [start, end] != [amount('DamageIncMin'), amount('DamageIncMax')]):
            raise ValueError('Cheap Shot trigger or damage changed')
        return dict(kind='conditional_true_damage', damage_by_level=by_level, cooldown_seconds=amount('Cooldown'),
                    trigger='damaging an enemy champion after movement or action impairment')
    if perk_id == 8237:
        if (len(parts) != 1 or 'next damaging ability hit' not in text or 'bonus magic damage' not in text
                or [start, end] != [amount('Damage'), amount('DamageMax')]):
            raise ValueError('Scorch trigger or damage changed')
        return dict(kind='delayed_magic_damage', damage_by_level=by_level, delay_seconds=amount('DotDuration'),
                    cooldown_seconds=amount('BurnlockoutDuration'), trigger='next damaging ability hit on a champion')
    if (perk_id != 8112 or '3 <b>separate</b> attacks or abilities' not in text or 'adaptive damage' not in text
            or [start, end] != [amount('DamageBase'), amount('DamageMax')]):
        raise ValueError('unreviewed Electrocute trigger')
    ap, ad = parts[1:]
    if (ap != {'__type':'StatByNamedDataValueCalculationPart','mDataValue':'APRatio'}
            or ad != {'__type':'StatByNamedDataValueCalculationPart','mDataValue':'BonusADRatio',
                      'mStat':2,'mStatFormula':2}):
        raise ValueError('unreviewed Electrocute scaling')
    return dict(kind='conditional_adaptive_damage', damage_by_level=by_level, bonus_ad_ratio=amount('BonusADRatio'),
                ap_ratio=amount('APRatio'), window_seconds=amount('WindowDuration'),
                required_distinct_attacks_or_abilities=3, cooldown_seconds=amount('Cooldown'))


def axiom_components(raw, strings):
    fields = ['mScriptName', 'mSpell', 'mSpellTags']
    entries = Reader(raw, {fnv(k):k for k in fields}).parse()['entries']
    tags = {row['mScriptName']:row['mSpell']['mSpellTags'] for row in entries.values()
            if row.get('mScriptName') in ('PantheonR','PantheonQ','PantheonW')}
    if (not {'Trait_Ultimate','Trait_AoE','Trait_DamageAbility'} <= set(tags['PantheonR'])
            or any('Trait_Ultimate' in tags[spell] for spell in ('PantheonQ','PantheonW'))):
        raise ValueError('Pantheon spell tag mismatch')
    description = tooltips(strings)['R']
    if ('<magicDamage>@DamageCalc@ magic damage</magicDamage> to enemies in a line' not in description
            or '<physicalDamage>@spell.PantheonQ:HoldDamageCalc@' not in description):
        raise ValueError('ultimate landing component no longer bound to the same area spell')
    return dict(tags=tags, source=SOURCES[2], tooltip='Spell_PantheonRJump_Tooltip',
                components={'R.landing_center':'area_ultimate','R.landing_edge':'area_ultimate',
                            'Q.tap':'non_ultimate','Q.throw_first':'non_ultimate',
                            'Q.throw_secondary':'non_ultimate','W.vault':'non_ultimate'},
                unresolved={'R.spear':'Q defines the spear amount; the impact damage tag has not been confirmed'})


def extract(game_dir):
    contents = []
    for source in SOURCES:
        raw, evidence = WadReader(game_dir / source['archive']).extract_bytes(source['asset'], 40_000_000)
        if evidence['sha256'] != source['sha256']:
            raise ValueError(f'unreviewed client member {source["asset"]}')
        contents.append(raw)
    names = {fnv(name):name for name in [*NAMES, *RECORDS.values()]}
    entries = Reader(contents[0], names).parse()['entries']
    keys = {perk_id:entries[path]['mLongDescLocalizationKey'] for perk_id,path in RECORDS.items()}
    texts = tooltips(contents[1], keys)
    display_names = tooltips(contents[1], {i:entries[path]['mDisplayNameLocalizationKey'] for i,path in RECORDS.items()})
    rules = {}
    for perk_id, path in RECORDS.items():
        perk = entries[path]
        if perk['__type'] != 'Perk' or perk['mPerkId'] != perk_id:
            raise ValueError('rune record identity mismatch')
        rules[str(perk_id)] = dict(name=perk['mPerkName'], display_name=display_names[perk_id], **rule(perk,texts[perk_id]),
                                   record=path, tooltip_key=keys[perk_id],
                                   tooltip_sha256=sha256(texts[perk_id].encode()).hexdigest())
    true_damage = dict(
        source_url='https://www.leagueoflegends.com/en-us/news/game-updates/patch-2025-s1-3-notes/',
        section='Bugfixes & QoL Changes',
        html_sha256='5c26e790169cdbfb568308604350b27007198f224d9ba6f2a2bb1218790e3112',
        source_quote='All sources of damage amplification now increase all true damage, except Smite and jungle pet damage.',
        quote_sha256='9432449dea776dff2d342ea7e2b807037442bf0a3883dba39dcfc5bc8dad8b21',
        evaluated_sources=['champion_ability', 'rune.8126', 'rune.8143'],
        patch_exceptions=['Smite', 'jungle pet damage'],
        scope='ordinary champion QWER components and separately reviewed Cheap Shot / Sudden Impact; summoner spells and pets outside calculator')
    return dict(schema='rune-damage-rules/v1', build=BUILD, sources=SOURCES,
                true_damage_amplification=true_damage,
                ultimate_component_tags={'Pantheon':axiom_components(contents[2], contents[1])},
                scope='CLASSIC Map11 champion targets; default perk effects, without mode overrides',
                level_interpolation_reference='https://github.com/moonshadow565/calcrev/blob/40f21c06e5cfc10750bb44b39d1f2d4e3567a6dc/calc.py#L332-L340',
                level_interpolation_source_sha256='35a130db9f9d9817206d8d02e013384e27ec088fe2f2dd9bf19140f4bd58d345',
                rules=rules)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='save a regenerated JSON copy')
    args = parser.parse_args()
    data = extract(args.game_dir)
    if args.output:
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')
    elif data != json.loads(PROFILE.read_bytes()):
        raise ValueError('archived rune rules differ from client sources')
    print(f'Verified {len(data["rules"])} rune and shard records for {BUILD}')
