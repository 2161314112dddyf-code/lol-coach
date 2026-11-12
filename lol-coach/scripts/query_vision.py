"""Query what one team could see at a time or at timed stops along a route."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lol_coach.region_vision import channel_intervals, checked_indexes, visibility_query
from lol_coach.region_vision import valid_time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay', type=Path, help='Read reviewed visibility channels directly from a ROFL')
    p.add_argument('--evidence', action='append', default=[], type=Path, help='Optional matching local evidence file')
    p.add_argument('--team', type=int, choices=(100, 200), required=True)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument('--subject', help='Exact ground: or entity: identifier')
    target.add_argument('--route', type=Path, help='JSON array of {subject, at_seconds} samples')
    target.add_argument('--world', type=float, nargs=2, action='append', metavar=('X', 'Z'),
                        help='Query a ground coordinate, with native ward contributions where bound')
    p.add_argument('--game-dir', type=Path, help='Matching installed Game directory, for --world')
    p.add_argument('--render-manifest', type=Path, help='Optional matching native fog-on/off frames for --world')
    p.add_argument('--minion-max-age', type=float, default=1.0,
                   help='Maximum age in seconds of a candidate allied minion location when reading --replay')
    p.add_argument('--at', type=float, help='Game seconds for --subject')
    p.add_argument('--interval', type=float, nargs=2, metavar=('START', 'END'),
                   help='Return time inside/outside the recorded channel for this subject')
    args = p.parse_args()
    indexes = []
    raw = None
    if args.replay:
        from scripts.export_vision_channels import export
        raw = args.replay.read_bytes()
        indexes.append(export(raw, game_dir=args.game_dir))
    indexes.extend(json.loads(path.read_bytes()) for path in args.evidence)
    checked_indexes(indexes)
    if args.world:
        from lol_coach.movement_1622 import PANTHEON, MAP11_REPLAYS, lane_minion_positions_at
        from lol_coach.ward_coverage import load_terrain, ward_contributions, nearby_minion_sources
        from lol_coach.faelights_1622 import faelight_query
        if args.game_dir is None or args.interval is not None or not valid_time(args.at):
            p.error('--world needs --game-dir and a single nonnegative --at')
        index = next((i for i in indexes if 'ward_placements' in i), None)
        if index is None:
            p.error('--world needs a ROFL or its native spatial index')
        if args.at > index['end_seconds'] or index['source_sha256'] not in MAP11_REPLAYS:
            p.error('Time or replay outside the reviewed 16.22 Map11 registration')
        grids, overlays = load_terrain(args.game_dir, index['version'])
        if not valid_time(args.minion_max_age):
            p.error('Minion sample age must be finite and nonnegative')
        minions = lane_minion_positions_at(raw, args.at) if raw is not None else None
        renderer = None
        if args.render_manifest:
            from scripts.query_rendered_ground import load_pair, sample_render
            renderer = load_pair(args.render_manifest, args.at)
            if renderer[2]['replay_sha256'] != index['source_sha256'] or renderer[2]['build'] != index['version']:
                p.error('Native ground captures belong to another replay or build')
        reviewed = index['source_sha256'] == PANTHEON
        wards = index['ward_placements']
        points = []
        # Only link an exact, physically matched resting position to its named
        # probe. The corroborated camp is not a disk of inferred visibility.
        camp = {(2112, 8450): 'blue-side-gromp-camp', (12678, 6430): 'red-side-gromp-camp'}
        for target_xz in args.world:
            point = ward_contributions(wards, args.team, args.at, target_xz, grids, overlays)
            bonuses = index.get('faelight_intervals')
            point['faelight'] = (faelight_query(bonuses, args.team, args.at, target_xz) if bonuses is not None
                                 else {'estimated_visible':None,'basis':'spatial_bonus_not_exported'})
            point['minion_coverage'] = (nearby_minion_sources(minions, args.team, target_xz, grids, overlays,
                                       args.minion_max_age) if minions is not None else None)
            name = camp.get(tuple(target_xz)) if reviewed else None
            if name:
                answer = visibility_query(indexes, args.team, 'ground:'+name, args.at)
                point['ground_evidence'] = answer
                point['observed_team_ground_visibility'] = answer['visible']
            if renderer:
                images, pose, manifest, hashes = renderer
                point['spectator_render'] = dict(**sample_render(images, pose, grids[0], *target_xz),
                    perspective=manifest['perspective'], team_attribution=None, png_sha256=hashes)
            points.append(point)
        result = dict(points=points, own_placements_seen_by_cutoff=sum(
                          w['team_id'] == args.team and w['start_seconds'] <= args.at for w in wards),
                      grids=[g.summary['raw_sha256'] for g in grids],
                      coverage_basis='Ordinary ward contribution estimated from native positions and terrain; '
                          'other sources, runtime effects and unobserved ground may change team visibility.')
    elif args.subject:
        if (args.at is None) == (args.interval is None):
            p.error('--subject requires either --at or --interval')
        if args.interval is not None:
            result = channel_intervals(indexes, args.team, args.subject, *args.interval)
        else:
            result = visibility_query(indexes, args.team, args.subject, args.at)
    else:
        if args.at is not None or args.interval is not None:
            p.error('Route samples each specify their game time')
        stops = json.loads(args.route.read_bytes())
        if not isinstance(stops, list) or not stops:
            raise ValueError('Route requires timed stops')
        answers = [visibility_query(indexes, args.team, stop['subject'], stop['at_seconds']) for stop in stops]
        if any(a['at_seconds'] > b['at_seconds'] for a, b in zip(answers, answers[1:])):
            raise ValueError('Route times must be ordered')
        result = {'samples': answers, 'visible_samples': sum(a['visible'] is True for a in answers),
                  'hidden_samples': sum(a['visible'] is False for a in answers),
                  'unknown_samples': sum(a['visible'] is None for a in answers),
                  'continuous_route_visibility': None}
    print(json.dumps({'version': indexes[0]['version'], 'source_sha256': indexes[0]['source_sha256'],
                      'observer_team_id': args.team, 'result': result}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError) as error:
        print(f'vision: {error}', file=sys.stderr)
        sys.exit(2)
