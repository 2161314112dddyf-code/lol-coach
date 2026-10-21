"""Offline reproduction and conservative visual comparison for the supplied sample."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.calibration import bind_bundle
from lol_coach.map_pipeline import load_bundle
from lol_coach.map_selection import query_selected_grid, verified_bytes
from lol_coach.ngrid import parse_ngrid, parse_overlay
from lol_coach.path_audit import audit_polyline
from lol_coach.movement_validation import candidate_transitions, shared_clock_offset, observed_duration_interval


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    private = ROOT / 'data/private/movement_11372643015'
    decoded = read(private / 'decoded.json')
    annotations = read(ROOT / 'reports/movement_visual_annotations.json')
    corrected = read(ROOT / 'reports/movement_visual_annotations_v2.json')
    diagnostics = read(ROOT / 'reports/video_timing_diagnostics.json')
    video = read(private / 'video_detail/manifest.json')
    for source in list(decoded['sources'].values()) + [{'path': video['source'], 'sha256': video['sha256']}]:
        if hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Source evidence changed: ' + source['path'])
    if any(a['video_sha256'] != video['sha256'] for a in (annotations, corrected, diagnostics)):
        raise ValueError('Annotation video mismatch')
    if decoded['failures'] or decoded['table_refitted']:
        raise ValueError('Sample no longer matches the reviewed decoding result')
    _, manifest = load_bundle(ROOT, '16.20', 'Default')
    binding = bind_bundle(decoded['session'], manifest)
    query_selected_grid(ROOT, manifest, 604, 612)
    grid_source = manifest['navigation_reference_audit']['container_grid_source']
    grid = parse_ngrid(verified_bytes(ROOT / 'data', grid_source))
    overlays = [{'source': o['source'], **parse_overlay(verified_bytes(ROOT / 'data', o['source']), grid.width, grid.height)}
                for o in manifest['overlays']]
    track = [{'time': p['time'], 'points': r['map_waypoints_assuming_legacy_origin'], 'speed': r['speed']}
             for p in decoded['packets'] if p['stream'] == 1
             for r in p['records'] if r['entity_id'] == '0x400000ae']
    paths = [{'packet_time_seconds': r['time'], **audit_polyline(grid, r['points'], overlays)} for r in track]
    transitions = candidate_transitions(track)
    stops = [t for t in transitions if t['kind'] == 'single_point_at_planned_endpoint']
    if len(track) != 9 or len(stops) != 3:
        raise ValueError('Reviewed sample counts changed')
    # Reviewed after decoding; no claim of a new blind test. The old invalid
    # brackets remain in history. Initial departure is no longer observed.
    packet_times = {'top_lane_stop': stops[0]['single_point_time'],
                    'base_stop': stops[1]['single_point_time'],
                    'base_move_right': stops[2]['start_time'], 'final_stop': stops[2]['single_point_time']}
    pairs = [{'event': e['id'], 'video_interval_seconds': e['video_interval_seconds'],
              'packet_time_seconds': packet_times[e['id']], 'role': e['role']}
             for e in corrected['events']]
    offset = shared_clock_offset(pairs)
    anchor = shared_clock_offset([p for p in pairs if p['role'] == 'clock_anchor'])
    anchors = anchor['shared_offset_interval_seconds']
    checks = []
    for pair in pairs:
        if pair['role'] != 'consistency_check':
            continue
        lo, hi = pair['video_interval_seconds']
        predicted = [pair['packet_time_seconds']-anchors[1], pair['packet_time_seconds']-anchors[0]]
        checks.append({'event': pair['event'], 'predicted_video_interval_from_anchor': predicted,
                       'observed_video_interval': [lo, hi],
                       'overlaps': max(lo, predicted[0]) <= min(hi, predicted[1])})
    intervals = {p['event']: p['video_interval_seconds'] for p in pairs}
    duration = observed_duration_interval(intervals['base_move_right'], intervals['final_stop'])
    timing_sample = {
        'schema_version': '0.1', 'sample_id': 'HN1-11372643015-base-movement-3',
        'data_kind': 'real_video_observed_duration_interval', 'video_sha256': video['sha256'],
        'replay_sha256': decoded['sources']['replay']['sha256'], 'client_version': decoded['version'],
        'start_video_interval_seconds': intervals['base_move_right'],
        'end_video_interval_seconds': intervals['final_stop'], 'duration_seconds_interval': duration,
        'duration_method': 'end lower - start upper; end upper - start lower, using visual evidence only',
        'annotation_evidence': 'reports/movement_visual_annotations_v2.json',
        'pixel_diagnostic_evidence': 'reports/video_timing_diagnostics.json',
        'observed': {'champion_candidate': 'Pantheon', 'level_visible': 1,
                     'start_region': 'base near allied top inhibitor',
                     'end_region': 'base near another allied inhibitor and tower',
                     'end_stationary_video_interval_seconds': [23.3, 24.8]},
        'unknown': {'independent_world_start': None, 'independent_world_end': None,
                    'actual_travel_distance_game_units': None, 'speed_profile': None,
                    'equipment_complete': None, 'runes': None, 'end_hp_numeric': None, 'end_mana_numeric': None},
        'decoder_comparison': {'packet_interval_seconds': stops[2]['packet_interval_seconds'],
                               'within_observed_interval': duration[0] <= stops[2]['packet_interval_seconds'] <= duration[1],
                               'constant_speed_hypothesis_seconds': stops[2]['constant_speed_duration_hypothesis_seconds']},
        'eligible_uses': ['retrospective_duration_comparison_for_this_sample'],
        'route_prediction_eligible': False, 'decision_input_eligible': False,
        'limitations': ['Manual observation after viewing decoder output; not blind validation.',
                       'Bounds reflect video sampling and visual interpretation, not statistical confidence.',
                       'World coordinates, complete speed/state and unseen collision rules remain unverified.']}
    sample_path = ROOT / 'data/normalized/movement_samples/HN1-11372643015-base-movement-3.json'
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_text(json.dumps(timing_sample, indent=2), encoding='utf-8')
    actual_frames = []
    for frame in video['frames']:
        path = private / 'video_detail' / frame['file']
        actual_frames.append({**frame, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    result = {
        'data_kind': 'real_local_evidence_with_manual_visual_correspondence',
        'replay': decoded['sources']['replay'], 'video': {k: v for k, v in video.items() if k != 'frames'},
        'source_integrity': 'verified', 'version': decoded['version'], 'session': decoded['session'],
        'video_replay_association': 'user_provided_pair_supported_by_event_order_and_landmarks; no embedded video GameID',
        'decoder': {'counts': decoded['counts'], 'failures': decoded['failures'], 'table_refitted': False},
        'hero_entity_candidate': '0x400000ae',
        'identity_limit': 'Pantheon appearance and matching movement pattern; champion-to-entity mapping not independently decoded',
        'map_binding': binding, 'grid_source': grid_source,
        'user_clarification': annotations.get('user_clarification'),
        'track': track, 'static_path_checks': paths, 'candidate_transitions': transitions,
        'visual_comparison': {'status': 'corrected_video_events_have_compatible_offset_in_this_clip',
                              'world_coordinate_error_units': None, 'manual_stop_before_destination_verified': False,
                              'actual_arrival_time_error_seconds': None,
                              'post_decode_manual_event_pairs': pairs, 'clock_offset_diagnostic': offset,
                              'single_anchor_offset': anchor, 'other_event_checks': checks,
                              'annotation_corrections': corrected['corrections']},
        'frames': actual_frames,
        'measured_duration_samples': 1, 'timing_sample': timing_sample,
        'actual_action_model_samples': 0, 'decision_input_eligible': False,
        'limitations': ['Offset is compatible with corrected manual observations in one video; no universal time calibration claim.',
                       'All three single-point records equal prior planned endpoints; no clearly observed stop-short counterexample.',
                       'First route was replanned and its speed is not established as constant.',
                       'Phone perspective and partially cropped minimap prevent independent precise world coordinates.',
                       'Initial position is only corroborated as fountain region; no coordinate fit from video.',
                       'Static grid compatibility does not establish runtime collision, overlays or hidden state.']}
    (ROOT / 'reports/movement_video_validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'source_hashes': 'verified', 'hero_stream1_records': len(track),
                      'endpoint_single_point_candidates': len(stops),
                      'static_blocking_contact_records': sum(bool(p['blocking_flag_contacts']) for p in paths),
                      'uncertain_flag_records': sum(bool(p['uncertain_flag_contacts']) for p in paths),
                      'overlay_contact_records': sum(bool(p['overlay_region_contacts']) for p in paths),
                      'clock_offset_diagnostic': offset,
                      'anchor_consistency_checks': checks, 'observed_duration_interval_seconds': duration,
                      'measured_duration_samples': 1,
                      'actual_action_model_samples': 0}, indent=2))


if __name__ == '__main__':
    main()
