"""Read activity-slot bytes from original ROFLs; retain helper/unknown slots."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.spell_slots import decode_slot
from lol_coach.spell_activity import decode_activity, load_profile
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS
from verify_world_collection import SPELL_GROUPS


def main():
    framer, _, _, refs = load_reviewed(ROOT.parent)
    profile = load_profile()
    refs['spell_slots.py'] = reference(ROOT/'lol_coach/spell_slots.py')
    refs['spell_activity_profile'] = reference(ROOT/'lol_coach/profiles/spell_activity_16_20.json')
    labels = {name: slot for groups in SPELL_GROUPS for slot, names in enumerate(groups) for name in names}
    directory = ROOT/'data/private/spell_slots'
    directory.mkdir(parents=True, exist_ok=True)
    summaries = []
    for stem in STEMS:
        source = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        digest = reference(source)['sha256']
        version, _, footer = read_metadata(source.read_bytes())
        actors = ACTORS[digest]
        rows, rejected, checks, summoner_checks = [], [], [], []
        for p in framer.packets(source):
            if p['stream'] != 1 or p['opcode'] != 0x2a1 or p['param'] not in actors:
                continue
            base = dict(time_seconds=p['time'], entity_id=hex(p['param']),
                source=dict(stream=1, chunk=p['chunk'], decompressed_offset=p['offset'], opcode='0x2a1',
                    payload_hex=p['payload'].hex(), payload_sha256=hashlib.sha256(p['payload']).hexdigest()))
            try:
                slot = decode_slot(p['payload'], version=version)
            except ValueError as exc:
                rejected.append(dict(**base, reason=str(exc)))
                continue
            try:
                named = decode_activity(p['payload'], version=version, profile=profile)
                name = named['spell_name']
            except ValueError:
                name = None
            row = dict(**base, **slot, spell_name=name)
            rows.append(row)
            if stem == STEMS[0] and name in labels:
                checks.append(dict(event=row, expected_slot_from_name=labels[name],
                    status='PASS' if slot['slot'] == labels[name] else 'FAIL'))
            # Cross-check IDs in the same replay footer, not a model's choice
            # of which summoner the player "probably" bound to each key.
            summoner_ids = {'SummonerFlash': 4, 'SummonerHaste': 6,
                            'SummonerDot': 14, 'SummonerSnowball': 32}
            if stem == STEMS[0] and name in summoner_ids and slot['slot'] in (4, 5):
                stat = footer[actors.index(p['param'])]
                configured_id = int(stat['SUMMONER_SPELL_'+str(slot['slot']-3)])
                summoner_checks.append(dict(event=row, configured_id=configured_id,
                    expected_id=summoner_ids[name],
                    status='PASS' if configured_id == summoner_ids[name] else 'FAIL'))
        if reference(source)['sha256'] != digest:
            raise ValueError('Input changed')
        aggregates = []
        if stem == STEMS[0]:
            for actor, stat in zip(actors, footer):
                for slot_index in range(4):
                    count = sum(e['entity_id'] == hex(actor) and e['slot'] == slot_index for e in rows)
                    expected = int(stat[f'SPELL{slot_index+1}_CAST'])
                    aggregates.append(dict(entity_id=hex(actor), slot=slot_index,
                        observed_activity_count=count, footer_cast_count=expected,
                        status='PASS' if count == expected else 'FAIL'))
        bundle = dict(schema='replay-activity-slots/v1', version=version, source_sha256=digest,
            events=rows, rejected=rejected, name_crosschecks=checks,
            summoner_config_crosschecks=summoner_checks, dependencies=refs,
            retrospective_footer_comparisons=aggregates,
            evidence_level='cross_hero_name_and_header_correlation', decision_input_eligible=False,
            limitations=['Activity != independent cast; recast/helper phases are retained',
                'Unknown variable slot bytes remain raw; no arbitrary slot numbers assigned',
                'No target, cooldown or cancellation semantics established',
                'Summoner slot order is a corpus inference; names come from separate hash decoder'])
        (directory/(stem+'.json')).write_text(json.dumps(bundle, indent=2), encoding='utf8')
        summaries.append(dict(replay=stem, parsed=len(rows), rejected=len(rejected),
            slots=dict(Counter(e['slot_label'] or 'unknown_internal' for e in rows)),
            crosschecks=dict(Counter(e['status'] for e in checks)),
            summoner_crosschecks=dict(Counter(e['status'] for e in summoner_checks)),
            footer_comparisons=dict(Counter(e['status'] for e in aggregates)),
            rejection_examples=rejected[:3]))
    (ROOT/'reports/spell_slots_counts.json').write_text(json.dumps(summaries, indent=2), encoding='utf8')
    print(json.dumps(summaries))


if __name__ == '__main__':
    main()
