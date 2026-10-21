"""Preserve binary anchors and counterexamples; not a gameplay event decoder."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed


def ref(p):
    return dict(time_seconds=p['time'],entity_id=hex(p['param']),stream=p['stream'],chunk=p['chunk'],
                decompressed_offset=p['offset'],opcode=hex(p['opcode']),payload_hex=p['payload'].hex())


def main():
    framer,_,_,dependencies=load_reviewed(ROOT.parent)
    folder=Path('C:/Users/21613/Documents/League of Legends/Replays')
    games=[];short=[]
    for name in ('11360086609','11363048522','11363093470','11372643015'):
        source=folder/f'HN1-{name}.rofl';raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if sha not in ACTORS:raise ValueError('Unverified input')
        version,_,stats=read_metadata(raw)
        counts=Counter();hero_vision=defaultdict(Counter);spells=[]
        for p in framer.packets(source):
            if p['stream']!=1:continue
            if p['opcode']==0x3cd:
                counts['vision_candidate_'+p['payload'].hex()]+=1
                if p['param'] in ACTORS[sha]:hero_vision[hex(p['param'])][p['payload'].hex()]+=1
            if p['opcode']==0x2a1:
                counts['spell_candidate_packets']+=1
                if p['param'] not in ACTORS[sha]:continue
                d=p['payload'];at=d.rfind(b'\xed'*4)
                row=ref(p)
                row.update(anchor_payload_offset=at if at>=0 else None,
                           tentative_word_hex=d[at+6:at+10].hex() if at>=0 else None,
                           tail_after_anchor_hex=d[at:].hex() if at>=0 else None,
                           accepted_spell_id=None,accepted_new_cast=None)
                spells.append(row)
                if name=='11363048522':short.append(row)
        teams={hex(0x40000034+i):int(s['TEAM']) for i,s in enumerate(stats)} if name=='11360086609' else {}
        games.append(dict(source=str(source),sha256=sha,version=version,counts=dict(counts),
           hero_vision={e:dict(v) for e,v in hero_vision.items()},footer_teams=teams,
           hero_candidate_packets=spells))
        if hashlib.sha256(source.read_bytes()).hexdigest()!=sha:raise ValueError('Replay changed')
    static_path=ROOT/'data/research/spell_sources/raw/cd6b77c20fc056c675c3c300c812a444e955885b68c3be4fb12af1eb98c99ce8.bin'
    if hashlib.sha256(static_path.read_bytes()).hexdigest()!=static_path.stem:raise ValueError('Static source changed')
    static=json.loads(static_path.read_text(encoding='utf8'))['data']['Pantheon']['spells']
    state=json.loads((ROOT/'data/private/replay_state/HN1-11363048522.json').read_text(encoding='utf8'))
    drops=[];previous=None
    for u in state['updates']:
        if u['entity_id']!='0x400000ae' or 'resource' not in u['values']:continue
        value=u['values']['resource']
        if previous is not None and value<previous-5:
            delta=previous-value
            names=[s['id'] for s in static if any(abs(cost-delta)<2 for cost in s['cost'])]
            nearby=[s for s in short if 0<=u['time_seconds']-s['time_seconds']<=0.3]
            drops.append(dict(time_seconds=u['time_seconds'],resource_decrease=delta,
                cost_compatible_spells=names,tolerance_points=2,nearby_packets=nearby,
                resource_source=u['source'],interpretation='cost association only; regeneration or other resource changes not decoded'))
        previous=value
    result=dict(status='INSUFFICIENT_EVIDENCE',acceptance_ids=['DYN-02','DYN-04'],dependencies=dependencies,
        games=games,pantheon_static_sha256=static_path.stem,resource_anchors=drops,
        findings=[
          'Five resource drops associate with Q/Q/Q/E/W costs, but cost matching does not decode a spell field.',
          'Repeated 0x2a1 packets share a stable word around the tail; repeated packets cannot count as separate casts.',
          'A fixed word offset after edededed fails on full-match variable-length records; no general spell hash decoder accepted.',
          'Full-match hero 0x3cd payloads partition by footer team and never switch value within an actor; the two payload values cannot be named visible/invisible.',
          'Enter/leave visibility semantics, observer/team mask and cast-stage identity remain unresolved.'],
        accepted_spell_events=0,accepted_visibility_events=0,decision_input_eligible=False)
    path=ROOT/'data/research/spell_vision_anchors.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(resource_anchors=[{k:v for k,v in x.items() if k not in ('nearby_packets','resource_source')} for x in drops],
       games=[dict(source=g['source'],counts=g['counts'],hero_vision=g['hero_vision']) for g in games]),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
