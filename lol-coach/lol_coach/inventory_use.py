"""Observed 16.20 item-use result fields; does not infer item cooldowns."""
from .replay_inventory import VERSION


def decode_use(payload, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported exact build')
    if len(payload) < 2:
        raise ValueError('Truncated item-use header')
    header = int.from_bytes(payload[:2], 'little')
    if header & ~0x1ff != 0xb600:
        raise ValueError('Unobserved item-use header')
    selector = (header >> 6) & 7
    slot = {4: 0, 1: 1, 7: 2}.get(selector)
    cursor = 2
    if slot is None:
        if selector not in (0, 2, 3, 6) or len(payload) < 3:
            raise ValueError('Unobserved item-use slot')
        slot = {0xda: 6}.get(payload[2])
        cursor += 1
        if slot is None:
            raise ValueError('Unknown item-use slot byte')
    stacks = {1: 0, 0: 1, 6: 2}.get((header >> 3) & 7)
    charge_selector = header & 7
    if stacks is None or charge_selector not in (3, 4, 5):
        raise ValueError('Unobserved item-use counter')
    if len(payload) != cursor:
        raise ValueError('Unconsumed item-use bytes')
    return dict(slot=slot, stack_count=stacks,
        remaining_charges={5: 1, 3: 0}.get(charge_selector),
        charge_status='no_charge_counter' if charge_selector == 4 else 'observed_remaining',
        clears_slot=stacks == 0, opcode='0x3f1',
        cooldown_seconds=None)
