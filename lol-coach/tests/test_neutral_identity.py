"""Synthetic boundary tests. Real packet checks are exported separately."""
import json,struct
from pathlib import Path
import pytest
from lol_coach.neutral_identity import decode_model,stationary_position
from test_compound_inventory import packet

PROFILE=json.loads((Path(__file__).parents[1]/'lol_coach/profiles/neutral_names_16_20.json').read_text())


def name_packet(name,mode):
    spec=PROFILE['modes'][str(mode)]
    table={int(k):v for k,v in spec['byte_pairs'].items()}
    size=next(int(k)for k,v in spec['length_pairs'].items()if v==len(name))
    wire=bytes(table[c]for c in name.encode())
    if spec['order']==2:
        buf=bytearray(len(wire));n=(len(wire)+1)//2
        buf[::2]=wire[:n];buf[1::2]=wire[n:][::-1];wire=bytes(buf)
    return (mode<<12).to_bytes(4,'little')+b'\xff'*9+bytes([size])+wire+b'\xff'*8


@pytest.mark.parametrize('mode',[0,2,3])
def test_length_disambiguates_small_raptor_from_large(mode):
    result=decode_model(name_packet('SRU_RazorbeakMini',mode))
    assert result['model_name']=='SRU_RazorbeakMini'
    assert result['camp_id'] is None and result['instance_name'] is None


def test_unseen_mode_and_wrong_version_rejected():
    raw=name_packet('SRU_RazorbeakMini',0)
    with pytest.raises(ValueError):decode_model(raw,version='16.21')
    with pytest.raises(ValueError):decode_model((1<<12).to_bytes(4,'little')+raw[4:])


def test_truncated_and_ambiguous_names_rejected():
    raw=name_packet('SRU_RazorbeakMini',0)
    with pytest.raises(ValueError):decode_model(raw[:22])
    with pytest.raises(ValueError):decode_model(raw+raw[4:])


def position_packet(x=7000.,z=4000.,dx=1.,dz=0.):
    prefix=bytes.fromhex('00000000000000000000803f0000000000000000000000000003')
    return packet(b'\x00'+prefix+b'\x00'*5+struct.pack('<4f',x,z,dx,dz))


def test_stationary_position_has_original_decoded_offset():
    result=stationary_position(position_packet())
    assert result['position_xz']==[7000.,4000.]
    assert result['position_decoded_offset']==32
    assert result['arbitrary_moving_object_supported'] is False


@pytest.mark.parametrize('values',[(-1.,4000.,1.,0.),(7000.,float('nan'),1.,0.),(7000.,4000.,2.,0.)])
def test_invalid_coordinate_or_direction_rejected(values):
    with pytest.raises(ValueError):stationary_position(position_packet(*values))


def test_other_compound_layout_not_called_stationary():
    with pytest.raises(ValueError):stationary_position(packet(b'\x00'+b'\x00'*47))
