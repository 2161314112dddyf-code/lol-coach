"""Static line-of-sight estimates for ordinary, active, ground vision sources.

The caller supplies the current position, effective sight radius and map grid.
These estimates describe a source's contribution to sight of a ground point.
Being able to see specific invisible units or reconstruct all sources for a
team requires independent observations.
"""
import math


def _ray_flags(grid, source, target):
    """Return flags on open subsegments of the ray, in order, plus both endpoints."""
    cuts = {0.0, 1.0}
    for axis, origin in enumerate((grid.bounds_min[0], grid.bounds_min[2])):
        start, end = source[axis], target[axis]
        if start == end:
            continue
        low, high = sorted((start, end))
        first = math.floor((low - origin) / grid.cell_size) + 1
        last = math.ceil((high - origin) / grid.cell_size)
        for i in range(first, last):
            crossing = (origin + i * grid.cell_size - start) / (end - start)
            if 0.0 < crossing < 1.0:
                cuts.add(crossing)
    cuts = sorted(cuts)
    times = [0.0, *((a + b) / 2 for a, b in zip(cuts, cuts[1:])), 1.0]
    cells = {}
    for time in times:
        point = [a + time * (b - a) for a, b in zip(source, target)]
        cell = grid.cell_at(*point)
        cells[cell["cell_x"], cell["cell_z"]] = cell["raw_flags"]
    return list(cells.values())


def source_coverage(grid, source_xz, target_xz, radius):
    """Estimate normal ground vision between two map positions on one base grid.

    Brush entered from outside can hide a target. For an intervening brush
    we retain uncertainty. No assumption about unobserved brush connections,
    special reveals, map overlays, team gates or stealth is used.
    """
    for point in (source_xz, target_xz):
        if len(point) != 2 or not all(math.isfinite(x) for x in point):
            raise ValueError("Expected two finite world coordinates (x,z)")
        grid.cell_at(*point)
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("Effective radius must be finite and positive")
    distance = math.dist(source_xz, target_xz)
    result = dict(distance_units=distance, radius_units=radius, cell_flags=[],
                  estimate="indeterminate", reason=None, observed_team_visibility=None)
    if distance > radius:
        result.update(estimate="outside_radius", reason="distance_exceeds_effective_radius")
        return result

    flags = _ray_flags(grid, source_xz, target_xz)
    result["cell_flags"] = flags
    if any(f & ~(1 | 2 | 4 | 64) for f in flags):
        result["reason"] = "special_or_unknown_grid_flags"
    elif any((f & (2 | 4)) and not (f & 64) for f in (flags[0], flags[-1])):
        result["reason"] = "endpoint_inside_opaque_terrain"
    elif any((f & (2 | 4)) and not (f & 64) for f in flags):
        result.update(estimate="occluded", reason="intervening_opaque_terrain")
    elif flags[-1] & 1 and not flags[0] & 1:
        result["reason"] = "target_in_brush_ground_shading_unverified"
    else:
        # A source in brush may look out. We cannot infer a distant brush's
        # group identity, or reconstruct a ray entering another patch of brush.
        first_open = next((i for i, f in enumerate(flags) if not f & 1), len(flags))
        if any(f & 1 for f in flags[first_open:]) or (flags[-1] & 1 and len(flags) > 1):
            result["reason"] = "brush_line_or_group_unresolved"
        else:
            result.update(estimate="clear", reason="within_radius_no_opaque_cell")
    return result
