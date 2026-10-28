"""Bounded item counters/stat maps for the four reviewed 16.20 recordings.

Counts are item-specific (growth, Tear charge, consumable charge), not a
universal number of uses. Unknown bytes fail instead of extrapolating a codec.
"""
import json
import math
import struct
from pathlib import Path
from .replay_inventory import VERSION


def load_profile():
    profile=json.loads((Path(__file__).with_name('profiles')/'inventory_counters_16_20.json').read_text())
    if profile['version']!=VERSION:raise ValueError('Counter profile version mismatch')
    return profile


def decode_modifiers(header,raw,*,version=VERSION,profile=None):
    if version!=VERSION:raise ValueError('Unsupported exact build')
    profile=load_profile()if profile is None else profile
    if profile['version']!=version:raise ValueError('Counter profile version mismatch')
    count={0:0,1:2,7:1}.get(header>>15&7);cursor=0
    if count is None:
        if header>>15&7 not in (2,3,4,5,6):raise ValueError('Unknown counter selector')
        inverse={v:int(k)for k,v in profile['charge_byte_pairs'].items()}
        count=0
        for shift in range(0,21,7):
            if cursor>=len(raw):raise ValueError('Truncated item counter')
            try:b=inverse[raw[cursor]]
            except KeyError:raise ValueError('Unobserved item counter byte')from None
            cursor+=1;count|=(b&127)<<shift
            if not b&128:
                if shift and b==0:raise ValueError('Noncanonical item counter')
                break
        else:raise ValueError('Item counter overflow')
        if count>65535:raise ValueError('Item counter exceeds uint16')
    counter_end=cursor
    # Observed records either omit price/stat fields or carry four price bytes.
    if cursor==len(raw):return dict(charge_count=count,stat_values=[],counter_byte_range=[0,counter_end])
    if cursor+4>len(raw):raise ValueError('Truncated opaque price')
    cursor+=4
    if cursor==len(raw):return dict(charge_count=count,stat_values=[],counter_byte_range=[0,counter_end])
    size={0x01:1,0x3a:3}.get(raw[cursor]);cursor+=1
    if size is None:raise ValueError('Unobserved item stat-map count')
    inverse={v:int(k)for k,v in profile['stat_float_pairs'].items()};stats=[]
    for _ in range(size):
        start=cursor
        if cursor>=len(raw):raise ValueError('Truncated stat header')
        selector=raw[cursor]&7;cursor+=1
        if selector==1:value=0.0
        elif selector in (2,3,4,5):
            if cursor+4>len(raw):raise ValueError('Truncated item stat float')
            try:plain=bytes(inverse[b]for b in raw[cursor:cursor+4])
            except KeyError:raise ValueError('Unobserved item stat float byte')from None
            value=struct.unpack('<f',plain)[0];cursor+=4
            if not math.isfinite(value):raise ValueError('Nonfinite item stat')
        else:raise ValueError('Unobserved item stat selector')
        if cursor>=len(raw):raise ValueError('Truncated stat key')
        key=profile['stat_keys'].get(str(raw[cursor]));cursor+=1
        if key is None:raise ValueError('Unobserved item stat key')
        stats.append(dict(**key,value=value,modifier_byte_range=[start,cursor]))
    if cursor!=len(raw):raise ValueError('Unconsumed item modifier bytes')
    return dict(charge_count=count,stat_values=stats,counter_byte_range=[0,counter_end])
