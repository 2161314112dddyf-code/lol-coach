"""Export bounded target fields and retain every unsupported record."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.spell_targets import decode_target, DISCOVERY_SHA256, HERO_CODES, candidate_anchors
from lol_coach.spell_activity import decode_activity, load_profile
from lol_coach.replay_fields import read_metadata
from export_replay_ten import load_reviewed, reference
from check_replay_semantics import read


def main():
    refs = {}
    source = Path('C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl')
    refs['replay'] = reference(source)
    if refs['replay']['sha256'] != DISCOVERY_SHA256:
        raise ValueError('Unexpected replay')
    version, _, footer = read_metadata(source.read_bytes())
    teams = {hex(0x40000034+i): int(s['TEAM']) for i, s in enumerate(footer)}
    health = read('data/private/replay_state/HN1-11360086609.json', refs)
    if health['source_sha256'] != DISCOVERY_SHA256:
        raise ValueError('State mismatch')
    profile = load_profile()
    framer, _, _, deps = load_reviewed(ROOT.parent)
    refs.update(deps)
    for path in (Path(__file__), ROOT/'lol_coach/spell_targets.py', ROOT/'lol_coach/profiles/spell_activity_16_20.json'):
        refs[path.name] = reference(path)
    rows, checks, self_witnesses, damage_checks = [], [], [], []
    # A limited hypothesis set, not a complete champion targeting rule system.
    self_names = {'SummonerHaste', 'Meditate', 'WujuStyle', 'Highlander', 'FizzW', 'KarthusDefile', 'ApheliosW'}
    enemy_names = {'RyzeW', 'RyzeE', 'LeblancQ', 'VeigarR', 'FizzQ', 'AlphaStrike'}
    ally_names = {'KayleR', 'KayleW'}
    for p in framer.packets(source):
        if p['stream'] != 1 or p['opcode'] != 0x2a1 or hex(p['param']) not in teams:
            continue
        try:
            name = decode_activity(p['payload'], profile=profile)['spell_name']
        except ValueError:
            name = None
        decoded = decode_target(p['payload'], version=version, source_sha256=DISCOVERY_SHA256)
        row = dict(time_seconds=p['time'], entity_id=hex(p['param']), spell_name=name, **decoded,
            source=dict(stream=1, chunk=p['chunk'], decompressed_offset=p['offset'], opcode='0x2a1',
                payload_hex=p['payload'].hex(), payload_sha256=hashlib.sha256(p['payload']).hexdigest()))
        rows.append(row)
        target = row['target_entity']
        if target is None:
            continue
        if name in self_names:
            self_witnesses.append(dict(event=row, expected_self=row['entity_id'],
                status='PASS' if target == row['entity_id'] else 'FAIL'))
        if name in enemy_names | ally_names:
            relation = 'enemy' if name in enemy_names else 'ally'
            same_team = teams[target] == teams[row['entity_id']]
            checks.append(dict(event=row, expected_team_relation=relation,
                status='PASS' if same_team == (relation == 'ally') else 'FAIL'))
        if name in enemy_names:
            samples = [e for e in health['updates'] if e['entity_id'] == target and 'health' in e['values']]
            decreases = [(a,b) for a,b in zip(samples, samples[1:])
                if p['time'] <= b['time_seconds'] <= p['time']+0.8 and b['values']['health'] < a['values']['health']]
            damage_checks.append(dict(event=row, window_seconds=0.8,
                health_decreases=[dict(before=a, after=b) for a,b in decreases],
                status='PASS' if decreases else 'INSUFFICIENT_EVIDENCE',
                scope='Temporal corroboration only; damage attribution and success are not established'))
    for ref in refs.values():
        if reference(Path(ref['path']))['sha256'] != ref['sha256']:
            raise ValueError('Input changed')
    result = dict(schema='replay-explicit-targets/v1', version=version, source_sha256=DISCOVERY_SHA256,
        events=rows, self_witnesses=self_witnesses, team_checks=checks, health_correlations=damage_checks,
        sources=refs, decision_input_eligible=False,
        limitations=['Nine hero codes only, learned from this replay; no general target-ID codec',
            'No anchor != no target; implicit targets and helper effects not promoted',
            'Target selection != successful hit or distinct new cast',
            'Crosschecks are retrospective; later health and metadata are not online decision inputs'])
    output = ROOT/'data/private/replay_targets/HN1-11360086609.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(dict(records=len(rows), states=dict(Counter(r['status'] for r in rows)),
        self_checks=dict(Counter(r['status'] for r in self_witnesses)),
        self_actors=sorted({r['event']['entity_id'] for r in self_witnesses}),
        team_checks=dict(Counter(r['status'] for r in checks)),
        health_correlations=dict(Counter(r['status'] for r in damage_checks)))))


if __name__ == '__main__':
    main()
