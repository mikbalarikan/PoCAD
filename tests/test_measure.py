# kaynak: oguz-atolye tools/tests/test_measure.py @ca27b1b (MIT, PoCAD'e taşındı)
"""pocad.measure: for every function a known-good fixture that must PASS, a known-bad
one that must FAIL (D-010), the measured value against the analytic answer R04
reports, and the INCONCLUSIVE path. The limits below are test limits, not GATES
values: tools read no threshold (D-009)."""
from __future__ import annotations

import math
import re

import numpy as np
import pytest

pytestmark = pytest.mark.cad
pytest.importorskip("build123d")
pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister")
pytest.importorskip("trimesh")

import trimesh
from build123d import (
    Align,
    Axis,
    Box,
    Circle,
    Compound,
    Cone,
    Cylinder,
    Ellipse,
    Plane,
    Pos,
    Rectangle,
    Rot,
    SlotOverall,
    Sphere,
    extrude,
    loft,
)
from fixtures import parts

from pocad import core, measure
from pocad.measure import draft as measure_draft
from pocad.measure import wall as measure_wall
from pocad.measure.sampling import face_grid
from pocad.result import FAIL, INCONCLUSIVE, PASS, gate

BAND = 1e-6
EXACT = 1e-6          # R04: the B-rep measurements are exact to float noise
MIN = (Align.MIN, Align.MIN, Align.MIN)
needs_embree = pytest.mark.skipif(not trimesh.ray.has_embree, reason="embreex has no wheel for this platform")


def status(result, op, limit, band=BAND):
    return gate("T", result, op, limit, band=band).status


def largest_step(shape, spacing: float, which=lambda face: True) -> float:
    """The largest step of the grids a sampled measurement uses on these faces."""
    return round(max(face_grid(f.wrapped, spacing).step_mm for f in shape.faces() if which(f)), 6)


# ------------------------------------------------------------------- walls

@pytest.mark.parametrize("fixture,analytic", [(parts.tray, 3.0), (parts.tube, 3.0)])
def test_min_wall_is_exact_on_the_analytic_fixtures(fixture, analytic):
    result = measure.min_wall(fixture())
    assert result.measured == pytest.approx(analytic, abs=EXACT)
    assert status(result, ">=", 1.2) == PASS
    assert result.at is not None and result.detail["lost_rays"] == 0
    assert result.detail["largest_step_mm"] <= 0.4


@pytest.mark.parametrize("fixture", [lambda: parts.tray(thin=0.8), lambda: parts.block_with_thin_fin(0.8)])
def test_min_wall_catches_the_thin_wall_and_the_thin_fin(fixture):
    result = measure.min_wall(fixture())                   # L-07: v1's erosion passed the fin
    assert result.measured == pytest.approx(0.8, abs=EXACT)
    assert status(result, ">=", 1.2) == FAIL


@pytest.mark.parametrize("angle", [0.0, 90.0, 30.0])
def test_min_wall_finds_the_web_between_two_small_holes(angle):
    """The samples on a Ø1.6 bore fell 12.86° either side of the line of centres,
    so the rays missed the web and read the plate (4.0); every pair of faces a ray
    joined is now measured exactly."""
    result = measure.min_wall(parts.two_holes(1.6, 1.19, angle), spacing=1.0)
    assert result.measured == pytest.approx(1.19, abs=EXACT)
    assert status(result, ">=", 1.2) == FAIL
    assert result.detail["face_pairs_failed"] == result.detail["exact_points_without_normal"] == 0


def test_a_corner_thinner_than_its_walls_shows_at_45_degrees():
    """Under an R5 round over a sharp cavity corner the part is 0.7574 mm thick, less
    than its 2.0 mm walls. The closest points there are 45° from opposed, so the
    gated 25° value does not see it (oguz-atolye U-17); the 45° value beside it does."""
    corner = 5.0 - math.hypot(3.0, 3.0)
    result = measure.min_wall(parts.rounded_box(5.0, 2.0), spacing=1.0)     # the exact pass finds it
    assert result.measured > 1.5
    assert result.detail["wide"]["measured"] == pytest.approx(corner, abs=EXACT)
    rounded = measure.min_wall(parts.rounded_box(5.0, 2.0, inner=1.0), spacing=1.0)   # two rounds face each other
    assert rounded.measured == pytest.approx(5.0 - (math.hypot(2.0, 2.0) + 1.0), abs=EXACT)


def test_a_sliver_thinner_than_the_hit_cutoff_is_measured():
    sliver = Box(20, 10, 10, align=MIN) - Pos(2, 2, 2) * Box(5, 6, 20, align=MIN) \
        - Pos(7 + 5e-5, 2, 2) * Box(5, 6, 20, align=MIN)
    assert measure.min_wall(sliver).measured == pytest.approx(5e-5, abs=1e-9)


@pytest.mark.parametrize("tooth", [2.5, 1.0])
def test_the_air_between_comb_teeth_is_not_a_wall(tooth):
    """The chord across the 0.5 mm gap between two teeth runs through air, against
    both faces' normals: without its checks the exact pass read the gap."""
    assert measure.min_wall(parts.comb(tooth, 0.5), spacing=0.5).measured == pytest.approx(tooth, abs=EXACT)


def test_a_wall_runs_along_both_normals():
    """Between the re-entrant corners of a Z-shaped neck the chord runs through
    material 26.6° off both faces' normals: a wall at 45°, not at 25° (oguz-atolye U-17),
    where it read 1.118 against the 2.0 plate. Where the plates overlap by only
    0.01 mm, the column's own faces meet 0.5001 mm apart along both normals."""
    neck = measure.min_wall(parts.zneck(1.0, 0.5), spacing=0.5)
    assert neck.measured == pytest.approx(2.0, abs=EXACT)
    assert neck.detail["wide"]["measured"] == pytest.approx(math.hypot(0.5, 1.0), abs=EXACT)
    thin = measure.min_wall(parts.zneck(0.01, 0.5), spacing=0.5)
    assert thin.measured == pytest.approx(math.hypot(0.5, 0.01), abs=EXACT)


@pytest.mark.parametrize("spacing", [0.4, 1.0])
def test_a_ray_that_meets_a_cone_apex_is_not_lost(spacing):
    """The bottom face's grid puts a sample on the drill point's axis, and its ray
    meets the apex, where the cone has no normal: min_wall read INCONCLUSIVE. The
    floor under the point is a wall at 45° only (its flanks are 31° off)."""
    result = measure.min_wall(parts.blind_bore("118"), spacing=spacing)
    assert result.measured == pytest.approx(17.0, abs=EXACT) and result.detail["lost_rays"] == 0
    floor = 10.0 - 3.0 / math.tan(math.radians(59.0))
    assert result.detail["wide"]["measured"] == pytest.approx(floor, abs=EXACT)


@pytest.mark.parametrize("stored", ["analytic", "b-splines", "in quarters"])
@pytest.mark.parametrize("turned", [False, True])
def test_the_floor_under_a_drill_point_is_read_at_its_apex(turned, stored):
    """A 140° point 0.5 mm above the bottom, off the sample grid: only the exact pass
    finds the floor, at the apex, where the cone has no normal. Built turned over,
    the apex lies at the other end of the cone's parameters, where the fallback took
    the normal from the other nappe, turned over, and the floor read 0.56 or 0.65.
    As a B-spline the apex reported a wrong normal (0.56, a pass against 0.55); in
    quarters its parameters lay outside the face's (INCONCLUSIVE)."""
    part = parts.blind_bore("140", floor=0.5, at=(19.61, 20.23), turned=turned)
    part = {"analytic": part, "b-splines": parts.nurbs(part), "in quarters": parts.split_closed(part, 4)}[stored]
    for spacing in (1.0,) if stored == "b-splines" else (0.4, 1.0):         # B-splines read 0.65 at 1.0
        assert measure.min_wall(part, spacing=spacing).measured == pytest.approx(0.5, abs=EXACT)


@pytest.mark.parametrize("included,gated", [(20.0, 0.3), (40.0, 10.0)])
def test_a_drafted_fin_is_a_wall_where_its_flanks_are_opposed(included, gated):
    """A fin's flanks meet its 0.3 mm top; their closest points lie on the top's edges.
    20° apart, the flanks are opposed within 25°: the fin is a 0.3 wall. 40° apart
    they are not, though the segment between them runs within 20° of each normal: at
    25° the thinnest wall is the 10 mm block, and at 45° the fin's top."""
    result = measure.min_wall(parts.tapered_fin(included), spacing=0.5)
    assert result.measured == pytest.approx(gated, abs=EXACT)
    assert result.detail["wide"]["measured"] == pytest.approx(0.3, abs=EXACT)


def test_a_segment_across_the_mouth_of_a_gap_is_not_a_wall():
    """Two wedges hang from a 10 mm back wall with 1 mm of air between them. The
    closest points of their bottom and top faces, and of the back wall's bottom, lie
    on their edges, and the segments between them run along faces across the gap's
    mouth: they read 6.0, then 9.0, where the thinnest wall is the back wall."""
    result = measure.min_wall(parts.two_wedges(), spacing=0.5)
    assert result.measured == pytest.approx(10.0, abs=EXACT)


def test_faces_that_can_never_face_each_other_are_not_measured():
    """On a block with 36 shallow dimples, every pair of dimples lay closer than the
    thinnest wall, so all were measured exactly (43,581 pairs, 101 s at 400 dimples):
    two dimples' normals can never be opposed."""
    result = measure.min_wall(parts.dimpled(6), spacing=1.0)
    assert result.measured == pytest.approx(49.5, abs=EXACT)
    assert result.detail["face_pairs_never_opposed"] > 300 and result.detail["face_pairs_measured_exactly"] < 100


def test_a_web_found_only_face_to_face_is_found_beside_a_thinner_corner():
    """The exact pass looks at pairs closer than the thickest of the gated and wide
    walls found so far: a 1.19 web the rays miss, in a box whose rounded corner is
    0.757 at 45°. Looking only closer than the thinnest (the corner) lost the web."""
    result = measure.min_wall(parts.rounded_box(5.0, 2.0, web=1.19), spacing=1.0)
    assert result.measured == pytest.approx(1.19, abs=EXACT) and result.detail["found_by"] == "exact"
    assert result.detail["wide"]["measured"] == pytest.approx(5.0 - math.hypot(3.0, 3.0), abs=EXACT)


def test_a_pair_that_cannot_be_measured_makes_min_wall_inconclusive(monkeypatch):
    """With a face pair left unmeasured, the web the rays miss was lost and the plate
    read 1.21, a pass against 1.2."""
    real = measure_wall.BRepExtrema_DistShapeShape

    class Failing:
        def __init__(self, a, b):
            self.inner = real(a, b)

        def IsDone(self):
            return False

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(measure_wall, "BRepExtrema_DistShapeShape", Failing)
    result = measure.min_wall(parts.two_holes(1.6, 1.19, 30.0), spacing=1.0)
    assert result.status == INCONCLUSIVE and "could not be measured" in result.reason


def test_min_wall_wide_is_the_45_degree_reading_as_its_own_result():
    """GATES U-06: under an R5 round over a sharp cavity corner the box is 0.7574 mm
    thick at 45°, less than its 2.0 walls; with the cavity's corners rounded
    concentric (R3) it is 2.0 all round."""
    bad = measure.min_wall_wide(parts.rounded_box(5.0, 2.0), spacing=1.0)
    assert bad.measured == pytest.approx(5.0 - math.hypot(3.0, 3.0), abs=EXACT) and status(bad, ">=", 1.5) == FAIL
    assert bad.at is not None and bad.params["opposition_deg"] == 45.0 and bad.detail["gated_mm"] > 1.5
    good = measure.min_wall_wide(parts.rounded_box(5.0, 2.0, inner=3.0), spacing=1.0)
    assert good.measured == pytest.approx(2.0, abs=EXACT) and status(good, ">=", 1.5) == PASS
    same = measure.min_wall(parts.rounded_box(5.0, 2.0), spacing=1.0).detail["wide"]
    assert (bad.measured, bad.at) == (same["measured"], same["at"])


def test_min_wall_wide_is_inconclusive_when_min_wall_is(monkeypatch):
    real = measure_wall.BRepExtrema_DistShapeShape

    class Failing:
        def __init__(self, a, b):
            self.inner = real(a, b)

        def IsDone(self):
            return False

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(measure_wall, "BRepExtrema_DistShapeShape", Failing)
    result = measure.min_wall_wide(parts.two_holes(1.6, 1.19, 30.0), spacing=1.0)
    assert result.status == INCONCLUSIVE and result.reason.startswith("min_wall is INCONCLUSIVE")
    assert measure.min_wall_wide(parts.open_box()).status == INCONCLUSIVE


