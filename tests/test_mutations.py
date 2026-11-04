# kaynak: oguz-atolye tools/tests/test_mutations.py @ca27b1b (MIT, PoCAD'e taşındı)
"""oguz-atolye U-19: every check against one mutant from each of four families.

mutations/MANIFEST.json says, for each check, whether each family's mutant is
KILLED, INCONCLUSIVE, or SURVIVED (with the blind spot named); this file proves
every row. A check that no family kills must be proved able to fail elsewhere:
PROVED_ELSEWHERE names the known-bad test that makes it FAIL (D-010). The manifest
covers every check the code offers: every name registered by @measurement in
pocad.core and pocad.measure (drawing and package checks come back with those
modules), and every result of the
STEP round trip.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

pytestmark = pytest.mark.cad
pytest.importorskip("build123d")
pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister")
pytest.importorskip("trimesh")

import trimesh
from build123d import Box, Pos, export_step
from fixtures import parts

from pocad import core, measure
from pocad.core import step as core_step
from pocad.core.shapes import quiet
from pocad.result import FAIL, INCONCLUSIVE, MEASUREMENTS, PASS, Result, gate

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "mutations" / "MANIFEST.json").read_text(encoding="utf-8"))
FAMILIES = ("resize", "relocate", "remove", "degrade")
OUTCOME = {PASS: "SURVIVED", FAIL: "KILLED", INCONCLUSIVE: "INCONCLUSIVE"}
PROVED_ELSEWHERE = {
    "brep_valid": "test_core.py::test_a_solid_that_overlaps_itself_fails_only_the_analyzer_stage",
    "step_roundtrip_volume_delta": "test_core.py::test_the_round_trip_fails_when_the_file_comes_back_different",
    "step_roundtrip_faces_delta": "test_core.py::test_the_round_trip_fails_when_the_file_comes_back_different",
    "step_roundtrip_valid": "test_core.py::test_the_round_trip_fails_when_the_file_comes_back_invalid",
    "step_roundtrip_labels": "test_core.py::test_an_unnamed_part_in_an_assembly_fails_the_label_check",
}
CODE_PREFIXES = ("pocad.core", "pocad.measure")
NEEDS_EMBREE = {"min_wall_mesh"}          # INCONCLUSIVE where embreex has no wheel
STAMP = "2026-09-20T00:00:00"


def through_ap214(shape, folder: Path, name: str):
    """The degrade family: the geometry travels through build123d's own AP214 writer."""
    path = folder / f"{name}_ap214.step"
    with quiet():
        export_step(shape, str(path))
    return core.read_step(path), path


def part(variant: str, folder: Path):
    if variant == "resize":
        return parts.bracket(thickness=1.0)
    if variant == "relocate":
        return parts.bracket(boss_lift=1.0)
    if variant == "remove":
        return parts.without_top_face(parts.bracket())
    if variant == "degrade":
        return through_ap214(parts.bracket(), folder, "bracket")[0]
    return parts.bracket()


def roundtrip(variant: str, folder: Path) -> dict[str, Result]:
    """The round trip of the part, or for the degrade family the AP214 file from
    build123d's writer compared with the part it came from."""
    if variant == "degrade":
        return core.compare_step(parts.bracket(), through_ap214(parts.bracket(), folder, "bracket")[1])
    return core.step_roundtrip(part(variant, folder), folder / f"{variant}.step", timestamp=STAMP)


def status(result: Result, op: str, limit, band: float = 0.0) -> str:
    return gate("M", result, op, limit, band=band).status


def check_solid_count(variant, folder):
    return status(core.solid_count(part(variant, folder)), "==", 1)


def check_brep_valid(variant, folder):
    return status(core.brep_valid(part(variant, folder)), "==", 1)


def check_naked_edges(variant, folder):
    return status(core.naked_edges(part(variant, folder)), "==", 0)


def check_step_schema(variant, folder):
    return status(roundtrip(variant, folder)["schema"], "==", 1)


def check_step_roundtrip_solids(variant, folder):
    return status(roundtrip(variant, folder)["solids"], "==", 1)


def check_step_roundtrip_volume_delta(variant, folder):
    return status(roundtrip(variant, folder)["volume_delta"], "<=", 0.0, band=1e-6)


