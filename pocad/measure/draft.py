# kaynak: oguz-atolye tools/measure/draft.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Draft and undercut against a pull direction (R04 functions 4 and 5).

Draft is 90° minus the angle between the outward normal and the pull, signed: a
negative draft is an undercut, and abs() would hide it. It varies over a curved
face, so it is the minimum over samples. Faces facing the pull or its opposite
within 0.999 (about 2.6°) are the caps and are left out (R04 §1).

An undercut is a sample on a face that could be drawn along the pull from which a
ray along the pull runs back into material. Features narrower than the spacing can
hide between samples, so the spacing is reported and should follow the smallest
declared feature.

The overhang census (GATES D-03a) reads the same samples against a build
direction instead of a pull: a downward face, one whose outward normal points
back toward the bed, stands at the angle between its plane and the horizontal,
0° for a flat ceiling and 90° for a wall. The lowest points of the part along the
build direction lie on the bed, which carries them, so samples there are left out.
A grid only overshoots the least angle, so the census refines it on curved faces
and says what bound is left.
"""
from __future__ import annotations

import math

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_IN, TopAbs_ON

from pocad._ocp import FClass2d
from pocad.core.shapes import faces, solids, vertices
from pocad.measure.sampling import MAX_SAMPLES_PER_FACE, Grid, face_grid, face_samples, kind, outward_normal
from pocad.result import INCONCLUSIVE, Result, inconclusive, measurement

CAP_COS = 0.999
DOWN_COS = 1e-9          # a normal this little toward the bed is a wall, not an overhang
BED_MM = 0.01            # a sample this close to the part's lowest height rests on the bed
NOISE_DEG = 1e-6         # a sample counts below min_deg by more than float noise: a 45° cone reads 44.99999999999998
REFINE_SEEDS = 4         # the lowest samples of a curved face refined, 1.5 grid cells apart
REFINE_POINTS = 5        # probes per side of a refinement window
REFINE_DEG = 0.01        # a refinement stops when the angle can change less than this across its window
REFINE_ROUNDS = 200      # and gives up, leaving the face's grid bound, after this many rounds


def _unit(pull) -> np.ndarray:
    vector = np.array(pull, float)
    size = np.linalg.norm(vector)
    if vector.shape != (3,) or size < 1e-12:
        raise ValueError(f"pull must be a 3D direction, not {pull!r}")
    return vector / size


@measurement("draft_angles", "deg")
def draft_angles(shape, pull, *, spacing: float = 1.0) -> Result:
    """The smallest draft in degrees over every sample of every side face, with where
    it is; detail["faces"] gives each face's minimum."""
    direction = _unit(pull)
    worst, per_face, samples, step = None, [], 0, 0.0
    for solid in solids(shape):
        for face in faces(solid):
            face_min = None
            grid = face_grid(face, spacing)
            step = max(step, grid.step_mm)
            for point, normal, _ in face_samples(face, spacing, grid):
                c = max(-1.0, min(1.0, float(np.dot(normal, direction))))
                if abs(c) > CAP_COS:
                    continue
                samples += 1
                draft = 90.0 - math.degrees(math.acos(c))
                if face_min is None or draft < face_min[0]:
                    face_min = (draft, tuple(round(float(x), 6) for x in point))
            if face_min:
                per_face.append({"kind": kind(face), "min_deg": round(face_min[0], 6), "at": face_min[1]})
                if worst is None or face_min[0] < worst[0]:
                    worst = face_min
    params = {"pull": tuple(float(x) for x in direction), "spacing_mm": spacing, "cap_cos": CAP_COS}
    if worst is None:
        return inconclusive("draft_angles", "deg", "no side face to measure", **params)
    return Result("draft_angles", worst[0], "deg", at=worst[1], params=params,
                  detail={"samples": samples, "largest_step_mm": round(step, 6),
                          "faces": sorted(per_face, key=lambda f: f["min_deg"])})


