"""Cross-field evidence for refunds. Does not infer missing inventory slots."""
import math


def refund_evidence(before, after, expected):
    """Subtract earned income from balance change, with exact source times."""
    if before['entity_id'] != after['entity_id']:
        raise ValueError('Different actors')
    if before['time_seconds'] >= after['time_seconds']:
        raise ValueError('Non-increasing observation times')
    values = [row['values'].get(key) for row in (before, after)
              for key in ('current_gold', 'total_gold')]
    if any(v is None or not math.isfinite(v) for v in values) or not math.isfinite(expected) or expected <= 0:
        raise ValueError('Missing or invalid gold evidence')
    current_before, earned_before, current_after, earned_after = values
    balance_delta = current_after-current_before
    income_delta = earned_after-earned_before
    net_refund = balance_delta-income_delta
    return dict(balance_delta=balance_delta, earned_income_delta=income_delta,
                net_refund=net_refund, expected_refund=expected,
                status='PASS' if income_delta >= 0 and abs(net_refund-expected) <= 0.01 else 'FAIL',
                evidence_available_at=after['time_seconds'])
