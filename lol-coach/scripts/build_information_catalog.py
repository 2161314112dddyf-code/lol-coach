"""One evidence index for collected macro inputs; never silently promote candidates."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-only',action='store_true',help='Refresh index without rewriting the historical RPL-004 run manifest')
    args=parser.parse_args()
    entries=[
        ('champion_base','static_source_complete','data/normalized/16.20.1/en_US/catalog','173 champions; patch 16.20.1'),
        ('ability_parameters','static_reference_only','data/normalized/16.20.1/en_US/ability_parameters.json','Not live cooldowns or matchup feasibility'),
        ('runtime_mechanisms','raw_source_reference','data/normalized/16.20.1/en_US/runtime_mechanics_reference.json','11 champions and six minion sources; mode overrides retained'),
        ('hero_dynamic_state','existing_bounded_decoder','data/private/replay_state','Apply existing visibility/time policy before use'),
        ('hero_visibility','existing_bounded_decoder','data/private/replay_vision','Hero channel only; no complete fog or wards'),
        ('spell_activity','partial_retrospective','data/private/spell_activity','Named activities; not completed casts or cooldown readiness'),
        ('inventory_operations','existing_partial_retrospective','data/private/replay_inventory','Operations, not complete slots'),
        ('inventory_sync','serialized_records_semantics_unresolved','data/private/inventory_sync','38 live serialized slot records; RPL-005 found cached/rollback-state conflicts in the same packet family; do not treat as current inventory'),
        ('world_objects','research_candidates','data/private/world_objects','Object names/team/map unresolved; no known-state eligibility'),
        ('turret_state','bounded_retrospective_decoder','data/private/turret_state','Ten Map12-associated tower identities; named enemy tower visibility can now filter live health; encoding mode 2 and other world identities unresolved'),
        ('structure_evidence','research_candidates','data/private/structure_evidence','Group-4 structural samples and inhibitor-like state event chain; exact identity, team, lane and visibility unresolved; not decision eligible'),
        ('remaining_decode','bounded_raw_extraction','data/private/remaining_decode','1541 serialized slot records including empty slots and 23533 numeric hero-attribute fields; six attribute candidates; inventory effective time unresolved'),
        ('enemy_tower_visibility','bounded_inferred_filter','data/private/tower_vision','136 strictly alternating messages on named enemy towers; source-linked live HP filtering; not region fog or ward coverage'),
        ('human_experience','historical_conditional_source','data/knowledge/human_decision_cases.json','Two sourced cards; no unconditional recommendation'),
        ('pantheon_mechanisms','source_backed_conditional_reference','data/knowledge/pantheon_mechanisms/Pantheon.mechanisms.json','Five source cards and Pantheon/Jhin ally plus Pantheon/Morgana counter scenarios; not observed cooldowns, live shield state or verified combat prediction'),
        ('time_t_snapshot','existing_filtered_structure','data/private/macro_snapshots','Core time/visibility-filtered structure; optional source-checked additions in integrated_analysis'),
        ('integrated_analysis','bounded_source_join','data/private/analysis','Same macro-snapshot/v1 with named enemy tower observations, lineup static references, three applicable conditional rules and two historical cards; not a complete tactical oracle'),
        ('movement_timeline','retrospective_evidence','data/private/analysis/movement-timeline.json','Nine packet plans/candidates and one existing video duration interval; no arrival inference'),
        ('inventory_time_hypotheses','unresolved_research','data/private/integration/inventory_time-v2.json','Five lag hypotheses, common-slot comparisons and counterexamples; timestamps unchanged'),
        ('clear_source_candidates','incomplete_source_conditions','data/knowledge/clear_candidates_int001-v2.json','No accepted complete measured record; public video HTML is not a viewed measurement')]
    items=[]
    for key,status,relative,boundary in entries:
        path=ROOT/relative
        if not path.exists():raise ValueError('Missing information artifact: '+relative)
        files=sorted(path.glob('*.json')) if path.is_dir() else [path]
        items.append(dict(category=key,status=status,path=relative,boundary=boundary,
            artifacts=[dict(path=str(p.relative_to(ROOT)).replace('\\','/'),sha256=digest(p)) for p in files]))
    catalog=dict(schema='macro-information-catalog/v1',generated_at_utc=datetime.now(timezone.utc).isoformat(),
        target_build='16.20.824.8524',items=items,complete_collection=False,
        missing=['Full spell casts/cancellations/targets/ranks/cooldown/reset state',
            'Complete inventory snapshots, consumption and extended keyframes',
            'Runtime map/mode ID, minion/inhibitor/nexus identity and remaining objective state; tower identity subset decoded',
            'Minion/ward/region visibility and special invisibility semantics; named enemy tower channel now filtered',
            'Condition-complete measured clear/action durations and final state',
            'Broader source-backed ally/opponent interactions and runtime conditions beyond five qualitative scenarios'],
        user_action_required_now=False)
    target=ROOT/'data/knowledge/macro_information_catalog.json'
    target.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
    if args.catalog_only:
        print(json.dumps(dict(categories=len(items),complete=False,historical_manifest_unchanged=True)))
        return
    names=['inventory_sync.py','spell_activity.py']
    paths=[ROOT/'lol_coach'/name for name in names]+[ROOT/'lol_coach/profiles/spell_activity_16_20.json']
    script_names=['export_inventory_sync','export_spell_activity','research_spell_hashes','research_runtime_spells',
        'research_world_objects','collect_champion_catalog','build_ability_reference','freeze_spell_activity_profile',
        'crosscheck_wave_reference','collect_human_cases','verify_world_collection','build_information_catalog']
    paths += [ROOT/'scripts'/(name+'.py') for name in script_names]
    paths += [ROOT/p for p in ['tests/test_world_collection.py','docs/WORLD_COLLECTION_TASK.md','README.md',
        'docs/CURRENT_TASK.md','reports/STATUS.md','reports/world_collection_validation.md',
        'reports/world_collection_attempt_failures.md','reports/world_collection_real_validation.json',
        'reports/ability_reference_validation.json','reports/wave_reference_validation.json',
        'reports/human_case_collection.json','reports/world_map_sources.json','reports/world_map11_retry.json',
        'reports/world_character_sources.json','reports/world_character_sources_corrected.json',
        'reports/inventory_sync_counts.json','reports/spell_activity_counts.json','reports/world_object_counts.json',
        'reports/pytest-world-collection.xml','data/knowledge/macro_information_catalog.json']]
    baseline=ROOT/'reports/world_collection_baseline'
    for row in json.loads((baseline/'manifest.json').read_text(encoding='utf8')):
        if digest(baseline/row['path'])!=row['sha256']:raise ValueError('Recovery copy changed')
    suite=ET.parse(ROOT/'reports/pytest-world-collection.xml').getroot().find('testsuite')
    manifest=dict(task='RPL-004',generated_at_utc=datetime.now(timezone.utc).isoformat(),
        implementation_and_report_files=[dict(path=str(p.relative_to(ROOT)).replace('\\','/'),sha256=digest(p)) for p in paths],
        data_catalog_sha256=digest(target),recovery_copies_verified=3,pytest=dict(suite.attrib),
        independent_review=None,human_signoff=None,overall_complete=False)
    (ROOT/'reports/world_collection_run.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(categories=len(items),manifest_files=len(paths),pytest=manifest['pytest'],complete=False)))


if __name__=='__main__':main()
