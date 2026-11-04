# kaynak: oguz-atolye tools/measure/band.py @ca27b1b (MIT, PoCAD'e taşındı)
"""What a cylindrical band keeps where slots interrupt it: the total arc a bore's
or a boss's own cylinder retains at every height of a band, and its runs (the
fidget-tetra job's REQ-12 c: a spigot centred on a band that entry slots and a
relief cut into).

The band is the part's cylindrical faces of `radius` about the axis. At each
station along the axis the circle of the band is cut from them exactly: the line
of that height in each face's own parameters (u is the angle, v the height) meets
the face's edges at the ends of its arcs, and each arc between is on the face or
off it. So a station's runs are exact, and the result is the least total over the
stations, with the runs where it is least.

Between stations the arc is bounded rather than sampled. Stations sit on a grid of
cells no longer than z_step, and just either side of every height where the band's
own edges turn (their ends, and where they run level or turn back in angle), so
between two neighbouring stations every run's two ends move one way each: a run
keeps at least the overlap of its readings at the two, and the band at least their
sum. Where the runs of two stations cannot be paired one to one, or the bound
could fall below min_total_deg, the interval is split, down to BISECT_MM; what
cannot be settled leaves the result INCONCLUSIVE, never a pass.
"""
from __future__ import annotations

import math
import numbers

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d, BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.Geom2d import Geom2d_Line, Geom2d_TrimmedCurve
from OCP.Geom2dAPI import Geom2dAPI_InterCurveCurve
from OCP.gp import gp_Dir2d, gp_Pnt2d
from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT

from pocad._ocp import FClass2d
from pocad.core.shapes import edges, faces, solids
from pocad.measure.features import _fit
from pocad.measure.radial import Axis
from pocad.measure.sampling import kind
from pocad.result import INCONCLUSIVE, Result, inconclusive, measurement

NUDGE_MM = 1e-5          # a station sits this far either side of a height where the band's edges turn
BISECT_MM = 1e-3         # an interval between stations is split no finer than this
MAX_STATIONS = 20_000    # stations one band may read, splits included
EDGE_SAMPLES = 64        # where an edge of the band is read for its turning heights, then refined
TOUCH_DEG = 1e-7         # runs this close on the circle are one
CLASSIFY_POINTS = 7      # points along an arc of a station where it is classified on or off its face


class _OnEdge(ValueError):
    """A station that runs along an edge of the band."""


def _default_ref(direction: np.ndarray) -> np.ndarray:
    basis = np.eye(3)[int(np.argmin(np.abs(direction)))]
    ref = np.cross(direction, basis)
    return ref / np.linalg.norm(ref)


class _Band:
    """The band's faces in the axis's frame, and the section of them at a height."""

    def __init__(self, axis: Axis, found: list):
        self.axis, self.faces = axis, []
        for face in found:
            cyl = BRepAdaptor_Surface(face).Cylinder()
            loc, d = cyl.Axis().Location(), cyl.Axis().Direction()
            self.faces.append({"face": face, "loc": np.array([loc.X(), loc.Y(), loc.Z()]),
                               "dir": np.array([d.X(), d.Y(), d.Z()]), "uv": BRepTools.UVBounds_s(face),
                               "surface": BRepAdaptor_Surface(face),
                               "inside": FClass2d(face, 1e-7),
                               "curves": [self._pcurve(edge, face) for edge in edges(face)]})

    @staticmethod
    def _pcurve(edge, face):
        span = BRepAdaptor_Curve2d(edge, face)
        return Geom2d_TrimmedCurve(BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0),
                                   span.FirstParameter(), span.LastParameter())

    def angle(self, point: np.ndarray) -> float:
        w = point - self.axis.origin
        return math.degrees(math.atan2(float(np.dot(w, self.axis.side)), float(np.dot(w, self.axis.ref))))

    def height(self, point: np.ndarray) -> float:
        return float(np.dot(point - self.axis.origin, self.axis.axis))

    @staticmethod
    def _on_face(f, a: float, b: float, v: float, z: float) -> bool:
        """Whether the arc from u = a to b at height v lies on the face: classified at
        CLASSIFY_POINTS points along it, a point ON the boundary (a small hole's edge
        passing near one) counting for neither side. Points IN and OUT together mean a
        cut was missed, and the station cannot be read."""
        states = {f["inside"].Perform(gp_Pnt2d(a + (b - a) * k / (CLASSIFY_POINTS + 1), v))
                  for k in range(1, CLASSIFY_POINTS + 1)} - {TopAbs_ON}
        if states == {TopAbs_IN}:
            return True
        if states <= {TopAbs_OUT}:
            return False
        raise ValueError(f"an arc of the band at {z:.6f} mm lies both on and off its face: a cut was missed")

    def runs(self, z: float) -> list[tuple[float, float]]:
        """The band's runs at height z, (start, length) in degrees about the axis,
        merged across faces and the seam; raises _OnEdge on an edge of the band."""
        at = self.axis.origin + z * self.axis.axis
        arcs = []
        for f in self.faces:
            u0, u1, v0, v1 = f["uv"]
            v = float(np.dot(at - f["loc"], f["dir"]))
            if not v0 - 1e-9 <= v <= v1 + 1e-9:
                continue
            line = Geom2d_Line(gp_Pnt2d(0.0, v), gp_Dir2d(1.0, 0.0))
            cuts = [u0, u1]
            for curve in f["curves"]:
                meet = Geom2dAPI_InterCurveCurve(curve, line, 1e-9)
                if meet.NbSegments():
                    raise _OnEdge(f"the station at {z:.6f} mm runs along an edge of the band")
                cuts += [meet.Point(i).X() for i in range(1, meet.NbPoints() + 1)]
            cuts = sorted(c for c in cuts if u0 - 1e-9 <= c <= u1 + 1e-9)
            turn = float(np.dot(f["dir"], self.axis.axis)) > 0
            for a, b in zip(cuts, cuts[1:]):
                if b - a <= 1e-12 or not self._on_face(f, a, b, v, z):
                    continue
                p = f["surface"].Value(a if turn else b, v)
                arcs.append((self.angle(np.array([p.X(), p.Y(), p.Z()])), math.degrees(b - a)))
        return _merge(arcs)


