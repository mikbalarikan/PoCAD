# kaynak: oguz-atolye tools/measure/wall.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Wall thickness and mesh checks (R04 functions 1 and 2, D-025, oguz-atolye U-17).

`min_wall` is the gate. From samples on every face a ray goes inward along the
negative outward normal, and the first face it leaves the solid through counts
as a wall when that face's normal is opposed to the start's within
`opposition_deg` (25°, fixed by oguz-atolye U-17). Samples can miss the thinnest spot (a
web between two small holes falls between them), so face pairs are then measured
exactly, face to face (BRepExtrema_DistShapeShape): every pair a ray joined, and
every pair whose bounding boxes lie closer than the thinnest wall the rays found,
nearest first, unless their normals can never be opposed. Their closest points
count as a wall under the same definition: the faces' normals there are opposed
within the opposition angle, and the segment between them runs through material
along both. The value at 45° is reported beside the
gated one, never instead (R04 open question 2); `min_wall_wide` returns it as
its own Result, for the gate that reads it (GATES U-06). Offsets are not used: they
collapse on thin walls (L-07). A tapered fin whose flanks are more than 25° apart
is not a wall at 25°, and neither is the neck between two re-entrant corners.

The mesh functions read an STL and only corroborate (D-025): a tessellated wall
reads thin by up to the chordal tolerance, so the caller holds `min_wall_mesh` to
the B-rep value minus that tolerance, never to the gate itself.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import trimesh
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location

from pocad._ocp import IndexedDataMapOfShapeListOfShape, IndexedMapOfShape, downcast
from pocad.core.shapes import faces, occ, solids
from pocad.measure.sampling import Inside, face_grid, face_samples, kind, outward_normal
from pocad.result import INCONCLUSIVE, Result, inconclusive, measurement, measurement_set

RAY_START = 1e-5          # start each ray this far inside, so it does not hit its own face
MIN_HIT = 1e-4            # a hit this close is the start face; thinner slivers the exact pass measures
WIDE_DEG = 45.0           # the wider opposition published beside the gated one
MESH_CHUNK = 20_000       # rays or points per trimesh query, to bound memory
MAX_MESH_RAYS = 1_000_000  # Embree casts about a million rays a second
MESH_HITS = 4             # hits per mesh ray: in float32 the first can be its own triangle, behind it
VERTEX_BITS = 23          # an STL stores coordinates in single precision
INWARD_MM = 1e-3          # a chord on the boundary slides this far sideways to be tested inside
CONE_GRID = 9             # normals per parameter direction for a face's normal cone
CHORD_POINTS = 15         # points classified along an exact pass's chord


