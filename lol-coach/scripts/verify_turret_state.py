"""Real-data checks; final totals are validation only and never exported as time-t facts."""
import collections
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.http import save_json
from lol_coach.replay_fields import read_metadata
from lol_coach.turret_identity import decode_name,load_profile,prefix_state
from scripts.export_replay_ten import load_reviewed,reference
from scripts.export_turret_state import build


def main():
    directory=Path(r'C:\Users\21613\Documents\League of Legends\Replays')
    stems=['HN1-11360086609','HN1-11363048522','HN1-11363093470','HN1-11372643015']
    before=[reference(directory/(stem+'.rofl')) for stem in stems]
    full=json.loads((ROOT/'data/private/turret_state'/f'{stems[0]}.json').read_text())
    framer,_,_,_=load_reviewed(ROOT.parent);profile=load_profile()
    packets={(p['stream'],p['chunk'],p['offset']):p for p in framer.packets(directory/(stems[0]+'.rofl')) if p['opcode']==0xd8}
    for row in full['identity_events']:
        key=tuple(row['source'][k] for k in ('stream','chunk','offset'))
        assert decode_name(packets[key]['payload'])==row['identity']
    assert len(packets)==len(full['identity_events'])+len(full['rejected_name_packets'])
    assert all('encoding mode' in r['reason'] for r in full['rejected_name_packets'])
    # Initial 0x32 is an identity holdout, not merely a later duplicate of a fitted name.
    assert all(a['entity_id']!='0x40000032' for a in profile['anchors'])
    heldout=next(r for r in full['identity_events'] if r['entity_id']=='0x40000032' and r['time_seconds']==0)
    assert heldout['identity']['static_object_hash']=='{79224d93}'
    identities={}
    for row in full['identity_events']:identities.setdefault(row['entity_id'],row)
    assert len(identities)==10
    assert collections.Counter(v['identity']['team'] for v in identities.values())=={100:5,200:5}
    values={};bounds=0;zeros={};initial={};maxima={}
    for row in full['health_samples']:
        entity=row['entity_id'];state=values.setdefault(entity,{})
        assert row['time_seconds']>=identities[entity]['time_seconds']
        state.update(row['values'])
        if 'health' in row['values']:
            initial.setdefault(entity,row['values']['health'])
            if row['values']['health']==0:zeros.setdefault(entity,[]).append(row['time_seconds'])
        if 'health' in state and 'max_health' in state:
            assert 0<=state['health']<=state['max_health']+.01;bounds+=1
        if 'max_health' in row['values']:maxima.setdefault(entity,[]).append((row['time_seconds'],row['values']['max_health']))
    reference_path=ROOT/'data/research/object_sources/raw/bf23fc342770ff03f38eed10ff6d77fbd6471d647147cbfa005315370640ef1f.bin'
    static=json.loads(reference_path.read_bytes());static_hp_checks=[]
    for entity,event in identities.items():
        record=event['identity']['character_record']
        if record not in static:continue
        base_hp=static[record]['baseHPModifiable']['baseValue']
        assert initial[entity]==base_hp
        static_hp_checks.append(dict(entity_id=entity,record=record,initial_health=initial[entity],reference_health=base_hp))
    assert len(static_hp_checks)==8
    paired=[];destroyed=collections.Counter()
    for event in full['destruction_events']:
        entity=event['entity_id'];nearest=min(zeros[entity],key=lambda t:abs(t-event['time_seconds']))
        gap=abs(nearest-event['time_seconds']);assert gap<.04
        team=identities[entity]['identity']['team'];destroyed[team]+=1
        paired.append(dict(entity_id=entity,team=team,name=identities[entity]['identity']['name'],
            event_seconds=event['time_seconds'],zero_health_seconds=nearest,gap_seconds=gap))
    assert set(zeros)=={r['entity_id'] for r in full['destruction_events']}
    _,_,stats=read_metadata((directory/(stems[0]+'.rofl')).read_bytes())
    for player in stats:assert int(player['FRIENDLY_TURRET_LOST'])==destroyed[int(player['TEAM'])]
    assert sum(int(p['TURRETS_KILLED']) for p in stats)==len(paired)
    prefixes=[]
    for cutoff in (0,60,119,120.044,299.5,300,400,725.7,753,841):
        clipped=copy.deepcopy(full)
        for field in ('identity_events','health_samples','destruction_events'):
            clipped[field]=[r for r in full[field] if r['time_seconds']<=cutoff]
        assert prefix_state(full,cutoff)==prefix_state(clipped,cutoff)
        prefixes.append(dict(cutoff=cutoff,objects=len(prefix_state(full,cutoff)['objects'])))
    assert '0x40000031' not in prefix_state(full,119)['objects']
    shorts=[]
    for stem in stems[1:]:
        result=build(directory/(stem+'.rofl'))
        save_json(ROOT/'data/private/turret_state'/f'{stem}.json',result)
        assert not result['identity_events'] # Map11 samples must not inherit Map12 identities.
        shorts.append(dict(replay=stem,accepted=0,rejected=len(result['rejected_name_packets'])))
    after=[reference(directory/(stem+'.rofl')) for stem in stems];assert before==after
    report=dict(status='PASS',scope='developer crosscheck, no independent UI signoff',
        replay_sources=before,raw_name_packets_redecoded=len(full['identity_events']),
        heldout_identity=heldout,identities=len(identities),health_bound_checks=bounds,
        zeros_and_destructions=paired,final_total_checks=11,prefix_checks=prefixes,
        short_replay_nonmatching_names=shorts,rejected_modes=len(full['rejected_name_packets']),
        static_health_reference=reference(reference_path),static_initial_health_checks=static_hp_checks,
        initial_health=initial,max_health_samples=maxima,
        limitations=full['limitations'])
    save_json(ROOT/'reports/turret_state_real_validation.json',report)
    save_json(ROOT/'data/private/turret_state/HN1-11360086609-at400.json',prefix_state(full,400))
    print(json.dumps({k:report[k] for k in ('status','raw_name_packets_redecoded','identities','health_bound_checks','final_total_checks','rejected_modes')}))


if __name__=='__main__':main()
