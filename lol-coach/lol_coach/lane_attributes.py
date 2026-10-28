"""Bounded nonhero attribute prefixes; never use hero field layouts here."""
from .replay_state import VERSION, floating, varuint


def attribute_prefix(group, *, version=VERSION):
    if version!=VERSION:raise ValueError('Unsupported exact build')
    layouts={4:(0xffffff,11,{5,6,7},{8:'attack_damage',9:'armor',10:'magic_resistance'}),
             8:(0x3ffffff,18,{10,11,14},{0:'health',1:'max_health',17:'attack_range'}),
             32:(0xfff,5,{0,1},{4:'movement_speed'})}
    kind=group['group']
    if kind not in layouts:raise ValueError('Unsupported nonhero group')
    mask,n,integers,names=layouts[kind]
    if group['field_mask']!=mask:raise ValueError('Only full initial nonhero masks supported')
    data=bytes.fromhex(group['decoded_data_hex']);pos=0;out={}
    for bit in range(n):
        start=pos
        value,pos=varuint(data,pos,defaultable=True)if bit in integers else floating(data,pos)
        if bit in names:
            out[names[bit]]=dict(value=value,group=kind,bit=bit,
                decoded_payload_offset=group['payload_offset']+start,decoded_hex=data[start:pos].hex())
    return out


def super_crosscheck(witness):
    """Specific observed entity signature vs four 16.20 HA minion classes.

    This is retrospective cross-field classification, not a model-name decode.
    Do not insert its future witness into earlier decision snapshots.
    """
    fields={}
    for group in witness['groups']:
        try:fields.update(attribute_prefix(group))
        except ValueError:continue
    expected={'armor':60.,'magic_resistance':10.,'attack_range':170.,'movement_speed':325.}
    match=all(fields.get(name,{}).get('value')==value for name,value in expected.items())
    return dict(matched=match,fields=fields,expected=expected,
        witnessed_at=witness['first_state_time'],source=witness['source'],
        classification='super'if match else None,
        basis='Unique joint signature among four patch-16.20 HA minion CharacterRecords',
        config_url='https://raw.communitydragon.org/16.20/game/data/characters/ha_chaosminionsuper/ha_chaosminionsuper.bin.json',
        config_sha256='e8212024cac333ab74fbc53b4b868690a1d1f09ab67655b7b1e0f52189bd6337',
        config_version_scope='patch 16.20; exact platform build equivalence not independently established')
