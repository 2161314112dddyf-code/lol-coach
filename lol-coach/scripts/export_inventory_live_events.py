"""Fresh-source export of live full inventories and item-use result counters."""
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.inventory_live import decode_snapshot
from lol_coach.inventory_use import decode_use
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS


def main():
    f,*_,deps=load_reviewed(ROOT.parent);summaries=[]
    for stem in STEMS:
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        ref=reference(source);version,*_=read_metadata(source.read_bytes())
        rows=[];rejected=[]
        for p in f.packets(source):
            if p['stream']!=1 or p['opcode'] not in (0x4e9,0x3f1):continue
            row=dict(time_seconds=p['time'],entity_id=hex(p['param']),
                source=dict(stream=1,chunk=p['chunk'],decompressed_offset=p['offset'],
                    opcode=hex(p['opcode']),payload_hex=p['payload'].hex()))
            try:
                result=decode_snapshot(p['opcode'],p['payload'],version=version) if p['opcode']==0x4e9 else decode_use(p['payload'],version=version)
            except ValueError as exc:
                rejected.append(dict(**row,reason=str(exc)));continue
            rows.append(dict(**row,kind='inventory_snapshot' if p['opcode']==0x4e9 else 'item_use_result',decoded=result))
        if reference(source)!=ref:raise ValueError('Replay changed')
        counts=Counter(r['kind']for r in rows)
        summary=dict(replay=stem,accepted=len(rows),rejected=len(rejected),counts=dict(counts),
            snapshots_with_all_counters=sum(r['decoded'].get('counters_complete',False)for r in rows))
        result=dict(schema='live-inventory-events/v1',version=version,source=ref,dependencies=deps,
            events=rows,rejected=rejected,summary=summary,complete_inventory_state=False,
            limitations=['One item-use slot code remains unresolved in the supplied full game',
                'Variable item charge counters and active-item cooldowns remain unknown',
                'Use events require prior inventory state to identify the item',
                'Never apply live-list absence semantics to other inventory opcodes'])
        (ROOT/'data/private/replay_completion'/(stem+'-live-inventory.json')).write_text(json.dumps(result,indent=2),encoding='utf8')
        summaries.append(summary)
    (ROOT/'data/private/replay_completion/live_inventory_run.json').write_text(json.dumps(summaries,indent=2))
    print(json.dumps(summaries))


if __name__=='__main__':main()
