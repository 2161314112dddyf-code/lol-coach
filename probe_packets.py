"""Read-only packet framing probe. No opcode is assigned a gameplay meaning.

Framing reference:
https://github.com/Toastaspiring/ROFL-X/blob/main/docs/ROFL_FORMAT.md
Signed parameter delta correction:
https://github.com/Danmoreng/league-replay-analyzer/blob/main/docs/packet-block-semantic-findings.md
"""
import collections
import json
import struct
from pathlib import Path

import zstandard

SOURCE = Path(r'C:\Users\21613\Desktop\HN1-11360086609.rofl')


def packets(source=SOURCE):
    data = Path(source).read_bytes()
    metadata_size = struct.unpack_from('<I', data, len(data) - 4)[0]
    end = len(data) - 4 - metadata_size - 256
    offset = 15 + data[14]
    while offset < end:
        chunk, next_id, stream, raw_size, compressed_size = struct.unpack_from('<IIBII', data, offset)
        stored_size = compressed_size or raw_size
        raw = data[offset + 17:offset + 17 + stored_size]
        if compressed_size:
            raw = zstandard.ZstdDecompressor().decompress(raw)
        assert len(raw) == raw_size
        pos = 0
        timestamp = 0.0
        opcode = param = 0
        while pos < len(raw):
            start = pos
            marker = raw[pos]
            pos += 1
            if marker & 0x80:
                timestamp += raw[pos] / 1000
                pos += 1
            else:
                timestamp = struct.unpack_from('<f', raw, pos)[0]
                pos += 4
            if marker & 0x10:
                length = raw[pos]
                pos += 1
            else:
                length = struct.unpack_from('<I', raw, pos)[0]
                pos += 4
            if not marker & 0x40:
                opcode = struct.unpack_from('<H', raw, pos)[0]
                pos += 2
            if marker & 0x20:
                param = (param + struct.unpack_from('<b', raw, pos)[0]) & 0xffffffff
                pos += 1
            else:
                param = struct.unpack_from('<I', raw, pos)[0]
                pos += 4
            assert pos + length <= len(raw), (chunk, stream, start, pos, length)
            payload = raw[pos:pos + length]
            pos += length
            yield dict(stream=stream, chunk=chunk, channel=marker & 0x0f, time=timestamp,
                       opcode=opcode, param=param, offset=start, payload=payload)
        assert pos == len(raw)
        offset += 17 + stored_size
    assert offset == end


if __name__ == '__main__':
    rows = list(packets())
    game = [p for p in rows if p['stream'] == 1]
    counts = collections.Counter(p['opcode'] for p in game)
    summary = {'all_packet_count': len(rows), 'game_packet_count': len(game),
               'time_range': [min(p['time'] for p in game), max(p['time'] for p in game)],
               'opcode_counts': {hex(k): v for k, v in counts.most_common()},
               'warning': 'No packet opcode or payload field has been assigned a verified gameplay meaning.'}
    Path('packet_probe.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    for opcode, count in counts.items():
        if 105 <= count <= 120:
            matches = [p for p in game if p['opcode'] == opcode]
            print('COUNT_CANDIDATE_ONLY', hex(opcode), count,
                  'lengths', collections.Counter(len(p['payload']) for p in matches))
            for p in matches[:5]:
                print(p['time'], hex(p['param']), p['payload'].hex(' '))
