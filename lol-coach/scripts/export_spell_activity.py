"""Export real spell-name activities, separately from independent cast counts."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.spell_activity import decode_activity, load_profile
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed


def main():
    framer, _, _, refs = load_reviewed(ROOT.parent)
    profile = load_profile()
    directory = ROOT/'data/private/spell_activity';directory.mkdir(exist_ok=True)
    results = []
    for stem in ('HN1-11360086609', 'HN1-11363048522', 'HN1-11363093470', 'HN1-11372643015'):
        source = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        raw = source.read_bytes();digest = hashlib.sha256(raw).hexdigest()
        version, _, _ = read_metadata(raw)
        actors = ACTORS[digest]
        events, unresolved = [], []
        for p in framer.packets(source):
            if p['stream'] != 1 or p['opcode'] != 0x2a1 or p['param'] not in actors: continue
            base = dict(time_seconds=p['time'], entity_id=hex(p['param']),
                source=dict(stream=1, chunk=p['chunk'], decompressed_offset=p['offset'], opcode='0x2a1',
                    payload_sha256=hashlib.sha256(p['payload']).hexdigest(), payload_hex=p['payload'].hex()))
            try: decoded = decode_activity(p['payload'], version=version, profile=profile)
            except ValueError as exc: unresolved.append(dict(**base, reason=str(exc)));continue
            events.append(dict(**base, **decoded))
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest: raise ValueError('Input changed')
        bundle = dict(schema='spell-activity-observations/v1', version=version, source_sha256=digest,
            events=events, unresolved=unresolved, dependencies=refs,
            profile_sha256=hashlib.sha256((ROOT/'lol_coach/profiles/spell_activity_16_20.json').read_bytes()).hexdigest(),
            decision_input_eligible=False, independent_cast_count=None,
            limitations=['Activity != new cast; stages/helpers retained separately',
                'Incomplete vocabulary/envelopes; no event is not proof of no cast',
                'Actor is packet outer entity; target/rank/cooldown unknown',
                'Retrospective evidence; visibility of the spell itself is not validated'])
        (directory/(stem+'.json')).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf8')
        results.append(dict(replay=stem, named_activities=len(events), unresolved=len(unresolved),
            names=dict(Counter(e['spell_name'] for e in events)), roles=dict(Counter(e['role_hint'] for e in events))))
    (ROOT/'reports/spell_activity_counts.json').write_text(json.dumps(results, indent=2), encoding='utf8')
    print(json.dumps(results))


if __name__ == '__main__': main()
