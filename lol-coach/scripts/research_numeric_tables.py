"""Offline bounded byte-codec search; candidate anchors are hypotheses only."""
from pathlib import Path
import json
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def rol(x, r):
    return ((x << r) | (x >> (8-r))) & 255


def swap(x):
    return ((x & 85) << 1) | ((x >> 1) & 85)


def search(pairs, tables, *, outer_add=False):
    xs = np.array(list(pairs), dtype=np.int32)
    ys = np.array(list(pairs.values()), dtype=np.int32)
    results = []
    bs = np.arange(256)[:, None]
    rights = {}
    for output_swap in (False, True):
        right = {}
        for e in (range(256) if outer_add else (0,)):
            y = (ys-e) & 255
            if output_swap:
                y = swap(y)
            for s in range(8):
                zs = rol(y[None, :] ^ bs, (8-s) % 8)
                diffs = ((zs[:, 1:]-zs[:, :1]) & 255).astype(np.uint8)
                for d, row in enumerate(diffs):
                    right.setdefault(row.tobytes(), []).append((s,d,int(zs[d,0]),e))
        rights[output_swap] = right
        print(json.dumps(dict(right_keys=len(right),output_swap=output_swap)),flush=True)
    for label, table in tables.items():
        for mode in range(4):
            x = swap(xs) if mode & 1 else xs
            right = rights[bool(mode & 2)]
            for r in range(8):
                for a in range(256):
                    z = table[rol((x+a) & 255, r) ^ bs]
                    diffs = ((z[:, 1:] - z[:, :1]) & 255).astype(np.uint8)
                    for b, row in enumerate(diffs):
                        for s, d, z0, e in right.get(row.tobytes(), []):
                            c = (z0-int(z[b, 0])) & 255
                            values = np.arange(256)
                            if mode & 1:
                                values = swap(values)
                            values = rol((table[rol((values+a) & 255, r)^b]+c) & 255, s)^d
                            if mode & 2:
                                values = swap(values)
                            values = (values+e) & 255
                            values = values.tolist()
                            assert all(values[k] == v for k,v in pairs.items())
                            results.append(dict(base=label, mode=mode, a=a,b=b,c=c,d=d,e=e,r=r,s=s,table=values))
            print(json.dumps(dict(base=label,mode=mode,models=len(results))),flush=True)
    return results


def main():
    raw = (ROOT/'data/research/client_16.20.824.8524_mac/LeagueofLegends').read_bytes()[16384:]
    tables = {hex(o):np.frombuffer(raw[o:o+256],dtype=np.uint8).astype(np.int32)
              for o in (0x232da30,0x232db30)}
    tables['replication'] = np.array(json.loads((ROOT/'lol_coach/profiles/replication_16_20.json').read_text())['encoding_table'])
    # These are NOT accepted labels: derived from the hypothesis of positive
    # float32 countdowns between observed Ghost casts and keyframes.
    pairs = {0:0xb9,0x3f:0x9f,0x40:0xeb,0x41:0xc0,0x42:0xb0,0x43:0xcf}
    result = dict(anchor_status='HYPOTHESIS_NOT_VALIDATED',pairs=pairs,models=search(pairs,tables))
    out = ROOT/'data/private/replay_completion'
    out.mkdir(parents=True,exist_ok=True)
    (out/'numeric_table_models.json').write_text(json.dumps(result,indent=2),encoding='utf8')


if __name__ == '__main__':
    main()
