"""Coverage acceptance for the units present in the four frozen recordings.

Opaque protocol IDs and models absent from these recordings are limitations,
not extra prerequisites for identifying these observed units.
"""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import reference
from export_skill_ranks import STEMS


def main():
    folder=ROOT/'data/private/replay_completion';rows=[]
    for stem in STEMS:
        lanes=json.loads((folder/(stem+'-lane-identities.json')).read_text(encoding='utf8'))
        neutrals=json.loads((folder/(stem+'-neutral-identities.json')).read_text(encoding='utf8'))
        if lanes['source']!=neutrals['source']or reference(Path(lanes['source']['path']))!=lanes['source']:
            raise ValueError('Source mismatch')
        lane_ids={r['entity_id']for r in lanes['events']}
        identified={r['entity_id']for r in lanes['events']if r['identity']['kind']in('melee','ranged','siege','super')
                    and r['identity']['team_id']in(100,200)and r['identity']['lane']}
        monster_ids={r['entity_id']for r in neutrals['name_events']if r['identity']['model_name'].startswith('SRU_')}
        grouped={r['entity_id']for r in neutrals['derived_camp_membership']}
        checks=dict(all_lane_entities_classified=lane_ids==identified,all_observed_monsters_grouped=monster_ids==grouped,
            no_rejected_messages=not lanes['rejected']and not neutrals['rejected'],
            no_identity_conflicts=lanes['summary']['identity_conflicts']==0 and neutrals['summary']['name_conflicts']==0)
        rows.append(dict(replay=stem,source=lanes['source'],lane_entities=len(lane_ids),monster_entities=len(monster_ids),
            camp_groups=neutrals['summary']['runtime_camp_groups'],checks=checks,status='PASS'if all(checks.values())else'FAIL'))
    result=dict(acceptance_id='RPL-008-observed-lane-and-camp-identity',target_version='16.20.824.8524',
        status='PASS'if all(r['status']=='PASS'for r in rows)else'FAIL',rows=rows,
        scope='Observed lane type/team/lane and neutral model/position/unique camp membership in four supplied recordings',
        evidence_level='original packets plus explicit cross-field classification and derived camp grouping',
        limitations=['Not a universal decoder for absent models','Numeric protocol camp ID and runtime instance strings are opaque',
                    'Super classification uses a later witness and must not leak into earlier decisions'],
        executed_by='Codex',independent_review=None,human_signoff=None,four_targets_complete=False)
    (folder/'observed_unit_identity_acceptance.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(status=result['status'],lane_entities=sum(r['lane_entities']for r in rows),
        monster_entities=sum(r['monster_entities']for r in rows),camp_groups=sum(r['camp_groups']for r in rows))))
    if result['status']!='PASS':raise ValueError('Observed unit coverage failed')


if __name__=='__main__':main()
