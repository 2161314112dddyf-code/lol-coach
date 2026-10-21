"""Export observed item identities from exact-build game-stream resyncs."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.inventory_sync import decode_sync
from lol_coach.replay_fields import read_metadata
from export_replay_state import ACTORS
from export_replay_ten import load_reviewed


def main():
    framer, _, _, refs = load_reviewed(ROOT.parent)
    reports = []
    output = ROOT/'data/private/inventory_sync'
    output.mkdir(exist_ok=True)
    for stem in ('HN1-11360086609', 'HN1-11363048522', 'HN1-11363093470', 'HN1-11372643015'):
        source = Path('C:/Users/21613/Documents/League of Legends/Replays')/(stem+'.rofl')
        raw = source.read_bytes();digest = hashlib.sha256(raw).hexdigest()
        version, _, _ = read_metadata(raw)
        if digest not in ACTORS:
            raise ValueError('Unverified replay')
        events, unresolved = [], []
        for p in framer.packets(source):
            if p['stream'] != 1 or p['opcode'] != 0x2ef or p['param'] not in ACTORS[digest]:
                continue
            base = dict(time_seconds=p['time'], entity_id=hex(p['param']),
                source=dict(stream=1, chunk=p['chunk'], decompressed_offset=p['offset'], opcode='0x2ef',
                            payload_sha256=hashlib.sha256(p['payload']).hexdigest(), payload_hex=p['payload'].hex()))
            try:
                decoded = decode_sync(p['payload'], version=version)
            except ValueError as exc:
                unresolved.append({**base, 'reason': str(exc)})
                continue
            events.append({**base, **decoded})
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        bundle = dict(schema='inventory-sync-observations/v1', version=version, source_sha256=digest,
            events=events, unresolved=unresolved, dependencies=refs,
            scope='Self/retrospective observed slots only; no enemy knowledge policy here',
            complete_inventory_state=False, decision_input_eligible=False,
            limitations=['Missing slots are unknown', 'Count/price/modifiers unresolved',
                         'Only fixed record wrappers and observed envelopes; no keyframe future fill'])
        (output/(stem+'.json')).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf8')
        reports.append(dict(replay=stem, events=len(events), items=sum(len(e['items']) for e in events),
            unknown_items=sum(i['item_id'] is None for e in events for i in e['items']), unresolved=len(unresolved)))
    (ROOT/'reports/inventory_sync_counts.json').write_text(json.dumps(reports, indent=2), encoding='utf8')
    print(json.dumps(reports))


if __name__ == '__main__':
    main()
