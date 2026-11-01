"""Compare causal path motion estimates against unused replay position samples.

Checkpoint targets are validation-only and never enter live estimates. Later
live starts are a second, same-channel continuity check, not an independent
checkpoint. World-coordinate comparison uses explicit inferred map profiles.
"""
import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from itertools import groupby
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.lane_tracking import estimate_path
from lol_coach.replay_state import VERSION


def reference(path):
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def order(row):
    return (row['time_seconds'], row['source']['chunk'], row['source']['decompressed_offset'],
            row['source'].get('packet_index', -1))


def stats(values):
    if not values:
        return dict(count=0, median=None, p90=None, maximum=None)
    values = sorted(values)
    return dict(count=len(values), median=statistics.median(values),
        p90=values[max(0, math.ceil(.9*len(values))-1)], maximum=values[-1],
        mean=statistics.mean(values), within_50=sum(v <= 50 for v in values),
        within_100=sum(v <= 100 for v in values))


def paired_stats(rows):
    return dict(hold_last_start=stats([r['hold_error'] for r in rows]),
        advance_along_path=stats([r['advance_error'] for r in rows]),
        advance_better=sum(r['advance_error'] < r['hold_error']-1e-8 for r in rows),
        same=sum(abs(r['advance_error']-r['hold_error']) <= 1e-8 for r in rows),
        advance_worse=sum(r['advance_error'] > r['hold_error']+1e-8 for r in rows))


def strata(rows):
    cohorts = dict(all=lambda r: True,
        prior_single_point=lambda r: r['support_points'] == 1,
        prior_multi_point=lambda r: r['support_points'] > 1,
        target_stopped=lambda r: r['target_points'] == 1,
        target_moving=lambda r: r['target_points'] is not None and r['target_points'] > 1,
        moving_to_stopped=lambda r: r['support_points'] > 1 and r['target_points'] == 1,
        stopped_to_moving=lambda r: r['support_points'] == 1 and r['target_points'] is not None and r['target_points'] > 1,
        age_le_0_25=lambda r: r['age_seconds'] <= .25,
        age_0_25_to_1=lambda r: .25 < r['age_seconds'] <= 1,
        age_1_to_3=lambda r: 1 < r['age_seconds'] <= 3,
        age_gt_3=lambda r: r['age_seconds'] > 3,
        endpoint_clamped=lambda r: r['endpoint_clamped'],
        recent_health_loss=lambda r: r['recent_health_loss'])
    return {key: paired_stats([r for r in rows if select(r)]) for key, select in cohorts.items()}


def infer_binding(bundle):
    families = {row['identity'].get('reference_map_family') for row in bundle['identities']}
    if families == {'single_lane_reference'}:
        path = ROOT/'data/private/lane_dynamics_map_origin_20261028.json'
        evidence = json.loads(path.read_text(encoding='utf-8'))
        origin = evidence['candidate_origin_xz']
        if origin != [6581, 6241] or evidence['replay_version'] != VERSION:
            raise ValueError('Unexpected saved Map12 origin evidence')
        return dict(map_id=12, origin_xz=origin, binding_status='inferred_map_profile',
            runtime_map_id_decoded=False, source_replay=bundle['source'],
            basis='single-lane spawn tokens plus preexisting relative/float crosscheck and Map12 static header',
            source_refs=[reference(path)], exact_replay_grid_version_matched=False,
            limitations=['Map12 local grid is 16.21; cached config and replay are 16.20',
                'Origin translation is an explicit corroborated hypothesis, not decoded runtime map selection'])
    if families == {'three_lane_reference'}:
        path = ROOT/'data/maps/16.20/Default/manifest.json'
        evidence = json.loads(path.read_text(encoding='utf-8'))
        grid = evidence['base_grid']
        origin = [math.floor((grid['bounds_min_xyz'][a]+grid['bounds_max_xyz'][a])/2) for a in (0, 2)]
        if evidence['map_id'] != 11 or evidence['patch'] != '16.20' or origin != [7358, 7412]:
            raise ValueError('Unexpected saved Map11 origin evidence')
        return dict(map_id=11, origin_xz=origin, binding_status='inferred_map_profile',
            runtime_map_id_decoded=False, source_replay=bundle['source'],
            basis='three-lane spawn tokens plus versioned Map11 grid header and preexisting float crosscheck',
            source_refs=[reference(path)], exact_replay_grid_version_matched=True,
            limitations=['Explicit inferred replay/profile selection; runtime map or skin is not decoded'])
    return None


