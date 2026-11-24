from copy import deepcopy

import pytest

from lol_coach.coaching_checkpoints import select_coaching_checkpoints
from lol_coach.lane_opportunities import ARRIVAL, REMOVAL, _scan, add_lane_candidates, attach_lane_change
from lol_coach.personal_episode import PersonalPathIndex
from lol_coach.reasoning_frame import digest


def native(at, entity, x):
    return dict(time_seconds=at, entity_id=entity, world_waypoints_xz=[[x, 0]],
                source=dict(stream=1, chunk=0, offset=at, record_index=entity))


def fixture(*, moved=False, missing=False, minions_move=True):
    units = (20, 21, 22)
    source = {'packet': 1}
    samples = [native(t, 1, 700 if moved and t >= 6 else 0) for t in (2, 4, 6, 8, 10, 12)]
    events = [(1, hex(e), 'bot', source) for e in units]
    for e in units:
        samples.append(native(4, e, 1700))
        samples.append(native(8, e, 700 if minions_move else 1700))
        if not missing or e != 20:
            events.append((12, hex(e), None, source))
    return PersonalPathIndex('source', samples), events


def test_fresh_arrival_and_explicit_removals_are_two_separate_prefixes():
    paths, events = fixture()
    changes = _scan(paths, 100, '0x1', 14, events)
    assert [(r['at'], r['kind']) for r in changes] == [(8, ARRIVAL), (12, REMOVAL)]
    for cutoff in (1.5, 4, 7.99, 8, 10.5, 12):
        prefix = [r for r in events if r[0] <= cutoff]
        assert _scan(paths, 100, '0x1', cutoff, prefix) == [r for r in changes if r['at'] <= cutoff]
    assert all(len(c['units']) == 3 and c['observer_team_id'] == 100 for c in changes)


def test_movement_or_absent_samples_do_not_claim_arrival_or_removal():
    paths, events = fixture(moved=True)
    assert not any(c['kind'] == ARRIVAL for c in _scan(paths, 100, '0x1', 14, events))
    paths, events = fixture(missing=True)
    assert [c['kind'] for c in _scan(paths, 100, '0x1', 18, events)] == [ARRIVAL]
    paths, events = fixture(minions_move=False)
    assert _scan(paths, 100, '0x1', 18, events) == []
    assert _scan(paths, 100, '0x9', 18, events) == []


def test_mixed_lane_groups_do_not_form_a_local_reinforcement_and_replacement_is_quiet():
    paths, events = fixture()
    mixed = [(at, entity, 'mid' if entity == '0x14' and lane else lane, source)
             for at, entity, lane, source in events]
    assert _scan(paths, 100, '0x1', 14, mixed) == []
    samples = [r for rows in paths.rows.values() for r in rows]
    for entity in range(30, 33):
        events.append((9, hex(entity), 'bot', {'packet': 2}))
        samples.append(native(12, entity, 200))
    paths = PersonalPathIndex('source', samples)
    assert [r['kind'] for r in _scan(paths, 100, '0x1', 14, sorted(events))] == [ARRIVAL]


def test_recent_repeat_is_silent_but_does_not_consume_later_personal_signal():
    paths, events = fixture()
    reach, removed = _scan(paths, 100, '0x1', 14, events)
    rows = [dict(at=0, selected_by=['regular']),
            dict(at=40, selected_by=['own_action_signal'],
                 triggers=[dict(kind='on_my_way', sent_at_seconds=39)])]
    saved = deepcopy(rows)
    candidates = add_lane_candidates(rows, [dict(reach, at=24), dict(removed, at=28)])
    result = select_coaching_checkpoints(candidates)
    assert result['selected_times'] == [0, 24, 40] and rows == saved
    assert result['rows'][1]['selection_reason'] == ARRIVAL
    assert not result['rows'][2]['selected']


def test_enemy_births_never_enter_the_allied_index(monkeypatch):
    from lol_coach import lane_opportunities as lo
    packets = [
        dict(time=2, stream=1, opcode=0x456, param=1, payload=b'a'),
        dict(time=2, stream=1, opcode=0x456, param=2, payload=b'b'),
        dict(time=2, stream=2, opcode=0x456, param=3, payload=b'a'),
    ]
    monkeypatch.setattr(lo, 'packets', lambda raw: packets)
    monkeypatch.setattr(lo, 'minion_birth', lambda b: (100 if b == b'a' else 200, 'middle'))
    monkeypatch.setattr(lo, '_ref', lambda p: {'source': p['param']})
    assert [r[1] for r in lo._lane_lifetimes(b'', 100)] == ['0x1']
    assert [r[1] for r in lo._lane_lifetimes(b'', 200)] == ['0x2']


@pytest.mark.parametrize('wrong', ['team', 'player', 'replay', 'future', 'ok'])
def test_lane_change_stays_bound_to_its_observer_clock_and_source(wrong):
    paths, events = fixture()
    event, _ = _scan(paths, 100, '0x1', 14, events)
    bundle = dict(frame=dict(facts={}, decision=dict(observer_team_id=100, player_entity_id='0x1', at_seconds=8)),
                  audit=dict(source_replay_sha256='source', fact_sources={}))
    if wrong == 'team':
        event['observer_team_id'] = 200
    elif wrong == 'player':
        event['player_entity_id'] = '0x2'
    elif wrong == 'replay':
        event['source_sha256'] = 'other'
    elif wrong == 'future':
        event['units']['0x14']['previous']['unit']['at'] = 9
    if wrong != 'ok':
        with pytest.raises(ValueError, match='lane_change_'):
            attach_lane_change(bundle, [event])
    else:
        f = attach_lane_change(bundle, [event])['frame']
        (fid, fact), = f['facts'].items()
        assert fid == 'f_' + digest(fact)[:20] and fact['available_at_seconds'] == 8
        assert fact['value']['kind'] == ARRIVAL
        assert bundle['audit']['fact_sources'][fid] == event
