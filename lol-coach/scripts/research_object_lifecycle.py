"""Correlate named-object terminal messages with independent health fields."""
import json,sys,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import load_reviewed,reference
from lol_coach.replay_state import decode_payload,floating,inverse_table


def main():
    folder=ROOT/'data/private/replay_completion';stem='HN1-11360086609'
    source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl');ref=reference(source)
    f,*_=load_reviewed(ROOT.parent);created=json.loads((folder/(stem+'-created-objects.json')).read_text())
    if created['source']!=ref:raise ValueError('Creation source mismatch')
    ids={int(r['entity_id'],16):r['identity']['model_name']for r in created['events']}
    by=collections.defaultdict(list);hp=collections.defaultdict(list);inv=inverse_table()
    for p in f.packets(source):
        if p['stream']!=1:continue
        src=dict(stream=1,chunk=p['chunk'],decompressed_offset=p['offset'],opcode=hex(p['opcode']),payload_hex=p['payload'].hex())
        if p['param']in ids:by[p['param']].append(dict(time=p['time'],source=src))
        if p['opcode']==0x3df:
            for r in decode_payload(p['payload'],inverse=inv)['records']:
                if r['entity_id']not in ids:continue
                for g in r['groups']:
                    if g['group']==8 and g['field_mask']&1:
                        try:v,_=floating(bytes.fromhex(g['decoded_data_hex']),0)
                        except ValueError:continue
                        hp[r['entity_id']].append(dict(time=p['time'],health=v,group=g,source=src))
    rows=[]
    for actor,model in ids.items():
        events=by[actor];death=[e for e in events if e['source']['opcode']=='0x167'];remove=[e for e in events if e['source']['opcode']=='0x490']
        if not death and not remove:continue
        matching=[]
        for e in death:
            zeros=[h for h in hp[actor]if h['health']==0 and abs(h['time']-e['time'])<.15]
            matching.append(dict(event=e,zero_health_witnesses=zeros))
        after=[e for e in events if remove and e['time']>remove[-1]['time']]
        afterhp=[h for h in hp[actor]if remove and h['time']>remove[-1]['time']]
        rows.append(dict(entity_id=hex(actor),model=model,terminal_candidates=remove,death_candidates=matching,
            packets_after_last_terminal=after,health_after_last_terminal=afterhp))
    summary=dict(entities=len(rows),terminal_entities=sum(bool(r['terminal_candidates'])for r in rows),
        terminal_records=sum(len(r['terminal_candidates'])for r in rows),
        deaths=sum(len(r['death_candidates'])for r in rows),
        deaths_with_zero_health=sum(bool(e['zero_health_witnesses'])for r in rows for e in r['death_candidates']),
        terminal_followup_conflicts=sum(bool(r['packets_after_last_terminal']or r['health_after_last_terminal'])for r in rows))
    if reference(source)!=ref:raise ValueError('Replay changed')
    (folder/'object_lifecycle_research.json').write_text(json.dumps(dict(source=ref,summary=summary,rows=rows,
        accepted=False,limitations=['Terminal message correlation does not establish source visibility shutdown time',
        'Health prefix labels borrowed only for named nonhero records; no complete nonhero replication decoder']),indent=2))
    print(json.dumps(summary))


if __name__=='__main__':main()
