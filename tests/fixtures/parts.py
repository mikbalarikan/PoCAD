# kaynak: oguz-atolye tools/tests/fixtures/parts.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Parametric geometry fixtures with known answers (R04 §6: generated, not committed).

Each function builds a part in memory. The mutation families of oguz-atolye U-19 are
parameters of the same generators: resize a dimension, relocate a feature, remove
a feature, or degrade the file it travels in.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Compound, Cylinder, Pos, Shell

MIN = (Align.MIN, Align.MIN, Align.MIN)
BASE = (Align.CENTER, Align.CENTER, Align.MIN)


def bracket(thickness: float = 4.0, boss_lift: float = 0.0, label: str = "bracket"):
    """A 40 x 20 plate with a Ø5 through hole at (10, 10) and a Ø8 x 6 boss at (30, 10).
    boss_lift > 0 lifts the boss off the plate (the relocate mutant: two solids)."""
    plate = Box(40, 20, thickness, align=MIN) - Pos(10, 10, -1) * Cylinder(2.5, thickness + 2, align=BASE)
    part = plate + Pos(30, 10, thickness + boss_lift) * Cylinder(4, 6, align=BASE)
    part.label = label
    return part


def bracket_volume(thickness: float = 4.0) -> float:
    return 40 * 20 * thickness - math.pi * 2.5 ** 2 * thickness + math.pi * 4 ** 2 * 6


def open_box():
    """A box missing one face: a valid open shell, no solid (R04: IsValid() is true)."""
    faces = list(Box(10, 10, 10).faces())
    return Shell(faces[:-1])


def without_top_face(part):
    """The remove mutant: the part's highest face taken away, leaving an open shell
    that keeps the part's name."""
    faces = sorted(part.faces(), key=lambda f: f.center().Z)
    shell = Shell(faces[:-1])
    shell.label = getattr(part, "label", "")
    return shell


def bow_tie():
    """A closed solid from a self-intersecting profile: one solid, no naked edges,
    and invalid topology. Only brep_valid catches it."""
    from build123d import Face, Polyline, Solid, Vector, Wire
    profile = Face(Wire(Polyline((0, 0), (10, 10), (10, 0), (0, 10), close=True).edges()))
    return Solid.extrude(profile, Vector(0, 0, 5))


def two_solids():
    return Compound(children=[Box(5, 5, 5), Pos(20, 0, 0) * Box(5, 5, 5)])


def empty_boolean():
    """What a boolean that removes everything returns: an empty compound (R02)."""
    return Box(5, 5, 5) - Box(10, 10, 10)


def tube(od: float = 30.0, bore: float = 24.0, height: float = 20.0):
    return Cylinder(od / 2, height) - Cylinder(bore / 2, height + 2)


def block(dx: float = 0.0, size: float = 10.0):
    return Pos(dx, 0, 0) * Box(size, size, size, align=MIN)


def pair(gap: float = 0.3, grow: float = 0.0, label_a: str = "base", label_b: str = "cover"):
    """Two 10 mm cubes along X, `gap` apart; `grow` enlarges the second one toward the first."""
    a = block()
    b = Pos(10 + gap - grow, 0, 0) * Box(10 + grow, 10, 10, align=MIN)
    a.label, b.label = label_a, label_b
    return a, b


def helix_sweep(pitch: float = 3.0, tube: float = 3.0, radius: float = 4.0, turns: float = 1.5):
    """A round tube swept along a helix. With pitch < 2 x tube the coils overlap: one
    closed solid, no naked edge, and BRepCheck passes it; only the analyzer stage of
    brep_valid finds the self-intersection."""
    from build123d import Circle, Helix, Plane, sweep
    path = Helix(pitch=pitch, height=pitch * turns, radius=radius)
    return sweep(Plane(origin=path @ 0, z_dir=path % 0) * Circle(tube), path=path)


def inside_out(size: float = 10.0):
    """A box with its orientation reversed: BRepCheck passes it; its volume is negative."""
    from build123d import Solid
    return Solid(Box(size, size, size, align=MIN).wrapped.Reversed())


def round_solids():
    """Sound solids with degenerate edges: a sphere (two poles) and a cone (an apex)."""
    from build123d import Cone, Sphere
    return Sphere(10), Cone(10, 0, 20)


def lofted():
    """A loft from a circle through an ellipse to a square: B-spline faces."""
    from build123d import Circle, Ellipse, Plane, Rectangle, loft
    return loft([Plane.XY * Circle(10), Plane.XY.offset(10) * Ellipse(12, 5),
                 Plane.XY.offset(20) * Rectangle(8, 8)])


def glyph(text: str = "O"):
    """Extruded text: build123d draws glyph outlines with Bezier curves."""
    from build123d import Text, extrude
    return extrude(Text(text, 10), 2)


def threaded_rod(length: float = 8.0, pitch: float = 2.0, radius: float = 5.0):
    """A rod with a triangular thread swept along a helix: a sound part whose pcurves
    come back from a STEP round trip a few picometres further off their edges than
    the edges' own tolerance."""
    from build123d import Helix, Plane, Triangle, sweep
    rod = Cylinder(radius, length + 4, align=BASE)
    path = Helix(pitch=pitch, height=length, radius=radius - 0.2, center=(0, 0, 2))
    profile = Plane(origin=path @ 0, x_dir=(1, 0, 0), z_dir=path % 0) * Triangle(
        a=0.8 * pitch, b=0.8 * pitch, c=0.8 * pitch)
    return rod + sweep(profile, path=path, is_frenet=True)


