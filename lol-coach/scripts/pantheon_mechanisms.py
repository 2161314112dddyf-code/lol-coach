"""Build cached fixed-version mechanisms or query a hypothetical interaction."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.mechanism_rules import build_bundle, evaluate_interaction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build', help='Offline only; validates frozen source hashes')
    build.add_argument('--cache-root', type=Path, default=ROOT / 'data/research/champion_catalog')
    build.add_argument('--output', type=Path, required=True)
    query = sub.add_parser('query')
    query.add_argument('--bundle', type=Path, required=True)
    query.add_argument('--case', required=True)
    query.add_argument('--patch', required=True)
    query.add_argument('--facts', type=Path, required=True, help='JSON object of hypothetical true/false/null conditions')
    query.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new filename')
    try:
        if args.command == 'build':
            result = build_bundle(args.cache_root)
        else:
            bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
            facts = json.loads(args.facts.read_text(encoding='utf-8'))
            result = evaluate_interaction(bundle, args.case, facts, patch=args.patch)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(dict(output=str(args.output), schema=result['schema'],
                         status=result.get('status', 'source_bundle_built')), ensure_ascii=False))


if __name__ == '__main__':
    main()