@measurement("undercuts", "count")
def undercuts(shape, pull, *, spacing: float = 1.0) -> Result:
    """How many samples facing the pull are blocked by material along it."""
    direction = _unit(pull)
    blocked, total, first, step = 0, 0, None, 0.0
    for solid in solids(shape):
        intersector = IntCurvesFace_ShapeIntersector()
        intersector.Load(solid, 1e-7)
        for face in faces(solid):
            grid = face_grid(face, spacing)
            step = max(step, grid.step_mm)
            for point, normal, _ in face_samples(face, spacing, grid):
                if float(np.dot(normal, direction)) <= 1e-6:
                    continue
                total += 1
                start = point + direction * 1e-4
                intersector.Perform(gp_Lin(gp_Pnt(*start), gp_Dir(*direction)), 0.0, 1e9)
                if not intersector.IsDone():
                    raise RuntimeError("a ray along the pull failed")
                if any(intersector.WParameter(j) > 1e-3 for j in range(1, intersector.NbPnt() + 1)):
                    blocked += 1
                    first = first or tuple(round(float(x), 6) for x in point)
    params = {"pull": tuple(float(x) for x in direction), "spacing_mm": spacing}
    if not total:
        return inconclusive("undercuts", "count", "no face faces the pull", **params)
    return Result("undercuts", blocked, "count", at=first, params=params,
                  detail={"samples_facing_pull": total, "largest_step_mm": round(step, 6)})