# ------------------------------------------------ R04 and R02 analytic fixtures

def tray(wall: float = 3.0, thin: float | None = None, shift: float = 0.0, length: float = 40.0,
         open_side: bool = False, at: tuple = (0.0, 0.0, 0.0)):
    """An open tray `length` x 30 x 20 with walls `wall` thick: one side wall `thin`,
    the cavity moved `shift` toward +X, or the +X wall cut away (`open_side`)."""
    width, height, floor = 30.0, 20.0, 3.0
    x_wall = wall if thin is None else thin
    far = -1.0 if open_side else wall
    cavity = Pos(x_wall + shift, wall, floor) * Box(length - x_wall - far, width - 2 * wall,
                                                    height - floor + 1, align=MIN)
    return Pos(*at) * (Box(length, width, height, align=MIN) - cavity)


def block_with_thin_fin(fin: float = 0.8):
    """v1's blind spot: a thick block next to one thin fin (R04, L-07)."""
    return Box(20, 20, 20, align=MIN) + Pos(20, 0, 0) * Box(30, fin, 15, align=MIN)


def drafted_boss(draft_deg: float = 3.0, height: float = 10.0, base_radius: float = 10.0):
    """A round boss narrowing upward at `draft_deg`; with no draft, a cylinder."""
    from build123d import Cone
    if draft_deg == 0:
        return Cylinder(base_radius, height)
    return Cone(base_radius, base_radius - height * math.tan(math.radians(draft_deg)), height)


def undercut_part():
    """A T-slot in the top face: the slot roof cannot be reached from +Z (R04)."""
    body = Box(30, 20, 12, align=MIN)
    neck = Pos(10, 8, 4) * Box(10, 4, 9, align=MIN)
    belly = Pos(10, 5, 4) * Box(10, 10, 4, align=MIN)
    return body - neck - belly


def holed_plate(shift: float = 0.0, blind_depth: float = 4.0, drill_point: bool = False,
                big: float | None = 5.0, small: bool = True):
    """Ø`big` (5.0) through at (15 + shift, 20) unless big is None, Ø3.2 through at
    (35, 20) unless small is False, Ø4.1 blind at (48, 20)."""
    from build123d import Cone
    plate = Box(60, 40, 8, align=MIN)
    if big is not None:
        plate -= Pos(15 + shift, 20, -1) * Cylinder(big / 2, 10, align=BASE)
    if small:
        plate -= Pos(35, 20, -1) * Cylinder(1.6, 10, align=BASE)
    plate -= Pos(48, 20, 8 - blind_depth) * Cylinder(2.05, blind_depth + 1, align=BASE)
    if drill_point:
        tip = 2.05 / math.tan(math.radians(59))
        plate -= Pos(48, 20, 8 - blind_depth - tip) * Cone(0, 2.05, tip, align=BASE)
    return plate


def pocket(radius: float | None = None, floor: bool = False, shift: float = 0.0,
           floor_radius: float | None = None):
    """A 40 x 40 x 20 block with a 30 x 30 pocket, its vertical corners (and with
    `floor` its floor edges too, at `floor_radius` when given) filleted at `radius`,
    or sharp when radius is None (R04); `shift` moves the pocket along +X."""
    from build123d import Axis
    cutter = Pos(5 + shift, 5, 5) * Box(30, 30, 20, align=MIN)
    if radius is not None:
        cutter = cutter.fillet(radius, cutter.edges().filter_by(Axis.Z))
        if floor:
            cutter = cutter.fillet(floor_radius or radius, cutter.edges().group_by(Axis.Z)[0])
    return Box(40, 40, 20, align=MIN) - cutter


def fillet_collision(bore: bool = True):
    """R02 §5.2: a 40 x 20 x 10 block with R3 vertical corners and a Ø6 bore: all five
    cylinders have radius 3. Without the bore, the missing-feature case (R02 F1)."""
    from build123d import Axis
    block = Box(40, 20, 10)
    block = block.fillet(3, block.edges().filter_by(Axis.Z))
    return block - Cylinder(3, 12) if bore else block


def scaled_tube(factor: float = 1.0, at: tuple = (0.0, 0.0, 0.0)):
    """The tube scaled about its centre and placed at `at` (mass and position mutants)."""
    return Pos(*at) * tube(30.0 * factor, 24.0 * factor, 20.0 * factor)


def solid_rod():
    """The tube without its bore (the remove mutant of the mass check)."""
    return Cylinder(15.0, 20.0)


# ------------------------------------------------ measure known-bad cases (the measure review)

def two_holes(diameter: float = 1.6, web: float = 1.19, angle_deg: float = 0.0):
    """Two holes through a 40 x 40 x 4 plate with `web` mm of material between them,
    their line of centres at `angle_deg` from X. Sampled rays missed this web."""
    plate = Box(40, 40, 4, align=MIN)
    step = diameter + web
    a = math.radians(angle_deg)
    for x, y in ((15.0, 15.0), (15.0 + step * math.cos(a), 15.0 + step * math.sin(a))):
        plate -= Pos(x, y, -1) * Cylinder(diameter / 2, 6, align=BASE)
    return plate


