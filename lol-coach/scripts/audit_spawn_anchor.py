"""Offline spawn-landmark comparison; does not fit an origin to a desired point."""
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.map_pipeline import load_bundle
from lol_coach.http import save_json

grid, manifest = load_bundle(ROOT, '16.20', 'Default')
source = manifest['public_config_json']
raw = (ROOT / 'data' / source['evidence_path']).read_bytes()
if hashlib.sha256(raw).hexdigest() != source['sha256']:
    raise ValueError('Config evidence hash mismatch')
config = json.loads(raw)
track_path = ROOT.parent / 'controlled-11363093470-route-analysis.json'
track_raw = track_path.read_bytes()
track = json.loads(track_raw)
first = track['track'][0]
position = first['map_waypoints_assuming_legacy_origin'][0]
comparisons = []
for mode in ('CLASSIC', 'PRACTICETOOL'):
    mode_key = 'Maps/Shipping/Map11/Modes/' + mode
    settings = config[mode_key]
    locator_key = settings['mMapLocators']
    respawn_key = settings['DefaultRespawnPoints']
    gates = []
    for locator in config[locator_key]['locators']:
        if locator['name'] not in ('OrderSpawnGate', 'ChaosSpawnGate'):
            continue
        xyz = locator['transform'][3][:3]
        gates.append({'name': locator['name'], 'position_xyz': xyz,
                      'distance_to_initial_candidate_game_units': math.dist(position, [xyz[0], xyz[2]]),
                      'meaning': 'named_spawn_gate_landmark_not_exact_champion_spawn'})
    if len(gates) != 2:
        raise ValueError('Expected both spawn-gate locators')
    comparisons.append({'mode_object': mode_key, 'locator_object': locator_key,
                        'gates': gates, 'respawn_object': respawn_key,
                        'respawn_config': config[respawn_key],
                        'mode_selected_in_match': None})
report = {'data_kind': 'real_config_landmarks_compared_with_decoder_hypothesis',
          'config_evidence': source, 'local_config_sha256': manifest['local_config']['sha256'],
          'track_source': {'path': str(track_path), 'sha256': hashlib.sha256(track_raw).hexdigest()},
          'first_record_time_seconds': first['time_seconds'],
          'relative_position_candidate': first['relative_waypoints'][0],
          'origin_hypothesis': track['origin'], 'initial_world_position_candidate_xz': position,
          'comparisons': comparisons,
          'interpretation': 'Consistent with Order spawn vicinity under the existing origin; regional anchor only',
          'exact_spawn_coordinate_verified': False, 'origin_independently_solved': False,
          'limitations': ['Spawn gate is not champion spawn; do not force the two coordinates to match',
                          'FirstSpawnPositionOffset lacks a verified base point/application rule here',
                          'Single regional anchor does not independently determine scale or axis orientation'],
          'recording_required_to_continue_offline_work': False}
save_json(ROOT / 'reports/spawn_anchor_audit.json', report)
print(json.dumps({'candidate': position, 'gates': comparisons[0]['gates'],
                  'exact_spawn_coordinate_verified': False}, ensure_ascii=False, indent=2))
