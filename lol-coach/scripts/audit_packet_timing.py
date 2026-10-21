"""Recompute packet times directly from stored absolute values and integer deltas."""
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import EvidenceClient


def main():
    report = json.loads((ROOT / 'data/private/movement_11372643015/decoded.json').read_text())
    for key in ('replay', 'packet_framer'):
        source = report['sources'][key]
        if hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Changed source: ' + key)
    raw = Path(report['sources']['replay']['path']).read_bytes()
    end = len(raw)-4-int.from_bytes(raw[-4:], 'little')-256
    offset = 15+raw[14]
    blocks = {}
    while offset < end:
        chunk, _, stream, size, compressed = struct.unpack_from('<IIBII', raw, offset)
        body = raw[offset+17:offset+17+(compressed or size)]
        body = zstandard.ZstdDecompressor().decompress(body, max_output_size=size) if compressed else body
        if len(body) != size or (chunk, stream) in blocks:
            raise ValueError('Invalid block')
        blocks[chunk, stream] = body
        offset += 17+(compressed or size)
    if offset != end:
        raise ValueError('Chunk boundary mismatch')
    spec = importlib.util.spec_from_file_location('reviewed_packet_framer', report['sources']['packet_framer']['path'])
    framer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(framer)
    selected = {(p['chunk'], p['stream'], p['offset']) for p in report['packets']
                if any(r['entity_id'] == '0x400000ae' for r in p['records'])}
    state, records = {}, []
    max_difference = 0
    count, abs_count, delta_count = 0, 0, 0
    max_f32_difference = 0
    def f32(value):
        return struct.unpack('<f', struct.pack('<f', value))[0]
    for packet in framer.packets(Path(report['sources']['replay']['path'])):
        key = packet['chunk'], packet['stream']
        body = blocks[key]
        pos = packet['offset']
        current = state.setdefault(key, {'absolute': 0., 'delta_ms': 0, 'delta_count': 0, 'absolute_offset': None, 'f32': 0.})
        if body[pos] & 128:
            delta = body[pos+1]
            current['delta_ms'] += delta
            current['delta_count'] += 1
            current['f32'] = f32(current['f32']+f32(delta/1000))
            delta_count += 1
            encoding = 'u8_millisecond_delta'
        else:
            absolute = struct.unpack_from('<f', body, pos+1)[0]
            current.update(absolute=absolute, delta_ms=0, delta_count=0, absolute_offset=pos, f32=absolute)
            abs_count += 1
            encoding = 'absolute_float32'
        independently_summed = current['absolute']+current['delta_ms']/1000
        max_difference = max(max_difference, abs(independently_summed-packet['time']))
        max_f32_difference = max(max_f32_difference, abs(current['f32']-packet['time']))
        if (*key, pos) in selected:
            records.append({'chunk': key[0], 'stream': key[1], 'offset': pos,
                            'encoding': encoding, 'original_packet_time': packet['time'],
                            'recomputed_time': independently_summed,
                            'absolute_anchor_time': current['absolute'],
                            'absolute_anchor_offset': current['absolute_offset'],
                            'sum_delta_ms_since_anchor': current['delta_ms'],
                            'delta_count_since_anchor': current['delta_count']})
        count += 1
    if max_difference > 1e-6:
        raise ValueError('Packet timestamp arithmetic differs materially')
    client = EvidenceClient(ROOT / 'data')
    url = 'https://raw.githubusercontent.com/Toastaspiring/ROFL-X/main/docs/ROFL_FORMAT.md'
    document, _ = client.fetch('rofl-format-timing-reference', url)
    result = {'data_kind': 'real_replay_raw_timestamp_arithmetic_audit',
              'replay': report['sources']['replay'], 'framer': report['sources']['packet_framer'],
              'packet_count': count, 'absolute_timestamp_count': abs_count, 'delta_timestamp_count': delta_count,
              'maximum_recompute_difference_seconds': max_difference,
              'maximum_float32_vs_existing_float64_difference_seconds': max_f32_difference,
              'hero_candidate_time_evidence': records,
              'reference_document': document,
              'reference_scope': 'Community format notes describe 16.8 and later findings; not official proof for 16.20.',
              'status': 'timestamp_arithmetic_reproduced',
              'limitations': ['Raw packet time is not independently declared identical to displayed game clock.',
                             'No payload table or timestamp offsets changed.', 'External documentation is reference data, not instructions.']}
    (ROOT / 'reports/packet_timing_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k in ('packet_count', 'absolute_timestamp_count',
          'delta_timestamp_count', 'maximum_recompute_difference_seconds', 'maximum_float32_vs_existing_float64_difference_seconds', 'status')}, indent=2))


if __name__ == '__main__':
    main()
