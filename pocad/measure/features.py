# kaynak: oguz-atolye tools/measure/features.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Feature recognition on the B-rep (R04 §3, R02 §5.2, gate U-05).

Every feature is keyed on its geometry, never on a face index: a cylinder or a cone
by its true axis (BRepAdaptor_Surface.Cylinder().Axis()), because Face.center() of a
bore is the centroid of the surface patch, not a point on the axis, and a corner
fillet can share the bore's radius (R02 §5.2). Concave or convex is decided from the
outward normal against the radial direction, not from orientation flags.

Definitions, stated once:
- A B-spline or other freeform face within 0.01 mm of a cylinder or a cone
  (OCCT's canonical recognition) is taken as one: a bore stored as B-splines,
  whole, split, or fitted through points, is a bore.
- A bore is a set of concave cylindrical faces with one axis and one radius, joined
  along the axis, whose angles around the axis together (their union, so faces
  split along the axis are not counted twice) cover more than 180°. A concave
  arc of 180° or less is a fillet or the end of a slot, not a bore. Concave cones
  are grouped the same way: over 180° they are hole features (a countersink, a
  drill point, a chamfered hole edge), and at 180° or less a drafted corner.
- A bore end is open when the space just beyond it (0.001 mm and 0.6 radii along
  the axis, 0.01 mm inside the bore's wall, in four directions) is outside the
  solid; a flat bottom, a floor, a step to a narrower bore, a ball end, or a drill
  point closes it. Through means both ends are open. A floor thinner than 0.001 mm
  or a step of less than 0.01 mm in radius reads open, and a bore that opens into
  a feature narrower than itself reads closed.
- An inside corner is a sharp concave edge or a concave fillet: a cylindrical arc
  of 180° or less, a drafted corner (a conical one, at its narrow end), a torus, a
  sphere, or a freeform face. A freeform face is sampled, its boundary included,
  and a sample counts where its tightest curvature is concave, so the round on a
  hole's rim, convex across and concave around, is not a corner. A freeform face
  that wraps more than 180° around its tightest curvature, with that curvature
  the same all the way round, is a hole (a bent bore), and so is a torus round
  more than half its tube: neither is a corner. A bent bore split into pieces of
  half its tube or less is not recognised and reads as corners of its radius.
- Along a tool axis means closer to it than to the plane across it (within 45°):
  the corners between walls, upright or drafted, and not the edges of a floor.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d, BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.gp import gp_Cone, gp_Cylinder, gp_Dir
from OCP.ShapeAnalysis import ShapeAnalysis_CanonicalRecognition
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp, TopExp_Explorer

from pocad._ocp import IndexedDataMapOfShapeListOfShape, downcast
from pocad.core.shapes import faces, solids
from pocad.measure.sampling import Inside, face_grid, face_samples, kind, outward_normal
from pocad.result import INCONCLUSIVE, MEASURED, Result, inconclusive, measurement, measurement_set

KINDS = ("plane", "cylinder", "cone", "sphere", "torus", "bspline", "other")
SAME = 1e-6                     # mm (or radians): coaxial and equal-radius test
ALONG_COS = math.cos(math.radians(45.0))   # along a tool axis: closer to it than to the plane across it
PROBE_DEPTHS = (0.001, 0.6)     # beyond a bore's end: in mm, then in radii
PROBE_INSET_MM = 0.01           # inside the bore's wall
ROUND = 1.01                    # a curvature the same all the way round, within 1 %
RECOGNISE_MM = 0.01             # a freeform face this close to a cylinder or cone is one
FIT_SAME = 2 * RECOGNISE_MM     # mm: pieces fitted each on its own to one cylinder or cone
FIT_TURN = 0.02                 # radians: and their axes


def _vec(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], float)


def _point(p) -> tuple:
    return tuple(round(float(x), 6) for x in p)


def _unit(direction) -> np.ndarray:
    vector = np.array(direction, float)
    size = np.linalg.norm(vector)
    if vector.shape != (3,) or size < 1e-12:
        raise ValueError(f"a direction is a 3D vector, not {direction!r}")
    return vector / size


def canonical(direction: np.ndarray) -> np.ndarray:
    """One sign per axis: the first clearly non-zero component positive."""
    for value in direction:
        if abs(value) > 1e-9:
            return direction if value > 0 else -direction
    return direction


def cylinder(face) -> tuple[np.ndarray, np.ndarray, float]:
    """(point on the axis, unit axis direction, radius) of a cylindrical face."""
    cyl = BRepAdaptor_Surface(face).Cylinder()
    axis = cyl.Axis()
    return _vec(axis.Location()), _vec(axis.Direction()), float(cyl.Radius())


def concave(face, origin: np.ndarray, direction: np.ndarray) -> bool | None:
    """True when the outward normal points toward the axis (material outside the
    surface: a bore, a countersink, or an inside corner); None when the face has no
    usable sample."""
    for point, normal, _ in face_samples(face, 5.0, coarse=True, boundary=True):
        w = point - origin
        radial = w - np.dot(w, direction) * direction
        size = np.linalg.norm(radial)
        if size > 1e-9:
            return float(np.dot(normal, radial / size)) < 0
    return None


def _fit(face):
    """The cylinder or cone a freeform face lies on within RECOGNISE_MM (OCCT's
    canonical recognition), as ("cylinder", gp_Cylinder) or ("cone", gp_Cone), or
    None."""
    if kind(face) not in ("bspline", "other"):
        return None
    fitted = gp_Cylinder()
    if ShapeAnalysis_CanonicalRecognition(face).IsCylinder(RECOGNISE_MM, fitted):
        return "cylinder", fitted
    fitted = gp_Cone()
    if ShapeAnalysis_CanonicalRecognition(face).IsCone(RECOGNISE_MM, fitted):
        return "cone", fitted
    return None


def _edge_points(face, per_edge: int = 64) -> np.ndarray:
    """Points along every edge of a face: its boundary, where its extent around an
    axis and along it lies."""
    points = []
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = downcast.Edge(explorer.Current())
        explorer.Next()
        if BRep_Tool.Degenerated_s(edge):
            continue
        curve = BRepAdaptor_Curve(edge)
        points.extend(_vec(curve.Value(float(t)))
                      for t in np.linspace(curve.FirstParameter(), curve.LastParameter(), per_edge))
    return np.array(points)


def _revolved(solid) -> list[dict]:
    """Every cylindrical and conical face, analytic or a freeform face fitted to one:
    its axis, its radius (a cone's at its narrow end), its extent along the axis,
    and whether it is concave."""
    out = []
    for face in faces(solid):
        k = kind(face)
        fitted = _fit(face) if k in ("bspline", "other") else None
        if fitted is not None:
            k, surface = fitted
        elif k in ("cylinder", "cone"):
            adaptor = BRepAdaptor_Surface(face)
            surface = adaptor.Cylinder() if k == "cylinder" else adaptor.Cone()
        else:
            continue
        origin, direction = _vec(surface.Axis().Location()), _vec(surface.Axis().Direction())
        record = {"face": face, "kind": k, "origin": origin, "dir": direction, "fitted": fitted is not None}
        if fitted is None:
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
            record.update(u=(u0, u1), v=(v0, v1))
            if k == "cylinder":
                record.update(radius=float(surface.Radius()), ends=[origin + direction * v for v in (v0, v1)])
            else:
                angle = float(surface.SemiAngle())
                radii = [float(surface.RefRadius()) + v * math.sin(angle) for v in (v0, v1)]
                ends = [origin + direction * v * math.cos(angle) for v in (v0, v1)]
                narrow = int(radii[1] < radii[0])
                record.update(radius=max(0.0, radii[narrow]), narrow_end=ends[narrow], ends=ends)
        else:
            points = _edge_points(face)
            t = (points - origin) @ direction
            record.update(points=points, ends=[origin + direction * t.min(), origin + direction * t.max()])
            if k == "cylinder":
                record["radius"] = float(surface.Radius())
            else:
                radial = np.linalg.norm(points - origin - np.outer(t, direction), axis=1)
                narrow = int(np.argmin(radial))
                record.update(radius=float(radial[narrow]), narrow_end=origin + direction * t[narrow])
        if k == "cone":
            apex = _vec(surface.Apex())
            side = float(np.dot(0.5 * (record["ends"][0] + record["ends"][1]) - apex, direction))
            record.update(apex=apex, semi_angle=abs(float(surface.SemiAngle())),
                          nappe=direction if side > 0 else -direction)
        record["concave"] = concave(face, origin, direction)
        out.append(record)
    return out


def _same_surface(a: dict, b: dict) -> bool:
    """Whether two faces lie on one cylinder or one cone: to SAME, or where either was
    fitted, each piece on its own, to FIT_SAME with axes within FIT_TURN."""
    fitted = a["fitted"] or b["fitted"]
    same, turn = (FIT_SAME, FIT_TURN) if fitted else (SAME, SAME)
    if a["kind"] != b["kind"] or np.linalg.norm(np.cross(a["dir"], b["dir"])) > turn:
        return False
    w = b["origin"] - a["origin"]
    if np.linalg.norm(w - np.dot(w, a["dir"]) * a["dir"]) > same:
        return False
    if a["kind"] == "cylinder":
        return abs(a["radius"] - b["radius"]) <= (same if fitted else SAME * max(1.0, a["radius"]))
    reach = max(1.0, float(np.linalg.norm(a["narrow_end"] - a["apex"])))
    return (np.linalg.norm(a["apex"] - b["apex"]) <= same * reach
            and abs(a["semi_angle"] - b["semi_angle"]) <= turn and float(np.dot(a["nappe"], b["nappe"])) > 0)


def _groups(revolved: list[dict]) -> list[list[dict]]:
    """Faces of one cylinder or cone whose extents along the axis touch or overlap."""
    groups: list[list[dict]] = []
    for c in revolved:
        for group in groups:
            ref = group[0]
            if not _same_surface(ref, c):
                continue
            t = sorted(float(np.dot(e - ref["origin"], ref["dir"])) for e in c["ends"])
            spans = [sorted(float(np.dot(e - ref["origin"], ref["dir"])) for e in g["ends"]) for g in group]
            same = FIT_SAME if ref["fitted"] or c["fitted"] else SAME
            if any(t[0] <= s[1] + same and s[0] <= t[1] + same for s in spans):
                group.append(c)
                break
        else:
            groups.append([c])
    return groups


def _covered_degrees(group: list[dict], direction: np.ndarray) -> float:
    """The angle around the axis the faces cover together, in degrees: the union of
    their arcs, measured in one frame, so faces split along the axis count once."""
    origin = group[0]["origin"]
    x_ref = np.cross(direction, [1.0, 0.0, 0.0] if abs(direction[0]) < 0.9 else [0.0, 1.0, 0.0])
    x_ref /= np.linalg.norm(x_ref)
    y_ref = np.cross(direction, x_ref)
    def angle(point: np.ndarray) -> float:
        w = point - origin
        return math.degrees(math.atan2(float(np.dot(w, y_ref)), float(np.dot(w, x_ref)))) % 360.0

    arcs = []
    for c in group:
        if c["fitted"]:                               # the whole turn less the widest gap in its boundary
            around = np.sort([angle(point) for point in c["points"]])
            gaps = np.diff(np.append(around, around[0] + 360.0))
            k = int(np.argmax(gaps))
            arcs.append((float(around[(k + 1) % len(around)]), float(360.0 - gaps[k])))
            continue
        surface = BRepAdaptor_Surface(c["face"])
        (u0, u1), (v0, v1) = c["u"], c["v"]
        width = math.degrees(u1 - u0)
        if width >= 360.0 - 1e-6:
            return 360.0
        start = angle(_vec(surface.Value(u0, 0.5 * (v0 + v1))))
        quarter = angle(_vec(surface.Value(u0 + 0.25 * (u1 - u0), 0.5 * (v0 + v1))))
        forward = (quarter - start) % 360.0 <= 180.0         # which way u turns in this frame
        arcs.append((start if forward else (start - width) % 360.0, width))
    pieces = []
    for start, width in arcs:
        end = start + width
        pieces.extend([(start, 360.0), (0.0, end - 360.0)] if end > 360.0 else [(start, end)])
    pieces.sort()
    total, (low, high) = 0.0, pieces[0]
    for a, b in pieces[1:]:
        if a <= high + 1e-6:
            high = max(high, b)
        else:
            total, low, high = total + high - low, a, b
    return min(360.0, total + high - low)


def _open_end(inside: Inside, point: np.ndarray, outward: np.ndarray, radius: float) -> bool:
    helper = np.array([1.0, 0.0, 0.0]) if abs(outward[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(outward, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(outward, e1)
    off = radius - min(PROBE_INSET_MM, 0.5 * radius)
    for depth in (PROBE_DEPTHS[0], PROBE_DEPTHS[1] * radius):
        for side in (e1, -e1, e2, -e2):
            if inside.on_or_in(point + outward * depth + side * off):
                return False
    return True


def _bores(shape, *, ends: bool = True) -> tuple[list[dict], list[dict], list[dict]]:
    """(bores, concave cylindrical arcs of 180° or less, drafted corners), each
    located, per solid. Concave cones over 180° (countersinks, drill points) are
    hole features, none of the three. With `ends` false the bores' ends are not
    probed, and open_ends and through are left out."""
    bores, arcs, drafted = [], [], []
    for index, solid in enumerate(solids(shape)):
        inside = Inside(solid)
        for group in _groups([r for r in _revolved(solid) if r["concave"]]):
            ref = group[0]
            direction = canonical(ref["dir"])
            span = _covered_degrees(group, direction)
            axis_dir = tuple(round(float(x), 9) for x in direction)
            fitted = any(g["fitted"] for g in group)
            if ref["kind"] == "cone":
                if span <= 180.0 + 1e-6:
                    narrow = min(group, key=lambda g: g["radius"])
                    drafted.append({"solid": index, "radius": narrow["radius"], "axis_dir": axis_dir,
                                    "start": _point(narrow["narrow_end"]), "span_deg": round(span, 6),
                                    "faces": len(group), "fitted": fitted})
                continue
            ts = [float(np.dot(e - ref["origin"], direction)) for g in group for e in g["ends"]]
            t0, t1 = min(ts), max(ts)
            start, end = ref["origin"] + direction * t0, ref["origin"] + direction * t1
            record = {"solid": index, "diameter": 2 * ref["radius"], "radius": ref["radius"],
                      "axis_dir": axis_dir, "start": _point(start), "end": _point(end),
                      "length": t1 - t0, "span_deg": round(span, 6), "faces": len(group), "fitted": fitted}
            if span > 180.0 + 1e-6:
                if ends:
                    opened = [_open_end(inside, start, -direction, ref["radius"]),
                              _open_end(inside, end, direction, ref["radius"])]
                    record.update(open_ends=opened, through=all(opened))
                bores.append(record)
            else:
                arcs.append(record)
    bores.sort(key=lambda b: (b["start"], b["diameter"]))
    return bores, arcs, drafted


@measurement("bore_census", "count")
def bore_census(shape) -> Result:
    """How many bores the shape has; detail["bores"] lists each one's diameter, axis
    direction, start and end points on the axis, length, angular span, and through."""
    bores, arcs, _ = _bores(shape)
    return Result("bore_census", len(bores), "count",
                  detail={"bores": bores, "concave_arcs": len(arcs)})


LOCATED = {"diameter": ("bore_diameter", "mm"), "offset": ("bore_axis_offset", "mm"),
           "length": ("bore_length", "mm"), "through": ("bore_through", "bool")}


@measurement_set("locate_bore", LOCATED)
def locate_bore(census: Result, point, direction=None) -> dict[str, Result]:
    """The bore whose axis segment passes nearest `point` (and runs along
    `direction`, when given): its diameter, how far the point is from that segment,
    its length, and whether it goes through (R04: a located claim needs a located
    measurement). Give a point on the bore's axis between its ends, such as the
    centre of its entry: a bore drilled from the other face, or one missing where a
    coaxial bore exists further along, then reads as far off. Gate each value."""
    if census.status != MEASURED:
        return {k: inconclusive(n, u, census.reason) for k, (n, u) in LOCATED.items()}
    target = np.array(point, float)
    want = None if direction is None else canonical(_unit(direction))
    best = None
    for bore in census.detail["bores"]:
        axis = np.array(bore["axis_dir"])
        if want is not None and np.linalg.norm(np.cross(axis, want)) > 1e-6:
            continue
        start, end = np.array(bore["start"]), np.array(bore["end"])
        t = float(np.clip(np.dot(target - start, axis), 0.0, np.linalg.norm(end - start)))
        offset = float(np.linalg.norm(target - (start + t * axis)))
        if best is None or offset < best[0]:
            best = (offset, bore)
    if best is None:
        return {k: inconclusive(n, u, "no bore along that direction") for k, (n, u) in LOCATED.items()}
    offset, bore = best
    params = {"near": tuple(point), "direction": None if want is None else tuple(want)}
    detail = {k: bore[k] for k in ("start", "end", "span_deg", "open_ends")}
    return {"diameter": Result("bore_diameter", bore["diameter"], "mm", at=bore["start"],
                               params=params, detail=detail),
            "offset": Result("bore_axis_offset", offset, "mm", at=bore["start"], params=params,
                             detail=detail),
            "length": Result("bore_length", bore["length"], "mm", at=bore["start"], params=params,
                             detail=detail),
            "through": Result("bore_through", int(bore["through"]), "bool", at=bore["start"],
                              params=params, detail=detail)}


CENSUS = {**{f"{k}_faces": (f"feature_census_{k}_faces", "count") for k in KINDS},
          "concave_cylinders": ("feature_census_concave_cylinders", "count"),
          "convex_cylinders": ("feature_census_convex_cylinders", "count"),
          "bores": ("feature_census_bores", "count")}


@measurement_set("feature_census", CENSUS)
def feature_census(shape) -> dict[str, Result]:
    """Faces per surface kind, cylinders split into concave and convex, and bores:
    the counts gate U-05 compares with the plan's feature list (R02 recommendation 1)."""
    counts = {k: 0 for k in KINDS}
    concave_cylinders = convex_cylinders = 0
    for solid in solids(shape):
        for face in faces(solid):
            counts[kind(face)] += 1
        for c in _revolved(solid):
            if c["kind"] != "cylinder":
                continue
            if c["concave"]:
                concave_cylinders += 1
            elif c["concave"] is False:
                convex_cylinders += 1
    bores, _, _ = _bores(shape)
    out = {f"{k}_faces": Result(f"feature_census_{k}_faces", n, "count") for k, n in counts.items()}
    out["concave_cylinders"] = Result("feature_census_concave_cylinders", concave_cylinders, "count")
    out["convex_cylinders"] = Result("feature_census_convex_cylinders", convex_cylinders, "count")
    out["bores"] = Result("feature_census_bores", len(bores), "count", detail={"bores": bores})
    return out


def _along(direction, want) -> bool:
    return want is None or abs(float(np.dot(np.array(direction, float), want))) >= ALONG_COS


def sharp_concave_edges(solid, *, axis=None, probe: float = 0.02, sharp_deg: float = 5.0) -> list[tuple]:
    """Midpoints of edges where two faces meet at an inside corner sharper than
    `sharp_deg`, found by two probe points that both land in material (R04 §1). The
    normals are taken on each face at the edge itself, through its pcurve. With
    `axis`, only edges running along it (within 45°) count."""
    want = None if axis is None else _unit(axis)
    ancestry = IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid, TopAbs_EDGE, TopAbs_FACE, ancestry)
    inside = Inside(solid)
    found = []
    for i in range(1, ancestry.Extent() + 1):
        adjacent = [downcast.Face(f) for f in ancestry.FindFromIndex(i)]
        if len(adjacent) != 2 or adjacent[0].IsSame(adjacent[1]):
            continue                                 # a free, naked, or seam edge
        edge = downcast.Edge(ancestry.FindKey(i))
        if BRep_Tool.Degenerated_s(edge):
            continue
        curve = BRepAdaptor_Curve(edge)
        t = 0.5 * (curve.FirstParameter() + curve.LastParameter())
        middle = _vec(curve.Value(t))
        if want is not None:
            tangent = curve.DN(t, 1)
            size = tangent.Magnitude()
            if size < 1e-12 or not _along(_vec(tangent) / size, want):
                continue
        normals = []
        for face in adjacent:
            uv = BRepAdaptor_Curve2d(edge, face).Value(t)
            normal = outward_normal(face, uv.X(), uv.Y())
            if normal is not None:
                normals.append(normal)
        if len(normals) != 2:
            continue
        cos = max(-1.0, min(1.0, float(np.dot(normals[0], normals[1]))))
        if math.degrees(math.acos(cos)) < sharp_deg:
            continue
        d = normals[0] - normals[1]
        size = np.linalg.norm(d)
        if size < 1e-12:
            continue
        d /= size
        if inside(middle + probe * d) and inside(middle - probe * d):
            found.append(_point(middle))
    return found


def _turning(line: list) -> float:
    """How far, in degrees, the normal turns along one iso line of samples."""
    line.sort(key=lambda s: s[0])
    return sum(math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(a[1], b[1]))))))
               for a, b in zip(line, line[1:]))


