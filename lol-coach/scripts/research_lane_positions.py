"""Join accepted lane IDs to path records and compound position layouts.

Research export only. Path starts remain candidates; path destinations are not
arrivals. Static-format positions are packet samples, never a continuous track.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS
from lol_coach.lane_positions import compound_lane_position
from lol_coach.replay_fields import read_metadata

def source_ref(packet):
    return dict(stream=packet['stream'], chunk=packet['chunk'],
        decompressed_offset=packet['offset'], opcode=hex(packet['opcode']),
        payload_sha256=hashlib.sha256(packet['payload']).hexdigest())


def run(stem, folder, framer, movement, inverse, dependencies):
    identities_path = ROOT/'data/private/replay_completion'/f'{stem}-lane-identities.json'
    identities = json.loads(identities_path.read_text(encoding='utf-8'))
    source = Path(identities['source']['path'])
    original = reference(source)
    if original != identities['source']:
        raise ValueError('Lane identities belong to another replay')
    version, _, _ = read_metadata(source.read_bytes())
    if identities['version'] != version:
        raise ValueError('Lane identity version mismatch')
    accepted_ids = {row['entity_id'] for row in identities['events']}
    paths = []
    compounds = []
    failures = []
    opcode_counts = Counter()
    movement_packets = Counter()
    for packet in framer.packets(source):
        actor = hex(packet['param'])
        if actor in accepted_ids:
            opcode_counts[(packet['stream'], hex(packet['opcode']))] += 1
        if packet['opcode'] == 0xc9:
            movement_packets[f"stream_{packet['stream']}_attempted"] += 1
            try:
                decoded = movement.decode_packet(packet['payload'], inverse)
            except (ValueError, IndexError, KeyError, struct.error) as exc:
                failures.append(dict(kind='movement_packet_rejected', time_seconds=packet['time'],
                    source=source_ref(packet), error=str(exc), lane_membership_unavailable=True))
                continue
            for record in decoded['records']:
                if record['entity_id'] not in accepted_ids:
                    continue
                paths.append(dict(entity_id=record['entity_id'], time_seconds=packet['time'],
                    source=source_ref(packet), relative_waypoints=record['relative_waypoints'],
                    first_relative_point_candidate=record['relative_waypoints'][0],
                    path_speed=record['speed'], flags=record['flags'], extra_byte=record['extra_byte'],
                    decoded_record_offset=record['decoded_offset'], decoded_record_end=record['decoded_end'],
                    encoded_array_offset=decoded['data_start'], actual_arrival=None,
                    position_semantics='path_start_candidate; not continuous current position',
                    map_origin=None, visibility=None, decision_input_eligible=False))
        if actor in accepted_ids and packet['opcode'] == 0x37d:
            try:
                value = compound_lane_position(packet['payload'], actor, movement, version=version)
            except (ValueError, IndexError, KeyError, struct.error) as exc:
                failures.append(dict(kind='compound_position_rejected', entity_id=actor,
                    time_seconds=packet['time'], source=source_ref(packet), error=str(exc)))
                continue
            compounds.append(dict(entity_id=actor, time_seconds=packet['time'],
                source=source_ref(packet), payload_hex=packet['payload'].hex(), **value,
                visibility=None, decision_input_eligible=False))

    by_time = defaultdict(list)
    for i, row in enumerate(paths):
        key = (row['source']['stream'], row['time_seconds'], row['entity_id'])
        by_time[key].append(i)
    comparisons = []
    origin_pairs = []
    for i, row in enumerate(compounds):
        key = (row['source']['stream'], row['time_seconds'], row['entity_id'])
        peers = by_time.get(key, [])
        if row['kind'] == 'embedded_path':
            matches = [j for j in peers if paths[j]['relative_waypoints'] == row['relative_waypoints']
                       and paths[j]['path_speed'] == row['path_speed']]
            comparisons.append(dict(compound_index=i, candidate_path_indices=peers,
                exact_match_indices=matches,
                status='MATCH' if matches else 'CONFLICT' if peers else 'NO_SAME_TIME_WITNESS'))
        else:
            for j in peers:
                first = paths[j]['relative_waypoints'][0]
                delta = [row['position_xz'][axis]-first[axis] for axis in range(2)]
                origin_pairs.append(dict(compound_index=i, path_index=j,
                    delta_xz=delta, path_point_count=len(paths[j]['relative_waypoints']),
                    old_origin_residual=math.dist(delta, [7358, 7412])))

    hypotheses = dict(status='INSUFFICIENT_EVIDENCE', independent_map_config=None,
        exact_origin=None, adopted_in_position_export=False,
        assumption='Same-time static-format float and path first point are same physical sample; each relative axis quantized in steps of 2',
        bound_per_axis=2, pairs=origin_pairs)
    if origin_pairs:
        ranges = [[max(r['delta_xz'][a]-2 for r in origin_pairs),
                   min(r['delta_xz'][a]+2 for r in origin_pairs)] for a in range(2)]
        hypotheses.update(candidate_origin_intervals=ranges,
            old_origin_consistent_under_bound=all(lo <= origin <= hi
                for (lo, hi), origin in zip(ranges, [7358, 7412])),
            largest_old_origin_residual=max(r['old_origin_residual'] for r in origin_pairs))

    summary = dict(replay=stem, accepted_lane_entities=len(accepted_ids),
        path_records=len(paths), live_path_records=sum(r['source']['stream'] == 1 for r in paths),
        keyframe_path_records=sum(r['source']['stream'] == 2 for r in paths),
        entities_with_paths=len({r['entity_id'] for r in paths}),
        compound_records=len(compounds),
        compound_path_records=sum(r['kind'] == 'embedded_path' for r in compounds),
        static_format_position_samples=sum(r['kind'] == 'static_format_position_sample' for r in compounds),
        compound_exact_path_matches=sum(r['status'] == 'MATCH' for r in comparisons),
        compound_same_time_path_conflicts=sum(r['status'] == 'CONFLICT' for r in comparisons),
        compound_no_same_time_witness=sum(r['status'] == 'NO_SAME_TIME_WITNESS' for r in comparisons),
        rejected_records=len(failures),
        static_position_origin_pairs=len(origin_pairs),
        old_legacy_origin_rejected=(bool(origin_pairs) and not hypotheses['old_origin_consistent_under_bound']))
    if reference(source) != original:
        raise ValueError('Original replay changed during research')
    output = dict(schema='lane-position-research/v1', version=version,
        source=original, lane_identity_source=reference(identities_path), dependencies=dependencies,
        summary=summary, path_records=paths, compound_position_records=compounds,
        same_time_comparisons=comparisons, origin_hypothesis=hypotheses, failures=failures,
        named_lane_opcode_counts=[dict(stream=s, opcode=o, count=n) for (s,o),n in opcode_counts.most_common()],
        movement_packet_counts=dict(movement_packets),
        accepted_layout_scope='Observed named lane-minion records in four exact-build replays only',
        current_position_reconstruction_complete=False, decision_input_eligible=False,
        limitations=['Path destination does not prove arrival or survival',
            'Path starts and static-format keyframes are discrete samples, not continuous trajectories',
            'Keyframe time and observer visibility require separate review before decision use',
            'Compound path and movement-array agreement establishes encoding agreement, not independent gameplay ground truth',
            'Legacy Map11 origin must not be silently applied to the single-lane sample',
            'No visibility, full alive count, lane pressure or tower-arrival time inferred'])
    with (folder/f'{stem}.json').open('x', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/private/lane_dynamics_position_attempt')
    args = parser.parse_args()
    folder = args.output.resolve()
    if not folder.is_relative_to((ROOT/'data/private').resolve()):
        raise ValueError('Research output must remain under data/private')
    folder.mkdir(parents=True, exist_ok=False)
    framer, movement, inverse, dependencies = load_reviewed(ROOT.parent)
    dependencies = dict(dependencies, research_script=reference(Path(__file__)),
        lane_position_decoder=reference(ROOT/'lol_coach/lane_positions.py'),
        compound_decoder=reference(ROOT/'lol_coach/compound_inventory.py'),
        stationary_decoder=reference(ROOT/'lol_coach/neutral_identity.py'))
    summaries = []
    for stem in STEMS:
        summary = run(stem, folder, framer, movement, inverse, dependencies)
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    with (folder/'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(task='RPL-010-LANE', summaries=summaries,
            accepted_runtime_position_decoder=False, new_game_capture=False,
            scope='Source-bound binary position/path joins; no independent UI or visibility validation'), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
