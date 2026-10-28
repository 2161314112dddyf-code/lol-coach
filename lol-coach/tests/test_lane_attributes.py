import pytest
from lol_coach.lane_attributes import attribute_prefix,super_crosscheck


GROUPS=[dict(group=4,field_mask=0xffffff,payload_offset=242,decoded_data_hex='ffffffffff8f80800804000080c34300007042000020410000803fffffffff48e17041ffffff00ffffff'),
 dict(group=8,field_mask=0x3ffffff,payload_offset=289,decoded_data_hex='00a0524500a05245ffffffffffffffff00010000c8420000c84201ff0000803f00002a43ff0000e03fffffffffffff'),
 dict(group=32,field_mask=0xfff,payload_offset=341,decoded_data_hex='0000ffff0080a243ff0000803fffa099193fff0104')]


def test_original_super_signature_and_field_offsets():
    value=super_crosscheck(dict(groups=GROUPS,first_state_time=845.6669,source={}))
    assert value['classification']=='super'
    assert value['fields']['attack_damage']['value']==391.
    assert value['fields']['armor']['decoded_payload_offset']==257
    assert value['fields']['max_health']['value']==3370.
    assert value['witnessed_at']==845.6669


def test_missing_independent_fields_never_confirms_super():
    value=super_crosscheck(dict(groups=GROUPS[:1],first_state_time=845.6669,source={}))
    assert value['classification']is None


@pytest.mark.parametrize('change',[{'field_mask':3},{'decoded_data_hex':'ff'},{'group':1}])
def test_unsupported_attribute_layout_rejected(change):
    with pytest.raises(ValueError):attribute_prefix(dict(GROUPS[0],**change))
