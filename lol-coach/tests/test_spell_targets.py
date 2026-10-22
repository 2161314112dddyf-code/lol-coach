"""Target subfield regressions, with deliberate false-positive counterexamples."""
import pytest

from lol_coach.spell_targets import decode_target, DISCOVERY_SHA256

HASTE = 'b50ba4f67cf2e8a334c396deb0156b3131b8db6f12f2ede6dbe16248b800eda5410659'
RYZE_W = 'b50fb4a67c72d9a340c396feb015fafaadf36f0210dcdcd4a8ede6dbe16248b800eda54106'
UNKNOWN_HERO = 'b50be4866c72d8c34a2396feb015fafaadf36f02c6dcdcd4a8ede6dbe16248b800eda54106'
LONG_ID = 'b50ad4867c72c5b33a4396feb01562c84cf36f2a22afdcdcd4a8ede6dbe16248b800eda54106'


def parse(raw):
    return decode_target(bytes.fromhex(raw), source_sha256=DISCOVERY_SHA256)


def test_self_and_enemy_targets_are_different():
    assert parse(HASTE)['target_entity'] == '0x4000003c'
    result = parse(RYZE_W)
    assert result['target_entity'] == '0x40000037'
    assert result['new_cast'] is None and result['hit_confirmed'] is None


def test_unknown_hero_stays_unknown_despite_valid_boundary():
    result = parse(UNKNOWN_HERO)
    assert result['status'] == 'unmapped_target_code'
    assert result['target_entity'] is None


def test_long_id_not_decoded_using_one_known_byte():
    # Synthetic mutation: a longer ID starts with a known hero byte.
    result = parse(LONG_ID.replace('6f2a22af', '6f2af2af'))
    assert result['status'] == 'unresolved_target_record_boundary'
    assert result['target_entity'] is None


def test_multiple_anchors_rejected_instead_of_first_match():
    result = parse(HASTE.replace('ede6dbe162', 'ede66f0210'))
    assert result['status'] == 'ambiguous_target_anchor'
    assert result['target_entity'] is None


def test_absent_target_is_unknown_not_zero():
    result = parse(HASTE.replace('6f12f2', '7012f2'))
    assert result['target_entity'] is None
    assert result['status'] == 'no_supported_explicit_target'


@pytest.mark.parametrize('version, digest', [('16.15', DISCOVERY_SHA256), ('16.20.824.8524', 'another_replay')])
def test_build_and_replay_gates(version, digest):
    with pytest.raises(ValueError):
        decode_target(bytes.fromhex(HASTE), version=version, source_sha256=digest)