@measurement("min_wall", "mm")
def min_wall(shape, *, spacing: float = 0.4, opposition_deg: float = 25.0) -> Result:
    """The thinnest opposed wall of every solid in `shape`, in mm, with where it is.
    detail["wide"] is the same at 45°; detail["largest_step_mm"] is the sampling
    actually used. A ray that fails or finds no exit makes the result INCONCLUSIVE,
    with the thinnest wall found so far in detail."""
    found = solids(shape)
    if not found:
        return inconclusive("min_wall", "mm", "no solid to scan", spacing=spacing)
    angles = {"gated": opposition_deg, "wide": max(WIDE_DEG, opposition_deg)}
    cosines = {key: math.cos(math.radians(deg)) for key, deg in angles.items()}
    best: dict[str, tuple | None] = {key: None for key in angles}
    counts = {"rays": 0, "lost_rays": 0, "face_pairs_measured_exactly": 0, "face_pairs_never_opposed": 0,
              "face_pairs_failed": 0, "exact_points_without_normal": 0}
    step = 0.0

    def offer(key, thickness, start, end, from_face, to_face, how):
        if best[key] is None or thickness < best[key][0]:
            best[key] = (thickness, _point(start), _point(end), kind(from_face), kind(to_face), how)

    for solid in found:
        face_map = IndexedMapOfShape()
        TopExp.MapShapes_s(solid, TopAbs_FACE, face_map)
        props = {i: GeomLProp_SLProps(BRep_Tool.Surface_s(downcast.Face(face_map.FindKey(i))), 1, 1e-7)
                 for i in range(1, face_map.Extent() + 1)}
        intersector = IntCurvesFace_ShapeIntersector()
        intersector.Load(solid, 1e-7)
        pairs: set[tuple[int, int]] = set()
        for index in range(1, face_map.Extent() + 1):
            face = downcast.Face(face_map.FindKey(index))
            grid = face_grid(face, spacing)
            step = max(step, grid.step_mm)
            for point, normal, _ in face_samples(face, spacing, grid):
                counts["rays"] += 1
                start, direction = point - normal * RAY_START, -normal
                found = _exit(intersector, start, direction) or _exit_again(solid, start, direction)
                if found is None:
                    counts["lost_rays"] += 1            # a ray into a closed solid always leaves it
                    continue
                w, hit_face, u, v = found
                other = face_map.FindIndex(hit_face)
                hit_normal = _normal_near(hit_face, u, v, props.get(other))
                if hit_normal is None:
                    counts["lost_rays"] += 1
                    continue
                pairs.add((min(index, other), max(index, other)))
                opposed = float(np.dot(hit_normal, normal))
                for key, cosine in cosines.items():
                    if opposed <= -cosine:              # along the ray, so along both normals
                        offer(key, w + RAY_START, point, start + direction * w, face, hit_face, "ray")
        _exact_walls(solid, face_map, pairs, cosines, best, offer, counts)

    params = {"spacing_mm": spacing, "opposition_deg": opposition_deg}
    detail = {**counts, "solids": len(found), "largest_step_mm": round(float(step), 6)}
    if best["wide"] is not None:
        detail["wide"] = {"opposition_deg": angles["wide"], "measured": best["wide"][0], "at": best["wide"][1]}
    lost = [f"{counts['lost_rays']} of {counts['rays']} rays failed or found no exit" if counts["lost_rays"] else "",
            f"{counts['face_pairs_failed']} face pairs could not be measured" if counts["face_pairs_failed"] else "",
            f"{counts['exact_points_without_normal']} closest points had no normal"
            if counts["exact_points_without_normal"] else ""]
    if any(lost):
        found_so_far = best["gated"][0] if best["gated"] else None
        return Result("min_wall", None, "mm", params=params, status=INCONCLUSIVE,
                      reason="; ".join(x for x in lost if x) + "; one may have hidden the thinnest wall",
                      detail={**detail, "thinnest_found_mm": found_so_far})
    if best["gated"] is None:
        return Result("min_wall", None, "mm", params=params, status=INCONCLUSIVE,
                      reason="no opposed wall found", detail=detail)
    thickness, at, hit, from_kind, to_kind, how = best["gated"]
    return Result("min_wall", thickness, "mm", at=at, params=params,
                  detail={**detail, "hit_at": hit, "from_face": from_kind, "to_face": to_kind, "found_by": how})


@measurement("min_wall_wide", "mm")
def min_wall_wide(shape, *, spacing: float = 0.4) -> Result:
    """min_wall's reading at the wider 45° opposition as a Result of its own, in mm,
    with where it is: the thinnest wall under a round over a sharp inside corner,
    which the gated 25° reading does not see (GATES U-06). It is the same scan, read
    once; detail gives the gated 25° reading beside it ("gated_mm") and min_wall's
    sampling. INCONCLUSIVE whenever min_wall is, with its reason, and when no wall
    is opposed within 45°."""
    result = min_wall(shape, spacing=spacing)
    params = {"spacing_mm": spacing, "opposition_deg": WIDE_DEG}
    if not result.ok:
        return Result("min_wall_wide", None, "mm", params=params, status=INCONCLUSIVE,
                      reason=f"min_wall is INCONCLUSIVE: {result.reason}", detail=result.detail)
    wide = result.detail.get("wide")
    if not isinstance(wide, dict) or wide.get("measured") is None:
        return inconclusive("min_wall_wide", "mm", "no wall opposed within 45°", **params)
    keep = ("rays", "solids", "largest_step_mm", "face_pairs_measured_exactly")
    return Result("min_wall_wide", wide["measured"], "mm", at=wide.get("at"), params=params,
                  detail={"gated_mm": result.measured, "gated_opposition_deg": result.params["opposition_deg"],
                          "gated_at": result.at, **{k: result.detail[k] for k in keep if k in result.detail}})


