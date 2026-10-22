"""Search bounded raw-array envelopes; matching length is not a semantic label."""
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_replay_ten import load_reviewed, reference


def length_bytes(total, start, tail):
    for width in (1,2,3):
        n = total-start-tail-width
        if n < 0:
            continue
        if width != (1 if n<128 else 2 if n<16384 else 3):
            continue
        out = []
        while n>=128:
            out.append((n&127)|128)
            n >>= 7
        return bytes(out+[n])
    return None


def main():
    framer,*_ = load_reviewed(ROOT.parent)
    source = Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    groups = defaultdict(list)
    for p in framer.packets(source):
        if p['payload']:
            groups[p['opcode'],p['payload'][0]].append(p)
    results = []
    for (op,first),rows in groups.items():
        if len({len(r['payload']) for r in rows}) < 8:
            continue
        for start in range(1,7):
            for tail in range(25):
                mapping, inverse = {}, {}
                good = True
                for row in rows:
                    d = row['payload']
                    plain = length_bytes(len(d), start, tail)
                    if plain is None:
                        good = False
                        break
                    for a,b in zip(plain,d[start:]):
                        if mapping.get(a,b)!=b or inverse.get(b,a)!=a:
                            good = False
                            break
                        mapping[a],inverse[b] = b,a
                    if not good:
                        break
                if good and len(mapping)>=8:
                    results.append(dict(opcode=hex(op),first_byte=hex(first),start=start,tail=tail,
                        packets=len(rows),pairs=mapping,
                        sample=[dict(time=r['time'],entity_id=hex(r['param']),stream=r['stream'],
                            chunk=r['chunk'],offset=r['offset'],payload_hex=r['payload'].hex()) for r in rows[:3]]))
    out = ROOT/'data/private/replay_completion/array_candidates.json'
    out.write_text(json.dumps(dict(source=reference(source),candidates=results),indent=2),encoding='utf8')
    print(json.dumps([{k:v for k,v in r.items() if k not in ('sample','pairs')}|dict(byte_pairs=len(r['pairs'])) for r in results]))


if __name__=='__main__':
    main()