def _freeform_corner(face, spacing: float, grid, want):
    """(radius, where) of a freeform face's tightest concave curvature where that is
    its tightest curvature and, given a tool axis, the face runs along it there;
    "hole" for a face that wraps more than 180° around its tightest curvature with
    that curvature the same all the way round (a bore or a countersink as
    B-splines); None when it has no inside corner."""
    props = GeomLProp_SLProps(BRep_Tool.Surface_s(face), 2, 1e-7)
    flip = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
    lines = {"u": defaultdict(list), "v": defaultdict(list)}     # the u lines run at fixed v
    bends = []
    for point, normal, (u, v) in face_samples(face, spacing, grid, boundary=True):
        lines["u"][v].append((u, normal))
        lines["v"][u].append((v, normal))
        props.SetParameters(u, v)
        if not props.IsCurvatureDefined():
            continue
        k_max, k_min = props.MaxCurvature(), props.MinCurvature()
        across = spine = None
        if not props.IsUmbilic():
            d_max, d_min = gp_Dir(), gp_Dir()
            props.CurvatureDirections(d_max, d_min)
            if abs(k_min) > abs(k_max):
                d_max, d_min = d_min, d_max
            across, spine = _vec(d_max), _vec(d_min)
        bend = flip * (k_max if abs(k_max) >= abs(k_min) else k_min)   # positive: toward the air
        if bend <= 1e-6:
            continue                                  # convex or flat across its tightest curvature
        du, dv = _vec(props.D1U()), _vec(props.D1V())
        runs = None if across is None else (
            "u" if abs(np.dot(across, du)) * np.linalg.norm(dv) >= abs(np.dot(across, dv)) * np.linalg.norm(du)
            else "v")
        bends.append({"radius": 1.0 / bend, "at": _point(point), "runs": runs, "spine": spine,
                      "line": v if runs == "u" else u})
    if not bends:
        return None
    for d in ("u", "v"):
        if all(b["runs"] == d for b in bends) and max(map(_turning, lines[d].values()), default=0.0) > 180.0 + 1e-6:
            rounds = defaultdict(list)
            for b in bends:
                rounds[b["line"]].append(b["radius"])
            spreads = [max(r) / min(r) for r in rounds.values() if len(r) > 1]
            if spreads and max(spreads) <= ROUND:
                return "hole"
    counted = [b for b in bends if want is None or (b["spine"] is not None and _along(b["spine"], want))]
    if not counted:
        return None
    best = min(counted, key=lambda b: b["radius"])
    return best["radius"], best["at"]


