"""Build a full causal review sequence and unlabeled negative-time review inputs."""
import argparse,hashlib,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.analysis import context
from lol_coach.reasoning_frame import compile_frame,model_messages
from lol_coach.decision_contract import output_schema
from lol_coach.review_checkpoints import CheckpointScheduler,prepare_checkpoint


def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--interval',type=float,default=30);a=p.parse_args();out=a.output.resolve();source=json.loads((a.scan/'summary.json').read_bytes())
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False);(out/'checkpoints').mkdir();(out/'nonselected').mkdir()
    scheduler=CheckpointScheduler(a.interval);end=source['range_seconds'][1];step=source['sampling_step_seconds']
    times=sorted(set([float(t) for t in range(0,int(end)+1,step)]+[end]+[t for t in (283.,293.,300.) if t<=end]))
    rows=[];inputs={};selected=[];kinds=Counter();code=['lol_coach/review_checkpoints.py','scripts/build_review_sequence.py'];start_code={n:sha(ROOT/n) for n in code}
    for i,t in enumerate(times):
        snapshot,_,refs=context(source['replay_id'],t,source['team'],source['player']);bundle=compile_frame(snapshot,max_chars=250000)
        for r in refs:
            if r['path'] in inputs and inputs[r['path']]!=r['sha256']:raise ValueError('Source changed')
            inputs[r['path']]=r['sha256']
        selection=scheduler.feed(bundle)
        if i==len(times)-1 and not selection['selected']:
            selection=scheduler.flush(bundle) or selection
        kinds[selection['selection_kind']]+=1
        if selection['selected']:
            cid=selection['checkpoint_id'];folder=out/'checkpoints'/cid;folder.mkdir();prepared=prepare_checkpoint(bundle,selection)
            write(folder/'bundle.json',prepared);write(folder/'messages.json',model_messages(prepared,output_schema()))
            selected.append(dict(checkpoint_id=cid,at_seconds=t,path=str(folder.relative_to(out)),frame_id=prepared['frame']['frame_id'],bundle_sha256=sha(folder/'bundle.json')))
        else:
            # Unselected does not mean no real boundary. Preserve for blind labeling.
            path=out/'nonselected'/f'{i:04d}.json';write(path,dict(frame=bundle['frame'],label=None,selection=selection,split_group=bundle['audit']['source_replay_sha256']))
        rows.append(selection)
        if i%25==0:print(json.dumps(dict(processed=i+1,selected=len(selected))),flush=True)
    if any(sha(Path(n))!=h for n,h in inputs.items()) or any(sha(ROOT/n)!=h for n,h in start_code.items()):raise ValueError('Input/code changed')
    result=dict(schema='review-sequence/v1',source_scan_sha256=sha(a.scan/'summary.json'),source_inputs=inputs,
        implementation=start_code,observer_team_id=source['team'],player_entity_id=source['player'],
        policy=dict(interval_seconds=a.interval,semantics='Engineering coalescing interval; not gameplay duration or round definition'),
        scan_frames=len(rows),selected_count=len(selected),selection_counts=dict(kinds),selected=selected,
        scan_decisions=rows,pending_tail=scheduler.tail(),labels_supplied=0,tactical_accuracy=None,model_calls=0,
        limitations=['Prepare supports the existing runner; this batch does not manufacture model answers',
            'Unselected frames have null labels, not negative truth','All frames from one game remain one evaluation group'])
    write(out/'sequence.json',result)
    table=['# 本局复盘检查点','', '工程调度，非已验收回合；每个目录含现有推理器可读取的bundle和messages。未调用模型，未标注战术正误。','', '| 秒 | 类型 | 合并观测候选数 | 输入 |','| --- | --- | --- | --- |']
    for s in selected:
        d=next(r for r in rows if r.get('checkpoint_id')==s['checkpoint_id']);table.append(f"| {s['at_seconds']:.3f} | {d['selection_kind']} | {len(d['covered_candidates'])} | [{s['checkpoint_id']}]({s['path']}/bundle.json) |")
    (out/'INDEX.md').write_text('\n'.join(table)+'\n',encoding='utf8');print(json.dumps(dict(scans=len(rows),selected=len(selected),kinds=dict(kinds),pending_tail=len(scheduler.tail()))))


if __name__=='__main__':main()
