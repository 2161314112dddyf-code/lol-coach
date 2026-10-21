"""Offline reproduction checks on real cached inputs; not in-game validation."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lol_coach.map_selection import verified_bytes
from lol_coach.ngrid import parse_ngrid,parse_overlay
from lol_coach.map_pipeline import load_bundle
from lol_coach.path_audit import audit_polyline
from lol_coach.clear_sources import extract_clear_candidates
from lol_coach.http import save_json

load=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8'))
paths=load('reports/replay_path_audit.json')
grid=parse_ngrid(verified_bytes(ROOT/'data',paths['grid_source']))
_,manifest=load_bundle(ROOT,'16.20','Default')
overlays=[{'source':o['source'],**parse_overlay(verified_bytes(ROOT/'data',o['source']),grid.width,grid.height)} for o in manifest['overlays']]
checked=0
for replay in paths['replays']:
    assert hashlib.sha256(Path(replay['replay_path']).read_bytes()).hexdigest()==replay['replay_sha256']
    assert hashlib.sha256(Path(replay['movement_report_path']).read_bytes()).hexdigest()==replay['movement_report_sha256']
    for record in replay['records']:
        assert audit_polyline(grid,record['points_candidate_xz'],overlays)==record['container_grid']
        assert record['container_grid']['actual_duration_seconds'] is None
        checked+=1
mechanics=load('data/normalized/16.20.1/en_US/Ivern.mechanics.json')
for source in mechanics['sources'].values():verified_bytes(ROOT/'data',source)
assert len(mechanics['claims'])==5
assert all(c['ally_context_required'] and c['opponent_context_required'] for c in mechanics['claims'])
assert mechanics['unresolved_discrepancies'][0]['runtime_rule'] is None
clears=load('data/normalized/clear_candidates/Ivern.json')
html=verified_bytes(ROOT/'data',clears['source']).decode('utf-8')
assert extract_clear_candidates(html,'Ivern')==clears['candidates']
assert all(r['elapsed_seconds'] is None and not r['action_model_eligible'] for r in clears['candidates'])
out={'status':'passed','data_kind':'real_cached_evidence_reproduction_not_gameplay_validation',
     'candidate_path_records_recomputed':checked,'mechanic_cards':5,'clear_source_rows_reproduced':len(clears['candidates']),
     'usable_measured_action_samples':0,
     'checks':['replay and prior movement hashes','container grid and overlay hashes','all candidate path audits reproduced',
               'mechanic source hashes and ally/opponent prerequisites','clear rows reproduced from source HTML',
               'missing durations and unresolved E rule remain unknown']}
save_json(ROOT/'reports/foundation_smoke.json',out)
print(json.dumps(out,indent=2))