def _exact_walls(solid, face_map, pairs, cosines, best, offer, counts) -> None:
    """Measure face pairs exactly, face to face, nearest first: every pair a ray
    joined, and every pair whose bounding boxes lie closer than the thinnest wall
    the rays found, since any thinner wall lies between such faces whether or not a
    ray joined them. Faces that share an edge meet at it, and faces whose normals can
    never be opposed within the widest angle hold no wall: both are skipped. The pass
    stops once no pair left is closer than the walls found."""
    neighbours = IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid, TopAbs_EDGE, TopAbs_FACE, neighbours)
    adjacent = set()
    for e in range(1, neighbours.Extent() + 1):
        indices = sorted({face_map.FindIndex(f) for f in neighbours.FindFromIndex(e)})
        adjacent.update((a, b) for n, a in enumerate(indices) for b in indices[n + 1:])
    boxes = _face_boxes(face_map)
    candidates = set(pairs)
    reach = _ceiling(best)
    if math.isfinite(reach):
        candidates |= _near_pairs(boxes, reach)
    candidates = [pair for pair in candidates if pair[0] != pair[1] and pair not in adjacent]
    widest = math.acos(min(cosines.values()))
    cones: dict[int, tuple | None] = {}
    for i in {i for pair in candidates for i in pair}:
        cones[i] = _normal_cone(downcast.Face(face_map.FindKey(i)))
    opposable = [pair for pair in candidates if _may_oppose(cones[pair[0]], cones[pair[1]], widest)]
    counts["face_pairs_never_opposed"] += len(candidates) - len(opposable)
    candidates = opposable
    gaps = {pair: _gap(boxes, *pair) for pair in candidates}
    inside = Inside(solid)
    for a, b in sorted(candidates, key=gaps.__getitem__):
        if gaps[(a, b)] >= _ceiling(best):
            break                                # no pair from here on can hold a thinner wall
        face_a, face_b = downcast.Face(face_map.FindKey(a)), downcast.Face(face_map.FindKey(b))
        extrema = BRepExtrema_DistShapeShape(face_a, face_b)
        if not extrema.IsDone():
            counts["face_pairs_failed"] += 1
            continue
        counts["face_pairs_measured_exactly"] += 1
        for s in range(1, extrema.NbSolution() + 1):
            p, q = _vec(extrema.PointOnShape1(s)), _vec(extrema.PointOnShape2(s))
            distance = float(np.linalg.norm(q - p))
            if distance <= 1e-9 or distance >= _ceiling(best):
                continue
            n_p, n_q = _normal_at(face_a, p), _normal_at(face_b, q)
            if n_p is None or n_q is None:
                counts["exact_points_without_normal"] += 1
                continue
            d = (q - p) / distance
            keys = [key for key, cosine in cosines.items()
                    if float(np.dot(n_p, n_q)) <= -cosine + 1e-9
                    and float(np.dot(-n_p, d)) >= cosine - 1e-9 and float(np.dot(n_q, d)) >= cosine - 1e-9
                    and (best[key] is None or distance < best[key][0])]
            if not keys:
                continue                          # not opposed, or not along both normals: no wall (U-17)
            if not _through_material(inside, p, q, face_a, face_b):
                continue
            for key in keys:
                offer(key, distance, p, q, face_a, face_b, "exact")


