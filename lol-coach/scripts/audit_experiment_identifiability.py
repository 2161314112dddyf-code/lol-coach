"""Inspect existing event windows for real controls, resource changes and confounds."""
import argparse,hashlib,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.build_experiment_windows import STEMS


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to((ROOT/'data/private').resolve()):raise ValueError('Private output required')
    out.mkdir(parents=True,exist_ok=False);jobs=[];inputs={}
    def load(path):
        raw=path.read_bytes();inputs[str(path)]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
    for stem in STEMS:
        d=load(ROOT/f'data/private/offline_audit_20261101/windows_v2/{stem}.json');events={r['event_id']:r for w in d['windows'] for r in w['rows']}
        pairs=[]
        for pair in d['natural_activity_pairs']:
            one=events[pair['first_id']];two=events[pair['second_id']];t1=one['time_seconds'];t2=two['time_seconds'];actor=pair['entity_id']
            activity=[r for r in events.values() if r['category']=='spell_activity' and r['entity_id']==actor and t1-0.5<=r['time_seconds']<=t2+0.5]
            resource=sorted([r for r in events.values() if r['category']=='state' and r['entity_id']==actor and t1-0.5<=r['time_seconds']<=t2+0.5 and 'resource' in r['data'].get('values',{})],key=lambda r:r['time_seconds'])
            deltas=[dict(before_id=x['event_id'],after_id=y['event_id'],delta=y['data']['values']['resource']-x['data']['values']['resource']) for x,y in zip(resource,resource[1:])]
            pairs.append(dict(pair=pair,nearby_activity_ids=[r['event_id'] for r in activity],resource_deltas=deltas,
                isolated_named_pair=len(activity)==2,successful_cast_label=None,readiness_label=None,
                cooldown_identifiable=False,confounds=['Activity phases/failure/reset not labeled','Regeneration and other resource consumers not excluded',
                    'Selected windows are not guaranteed to cover the full interval between distant paired activities']))
        objects=load(ROOT/f'data/private/replay_completion/{stem}-created-objects.json')
        models=Counter(r.get('identity',{}).get('model_name','unknown') for r in objects.get('events',[]) if r.get('source',{}).get('stream')==1)
        # Count explicitly named ward records, without assigning any radius or ownership.
        wards={name:n for name,n in models.items() if 'ward' in name.lower()}
        jobs.append(dict(replay=stem,source_sha256=d['source_sha256'],natural_pairs=pairs,live_created_models=dict(models),
            named_ward_models=wards,area_grid_truth_available=False,single_source_toggle_control_available=False,
            interpretation='Known creation/visibility events lack isolated two-perspective region labels; no area coverage inferred'))
    result=dict(schema='experiment-identifiability-audit/v1',jobs=jobs,source_inputs=inputs,
        decision_input_eligible=False,controlled_experiment_executed=False,
        conclusion='Resource covariance and object counts are research evidence, not cast/readiness or region-vision truth')
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps([dict(replay=j['replay'],pairs=len(j['natural_pairs']),subsecond_pairs=sum(p['pair']['activity_gap_seconds']<1 for p in j['natural_pairs']),
        isolated_pairs=sum(p['isolated_named_pair'] for p in j['natural_pairs']),pairs_with_resource_samples=sum(bool(p['resource_deltas']) for p in j['natural_pairs']),named_wards=j['named_ward_models']) for j in jobs]))


if __name__=='__main__':main()
