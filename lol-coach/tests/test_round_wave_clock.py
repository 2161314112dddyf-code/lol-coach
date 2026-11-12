"""Single-source, prefix-only tests of inferred birth cadence; all inputs synthetic."""
import pytest

from lol_coach.round_wave_clock import wave_clock_at


def cohorts(starts):
    rows = []
    for n, start in enumerate(starts):
        # Repeated melee and ranged units as well as a siege in between.
        for i, kind in enumerate(['melee', 'melee', 'siege', 'ranged', 'ranged']):
            rows.append((start + i / 2, n * 10 + i, kind))
    return rows


def test_forecast_uses_observed_gaps_and_collapses_individual_births():
    rows = cohorts([3, 14, 25, 38, 50, 61])
    clock = wave_clock_at(rows, at_seconds=40)
    assert clock['observed_starts'] == [14, 25, 38]
    assert clock['sample_intervals_seconds'] == [11, 13]
    assert clock['next_birth_window'] == [49, 51]
    assert clock == wave_clock_at(list(reversed(rows)) + rows, at_seconds=40)
    assert wave_clock_at(rows, at_seconds=50)['observed_starts'][-1] == 50


def test_forecast_stales_and_does_not_invent_missed_waves():
    rows = cohorts([5, 15, 25, 35])
    assert wave_clock_at(rows, at_seconds=28)['next_birth_window'] is None
    clock = wave_clock_at(rows, at_seconds=55)
    assert clock['next_birth_window'] is None
    assert clock['status'] == 'expected_birth_not_observed_in_prefix'


def test_all_melee_or_mixed_type_same_tick_do_not_create_markers():
    rows = [(10, 1, 'ranged'), (20, 2, 'melee'), (20, 3, 'ranged'),
            (30, 4, 'melee'), (40, 5, 'melee')]
    assert wave_clock_at(rows, at_seconds=40)['observed_starts'] == []


def test_history_is_bounded_and_cannot_look_ahead():
    rows = cohorts([i * 15 + 0.75 for i in range(20)])
    clock = wave_clock_at(rows, at_seconds=139)
    assert len(clock['sample_intervals_seconds']) == 5
    assert clock['next_birth_window'] == [150, 151]
    assert clock == wave_clock_at([row for row in rows if row[0] <= 139], at_seconds=139)
    assert wave_clock_at([(1, 9, 'ranged'), (8, 9, 'melee')], at_seconds=4)['observed_starts'] == []
    with pytest.raises(ValueError, match='ambiguous_minion_birth_identity'):
        wave_clock_at([(1, 9, 'ranged'), (8, 9, 'melee')], at_seconds=9)
