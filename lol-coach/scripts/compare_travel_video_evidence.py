"""Reconcile this clip's new visual attempt with unchanged frozen forecasts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.travel_observations import compare_samples, compare_duration


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--visual',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve(); allowed=(ROOT/'data/private').resolve()
    if not out.is_relative_to(allowed) or out==allowed:
        raise ValueError('Output must be a new private child directory')
    visual=read(args.visual)
    if visual.get('schema')!='travel-video-visual-evidence/v1':
        raise ValueError('Unsupported visual evidence schema')
    video_report_path=ROOT/'reports/movement_video_validation.json'
    report=read(video_report_path)
    video=Path(report['video']['source']); replay=Path(report['replay']['path'])
    if sha(video)!=visual['video_sha256'] or sha(replay)!=visual['replay_sha256']:
        raise ValueError('Original video/replay binding changed')
    for path,digest in visual['source_manifests'].items():
        if sha(ROOT/path)!=digest:
            raise ValueError('Visual extraction manifest changed')
    frozen_dir=ROOT/'data/private/time_audit_20261101/frozen'
    manifest=read(frozen_dir/'manifest.json')
    forecast_path=frozen_dir/'hero-HN1-11372643015.json'
    job=next(j for j in manifest['jobs'] if j['file']==forecast_path.name)
    if sha(forecast_path)!=job['sha256'] or job['raw']['sha256']!=visual['replay_sha256']:
        raise ValueError('Frozen forecast binding changed')
    frozen=read(forecast_path)
    if frozen['version']!=visual['version']:
        raise ValueError('Visual build mismatch')
    prior_path=ROOT/'data/private/time_audit_20261101/evaluation_v3/summary.json'
    prior=read(prior_path)['video']
    old_id=prior['prediction']['prediction_id']
    if prior['prediction'] not in frozen['records']:
        raise ValueError('Previous accepted sample does not match frozen forecast')
    old_visual=visual['previous_accepted_sample']
    labels=read(ROOT/old_visual['source'])
    old_start=next(e for e in labels['events'] if e['id']=='base_move_right')['video_interval_seconds']
    old_end=next(e for e in labels['events'] if e['id']=='final_stop')['video_interval_seconds']
    if old_start!=old_visual['video_start_interval_seconds'] or old_end!=old_visual['video_end_interval_seconds']:
        raise ValueError('Previous visual sample was changed')
    segment=next(s for s in visual['segments'] if s['id']=='top_to_base_existing_clip')
    # Exact existing path anchor, fixed before this visual attempt. Association
    # is candidate event order; missing departure cannot be silently filled.
    middle=next(p for p in frozen['records'] if p['support_source']['chunk']==15
                and p['support_source']['decompressed_offset']==787)
    samples=[dict(sample_id=segment['id'],prediction_id=middle['prediction_id'],
        start_video_interval_seconds=segment['start_video_interval_seconds'],
        end_video_interval_seconds=segment['end_video_interval_seconds'],
        association_status='candidate_event_order',endpoint_correspondence=segment['endpoint_correspondence'],
        evidence=segment['evidence_frames'],limitations=segment['limitations']),
        dict(sample_id=old_visual['id'],prediction_id=old_id,
        start_video_interval_seconds=old_start,end_video_interval_seconds=old_end,
        association_status='supported',endpoint_correspondence='visual_stop_with_replay_endpoint_correspondence',
        evidence=[old_visual['source'],'reports/movement_video_validation.json'],
        limitations=['Previously accepted retrospective clip interval; not a new blind trial',
                     'Physical destination is corroborated by replay endpoint, not independent world coordinates'])]
    observations=dict(schema='travel-visual-observations/v1',version=frozen['version'],
        replay_id=frozen['replay_id'],source_sha256=frozen['source_sha256'],
        video_sha256=visual['video_sha256'],review_order=visual['review_order'],samples=samples)
    result=compare_samples(frozen,observations,prior_prediction_ids=[old_id])
    # This is a different clock origin/quantity. Retain useful comparison but
    # explicitly exclude it from complete-traversal accuracy/sample counts.
    response=compare_duration(middle['predicted_duration_seconds'],
        segment['click_video_interval_seconds'],segment['end_video_interval_seconds'])
    response['interpretation']='Visible command-marker-to-stop interval; physical departure unavailable'
    result['command_response_crosscheck']=dict(prediction_id=middle['prediction_id'],
        predicted_route_duration_seconds=middle['predicted_duration_seconds'],comparison=response,
        movement_traversal_accuracy_qualified=False,adds_complete_traversal_sample=False,
        association_status='candidate_event_order',
        semantics='Visible command marker to later stop; different origin from physical departure; delay/interruption unknown')
    result['hud_absolute_arrival']=dict(status=visual['hud_clock']['status'],
        game_time_interval_seconds=None,reason=visual['hud_clock']['reason'])
    sources=[args.visual,video_report_path,forecast_path,frozen_dir/'manifest.json',prior_path,
             ROOT/old_visual['source'],video,replay]
    result['audit']=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),
        source_sha256={str(p.resolve()):sha(p) for p in sources},
        implementation_sha256={p:sha(ROOT/p) for p in ('lol_coach/travel_observations.py',
            'scripts/compare_travel_video_evidence.py')},
        human_signoff=None,model_called=False)
    out.mkdir(parents=True,exist_ok=False)
    for name,data in [('observations.json',observations),('comparison.json',result)]:
        with (out/name).open('x',encoding='utf8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(dict(new_complete_samples=result['new_comparable_samples'],
        total_complete_samples=result['total_comparable_samples'],
        command_response_interval=response['observed_duration_interval_seconds'],
        predicted_route_duration_seconds=middle['predicted_duration_seconds'],
        admission=result['gate_status'])))


if __name__=='__main__':
    main()
