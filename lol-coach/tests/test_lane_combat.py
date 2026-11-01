"""Synthetic decoder contracts plus literal bytes from the named exact build."""
from copy import deepcopy
import struct

import pytest

from lol_coach.lane_combat import decode_health_loss, load_profile


ACTOR = '0x400001f8'
PACKET = bytes.fromhex('60875b29387d65512069e9d52b')


def test_observed_variable_component_and_embedded_recipient_reference():
    result = decode_health_loss(PACKET, entity_id=ACTOR)
    assert result['value'] == struct.unpack('<f', bytes.fromhex('cdcc1441'))[0]
    assert result['reported_entity_id'] == ACTOR
    assert result['recipient_reference_payload_range'] == [4, 6]
    assert result['amount_payload_offset'] == 9
    assert result['amount_wire_hex'] == '69e9d52b'
    assert result['amount_decoded_hex'] == 'cdcc1441'
    assert result['opaque_middle_hex'] == '655120'
    assert result['attacker_entity_id'] is None
    assert result['attack_count'] is None
    assert result['hit_confirmed'] is None
    assert result['exact_death_time'] is None


def test_second_component_is_separate_from_attack_count():
    raw = bytes.fromhex('a11ddb28387dae629c45655120cbcbe32b')
    result = decode_health_loss(raw, entity_id=ACTOR)
    assert result['value'] == 11.0
    assert result['amount_payload_offset'] == 13
    assert result['opaque_middle_hex'] == 'ae629c45655120'
    assert result['health_after'] is None


def test_small_floating_precision_is_preserved_without_decimal_reconstruction():
    raw = bytes.fromhex('669d5b29387d65512050034e2b')
    assert decode_health_loss(raw, entity_id=ACTOR)['value'] == 8.496119499206543


def test_raw_counterexample_with_different_scalar_layout_is_rejected():
    raw = bytes.fromhex('61d05b288751bd4ebc4e1e2d14c2')
    with pytest.raises(ValueError, match='range or scalar layout'):
        decode_health_loss(raw, entity_id='0x4000a9aa')


def test_outer_recipient_mismatch_rejects_instead_of_naming_an_attacker():
    with pytest.raises(ValueError, match='match outer'):
        decode_health_loss(PACKET, entity_id='0x400001f7')


def test_unknown_actor_wire_byte_and_unknown_scalar_pair_are_not_guessed():
    profile = load_profile()
    unknown = next(i for i in range(256) if i not in profile['actor_reference_byte_pairs'].values())
    with pytest.raises(ValueError, match='Unobserved embedded actor byte'):
        decode_health_loss(PACKET[:4]+bytes([unknown])+PACKET[5:], entity_id=ACTOR)
    partial = deepcopy(profile)
    partial['amount_byte_pairs'] = {p: w for p, w in partial['amount_byte_pairs'].items() if w != PACKET[-1]}
    with pytest.raises(ValueError, match='Unobserved health-loss scalar byte'):
        decode_health_loss(PACKET, entity_id=ACTOR, profile=partial)


@pytest.mark.parametrize('value', [0., -1., float('nan'), float('inf'), 6101.])
def test_unsupported_magnitude_or_nonfinite_cannot_become_health_loss(value):
    table = {int(k): v for k, v in load_profile()['amount_byte_pairs'].items()}
    tail = bytes(table[b] for b in struct.pack('<f', value))
    with pytest.raises(ValueError, match='range or scalar layout'):
        decode_health_loss(PACKET[:-4]+tail, entity_id=ACTOR)


@pytest.mark.parametrize('raw', [b'', PACKET[:4], PACKET[:-1], PACKET+b'1234567', 'hex'])
def test_unobserved_length_or_input_type_rejected(raw):
    with pytest.raises(ValueError, match='length'):
        decode_health_loss(raw, entity_id=ACTOR)


@pytest.mark.parametrize('actor', [None, 0x400001f8, '0x800001f8', '0x400001F8', 'not-an-id'])
def test_only_canonical_class1_identity_binding_is_supported(actor):
    with pytest.raises(ValueError, match='canonical'):
        decode_health_loss(PACKET, entity_id=actor)


def test_exact_build_and_profile_version_gates():
    with pytest.raises(ValueError, match='build'):
        decode_health_loss(PACKET, entity_id=ACTOR, version='16.21')
    profile = load_profile()
    profile['version'] = '16.21'
    with pytest.raises(ValueError, match='profile'):
        decode_health_loss(PACKET, entity_id=ACTOR, profile=profile)