def build_comparison(prior, target, actual, binding, health_loss_times, target_kind):
    at = target['time_seconds']
    estimate = estimate_path(prior, at, map_binding=binding)
    losses = health_loss_times.get(target['entity_id'], [])
    index = bisect_right(losses, at)-1
    recent_loss = index >= 0 and at-losses[index] <= 2.
    return dict(entity_id=target['entity_id'], target_time_seconds=at,
        target_kind=target_kind, target_source=target['source'],
        support_time_seconds=prior['time_seconds'], support_source=prior['source'],
        support_points=len(prior['relative_waypoints']), support_speed=prior['path_speed'],
        target_points=len(target['relative_waypoints']) if target['kind'] == 'path_command' else None,
        age_seconds=estimate['path_age_seconds'], motion_state=estimate['motion_state'],
        endpoint_clamped=estimate['endpoint_clamped'], recent_health_loss=recent_loss,
        health_loss_semantics='group8 health decrease within preceding 2 seconds; not proof of an attack identity',
        hold_position=prior['relative_waypoints'][0],
        advance_position=estimate['relative_position_estimate'], target_relative_position=actual,
        hold_error=math.dist(prior['relative_waypoints'][0], actual),
        advance_error=math.dist(estimate['relative_position_estimate'], actual))


def run(path):
    before = reference(path)
    bundle = json.loads(path.read_text(encoding='utf-8'))
    if bundle['schema'] != 'lane-dynamics-evidence/v1' or bundle['version'] != VERSION:
        raise ValueError('Unsupported evidence schema/build')
    receipt_path = path.with_name('receipt.json')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt['output'] != before:
        raise ValueError('Normalized evidence does not match its receipt')
    if reference(Path(bundle['source']['path'])) != bundle['source']:
        raise ValueError('Replay source hash changed')
    binding = infer_binding(bundle)
    by_actor, health_losses, health = defaultdict(list), defaultdict(list), {}
    for row in sorted(bundle['events'], key=order):
        if row['source']['stream'] != 1:
            continue
        actor = row['entity_id']
        if row['kind'] == 'path_command':
            by_actor[actor].append(row)
        elif row['kind'] == 'health_sample' and 'health' in row['values']:
            value = row['values']['health']
            if actor in health and value < health[actor]:
                health_losses[actor].append(row['time_seconds'])
            health[actor] = value
    times = {actor: [r['time_seconds'] for r in rows] for actor, rows in by_actor.items()}
    checkpoints, float_checks, missing, origin_rows = [], [], [], []
    checkpoint_paths = {(row['entity_id'], row['time_seconds']): row for row in bundle['events']
        if row['source']['stream'] == 2 and row['kind'] == 'path_command'
        and row['encoding'] == 'movement_array'}
    for target in bundle['events']:
        if target['source']['stream'] != 2:
            continue
        if target['kind'] == 'path_command' and target['encoding'] == 'movement_array':
            cohort, actual, kind = checkpoints, target['relative_waypoints'][0], 'heldout_checkpoint_relative_start'
        elif target['kind'] == 'static_format_position_sample' and binding is not None:
            cohort = float_checks
            actual = [target['position_xz'][a]-binding['origin_xz'][a] for a in range(2)]
            kind = 'secondary_float_under_preexisting_origin_hypothesis'
            peer = checkpoint_paths.get((target['entity_id'], target['time_seconds']))
            if peer is not None:
                mapped = [peer['relative_waypoints'][0][a]+binding['origin_xz'][a] for a in range(2)]
                residual = [mapped[a]-target['position_xz'][a] for a in range(2)]
                origin_rows.append(dict(entity_id=target['entity_id'], time_seconds=target['time_seconds'],
                    path_source=peer['source'], float_source=target['source'],
                    relative_path_start=peer['relative_waypoints'][0],
                    position_xz=target['position_xz'], mapped_path_start=mapped,
                    residual_xz=residual, residual_distance=math.dist(mapped, target['position_xz'])))
        else:
            continue
        actor = target['entity_id']
        index = bisect_right(times.get(actor, []), target['time_seconds'])-1
        if index < 0:
            missing.append(dict(entity_id=actor, time_seconds=target['time_seconds'], source=target['source']))
            continue
        prior = by_actor[actor][index]
        cohort.append(build_comparison(prior, target, actual, binding, health_losses, kind))
    continuity = []
    for actor, rows in by_actor.items():
        previous = None
        # Same timestamp messages are one replacement group, not independent samples.
        for _, group in groupby(rows, key=lambda r: r['time_seconds']):
            target = list(group)[-1]
            if previous is not None:
                continuity.append(build_comparison(previous, target, target['relative_waypoints'][0],
                    binding, health_losses, 'next_live_start_same_channel'))
            previous = target
    if reference(path) != before:
        raise ValueError('Evidence changed during evaluation')
    report = dict(schema='lane-tracking-evaluation/v1', replay=path.parent.name,
        version=VERSION, source=bundle['source'], input_evidence=before,
        input_receipt=reference(receipt_path), map_binding=binding,
        checkpoint_crosscheck=strata(checkpoints), secondary_float_comparison=strata(float_checks),
        origin_same_time_residual=stats([r['residual_distance'] for r in origin_rows]),
        origin_same_time_rows=origin_rows,
        next_live_start_continuity=strata(continuity), missing_prior_paths=missing,
        checkpoint_rows=checkpoints, secondary_float_rows=float_checks,
        next_live_start_rows=continuity,
        worst_checkpoint_rows=sorted(checkpoints, key=lambda r: r['advance_error'], reverse=True)[:10],
        worst_continuity_rows=sorted(continuity, key=lambda r: r['advance_error'], reverse=True)[:10],
        limitations=['Checkpoints are separate serialized samples, not independent video ground truth',
            'Two short replays have no checkpoint and provide only same-channel next-start continuity',
            '37 direct float samples reuse a previously calibrated origin hypothesis; not extra independent holdouts',
            'Zero-health/removal and visibility are not applied here; caller must filter before wave aggregation',
            'Aggregate errors are measured outcomes, not guaranteed per-unit error bounds',
            'No tuning to future checkpoints occurs: estimator always starts from a live prefix path'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'data/private/lane_dynamics_run_20261028')
    parser.add_argument('--output', type=Path, default=ROOT/'data/private/lane_tracking_attempt_20261028')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/'data/private').resolve()):
        raise ValueError('Keep private replay evidence under data/private')
    output.mkdir(parents=True, exist_ok=False)
    reports = []
    for path in sorted(args.input.glob('*/evidence.json')):
        report = run(path)
        write_new(output/f'{path.parent.name}.json', report)
        reports.append(report)
        print(json.dumps(dict(replay=report['replay'], checkpoint=report['checkpoint_crosscheck']['all'],
            live_continuity=report['next_live_start_continuity']['all'])), flush=True)
    if not reports:
        raise ValueError('No normalized replay evidence found')
    checkpoints = [row for report in reports for row in report['checkpoint_rows']]
    continuity = [row for report in reports for row in report['next_live_start_rows']]
    summary = dict(task='RPL-011-WAVE', schema='lane-tracking-summary/v1',
        created_at_utc=datetime.now(timezone.utc).isoformat(), version=VERSION,
        dependencies=dict(script=reference(Path(__file__)),
            estimator=reference(ROOT/'lol_coach/lane_tracking.py')),
        replays=[dict(replay=report['replay'], source=report['source'],
            output=reference(output/f"{report['replay']}.json"),
            checkpoint=report['checkpoint_crosscheck']['all'],
            live_continuity=report['next_live_start_continuity']['all']) for report in reports],
        pooled_checkpoint_crosscheck=strata(checkpoints), pooled_live_continuity=strata(continuity),
        empirical_errors_are_guaranteed_bounds=False, independent_video_validation=False,
        new_capture=False, network_used=False)
    write_new(output/'summary.json', summary)


if __name__ == '__main__':
    main()