def _exit(intersector, start, direction):
    """The nearest exit of a ray beyond MIN_HIT, as (parameter, face, u, v), or None
    when the cast fails or finds none."""
    try:
        intersector.Perform(gp_Lin(gp_Pnt(*start), gp_Dir(*direction)), 0.0, 1e9)
    except Exception:                                               # noqa: BLE001: the caller counts it
        return None
    if not intersector.IsDone():
        return None
    hits = [(intersector.WParameter(j), j) for j in range(1, intersector.NbPnt() + 1)
            if intersector.WParameter(j) > MIN_HIT]
    if not hits:
        return None
    w, j = min(hits)
    return w, intersector.Face(j), intersector.UParameter(j), intersector.VParameter(j)


def _exit_again(solid, start, direction):
    """The same, found by BRepIntCurveSurface_Inter, which IntCurvesFace can miss: a
    ray that meets a face almost tangentially, 2° off a steep loft, found no exit."""
    crossing = BRepIntCurveSurface_Inter()
    try:
        crossing.Init(solid, gp_Lin(gp_Pnt(*start), gp_Dir(*direction)), 1e-7)
    except Exception:                                               # noqa: BLE001: the caller counts it
        return None
    best = None
    while crossing.More():
        if crossing.W() > MIN_HIT and (best is None or crossing.W() < best[0]):
            best = (crossing.W(), crossing.Face(), crossing.U(), crossing.V())
        crossing.Next()
    return best


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    return math.acos(max(-1.0, min(1.0, float(np.dot(a, b)))))


