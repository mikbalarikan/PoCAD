# kaynak: oguz-atolye tools/measure/sampling.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Face sampling shared by the measurements (R04 §1).

A face is sampled on its trimmed UV grid at a model-space spacing; each sample
carries its point and its outward unit normal. The normal comes from the surface
and is flipped for a reversed face, never trusted from an orientation flag alone
(REFERENCE-LIBRARY §3.5: a reversed-normal bug).

A grid never silently gets coarser than the spacing asked for: a face that would
need more than MAX_SAMPLES_PER_FACE samples raises Undersampled, which a
measurement turns into INCONCLUSIVE naming the spacing that would fit. Helpers
that only need a few samples (concavity) ask for a coarse grid on purpose.

Where a measurement changes by at most a known amount per mm (it is Lipschitz),
search_cells bounds it over whole faces rather than at samples: every point of a
grid cell lies within the cell's reach of its centre, so a centre that reads m
bounds the cell to m ± L·reach, and a cell that could still cross the caller's
limit is split in four, until it cannot, or SEARCH_DEPTH or SEARCH_CELLS is spent.
A cell whose centre lies off the trimmed face is dropped only when no sample of the
face's edges lies within its reach: otherwise the face runs through it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint, GCPnts_UniformAbscissa
from OCP.GeomAbs import (
    GeomAbs_BSplineCurve,
    GeomAbs_BSplineSurface,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_SurfaceOfExtrusion,
    GeomAbs_SurfaceOfRevolution,
    GeomAbs_Torus,
)
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.gp import gp_Pnt, gp_Pnt2d, gp_Vec
from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_REVERSED
from scipy.spatial import cKDTree

from pocad._ocp import FClass2d

KINDS = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone",
         GeomAbs_Sphere: "sphere", GeomAbs_Torus: "torus", GeomAbs_BSplineSurface: "bspline"}
MAX_SAMPLES_PER_FACE = 250_000
REACH_GRID = 33                 # nodes per parameter direction where a face's speed is measured, at least
NODES_PER_SPAN = 8              # and this many per polynomial piece of a B-spline
MAX_REACH_NODES = 65_536        # at most, over the whole grid
ORTHOGONAL = {"plane", "cylinder", "cone", "sphere", "torus"}   # kinds whose u and v run square to each other
SEARCH_DEPTH = 12               # a cell is split at most this many times, its reach 4096 times smaller
SEARCH_CELLS = 25_000           # cells one search splits, over all its faces, before it stops splitting


class Undersampled(ValueError):
    """A face too large to sample at the spacing asked for."""


@dataclass(frozen=True)
class Grid:
    nu: int
    nv: int
    step_mm: float          # the largest distance between neighbouring samples


def kind(face) -> str:
    """plane, cylinder, cone, sphere, torus, bspline, or other."""
    return KINDS.get(BRepAdaptor_Surface(face).GetType(), "other")


def outward_normal(face, u: float, v: float, props=None):
    """Outward unit normal at (u, v), or None where the surface has none: nor at a
    collapsed edge (a pole, an apex), where a B-spline reports a normal all the
    same, and a wrong one."""
    props = props or GeomLProp_SLProps(BRep_Tool.Surface_s(face), 1, 1e-7)
    props.SetParameters(u, v)
    if not props.IsNormalDefined():
        return None
    speed_u, speed_v = props.D1U().Magnitude(), props.D1V().Magnitude()
    if min(speed_u, speed_v) <= 1e-9 * max(1.0, speed_u, speed_v):
        return None
    n = props.Normal()
    vec = np.array([n.X(), n.Y(), n.Z()], float)
    norm = np.linalg.norm(vec)
    if norm < 1e-12:
        return None
    vec /= norm
    return -vec if face.Orientation() == TopAbs_REVERSED else vec