def rounded_box(outer: float = 5.0, wall: float = 2.0, inner: float | None = None, web: float | None = None,
                shift: float = 0.0):
    """A 40 x 40 x 20 box with a cavity: `wall` thick, its vertical outer edges rounded
    at `outer` over sharp (or `inner`-rounded) cavity corners. The corner is thinner
    than the walls: outer - (hypot(c, c) + inner), c = outer - wall - inner; with
    inner = outer - wall the rounds are concentric and the corner is as thick as the
    walls. With `web`, two Ø1.6 holes through the floor, their line of centres at 30°
    from X, leave a web that thick between them. `shift` moves the cavity toward +X."""
    from build123d import Axis
    body = Box(40, 40, 20, align=MIN)
    body = body.fillet(outer, body.edges().filter_by(Axis.Z))
    cavity = Pos(wall + shift, wall, wall) * Box(40 - 2 * wall, 40 - 2 * wall, 20, align=MIN)
    if inner:
        cavity = cavity.fillet(inner, cavity.edges().filter_by(Axis.Z))
    body -= cavity
    if web is not None:
        step, a = 1.6 + web, math.radians(30.0)
        for x, y in ((15.0, 15.0), (15.0 + step * math.cos(a), 15.0 + step * math.sin(a))):
            body -= Pos(x, y, -1) * Cylinder(0.8, wall + 2, align=BASE)
    return body


def blind_bore(bottom: str = "flat", radius: float = 3.0, depth: float = 10.0, floor: float | None = None,
               at: tuple = (20.0, 20.0), turned: bool = False):
    """A blind bore in a 40 x 40 x 20 block, from the top at `at`: `bottom` flat, ball,
    or a drill point of "118", "60", or "140" degrees; with `floor`, the block is only
    that much thicker than the bore's lowest point (a thin floor). `turned` builds the
    drill point upside down and turns it over, which puts its apex at the other end
    of the cone's parameter range."""
    from build123d import Cone, Rot, Sphere
    x, y = at
    tip = radius / math.tan(math.radians(float(bottom) / 2)) if bottom in ("118", "60", "140") else 0.0
    height = depth + tip + floor if floor is not None else 20.0
    top = height
    part = Box(40, 40, height, align=MIN) - Pos(x, y, top - depth) * Cylinder(radius, depth + 1, align=BASE)
    if bottom == "ball":
        part -= Pos(x, y, top - depth) * Sphere(radius)
    elif tip and turned:
        part -= Pos(x, y, top - depth) * Rot(180, 0, 0) * Cone(radius, 0, tip, align=BASE)
    elif tip:
        part -= Pos(x, y, top - depth - tip) * Cone(0, radius, tip, align=BASE)
    return part


def countersunk_plate(hole: float = 5.5, head: float = 11.0, split: bool = False):
    """A Ø`hole` hole through an 8 mm plate under a 90° countersink Ø`head` at the top;
    with `split`, the cone cut in two halves along the axis, as some STEP writers
    store it. A countersink has no inside corner."""
    from build123d import Compound, Cone
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepFeat import BRepFeat_SplitShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    from pocad._ocp import downcast
    sink = (head - hole) / 2
    plate = Box(40, 40, 8, align=MIN) - Pos(20, 20, -1) * Cylinder(hole / 2, 10, align=BASE)
    plate -= Pos(20, 20, 8 - sink) * Cone(hole / 2, head / 2 + 1, sink + 1, align=BASE)
    if not split:
        return plate
    splitter = BRepFeat_SplitShape(plate.wrapped)
    for face in plate.faces():
        if face.geom_type.name == "CONE":
            section = BRepAlgoAPI_Section(face.wrapped, gp_Pln(gp_Pnt(20, 20, 0), gp_Dir(1, 0, 0)))
            section.Build()
            edges = TopExp_Explorer(section.Shape(), TopAbs_EDGE)
            while edges.More():
                splitter.Add(downcast.Edge(edges.Current()), face.wrapped)
                edges.Next()
    splitter.Build()
    return Compound(splitter.Shape())


def counterbored_plate(small: float = 5.5, big: float = 10.0, depth: float = 4.0):
    """A Ø`small` hole through an 8 mm plate under a Ø`big` counterbore `depth` deep."""
    plate = Box(40, 40, 8, align=MIN) - Pos(20, 20, -1) * Cylinder(small / 2, 10, align=BASE)
    return plate - Pos(20, 20, 8 - depth) * Cylinder(big / 2, depth + 1, align=BASE)


def round_pocket(radius: float = 8.0, floor_fillet: float = 0.5):
    """A round pocket 15 deep in a 40 x 40 x 20 block, its floor edge filleted: the
    fillet is a torus."""
    from build123d import Axis
    cutter = Pos(20, 20, 5) * Cylinder(radius, 20, align=BASE)
    cutter = cutter.fillet(floor_fillet, cutter.edges().group_by(Axis.Z)[0])
    return Box(40, 40, 20, align=MIN) - cutter


# ------------------------------------------------ measure known-bad cases (the second measure review)

