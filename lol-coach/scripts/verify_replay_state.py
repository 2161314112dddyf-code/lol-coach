"""Execute real-corpus comparisons; no assertions of external/game-UI review."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from export_replay_state import build
from lol_coach.replay_state import prefix_state


def main():
    replay_dir=Path('C:/Users/21613/Documents/League of Legends/Replays')
    output_dir=ROOT/'data/private/replay_state'
    output_dir.mkdir(exist_ok=True)
    bundles={}
    for stem in ('HN1-11360086609','HN1-11363048522','HN1-11363093470','HN1-11372643015'):
        bundle=build(replay_dir/(stem+'.rofl'))
        (output_dir/(stem+'.json')).write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf8')
        bundles[stem]=bundle
    full=bundles['HN1-11360086609']
    old=json.loads((ROOT/'data/private/replay_fields/HN1-11360086609.json').read_text())
    life_path=ROOT.parent/'lifecycle_experiment.json'
    life=json.loads(life_path.read_text())['intervals']
    state={};bad_health=[];bad_resource=[];gold_drops=[];zero=[];levels=[]
    for u in full['updates']:
        a=state.setdefault(u['entity_id'],{})
        v=u['values']
        if 'total_gold' in v and v['total_gold']<a.get('total_gold',0)-.01:
            gold_drops.append(u['source'])
        a.update(v)
        if a.get('health',0)>a.get('max_health',float('inf'))+.02:bad_health.append(u['source'])
        if a.get('resource',0)>a.get('max_resource',float('inf'))+.02:bad_resource.append(u['source'])
        if v.get('health')==0:zero.append(u)
        if 'level' in v:levels.append(u)
    footer=[]
    for i,p in enumerate(old['final_statistics']['players']):
        a=state[hex(0x40000034+i)]
        footer.append(dict(champion=p['SKIN'],final_total_gold=a['total_gold'],
                           footer_gold=int(p['GOLD_EARNED']),gold_floor_match=math.floor(a['total_gold'])==int(p['GOLD_EARNED']),
                           final_level=a['level'],footer_level=int(p['LEVEL']),
                           level_match=a['level']==int(p['LEVEL'])))
    death_checks=[]
    for s in life:
        near=[u for u in zero if u['entity_id']==s['entity_id'] and -.001<=u['time_seconds']-s['death_seconds']<=.112]
        death_checks.append(dict(entity=s['entity_id'],death_time=s['death_seconds'],
                                matched=bool(near),zero_times=[u['time_seconds'] for u in near]))
    zero_outside=[]
    for u in zero:
        if not any(s['entity_id']==u['entity_id'] and s['death_seconds']-.001<=u['time_seconds']
                   and (s['respawn_seconds'] is None or u['time_seconds']<s['respawn_seconds']) for s in life):
            zero_outside.append(u['source'])
    level_checks=[]
    for event in old['level_events']:
        time=event['packet_time_seconds']
        same=[e for e in old['level_events'] if e['entity_id']==event['entity_id'] and abs(e['packet_time_seconds']-time)<.0001]
        final=same[-1]['level_candidate']
        if event['level_candidate']!=final:
            level_checks.append(dict(entity=event['entity_id'],time=time,status='coalesced_same_frame_intermediate',level=event['level_candidate']))
            continue
        matches=[u for u in levels if u['entity_id']==event['entity_id'] and u['values']['level']==final and -.001<=u['time_seconds']-time<=.112]
        level_checks.append(dict(entity=event['entity_id'],time=time,status='matched' if matches else 'unmatched',
                                 level=final,state_times=[u['time_seconds'] for u in matches]))
    prefix=prefix_state(full['updates'],50)
    prefix_ok=all(f['observed_at']<=50 for a in prefix['actors'].values() for f in a.values())
    # Compare late gold totals to footer only in this verification report, not decoder input.
    result=dict(schema='replay-state-validation/v1',version=full['version'],
        executed_by='Codex self-check; independent review not performed',
        inputs={k:v['source_sha256'] for k,v in bundles.items()},
        counts={k:v['counts'] for k,v in bundles.items()},
        unresolved={k:v['unresolved'] for k,v in bundles.items()},
        footer_checks=footer,death_checks=death_checks,level_timeline_checks=level_checks,
        zero_state_records=len(zero),zero_outside_death_intervals=zero_outside,
        health_above_max=bad_health,resource_above_max=bad_resource,total_gold_decreases=gold_drops,
        prefix_50_has_no_future_values=prefix_ok,
        acceptance={'DYN-01':'PASS for decoded state values in supplied samples; resource type/UI comparison not verified',
                    'DYN-03-gold':'PASS for supplied samples',
                    'DYN-03-equipment':'INSUFFICIENT_EVIDENCE',
                    'DYN-02':'INSUFFICIENT_EVIDENCE','DYN-04':'INSUFFICIENT_EVIDENCE',
                    'DYN-05':'Prefix check executed; synthetic checks reported separately'},
        notes=['A zero state record is not a new death event. Karthus has additional within-death changes.',
               'No matching-build client source or independent video/UI numeric labels were used.',
               'A matching floor of final gold is an independent embedded footer check; it was not used to train the byte table.',
               'Unknown economy suffixes remain unparsed, and visibility filtering is absent.'])
    result['checks_passed']=all(v['counts']['packets']==v['counts']['bounded_packets'] and not v['unresolved'] for v in bundles.values()) and all(x['gold_floor_match'] and x['level_match'] for x in footer) and all(x['matched'] for x in death_checks) and all(x['status']!='unmatched' for x in level_checks) and not any((zero_outside,bad_health,bad_resource,gold_drops)) and prefix_ok
    (ROOT/'reports/replay_state_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (output_dir/'HN1-11360086609-at50.json').write_text(json.dumps(prefix,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(checks_passed=result['checks_passed'],packet_counts={k:v['counts']['bounded_packets'] for k,v in bundles.items()},
        footer_gold_matches=sum(x['gold_floor_match'] for x in footer),footer_level_matches=sum(x['level_match'] for x in footer),
        deaths_matched=sum(x['matched'] for x in death_checks),deaths_total=len(death_checks),
        zero_records=len(zero),zero_outside=len(zero_outside),health_above_max=len(bad_health),resource_above_max=len(bad_resource),
        gold_decreases=len(gold_drops),unresolved={k:len(v['unresolved']) for k,v in bundles.items()})))
    if not result['checks_passed']:
        raise SystemExit(1)


if __name__=='__main__':main()
