"""Assemble a personal coaching readout from sealed decisions and separate hindsight records."""
import argparse
import json
import os
from pathlib import Path

from .file_model_bridge import file_sha256
from .reasoning_frame import digest, number
from .round_chain import _check_bundle, _source


def _read(path):
    return json.loads(path.read_bytes())


def _clock(at):
    return f'{int(at)//60:02}:{int(at)%60:02}'


def _detailed(step, answer, last_preference):
    """Spend time when the player's plan changes or a concrete branch is available."""
    choice = answer['recommendation']['preferred_option_id']
    return bool(
        step.get('selection_reason') in {'contact_after_gap', 'new_local_opponent', 'closer_local_opponent'}
        or answer.get('follow_through', {}).get('steps')
        or answer.get('continuation', {}).get('disposition') in {'revise', 'cancel'}
        or (choice == 'change_action' and (
            last_preference != choice or step.get('coordination_trigger', {}).get('active')))
    )


def _before(answer, detailed, *, brief_update=False, invite_choice=False, first_invitation=True):
    rec = answer['recommendation']
    if not detailed:
        return [' '.join((rec['why'], answer['immediate_action'])) if brief_update else answer['immediate_action']]
    options = {option['id']: option for option in answer['options']}
    best = options.get(rec['preferred_option_id'])
    other = options.get(rec['fallback_option_id'])
    paragraphs = []
    compare = invite_choice and best is not None and other is not None
    labels = {'continue_action': '继续当前动作', 'change_action': '现在换手'}
    if compare:
        paragraphs.append('**先选一手**　先停这儿。你会怎么走？' if first_invitation else '**先选一手**')
        for route in options.values():
            if route['id'] in (best['id'], other['id']):
                paragraphs.append(labels.get(route['id'], '可选走法') + '　' + route['action'])
    paragraphs.append(rec['why'])
    if compare:
        chosen = ['**这一拍更适合' + labels.get(best['id'], '采用首选') + '**']
        if best['action'] != answer['immediate_action']:
            chosen.append(answer['immediate_action'])
    else:
        chosen = [answer['immediate_action']]
    if best:
        gains = best['gains'][:1]
        if not compare and gains == [answer['objective']]:
            gains = []  # Already the chapter heading.
        chosen.extend([*gains, *best['costs'][:1]])
    paragraphs.append(' '.join(dict.fromkeys(chosen)))
    if other:
        branch = [] if compare else [other['action']]
        branch.extend(other['gains'][:1] or [other.get('end_state', '')])
        branch.extend(other['costs'][:1])
        if any(branch):
            paragraphs.append('**另一条路的得失**　' + ' '.join(dict.fromkeys(branch)))
    chain = answer.get('follow_through', {}).get('steps', [])
    if chain:
        for beat in chain:
            paragraphs.append('**接下来再看**　' + ' '.join(
                (beat['action'], beat['expected_state'], beat['check_when'], beat['if_confirmed'],
                 beat['if_not_confirmed'])))
    elif rec['switch_conditions']:
        paragraphs.append('**何时换手**　' + rec['switch_conditions'][0])
    return paragraphs


def _observed(directory, step, seal, until):
    """Read hindsight only for the same actor, clock, replay and sealed answer."""
    path = directory/'execution.json'
    reply_path = directory/'execution-answer.json'
    if not path.exists() and not reply_path.exists():
        return None
    if not path.exists():
        raise ValueError(f'{directory.name}: hindsight has no evidence file')
    actual = _read(path)
    at, through = step['at_seconds'], actual['observed_through']
    if (actual['frame_id'] != step['frame_id'] or actual['source_sha256'] != step['source_sha256']
            or actual['player_entity_id'] != step['player_entity_id'] or actual['decision_at'] != at
            or actual['sealed_answer_sha256'] != seal or not number(through) or not at < through <= until):
        raise ValueError(f'{directory.name}: mismatched hindsight window')
    if not reply_path.exists():
        return None
    reply = _read(reply_path)
    refs = reply['evidence_ids']
    if (reply['frame_id'] != step['frame_id'] or reply['answer_sha256'] != seal
            or not isinstance(refs, list) or bool(refs) != bool(actual['actual'])):
        raise ValueError(f'{directory.name}: mismatched hindsight answer')
    for ref in refs:
        item = actual['actual'].get(ref)
        observed_at = item.get('available_at_seconds', item.get('at')) if item else None
        if (not number(observed_at) or not at < observed_at <= through
                or ref != 'actual_' + digest(item)[:20]):
            raise ValueError(f'{directory.name}: invalid hindsight evidence')
    return reply if refs else None