def face_grid(face, spacing: float, *, coarse: bool = False) -> Grid:
    """The sample grid of one face at `spacing` mm. Raises Undersampled when it would
    need more than MAX_SAMPLES_PER_FACE samples, unless `coarse`, which thins it."""
    if not spacing > 0:
        raise ValueError(f"spacing must be positive, not {spacing!r}")
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    reach_u, reach_v = _reach(BRepAdaptor_Surface(face), (u0, u1, v0, v1))
    nu, nv = (max(3, math.ceil(reach / spacing) + 1) for reach in (reach_u, reach_v))
    if nu * nv > MAX_SAMPLES_PER_FACE:
        if not coarse:
            raise Undersampled(f"a {reach_u:.0f} x {reach_v:.0f} mm face needs {nu * nv} samples at "
                               f"{spacing:g} mm, more than {MAX_SAMPLES_PER_FACE}; a spacing of "
                               f"{_spacing_that_fits(reach_u, reach_v, spacing):g} mm fits")
        while nu * nv > MAX_SAMPLES_PER_FACE:
            nu, nv = max(3, nu // 2), max(3, nv // 2)
    return Grid(nu, nv, max(reach_u / nu, reach_v / nv))


def face_samples(face, spacing: float, grid: Grid | None = None, *, coarse: bool = False,
                 boundary: bool = False):
    """Yield (point, outward normal, (u, v)) on the trimmed UV grid of one face,
    no more than `spacing` mm apart (see face_grid). With `boundary`, the rows and
    columns at the edges of the parameter range are sampled too, where an extreme
    (the tightest radius of a drafted corner) often lies."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    if not all(map(math.isfinite, (u0, u1, v0, v1))):
        return
    grid = grid or face_grid(face, spacing, coarse=coarse)
    surface = BRepAdaptor_Surface(face)
    props = GeomLProp_SLProps(BRep_Tool.Surface_s(face), 1, 1e-7)
    inside = FClass2d(face, 1e-7)
    us = [u0 + (u1 - u0) * (i + 0.5) / grid.nu for i in range(grid.nu)]
    vs = [v0 + (v1 - v0) * (j + 0.5) / grid.nv for j in range(grid.nv)]
    accept = (TopAbs_IN,)
    if boundary:
        us = [u0 + (u1 - u0) * 1e-9] + us + [u1 - (u1 - u0) * 1e-9]
        vs = [v0 + (v1 - v0) * 1e-9] + vs + [v1 - (v1 - v0) * 1e-9]
        accept = (TopAbs_IN, TopAbs_ON)
    for u in us:
        for v in vs:
            if inside.Perform(gp_Pnt2d(u, v)) not in accept:
                continue
            normal = outward_normal(face, u, v, props)
            if normal is None:
                continue
            p = surface.Value(u, v)
            yield np.array([p.X(), p.Y(), p.Z()], float), normal, (u, v)


def _reach(surface, bounds) -> tuple[float, float]:
    """The model-space lengths across the face along u and along v if all of it ran
    at its fastest: the surface's speed (the length of its first derivative) on a
    grid of nodes over its parameter box, REACH_GRID each way and NODES_PER_SPAN per
    polynomial piece of a B-spline, exact at the nodes, the edges included, where a
    face often runs fastest. Where the speed changes at all, 1 % is added for a peak
    between nodes. A grid sized from them keeps its largest step, not only its mean
    step, within the spacing."""
    u0, u1, v0, v1 = bounds
    if not all(map(math.isfinite, bounds)):
        return 0.0, 0.0
    spans_u, spans_v = _spans(surface)
    count_u, count_v = (max(REACH_GRID, NODES_PER_SPAN * spans + 1) for spans in (spans_u, spans_v))
    shrink = math.sqrt(min(1.0, MAX_REACH_NODES / (count_u * count_v)))
    count_u, count_v = max(REACH_GRID, int(count_u * shrink)), max(REACH_GRID, int(count_v * shrink))
    speed_u, speed_v = np.empty((count_u, count_v)), np.empty((count_u, count_v))
    point, d_u, d_v = gp_Pnt(), gp_Vec(), gp_Vec()
    for i, u in enumerate(np.linspace(u0, u1, count_u)):
        for j, v in enumerate(np.linspace(v0, v1, count_v)):
            surface.D1(float(u), float(v), point, d_u, d_v)
            speed_u[i, j], speed_v[i, j] = d_u.Magnitude(), d_v.Magnitude()
    reaches = []
    for speed, span in ((speed_u, u1 - u0), (speed_v, v1 - v0)):
        even = speed.max() <= 1.0001 * speed.min()
        reaches.append(float(speed.max()) * span * (1.0 if even else 1.01))
    return reaches[0], reaches[1]


def _spans(surface) -> tuple[int, int]:
    """How many polynomial pieces the surface has along u and along v: its knot spans
    for a B-spline, its curve's for a surface of revolution or extrusion, 1 else."""
    k = surface.GetType()
    try:
        if k == GeomAbs_BSplineSurface:
            return surface.NbUKnots() - 1, surface.NbVKnots() - 1
        if k in (GeomAbs_SurfaceOfRevolution, GeomAbs_SurfaceOfExtrusion):
            curve = surface.BasisCurve()
            pieces = curve.NbKnots() - 1 if curve.GetType() == GeomAbs_BSplineCurve else 1
            return (1, pieces) if k == GeomAbs_SurfaceOfRevolution else (pieces, 1)
    except Exception:                                               # noqa: BLE001: fall back to the grid
        pass
    return 1, 1


def _cells(reach_u: float, reach_v: float, spacing: float) -> int:
    return max(3, math.ceil(reach_u / spacing) + 1) * max(3, math.ceil(reach_v / spacing) + 1)


def _spacing_that_fits(reach_u: float, reach_v: float, spacing: float) -> float:
    """The smallest spacing of two significant figures whose grid stays within
    MAX_SAMPLES_PER_FACE, checked with the grid's own count."""
    s = spacing * math.sqrt(_cells(reach_u, reach_v, spacing) / MAX_SAMPLES_PER_FACE)
    while True:
        unit = 10.0 ** (math.floor(math.log10(s)) - 1)
        candidate = float(f"{math.ceil(s / unit - 1e-9) * unit:.2g}")
        if candidate >= s and _cells(reach_u, reach_v, candidate) <= MAX_SAMPLES_PER_FACE:
            return candidate
        s = max(s, candidate) + unit


class Inside:
    """Point-in-solid classification against one solid (BRepClass3d misreads a
    Compound of touching solids: docs/BUILD123D-NOTLARI.md)."""

    def __init__(self, solid, tolerance: float = 1e-7):
        self.classifier = BRepClass3d_SolidClassifier(solid)
        self.tolerance = tolerance

    def __call__(self, point) -> bool:
        self.classifier.Perform(gp_Pnt(*map(float, point)), self.tolerance)
        return self.classifier.State() == TopAbs_IN

    def on_or_in(self, point) -> bool:
        return self.state(point) in (TopAbs_IN, TopAbs_ON)

    def state(self, point):
        """TopAbs_IN, TopAbs_ON, or TopAbs_OUT."""
        self.classifier.Perform(gp_Pnt(*map(float, point)), self.tolerance)
        return self.classifier.State()


def edge_points(edge, spacing: float) -> tuple[list, float]:
    """Points along one edge no more than `spacing` mm apart along it, both ends
    included, as (point, unit tangent or None) pairs, and the step used. A collapsed
    edge (a pole, an apex) is a point and yields nothing."""
    if not spacing > 0:
        raise ValueError(f"spacing must be positive, not {spacing!r}")
    if BRep_Tool.Degenerated_s(edge):
        return [], 0.0
    curve = BRepAdaptor_Curve(edge)
    length = GCPnts_AbscissaPoint.Length_s(curve)
    count = max(2, math.ceil(length / spacing) + 1)
    uniform = GCPnts_UniformAbscissa(curve, count, 1e-9)
    if uniform.IsDone() and uniform.NbPoints() >= 2:
        params = [uniform.Parameter(i) for i in range(1, uniform.NbPoints() + 1)]
    else:                                                      # a curve OCCT cannot measure evenly
        first, last = curve.FirstParameter(), curve.LastParameter()
        params = list(np.linspace(first, last, count))
    point, tangent, out = gp_Pnt(), gp_Vec(), []
    for u in params:
        curve.D1(float(u), point, tangent)
        size = tangent.Magnitude()
        direction = None if size < 1e-12 else np.array([tangent.X(), tangent.Y(), tangent.Z()]) / size
        out.append((np.array([point.X(), point.Y(), point.Z()], float), direction))
    return out, length / (len(params) - 1)


def cell_reach(face, grid: Grid) -> float:
    """How far, at most, any point of one of the grid's cells lies from the cell's
    centre in mm, along the face: half the cell's diagonal where u and v run square to
    each other (every analytic kind), the whole step elsewhere (the two half sides
    added). The step comes from the face's fastest speed, so this holds everywhere."""
    return grid.step_mm * (math.sqrt(0.5) if kind(face) in ORTHOGONAL else 1.0)


@dataclass
class Search:
    """What a search_cells run over one or more faces left: every cell it could not
    settle, as (bound, point, reach), and how many it split."""

    unsettled: list = field(default_factory=list)
    split: int = 0
    visited: int = 0
    budget: int = SEARCH_CELLS


def search_cells(face, grid: Grid, visit, search: Search, *, edges=None, edge_step: float = 0.0,
                 edge_values=None) -> None:
    """Branch and bound over the cells of one face's grid. Each cell is read at its
    centre, a level of cells at a time: visit(points, inside, reaches) returns, per
    cell, None (or NaN) when the cell is settled, or the bound it could still reach,
    and the cell is then split in four (its reach halved) until SEARCH_DEPTH or the
    search's budget, when it stays in search.unsettled. `inside` says whether each
    centre lies on the trimmed face; the face's own
    parameters run past its trim, so a centre off it is still a point of its surface,
    and bounds the cell the same way. With `edges` (samples of the face's edges,
    `edge_step` apart), a centre off the face with no edge sample within its reach
    plus half the step holds no point of the face (the face would cross its edge on
    the way to it) and is dropped unread. With `edge_values` too (the measurement at
    each edge sample), visit is given a fourth argument: for a centre off the face,
    the least value over the edge samples within its reach plus half the step (NaN
    otherwise). Every point of the face in such a cell lies within that distance of
    one of them, since the face crosses its edge between the point and the centre,
    so the cell can be bounded from them, real points of the face, rather than from
    the surface running on past its trim."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    if not all(map(math.isfinite, (u0, u1, v0, v1))):
        raise ValueError("a face with unbounded parameters")
    surface = BRepAdaptor_Surface(face)
    classify = FClass2d(face, 1e-7)
    tree = cKDTree(np.asarray(edges, float)) if edges is not None and len(edges) else None
    values = None if edge_values is None or tree is None else list(edge_values)
    reach0, speeds = cell_reach(face, grid), _speeds(surface)
    du, dv = (u1 - u0) / grid.nu, (v1 - v0) / grid.nv
    level = [(u0 + i * du, v0 + j * dv, du, dv) for i in range(grid.nu) for j in range(grid.nv)]
    depth = 0
    while level:                                   # breadth first: the budget goes coarse to fine
        centres, inside = [], []
        for u, v, su, sv in level:
            cu, cv = u + su / 2, v + sv / 2
            p = surface.Value(cu, cv)
            centres.append((p.X(), p.Y(), p.Z()))
            inside.append(classify.Perform(gp_Pnt2d(cu, cv)) in (TopAbs_IN, TopAbs_ON))
        centres = np.array(centres, float)
        if speeds is None:
            reaches = np.full(len(level), reach0 / 2 ** depth)
        else:
            reaches = np.array([math.hypot(a * su, b * sv) / 2 * (1 + 1e-9)
                                for (u, v, su, sv) in level for a, b in [speeds(v, v + sv)]])
        keep = np.ones(len(level), bool)
        off = ~np.array(inside)
        if tree is not None and off.any():
            gap, _ = tree.query(centres[off])
            keep[np.flatnonzero(off)] = gap <= reaches[off] + edge_step / 2
        following, read = [], np.flatnonzero(keep)
        search.visited += len(read)
        floors = np.full(len(level), np.nan)
        if values is not None:
            for k in np.flatnonzero(keep & off):
                near = tree.query_ball_point(centres[k], reaches[k] + edge_step / 2)
                floors[k] = min(values[j] for j in near) if near else np.nan
        bounds = visit(centres[read], np.array(inside)[read], reaches[read], floors[read]) if len(read) else []
        for k, bound in zip(read, bounds):
            if bound is None or math.isnan(bound):
                continue
            if depth >= SEARCH_DEPTH or search.split >= search.budget:
                search.unsettled.append((bound, centres[k], float(reaches[k])))
                continue
            search.split += 1
            u, v, su, sv = level[k]
            hu, hv = su / 2, sv / 2
            following += [(u, v, hu, hv), (u + hu, v, hu, hv), (u, v + hv, hu, hv), (u + hu, v + hv, hu, hv)]
        level, depth = following, depth + 1

def _cos_range(a: float, b: float) -> tuple[float, float]:
    """The least and the greatest cosine over [a, b] (radians)."""
    values = [math.cos(a), math.cos(b)]
    if math.floor(b / (2 * math.pi)) > math.floor(a / (2 * math.pi)) or a % (2 * math.pi) == 0.0:
        values.append(1.0)
    if math.floor((b - math.pi) / (2 * math.pi)) > math.floor((a - math.pi) / (2 * math.pi)):
        values.append(-1.0)
    return min(values), max(values)


def _speeds(surface):
    """For an analytic surface, a function (v_low, v_high) -> the fastest the surface
    runs along u and along v over that band of v, exact (u and v are square to each
    other on all of them, so a cell's reach is half its diagonal at those speeds);
    None for any other kind, which keeps the grid's own bound."""
    k = surface.GetType()
    if k == GeomAbs_Plane:
        return lambda a, b: (1.0, 1.0)
    if k == GeomAbs_Cylinder:
        r = abs(surface.Cylinder().Radius())
        return lambda a, b: (r, 1.0)
    if k == GeomAbs_Cone:
        cone = surface.Cone()
        r, sin = cone.RefRadius(), math.sin(cone.SemiAngle())
        return lambda a, b: (max(abs(r + a * sin), abs(r + b * sin)), 1.0)
    if k == GeomAbs_Sphere:
        r = abs(surface.Sphere().Radius())

        def sphere(a, b):
            low, high = _cos_range(a, b)
            return r * max(abs(low), abs(high)), r
        return sphere
    if k == GeomAbs_Torus:
        torus = surface.Torus()
        big, small = torus.MajorRadius(), torus.MinorRadius()

        def ring(a, b):
            low, high = _cos_range(a, b)
            return max(abs(big + small * low), abs(big + small * high)), abs(small)
        return ring
    return None
