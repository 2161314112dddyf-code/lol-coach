"""Compare frozen route durations with explicitly uncertain visual intervals.

The arithmetic does not certify identity, destination, constant speed, clock
alignment, or independent/causal observation. Those remain attached evidence.
"""
from copy import deepcopy
import math


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _interval(value):
    if (not isinstance(value, (list, tuple)) or len(value)!=2
            or not all(_finite(v) and v>=0 for v in value) or value[0]>value[1]):
        raise ValueError('Expected an ordered finite nonnegative interval')
    return list(value)


def compare_duration(predicted, start, end):
    """Endpoint uncertainty propagated without choosing a convenient timestamp."""
    if not _finite(predicted) or predicted<=0:
        raise ValueError('Expected a positive finite prediction')
    start, end = _interval(start), _interval(end)
    if start[1]>=end[0]:
        raise ValueError('Departure and stop intervals overlap or are reversed')
    lower, upper = end[0]-start[1], end[1]-start[0]
    if not _finite(upper):
        raise ValueError('Interval overflow')
    return dict(observed_duration_interval_seconds=[lower,upper],
        duration_interval_width_seconds=upper-lower,
        prediction_within_observed_interval=lower<=predicted<=upper,
        minimum_absolute_error_seconds=max(lower-predicted,predicted-upper,0.0),
        maximum_absolute_error_within_interval_seconds=max(abs(predicted-lower),abs(predicted-upper)),
        exact_duration_seconds=None,
        interpretation='Visual departure-to-stop interval; endpoint correspondence is separately evidenced')


def compare_samples(frozen, bundle, *, prior_prediction_ids=()):
    """Join visual observations to immutable forecasts, preserving exclusions."""
    if frozen.get('schema')!='frozen-travel-predictions/v1':
        raise ValueError('Expected frozen predictions')
    if bundle.get('schema')!='travel-visual-observations/v1':
        raise ValueError('Expected visual observations')
    for key in ('version','replay_id','source_sha256'):
        if bundle.get(key)!=frozen.get(key) or bundle.get(key) is None:
            raise ValueError('Visual/forecast source mismatch')
    digest=bundle.get('video_sha256')
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Video SHA256 required')
    if not isinstance(bundle.get('review_order'),str) or not bundle['review_order']:
        raise ValueError('Review order must be disclosed')
    records={p['prediction_id']:p for p in frozen['records']}
    if len(records)!=len(frozen['records']):
        raise ValueError('Duplicate frozen prediction ID')
    prior=set(prior_prediction_ids)
    if not prior.issubset(records):
        raise ValueError('Unknown prior sample prediction')
    ids=set(); used=set(); intervals=set(); rows=[]
    for sample in bundle['samples']:
        sid=sample['sample_id']; pid=sample['prediction_id']
        if not isinstance(sid,str) or not sid or sid in ids or pid in used:
            raise ValueError('Duplicate/invalid observation or forecast')
        if pid not in records:
            raise ValueError('Unknown frozen prediction')
        if not sample.get('evidence') or not isinstance(sample.get('limitations'),list):
            raise ValueError('Evidence and explicit limitations required')
        ids.add(sid);used.add(pid)
        row=deepcopy(sample)
        row.update(predicted_duration_seconds=records[pid]['predicted_duration_seconds'],
            previously_counted=pid in prior, exact_arrival_seconds=None,
            decision_input_eligible=False)
        if not _finite(row['predicted_duration_seconds']) or row['predicted_duration_seconds']<=0:
            raise ValueError('Invalid referenced prediction duration')
        start=sample.get('start_video_interval_seconds'); end=sample.get('end_video_interval_seconds')
        if start is not None:
            _interval(start)
        if end is not None:
            _interval(end)
        if start is None or end is None:
            row.update(status='INSUFFICIENT_EVIDENCE',comparison=None,new_comparable_sample=False)
        else:
            key=(tuple(_interval(start)),tuple(_interval(end)))
            if key in intervals:
                raise ValueError('Same visual interval assigned to multiple forecasts')
            intervals.add(key)
            comparison=compare_duration(row['predicted_duration_seconds'],start,end)
            row['comparison']=comparison
            # A duration may be measurable even when association/destination is
            # uncertain. Preserve its measurement without qualifying an ETA.
            comparable=sample.get('association_status')=='supported' and sample.get('endpoint_correspondence') in (
                'direct_visual_target','visual_stop_with_replay_endpoint_correspondence')
            row.update(status='PASS' if comparable else 'INSUFFICIENT_EVIDENCE',
                       new_comparable_sample=comparable and pid not in prior)
        rows.append(row)
    return dict(schema='travel-visual-comparison/v1',version=bundle['version'],
        replay_id=bundle['replay_id'],source_sha256=bundle['source_sha256'],
        video_sha256=digest,review_order=bundle['review_order'],rows=rows,
        new_comparable_samples=sum(r['new_comparable_sample'] for r in rows),
        total_comparable_samples=sum(r['status']=='PASS' for r in rows),
        gate_status='INSUFFICIENT_EVIDENCE',decision_input_eligible=False,
        gate_semantics='Sample correspondence and interval arithmetic do not establish corpus-level timing admission')
