"""Apply the existing experimental 16.20 decoder unchanged to a new local replay.

The parent workspace files are explicitly supplied, reviewed local prerequisites.
This does not train/solve a new substitution table from the validation video.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.calibration import parse_session_log


def reference(path):
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
            'size_bytes': len(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--decoder-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.replay.read_bytes()
    version = raw[15:15+raw[14]].decode('ascii')
    if version != '16.20.824.8524':
        raise ValueError('Only the previously investigated exact build is supported')
    if not args.replay.stem.startswith('HN1-'):
        raise ValueError('Expected original HN1-GameID replay filename')
    game_id = args.replay.stem.removeprefix('HN1-')
    session = parse_session_log(args.log.read_text(encoding='utf-8'), game_id)
    if session['version'] != version:
        raise ValueError('Session and replay versions differ')
    table_path = args.decoder_dir / 'controlled-byte-synthesis.json'
    models = [m for m in json.loads(table_path.read_text(encoding='utf-8')) if m['status'] == 'sat']
    if len(models) != 1 or not models[0]['bijection'] or sorted(models[0]['table']) != list(range(256)):
        raise ValueError('Expected one existing bijective byte table')
    table = models[0]['table']
    inverse = bytes(table.index(i) for i in range(256))
    sys.path.insert(0, str(args.decoder_dir.resolve()))
    decoder_path = args.decoder_dir / 'decode_movement_1620.py'
    spec = importlib.util.spec_from_file_location('reviewed_movement_decoder', decoder_path)
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    counts = Counter()
    decoded, failures = [], []
    for packet in decoder.packets(args.replay):
        counts['all_packets'] += 1
        if packet['opcode'] != 0xc9 or packet['stream'] not in (1, 2):
            continue
        counts['candidate_movement_packets'] += 1
        where = {k: packet[k] for k in ('time', 'stream', 'chunk', 'offset')}
        try:
            result = decoder.decode_packet(packet['payload'], inverse)
        except ValueError as exc:
            failures.append({**where, 'error': str(exc)})
            continue
        counts['decoded_packets'] += 1
        counts['decoded_records'] += len(result['records'])
        decoded.append({**where, **result})
    metadata_size = int.from_bytes(raw[-4:], 'little')
    metadata = json.loads(raw[-4-metadata_size:-4])
    report = {'data_kind': 'experimental_decoder_candidates_on_held_out_replay',
              'sources': {'replay': reference(args.replay), 'log': reference(args.log),
                          'decoder': reference(decoder_path), 'byte_table': reference(table_path),
                          'packet_framer': reference(args.decoder_dir / 'probe_packets.py')},
              'version': version, 'session': session,
              'association_limit': 'Log GameID matched original replay filename, not decoded replay GameID. Video has no embedded GameID.',
              'game_length_metadata_ms': metadata.get('gameLength'),
              'counts': dict(counts), 'failures': failures, 'packets': decoded,
              'origin_hypothesis': decoder.MAP_ORIGIN_HYPOTHESIS,
              'table_refitted': False, 'actual_arrival_times': None,
              'decision_input_eligible': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'version': version, 'session': session, 'counts': dict(counts),
                      'failed_packets': len(failures), 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
