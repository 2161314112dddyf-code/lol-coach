"""Read-only container probe and quarantined old-rule negative control."""
import argparse
from collections import Counter
import hashlib,json,math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.export_replay_ten import load_reviewed
from lol_coach.replay_container import packets as extended_packets

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reader',choices=('legacy','extended'),default='extended');a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False)
    framer,movement,inverse,deps=load_reviewed(ROOT.parent);jobs=[]
    for stem in ('HN1-11372643015','HN1-11404040952'):
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        raw=source.read_bytes();h=hashlib.sha256(raw).hexdigest();version=raw[15:15+raw[14]].decode('ascii')
        counts=Counter();attempt=success=0;failures=[];times=[];bad_time=0;records=0;error=None
        try:
            for r in (framer.packets(source) if a.reader=='legacy' else extended_packets(raw)):
                counts[(r['stream'],hex(r['opcode']))]+=1
                if not math.isfinite(r['time']) or r['time']<0:bad_time+=1
                if r['stream']==1:
                    times.append(r['time'])
                    if r['opcode']==0xc9:
                        attempt+=1
                        try:
                            decoded=movement.decode_packet(r['payload'],inverse);success+=1;records+=len(decoded['records'])
                        except Exception as exc:
                            if len(failures)<10:failures.append(dict(chunk=r['chunk'],offset=r['offset'],time=r['time'],error=type(exc).__name__+': '+str(exc)))
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        job=dict(replay_id=stem,source=str(source),source_sha256=h,version=version,
            framed_packets=sum(counts.values()),container_error=error,invalid_times=bad_time,
            live_time_range=[min(times),max(times)] if times else None,
            families=[dict(stream=s,opcode=o,count=n) for (s,o),n in sorted(counts.items())],
            old_movement_probe=dict(attempted=attempt,structurally_decoded=success,records=records,failed=attempt-success,examples=failures),
            container_reader=a.reader,gameplay_semantics_compatible=version=='16.20.824.8524',
            new_build_recording_approved=False,
            interpretation='Shared packet framing is separate from version-specific opcode and payload meaning; old rule output on new build is quarantined')
        assert hashlib.sha256(source.read_bytes()).hexdigest()==h
        (out/(stem+'.json')).write_text(json.dumps(job,indent=2),encoding='utf8');jobs.append(job)
    (out/'summary.json').write_text(json.dumps(dict(dependencies=deps,jobs=jobs,decision_input_eligible=False),indent=2),encoding='utf8')
    print(json.dumps([{k:v for k,v in j.items() if k not in ('families','old_movement_probe')}|{'old_movement_probe':j['old_movement_probe']} for j in jobs]))
if __name__=='__main__':main()
