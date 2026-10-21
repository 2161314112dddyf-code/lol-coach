"""Batch existing replay extensions and targeted unresolved-field surveys offline."""
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from lol_coach.http import save_json
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_state import decode_payload, inverse_table
from lol_coach.replay_extensions import inventory_checkpoint, attribute_group, checkpoint_profile
from scripts.export_replay_state import ACTORS
from scripts.export_replay_ten import load_reviewed, reference
from scripts.verify_structure_evidence import STEMS


def source_packet(p):
    return dict(time_seconds=p['time'], entity_id=hex(p['param']),
        source={**{k:p[k] for k in ('stream','chunk','offset','opcode')},
            'payload_sha256':hashlib.sha256(p['payload']).hexdigest(), 'payload_hex':p['payload'].hex()})


def main():
    framer, _, _, dependencies = load_reviewed(ROOT.parent)
    inverse = inverse_table(); reports = []; map_signatures = []; profile = checkpoint_profile()
    for stem in STEMS:
        replay = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        ref = reference(replay); heroes = set(ACTORS[ref['sha256']])
        version, metadata, stats = read_metadata(replay.read_bytes())
        packets = sorted(framer.packets(replay), key=lambda p:(p['time'], 0 if p['stream']==2 else 1,p['chunk'],p['offset']))
        frames = []; attrs = []; errors = []; vision = collections.Counter(); last = {}
        spell_adjacent = []; opcode_counts = collections.Counter(); initial = collections.defaultdict(list)
        for order, p in enumerate(packets):
            opcode_counts[(p['stream'], p['opcode'])] += 1
            if p['time']==0 and p['param']==0 and len(p['payload'])<=16:
                initial[hex(p['opcode'])].append(p['payload'].hex())
            if p['opcode']==0x2ef and p['param'] in heroes:
                try: decoded = inventory_checkpoint(p['payload'], version=version, profile=profile)
                except ValueError as exc: errors.append(dict(**source_packet(p), category='inventory', reason=str(exc)))
                else: frames.append(dict(**source_packet(p), order=order, **decoded))
            if p['opcode']==0x3df:
                for record in decode_payload(p['payload'], version=version, inverse=inverse)['records']:
                    if record['entity_id'] not in heroes: continue
                    for group in record['groups']:
                        if group['group'] not in (4,8): continue
                        try: fields = attribute_group(group, version=version)
                        except ValueError as exc:
                            errors.append(dict(**source_packet(p), category='attributes', reason=str(exc)))
                        else:
                            attrs.append(dict(time_seconds=p['time'], entity_id=hex(record['entity_id']),
                                order=order, source={k:source_packet(p)['source'][k] for k in ('stream','chunk','offset','opcode','payload_sha256')}, fields=fields))
            if p['stream']==1 and p['opcode'] in (0x484,0x3cd) and p['param'] not in heroes:
                code=p['payload'].hex();key=(p['param'],code);direction='enter' if p['opcode']==0x484 else 'leave'
                vision[direction]+=1;vision['payload_'+code]+=1
                if last.get(key)==direction:vision['repeated_'+direction]+=1
                last[key]=direction
            if p['stream']==1 and p['opcode'] in (0x360,0x2a1) and p['param'] in heroes:
                spell_adjacent.append(source_packet(p))
        out = dict(schema='remaining-decode-observations/v1', source=ref, version=version,
            dependencies=dependencies, inventory_checkpoints=frames, hero_attribute_groups=attrs,
            unresolved=errors, decision_input_eligible=False,
            limitations=['Attribute semantics are candidates; numeric layout is distinct from nonhero layout',
                'Packet time is not effective inventory time: cached/rollback slots conflict with current-operation reconstruction',
                'Omitted slots remain unknown; no current inventory state is produced',
                'No enemy visibility/private-inventory policy applied; not a decision snapshot'])
        save_json(ROOT/'data/private/remaining_decode'/f'{stem}.json',out)
        # All unchanged final footer values below are research crosschecks only.
        final_fields=[{k:v for k,v in s.items() if k.startswith('SPELL') or k in ('SKIN','TEAM','MINIONS_KILLED','NEUTRAL_MINIONS_KILLED')} for s in stats]
        report=dict(replay=stem,source=ref,inventory_packets=len(frames),
            inventory_items=sum(len(x['items']) for x in frames),
            omitted_records=sum(len(x['omitted_records']) for x in frames),
            unknown_items=sum(i['item_id'] is None for x in frames for i in x['items']),
            attribute_groups=len(attrs),attribute_fields=sum(len(x['fields']) for x in attrs),
            errors=len(errors),nonhero_vision=dict(vision),
            spell_adjacent_packets=len(spell_adjacent),footer_spell_counts=final_fields,
            raw_opcode_counts={f'{s}:{hex(o)}':n for (s,o),n in sorted(opcode_counts.items())})
        save_json(ROOT/'data/private/remaining_decode'/f'{stem}-spell-survey.json',
            dict(source=ref,packets=spell_adjacent,semantic_status='research_only; cast/cooldown/target not decoded'))
        map_signatures.append(dict(replay=stem,initial_short_param0_packets=dict(initial),
            metadata_keys=sorted(metadata),runtime_map_id=None,runtime_mode=None))
        assert reference(replay)==ref
        reports.append(report)
        print(json.dumps({k:v for k,v in report.items() if k not in ('raw_opcode_counts','footer_spell_counts','nonhero_vision')},ensure_ascii=False),flush=True)
    save_json(ROOT/'reports/remaining_decode_collection.json',dict(task='RPL-005',replays=reports,
        map_probe=map_signatures,decision_input_eligible=False,signer=None))


if __name__=='__main__':main()