def comb(tooth: float = 1.0, gap: float = 0.5, teeth: int = 6, height: float = 10.0):
    """Teeth `tooth` thick standing `gap` apart on a 5 mm base: the chord across a gap
    runs through air, and without its checks the exact wall pass read the gap."""
    body = Box(teeth * (tooth + gap) + gap, 10, 5, align=MIN)
    for i in range(teeth):
        body += Pos(gap + i * (tooth + gap), 0, 5) * Box(tooth, 10, height, align=MIN)
    return body


def zneck(overlap: float = 1.0, column: float = 0.5):
    """A 2 mm plate and a higher one joined by a column `column` wide, overlapping
    `overlap` in height: the chord between the two re-entrant corners runs through
    material, far from both faces' normals (not a wall at 25°, oguz-atolye U-17)."""
    left = Box(10, 10, 2, align=MIN)
    col = Pos(10, 0, 0) * Box(column, 10, 5, align=MIN)
    right = Pos(10 + column, 0, 2 - overlap) * Box(10, 10, 3 + overlap, align=MIN)
    return left + col + right


def large_box(thin: float = 0.8, wall: float = 1.5):
    """A 600 x 300 x 200 box open at the top, walls `wall` thick and the +X wall
    `thin`: large enough that single-precision rays start on their own triangle."""
    cavity = Pos(wall, wall, wall) * Box(600 - wall - thin, 300 - 2 * wall, 200, align=MIN)
    return Box(600, 300, 200, align=MIN) - cavity


def nurbs(shape):
    """The shape with every face converted to a B-spline, as a STEP from a
    NURBS-only system arrives."""
    from build123d import Solid
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    return Solid(BRepBuilderAPI_NurbsConvert(shape.wrapped, True).Shape())


def holed_pocket_plate():
    """A 40 x 40 x 10 plate with a Ø3 through hole and a 10 x 10 through pocket whose
    corners are R3: its inside corners are 3.0, and the hole is a bore."""
    from build123d import Axis
    cutter = Pos(5, 5, -1) * Box(10, 10, 12, align=MIN)
    cutter = cutter.fillet(3.0, cutter.edges().filter_by(Axis.Z))
    return Box(40, 40, 10, align=MIN) - Pos(30, 30, -1) * Cylinder(1.5, 12, align=BASE) - cutter


def drum_boss(fillet: float = 1.0):
    """A Ø8 boss on a Ø40 drum, its base filleted at `fillet`: OCCT makes the fillet a
    B-spline, concave across and convex around."""
    from build123d import Rot
    part = Rot(90, 0, 0) * Cylinder(20, 40) + Pos(0, 0, 15) * Cylinder(4, 10, align=BASE)
    base = [e for e in part.edges() if e.geom_type.name not in ("LINE", "CIRCLE") and 17 < e.center().Z < 21]
    return part.fillet(fillet, base)


def rim_round_tube(fillet: float = 0.5):
    """A tube with a radial Ø4 hole whose outer rim is rounded at `fillet`: a B-spline
    saddle, convex across and concave around. The part has no inside corner."""
    from build123d import Rot
    part = Cylinder(15, 30) - Cylinder(12, 32) - Rot(0, 90, 0) * Cylinder(2, 40, align=BASE)
    rim = max((e for e in part.edges() if e.geom_type.name != "LINE"), key=lambda e: e.center().X)
    return part.fillet(fillet, [rim])


def loft_hole():
    """A block with a lofted through hole, a Ø20 circle at the bottom to a 24 x 10
    ellipse at the top: its tightest curvature is 25/12 mm, at the ellipse's ends."""
    from build123d import Circle, Ellipse, Plane, loft
    hole = loft([Plane.XY.offset(-0.001) * Circle(10), Plane.XY.offset(20.001) * Ellipse(12, 5)])
    return Box(40, 40, 20, align=MIN) - Pos(20, 20, 0) * hole


def drafted_pocket(corner: float | None = 0.5, draft_deg: float = 3.0):
    """A 20 x 20 pocket 15 deep in a 40 x 40 x 20 block, its walls drafted and its
    corners `corner` at the floor, widening upward: the corners are cones or B-splines,
    or sharp edges leaning off the vertical when corner is None."""
    from build123d import Plane, Rectangle, RectangleRounded, loft
    grow = 16 * math.tan(math.radians(draft_deg))
    size = 20 + 2 * grow
    if corner is None:
        profiles = [Plane.XY.offset(5) * Rectangle(20, 20), Plane.XY.offset(21) * Rectangle(size, size)]
    else:
        profiles = [Plane.XY.offset(5) * RectangleRounded(20, 20, corner),
                    Plane.XY.offset(21) * RectangleRounded(size, size, corner + grow)]
    cutter = loft(profiles, ruled=True)
    return Box(40, 40, 20, align=MIN) - Pos(20, 20, 0) * cutter


# ------------------------------------------------ measure known-bad cases (the check of the second round)

def split_closed(shape, pieces: int = 2):
    """The shape with every closed face (a whole cylinder, cone, or torus) split into
    `pieces` along its seam direction, as some STEP writers store them."""
    from build123d import Solid
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed
    divide = ShapeUpgrade_ShapeDivideClosed(shape.wrapped)
    divide.SetNbSplitPoints(pieces - 1)
    divide.Perform()
    return Solid(divide.Result())


