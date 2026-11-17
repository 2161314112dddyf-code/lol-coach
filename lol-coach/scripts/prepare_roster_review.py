"""Prepare independently scoped player decisions from one reviewed replay and its verified roster."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json
from lol_coach.hero_sight import native_vision_snapshot
from lol_coach.reasoning_frame import canonical, compile_frame, digest
from lol_coach.replay_pings import build_ping_index
from lol_coach.round_chain import _check_bundle, _source
from lol_coach.round_camps import attach_personal_camps
from lol_coach.review_data_store import DEFAULT_ROOT
from lol_coach.review_external_context import bind_session_external_data
from lol_coach.review_subject import bottom_lane_actors, load_review_subject, roam_actors, validate_review_subject
from lol_coach.round_lane_evidence import attach_round_lanes
from lol_coach.round_tools import bind_round
from scripts.export_vision_channels import export


def apply_team_lane_observations(bundle, measured):
    """The lane/ally-path extractor depends on replay, cutoff, team and allied actor IDs."""
    target, donor = _check_bundle(bundle), _check_bundle(measured)
    def scope(frame):
        return (frame['decision']['build'], frame['decision']['at_seconds'], frame['decision']['observer_team_id'],
                sorted(h['entity_id'] for h in frame['lineup'] if h['relation'] == 'ally'))
    if _source(bundle) != _source(measured) or scope(target) != scope(donor):
        raise ValueError('lane measurement scope mismatch')
    for key in ('allied_path_fact_ids', 'lane_fact_ids'):
        target[key] = list(donor[key])
        for fid in target[key]:
            target['facts'][fid] = deepcopy(donor['facts'][fid])
            bundle['audit']['fact_sources'][fid] = deepcopy(measured['audit']['fact_sources'][fid])
    target['unknowns']['waves'] = donor['unknowns']['waves']
    from lol_coach.review_pings import attach_own_assist_path
    attach_own_assist_path(bundle)
    for note in donor['input_policy']:
        if note not in target['input_policy']:
            target['input_policy'].append(note)
    target.pop('frame_id')
    target['frame_id'] = 'frame_' + digest(target)[:24]
    bundle['audit']['frame_chars'] = len(canonical(target))
    return bundle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay', type=Path, required=True)
    p.add_argument('--game-log', type=Path, required=True)
    p.add_argument('--game-dir', type=Path)
    p.add_argument('--at', type=int, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--resume', action='store_true', help='verify and continue this exact sampling run')
    args = p.parse_args()
    if sorted(set(args.at)) != args.at:
        p.error('pass unique times in increasing order')
    subject = load_review_subject(args.replay, args.game_log)
    raw = args.replay.read_bytes()
    index = export(raw, game_dir=args.game_dir)
    ping_index = build_ping_index(raw)
    if index['source_sha256'] != subject['replay_sha256']:
        raise ValueError('replay source mismatch')
    if min(args.at) < 0 or max(args.at) > index['end_seconds']:
        raise ValueError('time outside replay')
    roster = subject['roster']
    roles = {'TOP': 'top', 'MIDDLE': 'mid', 'BOTTOM': 'bot', 'UTILITY': 'bot', 'JUNGLE': 'jungle'}
    if len(roster) != 10 or any({r['assigned_role'] for r in roster if r['team_id'] == side} != roles.keys()
                                for side in (100, 200)):
        raise ValueError('expected two verified sides with five assigned roles')
    root = args.output
    (root / 'frames').mkdir(parents=True, exist_ok=args.resume)
    header = dict(match_id=subject['match_id'], source_sha256=subject['replay_sha256'],
                  game_log_sha256=subject['log_sha256'], build=index['version'], roster=roster,
                  end_seconds=index['end_seconds'], times=args.at, local_champion=subject['local_champion'],
                  jungle_lane_comparison='camp opportunity and scoped clear clock', timing_scenario='dragon, help 5s',
                  ping_projection='scoped-sends-eight-smart-pings-v3', ping_window_seconds=30,
                  ping_hud_report_sha256=sorted({e['marker_report_sha256'] for e in ping_index['events']
                                                 if 'marker_report_sha256' in e}))
    if args.resume:
        if json.loads((root/'run.json').read_bytes()) != header:
            raise ValueError('existing audit parameters differ')
    else:
        atomic_json(root/'run.json', header)
    pinned = {}
    for at in args.at:
        measured = {}
        for player in roster:
            name, team, role = player['champion'], player['team_id'], player['assigned_role']
            path = root / 'frames' / name / str(at)
            if args.resume and (path/'bundle.json').is_file():
                previous = json.loads((path/'bundle.json').read_bytes())
                frame = _check_bundle(previous)
                if (_source(previous) != subject['replay_sha256'] or frame['decision']['at_seconds'] != at or
                        frame['task']['player_perspective']['champion'] != name or frame['decision']['observer_team_id'] != team):
                    raise ValueError('existing audit frame scope mismatch')
                pinned[name] = previous
                continue
            snap = native_vision_snapshot(index, team, name, at)
            enemies = ['entity:' + h['entity_id'] for h in snap['heroes'] if h['team_id'] != team]
            bundle = compile_frame(snap, vision_indexes=[index], vision_subjects=enemies, ping_index=ping_index)
            local = name == subject['local_champion'] and team == subject['local_team_id']
            if local:
                validate_review_subject(subject, bundle)
            if team in measured:
                bundle = apply_team_lane_observations(bundle, measured[team])
            else:
                bundle = measured[team] = attach_round_lanes(bundle, raw)
            duos = bottom_lane_actors(bundle['frame'], subject) if role == 'UTILITY' else None
            if role == 'JUNGLE':
                bundle = attach_personal_camps(bundle)
            origin = dict(match_id=subject['match_id'], replay_sha256=subject['replay_sha256'],
                          perspective='personal' if local else 'comparison')
            bundle = bind_round(bundle, roles[role], 'dragon', 5, macro_review=True, require_objective_credit=True,
                                review_origin=origin, bottom_lane_actors=duos,
                                roam_actors=roam_actors(bundle['frame'], subject) if duos else None)
            bundle, = bind_session_external_data([bundle], DEFAULT_ROOT,
                                                 cutoff=subject['match_information_cutoff_utc'], subject=subject,
                                                 previous=pinned.get(name))
            pinned[name] = bundle
            path.mkdir(parents=True, exist_ok=True)
            atomic_json(path/'bundle.json', bundle)
            print(at, team, name, flush=True)


if __name__ == '__main__':
    main()
