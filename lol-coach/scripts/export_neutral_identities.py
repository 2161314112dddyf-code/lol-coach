"""Decode neutral model names/positions from original exact-build replays."""
from collections import Counter
import json,math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.neutral_identity import decode_model, stationary_position
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed,reference
from export_skill_ranks import STEMS


def main():
    f,*_,deps=load_reviewed(ROOT.parent);summary=[]
    static=ROOT/'data/raw/68aec4f56ef93e8f35b49b2ab4ea345d838945a13dc549090a673bb3c7528317.bin'
    units=json.loads(static.read_text())['{a5773026}']['units']
    records={v['CharacterRecord'] for v in units.values()}
    map12=ROOT/'data/research/world_sources/raw/796314255a582977e917bb59d8d6dbfdcd9c1f1f839e9efdde14bda7e037526c.bin'
    relic=json.loads(map12.read_text())['Characters/HA_AP_HealthRelic']
    if relic['name']!='HA_AP_HealthRelic':raise ValueError('Relic source mismatch')
    records.add('Characters/HA_AP_HealthRelic')
    for stem in STEMS:
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        ref=reference(source);version,*_=read_metadata(source.read_bytes());identities={};names=[];positions=[];rejected=[];checks=[]
        for p in f.packets(source):
            actor=hex(p['param'])
            if p['opcode']!=0x2df and not(p['opcode']==0x37d and actor in identities):continue
            row=dict(entity_id=actor,time_seconds=p['time'],source=dict(stream=p['stream'],chunk=p['chunk'],
                decompressed_offset=p['offset'],opcode=hex(p['opcode']),payload_hex=p['payload'].hex()))
            try:
                if p['opcode']==0x2df:
                    value=decode_model(p['payload'],version=version)
                    if value['character_record'] not in records:raise ValueError('No static character reference')
                    if actor in identities:checks.append(dict(entity_id=actor,name_stable=identities[actor]['model_name']==value['model_name']))
                    identities[actor]=value;names.append(dict(**row,identity=value))
                else:positions.append(dict(**row,**stationary_position(p['payload'],version=version)))
            except ValueError as exc:rejected.append(dict(**row,reason=str(exc)))
        first={}
        for r in positions:
            if r['source']['stream']==1:first.setdefault(r['entity_id'],r)
        groups=[]
        for actor,pos in first.items():
            name=identities[actor]['model_name'];root=name.removesuffix('Mini')
            if name=='HA_AP_HealthRelic':continue
            candidates=[(other,p)for other,p in first.items()if identities[other]['model_name']==root
                and abs(p['time_seconds']-pos['time_seconds'])<.1 and math.dist(p['position_xz'],pos['position_xz'])<500]
            if len(candidates)==1:
                groups.append(dict(entity_id=actor,model_name=name,runtime_camp_group_anchor=candidates[0][0],
                    grouping_method='same model family, spawn time and stationary position within 500 units',
                    protocol_camp_id=None,position=pos))
        if reference(source)!=ref:raise ValueError('Replay changed')
        s=dict(replay=stem,name_records=len(names),entities=len(identities),position_records=len(positions),rejected=len(rejected),
            name_repeats=len(checks),name_conflicts=sum(not r['name_stable']for r in checks),
            models=dict(Counter(r['model_name']for r in identities.values())),runtime_camp_groups=len({r['runtime_camp_group_anchor']for r in groups}))
        bundle=dict(schema='neutral-identities/v1',version=version,source=ref,dependencies=deps,static_reference=reference(static),map12_reference=reference(map12),
            name_events=names,position_events=positions,derived_camp_membership=groups,
            rejected=rejected,repeat_checks=checks,summary=s,decision_input_eligible=False,
            limitations=['Runtime instance-name and numeric camp-ID remain unknown',
                'Only six observed neutral models; no Krug/Gromp/dragon/Baron decoder claim',
                'Stationary compound positions only; no moving-position interpolation',
                'Camp grouping is derived, not a decoded ownership/team field'])
        (ROOT/'data/private/replay_completion'/(stem+'-neutral-identities.json')).write_text(json.dumps(bundle,indent=2),encoding='utf8');summary.append(s)
    (ROOT/'data/private/replay_completion/neutral_identity_run.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))


if __name__=='__main__':main()