def fitted_hole_plate(points: int = 24, noise: float = 0.0, seed: int = 1):
    """holed_pocket_plate with its Ø3 hole a B-spline fitted through `points` points on
    the circle, as a reverse-engineered STEP holds it: round to about 3e-4 mm at 24
    points, while its curvature ripples by a few per cent. With `noise`, each point
    moves radially by up to that much, as on a scan."""
    import numpy as np
    from build123d import Axis, Spline, loft, make_face
    radial = 1.5 + np.random.default_rng(seed).uniform(-noise, noise, points)
    rings = []
    for z in (0.0, 12.0):
        ring = [(float(radial[k]) * math.cos(2 * math.pi * k / points),
                 float(radial[k]) * math.sin(2 * math.pi * k / points), z) for k in range(points)]
        rings.append(make_face(Spline(*ring, periodic=True)))
    cutter = Pos(5, 5, -1) * Box(10, 10, 12, align=MIN)
    cutter = cutter.fillet(3.0, cutter.edges().filter_by(Axis.Z))
    return Box(40, 40, 10, align=MIN) - Pos(30, 30, -1) * loft(rings, ruled=True) - cutter


def ring_channel(major: float = 10.0, minor: float = 2.0):
    """A Ø`2 x minor` ring channel inside a 40 x 40 x 10 block: a bent bore, a torus round
    its whole tube, with no inside corner."""
    from build123d import Torus
    return Box(40, 40, 10, align=MIN) - Pos(20, 20, 5) * Torus(major, minor)


def two_wedges(gap: float = 1.0, span: float = 4.0, slope_deg: float = 30.0):
    """Two 30° wedges hanging from a 10 mm back wall, `gap` of air between their sloped
    faces. No wall lies in them at 25°: the thinnest is the back wall. The 6 mm chord
    from their bottom face to their top face runs along the back wall's face across
    the mouth of the gap."""
    from build123d import Polyline, extrude, make_face

    def wedge(points):
        profile = make_face(Polyline(*[(x, 0, z) for x, z in points], close=True))
        return extrude(profile, amount=20.0, dir=(0, 1, 0))

    k = math.tan(math.radians(slope_deg))
    lower = wedge([(0, 0), (span, 0), (span, 1 + k * span), (0, 1)])
    upper = wedge([(0, 1 + gap), (span, 1 + gap + k * span), (span, 6), (0, 6)])
    return Pos(-10, 0, -3) * Box(10, 20, 12, align=MIN) + lower + upper


def dimpled(n: int = 6, radius: float = 3.0, depth: float = 0.5):
    """A 100 x 100 x 50 block with n x n shallow spherical dimples on top: no two dimples
    can hold a wall between them, and every wall is thick."""
    from build123d import Sphere
    pitch = 100.0 / n
    cutters = None
    for i in range(n):
        for j in range(n):
            s = Pos(pitch * (i + 0.5), pitch * (j + 0.5), 50 + radius - depth) * Sphere(radius)
            cutters = s if cutters is None else cutters + s
    return Box(100, 100, 50, align=MIN) - cutters


def loft_wall():
    """A thin lofted shell, a Ø20 circle to a 24 x 12 ellipse outside and a Ø18 circle
    to a 22 x 10 ellipse inside: its outer face is so steep that a ray from the top
    face near its edge meets it about 2° off tangent."""
    from build123d import Circle, Ellipse, Plane, loft
    outer = loft([Plane.XY * Circle(10), Plane.XY.offset(20) * Ellipse(12, 6)])
    inner = loft([Plane.XY.offset(-1) * Circle(9), Plane.XY.offset(21) * Ellipse(11, 5)])
    return outer - inner


PROFILES = {"bulge": [(5, 0), (20, 3), (5, 6), (5, 12), (5, 20)],
            "wave": [(5, 0), (9, 2), (5, 4), (9, 6), (5, 8), (9, 10), (5, 12), (9, 14), (5, 20)],
            "ripple": [(6 + 0.3 * math.sin(2 * math.pi * 64 * t / 640), 20 * t / 640) for t in range(641)],
            "knurl": [(6 + 1.0 * math.sin(2 * math.pi * 16 * t / 320), 20 * t / 320) for t in range(321)]}


def revolved(profile: str = "bulge"):
    """A solid of revolution with a spline profile 20 tall. "bulge" swells from R5 to
    R20 near its base: it runs four times faster there than at the iso lines through
    the middle, and fastest of all at its edge. "wave" ripples between R5 and R9 and
    runs fastest between the nodes where a grid's speed is measured. "ripple" and
    "knurl" carry 64 waves of 0.3 mm and 16 of 1 mm, more than a fixed grid of
    nodes can see."""
    from build123d import Axis, Line, Spline, make_face, revolve
    points = PROFILES[profile]
    (x0, z0), (x1, z1) = points[0], points[-1]
    edges = [Spline(*[(x, 0, z) for x, z in points]).edges()[0], Line((x1, 0, z1), (0, 0, z1)),
             Line((0, 0, z1), (0, 0, z0)), Line((0, 0, z0), (x0, 0, z0))]
    return revolve(make_face(edges), Axis.Z, 360)