def write_player_review(session, output=None):
    session = Path(session)
    output = Path(output) if output is not None else session/'player-review.md'
    manifest = _read(session/'manifest.json')
    steps = manifest['steps']
    if not steps or any(step['status'] != 'completed' for step in steps):
        raise ValueError('player review requires a fully sealed personal session')

    chapters = []
    previous_choice = scope = None
    first_focus = True
    last_at = -1
    for i, step in enumerate(steps, 1):
        directory = session/f'{i:02}'
        path = directory/'bundle.json'
        bundle = _read(path)
        frame = _check_bundle(bundle)
        decision = frame['decision']
        source = _source(bundle)
        current_scope = (source, decision['observer_team_id'], decision['player_entity_id'])
        answer = _read(directory/'answer.json')
        audit = _read(directory/'claim-review.json')
        seal = digest(answer)
        if (file_sha256(path) != step['input_sha256'] or (scope is not None and current_scope != scope)
                or source != step['source_sha256'] or step['player_entity_id'] != decision['player_entity_id']
                or step['at_seconds'] != decision['at_seconds'] or step['at_seconds'] <= last_at
                or step['frame_id'] != frame['frame_id'] or answer['frame_id'] != frame['frame_id']
                or audit['answer_sha256'] != seal or audit['accepted'] is not True
                or 'immediate_action' not in answer):
            raise ValueError(f'{directory.name}: mismatched sealed personal decision')
        brief_update = step.get('review_mode') == 'brief_update'
        detailed = not brief_update and _detailed(step, answer, previous_choice)
        invite = detailed and (first_focus or bool(answer.get('follow_through', {}).get('steps')))
        before = _before(answer, detailed, brief_update=brief_update, invite_choice=invite,
                         first_invitation=first_focus)
        title = '' if invite else answer['objective']
        chapters.append((directory, step, seal, detailed, title, before))
        if detailed:
            first_focus = False
        scope = current_scope
        previous_choice = answer['recommendation']['preferred_option_id']
        last_at = step['at_seconds']

    practice = None
    lines = ['# ' + (steps[0]['champion'] or steps[0]['player_entity_id']) + ' · 个人复盘', '',
             steps[0]['review_scope'], '',
             '我们一起看这把。碰到两条路都说得通的地方，你先选，再往下看。', '']
    for i, (directory, step, seal, detailed, title, before) in enumerate(chapters):
        at = step['at_seconds']
        until = min(at+30, steps[i+1]['at_seconds']) if i+1 < len(steps) else at+30
        observed = _observed(directory, step, seal, until)
        stamp = _clock(at)
        if detailed:
            lines.extend([f'## {stamp}　{title}'.rstrip(), ''])
            for paragraph in before:
                lines.extend([paragraph, ''])
        else:
            lines.extend([f'**{stamp}**　{before[0]}', ''])
        if observed:
            lines.extend(['**回放里**　' + observed['observed_actions'], ''])
            if detailed:
                lines.extend([observed['tradeoff'] + ' ' + observed['lesson'], ''])
                if practice is None:
                    practice = (stamp, observed['lesson'])
                if observed['unknowns']:
                    lines.extend(['还缺的证据　' + ' '.join(observed['unknowns']), ''])
        else:
            lines.extend(['这一步缺少可核验的后续，实际选择和结果未知。', ''])
    if practice is not None and len(chapters) > 1:
        stamp, lesson = practice
        lines.extend(['## 下把试一次', '',
                      f'还记得 {stamp} 那一手吗？下次再遇到那种局面，给自己一句提醒。', '', lesson, ''])
    case_path = Path(os.path.relpath(session, output.parent)).as_posix()
    lines.extend([f'本稿重排本次会话已封存的 {len(steps)} 个暂停点。秒数向下取整。精确时刻、逐点答卷和后续记录见[会话清单](<{case_path}/manifest.json>)。', ''])
    output.write_text('\n'.join(lines), encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(write_player_review(args.session, args.output))
