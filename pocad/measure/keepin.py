# kaynak: oguz-atolye tools/measure/keepin.py @ca27b1b (MIT, PoCAD'e taşındı)
"""A keep-in envelope about an axis: whether a part stays inside a cone, or any
envelope r <= R(s) about an axis, or keeps out of one, and by how much.

s is the distance along `axis` from `apex` and r the distance from the axis line.
The envelope is r <= R(s) over s_range: R(s) = tan(half_angle)·s - offset for a
cone, or any function of s given with its largest slope. A point's margin is
R(s) - r with keep="in" (the part stays inside) and r - R(s) with keep="out" (the
envelope stays free of it); positive is clear either way, and the result is the
least margin over the part.

The margin's gradient never vanishes off the axis (a unit radial term beside R'(s)
along it), so its least over the part lies on the part's surface, or, with
keep="out", on the axis, where material can fill the envelope with no surface
inside it: the axis is probed there. The margin changes by at most
L = sqrt(1 + max|R'|²) per mm, so the surface is searched cell by cell
(sampling.search_cells): a cell whose centre reads m holds nothing below m - L·reach.
A least of 0 or more is MEASURED only when every cell has been settled clear;
otherwise it is INCONCLUSIVE with its sampling bound, never a pass.
"""
from __future__ import annotations

import math
import numbers

import numpy as np

from pocad.core.shapes import edges, faces, solids
from pocad.measure.sampling import Inside, Search, edge_points, face_grid, search_cells
from pocad.result import INCONCLUSIVE, Result, inconclusive, measurement

KEEPS = ("in", "out")
AXIS_SAMPLES = 2049      # where a given R(s) is read to find where it is positive, and its slope if not given
SLOPE_MARGIN = 1.05      # a slope read from AXIS_SAMPLES is taken this much steeper
EDGE_MM = 0.02           # the edges of every face are sampled at least this finely


def _vector(value, what: str, unit: bool = False) -> np.ndarray:
    v = np.asarray(value, float).reshape(-1)
    if v.shape != (3,) or not np.all(np.isfinite(v)):
        raise ValueError(f"{what} must be a 3D vector, not {value!r}")
    if unit:
        size = float(np.linalg.norm(v))
        if size < 1e-12:
            raise ValueError(f"{what} must be a non-zero direction, not {value!r}")
        v = v / size
    return v


def _range(s_range) -> tuple[float, float]:
    lo, hi = s_range
    lo = -math.inf if lo is None else float(lo)
    hi = math.inf if hi is None else float(hi)
    if math.isnan(lo) or math.isnan(hi) or not lo < hi:
        raise ValueError(f"s_range is (low, high) with low < high, None for open, not {s_range!r}")
    return lo, hi


def _envelope(half_angle_deg, radius, max_slope, offset, lo, hi):
    """(R(s) over s_range, its largest slope, whether the slope was read, a description)."""
    if (half_angle_deg is None) == (radius is None):
        raise ValueError("give the envelope as half_angle_deg or as radius=R(s), one of them")
    if half_angle_deg is not None:
        angle = float(half_angle_deg)
        if not 0.0 < angle < 90.0:
            raise ValueError(f"half_angle_deg is in (0, 90), not {half_angle_deg!r}")
        slope = math.tan(math.radians(angle))
        return (lambda s: slope * s - offset), slope, False, f"tan({angle:g}°)·s - {offset:g}"
    if not callable(radius):
        raise ValueError(f"radius is a function of s, not {radius!r}")
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError("an envelope given as radius=R(s) needs a closed s_range")
    if max_slope is not None:
        if not (isinstance(max_slope, numbers.Real) and math.isfinite(max_slope) and max_slope >= 0):
            raise ValueError(f"max_slope is a number >= 0, not {max_slope!r}")
        return radius, float(max_slope), False, "R(s) given"
    s = np.linspace(lo, hi, AXIS_SAMPLES)
    values = np.array([float(radius(float(x))) for x in s])
    if not np.all(np.isfinite(values)):
        raise ValueError("R(s) is not finite over s_range")
    slope = float(np.max(np.abs(np.diff(values) / np.diff(s)))) * SLOPE_MARGIN
    return radius, slope, True, "R(s) given"


