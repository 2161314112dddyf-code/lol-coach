"""Measure a completed personal file-host run from its envelopes and sealed artifacts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from lol_coach.file_model_bridge import atomic_json
from lol_coach.reasoning_frame import canonical, digest
from scripts.audit_personal_session import audit


def read(path):
    return json.loads(path.read_bytes())


def length(text):
    return dict(nonspace_chars=sum(not c.isspace() for c in text),
                han_chars=len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', text)))


def measure(session, sequence, player_review, narration, replay=None):
    receipt = audit(session)
    schedule = read(sequence)
    if receipt['source_sha256'] != schedule['source_sha256']:
        raise ValueError('wrong replay in prepared sequence')
    if [row['at'] for row in receipt['steps']] != [row['at'] for row in schedule['selections']]:
        raise ValueError('session does not cover the supplied sequence')
    stages = {stage: [] for stage in ('exchange', 'claim_exchange', 'execution_exchange')}
    texts = {k: Counter() for k in ('sealed_json', 'player_cards')}
    ab = []
    no_window = []
    last_path_time = None
    if replay:
        from lol_coach.personal_episode import PersonalPathIndex
        index = PersonalPathIndex.from_replay(replay.read_bytes())
        if index.source != receipt['source_sha256']:
            raise ValueError('wrong replay for execution coverage')
        last_path_time = max((rows[-1]['time_seconds'] for rows in index.rows.values() if rows), default=0)
    for i, step in enumerate(receipt['steps'], 1):
        directory = session / f'{i:02}'
        answer = read(directory/'answer.json')
        expected = digest(answer)
        claim = read(directory/'claim-review.json')
        if claim['accepted'] is not True or claim['answer_sha256'] != expected:
            raise ValueError(f'missing accepted review at {i}')
        skip_execution = last_path_time is not None and last_path_time <= step['at']
        if skip_execution:
            no_window.append(step['at'])
        elif read(directory/'execution-answer.json')['answer_sha256'] != expected:
            raise ValueError(f'execution bound to another answer at {i}')
        texts['sealed_json'].update(length(canonical(answer)))
        texts['player_cards'].update(length((directory/'answer.md').read_text(encoding='utf-8-sig')))
        ab.append((directory/'answer.json').stat().st_mtime_ns)
        for stage, history in stages.items():
            requests = sorted((directory/stage/'requests').glob('*.json'))
            responses = sorted((directory/stage/'responses').glob('*.json'))
            if stage == 'execution_exchange' and skip_execution and not requests and not responses:
                continue
            if not requests or [p.name for p in requests] != [p.name for p in responses]:
                raise ValueError(f'incomplete {stage} at {i}')
            for req, reply in zip(requests, responses):
                if read(req)['request_id'] != read(reply)['request_id']:
                    raise ValueError(f'unmatched {stage} at {i}')
                history.append((req.stat().st_mtime_ns, reply.stat().st_mtime_ns))
    if stages['execution_exchange'] and min(a for a, _ in stages['execution_exchange']) < max(ab):
        raise ValueError('execution evidence opened before all decision files were sealed')
    timing = {}
    for stage, history in stages.items():
        if any(b < a for a, b in history):
            raise ValueError('invalid exchange timestamps')
        timing[stage] = dict(responses=len(history), summed_response_wait_seconds=round(
            sum(b-a for a,b in history)/1e9, 2))
    spans = [pair for history in stages.values() for pair in history]
    texts['review_overview'] = length((session/'review.md').read_text(encoding='utf-8-sig'))
    texts['player_edition'] = length(player_review.read_text(encoding='utf-8-sig'))
    texts['narration'] = length(narration.read_text(encoding='utf-8-sig'))
    return dict(match=receipt['match'], decisions=receipt['checks'], tools=receipt['tools'],
                mcp_calls=sum(receipt['tools'].values()), stages=timing,
                last_path_time=last_path_time, no_later_execution_window=no_window,
                first_request_to_last_reply_seconds=round((max(b for _,b in spans)-min(a for a,_ in spans))/1e9,2),
                lengths=texts, usage_records_by_step=[s.get('usage') for s in read(session/'manifest.json')['steps']],
                scope='File response waits include the responder and scheduling. Character counts are not tokens.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('session','sequence','player_review','narration','output'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--replay', type=Path, help='Verify the last available path sample when the game ends')
    args = parser.parse_args()
    result = measure(args.session, args.sequence, args.player_review, args.narration, args.replay)
    if args.output.exists():
        parser.error('Use a new output path')
    atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
