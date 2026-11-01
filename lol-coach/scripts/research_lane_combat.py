"""Finite exact-build lane combat/reference study on the four supplied ROFLs.

All source files are read-only and the movement/framing reader stays frozen.
Reference bytes, health decreases and proximity are separate observations;
neither a temporally adjacent message nor a reference proves an attack landed.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_replay_ten import load_reviewed, reference
from export_skill_ranks import STEMS
from lol_coach.replay_fields import read_metadata
from lol_coach.lane_combat import decode_health_loss, load_profile, PROFILE

VERSION = '16.20.824.8524'


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def leb(number):
    result = []
    while number >= 128:
        result.append((number & 127) | 128)
        number >>= 7
    return bytes(result+[number])


def extract(output):
    framer, _, _, deps = load_reviewed(ROOT.parent)
    results = []
    for stem in STEMS:
        evidence_path = ROOT/'data/private/lane_dynamics_run_20261028'/stem/'evidence.json'
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        source = Path(evidence['source']['path'])
        source_ref = reference(source)
        version, _, _ = read_metadata(source.read_bytes())
        if version != VERSION or source_ref != evidence['source']:
            raise ValueError('Evidence/replay build or source mismatch')
        lanes = {r['entity_id']: r for r in evidence['identities']}
        records, known, counts = [], {}, Counter()
        for index, packet in enumerate(framer.packets(source)):
            actor = hex(packet['param'])
            if packet['param'] >> 30 in (1, 2):
                known.setdefault(actor, dict(first_packet_time=packet['time'],
                    first_packet_stream=packet['stream']))
            is_lane = actor in lanes
            if is_lane:
                counts[(packet['stream'], hex(packet['opcode']))] += 1
            if packet['opcode'] == 0x167 or is_lane and packet['opcode'] in (0xe, 0x229, 0x27c):
                records.append(dict(entity_id=actor, time_seconds=packet['time'],
                    source=dict(stream=packet['stream'], chunk=packet['chunk'],
                        decompressed_offset=packet['offset'], packet_index=index,
                        opcode=hex(packet['opcode']),
                        payload_sha256=hashlib.sha256(packet['payload']).hexdigest()),
                    payload_hex=packet['payload'].hex(), named_lane_actor=is_lane))
        if reference(source) != source_ref:
            raise ValueError('Input replay changed')
        result = dict(schema='lane-combat-raw-study/v1', version=version,
            source=source_ref, evidence_source=reference(evidence_path), dependencies=deps,
            lane_identities=list(lanes.values()), known_outer_entity_ids=known, records=records,
            lane_opcode_counts=[dict(stream=s, opcode=o, count=n)
                for (s, o), n in sorted(counts.items())])
        write_new(output/(stem+'-raw.json'), result)
        results.append(dict(replay=stem, selected_records=len(records),
                            known_outer_entities=len(known)))
        print(json.dumps(results[-1]), flush=True)
    write_new(output/'extraction_receipt.json', dict(task='RPL-011-WAVE',
        script=reference(Path(__file__)), replays=results, dependencies=deps,
        semantics='Raw evidence extraction only; no attack or damage attribution'))


def key(row):
    source = row['source']
    return row['time_seconds'], source['chunk'], source['decompressed_offset']


def analyze(raw_directory, output):
    profile = load_profile()
    dependencies = {p.name: reference(p) for p in
        (Path(__file__), ROOT/'lol_coach/lane_combat.py', PROFILE)}
    summaries = []
    for stem in STEMS:
        raw_path = raw_directory/(stem+'-raw.json')
        raw = json.loads(raw_path.read_text(encoding='utf-8'))
        evidence_path = Path(raw['evidence_source']['path'])
        if reference(evidence_path) != raw['evidence_source']:
            raise ValueError('Original dynamic evidence changed')
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        events, rejected = [], []
        for row in raw['records']:
            if not row['named_lane_actor'] or row['source']['opcode'] != '0x167':
                continue
            try:
                decoded = decode_health_loss(bytes.fromhex(row['payload_hex']),
                    entity_id=row['entity_id'], version=raw['version'], profile=profile)
            except ValueError as exc:
                rejected.append(dict(row, reason=str(exc)))
                continue
            events.append(dict(entity_id=row['entity_id'], time_seconds=row['time_seconds'],
                               source=row['source'], **decoded))
        health, components = defaultdict(list), defaultdict(list)
        for event in evidence['events']:
            if (event['source']['stream'] == 1 and event['kind'] == 'health_sample'
                    and 'health' in event['values']):
                health[event['entity_id']].append(event)
        for event in events:
            if event['source']['stream'] == 1:
                components[event['entity_id']].append(event)
        checks, counts = [], Counter()
        for actor, samples in health.items():
            samples.sort(key=key)
            for before, after in zip(samples, samples[1:]):
                difference = before['values']['health']-after['values']['health']
                if difference <= 0:
                    continue
                received = [r for r in components[actor] if key(before) < key(r) <= key(after)]
                terminal = after['values']['health'] == 0
                label = 'zero_after' if terminal else 'positive_after'
                counts[label+'_health_drop_intervals'] += 1
                if received:
                    counts[label+'_with_components'] += 1
                total = sum(r['value'] for r in received)
                error = abs(difference-total)
                exact = bool(received) and error <= 0.01
                counts[label+'_sum_equals_net_drop_within_0_01'] += exact
                overkill = bool(received) and total+0.01 >= difference
                if terminal:
                    counts['zero_after_components_cover_net_drop'] += overkill
                    counts['zero_after_sum_exceeds_remaining_hp'] += total > difference+0.01
                checks.append(dict(entity_id=actor, before=before, after=after,
                    net_health_drop=difference, components=received, component_sum=total,
                    absolute_sum_error=error, positive_health_after=not terminal,
                    exact_net_match=exact, components_cover_zero_after_drop=overkill if terminal else None,
                    semantics='Net HP comparison is a retrospective crosscheck; not attacker attribution'))
        summary = dict(replay=stem, **counts,
            event_counts_by_stream=dict(Counter(str(e['source']['stream']) for e in events)),
            rejected_records=len(rejected), source_reference_decoder='unresolved',
            training_split=('scalar seed magnitudes' if stem == 'HN1-11363093470' else
                '205 integer-difference refinement witnesses; remaining intervals validation' if stem == 'HN1-11360086609' else
                'replay held out from scalar table fitting'))
        folder = output/stem
        folder.mkdir()
        result = dict(schema='lane-combat-evidence/v1', version=raw['version'],
            source=raw['source'], recording_end_seconds=evidence['recording_end_seconds'],
            dependencies=dict(dependencies, raw_extraction=reference(raw_path),
                              dynamic_evidence=raw['evidence_source']),
            events=events, rejected=rejected, summary=summary,
            decision_input_eligible=False,
            limitations=['Per-event observed components need at-t identity and explicit visibility filtering',
                'Multiple components do not equal multiple attacks or successful casts',
                'Positive components may exceed remaining HP; do not infer exact death time',
                'Optional middle fields and attacker/source identity remain unresolved',
                'Observed byte crosschecks are not independent gameplay/video truth'])
        write_new(folder/'evidence.json', result)
        write_new(folder/'health_interval_checks.json', dict(source=raw['source'], summary=summary, checks=checks))
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    for ref in dependencies.values():
        if reference(Path(ref['path'])) != ref:
            raise ValueError('Analysis dependency changed')
    write_new(output/'analysis_receipt.json', dict(task='RPL-011-WAVE', summaries=summaries,
        dependencies=dependencies,
        method='Three candidate scalar magnitudes followed by integer-difference refinement; validate sums against consecutive HP samples',
        unresolved=['Optional middle/source-reference fields', 'Specific attack or skill attribution',
                    'One rejected scalar-layout counterexample', 'No independent video truth'],
        precision_correction='Initial decimal8.49612 seed produced UNSAT; binary float candidate8.496119499206543 retained after held-out HP balance',
        parameter_search_scope='Bounded arithmetic/rotation/swap templates; seed-only alternative functions remain possible'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT/'data/private/lane_combat_attempt_20261028')
    parser.add_argument('--raw-input', type=Path,
                        help='Reuse an existing four-replay extraction; write analysis to a new output')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/'data/private').resolve()):
        parser.error('Output must be a new directory under data/private')
    output.mkdir(parents=True, exist_ok=False)
    if args.raw_input is None:
        extract(output)
        analyzed = output/'analysis'
        analyzed.mkdir()
        analyze(output, analyzed)
    else:
        analyze(args.raw_input.resolve(), output)


if __name__ == '__main__':
    main()