def test_faces_sewn_a_few_tenths_of_a_micron_apart_are_measured():
    """A STEP from another system often sews its faces with edge tolerances of a few
    1e-4 mm: the closest points on those edges lie that far off the surfaces, and a
    normal refused beyond 1e-4 mm made the tray INCONCLUSIVE."""
    result = measure.min_wall(parts.sewn_loose(parts.tray(thin=0.8), 2e-4), spacing=1.0)
    assert result.status == "MEASURED" and result.measured == pytest.approx(0.8, abs=1e-3)


def test_a_face_too_large_for_its_spacing_is_inconclusive_not_coarser():
    plate = Box(250, 250, 4, align=MIN)
    fine = measure.min_wall(plate)
    assert fine.status == INCONCLUSIVE and "a spacing of" in fine.reason
    coarse = measure.min_wall(plate, spacing=3.0)
    assert coarse.measured == pytest.approx(4.0, abs=EXACT) and coarse.detail["largest_step_mm"] <= 3.0
    assert measure.undercuts(Box(300, 300, 10), (0, 0, 1), spacing=0.5).status == INCONCLUSIVE


def test_the_spacing_a_refusal_names_fits():
    """The hint rounded down and counted cells the grid does not have: at 0.5 mm it
    named 0.5 mm, again and again. The grid at the named spacing fits."""
    from pocad.measure.sampling import MAX_SAMPLES_PER_FACE
    plate = Box(250, 250, 4, align=MIN)
    top = max(plate.faces(), key=lambda f: f.area).wrapped
    for spacing in (0.4, 0.5):
        refused = measure.min_wall(plate, spacing=spacing)
        hint = float(re.search(r"a spacing of ([0-9.]+) mm fits", refused.reason).group(1))
        grid = face_grid(top, hint)                   # it raises Undersampled where the hint does not fit
        assert hint > spacing and grid.nu * grid.nv <= MAX_SAMPLES_PER_FACE


@pytest.mark.parametrize("profile", ["bulge", "wave", "ripple", "knurl"])
def test_a_face_that_bulges_between_iso_lines_keeps_its_step(profile):
    """A spline profile that swells from R5 to R20 near its base runs fastest there,
    and fastest of all at its edge: sized from three iso lines, the grid stepped
    0.69 mm at a 0.4 mm spacing while it reported 0.398. A wavy one runs fastest
    between the grid nodes where its speed is taken: without the 1 % added, it
    stepped 0.4004. Ripples finer than 33 nodes (64 waves of 0.3 mm, 16 of 1 mm)
    stepped 0.44 and 0.46: a B-spline gets nodes on every piece."""
    face = next(f for f in parts.revolved(profile).faces() if f.geom_type.name != "PLANE").wrapped
    grid = face_grid(face, 0.4)
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    surface = BRepAdaptor_Surface(face)
    us = u0 + (u1 - u0) * (np.arange(grid.nu) + 0.5) / grid.nu
    vs = v0 + (v1 - v0) * (np.arange(grid.nv) + 0.5) / grid.nv
    points = np.array([[(lambda p: (p.X(), p.Y(), p.Z()))(surface.Value(float(u), float(v))) for v in vs]
                       for u in us])
    largest = max(np.linalg.norm(np.diff(points, axis=0), axis=2).max(),
                  np.linalg.norm(np.diff(points, axis=1), axis=2).max())
    assert largest <= grid.step_mm <= 0.4


def test_a_grid_keeps_its_largest_step_within_the_spacing():
    """A cylinder converted to a rational B-spline runs faster in places than on
    average: sized from its mean speed, the grid stepped 0.44 mm at a 0.4 mm spacing
    and reported 0.397."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools

    from pocad.measure.sampling import face_grid
    face = max(parts.nurbs(parts.tube()).faces(), key=lambda f: f.area).wrapped
    grid = face_grid(face, 0.4)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    surface = BRepAdaptor_Surface(face)
    points = np.array([[[c for c in (lambda p: (p.X(), p.Y(), p.Z()))(surface.Value(u, v))]
                        for v in np.linspace(v0, v1, grid.nv, endpoint=False) + (v1 - v0) / (2 * grid.nv)]
                       for u in np.linspace(u0, u1, grid.nu, endpoint=False) + (u1 - u0) / (2 * grid.nu)])
    largest = max(np.linalg.norm(np.diff(points, axis=0), axis=2).max(),
                  np.linalg.norm(np.diff(points, axis=1), axis=2).max())
    assert largest <= grid.step_mm <= 0.4


@pytest.mark.parametrize("fault", ["raises", "finds no exit"])
def test_a_lost_ray_makes_min_wall_inconclusive_with_what_it_found(monkeypatch, fault):
    real = measure_wall.IntCurvesFace_ShapeIntersector

    class Flaky:
        """An intersector that loses one ray start in 50, tilted or not: it raises, or
        finds nothing."""

        def __init__(self):
            self.inner, self.empty = real(), False

        def Perform(self, line, low, high):
            start = line.Location()
            lost = hash((round(start.X(), 6), round(start.Y(), 6), round(start.Z(), 6))) % 50 == 0
            self.empty = lost and fault == "finds no exit"
            if lost and fault == "raises":
                raise RuntimeError("lost")
            self.inner.Perform(line, low, high)

        def NbPnt(self):
            return 0 if self.empty else self.inner.NbPnt()

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(measure_wall, "IntCurvesFace_ShapeIntersector", Flaky)
    monkeypatch.setattr(measure_wall, "_exit_again", lambda solid, start, direction: None)
    result = measure.min_wall(parts.tray(thin=0.8), spacing=1.0)
    assert result.status == INCONCLUSIVE and result.detail["lost_rays"] > 0
    assert result.detail["thinnest_found_mm"] == pytest.approx(0.8, abs=EXACT)


def test_a_ray_that_meets_a_face_almost_tangentially_is_not_lost():
    """Two rays from the top of a thin loft meet its steep outer face 2° off tangent,
    and IntCurvesFace found no exit for them: min_wall read INCONCLUSIVE at 0.3 and
    0.4 mm. They are cast again with BRepIntCurveSurface_Inter."""
    result = measure.min_wall(parts.loft_wall(), spacing=0.4)
    assert result.status == "MEASURED" and result.detail["lost_rays"] == 0
    assert result.measured == pytest.approx(0.805, abs=1e-3)          # as at 0.5 mm, where no ray was lost


def test_min_wall_without_a_solid_is_inconclusive():
    for shape in (parts.open_box(), None):
        result = measure.min_wall(shape)
        assert result.status == INCONCLUSIVE and status(result, ">=", 0.0) == INCONCLUSIVE


# -------------------------------------------------------------- mesh checks

@needs_embree
def test_min_wall_mesh_corroborates_within_the_chordal_tolerance(tmp_path):
    written = core.write_stl(parts.tube(), tmp_path / "tube.stl", tolerance=0.01, angular_tolerance=0.1)
    mesh = measure.min_wall_mesh(written.path)
    brep = measure.min_wall(parts.tube())
    assert brep.measured - written.detail["max_sagitta_mm"] - EXACT <= mesh.measured <= brep.measured + EXACT
    thin = core.write_stl(parts.tray(thin=0.8), tmp_path / "thin.stl", tolerance=0.01, angular_tolerance=0.1)
    assert status(measure.min_wall_mesh(thin.path), ">=", 1.2) == FAIL


@needs_embree
def test_min_wall_mesh_refuses_an_inside_out_mesh(tmp_path):
    written = core.write_stl(parts.tray(), tmp_path / "tray.stl", tolerance=0.01, angular_tolerance=0.1)
    mesh = trimesh.load(str(written.path), force="mesh")
    trimesh.Trimesh(mesh.vertices, mesh.faces[:, ::-1], process=False).export(str(tmp_path / "inverted.stl"))
    result = measure.min_wall_mesh(tmp_path / "inverted.stl")          # it read 24.0, the cavity
    assert result.status == INCONCLUSIVE and "inside out" in result.reason


@needs_embree
def test_min_wall_mesh_keeps_to_its_ray_cap(tmp_path):
    written = core.write_stl(parts.tube(), tmp_path / "tube.stl", tolerance=0.01, angular_tolerance=0.1)
    result = measure.min_wall_mesh(written.path, max_rays=400)
    assert result.detail["rays"] == 400
    assert result.measured == pytest.approx(3.0, abs=0.01)


@needs_embree
@pytest.mark.parametrize("wall", [0.6, 0.81])
def test_min_wall_mesh_skips_a_rays_own_triangle_on_a_large_part(tmp_path, wall):
    """Embree works in single precision: on a 600 mm box a ray that starts 1e-5 mm
    inside a face met its own triangle first, and 51 of 60 thin walls, these two
    among them, read 1.5. The STL's single-precision coordinates move the wall by
    less than vertex_precision_mm."""
    written = core.write_stl(parts.large_box(wall), tmp_path / "large.stl", tolerance=0.01, angular_tolerance=0.1)
    result = measure.min_wall_mesh(written.path)
    assert result.detail["rays_without_exit"] == 0
    assert result.measured == pytest.approx(wall, abs=result.detail["vertex_precision_mm"])
    assert result.detail["vertex_precision_mm"] < 1e-4


@needs_embree
def test_a_mesh_ray_without_an_exit_makes_the_result_inconclusive(tmp_path, monkeypatch):
    real = trimesh.ray.ray_pyembree.RayMeshIntersector.intersects_id

    def lossy(self, origins, directions, **options):
        """Every 50th ray finds nothing."""
        tri, ray, where = real(self, origins, directions, **options)
        keep = ray % 50 != 0
        return tri[keep], ray[keep], where[keep]

    monkeypatch.setattr(trimesh.ray.ray_pyembree.RayMeshIntersector, "intersects_id", lossy)
    written = core.write_stl(parts.tray(thin=0.8), tmp_path / "thin.stl", tolerance=0.01, angular_tolerance=0.1)
    result = measure.min_wall_mesh(written.path)
    assert result.status == INCONCLUSIVE and result.detail["rays_without_exit"] > 0
    assert result.detail["thinnest_found_mm"] == pytest.approx(0.8, abs=1e-4)


def test_min_wall_mesh_without_embree_is_inconclusive(tmp_path, monkeypatch):
    """embreex has no wheel for ARM Linux, and trimesh's own engine ran out of memory
    on a real STL: without Embree the mesh wall check says so."""
    written = core.write_stl(parts.tube(), tmp_path / "tube.stl", tolerance=0.01, angular_tolerance=0.1)
    monkeypatch.setattr(trimesh.ray, "has_embree", False)
    result = measure.min_wall_mesh(written.path)
    assert result.status == INCONCLUSIVE and "Embree" in result.reason


def test_min_wall_mesh_of_no_mesh_is_inconclusive(tmp_path):
    empty = tmp_path / "empty.stl"
    empty.write_bytes(b"")
    assert measure.min_wall_mesh(empty).status == INCONCLUSIVE


def one_closed_shell(census) -> str:
    """The V-05 gate on a census: one body, closed, wound consistently, facing out."""
    checks = [status(census["bodies"], "==", 1, 0), status(census["naked_edges"], "==", 0, 0),
              status(census["winding"], "==", 1, 0), status(census["volume"], ">=", 1e-9, 0)]
    return next((s for s in (FAIL, INCONCLUSIVE) if s in checks), PASS)


def test_mesh_census_of_a_closed_mesh(tmp_path):
    written = core.write_stl(parts.bracket(), tmp_path / "bracket.stl", tolerance=0.01, angular_tolerance=0.1)
    census = measure.mesh_census(written.path)
    assert one_closed_shell(census) == PASS
    assert census["triangles"].measured == written.detail["triangles"]
    assert census["volume"].measured == pytest.approx(parts.bracket_volume(), rel=1e-3)


@pytest.mark.parametrize("shape", [lambda: Sphere(10), lambda: Cone(10, 0, 20), lambda: parts.pocket(2.0, floor=True)])
def test_mesh_census_reads_poles_and_apexes_as_one_closed_shell(tmp_path, shape):
    """OCCT's STL carries zero-area triangles at a sphere's poles and a cone's apex;
    counted, they split the shell into bodies with open edges."""
    written = core.write_stl(shape(), tmp_path / "part.stl", tolerance=0.01, angular_tolerance=0.1)
    census = measure.mesh_census(written.path)
    assert census["triangles"].detail["degenerate_triangles"] >= 1
    assert one_closed_shell(census) == PASS


def test_a_zero_area_triangle_that_closes_a_t_junction_stays(tmp_path):
    """A unit cube whose top carries a vertex on the midpoint of an edge, closed by a
    triangle of three distinct collinear vertices: dropped for its zero area, it left
    three open edges and failed a sound mesh."""
    vertices = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
                         [0.5, 0, 1]], float)
    triangles = np.array([[0, 2, 1], [0, 3, 2], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6],
                          [3, 0, 4], [3, 4, 7], [4, 8, 7], [8, 6, 7], [8, 5, 6], [4, 5, 8]])
    trimesh.Trimesh(vertices, triangles, process=False).export(str(tmp_path / "t.stl"))
    census = measure.mesh_census(tmp_path / "t.stl")
    assert one_closed_shell(census) == PASS and census["volume"].measured == pytest.approx(1.0, abs=1e-6)
    assert census["triangles"].detail["degenerate_triangles"] == 0
    if trimesh.ray.has_embree:                    # its zero normal made four rays without a direction
        assert measure.min_wall_mesh(tmp_path / "t.stl").measured == pytest.approx(1.0, abs=1e-6)


def test_mesh_census_finds_an_open_mesh_two_bodies_and_an_inside_out_one(tmp_path):
    open_mesh = core.write_stl(parts.open_box(), tmp_path / "open.stl", tolerance=0.01, angular_tolerance=0.1)
    census = measure.mesh_census(open_mesh.path)
    assert status(census["naked_edges"], "==", 0, 0) == FAIL
    assert census["volume"].status == INCONCLUSIVE
    two = core.write_stl(parts.bracket(boss_lift=1.0), tmp_path / "two.stl", tolerance=0.01, angular_tolerance=0.1)
    assert status(measure.mesh_census(two.path)["bodies"], "==", 1, 0) == FAIL
    tray = core.write_stl(parts.tray(), tmp_path / "tray.stl", tolerance=0.01, angular_tolerance=0.1)
    mesh = trimesh.load(str(tray.path), force="mesh")
    trimesh.Trimesh(mesh.vertices, mesh.faces[:, ::-1], process=False).export(str(tmp_path / "inverted.stl"))
    inverted = measure.mesh_census(tmp_path / "inverted.stl")
    assert inverted["volume"].measured < 0 and one_closed_shell(inverted) == FAIL
    assert all(r.status == INCONCLUSIVE for r in measure.mesh_census(tmp_path / "none.stl").values())


def test_mesh_deviation_matches_the_writers_own_sagitta(tmp_path):
    written = core.write_stl(parts.tube(), tmp_path / "tube.stl", tolerance=0.01, angular_tolerance=0.1)
    deviation = measure.mesh_deviation(written.path, parts.tube())
    assert deviation.measured == pytest.approx(written.detail["max_sagitta_mm"], abs=0.001)
    assert status(deviation, "<=", 0.01 + 0.001) == PASS


def test_mesh_deviation_catches_a_coarse_mesh_and_a_mesh_of_another_part(tmp_path):
    coarse = core.write_stl(parts.tube(), tmp_path / "coarse.stl", tolerance=0.5, angular_tolerance=0.8)
    assert status(measure.mesh_deviation(coarse.path, parts.tube()), "<=", 0.011) == FAIL
    other = core.write_stl(parts.bracket(thickness=3.0), tmp_path / "other.stl", tolerance=0.01,
                           angular_tolerance=0.1)
    assert status(measure.mesh_deviation(other.path, parts.bracket()), "<=", 0.011) == FAIL


def test_mesh_deviation_sees_geometry_missing_from_the_mesh(tmp_path):
    """Every point of a mesh missing a face lies on the part, so only the distance
    from the part to the mesh finds the hole."""
    holed = core.write_stl(parts.without_top_face(parts.tube()), tmp_path / "holed.stl", tolerance=0.01,
                           angular_tolerance=0.1)
    deviation = measure.mesh_deviation(holed.path, parts.tube())
    assert deviation.detail["mesh_to_shape_mm"] <= 0.011 < deviation.detail["shape_to_mesh_mm"]
    assert status(deviation, "<=", 0.011) == FAIL


def test_mesh_deviation_of_no_mesh_is_inconclusive(tmp_path):
    assert measure.mesh_deviation(tmp_path / "none.stl", parts.tube()).status == INCONCLUSIVE


# ------------------------------------------------------------ bores, census

def test_bore_census_reads_the_holed_plate_exactly():
    census = measure.bore_census(parts.holed_plate())
    assert census.measured == 3
    bores = {round(b["diameter"], 6): b for b in census.detail["bores"]}
    assert set(bores) == {5.0, 3.2, 4.1}
    assert bores[5.0]["start"][:2] == (15.0, 20.0) and bores[5.0]["through"]
    assert bores[3.2]["start"][:2] == (35.0, 20.0) and bores[3.2]["through"]
    assert bores[4.1]["start"] == (48.0, 20.0, 4.0) and not bores[4.1]["through"]
    assert bores[4.1]["length"] == pytest.approx(4.0, abs=EXACT)


def test_a_drill_point_closes_a_blind_bore():
    bores = {round(b["diameter"], 6): b for b in measure.bore_census(parts.holed_plate(drill_point=True)).detail["bores"]}
    assert bores[4.1]["open_ends"] == [False, True] and not bores[4.1]["through"]


@pytest.mark.parametrize("bottom,floor", [("flat", None), ("ball", None), ("118", None), ("60", None),
                                          ("flat", 0.08), ("flat", 0.002)])
def test_every_blind_bottom_closes_its_bore(bottom, floor):
    """A ball end, a 60° point, and a 0.08 mm floor read through when the ends were
    probed half a radius off the axis and 0.05 radii beyond; a 0.002 mm floor did
    when the first probe went 0.01 mm beyond."""
    bore = measure.bore_census(parts.blind_bore(bottom, floor=floor)).detail["bores"][0]
    assert bore["open_ends"] == [False, True] and not bore["through"]


def test_bores_stored_as_b_splines_are_bores():
    """Converted to B-splines, the holed plate kept no cylinder, and its census read
    no bore."""
    census = measure.bore_census(parts.nurbs(parts.holed_plate()))
    bores = {round(b["diameter"], 6): b for b in census.detail["bores"]}
    assert set(bores) == {5.0, 3.2, 4.1} and bores[5.0]["through"] and not bores[4.1]["through"]


@pytest.mark.parametrize("small", [5.5, 9.2, 9.9])
def test_a_counterbore_is_not_through_and_its_hole_is(small):
    """Probed 0.9 radii off the axis, a Ø10 counterbore over a Ø9.2 hole read through:
    the probes fell inside the hole. They go 0.01 mm inside the bore's wall."""
    census = measure.bore_census(parts.counterbored_plate(small=small))
    bores = {round(b["diameter"], 6): b for b in census.detail["bores"]}
    assert bores[small]["through"] and not bores[10.0]["through"]


