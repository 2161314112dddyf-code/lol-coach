import pytest

from lol_coach.ngrid import Grid
from lol_coach.vision_geometry import source_coverage


def row(flags):
    return Grid((0, 0, 0), (len(flags), 1, 1), 1, len(flags), 1, tuple(flags), {})


@pytest.mark.parametrize("flags, expected", [
    ([0, 0, 0], "clear"),
    ([0, 66, 0], "clear"),
    ([0, 2, 0], "occluded"),
    ([0, 64, 1], "indeterminate"),
    ([1, 0, 0], "clear"),
    ([1, 0, 1], "indeterminate"),
    ([0, 1, 0], "indeterminate"),
    ([0, 128, 0], "indeterminate"),
    ([0, 1088, 0], "indeterminate"),
    ([2, 0, 0], "indeterminate"),
])
def test_synthetic_terrain(flags, expected):
    estimate = source_coverage(row(flags), (0.5, 0.5), (2.5, 0.5), 2)
    assert estimate["estimate"] == expected
    assert estimate["observed_team_visibility"] is None


def test_outside_range_of_this_source_does_not_hide_ground_for_team():
    result = source_coverage(row([0, 0]), (0.5, 0.5), (1.5, 0.5), 0.9)
    assert result["estimate"] == "outside_radius"
    assert result["observed_team_visibility"] is None


def test_ray_hits_short_segment_that_fixed_interval_sampling_could_miss():
    grid = Grid((0, 0, 0), (3, 1, 3), 1, 3, 3, (0, 2, 0, 0, 0, 0, 0, 0, 0), {})
    for a, b in [((0.1, 0.1), (2.11, 2.10)), ((2.11, 2.10), (0.1, 0.1))]:
        assert source_coverage(grid, a, b, 5)["estimate"] == "occluded"


@pytest.mark.parametrize("source, target, radius", [
    ((0, 0), (2, 0), 1), ((0, 0), (1, 0), float("nan")), ((float("nan"), 0), (0, 0), 10),
])
def test_invalid_inputs(source, target, radius):
    with pytest.raises(ValueError):
        source_coverage(row([0, 0]), source, target, radius)
