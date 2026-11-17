"""Query the review MCP for versioned spell data and damage at one frozen game clock."""
import argparse
import asyncio
import json
from pathlib import Path

from lol_coach.file_model_bridge import atomic_json, file_sha256
from lol_coach.round_chain import _check_bundle, _source
from scripts.reasoning import read_bundle, read_json
from scripts.round_review_mcp import query, round_client


async def inspect(bundle_path, slot, champion=None, target=None, hits=(), assumptions=None):
    bundle = read_bundle(bundle_path)
    frame = _check_bundle(bundle)
    decision = frame['decision']
    player = next(h for h in frame['lineup'] if h['entity_id'] == decision['player_entity_id'])
    champion = champion or player['champion']
    if hits and (not target or champion != player['champion']):
        raise ValueError('damage requires the selected player and an opponent')
    if (target or assumptions is not None) and not hits:
        raise ValueError('select spell hits with --hit SLOT.component')
    input_hash = file_sha256(bundle_path)
    async with round_client(bundle_path, input_hash) as (client, protocol):
        static = await query(client, 'get_ability_parameters', dict(champion=champion, slot=slot))
        result = dict(frame_id=frame['frame_id'], build=decision['build'], at_seconds=decision['at_seconds'],
                      player=player['champion'], observer_team_id=decision['observer_team_id'],
                      replay_sha256=_source(bundle), bundle_sha256=input_hash,
                      protocol=protocol, ability=static)
        if hits:
            enemy = next((h for h in frame['lineup'] if h['champion'] == target and h['relation'] == 'enemy'), None)
            if enemy is None:
                raise ValueError(f'{target} is not an enemy in this frame')
            request = dict(target_id=enemy['entity_id'], hits=[])
            for hit in hits:
                spell, separator, component = hit.partition('.')
                if not separator or not component or spell not in ('Q', 'W', 'E', 'R'):
                    raise ValueError('use --hit SLOT.component, for example R.landing_center')
                request['hits'].append(dict(slot=spell, component=component))
            result['frame_inputs_only'] = await query(client, 'calculate_ability_damage', dict(request, assumptions={}))
            if assumptions is not None:
                result['what_if'] = await query(client, 'calculate_ability_damage', dict(request, assumptions=assumptions))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--slot', choices=list('QWER'), required=True)
    parser.add_argument('--champion', help='Defaults to the player in the frame')
    parser.add_argument('--target', help='Enemy champion, for damage calculations')
    parser.add_argument('--hit', action='append', default=[], help='One reviewed component, e.g. R.landing_center')
    parser.add_argument('--assumptions-file', type=Path, help='JSON object for an additional explicit what-if')
    parser.add_argument('--output', type=Path, help='Optional new JSON receipt')
    args = parser.parse_args()
    assumptions = read_json(args.assumptions_file) if args.assumptions_file else None
    result = asyncio.run(inspect(args.bundle, args.slot, args.champion, args.target, args.hit, assumptions))
    if args.output:
        atomic_json(args.output, result)
        print(args.output)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