def _blend_radii(solid, spacing: float, want) -> tuple[list[tuple], dict]:
    """(radius, where, what) of every concave torus, sphere, and freeform corner, and
    counts for the detail: the largest sampling step, and the freeform faces taken for
    holes. With a tool axis, tori and spheres are a floor's blends and do not count."""
    out, info = [], {"largest_step_mm": 0.0, "freeform_holes": 0}
    for face in faces(solid):
        k = kind(face)
        adaptor = BRepAdaptor_Surface(face)
        if k == "torus" and want is None:
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
            if v1 - v0 > math.pi + 1e-9:
                continue                              # round more than half its tube: a bent bore
            torus = adaptor.Torus()
            centre, axis = _vec(torus.Location()), _vec(torus.Axis().Direction())
            for point, normal, _ in face_samples(face, spacing, coarse=True, boundary=True):
                w = point - centre
                w -= np.dot(w, axis) * axis
                if np.linalg.norm(w) < 1e-9:
                    continue
                tube = centre + torus.MajorRadius() * w / np.linalg.norm(w)
                if float(np.dot(normal, tube - point)) > 0:           # the normal faces the tube's core
                    out.append((float(torus.MinorRadius()), _point(point), "torus"))
                break
        elif k == "sphere" and want is None:
            centre = _vec(adaptor.Sphere().Location())
            for point, normal, _ in face_samples(face, spacing, coarse=True, boundary=True):
                if float(np.dot(normal, centre - point)) > 0:
                    out.append((float(adaptor.Sphere().Radius()), _point(point), "sphere"))
                break
        elif k in ("bspline", "other"):
            if _fit(face) is not None:
                continue                              # a cylinder or cone: read with them
            grid = face_grid(face, spacing)
            info["largest_step_mm"] = max(info["largest_step_mm"], grid.step_mm)
            found = _freeform_corner(face, spacing, grid, want)
            if found == "hole":
                info["freeform_holes"] += 1
            elif found:
                out.append((*found, "freeform, sampled"))
    return out, info


