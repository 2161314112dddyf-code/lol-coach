"""Extract named-tower visibility, validate channel structure, emit team views."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from lol_coach.http import save_json
from lol_coach.replay_vision import decode_payload
from lol_coach.tower_vision import enemy_tower_view
from scripts.export_replay_ten import load_reviewed,reference


def main():
    path=ROOT/'data/private/turret_state/HN1-11360086609.json'
    towers=json.loads(path.read_text(encoding='utf8'))
    replay=Path(towers['source']['path']);assert reference(replay)==towers['source']
    owners={e['entity_id']:e['identity']['team'] for e in towers['identity_events']}
    f,_,_,_=load_reviewed(ROOT.parent);events=[];previous={};opposite=0
    for p in f.packets(replay):
        entity=hex(p['param'])
        if p['stream']!=1 or p['opcode'] not in (0x484,0x3cd) or entity not in owners:continue
        value=decode_payload(p['opcode'],p['payload'],version=towers['version'])
        observer=value['observer_team_id'];key=(entity,observer)
        assert key not in previous or previous[key]!=value['visible']
        previous[key]=value['visible']
        assert observer!=owners[entity];opposite+=1
        events.append(dict(time_seconds=p['time'],entity_id=entity,**value,
            source=dict(stream=1,chunk=p['chunk'],decompressed_offset=p['offset'],opcode=hex(p['opcode']),payload_hex=p['payload'].hex())))
    bundle=dict(schema='named-tower-vision/v1',source=towers['source'],version=towers['version'],
        identity_source=reference(path),events=events,complete_world_vision=False,
        evidence='Known tower identities independently constrain observer team; all observed channels alternate')
    save_json(ROOT/'data/private/tower_vision/HN1-11360086609.json',bundle)
    counts=[]
    for at in (0,119,120.1,300,400,753,841):
        for team in (100,200):
            view=enemy_tower_view(towers,bundle,at,team)
            cut_towers=dict(towers,identity_events=[e for e in towers['identity_events'] if e['time_seconds']<=at],
                health_samples=[e for e in towers['health_samples'] if e['time_seconds']<=at])
            cut_vision=dict(bundle,events=[e for e in events if e['time_seconds']<=at])
            assert view==enemy_tower_view(cut_towers,cut_vision,at,team)
            if at<120.04399108886719:assert '0x40000031' not in view['towers']
            for state in view['towers'].values():
                if state['visible'] is not True:assert state['current_observed'] is None
                for sample in (state['current_observed'] or {}).values():assert sample['observed_at_seconds']<=at
            counts.append(dict(at=at,team=team,identified_enemies=len(view['towers']),
                visible=sum(s['visible'] is True for s in view['towers'].values())))
            if at==400:save_json(ROOT/'data/private/tower_vision'/f'HN1-11360086609-team{team}-at400.json',view)
    assert reference(replay)==towers['source']
    report=dict(task='RPL-005',target_version=towers['version'],status='PASS',scope='Named enemy tower channel and conservative sample filter',
        source=towers['source'],events=len(events),enters=sum(e['visible'] for e in events),
        leaves=sum(not e['visible'] for e in events),opposite_team_checks=opposite,
        strict_alternation=True,prefix_checks=counts,executed_by='Codex',independent_ui_review=None,
        complete_world_vision=False)
    save_json(ROOT/'reports/tower_vision_validation.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('source','prefix_checks')},ensure_ascii=False))


if __name__=='__main__':main()
