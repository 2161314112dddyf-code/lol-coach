import pytest

from lol_coach.spell_state_fields import decode_fields


def test_three_values_have_separate_boundaries():
    row = decode_fields(bytes.fromhex('b76fe73a3feb12123100128729b7'))
    assert row['slot']['index'] == 0
    assert [f['wire_hex'] for f in row['numeric_fields']] == ['e73a3feb', '12123100', '128729b7']
    assert [f['payload_offset'] for f in row['numeric_fields']] == [2, 6, 10]
    assert row['cooldown_seconds'] is None and row['ready_at'] is None


def test_variable_slot_is_between_first_and_second_value():
    row = decode_fields(bytes.fromhex('3ff0b9b90fc0b91212aac6'))
    assert row['slot']['index'] == 4
    assert row['slot']['payload_offset'] == 6
    assert [f['wire_hex'] for f in row['numeric_fields']] == ['b9b90fc0', '1212aac6', None]


def test_keyframe_flag_is_preserved_without_readiness_claim():
    row = decode_fields(bytes.fromhex('b0e3eb19d19f'))
    assert row['raw_flag_bit0'] == 0
    assert row['ready_at'] is None


def test_unknown_internal_slot_and_constant_not_filled_with_zero():
    row = decode_fields(bytes.fromhex('31f55a'))
    assert row['slot']['index'] is None
    assert row['slot']['wire_hex'] == '5a'
    assert all(f['value'] is None for f in row['numeric_fields'])


@pytest.mark.parametrize('raw', ['', '31', '318dc9c9e3', '31ed00', '30a1', '3200'])
def test_invalid_fields_rejected(raw):
    with pytest.raises(ValueError):
        decode_fields(bytes.fromhex(raw))


def test_wrong_build():
    with pytest.raises(ValueError):
        decode_fields(bytes.fromhex('31ed'), version='16.15')
