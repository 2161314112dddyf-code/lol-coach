"""Extract source values without pretending static parameters are live readiness."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def verified_json(path,digest):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Source hash mismatch: '+str(path))
    return json.loads(raw)


def main():
    directory=ROOT/'data/normalized/16.20.1/en_US/catalog'
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf8'))
    champions=[]
    for row in manifest['normalized']:
        champion=row['champion'];source=row['source']
        normalized=verified_json(directory/(champion+'.json'),row['sha256'])
        raw=verified_json(ROOT/'data/research/champion_catalog'/source['evidence_path'],source['sha256'])
        if raw['version']!='16.20.1':raise ValueError('Version mismatch')
        item=raw['data'][champion]
        abilities=[]
        for i,spell in enumerate(item['spells']):
            fields={k:spell[k] for k in ('id','name','description','tooltip','cooldown','cooldownBurn',
                'cost','costType','resource','range','rangeBurn','effect','effectBurn','vars','leveltip','maxrank') if k in spell}
            abilities.append(dict(slot='QWER'[i],source_pointer=f'/data/{champion}/spells/{i}',source_values=fields))
        champions.append(dict(champion=champion,base_stats=item['stats'],passive=item['passive'],
            abilities=abilities,source=normalized['source'],map=None,mode=None,
            restrictions=['Description/formula placeholders retained; not evaluated',
                'Static costs/cooldowns/ranges do not imply actual rank, haste, resource cost or readiness',
                'Ally/opponent interactions need separate sourced rules']))
    if {c['champion'] for c in champions}!=set(manifest['expected_names']):raise ValueError('Catalog incomplete')
    target=ROOT/'data/normalized/16.20.1/en_US/ability_parameters.json'
    target.write_text(json.dumps(dict(schema='static-ability-reference/v1',patch='16.20.1',
        champions=champions,actual_game_state=False,exact_build_compatibility='not_independently_verified'),
        ensure_ascii=False,indent=2),encoding='utf8')
    internal=[]
    sources=json.loads((ROOT/'reports/world_character_sources_corrected.json').read_text(encoding='utf8'))
    for source in sources:
        data=verified_json(ROOT/'data/research/world_sources'/source['evidence_path'],source['sha256'])
        objects=[]
        for key,value in data.items():
            if not isinstance(value,dict):continue
            if value.get('__type')=='SpellObject':
                objects.append(dict(object_key=key,script_name=value.get('mScriptName'),
                    raw_spell=value.get('mSpell'),raw_buff=value.get('mBuff')))
            elif value.get('__type')=='CharacterRecord':
                objects.append(dict(object_key=key,character_name=value.get('mCharacterName'),
                    unit_tags=value.get('unitTagsString'),raw_character_record=value))
        internal.append(dict(source=source,objects=objects))
    (target.parent/'runtime_mechanics_reference.json').write_text(json.dumps(dict(
        schema='runtime-mechanics-source-reference/v1',source_patch='16.20',sources=internal,
        limitations=['Raw versioned client data, not a validated combat simulator',
            'Duplicate/hashed records and map/mode overrides remain distinct',
            'Replay object identity cannot be inferred solely from matching base health']),
        ensure_ascii=False,indent=2),encoding='utf8')
    result=dict(champions=len(champions),basic_abilities=sum(len(c['abilities']) for c in champions),
        passive_records=len(champions),internal_sources=len(internal),
        internal_objects=sum(len(s['objects']) for s in internal),
        official_source_hashes_verified=len(champions),normalized_hashes_verified=len(champions),
        internal_source_hashes_verified=len(internal),network_used=False)
    (ROOT/'reports/ability_reference_validation.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':main()