def _positive_spans(envelope, lo, hi, cone_start):
    """One s per stretch of s_range where R(s) > 0: where the axis is probed."""
    if cone_start is not None:                   # a cone: R > 0 past offset / tan
        start = max(lo, cone_start)
        if start >= hi:
            return []
        return [0.5 * (start + hi) if math.isfinite(hi) else start + 1.0]
    s = np.linspace(lo, hi, AXIS_SAMPLES)
    values = np.array([float(envelope(float(x))) for x in s])
    out, k = [], 0
    while k < len(s):
        if values[k] > 0:
            j = k
            while j + 1 < len(s) and values[j + 1] > 0:
                j += 1
            out.append(float(s[k + int(np.argmax(values[k:j + 1]))]))
            k = j + 1
        else:
            k += 1
    return out


@measurement("keepin_cone_free", "mm")
def keepin_cone_free(shape, apex, axis, half_angle_deg: float | None = None, *, radius=None,
                     max_slope: float | None = None, offset: float = 0.0, s_range=(None, None),
                     keep: str = "in", spacing: float = 0.5) -> Result:
    """The least margin in mm by which the part keeps to an envelope about `axis`
    through `apex`, with where it is: r <= tan(half_angle_deg)·s - offset for a cone,
    or r <= radius(s) with `max_slope` its largest |dR/ds| (read from the function,
    and taken 5 % steeper, when not given; a closed s_range is then required). s runs
    along `axis` from `apex`, the cone opening that way; only points with s in
    `s_range` (low, high), None for open, are held to it. keep="in": the margin is
    R(s) - r, how far inside the part stays; keep="out": r - R(s), how far outside
    the envelope the part's material stands. A clearance the gate asks for belongs in
    `offset` (or in radius): the search decides against 0, so the result is exact
    only against the gate `>= 0` with that clearance in `offset`. Gated against any
    other limit, a MEASURED least may lie within detail["sampling_bound_mm"] of it on
    the wrong side.

    Every face is searched on its grid at `spacing`, and its edges sampled as finely:
    each cell is bounded by its centre's margin less L·reach (L = sqrt(1 + slope²)),
    and split until it is clear or SEARCH_DEPTH or SEARCH_CELLS is spent. A cell whose
    centre lies past the face's trim is bounded from the edge samples near it too
    (sampling.search_cells): the plane beyond a rim runs on toward the envelope, the
    rim itself does not. A negative
    margin at a point of the part is MEASURED at once: the part leaves the envelope
    there, and may leave it deeper elsewhere. With keep="out", the axis is probed in
    each stretch where R(s) > 0: material there with no surface inside the envelope
    fills it, and reads -R(s) at that point. A least of 0 or more with a cell left
    unsettled could be below 0 and is INCONCLUSIVE, with detail["sampling_bound_mm"]
    how far below the least the part could still reach; settled, detail["proven_mm"]
    is the margin proven over the whole surface. INCONCLUSIVE when there is no solid,
    when no point of the part lies in s_range, or when a face is too large for the
    spacing."""
    if keep not in KEEPS:
        raise ValueError(f"keep is one of {', '.join(KEEPS)}, not {keep!r}")
    if not (isinstance(offset, numbers.Real) and math.isfinite(offset)):
        raise ValueError(f"offset is a number in mm, not {offset!r}")
    apex, direction = _vector(apex, "apex"), _vector(axis, "axis", unit=True)
    lo, hi = _range(s_range)
    envelope, slope, estimated, text = _envelope(half_angle_deg, radius, max_slope, float(offset), lo, hi)
    lipschitz = math.hypot(1.0, slope)
    params = {"apex": tuple(float(x) for x in apex), "axis": tuple(float(x) for x in direction),
              "envelope": text, "s_range": (None if math.isinf(lo) else lo, None if math.isinf(hi) else hi),
              "keep": keep, "spacing_mm": spacing, "max_slope": slope, "slope_estimated": estimated}
    found = solids(shape)
    if not found:
        return inconclusive("keepin_cone_free", "mm", "no solid to scan", **params)
    sign = 1.0 if keep == "in" else -1.0

    (ax, ay, az), (dx, dy, dz) = apex.tolist(), direction.tolist()

    def margin(point) -> tuple[float, float]:           # plain floats: it runs once per cell
        x, y, z = point.tolist()
        x, y, z = x - ax, y - ay, z - az
        s = x * dx + y * dy + z * dz
        r = math.sqrt(max(0.0, x * x + y * y + z * z - s * s))
        return sign * (float(envelope(min(max(s, lo), hi))) - r), s

    def outside(s: float) -> float:
        return max(lo - s, s - hi, 0.0)

    least, proven, step = [math.inf, None], [math.inf], 0.0
    search = Search()

    def visit(points, inside, reaches, floors):
        return [cell(p, i, float(r), float(f)) for p, i, r, f in zip(points, inside, reaches, floors)]

    def cell(point, inside, reach, floor):
        m, s = margin(point)
        if outside(s) > reach:
            return None                                 # no point of the cell lies in s_range
        if inside and outside(s) == 0.0 and m < least[0]:
            least[:] = [m, point]
        if least[0] < 0.0:
            return None                                 # the part leaves the envelope: settled
        lower = m - lipschitz * reach
        if not inside and math.isfinite(floor):         # off the face: bounded from its edge samples
            lower = max(lower, floor - lipschitz * (reach + edge_step / 2))
        if lower >= 0.0:
            proven[0] = min(proven[0], lower)
            return None
        return lower

    for solid in found:
        for face in faces(solid):
            grid = face_grid(face, spacing)
            step = max(step, grid.step_mm)
            points, edge_step = [], 0.0
            for edge in edges(face):
                samples, used = edge_points(edge, min(spacing / 4.0, EDGE_MM))
                edge_step = max(edge_step, used)
                points += [p for p, _ in samples]
            values = []
            for p in points:
                m, s = margin(p)
                values.append(m)                            # clamped past s_range: still Lipschitz
                if outside(s) == 0.0 and m < least[0]:
                    least[:] = [m, p]
            search_cells(face, grid, visit, search, edges=points, edge_step=edge_step, edge_values=values)
    detail = {"cells_visited": search.visited, "cells_split": search.split,
              "unsettled_cells": len(search.unsettled), "lipschitz": round(lipschitz, 9),
              "largest_step_mm": round(step, 6)}
    if least[0] < 0.0:
        return Result("keepin_cone_free", least[0], "mm", at=_point(least[1]), params=params, detail=detail)
    if keep == "out":
        cone_start = offset / slope if half_angle_deg is not None else None
        inside = [Inside(solid) for solid in found]
        for s in _positive_spans(envelope, lo, hi, cone_start):
            probe = apex + s * direction
            if any(check.on_or_in(probe) for check in inside):
                return Result("keepin_cone_free", -float(envelope(s)), "mm", at=_point(probe), params=params,
                              detail={**detail, "filled_at_s": s})
    if least[1] is None:
        return inconclusive("keepin_cone_free", "mm", "no point of the part lies in s_range", **params)
    at = _point(least[1])
    if search.unsettled:
        floor = min(bound for bound, _, _ in search.unsettled)
        return Result("keepin_cone_free", None, "mm", at=at, params=params, status=INCONCLUSIVE,
                      reason=f"the least, {least[0]:.4f} mm, lies within its sampling bound "
                             f"({least[0] - floor:.4f} mm) of the envelope; a finer spacing settles it",
                      detail={**detail, "least_found_mm": least[0], "sampling_bound_mm": least[0] - floor})
    return Result("keepin_cone_free", least[0], "mm", at=at, params=params,
                  detail={**detail, "proven_mm": proven[0] if math.isfinite(proven[0]) else least[0],
                          "sampling_bound_mm": least[0] - min(proven[0], least[0])})


def _point(p) -> tuple:
    return tuple(round(float(x), 6) for x in p)