def sewn_loose(part, jitter: float = 2e-4, seed: int = 0):
    """The part with each face moved along its normal by up to `jitter` mm and sewn
    back, as a STEP from another system often arrives: edge tolerances of a few
    1e-4 mm, and still valid."""
    import numpy as np
    from build123d import Solid
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing, BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.ShapeFix import ShapeFix_Solid

    from pocad._ocp import downcast
    rng = np.random.default_rng(seed)
    sewing = BRepBuilderAPI_Sewing(10 * jitter)
    for face in part.faces():
        n = face.normal_at()
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*(float(x) * float(rng.uniform(-jitter, jitter)) for x in (n.X, n.Y, n.Z))))
        sewing.Add(BRepBuilderAPI_Transform(face.wrapped, move, True).Shape())
    sewing.Perform()
    fix = ShapeFix_Solid(BRepBuilderAPI_MakeSolid(downcast.Shell(sewing.SewedShape())).Solid())
    fix.Perform()
    return Solid(fix.Solid())


def tapered_fin(included_deg: float = 40.0, tip: float = 0.3, height: float = 10.0):
    """A 20 x 20 x 10 block with a fin on top whose flanks are `included_deg` apart and
    meet a flat top `tip` wide: a wall at 25° only when the flanks are less than 25°
    apart, at 45° when less than 45°."""
    from build123d import Polyline, extrude, make_face
    half = height * math.tan(math.radians(included_deg / 2))
    outline = [(10 - tip / 2 - half, 10), (10 + tip / 2 + half, 10), (10 + tip / 2, 10 + height),
               (10 - tip / 2, 10 + height)]
    fin = extrude(make_face(Polyline(*[(x, 0, z) for x, z in outline], close=True)), amount=20.0, dir=(0, 1, 0))
    return Box(20, 20, 10, align=MIN) + fin


# ------------------------------------------------ contact and radial probes (L-22, L-09)

def contact_pair(width: float = 20.0, gap: float = 0.0, shift: float = 0.0, near: float | None = None):
    """A 10 x 20 x 10 block and a 10 x `width` x 10 block beside it along +X, `gap`
    apart (negative overlaps) and slid `shift` along +Y: at gap 0 they share a
    10 x 20 face, 200 mm², and no volume. With `near`, the block carries a tab on
    top, 12 x 3 x 10, lying on the cover, and the cover a step whose face stands
    `near` mm off the tab's 3 x 10 end along +X: a 30 mm² face that does not touch."""
    a = Box(10, 20, 10, align=MIN)
    b = Pos(10 + gap, shift, 0) * Box(10, width, 10, align=MIN)
    if near is not None:
        a += Pos(0, 0, 10) * Box(12, 3, 10, align=MIN)
        b += Pos(12 + near, 0, 10) * Box(8 + gap - near, 20, 10, align=MIN)
    a.label, b.label = "block", "cover"
    return a, b


def _revolved(points):
    from build123d import Axis, Polyline, make_face, revolve
    return revolve(make_face(Polyline(*[(r, 0, z) for r, z in points], close=True)), Axis.Z, 360)


def bead_in_groove(bead: float = 11.0, lift: float = 0.0, bore: float = 10.2):
    """A Ø20 shaft with an annular bead whose lower flank, a 45° cone, rests on the
    matching lower flank of a groove in a housing with a Ø`2 x bore` bore. The flanks
    touch from the bore's radius to the bead's (`bead`), so pushed down the axis the
    shaft bears on π(bead² - bore²) mm²: 53.28 mm² as built. `lift` raises the shaft
    off the flank. Returns (shaft, housing)."""
    shaft = _revolved([(0, 0), (10, 0), (10, 4), (bead, bead - 6), (bead, 6), (10, 17 - bead),
                       (10, 12), (0, 12)])
    housing = _revolved([(bore, 0), (15, 0), (15, 12), (bore, 12), (bore, 18.5 - bore), (11.5, 7),
                         (11.5, 5.5), (bore, bore - 6)])
    return Pos(0, 0, lift) * shaft, housing


RING = {"outer": 20.0, "inner": 16.0, "height": 12.0, "relief": 19.6, "groove": 19.5,
        "groove_band": (8.0, 10.0)}


def relieved_ring(relief: float = 19.6, relief_from: float = -1.0, turn_deg: float = 0.0,
                  sectors: int = 3, width_deg: float = 40.0):
    """A snap-fit shell reduced to a ring: R20 outside, R16 inside, 12
    tall with its rim at z = 0, and a groove R19.5 at z 8 to 10 where the bead locks.
    `sectors` release reliefs `width_deg` wide, centred at `turn_deg` + k·360/sectors,
    cut the outside down to R`relief` from `relief_from` up into the groove: from
    below the rim (-1) they span the whole extraction stroke; from 3 they stop 3 mm
    short of the rim (a known snap-fit defect)."""
    from build123d import Polyline, Rot, extrude, make_face
    ring = _revolved([(RING["inner"], 0), (RING["outer"], 0), (RING["outer"], 8), (RING["groove"], 8),
                      (RING["groove"], 10), (RING["outer"], 10), (RING["outer"], 12),
                      (RING["inner"], 12)])
    half = math.radians(width_deg / 2)
    slice_ = [(0.0, 0.0), (25 * math.cos(half), -25 * math.sin(half)), (25 / math.cos(half), 0.0),
              (25 * math.cos(half), 25 * math.sin(half))]
    pie = extrude(make_face(Polyline(*[(x, y, relief_from) for x, y in slice_], close=True)),
                  amount=9.0 - relief_from)
    cutter = pie - Pos(0, 0, relief_from - 1) * Cylinder(relief, 12 - relief_from, align=BASE)
    for k in range(sectors):
        ring -= Rot(0, 0, turn_deg + k * 360.0 / sectors) * cutter
    return ring


