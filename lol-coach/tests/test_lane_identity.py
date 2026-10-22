"""Synthetic mutations of bounded layouts, not independent gameplay proof."""
import pytest
from lol_coach.lane_identity import decode_spawn


def test_live_and_keyframe_identity_stable():
    a=decode_spawn(bytes.fromhex('ae5c749c87732930392723ec4ead43'))
    b=decode_spawn(bytes.fromhex('9113689a8723ec4ead43'))
    for key in ('team_id','lane','kind','opaque_instance_token_hex'):assert a[key]==b[key]
    assert a['character_name'] is None and a['runtime_map_id'] is None


def test_map11_lane_token_not_a_team_byte():
    a=decode_spawn(bytes.fromhex('6c246b988794aa925ea02d3bec900203'))
    assert (a['team_id'],a['lane'],a['kind'])==(100,'bottom','melee')


def test_single_super_example_stays_candidate():
    a=decode_spawn(bytes.fromhex('bc51ca983387ee4428a1593e1eb4b39d7cfb77'))
    assert a['kind']=='super_candidate'


@pytest.mark.parametrize('payload',['','9113689a8723ec','9113689a8722ec4ead43','9113689a8723eb4ead43'])
def test_unknown_forms_rejected(payload):
    with pytest.raises(ValueError):decode_spawn(bytes.fromhex(payload))


def test_wrong_version_rejected():
    with pytest.raises(ValueError):decode_spawn(bytes.fromhex('9113689a8723ec4ead43'),version='16.21')
