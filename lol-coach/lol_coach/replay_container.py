"""Bounded container framing for two observed builds; no gameplay semantics."""
import json
import math
import struct
import zstandard

HEADERS={'16.20.824.8524':17,'16.21.829.9102':18}


def container_info(data):
    if len(data)<280 or data[:5]!=b'RIOT\x02':raise ValueError('Unsupported container')
    start=15+data[14]
    version=data[15:start].decode('ascii')
    if version not in HEADERS:raise ValueError('Unobserved build')
    size=int.from_bytes(data[-4:],'little');end=len(data)-4-size-256
    if size<=0 or end<start:raise ValueError('Invalid metadata boundary')
    metadata=json.loads(data[end+256:-4])
    if not isinstance(metadata,dict):raise ValueError('Invalid metadata')
    return dict(version=version,start=start,end=end,metadata=metadata,chunk_header_size=HEADERS[version])


def chunks(data):
    info=container_info(data);pos=info['start'];end=info['end'];size=info['chunk_header_size']
    while pos<end:
        if pos+size>end:raise ValueError('Truncated chunk header')
        chunk,next_id,stream,raw_size,compressed_size=struct.unpack_from('<IIBII',data,pos)
        if size==18 and data[pos+17]!=4:raise ValueError('Unknown extended chunk header flag')
        stored=compressed_size or raw_size
        if raw_size>64*1024*1024 or pos+size+stored>end:raise ValueError('Invalid chunk size')
        blob=data[pos+size:pos+size+stored]
        raw=zstandard.ZstdDecompressor().decompress(blob,max_output_size=raw_size) if compressed_size else blob
        if len(raw)!=raw_size:raise ValueError('Chunk size mismatch')
        yield dict(chunk=chunk,next_id=next_id,stream=stream,container_offset=pos,
                   header_size=size,header_extension_hex=data[pos+17:pos+size].hex(),raw=raw)
        pos+=size+stored
    if pos!=end:raise ValueError('Container boundary mismatch')


def packets(data):
    for chunk in chunks(data):
        raw=chunk['raw'];pos=0;t=0.;opcode=param=0
        def take(fmt):
            nonlocal pos
            n=struct.calcsize(fmt)
            if pos+n>len(raw):raise ValueError('Truncated packet field')
            value=struct.unpack_from(fmt,raw,pos)[0];pos+=n;return value
        while pos<len(raw):
            start=pos;marker=take('<B')
            t=t+take('<B')/1000 if marker&0x80 else take('<f')
            if not math.isfinite(t) or t<0:raise ValueError('Invalid packet time')
            length=take('<B') if marker&0x10 else take('<I')
            if not marker&0x40:opcode=take('<H')
            param=(param+take('<b'))&0xffffffff if marker&0x20 else take('<I')
            if pos+length>len(raw):raise ValueError('Packet exceeds chunk')
            payload=raw[pos:pos+length];pos+=length
            yield dict(stream=chunk['stream'],chunk=chunk['chunk'],channel=marker&15,time=t,
                       opcode=opcode,param=param,offset=start,payload=payload)
