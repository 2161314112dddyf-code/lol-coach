"""Byte fixtures copied from supplied ROFL; semantic claims need corpus report."""
import pytest

from lol_coach.skill_ranks import decode_payload, prefix_ranks


def test_practice_thirteen_point_allocation_budget():
    # Level 13 is independently observed before this sequence in 11363048522.
    raw = ['5cb260', '68b238', '6db228', '7cb030', '7eb2db20', '6db058',
           '58b048', '7cb350e7', '79b0db40', '7db318e7', 'e0b2e7', 'd5b2cf', '70b1cf']
    state = [0, 0, 0, 0]
    for i, value in enumerate(raw):
        event = decode_payload(bytes.fromhex(value))
        assert event['rank'] == state[event['slot']]+1
        state[event['slot']] = event['rank']
        assert event['unspent_points_observation'] == 12-i
        assert sum(state)+event['unspent_points_observation'] == 13
    assert state == [4, 4, 3, 2]


@pytest.mark.parametrize('payload', ['', '75', '70b1', '70b100', '75b200', '73b2', '45b2'])
def test_reject_unknown_or_truncated_without_guessing(payload):
    with pytest.raises(ValueError):
        decode_payload(bytes.fromhex(payload))


def test_wrong_build():
    with pytest.raises(ValueError):
        decode_payload(bytes.fromhex('75b2'), version='16.15')


def test_prefix_ignores_future_and_keyframe_and_does_not_seed_zero():
    def row(t, rank, stream):
        return dict(time_seconds=t, rank=rank, source={'stream': stream}, entity_id='hero', slot_label='Q')
    result = prefix_ranks([row(20, 4, 1), row(10, 2, 1), row(0, 0, 2), row(15, 3, 2)], 15)
    assert result['hero']['Q']['rank'] == 2
    assert set(result['hero']) == {'Q'}
    assert prefix_ranks([row(20, 4, 1)], 15) == {}


@pytest.mark.parametrize('cutoff', [-1, float('nan'), float('inf')])
def test_bad_cutoff(cutoff):
    with pytest.raises(ValueError):
        prefix_ranks([], cutoff)
