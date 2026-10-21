"""Exact-build structural replication evidence, deliberately not resolved identities."""
import math

from .replay_state import VERSION, floating


def is_initial_layout(record):
    return record['group_mask'] == 68 and {
        g['group']: g['field_mask'] for g in record['groups']
    } == {4: 4095, 64: 3}


def health_candidates(record, *, version=VERSION):
    """Caller must first establish the initial layout; never use on arbitrary units."""
    if version != VERSION:
        raise ValueError('Unsupported replay version')
    values = {}; fields = []
    for group in record['groups']:
        if group['group'] != 4:
            continue
        data = bytes.fromhex(group['decoded_data_hex']); cursor = 0
        for bit, name in ((0, 'health_candidate'), (1, 'max_health_candidate')):
            if not group['field_mask'] & (1 << bit):
                continue
            start = cursor
            value, cursor = floating(data, cursor)
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid structural health candidate')
            values[name] = value
            fields.append(dict(field=name, group=4, bit=bit,
                decoded_payload_offset=group['payload_offset'] + start,
                byte_length=cursor-start, decoded_hex=data[start:cursor].hex()))
    return values, fields


def state_observation(payload, *, version=VERSION):
    if version != VERSION:
        raise ValueError('Unsupported replay version')
    if len(payload) != 1:
        raise ValueError('Unknown structural state layout')
    # Labels are correlations from this build, not a decoded public game enum.
    correlation = {
        0x8d: 'observed_with_positive_health',
        0x9c: 'transition_followed_by_zero_health',
        0x9d: 'checkpoint_with_zero_health',
    }.get(payload[0])
    return dict(raw_code=payload[0], raw_hex=payload.hex(),
                research_correlation=correlation, authoritative_state=None)


def prefix_evidence(bundle, cutoff):
    if not math.isfinite(cutoff) or cutoff < 0:
        raise ValueError('Invalid cutoff')
    result = {}
    for event in sorted(bundle['discoveries'], key=lambda x: x['order']):
        if event['time_seconds'] <= cutoff:
            result.setdefault(event['entity_id'], dict(discovery=event,
                latest_samples={}, latest_state=None, identity=None, team=None))
    for sample in sorted(bundle['health_samples'], key=lambda x: x['order']):
        if sample['time_seconds'] > cutoff or sample['entity_id'] not in result:
            continue
        entry = result[sample['entity_id']]
        if sample['order'] < entry['discovery']['order']:
            continue
        for key, value in sample['values'].items():
            entry['latest_samples'][key] = dict(value=value,
                observed_at=sample['time_seconds'], source=sample['source'])
    for event in sorted(bundle['state_observations'], key=lambda x: x['order']):
        if event['time_seconds'] > cutoff or event['entity_id'] not in result:
            continue
        entry = result[event['entity_id']]
        # The raw opcode can precede replication discovery; it stays in the
        # bundle, but is never retroactively inserted into a prefix state.
        if event['order'] >= entry['discovery']['order']:
            entry['latest_state'] = event
    return dict(schema='structure-evidence-prefix/v1', cutoff=cutoff,
        source=bundle['source'], version=bundle['version'], objects=result,
        decision_input_eligible=False, visibility=None,
        limitation='Research observations; identity, team and observer visibility unresolved')