@measurement("min_internal_radius", "mm")
def min_internal_radius(shape, *, axis=None, spacing: float = 0.5) -> Result:
    """The smallest inside-corner radius, in mm (R04 §1): 0 when any inside edge is
    sharp, else the smallest concave fillet; detail["from"] says which kind. A part
    with no inside corner has no such radius: INCONCLUSIVE, and the row does not
    apply. Freeform faces are sampled `spacing` mm apart, their boundary included:
    detail["largest_step_mm"] is the step used, and a sampled radius can read a
    little above the true one between samples.

    With `axis`, the axis of a milling tool, only the corners it cuts count: sharp
    edges, cylinders and cones, and freeform corners running along it (within 45°),
    so the sharp floor edges a flat end mill leaves do not read 0, and tori and
    spheres, a floor's blends, are left out. Without it, every inside corner
    counts, as a moulded or cast part needs."""
    want = None if axis is None else _unit(axis)
    found = solids(shape)
    sharp = [e for solid in found for e in sharp_concave_edges(solid, axis=want)]
    params = {"axis": None if want is None else tuple(float(x) for x in want), "spacing_mm": spacing}
    if sharp:                                     # nothing is smaller: the fillets need not be read
        return Result("min_internal_radius", 0.0, "mm", at=sharp[0], params=params,
                      detail={"sharp_concave_edges": len(sharp)})
    _, arcs, drafted = _bores(shape, ends=False)
    fit = {False: "", True: ", fitted"}
    radii = [(a["radius"], a["start"], "cylinder" + fit[a["fitted"]]) for a in arcs if _along(a["axis_dir"], want)]
    radii += [(c["radius"], c["start"], "cone, at its narrow end" + fit[c["fitted"]])
              for c in drafted if _along(c["axis_dir"], want)]
    info = {"largest_step_mm": 0.0, "freeform_holes": 0}
    for solid in found:
        blends, counts = _blend_radii(solid, spacing, want)
        radii += blends
        info = {"largest_step_mm": max(info["largest_step_mm"], counts["largest_step_mm"]),
                "freeform_holes": info["freeform_holes"] + counts["freeform_holes"]}
    detail = {"sharp_concave_edges": 0, "fillet_radii": sorted({round(r, 9) for r, _, _ in radii}),
              "largest_step_mm": round(float(info["largest_step_mm"]), 6), "freeform_holes": info["freeform_holes"]}
    if radii:
        radius, at, source = min(radii, key=lambda r: r[0])
        return Result("min_internal_radius", radius, "mm", at=at, params=params,
                      detail={**detail, "from": source})
    return Result("min_internal_radius", None, "mm", params=params, status=INCONCLUSIVE,
                  reason="no inside corner on this part", detail=detail)


@measurement("sharp_concave_edge_count", "count")
def sharp_concave_edge_count(shape, *, axis=None) -> Result:
    """How many inside edges are sharp (no fillet), with the first one's midpoint;
    with `axis`, only those running along it (within 45°)."""
    want = None if axis is None else _unit(axis)
    sharp = [e for solid in solids(shape) for e in sharp_concave_edges(solid, axis=want)]
    return Result("sharp_concave_edge_count", len(sharp), "count", at=sharp[0] if sharp else None,
                  params={"axis": None if want is None else tuple(float(x) for x in want)},
                  detail={"edges": sharp[:20]})