def tube_with_pin(pin: float = 7.0, bore: float = 16.0, outer: float = 20.0):
    """A tube, bore R`bore` and outside R`outer`, 12 tall, with a pin R`pin` standing
    on the axis inside it as a second solid: a ray from the axis meets the pin first."""
    return Compound(children=[Cylinder(outer, 12, align=BASE) - Cylinder(bore, 14, align=BASE),
                              Cylinder(pin, 12, align=BASE)])


def base_with_bead(tip: float = 45.0, wall: tuple = (38.0, 40.0), ring: tuple = (46.0, 48.0)):
    """A snap-fit base reduced to its profile: a floor 2 thick, an inner wall from
    R38 to R40 and an outer ring from R46 to R48 standing 10 high, the ring carrying
    an inward bead down to R`tip` at z 5 to 7 (45° flanks from z 4 and to z 8). At
    the bead's height a ray from the axis crosses the wall first, then the bead."""
    w0, w1 = wall
    r0, r1 = ring
    lift = r0 - tip
    return _revolved([(w0, 0), (r1, 0), (r1, 12), (r0, 12), (r0, 7 + lift), (tip, 7), (tip, 5),
                      (r0, 5 - lift), (r0, 2), (w1, 2), (w1, 12), (w0, 12)])


# ------------------------------------------------ print checks (GATES D-03a, U-06)

def ledge(slope_deg: float = 50.0, reach: float = 5.0, height: float = 10.0, foot: float | None = None):
    """A 10 x 20 x 20 column standing on the bed (z 0) with a ledge `reach` mm out in
    +X at its top, `height` mm above the bed, whose underside rises out from the column
    at `slope_deg` from horizontal: a chamfered overhang, flat-bottomed at 0°. Built
    along +Z its least overhang is the slope; the bed face reads 0 unless left out.
    With `foot`, a 5 mm block on the -X side whose flat underside is `foot` mm above
    the bed: on it at 0, a 0° ceiling above it, which the bed band must not swallow."""
    from build123d import Polyline, extrude, make_face
    rise = reach * math.tan(math.radians(slope_deg))
    outline = [(0, 0), (10, 0), (10, height), (10 + reach, height + rise), (10 + reach, 20), (0, 20)]
    profile = make_face(Polyline(*[(x, 0, z) for x, z in outline], close=True))
    part = extrude(profile, amount=20.0, dir=(0, 1, 0))
    if foot is not None:
        part += Pos(-5, 0, foot) * Box(5, 20, 20 - foot, align=MIN)
    return part


def tilted_hole(radius: float = 0.5, tilt_deg: float = 42.0):
    """A 20 mm cube with a through hole of `radius`, its axis `tilt_deg` from
    horizontal: its crown faces down at `tilt_deg`. A 0.5 mm grid on a small hole
    steps 45° round it and read R0.5 at 42° as 46.64, a pass."""
    from build123d import Rot
    return Box(20, 20, 20) - Rot(0, 90 - tilt_deg, 0) * Cylinder(radius, 40)


def standing_cone(slope_deg: float = 45.0, radius: float = 10.0):
    """A cone standing on its point, its side `slope_deg` from horizontal: an overhang
    all round, and a curved one, whose least angle is the slope."""
    from build123d import Cone
    return Cone(0.0, radius, radius * math.tan(math.radians(slope_deg)), align=BASE)


# ------------------------------------------------ bridges, keep-in envelopes, retained bands (GATES D-03b)

def tunnel(width: float = 4.0, height: float = 4.0, shift: float = 0.0):
    """A 20 x 20 x 10 block on the bed with a tunnel `width` wide and `height` high
    through it along Y from the bed: its flat ceiling is carried by the tunnel's two
    walls, a bridge `width` across. The ceiling's ends open onto the block's faces,
    which carry nothing. `shift` moves the tunnel along +X: at 8 its right wall is
    gone and the ceiling is carried on one side only."""
    return Box(20, 20, 10, align=MIN) - Pos(10 - width / 2 + shift, -1, -1) * Box(width, 22, height + 1, align=MIN)


def stepped_bore(big: float = 8.0, small: float = 4.0, step: float = 3.0, top: float = 6.0):
    """A 20 x 20 x 10 block on the bed with a Ø`big` bore from the bed up to `step`,
    and a Ø`small` bore on up to `top`: two flat ceilings. The small bore's round
    top is carried all round by its wall, a bridge of its diameter; the annulus at
    the step is carried only at its outside (the small bore's wall rises from its
    inside), twice its (big - small) / 2 reach."""
    block = Box(20, 20, 10, align=MIN)
    block -= Pos(10, 10, -1) * Cylinder(big / 2, step + 1, align=BASE)
    return block - Pos(10, 10, -1) * Cylinder(small / 2, top + 1, align=BASE)


KEEPIN = {"slope": math.sqrt(2.0), "apex_t": 16.330, "back": 0.75}      # r(t) <= √2·(16.330 - t) - 0.75


