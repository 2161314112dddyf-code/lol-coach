"""Run the existing reasoning loop through a bounded local file responder."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.decision_contract import render_decision
from lol_coach.file_model_bridge import (DEFAULT_TIMEOUT_SECONDS, atomic_json,
    file_generate, file_sha256, new_directory)
from lol_coach.reasoning_runner import run_reasoning
from scripts.reasoning import read_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument('--max-calls', type=int, default=6)
    args = parser.parse_args()
    if args.max_calls < 1:
        parser.error('--max-calls must be positive')
    bundle = read_bundle(args.bundle)
    output = new_directory(args.output)
    bridge = file_generate(output / 'exchange', timeout_seconds=args.timeout_seconds,
        on_request=lambda event: print(json.dumps(event, ensure_ascii=True), flush=True))
    result = run_reasoning(bundle, bridge, max_calls=args.max_calls, max_repairs=1)
    atomic_json(output / 'result.json', result)
    if result['answer'] is not None:
        atomic_json(output / 'answer.json', result['answer'])
    if result['validation'] is not None:
        atomic_json(output / 'validation.json', result['validation'])
    markdown = render_decision(result['answer'], result['validation'])
    if result['error']:
        markdown += '\n运行状态：' + result['status'] + '\n\n' + result['error'] + '\n'
    with (output / 'answer.md').open('x', encoding='utf-8') as stream:
        stream.write(markdown)
    sources = ['scripts/run_reasoning_session.py', 'scripts/reasoning.py',
               'lol_coach/file_model_bridge.py', 'lol_coach/reasoning_runner.py',
               'lol_coach/reasoning_frame.py', 'lol_coach/decision_contract.py',
               'lol_coach/profiles/round_reasoning_cards_v1.json']
    manifest = dict(schema='file-reasoning-session/v1', execution_method='file_model_bridge',
        response_producer='not_authenticated_by_file_transport', external_api_used_by_cli=False,
        input_bundle=dict(path=str(args.bundle.resolve()), sha256=file_sha256(args.bundle)),
        frame_id=bundle['frame']['frame_id'], status=result['status'],
        model_callback_calls=result['model_calls'], reference_reads=result['reference_reads'],
        timeout_seconds_per_response=args.timeout_seconds, max_calls=args.max_calls, max_repairs=1,
        implementation={path: file_sha256(ROOT/path) for path in sources},
        outputs={str(path.relative_to(output)):file_sha256(path)
                 for path in output.rglob('*') if path.is_file()})
    atomic_json(output / 'manifest.json', manifest)
    print(json.dumps({'event':'session_finished', 'status':result['status'],
                      'output':str(output), 'model_callback_calls':result['model_calls']},
                     ensure_ascii=True), flush=True)
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        print('run_reasoning_session: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
