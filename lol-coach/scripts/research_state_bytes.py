"""RPL-003B: infer replication bytes from existing replay observations.

Seed constraints are explicit hypotheses; length witnesses recover the full table.
Gameplay checks are separate. No game process, network, or client executable.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from export_replay_ten import load_reviewed

REPLAYS = Path('C:/Users/21613/Documents/League of Legends/Replays')
SOURCES = {
    'HN1-11363048522': '1c17e0bb43b2629bf73972ddac9c53782abc1c2c32fca2d039c024e6c004aca3',
    'HN1-11360086609': 'c08c6f1a4a87f1670a6156c6badfca15a21aa13c74eaa18dff5efdc26b94e7e0',
}
# Each source of a constraint is kept separate from subsequent observations.
STRUCTURAL = {0: 0xc9, 1: 0x28, 2: 0x53, 3: 0x1f, 4: 0xbb,
              5: 0x13, 6: 0x63, 7: 0x00, 8: 0xdc, 9: 0x1d,
              10: 0x7b, 11: 0x27, 12: 0x80, 13: 0x0a, 14: 0x9c,
              16: 0x0d, 17: 0x52, 20: 0x92, 21: 0xba,
              32: 0x12, 33: 0x5b, 36: 0xf5, 40: 0xe5,
              41: 0x45, 44: 0xe6, 64: 0xdf, 136: 0xaa,
              174: 0xe7, 254: 0xbd, 255: 0x1c}
IDENTITIES = dict(zip(range(52, 62), bytes.fromhex('a9 b7 a0 e2 85 4d ec 19 66 11')))
XP_THRESHOLDS = [0, 280, 660, 1140, 1720, 2400, 3180, 4060, 5040, 6120, 7300, 8580, 9960]
LEVEL_SUFFIXES = dict(zip(range(2, 14), bytes.fromhex('19 be e4 65 83 dc b1 c8 1d 1b c7 aa')))
FLOAT_BITS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 19, 20, 25, 26, 27}


def ref(p, start=None):
    return dict(time=p['time'], stream=p['stream'], chunk=p['chunk'],
                offset=p['offset'], payload_offset=start,
                payload_sha256=hashlib.sha256(p['payload']).hexdigest())


def add_pairs(enc, pairs):
    for plain, wire in pairs:
        if plain in enc and enc[plain] != wire:
            raise ValueError(f'Conflicting constraint for {plain}')
        if wire in enc.values() and enc.get(plain) != wire:
            raise ValueError(f'Non-bijective constraint for {wire}')
        enc[plain] = wire


def train(rows):
    enc = dict(STRUCTURAL)
    add_pairs(enc, IDENTITIES.items())
    evidence = []
    # Observed narrow/wide group layouts: HP, maxHP, XP, [resource,max], level.
    # XP threshold equality is a training assumption, not held-out validation.
    for level in range(2, 14):
        anchor = [p for p in rows if p['opcode'] == 0x229 and p['param'] == 0x400000ae
                  and p['payload'][-1] == LEVEL_SUFFIXES[level]]
        if len(anchor) != 1:
            raise ValueError('Expected unique training level anchor')
        a = anchor[0]
        candidates = []
        for p in rows:
            if p['opcode'] != 0x3df or not 0 <= p['time'] - a['time'] <= .101:
                continue
            for header in ('1fdcc90d0a', '1faa280dba'):
                pos = p['payload'].find(bytes.fromhex(header))
                if pos >= 0:
                    candidates.append((p, pos+5+8))
        if len(candidates) != 1:
            raise ValueError(f'Ambiguous XP training window: {level}: {len(candidates)}')
        p, start = candidates[0]
        wire = p['payload'][start:start+4]
        plain = struct.pack('<f', XP_THRESHOLDS[level-1])
        add_pairs(enc, zip(plain, wire))
        evidence.append(dict(level=level, assumed_experience=XP_THRESHOLDS[level-1],
                             encoded_hex=wire.hex(), reference=ref(p, start)))
    return enc, evidence


def leb(n):
    result = []
    while n >= 128:
        result.append((n & 127) | 128)
        n >>= 7
    return bytes(result+[n])


def walk_records(d, start, inv):
    """Only structural boundaries: skip values, do not use gameplay labels."""
    cursor, count = start, 0
    while cursor+10 <= len(d) and 0 < inv.get(d[cursor], 0) < 128 and d[cursor+4] == 0xdf:
        group_mask = inv[d[cursor]]
        after = cursor+5
        for group in (1, 2, 4, 8, 16, 32, 64):
            if group_mask & group:
                if after+5 > len(d) or d[after+4] not in inv:
                    return cursor, count
                after += 5+inv[d[after+4]]
        if after > len(d):
            return cursor, count
        cursor, count = after, count+1
    return cursor, count


def learn_lengths(rows, seed):
    """Learn outer vector length bytes from independently walked inner records.

    Uses only first 400 s of the full replay; late packets remain held out.
    A byte needs >= 2 structural witnesses and a unique bijective assignment.
    Conflicting hypotheses remain in the report, not silently counted as passes.
    """
    enc = dict(seed)
    rounds = []
    for iteration in range(5):
        inv = {v:k for k,v in enc.items()}
        pairs = {}
        contradictions = []
        for p in rows:
            if p['opcode'] != 0x3df or p['time'] >= 400:
                continue
            d = p['payload']
            candidates = []
            for h in (3,4,5):
                end, count = walk_records(d,h,inv)
                plain = leb(end-h)
                if count and 6 <= len(d)-end <= 8 and len(plain)==h-2:
                    candidates.append((h,end,plain))
            if len(candidates)!=1:
                continue
            h,end,plain = candidates[0]
            wire=d[2:h]
            if any((x in enc and enc[x]!=w) or (w in inv and inv[w]!=x) for x,w in zip(plain,wire)):
                contradictions.append(dict(reference=ref(p), plain_length_hex=plain.hex(), wire_length_hex=wire.hex()))
                continue
            for x,w in zip(plain,wire):
                bucket=pairs.setdefault(x,{}).setdefault(w,[])
                bucket.append(ref(p,2))
        additions={}
        witnesses={}
        # Reject ties; do not resolve a conflict by majority vote.
        for x, choices in pairs.items():
            if x in enc:
                continue
            eligible={w:refs for w,refs in choices.items() if len(refs)>=2}
            if len(eligible)==1:
                w,refs=next(iter(eligible.items()))
                if not any(other!=x and len(c.get(w,[]))>=2 for other,c in pairs.items()):
                    additions[x]=w
                    witnesses[x]=dict(wire=w,count=len(refs),examples=refs[:2],discarded_singletons={str(k):len(v) for k,v in choices.items() if k!=w})
        add_pairs(enc,additions.items())
        rounds.append(dict(iteration=iteration, added=len(additions), witnesses=witnesses,
                           contradictions=contradictions))
        if not additions:
            break
    return enc,rounds


def validate_envelopes(rows,enc):
    inv={v:k for k,v in enc.items()}
    counts=Counter()
    failures=[]
    for p in rows:
        if p['opcode']!=0x3df:
            continue
        region='heldout_after_400s' if p['time']>=400 else 'early'
        d=p['payload'];length=0;h=2
        for shift in range(0,35,7):
            if h>=len(d) or d[h] not in inv:
                counts[region+':unknown_length']+=1;break
            b=inv[d[h]];h+=1;length|=(b&127)<<shift
            if b<128:
                end=h+length
                actual,n=walk_records(d[:end],h,inv)
                counts[region+f':opaque_tail_length_{len(d)-end}']+=1
                if n and actual==end and end<=len(d):
                    counts[region+':exact_record_boundary']+=1
                else:
                    counts[region+':unresolved_structure']+=1
                    if len(failures)<15:failures.append(dict(reference=ref(p),start=h,declared_end=end,walked_end=actual,trailing_bytes=len(d)-end))
                break
        else:counts[region+':invalid_length']+=1
    return dict(counts=dict(counts),unresolved_examples=failures)


def fields(blob, mask, inv, group):
    """Maintain boundaries through unknown float bytes; never guess their value."""
    pos = 0
    values = []
    for bit in range(32):
        if not mask >> bit & 1:
            continue
        if group == 1 and bit > 1:
            return None  # Other economy fields have no established type here.
        start = pos
        if pos >= len(blob):
            return None
        if inv.get(blob[pos]) == 255:
            value = 0
            pos += 1
        elif group == 1 or bit in FLOAT_BITS:
            if inv.get(blob[pos]) == 254:
                pos += 1
            # The escape code is separately constrained by five-byte, one-field
            # records; other unknown bytes can retain a four-byte boundary.
            if pos+4 > len(blob):
                return None
            raw = blob[pos:pos+4]
            value = struct.unpack('<f', bytes(inv[b] for b in raw))[0] if all(b in inv for b in raw) else None
            pos += 4
        else:
            value = 0
            for shift in range(0, 35, 7):
                if pos >= len(blob) or blob[pos] not in inv:
                    return None
                b = inv[blob[pos]]
                pos += 1
                if shift == 28 and b > 15:
                    return None
                value |= (b & 127) << shift
                if b < 128:
                    break
            else:
                return None
        values.append(dict(bit=bit, value=value, wire_hex=blob[start:pos].hex(), data_offset=start))
    return values if pos == len(blob) else None


def scan(rows, ids, enc):
    inv = {v: k for k, v in enc.items()}
    output = []
    counters = Counter()
    for p in rows:
        if p['opcode'] != 0x3df:
            continue
        d = p['payload']
        for eid in ids:
            pattern = bytes((enc[eid], enc[0], enc[0], enc[64]))
            at = d.find(pattern, 1)
            while at >= 0:
                start = at-1
                group_mask = inv.get(d[start])
                if group_mask is not None and 0 < group_mask < 128:
                    cursor = at+4
                    groups = []
                    valid = True
                    for group in (1, 2, 4, 8, 16, 32, 64):
                        if not group_mask & group:
                            continue
                        if cursor+5 > len(d) or d[cursor+4] not in inv:
                            valid = False
                            break
                        length = inv[d[cursor+4]]
                        data_at = cursor+5
                        if data_at+length > len(d):
                            valid = False
                            break
                        mask_bytes = d[cursor:cursor+4]
                        mask = int.from_bytes(bytes(inv[b] for b in mask_bytes), 'little') if all(b in inv for b in mask_bytes) else None
                        blob = d[data_at:data_at+length]
                        decoded = fields(blob, mask, inv, group) if mask is not None and group in (1, 32) else None
                        groups.append(dict(group=group, field_mask=mask, mask_hex=mask_bytes.hex(),
                                           data_offset=data_at, data_hex=blob.hex(), fields=decoded))
                        cursor = data_at+length
                    if valid:
                        counters['bounded_records'] += 1
                        useful = [g for g in groups if g['fields'] is not None]
                        if useful:
                            counters['records_with_partial_fields'] += 1
                            output.append(dict(entity=hex(0x40000000|eid), group_mask=group_mask,
                                               reference=ref(p, start), end_offset=cursor, groups=useful))
                at = d.find(pattern, at+1)
    return output, dict(counters)


def compare(records, rows):
    values = [(r, g, f) for r in records for g in r['groups'] for f in g['fields']]
    zero = [(r, f) for r,g,f in values if g['group']==32 and f['bit']==0 and f['value']==0]
    entities = {int(r['entity'],16) for r in records}
    deaths = [p for p in rows if p['opcode']==0x28 and len(p['payload'])==5 and p['param'] in entities]
    matches = []
    for r,f in zero:
        near = [p for p in deaths if hex(p['param'])==r['entity'] and abs(p['time']-r['reference']['time'])<=.11]
        same = [p for p in deaths if hex(p['param'])==r['entity']]
        nearest = min(same, key=lambda p:abs(p['time']-r['reference']['time'])) if same else None
        matches.append(dict(entity=r['entity'], state_reference=r['reference'],
                            matching_death_references=[ref(p) for p in near],
                            nearest_death_reference=ref(nearest) if nearest else None,
                            delta_from_nearest_death=r['reference']['time']-nearest['time'] if nearest else None))
    return dict(field_value_counts=dict(Counter(f"{g['group']}:{f['bit']}:{'unknown' if f['value'] is None else 'numeric'}" for _,g,f in values)),
                zero_hp_candidates=len(zero), zero_death_comparisons=matches,
                zero_with_nearby_death=sum(bool(x['matching_death_references']) for x in matches),
                total_deaths=len(deaths))


def main():
    framer, _, _, refs = load_reviewed(ROOT.parent)
    inputs = {}
    for stem, expected in SOURCES.items():
        source = REPLAYS/(stem+'.rofl')
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected or raw[15:15+raw[14]]!=b'16.20.824.8524':
            raise ValueError('Unexpected replay identity or version')
        inputs[stem] = [p for p in framer.packets(source) if p['stream']==1]
    seed, training = train(inputs['HN1-11363048522'])
    enc, length_rounds = learn_lengths(inputs['HN1-11360086609'],seed)
    result = dict(schema='partial-state-byte-research/v1', version='16.20.824.8524',
                  status='PASS' if len(enc)==256 else 'INSUFFICIENT_EVIDENCE', sources=SOURCES, dependencies=refs,
                  scope='Byte-table recovery only; gameplay validation is in reports/replay_state_validation.json.',
                  limitation='The candidate scan below is exploratory. Production decoding walks declared vector boundaries in lol_coach/replay_state.py.',
                  corrected_hypothesis='An early guessed seed 28 -> 0x40 was rejected: the two 14-byte records at 18.750 s have length 28 encoded 0x31. Length learning recovers 24 -> 0x40 and 28 -> 0x31.',
                  structural_constraints=STRUCTURAL, identity_constraints=IDENTITIES,
                  xp_training_assumption='Practice level-up sets XP to the listed thresholds; thresholds borrowed as a hypothesis from cached 16.15 research, not verified 16.20 source.',
                  training=training, seed_table=seed, length_learning=length_rounds,
                  encoding_table_partial=enc, replays={})
    for stem, rows in inputs.items():
        records, counts = scan(rows, [174] if stem.endswith('48522') else range(52,62), enc)
        result['replays'][stem] = dict(counts=counts, envelope_validation=validate_envelopes(rows,enc), comparisons=compare(records,rows), records=records)
    target=ROOT/'data/research/state_byte_candidates.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    for stem in SOURCES:
        if hashlib.sha256((REPLAYS/(stem+'.rofl')).read_bytes()).hexdigest()!=SOURCES[stem]:
            raise ValueError('Input changed during research')
    print(json.dumps(dict(table_entries=len(enc), replays={k:dict(counts=v['counts'], comparisons={a:b for a,b in v['comparisons'].items() if a!='zero_death_comparisons'}) for k,v in result['replays'].items()}),ensure_ascii=False))


if __name__=='__main__':
    main()