def _merge(arcs: list) -> list[tuple[float, float]]:
    """Arcs on the circle, (start, length) in degrees, merged where they touch."""
    if not arcs:
        return []
    arcs = sorted(((start % 360.0, length) for start, length in arcs))
    out = [list(arcs[0])]
    for start, length in arcs[1:]:
        end = out[-1][0] + out[-1][1]
        if start <= end + TOUCH_DEG:
            out[-1][1] = max(end, start + length) - out[-1][0]
        else:
            out.append([start, length])
    if len(out) > 1 and out[-1][0] + out[-1][1] >= out[0][0] + 360.0 - TOUCH_DEG:
        last = out.pop()
        out[0] = [last[0], max(last[0] + last[1], out[0][0] + 360.0 + out[0][1]) - last[0]]
    if any(length >= 360.0 - TOUCH_DEG for _, length in out):
        return [(0.0, 360.0)]
    return [(start % 360.0, length) for start, length in out]


def _total(runs) -> float:
    return min(360.0, sum(length for _, length in runs))


def _paired(a: list, b: list) -> float | None:
    """The least the band can keep between two stations whose runs pair one to one
    (each run of one overlaps exactly one of the other): the sum of each pair's
    overlap, every run's ends moving one way between them. None when they do not pair."""
    if len(a) != len(b):
        return None
    if a == [(0.0, 360.0)] or b == [(0.0, 360.0)]:
        return 360.0 if a == b else None
    total, used = 0.0, set()
    for start_a, length_a in a:
        hits = []
        for j, (start_b, length_b) in enumerate(b):
            start = start_a + ((start_b - start_a + 180.0) % 360.0) - 180.0
            overlap = min(start_a + length_a, start + length_b) - max(start_a, start)
            if overlap > 0.0:
                hits.append((j, overlap))
        if len(hits) != 1 or hits[0][0] in used:
            return None
        used.add(hits[0][0])
        total += hits[0][1]
    return total


def _turning_heights(band: _Band, lo: float, hi: float) -> list[float]:
    """Heights within (lo, hi) where an edge of the band ends, runs level, or turns
    back in angle: its vertices and the extremes of its height and of its angle along
    it, each refined by a golden-section search on the edge's parameter."""
    out = []
    for f in band.faces:
        for edge in edges(f["face"]):
            curve = BRepAdaptor_Curve(edge)
            first, last = curve.FirstParameter(), curve.LastParameter()

            def point(t):
                p = curve.Value(t)
                return np.array([p.X(), p.Y(), p.Z()])

            ts = np.linspace(first, last, EDGE_SAMPLES + 1)
            points = [point(float(t)) for t in ts]
            out += [band.height(points[0]), band.height(points[-1])]
            heights = np.array([band.height(p) for p in points])
            angles = np.unwrap(np.radians([band.angle(p) for p in points]))
            for series, read in ((heights, lambda t: band.height(point(t))),
                                 (angles, lambda t: math.radians(band.angle(point(t))))):
                for k in range(1, EDGE_SAMPLES):
                    left, mid, right = series[k - 1], series[k], series[k + 1]
                    if (mid - left) * (right - mid) < 0.0:
                        t = _golden(read, float(ts[k - 1]), float(ts[k + 1]), mid > left, series is angles)
                        out.append(band.height(point(t)))
    return sorted(z for z in out if lo < z < hi)