def check_step_roundtrip_faces_delta(variant, folder):
    return status(roundtrip(variant, folder)["faces_delta"], "==", 0)


def check_step_roundtrip_labels(variant, folder):
    return status(roundtrip(variant, folder)["labels"], "==", 1)


def check_step_roundtrip_valid(variant, folder):
    return status(roundtrip(variant, folder)["valid_after"], "==", 1)


def check_stl_max_sagitta(variant, folder):
    coarse = variant == "degrade"
    shape = parts.bracket() if coarse else part(variant, folder)
    written = core.write_stl(shape, folder / f"{variant}.stl", tolerance=0.5 if coarse else 0.01,
                             angular_tolerance=0.8 if coarse else 0.1)
    return status(written.checks["max_sagitta"], "<=", 0.01, band=1e-9)


def check_common_volume(variant, folder):
    if variant == "resize":
        a, b = parts.pair(grow=0.5)
    elif variant == "relocate":
        a, b = parts.pair(gap=0.3 - 0.5)
    elif variant == "remove":
        a, b = parts.pair()[0], parts.open_box()
    elif variant == "degrade":
        a, b = (through_ap214(x, folder, n)[0] for x, n in zip(parts.pair(), ("base", "cover")))
    else:
        a, b = parts.pair()
    return status(core.common_volume(a, b), "<=", 0.0, band=1e-6)


# --------------------------------------------------------------------- measure
# Each check below builds its base fixture and the four mutants from the generators
# in fixtures/parts.py; the manifest row says which is which. The limits are test
# limits chosen so the base passes, not GATES values (D-009).

def every(*statuses: str) -> str:
    """One status for a gate on several values: FAIL when any fails (the rest cannot
    save it), else INCONCLUSIVE when any is, else PASS."""
    return next((s for s in (FAIL, INCONCLUSIVE) if s in statuses), PASS)


def mutant(variant, folder, base, mutants: dict, name: str):
    """The base fixture, the family's mutant, or for degrade the base through AP214."""
    if variant == "degrade" and "degrade" not in mutants:
        return through_ap214(base(), folder, name)[0]
    return mutants[variant]() if variant in mutants else base()


def stl(shape, folder, name, tolerance=0.01, angular=0.1):
    return core.write_stl(shape, folder / f"{name}.stl", tolerance=tolerance, angular_tolerance=angular).path


TRAY = {"resize": lambda: parts.tray(wall=1.1), "relocate": lambda: parts.tray(shift=1.9),
        "remove": lambda: parts.tray(open_side=True)}


def check_min_wall(variant, folder):
    shape = mutant(variant, folder, parts.tray, TRAY, "tray")
    return status(measure.min_wall(shape, spacing=1.0), ">=", 1.2, band=1e-6)     # flat walls: exact


def check_min_wall_mesh(variant, folder):
    shape = parts.tray() if variant in ("base", "degrade") else TRAY[variant]()
    coarse = variant == "degrade"
    path = stl(shape, folder, variant, 0.5 if coarse else 0.01, 0.8 if coarse else 0.1)
    return status(measure.min_wall_mesh(path), ">=", 1.2, band=1e-6)


ROUNDED = {"resize": lambda: parts.rounded_box(5.0, 2.0, inner=1.0),
           "relocate": lambda: parts.rounded_box(5.0, 2.0, inner=3.0, shift=0.8),
           "remove": lambda: parts.rounded_box(5.0, 2.0)}


def check_min_wall_wide(variant, folder):
    shape = mutant(variant, folder, lambda: parts.rounded_box(5.0, 2.0, inner=3.0), ROUNDED, "rounded")
    return status(measure.min_wall_wide(shape, spacing=1.0), ">=", 1.5, band=1e-6)


def check_mesh_census(variant, folder):
    shape = {"resize": lambda: parts.bracket(thickness=1.0), "relocate": lambda: parts.bracket(boss_lift=1.0),
             "remove": lambda: parts.without_top_face(parts.bracket())}.get(variant, parts.bracket)()
    coarse = variant == "degrade"
    census = measure.mesh_census(stl(shape, folder, variant, 0.5 if coarse else 0.01, 0.8 if coarse else 0.1))
    return every(status(census["bodies"], "==", 1), status(census["naked_edges"], "==", 0),
                 status(census["winding"], "==", 1), status(census["volume"], ">=", 1e-9))


