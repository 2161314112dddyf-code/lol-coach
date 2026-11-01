"""Export source-bound minion evidence, or query a conservative packet-time prefix.

Exact-build research only. This CLI never infers continuous position, alive
counts, lane priority, arrival time, or player knowledge from mere identity.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_replay_ten import load_reviewed, reference
from lol_coach.lane_dynamics import query_at
from lol_coach.lane_health import decode_health_prefix
from lol_coach.lane_identity import decode_spawn
from lol_coach.lane_positions import compound_lane_position
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_state import VERSION, decode_payload, inverse_table
from lol_coach.replay_vision import decode_payload as decode_visibility


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def validate_identities(bundle, source, version):
    if version != VERSION or bundle.get('version') != version:
        raise ValueError('Unsupported or mismatched lane build')
    if bundle.get('schema') != 'lane-spawn-identities/v1' or bundle.get('source') != source:
        raise ValueError('Lane identity source/schema mismatch')
    rows, names = [], {}
    for row in bundle['events']:
        identity = row['identity']
        # Empty prefix invokes the class/build gate without inventing health.
        decode_health_prefix(dict(group=8, field_mask=0, decoded_data_hex=''),
                             version=version, identity=identity)
        actor = row['entity_id']
        try:
            actor_int = int(actor, 16) if isinstance(actor, str) else -1
        except ValueError:
            actor_int = -1
        if actor_int >> 30 != 1 or hex(actor_int) != actor:
            raise ValueError('Expected canonical class-1 entity ID')
        if not math.isfinite(row['time_seconds']) or row['time_seconds'] < 0:
            raise ValueError('Invalid identity timestamp')
        if row['source']['stream'] not in (1, 2) or int(row['source']['opcode'], 16) != 5:
            raise ValueError('Expected original live/checkpoint spawn evidence')
        decoded = decode_spawn(bytes.fromhex(row['source']['payload_hex']), version=version)
        for key, value in decoded.items():
            if key == 'kind' and value == 'super_candidate' and identity.get(key) == 'super':
                available = identity.get('classification_available_at')
                if not isinstance(available, (int, float)) or not math.isfinite(available) or available < 0:
                    raise ValueError('Super classification needs a timestamped witness')
                continue
            if identity.get(key) != value:
                raise ValueError('Lane identity conflicts with spawn bytes: ' + key)
        prior = names.get(actor)
        if prior and any(prior.get(key) != identity.get(key)
                         for key in ('team_id', 'lane', 'kind', 'spawn_token', 'opaque_instance_token_hex')):
            raise ValueError('Conflicting lane identity for ' + actor)
        names[actor] = identity
        # Retrospective health/path witnesses never travel with a prefix identity.
        rows.append({key: row[key] for key in ('entity_id', 'time_seconds', 'source', 'identity')})
    if not names:
        raise ValueError('No named lane identities')
    return rows, names


def packet_source(packet, packet_index):
    return dict(stream=packet['stream'], chunk=packet['chunk'],
                decompressed_offset=packet['offset'], packet_index=packet_index,
                opcode=hex(packet['opcode']), payload_sha256=hashlib.sha256(packet['payload']).hexdigest())


def build_evidence(packets, identities, names, version, movement, movement_inverse, state_inverse):
    events, rejected = [], []
    end = 0.0
    pending = {}
    for row in identities:
        key = (row['source']['stream'], row['source']['chunk'], row['source']['decompressed_offset'])
        if key in pending:
            raise ValueError('Duplicate identity source anchor')
        pending[key] = row
    for index, packet in enumerate(packets):
        if packet['stream'] == 1:
            end = max(end, packet['time'])
        actor = hex(packet['param'])
        src = packet_source(packet, index)
        base = dict(entity_id=actor, time_seconds=packet['time'], source=src)
        opcode = packet['opcode']
        anchor = (packet['stream'], packet['chunk'], packet['offset'])
        expected = pending.pop(anchor, None)
        if expected is not None and (opcode != 5 or actor != expected['entity_id']
                or packet['time'] != expected['time_seconds']
                or packet['payload'].hex() != expected['source']['payload_hex']):
            raise ValueError('Identity does not match its original packet anchor')
        try:
            if opcode == 0x3df:
                records = decode_payload(packet['payload'], version=version, inverse=state_inverse)['records']
                for record in records:
                    entity = hex(record['entity_id'])
                    if entity not in names:
                        continue
                    for group in record['groups']:
                        if group['group'] != 8 or not group['field_mask'] & 3:
                            continue
                        try:
                            decoded = decode_health_prefix(group, version=version, identity=names[entity])
                        except ValueError as exc:
                            rejected.append(dict(**base, entity_in_record=entity,
                                layer='lane_health', error=str(exc), group=group))
                            continue
                        fields = {name: dict(field, decoded_payload_offset=group['payload_offset']+field['decoded_offset'])
                                  for name, field in decoded['fields'].items()}
                        events.append(dict(entity_id=entity, time_seconds=packet['time'],
                            source=dict(src, decoded_record_offset=record['payload_offset'],
                                        decoded_group_offset=group['payload_offset']),
                            kind='health_sample', values=decoded['values'], fields=fields,
                            field_mask=group['field_mask'], unparsed_suffix_hex=decoded['unparsed_suffix_hex'],
                            evidence_level='cross_checked_binary_inference', unit='health_points'))
            elif opcode == 0xc9:
                decoded = movement.decode_packet(packet['payload'], movement_inverse)
                for record in decoded['records']:
                    if record['entity_id'] not in names:
                        continue
                    events.append(dict(entity_id=record['entity_id'], time_seconds=packet['time'],
                        source=dict(src, decoded_record_offset=record['decoded_offset'],
                                    decoded_record_end=record['decoded_end'], encoded_array_offset=decoded['data_start']),
                        kind='path_command', encoding='movement_array', relative_waypoints=record['relative_waypoints'],
                        path_speed=record['speed'], flags=record['flags'], extra_byte=record['extra_byte'],
                        position_semantics='path start candidate; not continuous current position',
                        current_map_position=None, map_origin=None, actual_arrival=None))
            elif actor in names and opcode == 0x37d:
                decoded = compound_lane_position(packet['payload'], actor, movement, version=version)
                kind = decoded.pop('kind')
                events.append(dict(**base, **decoded,
                    kind='path_command' if kind == 'embedded_path' else kind,
                    encoding='compound_state', map_origin=None))
            elif actor in names and opcode in (0x484, 0x3cd):
                try:
                    decoded = decode_visibility(opcode, packet['payload'], version=version)
                except ValueError as exc:
                    rejected.append(dict(**base, layer='visibility', error=str(exc)))
                    decoded = dict(kind='visibility_unknown_barrier', observer_team_id=None, visible=None)
                events.append(dict(**base, **decoded, payload_hex=packet['payload'].hex(),
                    scope='named minion entity channel; not area fog or proof of survival'))
            elif actor in names and opcode in (0x167, 0x490):
                events.append(dict(**base, kind='uninterpreted_167' if opcode == 0x167 else 'terminal_removal_candidate',
                    payload_hex=packet['payload'].hex(), exact_death_time=None))
        except (ValueError, IndexError, KeyError, struct.error) as exc:
            rejected.append(dict(**base, layer='packet_decode', error=str(exc)))
    if pending:
        raise ValueError('Identity source anchors were not found in this replay')
    return dict(schema='lane-dynamics-evidence/v1', version=version,
        recording_end_seconds=end, identities=identities, events=events, rejected=rejected,
        summary=dict(identity_entities=len(names), event_counts=[dict(stream=s, kind=k, count=n)
            for (s, k), n in sorted(Counter((e['source']['stream'], e['kind']) for e in events).items())],
            rejected_records=len(rejected)), decision_input_eligible=False,
        current_position_reconstruction_complete=False,
        limitations=['Exact-build named minions only; binary crosschecks are not independent gameplay ground truth',
            'Positive health is a historical sample, not a guarantee of current survival',
            'Zero health, delayed removal, and visibility leave are different observations',
            'Checkpoint data never backfills live prefixes',
            'Map-specific origin is unresolved; relative paths are not continuous current world coordinates',
            'No current alive count, wave pressure, tower-arrival ETA, or region fog coverage'])


def export(replay, identity_path, decoder_dir):
    source = reference(replay)
    version, *_ = read_metadata(replay.read_bytes())
    identity_ref = reference(identity_path)
    identity_bundle = json.loads(identity_path.read_text(encoding='utf-8'))
    rows, names = validate_identities(identity_bundle, source, version)
    framer, movement, movement_inverse, refs = load_reviewed(decoder_dir)
    for name in ('lane_health.py', 'lane_identity.py', 'lane_positions.py', 'lane_dynamics.py', 'replay_state.py',
                 'replay_vision.py', 'compound_inventory.py', 'neutral_identity.py', 'replay_inventory.py', 'replay_fields.py'):
        refs[name] = reference(ROOT/'lol_coach'/name)
    for name in ('replication_16_20.json', 'vision_16_20.json'):
        path = ROOT/'lol_coach/profiles'/name
        refs[name] = reference(path)
    refs['export_script'] = reference(Path(__file__))
    refs['identities'] = identity_ref
    result = build_evidence(framer.packets(replay), rows, names, version, movement, movement_inverse, inverse_table())
    result.update(source=source, dependencies=refs)
    if reference(replay) != source:
        raise ValueError('Source replay changed during export')
    for ref in refs.values():
        if reference(Path(ref['path'])) != ref:
            raise ValueError('Dependency changed during export: ' + ref['path'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('export', help='Read original packets; write a new private directory')
    build.add_argument('--replay', type=Path, required=True)
    build.add_argument('--identities', type=Path, required=True)
    build.add_argument('--decoder-dir', type=Path, default=ROOT.parent)
    build.add_argument('--output', type=Path, required=True)
    query = sub.add_parser('query', help='Read an evidence bundle; emit a prefix research view')
    query.add_argument('--bundle', type=Path, required=True)
    query.add_argument('--at', type=float, required=True)
    query.add_argument('--observer-team', type=int, choices=(100, 200))
    query.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/'data/private').resolve()):
        parser.error('Output must remain under data/private')
    if args.command == 'export':
        if output.exists():
            parser.error('Use a new output directory')
        output.mkdir(parents=True)
        bundle = export(args.replay.resolve(), args.identities.resolve(), args.decoder_dir.resolve())
        write_new(output/'evidence.json', bundle)
        write_new(output/'receipt.json', dict(task='RPL-010-LANE', command=sys.argv,
            source=bundle['source'], dependencies=bundle['dependencies'],
            output=reference(output/'evidence.json'), summary=bundle['summary']))
        print(json.dumps(bundle['summary']))
    else:
        bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
        result = query_at(bundle, args.at, args.observer_team)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_new(output, result)
        print(json.dumps(dict(output=str(output), at=args.at, observer_team_id=args.observer_team)))


if __name__ == '__main__':
    main()
