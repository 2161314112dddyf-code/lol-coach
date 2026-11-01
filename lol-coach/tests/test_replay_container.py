import json,struct
import pytest,zstandard
from lol_coach.replay_container import container_info,packets

def replay(version='16.21.829.9102',flag=4,compressed=True,payload=None):
    raw=payload if payload is not None else struct.pack('<BfIHI',1,2.,1,0x55,0)+b'x'+bytes([0xf1,10,1,255])+b'y'
    blob=zstandard.ZstdCompressor().compress(raw) if compressed else raw
    v=version.encode();head=b'RIOT\x02'+b'\0'*9+bytes([len(v)])+v
    chunk=struct.pack('<IIBII',1,2,1,len(raw),len(blob) if compressed else 0)
    if version.startswith('16.21'):chunk+=bytes([flag])
    meta=json.dumps({'gameLength':3000}).encode()
    return head+chunk+blob+b'\0'*256+meta+len(meta).to_bytes(4,'little')

@pytest.mark.parametrize('version',['16.20.824.8524','16.21.829.9102'])
@pytest.mark.parametrize('compressed',[True,False])
def test_both_headers_and_signed_parameter_delta(version,compressed):
    rows=list(packets(replay(version,compressed=compressed)))
    assert len(rows)==2 and rows[1]['param']==0xffffffff
    assert rows[1]['opcode']==0x55 and rows[1]['time']==pytest.approx(2.01)
    assert rows[1]['payload']==b'y'

def test_unknown_extension_build_and_truncated_packet_fail():
    with pytest.raises(ValueError):list(packets(replay(flag=5)))
    with pytest.raises(ValueError):container_info(replay('16.22.000.0000'))
    with pytest.raises(ValueError):list(packets(replay(payload=b'\x01')))

def test_packet_cannot_overrun_chunk():
    with pytest.raises(ValueError):list(packets(replay(payload=struct.pack('<BfIHI',1,2.,100,1,1))))
