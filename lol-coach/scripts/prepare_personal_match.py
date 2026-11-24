"""Prepare one player's ordered decision frames from the start through the last game second."""
import argparse
import math
from pathlib import Path

from lol_coach.coaching_checkpoints import select_coaching_checkpoints
from lol_coach.lane_opportunities import add_lane_candidates, attach_lane_change, lane_opportunities
from lol_coach.file_model_bridge import atomic_json
from lol_coach.hero_sight import native_vision_snapshot
from lol_coach.reasoning_frame import compile_frame
from lol_coach.replay_pings import build_ping_index
from lol_coach.replay_runes import attach_player_runes, read_replay_rune_pages
from lol_coach.review_subject import load_review_subject, validate_review_subject
from lol_coach.round_lane_evidence import attach_round_lanes
from lol_coach.team_coordination import COORDINATED_ACTION_PINGS, novel_team_signal, signal_point_at
from scripts.export_vision_channels import export
from scripts.reasoning import new_directory
from lol_coach.personal_episode import PersonalPathIndex, attach_personal_history, event_review_times, nearby_threat_observations
from lol_coach.hero_sight import reviewed_heroes
from lol_coach.native_kill_feed import FEED_ROOT
from lol_coach.reasoning_frame import digest
import json


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


def own_action_signals(events, actor, team, end):
    """Only actual, novel sends by the bound player can add a personal ping checkpoint."""
    history = {}
    selected = []
    for event in sorted(events, key=lambda row: row['time_seconds']):
        sent, kind = event['time_seconds'], event['kind']
        if (event.get('sender_entity_id') != actor or event.get('team_id') != team
                or kind not in COORDINATED_ACTION_PINGS or not event.get('source') or not 0 <= sent <= end):
            continue
        if novel_team_signal(history, actor, kind, sent, signal_point_at(event, sent)):
            selected.append(event)
    return selected


