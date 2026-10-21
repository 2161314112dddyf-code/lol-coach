"""Byte repetition constraints only: these candidates are NOT decoded identities."""
import collections
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.export_replay_ten import load_reviewed, reference
from lol_coach.http import save_json


def shape(value):
    seen = {}
    return tuple(seen.setdefault(c, len(seen)) for c in value)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def main():
    source_refs = json.loads((ROOT/'reports/object_reference_materials.json').read_text())
    dictionary = collections.defaultdict(set)
    source_files = []
    for ref in source_refs:
        path = ROOT/'data/research/object_sources'/ref['evidence_path']
        source_files.append(reference(path))
        for text in strings(json.loads(path.read_bytes())):
            for token in re.findall(r'[A-Za-z0-9_]{5,55}', text):
                for word in {token, token.removeprefix('LevelProp_'), re.sub(r'\d+$', '', token.removeprefix('LevelProp_'))}:
                    if len(word) >= 5:
                        dictionary[shape(word)].add(word)
                        dictionary[shape(word.lower())].add(word.lower())
    replay = Path(r'C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl')
    framer, _, _, dependencies = load_reviewed(ROOT.parent)
    props = []
    scanned = []
    names = ['HA_ChaosMinionMelee', 'HA_OrderMinionMelee', 'HA_ChaosMinionRanged',
             'HA_OrderMinionRanged', 'HA_ChaosMinionSiege', 'HA_OrderMinionSiege',
             'HA_AP_HealthRelic', 'Turret_T1_C_01_A', 'Turret_T2_C_01_A']
    patterns = []
    for name in [n for word in names for n in (word, word[::-1])]:
        seen = {}; pattern = b''
        for c in name:
            if c in seen:
                pattern += b'\\' + str(seen[c]).encode()
            else:
                seen[c] = len(seen)+1
                pattern += b'(.)'
        patterns.append((name, re.compile(pattern, re.S)))
    for packet in framer.packets(replay):
        if packet['time'] > 55:
            continue
        payload = packet['payload']
        loc = {k: packet[k] for k in ('stream', 'chunk', 'offset', 'time', 'opcode', 'param')}
        if packet['opcode'] == 0x1d4:
            end = payload.find(b'\x5c\x24', 7)
            if end >= 7:
                wire = payload[7:end]
                props.append(dict(loc, payload_hex=payload.hex(), candidate_offset=7,
                                  wire_hex=wire.hex(), candidates=sorted(dictionary[shape(wire)])))
        for name, pattern in patterns:
            for match in pattern.finditer(payload):
                wire = match.group()
                if shape(wire) == shape(name):
                    scanned.append(dict(loc, payload_hex=payload.hex(), candidate_offset=match.start(),
                                        candidate_name=name, wire_hex=wire.hex()))
    result = {'schema':'object-name-pattern-research/v1', 'status':'INSUFFICIENT_EVIDENCE',
              'warning':'Pattern matches are hypotheses. No identity, map or team is asserted.',
              'replay':reference(replay), 'sources':source_refs, 'source_files':source_files,
              'decoder_dependencies':dependencies, 'scan_cutoff_seconds':55,
              'prop_candidates':props, 'long_name_candidates':scanned}
    save_json(ROOT/'data/private/world_objects/object_name_patterns.json',result)
    print(json.dumps({'prop_packets':len(props), 'props_with_candidates':sum(bool(p['candidates']) for p in props),
                      'long_name_matches':len(scanned), 'opcode_counts':collections.Counter(hex(p['opcode']) for p in scanned)}))


if __name__ == '__main__':
    main()