def check_mesh_deviation(variant, folder):
    shape = {"resize": lambda: parts.tube(od=30.5), "relocate": lambda: Pos(0.5, 0, 0) * parts.tube(),
             "remove": lambda: parts.without_top_face(parts.tube())}.get(variant, parts.tube)()
    coarse = variant == "degrade"
    path = stl(shape, folder, variant, 0.5 if coarse else 0.01, 0.8 if coarse else 0.1)
    return status(measure.mesh_deviation(path, parts.tube()), "<=", 0.011, band=1e-6)


PLATE = {"resize": lambda: parts.holed_plate(big=5.4), "relocate": lambda: parts.holed_plate(shift=0.5)}


def check_bore_census(variant, folder):
    plate = mutant(variant, folder, parts.holed_plate, {**PLATE, "remove": lambda: parts.holed_plate(small=False)},
                   "plate")
    return status(measure.bore_census(plate), "==", 3)


def check_locate_bore(variant, folder):
    plate = mutant(variant, folder, parts.holed_plate, {**PLATE, "remove": lambda: parts.holed_plate(big=None)},
                   "plate")
    located = measure.locate_bore(measure.bore_census(plate), (15, 20, 0), (0, 0, 1))
    return every(status(located["diameter"], "==", 5.0, band=1e-6), status(located["offset"], "<=", 0.1, band=1e-6))


def check_feature_census(variant, folder):
    expected = {k: r.measured for k, r in measure.feature_census(parts.holed_plate()).items()}
    plate = mutant(variant, folder, parts.holed_plate, {**PLATE, "remove": lambda: parts.holed_plate(small=False)},
                   "plate")
    census = measure.feature_census(plate)
    return every(*(status(census[k], "==", v) for k, v in expected.items()))


POCKET = {"resize": lambda: parts.pocket(0.8), "relocate": lambda: parts.pocket(1.5, shift=2.0),
          "remove": lambda: parts.pocket(None)}


def check_min_internal_radius(variant, folder):
    shape = mutant(variant, folder, lambda: parts.pocket(1.5), POCKET, "pocket")
    return status(measure.min_internal_radius(shape, axis=(0, 0, 1)), ">=", 1.0, band=1e-6)


def check_sharp_concave_edge_count(variant, folder):
    floor = {"resize": lambda: parts.pocket(0.8, floor=True), "relocate": lambda: parts.pocket(1.5, floor=True, shift=2.0),
             "remove": lambda: parts.pocket(1.5)}
    shape = mutant(variant, folder, lambda: parts.pocket(1.5, floor=True), floor, "pocket")
    return status(measure.sharp_concave_edge_count(shape), "==", 0)


def check_draft_angles(variant, folder):
    boss = {"resize": lambda: parts.drafted_boss(1.0), "relocate": lambda: Pos(5, 0, 0) * parts.drafted_boss(3.0),
            "remove": lambda: parts.drafted_boss(0.0)}
    shape = mutant(variant, folder, lambda: parts.drafted_boss(3.0), boss, "boss")
    return status(measure.draft_angles(shape, (0, 0, 1)), ">=", 1.5, band=1e-6)


def check_undercuts(variant, folder):
    body = lambda: Box(30, 20, 12, align=parts.MIN)                        # the T-slot part's body
    block = {"resize": lambda: Box(30, 20, 6, align=parts.MIN), "relocate": lambda: Pos(5, 0, 0) * body(),
             "remove": parts.undercut_part}
    return status(measure.undercuts(mutant(variant, folder, body, block, "body"), (0, 0, 1)), "==", 0)


def check_overhang_census(variant, folder):
    """The relocate mutant lifts a flat foot 0.5 mm off the bed: it survives any bed
    band of 0.5 mm or more."""
    ledge = {"resize": lambda: parts.ledge(30.0, foot=0.0), "relocate": lambda: parts.ledge(50.0, foot=0.5),
             "remove": lambda: parts.ledge(0.0, foot=0.0)}
    shape = mutant(variant, folder, lambda: parts.ledge(50.0, foot=0.0), ledge, "ledge")
    return status(measure.overhang_census(shape, (0, 0, 1)), ">=", 45.0, band=1e-6)



