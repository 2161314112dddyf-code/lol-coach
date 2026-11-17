"""Reproduce Pantheon's standard Map11 damage profile from the reviewed 16.22 client assets."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct

import xxhash

from lol_coach.ability_damage_data import PROFILE
from lol_coach.prop_reader import Reader, fnv
from lol_coach.wad import WadReader


BUILD = '16.22.836.1077'
SPELL_BIN = 'data/characters/pantheon/pantheon.bin'
STRING_TABLE = 'data/menu/en_us/lol.stringtable'
BIN_SHA = '366f02ef3dee9859140fc9faedc120b58b41a913d20c3f23db78b422cceed9ac'
RST_SHA = 'a66c16185f2b2e224564230014e1c178f513526e7633f43c64148afa6de64fc9'
TOOLTIPS = dict(Q='Spell_PantheonQ_Tooltip', W='Spell_PantheonW_Tooltip', R='Spell_PantheonRJump_Tooltip')
NAMES = """mScriptName mSpell DataValues name values mSpellCalculations mFormulaParts mCoefficient
mStat mStatFormula mDataValue mModifiedGameCalculation mMultiplier mClientData mTooltipData
GameCalculation GameCalculationModified NamedDataValueCalculationPart StatByCoefficientCalculationPart
StatByNamedDataValueCalculationPart DamageCalc MinDamage MaxHealthDamageCalc HoldDamageCalc TapDamageCalc
BaseDamage APRatio HoldDamage TapDamage EdgeDamageReduction MaxHealthDamage MaxHealthPer100AP
ExecuteDamageCalcModified HoldExecuteDamage SumOfSubPartsCalculationPart mSubparts
cooldownTime castRange mana""".split()


def tooltips(raw, keys=TOOLTIPS):
    """Observed RST v5, 38-bit XXH3 keys; see CommunityDragon/CDTB cdtb/rstfile.py."""
    if raw[:4] != b'RST\x05':
        raise ValueError('unsupported RST header')
    count, = struct.unpack_from('<I',raw,4)
    end = 8 + 8 * count
    if end >= len(raw):
        raise ValueError('bad RST index')
    mask = (1<<38)-1
    wanted = {xxhash.xxh3_64_intdigest(k.lower().encode()) & mask:s for s,k in keys.items()}
    found = {}
    for entry, in struct.iter_unpack('<Q',memoryview(raw)[8:end]):
        slot = wanted.get(entry & mask)
        if slot is None:
            continue
        start = end + (entry >> 38)
        stop = raw.find(b'\0',start)
        if stop < start or slot in found:
            raise ValueError('invalid tooltip string')
        found[slot] = raw[start:stop].decode('utf8')
    if found.keys() != keys.keys():
        raise ValueError('missing reviewed spell tooltip')
    return found


def values(spell, name):
    row, = [r for r in spell['DataValues'] if r['name'] == name]
    return row['values']


def calculation(spell, name):
    calc = dict(spell['mSpellCalculations'])[name]
    if calc['__type'] != 'GameCalculation':
        raise ValueError(f'unexpected calculation type for {name}')
    return calc['mFormulaParts']


def coefficient(part, stat, formula=0):
    if (part['__type'],part.get('mStat',0),part.get('mStatFormula',0)) != (
            'StatByCoefficientCalculationPart',stat,formula):
        raise ValueError('unexpected scaling stat or operation')
    return part['mCoefficient']


def named(part, field, kind='NamedDataValueCalculationPart'):
    if part['__type'] != kind or part['mDataValue'] != field:
        raise ValueError(f'unexpected data reference for {field}')


def component(label, slot, damage_type, base, coeff, condition, **extra):
    return dict(label=label,rank_slot=slot,damage_type=damage_type,base_by_rank=base,
                coefficients=coeff,condition=condition,**extra)


def extract(game_dir):
    base = game_dir / 'DATA/FINAL'
    raw, b = WadReader(base/'Champions/Pantheon.wad.client').extract_bytes(SPELL_BIN)
    strings, s = WadReader(base/'Localized/Global.en_US.wad.client').extract_bytes(STRING_TABLE,max_bytes=30_000_000)
    if (b['sha256'],s['sha256']) != (BIN_SHA,RST_SHA):
        raise ValueError('unreviewed client spell or localization asset')
    text = tooltips(strings)
    entries = Reader(raw,{fnv(n):n for n in NAMES}).parse()['entries']
    spells = {}
    for slot,key in TOOLTIPS.items():
        spell, = [v['mSpell'] for v in entries.values() if v.get('mScriptName') == 'Pantheon'+slot]
        tooltip = spell['mClientData']['mTooltipData']
        if dict(tooltip['{0381f7e2}']).get('keyTooltip') != key:
            raise ValueError('tooltip not bound to equipped spell')
        count = dict(tooltip['{91ed07c9}'])['LevelUp']['{071a48dc}']
        spells[slot] = dict(data=spell, max_rank=count)
    q,w,r = (spells[k]['data'] for k in 'QWR')
    if [spells[k]['max_rank'] for k in 'QWR'] != [5,5,3]:
        raise ValueError('unexpected rank limits')
    for slot,tokens in dict(R=['<physicalDamage>@spell.PantheonQ:HoldDamageCalc@','<magicDamage>@DamageCalc@',
                               '@EdgeDamageReduction*100@% at the edges'], Q=['<physicalDamage>@TapDamageCalc@',
                               '<physicalDamage>@HoldDamageCalc@','@DamageFalloff*100@% less to further targets',
                               'below @CritHealthThreshold*100@% Health to deal <physicalDamage>@ExecuteDamageCalcModified@'],
                            W=['<physicalDamage>@MaxHealthDamageCalc@ max Health physical damage']).items():
        if any(token not in text[slot] for token in tokens):
            raise ValueError(f'localized effect binding changed for {slot}')

    qbase,ad,ap = calculation(q,'HoldDamageCalc')
    named(qbase,'HoldDamage')
    qbase_tap,ad_tap = calculation(q,'TapDamageCalc')
    named(qbase_tap,'TapDamage')
    held = values(q,'HoldDamage')[1:6]
    coef = dict(bonus_ad=coefficient(ad,2,2),ap=coefficient(ap,0))
    falloff = 1-values(q,'DamageFalloff')[1]
    execute_sum, execute_ad = calculation(q, 'ExecuteDamageCalcModified')
    if execute_sum['__type'] != 'SumOfSubPartsCalculationPart':
        raise ValueError('unexpected Q low-health base')
    left, right = execute_sum['mSubparts']
    named(left, 'HoldDamage')
    named(right, 'HoldExecuteDamage')
    execute_base = [a+b for a,b in zip(held, values(q, 'HoldExecuteDamage')[1:6], strict=True)]
    if execute_base != values(q, 'ExecuteBaseDamage')[1:6]:
        raise ValueError('Q low-health base disagrees with its level-up table')
    threshold, = set(values(q, 'CritHealthThreshold')[1:6])
    # The user-facing fraction is the percent from the client tooltip. Avoid
    # comparing a decimal 20% against the larger binary32 encoding of 0.2.
    threshold = round(threshold * 100, 5) / 100
    execute_coef = coefficient(execute_ad, 2, 2)
    base_part, ap_part = calculation(r,'DamageCalc')
    named(base_part,'BaseDamage')
    named(ap_part,'APRatio','StatByNamedDataValueCalculationPart')
    if ap_part.get('mStat',0) != 0 or ap_part.get('mStatFormula',0) != 0:
        raise ValueError('ultimate AP scaling changed')
    base_r = values(r,'BaseDamage')[1:4]
    ratio = values(r,'APRatio')[1]
    edge = 1-values(r,'EdgeDamageReduction')[1]
    base_w,bhp_w,ap_w = calculation(w,'MaxHealthDamageCalc')
    named(base_w,'MaxHealthDamage')
    named(ap_w,'MaxHealthPer100AP','StatByNamedDataValueCalculationPart')

    desc = {}
    for slot,entry in spells.items():
        data, n = entry['data'],entry['max_rank']
        desc[slot] = dict(max_rank=n,range_by_rank=data['castRange'][1:n+1] if slot!='Q' else [],
                          base_cooldown_seconds=data['cooldownTime'][1:n+1],
                          base_mana_cost=data['mana'][1:n+1],components={})
    desc['R'].update(mutually_exclusive=[['landing_center','landing_edge']],
                     hit_geometry='前置矛与落地波可各自命中。中心至外缘的精确衰减曲线未建模。',
                     passive_percent_armor_penetration_by_rank=values(r,'ArmorPenetration')[1:4])
    desc['R']['components'] = dict(
        landing_center=component('R 落地中心','R','magic',base_r,{'ap':ratio},'冲击波最大伤害区命中'),
        landing_edge=component('R 落地最外缘','R','magic',[x*edge for x in base_r],{'ap':ratio*edge},'冲击波命中且达到最大衰减'),
        spear=component('R 前置矛','Q','physical',held,coef,
                        '前置矛小范围命中，按 R 自身提示的 Q.HoldDamageCalc 结算。未找到 R 继承 Q 低血替换的独立证据。'))
    desc['Q'].update(hold_range_world=values(q,'HoldRange')[1], mutually_exclusive=[['tap','throw_first','throw_secondary']],
                     unsupported='仅非满被动的 Q。强化 Q 的额外伤害不在这些分段中。',
                     low_health_rule=dict(target_health_fraction_below=threshold,
                         calculation='ExecuteDamageCalcModified', threshold_data_value='CritHealthThreshold',
                         condition='以目标被这段 Q 命中前的当前生命除以最大生命判定；护盾不算生命。'))
    desc['Q']['components'] = dict(
        tap=component('Q 短按','Q','physical',values(q,'TapDamage')[1:6],{'bonus_ad':coefficient(ad_tap,2,2)},'未强化短按命中英雄'),
        throw_first=component('Q 投掷首个目标','Q','physical',held,coef,'未强化蓄力投掷首个命中目标'),
        throw_secondary=component('Q 投掷穿透目标','Q','physical',[x*falloff for x in held],
                                  {k:v*falloff for k,v in coef.items()},'未强化蓄力投掷，穿过首个目标后命中英雄'))
    for name, part in desc['Q']['components'].items():
        factor = falloff if name == 'throw_secondary' else 1
        part['low_health'] = dict(base_by_rank=[n * factor for n in execute_base],
                                  coefficients={'bonus_ad': execute_coef * factor})
        if name != 'tap':
            part['low_health']['requires_zero_ap'] = True
            part['low_health']['scope'] = ('客户端替代公式未绑定投掷低血量时的法强系数。'
                                            '当前仅对命中时法强为 0 的投掷核算该分支。')
    desc['W']['components'] = dict(vault=component('W 盾跃冲击','W','physical',values(w,'MaxHealthDamage')[1:6],
            dict(bonus_health=coefficient(bhp_w,12,2),ap=values(w,'MaxHealthPer100AP')[1]),
            '对英雄命中盾跃本体；强化后的三次攻击及装备效果不计',multiply_by='target_max_health'))
    return dict(build=BUILD,champion='Pantheon',scope='标准召唤师峡谷，对英雄，未套用其他模式覆盖或附加效果。',
        source=dict(spell_asset=SPELL_BIN,spell_sha256=b['sha256'],spell_archive='DATA/FINAL/Champions/Pantheon.wad.client',
                    tooltip_asset=STRING_TABLE,tooltip_archive='DATA/FINAL/Localized/Global.en_US.wad.client',
                    tooltip_sha256=s['sha256'],tooltip_keys=TOOLTIPS,
                    tooltip_text_sha256={k:sha256(t.encode()).hexdigest() for k,t in text.items()}), abilities=desc)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    data=extract(args.game_dir)
    if args.output:
        args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    elif json.loads(PROFILE.read_bytes()) != data:
        parser.exit(1,'stored profile differs from client extraction\n')
    print('Verified exact spell and tooltip assets for',BUILD)
