"""Verify the ten reviewed champion base-stat records against the 16.22.836.1077 installation."""
import argparse
import json
import math
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json
from lol_coach.prop_reader import Reader, fnv
from lol_coach.review_data_store import CLIENT_BASE_PROFILE, CLIENT_BASE_BUILD
from lol_coach.wad import WadReader


FIELDS = dict(attack_damage=['baseDamageModifiable','damagePerLevelModifiable'],
              armor=['baseArmorModifiable','armorPerLevelModifiable'], magic_resist=['baseMR','mrPerLevel'],
              health=['baseHPModifiable','hpPerLevelModifiable'])


def extract(game_dir, expected_assets):
    results = {}
    for champion, fingerprint in sorted(expected_assets.items()):
        archive = game_dir / 'DATA/FINAL/Champions' / f'{champion}.wad.client'
        asset = f'data/characters/{champion.lower()}/{champion.lower()}.bin'
        raw, receipt = WadReader(archive).extract_bytes(asset)
        if receipt['sha256'] != fingerprint:
            raise ValueError(f'{champion} differs from the reviewed client asset')
        record = f'Characters/{champion}/CharacterRecords/Root'
        names = ['BaseValue','mCharacterName',record] + [name for pair in FIELDS.values() for name in pair]
        root = Reader(raw, {fnv(s):s for s in names}).parse()['entries'][record]
        if root['mCharacterName'].lower() != champion.lower():
            raise ValueError(f'incorrect character record for {champion}')
        stats = {}
        for stat, pair in FIELDS.items():
            values = [root[name]['BaseValue'] for name in pair]
            if any(type(v) not in (float,int) or not math.isfinite(v) for v in values):
                raise ValueError(f'invalid client stat for {champion}/{stat}')
            stats[stat] = dict(zip(('level_1','growth'), (round(v,5) for v in values)))
        results[champion] = dict(stats=stats, source=dict(asset=asset, sha256=fingerprint, record=record))
    return dict(schema='client-combat-base/v1',build=CLIENT_BASE_BUILD,
                scope='精确版本英雄定义中的一级值与成长参数。局内面板、装备和增减益须另核。',
                fields={stat:[field+'.BaseValue' for field in pair] for stat,pair in FIELDS.items()},
                champions=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='write a regenerated copy; default compares against the profile')
    args = parser.parse_args()
    saved = json.loads(CLIENT_BASE_PROFILE.read_bytes())
    fingerprints = {champion:row['source']['sha256'] for champion,row in saved['champions'].items()}
    actual = extract(args.game_dir,fingerprints)
    if args.output:
        atomic_json(args.output,actual)
    elif actual != saved:
        raise ValueError('archived base statistics differ from client extraction')
    print(f"Verified {len(fingerprints)} champion records in {CLIENT_BASE_BUILD}")


if __name__ == '__main__':
    main()
