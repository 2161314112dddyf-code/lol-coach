"""Decode 0x322 from the four existing replays; preserve raw packet evidence."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.skill_ranks import decode_payload
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed, reference

STEMS = ('HN1-11360086609', 'HN1-11363048522', 'HN1-11363093470', 'HN1-11372643015')


def main():
    framer, _, _, refs = load_reviewed(ROOT.parent)
    refs['skill_ranks.py'] = reference(ROOT/'lol_coach/skill_ranks.py')
    refs['export_skill_ranks.py'] = reference(Path(__file__))
    directory = ROOT/'data/private/skill_ranks'
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for stem in STEMS:
        source = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        version, _, _ = read_metadata(raw)
        actors = ACTORS[digest]
        events, keyframes, unresolved = [], [], []
        for packet_index, p in enumerate(framer.packets(source)):
            if p['opcode'] != 0x322:
                continue
            base = dict(time_seconds=p['time'], entity_id=hex(p['param']),
                known_hero=p['param'] in actors,
                source=dict(stream=p['stream'], chunk=p['chunk'], packet_index=packet_index,
                    decompressed_offset=p['offset'], opcode='0x322',
                    payload_sha256=hashlib.sha256(p['payload']).hexdigest(), payload_hex=p['payload'].hex()))
            try:
                decoded = decode_payload(p['payload'], version=version)
            except ValueError as exc:
                unresolved.append(dict(**base, reason=str(exc)))
                continue
            row = dict(**base, **decoded)
            (events if p['stream'] == 1 else keyframes).append(row)
        if reference(source)['sha256'] != digest:
            raise ValueError('Input changed')
        bundle = dict(schema='replay-skill-ranks/v1', version=version, source_sha256=digest,
            events=events, keyframes=keyframes, unresolved=unresolved, dependencies=refs,
            evidence_level='binary_sequence_inference; no independent UI verification',
            decision_input_eligible=False,
            limitations=['Slot labels are allocation slots, not spell-name proof (especially Aphelios)',
                'Keyframes kept separately; update time and current unspent points not inferred from them',
                'No cast, cooldown, reset, target, visibility or buff decoding is implied'])
        (directory/(stem+'.json')).write_text(json.dumps(bundle, indent=2), encoding='utf8')
        results.append(dict(replay=stem, live=len(events), keyframes=len(keyframes),
            unknown_actor_live=sum(not e['known_hero'] for e in events), unresolved=len(unresolved),
            rank_counts=dict(Counter(e['rank'] for e in events+keyframes)),
            rejection_examples=unresolved[:4]))
    (ROOT/'reports/skill_ranks_counts.json').write_text(json.dumps(results, indent=2), encoding='utf8')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
