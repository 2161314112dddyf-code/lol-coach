"""Publish a validated public-only subset from a continuous native replay audit."""
import argparse
from collections import Counter
import json
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json
from lol_coach.hero_sight import reviewed_heroes
from lol_coach.native_kill_feed import FEED_ROOT
from lol_coach.reasoning_frame import digest, number


def publish(path, root=FEED_ROOT):
    audit = json.loads(path.read_bytes())
    source = audit['source_sha256']
    roster = {h['name'] for h in reviewed_heroes(source).values()}
    checks = audit['checks']
    if not roster or set(checks) != roster or any(r['event_kda'] != r['footer_kda'] for r in checks.values()):
        raise ValueError('feed identities or final KDA mismatch')
    events = audit['events']
    if (not events or events[0]['EventName'] != 'GameStart' or events[-1]['EventName'] != 'GameEnd'
            or len({e['EventID'] for e in events}) != len(events)):
        raise ValueError('incomplete or duplicate event log')
    rows = []
    kills, deaths, assists = Counter(), Counter(), Counter()
    for e in events:
        if e['EventName'] != 'ChampionKill':
            continue
        if e['VictimName'] not in roster or e['KillerName'] is not None and e['KillerName'] not in roster:
            raise ValueError('unresolved public kill participant')
        t, available = e['EventTime'], e['first_observed_seconds']
        if not number(t) or not number(available) or t < 0 or available < 0 or t > available + .5:
            raise ValueError('inconsistent event and observation clocks')
        kills[e['KillerName']] += 1
        deaths[e['VictimName']] += 1
        assists.update(e['Assisters'])
        rows.append(dict(event_id=e['EventID'], time_seconds=t, available_at_seconds=max(t,available),
                         victim=e['VictimName'], killer=e['KillerName']))
    if any([kills[p],deaths[p],assists[p]] != checks[p]['footer_kda'] for p in roster):
        raise ValueError('event rows do not reproduce individual KDA')
    record = dict(schema='native-public-kills/v1', source_sha256=source, build=audit['client_build'], events=rows)
    record['checksum'] = digest(record)
    out = root / source / 'events.json'
    out.parent.mkdir(exist_ok=True,parents=True)
    if not out.exists() or json.loads(out.read_bytes()) != record:
        atomic_json(out, record)
    return out


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit',type=Path)
    parser.add_argument('--root',type=Path,default=FEED_ROOT)
    args=parser.parse_args()
    print(publish(args.audit,args.root))
