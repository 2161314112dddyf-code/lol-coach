"""Check raw replay provenance, every numeric field, and inventory subrecords."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from lol_coach.http import save_json
from lol_coach.inventory_sync import decode_sync
from lol_coach.replay_extensions import inventory_checkpoint, checkpoint_profile
from lol_coach.replay_state import decode_payload,inverse_table
from scripts.export_replay_ten import load_reviewed,reference
from scripts.verify_structure_evidence import STEMS


def key(p):return tuple(p[k] for k in ('stream','chunk','offset','opcode'))


def independent_number(raw,kind):
    if raw==b'\xff':return 0
    if kind=='float':return struct.unpack('<f',raw[1:] if raw[0]==254 else raw)[0]
    value=0
    for i,b in enumerate(raw):value|=(b&127)<<(7*i)
    assert not raw[-1]&128
    return value


def main():
    framer,_,_,_=load_reviewed(ROOT.parent);inv=inverse_table();profile=checkpoint_profile();reports=[]
    for stem in STEMS:
        path=ROOT/'data/private/remaining_decode'/f'{stem}.json'
        bundle=json.loads(path.read_text(encoding='utf8'));replay=Path(bundle['source']['path'])
        assert reference(replay)==bundle['source']
        packets={key(p):p for p in framer.packets(replay) if p['opcode'] in (0x3df,0x2ef)}
        items=0;fields=0;old_agree=0;decoded={}
        for event in bundle['inventory_checkpoints']:
            p=packets[key(event['source'])]
            assert p['time']==event['time_seconds'] and hex(p['param'])==event['entity_id']
            assert hashlib.sha256(p['payload']).hexdigest()==event['source']['payload_sha256']
            value=inventory_checkpoint(p['payload'],profile=profile)
            assert value['items']==event['items'] and value['effective_inventory_time'] is None
            assert not value['decision_input_eligible']
            for item in event['items']:
                if item['item_wire']:
                    at=item['identity_payload_offset'];assert p['payload'][at:at+2].hex()==item['item_wire']
                items+=1
            if p['stream']==1:
                old=decode_sync(p['payload'])
                assert [(i['slot'],i['item_wire']) for i in old['items']]==[(i['slot'],i['item_wire']) for i in value['items']]
                old_agree+=len(old['items'])
        for update in bundle['hero_attribute_groups']:
            k=key(update['source']);p=packets[k]
            assert p['time']==update['time_seconds']
            assert hashlib.sha256(p['payload']).hexdigest()==update['source']['payload_sha256']
            if k not in decoded:decoded[k]=decode_payload(p['payload'],inverse=inv)['records']
            record=next(r for r in decoded[k] if hex(r['entity_id'])==update['entity_id'])
            for field in update['fields']:
                g=next(g for g in record['groups'] if g['group']==field['group'])
                assert g['field_mask']&(1<<field['bit'])
                data=bytes.fromhex(g['decoded_data_hex']);raw=bytes.fromhex(field['decoded_hex'])
                at=field['decoded_payload_offset']-g['payload_offset']
                assert data[at:at+len(raw)]==raw
                assert independent_number(raw,field['encoding'])==field['value'];fields+=1
        assert not bundle['unresolved']
        assert reference(replay)==bundle['source']
        reports.append(dict(replay=stem,source=bundle['source'],item_records=items,numeric_fields=fields,
            previous_live_decoder_agreement=old_agree,source_unchanged=True))
    gaps=json.loads((ROOT/'reports/remaining_decode_gap_analysis.json').read_text(encoding='utf8'))
    # These are deliberately unresolved findings, not assertions weakened to pass.
    assert len(gaps['inventory_reconciliation']['mismatches'])==299
    result=dict(task='RPL-005',target_version='16.20.824.8524',executed_by='Codex',
        raw_reproduction='PASS',current_inventory_semantics='INSUFFICIENT_EVIDENCE',
        full_remaining_decoding='INSUFFICIENT_EVIDENCE',replays=reports,
        independent_review=None,human_signoff=None,
        limitation='Extraction checks do not resolve the 299 inventory semantic conflicts or two item-stat delta counterexamples')
    save_json(ROOT/'reports/remaining_decode_real_validation.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
