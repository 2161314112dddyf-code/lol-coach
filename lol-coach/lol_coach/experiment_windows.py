"""Retrospective research windows, never time-t model knowledge."""
from copy import deepcopy
import math


def order(row):
    s=row['source']
    return (row['time_seconds'],s['chunk'],s['decompressed_offset'],row['category'],row['record_index'])


def research_windows(events, anchors, *, radius=5.0):
    if type(radius) not in (int,float) or not math.isfinite(radius) or radius<=0:
        raise ValueError('Positive finite radius required')
    live=[]
    for row in events:
        if row.get('source',{}).get('stream')!=1:
            continue
        t=row.get('time_seconds')
        if type(t) not in (int,float) or not math.isfinite(t) or t<0:
            raise ValueError('Invalid event time')
        live.append(row)
    live.sort(key=order)
    by_id={r['event_id']:r for r in live}
    if len(by_id)!=len(live):
        raise ValueError('Duplicate event identity')
    output=[]
    for aid in anchors:
        if aid not in by_id:
            raise ValueError('Anchor is not a live event')
        anchor=by_id[aid];t=anchor['time_seconds']
        rows=[deepcopy(r) for r in live if r['entity_id']==anchor['entity_id'] and abs(r['time_seconds']-t)<=radius]
        inventory=[r for r in live if r['entity_id']==anchor['entity_id']
                   and r['category']=='inventory' and r.get('data',{}).get('kind')=='inventory_snapshot']
        before=[r for r in inventory if order(r)<order(anchor)]
        after=[r for r in inventory if order(r)>order(anchor)]
        output.append(dict(anchor_id=aid,entity_id=anchor['entity_id'],
            start_seconds=max(0,t-radius),end_seconds=t+radius,rows=rows,
            inventory_brackets=dict(previous=deepcopy(before[-1]) if before else None,
                following=deepcopy(after[0]) if after else None,
                semantics='Nearest serialized snapshots, possibly far away; no interpolation or current-state claim'),
            purpose='Retrospective natural observation; not a controlled intervention',
            includes_future_relative_to_anchor=True,decision_input_eligible=False,
            labels=dict(successful_cast=None,cooldown_seconds=None,actual_item_slot=None,region_visibility=None)))
    return output


def repeated_activity_pairs(events):
    previous={};pairs=[]
    for row in sorted(events,key=order):
        if row['source']['stream']!=1 or row['category']!='spell_activity':
            continue
        name=row.get('data',{}).get('spell_name')
        if not name:continue
        key=(row['entity_id'],name)
        if key in previous:
            p=previous[key]
            pairs.append(dict(first_id=p['event_id'],second_id=row['event_id'],
                entity_id=key[0],spell_name=name,
                activity_gap_seconds=row['time_seconds']-p['time_seconds'],
                cooldown_seconds=None,successful_casts=None,
                semantics='Activity gap only; recast, failure, phase and reset unknown'))
        previous[key]=row
    return pairs
