"""Read new structural constraints and retain failed object-ID hypotheses."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.spell_state_fields import decode_fields
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS
from check_replay_semantics import read


def bijection_probe(pairs, transform):
    maps = [dict() for _ in range(4)]
    inverses = [dict() for _ in range(4)]
    conflicts = []
    for row in pairs:
        plain = transform(row['entity_id']).to_bytes(4, 'little')
        wire = bytes.fromhex(row['wire_hex'])
        for position, (a,b) in enumerate(zip(plain, wire)):
            if a in maps[position] and maps[position][a] != b or b in inverses[position] and inverses[position][b] != a:
                conflicts.append(dict(pair=row, byte_position=position,
                    plain_byte=a, wire_byte=b, prior_wire=maps[position].get(a), prior_plain=inverses[position].get(b)))
            else:
                maps[position][a] = b
                inverses[position][b] = a
    return dict(conflicts=conflicts, learned_pairs=[len(m) for m in maps],
                status='FAIL' if conflicts else 'INSUFFICIENT_EVIDENCE')


def main():
    refs = {}
    framer, _, _, deps = load_reviewed(ROOT.parent)
    refs.update(deps)
    refs['state_decoder'] = reference(ROOT/'lol_coach/spell_state_fields.py')
    refs['research_script'] = reference(Path(__file__))
    directory = ROOT/'data/private/replay_targets'
    directory.mkdir(parents=True, exist_ok=True)
    summaries = []
    for stem in STEMS:
        source = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        refs[stem] = reference(source)
        version, _, _ = read_metadata(source.read_bytes())
        rows, rejected = [], []
        for p in framer.packets(source):
            if p['opcode'] != 0x43e:
                continue
            base = dict(time_seconds=p['time'], entity_id=hex(p['param']),
                source=dict(stream=p['stream'], chunk=p['chunk'], decompressed_offset=p['offset'],
                    opcode='0x43e', payload_hex=p['payload'].hex(),
                    payload_sha256=hashlib.sha256(p['payload']).hexdigest()))
            try:
                decoded = decode_fields(p['payload'], version=version)
            except ValueError as exc:
                rejected.append(dict(**base, reason=str(exc)))
                continue
            rows.append(dict(**base, **decoded))
        (directory/(stem+'-state-fields.json')).write_text(json.dumps(dict(
            schema='replay-spell-state-structure/v1', version=version, source=refs[stem],
            events=rows, rejected=rejected, decision_input_eligible=False,
            limitation='No numeric value, cooldown or readiness claim. Unknown slots remain raw.'), indent=2), encoding='utf8')
        summaries.append(dict(replay=stem, bounded=len(rows), rejected=len(rejected),
            streams=dict(Counter(r['source']['stream'] for r in rows)), examples=rejected[:3]))
    # New hypotheses examine cross-byte carries and compact network-ID base.
    # The 38 birth associations are candidates, not independently identified
    # objects. Failure can falsify the representation or the association.
    pairs_doc = read('data/private/world_objects/spawn_id_models16.json', refs)
    pairs = pairs_doc['training_pairs']+pairs_doc['heldout_pairs']
    hypotheses = {}
    for shift in range(4):
        for offset in (0, 1, -1):
            key = f'base_removed_left_shift_{shift}_offset_{offset}'
            hypotheses[key] = bijection_probe(pairs,
                lambda value, shift=shift, offset=offset: (((value-0x40000000)<<shift)+offset)&0xffffffff)
    for ref in refs.values():
        if reference(Path(ref['path']))['sha256'] != ref['sha256']:
            raise ValueError('Input changed')
    result = dict(structure=summaries, spawn_probes=hypotheses, sources=refs,
        failures=['Initial three-selector length model had no solution; bit 1, not bit 0, controls the second numeric field',
                  'Initial live-only envelope gate rejected 501 keyframe packets; bit 0 varies in keyframes and is now preserved as an uninterpreted flag',
                  'z3 unavailable; length constraints solved with standard-library enumeration; no dependency installed'],
        accepted_creation_id_decoder=False, accepted_cooldown_decoder=False)
    (directory/'structure_and_spawn.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(dict(structure=summaries, spawn_probe_counts={k:len(v['conflicts']) for k,v in hypotheses.items()})))


if __name__ == '__main__':
    main()
