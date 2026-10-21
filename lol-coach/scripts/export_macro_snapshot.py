"""Join four cached replay exports into a point-in-time macro analysis input."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.macro_snapshot import build_snapshot, render_markdown

KINDS = ('ten', 'state', 'inventory', 'vision')


def load_inputs(replay_id, data_root=ROOT/'data/private'):
    if Path(replay_id).name != replay_id or '/' in replay_id or '\\' in replay_id or replay_id in ('.', '..'):
        raise ValueError('Replay ID must be a filename stem')
    bundles, inputs = [], []
    for kind in KINDS:
        path = data_root/f'replay_{kind}'/f'{replay_id}.json'
        raw = path.read_bytes()
        bundles.append(json.loads(raw))
        inputs.append(dict(kind=kind, path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest()))
    return bundles, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-id', required=True, help='e.g. HN1-11360086609')
    parser.add_argument('--at', required=True, type=float)
    parser.add_argument('--team', required=True, type=int, choices=(100, 200))
    parser.add_argument('--player', help='Optional own-team entity ID; enables only self private fields')
    parser.add_argument('--window', default=30, type=float)
    parser.add_argument('--output', required=True, type=Path, help='New JSON under data/private/macro_snapshots')
    args = parser.parse_args()
    target = args.output.resolve()
    allowed = (ROOT/'data/private/macro_snapshots').resolve()
    if allowed not in target.parents or target.suffix.lower() != '.json':
        raise ValueError(f'Output must be JSON under {allowed}')
    paths = [target, target.with_suffix('.md'), target.with_suffix('.manifest.json')]
    if any(p.exists() for p in paths):
        raise ValueError('Output already exists; choose a new filename')
    bundles, inputs = load_inputs(args.replay_id)
    snapshot = build_snapshot(*bundles, at=args.at, team=args.team, player=args.player, window=args.window)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    target.with_suffix('.md').write_text(render_markdown(snapshot), encoding='utf8')
    # Artifact hashes stay outside model-facing snapshot: no full-run counts or future events.
    manifest = dict(schema='macro-snapshot-artifacts/v1', inputs=inputs,
        output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        implementation_sha256=hashlib.sha256((ROOT/'lol_coach/macro_snapshot.py').read_bytes()).hexdigest())
    target.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(output=str(target), actors=len(snapshot['heroes']),
        evidence=len(snapshot['evidence']), summary=snapshot['summary']), ensure_ascii=False))


if __name__ == '__main__':
    main()
