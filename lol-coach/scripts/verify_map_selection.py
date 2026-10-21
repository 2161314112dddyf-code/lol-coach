"""Real cached-evidence smoke for documented container-vs-skin selection."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import save_json
from lol_coach.map_pipeline import load_bundle
from lol_coach.map_selection import query_selected_grid, verified_bytes, build_policy
from lol_coach.ngrid import parse_ngrid

skin, manifest = load_bundle(ROOT,'16.20','Default')
policy = manifest['navigation_selection_policy']
metadata = json.loads(verified_bytes(ROOT/'data',policy['metadata_evidence']))
verified_bytes(ROOT/'data',policy['rule_evidence'])
assert build_policy(metadata,policy['rule_evidence'],manifest)['analysis_default']=='container'
container_source=manifest['navigation_reference_audit']['container_grid_source']
container=parse_ngrid(verified_bytes(ROOT/'data',container_source))
index=next(i for i,(a,b) in enumerate(zip(skin.flags,container.flags)) if a!=b)
x=skin.bounds_min[0]+(index%skin.width+0.5)*skin.cell_size
z=skin.bounds_min[2]+(index//skin.width+0.5)*skin.cell_size
a=query_selected_grid(ROOT,manifest,x,z)
b=query_selected_grid(ROOT,manifest,x,z,'skin')
assert a['grid_source']=='container' and b['grid_source']=='skin'
assert a['raw_flags']!=b['raw_flags']
assert a['queried_asset_sha256']==container_source['sha256']
assert a['actual_passability'] is None and a['runtime_selected_path'] is None
assert a['runtime_observed'] is False and a['active_overlays_applied'] is False
report={'status':'passed','data_kind':'real_cached_asset_and_documentation_smoke',
        'test_point_xz':[x,z],'default_query':a,'explicit_skin_query':b,
        'checks':['rule document hash','metadata hash and target build match','container raw hash and NGRID parse',
                  'actual differing cell query selects distinct assets','runtime and collision claims remain unknown'],
        'not_tested':['actual runtime file selection','collision','overlay composition','spawn placement']}
save_json(ROOT/'reports/map_selection_smoke.json',report)
print(json.dumps(report,indent=2))
