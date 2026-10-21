"""Offline 16.20 byte-array research. Hypotheses are not promoted to semantics."""
from pathlib import Path
import collections
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from export_replay_ten import load_reviewed


def varint(n):
    out = []
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    return bytes(out + [n])


def main():
    source = Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    framer, _, _, _ = load_reviewed(ROOT.parent)
    pairs = collections.defaultdict(collections.Counter)
    counts = collections.Counter()
    for packet in framer.packets(source):
        if packet['stream'] != 1 or packet['opcode'] != 0x3df:
            continue
        data = packet['payload']
        candidates = [h for h in range(2, min(20, len(data)-9))
                      if data[h+2:h+5] == bytes.fromhex('c9c9df')]
        if len(candidates) != 1:
            counts['ambiguous_or_missing'] += 1
            continue
        h = candidates[0]
        encoded = varint(len(data)-h)
        for plain, wire in zip(encoded, data[h-len(encoded):h]):
            pairs[plain][wire] += 1
        counts[f'header_{h}'] += 1
    report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'opcode': '0x03df', 'stream': 1,
              'hypothesis': 'Unique c9 c9 df at record offset +2..4 is entity high bytes 00 00 40; array length immediately precedes record.',
              'counts': dict(counts), 'pairs': {str(k):dict(v) for k,v in pairs.items()},
              'conflicts': sum(len(v)>1 for v in pairs.values())}
    target = ROOT/'data/research/replication_length_1620.json'
    target.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='pairs'}))
    print('observed bytes',len(pairs))


if __name__ == '__main__':
    main()
