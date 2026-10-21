"""NGRID 7.1 structural parser. Flag meanings remain community interpretations."""
import hashlib
import math
import struct
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


FLAG_BITS = {1: "brush", 2: "wall", 4: "structure", 64: "see_through",
             128: "unknown_128", 256: "global_vision", 1024: "blue_only",
             2048: "red_only", 4096: "neutral_zone_visibility"}
KNOWN_MASK = sum(FLAG_BITS)


def flag_category(flags):
    if flags & ~KNOWN_MASK:
        return "unknown_flags"
    if flags & (1024 | 2048):
        return "team_restricted"
    if flags & (2 | 4):
        return "static_blocked_candidate"
    return "static_open_candidate"


@dataclass
class Grid:
    bounds_min: tuple
    bounds_max: tuple
    cell_size: float
    width: int
    height: int
    flags: tuple
    summary: dict

    def cell_at(self, x, z):
        if not math.isfinite(x) or not math.isfinite(z):
            raise ValueError("Coordinates must be finite")
        if not (self.bounds_min[0] <= x < self.bounds_max[0] and self.bounds_min[2] <= z < self.bounds_max[2]):
            raise ValueError("Coordinate outside declared NGRID bounds")
        cx = math.floor((x - self.bounds_min[0]) / self.cell_size)
        cz = math.floor((z - self.bounds_min[2]) / self.cell_size)
        flag = self.flags[cz * self.width + cx]
        return {"cell_x": cx, "cell_z": cz, "raw_flags": flag,
                "decoded_flags": [name for bit, name in FLAG_BITS.items() if flag & bit],
                "unknown_bits": flag & ~KNOWN_MASK, "category": flag_category(flag),
                "actual_passability": None,
                "coordinate_transform_status": "derived_from_header_not_in_game_calibrated",
                "limitations": ["Base grid only; active overlays, team gates, unit radius and dynamic obstacles are not resolved"]}


