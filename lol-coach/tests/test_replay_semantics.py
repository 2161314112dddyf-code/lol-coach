import pytest

from lol_coach.inventory_undo import refund_evidence
from lol_coach.spell_slots import decode_slot


def gold(t, current, earned, actor='hero'):
    return dict(entity_id=actor, time_seconds=t, values=dict(current_gold=current, total_gold=earned))


def test_refund_requires_observed_income_not_assumed_tick():
    before = gold(505.58782348633247, 763.6668701171875, 6838.66650390625)
    after = gold(506.08882348633256, 1316.6668701171875, 6841.66650390625)
    result = refund_evidence(before, after, 550)
    assert result['status'] == 'PASS'
    assert result['earned_income_delta'] == 3
    assert result['net_refund'] == 550
    assert result['evidence_available_at'] == after['time_seconds']
    assert refund_evidence(before, gold(after['time_seconds'], after['values']['current_gold'], before['values']['total_gold']), 550)['status'] == 'FAIL'


@pytest.mark.parametrize('after', [gold(1, 500, 500), gold(3, 500, 500, 'other'), gold(3, float('nan'), 500)])
def test_refund_rejects_invalid_witness(after):
    with pytest.raises(ValueError):
        refund_evidence(gold(2, 200, 500), after, 300)


@pytest.mark.parametrize('payload, expected', [
    ('b50f84867c72e1333420921eb0155b', 'Q'),
    ('b50bd4f60b0aee43a04096feb01556', 'W'),
    ('b50ce4f65c72e5c3a440967eb015fa', 'E'),
    ('b50894f65c32dd5312e0963eb015a9', 'R'),
])
def test_real_packet_header_subfields(payload, expected):
    result = decode_slot(bytes.fromhex(payload))
    assert result['slot_label'] == expected
    assert result['new_cast'] is None and result['cooldown_ready_at'] is None


def test_unknown_variable_slot_is_not_forced_to_r():
    # Synthetic change to the observed R header: an internal slot stays unknown.
    result = decode_slot(bytes.fromhex('b50894f65c32dd5312e0963eb0159b'))
    assert result['slot'] is None
    assert result['variable_byte'] == '0x9b'


@pytest.mark.parametrize('payload', ['', 'b50894f65c32dd5312e0963eb015', 'b50894f65c32dd5312e0963e0015a9'])
def test_slot_rejects_truncated_or_other_envelope(payload):
    with pytest.raises(ValueError):
        decode_slot(bytes.fromhex(payload))


def test_slot_build_gate():
    with pytest.raises(ValueError):
        decode_slot(bytes.fromhex('b50894f65c32dd5312e0963eb015a9'), version='16.15')
