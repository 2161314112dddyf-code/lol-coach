"""Compare live lane state with withheld checkpoints and inspect death signals.

RPL-011-WAVE: exact-build, named lane IDs only. Checkpoints are validation
witnesses, never state updates. The script reads existing evidence plus bounded
opcode 0x26 records from the four original replays; it does not run the game.
"""
from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS


def key(row):
    s = row['source']
    return (row['time_seconds'], s['chunk'], s['decompressed_offset'],
            s.get('decoded_record_offset', -1), s.get('decoded_group_offset', -1))


def stats(values):
    return dict(count=len(values), minimum=min(values, default=None),
                maximum=max(values, default=None),
                median=statistics.median(values) if values else None)


def anchor(row):
    return {k: row[k] for k in ('entity_id', 'time_seconds', 'source', 'values',
                               'payload_hex') if k in row}


def inspect(stem, path, framer):
    raw = path.read_bytes()
    d = json.loads(raw)
    if d['version'] != '16.20.824.8524':
        raise ValueError('Exact build required')
    identities = d['identities']
    events = d['events']
    live = sorted((r for r in events if r['source']['stream'] == 1), key=key)
    births = {}
    for row in sorted(identities, key=key):
        if row['source']['stream'] == 1:
            births.setdefault(row['entity_id'], row)
    fields, zeros, removals, paths = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for row in live:
        actor = row['entity_id']
        if row['kind'] == 'health_sample':
            for field, value in row['values'].items():
                fields[(actor, field)].append(dict(row, field=field, value=value))
                if field == 'health' and value == 0:
                    zeros[actor].append(row)
        elif row['kind'] == 'terminal_removal_candidate':
            removals[actor].append(row)
        elif row['kind'] == 'path_command':
            paths[actor].append(row)
    chunks = sorted({r['source']['chunk'] for r in events + identities
                     if r['source']['stream'] == 2})
    checkpoints, comparisons, checkpoint_490 = [], [], []
    for chunk in chunks:
        cp = [r for r in events if r['source']['stream'] == 2 and r['source']['chunk'] == chunk]
        ci = [r for r in identities if r['source']['stream'] == 2 and r['source']['chunk'] == chunk]
        times = sorted({r['time_seconds'] for r in cp + ci})
        if len(times) != 1:
            raise ValueError('Checkpoint has multiple timestamps')
        at = times[0]
        born = {a for a, r in births.items() if r['time_seconds'] <= at}
        dead = {a for a, rows in zeros.items() if any(r['time_seconds'] <= at for r in rows)}
        removed = {a for a, rows in removals.items() if any(r['time_seconds'] <= at for r in rows)}
        active = born - dead - removed
        cpids = {r['entity_id'] for r in ci}
        hp = [r for r in cp if r['kind'] == 'health_sample']
        positive = {r['entity_id'] for r in hp if r['values'].get('health', 0) > 0}
        zero = {r['entity_id'] for r in hp if r['values'].get('health') == 0}
        checkpoints.append(dict(chunk=chunk, at_seconds=at, live_birth_count=len(born),
            live_zero_count=len(dead), live_removal_count=len(removed),
            live_alive_ids=sorted(active), checkpoint_identity_ids=sorted(cpids),
            live_alive_missing_in_checkpoint=sorted(active-cpids),
            checkpoint_identity_missing_in_live_alive=sorted(cpids-active),
            exact_identity_set_match=active == cpids,
            checkpoint_positive_health_ids=sorted(positive), checkpoint_zero_health_ids=sorted(zero),
            alive_without_checkpoint_health=sorted(active-positive),
            checkpoint_all_entity_ids=sorted({r['entity_id'] for r in cp})))
        for row in hp:
            actor = row['entity_id']
            for field, value in row['values'].items():
                candidates = fields[(actor, field)]
                before = [x for x in candidates if x['time_seconds'] <= at]
                after = [x for x in candidates if x['time_seconds'] > at]
                previous = before[-1] if before else None
                following = after[0] if after else None
                matching = next((x for x in after if x['value'] == value), None)
                comparisons.append(dict(entity_id=actor, field=field, checkpoint=anchor(row),
                    checkpoint_value=value, live_previous=anchor(previous) if previous else None,
                    live_previous_value=previous['value'] if previous else None,
                    live_previous_age_seconds=at-previous['time_seconds'] if previous else None,
                    equal=previous['value'] == value if previous else None,
                    live_minus_checkpoint=previous['value']-value if previous else None,
                    first_live_after=anchor(following) if following else None,
                    next_live_value_matches=following['value'] == value if following else None,
                    first_matching_live_after=anchor(matching) if matching else None,
                    first_matching_delay_seconds=matching['time_seconds']-at if matching else None))
        for row in cp:
            if row['kind'] != 'terminal_removal_candidate':
                continue
            actor = row['entity_id']
            later_pos = next((x for x in fields[(actor, 'health')]
                              if x['time_seconds'] > at and x['value'] > 0), None)
            later_path = next((x for x in paths[actor] if x['time_seconds'] > at), None)
            checkpoint_490.append(dict(event=anchor(row),
                live_alive_at_checkpoint=actor in active,
                checkpoint_has_identity=actor in cpids,
                checkpoint_positive_health=actor in positive,
                checkpoint_zero_health=actor in zero,
                next_positive_live_health=anchor(later_pos) if later_pos else None,
                next_live_path=anchor(later_path) if later_path else None))
    source = Path(d['source']['path'])
    if reference(source) != d['source']:
        raise ValueError('Replay reference changed')
    death26 = []
    opcode26_streams = Counter()
    for packet_index, p in enumerate(framer.packets(source)):
        actor = hex(p['param'])
        if p['opcode'] != 0x26 or actor not in births:
            continue
        opcode26_streams[p['stream']] += 1
        if p['stream'] != 1:
            continue
        row = dict(entity_id=actor, time_seconds=p['time'], payload_hex=p['payload'].hex(),
            source=dict(stream=p['stream'], chunk=p['chunk'], decompressed_offset=p['offset'],
                packet_index=packet_index, opcode='0x26',
                payload_sha256=hashlib.sha256(p['payload']).hexdigest()))
        zs = zeros[actor]
        nearest = min(zs, key=lambda x: abs(x['time_seconds']-p['time']), default=None)
        prev = [x for x in fields[(actor, 'health')] if x['time_seconds'] <= p['time']]
        later_pos = next((x for x in fields[(actor, 'health')]
                          if x['time_seconds'] > p['time']+.000001 and x['value'] > 0), None)
        later_move = next((x for x in paths[actor] if x['time_seconds'] > p['time']+.15), None)
        rm = next((x for x in removals[actor] if x['time_seconds'] >= p['time']), None)
        death26.append(dict(event=row, nearest_zero=anchor(nearest) if nearest else None,
            zero_minus_26_seconds=nearest['time_seconds']-p['time'] if nearest else None,
            preceding_health=anchor(prev[-1]) if prev else None,
            later_positive_health=anchor(later_pos) if later_pos else None,
            later_movement_after_150ms=anchor(later_move) if later_move else None,
            following_removal=anchor(rm) if rm else None,
            removal_minus_26_seconds=rm['time_seconds']-p['time'] if rm else None))
    live26ids = {r['event']['entity_id'] for r in death26}
    ages = [r['live_previous_age_seconds'] for r in comparisons if r['equal'] is True]
    summary = dict(replay=stem, named_entities=len(births),
        checkpoint_count=len(checkpoints), exact_alive_identity_matches=sum(r['exact_identity_set_match'] for r in checkpoints),
        checkpoint_identity_total=sum(len(r['checkpoint_identity_ids']) for r in checkpoints),
        checkpoints_with_sparse_health=sum(bool(r['alive_without_checkpoint_health']) for r in checkpoints),
        field_comparisons={f: dict(Counter('equal' if r['equal'] is True else 'different' if r['equal'] is False else 'no_live_prefix'
            for r in comparisons if r['field'] == f)) for f in ('health', 'max_health')},
        matching_hold_age_seconds=stats(ages),
        checkpoint_490_count=len(checkpoint_490),
        checkpoint_490_with_positive_health=sum(r['checkpoint_positive_health'] for r in checkpoint_490),
        checkpoint_490_live_alive=sum(r['live_alive_at_checkpoint'] for r in checkpoint_490),
        checkpoint_490_with_later_positive_live_health=sum(r['next_positive_live_health'] is not None for r in checkpoint_490),
        live_26_count=len(death26), live_26_entities=len(live26ids),
        zero_entities=len(zeros), zero_without_26=sorted(set(zeros)-live26ids),
        opcode26_without_zero=sorted(live26ids-set(zeros)),
        opcode26_stream_counts=dict(opcode26_streams),
        zero_minus_26_seconds=stats([r['zero_minus_26_seconds'] for r in death26 if r['zero_minus_26_seconds'] is not None]),
        opcode26_with_later_positive_health=sum(r['later_positive_health'] is not None for r in death26),
        opcode26_with_later_movement_after_150ms=sum(r['later_movement_after_150ms'] is not None for r in death26),
        removal_minus_26_seconds=stats([r['removal_minus_26_seconds'] for r in death26 if r['removal_minus_26_seconds'] is not None]))
    return dict(schema='lane-current-state-research/v1', task='RPL-011-WAVE', version=d['version'],
        source=d['source'], input_evidence=dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()),
        summary=summary, checkpoints=checkpoints, health_comparisons=comparisons,
        checkpoint_490_counterexamples=checkpoint_490, opcode26_correlations=death26,
        scope='Four existing exact-build replays and accepted named lane IDs; checkpoint crosschecks are withheld validation only',
        limitations=['Replication is sampled/delayed; retained health is latest replicated value, not exact underlying simulation health',
            'Checkpoint positive-health fields are sparse; absence does not mean dead',
            'Opcode 0x490 is stream/context dependent; checkpoint occurrences are not destruction',
            'Observer state must stop carrying current attributes across leave/unknown transitions',
            'Raw opcode 0x26 association alone does not decode killer, damage, animation or exact simulation death time'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT/'data/private/lane_current_state_attempt_20261028')
    p.add_argument('--evidence-root', type=Path, default=ROOT/'data/private/lane_dynamics_run_20261028')
    args = p.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'data/private'):
        p.error('Output must be a new directory under data/private')
    out.mkdir(parents=True, exist_ok=False)
    framer, _, _, deps = load_reviewed(ROOT.parent)
    summaries, written = [], []
    for stem in STEMS:
        result = inspect(stem, args.evidence_root/stem/'evidence.json', framer)
        result['dependencies'] = deps
        target = out/(stem+'.json')
        target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        written.append(reference(target))
        summaries.append(result['summary'])
        print(json.dumps(result['summary']), flush=True)
    target = out/'summary.json'
    target.write_text(json.dumps(summaries, indent=2)+'\n', encoding='utf-8')
    written.append(reference(target))
    receipt = dict(created_at_utc=datetime.now(timezone.utc).isoformat(),
        command=[sys.executable, *sys.argv], exit_code=0,
        script=reference(Path(__file__)), outputs=written)
    (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
