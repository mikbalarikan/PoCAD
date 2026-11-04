# kaynak: oguz-atolye tools/core/mesh.py @ca27b1b (MIT, PoCAD'e taşındı)
"""The STL writer for printed parts (DELIVERY.md §4, PLAYBOOK §3 D5).

OCCT keeps a triangulation on the shape, and a later export silently reuses it:
R04 measured 756 triangles at every angular tolerance on a re-used shape. So the
cached triangulation is cleared first (BRepTools.Clean_s), and the mesh is made
with an absolute chordal tolerance in millimetres. build123d's export_stl meshes
with a relative one (isRelative=True), whose size depends on the edges.

The manifest needs the tolerance, the angular tolerance, the triangle count, and
the max sagitta. The sagitta is measured, not assumed, because the mesher does not
always keep to the tolerance it is given: the distance from sample points of every
triangle on a curved face to that face's surface.
"""
from __future__ import annotations

from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Plane
from OCP.gp import gp_Pnt, gp_Pnt2d
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.StlAPI import StlAPI_Writer
from OCP.TopLoc import TopLoc_Location

from pocad.core.shapes import faces, occ, quiet
from pocad.core.step import ExportError, Written, file_sha256
from pocad.result import INCONCLUSIVE, Result, inconclusive, measurement

# Barycentric sample points of a triangle: its centroid and a grid of step 1/4 (edge
# points, edge midpoints, and three interior points), vertices left out. On a lofted
# B-spline face this finds 0.503 mm where the centroid and edge midpoints alone found
# 0.476 mm and a 16 x 16 grid 0.515 mm: a close lower bound of the maximum, within
# 2.2 % of a dense grid on every shape the reviews tried.
WEIGHTS = [(1 / 3, 1 / 3, 1 / 3)] + [(i / 4, j / 4, (4 - i - j) / 4) for i in range(5)
                                     for j in range(5 - i) if max(i, j, 4 - i - j) < 4]


def write_stl(shape, path: Path | str, *, tolerance: float, angular_tolerance: float) -> Written:
    """Mesh `shape` afresh and write a binary STL.

    IN   tolerance: chordal deviation in mm (absolute); angular_tolerance in radians.
    OUT  Written; detail holds tolerance_mm, angular_tolerance_rad, triangles, and
         max_sagitta_mm (None when it could not be measured); checks["max_sagitta"]
         is the measured Result to gate against the spec's tolerance.
    ERR  ValueError on a bad tolerance; ExportError when meshing or writing fails, or
         a face ends up without triangles.
    """
    if not (tolerance > 0 and angular_tolerance > 0):
        raise ValueError("tolerance and angular_tolerance must be positive")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shape_occ = occ(shape)
    BRepTools.Clean_s(shape_occ)
    mesher = BRepMesh_IncrementalMesh(shape_occ, tolerance, False, angular_tolerance, True)
    if not mesher.IsDone():
        raise ExportError("meshing failed")
    sagitta = mesh_sagitta(shape)
    if sagitta.detail.get("faces_without_triangles"):
        raise ExportError(f"{sagitta.detail['faces_without_triangles']} face(s) have no triangles")
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    with quiet():
        written = writer.Write(shape_occ, str(path))
    if not written:
        raise ExportError(f"STL write failed: {path.name}")
    return Written(path, file_sha256(path), "STL", path.stat().st_size,
                   detail={"tolerance_mm": tolerance, "angular_tolerance_rad": angular_tolerance,
                           "triangles": sagitta.detail.get("triangles"),
                           "max_sagitta_mm": sagitta.measured},
                   checks={"max_sagitta": sagitta})


@measurement("stl_max_sagitta", "mm")
def mesh_sagitta(shape) -> Result:
    """The largest distance, in mm, from the triangulation the shape carries now to
    the faces it approximates, over WEIGHTS sample points on every triangle of every
    curved face: each point is projected onto the face's surface
    (ShapeAnalysis_Surface, which starts a search from the triangle's own surface
    parameters). Planar faces have none. A face without triangles, or a point that
    cannot be projected, makes the result INCONCLUSIVE."""
    triangles = samples = bare = missed = 0
    worst, at = 0.0, None
    for face in faces(shape):
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is None:
            bare += 1
            continue
        triangles += mesh.NbTriangles()
        if BRepAdaptor_Surface(face).GetType() == GeomAbs_Plane:
            continue                                        # a flat face has no sagitta
        if not mesh.HasUVNodes():
            return inconclusive("stl_max_sagitta", "mm", "a triangulation without surface parameters")
        distance, point, count, lost = _face_sagitta(face, mesh, location)
        samples += count
        missed += lost
        if distance > worst:
            worst, at = distance, point
    detail = {"triangles": triangles, "samples": samples, "faces_without_triangles": bare,
              "unprojected_samples": missed}
    if bare or missed:
        reason = (f"{bare} face(s) have no triangles" if bare else
                  f"{missed} sample point(s) could not be projected onto their face")
        return Result("stl_max_sagitta", None, "mm", status=INCONCLUSIVE, reason=reason, detail=detail)
    return Result("stl_max_sagitta", worst, "mm", at=at,
                  params={"samples_per_triangle": len(WEIGHTS)}, detail=detail)


def _face_sagitta(face, mesh, location) -> tuple[float, tuple | None, int, int]:
    transform = location.Transformation()
    xyz, uv = [], []
    for i in range(1, mesh.NbNodes() + 1):
        node, param = mesh.Node(i).Transformed(transform), mesh.UVNode(i)
        xyz.append((node.X(), node.Y(), node.Z()))
        uv.append((param.X(), param.Y()))
    surface = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))   # the face's location applied
    worst, at, count, lost = 0.0, None, 0, 0
    for t in range(1, mesh.NbTriangles() + 1):
        i, j, k = (n - 1 for n in mesh.Triangle(t).Get())
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = xyz[i], xyz[j], xyz[k]
        (au, av), (bu, bv), (cu, cv) = uv[i], uv[j], uv[k]
        for wa, wb, wc in WEIGHTS:
            point = gp_Pnt(wa * ax + wb * bx + wc * cx, wa * ay + wb * by + wc * cy,
                           wa * az + wb * bz + wc * cz)
            surface.NextValueOfUV(gp_Pnt2d(wa * au + wb * bu + wc * cu, wa * av + wb * bv + wc * cv),
                                  point, 1e-9, -1.0)
            count += 1
            gap = surface.Gap()
            if gap < 0:                                      # -1: the projection failed
                lost += 1
            elif gap > worst:
                worst, at = gap, (point.X(), point.Y(), point.Z())
    return worst, at, count, lost
