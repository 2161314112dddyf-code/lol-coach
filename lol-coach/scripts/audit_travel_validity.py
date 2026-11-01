"""Freeze causal ETA-validity queries, then compare with prior arrival labels.

No model calls, forecast refitting, or gameplay arrival claims. Local files only.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.travel_validity import TravelValidityTracker, query_validity, event_order
from lol_coach.travel_validity_inputs import load_inputs
from lol_coach.travel_validation import digest

HORIZONS = (0, .25, .5, 1, 2, 5, 10)
CODE = ('lol_coach/travel_validity.py', 'lol_coach/travel_validity_inputs.py',
        'lol_coach/action_evidence.py', 'scripts/audit_travel_validity.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def save(path, value):
    with path.open('x', encoding='utf8') as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def new_dir(path):
    path = path.resolve()
    allowed = (ROOT/'data/private').resolve()
    if not path.is_relative_to(allowed) or path == allowed:
        raise ValueError('Output must be a new child of data/private')
    path.mkdir(parents=True, exist_ok=False)
    return path


def binding(bundle, team, age):
    return dict(source_sha256=bundle['source_sha256'], version=bundle['version'],
                observer_team_id=team, max_path_age_seconds=age)


def same_support(plan, pred):
    if not plan or plan['issued_at_seconds'] != pred['support_time_seconds']:
        return False
    return (plan['points'] == pred['points']
            and plan['speed'] == pred['speed']
            and all(plan['source'].get(k) == pred['support_source'].get(k)
                    for k in ('stream', 'chunk', 'decompressed_offset')))


def freeze_queries(frozen, output, age):
    manifest = read(frozen/'manifest.json')
    out = new_dir(output)
    jobs, checks, inputs = [], [], {}
    bundles = {}
    for job in manifest['jobs']:
        path = frozen/job['file']
        if sha(path) != job['sha256']:
            raise ValueError('Old frozen forecasts changed')
        predictions = read(path)
        stem = predictions['replay_id']; kind = predictions['entity_kind']
        for team in (100, 200):
            key = (stem, team)
            if key not in bundles:
                bundles[key] = load_inputs(ROOT, stem, team)
            bundle = bundles[key]
            if bundle['source_sha256'] != job['raw']['sha256']:
                raise ValueError('Validity/forecast source mismatch')
            inputs.update(bundle['inputs'])
            events = sorted((e for e in bundle['events'] if e['entity_kind']==kind), key=event_order)
            tracker = TravelValidityTracker(**binding(bundle, team, age))
            schedule = sorted((p['support_time_seconds']+h, i, h)
                for i,p in enumerate(predictions['records']) for h in HORIZONS)
            index = 0; rows = []; transitions = []; counts = Counter()
            for at, i, horizon in schedule:
                pred = predictions['records'][i]
                if at > bundle['recording_end_seconds']:
                    row = dict(forecast_id=pred['prediction_id'], horizon_seconds=horizon,
                               at_seconds=at, status='outside_recording', original_plan_current=False,
                               conditional_remaining_seconds=None)
                else:
                    while index < len(events) and events[index]['time_seconds'] <= at:
                        event = events[index]; index += 1
                        before = tracker.entities.get(event['entity_id'], {}).get('plan')
                        tracker.feed(event)
                        state = tracker.entities.get(event['entity_id'], {})
                        after = state.get('plan')
                        if before and (after is None or before['plan_id'] != after['plan_id']):
                            transitions.append(dict(entity_id=event['entity_id'],
                                plan_id=before['plan_id'], issued_at_seconds=before['issued_at_seconds'],
                                nominal_arrival_seconds=before['nominal_arrival_seconds'],
                                expires_at_seconds=before['expires_at_seconds'],
                                **state['last_transition']))
                    state = tracker.snapshot(at, entity_ids={pred['entity_id']})['entities'].get(pred['entity_id'])
                    current = bool(state and same_support(state['plan'], pred))
                    row = dict(forecast_id=pred['prediction_id'], horizon_seconds=horizon, at_seconds=at,
                        status=state['status'] if state else 'unobserved_or_unknown_identity',
                        original_plan_current=current,
                        conditional_remaining_seconds=state['conditional_remaining_seconds'] if current else None,
                        current_plan_id=state['plan']['plan_id'] if state and state['plan'] else None,
                        transition_reason=state['last_transition']['reason'] if state and state['last_transition'] else None)
                rows.append(row)
                counts[row['status']] += 1
            name = f'{kind}-{stem}-team{team}.json'
            save(out/name, dict(schema='travel-validity-frozen-queries/v1', replay_id=stem,
                entity_kind=kind, observer_team_id=team, binding=binding(bundle,team,age),
                horizons_seconds=HORIZONS, source_forecast_file=str(path.resolve()),
                source_forecast_sha256=sha(path), rows=rows, invalidations=transitions,
                limitations=bundle['limitations'], decision_input_eligible=False))
            jobs.append(dict(file=name, sha256=sha(out/name), query_count=len(rows),
                status_counts=dict(counts), original_active_count=sum(
                    r['original_plan_current'] and r['status']=='conditional_active' for r in rows),
                invalidation_counts=dict(Counter(r['reason'] for r in transitions))))
            # Prefix invariance is tested on actual normalized evidence, separate
            # from arrival labels. Malformed checkpoints/future payloads are noise.
            for cutoff in sorted({min(t, bundle['recording_end_seconds']) for t in (10,50,300)}):
                prefix = [e for e in events if e['time_seconds']<=cutoff]
                kwargs = binding(bundle,team,age)
                expected = query_validity(prefix,at_seconds=cutoff,**kwargs)
                actual = query_validity(events,at_seconds=cutoff,**kwargs)
                noise = [dict(source=dict(stream=2),time_seconds=0,kind='malformed_checkpoint'),
                         dict(source=dict(stream=1),time_seconds=cutoff+1,kind='future_invalid_payload')]
                polluted = query_validity(events+noise,at_seconds=cutoff,**kwargs)
                if expected != actual or expected != polluted:
                    raise AssertionError('Real prefix/checkpoint/future invariance failed')
                checks.append(dict(replay_id=stem,entity_kind=kind,observer_team_id=team,
                                   at_seconds=cutoff,status='PASS'))
    save(out/'manifest.json', dict(schema='travel-validity-freeze-manifest/v1',
        created_at_utc=datetime.now(timezone.utc).isoformat(), jobs=jobs, inputs=inputs,
        old_forecasts_manifest=dict(path=str((frozen/'manifest.json').resolve()),sha256=sha(frozen/'manifest.json')),
        implementation={p:sha(ROOT/p) for p in CODE}, horizons_seconds=HORIZONS,
        max_path_age_seconds=age, real_prefix_checks=checks,
        downstream_labels_read=False, decision_input_eligible=False))
    print(json.dumps(dict(stage='freeze',jobs=len(jobs),queries=sum(j['query_count'] for j in jobs),
                         prefix_checks=len(checks))))


def evaluate_queries(frozen, labels, output):
    manifest = read(frozen/'manifest.json')
    # Retain the exact implementation and inputs that issued the queries.
    if any(sha(ROOT/p)!=h for p,h in manifest['inputs'].items()):
        raise ValueError('Causal inputs changed')
    out = new_dir(output)
    groups = defaultdict(lambda: dict(query_counts=Counter(), active_original_by_horizon=Counter(),
        invalidations=Counter(), original_forecasts_at_zero=0, active_at_zero=0,
        active_zero_old_outcomes=Counter(), old_live_endpoint_reports=[],
        old_narrow_bracket_games=set(), old_narrow_bracket_count=0))
    label_files = {}
    for job in manifest['jobs']:
        path = frozen/job['file']
        if sha(path)!=job['sha256']:
            raise ValueError('Causal queries changed')
        query = read(path)
        kind = query['entity_kind']; stem = query['replay_id']
        label_path = labels/f'{kind}-{stem}.json'
        label_files[str(label_path.resolve())] = sha(label_path)
        old = read(label_path)
        forecast_path = Path(query['source_forecast_file'])
        if sha(forecast_path) != query['source_forecast_sha256']:
            raise ValueError('Original forecasts changed after validity freeze')
        forecast_bundle = read(forecast_path)
        if (old.get('replay_id')!=stem or old.get('entity_kind')!=kind
                or old.get('frozen_prediction_sha256')!=digest(forecast_bundle)):
            raise ValueError('Arrival labels do not match the frozen forecast source')
        labels_by_id = {r['prediction_id']:r for r in old['rows']}
        expected_ids = {r['prediction_id'] for r in forecast_bundle['records']}
        if len(labels_by_id)!=len(old['rows']) or set(labels_by_id)!=expected_ids:
            raise ValueError('Arrival labels missing, duplicated or unrelated')
        group = groups[kind]
        for transition in query['invalidations']:
            group['invalidations'][transition['reason']] += 1
        for row in query['rows']:
            group['query_counts'][row['status']] += 1
            active = row['original_plan_current'] and row['status']=='conditional_active'
            if active:
                group['active_original_by_horizon'][str(row['horizon_seconds'])] += 1
            if row['horizon_seconds']!=0:
                continue
            group['original_forecasts_at_zero'] += 1
            if not active:
                continue
            group['active_at_zero'] += 1
            label = labels_by_id[row['forecast_id']]
            group['active_zero_old_outcomes'][label['outcome']] += 1
            if (label['outcome']=='endpoint_position_report' and label['observation_source']['stream']==1
                    and .1<=label['predicted_duration_seconds']<=10):
                group['old_live_endpoint_reports'].append(dict(replay_id=stem,forecast_id=label['prediction_id'],
                    report_error_seconds=label['report_time_absolute_error_seconds'],
                    bracket_width_seconds=label['arrival_bracket_width_seconds']))
                if label['arrival_bracket_width_seconds'] is not None and label['arrival_bracket_width_seconds']<=1:
                    group['old_narrow_bracket_count'] += 1
                    group['old_narrow_bracket_games'].add(stem)
    for group in groups.values():
        group['old_narrow_bracket_games'] = sorted(group['old_narrow_bracket_games'])
        group['scope'] = 'Historical endpoint-report comparison, not validated physical arrival accuracy'
        group['timing_qualification'] = 'INSUFFICIENT_EVIDENCE'
    save(out/'summary.json',dict(schema='travel-validity-evaluation/v1', groups=dict(groups),
        frozen_manifest_sha256=sha(frozen/'manifest.json'), label_inputs=label_files,
        implementation={p:sha(ROOT/p) for p in CODE},
        timing_qualification='INSUFFICIENT_EVIDENCE', model_integration_permitted=False,
        rationale='Validity/expiry management supplies no new independent arrival labels; original T5/T6 not passed',
        policy='1-second freshness is an engineering expiry, never a measured error bound',
        human_signoff=None, model_calls=0))
    print(json.dumps(dict(stage='evaluate',timing_qualification='INSUFFICIENT_EVIDENCE',
        groups={k:{n:v for n,v in g.items() if n!='old_live_endpoint_reports'} for k,g in groups.items()})))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    query = sub.add_parser('query')
    query.add_argument('--replay',required=True)
    query.add_argument('--team',type=int,choices=(100,200),required=True)
    query.add_argument('--at',type=float,required=True)
    query.add_argument('--max-path-age',type=float,default=1.0)
    query.add_argument('--output',type=Path,required=True)
    freeze = sub.add_parser('freeze')
    freeze.add_argument('--forecasts',type=Path,required=True)
    freeze.add_argument('--output',type=Path,required=True)
    freeze.add_argument('--max-path-age',type=float,default=1.0)
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('--frozen',type=Path,required=True)
    evaluate.add_argument('--labels',type=Path,required=True)
    evaluate.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.command=='freeze':
        freeze_queries(args.forecasts,args.output,args.max_path_age)
    elif args.command=='evaluate':
        evaluate_queries(args.frozen,args.labels,args.output)
    else:
        bundle=load_inputs(ROOT,args.replay,args.team)
        if not 0<=args.at<=bundle['recording_end_seconds']:
            raise ValueError('Query outside recording')
        result=query_validity(bundle['events'],at_seconds=args.at,
                              **binding(bundle,args.team,args.max_path_age))
        result['audit']=dict(inputs=bundle['inputs'],limitations=bundle['limitations'])
        save(new_dir(args.output)/'query.json',result)
        print(json.dumps(dict(stage='query',entities=len(result['entities']),output=str(args.output))))


if __name__=='__main__':
    main()