def _golden(read, a: float, b: float, peak: bool, wrap: bool) -> float:
    """The parameter of the extreme of read(t) between a and b (a peak or a trough)."""
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    first = read(a)

    def value(t):
        v = read(t)
        if wrap:                                        # an angle, taken on the branch of the bracket
            v = first + ((v - first + math.pi) % (2 * math.pi)) - math.pi
        return v if peak else -v

    for _ in range(80):
        c, d = b - ratio * (b - a), a + ratio * (b - a)
        if value(c) > value(d):
            b = d
        else:
            a = c
        if b - a < 1e-13 * max(1.0, abs(a)):
            break
    return 0.5 * (a + b)


def _coaxial(location, direction, radius, axis: Axis, want: float, tol: float) -> bool:
    if float(np.linalg.norm(np.cross(direction, axis.axis))) > 1e-6:
        return False
    w = location - axis.origin
    off = float(np.linalg.norm(w - float(np.dot(w, axis.axis)) * axis.axis))
    return off <= tol and abs(radius - want) <= tol


@measurement("retained_arc", "deg")
def retained_arc(shape, axis, radius: float, z_range, *, min_total_deg: float, ref_dir=None,
                 run_floor_deg: float = 0.0, tol: float = 1e-3, z_step: float = 0.1) -> Result:
    """The least total arc in degrees that the band of `radius` about `axis`
    ((origin, direction)) retains at any height of `z_range` (z_low, z_high) along
    it, with where the band is most broken: `at` is the middle of the widest gap at
    that height. The band is every analytic cylindrical face within `tol` of that
    radius and coaxial within `tol`, a bore or a boss alike; angles turn from
    `ref_dir` (any square direction when not given) by the right-hand rule.

    Each station's runs are cut exactly (see the module), and between stations the
    total is bounded from below by the overlap of paired runs; min_total_deg, which
    has no default, is where that bound is held: an interval that could fall below it
    is split down to BISECT_MM, and a least at or above it with any interval left
    below is INCONCLUSIVE, detail["sampling_bound_deg"] how far below the least the
    band could still fall. Across a height where the band's own edges end (a slot's
    top), the section either side stands for it. detail gives, at the height of the
    least, the runs as [start, length] ("runs_deg") and the longest ("longest_run_deg"),
    and over every station the least longest run ("least_longest_run_deg") and the
    fewest runs of at least `run_floor_deg` where the band is broken at all
    ("fewest_runs_over_floor", None where it never is).

    INCONCLUSIVE when there is no solid, no such face, a freeform face lying on the
    band (only analytic cylinders are cut exactly), or more than MAX_STATIONS."""
    origin, direction = (np.asarray(v, float).reshape(3) for v in axis)
    unit = direction / np.linalg.norm(direction)
    frame = Axis(origin, unit, _default_ref(unit) if ref_dir is None else ref_dir)
    lo, hi = (float(x) for x in z_range)
    for value, what in ((radius, "radius"), (tol, "tol"), (z_step, "z_step")):
        if not (isinstance(value, numbers.Real) and math.isfinite(value) and value > 0):
            raise ValueError(f"{what} must be a positive number, not {value!r}")
    if not (math.isfinite(lo) and math.isfinite(hi) and hi - lo > 4 * NUDGE_MM):
        raise ValueError(f"z_range is (z_low, z_high) with z_low < z_high, not {z_range!r}")
    if not (isinstance(min_total_deg, numbers.Real) and 0.0 < min_total_deg <= 360.0):
        raise ValueError(f"min_total_deg is an angle in (0, 360], not {min_total_deg!r}")
    params = {"axis_origin": tuple(float(x) for x in frame.origin), "axis_dir": tuple(float(x) for x in frame.axis),
              "ref_dir": tuple(float(x) for x in frame.ref), "radius": float(radius), "z_range": (lo, hi),
              "min_total_deg": float(min_total_deg), "run_floor_deg": float(run_floor_deg), "tol_mm": tol,
              "z_step": z_step}
    found = solids(shape)
    if not found:
        return inconclusive("retained_arc", "deg", "no solid to scan", **params)
    chosen, freeform = [], 0
    for solid in found:
        for face in faces(solid):
            if kind(face) == "cylinder":
                cyl = BRepAdaptor_Surface(face).Cylinder()
                loc, d = cyl.Axis().Location(), cyl.Axis().Direction()
                if _coaxial(np.array([loc.X(), loc.Y(), loc.Z()]), np.array([d.X(), d.Y(), d.Z()]),
                            cyl.Radius(), frame, radius, tol):
                    chosen.append(face)
            elif kind(face) in ("bspline", "other"):
                fitted = _fit(face)
                if fitted and fitted[0] == "cylinder":
                    loc, d = fitted[1].Axis().Location(), fitted[1].Axis().Direction()
                    freeform += _coaxial(np.array([loc.X(), loc.Y(), loc.Z()]), np.array([d.X(), d.Y(), d.Z()]),
                                         fitted[1].Radius(), frame, radius, tol)
    if freeform:
        return inconclusive("retained_arc", "deg", f"{freeform} freeform faces lie on the band; only analytic "
                            "cylinders are cut exactly", **params)
    if not chosen:
        return inconclusive("retained_arc", "deg", f"no cylindrical face of radius {radius:g} mm about the axis",
                            **params)
    band = _Band(frame, chosen)
    turning = _turning_heights(band, lo, hi)
    cells = max(1, math.ceil((hi - lo) / z_step - 1e-9))
    grid = [lo + (i + 0.5) * (hi - lo) / cells for i in range(cells)]
    grid = [z for z in grid if all(abs(z - c) > NUDGE_MM for c in turning)]
    near = [c + s * NUDGE_MM for c in turning for s in (-1.0, 1.0)]
    stations = sorted({z for z in grid + near + [lo + NUDGE_MM, hi - NUDGE_MM] if lo < z < hi})
    read = {z: band.runs(z) for z in stations}
    pending, lows, unsettled = list(zip(stations, stations[1:])), [], 0
    while pending:
        a, b = pending.pop()
        ta, tb = _total(read[a]), _total(read[b])
        low = _paired(read[a], read[b])
        if low is None and b - a <= 2.5 * NUDGE_MM and any(a < c < b for c in turning):
            low = min(ta, tb)                              # across the band's own edge
        if (low is None or low < min_total_deg <= min(ta, tb)) and b - a > BISECT_MM:
            if len(read) >= MAX_STATIONS:
                raise ValueError(f"the band needs more than {MAX_STATIONS} stations to settle")
            m = 0.5 * (a + b)
            read[m] = band.runs(m)
            pending += [(a, m), (m, b)]
            continue
        if low is None:
            low, unsettled = 0.0, unsettled + 1
        lows.append(low)
    return _result(frame, radius, read, lows, unsettled, len(turning), len(chosen), params)