def check_flat_ceiling_spans(variant, folder):
    """The relocate mutant keeps its 4 mm width and loses a wall: a check that read
    the ceiling's width alone, not what carries it, would pass it."""
    tunnel = {"resize": lambda: parts.tunnel(7.0), "relocate": lambda: parts.tunnel(4.0, shift=8.0),
              "remove": lambda: parts.without_top_face(parts.tunnel(4.0))}
    shape = mutant(variant, folder, parts.tunnel, tunnel, "tunnel")
    return status(measure.flat_ceiling_spans(shape, (0, 0, 1), max_span=5.0), "<=", 5.0, band=1e-6)


KEEPIN_CONE = ((0.0, 0.0, -16.330), (0, 0, 1), math.degrees(math.atan(math.sqrt(2.0))))


def check_keepin_cone_free(variant, folder):
    plug = {"resize": lambda: parts.keepin_plug(-0.3), "relocate": lambda: Pos(1.0, 0, 0) * parts.keepin_plug(0.5),
            "remove": lambda: parts.without_top_face(parts.keepin_plug(0.5))}
    shape = mutant(variant, folder, lambda: parts.keepin_plug(0.5), plug, "plug")
    return status(measure.keepin_cone_free(shape, *KEEPIN_CONE, offset=0.75, s_range=(None, 16.330)), ">=", 0.0,
                  band=1e-6)


def check_retained_arc(variant, folder):
    collar = {"resize": lambda: parts.slotted_collar(width=8.0),
              "relocate": lambda: parts.slotted_collar(tilt_deg=20.0),
              "remove": lambda: parts.without_top_face(parts.slotted_collar())}
    shape = mutant(variant, folder, parts.slotted_collar, collar, "collar")
    result = measure.retained_arc(shape, ((0, 0, 0), (0, 0, 1)), 8.0, (0.0, 10.0), min_total_deg=195.0)
    return status(result, ">=", 195.0, band=1e-6)

def pair_mutant(variant, folder):
    if variant == "resize":
        return parts.pair(grow=0.2)
    if variant == "relocate":
        return parts.pair(gap=0.1)
    if variant == "remove":
        base, cover = parts.pair()
        return base, parts.without_top_face(cover)
    if variant == "degrade":
        return tuple(through_ap214(x, folder, n)[0] for x, n in zip(parts.pair(), ("base", "cover")))
    return parts.pair()


def check_interference(variant, folder):
    overlap = {"resize": lambda: parts.pair(grow=0.5), "relocate": lambda: parts.pair(gap=-0.2)}
    base, cover = overlap[variant]() if variant in overlap else pair_mutant(variant, folder)
    return status(measure.interference({"base": base, "cover": cover})["base|cover"], "<=", 0.0, band=1e-6)


def check_clearance(variant, folder):
    return status(measure.clearance(*pair_mutant(variant, folder)), ">=", 0.25, band=1e-6)


def check_engaged_area(variant, folder):
    """The shaft's bead on the housing's groove flank, pushed down the axis: 53.28 mm²."""
    pairs = {"resize": lambda: parts.bead_in_groove(bead=10.6), "relocate": lambda: parts.bead_in_groove(lift=0.3)}
    if variant == "remove":
        shaft, housing = parts.bead_in_groove()
        housing = parts.without_top_face(housing)
    elif variant == "degrade":
        shaft, housing = (through_ap214(x, folder, n)[0] for x, n in zip(parts.bead_in_groove(), ("shaft", "housing")))
    else:
        shaft, housing = pairs.get(variant, parts.bead_in_groove)()
    return status(measure.engaged_area(shaft, housing, (0, 0, -1), 0.01), ">=", 50.0, band=1e-6)


RING_AXIS = ((0, 0, 0), (0, 0, 1), (1, 0, 0))
RING = {"resize": lambda: parts.relieved_ring(relief=19.8), "relocate": lambda: parts.relieved_ring(turn_deg=30.0),
        "remove": lambda: parts.relieved_ring(relief_from=3.0)}


def check_radial_extent(variant, folder):
    """The wall at a release angle, 1 mm above the rim: inside the relief."""
    ring = mutant(variant, folder, parts.relieved_ring, RING, "ring")
    return status(measure.radial_extent(ring, *RING_AXIS, 0.0, 1.0), "<=", 19.6, band=1e-6)


