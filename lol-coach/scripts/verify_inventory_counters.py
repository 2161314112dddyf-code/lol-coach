"""Fresh-source verification of accepted live counters and separate cache matches."""
import json,hashlib,sys,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import load_reviewed,reference
from lol_coach.inventory_live import decode_snapshot
from lol_coach.compound_inventory import decode_inventory
from lol_coach.replay_fields import read_metadata

def main():
    source=Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    ref=reference(source);version,*_=read_metadata(source.read_bytes());f,*_,deps=load_reviewed(ROOT.parent)
    live=[];cached=[];relationships=[]
    for p in f.packets(source):
        if p['opcode']==0x37d:
            try:d=decode_inventory(p['payload'],version=version)
            except ValueError:continue
            for i in d['items']:
                cached.append(dict(actor=p['param'],time=p['time'],item=i))
        elif p['stream']==1 and p['opcode']==0x4e9:
            d=decode_snapshot(p['opcode'],p['payload'],version=version)
            live.append(dict(actor=p['param'],time=p['time'],chunk=p['chunk'],offset=p['offset'],decoded=d))
            if not d['counters_complete']:raise ValueError('Unresolved counter in reviewed snapshot')
            for item in list(d['slots'].values())+d['internal_slots']:
                stats={v['key']:v['value']for v in item.get('stat_values',[])}
                count=item['charge_count'];kind=item['item_id'];check=None
                if kind==6657:check=stats=={80:count*3.,56:count*30.,51:count*10.}
                elif kind in(3070,3084)and stats:check=int(next(iter(stats.values())))==count
                elif kind==3008 and stats:
                    value=0.;step=struct.unpack('<f',struct.pack('<f',.006))[0]
                    for _ in range(count):value=struct.unpack('<f',struct.pack('<f',value+step))[0]
                    check=stats=={96:value}
                if check is not None:
                    relationships.append(dict(actor=hex(p['param']),time=p['time'],item_id=kind,count=count,stats=stats,consistent=check))
                    if not check:raise ValueError('Counter/stat constraint violated')
    overlap=[]
    for r in relationships:
        matches=[x for x in cached if hex(x['actor'])==r['actor']and x['item']['item_id']==r['item_id']
                 and x['item']['charge_count']==r['count']and {s['key']:s['value']for s in x['item']['stat_values']}==r['stats']]
        if matches:overlap.append(dict(**r,cache_times=[m['time']for m in matches],claim='same tuple only; cache time is not live time'))
    operation_path=ROOT/'data/private/replay_inventory/HN1-11360086609.json'
    kill_path=ROOT/'data/private/replay_ten/HN1-11360086609.json'
    operations=json.loads(operation_path.read_text(encoding='utf8'))
    kills=json.loads(kill_path.read_text(encoding='utf8'))
    if operations['source_sha256']!=ref['sha256']or kills['replay_sha256']!=ref['sha256']:
        raise ValueError('Independent event source mismatch')
    independent=[];timing=[]
    for row in relationships:
        buys=[e for e in operations['events']if e.get('item_id')==row['item_id']and e['entity_id']==row['actor']and e['time_seconds']<=row['time']]
        if len(buys)!=1:continue
        purchased=buys[0]['time_seconds']
        if row['item_id']==3008:
            events=[e for e in kills['categories']['kills']if purchased<e['time_seconds']<=row['time']and
                (e['killer_entity_id']==row['actor']or row['actor']in e['assist_entity_ids'])]
            expected=min(10,len(events));consistent=expected==row['count']
            independent.append(dict(row,purchase=buys[0],takedowns=events,expected_count=expected,consistent=consistent))
            if not consistent:raise ValueError('Independent takedown count conflict')
        elif row['item_id']==6657 and 0<row['count']<10:
            elapsed=row['time']-purchased
            timing.append(dict(**row,purchased_at=purchased,period_lower_exclusive=elapsed/(row['count']+1),period_upper_inclusive=elapsed/row['count']))
    lower=max(r['period_lower_exclusive']for r in timing);upper=min(r['period_upper_inclusive']for r in timing)
    if reference(source)!=ref:raise ValueError('Source changed')
    summary=dict(snapshots=len(live),snapshots_all_counters=sum(r['decoded']['counters_complete']for r in live),
        serialized_item_records=sum(sum('payload_range'in i for i in r['decoded']['slots'].values())+len(r['decoded']['internal_slots'])for r in live),
        variable_counts=sum(i.get('charge_selector')not in(0,1,7)for r in live for i in list(r['decoded']['slots'].values())+r['decoded']['internal_slots']if 'payload_range'in i),
        stat_entries=sum(len(i.get('stat_values',[]))for r in live for i in list(r['decoded']['slots'].values())+r['decoded']['internal_slots']),
        growth_relationships=len(relationships),relationships_failed=sum(not r['consistent']for r in relationships),independent_cached_tuple_matches=len(overlap),
        independent_takedown_checks=len(independent),independent_takedown_failures=sum(not r['consistent']for r in independent))
    report=dict(source=ref,version=version,dependencies=deps,summary=summary,relationships=relationships,cache_overlaps=overlap,
        independent_event_sources=[reference(operation_path),reference(kill_path)],independent_takedown_checks=independent,
        rod_simple_timer_hypothesis=dict(rows=timing,lower_exclusive=lower,upper_inclusive=upper,consistent=lower<upper,
            assumption='All actors gain one stack per identical fixed period from purchase, with no pauses/resets/lag',
            conclusion='This simple timing model is rejected; do not interpolate counters from purchase time'),
        limitations=['Count/stat relationships were part of calibration, not blind game UI labels',
                    'Separate compound tuples corroborate values but not live time','Unknown use slot and item cooldowns remain unresolved'])
    (ROOT/'data/private/replay_completion/inventory_counters_validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(summary))

if __name__=='__main__':main()
