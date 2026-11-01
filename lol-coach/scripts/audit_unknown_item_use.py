"""Compare every raw item-use packet with frozen exports; no guessed slot map."""
import argparse,hashlib,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.export_replay_ten import load_reviewed
from scripts.build_experiment_windows import STEMS
from lol_coach.inventory_use import decode_use


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False)
    framer,_,_,dependencies=load_reviewed(ROOT.parent);jobs=[];unknowns=[];inputs={}
    for stem in STEMS:
        export=ROOT/f'data/private/replay_completion/{stem}-live-inventory.json'
        raw=export.read_bytes();inputs[str(export)]=hashlib.sha256(raw).hexdigest();bundle=json.loads(raw)
        source=Path(bundle['source']['path']);sha=hashlib.sha256(source.read_bytes()).hexdigest()
        if sha!=bundle['source']['sha256']:raise ValueError('Source changed')
        inputs[str(source)]=sha
        uses=[];errors=[];hist=Counter()
        for r in framer.packets(source):
            if r['stream']!=1 or r['opcode']!=0x3f1:continue
            row={k:v for k,v in r.items() if k!='payload'};row['payload_hex']=r['payload'].hex()
            row['entity_id']=f"0x{r['param']:08x}"
            try:row['decoded']=decode_use(r['payload'],version=bundle['version'])
            except ValueError as exc:row['error']=str(exc);errors.append(row)
            uses.append(row);hist[row['payload_hex']]+=1
        exported=[r for r in bundle['events']+bundle['rejected'] if r['source']['opcode']=='0x3f1']
        key=lambda r:(r['source']['chunk'],r['source']['decompressed_offset'],r['source']['payload_hex'])
        if sorted(key(r) for r in exported)!=sorted((r['chunk'],r['offset'],r['payload_hex']) for r in uses):
            raise ValueError('Raw use packets differ from exports')
        for unknown in errors:
            actor=unknown['entity_id'];t=unknown['time']
            snapshots=sorted([r for r in bundle['events'] if r['entity_id']==actor and r['kind']=='inventory_snapshot'],key=lambda r:r['time_seconds'])
            before=[r for r in snapshots if r['time_seconds']<t];after=[r for r in snapshots if r['time_seconds']>t]
            left=before[-1] if before else None;right=after[0] if after else None
            neighbours=[]
            for r in framer.packets(source):
                if r['stream']==1 and r['param']==unknown['param'] and abs(r['time']-t)<=5:
                    neighbours.append({k:v for k,v in r.items() if k!='payload'}|dict(payload_hex=r['payload'].hex()))
            between=[r for r in bundle['events'] if r['entity_id']==actor and (left is None or r['time_seconds']>=left['time_seconds']) and (right is None or r['time_seconds']<=right['time_seconds'])]
            unknowns.append(dict(replay_id=stem,source_sha256=sha,raw=unknown,
                previous_inventory_snapshot=left,next_inventory_snapshot=right,inventory_events_between_anchors=between,
                same_actor_raw_packets_within_five_seconds=neighbours,
                slot_hypotheses=[dict(slot=s,status='INSUFFICIENT_EVIDENCE',reason='No concurrent slot transition or controlled same-item slot comparison') for s in (3,4,5)],
                other_hypothesis='Extended encoding or internal slot semantics remain possible',
                conclusion='No unique slot mapping; do not use a later inventory as the inventory at this event',
                decoded_slot=None,cooldown_seconds=None,decision_input_eligible=False))
        jobs.append(dict(replay_id=stem,source_sha256=sha,raw_use_packets=len(uses),accepted=len(uses)-len(errors),rejected=len(errors),payload_counts=dict(hist),raw_matches_export=True))
    for name,sha in inputs.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=sha:raise ValueError('Input changed')
    report=dict(schema='unknown-item-use-audit/v1',jobs=jobs,unknowns=unknowns,source_inputs=inputs,
        dependencies=dependencies,inputs_unchanged=True,decision_input_eligible=False,
        result='Bounded corpus audit complete; unresolved semantics are not promoted',
        future_research_context=True,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(jobs=jobs,unknowns=len(unknowns))))


if __name__=='__main__':main()