def add_signal_checkpoints(selections, signals, end):
    """An existing pause within the observation window can carry the new evidence."""
    by_time = {row['at']: dict(at=row['at'], selected_by=list(row['selected_by']),
                               triggers=list(row.get('triggers', []))) for row in selections}
    for event in signals:
        sent = event['time_seconds']
        due = min(math.ceil(sent) + 2, end)
        if event['kind'] == 'assist_me' and 'own_assist' in by_time.get(due, {}).get('selected_by', []):
            at = due
        else:
            at = min((t for t in by_time if sent <= t <= due), default=due)
        row = by_time.setdefault(at, dict(at=at, selected_by=[], triggers=[]))
        if 'own_action_signal' not in row['selected_by']:
            row['selected_by'] = sorted([*row['selected_by'], 'own_action_signal'])
        row['triggers'].append(dict(kind=event['kind'], sender_entity_id=event['sender_entity_id'],
                                    sent_at_seconds=sent, send_source=event['source']))
    return [by_time[t] for t in sorted(by_time)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', required=True, type=Path)
    parser.add_argument('--game-log', required=True, type=Path)
    parser.add_argument('--game-dir', type=Path)
    parser.add_argument('--interval', type=int, default=150, help='Seconds between regular decisions')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--at', type=float, nargs='+', help='Explicit increasing development clocks')
    parser.add_argument('--event-checkpoints', action='store_true',
                        help='Select coaching stops from personal signals, commands, sightings, public kills and local allied minions')
    parser.add_argument('--all-event-candidates', action='store_true',
                        help='With --event-checkpoints, prepare frames at every raw candidate for inspection')
    parser.add_argument('--schedule-only', action='store_true',help='Write candidate clocks without preparing model frames')
    args = parser.parse_args()
    if args.all_event_candidates and (not args.event_checkpoints or args.at is not None):
        parser.error('--all-event-candidates requires --event-checkpoints without --at')
    subject = load_review_subject(args.replay, args.game_log)
    raw = args.replay.read_bytes()
    index = export(raw, game_dir=args.game_dir)
    pings = build_ping_index(raw)
    rune_pages = read_replay_rune_pages(raw)
    if index['source_sha256'] != subject['replay_sha256'] or pings['source_sha256'] != index['source_sha256']:
        raise ValueError('inconsistent replay sources')
    team, player = subject['local_team_id'], subject['local_champion']
    path_index = PersonalPathIndex.from_replay(raw)
    actors = reviewed_heroes(index['source_sha256'])
    actor, = [hex(e) for e,h in actors.items() if h['team_id'] == team and h['name'] == player]
    signals = pings.get('events', [])
    if args.event_checkpoints:
        signals = own_action_signals(signals, actor, team, index['end_seconds'])
    selections = review_times(index['end_seconds'], args.interval, signals, player, team)
    if args.event_checkpoints:
        feed_path = FEED_ROOT/index['source_sha256']/'events.json'
        events = []
        if feed_path.exists():
            feed = json.loads(feed_path.read_bytes())
            if feed['source_sha256'] != index['source_sha256'] or feed['checksum'] != digest(
                    {k:v for k,v in feed.items() if k != 'checksum'}):
                raise ValueError('invalid public event index')
            events = feed['events']
        threats=nearby_threat_observations(path_index,index,actor,team,index['end_seconds'])
        selections = event_review_times(selections, path_index, actor, index['end_seconds'], events,nearby_events=threats)
        selections = add_signal_checkpoints(selections, signals, index['end_seconds'])
        if args.at is None:
            lane_changes = lane_opportunities(raw, path_index, team, actor, index['end_seconds'])
            selections = add_lane_candidates(selections, lane_changes)
    if args.at is not None:
        if (any(not math.isfinite(t) or not 0 <= t <= index['end_seconds'] for t in args.at)
                or any(a >= b for a,b in zip(args.at,args.at[1:]))):
            raise ValueError('development clocks must be finite, in the game and increasing')
        selections = [dict(at=t, selected_by=['explicit_development_clock']) for t in args.at]
    out = new_directory(args.output)
    metadata = dict(source_sha256=index['source_sha256'], player_entity_id=actor, team=team,
                    end_seconds=index['end_seconds'])
    coaching = None
    if args.event_checkpoints and args.at is None:
        coaching = select_coaching_checkpoints(selections)
        atomic_json(out/'selection.json', dict(**metadata, **coaching))
    if args.schedule_only:
        atomic_json(out/'schedule.json',dict(**metadata, selections=selections,
            meaning='Forward-only candidate clocks with source evidence; not verified round boundaries.'))
        result = dict(schedule=str(out/'schedule.json'), count=len(selections))
        if coaching is not None:
            result.update(selection=str(out/'selection.json'), selected_count=coaching['selected_count'])
        print(json.dumps(result), flush=True)
        return
    if coaching is not None and not args.all_event_candidates:
        selections = [dict(row, selection_reason=decision['selection_reason'], review_mode=decision['review_mode'])
                      for row, decision in zip(selections, coaching['rows']) if decision['selected']]
    for selection in selections:
        at = selection['at']
        snapshot = native_vision_snapshot(index, team, player, at)
        enemies = ['entity:' + hero['entity_id'] for hero in snapshot['heroes'] if hero['team_id'] != team]
        bundle = compile_frame(snapshot, vision_indexes=[index], vision_subjects=enemies, ping_index=pings)
        validate_review_subject(subject, bundle)
        bundle['audit']['verified_subject'] = subject
        bundle = attach_round_lanes(bundle, raw)
        bundle = attach_player_runes(bundle, rune_pages)
        bundle = attach_personal_history(bundle, path_index)
        if selection.get('triggers'):
            bundle = attach_lane_change(bundle, selection['triggers'])
        file = out / (str(at).replace('.', '_')+'.json')
        atomic_json(file, bundle)
        selection.update(bundle=file.name, frame_id=bundle['frame']['frame_id'])
        print(at, file.name, flush=True)
    atomic_json(out / 'sequence.json', dict(match=subject['match_id'], source_sha256=index['source_sha256'],
                team=team, champion=player, end_seconds=index['end_seconds'], interval=args.interval,
                ping_coverage=pings['status'], selections=selections,
                meaning='Selected game clocks are prompts to review, not verified macro round boundaries.'))


if __name__ == '__main__':
    main()
