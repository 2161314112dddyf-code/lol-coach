"""Reproduce RPL-003 input/structure evidence; does not decode gameplay fields."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from export_replay_ten import load_reviewed
from lol_coach.replay_fields import read_metadata

REPLAYS = {
    '11360086609': 'c08c6f1a4a87f1670a6156c6badfca15a21aa13c74eaa18dff5efdc26b94e7e0',
    '11363048522': '1c17e0bb43b2629bf73972ddac9c53782abc1c2c32fca2d039c024e6c004aca3',
    '11363093470': 'f89bb444d046b7e6a9699e6dc83c06861d81e2a6d4c2b7585cc4e35cc9654238',
    '11372643015': '63722ae127363373452b24702a855a0f54de1da0be615e661c73c9cb23912f0b',
}
CLIENTS = {
    'windows': ('data/research/client_16.20.824.8524/League of Legends.exe',
                'f6fd49d6fb21c6cec23e329ca8a9a7c0809393cb950daf29ca62cf60a08455c6'),
    'macos': ('data/research/client_16.20.824.8524_mac/LeagueofLegends',
              'f0ff0944c204e51cce8df8493f8d769c82e0b0f70bae63fe90e074c30a973671'),
}


def checked_read(path, expected):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise ValueError(f'Input hash mismatch: {path.name}')
    return data, {'path': str(path.resolve()), 'sha256': digest, 'size': len(data)}


def pe_sections(data):
    pe = struct.unpack_from('<I', data, 60)[0]
    if data[:2] != b'MZ' or data[pe:pe+4] != b'PE\0\0':
        raise ValueError('Invalid PE input')
    count = struct.unpack_from('<H', data, pe+6)[0]
    optional = struct.unpack_from('<H', data, pe+20)[0]
    sections = []
    for index in range(count):
        at = pe+24+optional+index*40
        name = data[at:at+8].rstrip(b'\0').decode('ascii')
        virtual_size, rva, size, offset = struct.unpack_from('<IIII', data, at+8)
        body = data[offset:offset+size]
        if len(body) != size:
            raise ValueError('Truncated PE section')
        entropy = -sum((n/size)*math.log2(n/size) for n in Counter(body).values()) if size else None
        sections.append(dict(name=name,rva=rva,raw_offset=offset,raw_size=size,
                             virtual_size=virtual_size,entropy_bits_per_byte=entropy))
    return sections


def main():
    framer, _, _, refs = load_reviewed(ROOT.parent)
    sources = dict(refs)
    replays = []
    for game_id, digest in REPLAYS.items():
        path = Path('C:/Users/21613/Documents/League of Legends/Replays')/f'HN1-{game_id}.rofl'
        raw, ref = checked_read(path,digest);sources[path.name]=ref
        version, _, _ = read_metadata(raw)
        counts = Counter();selected = {}
        for packet in framer.packets(path):
            counts[f"stream_{packet['stream']}"] += 1
            if packet['opcode'] not in (0x3df,0x14,0x167,0x2a1,0x360,0x3cd,0x484):
                continue
            key = f"stream_{packet['stream']}:0x{packet['opcode']:04x}"
            entry = selected.setdefault(key,{'count':0,'first_examples':[]})
            entry['count'] += 1
            if len(entry['first_examples'])<2:
                entry['first_examples'].append({
                    **{k:packet[k] for k in ('time','stream','chunk','offset','channel')},
                    'outer_param':hex(packet['param']), 'payload_size':len(packet['payload']),
                    'payload_sha256':hashlib.sha256(packet['payload']).hexdigest(),
                    'semantic_status':'unassigned',
                })
        replays.append({'source':ref,'version':version,'packet_counts':dict(counts),
                        'research_opcodes_not_decoded_fields':selected})
    win, ref = checked_read(ROOT/CLIENTS['windows'][0],CLIENTS['windows'][1]);sources['windows_client']=ref
    mac, ref = checked_read(ROOT/CLIENTS['macos'][0],CLIENTS['macos'][1]);sources['mac_client']=ref
    # Only find literal names. Their presence proves neither a wire field nor compatibility.
    labels = {}
    for name in ('mHP','mMaxHP','mPAR','mMaxPAR','mGold','mGoldTotal','mVisionScore'):
        at = mac.find(name.encode()+b'\0')
        labels[name] = {'file_offset': at if at>=0 else None,'wire_field_index':None}
    experiments = {}
    for name in ('replication_length_1620.json','replication_synthesis_1620.json',
                 'replication_sbox_models.json','replication_sbox_search.json'):
        path=ROOT/'data/research'/name
        data=path.read_bytes();value=json.loads(data)
        experiments[name]={'path':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest(),
                          'conflicts':value.get('conflicts'),
                          'model_status_counts':dict(Counter(m.get('status','candidate') for m in value.get('models',[]))),
                          'accepted_gameplay_decoder':False}
    for ref in sources.values():
        checked_read(Path(ref['path']),ref['sha256'])
    report = {
        'task':'RPL-003','generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'target_build':'16.20.824.8524','sources':sources,'replays':replays,
        'windows_static_audit':{'sections':pe_sections(win),'PKT_string_occurrences':win.count(b'PKT_'),
                                'interpret_cli_result':'FAILED: Could not identify the common packet registration function',
                                'interpret_result_source':'Observed command output in this task; not rerun by this audit'},
        'mac_static_audit':{'field_labels':labels,'windows_wire_compatibility':'not_established',
                            'decoder_dispatched_at_0x3df_is_not_an_accepted_windows_decoder':True},
        'experiments':experiments,
        'coverage':{name:{'status':'INSUFFICIENT_EVIDENCE','accepted_dynamic_records':0,'value':None}
                    for name in ('health_and_resources','spell_casts','inventory_changes','gold_changes','vision')},
        'input_hashes_unchanged':True,'semantic_acceptance_passed':False,
        'independent_review_performed':False,'executed_game_binary':False,
        'note':'Opcode counts, static labels, cached clients and passing software tests are not decoded dynamic gameplay.',
    }
    output=ROOT/'reports/replay_dynamic_validation.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'input_hashes_unchanged':True,'replay_packets':[sum(r['packet_counts'].values()) for r in replays],
                      'coverage':report['coverage'],'report':str(output)},ensure_ascii=False))


if __name__=='__main__':main()