@measurement("overhang_census", "deg")
def overhang_census(shape, build_dir=(0, 0, 1), *, min_deg: float = 45.0, spacing: float = 0.5) -> Result:
    """The least angle from horizontal, in degrees, over every downward-facing point
    of every face, with where it is, printed along `build_dir` (the way the layers
    stack, away from the bed).

    A point faces down when its outward normal points back toward the bed by more
    than DOWN_COS; its angle from horizontal is then acos(-n·build_dir): a flat
    ceiling reads 0, a 45° chamfer 45, and a vertical wall is not downward. Points
    within BED_MM of the part's lowest height along the build direction rest on the
    bed and are left out (detail["bed_samples"]).

    Faces are sampled on the grid pocad.measure.sampling sizes, boundary rows
    included. A grid only ever overshoots the least angle, by up to the angle the
    normal turns through in one step (curvature × step: 45° on an R0.5 hole at
    0.5 mm), so on every curved face that could hold a lower angle than the least
    found, the lowest samples (REFINE_SEEDS of them, 1.5 grid cells apart) are
    refined: a pattern search on the face's parameters that closes in until the
    angle can change by less than REFINE_DEG across its window. What is left is
    detail["sampling_bound_deg"]; a face whose search does not settle leaves its
    whole grid bound. A least within that bound above `min_deg` could be below it,
    and is INCONCLUSIVE, never a pass. The curvature is the largest at the face's
    samples: exact on analytic faces, an estimate on a freeform one.

    detail["below_min_deg"] counts the grid samples under `min_deg` by more than
    NOISE_DEG, and detail["per_kind_least_deg"] gives the least per surface kind.
    A part with no downward point off the bed reads 90 with no `at`. INCONCLUSIVE
    when there is no solid, when a face yields no sample even on a grid eight times
    finer (it could face down), or when a face is too large for the spacing (never
    a coarser grid on the quiet)."""
    direction = _unit(build_dir)
    if not 0.0 < float(min_deg) <= 90.0:
        raise ValueError(f"min_deg is an angle in (0, 90], not {min_deg!r}")
    params = {"build_dir": tuple(float(x) for x in direction), "min_deg": float(min_deg),
              "spacing_mm": spacing, "bed_mm": BED_MM}
    found = solids(shape)
    if not found:
        return inconclusive("overhang_census", "deg", "no solid to scan", **params)
    records, unsampled, step = [], 0, 0.0
    for solid in found:
        for face in faces(solid):
            grid = face_grid(face, spacing)
            step = max(step, grid.step_mm)
            samples = list(face_samples(face, spacing, grid, boundary=True))
            if not samples and grid.nu * grid.nv * 64 <= MAX_SAMPLES_PER_FACE:
                finer = Grid(grid.nu * 8, grid.nv * 8, grid.step_mm / 8)
                samples = list(face_samples(face, spacing, finer, boundary=True))
            if not samples:
                unsampled += 1
                continue
            records.append((face, grid, samples))
    if unsampled:
        return inconclusive("overhang_census", "deg", f"{unsampled} faces yielded no sample; "
                            "one may face down", **params)
    corners = [BRep_Tool.Pnt_s(v) for solid in found for v in vertices(solid)]
    heights = [float(np.dot(point, direction)) for _, _, samples in records for point, _, _ in samples]
    bed = min(heights + [float(np.dot((p.X(), p.Y(), p.Z()), direction)) for p in corners])

    total, downward, below, on_bed, per_kind, lows = 0, 0, 0, 0, {}, []
    for face, grid, samples in records:
        face_kind, angles = kind(face), []
        for point, normal, uv in samples:
            total += 1
            toward_bed = -float(np.dot(normal, direction))
            if toward_bed <= DOWN_COS:
                continue
            if float(np.dot(point, direction)) - bed <= BED_MM:
                on_bed += 1
                continue
            angle = math.degrees(math.acos(min(1.0, toward_bed)))
            downward += 1
            below += angle < min_deg - NOISE_DEG
            angles.append((angle, uv, point))
        if angles:
            angles.sort(key=lambda a: a[0])
            per_kind[face_kind] = min(per_kind.get(face_kind, 90.0), angles[0][0])
            turn = math.degrees(_curvature(face, samples) * grid.step_mm)
            lows.append((angles[0][0] - turn, face, grid, angles, turn))
    if not lows:
        return Result("overhang_census", 90.0, "deg", params=params,
                      detail=_overhang_detail(total, downward, below, on_bed, bed, step, per_kind, 0.0, 0))
    least, _, at = min((a[3][0] for a in lows), key=lambda a: a[0])
    bound, refined = 0.0, 0
    for lower, face, grid, angles, turn in sorted(lows, key=lambda a: a[0]):
        if lower >= least or turn <= 0.0:
            continue                             # a plane is exact; this face cannot go lower
        probe = _Probe(face, direction, bed)
        seeds = _seeds(angles, grid, probe)
        settled = True
        for angle, uv, _ in seeds:
            if angle - turn >= least:
                continue
            refined += 1
            best, residual = _refine(probe, uv, angle, grid, turn / grid.step_mm)
            if residual is None:
                settled = False
            if best[0] < least - NOISE_DEG:
                least, at, bound = best[0], best[1], residual or 0.0
                per_kind[kind(face)] = min(per_kind.get(kind(face), 90.0), best[0])
            elif best[0] <= least + NOISE_DEG:
                bound = max(bound, residual or 0.0)      # the least again: it carries this bound too
        if not settled:
            bound = max(bound, least - lower)
    detail = _overhang_detail(total, downward, below, on_bed, bed, step, per_kind, bound, refined)
    at = tuple(round(float(x), 6) for x in at)
    if least - bound < min_deg - NOISE_DEG and min_deg <= least + NOISE_DEG:
        return Result("overhang_census", None, "deg", at=at, params=params, status=INCONCLUSIVE,
                      reason=f"the least, {least:.4f}°, lies within its sampling bound ({bound:.4f}°) "
                             f"above min_deg; a finer spacing settles it",
                      detail={**detail, "least_found_deg": least})
    return Result("overhang_census", least, "deg", at=at, params=params, detail=detail)


def _overhang_detail(total, downward, below, on_bed, bed, step, per_kind, bound, refined) -> dict:
    return {"samples": total, "downward_samples": downward, "below_min_deg": below, "bed_samples": on_bed,
            "bed_height_mm": round(bed, 6), "largest_step_mm": round(step, 6),
            "sampling_bound_deg": round(bound, 6), "seeds_refined": refined,
            "per_kind_least_deg": {k: round(v, 6) for k, v in sorted(per_kind.items())}}


