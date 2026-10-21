"""Replay the extraction and check packet, numeric and event-chain evidence."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import save_json
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_state import decode_payload, inverse_table
from lol_coach.structure_evidence import prefix_evidence
from scripts.export_replay_ten import load_reviewed, reference
from scripts.export_structure_evidence import build

STEMS = ['HN1-11360086609', 'HN1-11363048522', 'HN1-11363093470', 'HN1-11372643015']


def packet_key(p):
    return tuple(p[k] for k in ('stream', 'chunk', 'offset', 'opcode'))


def main():
    framer, _, _, _ = load_reviewed(ROOT.parent)
    inv = inverse_table(); reports = []
    for stem in STEMS:
        replay = Path('C:/Users/21613/Documents/League of Legends/Replays') / (stem+'.rofl')
        before = reference(replay)
        result = build(replay)
        assert len(result['discoveries']) == (6 if stem == STEMS[0] else 14)
        packets = {packet_key(p): p for p in framer.packets(replay) if p['opcode'] in (0x3df, 0x3f3)}
        fields_checked = 0
        for sample in result['health_samples']:
            p = packets[packet_key(sample['source'])]
            assert sample['time_seconds'] == p['time']
            assert hashlib.sha256(p['payload']).hexdigest() == sample['source']['payload_sha256']
            records = decode_payload(p['payload'], inverse=inv)['records']
            r = next(r for r in records if hex(r['entity_id']) == sample['entity_id'])
            g = next(g for g in r['groups'] if g['group'] == 4)
            data = bytes.fromhex(g['decoded_data_hex'])
            for field in sample['source']['fields']:
                assert g['field_mask'] & (1 << field['bit'])
                offset = field['decoded_payload_offset'] - g['payload_offset']
                segment = data[offset:offset+field['byte_length']]
                assert segment.hex() == field['decoded_hex']
                value = 0.0 if segment == b'\xff' else struct.unpack('<f', segment[1:] if segment[0] == 254 else segment)[0]
                assert value == sample['values'][field['field']]
                fields_checked += 1
        for event in result['state_observations']:
            p = packets[packet_key(event['source'])]
            assert p['payload'].hex() == event['state']['raw_hex']
            assert p['time'] == event['time_seconds'] and hex(p['param']) == event['entity_id']
        prefixes = 0
        for cutoff in (0, 50, 833.38, 840.3):
            state = prefix_evidence(result, cutoff)
            truncated = dict(result, **{k: [e for e in result[k] if e['time_seconds'] <= cutoff]
                for k in ('discoveries', 'health_samples', 'state_observations')})
            assert state == prefix_evidence(truncated, cutoff)
            assert state['decision_input_eligible'] is False
            assert all(x['identity'] is None and x['team'] is None for x in state['objects'].values())
            prefixes += 1
        transitions = [e for e in result['state_observations'] if e['state']['raw_hex'] == '9c']
        chains = []
        for event in transitions:
            following = [s for s in result['health_samples'] if s['entity_id'] == event['entity_id']
                         and s['order'] > event['order'] and 'health_candidate' in s['values']]
            assert following and following[0]['values']['health_candidate'] == 0
            checkpoints = [s for s in result['state_observations'] if s['entity_id'] == event['entity_id']
                and s['order'] > event['order'] and s['state']['raw_hex'] == '9d']
            assert checkpoints
            chains.append(dict(entity_id=event['entity_id'], transition_time=event['time_seconds'],
                first_zero_time=following[0]['time_seconds'], checkpoint_time=checkpoints[0]['time_seconds'],
                zero_delay_seconds=following[0]['time_seconds']-event['time_seconds']))
        _, _, stats = read_metadata(replay.read_bytes())
        total = sum(int(x['BARRACKS_KILLED']) for x in stats) if stats else None
        if total is not None:
            assert total == len(transitions)
        assert reference(replay) == before
        save_json(ROOT/'data/private/structure_evidence'/f'{stem}.json', result)
        if stem == STEMS[0]:
            for cutoff in (833.38, 833.45, 840.3):
                save_json(ROOT/'data/private/structure_evidence'/f'{stem}-at{cutoff}.json', prefix_evidence(result, cutoff))
        reports.append(dict(source=before, objects=len(result['discoveries']), health_samples=len(result['health_samples']),
            numeric_fields_checked=fields_checked, raw_states_checked=len(result['state_observations']),
            prefix_checks=prefixes, rejected=result['rejected'], transition_chains=chains,
            final_barracks_killed=total, source_unchanged=True))
    output = dict(task='RPL-004C', target_version='16.20.824.8524', executed_by='Codex',
        evidence_level='REPRODUCED', validation_scope='packet and correlation self-check, not independent UI verification',
        extraction_checks='PASS', full_identity_goal='INSUFFICIENT_EVIDENCE', replays=reports,
        signer=None, independent_review=None,
        limitations=['Inhibitor type remains event-family inference; team/lane/name unresolved',
            'No destroyed-to-respawn cycle in this sample; no timer inferred',
            'Nexus and minion identity decoders unresolved; no observer visibility'])
    save_json(ROOT/'reports/structure_evidence_real_validation.json', output)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
