"""Acquire/check the reviewed rule and enable explicit container-based queries."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import EvidenceClient, save_json
from lol_coach.map_pipeline import load_bundle, keep
from lol_coach.map_selection import build_policy, verified_bytes
from lol_coach.wad import WadReader


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--offline', action='store_true')
    args = p.parse_args()
    _, manifest = load_bundle(ROOT, '16.20', 'Default')
    client = EvidenceClient(ROOT / 'data')
    metadata_ref, metadata = client.fetch('map-rule-meta', 'https://meta-api.leaguetoolkit.dev/v1', expect_json=True, offline=args.offline)
    docs_ref, docs = client.fetch('map-rule-docs', 'https://meta-api.leaguetoolkit.dev/v1/docs/MapSkin', expect_json=True, offline=args.offline)
    if not isinstance(metadata,dict) or not isinstance(docs,dict):
        raise ValueError('Metadata or rule documentation unavailable')
    policy = build_policy(metadata, docs_ref, manifest)
    policy['metadata_evidence'] = metadata_ref
    policy['attribution'] = 'LoL Meta Wiki — https://meta-wiki.leaguetoolkit.dev'
    policy['documentation_license'] = 'CC BY-SA 4.0 with League Toolkit Developer Tooling Exception'

    config = json.loads(verified_bytes(ROOT / 'data', manifest['public_config_json']))
    cfg_path = config[manifest['selection']['object']]['mMapObjectsCFG']
    raw, cfg_source = WadReader(manifest['archive']['path']).extract_bytes(cfg_path)
    cfg_source.update(keep(ROOT / 'data', raw, '.cfg'))
    # This evidence is saved as data, never executed or treated as commands.
    sections = [line for line in raw.decode('utf-8').splitlines() if line.startswith('[')]
    report = {'selection_policy':policy, 'object_config_source':cfg_source,
              'object_config_section_count':len(sections),
              'spawn_named_sections':[line for line in sections if 'spawn' in line.lower()],
              'spawn_rule_status':'no_verified_champion_spawn_slot_rule_obtained',
              'navigation_rule_status':'community_documented_not_runtime_observed'}
    save_json(ROOT / 'reports/map_rules_audit.json', report)
    manifest['navigation_selection_policy'] = policy
    save_json(ROOT / 'data/maps/16.20/Default/manifest.json', manifest)
    print(json.dumps({'analysis_default':policy['analysis_default'], 'basis':policy['basis'],
                      'runtime_observed':False, 'spawn_rule_status':report['spawn_rule_status']},indent=2))


if __name__ == '__main__':
    main()
