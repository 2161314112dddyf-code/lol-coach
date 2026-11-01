"""Freeze path-only predictions, then independently score saved forecasts offline."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.travel_validation import freeze_predictions, evaluate_predictions, digest

STEMS = ['HN1-11360086609', 'HN1-11363048522', 'HN1-11363093470', 'HN1-11372643015']
VERSION = '16.20.824.8524'
CODE = ['lol_coach/action_evidence.py', 'lol_coach/travel_validation.py', 'scripts/audit_action_time.py']


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def new_dir(path):
    path = path.resolve()
    allowed = (ROOT/'data/private').resolve()
    if not path.is_relative_to(allowed) or path == allowed:
        raise ValueError('Output must be a new child of data/private')
    path.mkdir(parents=True, exist_ok=False)
    return path


def load(stem, kind):
    lane_path = ROOT/f'data/private/lane_dynamics_run_20261028/{stem}/evidence.json'
    lane = read(lane_path)
    if kind == 'minion':
        path, bundle = lane_path, lane
        if read(path.with_name('receipt.json'))['output']['sha256'] != sha(path):
            raise ValueError('Lane receipt mismatch')
        events = bundle['events']
        raw = bundle['source']
    else:
        path = ROOT/f'data/private/replay_ten/{stem}.json'
        bundle = read(path)
        raw = bundle['sources'][stem+'.rofl']
        events = []
        for row in bundle['categories']['movement']['events']:
            packet = row['packet']
            events.append(dict(entity_id=row['entity_id'], time_seconds=row['time_seconds'],
                kind='path_command', relative_waypoints=row['relative_waypoints'],
                path_speed=row['speed_candidate'], flags=row.get('flags'), extra_byte=row.get('extra_byte'),
                source=dict(stream=packet['stream'], chunk=packet['chunk'],
                    decompressed_offset=packet['offset'], packet_index=int(row['record_id'].split(':')[0]),
                    record_id=row['record_id']), encoding='movement_array'))
        for row in bundle['categories']['lifecycle']['events']:
            if row['kind'] not in ('death','respawn_candidate'):
                continue
            packet = row['packet']
            events.append(dict(entity_id=row['entity_id'], time_seconds=row['time_seconds'],
                kind='observed_death' if row['kind']=='death' else 'respawn_candidate', source=dict(stream=packet['stream'], chunk=packet['chunk'],
                    decompressed_offset=packet['offset'], packet_index=-1)))
    if bundle['version'] != VERSION or lane['version'] != VERSION or raw['sha256'] != lane['source']['sha256']:
        raise ValueError('Build or replay binding mismatch')
    return events, lane['recording_end_seconds'], dict(path=str(path.resolve()), sha256=sha(path)), raw


def freeze(output):
    out = new_dir(output)
    jobs = []
    verified_raw = set()
    for kind in ('hero', 'minion'):
        for stem in STEMS:
            events, end, source, raw = load(stem, kind)
            if raw['path'] not in verified_raw:
                if sha(Path(raw['path'])) != raw['sha256']:
                    raise ValueError('Raw replay changed')
                verified_raw.add(raw['path'])
            pred = freeze_predictions(events, replay_id=stem, version=VERSION,
                source_sha256=raw['sha256'], entity_kind=kind)
            name = f'{kind}-{stem}.json'
            save(out/name, pred)
            jobs.append(dict(file=name, sha256=sha(out/name), input=source, raw=raw,
                recording_end_seconds=end, forecast_count=len(pred['records'])))
    save(out/'manifest.json', dict(schema='time-freeze-manifest/v1',
        created_at_utc=datetime.now(timezone.utc).isoformat(), jobs=jobs,
        implementation={p: sha(ROOT/p) for p in CODE}, prediction_data_only=True))
    print(json.dumps({'stage': 'freeze', 'forecasts': sum(j['forecast_count'] for j in jobs), 'files': len(jobs)}))


def stats(values):
    values = sorted(values)
    return None if not values else dict(count=len(values), median=statistics.median(values),
        p90=values[math.ceil(.9*len(values))-1], maximum=values[-1], over_1_5=sum(x>1.5 for x in values))


def evaluate(frozen, output):
    manifest = read(frozen/'manifest.json')
    # Evaluation may be repaired without regenerating or refitting forecasts.
    # Keep the original forecaster manifest AND the evaluator version separate.
    revisions = {p: {'frozen_version':h,'evaluator_version':sha(ROOT/p)}
                 for p,h in manifest['implementation'].items() if sha(ROOT/p)!=h}
    out = new_dir(output)
    results, all_rows = [], []
    video_pred = None
    for job in manifest['jobs']:
        path = frozen/job['file']
        if sha(path) != job['sha256']:
            raise ValueError('Frozen forecasts changed')
        pred = read(path)
        events, end, source, raw = load(pred['replay_id'], pred['entity_kind'])
        if source != job['input'] or raw != job['raw'] or end != job['recording_end_seconds']:
            raise ValueError('Evaluation source changed')
        result = evaluate_predictions(pred, events, recording_end_seconds=end)
        save(out/job['file'], result)
        results.append({k: result[k] for k in ('replay_id','entity_kind','outcome_counts',
            'short_outcome_counts','short_endpoint_report_deviation','narrow_bracket_count')})
        for row in result['rows']:
            all_rows.append(dict(row, replay_id=pred['replay_id'], entity_kind=pred['entity_kind']))
        if pred['entity_kind']=='hero' and pred['replay_id']=='HN1-11372643015':
            video_pred = next(r for r in pred['records'] if abs(r['support_time_seconds']-43.55914889526368)<1e-8)
    summary = {}
    for kind in ('hero','minion'):
        rows = [r for r in all_rows if r['entity_kind']==kind and .1<=r['predicted_duration_seconds']<=10]
        matched = [r for r in rows if r['outcome']=='endpoint_position_report']
        live_matched = [r for r in matched if r['observation_source']['stream']==1]
        errors = [r['report_time_absolute_error_seconds'] for r in live_matched]
        s = stats(errors)
        games = sorted({r['replay_id'] for r in live_matched})
        narrow = [r for r in matched if r['arrival_bracket_width_seconds'] is not None and r['arrival_bracket_width_seconds']<=1]
        overdues = [r for r in rows if r['outcome']=='not_at_endpoint_after_expected_arrival']
        proxy_pass = bool(s and len(errors)>=20 and len(games)>=2 and s['median']<=.25
            and s['p90']<=.75 and s['over_1_5']/len(errors)<=.05)
        missed = sum(r['overdue_observation_seconds']>.75 for r in overdues)
        judged = len(matched)+len(overdues)
        missed_rate = missed/judged if judged else None
        # An elsewhere position after ETA may follow an unobserved arrival and
        # departure. Keep its uncertainty; do not call it a proven late arrival.
        quality = proxy_pass and missed_rate is not None and missed_rate<=.05
        enough_brackets = len(narrow)>=20 and len({r['replay_id'] for r in narrow})>=2
        gate = 'PASS' if quality and enough_brackets else 'INSUFFICIENT_EVIDENCE'
        summary[kind] = dict(total_short_forecasts=len(rows), outcomes=dict(Counter(r['outcome'] for r in rows)),
            endpoint_report_deviation=s, games_with_endpoint_reports=games,
            checkpoint_endpoint_observation_count=len(matched)-len(live_matched),
            narrow_bracket_count=len(narrow), narrow_bracket_games=sorted({r['replay_id'] for r in narrow}),
            worst_case_bracket_error=stats([r['worst_case_error_within_bracket_seconds'] for r in matched
                                           if r['worst_case_error_within_bracket_seconds'] is not None]),
            instant_arrival_baseline=stats([r['instant_arrival_baseline_report_error_seconds'] for r in matched]),
            overdue_lateness=stats([r['overdue_observation_seconds'] for r in overdues]),
            overdue_over_0_75_seconds=sum(r['overdue_observation_seconds']>.75 for r in overdues),
            overdue_over_1_5_seconds=sum(r['overdue_observation_seconds']>1.5 for r in overdues),
            conditional_endpoint_proxy_threshold='PASS' if proxy_pass else 'FAIL',
            missed_after_0_75_fraction_of_uncensored=missed_rate,
            integration_status=gate,
            integration_reason=('Too many unresolved ends and/or too few qualified endpoint reports to establish the preset gate' if not quality else
                'Too few narrow observation brackets across separate games' if not enough_brackets else
                'Only conditional received-route timing; not arbitrary navigation, exact arrival, combat or action-window certification'),
            worst_endpoint_reports=sorted(matched,key=lambda r:r['report_time_absolute_error_seconds'],reverse=True)[:10],
            worst_overdue_reports=sorted(overdues,key=lambda r:r['overdue_observation_seconds'],reverse=True)[:10])
    sample_path = ROOT/'data/normalized/movement_samples/HN1-11372643015-base-movement-3.json'
    sample = read(sample_path)
    if video_pred is None or sample['replay_sha256'] != next(j['raw']['sha256'] for j in manifest['jobs'] if 'hero-HN1-11372643015' in j['file']):
        raise ValueError('Video comparison source mismatch')
    lo = sample['end_video_interval_seconds'][0]-sample['start_video_interval_seconds'][1]
    hi = sample['end_video_interval_seconds'][1]-sample['start_video_interval_seconds'][0]
    video = dict(source_path=str(sample_path), source_sha256=sha(sample_path), prediction=video_pred,
        independently_observed_duration_interval=[lo,hi],
        within_video_bracket=lo<=video_pred['predicted_duration_seconds']<=hi,
        deviation_from_interval=max(lo-video_pred['predicted_duration_seconds'],video_pred['predicted_duration_seconds']-hi,0),
        independent_duration_count=1, blind_test=False,
        scope='Existing retrospective video interval; annotations previously revised after decoding, not a new game trial')
    save(out/'summary.json', dict(schema='standalone-time-audit/v1', per_replay=results,
        by_kind=summary, video=video, freeze_manifest_sha256=sha(frozen/'manifest.json'),
        frozen_outputs_unchanged=all(sha(frozen/j['file'])==j['sha256'] for j in manifest['jobs']),
        implementation={p:sha(ROOT/p) for p in CODE}, model_called=False, model_integration_changed=False))
    save(out/'evaluation_revision.json', dict(forecasts_regenerated=False,
        original_forecaster_manifest_sha256=sha(frozen/'manifest.json'), revisions=revisions,
        reasons=['Exclude paths already known dead at support using prior evidence',
                 'Separate checkpoint endpoint sampling lag from live endpoint report proxy',
                 'Later position elsewhere does not prove first arrival never occurred'],
        input_predictions_unchanged=True))
    for kind,s in summary.items():
        print(json.dumps({'kind':kind, **{k:s[k] for k in ('total_short_forecasts','outcomes','endpoint_report_deviation',
            'narrow_bracket_count','overdue_over_0_75_seconds','conditional_endpoint_proxy_threshold')}},ensure_ascii=True))
    print(json.dumps({'video_prediction':video_pred['predicted_duration_seconds'],'video_interval':[lo,hi],
                      'inside':video['within_video_bracket']}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    a=sub.add_parser('freeze');a.add_argument('--output',type=Path,required=True)
    b=sub.add_parser('evaluate');b.add_argument('--frozen',type=Path,required=True);b.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='freeze':freeze(args.output)
    else:evaluate(args.frozen.resolve(),args.output)


if __name__=='__main__':
    main()