def keepin_radius(t: float, clear: float = 0.0) -> float:
    """The keep-in cone's radius at depth t below the face plane (z = -t), less `clear`."""
    return KEEPIN["slope"] * (KEEPIN["apex_t"] - t) - KEEPIN["back"] - clear


def keepin_plug(clear: float = 0.5, t0: float = 6.0, t1: float = 14.0):
    """A plug standing inside the keep-in cone r(t) <= √2·(16.330 - t) - 0.75, t = -z,
    from depth t0 to t1: a cone `clear` inside the envelope all along its side (a
    negative clear stands outside it)."""
    return _revolved([(0, -t1), (keepin_radius(t1, clear), -t1), (keepin_radius(t0, clear), -t0), (0, -t0)])


def keepin_socket(clear: float = 0.5, t0: float = 4.0, t1: float = 14.0, filled: bool = False):
    """A 40 x 40 block from depth t0 - 1 to t1 + 1 with a conical cavity `clear` outside
    the keep-in cone from t0 to t1, a bore above it and a floor below both out of that
    range. `filled` leaves the cavity out: the envelope is then solid material, with
    no surface inside it."""
    block = Pos(0, 0, -t1 - 1) * Box(40, 40, t1 - t0 + 2, align=BASE)
    if filled:
        return block
    r0, r1 = keepin_radius(t0, -clear), keepin_radius(t1, -clear)
    return block - _revolved([(0, -t1 - 0.5), (r1, -t1 - 0.5), (r1, -t1), (r0, -t0), (r0, -t0 + 2), (0, -t0 + 2)])


def slotted_collar(slots: int = 3, width: float = 3.0, depth: float = 6.0, tilt_deg: float = 0.0,
                   hole: float | None = None):
    """A collar R12 outside with an R8 bore, 10 tall on z = 0, and `slots` entry slots
    `width` wide cut down from its top `depth` deep, the first on +Y, tilted
    `tilt_deg` about their own radial line. Each straight slot takes 2·asin(w/16) of
    the bore: three 3 mm slots leave 295.158°. With `hole`, a Ø`hole` radial hole
    through both walls at z = 5 instead, widest at its own centre height."""
    from build123d import Rot
    part = Cylinder(12, 10, align=BASE) - Cylinder(8, 12, align=BASE)
    if hole is not None:
        return part - Pos(0, 0, 5) * Rot(0, 90, 0) * Cylinder(hole / 2, 30)
    for k in range(slots):
        cutter = Rot(tilt_deg, 0, 0) * Box(6, width, 2 * depth)
        part -= Rot(0, 0, 90 + k * 360 / slots) * Pos(10, 0, 10) * cutter
    return part


# ------------------------------------------------ bridge known-bad cases (the review of the second harvest)

def tunnel_rib(rib: float = 0.05):
    """tunnel(10.0) with a rib `rib` wide standing from the bed to its ceiling all along
    its middle: thinner than a printable wall, it carries nothing, and the ceiling still
    spans 10 mm."""
    return tunnel(10.0) + Pos(10 - rib / 2, 0, 0) * Box(rib, 20, 4.0, align=MIN)


def tunnel_curtain(curtain: float = 0.5, gap: float = 1.0):
    """tunnel(10.0) with a curtain `curtain` thick hanging from the middle of its ceiling
    all along it and ending in a 45° V `gap` mm short of the bed: it never reaches the
    bed, so it carries nothing."""
    from build123d import Polyline, extrude, make_face
    half = curtain / 2
    outline = [(10 - half, 4.0), (10 + half, 4.0), (10 + half, gap + half), (10, gap), (10 - half, gap + half)]
    profile = make_face(Polyline(*[(x, 0, z) for x, z in outline], close=True))
    return tunnel(10.0) + extrude(profile, amount=20.0, dir=(0, 1, 0))


def tunnel_post(post: float = 0.05, plate: float = 3.0, thick: float = 0.5):
    """tunnel(10.0) with a `plate` x `plate` x `thick` plate under the middle of its
    ceiling, standing on a Ø`post` post from the bed: the plate's sides would carry the
    ceiling, but the plate itself is carried by nothing that prints."""
    plate_ = Pos(10 - plate / 2, 10 - plate / 2, 4.0 - thick) * Box(plate, plate, thick, align=MIN)
    return tunnel(10.0) + plate_ + Pos(10, 10, 0) * Cylinder(post / 2, 4.0 - thick, align=BASE)


def comb_ceiling(arm: float = 1.5, gap: float = 0.25, length: float = 16.0):
    """tunnel(4.0) whose roof is cut through by a U of slits `gap` wide round a tongue
    `arm` wide down its middle, `length` long and attached only at its root (y 18): the
    tongue's tip is 2 mm from a wall in a straight line, through the slit, and about 18
    mm going within the ceiling round by its root."""
    part = tunnel(4.0)
    left, right = 10 - arm / 2, 10 + arm / 2
    top = 18.0
    for x0, width in ((left - gap, gap), (right, gap)):
        part -= Pos(x0, top - length - gap, 3.0) * Box(width, length + gap, 8.0, align=MIN)
    return part - Pos(left - gap, top - length - gap, 3.0) * Box(arm + 2 * gap, gap, 8.0, align=MIN)
