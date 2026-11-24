import json

import pytest

from lol_coach.file_model_bridge import file_sha256
from lol_coach.player_review import _before, write_player_review
from lol_coach.reasoning_frame import digest


def put(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def read(path):
    return json.loads(path.read_bytes())


def sealed_step(root, i, at, choice, **extra):
    source = 'a' * 64
    d = root/f'{i:02}'
    d.mkdir()
    frame = dict(schema='decision-frame/v1', task={}, input_policy=[], facts={},
                 decision=dict(build='test', at_seconds=at, observer_team_id=100, player_entity_id='me'))
    frame_id = 'frame_' + digest(frame)[:24]
    frame['frame_id'] = frame_id
    bundle = dict(schema='reasoning-bundle/v1', frame=frame, audit=dict(source_replay_sha256=source))
    put(d/'bundle.json', bundle)
    other = 'change_action' if choice == 'continue_action' else 'continue_action'
    answer = dict(frame_id=frame_id, objective='留一个退路', immediate_action='往线侧靠。',
                  options=[dict(id=choice, action='选中走法。', gains=['保住线权。'], costs=['会晚到河口。']),
                           dict(id=other, action='绕草过去。', gains=['提前占住河口。'], costs=['对线搭档少人。'])],
                  recommendation=dict(preferred_option_id=choice, fallback_option_id=other,
                                      why='目前你能看到河口。', switch_conditions=['等搭档靠近。']))
    put(d/'answer.json', answer)
    seal = digest(answer)
    put(d/'claim-review.json', dict(answer_sha256=seal, accepted=True))
    step = dict(status='completed', review_scope='蓝方本人', champion='测试英雄',
                player_entity_id='me', source_sha256=source, at_seconds=at, frame_id=frame_id,
                input_sha256=file_sha256(d/'bundle.json'), **extra)
    item = dict(kind='own_position_and_command', at=at+1)
    ref = 'actual_' + digest(item)[:20]
    put(d/'execution.json', dict(frame_id=frame_id, source_sha256=source, player_entity_id='me',
                                decision_at=at, observed_through=at+2, sealed_answer_sha256=seal,
                                actual={ref: item}))
    put(d/'execution-answer.json', dict(frame_id=frame_id, answer_sha256=seal, evidence_ids=[ref],
                                       observed_actions='后来往河口走。', tradeoff='路线已经走了一段。',
                                       lesson='下次先等搭档。', unknowns=['没有命中记录。']))
    return step


def test_costs_outcome_and_open_tail_with_short_interrupt(tmp_path):
    steps = [sealed_step(tmp_path, 1, 20, 'change_action'),
             sealed_step(tmp_path, 2, 24, 'continue_action', selection_reason='closer_local_opponent',
                         review_mode='brief_update')]
    for name in ('execution.json', 'execution-answer.json'):
        (tmp_path/'02'/name).unlink()
    put(tmp_path/'manifest.json', dict(steps=steps))
    output = write_player_review(tmp_path)
    text = output.read_text(encoding='utf-8')
    assert text.index('先选一手') < text.index('目前你能看到') < text.index('会晚到河口')
    assert text.index('选中走法') < text.index('目前你能看到')
    assert text.index('绕草过去') < text.index('目前你能看到')
    assert text.index('提前占住河口') < text.index('对线搭档少人') < text.index('后来往河口走')
    assert text.count('绕草过去') == 1
    before_practice, practice = text.split('## 下把试一次')
    assert '下次先等搭档。' in before_practice
    assert '00:20' in practice and '下次先等搭档。' in practice
    assert '没有命中记录' in text
    assert '## 00:24' not in text and '结果未知' in text.split('**00:24**')[1]
    before = text.split('**回放里**')[0]
    reply = read(tmp_path/'01/execution-answer.json')
    reply['observed_actions'] = '实际走向另一侧。'
    put(tmp_path/'01/execution-answer.json', reply)
    assert write_player_review(tmp_path).read_text(encoding='utf-8').split('**回放里**')[0] == before


def test_follow_through_connects_the_action_to_the_observation_and_both_exits(tmp_path):
    sealed_step(tmp_path, 1, 20, 'continue_action')
    answer = read(tmp_path/'01/answer.json')
    beat = dict(action='占住路口。', expected_state='对面只能分开绕。',
                check_when='等前排越过路口。', if_confirmed='两人先打一人。', if_not_confirmed='跟搭档退线。')
    answer['follow_through'] = dict(steps=[beat])
    text = '\n'.join(_before(answer, True))
    assert '占住路口。 对面只能分开绕。 等前排越过路口。 两人先打一人。 跟搭档退线。' in text
    assert text.index('绕草过去') < text.index('提前占住河口') < text.index('对线搭档少人')


def test_registered_question_must_survive_unchanged(tmp_path):
    from lol_coach.lesson_threads import register_question

    step = sealed_step(tmp_path, 1, 20, 'change_action')
    d = tmp_path/'01'
    question = register_question(read(d/'bundle.json'), read(d/'answer.json'))
    step['lesson_question_sha256'] = digest(question)
    put(tmp_path/'manifest.json', dict(steps=[step]))
    with pytest.raises(ValueError, match='teaching question'):
        write_player_review(tmp_path)
    put(d/'lesson-question.json', dict(question, watch_text='事后改题'))
    with pytest.raises(ValueError, match='teaching question'):
        write_player_review(tmp_path)
    put(d/'lesson-question.json', question)
    output = write_player_review(tmp_path)
    entry = read(output.with_suffix('.lessons.json'))['threads'][0][0]
    assert entry['registration'] == 'registered_at_seal' and entry['question'] == question


def test_native_brief_has_no_full_options_or_recommendation(tmp_path):
    d = tmp_path/'01'
    step = sealed_step(tmp_path, 1, 20, 'change_action', review_mode='brief_update')
    answer = dict(schema='personal-brief/v1', frame_id=step['frame_id'], change='看见第二个人了。',
                  immediate_action='往回靠一步。', switch_if='他走开时再上前。', disposition='unanchored', fact_refs=[])
    put(d/'answer.json', answer)
    seal = digest(answer)
    put(d/'claim-review.json', dict(answer_sha256=seal, accepted=True))
    put(d/'execution-answer.json', dict(read(d/'execution-answer.json'), answer_sha256=seal))
    put(d/'execution.json', dict(read(d/'execution.json'), sealed_answer_sha256=seal))
    put(tmp_path/'manifest.json', dict(steps=[step]))
    text = write_player_review(tmp_path).read_text(encoding='utf-8')
    assert text.index(answer['change']) < text.index(answer['immediate_action']) < text.index('后来往河口走')
    assert '另一条路的得失' not in text


def test_brief_hindsight_sampler_preserves_origin_and_limits_citable_rows():
    from lol_coach.execution_review import _short_execution

    rows = {str(i): dict(kind='own_position_and_command', at=i, source={'offset': i},
                         command_xz=[[1, 0], [2, 0], [i+3, 0]]) for i in range(10)}
    actual = dict(actual=rows)
    shown = _short_execution(actual)
    assert set(shown['actual']) == {'0', '5', '9'}
    assert shown['actual']['9']['command_xz'] == [[12, 0]]
    assert rows['9']['source'] == {'offset': 9} and len(rows['9']['command_xz']) == 3


def test_execution_stage_publishes_the_player_readout(tmp_path):
    from lol_coach.execution_review import finish_execution_review
    from lol_coach.personal_episode import PersonalPathIndex
    from test_personal_episode import pair, sample

    bundle, answer = pair()
    directory = tmp_path/'01'
    directory.mkdir()
    put(directory/'bundle.json', bundle)
    put(directory/'answer.json', answer)
    put(directory/'claim-review.json', dict(answer_sha256=digest(answer), accepted=True))
    step = dict(status='completed', frame_id=answer['frame_id'], source_sha256='a'*64,
                at_seconds=20, player_entity_id='0x1', input_sha256=file_sha256(directory/'bundle.json'),
                champion='Test', review_scope='蓝方')
    put(tmp_path/'manifest.json', dict(steps=[step]))
    index = PersonalPathIndex('a'*64, [sample(20, 0, 100), sample(21, 20, 100)])

    def review(request):
        payload = json.loads(request['messages'][-1]['content'])
        actual = payload['execution']
        return dict(frame_id=actual['frame_id'], answer_sha256=actual['sealed_answer_sha256'],
                    observed_actions='下一秒有一次移动采样。', tradeoff='站位改变。', lesson='看退路。',
                    unknowns=['技能命中未知。'], evidence_ids=list(actual['actual']))

    finish_execution_review(tmp_path, index, None, generator_factory=lambda directory: review)
    assert '下一秒有一次移动采样。' in (tmp_path/'player-review.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('damage', ['actor', 'answer', 'window', 'event', 'unsealed'])
def test_cross_player_time_or_unsealed_data_cannot_be_written(tmp_path, damage):
    step = sealed_step(tmp_path, 1, 20, 'change_action')
    path = tmp_path/'01/execution.json'
    actual = read(path)
    if damage == 'actor':
        actual['player_entity_id'] = 'someone-else'
    elif damage == 'answer':
        actual['sealed_answer_sha256'] = 'old'
    elif damage == 'window':
        actual['observed_through'] = 90
    elif damage == 'event':
        next(iter(actual['actual'].values()))['at'] = 12
    else:
        step['status'] = 'evidence_only'
    put(path, actual)
    put(tmp_path/'manifest.json', dict(steps=[step]))
    with pytest.raises(ValueError):
        write_player_review(tmp_path)
    assert not (tmp_path/'player-review.md').exists()
