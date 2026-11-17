"""Check a completed file-backed personal review against its frozen inputs and model exchanges."""
import argparse
from collections import Counter
import json
from pathlib import Path

from lol_coach.decision_contract import validate_decision
from lol_coach.file_model_bridge import atomic_json, file_sha256
from lol_coach.round_chain import _check_bundle, _source


def audit(directory):
    manifest = json.loads((directory/'manifest.json').read_bytes())
    if manifest['backend'] != 'file' or manifest['perspective'] != 'personal' or not manifest['steps']:
        raise ValueError('requires a file-backed personal session')
    subject = manifest['verified_subject']
    previous_id, previous_time, previous_write = None, -1, 0
    counts, rows = Counter(), []
    for index, step in enumerate(manifest['steps'],1):
        path = directory/f'{index:02}'
        if step['status'] != 'completed' or file_sha256(path/'bundle.json') != step['input_sha256']:
            raise ValueError(f'unsealed or changed input at step {index}')
        bundle = json.loads((path/'bundle.json').read_bytes())
        frame = _check_bundle(bundle)
        decision = frame['decision']
        selected, = [p for p in frame['lineup'] if p['entity_id'] == decision['player_entity_id']]
        at = decision['at_seconds']
        if (at <= previous_time or previous_id != step['previous_frame_id'] or frame['frame_id'] != step['frame_id']
                or (_source(bundle),decision['observer_team_id'],selected['champion'])
                != (subject['replay_sha256'],subject['local_team_id'],subject['local_champion'])):
            raise ValueError(f'scope or order mismatch at step {index}')
        result = json.loads((path/'result.json').read_bytes())
        answer = json.loads((path/'answer.json').read_bytes())
        if result['answer'] != answer or validate_decision(answer,frame)['status'] != 'PASS':
            raise ValueError(f'invalid decision at step {index}')
        exchange = path/'exchange'
        first = exchange/'requests/01.json'
        if first.stat().st_mtime_ns < previous_write:
            raise ValueError(f'next request issued before preceding seal at step {index}')
        for call in range(1,result['model_calls']+1):
            name=f'{call:02}.json'
            request=json.loads((exchange/'requests'/name).read_bytes())
            reply=json.loads((exchange/'responses'/name).read_bytes())
            if reply['request_id'] != request['request_id']:
                raise ValueError('response does not match request')
        used = Counter()
        for item in result['trace']:
            if item['event'] == 'model_response':
                requests = {r['id']:r['name'] for r in item['response'].get('tool_requests',[])}
            elif item['event'] == 'tool_results':
                used.update(requests[r['id']] for r in item['results'])
        counts.update(used)
        previous_write=(exchange/'responses'/f"{result['model_calls']:02}.json").stat().st_mtime_ns
        rows.append(dict(at=at,frame_id=frame['frame_id'],prior=previous_id,tools=dict(used),
                         answer_sha256=file_sha256(path/'answer.json'),transition=answer['macro_round']['transition']))
        previous_id,previous_time=frame['frame_id'],at
    return dict(match=subject['match_id'],champion=subject['local_champion'],team=subject['local_team_id'],
                source_sha256=subject['replay_sha256'],checks=len(rows),tools=dict(counts),steps=rows)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('session',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    receipt=audit(a.session)
    atomic_json(a.output,receipt)
    print('sealed decisions',receipt['checks'],'tool calls',receipt['tools'])
