"""Read four original ROFLs, associate spawn tokens with state/path evidence."""
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.lane_identity import decode_spawn
from lol_coach.lane_attributes import super_crosscheck
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS


def main():
    f,*_,dependencies=load_reviewed(ROOT.parent)
    summaries=[]
    for stem in STEMS:
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        ref=reference(source);version,*_=read_metadata(source.read_bytes())
        world_path=ROOT/'data/private/world_objects'/(stem+'.json')
        world=json.loads(world_path.read_text())
        if world['source_sha256']!=ref['sha256']:raise ValueError('World source mismatch')
        births={r['entity_id']:r for r in world['object_births']}
        paths={}
        for r in world['nonhero_path_starts']:paths.setdefault(r['entity_id'],r)
        identities={};events=[];rejected=[];checks=[]
        for p in f.packets(source):
            if p['opcode']!=5:continue
            actor=hex(p['param'])
            row=dict(entity_id=actor,time_seconds=p['time'],
                source=dict(stream=p['stream'],chunk=p['chunk'],decompressed_offset=p['offset'],
                    opcode='0x005',payload_hex=p['payload'].hex()))
            try:identity=decode_spawn(p['payload'],version=version)
            except ValueError as exc:
                rejected.append(dict(**row,reason=str(exc)));continue
            signature=(identity['spawn_token'],identity['kind'],identity['opaque_instance_token_hex'])
            prior=identities.get(actor)
            if prior is not None:checks.append(dict(entity_id=actor,stable=prior==signature,source=row['source']))
            identities[actor]=signature
            witness=births.get(actor)
            corroboration=None
            if identity['kind']=='super_candidate' and witness:
                corroboration=super_crosscheck(witness)
                if corroboration['matched']:
                    identity.update(kind='super',classification_basis='retrospective_attribute_crosscheck',
                        classification_available_at=corroboration['witnessed_at'])
            events.append(dict(**row,identity=identity,
                class_crosscheck=corroboration,
                first_health_witness=witness,first_path_witness=paths.get(actor),
                witness_policy='retrospective crosscheck; future witnesses are not decision inputs'))
        if reference(source)!=ref:raise ValueError('Replay changed')
        summary=dict(replay=stem,accepted=len(events),rejected=len(rejected),
            live_spawns=sum(e['source']['stream']==1 for e in events),entities=len(identities),
            repeated_identity_checks=len(checks),identity_conflicts=sum(not c['stable']for c in checks),
            live_kinds=dict(Counter(e['identity']['kind']for e in events if e['source']['stream']==1)))
        bundle=dict(schema='lane-spawn-identities/v1',source=ref,version=version,
            dependencies=dependencies,world_source=reference(world_path),events=events,
            rejected=rejected,identity_checks=checks,summary=summary,
            decision_input_eligible=False,complete_world_identity=False,
            limitations=['Three common types crosschecked with wave order, static reference and health',
                'Super classification uses a later four-attribute witness; not a decoded character string',
                'Team/lane labels use spawn/path geometry; runtime map ID is not decoded',
                'No jungle-monster, ward or summoned-unit identity is claimed'])
        (ROOT/'data/private/replay_completion'/(stem+'-lane-identities.json')).write_text(json.dumps(bundle,indent=2),encoding='utf8')
        summaries.append(summary)
    (ROOT/'data/private/replay_completion/lane_identity_run.json').write_text(json.dumps(summaries,indent=2))
    print(json.dumps(summaries))


if __name__=='__main__':main()