def _result(frame: Axis, radius: float, read: dict, lows: list, unsettled: int, turning: int, found: int,
            params: dict) -> Result:
    z, runs = min(read.items(), key=lambda item: (_total(item[1]), item[0]))
    least = _total(runs)
    floor = params["run_floor_deg"]
    gap_mid = 0.0
    if runs and runs != [(0.0, 360.0)]:
        ordered = sorted(runs)
        gaps = [((ordered[(i + 1) % len(ordered)][0] - (s + l)) % 360.0, s + l) for i, (s, l) in enumerate(ordered)]
        width, start = max(gaps)
        gap_mid = start + width / 2.0
    a = math.radians(gap_mid)
    at = frame.origin + z * frame.axis + radius * (math.cos(a) * frame.ref + math.sin(a) * frame.side)
    lower = min(lows, default=least)
    detail = {"z": round(z, 9), "runs_deg": [[round(s, 6), round(l, 6)] for s, l in sorted(runs, key=lambda r: -r[1])],
              "longest_run_deg": round(max((l for _, l in runs), default=0.0), 6), "runs": len(runs),
              "least_longest_run_deg": round(min(max((l for _, l in r), default=0.0) for r in read.values()), 6),
              "fewest_runs_over_floor": min((sum(1 for _, l in r if l >= floor) for r in read.values()
                                             if r != [(0.0, 360.0)]), default=None),
              "stations": len(read), "turning_heights": turning, "faces": found, "unpaired_intervals": unsettled,
              "sampling_bound_deg": round(max(0.0, least - lower), 6)}
    at = tuple(round(float(x), 6) for x in at)
    if least >= params["min_total_deg"] and lower < params["min_total_deg"]:
        return Result("retained_arc", None, "deg", at=at, params=params, status=INCONCLUSIVE,
                      reason=f"the least, {least:.4f}°, lies within its sampling bound ({least - lower:.4f}°) "
                             f"above min_total_deg; the band could fall below it between stations",
                      detail={**detail, "least_found_deg": least})
    return Result("retained_arc", least, "deg", at=at, params=params, detail=detail)
