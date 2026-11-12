"""Read flat, unobscured fog shading from a calibrated player's minimap."""
import math

import cv2
import numpy as np


def ground_classes(image, background, terrain_mask, palette, *, tolerance=14):
    """Classify homogeneous cores with agreement across a wider neighborhood.

    Colors are BGR bytes, sampled on this HUD in both shading states. The
    reference and query must agree about the surface (land or water), while
    the fog may change. 0 is unknown, 1 visible, 2 fogged. The erosion
    excludes mixed terrain, fog boundaries, icons, outlines and blended edges.
    """
    if (image.dtype != np.uint8 or background.dtype != np.uint8 or image.shape != background.shape
            or image.ndim != 3 or image.shape[2] != 3 or terrain_mask.shape != image.shape[:2]):
        raise ValueError("Incompatible minimap images or terrain mask")
    if not 0 < tolerance < 64:
        raise ValueError("Invalid color tolerance")
    evidence = np.zeros(image.shape[:2], dtype=np.uint8)
    conflicting = np.zeros(image.shape[:2], dtype=bool)
    core = np.ones((3, 3), dtype=np.uint8)
    footing = cv2.erode(terrain_mask.astype(bool).astype(np.uint8), core, borderType=cv2.BORDER_CONSTANT,
                         borderValue=0) != 0

    def close(picture, color):
        value = np.asarray(color, dtype=np.int16)
        if value.shape != (3,) or np.any((value < 0) | (value > 255)):
            raise ValueError("Invalid BGR palette color")
        return cv2.inRange(picture, np.maximum(value - tolerance, 0), np.minimum(value + tolerance, 255))

    for colors in palette.values():
        reference = close(background, colors["visible"]) | close(background, colors["fogged"])
        for status, code in (("visible", 1), ("fogged", 2)):
            current = reference & close(image, colors[status])
            center = cv2.erode(current, core, borderType=cv2.BORDER_CONSTANT, borderValue=0) != 0
            neighbors = cv2.boxFilter(current, cv2.CV_32F, (5, 5), borderType=cv2.BORDER_CONSTANT)
            selected = footing & center & (neighbors >= 255 * 0.84)
            conflicting |= selected & (evidence != 0) & (evidence != code)
            evidence[selected] = code
    evidence[conflicting] = 0
    return evidence


def minimap_point(classes, u, v):
    """Normalized coordinates use the map's upper-left corner as (0, 0)."""
    if not all(math.isfinite(value) and 0 <= value < 1 for value in (u, v)):
        raise ValueError("Normalized minimap coordinates must be in [0,1)")
    h, w = classes.shape
    x, y = int(u * w), int(v * h)
    code = int(classes[y, x])
    return dict(uv=[u, v], map_pixel_xy=[x, y], visible={0: None, 1: True, 2: False}[code],
                basis="calibrated_player_minimap_shading" if code else "unsupported_or_obscured_pixel")