def _normal_cone(face):
    """(axis, half-angle in radians) of a cone that holds every outward normal of the
    face's surface over its parameter box: sampled on a CONE_GRID grid and widened by
    the largest turn between neighbouring samples. None when it holds too much to
    help (a whole cylinder), or the surface cannot be sampled."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    if not all(map(math.isfinite, (u0, u1, v0, v1))):
        return None
    props = GeomLProp_SLProps(BRep_Tool.Surface_s(face), 1, 1e-7)
    grid = [[outward_normal(face, float(u), float(v), props) for v in np.linspace(v0, v1, CONE_GRID)]
            for u in np.linspace(u0, u1, CONE_GRID)]
    normals = [n for row in grid for n in row if n is not None]
    if len(normals) < CONE_GRID:
        return None
    turn = 0.0
    for i in range(CONE_GRID):
        for j in range(CONE_GRID):
            here = grid[i][j]
            for there in (grid[i + 1][j] if i + 1 < CONE_GRID else None,
                          grid[i][j + 1] if j + 1 < CONE_GRID else None):
                if here is not None and there is not None:
                    turn = max(turn, _angle(here, there))
    axis = np.sum(normals, axis=0)
    if np.linalg.norm(axis) < 1e-6 * len(normals):
        return None
    axis /= np.linalg.norm(axis)
    spread = max(_angle(axis, n) for n in normals) + turn
    return (axis, spread) if spread < math.pi else None


def _may_oppose(cone_a, cone_b, limit: float) -> bool:
    """Whether a normal of one face can be opposed to a normal of the other within
    `limit` radians, judged from their normal cones."""
    if cone_a is None or cone_b is None:
        return True
    return _angle(cone_a[0], -cone_b[0]) <= limit + cone_a[1] + cone_b[1] + 1e-9


def _through_material(inside: Inside, p: np.ndarray, q: np.ndarray, face_a, face_b) -> bool:
    """Whether the segment p-q runs through material: each of CHORD_POINTS points
    along it lies inside the solid or on its boundary. Parallel walls meet their
    closest points on their edges, so the segment can lie along a face; then it must
    slide INWARD_MM sideways, in one of eight directions across it, to a place where
    its ends, projected back onto their own faces, still lie on them, and every point
    between them is inside. The segment between two walls does, drafted or not; one
    along a face across the mouth of a gap, or between two faces that only touch at a
    corner, does not. A gap narrower than the points' spacing can slip between them:
    the wall then reads thinner, never thicker."""
    steps = np.arange(1, CHORD_POINTS + 1) / (CHORD_POINTS + 1)
    states = [inside.state(p + t * (q - p)) for t in steps]
    if any(state not in (TopAbs_IN, TopAbs_ON) for state in states):
        return False
    if all(state == TopAbs_IN for state in states) or np.linalg.norm(q - p) <= 2 * MIN_HIT:
        return True
    d = (q - p) / np.linalg.norm(q - p)
    e1 = np.cross(d, [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(d, e1)
    for turn in np.arange(8) * math.pi / 4:
        slide = INWARD_MM * (math.cos(turn) * e1 + math.sin(turn) * e2)
        ends = _onto(face_a, p + slide), _onto(face_b, q + slide)
        if ends[0] is None or ends[1] is None:
            continue
        a, b = ends
        if all(inside.state(a + t * (b - a)) == TopAbs_IN for t in steps):
            return True
    return False


def _onto(face, point: np.ndarray):
    """The point projected onto the face's surface, if it lands on the face within
    3 x INWARD_MM; else None."""
    projection = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))
    uv = projection.ValueOfUV(gp_Pnt(*map(float, point)), 1e-7)
    if projection.Gap() < 0 or projection.Gap() > 3 * INWARD_MM:
        return None
    landed = _vec(projection.Value(uv))
    if BRepClass_FaceClassifier(face, gp_Pnt(*map(float, landed)), 1e-7).State() not in (TopAbs_IN, TopAbs_ON):
        return None
    return landed


def _ceiling(best: dict) -> float:
    """The thickness no candidate needs to beat: the largest of the walls found, or
    infinity while a limit has found none."""
    found = [b[0] for b in best.values() if b is not None]
    return max(found) if len(found) == len(best) else math.inf


def _face_boxes(face_map) -> np.ndarray:
    count = face_map.Extent()
    boxes = np.empty((count, 6))
    for i in range(1, count + 1):
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(face_map.FindKey(i), box, False, False)
        low, high = box.CornerMin(), box.CornerMax()
        boxes[i - 1] = (low.X(), low.Y(), low.Z(), high.X(), high.Y(), high.Z())
    return boxes


def _gap(boxes: np.ndarray, a: int, b: int) -> float:
    low_a, high_a, low_b, high_b = boxes[a - 1, :3], boxes[a - 1, 3:], boxes[b - 1, :3], boxes[b - 1, 3:]
    return float(np.linalg.norm(np.maximum(0.0, np.maximum(low_a - high_b, low_b - high_a))))


def _near_pairs(boxes: np.ndarray, reach: float) -> set[tuple[int, int]]:
    """Face pairs (1-based, a < b) whose bounding boxes are less than `reach` apart."""
    count = len(boxes)
    low, high = boxes[:, :3], boxes[:, 3:]
    found = set()
    for start in range(0, count, 512):
        rows = slice(start, start + 512)
        gap = np.maximum(0.0, np.maximum(low[rows, None, :] - high[None, :, :], low[None, :, :] - high[rows, None, :]))
        a, b = np.nonzero(np.linalg.norm(gap, axis=2) < reach)
        found.update((int(i) + start + 1, int(j) + 1) for i, j in zip(a, b) if i + start < j)
    return found


def _normal_near(face, u: float, v: float, props=None):
    """The outward normal at (u, v), or, where the surface has none (a cone's apex),
    at the nearest parameters around it that have one, inside the face's own range:
    beyond an apex lies the cone's other nappe, whose normal is turned over."""
    normal = outward_normal(face, u, v, props)
    if normal is not None:
        return normal
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    surface = BRep_Tool.Surface_s(face)                 # at an apex every u is the same point: bring the
    if surface.IsUPeriodic():                           # parameters into the face's own range first
        u = u0 + (u - u0) % surface.UPeriod()
    if surface.IsVPeriodic():
        v = v0 + (v - v0) % surface.VPeriod()
    u, v = min(max(u, u0), u1), min(max(v, v0), v1)
    for scale in (1e-6, 1e-4):
        for du, dv in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            su, sv = u + du * scale * (u1 - u0), v + dv * scale * (v1 - v0)
            if not (u0 <= su <= u1 and v0 <= sv <= v1):
                continue
            normal = outward_normal(face, su, sv, props)
            if normal is not None:
                return normal
    return None


def _normal_at(face, point):
    """Outward normal of `face` at the surface point nearest `point`, which may lie off
    the surface by up to twice the tolerance of the face's edges (a STEP from another
    system sews its faces a few 1e-4 mm apart)."""
    surface = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))
    uv = surface.ValueOfUV(gp_Pnt(*map(float, point)), 1e-7)
    if surface.Gap() < 0 or surface.Gap() > max(1e-4, 2 * BRep_Tool.MaxTolerance_s(face, TopAbs_EDGE)):
        return None
    return _normal_near(face, uv.X(), uv.Y())


