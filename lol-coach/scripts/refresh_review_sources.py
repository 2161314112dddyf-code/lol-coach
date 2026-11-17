"""Pull public Riot and Tencent data into a local, versioned review source directory."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import time

from lol_coach.review_data_store import DEFAULT_ROOT, refresh_sources
from lol_coach.http import EvidenceClient
from lol_coach.review_subject import _log_roster
from lol_coach.riot_review_data import current_riot_version


def roster_scope(log_bytes):
    roster, (local_team, _, _), roles = _log_roster(log_bytes)
    by_role = defaultdict(list)
    for team, champion in roster:
        role = roles.get((team, champion))
        if role:
            by_role[team, role].append(champion)
    matchups = []
    missing = []
    for lane in ('TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY'):
        own, opponents = by_role[local_team, lane], by_role[300-local_team, lane]
        if len(own) == len(opponents) == 1:
            matchups.append((lane, own[0], opponents[0]))
        else:
            missing.append(lane)
    return sorted({champion for _, champion in roster}), matchups, missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--version', help='exact Riot release or current; with --replay the default resolves its historical patch')
    roster_input = parser.add_mutually_exclusive_group(required=True)
    roster_input.add_argument('--champions', nargs='+', help='Riot champion identifiers')
    roster_input.add_argument('--game-log', type=Path, help='derive participants and role pairs from a game-start log; current tracks this roster, independently of the game build')
    roster_input.add_argument('--replay', type=Path, help='derive the roster and combat build from a local ROFL')
    parser.add_argument('--matchup', nargs=3, action='append', default=[], metavar=('LANE', 'ALLY', 'OPPONENT'))
    parser.add_argument('--lane-profiles', action='store_true', help='also fetch versioned lane profiles for participants in each matched role')
    parser.add_argument('--combat-build', help='also store rune and item data plus reviewed rules for this exact game build')
    parser.add_argument('--game-dir', type=Path, help='archive verified original game assets for --combat-build')
    parser.add_argument('--max-age-hours', type=float, default=6, help='reuse a complete recent update')
    parser.add_argument('--force', action='store_true', help='revalidate against both upstreams immediately')
    parser.add_argument('--interval-minutes', type=float, help='keep polling until stopped (minimum 1 minute)')
    parser.add_argument('--stop-file', type=Path, help='end polling when this file exists')
    args = parser.parse_args()
    if args.interval_minutes is not None and not 1 <= args.interval_minutes <= 525600:
        parser.error('--interval-minutes must be in [1,525600]')
    if args.stop_file and args.interval_minutes is None:
        parser.error('--stop-file requires --interval-minutes')
    if not 0 <= args.max_age_hours <= 8760:
        parser.error('--max-age-hours must be in [0,8760]')
    if args.game_log and args.matchup:
        parser.error('--game-log derives its own lane pairs; use --champions with explicitly selected matchups')
    if not args.version and not args.replay:
        parser.error('supply --version or a local --replay')
    champions, matchups, missing = args.champions, args.matchup, []
    if args.replay:
        from lol_coach.replay_runes import read_replay_rune_pages
        try:
            index = read_replay_rune_pages(args.replay.read_bytes())
            if args.combat_build and args.combat_build != index['build']:
                parser.error('--combat-build differs from the replay')
            args.combat_build = index['build']
            roster = [row['champion'] for row in index['rows']]
            if not roster or any(not isinstance(name, str) or not name.strip() for name in roster):
                parser.error('replay roster has missing champion identifiers')
            champions = sorted(set(roster))
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.game_log:
        try:
            champions, matchups, missing = roster_scope(args.game_log.read_bytes())
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
    while True:
        if args.stop_file and args.stop_file.exists():
            print(json.dumps(dict(status='polling_stopped')), flush=True)
            return 0
        try:
            client = EvidenceClient(args.root / 'evidence')
            if args.replay and args.version in (None, 'current'):
                resolution = current_riot_version(client, patch='.'.join(args.combat_build.split('.')[:2]))
            else:
                resolution = current_riot_version(client) if args.version == 'current' else None
            version = resolution['version'] if resolution else args.version
            result = refresh_sources(args.root, version, champions, matchups, include_profiles=args.lane_profiles,
                                     max_age_hours=args.max_age_hours, force=args.force, client=client,
                                     combat_build=args.combat_build, game_dir=args.game_dir)
            if args.game_log:
                result['roster_scope'] = dict(champions=champions, matchups=matchups, unpaired_roles=missing)
            if resolution:
                result['version_resolution'] = resolution
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except (ValueError, OSError) as exc:
            print(json.dumps(dict(status='refresh_failed', error=str(exc)), ensure_ascii=False),
                  file=sys.stderr, flush=True)
            if args.interval_minutes is None:
                return 1
        if args.interval_minutes is None:
            return 0
        if not args.stop_file:
            time.sleep(args.interval_minutes * 60)
            continue
        wake_at = time.monotonic() + args.interval_minutes * 60
        while not args.stop_file.exists() and (remaining := wake_at - time.monotonic()) > 0:
            time.sleep(min(remaining, 10))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
