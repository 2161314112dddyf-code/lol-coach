"""Freeze the observed name/hash vocabulary with provenance and cautious roles."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT/'data/research/runtime_spell_hashes.json'
    data = json.loads(path.read_text(encoding='utf8'))
    summoner_source = json.loads((ROOT/'reports/world_summoner_source.json').read_text(encoding='utf8'))[0]
    vocabulary = {}
    helpers = ('SoundDummy', 'SFX', 'CastLockout', 'Missile', 'AttackMis', 'Orbit',
               'Passive', 'WDOT', 'VsAatrox', 'Trap', 'Slow')
    stages = {'RyzeQ', 'KayleWHeal', 'FizzEBuffer', 'FizzETwo', 'FizzEOne',
              'JhinRShot', 'KarthusWallOfPain2', 'KarthusFallenOne2', 'RyzeR2'}
    for name, wire in data['words'].items():
        if any(part in name for part in helpers): role = 'helper_or_effect'
        elif 'Return' in name: role = 'return_stage'
        elif name in stages: role = 'followup_or_alternate_stage'
        elif 'Attack' in name: role = 'weapon_attack'
        else: role = 'ability_or_summoner_name'
        vocabulary[name] = dict(wire=wire, role_hint=role,
            name_source=data['source_refs'].get(name) or (summoner_source if name.startswith('Summoner') else None),
            observed_in_calibration=name in data['phase_counts'])
    profile = dict(schema='spell-activity-profile/v1', version='16.20.824.8524',
        encoding_pairs=data['encoding_pairs'], vocabulary=vocabulary,
        calibration=dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            method='Lowercase ELF hash -> unsigned LEB128 -> observed byte substitution',
            seeds='Pantheon Q/W/E resource-cost associations; Zyra R/P distinguished by seven -100 resource transitions; then unique constrained source names',
            limitation='Calibration is not an independent test; no generic packet grammar or cooldown decode'),
        role_policy='Source script names distinguish phases; no row is automatically counted as a new cast')
    target = ROOT/'lol_coach/profiles/spell_activity_16_20.json'
    target.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(vocabulary=len(vocabulary), byte_pairs=len(data['encoding_pairs']))))


if __name__ == '__main__': main()
