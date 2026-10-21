"""Export structural layout/state evidence without inventing building identities."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import save_json
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_state import decode_payload, inverse_table
from lol_coach.structure_evidence import is_initial_layout, health_candidates, state_observation, prefix_evidence
from scripts.export_replay_ten import load_reviewed, reference


def build(replay):
    source = reference(replay)
    version, _, _ = read_metadata(replay.read_bytes())
    framer, _, _, deps = load_reviewed(ROOT.parent)
    packets = sorted(framer.packets(replay), key=lambda p:
        (p['time'], 0 if p['stream'] == 2 else 1, p['chunk'], p['offset']))
    identities = {}; discoveries = []; samples = []; states = []; rejected = []
    inverse = inverse_table()
    for order, p in enumerate(packets):
        if p['opcode'] not in (0x3df, 0x3f3):
            continue
        ref = {k: p[k] for k in ('stream', 'chunk', 'offset', 'opcode')}
        ref['payload_sha256'] = hashlib.sha256(p['payload']).hexdigest()
        base = dict(time_seconds=p['time'], order=order, source=ref)
        if p['opcode'] == 0x3f3:
            try:
                state = state_observation(p['payload'], version=version)
            except ValueError as exc:
                rejected.append(dict(**base, entity_id=hex(p['param']), reason=str(exc)))
            else:
                states.append(dict(**base, entity_id=hex(p['param']), state=state,
                    type_hypothesis='inhibitor', identity=None, team=None,
                    interpretation='event-family inference, not decoded object name'))
            continue
        for record in decode_payload(p['payload'], version=version, inverse=inverse)['records']:
            actor = record['entity_id']
            if actor not in identities and p['time'] == 0 and is_initial_layout(record):
                event = dict(**base, entity_id=hex(actor), identity=None, team=None,
                    initial_layout={str(g['group']): g['field_mask'] for g in record['groups']})
                identities[actor] = event; discoveries.append(event)
            if actor not in identities:
                continue
            values, fields = health_candidates(record, version=version)
            if values:
                samples.append(dict(time_seconds=p['time'], order=order, entity_id=hex(actor),
                    values=values, source=dict(ref, fields=fields)))
    if reference(replay) != source:
        raise ValueError('Replay changed during export')
    return dict(schema='structure-evidence/v1', version=version, source=source,
        decoder_dependencies=deps, discoveries=discoveries, health_samples=samples,
        state_observations=states, rejected=rejected, decision_input_eligible=False,
        limitations=['Initial layout selects structural candidates, not names or teams',
            'State labels are exact-build correlations, not authoritative enum meanings',
            'No observer visibility, respawn timer, lane, runtime position or map ID decoded',
            'No future identity backfill; no global minion/Nexus identity decoder'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--at', type=float)
    args = parser.parse_args()
    if args.output.resolve() == args.replay.resolve():
        raise ValueError('Cannot overwrite input replay')
    bundle = build(args.replay)
    if args.at is not None:
        bundle = prefix_evidence(bundle, args.at)
    save_json(args.output, bundle)
    print(str(args.output))


if __name__ == '__main__':
    main()