def parse_ngrid(data):
    if len(data) < 39 or data[:3] != b"\x07\x01\x00":
        raise ValueError("Only NGRID 7.1 is supported")
    values = struct.unpack_from("<7fII", data, 3)
    low, high, cell_size = values[:3], values[3:6], values[6]
    width, height = values[7:]
    if (not all(math.isfinite(v) for v in values[:7]) or cell_size <= 0 or
            not all(a < b for a, b in zip(low, high)) or not 0 < width * height <= 2_000_000):
        raise ValueError("Invalid NGRID bounds or dimensions")
    if width != math.ceil((high[0] - low[0]) / cell_size) or height != math.ceil((high[2] - low[2]) / cell_size):
        raise ValueError("Grid dimensions disagree with bounds/cell size")
    count = width * height
    flag_offset = 39 + count * 48
    height_offset = 39 + count * 54 + 1056
    if height_offset + 16 > len(data):
        raise ValueError("Truncated NGRID cell/flag blocks")
    for i in range(count):
        x, z = struct.unpack_from("<hh", data, 39 + i * 48 + 20)
        if (x, z) != (i % width, i // width):
            raise ValueError(f"Cell coordinate/order mismatch at index {i}")
    flags = struct.unpack_from(f"<{count}H", data, flag_offset)
    hw, hh, spacing_x, spacing_z = struct.unpack_from("<IIff", data, height_offset)
    if hw != 2 * width + 1 or hh != 2 * height + 1:
        raise ValueError("Unexpected height-sample dimensions")
    if not all(math.isfinite(v) and v > 0 for v in (spacing_x, spacing_z)):
        raise ValueError("Invalid height-sample spacing fields")
    samples_end = height_offset + 16 + hw * hh * 4
    hint_size = 900 * (900 * 4 + 4)
    if len(data) != samples_end + hint_size:
        raise ValueError("Unexpected NGRID length; refusing partial/unknown layout")
    heights = struct.unpack_from(f"<{hw * hh}f", data, height_offset + 16)
    if not all(math.isfinite(v) for v in heights):
        raise ValueError("Non-finite height sample")
    summary = {"format_version": "7.1", "bounds_min_xyz": list(low), "bounds_max_xyz": list(high),
               "horizontal_axes": ["x", "z"], "up_axis": "y", "cell_size_game_units": cell_size,
               "width": width, "height": height, "cell_count": count,
               "cell_order": "index=z*width+x; all stored integer coordinates verified",
               "flag_histogram": {str(k): v for k, v in sorted(Counter(flags).items())},
               "category_counts": dict(Counter(flag_category(f) for f in flags)),
               "height_samples": {"width": hw, "height": hh, "minimum": min(heights), "maximum": max(heights),
                                  "spacing_fields": [spacing_x, spacing_z], "interpolation_status": "not_implemented"},
               "layout_status": "validated_7.1", "opaque_blocks": [
                   {"offset": height_offset - 1056, "length": 1056, "meaning": "unknown_metadata"},
                   {"offset": samples_end, "length": hint_size, "meaning": "hint_matrix_not_semantically_validated"}],
               "raw_sha256": hashlib.sha256(data).hexdigest(),
               "coordinate_transform_status": "derived_from_header_not_in_game_calibrated",
               "flag_semantics_status": "community_reference_not_in_game_calibrated"}
    return Grid(low, high, cell_size, width, height, flags, summary)


def parse_overlay(data, width, height):
    if len(data) < 2 or data[0] != 1:
        raise ValueError("Only overlay format 1 is supported")
    regions, offset = [], 2
    cells_seen = set()
    overlaps = 0
    for _ in range(data[1]):
        if offset + 16 > len(data):
            raise ValueError("Truncated overlay region")
        x, z, w, h = struct.unpack_from("<4I", data, offset)
        offset += 16
        if not w or not h or x + w > width or z + h > height:
            raise ValueError("Overlay region outside base grid")
        if offset + w * h * 2 > len(data):
            raise ValueError("Truncated overlay flags")
        flags = struct.unpack_from(f"<{w*h}H", data, offset)
        offset += w * h * 2
        for dz in range(h):
            for dx in range(w):
                cell = (z + dz) * width + x + dx
                overlaps += cell in cells_seen
                cells_seen.add(cell)
        regions.append({"x": x, "z": z, "width": w, "height": h, "flags": list(flags)})
    tail = data[offset:]
    if len(tail) not in (0, 1):
        raise ValueError("Unexpected overlay trailing data")
    return {"format_version": 1, "region_count": data[1], "regions": regions,
            "covered_cell_count": len(cells_seen), "overlapping_cell_writes": overlaps,
            "trailing_bytes_hex": tail.hex(), "trailing_bytes_meaning": "unknown" if tail else "absent",
            "validation_status": "regions_decoded_tail_preserved",
            "application_status": "not_applied_unknown_tail_and_runtime_composition",
            "raw_sha256": hashlib.sha256(data).hexdigest()}


def render_flags_png(grid, output, scale=3):
    """Exact per-cell raster, +Z up. No synthetic terrain or smoothing."""
    palette = {"unknown_flags": (233, 77, 203), "team_restricted": (88, 129, 244),
               "static_blocked_candidate": (45, 51, 61), "static_open_candidate": (230, 233, 225)}
    rows = []
    for z in range(grid.height - 1, -1, -1):
        row = bytearray()
        for x in range(grid.width):
            flags = grid.flags[z * grid.width + x]
            color = palette[flag_category(flags)]
            if flag_category(flags) == "static_open_candidate" and flags & 1:
                color = (53, 132, 81)
            row.extend(bytes(color) * scale)
        rows.extend([b"\0" + bytes(row)] * scale)
    def chunk(name, body):
        return struct.pack(">I", len(body)) + name + body + struct.pack(">I", zlib.crc32(name + body))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", grid.width * scale, grid.height * scale, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")
    Path(output).write_bytes(png)
