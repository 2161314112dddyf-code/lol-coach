"""Compare early paired births with versioned barracks rules; retain inference boundary."""
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    refs=json.loads((ROOT/'reports/world_map_sources.json').read_text(encoding='utf8'))
    source=next(s for s in refs if s['source_id']=='world-map12-16.20')
    path=ROOT/'data/research/world_sources'/source['evidence_path'];raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('Map source changed')
    data=json.loads(raw)
    key='{2dd5c6a6}';config=data[key]
    character_sources=json.loads((ROOT/'reports/world_character_sources_corrected.json').read_text(encoding='utf8'))
    units={}
    for unit in config['units']:
        if unit['MinionType'] not in (4,5,6):continue
        template=data[unit['{fee040bc}']];name=template['name']
        ref=next(s for s in character_sources if '/'+name.lower()+'/' in s['requested_url'])
        body=(ROOT/'data/research/world_sources'/ref['evidence_path']).read_bytes()
        if hashlib.sha256(body).hexdigest()!=ref['sha256']:raise ValueError('Character source changed')
        record=json.loads(body)[template['Character']['CharacterRecord']]
        units[unit['MinionType']]=dict(character=name,base_health=record['baseHPModifiable']['baseValue'],
            unit_tags=record['unitTagsString'],upgrade=unit['MinionUpgradeStats'],source=ref)
    world=json.loads((ROOT/'data/private/world_objects/HN1-11360086609.json').read_text(encoding='utf8'))
    waves=[];classified=[]
    for wave in range(5):
        expected_start=config['InitialSpawnTimeSecs']+wave*config['WaveSpawnIntervalSecs']
        pairs=[p for p in world['birth_pair_candidates'] if expected_start<=p['time_seconds']<expected_start+6]
        # Explicit hypothesis: upgrades are applied at spawn and every two waves,
        # with floored HP. This is a reference fit, not a decoded game-mode enum.
        n=wave//2+1;counts={4:0,5:0,6:0};observations=[]
        for pair in pairs:
            fits=[]
            for kind,u in units.items():
                g=u['upgrade'];hp=math.floor(u['base_health']+n*g['HPUpgrade']+n*(n-1)/2*g.get('HPUpgradeGrowth',0))
                if hp==pair['initial_health_candidate']:fits.append(kind)
            if len(fits)!=1:continue
            kind=fits[0];counts[kind]+=1
            row=dict(**pair,inferred_minion_type=kind,inferred_unit_tags=units[kind]['unit_tags'],
                team=None,exact_character_name=None,confidence_kind='multi_constraint_reference_fit',
                evidence=dict(map_source_sha256=source['sha256'],barracks_config_key=key,
                              character_source=units[kind]['source']),decision_input_eligible=False)
            classified.append(row);observations.append(row)
        expected_counts={4:3,5:3,6:1 if wave>=2 and wave%2==0 else 0}
        gaps=[b['time_seconds']-a['time_seconds'] for a,b in zip(observations,observations[1:])]
        gap_match=all(abs(g-config['MinionSpawnIntervalSecs'])<.01 for g in gaps)
        waves.append(dict(wave_number=wave+1,expected_start=expected_start,
            first_observed=pairs[0]['time_seconds'] if pairs else None,
            expected_pair_counts=expected_counts,observed_pair_counts=counts,
            other_pair_candidates=[p for p in pairs if p['entities'] not in [o['entities'] for o in observations]],
            birth_gaps=gaps,spacing_matches=gap_match,
            status='PASS' if counts==expected_counts and gap_match else 'INSUFFICIENT_EVIDENCE'))
    output=dict(schema='lane-wave-reference-fit/v1',source_sha256=world['source_sha256'],
        map_reference=source,barracks_config_key=key,barracks_config=config,units=units,waves=waves,
        classified_pairs=classified,decision_input_eligible=False,
        scope='First five waves only; joint count/spacing/health-growth fit to public static reference',
        map_mode_confirmed=False,limitations=['Neither runtime object names nor map ID decoded',
            'Two sides remain unassigned; later waves/buildings/objectives not covered',
            'No nonhero visibility or current-lane-control inference',
            'Reference match narrows candidates, not proof that the map or mode is uniquely identified'])
    (ROOT/'data/private/world_objects/early_wave_reference_fit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    summary=dict(waves=len(waves),reference_fits=sum(w['status']=='PASS' for w in waves),
        classified_pairs=len(classified),candidate_entities=2*len(classified),map_mode_confirmed=False)
    (ROOT/'reports/wave_reference_validation.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(summary))


if __name__=='__main__':main()
