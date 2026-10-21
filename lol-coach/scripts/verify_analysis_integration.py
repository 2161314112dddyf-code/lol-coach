"""Real-cache integration checks; no claim of independently verified game semantics."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.analysis import context,load,checked_human_cards
from scripts.export_macro_snapshot import load_inputs
from lol_coach.analysis_context import build_context
from lol_coach.lineup_rules import build_lineup_bundle
from lol_coach.mechanism_rules import evaluate_interaction


def main():
    target=ROOT/'reports/analysis_integration_validation.json'
    if target.exists():raise ValueError('Existing run evidence must not be overwritten')
    cache=ROOT/'data/research/champion_catalog';inputs=[];human=checked_human_cards(inputs);mechanics=build_lineup_bundle(cache)
    records=[]
    for replay_id in ['HN1-11360086609','HN1-11363048522','HN1-11363093470','HN1-11372643015']:
        bundles,refs=load_inputs(replay_id);inputs.extend(refs)
        towers_path=ROOT/'data/private/turret_state'/f'{replay_id}.json';vision_path=ROOT/'data/private/tower_vision'/f'{replay_id}.json'
        paired=towers_path.exists() and vision_path.exists()
        towers=load(towers_path,inputs) if paired else None
        vision=load(vision_path,inputs) if paired else None
        for at,team in ([(0,100),(50,100),(400,100),(400,200),(859,100),(859,200)] if replay_id=='HN1-11360086609' else [(30,100)]):
            kw=dict(at=at,team=team,cache_root=cache,human_cards=human,mechanisms=mechanics,towers=towers,tower_vision=vision)
            result=build_context(bundles,**kw)
            prefix=deepcopy(bundles)
            for key in ('movement','lifecycle'):
                prefix[0]['categories'][key]['events']=[r for r in prefix[0]['categories'][key]['events'] if r['time_seconds']<=at]
            prefix[0]['categories']['kills']=[r for r in prefix[0]['categories']['kills'] if r['time_seconds']<=at]
            for index,keys in [(1,['updates']),(2,['events','state_barriers','unresolved']),(3,['events'])]:
                for key in keys:prefix[index][key]=[r for r in prefix[index][key] if r['time_seconds']<=at]
            if towers is not None:
                pt=deepcopy(towers);pv=deepcopy(vision)
                for key in ['identity_events','health_samples','destruction_events']:pt[key]=[r for r in pt[key] if r['time_seconds']<=at]
                pv['events']=[r for r in pv['events'] if r['time_seconds']<=at]
                kw.update(towers=pt,tower_vision=pv)
            assert build_context(prefix,**kw)==result,'Future input affected snapshot'
            assert all(e['time_seconds']<=at for e in result['evidence'].values())
            for t in result['world'].get('enemy_towers',{}).get('towers',[]):
                if t['visible'] is not True:assert t['observed_now'] is None
                for k in ('observed_now','last_observed'):
                    assert all(v['observed_at_seconds']<=at for v in (t[k] or {}).values())
            records.append(dict(replay_id=replay_id,at=at,team=team,coverage=result['coverage'],prefix_invariant=True,
                enemy_towers=len(result['world'].get('enemy_towers',{}).get('towers',[]))))
    cases=[]
    for rule in mechanics['interactions'][2:]:
        facts=rule['requires'].copy();r=evaluate_interaction(mechanics,rule['id'],facts,patch='16.20.1')
        assert r['status']==rule['when_met']['status'];assert not r['actual_match_observation']
        cases.append(dict(rule_id=rule['id'],input_kind='synthetic_conditions',result=r['status']))
    unique={r['path']:r for r in inputs}
    for r in unique.values():assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256']
    out=dict(schema='analysis-integration-validation/v1',executed_by='Codex',independent_review=False,
        game_semantic_independent_validation=False,queries=records,rule_cases=cases,
        mechanism_source_hashes_verified=len(mechanics['sources']),source_pointer_checks=len(mechanics['source_pointer_checks']),
        inputs_unchanged=list(unique.values()),status='PASS',scope='Offline source integrity, bounded joins, prefix and visibility policies')
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(queries=len(records),unchanged_inputs=len(unique),source_checks=len(mechanics['sources']),pointer_checks=len(mechanics['source_pointer_checks']))))


if __name__=='__main__':main()
