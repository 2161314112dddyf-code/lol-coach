"""Reproduce the newly found item deltas directly from four original replays."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.compound_inventory import decode_inventory, unpack_array, ENCODING_TABLE
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS


def main():
    framer, _, _, dependencies = load_reviewed(ROOT.parent)
    out = ROOT/'data/private/replay_completion'
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    length_pairs = {}
    for stem in STEMS:
        source = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        ref = reference(source)
        version, _, _ = read_metadata(source.read_bytes())
        rows, rejected = [], []
        for p in framer.packets(source):
            if p['opcode'] != 0x37d:
                continue
            base = dict(time_seconds=p['time'], entity_id=hex(p['param']),
                source=dict(stream=p['stream'], chunk=p['chunk'],
                    decompressed_offset=p['offset'], opcode='0x37d',
                    payload_hex=p['payload'].hex(),
                    payload_sha256=hashlib.sha256(p['payload']).hexdigest()))
            try:
                decoded = decode_inventory(p['payload'], version=version)
            except ValueError as exc:
                rejected.append(dict(**base, reason=str(exc)))
                continue
            rows.append(dict(**base, **decoded))
            # Independent size labels: the declared array ends at EOF or
            # before the observed 13-byte outer coordinate-shaped field.
            n = len(p['payload'])-decoded['data_start']-len(bytes.fromhex(decoded['outer_tail_hex']))
            plain = []
            while n >= 128:
                plain.append((n & 127)|128)
                n >>= 7
            plain.append(n)
            for a,b in zip(plain,p['payload'][1:decoded['data_start']]):
                if length_pairs.get(a,b) != b:
                    raise ValueError('Conflicting byte-length evidence')
                length_pairs[a] = b
        if reference(source)['sha256'] != ref['sha256']:
            raise ValueError('Source changed')
        result = dict(schema='compound-inventory-deltas/v1', version=version,
            source=ref, events=rows, rejected=rejected, dependencies=dependencies,
            decision_input_eligible=False,
            limitations=['Unlisted slots are unchanged/unknown, never implicitly empty',
                'Charge counters have item-specific meaning',
                'No exact earlier use time is recovered from keyframe deltas',
                'The rest of compound state is retained without semantic labels'])
        (out/(stem+'-compound-inventory.json')).write_text(json.dumps(result,indent=2),encoding='utf8')
        summaries.append(dict(replay=stem,packets=len(rows),rejected=len(rejected),
            item_deltas=sum(len(r['items']) for r in rows),
            streams=dict(Counter(r['source']['stream'] for r in rows)),
            rejection_examples=rejected[:2]))
    # This finite model class can be exhaustively checked, unlike the wider
    # SMT templates. Equality here is a model result, not client source proof.
    unique = set()
    for a in range(256):
        for b in range(256):
            x = next(iter(length_pairs))
            c = (length_pairs[x]-(((x+a)&255)^b))&255
            if all((((((x+a)&255)^b)+c)&255)==y for x,y in length_pairs.items()):
                unique.add(bytes(((((x+a)&255)^b)+c)&255 for x in range(256)))
    result = dict(summaries=summaries, length_pairs=length_pairs,
        byte_model='encode(x) = (((x+40) mod 256) XOR 41) + 225 mod 256',
        distinct_tables_in_add_xor_add_class=len(unique),
        selected_table_is_in_finite_models=ENCODING_TABLE in unique,
        known_bad=['Ignoring the 13-byte suffix produced false length conflicts',
                  'Treating all item records as 33 bytes fails on Tear/Rod stat maps',
                  'Treating the slot delta list as a complete snapshot erases unchanged items'],
        four_target_completion=False)
    (out/'compound_inventory_run.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
