"""Scan existing observer-filtered frames and create an unlabeled review set."""
import argparse,hashlib,json
from collections import Counter
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.analysis import context
from lol_coach.reasoning_frame import compile_frame
from lol_coach.round_boundaries import BoundaryTracker


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay',default='HN1-11360086609');p.add_argument('--team',type=int,default=100)
    p.add_argument('--player',default='0x40000034');p.add_argument('--step',type=int,default=5)
    p.add_argument('--end',type=float);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve()
    first=context(a.replay,0.,a.team,a.player)
    bounds=[]
    for row in first[2]:
        if Path(row['path']).name=='evidence.json':
            evidence=json.loads(Path(row['path']).read_bytes())
            if 'recording_end_seconds' in evidence:bounds.append(evidence['recording_end_seconds'])
    if not bounds:raise ValueError('No source-bound recording end available')
    supported_end=min(bounds)
    if a.end is None:a.end=supported_end
    if a.step<=0 or not 0<=a.end<=supported_end:raise ValueError('Invalid scan range')
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False);(out/'cases').mkdir();(out/'audit').mkdir()
    tracker=BoundaryTracker();candidates=[];manifest=[];input_hashes={};counts=Counter()
    times=sorted(set([float(t) for t in range(0,int(a.end)+1,a.step)]+[a.end,283.,293.,300.]))
    times=[t for t in times if t<=a.end]
    for index,t in enumerate(times):
        snap,_,inputs=first if t==0 else context(a.replay,t,a.team,a.player)
        bundle=compile_frame(snap,max_chars=250000)
        for r in inputs:
            if r['path'] in input_hashes and input_hashes[r['path']]!=r['sha256']:raise ValueError('Inputs changed')
            input_hashes[r['path']]=r['sha256']
        candidate=tracker.feed(bundle)
        if candidate:
            candidates.append(candidate);counts.update(r['reason'] for r in candidate['reasons'])
            cid=candidate['candidate_id']
            # Model/human review input contains only the existing filtered frame
            # and candidate, never later outcome or retrospective research windows.
            case=dict(schema='round-boundary-review-case/v1',candidate=candidate,frame=bundle['frame'],
                label=None,label_author=None,split_group=bundle['audit']['source_replay_sha256'],
                split='unassigned',evaluation_status='UNREVIEWED',future_outcome_included=False)
            data=json.dumps(case,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
            (out/'cases'/f'{cid}.json').write_bytes(data)
            (out/'audit'/f'{cid}.json').write_text(json.dumps(bundle['audit'],ensure_ascii=False,indent=2),encoding='utf8')
            manifest.append(dict(file=f'cases/{cid}.json',sha256=hashlib.sha256(data).hexdigest(),frame_id=bundle['frame']['frame_id'],at_seconds=t,split_group=case['split_group']))
        if index%20==0:print(json.dumps(dict(processed=index+1,at=t,candidates=len(candidates))),flush=True)
    for path,h in input_hashes.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=h:raise ValueError('Source changed during scan')
    summary=dict(schema='round-boundary-scan/v1',replay_id=a.replay,team=a.team,player=a.player,
        scanned_frames=len(times),range_seconds=[times[0],times[-1]],supported_end_seconds=supported_end,sampling_step_seconds=a.step,
        candidate_count=len(candidates),reason_counts=dict(counts),candidates=candidates,cases=manifest,
        source_inputs=input_hashes,software_only=True,model_calls=0,human_labels=0,
        tactical_accuracy=None,training_ready=False,
        implementation={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['lol_coach/round_boundaries.py','scripts/scan_round_boundaries.py','lol_coach/reasoning_frame.py']},
        limitations=['Periodic observation scans, not fixed-size rounds; transitions between scans may be missed',
                    'One game remains one split group; not an independent evaluation set',
                    'No numerical ETA/cooldown/area-vision prerequisites used'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'review_queue.json').write_text(json.dumps(dict(cases=manifest,instructions='Label boundary usefulness using this frame only; leave unknown when uncertain. No labels supplied by this exporter.'),indent=2),encoding='utf8')
    print(json.dumps({k:summary[k] for k in ('scanned_frames','candidate_count','reason_counts')}))
if __name__=='__main__':main()
