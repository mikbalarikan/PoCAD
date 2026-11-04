# kaynak: oguz-atolye tools/measure/assembly.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Interference and clearance between placed parts (R04 functions 7 and 8).

Both are exact on the B-rep (R04: 200.000 mm³ against 200.0; 0.300000 mm on a
0.30 mm gap). Interference is volume, so touching parts read 0 mm³; clearance is
the smallest distance between the solids, so touching parts and parts that
overlap or sit one inside the other all read 0 mm: read the two together. A
boolean that does not finish, or an unsound part, is INCONCLUSIVE
(pocad.core.common_volume). The contact that neither sees is `engaged_area`: the
area one part bears on the other, measured with a probe depth (L-22).
"""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location

from pocad.core.boolean import common_volume
from pocad.core.shapes import occ, solids
from pocad.result import INCONCLUSIVE, MEASURED, Result, measurement, register

DEPTH_SHARE = 0.01          # the probe depth is at most this share of the smaller part's least extent
TOUCH_MM = 1e-6             # parts nearer than this touch
OVERLAP_MM3 = 1e-6          # parts that share more than this overlap before the push
DEPTH_AGREEMENT = 1e-6      # the area at half the depth agrees within this share, or it is not a contact area


def interference(named: dict) -> dict[str, Result]:
    """Common volume in mm³ for every pair of the named parts, keyed "a|b". Each pair
    is pocad.core.common_volume, so an unsound part makes its pairs INCONCLUSIVE."""
    if len(named) < 2:
        raise ValueError("interference needs at least two named parts")
    out = {}
    for (a, shape_a), (b, shape_b) in combinations(named.items(), 2):
        result = common_volume(shape_a, shape_b)
        out[f"{a}|{b}"] = Result("interference", result.measured, "mm3", params={"pair": [a, b]},
                                 status=result.status, reason=result.reason, detail=result.detail)
    return out


register("interference", __name__)


@measurement("clearance", "mm")
def clearance(a, b) -> Result:
    """The smallest distance between two shapes, in mm, with the nearest points,
    measured solid by solid: given Compounds, BRepExtrema only measures between
    surfaces and reads a part inside another as the gap to its walls."""
    left, right = solids(a) or [occ(a)], solids(b) or [occ(b)]
    best = None
    for x in left:
        for y in right:
            distance = BRepExtrema_DistShapeShape(x, y)
            if not distance.IsDone() or distance.NbSolution() < 1:
                raise RuntimeError("the distance computation did not finish")
            if best is None or distance.Value() < best.Value():
                best = distance
    on_a, on_b = best.PointOnShape1(1), best.PointOnShape2(1)
    return Result("clearance", float(best.Value()), "mm",
                  at=(round(on_a.X(), 6), round(on_a.Y(), 6), round(on_a.Z(), 6)),
                  detail={"on_b": (round(on_b.X(), 6), round(on_b.Y(), 6), round(on_b.Z(), 6)),
                          "inside": bool(best.InnerSolution()),
                          "solid_pairs": len(left) * len(right)})


def _least_extent(shape) -> float:
    box = Bnd_Box()
    for solid in solids(shape):
        BRepBndLib.AddOptimal_s(solid, box, False, False)
    if box.IsVoid():
        raise ValueError("a shape without solids")
    low, high = box.CornerMin(), box.CornerMax()
    return min(high.X() - low.X(), high.Y() - low.Y(), high.Z() - low.Z())


def _pushed(shape, vector):
    move = gp_Trsf()
    move.SetTranslation(gp_Vec(*map(float, vector)))
    return occ(shape).Moved(TopLoc_Location(move))


@measurement("engaged_area", "mm2")
def engaged_area(a, b, direction, depth: float) -> Result:
    """The area in mm² over which part `a` bears on part `b` when pushed along
    `direction`: `a` is moved `depth` mm along the unit direction, and the volume it
    then shares with `b` (pocad.core.common_volume, solid by solid) is divided by the
    depth. That is the contact projected on the plane square to the direction, so a
    45° flank bears with its projected annulus, and a face parallel to the push bears
    nothing. Touching parts that interference reads as 0 mm³ give their contact area;
    parts more than `depth` apart give 0.

    `depth` has no default and must be > 0 and at most DEPTH_SHARE (1 %) of the least
    bounding-box extent of either part, so the push reaches no feature but the one
    in contact. Refused, INCONCLUSIVE:
    - parts that already share more than OVERLAP_MM3: that is interference, and an
      area read through it would count the overlap (`detail["overlap_mm3"]`);
    - parts nearer than the depth that do not touch, whose area would be part of
      one (`detail["gap_mm"]`);
    - an area that changes with the depth. Of touching faces, the pushed volume is
      the area times the depth exactly, so the area read again at half the depth
      agrees to float noise (1e-13 on the planar and conical fixtures). A face of
      `a` that lies within the depth along the push but does not touch `b` adds
      volume only once the push passes its gap, and a push that slides the contact
      along itself trims it: either way the two readings part. They must agree
      within DEPTH_AGREEMENT (1e-6 of the area), or the result is refused, with
      both readings and the linear extrapolation 2·A(d/2) − A(d) in detail. The
      extrapolation is reported, never returned: it removes a slide's trim exactly
      but only part of a near face's volume, so it is not a contact area either.
      A line or point contact has no area and is refused the same way."""
    if not (isinstance(depth, (int, float)) and not isinstance(depth, bool) and math.isfinite(depth)
            and depth > 0):
        raise ValueError(f"depth must be a number > 0 mm, not {depth!r}")
    unit = np.asarray(direction, float).reshape(3)
    norm = float(np.linalg.norm(unit))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError(f"direction must be a non-zero vector, not {direction!r}")
    unit = unit / norm
    least = min(_least_extent(a), _least_extent(b))
    params = {"direction": [round(float(x), 9) for x in unit], "depth": depth, "depth_limit": DEPTH_SHARE * least}
    if depth > DEPTH_SHARE * least:
        return Result("engaged_area", None, "mm2", params=params, status=INCONCLUSIVE,
                      reason=f"a depth of {depth:g} mm is more than {DEPTH_SHARE:.0%} of the parts' least "
                             f"extent ({least:g} mm): at most {DEPTH_SHARE * least:g}")
    gap = clearance(a, b)
    if gap.status != MEASURED:
        return Result("engaged_area", None, "mm2", params=params, status=INCONCLUSIVE,
                      reason=f"the gap cannot be measured ({gap.reason})")
    if TOUCH_MM < gap.measured < depth:
        return Result("engaged_area", None, "mm2", at=gap.at, params=params, status=INCONCLUSIVE,
                      reason=f"the parts are {gap.measured:g} mm apart, less than the depth: they do not "
                             "touch, and the push would read part of an area",
                      detail={"gap_mm": gap.measured})
    before = common_volume(a, b)
    if before.status != MEASURED:
        return Result("engaged_area", None, "mm2", params=params, status=INCONCLUSIVE,
                      reason=f"before the push: {before.reason}")
    if before.measured > OVERLAP_MM3:
        return Result("engaged_area", None, "mm2", params=params, status=INCONCLUSIVE,
                      reason=f"the parts already overlap by {before.measured:g} mm³: that is interference, "
                             "not a contact area", detail={"overlap_mm3": before.measured})
    areas = []
    for push in (depth, depth / 2):
        shared = common_volume(_pushed(a, unit * push), b)
        if shared.status != MEASURED:
            return Result("engaged_area", None, "mm2", params=params, status=INCONCLUSIVE,
                          reason=f"pushed {push:g} mm: {shared.reason}")
        areas.append((shared.measured - before.measured) / push)
    area, half = areas
    detail = {"area_at_half_depth": half, "gap_mm": gap.measured, "overlap_mm3": before.measured}
    if abs(area - half) > DEPTH_AGREEMENT * max(abs(area), abs(half)):
        return Result("engaged_area", None, "mm2", at=gap.at, params=params, status=INCONCLUSIVE,
                      reason=f"the area changes with the depth ({area:.9g} mm² at {depth:g} mm, {half:.9g} at "
                             f"{depth / 2:g}): a face within the depth along the push that does not touch, "
                             "a push that slides the contact, or a line or point contact",
                      detail={**detail, "area_at_depth": area, "extrapolated": 2 * half - area,
                              "spread": abs(area - half)})
    return Result("engaged_area", area, "mm2", at=gap.at, params=params, detail=detail)
