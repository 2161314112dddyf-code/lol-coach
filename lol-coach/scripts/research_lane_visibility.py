"""Audit the existing enter/leave byte forms against named lane entities.

This is an original-packet research export. It does not change the reviewed
hero visibility profile, label region fog, or turn health candidates into
accepted minion health semantics. Outputs must be new directories.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.replay_fields import read_metadata
from lol_coach.replay_vision import decode_payload, event_key, visibility_at
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def build(source, framer, dependencies):
    lane_path = ROOT/'data/private/replay_completion'/(source.stem+'-lane-identities.json')
    world_path = ROOT/'data/private/world_objects'/(source.stem+'.json')
    source_ref = reference(source)
    version, metadata, _ = read_metadata(source.read_bytes())
    lane = json.loads(lane_path.read_text(encoding='utf-8'))
    world = json.loads(world_path.read_text(encoding='utf-8'))
    if lane['source'] != source_ref or world['source_sha256'] != source_ref['sha256']:
        raise ValueError('Input source mismatch')
    if lane['version'] != version or world['version'] != version:
        raise ValueError('Input build mismatch')
    identities = {}
    for row in sorted(lane['events'], key=event_key):
        actor = row['entity_id']
        team = row['identity']['team_id']
        if actor in identities and identities[actor]['team_id'] != team:
            raise ValueError('Identity team conflict')
        identities.setdefault(actor, dict(team_id=team, lane=row['identity']['lane'],
            kind=row['identity']['kind'], first_identity_at=row['time_seconds'],
            first_identity_source=row['source']))
    events, rejected, terminal = [], [], defaultdict(list)
    all_counts = Counter()
    for index, packet in enumerate(framer.packets(source)):
        actor = hex(packet['param'])
        if packet['opcode'] in (0x484, 0x3cd):
            all_counts[str(packet['stream'])] += 1
        if actor not in identities:
            continue
        if packet['opcode'] in (0x167, 0x490) and packet['stream'] == 1:
            terminal[actor].append(dict(time_seconds=packet['time'], opcode=hex(packet['opcode'])))
        if packet['opcode'] not in (0x484, 0x3cd):
            continue
        row = dict(time_seconds=packet['time'], entity_id=actor,
            source=dict(stream=packet['stream'], chunk=packet['chunk'],
                decompressed_offset=packet['offset'], packet_index=index,
                opcode=hex(packet['opcode']), payload_hex=packet['payload'].hex(),
                payload_sha256=hashlib.sha256(packet['payload']).hexdigest()))
        try:
            decoded = decode_payload(packet['opcode'], packet['payload'], version=version)
        except ValueError as error:
            rejected.append(dict(**row, reason=str(error)))
            decoded = dict(observer_team_id=None, visible=None, kind='visibility_unknown_barrier')
        events.append(dict(**row, **decoded))
    live = sorted((e for e in events if e['source']['stream'] == 1), key=event_key)
    by_actor = defaultdict(list)
    previous = {}
    repeated = []
    same_team = []
    before_identity = []
    first_kinds = Counter()
    for event in live:
        actor = event['entity_id']; observer = event['observer_team_id']
        by_actor[actor].append(event)
        if observer == identities[actor]['team_id']:
            same_team.append(event)
        if event['time_seconds'] < identities[actor]['first_identity_at']:
            before_identity.append(event)
        key = actor, observer
        if key not in previous:
            first_kinds[event['kind']] += 1
        elif previous[key] is event['visible']:
            repeated.append(dict(previous_visible=previous[key], event=event))
        previous[key] = event['visible']
    health_by_actor = defaultdict(list)
    for row in world['candidate_health_samples']:
        if row['entity_id'] in identities:
            health_by_actor[row['entity_id']].append(row)
    sample_visibility = Counter()
    examples = []
    for actor, samples in health_by_actor.items():
        opposing_team = 300-identities[actor]['team_id']
        transition = by_actor[actor]
        timeline = [(event_key(e), 0, e) for e in transition if e['observer_team_id'] in (None, opposing_team)]
        timeline += [(event_key(s), 1, s) for s in samples]
        visible = None
        for _, kind, row in sorted(timeline, key=lambda x: (x[0], x[1])):
            if kind == 0:
                visible = row['visible']
            else:
                label = 'visible' if visible is True else 'hidden' if visible is False else 'unknown'
                sample_visibility[label] += 1
                if label != 'visible' and len(examples) < 8:
                    examples.append(dict(label=label, health_candidate=row,
                        observer_team_id=opposing_team))
    cutoff_rows = []
    duration = metadata['gameLength']/1000
    for t in (0, 30, 50, 283, 293, 300):
        if t > duration:
            continue
        for team in (100, 200):
            enemies = [e for e, identity in identities.items()
                       if identity['team_id'] != team and identity['first_identity_at'] <= t]
            state = visibility_at(live, t, team, enemies)
            cut = [e for e in live if e['time_seconds'] <= t]
            if state != visibility_at(cut, t, team, enemies):
                raise ValueError('Future visibility event affects prefix')
            counts = Counter('visible' if s['visible'] is True else 'hidden' if s['visible'] is False else 'unknown'
                             for s in state.values())
            cutoff_rows.append(dict(at=t, observer_team_id=team, identified_enemy_entities=len(enemies),
                transition_state_counts=dict(counts), prefix_check='PASS',
                caution='Includes historical entities; visibility state does not prove current existence or alive count'))
    first_enter = []
    own_enter_delays = []
    opposing_enter_delays = []
    own_channels = Counter()
    opposing_channels = Counter()
    leave_then_reenter = []
    leave_near_terminal = 0
    leave_without_terminal = 0
    for actor, rows in by_actor.items():
        enter = next((e for e in rows if e['visible'] is True), None)
        if enter:
            first_enter.append(enter['time_seconds']-identities[actor]['first_identity_at'])
        own = [e for e in rows if e['observer_team_id'] == identities[actor]['team_id']]
        opposing = [e for e in rows if e['observer_team_id'] == 300-identities[actor]['team_id']]
        own_channels.update(e['kind'] for e in own)
        opposing_channels.update(e['kind'] for e in opposing)
        if own:
            own_enter_delays.append(own[0]['time_seconds']-identities[actor]['first_identity_at'])
        if opposing:
            opposing_enter_delays.append(opposing[0]['time_seconds']-identities[actor]['first_identity_at'])
        for index, row in enumerate(opposing):
            if row['visible'] is False and index+1 < len(opposing) and opposing[index+1]['visible'] is True:
                leave_then_reenter.append(dict(entity_id=actor, leave=row, reentry=opposing[index+1],
                    interval_seconds=opposing[index+1]['time_seconds']-row['time_seconds']))
        for row in rows:
            if row['visible'] is not False:
                continue
            nearby = [e for e in terminal[actor] if abs(e['time_seconds']-row['time_seconds']) <= .15]
            if nearby: leave_near_terminal += 1
            else: leave_without_terminal += 1
    if reference(source) != source_ref:
        raise ValueError('Replay changed during research')
    summary = dict(replay=source.stem, lane_entities=len(identities), all_visibility_messages_by_stream=dict(all_counts),
        lane_visibility_messages=len(events), lane_visibility_streams=dict(Counter(str(e['source']['stream']) for e in events)),
        lane_entities_with_live_transition=len(by_actor), live_messages=len(live),
        enters=sum(e['visible'] is True for e in live), leaves=sum(e['visible'] is False for e in live),
        rejected=len(rejected), same_team_observer_messages=len(same_team), repeated_equal_transitions=len(repeated),
        before_identity_messages=len(before_identity), first_channel_events=dict(first_kinds),
        own_channel_kinds=dict(own_channels), opposing_channel_kinds=dict(opposing_channels),
        own_first_event_delay_range=None if not own_enter_delays else [min(own_enter_delays), max(own_enter_delays)],
        opposing_first_event_delay_range=None if not opposing_enter_delays else [min(opposing_enter_delays), max(opposing_enter_delays)],
        opposing_leave_then_reentry_intervals=len(leave_then_reenter),
        health_candidate_samples_by_opponent_visibility=dict(sample_visibility),
        leave_near_lifecycle_candidate=leave_near_terminal, leave_without_near_lifecycle_candidate=leave_without_terminal,
        first_enter_minus_first_identity_range=None if not first_enter else [min(first_enter), max(first_enter)])
    return dict(schema='lane-visibility-research/v1', task='RPL-010-LANE', source=source_ref,
        version=version, lane_input=reference(lane_path), world_input=reference(world_path),
        dependencies=dependencies, reused_visibility_profile=reference(ROOT/'lol_coach/profiles/vision_16_20.json'),
        identities=identities, events=events, rejected=rejected, summary=summary,
        same_team_events=same_team, repeated_transitions=repeated, before_identity=before_identity,
        leave_then_reentry=leave_then_reenter,
        health_hidden_or_unknown_examples=examples, cutoff_checks=cutoff_rows,
        accepted_channel_scope='Observed named lane entities; same exact byte forms as reviewed hero/tower channels; cross-field binary inference',
        tested_hypotheses=[dict(id='V1', claim='All observed minion visibility payloads use the reviewed two-byte forms',
                status='PASS' if not rejected else 'FAIL'),
            dict(id='V2', claim='Minion messages exist only for the opposing team, as in the old hero/tower scope',
                status='FAIL' if same_team else 'INSUFFICIENT_EVIDENCE', counterexamples=len(same_team)),
            dict(id='V3', claim='Each live entity/observer channel strictly alternates without same-state duplicates',
                status='PASS' if not repeated else 'FAIL'),
            dict(id='V4', claim='A leave message alone proves death/removal', status='FAIL' if leave_then_reenter else 'INSUFFICIENT_EVIDENCE',
                leave_then_reentry_counterexamples=len(leave_then_reenter))],
        independent_ui_validation=None, decision_input_eligible=False, complete_region_vision=False,
        limitations=['This audit does not itself accept dynamic health or path-start coordinates as current position',
            'No allied visibility assumption or initial hidden default is introduced',
            'No lifecycle event synthesizes a visibility transition; removed/dead entities need separate lifetime handling',
            'Static lane identity and team labels are existing cross-field inferences, not decoded model strings',
            'Unknown forms remain barriers, hidden samples cannot be made current by later reentry'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/private/lane_dynamics_visibility_attempt')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/'data/private').resolve()):
        raise ValueError('Research output must stay inside private data')
    output.mkdir(parents=True, exist_ok=False)
    framer, _, _, dependencies = load_reviewed(ROOT.parent)
    dependencies['research_lane_visibility.py'] = reference(Path(__file__))
    summaries = []
    for stem in STEMS:
        source = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        bundle = build(source, framer, dependencies)
        write_new(output/(stem+'.json'), bundle)
        summaries.append(bundle['summary'])
        print(json.dumps(bundle['summary']), flush=True)
    write_new(output/'summary.json', dict(task='RPL-010-LANE', rows=summaries,
        decision_input_eligible=False, independent_ui_validation=None,
        scope='Original packet audit, not whole-world fog or independently observed gameplay'))


if __name__ == '__main__':
    main()