def _curvature(face, samples) -> float:
    """The largest principal curvature (1/mm) at a face's samples; 0 on a plane."""
    if kind(face) == "plane":
        return 0.0
    props = GeomLProp_SLProps(BRep_Tool.Surface_s(face), 2, 1e-7)
    largest = 0.0
    for _, _, (u, v) in samples:
        props.SetParameters(u, v)
        if props.IsCurvatureDefined():
            largest = max(largest, abs(props.MaxCurvature()), abs(props.MinCurvature()))
    return largest


class _Probe:
    """The overhang angle at (u, v) of one face: (angle, point), or None where the
    point is off the face, has no normal, is not downward, or rests on the bed."""

    def __init__(self, face, direction, bed):
        self.face, self.direction, self.bed = face, direction, bed
        self.surface = BRepAdaptor_Surface(face)
        self.props = GeomLProp_SLProps(BRep_Tool.Surface_s(face), 1, 1e-7)
        self.inside = FClass2d(face, 1e-7)
        self.bounds = BRepTools.UVBounds_s(face)

    def point(self, u, v) -> np.ndarray:
        p = self.surface.Value(u, v)
        return np.array([p.X(), p.Y(), p.Z()], float)

    def __call__(self, u, v):
        u0, u1, v0, v1 = self.bounds
        if not (u0 <= u <= u1 and v0 <= v <= v1):
            return None
        if self.inside.Perform(gp_Pnt2d(u, v)) not in (TopAbs_IN, TopAbs_ON):
            return None
        normal = outward_normal(self.face, u, v, self.props)
        if normal is None:
            return None
        toward_bed = -float(np.dot(normal, self.direction))
        point = self.point(u, v)
        if toward_bed <= DOWN_COS or float(np.dot(point, self.direction)) - self.bed <= BED_MM:
            return None
        return math.degrees(math.acos(min(1.0, toward_bed))), point


def _seeds(angles, grid, probe) -> list:
    """The lowest samples of a face, at most REFINE_SEEDS, each more than 1.5 grid
    cells from the ones before it."""
    u0, u1, v0, v1 = probe.bounds
    du, dv = (u1 - u0) / grid.nu, (v1 - v0) / grid.nv
    chosen = []
    for angle, (u, v), point in angles:
        if all(abs(u - cu) > 1.5 * du or abs(v - cv) > 1.5 * dv for _, (cu, cv), _ in chosen):
            chosen.append((angle, (u, v), point))
            if len(chosen) == REFINE_SEEDS:
                break
    return chosen


def _refine(probe, uv, angle, grid, curvature):
    """A pattern search for the least angle near one sample: REFINE_POINTS² probes
    over a window one grid cell each way, moved to the lowest, halved when the
    centre stays lowest, until the angle can change by less than REFINE_DEG across
    the window (curvature × its half-diagonal). Returns ((angle, point), residual),
    the residual None when the search does not settle in REFINE_ROUNDS rounds."""
    u0, u1, v0, v1 = probe.bounds
    u, v = uv
    half_u, half_v = (u1 - u0) / grid.nu, (v1 - v0) / grid.nv
    best = (angle, probe.point(u, v))
    offsets = [2.0 * i / (REFINE_POINTS - 1) - 1.0 for i in range(REFINE_POINTS)]
    for _ in range(REFINE_ROUNDS):
        centre = (u, v)
        for a in offsets:
            for b in offsets:
                found = probe(centre[0] + a * half_u, centre[1] + b * half_v)
                if found is not None and found[0] < best[0] - 1e-12:
                    best, u, v = found, centre[0] + a * half_u, centre[1] + b * half_v
        if (u, v) != centre:
            continue
        reach = max(float(np.linalg.norm(probe.point(u + half_u, v + half_v) - probe.point(u - half_u, v - half_v))),
                    float(np.linalg.norm(probe.point(u + half_u, v - half_v) - probe.point(u - half_u, v + half_v))))
        residual = math.degrees(curvature * reach / 2.0)
        if residual < REFINE_DEG:
            return best, residual
        half_u, half_v = half_u / 2.0, half_v / 2.0
    return best, None
