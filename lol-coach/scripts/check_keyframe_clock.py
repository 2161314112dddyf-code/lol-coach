"""Test the whole-keyframe-delay hypothesis against independent live fields."""
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.replay_state import decode_payload, inverse_table
from export_replay_ten import load_reviewed, reference
from check_replay_semantics import read


def main():
    refs = {}
    source = Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    refs['replay'] = reference(source)
    state = read('data/private/replay_state/HN1-11360086609.json', refs)
    if state['source_sha256'] != refs['replay']['sha256']:
        raise ValueError('Source mismatch')
    framer, _, _, dependencies = load_reviewed(ROOT.parent)
    refs.update(dependencies)
    inverse = inverse_table()
    rows = []
    for p in framer.packets(source):
        if p['stream'] != 2 or p['opcode'] != 0x3df or p['time'] == 0:
            continue
        for record in decode_payload(p['payload'], inverse=inverse)['records']:
            if record['entity_id'] != 0x40000034:
                continue
            for group in record['groups']:
                for field in ('current_gold', 'health'):
                    if field not in group['fields']:
                        continue
                    value = group['fields'][field]['value']
                    comparisons = []
                    for shift in (0, 60):
                        observations = [e for e in state['updates'] if e['entity_id'] == hex(record['entity_id'])
                            and e['time_seconds'] <= p['time']-shift and field in e['values']]
                        prior = observations[-1] if observations else None
                        comparisons.append(dict(delay_hypothesis_seconds=shift, prior=prior,
                            status='INSUFFICIENT_EVIDENCE' if prior is None else
                            'PASS' if prior['values'][field] == value else 'FAIL'))
                    rows.append(dict(time_seconds=p['time'], field=field, value=value,
                        source=dict(stream=2, chunk=p['chunk'], decompressed_offset=p['offset'],
                            payload_hex=p['payload'].hex(), record_payload_offset=record['payload_offset']),
                        comparisons=comparisons))
    for ref in refs.values():
        if reference(Path(ref['path']))['sha256'] != ref['sha256']:
            raise ValueError('Input changed')
    summary = {shift: dict(Counter(c['status'] for r in rows for c in r['comparisons']
        if c['delay_hypothesis_seconds'] == shift)) for shift in (0, 60)}
    output = ROOT/'data/private/replay_semantics/keyframe_clock.json'
    output.write_text(json.dumps(dict(rows=rows, summary=summary, sources=refs,
        conclusion='An inventory mismatch does not justify shifting whole-keyframe time. Field-specific cache semantics remain unresolved.'), indent=2), encoding='utf8')
    print(json.dumps(dict(samples=len(rows), hypotheses=summary)))


if __name__ == '__main__':
    main()