def test_arcs_split_along_the_axis_are_not_a_bore():
    """A slot whose 180° ends each carry an imprinted edge: the two faces of an end
    cover the same half turn, and summing them made a 360° "bore"."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepFeat import BRepFeat_SplitShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    from pocad._ocp import downcast
    from pocad.core.shapes import faces
    from pocad.measure.sampling import kind
    slot = Box(40, 40, 8, align=MIN) - Pos(20, 20, -1) * extrude(SlotOverall(20, 6), 10)
    splitter = BRepFeat_SplitShape(slot.wrapped)
    for face in faces(slot):
        if kind(face) == "cylinder":
            section = BRepAlgoAPI_Section(face, gp_Pln(gp_Pnt(0, 0, 4), gp_Dir(0, 0, 1)))
            section.Build()
            edges = TopExp_Explorer(section.Shape(), TopAbs_EDGE)
            while edges.More():
                splitter.Add(downcast.Edge(edges.Current()), face)
                edges.Next()
    splitter.Build()
    split = Compound(splitter.Shape())
    census = measure.bore_census(split)
    assert census.measured == 0 and census.detail["concave_arcs"] == 2
    assert measure.min_internal_radius(split).measured == pytest.approx(3.0, abs=EXACT)


def test_fillets_with_the_bore_radius_are_not_bores():
    census = measure.bore_census(parts.fillet_collision())        # R02 §5.2: five radius-3 cylinders
    assert census.measured == 1 and census.detail["bores"][0]["diameter"] == pytest.approx(6.0, abs=EXACT)


def test_the_missing_bore_fails_the_census():
    census = measure.bore_census(parts.fillet_collision(bore=False))   # R02 F1
    assert status(census, "==", 1, 0) == FAIL
    assert status(measure.feature_census(parts.fillet_collision(bore=False))["bores"], "==", 1, 0) == FAIL
    assert measure.bore_census(None).status == INCONCLUSIVE


def test_locate_bore_gives_a_located_diameter_and_catches_a_moved_bore():
    located = measure.locate_bore(measure.bore_census(parts.holed_plate()), (15, 20, 0), (0, 0, 1))
    assert status(located["diameter"], "==", 5.0) == PASS
    assert status(located["offset"], "<=", 0.1) == PASS
    assert located["through"].measured == 1 and located["length"].measured == pytest.approx(8.0, abs=EXACT)
    moved = measure.locate_bore(measure.bore_census(parts.holed_plate(shift=0.5)), (15, 20, 0), (0, 0, 1))
    assert moved["offset"].measured == pytest.approx(0.5, abs=EXACT)
    assert status(moved["offset"], "<=", 0.1) == FAIL
    none = measure.locate_bore(measure.bore_census(parts.fillet_collision(bore=False)), (0, 0, 0))
    assert none["diameter"].status == INCONCLUSIVE


def test_locate_bore_sees_a_blind_bore_drilled_from_the_wrong_face():
    """The offset is to the bore's axis segment, not to its endless axis."""
    plate = Box(60, 40, 8, align=MIN) - Pos(48, 20, -1) * Cylinder(2.05, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    located = measure.locate_bore(measure.bore_census(plate), (48, 20, 8), (0, 0, 1))   # expected from the top
    assert located["offset"].measured == pytest.approx(4.0, abs=EXACT)
    assert status(located["offset"], "<=", 0.1) == FAIL
    assert located["through"].measured == 0 and located["length"].measured == pytest.approx(4.0, abs=EXACT)


def test_feature_census_counts_faces_by_kind():
    census = measure.feature_census(parts.holed_plate())
    assert {k: census[k].measured for k in ("plane_faces", "cylinder_faces", "concave_cylinders",
                                             "convex_cylinders", "bores")} == {
        "plane_faces": 7, "cylinder_faces": 3, "concave_cylinders": 3, "convex_cylinders": 0, "bores": 3}
    assert all(r.status == INCONCLUSIVE for r in measure.feature_census(None).values())


# -------------------------------------------------------- inside corners

MILL = (0, 0, 1)


def test_min_internal_radius_reads_the_fillet_and_catches_a_small_one():
    good = measure.min_internal_radius(parts.pocket(1.5), axis=MILL)
    bad = measure.min_internal_radius(parts.pocket(0.8), axis=MILL)
    assert good.measured == pytest.approx(1.5, abs=EXACT) and status(good, ">=", 1.0) == PASS
    assert bad.measured == pytest.approx(0.8, abs=EXACT) and status(bad, ">=", 1.0) == FAIL


def test_without_a_tool_axis_every_inside_corner_counts():
    """The pocket's floor edges are sharp: fine for a flat end mill, not for a part
    that is moulded or cast."""
    assert measure.min_internal_radius(parts.pocket(1.5)).measured == 0.0
    filleted = measure.min_internal_radius(parts.pocket(2.0, floor=True))       # sphere corners
    assert filleted.measured == pytest.approx(2.0, abs=EXACT) and filleted.detail["sharp_concave_edges"] == 0


@pytest.mark.parametrize("as_splines", [False, True])
def test_along_a_tool_axis_only_the_corners_it_cuts_count(as_splines):
    """R3 vertical corners over R0.5 floor fillets: a flat end mill's corners are the
    R3; the floor fillets lie across its axis, whether cylinders and tori or, from a
    NURBS-only system, B-splines."""
    shape = parts.pocket(3.0, floor=True, floor_radius=0.5)
    shape = parts.nurbs(shape) if as_splines else shape
    assert measure.min_internal_radius(shape, axis=MILL).measured == pytest.approx(3.0, abs=1e-6)
    assert measure.min_internal_radius(shape).measured == pytest.approx(0.5, abs=1e-6)


def test_a_skipped_fillet_reads_zero_along_the_tool_axis():
    cutter = Pos(5, 5, 5) * Box(30, 30, 20, align=MIN)
    three = cutter.fillet(1.5, cutter.edges().filter_by(Axis.Z).sort_by(Axis.X)[1:])
    result = measure.min_internal_radius(Box(40, 40, 20, align=MIN) - three, axis=MILL)
    assert result.measured == 0.0 and result.detail["sharp_concave_edges"] == 1


def boss_with_a_base_fillet(radius: float = 0.5):
    plate = Box(60, 40, 5, align=MIN) + Pos(20, 20, 5) * Cylinder(5, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    base = plate.edges().filter_by(lambda e: abs(e.center().Z - 5) < 1e-6 and e.geom_type.name == "CIRCLE")
    return plate.fillet(radius, base)


@pytest.mark.parametrize("shape", [lambda: parts.round_pocket(8.0, 0.5), boss_with_a_base_fillet])
def test_a_torus_fillet_is_an_inside_corner(shape):
    """A round pocket's floor fillet and a boss's base fillet are tori: counting only
    cylinders read such a part as having no inside corner (or another pocket's R3)."""
    result = measure.min_internal_radius(shape())
    assert result.measured == pytest.approx(0.5, abs=EXACT) and result.detail["from"] == "torus"


def test_a_torus_fillet_stored_as_b_splines_is_an_inside_corner():
    """Converted to B-splines, a round pocket's floor fillet wraps all the way round
    the pocket with one radius, but that is not the way it curves tightest: it is a
    corner, and only the pocket's wall is a bore."""
    part = parts.nurbs(parts.round_pocket(8.0, 0.5))
    result = measure.min_internal_radius(part)
    assert result.measured == pytest.approx(0.5, abs=1e-6) and result.detail["from"] == "freeform, sampled"
    assert measure.bore_census(part).measured == 1


@pytest.mark.parametrize("split", [False, True])
def test_a_countersink_is_not_a_drafted_corner(split):
    """A countersink is a concave cone round the whole hole. Split along the axis
    (with its seam, into three pieces of 180° or less), its pieces read as drafted
    corners of the hole's radius until their angles were united."""
    plate = parts.countersunk_plate(split=split)
    cones = sum(f.geom_type.name == "CONE" for f in plate.faces())
    assert cones >= 2 if split else cones == 1
    assert measure.min_internal_radius(plate).status == INCONCLUSIVE
    assert measure.bore_census(plate).measured == 1


def test_a_freeform_fillet_is_an_inside_corner():
    """OCCT makes the base fillet of a boss on a drum a B-spline, concave across and
    convex around: its radius is read from the curvature at samples."""
    part = parts.drum_boss(1.0)
    result = measure.min_internal_radius(part)
    assert result.measured == pytest.approx(1.0, abs=1e-3) and result.detail["from"] == "freeform, sampled"
    assert result.detail["largest_step_mm"] == largest_step(part, 0.5, lambda f: f.geom_type.name == "BSPLINE")


def test_a_round_on_a_holes_rim_is_not_an_inside_corner():
    """The round on a radial hole's rim is convex across (R0.5) and concave around
    the hole: counting any concave curvature read it as a 1.97 mm corner, and a
    convex loft as a 203 mm one."""
    assert measure.min_internal_radius(parts.rim_round_tube(0.5)).status == INCONCLUSIVE
    convex = loft([Plane.XY * Circle(10), Plane.XY.offset(20) * Ellipse(12, 5)])
    assert measure.min_internal_radius(convex).status == INCONCLUSIVE


@pytest.mark.parametrize("axis", [None, MILL])
@pytest.mark.parametrize("stored", ["analytic", "b-splines", "split in 2, b-splines", "split in 4, b-splines",
                                    "fitted through 24 points", "fitted, split in 2", "16 points, in quarters",
                                    "scanned, split in 2"])
def test_a_bore_is_not_an_inside_corner_however_it_is_stored(axis, stored):
    """The plate's inside corners are its pocket's R3, and its Ø3 hole is a bore. As
    B-splines, as a STEP from a NURBS-only system arrives, the hole read as a 1.5 mm
    corner; split into pieces of 180° or less it still did; fitted through points,
    as a reverse-engineered STEP holds it, its curvature ripples a few per cent and
    it read 1.42. Fitted piece by piece, the pieces' axes land up to 4e-3 mm apart:
    compared at 1e-3 they read as two bores, or as corners of 1.5."""
    part = {"analytic": lambda: parts.holed_pocket_plate(),
            "b-splines": lambda: parts.nurbs(parts.holed_pocket_plate()),
            "split in 2, b-splines": lambda: parts.nurbs(parts.split_closed(parts.holed_pocket_plate(), 2)),
            "split in 4, b-splines": lambda: parts.nurbs(parts.split_closed(parts.holed_pocket_plate(), 4)),
            "fitted through 24 points": lambda: parts.fitted_hole_plate(24),
            "fitted, split in 2": lambda: parts.split_closed(parts.fitted_hole_plate(24), 2),
            "16 points, in quarters": lambda: parts.split_closed(parts.fitted_hole_plate(16), 4),
            "scanned, split in 2": lambda: parts.split_closed(parts.fitted_hole_plate(36, 0.002), 2)}[stored]()
    assert measure.min_internal_radius(part, axis=axis).measured == pytest.approx(3.0, abs=1e-6)
    assert measure.bore_census(part).measured == 1


def test_pieces_of_one_bore_fitted_apart_are_one_bore(monkeypatch):
    """Pieces of a bore fitted each on its own land a hair apart: their axes and radii
    are compared to 1e-3 mm, not to the 1e-6 mm of analytic faces. With one half of
    the Ø3 hole fitted 2e-4 mm off, the halves read as two 1.5 mm corners."""
    from build123d import Face
    from OCP.gp import gp_Ax3, gp_Cylinder, gp_Pnt

    from pocad.measure import features
    real = features._fit

    def apart(face):
        found = real(face)
        if found and found[0] == "cylinder" and abs(found[1].Radius() - 1.5) < 1e-6 and Face(face).center().Y > 30:
            where = found[1].Position()
            at = where.Location()
            moved = gp_Ax3(gp_Pnt(at.X() + 2e-4, at.Y(), at.Z()), where.Direction(), where.XDirection())
            return "cylinder", gp_Cylinder(moved, found[1].Radius() + 2e-4)
        return found

    monkeypatch.setattr(features, "_fit", apart)
    part = parts.nurbs(parts.split_closed(parts.holed_pocket_plate(), 2))
    assert measure.min_internal_radius(part).measured == pytest.approx(3.0, abs=1e-6)
    assert measure.bore_census(part).measured == 1


def test_split_hole_features_stored_as_b_splines_are_not_corners():
    """A countersink or a round pocket's wall, split in halves and stored as
    B-splines: each half covers 180° and read as a corner of the hole's radius."""
    countersink = parts.nurbs(parts.split_closed(parts.countersunk_plate(), 2))
    assert measure.min_internal_radius(countersink).status == INCONCLUSIVE
    pocket = parts.nurbs(parts.split_closed(parts.round_pocket(8.0, 0.5), 2))
    assert measure.min_internal_radius(pocket, axis=MILL).status == INCONCLUSIVE     # it read 8.0


@pytest.mark.parametrize("as_splines", [False, True])
def test_a_bent_bore_is_not_an_inside_corner(as_splines):
    """A ring channel is a torus round its whole tube: it read as a 2.0 mm corner as
    a torus, and as no corner as B-splines."""
    part = parts.nurbs(parts.ring_channel()) if as_splines else parts.ring_channel()
    assert measure.min_internal_radius(part).status == INCONCLUSIVE


def test_a_shaped_hole_is_read_at_its_tightest_curvature():
    """A lofted hole whose curvature changes around it is not a bore: its tightest
    radius, 25/12 mm at the ellipse's ends, is an inside corner, read from samples
    (so a little above it)."""
    result = measure.min_internal_radius(parts.loft_hole())
    assert 25 / 12 <= result.measured <= 1.01 * 25 / 12 and result.detail["freeform_holes"] == 0


@pytest.mark.parametrize("as_splines", [False, True])
def test_a_drafted_corner_is_read_at_its_narrow_end(as_splines):
    """A drafted pocket's corners are cones (some stored as B-splines), 0.5 at the
    floor and wider above, leaning off the tool axis. Along the axis none of them
    counted; read from its curvature, a B-spline corner read 0.5/cos(draft)."""
    part = parts.nurbs(parts.drafted_pocket(0.5)) if as_splines else parts.drafted_pocket(0.5)
    result = measure.min_internal_radius(part, axis=MILL)
    assert result.measured == pytest.approx(0.5, abs=1e-6) and result.detail["from"].startswith("cone")
    undercut = parts.drafted_pocket(2.0, draft_deg=-3.0)                  # narrowest at the top
    undercut = parts.nurbs(undercut) if as_splines else undercut
    narrow = 2.0 - 15.0 * math.tan(math.radians(3.0))
    assert measure.min_internal_radius(undercut, axis=MILL).measured == pytest.approx(narrow, abs=1e-6)


def test_a_sharp_drafted_corner_reads_zero_along_the_tool_axis():
    """The sharp corners of a drafted pocket lean 4.2° off the tool axis. Counted only
    within 1° of it, they were missed, and the pocket read as having no inside
    corner."""
    sharp = parts.drafted_pocket(None)
    assert measure.min_internal_radius(sharp, axis=MILL).measured == 0.0
    assert measure.sharp_concave_edge_count(sharp, axis=MILL).measured == 4


def test_min_internal_radius_does_not_probe_bore_ends(monkeypatch):
    """It reads no bore's ends, and probing them doubled its time on a B-spline plate
    with 100 holes."""
    from pocad.measure import features

    def refuse(*args):
        raise AssertionError("a bore end was probed")

    monkeypatch.setattr(features, "_open_end", refuse)
    assert measure.min_internal_radius(parts.holed_pocket_plate()).measured == pytest.approx(3.0, abs=EXACT)


def test_a_freeform_face_too_large_for_its_spacing_is_inconclusive():
    result = measure.min_internal_radius(parts.nurbs(Box(300, 300, 10)))
    assert result.status == INCONCLUSIVE and "a spacing of" in result.reason


def test_a_chamfered_corner_is_sharp():
    cutter = Pos(5, 5, 5) * Box(30, 30, 20, align=MIN)
    chamfered = Box(40, 40, 20, align=MIN) - cutter.chamfer(1.0, None, cutter.edges().filter_by(Axis.Z))
    assert measure.min_internal_radius(chamfered, axis=MILL).measured == 0.0


def test_a_sharp_pocket_has_radius_zero_not_no_data():
    sharp = measure.min_internal_radius(parts.pocket(None))      # R04 §1
    assert sharp.measured == 0.0 and status(sharp, ">=", 1.0) == FAIL
    assert measure.min_internal_radius(Box(10, 10, 10)).status == INCONCLUSIVE


def test_sharp_concave_edges_are_counted():
    assert measure.sharp_concave_edge_count(parts.pocket(1.5, floor=True)).measured == 0
    assert measure.sharp_concave_edge_count(parts.pocket(None)).measured == 8
    assert measure.sharp_concave_edge_count(parts.pocket(None), axis=MILL).measured == 4
    assert measure.sharp_concave_edge_count(parts.pocket(1.5)).measured == 8        # four straight, four arcs
    assert measure.sharp_concave_edge_count(parts.pocket(1.5), axis=MILL).measured == 0
    blind = measure.sharp_concave_edge_count(parts.holed_plate())    # the blind hole's flat bottom
    assert blind.measured == 1 and blind.at == pytest.approx((45.95, 20.0, 4.0), abs=1e-6)
    assert measure.sharp_concave_edge_count(parts.tube()).measured == 0
    assert measure.sharp_concave_edge_count(None).status == INCONCLUSIVE


# ----------------------------------------------------------------- draft

def test_draft_angles_are_signed_and_exact():
    pull = (0, 0, 1)
    assert measure.draft_angles(parts.drafted_boss(3.0), pull).measured == pytest.approx(3.0, abs=1e-6)
    boss = parts.drafted_boss(3.0)
    assert measure.draft_angles(boss, pull).detail["largest_step_mm"] == largest_step(boss, 1.0)
    assert status(measure.draft_angles(parts.drafted_boss(3.0), pull), ">=", 1.5) == PASS
    assert status(measure.draft_angles(parts.drafted_boss(1.0), pull), ">=", 1.5) == FAIL
    inverted = Cone(10 - 10 * math.tan(math.radians(3)), 10, 10)
    assert measure.draft_angles(inverted, pull).measured == pytest.approx(-3.0, abs=1e-6)
    assert measure.draft_angles(Box(10, 10, 10), pull).measured == pytest.approx(0.0, abs=1e-9)
    assert measure.draft_angles(Box(10, 10, 10), (0, 0, 0)).status == INCONCLUSIVE


def test_undercuts_are_found_where_r04_found_them():
    t_slot = measure.undercuts(parts.undercut_part(), (0, 0, 1))
    assert (t_slot.measured, t_slot.detail["samples_facing_pull"]) == (66, 717)
    assert t_slot.detail["largest_step_mm"] == largest_step(parts.undercut_part(), 1.0)
    assert t_slot.at == pytest.approx((10.454545, 5.454545, 4.0), abs=1e-6)
    assert status(t_slot, "==", 0, 0) == FAIL
    assert status(measure.undercuts(parts.drafted_boss(3.0), (0, 0, 1)), "==", 0, 0) == PASS
    assert measure.undercuts(Box(10, 10, 10), (0, 0, 0)).status == INCONCLUSIVE


@pytest.mark.parametrize("slope,verdict", [(50.0, PASS), (45.0, PASS), (30.0, FAIL), (0.0, FAIL)])
def test_the_overhang_census_reads_a_ledge_at_its_slope(slope, verdict):
    """GATES D-03a: a ledge chamfered underneath at 50° is self-supporting, one at
    exactly 45° is on the limit (a plane is exact: no sampling bound), a 30° one and
    a flat-bottomed one are not. The column's bottom face lies on the bed and would
    read 0: it is left out, so the known-good part passes."""
    result = measure.overhang_census(parts.ledge(slope))
    assert result.measured == pytest.approx(slope, abs=1e-9) and status(result, ">=", 45.0) == verdict
    assert result.at[0] == pytest.approx(10.0, abs=1e-9) and result.at[2] == pytest.approx(10.0, abs=1e-9)
    assert result.detail["bed_samples"] > 0 and result.detail["bed_height_mm"] == 0.0
    assert result.detail["sampling_bound_deg"] == 0.0 and result.detail["seeds_refined"] == 0
    assert (result.detail["below_min_deg"] > 0) == (verdict == FAIL)
    assert result.detail["largest_step_mm"] == largest_step(parts.ledge(slope), 0.5)


@pytest.mark.parametrize("shape", [lambda: parts.ledge(30.0, height=0.5), lambda: parts.ledge(50.0, foot=0.5)],
                         ids=["30-degree ledge 0.5 above the bed", "flat foot 0.5 above the bed"])
def test_an_overhang_just_above_the_bed_is_not_taken_for_the_bed(shape):
    """Only what lies within 0.01 mm of the lowest height rests on the bed: a band
    of 0.5 mm or more would have swallowed both of these and passed them."""
    result = measure.overhang_census(shape())
    assert result.measured < 45.0 and status(result, ">=", 45.0) == FAIL
    assert result.at[2] == pytest.approx(0.5, abs=1e-9) and result.detail["bed_height_mm"] == 0.0
    on_bed = measure.overhang_census(parts.ledge(50.0, foot=0.0))
    assert on_bed.measured == pytest.approx(50.0, abs=1e-9)


@pytest.mark.parametrize("radius,tilt", [(0.5, 42.0), (0.7, 42.0), (0.35, 40.0), (0.5, 44.0), (4.0, 42.0)])
def test_a_small_tilted_hole_is_read_at_its_tilt(radius, tilt):
    """A grid only overshoots the least angle: at 0.5 mm it stepped 45° round an R0.5
    hole and read 46.64 for 42°, 45.03 for R0.7 at 42°, 48.44 for R0.35 at 40° and
    48.35 for R0.5 at 44°, all passes. Refined, the crown reads its tilt."""
    result = measure.overhang_census(parts.tilted_hole(radius, tilt))
    assert result.measured == pytest.approx(tilt, abs=0.01) and status(result, ">=", 45.0) == FAIL
    assert result.detail["seeds_refined"] > 0 and 0.0 < result.detail["sampling_bound_deg"] < 0.01
    assert set(result.detail["per_kind_least_deg"]) == {"cylinder"}


def test_a_curved_overhang_within_its_sampling_bound_of_the_limit_is_inconclusive():
    """A hole and a cone at exactly 45° read 45 to within their bound (under 0.01°):
    that could be below 45, so it is INCONCLUSIVE, never a pass. At 46° and 50° they
    are clear of it."""
    for shape in (parts.tilted_hole(0.5, 45.0), parts.standing_cone(45.0)):
        result = measure.overhang_census(shape)
        assert result.status == INCONCLUSIVE and "sampling bound" in result.reason
        assert result.detail["least_found_deg"] == pytest.approx(45.0, abs=0.01)
        assert status(result, ">=", 45.0) == INCONCLUSIVE
    for shape, angle in ((parts.tilted_hole(0.5, 46.0), 46.0), (parts.standing_cone(50.0), 50.0)):
        result = measure.overhang_census(shape)
        assert result.measured == pytest.approx(angle, abs=0.01) and status(result, ">=", 45.0) == PASS


@pytest.mark.parametrize("slope", [50.0, 30.0])
def test_a_cone_on_its_point_overhangs_at_its_slope_all_round(slope):
    """A curved overhang: every sample of the side is at the slope, and the samples
    at the point rest on the bed."""
    result = measure.overhang_census(parts.standing_cone(slope))
    assert result.measured == pytest.approx(slope, abs=1e-9)
    assert result.detail["per_kind_least_deg"] == {"cone": pytest.approx(slope, abs=1e-6)}
    below = result.detail["below_min_deg"]
    assert below == (result.detail["downward_samples"] if slope < 45.0 else 0)


def test_a_part_with_nothing_past_vertical_reads_90():
    """A box, a cone on its base, and the ledge printed upside down (its top on the
    bed) have no downward face off the bed."""
    for shape, build in ((Box(10, 10, 10), (0, 0, 1)), (Cone(10, 0, 10), (0, 0, 1)), (parts.ledge(), (0, 0, -1))):
        result = measure.overhang_census(shape, build)
        assert (result.measured, result.at, result.detail["downward_samples"]) == (90.0, None, 0)
        assert status(result, ">=", 45.0) == PASS


def test_the_overhang_census_follows_the_build_direction():
    """The ledge turned so that its build axis is +X, and a direction not of unit
    length, read the same angle."""
    turned = measure.overhang_census(Rot(0, 90, 0) * parts.ledge(50.0), (1, 0, 0))
    assert turned.measured == pytest.approx(50.0, abs=1e-9) and turned.params["build_dir"] == (1.0, 0.0, 0.0)
    assert measure.overhang_census(parts.ledge(30.0), (0, 0, 3)).measured == pytest.approx(30.0, abs=1e-9)


def test_a_horizontal_bores_crown_fails_the_overhang_census():
    """The crown of a bore on its side is a flat ceiling: 0°, found by refinement
    where the grid read 3.5°."""
    result = measure.overhang_census(Box(20, 20, 20) - Rot(0, 90, 0) * Cylinder(4, 30))
    assert result.measured == pytest.approx(0.0, abs=0.01) and status(result, ">=", 45.0) == FAIL
    assert set(result.detail["per_kind_least_deg"]) == {"cylinder"}


def test_the_overhang_census_is_inconclusive_when_it_cannot_measure(monkeypatch):
    assert measure.overhang_census(Box(10, 10, 10), (0, 0, 0)).status == INCONCLUSIVE
    assert measure.overhang_census(Box(10, 10, 10), min_deg=0.0).status == INCONCLUSIVE
    assert measure.overhang_census(parts.open_box()).reason == "no solid to scan"
    coarse = measure.overhang_census(Box(100, 100, 1), spacing=0.1)             # no quiet thinning
    assert coarse.status == INCONCLUSIVE and "fits" in coarse.reason
    real = measure_draft.face_samples
    ceiling = parts.ledge(0.0)
    flat = max((f for f in ceiling.faces() if f.normal_at().Z < -0.99), key=lambda f: f.center().Z).wrapped

    def blind(face, *args, **kwargs):                                  # the ledge's ceiling yields nothing
        return iter(()) if face.IsSame(flat) else real(face, *args, **kwargs)

    monkeypatch.setattr(measure_draft, "face_samples", blind)
    result = measure.overhang_census(ceiling)
    assert result.status == INCONCLUSIVE and "yielded no sample" in result.reason


def spans(shape, *args, **kw):
    kw.setdefault("max_span", 5.0)
    return measure.flat_ceiling_spans(shape, *args, **kw)


@pytest.mark.parametrize("width,verdict", [(4.0, PASS), (7.0, FAIL)])
def test_a_tunnel_is_a_bridge_its_width_across(width, verdict):
    """GATES D-03b: a tunnel's ceiling is carried by its two walls and spans its
    width; its ends open onto faces that rise from it and carry nothing, and do not
    make it longer. The true span lies within the reported bounds."""
    result = spans(parts.tunnel(width))
    assert result.measured == pytest.approx(width, abs=1e-3) and status(result, "<=", 5.0) == verdict
    assert result.at[0] == pytest.approx(10.0, abs=1e-9) and result.at[2] == pytest.approx(4.0, abs=1e-9)
    (ceiling,) = result.detail["ceilings"]
    assert ceiling["at_least_mm"] <= width <= ceiling["at_most_mm"]


def test_a_bridge_within_its_sampling_bound_of_max_span_is_inconclusive():
    """A 5.00 mm tunnel reads 5 to within its bound at the finest raster: it could be
    over 5, so it is INCONCLUSIVE, never a pass. At 4.95 the raster settles it under 5."""
    result = spans(parts.tunnel(5.0))
    assert result.status == INCONCLUSIVE and "sampling bound" in result.reason
    assert result.detail["span_found_mm"] == pytest.approx(5.0, abs=0.01)
    assert status(result, "<=", 5.0) == INCONCLUSIVE
    near = spans(parts.tunnel(4.95))
    assert near.measured == pytest.approx(4.95, abs=0.01) and status(near, "<=", 5.0) == PASS
    assert near.detail["ceilings"][0]["at_most_mm"] <= 5.0


def test_a_ceiling_carried_on_one_side_reads_twice_its_reach():
    """A flat-bottomed ledge 5 mm out from its column, and a tunnel whose right wall
    is gone, are carried on one side only: 10 and 8 mm, a fail. Of a stepped bore,
    the small bore's round top spans its 4 mm diameter, carried by a wall standing on
    the annulus at the step, a carried layer below; the annulus is carried only
    outside, where the big bore's wall goes down to the bed, and reads 2 x 2 mm."""
    ledge = spans(parts.ledge(0.0))
    assert ledge.measured == pytest.approx(10.0, abs=1e-3) and status(ledge, "<=", 5.0) == FAIL
    assert spans(parts.tunnel(4.0, shift=8.0)).measured == pytest.approx(8.0, abs=1e-3)
    stepped = spans(parts.stepped_bore())
    assert sorted(c["span_mm"] for c in stepped.detail["ceilings"]) == [pytest.approx(4.0, abs=1e-3)] * 2
    assert status(stepped, "<=", 5.0) == PASS


@pytest.mark.parametrize("shape,reach", [(lambda: parts.tunnel_rib(0.05), 9.95), (lambda: parts.tunnel_curtain(0.5), 9.5),
                                         (lambda: parts.tunnel_curtain(2.0), 8.0), (parts.tunnel_post, 10.0)],
                         ids=["rib 0.05 wide", "curtain 0.5 thick", "curtain 2 thick, short of the bed",
                              "plate on a 0.05 post"])
def test_a_support_that_will_not_print_carries_nothing(shape, reach):
    """A 10 mm tunnel with a rib thinner than a printable wall, a curtain hanging short
    of the bed (thin, or thick and ending in a V in air), or a plate on a hair-thin
    post: the review read 4.975, 4.75 and 4.17 mm, all passes. None of them reaches
    the bed min_support wide, so the ceiling is carried by the tunnel's walls alone."""
    result = spans(shape())
    assert result.measured == pytest.approx(reach, abs=1e-3) and status(result, "<=", 5.0) == FAIL


def test_a_rib_as_wide_as_min_support_carries():
    """A 1 mm rib down the middle of the 10 mm tunnel prints and carries: two bridges
    of 4.5 mm. Held to a min_support of 1.2 mm it does not, and each half is carried
    on one side only."""
    assert spans(parts.tunnel_rib(1.0)).measured == pytest.approx(4.5, abs=1e-3)
    assert spans(parts.tunnel_rib(1.0), min_support=1.2).measured == pytest.approx(9.0, abs=1e-3)


def test_the_way_to_support_runs_within_the_ceiling_not_through_air():
    """A tongue of ceiling 1.5 wide, attached only at its root 16 mm away, its tip
    2 mm from a wall across a 0.25 mm slit: the review read 3.98 mm through the slit.
    Within the ceiling it is about 17.4 mm from support, a 34.9 mm span."""
    result = spans(parts.comb_ceiling())
    assert result.measured > 30.0 and status(result, "<=", 5.0) == FAIL
    assert result.at[1] == pytest.approx(2.0, abs=0.3)


def test_nothing_flat_overhead_reads_0():
    """A box, a ledge chamfered at 50° and a cone on its base have no flat ceiling off
    the bed; the bed face is not one."""
    for shape in (Box(10, 10, 10), parts.ledge(50.0), Cone(10, 0, 10)):
        result = spans(shape)
        assert (result.measured, result.at, result.detail["ceilings"]) == (0.0, None, [])
    assert spans(Box(10, 10, 10)).detail["bed_faces"] == 1


def test_the_bridge_follows_the_build_direction():
    """The tunnel turned so that its build axis is +X reads the same span; printed
    along -Z it has no ceiling at all (its roof then faces up)."""
    assert spans(Rot(0, 90, 0) * parts.tunnel(4.0), (1, 0, 0)).measured == pytest.approx(4.0, abs=1e-3)
    assert spans(parts.tunnel(4.0), (0, 0, -1)).measured == 0.0


def test_the_bridge_is_inconclusive_when_it_cannot_measure():
    """No solid; a floating block, whose underside no edge carries (not a bridge: an
    overhang); a face too large for the spacing; arguments out of range; and no
    max_span, which has no default."""
    assert spans(parts.open_box()).reason == "no solid to scan"
    floating = Compound(children=[Box(10, 10, 2, align=MIN), Pos(0, 20, 5) * Box(4, 4, 4, align=MIN)])
    result = spans(floating)
    assert result.status == INCONCLUSIVE and "carried edge" in result.reason
    coarse = spans(parts.tunnel(4.0), spacing=0.001)
    assert coarse.status == INCONCLUSIVE and "fits" in coarse.reason
    for kw in ({"max_span": 0.0}, {"flat_deg": 50.0}, {"spacing": -1.0}, {"min_support": 0.0}):
        assert spans(parts.tunnel(4.0), **kw).status == INCONCLUSIVE
    assert spans(parts.tunnel(4.0), (0, 0, 0)).status == INCONCLUSIVE
    assert measure.flat_ceiling_spans(parts.tunnel(4.0)).status == INCONCLUSIVE


# -------------------------------------------------------------- assemblies

def test_interference_and_clearance_are_exact():
    base, cover = parts.pair(gap=0.3)
    assert measure.clearance(base, cover).measured == pytest.approx(0.3, abs=EXACT)
    assert status(measure.clearance(base, cover), ">=", 0.25) == PASS
    clash = measure.interference({"base": base, "cover": cover})["base|cover"]
    assert clash.measured == 0.0 and status(clash, "<=", 0.0) == PASS


def test_a_clash_and_a_tight_gap_fail():
    base, cover = parts.pair(gap=0.1)
    assert status(measure.clearance(base, cover), ">=", 0.25) == FAIL
    base, cover = parts.pair(gap=-0.1)                              # the 0.1 mm positive control
    clash = measure.interference({"base": base, "cover": cover})["base|cover"]
    assert clash.measured == pytest.approx(10.0, abs=EXACT) and status(clash, "<=", 0.0) == FAIL
    assert measure.clearance(None, base).status == INCONCLUSIVE
    with pytest.raises(ValueError):
        measure.interference({"base": base})


def test_a_part_inside_another_has_no_clearance():
    """Given Compounds, BRepExtrema measured the 3 mm to the walls, not the 0 of a part
    that sits inside another."""
    outer, inner = Compound(children=[Box(10, 10, 10)]), Compound(children=[Box(4, 4, 4)])
    result = measure.clearance(outer, inner)
    assert result.measured == 0.0 and result.detail["inside"]
    assert measure.interference({"outer": outer, "inner": inner})["outer|inner"].measured == pytest.approx(64.0)


def test_interference_with_an_unsound_part_is_inconclusive():
    clash = measure.interference({"sweep": parts.helix_sweep(), "block": parts.block(0.0, 2.0)})["sweep|block"]
    assert clash.status == INCONCLUSIVE and "BOPAlgo_SelfIntersect" in clash.reason


# --------------------------------------------------------- contact (L-22)

def test_touching_parts_have_no_common_volume_and_an_engaged_area():
    """Two blocks sharing a 10 x 20 face: interference reads 0 mm³, the contact 200 mm²."""
    block, cover = parts.contact_pair()
    assert measure.interference({"block": block, "cover": cover})["block|cover"].measured == 0.0
    area = measure.engaged_area(block, cover, (1, 0, 0), 0.05)
    assert area.measured == pytest.approx(200.0, abs=EXACT) and area.unit == "mm2"
    assert area.detail["area_at_half_depth"] == pytest.approx(200.0, abs=EXACT)
    assert area.params["depth"] == 0.05 and area.params["direction"] == [1.0, 0.0, 0.0]
    assert measure.engaged_area(block, cover, (5, 0, 0), 0.05).measured == pytest.approx(200.0, abs=EXACT)
    assert status(area, ">=", 190.0) == PASS
    assert measure.engaged_area(block, cover, (-1, 0, 0), 0.05).measured == 0.0    # pulled apart
    assert measure.engaged_area(block, cover, (0, 0, 1), 0.05).measured == 0.0     # sliding along the face


@pytest.mark.parametrize("kw,area", [({"width": 15.0}, 150.0), ({"shift": 5.0}, 150.0), ({"gap": 0.3}, 0.0),
                                     ({"gap": 0.05}, 0.0)])
def test_a_smaller_contact_or_a_gap_reads_less(kw, area):
    result = measure.engaged_area(*parts.contact_pair(**kw), (1, 0, 0), 0.05)
    assert result.measured == pytest.approx(area, abs=EXACT)
    assert status(result, ">=", 190.0) == (PASS if area >= 190 else FAIL)


def test_an_annular_bead_bears_with_its_projected_flank():
    """The bead's 45° flank rests on the groove's from R10.2 to R11: pushed down the
    axis the shaft bears on π(11² - 10.2²) mm²; lifted, it bears on nothing."""
    shaft, housing = parts.bead_in_groove()
    assert measure.interference({"shaft": shaft, "housing": housing})["shaft|housing"].measured == 0.0
    down = measure.engaged_area(shaft, housing, (0, 0, -1), 0.01)
    assert down.measured == pytest.approx(math.pi * (11 ** 2 - 10.2 ** 2), abs=EXACT)
    assert measure.engaged_area(shaft, housing, (0, 0, 1), 0.01).measured == 0.0
    small = measure.engaged_area(*parts.bead_in_groove(bead=10.6), (0, 0, -1), 0.01)
    assert small.measured == pytest.approx(math.pi * (10.6 ** 2 - 10.2 ** 2), abs=EXACT)
    assert measure.engaged_area(*parts.bead_in_groove(lift=0.3), (0, 0, -1), 0.01).measured == 0.0


def test_overlapping_parts_are_interference_not_an_area():
    result = measure.engaged_area(*parts.contact_pair(gap=-0.2), (1, 0, 0), 0.05)
    assert result.status == INCONCLUSIVE and "overlap" in result.reason
    assert result.detail["overlap_mm3"] == pytest.approx(40.0, abs=EXACT)


def test_parts_nearer_than_the_depth_that_do_not_touch_are_refused():
    result = measure.engaged_area(*parts.contact_pair(gap=0.02), (1, 0, 0), 0.05)
    assert result.status == INCONCLUSIVE and result.detail["gap_mm"] == pytest.approx(0.02, abs=EXACT)


@pytest.mark.parametrize("depth", [0, -0.05, 0.11, float("nan"), None])
def test_the_depth_is_positive_and_small_against_the_parts(depth):
    """At most 1 % of the least extent of either part: 0.1 mm for 10 mm blocks."""
    result = measure.engaged_area(*parts.contact_pair(), (1, 0, 0), depth)
    assert result.status == INCONCLUSIVE
    assert measure.engaged_area(*parts.contact_pair(), (1, 0, 0), 0.1).measured == pytest.approx(200.0, abs=EXACT)
    assert measure.engaged_area(*parts.contact_pair(), (0, 0, 0), 0.05).status == INCONCLUSIVE


def test_the_depth_has_no_default():
    result = measure.engaged_area(*parts.contact_pair(), (1, 0, 0))
    assert result.status == INCONCLUSIVE and "depth" in result.reason


def test_a_line_contact_has_no_area_to_give():
    """A cylinder lying on a block: the pushed volume grows as the depth to the power
    1.5, so the area read at half the depth disagrees and the result is refused."""
    roller = Pos(0, 0, 5) * Cylinder(5, 20, rotation=(90, 0, 0))
    result = measure.engaged_area(roller, Pos(0, 0, -5) * Box(20, 30, 10), (0, 0, -1), 0.05)
    assert result.status == INCONCLUSIVE and "changes with the depth" in result.reason


@pytest.mark.parametrize("near,depth", [(0.002, 0.05), (0.02, 0.05), (0.03, 0.05)])
def test_a_face_within_the_depth_along_the_push_is_refused(near, depth):
    """200 mm² touching and a 30 mm² face `near` mm off along the push: the push
    reaches the second face, and the area read at half the depth parts from the
    one at the full depth (228.8 against 227.6 at 2 µm). Refused, with both and
    the extrapolation in detail."""
    result = measure.engaged_area(*parts.contact_pair(near=near), (1, 0, 0), depth)
    assert result.status == INCONCLUSIVE and "changes with the depth" in result.reason
    assert result.detail["area_at_depth"] > 200.0 and "extrapolated" in result.detail


def test_a_face_beyond_the_depth_along_the_push_does_not_count():
    result = measure.engaged_area(*parts.contact_pair(near=0.1), (1, 0, 0), 0.05)
    assert result.measured == pytest.approx(200.0, abs=EXACT)


def test_a_push_that_slides_the_contact_is_refused():
    """Pushed at 45° the blocks also slide along their face, trimming the contact
    as the depth grows (141.17 against 141.30 mm²)."""
    result = measure.engaged_area(*parts.contact_pair(), (1, 1, 0), 0.05)
    assert result.status == INCONCLUSIVE and result.detail["spread"] > 0


def test_an_open_part_makes_the_engaged_area_inconclusive():
    block, cover = parts.contact_pair()
    assert measure.engaged_area(block, parts.without_top_face(cover), (1, 0, 0), 0.05).status == INCONCLUSIVE


# ----------------------------------------------------- radial probes (L-09, L-22)

AXIS = ((0, 0, 0), (0, 0, 1), (1, 0, 0))
RELEASE, LOCK = (0.0, 120.0, 240.0), (60.0, 180.0, 300.0)      # the relief centres, and between them


def test_radial_extent_reads_the_ring_exactly():
    ring = parts.relieved_ring()
    for angle, z, outer in ((0, 1, 19.6), (0, 4, 19.6), (0, 9, 19.5), (0, 11, 20.0), (60, 4, 20.0), (60, 9, 19.5)):
        result = measure.radial_extent(ring, *AXIS, angle, z)
        assert result.measured == pytest.approx(outer, abs=EXACT), (angle, z)
    inner = measure.radial_extent(ring, *AXIS, 60, 4, side="inner")
    assert inner.measured == pytest.approx(16.0, abs=EXACT)
    at = measure.radial_extent(ring, *AXIS, 90, 4)                 # 90° from the reference, about +Z
    assert at.at == pytest.approx((0.0, 20.0, 4.0), abs=EXACT)
    assert at.detail["material"] == [[pytest.approx(16.0, abs=EXACT), pytest.approx(20.0, abs=EXACT)]]


@pytest.mark.parametrize("window,side,expected", [((10.0, None), "inner", 16.0), ((0.0, None), "inner", 0.0),
                                                  ((0.0, 10.0), "outer", 7.0), ((0.0, None), "outer", 20.0)])
def test_the_radial_window_picks_the_annulus_meant_inside_a_tube_with_a_pin(window, side, expected):
    """From the axis the ray runs through the pin (R0 to R7) before the tube (R16 to
    R20): the innermost material of the whole ray is the pin, of the window from R10
    the bore; the outermost is the tube's outside, and within R10 the pin's."""
    r_min, r_max = window
    result = measure.radial_extent(parts.tube_with_pin(), *AXIS, 30, 6, side=side, r_min=r_min, r_max=r_max)
    assert result.measured == pytest.approx(expected, abs=EXACT)
    assert (result.params["r_min"], result.params["r_max"]) == window


def test_the_radial_window_reads_the_bead_tip_not_the_inner_wall():
    """At the bead's height a base's inner wall (R38 to R40) lies inside its bead
    (tip R45): only a window past the wall reads the tip the engagement needs."""
    base = parts.base_with_bead()
    assert measure.radial_extent(base, *AXIS, 0, 6, side="inner").measured == pytest.approx(38.0, abs=EXACT)
    tip = measure.radial_extent(base, *AXIS, 0, 6, side="inner", r_min=42.0)
    assert tip.measured == pytest.approx(45.0, abs=EXACT)
    below = measure.radial_extent(base, *AXIS, 0, 3, side="inner", r_min=42.0)       # under the bead
    assert below.measured == pytest.approx(46.0, abs=EXACT)
    profile = measure.radial_profile(base, *AXIS, range(0, 360, 30), (5.0, 7.0), margin=0.0, z_step=0.25,
                                     side="inner", r_min=42.0)
    assert profile["max"].measured == pytest.approx(45.0, abs=EXACT)


@pytest.mark.parametrize("window", [(39.0, None), (0.0, 47.0)])
def test_a_window_bound_through_material_is_refused(window):
    """A bound that cuts a stretch of material would read the bound as a wall."""
    result = measure.radial_extent(parts.base_with_bead(), *AXIS, 0, 6, side="inner", r_min=window[0],
                                   r_max=window[1])
    assert result.status == INCONCLUSIVE and "crosses" in result.reason


@pytest.mark.parametrize("window", [(-1.0, None), (20.0, 10.0), (0.0, float("inf"))])
def test_a_bad_radial_window_is_refused(window):
    assert measure.radial_extent(parts.tube_with_pin(), *AXIS, 0, 6, r_min=window[0], r_max=window[1]).status \
        == INCONCLUSIVE


def test_radial_extent_off_the_origin():
    """The ring moved to (5, -3, 2): the same radii about an axis through its new centre."""
    ring = Pos(5, -3, 2) * parts.relieved_ring()
    axis = ((5, -3, 2), (0, 0, 1), (1, 0, 0))
    assert measure.radial_extent(ring, *axis, 0, 4).measured == pytest.approx(19.6, abs=EXACT)
    moved = measure.radial_extent(ring, *axis, 90, 4)
    assert moved.measured == pytest.approx(20.0, abs=EXACT) and moved.at == pytest.approx((5, 17, 6), abs=EXACT)
    profile = measure.radial_profile(ring, *axis, RELEASE, (3.0, 8.0), margin=1.0, z_step=0.25)
    assert profile["max"].measured == pytest.approx(19.6, abs=EXACT)
    assert measure.radial_extent(ring, *AXIS, 0, 4).measured != pytest.approx(19.6, abs=1e-3)


def test_a_reference_leaning_off_square_is_refused():
    """0.5° is taken out and reported; 5° is refused, never projected quietly."""
    lean = (1, 0, math.tan(math.radians(0.5)))
    small = measure.radial_extent(parts.relieved_ring(), (0, 0, 0), (0, 0, 1), lean, 0, 4)
    assert small.measured == pytest.approx(19.6, abs=EXACT) and small.params["ref_lean_deg"] == pytest.approx(0.5)
    steep = measure.radial_extent(parts.relieved_ring(), (0, 0, 0), (0, 0, 1), (1, 0, math.tan(math.radians(5))), 0, 4)
    assert steep.status == INCONCLUSIVE and "leans" in steep.reason


@pytest.mark.parametrize("every", [1, 5])
def test_a_whole_degree_sweep_reads_the_rays_on_relief_faces(every):
    """The reliefs' side faces lie at ±20° about 0°, 120° and 240°: a ray there runs in
    the face, and is read 0.001° either side. The good ring's worst is the full wall
    (max R20 beside every relief) and its best the groove (min R19.5); the short
    relief is read the same way."""
    angles = range(0, 360, every)
    good = measure.radial_profile(parts.relieved_ring(), *AXIS, angles, (0.0, 8.0), margin=(0.0, 1.0), z_step=0.5)
    assert good["max"].status == good["min"].status == "MEASURED"
    assert good["max"].measured == pytest.approx(20.0, abs=EXACT)
    assert good["min"].measured == pytest.approx(19.5, abs=EXACT)
    faces = good["max"].detail["on_face"]
    assert {f["angle_deg"] % 120 for f in faces} == {20.0, 100.0} and not good["max"].detail["unread"]
    assert all(sorted(f["sides"]) == pytest.approx([19.6, 20.0], abs=EXACT) for f in faces if f["z"] < 8)
    release = measure.radial_profile(parts.relieved_ring(), *AXIS, [a for a in angles if a % 120 in (0, 20, 100)],
                                     (0.0, 8.0), margin=(0.0, 1.0), z_step=0.5)
    assert release["max"].measured == pytest.approx(20.0, abs=EXACT)    # the face ray counts its worse side
    inside = measure.radial_profile(parts.relieved_ring(), *AXIS, [a for a in angles if a % 120 in (0, 115, 5)],
                                    (0.0, 8.0), margin=(0.0, 1.0), z_step=0.5)
    assert inside["max"].measured == pytest.approx(19.6, abs=EXACT)


def test_a_ray_unread_on_both_sides_makes_the_profile_inconclusive():
    """A level in the rim's plane runs along a face at every angle, and turning it
    does not help: each such ray is listed unread."""
    result = measure.radial_profile(parts.relieved_ring(), *AXIS, (0.0, 60.0), (0.5, 1.5), margin=0.0, z_step=1.0)
    assert result["max"].status == "MEASURED"
    top = measure.radial_profile(parts.relieved_ring(), *AXIS, (0.0, 60.0), (11.5, 12.5), margin=0.0, z_step=0.5)
    assert top["max"].status == INCONCLUSIVE and len(top["max"].detail["unread"]) >= 2


def test_radial_extent_on_a_turned_axis():
    """The same ring turned to lie along X reads the same radii."""
    from build123d import Rot
    ring = Rot(0, 90, 0) * parts.relieved_ring()                  # the ring's +Z is now +X
    assert measure.radial_extent(ring, (0, 0, 0), (1, 0, 0), (0, 0, -1), 0, 4).measured == pytest.approx(19.6, abs=EXACT)
    assert measure.radial_extent(ring, (0, 0, 0), (1, 0, 0), (0, 0, -1), 60, 4).measured == pytest.approx(20.0, abs=EXACT)


@pytest.mark.parametrize("args", [(13.0,), (-2.0,)])
def test_a_ray_that_finds_no_material_is_inconclusive(args):
    result = measure.radial_extent(parts.relieved_ring(), *AXIS, 0, *args)
    assert result.status == INCONCLUSIVE and "no material" in result.reason


def test_a_ray_along_a_face_is_inconclusive():
    """At z = 0 the ray runs in the rim's face: neither inside nor outside."""
    result = measure.radial_extent(parts.relieved_ring(), *AXIS, 60, 0)
    assert result.status == INCONCLUSIVE and "along a face" in result.reason


def test_radial_extent_refuses_a_reference_along_the_axis_and_a_bad_side():
    assert measure.radial_extent(parts.relieved_ring(), (0, 0, 0), (0, 0, 1), (0, 0, 2), 0, 4).status == INCONCLUSIVE
    assert measure.radial_extent(parts.relieved_ring(), *AXIS, 0, 4, side="middle").status == INCONCLUSIVE


def test_radial_profile_sweeps_angle_and_height_together():
    """The good ring: at the release angles the wall stays at the relief's R19.6 (or
    the groove's R19.5) over the whole stroke, rim to groove; at the lock angles it
    stands at R20 below the groove."""
    ring = parts.relieved_ring()
    release = measure.radial_profile(ring, *AXIS, RELEASE, (0.0, 8.0), margin=(0.0, 1.0), z_step=0.25)
    assert release["max"].measured == pytest.approx(19.6, abs=EXACT)
    assert release["min"].measured == pytest.approx(19.5, abs=EXACT)
    assert release["max"].params["window"] == [0.0, 9.0] and release["max"].params["margin"] == [0.0, 1.0]
    points = release["max"].detail["points"]
    assert len(points) == 3 * 36 and release["max"].detail["largest_step_mm"] == pytest.approx(0.25)
    assert min(p["z"] for p in points) == pytest.approx(0.125) and max(p["z"] for p in points) == pytest.approx(8.875)
    lock = measure.radial_profile(ring, *AXIS, LOCK, (0.0, 8.0), margin=0.0, z_step=0.25)
    assert lock["min"].measured == pytest.approx(20.0, abs=EXACT)


def test_a_relief_that_stops_short_of_the_rim_is_caught_only_past_the_nominal_cut():
    """a known snap-fit defect (L-09, L-22): the reliefs stop 3 mm short of the rim. A window
    exactly at the modelled cut, z 3 up to the groove at 8, sees the relief everywhere and passes;
    widened by 1 mm it reads the full R20 wall below the cut and fails. The same
    widened window passes the ring whose reliefs reach the rim, so the widening is
    what finds the defect, not a stricter window."""
    short, good = parts.relieved_ring(relief_from=3.0), parts.relieved_ring()
    cut = (3.0, 8.0)
    exact = measure.radial_profile(short, *AXIS, RELEASE, cut, margin=0.0, z_step=0.25)["max"]
    assert exact.measured == pytest.approx(19.6, abs=EXACT) and status(exact, "<=", 19.6) == PASS
    widened = measure.radial_profile(short, *AXIS, RELEASE, cut, margin=1.0, z_step=0.25)["max"]
    assert widened.measured == pytest.approx(20.0, abs=EXACT) and status(widened, "<=", 19.6) == FAIL
    assert widened.detail["z"] < 3.0 and widened.params["window"] == [2.0, 9.0]
    assert status(measure.radial_profile(good, *AXIS, RELEASE, cut, margin=1.0, z_step=0.25)["max"],
                  "<=", 19.6) == PASS


def test_an_angle_only_sweep_passes_the_defect_at_one_height():
    """L-09: the designer's sweep, every angle at one height inside the relief band."""
    short = parts.relieved_ring(relief_from=3.0)
    one_height = [measure.radial_extent(short, *AXIS, a, 4.0).measured for a in RELEASE]
    assert one_height == pytest.approx([19.6] * 3, abs=EXACT)


def test_radial_profile_is_inconclusive_where_a_ray_finds_nothing():
    """Widened past the rim, a window reaches levels with no wall: refused, with the
    points read so far."""
    result = measure.radial_profile(parts.relieved_ring(), *AXIS, RELEASE, (0.0, 8.0), margin=1.0, z_step=0.25)
    assert all(r.status == INCONCLUSIVE for r in result.values())
    unread = result["max"].detail["unread"]
    assert "no material" in result["max"].reason and unread and all(u["z"] < 0 for u in unread)
    assert len(unread) == 3 * 4 and len(result["max"].detail["points"]) == 3 * 36     # every other ray read
    widened_up = measure.radial_profile(parts.relieved_ring(), *AXIS, RELEASE, (0.0, 8.0), margin=(0.0, 1.0),
                                        z_step=0.25)                    # widened toward one end only
    assert widened_up["max"].measured == pytest.approx(19.6, abs=EXACT)


@pytest.mark.parametrize("kw", [{"margin": -1.0}, {"margin": (1.0,)}, {"margin": 0.0, "z_step": 0},
                                {"margin": 0.0, "z_step": 1e-4}])
def test_radial_profile_refuses_a_bad_window(kw):
    result = measure.radial_profile(parts.relieved_ring(), *AXIS, RELEASE, (3.0, 8.0), **kw)
    assert all(r.status == INCONCLUSIVE for r in result.values())


def test_radial_profile_has_no_default_margin():
    result = measure.radial_profile(parts.relieved_ring(), *AXIS, RELEASE, (3.0, 8.0))
    assert result["max"].status == INCONCLUSIVE and "margin" in result["max"].reason


# ------------------------------------------------ keep-in envelopes and retained bands

KEEPIN_APEX, KEEPIN_ANGLE = (0.0, 0.0, -16.330), math.degrees(math.atan(math.sqrt(2.0)))


def keepin(shape, **kw):
    """The REQ-04 envelope r(t) <= √2·(16.330 - t) - 0.75, t = -z: apex at t = 16.330,
    opening toward the face plane; below the face plane only (t >= 0, s <= 16.330)."""
    kw.setdefault("s_range", (None, 16.330))
    kw.setdefault("offset", 0.75)
    return measure.keepin_cone_free(shape, KEEPIN_APEX, (0, 0, 1), KEEPIN_ANGLE, **kw)


@pytest.mark.parametrize("clear,verdict", [(0.5, PASS), (-0.3, FAIL)])
def test_a_plug_inside_the_keepin_cone_reads_its_clearance(clear, verdict):
    """A cone plug 0.5 inside the envelope all along its side reads 0.5, proven over
    every face; one 0.3 outside it reads -0.3, a real point of the part outside."""
    result = keepin(parts.keepin_plug(clear))
    assert result.measured == pytest.approx(clear, abs=1e-9) and status(result, ">=", 0.0) == verdict
    t = -result.at[2]
    assert math.hypot(result.at[0], result.at[1]) == pytest.approx(parts.keepin_radius(t, clear), abs=1e-6)
    if verdict == PASS:
        assert 0.0 <= result.detail["proven_mm"] <= result.measured and result.detail["unsettled_cells"] == 0


def test_the_keepin_envelope_given_as_a_function_reads_the_same():
    """r <= R(s) given as a function, with its slope read from it or stated."""
    def radius(s):
        return math.sqrt(2.0) * s - 0.75

    for kw in ({}, {"max_slope": math.sqrt(2.0)}):
        result = measure.keepin_cone_free(parts.keepin_plug(0.5), KEEPIN_APEX, (0, 0, 1), radius=radius,
                                          s_range=(0.0, 16.330), **kw)
        assert result.measured == pytest.approx(0.5, abs=1e-9)
        assert result.params["slope_estimated"] == (not kw)


@pytest.mark.parametrize("clear,verdict", [(0.5, PASS), (-0.3, FAIL)])
def test_a_socket_keeps_out_of_the_envelope_by_its_clearance(clear, verdict):
    """keep="out", as the frame holds it: a conical cavity 0.5 outside the envelope
    over the range reads 0.5; one 0.3 inside it reads -0.3. The floor and the bore
    past either end of the range are not held to it."""
    result = keepin(parts.keepin_socket(clear), keep="out", s_range=(16.330 - 14.0, 16.330 - 4.0))
    assert result.measured == pytest.approx(clear, abs=1e-9) and status(result, ">=", 0.0) == verdict


def test_material_filling_the_envelope_with_no_surface_inside_it_fails():
    """A block with no cavity at all: every face lies outside the envelope, and a
    reading of the surface alone passed it. The axis in the envelope is in the block,
    so the envelope is full: -R(s) at that point."""
    result = keepin(parts.keepin_socket(filled=True), keep="out", s_range=(16.330 - 14.0, 16.330 - 4.0))
    assert status(result, ">=", 0.0) == FAIL and result.at[:2] == (0.0, 0.0)
    s = result.detail["filled_at_s"]
    assert result.measured == pytest.approx(-(math.sqrt(2.0) * s - 0.75), abs=1e-9)


def test_a_keepin_margin_within_its_sampling_bound_is_inconclusive():
    """A plug 0.05 inside the envelope: its cells cannot all be proven clear before
    the search's budget, so the least, 0.05, is INCONCLUSIVE, never a pass."""
    result = keepin(parts.keepin_plug(0.05))
    assert result.status == INCONCLUSIVE and "sampling bound" in result.reason
    assert result.detail["least_found_mm"] == pytest.approx(0.05, abs=1e-9)
    assert result.detail["sampling_bound_mm"] > 0.05 and status(result, ">=", 0.0) == INCONCLUSIVE


def test_a_cylinder_whose_least_lies_on_a_rim_settles():
    """An R2 cylinder 0.8 off the axis of a 30° cone stands 0.0868 inside it at its
    bottom rim. The square parameter box of its bottom face runs past the rim, and
    the cells there were bounded from the plane beyond it, which runs out of the
    cone: at 0.5 mm the review read INCONCLUSIVE. They are bounded from the rim's own
    samples now, and the least is proven."""
    cylinder = Pos(0.8, 0, 5) * Cylinder(2, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    result = measure.keepin_cone_free(cylinder, (0, 0, 0), (0, 0, 1), 30.0, spacing=0.5)
    assert result.measured == pytest.approx(math.tan(math.radians(30.0)) * 5.0 - 2.8, abs=1e-9)
    assert result.at == pytest.approx((2.8, 0.0, 5.0), abs=1e-6) and result.detail["unsettled_cells"] == 0


def test_the_keepin_is_inconclusive_when_it_cannot_measure():
    assert keepin(parts.open_box()).reason == "no solid to scan"
    assert "no point" in keepin(parts.keepin_plug(0.5), s_range=(20.0, 30.0)).reason
    for kw in ({"keep": "sideways"}, {"s_range": (5.0, 1.0)}, {"offset": math.nan}):
        assert keepin(parts.keepin_plug(0.5), **kw).status == INCONCLUSIVE
    both = measure.keepin_cone_free(parts.keepin_plug(0.5), KEEPIN_APEX, (0, 0, 1), 45.0, radius=abs)
    open_range = measure.keepin_cone_free(parts.keepin_plug(0.5), KEEPIN_APEX, (0, 0, 1), radius=abs)
    assert both.status == open_range.status == INCONCLUSIVE and "closed s_range" in open_range.reason


BORE_AXIS = ((0, 0, 0), (0, 0, 1))


def slot_deg(width: float, radius: float = 8.0) -> float:
    return math.degrees(2 * math.asin(width / 2 / radius))


def test_a_slotted_collar_retains_its_bore_less_its_slots():
    """Three 3 mm entry slots take 2·asin(3/16) each of the R8 bore; the band keeps
    three runs between them. Below the slots it keeps the whole circle."""
    result = measure.retained_arc(parts.slotted_collar(), BORE_AXIS, 8.0, (0.0, 10.0), min_total_deg=195.0,
                                  run_floor_deg=60.0)
    assert result.measured == pytest.approx(360 - 3 * slot_deg(3.0), abs=1e-6)
    assert status(result, ">=", 195.0) == PASS
    assert result.detail["runs"] == 3 and result.detail["fewest_runs_over_floor"] == 3
    assert result.detail["longest_run_deg"] == pytest.approx(120 - slot_deg(3.0), abs=1e-6)
    assert result.detail["sampling_bound_deg"] == 0.0 and 4.0 < result.detail["z"] < 10.0
    assert math.hypot(result.at[0], result.at[1]) == pytest.approx(8.0, abs=1e-6)
    below = measure.retained_arc(parts.slotted_collar(), BORE_AXIS, 8.0, (0.0, 3.5), min_total_deg=195.0)
    assert below.measured == 360.0 and below.detail["fewest_runs_over_floor"] is None


def test_too_many_slots_fail_the_band_and_the_boss_is_read_too():
    many = measure.retained_arc(parts.slotted_collar(slots=9), BORE_AXIS, 8.0, (0.0, 10.0), min_total_deg=195.0)
    assert many.measured == pytest.approx(360 - 9 * slot_deg(3.0), abs=1e-6)
    assert status(many, ">=", 195.0) == FAIL
    outer = measure.retained_arc(parts.slotted_collar(), BORE_AXIS, 12.0, (0.0, 10.0), min_total_deg=195.0)
    assert outer.measured == pytest.approx(360 - 3 * slot_deg(3.0, 12.0), abs=1e-6)


def test_a_round_hole_is_read_at_its_widest_height():
    """A Ø4 radial hole is widest at its own centre height, which no grid station
    need hit: the band is read there, at the height where the hole's edge turns."""
    hole = parts.slotted_collar(hole=4.0)
    result = measure.retained_arc(hole, BORE_AXIS, 8.0, (0.0, 10.0), min_total_deg=195.0, z_step=0.3)
    assert result.measured == pytest.approx(360 - 2 * slot_deg(4.0), abs=1e-6)
    assert result.detail["turning_heights"] > 0 and result.detail["z"] == pytest.approx(5.0, abs=1e-4)


@pytest.mark.parametrize("hole,expected", [(0.5, 352.84), (1.0, 345.67)])
def test_a_small_radial_hole_takes_only_its_own_width(hole, expected):
    """A small hole's edge passes so near the middle of the long arcs between the
    holes that a classifier reads it ON there: the review read 0°. The arc is now
    classified at several points, ON counting for neither side."""
    result = measure.retained_arc(parts.slotted_collar(hole=hole), BORE_AXIS, 8.0, (0.0, 10.0), min_total_deg=195.0)
    assert result.measured == pytest.approx(360 - 2 * slot_deg(hole), abs=1e-6)
    assert result.measured == pytest.approx(expected, abs=0.01) and result.detail["runs"] == 2


def test_a_band_whose_runs_slide_is_inconclusive_at_its_limit():
    """Tilted slots slide round as they go down: between stations the band is only
    bounded by the overlap of its runs. Clear of the limit it is MEASURED with that
    bound; exactly at its least it could dip below between stations, and is
    INCONCLUSIVE."""
    tilted = parts.slotted_collar(tilt_deg=20.0)
    clear = measure.retained_arc(tilted, BORE_AXIS, 8.0, (5.0, 6.0), min_total_deg=195.0)
    assert status(clear, ">=", 195.0) == PASS and clear.detail["sampling_bound_deg"] > 0.1
    limit = measure.retained_arc(tilted, BORE_AXIS, 8.0, (5.0, 6.0), min_total_deg=clear.measured)
    assert limit.status == INCONCLUSIVE and "sampling bound" in limit.reason
    assert limit.detail["least_found_deg"] == pytest.approx(clear.measured, abs=1e-6)


def test_the_retained_arc_is_inconclusive_when_it_cannot_measure():
    collar = parts.slotted_collar()
    assert "no cylindrical face" in measure.retained_arc(collar, BORE_AXIS, 9.0, (0, 10), min_total_deg=195).reason
    assert measure.retained_arc(parts.open_box(), BORE_AXIS, 8.0, (0, 10), min_total_deg=195).status == INCONCLUSIVE
    freeform = measure.retained_arc(parts.nurbs(collar), BORE_AXIS, 8.0, (0, 10), min_total_deg=195)
    assert freeform.status == INCONCLUSIVE and "freeform" in freeform.reason
    for kw in ({"min_total_deg": 0.0}, {"min_total_deg": 195, "z_step": 0.0}):
        assert measure.retained_arc(collar, BORE_AXIS, 8.0, (0, 10), **kw).status == INCONCLUSIVE
    assert measure.retained_arc(collar, BORE_AXIS, 8.0, (5, 5), min_total_deg=195).status == INCONCLUSIVE


# ------------------------------------------------------------- properties

def test_mass_properties_are_exact_and_need_a_density():
    props = measure.mass_properties(parts.tube(), 1240.0)
    analytic = math.pi * (15 ** 2 - 12 ** 2) * 20
    assert props["volume"].measured == pytest.approx(analytic, rel=1e-12)
    assert props["mass"].measured == pytest.approx(analytic * 1240.0 * 1e-6, rel=1e-12)
    heavy = measure.mass_properties(parts.scaled_tube(1.05), 1240.0)["mass"]
    reference = props["mass"].measured
    assert status(heavy, "in", (0.95 * reference, 1.05 * reference)) == FAIL
    assert all(r.status == INCONCLUSIVE for r in measure.mass_properties(parts.tube(), 0).values())


def test_mass_counts_only_the_solids():
    stray = Compound(children=[Box(10, 10, 10), Plane.XY.offset(20) * Rectangle(10, 10)])
    assert measure.mass_properties(stray, 1000.0)["volume"].measured == pytest.approx(1000.0)


def test_envelope_reports_size_and_position_apart():
    box = measure.envelope(parts.tray())
    assert [box[f"size_{a}"].measured for a in "xyz"] == pytest.approx([40.0, 30.0, 20.0], abs=EXACT)
    moved = measure.envelope(parts.tray(at=(5.0, 0.0, 0.0)))      # L-12: the size did not change
    assert moved["size_x"].measured == pytest.approx(40.0, abs=EXACT)
    assert moved["min_x"].measured == pytest.approx(5.0, abs=EXACT)
    long = measure.envelope(parts.tray(length=41.0))                # a part 1 mm over a 40 mm bed
    assert status(long["size_x"], "<=", 40.0) == FAIL
    assert all(r.status == INCONCLUSIVE for r in measure.envelope(None).values())


# ------------------------------------------------------------------ traps

def test_trap_the_solid_classifier_is_wrong_on_a_compound_of_touching_solids():
    """A point inside the second of two touching solids reads OUT when the classifier
    is given their Compound; pocad.measure classifies against each solid."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_OUT

    from pocad.measure.sampling import Inside
    first, second = parts.block(0.0), parts.block(10.0)
    classifier = BRepClass3d_SolidClassifier(Compound(children=[first, second]).wrapped)
    classifier.Perform(gp_Pnt(15, 5, 5), 1e-7)
    assert classifier.State() == TopAbs_OUT
    assert Inside(second.wrapped)((15, 5, 5))


@needs_embree
def test_trap_trimesh_casts_rays_with_embree(tmp_path):
    """Without embreex, trimesh falls back to its rtree engine without a word: it
    tests every triangle in each ray's box out to the mesh bounds, so the wall scan
    of a 29k-triangle STL ran out of memory. With Embree a 25k-triangle STL takes
    under a second."""
    written = core.write_stl(parts.tube(), tmp_path / "tube.stl", tolerance=0.01, angular_tolerance=0.1)
    assert trimesh.ray.has_embree
    assert type(measure_wall.load_mesh(written.path).ray).__module__ == "trimesh.ray.ray_pyembree"
