"""Only the time, killer and victim from locally observed public champion-kill notifications."""
import json
from pathlib import Path

from .reasoning_frame import digest, number

FEED_ROOT = Path(__file__).resolve().parents[1] / 'data/private/public_kill_feed'


def project_feed(record, source, build, roster, at, window=30):
    if (record.get('schema'), record.get('source_sha256'), record.get('build')) != (
            'native-public-kills/v1', source, build):
        raise ValueError('native kill feed source mismatch')
    if digest({k:v for k,v in record.items() if k != 'checksum'}) != record.get('checksum'):
        raise ValueError('native kill feed checksum mismatch')
    ids = {h['name']:hex(e) for e,h in roster.items()}
    feed, evidence = [], {}
    for event in record['events']:
        t, seen = event['time_seconds'], event['available_at_seconds']
        if not number(t) or not number(seen) or not 0 <= t <= seen:
            raise ValueError('invalid native kill timestamp')
        if not at-window <= t <= seen <= at:
            continue
        key = f"native-public-kill/{source}/{event['event_id']}"
        feed.append(dict(evidence_id=key, time_seconds=t, available_at_seconds=seen,
                         victim_entity_id=ids[event['victim']], killer_entity_id=ids.get(event['killer'])))
        evidence[key] = dict(time_seconds=t, available_at_seconds=seen, source={})
    return feed, evidence


def load_feed(index, roster, at, root=FEED_ROOT):
    source = index['source_sha256']
    if not roster:
        return None, {}
    path = root / source / 'events.json'
    if not path.is_file():
        return None, {}
    return project_feed(json.loads(path.read_bytes()), source, index['version'], roster, at)
