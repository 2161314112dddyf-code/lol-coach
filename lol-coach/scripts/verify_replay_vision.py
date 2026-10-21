"""Real-corpus visibility checks and prefix/knowledge-filter evidence."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from export_replay_vision import ROOT,build,prefix
from lol_coach.replay_vision import visibility_at,event_key


def main():
    out=ROOT/'data/private/replay_vision';out.mkdir(parents=True,exist_ok=True)
    rows=[];full=None;checks=[]
    for name in ('11360086609','11363048522','11363093470','11372643015'):
        source=Path('C:/Users/21613/Documents/League of Legends/Replays')/f'HN1-{name}.rofl'
        result=build(source);path=out/(source.stem+'.json')
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        state=json.loads((ROOT/'data/private/replay_state'/path.name).read_text(encoding='utf8'))
        selected=prefix(result,50,100,state)
        prefix_path=out/(source.stem+'-team100-at50.json')
        prefix_path.write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf8')
        # Future input mutation must not alter time-50 knowledge.
        shortened={**result,'events':[e for e in result['events'] if e['time_seconds']<=50]}
        shortened_state={**state,'updates':[u for u in state['updates'] if u['time_seconds']<=50]}
        if prefix(shortened,50,100,shortened_state)!=selected:raise ValueError('Future input affects prefix')
        for invalid in (-1,float('nan'),float('inf'),1000):
            try:prefix(result,invalid,100)
            except ValueError:pass
            else:raise ValueError('Invalid cutoff accepted')
        by=defaultdict(list)
        for interval in result['intervals']:by[(interval['entity_id'],interval['observer_team_id'])].append(interval)
        for spans in by.values():
            if spans[0]['start_seconds']!=0 or spans[-1]['end_seconds']!=result['game_length_seconds']:
                raise ValueError('Incomplete interval partition')
            if any(a['end_seconds']!=b['start_seconds'] for a,b in zip(spans,spans[1:])):raise ValueError('Interval gap/overlap')
        rows.append(dict(source=str(source),source_sha256=result['source_sha256'],counts=result['counts'],
           unresolved=len(result['unresolved']),interval_partition='PASS',future_mutation_check='PASS',
           invalid_cutoff_check='PASS',output=str(path),output_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if name=='11360086609':full=result
    # Known transition boundaries and the counterexample to respawn=>invisible.
    for entity,t,team,expected in [('0x40000034',33,200,False),('0x40000034',34,200,True),
       ('0x40000034',41.1,200,False),('0x40000034',42,200,True),
       ('0x4000003a',20,100,None),('0x40000035',842.6,200,True),('0x40000035',843.8,200,False)]:
        actual=visibility_at(full['events'],t,team,[entity])[entity]['visible']
        if actual is not expected:raise ValueError('Real transition boundary mismatch')
        checks.append(dict(entity_id=entity,time_seconds=t,observer_team_id=team,expected=expected,actual=actual,status='PASS'))
    state=json.loads((ROOT/'data/private/replay_state/HN1-11360086609.json').read_text(encoding='utf8'))
    checked=0;hidden=0
    for team in (100,200):
        for t in (0,20,34,41.1,50,100,400,600,842.6,843.8,859):
            view=prefix(full,t,team,state)
            for entity,v in view['observed_enemy_state'].items():
                if v['visible'] is not True:
                    hidden+=1
                    if v['current_observed'] is not None:raise ValueError('Hidden entity has current data')
                for field,sample in v['last_observed'].items():
                    if sample['observed_at_seconds']>t:raise ValueError('Future sample leaked')
                    preceding=[e for e in full['events'] if e['entity_id']==entity and e['observer_team_id']==team and event_key(e)<=event_key(dict(time_seconds=sample['observed_at_seconds'],source=sample['source']))]
                    if not preceding or preceding[-1]['visible'] is not True:raise ValueError('Hidden sample leaked')
                    if field not in ('health','max_health','resource','max_resource','level'):raise ValueError('Unapproved field exposed')
                    checked+=1
    report=dict(task='RPL-003D',generated_at_utc=datetime.now(timezone.utc).isoformat(),target_version=full['version'],
      executed_by='Codex',independent_review=None,human_signoff=None,corpus=rows,transition_checks=checks,
      knowledge_filter=dict(checked_samples=checked,hidden_or_unknown_queries=hidden,status='PASS'),
      acceptance=[dict(id='DYN-04/hero-channel',status='PASS',evidence_level='cross_checked_binary_inference',scope='Supplied hero directory; inferred opposing-team enter/leave channel, not independently UI-verified'),
        dict(id='DYN-05/prefix-and-filter',status='PASS',scope='Actual corpus prefix/hidden-sample checks; synthetic edge checks recorded separately'),
        dict(id='DYN-04/complete-world-vision',status='INSUFFICIENT_EVIDENCE',scope='Region fog, wards, stealth/true sight, nonheroes and camera not reconstructed')])
    (ROOT/'reports/replay_vision_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(corpus=rows,knowledge_filter=report['knowledge_filter'],transition_checks=checks),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
