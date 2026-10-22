"""Live 0x4e9 inventory observations, distinct from the 0x2ef rollback cache."""
from .replay_extensions import inventory_checkpoint
from .replay_inventory import VERSION


def decode_snapshot(opcode,payload,*,version=VERSION):
    if opcode != 0x4e9:
        raise ValueError('Only live inventory opcode 0x4e9 is supported')
    parsed=inventory_checkpoint(payload,version=version)
    if parsed['omitted_records']:
        raise ValueError('Omitted nested record has unresolved semantics')
    slots={}
    internal=[]
    for item in parsed['items']:
        if item['item_id'] is None:
            raise ValueError('Unmapped item identity')
        start,end=item['payload_range']
        raw=payload[start:end];header=int.from_bytes(raw[:3],'little')
        selector=(header>>15)&7
        charge_count={0:0,1:2,7:1}.get(selector)
        row={**item,'stack_count':item['count_candidate'],'charge_count':charge_count,
            'charge_selector':selector,
            'charge_semantics':'item_specific_counter; not universally remaining uses',
            'counter_complete':charge_count is not None and item['count_candidate'] is not None}
        if item['slot']<7:slots[item['slot']]=row
        else:internal.append(row)
    for slot in range(7):
        slots.setdefault(slot,dict(slot=slot,item_id=0,empty=True,stack_count=0,
            charge_count=0,counter_complete=True,evidence='absent from live full list'))
    return dict(slots=slots,internal_slots=internal,identities_complete=True,
        counters_complete=all(s['counter_complete'] for s in slots.values()),
        effective_time='live_packet_time',
        evidence_scope='four supplied exact-build replays; independent operation-history crosscheck',
        complete_inventory_state=False,
        limitations=['Variable charge counters and active-item cooldowns remain unresolved',
            'This full-list meaning must not be applied to 0x2ef or 0x37d'])
