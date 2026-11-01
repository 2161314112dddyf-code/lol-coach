"""Bounded minion lifecycle correlation, never a general death/visibility decoder.

Reads the four existing exact-build source files and accepted lane identities.
Reports live-stream and checkpoint counts separately. Health values are decoded
only from nonhero group-8 prefix bits 0/1 and remain scoped to named lane IDs.
"""
from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_state import decode_payload, floating, inverse_table


def packet_ref(packet):
    return dict(stream=packet['stream'], chunk=packet['chunk'],
        decompressed_offset=packet['offset'], opcode=hex(packet['opcode']),
        payload_length=len(packet['payload']),
        payload_sha256=hashlib.sha256(packet['payload']).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
        default=ROOT/'data/private/lane_dynamics_lifecycle_attempt')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'data/private'):
        parser.error('Output must be a new directory under data/private')
    output.mkdir(parents=True, exist_ok=False)
    framer, movement, movement_inverse, deps = load_reviewed(ROOT.parent)
    inverse = inverse_table()
    totals = []
    for stem in STEMS:
        identity_path = ROOT/'data/private/replay_completion'/(stem+'-lane-identities.json')
        identities = json.loads(identity_path.read_text(encoding='utf-8'))
        source = Path(identities['source']['path'])
        source_ref = reference(source)
        version, *_ = read_metadata(source.read_bytes())
        if source_ref != identities['source'] or version != identities['version']:
            raise ValueError('Identity replay/build mismatch')
        names = {int(e['entity_id'], 16): e['identity'] for e in identities['events']}
        health, direct, moves = defaultdict(list), defaultdict(list), defaultdict(list)
        opcode_stream = Counter()
        rejected = []
        stream_end_times = {}
        for packet_index, packet in enumerate(framer.packets(source)):
            stream_end_times[packet['stream']] = max(stream_end_times.get(packet['stream'], 0), packet['time'])
            src = packet_ref(packet)
            actor = packet['param']
            if actor in names:
                opcode_stream[(packet['stream'], hex(packet['opcode']))] += 1
                row = dict(time_seconds=packet['time'], packet_index=packet_index, source=src)
                if packet['opcode'] in (0x167, 0x490):
                    row['payload_hex'] = packet['payload'].hex()
                direct[actor].append(row)
            if packet['opcode'] == 0x3df:
                try:
                    records = decode_payload(packet['payload'], version=version, inverse=inverse)['records']
                except ValueError as exc:
                    rejected.append(dict(source=src, reason=str(exc), layer='replication'))
                    continue
                for record in records:
                    actor = record['entity_id']
                    if actor not in names:
                        continue
                    for group in record['groups']:
                        if group['group'] != 8 or not group['field_mask'] & 3:
                            continue
                        data = bytes.fromhex(group['decoded_data_hex'])
                        cursor, values, fields = 0, {}, {}
                        try:
                            for bit, label in ((0, 'health'), (1, 'max_health')):
                                if group['field_mask'] >> bit & 1:
                                    start = cursor
                                    value, cursor = floating(data, cursor)
                                    if value < 0:
                                        raise ValueError('Negative lane health prefix')
                                    values[label] = value
                                    fields[label] = dict(group=8, bit=bit,
                                        decoded_payload_offset=group['payload_offset']+start,
                                        decoded_hex=data[start:cursor].hex())
                        except ValueError as exc:
                            rejected.append(dict(source=src, entity_id=hex(actor), reason=str(exc),
                                layer='lane_health_prefix'))
                            continue
                        health[actor].append(dict(time_seconds=packet['time'], packet_index=packet_index,
                            values=values, fields=fields, source=src))
            elif packet['opcode'] == 0xc9:
                try:
                    records = movement.decode_packet(packet['payload'], movement_inverse)['records']
                except (ValueError, IndexError, KeyError) as exc:
                    rejected.append(dict(source=src, reason=str(exc), layer='movement'))
                    continue
                for record in records:
                    actor = int(record['entity_id'], 16)
                    if actor in names:
                        moves[actor].append(dict(time_seconds=packet['time'], packet_index=packet_index,
                            speed=record['speed'], waypoint_count=len(record.get('relative_waypoints', [])),
                            source=src))
        rows, aggregate = [], Counter()
        delta_167_zero, delta_167_490, delta_zero_490 = [], [], []
        for actor, identity in names.items():
            events = sorted((r for r in direct[actor] if r['source']['stream'] == 1),
                key=lambda r: (r['time_seconds'], r['packet_index']))
            samples = sorted((r for r in health[actor] if r['source']['stream'] == 1),
                key=lambda r: (r['time_seconds'], r['packet_index']))
            paths = sorted((r for r in moves[actor] if r['source']['stream'] == 1),
                key=lambda r: (r['time_seconds'], r['packet_index']))
            zeros = [r for r in samples if r['values'].get('health') == 0]
            positives = [r for r in samples if r['values'].get('health', 0) > 0]
            d167 = [r for r in events if r['source']['opcode'] == '0x167']
            d490 = [r for r in events if r['source']['opcode'] == '0x490']
            associations = []
            for event in d167:
                at = event['time_seconds']
                near = [r for r in zeros if abs(r['time_seconds']-at) <= .15]
                nearest = min(zeros, key=lambda r: abs(r['time_seconds']-at), default=None)
                next_remove = next((r for r in d490 if r['time_seconds'] >= at-.000001), None)
                after_positive = [r for r in positives if r['time_seconds'] > at+.15]
                after_moves = [r for r in paths if r['time_seconds'] > at+.15]
                row = dict(event=event, near_zero_health_samples=near,
                    nearest_zero_delta=None if nearest is None else nearest['time_seconds']-at,
                    first_removal_at_or_after=next_remove,
                    positive_health_after_150ms=after_positive,
                    movement_plan_after_150ms=after_moves)
                associations.append(row)
                aggregate['opcode_167'] += 1
                aggregate['167_with_zero_within_150ms'] += bool(near)
                aggregate['167_with_later_positive_health'] += bool(after_positive)
                aggregate['167_with_later_movement_plan'] += bool(after_moves)
                if nearest is not None:
                    delta_167_zero.append(nearest['time_seconds']-at)
                if next_remove is not None:
                    delta_167_490.append(next_remove['time_seconds']-at)
            last_remove = d490[-1] if d490 else None
            at_remove = last_remove['time_seconds'] if last_remove else None
            after_direct = [r for r in events if at_remove is not None and r['time_seconds'] > at_remove+.000001]
            after_health = [r for r in samples if at_remove is not None and r['time_seconds'] > at_remove+.000001]
            after_moves = [r for r in paths if at_remove is not None and r['time_seconds'] > at_remove+.000001]
            positives_after_zero = [r for r in positives if zeros and r['time_seconds'] > zeros[0]['time_seconds']+.15]
            removals = []
            for event in d490:
                preceding_zero = [r for r in zeros if r['time_seconds'] <= event['time_seconds']]
                prior = preceding_zero[-1] if preceding_zero else None
                delta = None if prior is None else event['time_seconds']-prior['time_seconds']
                removals.append(dict(event=event, preceding_zero_sample=prior,
                    seconds_since_last_zero=delta))
                aggregate['490_with_preceding_zero'] += prior is not None
                if delta is not None:
                    delta_zero_490.append(delta)
            aggregate['entities'] += 1
            aggregate['entities_with_live_health'] += bool(samples)
            aggregate['entities_with_zero_health'] += bool(zeros)
            aggregate['entities_with_167'] += bool(d167)
            aggregate['entities_with_490'] += bool(d490)
            aggregate['opcode_490'] += len(d490)
            aggregate['entities_zero_without_167'] += bool(zeros) and not bool(d167)
            aggregate['entities_167_without_zero'] += bool(d167) and not bool(zeros)
            aggregate['entities_positive_after_first_zero'] += bool(positives_after_zero)
            aggregate['entities_direct_after_last_490'] += bool(after_direct)
            aggregate['entities_health_after_last_490'] += bool(after_health)
            aggregate['entities_path_after_last_490'] += bool(after_moves)
            aggregate['live_health_samples'] += len(samples)
            aggregate['checkpoint_health_samples'] += sum(r['source']['stream'] != 1 for r in health[actor])
            rows.append(dict(entity_id=hex(actor), identity=identity,
                health_samples_live=samples, zero_health_samples=zeros,
                health_samples_checkpoint=[r for r in health[actor] if r['source']['stream'] != 1],
                opcode_167_associations=associations, opcode_490_events=d490,
                opcode_490_zero_associations=removals,
                direct_after_last_490=after_direct, health_after_last_490=after_health,
                paths_after_last_490=after_moves,
                positive_health_after_first_zero=positives_after_zero,
                movement_plans_live=paths))
        summary = dict(replay=stem, **aggregate,
            stream_end_times=stream_end_times,
            opcode_stream_counts=[dict(stream=s, opcode=o, count=n) for (s, o), n in sorted(opcode_stream.items())],
            rejected_by_layer=dict(Counter(r['layer'] for r in rejected)),
            nearest_167_zero_deltas=delta_167_zero,
            forward_167_490_deltas=delta_167_490,
            preceding_zero_to_490_seconds=dict(count=len(delta_zero_490),
                minimum=min(delta_zero_490, default=None), maximum=max(delta_zero_490, default=None)),
            zero_without_removal=[dict(entity_id=r['entity_id'],
                last_zero_at=r['zero_health_samples'][-1]['time_seconds'],
                recording_remaining_seconds=stream_end_times.get(1, 0)-r['zero_health_samples'][-1]['time_seconds'])
                for r in rows if r['zero_health_samples'] and not r['opcode_490_events']])
        result = dict(schema='lane-lifecycle-research/v1', task='RPL-010-LANE',
            source=source_ref, identity_source=reference(identity_path), version=version,
            dependencies=deps, summary=summary, rows=rows, rejected=rejected,
            general_death_decoder_accepted=False, decision_input_eligible=False,
            findings=dict(opcode_167_as_death='REJECTED_BY_LATER_POSITIVE_HEALTH' if aggregate['167_with_later_positive_health'] else 'INSUFFICIENT_EVIDENCE',
                opcode_490='terminal_removal_candidate_after_zero; not death_timestamp',
                zero_health='observed_lane_health_sample; do not backdate from later terminal evidence'),
            limitations=['Health/lifecycle correlation is scoped to accepted lane entity IDs and live stream',
                'Zero health is a recorded sample, not independently observed game death',
                '0x167 and 0x490 semantic labels remain scoped hypotheses without UI ground truth',
                'No following packets cannot by itself prove source termination, death or visibility shutdown',
                'No interpolation, current alive count, team visibility or hidden-state inference'])
        if reference(source) != source_ref:
            raise ValueError('Replay changed during research')
        (output/(stem+'.json')).write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        totals.append(summary)
        print(json.dumps({k: v for k, v in summary.items() if k not in
            ('opcode_stream_counts', 'nearest_167_zero_deltas', 'forward_167_490_deltas')}), flush=True)
    (output/'summary.json').write_text(json.dumps(totals, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
