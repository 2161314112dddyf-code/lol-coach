"""Evidence-backed analysis selection; runtime observation remains separate."""
import hashlib
import json
from pathlib import Path

from .ngrid import parse_ngrid

REVIEWED_MAPSKIN_DOC_SHA256 = '8b5e925982ffa1e0dabf71f9b9057ec33a3e81dd2aa6972f8dc3628c37fb046a'


def build_policy(metadata, docs_source, manifest):
    dataset = metadata.get('dataset', {})
    if dataset.get('latestPatch') != manifest['patch']:
        raise ValueError('Metadata patch does not match map bundle')
    for local in manifest['local_metadata'].values():
        build = local['version'].split('+')[0].split('.')[-1]
        if str(dataset.get('latestBuild')) != build:
            raise ValueError('Metadata build does not match local asset build')
    if docs_source.get('sha256') != REVIEWED_MAPSKIN_DOC_SHA256:
        raise ValueError('Changed navigation documentation requires a new review')
    if 'container_grid_source' not in manifest.get('navigation_reference_audit', {}):
        raise ValueError('Run audit_map_context.py before applying the rule')
    return {'analysis_default': 'container',
            'basis': 'community_documented_container_navigation_rule',
            'rule_evidence': docs_source,
            'rule_pointer': '/properties/mNavigationMesh/description',
            'metadata_dataset': dataset,
            'runtime_observed': False,
            'limitations': ['Documentation claims priority; no target-session file-load trace',
                            'Documentation says the paths name the same file, but local assets differ',
                            'Active overlays and collision remain unverified']}


def verified_bytes(data_root, source):
    root = Path(data_root).resolve()
    path = (root / source['evidence_path']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Evidence path escapes data directory')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ValueError('Evidence SHA256 mismatch')
    return raw


def query_selected_grid(root, manifest, x, z, source='container'):
    if source not in ('skin', 'container'):
        raise ValueError('Unknown grid source')
    audit = manifest.get('navigation_reference_audit', {})
    if source == 'container':
        policy = manifest.get('navigation_selection_policy')
        if not policy or policy.get('analysis_default') != 'container':
            raise ValueError('Container rule not audited; run scripts/audit_map_rules.py --offline')
        raw_docs = verified_bytes(Path(root) / 'data', policy['rule_evidence'])
        if hashlib.sha256(raw_docs).hexdigest() != REVIEWED_MAPSKIN_DOC_SHA256:
            raise ValueError('Unreviewed navigation documentation')
        entry = audit['container_grid_source']
        basis = policy['basis']
    else:
        entry = manifest['base_grid']['source']
        basis = 'explicit_skin_reference_for_comparison'
    grid = parse_ngrid(verified_bytes(Path(root) / 'data', entry))
    result = grid.cell_at(x,z)
    result.update(queried_asset_path=entry['internal_path'], queried_asset_sha256=entry['sha256'],
                  grid_source=source, selection_basis=basis,
                  navigation_reference_status=audit.get('status', 'container_reference_not_audited'),
                  runtime_selected_path=None, runtime_observed=False,
                  active_overlays_applied=False)
    return result
