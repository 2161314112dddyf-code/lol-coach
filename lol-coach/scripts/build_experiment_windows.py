"""Build bound offline evidence packets for existing controlled-experiment work."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.experiment_windows import research_windows,repeated_activity_pairs

STEMS=('HN1-11360086609','HN1-11363048522','HN1-11363093470','HN1-11372643015')
VERSION='16.20.824.8524'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    out=args.output.resolve();allowed=(ROOT/'data/private').resolve()
    if not out.is_relative_to(allowed) or out==allowed:raise ValueError('Use a new private child directory')
    out.mkdir(parents=True,exist_ok=False);jobs=[];inputs={}
    for stem in STEMS:
        files={
            'spell_activity':f'data/private/spell_activity/{stem}.json',
            'state':f'data/private/replay_state/{stem}.json',
            'inventory':f'data/private/replay_completion/{stem}-live-inventory.json',
            'vision':f'data/private/replay_vision/{stem}.json',
            'created_object':f'data/private/replay_completion/{stem}-created-objects.json'}
        bundles={k:json.loads((ROOT/n).read_text(encoding='utf8')) for k,n in files.items()}
        raw=bundles['inventory']['source'];digest=sha(Path(raw['path']))
        if digest!=raw['sha256']:raise ValueError('Raw replay changed')
        inputs[raw['path']]=digest;events=[]
        for category,b in bundles.items():
            source=b.get('source')
            bound=b.get('source_sha256') or (source.get('sha256') if isinstance(source,dict) else None)
            if b.get('version')!=VERSION or bound!=digest:
                raise ValueError('Mismatched replay/version')
            inputs[files[category]]=sha(ROOT/files[category])
            rows=b.get('updates',b.get('events',[]))
            for suffix,records in [('accepted',rows),('rejected',b.get('rejected',[]) if category=='inventory' else [])]:
                for i,r in enumerate(records):
                    if r.get('source',{}).get('stream')!=1:continue
                    # Retain source and undecoded bytes, not speculative labels.
                    events.append(dict(event_id=f'{category}:{suffix}:{i}',category=category,
                        record_index=i,time_seconds=r['time_seconds'],entity_id=r['entity_id'],
                        source=r['source'],rejected=suffix=='rejected',
                        data={k:v for k,v in r.items() if k not in ('source','entity_id','time_seconds')}))
        pairs=repeated_activity_pairs(events)
        # One first pair per entity/name, no outcome-selected examples.
        seen=set();selected=[]
        for pair in pairs:
            key=(pair['entity_id'],pair['spell_name'])
            if key in seen:continue
            seen.add(key);selected.append(pair)
        anchors={pid for r in selected for pid in (r['first_id'],r['second_id'])}
        for category in ('inventory','vision','created_object'):
            rows=sorted([r for r in events if r['category']==category],key=lambda r:(r['time_seconds'],r['record_index']))
            anchors.update(r['event_id'] for r in rows[:3])
        anchors.update(r['event_id'] for r in events if r['rejected'])
        windows=research_windows(events,sorted(anchors))
        result=dict(schema='offline-experiment-evidence/v1',version=VERSION,replay_id=stem,
            source_sha256=digest,events_by_category=dict(Counter(r['category'] for r in events)),
            natural_activity_pairs=selected,windows=windows,
            retained_rejections=[r for r in events if r['rejected']],
            controlled_experiment_executed=False,decision_input_eligible=False,
            limitations=['Five-second context is not a full cooldown cycle',
                'No visible-success labels, exact cooldowns, unknown slot resolution or area vision inferred',
                'Future/hidden retrospective evidence is deliberately excluded from model pipeline'])
        path=out/(stem+'.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
        jobs.append(dict(replay=stem,file=path.name,sha256=sha(path),windows=len(windows),
            activity_pairs=len(selected),rejections=len(result['retained_rejections'])))
    if any(sha(ROOT/n)!=h for n,h in inputs.items()):raise ValueError('Inputs changed during export')
    manifest=dict(jobs=jobs,inputs=inputs,inputs_unchanged=True,
        implementation={n:sha(ROOT/n) for n in ('lol_coach/experiment_windows.py','scripts/build_experiment_windows.py')})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print(json.dumps(jobs))


if __name__=='__main__':main()