def _vec(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], float)


def _point(p) -> tuple:
    return tuple(round(float(x), 6) for x in p)


def load_mesh(stl_path) -> trimesh.Trimesh:
    """The STL with its vertices merged and the triangles that repeat a vertex after
    the merge dropped: OCCT's meshes carry them at a sphere's poles and a cone's apex,
    and they would split the shell into bodies with open edges. A zero-area triangle
    with three distinct vertices can close a T-junction, so it stays."""
    mesh = trimesh.load(str(Path(stl_path)), force="mesh", process=True)
    if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty or not len(mesh.faces):
        raise ValueError(f"{Path(stl_path).name} holds no triangles")
    raw = len(mesh.faces)
    f = mesh.faces
    mesh.update_faces((f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2]))
    mesh.remove_unreferenced_vertices()
    if not len(mesh.faces):
        raise ValueError(f"{Path(stl_path).name} holds only degenerate triangles")
    mesh.metadata["raw_triangles"] = raw
    return mesh


def mesh_samples(mesh: trimesh.Trimesh, limit: int = MAX_MESH_RAYS) -> tuple[np.ndarray, np.ndarray]:
    """Four points per triangle (R04 §1) and the triangle's normal for each, from the
    triangles that have a normal (a zero-area triangle closing a T-junction has none);
    on a mesh with more than `limit` samples, triangles are drawn in proportion to
    their area (a fixed seed, so the same mesh gives the same samples)."""
    weights = np.array([(0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6), (1 / 3, 1 / 3, 1 / 3)])
    chosen = np.flatnonzero(np.linalg.norm(mesh.face_normals, axis=1) > 0.5)
    if 4 * len(chosen) > limit:
        rng = np.random.default_rng(0)
        area = mesh.area_faces[chosen]
        chosen = np.sort(rng.choice(chosen, size=limit // 4, replace=False, p=area / area.sum()))
    points = np.einsum("wk,tkd->twd", weights, mesh.triangles[chosen]).reshape(-1, 3)
    normals = np.repeat(mesh.face_normals[chosen], len(weights), axis=0)
    return points, normals


@measurement("min_wall_mesh", "mm")
def min_wall_mesh(stl_path, *, opposition_deg: float = 25.0, max_rays: int = MAX_MESH_RAYS) -> Result:
    """The same scan on an STL: four samples per triangle (at most `max_rays` rays,
    drawn by area on a larger mesh), the first triangle each inward ray leaves
    through, counted when opposed. Rays are cast with Embree in single precision,
    where a ray on a part a few hundred millimetres long can meet its own triangle,
    RAY_START behind its start, first: every hit nearer than MIN_HIT is skipped, and
    a ray left without an exit makes the result INCONCLUSIVE. Without Embree it is
    INCONCLUSIVE: trimesh's own engine runs out of memory on a real STL. The STL's
    coordinates are single precision too, so a wall reads within
    detail["vertex_precision_mm"] of the mesh's true wall. Corroboration only
    (D-025)."""
    mesh = load_mesh(stl_path)
    if not type(mesh.ray).__module__.endswith("ray_pyembree"):
        return inconclusive("min_wall_mesh", "mm", "no Embree on this platform (embreex has wheels for "
                            "x86-64 and macOS only), and trimesh's own ray engine runs out of memory on "
                            "a real STL", opposition_deg=opposition_deg)
    if mesh.is_watertight and mesh.volume < 0:
        return inconclusive("min_wall_mesh", "mm", "the mesh is inside out (negative volume): its rays "
                            "would measure the air", opposition_deg=opposition_deg)
    points, normals = mesh_samples(mesh, max_rays)
    origins = points - normals * RAY_START
    limit = -math.cos(math.radians(opposition_deg))
    best, walls, lost = None, 0, 0
    for c in range(0, len(points), MESH_CHUNK):
        rows = slice(c, c + MESH_CHUNK)
        count = len(origins[rows])
        tri, ray, where = mesh.ray.intersects_id(origins[rows], -normals[rows], return_locations=True,
                                                 multiple_hits=True, max_hits=MESH_HITS)
        ray = np.asarray(ray, int) + c
        distance = np.linalg.norm(where - origins[ray], axis=1) if len(ray) else np.empty(0)
        keep = distance > MIN_HIT                               # its own triangle is RAY_START behind it
        tri, ray, distance = np.asarray(tri)[keep], ray[keep], distance[keep]
        order = np.lexsort((distance, ray))                     # nearest exit first, per ray
        first = order[np.r_[True, ray[order][1:] != ray[order][:-1]]] if len(order) else order
        lost += count - len(first)
        if not len(first):
            continue
        opposed = np.einsum("ij,ij->i", mesh.face_normals[tri[first]], normals[ray[first]]) <= limit
        walls += int(opposed.sum())
        if opposed.any():
            k = first[opposed][np.argmin(distance[first][opposed])]
            if best is None or distance[k] + RAY_START < best[0]:
                best = (float(distance[k] + RAY_START), _point(points[ray[k]]))
    params = {"opposition_deg": opposition_deg, "samples_per_triangle": 4, "max_rays": max_rays}
    detail = {"triangles": int(len(mesh.faces)), "rays": int(len(points)), "opposed_hits": walls,
              "rays_without_exit": lost, "watertight": bool(mesh.is_watertight),
              "vertex_precision_mm": float(np.abs(mesh.bounds).max()) * 2.0 ** -VERTEX_BITS}
    if lost:
        return Result("min_wall_mesh", None, "mm", params=params, status=INCONCLUSIVE,
                      reason=f"{lost} of {len(points)} rays found no exit",
                      detail={**detail, "thinnest_found_mm": best[0] if best else None})
    if best is None:
        return Result("min_wall_mesh", None, "mm", params=params, status=INCONCLUSIVE,
                      reason="no opposed wall found", detail=detail)
    return Result("min_wall_mesh", best[0], "mm", at=best[1], params=params, detail=detail)


MESH_CENSUS = {"triangles": ("mesh_triangles", "count"), "bodies": ("mesh_bodies", "count"),
               "naked_edges": ("mesh_naked_edges", "count"), "winding": ("mesh_winding", "bool"),
               "volume": ("mesh_volume", "mm3")}


@measurement_set("mesh_census", MESH_CENSUS)
def mesh_census(stl_path) -> dict[str, Result]:
    """What a delivered mesh is: triangles (as in the file), bodies, open (naked)
    edges, whether its triangles wind consistently, and its signed volume, all after
    zero-area triangles are dropped. One closed shell facing out is bodies == 1,
    naked_edges == 0, winding == 1, and volume > 0 (the reviewer's V-05 check): an
    inside-out mesh has a negative volume."""
    mesh = load_mesh(stl_path)
    edges = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    bodies = len(trimesh.graph.connected_components(mesh.face_adjacency, min_len=1,
                                                     nodes=np.arange(len(mesh.faces)), engine="scipy"))
    raw = mesh.metadata["raw_triangles"]
    detail = {"degenerate_triangles": raw - len(mesh.faces)}
    return {"triangles": Result("mesh_triangles", raw, "count", detail=detail),
            "bodies": Result("mesh_bodies", bodies, "count"),
            "naked_edges": Result("mesh_naked_edges", int(len(edges)), "count"),
            "winding": Result("mesh_winding", int(mesh.is_winding_consistent), "bool"),
            "volume": (Result("mesh_volume", float(mesh.volume), "mm3") if mesh.is_watertight else
                       inconclusive("mesh_volume", "mm3", "an open mesh has no volume"))}


@measurement("mesh_deviation", "mm")
def mesh_deviation(stl_path, shape, *, reference_tolerance: float = 0.001) -> Result:
    """The largest distance between the STL and the B-rep, both ways, in mm: from the
    STL's vertices, edge midpoints, and triangle centres to the shape, and from the
    shape to the STL, so geometry missing from the mesh counts too. It is the
    tolerance the delivered mesh actually achieved (V-05). The shape is a reference
    mesh of a copy at `reference_tolerance`, so the result is exact to that tolerance.
    Each distance is exact to the nearest triangle (trimesh's proximity query), at
    about 0.25 ms per sample point: a 58k-triangle STL takes about two minutes."""
    mesh = load_mesh(stl_path)
    reference = reference_mesh(shape, reference_tolerance)
    worst = []
    for source, target in ((mesh, reference), (reference, mesh)):
        edges = source.vertices[source.edges_unique]
        points = np.vstack([source.vertices, source.triangles_center, edges.mean(axis=1)])
        distance = np.concatenate([trimesh.proximity.closest_point(target, points[c:c + MESH_CHUNK])[1]
                                   for c in range(0, len(points), MESH_CHUNK)])
        k = int(np.argmax(distance))
        worst.append((float(distance[k]), _point(points[k]), len(points)))
    (to_shape, at_mesh, n_mesh), (to_mesh, at_shape, n_shape) = worst
    at = at_mesh if to_shape >= to_mesh else at_shape
    return Result("mesh_deviation", max(to_shape, to_mesh), "mm", at=at,
                  params={"reference_tolerance_mm": reference_tolerance},
                  detail={"mesh_to_shape_mm": to_shape, "shape_to_mesh_mm": to_mesh,
                          "samples": n_mesh + n_shape, "reference_triangles": int(len(reference.faces))})


def reference_mesh(shape, tolerance: float) -> trimesh.Trimesh:
    """A fine mesh of a copy of the shape; the caller's shape keeps its own triangulation."""
    copy = BRepBuilderAPI_Copy(occ(shape)).Shape()
    mesher = BRepMesh_IncrementalMesh(copy, tolerance, False, 0.1, True)
    if not mesher.IsDone():
        raise RuntimeError("meshing the reference failed")
    vertices, triangles = [], []
    for face in faces(copy):
        location = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, location)
        if tri is None:
            raise RuntimeError("a face of the reference has no triangles")
        offset = len(vertices)
        transform = location.Transformation()
        for i in range(1, tri.NbNodes() + 1):
            p = tri.Node(i).Transformed(transform)
            vertices.append((p.X(), p.Y(), p.Z()))
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            triangles.append((offset + a - 1, offset + b - 1, offset + c - 1))
    return trimesh.Trimesh(np.array(vertices), np.array(triangles), process=False)
