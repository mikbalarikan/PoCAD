# kaynak: oguz-atolye tools/measure/radial.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Radial probes of rotational parts: where the material ends on a ray from an axis,
at an angle and an axial position together (L-09, L-22).

A snap-fit's release reliefs stopped at z = -5.0 against the shell's rim at -8.6, so they
relieved 3.25 mm of a 7.4 mm extraction stroke, and the designer's check passed 36/36 because it swept the angle at one height only (L-09); the
reviewer found DEFECT-01 by reading the shell's outer radius as a function of
height at a lock angle and a release angle. A press-turn joint
is a function of rotation and axial position, so `radial_profile` sweeps both on
one grid, and its window is the nominal band widened by a stated margin: a window
exactly at the nominal cut sees the cut everywhere and nothing past its ends
(L-22). The window cannot run past the part's end, where a ray finds nothing: to
widen toward one end only, give the margin as (0, x) or (x, 0).

A ray may cross more than one stretch of material (a pin inside a tube, a base's
inner wall inside the ring that carries its bead): `r_min` and `r_max` bound the
annulus meant, and a stretch that crosses either bound is refused rather than cut.

A radius is found exactly on the B-rep: the ray from the axis is intersected with
every face of each solid (IntCurvesFace and BRepIntCurveSurface together, since
either can lose a grazing hit), and each stretch between hits is classified at its
middle against its own solid (sampling.Inside). No tessellation is involved.
"""
from __future__ import annotations

import math
import numbers

import numpy as np
from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_IN, TopAbs_ON

from pocad.core.shapes import solids
from pocad.measure.sampling import Inside
from pocad.result import INCONCLUSIVE, Result, measurement, measurement_set

SIDES = ("outer", "inner")
MERGE = 1e-9            # mm: hits closer than this along a ray are one crossing
MAX_RAYS = 20_000       # angles x levels in one profile; more is refused, never thinned
SQUARE_DEG = 1.0        # ref_dir may lean at most this far off square to the axis
FACE_EPS_DEG = 1e-3     # a ray along a face is read again this far either side in angle
PROFILE = {"max": ("radial_profile_max", "mm"), "min": ("radial_profile_min", "mm")}


class NoMaterial(ValueError):
    """A ray from the axis that meets no material."""


class OnFace(ValueError):
    """A ray that runs along a face, where IN and OUT cannot be told apart."""


class Crossing(ValueError):
    """A stretch of material that crosses a bound of the radial window."""


def _unit(vector, what: str) -> np.ndarray:
    v = np.asarray(vector, float).reshape(3)
    norm = float(np.linalg.norm(v))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError(f"{what} must be a non-zero vector, not {vector!r}")
    return v / norm


class Axis:
    """An axis with its angular reference: `ref_dir` must lie within SQUARE_DEG of
    square to `axis_dir` (the small lean left is taken out, never a large one), and
    an angle turns from it about `axis_dir` by the right-hand rule."""

    def __init__(self, origin, axis_dir, ref_dir):
        self.origin = np.asarray(origin, float).reshape(3)
        self.axis = _unit(axis_dir, "axis_dir")
        ref = _unit(ref_dir, "ref_dir")
        lean = math.degrees(math.asin(min(1.0, abs(float(np.dot(ref, self.axis))))))
        if lean > SQUARE_DEG:
            raise ValueError(f"ref_dir leans {lean:.3g}° off square to the axis; at most {SQUARE_DEG:g}°")
        self.lean_deg = lean
        ref = ref - float(np.dot(ref, self.axis)) * self.axis
        self.ref = _unit(ref, "ref_dir square to the axis")
        self.side = np.cross(self.axis, self.ref)

    def ray(self, angle_deg: float, z: float) -> tuple[np.ndarray, np.ndarray]:
        a = math.radians(angle_deg)
        return self.origin + z * self.axis, math.cos(a) * self.ref + math.sin(a) * self.side


class Probe:
    """The solids of a shape, each loaded once for rays and for classification."""

    def __init__(self, shape):
        self.solids = solids(shape)
        if not self.solids:
            raise ValueError("a shape without solids")
        self.loaded = []
        for solid in self.solids:
            intersector = IntCurvesFace_ShapeIntersector()
            intersector.Load(solid, 1e-7)
            self.loaded.append((solid, intersector, Inside(solid)))

    def intervals(self, start: np.ndarray, direction: np.ndarray) -> list[tuple[float, float]]:
        """The stretches of the ray, as (from, to) distances from `start` in mm, that
        run through material, over every solid, sorted."""
        out = []
        for solid, intersector, inside in self.loaded:
            line = gp_Lin(gp_Pnt(*map(float, start)), gp_Dir(*map(float, direction)))
            hits = set()
            intersector.Perform(line, 0.0, 1e9)
            if intersector.IsDone():
                hits.update(intersector.WParameter(j) for j in range(1, intersector.NbPnt() + 1))
            crossing = BRepIntCurveSurface_Inter()
            crossing.Init(solid, line, 1e-7)
            while crossing.More():
                hits.add(crossing.W())
                crossing.Next()
            stops = [0.0]
            for w in sorted(h for h in hits if h > MERGE):
                if w - stops[-1] > MERGE:
                    stops.append(w)
            stops.append(stops[-1] + 1.0)
            for low, high in zip(stops, stops[1:]):
                state = inside.state(start + 0.5 * (low + high) * direction)
                if state == TopAbs_ON:
                    raise OnFace(f"the ray runs along a face between {low:.6f} and {high:.6f} mm")
                if state == TopAbs_IN:
                    if out and abs(out[-1][1] - low) <= MERGE and out[-1][2] is solid:
                        out[-1] = (out[-1][0], high, solid)
                    else:
                        out.append((low, high, solid))
        return sorted((low, high) for low, high, _ in out)

    def extent(self, axis: Axis, angle_deg: float, z: float, side: str, window=(0.0, None)):
        """(radius, point, material intervals) on the ray at (angle, z), counting only
        the stretches inside the radial window (r_min, r_max); one that crosses a
        bound is refused, since cutting it there would read the bound as a wall."""
        start, direction = axis.ray(angle_deg, z)
        intervals = self.intervals(start, direction)
        r_min, r_max = window
        top = math.inf if r_max is None else r_max
        for low, high in intervals:
            for bound in (r_min, top):
                if low + MERGE < bound < high - MERGE:
                    raise Crossing(f"material from {low:.6f} to {high:.6f} mm crosses the window's bound "
                                   f"at {bound:g} mm at {angle_deg:g}° and z = {z:g} mm")
        inside = [(low, high) for low, high in intervals if low >= r_min - MERGE and high <= top + MERGE]
        if not inside:
            raise NoMaterial(f"no material between {r_min:g} and {top:g} mm on the ray at {angle_deg:g}° "
                             f"and z = {z:g} mm")
        radius = max(high for _, high in inside) if side == "outer" else min(low for low, _ in inside)
        return radius, start + radius * direction, intervals


def _side(side: str) -> str:
    if side not in SIDES:
        raise ValueError(f"side is one of {', '.join(SIDES)}, not {side!r}")
    return side


def _window(r_min, r_max) -> tuple[float, float | None]:
    ok = isinstance(r_min, numbers.Real) and math.isfinite(r_min) and r_min >= 0
    ok = ok and (r_max is None or (isinstance(r_max, numbers.Real) and math.isfinite(r_max) and r_max > r_min))
    if not ok:
        raise ValueError(f"the radial window is 0 <= r_min < r_max (r_max None: the whole ray), "
                         f"not ({r_min!r}, {r_max!r})")
    return float(r_min), None if r_max is None else float(r_max)


def _point(p) -> tuple:
    return tuple(round(float(x), 6) for x in p)


@measurement("radial_extent", "mm")
def radial_extent(shape, axis_origin, axis_dir, ref_dir, angle_deg: float, z: float,
                  side: str = "outer", r_min: float = 0.0, r_max: float | None = None) -> Result:
    """The outermost (or, with side="inner", innermost) material radius in mm on the
    ray from the axis at `angle_deg` from `ref_dir` and at `z` mm along `axis_dir`
    from `axis_origin`, by exact line-solid intersection, over the material between
    `r_min` and `r_max` (the whole ray by default). Where the ray crosses more than
    one stretch of material, say which annulus is meant: the innermost material of a
    tube with a pin in it is the pin, and of a base with an inner wall inside its
    bead ring the wall, not the bead's tip. INCONCLUSIVE when the window holds no
    material, when a stretch crosses one of its bounds, or when the ray runs along
    a face (move the level or the angle off it)."""
    side = _side(side)
    window = _window(r_min, r_max)
    axis = Axis(axis_origin, axis_dir, ref_dir)
    radius, point, intervals = Probe(shape).extent(axis, float(angle_deg), float(z), side, window)
    return Result("radial_extent", radius, "mm", at=_point(point),
                  params={"angle_deg": float(angle_deg), "z": float(z), "side": side,
                          "r_min": window[0], "r_max": window[1], "ref_lean_deg": axis.lean_deg,
                          "axis_origin": _point(axis.origin), "axis_dir": _point(axis.axis),
                          "ref_dir": _point(axis.ref)},
                  detail={"material": [[round(a, 9), round(b, 9)] for a, b in intervals]})


def _margin(margin) -> tuple[float, float]:
    pair = (margin, margin) if isinstance(margin, numbers.Real) else tuple(margin)
    if len(pair) != 2 or not all(isinstance(m, numbers.Real) and math.isfinite(m) and m >= 0 for m in pair):
        raise ValueError(f"margin is a number >= 0 or (below, above), not {margin!r}")
    return float(pair[0]), float(pair[1])


@measurement_set("radial_profile", PROFILE)
def radial_profile(shape, axis_origin, axis_dir, ref_dir, angles_deg, band, *, margin,
                   z_step: float = 0.1, side: str = "outer", r_min: float = 0.0,
                   r_max: float | None = None) -> dict[str, Result]:
    """radial_extent over every angle in `angles_deg` at every level of a window along
    the axis: the nominal `band` (z_low, z_high) widened by `margin` mm at each end,
    or by (below, above). The margin has no default: a window exactly at the nominal
    cut sees the cut everywhere and nothing past its ends (L-22), so the caller states
    how far past the band the part must be read, and a margin of 0 is a statement
    too. The window stops at the part's end, where a ray finds nothing: widen toward
    one end only with (0, x). Levels sit at the middles of equal cells no longer than
    `z_step`, so none lies on the window's own ends, where a modelled cut has its
    step face. `r_min` and `r_max` bound the annulus read, as in radial_extent.

    `max` is the largest radius on the grid and `min` the smallest, each with the
    angle and level where it lies; `detail["points"]` holds every (angle, z, radius).
    For an annular snap, a relief must keep `max` at the release angles within the
    relieved radius over the whole stroke, and the lock must keep `min` at the lock
    angles at the full one: engagement is the radius less the mating bead's.

    Every ray is read. A ray that runs along a face (a relief's side face lies in a
    plane through the axis, so whole-degree sweeps meet them) is read again
    FACE_EPS_DEG either side in angle and counts as both readings: the larger for
    `max`, the smaller for `min`; it is listed in `detail["on_face"]`. A ray that
    cannot be read, or whose both sides cannot, stays unread and is listed in
    `detail["unread"]`; any unread ray makes both results INCONCLUSIVE."""
    side = _side(side)
    window_r = _window(r_min, r_max)
    axis = Axis(axis_origin, axis_dir, ref_dir)
    low, high = map(float, band)
    if not (math.isfinite(low) and math.isfinite(high) and low <= high):
        raise ValueError(f"band is (z_low, z_high) with z_low <= z_high, not {band!r}")
    below, above = _margin(margin)
    if not (isinstance(z_step, numbers.Real) and z_step > 0):
        raise ValueError(f"z_step must be positive, not {z_step!r}")
    angles = [float(a) for a in angles_deg]
    if not angles:
        raise ValueError("no angle to probe")
    window = (low - below, high + above)
    cells = max(1, math.ceil((window[1] - window[0]) / z_step - 1e-9))
    step = (window[1] - window[0]) / cells
    levels = [window[0] + (i + 0.5) * step for i in range(cells)]
    if len(angles) * len(levels) > MAX_RAYS:
        raise ValueError(f"{len(angles)} angles x {len(levels)} levels is more than {MAX_RAYS} rays; "
                         f"a z_step of {z_step * len(angles) * len(levels) / MAX_RAYS:.2g} mm fits")
    params = {"band": [low, high], "margin": [below, above], "window": list(window), "z_step": z_step,
              "levels": len(levels), "angles_deg": angles, "side": side, "r_min": window_r[0],
              "r_max": window_r[1], "face_eps_deg": FACE_EPS_DEG, "ref_lean_deg": axis.lean_deg,
              "axis_origin": _point(axis.origin), "axis_dir": _point(axis.axis), "ref_dir": _point(axis.ref)}
    probe = Probe(shape)
    points, on_face, unread = [], [], []
    for angle in angles:
        for z in levels:
            try:
                radius, point, _ = probe.extent(axis, angle, z, side, window_r)
                points.append({"angle_deg": angle, "z": round(z, 9), "radius": radius, "low": radius,
                               "at": _point(point)})
                continue
            except OnFace as exc:
                why = str(exc)
            except (NoMaterial, Crossing) as exc:
                unread.append({"angle_deg": angle, "z": round(z, 9), "reason": str(exc)})
                continue
            sides = []
            for turn in (-FACE_EPS_DEG, FACE_EPS_DEG):
                try:
                    radius, point, _ = probe.extent(axis, angle + turn, z, side, window_r)
                    sides.append((radius, point))
                except (NoMaterial, OnFace, Crossing) as exc:
                    sides.append((None, str(exc)))
            read = [(r, p) for r, p in sides if r is not None]
            if not read:
                unread.append({"angle_deg": angle, "z": round(z, 9),
                               "reason": f"{why}; either side: " + "; ".join(p for _, p in sides)})
                continue
            hi, lo = max(read, key=lambda rp: rp[0]), min(read, key=lambda rp: rp[0])
            points.append({"angle_deg": angle, "z": round(z, 9), "radius": hi[0], "low": lo[0],
                           "at": _point(hi[1]), "at_low": _point(lo[1])})
            on_face.append({"angle_deg": angle, "z": round(z, 9), "sides": [r for r, _ in sides]})
    detail = {"points": points, "largest_step_mm": step, "on_face": on_face, "unread": unread}
    if unread:
        first = unread[0]
        reason = (f"{len(unread)} of {len(angles) * len(levels)} rays unread, first at {first['angle_deg']:g}° "
                  f"and z = {first['z']:.6f} mm: {first['reason']}")
        return {k: Result(n, None, u, params=params, status=INCONCLUSIVE, reason=reason, detail=detail)
                for k, (n, u) in PROFILE.items()}
    top = max(points, key=lambda p: p["radius"])
    bottom = min(points, key=lambda p: p["low"])
    return {"max": Result("radial_profile_max", top["radius"], "mm", at=top["at"], params=params,
                          detail={**detail, "angle_deg": top["angle_deg"], "z": top["z"]}),
            "min": Result("radial_profile_min", bottom["low"], "mm", at=bottom.get("at_low", bottom["at"]),
                          params=params, detail={**detail, "angle_deg": bottom["angle_deg"], "z": bottom["z"]})}
