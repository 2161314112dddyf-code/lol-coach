"""Test inventory checkpoint time hypotheses without changing event timestamps."""
import argparse
import bisect
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def op_states(events):
    states, timeline = {}, {}
    for e in sorted(events, key=lambda r: (r['time_seconds'], r['source']['chunk'], r['source']['decompressed_offset'])):
        entity = e['entity_id']
        slots = states.setdefault(entity, {})
        slot = e['slot']
        if e['kind'] == 'slot_update':
            slots[slot] = e.get('item_id')
        elif e['kind'] == 'slot_clear':
            slots[slot] = 0
        elif e['kind'] == 'slot_swap':
            other = e['other_slot']
            slots[slot], slots[other] = slots.get(other), slots.get(slot)
        timeline.setdefault(entity, []).append((e['time_seconds'], dict(slots)))
    return timeline


def compare(expected, actual):
    pairs = [(slot, value, actual.get(slot)) for slot, value in expected.items()
             if value is not None and actual.get(slot) is not None]
    bad = [dict(slot=s, checkpoint=a, operation=b) for s, a, b in pairs if a != b]
    return dict(compared=len(pairs), matched=len(pairs)-len(bad), conflicts=bad,known_slot_ids=[s for s,_,_ in pairs])


def investigate(checkpoints, events):
    timelines = op_states(events)
    rows = []
    for c in checkpoints:
        if c['source']['stream'] != 2:
            continue
        expected = {s['slot']: 0 if s['empty'] else s['item_id'] for s in c['items'] if s['slot'] in range(6)}
        line = timelines.get(c['entity_id'], [])
        times = [t for t, _ in line]
        attempts = []
        for lag in (0, 30, 60, 90, 120):
            query = c['time_seconds']-lag
            ix = bisect.bisect_right(times, query)-1
            result = compare(expected, line[ix][1] if ix >= 0 else {})
            attempts.append(dict(lag_seconds=lag, query_time=query, **result))
        compatible = []
        for ix, (t, slots) in enumerate(line):
            if t > c['time_seconds']:
                break
            end = min(line[ix+1][0] if ix+1 < len(line) else c['time_seconds'], c['time_seconds'])
            result = compare(expected, slots)
            if end > t and result['compared'] >= 3 and not result['conflicts']:
                compatible.append(dict(start=t, end=end, compared_slots=result['compared']))
        rows.append(dict(entity_id=c['entity_id'], packet_time=c['time_seconds'], packet_source=c['source'],
                         expected_slots=expected, lag_attempts=attempts, compatible_operation_intervals=compatible))
    totals = []
    for lag in (0, 30, 60, 90, 120):
        stat = Counter()
        for r in rows:
            a = next(a for a in r['lag_attempts'] if a['lag_seconds'] == lag)
            stat['compared_slots'] += a['compared']; stat['matched_slots'] += a['matched']
            stat['conflict_slots'] += len(a['conflicts'])
            stat['checkpoints_with_three_known_slots'] += a['compared'] >= 3
            stat['matching_checkpoints_with_three_known_slots'] += a['compared'] >= 3 and not a['conflicts']
        totals.append(dict(lag_seconds=lag, **stat))
    common_totals=[]
    for split in ('first_420_seconds','after_420_seconds'):
        for lag in (0,30,60,90,120):
            compared=conflicts=eligible=0
            for r in rows:
                if (r['packet_time']<=420)!=(split=='first_420_seconds'):continue
                common=set.intersection(*(set(a['known_slot_ids']) for a in r['lag_attempts']))
                if len(common)<3:continue
                eligible+=1;compared+=len(common)
                a=next(a for a in r['lag_attempts'] if a['lag_seconds']==lag)
                conflicts+=sum(b['slot'] in common for b in a['conflicts'])
            common_totals.append(dict(split=split,lag_seconds=lag,checkpoints=eligible,compared_slots=compared,conflict_slots=conflicts))
    return dict(schema='inventory-time-hypotheses/v1', hypothesis='Keyframe packet time may differ from inventory effective time',
        status='INSUFFICIENT_EVIDENCE', decision_input_eligible=False, timestamps_modified=False,
        comparison_scope='Only slots 0..5 whose identities are known on both sides; counts/charges omitted',
        caveats=['Operation reconstruction itself misses undo/consumption; agreement is not independent truth',
                 'Different lag comparisons have different known-slot denominators',
                 'Stable inventories produce multiple compatible times; do not assign effective time from matches'],
        totals=totals, common_slot_comparison=common_totals,checkpoints=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    target=a.output.resolve()
    if not target.is_relative_to((ROOT/'data/private').resolve()) or target.exists():
        raise ValueError('Choose a new output under data/private')
    reports=[];inputs=[]
    for path in sorted((ROOT/'data/private/remaining_decode').glob('HN1-*.json')):
        if not path.stem.removeprefix('HN1-').isdigit():
            continue
        inv=ROOT/'data/private/replay_inventory'/path.name
        raw=path.read_bytes();ops=inv.read_bytes();d=json.loads(raw);o=json.loads(ops)
        if d['source']['sha256']!=o['source_sha256'] or d['version']!=o['version']:
            raise ValueError('Inventory provenance mismatch')
        reports.append(dict(replay_id=path.stem, **investigate(d['inventory_checkpoints'],o['events'])))
        inputs.extend(dict(path=str(f),sha256=hashlib.sha256(b).hexdigest()) for f,b in [(path,raw),(inv,ops)])
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(dict(inputs=inputs,replays=reports),ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps([dict(replay_id=r['replay_id'],totals=r['totals']) for r in reports]))


if __name__=='__main__':main()
