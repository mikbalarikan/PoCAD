# kaynak: oguz-atolye tools/measure/bridge.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Bridges (GATES D-03b): the widest flat ceiling a printer must span between the
walls that carry it.

A ceiling is a planar downward face within flat_deg of horizontal, off the bed,
joined with the flat faces that share an edge with it. An edge of a ceiling is
carried only by a support that will print under it: at COLUMNS points across
`min_support` past the edge (the narrowest wall that prints, D-06a / D-01a), the
line straight down from just below the edge runs through material without a break
until it reaches the bed or lands on another ceiling that is itself carried (a
supported layer below). A rib, a curtain or a post thinner than `min_support`, and
a wall that stops short of the bed in air, carry nothing.

Every point of the ceiling must lie within half the span of a carried edge, going
within the ceiling: the distance is a geodesic across the ceiling's own area,
never a straight line through air, so an arm attached only at its root is as far
from support as the way round by its root. It is read on a raster of the ceiling
in the plane square to the build direction (a 16-neighbour shortest path, whose
path runs at most STENCIL times the straight line it follows), refined until the
widest span is proven on one side of max_span or the raster reaches its finest.
"""
from __future__ import annotations

import math
import numbers

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from pocad._ocp import IndexedDataMapOfShapeListOfShape, downcast
from pocad.core.shapes import edges, faces, solids, vertices
from pocad.measure.sampling import Inside, edge_points, face_grid, face_samples, kind, outward_normal
from pocad.result import INCONCLUSIVE, Result, inconclusive, measurement

FLAT_DEG = 10.0          # a planar downward face this near horizontal is a ceiling a printer bridges
MIN_SUPPORT_MM = 0.8     # D-06a / D-01a: a support narrower than this does not print, and carries nothing
SUPPORT_MM = 0.01        # a support column starts this far past the edge and this far below it
COLUMNS = 5              # columns across min_support where a support is read
EDGE_MM = 0.02           # a ceiling's edges are sampled at least this finely
BED_MM = 0.01            # a point this close to the part's lowest height is on the bed
STENCIL = 1.0275         # a 16-neighbour raster path runs at most this times the straight line it follows
FINEST = 32              # the raster is refined down to a pitch of spacing / FINEST
SUB = 4                  # a raster move is checked inside the ceiling at every 1/SUB of its length
MAX_PIXELS = 12_000_000  # fine raster points one ceiling may take at one pitch
MOVES = ((1, 0), (0, 1), (1, 1), (1, -1), (2, 1), (1, 2), (2, -1), (1, -2))


def _unit(direction) -> np.ndarray:
    vector = np.array(direction, float)
    size = np.linalg.norm(vector)
    if vector.shape != (3,) or size < 1e-12:
        raise ValueError(f"build_dir must be a 3D direction, not {direction!r}")
    return vector / size


def _lowest(found, direction) -> float:
    """The part's lowest height along the build direction: its vertices, and a coarse
    grid on every curved face, whose lowest point need not be a vertex."""
    heights = [float(np.dot((p.X(), p.Y(), p.Z()), direction))
               for solid in found for p in (BRep_Tool.Pnt_s(v) for v in vertices(solid))]
    for solid in found:
        for face in faces(solid):
            if kind(face) != "plane":
                heights += [float(np.dot(point, direction))
                            for point, _, _ in face_samples(face, 1.0, coarse=True, boundary=True)]
    return min(heights)


def _joined(flat, ancestors) -> list[list]:
    """The flat faces of one solid grouped into ceilings: faces sharing an edge are one."""
    parent = list(range(len(flat)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (face, _) in enumerate(flat):
        for edge in edges(face):
            for other in ancestors.FindFromKey(edge):
                for j, (candidate, _) in enumerate(flat):
                    if j != i and candidate.IsSame(other):
                        parent[root(i)] = root(j)
    groups: dict[int, list] = {}
    for i, item in enumerate(flat):
        groups.setdefault(root(i), []).append(item)
    return list(groups.values())


class _Supports:
    """Where the line down from a point past a ceiling's edge ends: "bed", the index of
    the ceiling it lands on, or None (it starts in air, or ends on anything else)."""

    def __init__(self, found, direction, bed, ceiling_faces):
        self.direction, self.bed, self.ceiling_faces = direction, bed, ceiling_faces
        self.solids = []
        for solid in found:
            intersector = IntCurvesFace_ShapeIntersector()
            intersector.Load(solid, 1e-7)
            self.solids.append((Inside(solid), intersector))

    def _on_bed(self, point) -> bool:
        return float(np.dot(point, self.direction)) - self.bed <= BED_MM

    def column(self, start):
        if self._on_bed(start):
            return "bed"
        for inside, intersector in self.solids:
            if not inside(start):
                continue
            intersector.Perform(gp_Lin(gp_Pnt(*map(float, start)), gp_Dir(*map(float, -self.direction))), 0.0, 1e9)
            if not intersector.IsDone():
                raise RuntimeError("a support column could not be cast")
            hits = [(intersector.WParameter(j), j) for j in range(1, intersector.NbPnt() + 1)
                    if intersector.WParameter(j) > 1e-7]
            if not hits:
                return None
            w, j = min(hits)
            if self._on_bed(start - w * self.direction):
                return "bed"
            face = intersector.Face(j)
            return next((index for candidate, index in self.ceiling_faces if candidate.IsSame(face)), None)
        return None

    def landing(self, point, tangent, normal, min_support: float):
        """What carries the edge at `point`, as a frozenset of "bed" and ceiling
        indices, when every column across min_support on one side of it is carried;
        None when no side is. The side under the ceiling is air, so one side at most."""
        if tangent is None:
            return None
        side = np.cross(tangent, normal)
        size = float(np.linalg.norm(side))
        if size < 1e-9:
            return None
        side /= size
        offsets = np.linspace(2 * SUPPORT_MM, min_support - SUPPORT_MM, COLUMNS)
        for sign in (1.0, -1.0):
            ends = set()
            for offset in offsets:
                end = self.column(point + sign * offset * side - SUPPORT_MM * self.direction)
                if end is None:
                    break
                ends.add(end)
            else:
                return frozenset(ends)
        return None


class _Raster:
    """One ceiling projected onto the plane square to the build direction, as the
    closed polylines of every wire of its faces: a point is on the ceiling where a
    line through it crosses them an odd number of times (a hole's wire inside its
    face's, and an edge two faces share, cancel as they should)."""

    def __init__(self, members, direction, edge_step):
        basis = np.eye(3)[int(np.argmin(np.abs(direction)))]
        self.e1 = np.cross(direction, basis)
        self.e1 /= np.linalg.norm(self.e1)
        self.e2 = np.cross(direction, self.e1)
        self.direction = direction
        segments = []
        for face in members:
            wires = TopExp_Explorer(face, TopAbs_WIRE)
            while wires.More():
                ring = []
                walk = BRepTools_WireExplorer(downcast.Wire(wires.Current()), face)
                while walk.More():
                    edge = walk.Current()
                    points = [p for p, _ in edge_points(edge, edge_step)[0]]
                    ring += points[::-1] if edge.Orientation() == TopAbs_REVERSED else points
                    walk.Next()
                if len(ring) >= 3:
                    flat = self.flat(np.array(ring))
                    segments.append(np.hstack([flat, np.roll(flat, -1, axis=0)]))
                wires.Next()
        self.segments = np.vstack(segments)
        self.plane = _plane(members[0])

    def flat(self, points) -> np.ndarray:
        points = np.atleast_2d(points)
        return np.column_stack([points @ self.e1, points @ self.e2])

    def lift(self, xy) -> np.ndarray:
        """The point of the ceiling's first face over a projected point."""
        origin, normal = self.plane
        guess = xy[0] * self.e1 + xy[1] * self.e2
        height = float(np.dot(origin - guess, normal) / np.dot(self.direction, normal))
        return guess + height * self.direction

    def mask(self, x0: float, y0: float, h: float, nx: int, ny: int) -> np.ndarray:
        """Which points (x0 + i·h, y0 + j·h) lie on the ceiling, by scanline."""
        out = np.zeros((nx, ny), bool)
        ax, ay, bx, by = self.segments.T
        xs = x0 + h * np.arange(nx)
        for j in range(ny):
            y = y0 + j * h
            cross = ((ay <= y) & (y < by)) | ((by <= y) & (y < ay))
            if not cross.any():
                continue
            t = (y - ay[cross]) / (by[cross] - ay[cross])
            at = np.sort(ax[cross] + t * (bx[cross] - ax[cross]))
            count = np.searchsorted(at, xs, side="right")
            out[:, j] = count % 2 == 1
        return out



def _plane(face) -> tuple[np.ndarray, np.ndarray]:
    """A point of a planar face and its outward normal."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    u, v = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
    p = BRepAdaptor_Surface(face).Value(u, v)
    return np.array([p.X(), p.Y(), p.Z()]), outward_normal(face, u, v)


def _geodesic(raster: _Raster, carried: np.ndarray, g: float):
    """The farthest any raster node of the ceiling stands from a carried edge going
    within the ceiling, at pitch g: (distance, projected point, nodes, unreached
    nodes), or None when the raster would take more than MAX_PIXELS. A move between
    neighbouring nodes counts only where every 1/SUB of it lies on the ceiling, and a
    node is seeded from a carried edge sample within 1.5 g only along a line on it."""
    h = g / SUB
    low = np.minimum(raster.segments[:, :2].min(0), raster.segments[:, 2:].min(0)) - g
    high = np.maximum(raster.segments[:, :2].max(0), raster.segments[:, 2:].max(0)) + g
    nx, ny = (int(math.ceil((high[k] - low[k]) / g)) * SUB + 1 for k in (0, 1))
    if nx * ny > MAX_PIXELS:
        return None
    fine = raster.mask(float(low[0]), float(low[1]), h, nx, ny)
    node = fine[::SUB, ::SUB]
    big_x, big_y = node.shape
    ids = np.full(node.shape, -1, int)
    count = int(node.sum())
    ids[node] = np.arange(count)
    rows, cols, weights = [], [], []
    ii, jj = np.nonzero(node)
    for dx, dy in MOVES:
        i2, j2 = ii + dx, jj + dy
        ok = (i2 >= 0) & (i2 < big_x) & (j2 >= 0) & (j2 < big_y)
        a, b, i2, j2 = ii[ok], jj[ok], i2[ok], j2[ok]
        ok = node[i2, j2]
        for k in range(1, SUB):
            ok &= fine[SUB * a + k * dx, SUB * b + k * dy]
        rows.append(ids[a[ok], b[ok]])
        cols.append(ids[i2[ok], j2[ok]])
        weights.append(np.full(int(ok.sum()), g * math.hypot(dx, dy)))
    points = low + g * np.column_stack([ii, jj])
    gap, nearest = cKDTree(carried).query(points, distance_upper_bound=1.5 * g)
    seeded = np.isfinite(gap)
    for fraction in (0.25, 0.5):
        where = points + fraction * (carried[np.minimum(nearest, len(carried) - 1)] - points)
        fi = np.clip(np.rint((where[:, 0] - low[0]) / h).astype(int), 0, nx - 1)
        fj = np.clip(np.rint((where[:, 1] - low[1]) / h).astype(int), 0, ny - 1)
        seeded &= fine[fi, fj]
    rows.append(np.full(int(seeded.sum()), count))
    cols.append(ids[ii[seeded], jj[seeded]])
    weights.append(np.maximum(gap[seeded], 1e-12))
    graph = coo_matrix((np.concatenate(weights), (np.concatenate(rows), np.concatenate(cols))),
                       shape=(count + 1, count + 1)).tocsr()
    dist = dijkstra(graph, directed=False, indices=count)[:count]
    reached = np.isfinite(dist)
    if not reached.any():
        return 0.0, None, count, count
    far = int(np.argmax(np.where(reached, dist, -1.0)))
    return float(dist[far]), points[far], count, int((~reached).sum())


@measurement("flat_ceiling_spans", "mm")
def flat_ceiling_spans(shape, build_dir=(0, 0, 1), *, max_span: float, spacing: float = 0.5,
                       flat_deg: float = FLAT_DEG, min_support: float = MIN_SUPPORT_MM) -> Result:
    """The widest bridge in mm, with where it is, printed along `build_dir`: over
    every flat ceiling, twice the farthest any point of it stands from a carried edge,
    going within the ceiling. `max_span` (the spec's limit, no default) is where the
    raster is refined to decide: from a pitch of spacing / 2 down to spacing / FINEST,
    until twice the farthest distance less two pitches, over STENCIL, is above it (a
    proven fail), or twice the farthest plus a pitch is at or below it with every node
    reached (a proven pass). The result is twice the farthest distance on the raster;
    detail gives each ceiling's bounds.

    An edge is carried as the module says: every one of COLUMNS lines down, across
    `min_support` past the edge, runs through material to the bed or onto a carried
    ceiling (found by fixed point, from the bed up). A gap in a ceiling narrower than
    a quarter of the raster pitch can be crossed, and is reported as the pitch.

    A part with no flat ceiling off the bed reads 0 with no `at`. INCONCLUSIVE when
    there is no solid, when a ceiling has no carried edge or a part of it no way to
    one at the finest pitch (an overhang, D-03a), when the span stays undecided at the
    finest pitch (one at the limit), or when a face is too large for the spacing.
    Curved downward faces are the overhang census's."""
    direction = _unit(build_dir)
    for value, what in ((max_span, "max_span"), (spacing, "spacing"), (min_support, "min_support")):
        if not (isinstance(value, numbers.Real) and math.isfinite(value) and value > 0):
            raise ValueError(f"{what} must be a length in mm > 0, not {value!r}")
    if not 0.0 < float(flat_deg) < 45.0:
        raise ValueError(f"flat_deg is an angle in (0, 45), not {flat_deg!r}")
    edge_step = min(spacing / 4.0, EDGE_MM)
    params = {"build_dir": tuple(float(x) for x in direction), "max_span": float(max_span), "spacing_mm": spacing,
              "flat_deg": float(flat_deg), "min_support_mm": float(min_support), "bed_mm": BED_MM}
    found = solids(shape)
    if not found:
        return inconclusive("flat_ceiling_spans", "mm", "no solid to scan", **params)
    bed = _lowest(found, direction)
    cos_flat = math.cos(math.radians(flat_deg))
    regions, ceiling_faces, on_bed = [], [], 0
    for solid in found:
        ancestors = IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(solid, TopAbs_EDGE, TopAbs_FACE, ancestors)
        flat = []
        for face in faces(solid):
            if kind(face) != "plane":
                continue
            _, normal = _plane(face)
            if normal is None or -float(np.dot(normal, direction)) < cos_flat:
                continue
            face_grid(face, spacing)                       # a face too large for the spacing stops here
            rim = [p for edge in edges(face) for p, _ in edge_points(edge, edge_step)[0]]
            if max(float(np.dot(p, direction)) for p in rim) - bed <= BED_MM:
                on_bed += 1
                continue
            flat.append((face, normal))
        for group in _joined(flat, ancestors):
            ceiling_faces += [(face, len(regions)) for face, _ in group]
            regions.append({"members": group, "ancestors": ancestors})
    if not regions:
        return Result("flat_ceiling_spans", 0.0, "mm", params=params,
                      detail={"ceilings": [], "bed_faces": on_bed, "sampling_bound_mm": 0.0})
    supports = _Supports(found, direction, bed, ceiling_faces)
    for index, region in enumerate(regions):
        region["rim"] = _rim(region, supports, edge_step, min_support)
    anchored, grew = set(), True
    while grew:                                           # from the bed up: a ceiling carried by a carried one
        grew = False
        for index, region in enumerate(regions):
            if index not in anchored and any(_holds(land, anchored, index) for _, land in region["rim"]):
                anchored.add(index)
                grew = True
    ceilings = [_span(region, index, anchored, direction, edge_step, spacing, max_span)
                for index, region in enumerate(regions)]
    return _verdict(ceilings, on_bed, edge_step, max_span, params)


def _holds(land, anchored: set, index: int) -> bool:
    return land is not None and all(end == "bed" or (end in anchored and end != index) for end in land)


def _rim(region, supports: _Supports, edge_step: float, min_support: float) -> list:
    """(point, landing) for every sample of the ceiling's boundary edges; an edge
    shared by two of its faces is inside it and left out. Three samples of an edge
    are read first; when they agree, the edge is taken as one."""
    members = [face for face, _ in region["members"]]
    out = []
    for face, normal in region["members"]:
        for edge in edges(face):
            others = [o for o in region["ancestors"].FindFromKey(edge) if not o.IsSame(face)]
            if others and all(any(o.IsSame(m) for m in members) for o in others):
                continue
            samples, _ = edge_points(edge, edge_step)
            if not samples:
                continue
            picks = {len(samples) // 4, len(samples) // 2, (3 * len(samples)) // 4}
            first = {supports.landing(*samples[k], normal, min_support) for k in picks}
            if len(first) == 1:
                land = first.pop()
                out += [(p, land) for p, _ in samples]
            else:
                out += [(p, supports.landing(p, t, normal, min_support)) for p, t in samples]
    return out


def _span(region, index: int, anchored: set, direction, edge_step: float, spacing: float, max_span: float) -> dict:
    """One ceiling: its state ("fail", "pass", "undecided", "unreached" or
    "unsupported"), its span on the raster, the bounds of the true span, and where."""
    members = [face for face, _ in region["members"]]
    carried = [p for p, land in region["rim"] if _holds(land, anchored, index)]
    summary = {"faces": len(members), "carried_edge_samples": len(carried), "edge_samples": len(region["rim"])}
    if not carried:
        at = tuple(round(float(x), 6) for x in region["rim"][0][0]) if region["rim"] else None
        return {"state": "unsupported", "span": None, "at": at, "summary": {**summary, "at": at}}
    raster = _Raster(members, direction, edge_step)
    flat_carried = raster.flat(np.array(carried))
    g, read = spacing / 2.0, None
    while True:
        found = _geodesic(raster, flat_carried, g)
        if found is None:
            state = "undecided"
            break
        read = (g, *found)
        far, _, _, unreached = found
        lower, upper = 2.0 * max(0.0, (far - 2.0 * g) / STENCIL), 2.0 * (far + g)
        if lower > max_span:
            state = "fail"
            break
        if upper <= max_span and not unreached:
            state = "pass"
            break
        if g / 2.0 < spacing / FINEST:
            state = "unreached" if unreached else "undecided"
            break
        g /= 2.0
    if read is None:
        return {"state": "undecided", "span": None, "at": None, "lower": 0.0, "upper": math.inf,
                "summary": {**summary, "reason": "the raster is too large"}}
    g, far, xy, nodes, unreached = read
    at = None if xy is None else tuple(round(float(x), 6) for x in raster.lift(xy))
    lower, upper = 2.0 * max(0.0, (far - 2.0 * g) / STENCIL), 2.0 * (far + g)
    return {"state": state, "span": 2.0 * far, "lower": lower, "upper": upper, "at": at,
            "summary": {**summary, "span_mm": round(2.0 * far, 6), "at_least_mm": round(lower, 6),
                        "at_most_mm": round(upper, 6), "pitch_mm": g, "nodes": nodes, "unreached_nodes": unreached,
                        "at": at, "state": state}}


def _verdict(ceilings: list, on_bed: int, edge_step: float, max_span: float, params: dict) -> Result:
    detail = {"ceilings": [c["summary"] for c in ceilings], "bed_faces": on_bed, "edge_step_mm": edge_step}
    fails = [c for c in ceilings if c["state"] == "fail"]
    if fails:
        worst = max(fails, key=lambda c: c["span"])
        return Result("flat_ceiling_spans", worst["span"], "mm", at=worst["at"], params=params,
                      detail={**detail, "sampling_bound_mm": worst["upper"] - worst["span"]})
    loose = [c for c in ceilings if c["state"] in ("unsupported", "unreached")]
    if loose:
        return Result("flat_ceiling_spans", None, "mm", at=loose[0]["at"], params=params, status=INCONCLUSIVE,
                      reason=f"{len(loose)} flat ceilings, or parts of them, have no way to a carried edge: "
                             "no bridge, an overhang (D-03a)", detail=detail)
    worst = max(ceilings, key=lambda c: c["upper"])
    detail["sampling_bound_mm"] = worst["upper"] - (worst["span"] or 0.0)
    if any(c["state"] == "undecided" for c in ceilings):
        return Result("flat_ceiling_spans", None, "mm", at=worst["at"], params=params, status=INCONCLUSIVE,
                      reason=f"the widest span found, {worst['span'] or 0.0:.4f} mm, could be up to "
                             f"{worst['upper']:.4f} mm within its sampling bound, over max_span; "
                             "a finer spacing settles it",
                      detail={**detail, "span_found_mm": worst["span"]})
    widest = max(ceilings, key=lambda c: c["span"])
    return Result("flat_ceiling_spans", widest["span"], "mm", at=widest["at"], params=params, detail=detail)
