"""Prepare one player's ordered decision frames from the start through the last game second."""
import argparse
import math
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json
from lol_coach.hero_sight import native_vision_snapshot
from lol_coach.reasoning_frame import compile_frame
from lol_coach.replay_pings import build_ping_index
from lol_coach.replay_runes import attach_player_runes, read_replay_rune_pages
from lol_coach.review_subject import load_review_subject, validate_review_subject
from lol_coach.round_lane_evidence import attach_round_lanes
from scripts.export_vision_channels import export
from scripts.reasoning import new_directory


def review_times(end, interval, events, player, team):
    """Regular coverage with two reassessments after each personal call for assistance."""
    if not math.isfinite(end) or end < 0 or interval < 1:
        raise ValueError('invalid review interval or game duration')
    last = math.floor(end)
    times = {at: {'regular'} for at in range(0, last + 1, interval)}
    times.setdefault(last, set()).add('last_game_second')
    for event in events:
        if (event['sender_champion'], event['team_id'], event['kind']) != (player, team, 'assist_me'):
            continue
        sent = event['time_seconds']
        for delay, reason in [(2, 'own_assist'), (17, 'follow_up_own_assist')]:
            at = math.ceil(sent) + delay
            if at <= last:
                times.setdefault(at, set()).add(reason)
    selected = []
    for at, reasons in sorted(times.items()):
        if selected and reasons == {'regular'} and at - selected[-1]['at'] <= 5:
            continue
        selected.append(dict(at=at, selected_by=sorted(reasons)))
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', required=True, type=Path)
    parser.add_argument('--game-log', required=True, type=Path)
    parser.add_argument('--game-dir', type=Path)
    parser.add_argument('--interval', type=int, default=150, help='Seconds between regular decisions')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    subject = load_review_subject(args.replay, args.game_log)
    raw = args.replay.read_bytes()
    index = export(raw, game_dir=args.game_dir)
    pings = build_ping_index(raw)
    rune_pages = read_replay_rune_pages(raw)
    if index['source_sha256'] != subject['replay_sha256'] or pings['source_sha256'] != index['source_sha256']:
        raise ValueError('inconsistent replay sources')
    team, player = subject['local_team_id'], subject['local_champion']
    selections = review_times(index['end_seconds'], args.interval, pings.get('events', []), player, team)
    out = new_directory(args.output)
    for selection in selections:
        at = selection['at']
        snapshot = native_vision_snapshot(index, team, player, at)
        enemies = ['entity:' + hero['entity_id'] for hero in snapshot['heroes'] if hero['team_id'] != team]
        bundle = compile_frame(snapshot, vision_indexes=[index], vision_subjects=enemies, ping_index=pings)
        validate_review_subject(subject, bundle)
        bundle['audit']['verified_subject'] = subject
        bundle = attach_round_lanes(bundle, raw)
        bundle = attach_player_runes(bundle, rune_pages)
        file = out / f'{at:05}.json'
        atomic_json(file, bundle)
        selection.update(bundle=file.name, frame_id=bundle['frame']['frame_id'])
        print(at, file.name, flush=True)
    atomic_json(out / 'sequence.json', dict(match=subject['match_id'], source_sha256=index['source_sha256'],
                team=team, champion=player, end_seconds=index['end_seconds'], interval=args.interval,
                ping_coverage=pings['status'], selections=selections,
                meaning='Selected game clocks are prompts to review, not verified macro round boundaries.'))


if __name__ == '__main__':
    main()