def check_radial_profile(variant, folder):
    """The wall at the three release angles over the band z 3 to 8, the short
    relief's modelled cut (the base's reliefs are cut from z -1 to 9), widened by
    1 mm (L-22): the relief must hold it at R19.6 from z 2 to 9."""
    ring = mutant(variant, folder, parts.relieved_ring, RING, "ring")
    profile = measure.radial_profile(ring, *RING_AXIS, (0.0, 120.0, 240.0), (3.0, 8.0), margin=1.0, z_step=0.25)
    return status(profile["max"], "<=", 19.6, band=1e-6)


def check_envelope(variant, folder):
    tray = {"resize": lambda: parts.tray(length=41.0), "relocate": lambda: parts.tray(at=(5.0, 0.0, 0.0)),
            "remove": lambda: parts.tray(open_side=True)}
    box = measure.envelope(mutant(variant, folder, parts.tray, tray, "tray"))
    return every(status(box["size_x"], "<=", 40.0, band=1e-6), status(box["min_x"], "==", 0.0, band=1e-6))


def check_mass_properties(variant, folder):
    nominal = measure.mass_properties(parts.tube(), 1240.0)["mass"].measured
    tube = {"resize": lambda: parts.scaled_tube(1.05), "relocate": lambda: parts.scaled_tube(1.0, at=(5.0, 0.0, 0.0)),
            "remove": parts.solid_rod}
    mass = measure.mass_properties(mutant(variant, folder, parts.tube, tube, "tube"), 1240.0)["mass"]
    return status(mass, "in", (0.95 * nominal, 1.05 * nominal))


EVALUATORS = {name[len("check_"):]: fn for name, fn in globals().items() if name.startswith("check_")}
CELLS = [(check, family) for check in sorted(MANIFEST["checks"]) for family in FAMILIES]


def offered_checks() -> dict[str, str]:
    """Every check the code offers, by result name, with its module."""
    offered = {name: module for name, module in MEASUREMENTS.items() if module.startswith(CODE_PREFIXES)}
    offered.update({name: "pocad.core.step" for name, _ in core_step.ROUNDTRIP.values()})
    return offered


def test_the_manifest_covers_every_check_the_code_offers():
    offered = offered_checks()
    assert set(MANIFEST["checks"]) == set(offered) == set(EVALUATORS)
    for name, row in MANIFEST["checks"].items():
        assert row["module"] == offered[name], name


def test_every_row_is_complete_and_every_check_can_fail():
    for name, row in MANIFEST["checks"].items():
        assert row.get("base") and row.get("gate"), f"{name}: the row names its base fixture and gate"
        for family in FAMILIES:
            cell = row[family]
            assert cell.get("mutant"), f"{name}/{family}: the cell names its mutant"
            assert cell["expect"] in ("KILLED", "SURVIVED", "INCONCLUSIVE"), (name, family)
            if cell["expect"] == "SURVIVED":
                assert cell.get("blind_spot"), f"{name}/{family}: a survivor names its blind spot"
        killed = any(row[f]["expect"] != "SURVIVED" for f in FAMILIES)
        assert killed or name in PROVED_ELSEWHERE, f"{name}: nothing proves it can fail"
        assert (name in PROVED_ELSEWHERE) == ("known_bad" in row), f"{name}: known_bad and PROVED_ELSEWHERE differ"
    for proof in PROVED_ELSEWHERE.values():
        file, test = proof.split("::")
        assert f"def {test}(" in (HERE / file).read_text(encoding="utf-8"), proof


def embree_or_skip(check: str) -> None:
    if check in NEEDS_EMBREE and not trimesh.ray.has_embree:
        pytest.skip("embreex has no wheel for this platform")


@pytest.mark.parametrize("check", sorted(EVALUATORS))
def test_every_check_passes_its_base_fixture(check, tmp_path):
    embree_or_skip(check)
    assert EVALUATORS[check]("base", tmp_path) == PASS


@pytest.mark.parametrize("check,family", CELLS, ids=[f"{c}-{f}" for c, f in CELLS])
def test_each_mutant_meets_its_manifest_row(check, family, tmp_path):
    embree_or_skip(check)
    outcome = OUTCOME[EVALUATORS[check](family, tmp_path)]
    assert outcome == MANIFEST["checks"][check][family]["expect"]
