"""Experimental 16.20.824.8524 movement decoder for supplied ROFL samples.

Byte transform synthesized from array-length/encoded-byte pairs, not coordinates.
Envelope start is resolved by encoded length and complete path grammar, rather
than assigning an unverified meaning to its preceding header fields.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct

from probe_packets import SOURCE as ORIGINAL, packets

SOURCES = [ORIGINAL,
           Path(r'C:\Users\21613\Documents\League of Legends\Replays\HN1-11363048522.rofl'),
           Path(r'C:\Users\21613\Documents\League of Legends\Replays\HN1-11363093470.rofl')]
MAP_ORIGIN_HYPOTHESIS = (7358, 7412)


def parse_paths(data, signed_delta=True):
    cursor = 0
    records = []
    while cursor < len(data):
        start = cursor
        if len(data) - cursor < 14:
            raise ValueError('short record')
        flags, entity, speed = struct.unpack_from('<HIf', data, cursor)
        cursor += 10
        if entity >> 30 != 1:
            raise ValueError('entity class')
        if not math.isfinite(speed) or not 0 <= speed <= 5000:
            raise ValueError('speed')
        count = (flags & 255) >> 1
        if count == 0:
            raise ValueError('empty path')
        extra = None
        if flags & 1:
            if cursor >= len(data): raise ValueError('extra byte')
            extra = data[cursor]
            cursor += 1
        mask_size = (2 * (count - 1) + 7) // 8
        if cursor + mask_size > len(data): raise ValueError('bitmap')
        mask = data[cursor:cursor + mask_size]
        cursor += mask_size
        previous = [0, 0]
        points = []
        for i in range(count):
            for axis in range(2):
                bit = 2 * (i - 1) + axis
                compact = i > 0 and mask[bit // 8] & (1 << (bit % 8))
                width = 1 if compact else 2
                if cursor + width > len(data): raise ValueError('coordinates')
                value = data[cursor] if compact else struct.unpack_from('<H', data, cursor)[0]
                if compact:
                    if signed_delta and value >= 128: value -= 256
                    value = (previous[axis] + value) & 65535
                previous[axis] = value
                cursor += width
            points.append([2 * (v if v < 32768 else v - 65536) for v in previous])
        records.append({'entity_id': hex(entity), 'flags': flags, 'extra_byte': extra,
                        'speed': speed, 'relative_waypoints': points,
                        'map_waypoints_assuming_legacy_origin': [[p[0] + MAP_ORIGIN_HYPOTHESIS[0], p[1] + MAP_ORIGIN_HYPOTHESIS[1]] for p in points],
                        'decoded_offset': start, 'decoded_end': cursor})
    if not records: raise ValueError('empty array')
    return records


def length_candidates(payload, inverse):
    # First byte belongs to an as-yet uninterpreted outer field. At most ten
    # header bytes are searched; all candidate byte arrays must consume EOF.
    for start in range(1, min(11, len(payload))):
        value = 0
        for i in range(5):
            if start + i >= len(payload): break
            byte = inverse[payload[start + i]]
            if i == 4 and byte > 15: break
            value |= (byte & 127) << (7 * i)
            if not byte & 128:
                end = start + i + 1
                if not (i and byte == 0) and value == len(payload) - end:
                    yield start, end
                break


def decode_packet(payload, inverse, signed_delta=True):
    choices = []
    for size_start, data_start in length_candidates(payload, inverse):
        body = payload[data_start:]
        # Recover front/back alternating storage, confirmed by full-array parse.
        plain = (body[::2] + body[1::2][::-1]).translate(inverse)
        try:
            records = parse_paths(plain, signed_delta)
        except ValueError:
            continue
        choices.append({'length_field_start': size_start, 'data_start': data_start,
                        'records': records})
    if len(choices) != 1:
        raise ValueError(f'{len(choices)} complete envelope candidates')
    return choices[0]


def main():
    synthesis = json.loads(Path('controlled-byte-synthesis.json').read_text())
    models = [m for m in synthesis if m['status'] == 'sat']
    assert len(models) == 1 and models[0]['bijection']
    table = models[0]['table']
    inverse = bytes(table.index(i) for i in range(256))
    reports = []
    for source in SOURCES:
        rows = list(packets(source))
        known_entities = {p['param'] for p in rows if p['param'] >> 30 == 1}
        counts, failures, decoded_rows = Counter(), [], []
        for p in rows:
            if p['opcode'] != 0xc9 or p['stream'] not in (1, 2): continue
            counts[f'stream_{p["stream"]}_packets'] += 1
            try:
                decoded = decode_packet(p['payload'], inverse)
            except ValueError as error:
                counts['failed_packets'] += 1
                failures.append({'time': p['time'], 'stream': p['stream'], 'chunk': p['chunk'],
                                 'offset': p['offset'], 'error': str(error), 'payload_hex': p['payload'].hex()})
                continue
            counts['decoded_packets'] += 1
            counts['decoded_paths'] += len(decoded['records'])
            counts['paths_with_entity_seen_in_outer_headers'] += sum(int(r['entity_id'],16) in known_entities for r in decoded['records'])
            decoded_rows.append({'time': p['time'], 'stream': p['stream'], 'chunk': p['chunk'],
                                 'offset': p['offset'], **decoded})
        output = Path(source.stem + '-movement.json')
        result = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                  'version': source.read_bytes()[15:15+source.read_bytes()[14]].decode(),
                  'counts': dict(counts), 'failures': failures, 'packets': decoded_rows,
                  'map_origin_hypothesis': MAP_ORIGIN_HYPOTHESIS,
                  'limitations': ['Map origin is inherited from older decoders, without independent current-build visual calibration.',
                                 'Path waypoints are planned routes; their final point is not proof the unit reached it.',
                                 'Signed compact deltas are a hypothesis checked against controlled continuity.',
                                 'Envelope fields before the array length are not semantically decoded.']}
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        reports.append({'source': source.name, 'counts': dict(counts), 'failure_examples': failures[:2], 'output': str(output.resolve())})
        print(json.dumps(reports[-1]), flush=True)
    Path('movement-1620-validation.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
