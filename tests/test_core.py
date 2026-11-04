# kaynak: oguz-atolye tools/tests/test_core.py @ca27b1b (MIT, PoCAD'e taşındı)
"""pocad.core: every check with a known-good fixture that must PASS and a known-bad one
that must FAIL (D-010), the INCONCLUSIVE path, and the build123d/OCCT traps the core
exists to avoid (docs/BUILD123D-NOTLARI.md)."""
from __future__ import annotations

import importlib
import re
import struct
import subprocess
import sys

import pytest

pytestmark = pytest.mark.cad
pytest.importorskip("build123d")
pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister")

from build123d import Align, Axis, Box, Compound, Pos, export_step, export_stl
from fixtures import parts
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer

from pocad import core
from pocad.core import boolean as core_boolean
from pocad.core import mesh as core_mesh
from pocad.core import step as core_step
from pocad.core.shapes import quiet
from pocad.result import FAIL, INCONCLUSIVE, PASS, Result, gate

core_validity = importlib.import_module("pocad.core.validity")   # the package re-exports validity()
STAMP = "2026-09-20T00:00:00"


def passes(result, op, limit, band=0.0):
    return gate("G", result, op, limit, band=band).status


# ------------------------------------------------------------------- validity

def test_a_sound_part_passes_all_three_validity_checks():
    checks = core.validity(parts.bracket())
    assert passes(checks["solid_count"], "==", 1) == PASS
    assert passes(checks["brep_valid"], "==", 1) == PASS
    assert passes(checks["naked_edges"], "==", 0) == PASS
    assert checks["solid_count"].detail["volume_mm3"] == pytest.approx(parts.bracket_volume(), abs=1e-6)
    assert checks["brep_valid"].detail["bop_faults"] == []                 # the analyzer ran


@pytest.mark.parametrize("fixture,solid_count,brep_valid,naked", [
    (parts.two_solids, 2, 1, 0),             # two bodies in one part file
    (parts.open_box, 0, 1, 4),               # IsValid() is true for a box missing a face
    (parts.empty_boolean, 0, 1, 0),          # a boolean that removed everything
])
def test_each_known_bad_part_fails_at_least_one_validity_check(fixture, solid_count, brep_valid, naked):
    checks = core.validity(fixture())
    assert (checks["solid_count"].measured, checks["brep_valid"].measured,
            checks["naked_edges"].measured) == (solid_count, brep_valid, naked)
    statuses = [passes(checks["solid_count"], "==", 1), passes(checks["brep_valid"], "==", 1),
                passes(checks["naked_edges"], "==", 0)]
    assert FAIL in statuses
    assert statuses[1] == PASS, "BRepCheck alone passes these: that is why validity is three checks"


def test_a_self_intersecting_solid_fails_brep_valid_alone():
    checks = core.validity(parts.bow_tie())
    assert passes(checks["solid_count"], "==", 1) == PASS
    assert passes(checks["naked_edges"], "==", 0) == PASS
    assert passes(checks["brep_valid"], "==", 1) == FAIL
    assert checks["brep_valid"].detail["brepcheck"] is False


def test_a_solid_that_overlaps_itself_fails_only_the_analyzer_stage():
    """BRepCheck, the solid count, and the naked edges all pass a helix sweep whose
    coils overlap; BOPAlgo's self-interference check does not."""
    checks = core.validity(parts.helix_sweep())
    assert passes(checks["solid_count"], "==", 1) == PASS
    assert passes(checks["naked_edges"], "==", 0) == PASS
    assert passes(checks["brep_valid"], "==", 1) == FAIL
    detail = checks["brep_valid"].detail
    assert detail["brepcheck"] is True and detail["bop_faults"] == ["BOPAlgo_SelfIntersect"]
    quick = core.brep_valid(parts.helix_sweep(), analyzer=False)
    assert quick.measured == 1 and quick.params["analyzer"] is False


def test_self_intersections_still_fail_after_a_step_round_trip(tmp_path):
    """The round trip rebuilds a bow tie into a solid BRepCheck accepts; its lobes
    cancel, so it encloses no volume. The overlapping sweep keeps its volume and
    its self-intersection."""
    core.write_step(parts.bow_tie(), tmp_path / "bow_tie.step", timestamp=STAMP)
    bow_tie = core.brep_valid(core.read_step(tmp_path / "bow_tie.step"))
    assert bow_tie.detail["brepcheck"] is True and bow_tie.detail["solids_without_volume"] == 1
    assert passes(bow_tie, "==", 1) == FAIL
    core.write_step(parts.helix_sweep(), tmp_path / "sweep.step", timestamp=STAMP)
    sweep = core.brep_valid(core.read_step(tmp_path / "sweep.step"))
    assert sweep.detail["brepcheck"] is True and sweep.detail["bop_faults"] == ["BOPAlgo_SelfIntersect"]
    assert passes(sweep, "==", 1) == FAIL


def test_an_inside_out_solid_fails_brep_valid():
    checks = core.validity(parts.inside_out())
    assert checks["solid_count"].detail["volume_mm3"] == pytest.approx(-1000.0)
    assert passes(checks["solid_count"], "==", 1) == PASS
    assert passes(checks["naked_edges"], "==", 0) == PASS
    assert passes(checks["brep_valid"], "==", 1) == FAIL
    assert checks["brep_valid"].detail["brepcheck"] is True
    assert checks["brep_valid"].detail["solids_without_volume"] == 1


def test_degenerate_edges_are_not_naked():
    for solid in parts.round_solids():
        checks = core.validity(solid)
        assert checks["naked_edges"].measured == 0 and checks["naked_edges"].detail["degenerate_edges"] >= 1
        assert all(passes(checks[k], "==", v) == PASS
                   for k, v in (("solid_count", 1), ("brep_valid", 1), ("naked_edges", 0)))


@pytest.mark.parametrize("status", ["BOPAlgo_OperationAborted", "BOPAlgo_CheckUnknown"])
def test_an_analyzer_that_cannot_check_is_inconclusive(monkeypatch, status):
    answer = {"faults": [], "unknown": [status], "curve_on_surface_mm": 0.0, "seconds": 0.1, "solids": 1,
              "loose_shells": 0, "loose_faces": 0, "curve_on_surface_limit_mm": 1e-4}
    monkeypatch.setattr(core_validity._WORKER, "ask", lambda shape, budget, limit: answer)
    valid = core.brep_valid(parts.bracket())
    assert valid.status == INCONCLUSIVE and status in valid.reason
    assert passes(valid, "==", 1) == INCONCLUSIVE
    faulty = {**answer, "faults": ["BOPAlgo_SelfIntersect"]}       # a fault found elsewhere still fails
    monkeypatch.setattr(core_validity._WORKER, "ask", lambda shape, budget, limit: faulty)
    assert passes(core.brep_valid(parts.bracket()), "==", 1) == FAIL


def test_the_analyzer_stops_at_its_budget_and_the_next_check_runs():
    """A helical part can keep the analyzer busy for many minutes (25 on a 32 mm
    thread): it runs in a worker process that is stopped when the budget runs out."""
    slow = core.brep_valid(parts.helix_sweep(turns=3), budget_s=0.5)
    assert slow.status == INCONCLUSIVE and "within 0.5 s" in slow.reason
    assert passes(core.brep_valid(parts.bracket()), "==", 1) == PASS


@pytest.mark.parametrize("budget", [float("inf"), -1.0, 0.0, 1e7, "60", True])
def test_an_impossible_budget_is_refused_before_anything_is_asked(budget):
    """An infinite or negative budget once left the worker's answer queued, and the
    next shape got it: a self-intersecting coil passed."""
    refused = core.brep_valid(parts.bracket(), budget_s=budget)
    assert refused.status == INCONCLUSIVE and "budget_s" in refused.reason
    assert core.brep_valid(parts.helix_sweep()).detail["bop_faults"] == ["BOPAlgo_SelfIntersect"]
    assert passes(core.brep_valid(parts.bracket()), "==", 1) == PASS


def test_an_interrupted_check_leaves_no_answer_for_the_next(monkeypatch):
    """Ctrl+C while the analyzer works: the worker is stopped, so its late answer
    cannot become the next shape's."""
    worker = core_validity._WORKER
    real = worker._next

    def interrupted(timeout, want):
        if want > 0:
            raise KeyboardInterrupt
        return real(timeout, want)

    monkeypatch.setattr(worker, "_next", interrupted)
    with pytest.raises(KeyboardInterrupt):
        core.brep_valid(parts.helix_sweep())
    assert worker.process is None
    monkeypatch.setattr(worker, "_next", real)
    assert passes(core.brep_valid(parts.bracket()), "==", 1) == PASS
    assert passes(core.brep_valid(parts.helix_sweep()), "==", 1) == FAIL


def test_an_answer_to_another_request_is_refused(monkeypatch):
    worker = core_validity._WORKER
    real = worker._next
    monkeypatch.setattr(worker, "_next", lambda timeout, want: real(timeout, want - 1 if want else 0))
    stale = core.brep_valid(parts.bracket())
    assert stale.status == INCONCLUSIVE and "answered request" in stale.reason
    monkeypatch.setattr(worker, "_next", real)
    assert passes(core.brep_valid(parts.bracket()), "==", 1) == PASS


def test_a_worker_that_dies_mid_check_says_why():
    """A worker that died between checks is simply started again; one that dies
    during a check makes it INCONCLUSIVE, with the end of what it wrote to stderr."""
    import threading
    worker = core_validity._WORKER
    core.brep_valid(parts.bracket())                                    # a running worker
    process = worker.process

    def crash():
        worker.errors.append("MemoryError: the analyzer ran out of memory")
        process.kill()

    threading.Timer(0.3, crash).start()
    died = core.brep_valid(parts.helix_sweep(turns=3), budget_s=60)
    assert died.status == INCONCLUSIVE and "ran out of memory" in died.reason
    assert passes(core.brep_valid(parts.bracket()), "==", 1) == PASS


def test_the_pcurve_limit_grows_with_the_part():
    """A STEP round trip moves pcurves by up to 1.3e-4 mm on a thread 600 mm long."""
    small = core_validity._pcurve_limit(parts.bracket().wrapped)
    large = core_validity._pcurve_limit(Box(600, 400, 300).wrapped)
    assert small == core_validity.CURVE_ON_SURFACE_MM
    assert large == pytest.approx(1e-6 * (600 ** 2 + 400 ** 2 + 300 ** 2) ** 0.5, rel=1e-3)


def test_a_loose_shell_that_overlaps_itself_is_caught():
    """Solid by solid alone, a bracket plus a closed shell that overlaps itself passed
    all three gates."""
    coil = parts.helix_sweep()
    loose = Compound([parts.bracket(), coil.shells()[0]])
    checks = core.validity(loose)
    assert passes(checks["solid_count"], "==", 1) == PASS
    assert checks["brep_valid"].detail["loose_shells"] == 1
    assert passes(checks["brep_valid"], "==", 1) == FAIL


def test_a_threaded_part_stays_valid_through_a_step_round_trip(tmp_path):
    """OCCT's curve-on-surface check compares with each edge's own tolerance
    (1e-7 mm), so after the round trip a sound thread failed it by picometres."""
    rod = parts.threaded_rod()
    rod.label = "rod"
    assert passes(core.brep_valid(rod), "==", 1) == PASS
    core.write_step(rod, tmp_path / "rod.step", timestamp=STAMP)
    back = core.brep_valid(core.read_step(tmp_path / "rod.step"))
    assert 1e-7 < back.detail["curve_on_surface_mm"] <= core_validity.CURVE_ON_SURFACE_MM
    assert passes(back, "==", 1) == PASS


def test_parts_that_touch_in_an_assembly_are_not_a_self_intersection(tmp_path):
    """The analyzer checks each solid on its own; a clash between parts is
    common_volume's question."""
    base, cover = parts.pair(gap=0.0)
    assembly = Compound(children=[base, cover], label="pair")
    assert passes(core.brep_valid(assembly), "==", 1) == PASS
    rt = core.step_roundtrip(assembly, tmp_path / "pair.step", timestamp=STAMP)
    assert passes(rt["valid_after"], "==", 1) == PASS


def test_a_stray_edge_is_naked():
    from build123d import Edge
    stray = Compound(children=[parts.bracket(), Edge.make_line((0, 0, 20), (10, 0, 20))])
    checks = core.validity(stray)
    assert passes(checks["solid_count"], "==", 1) == PASS
    assert checks["naked_edges"].detail["free_edges"] == 1
    assert passes(checks["naked_edges"], "==", 0) == FAIL


def test_validity_of_a_non_shape_is_inconclusive():
    for result in core.validity(None).values():
        assert result.status == INCONCLUSIVE and "not a shape" in result.reason


# ------------------------------------------------------------------ STEP writer

def test_the_writer_gives_ap242_a_clean_header_and_the_same_bytes_twice(tmp_path):
    part = parts.bracket()
    first = core.write_step(part, tmp_path / "a" / "bracket.step", timestamp=STAMP)
    second = core.write_step(part, tmp_path / "b" / "bracket.step", timestamp=STAMP)
    assert first.format == "AP242" and core.read_schema(first.path) == "AP242"
    assert first.detail["length_unit"] == "MM" == core.read_length_unit(first.path)
    assert first.sha256 == second.sha256                          # R04 recommendation 7
    head = core.read_header(first.path)
    assert head["name"] == "bracket.step" and head["time_stamp"] == STAMP
    assert head["author"] == [""] and head["organization"] == [""] and head["authorization"] == ""
    assert head["originating_system"].startswith("build123d 0.13.0")
    assert core_step.header_leaks(head) == []
    assert str(tmp_path).casefold() not in first.path.read_text(errors="replace").casefold()
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == ["bracket.step"]


def test_the_writer_keeps_part_names_and_writes_ap214_on_request(tmp_path):
    base, cover = parts.pair()
    assembly = Compound(children=[base, cover], label="pair")
    written = core.write_step(assembly, tmp_path / "pair.step", timestamp=STAMP, schema="AP214")
    assert written.format == "AP214" and core.read_schema(written.path) == "AP214"
    assert sorted(core_step.labels(core.read_step(written.path))) == ["base", "cover"]


def test_the_writer_pins_its_statics_and_restores_whatever_was_set(tmp_path):
    """Earlier code in the process (build123d's export_step, a plain OCCT writer) may
    leave the writer statics anywhere. The file must not change, and they must be
    handed back as found."""
    clean = core.write_step(parts.bracket(), tmp_path / "clean" / "bracket.step", timestamp=STAMP)
    odd = {"write.step.schema": "AP203", "write.step.unit": "INCH", "write.surfacecurve.mode": "Off",
           "write.precision.mode": "Max", "step.angleunit.mode": "Deg", "write.precision.val": 0.5}
    with core_step.pinned(odd):
        written = core.write_step(parts.bracket(), tmp_path / "odd" / "bracket.step", timestamp=STAMP)
        assert {k: Interface_Static.CVal_s(k) for k in odd if k != "write.precision.val"} == \
            {k: v for k, v in odd.items() if k != "write.precision.val"}
        assert Interface_Static.RVal_s("write.precision.val") == 0.5
    assert written.sha256 == clean.sha256
    assert written.format == "AP242" and written.detail["length_unit"] == "MM"


def test_the_reader_pins_its_statics(tmp_path):
    """With xstep.cascade.unit left at M by earlier code, a 40 mm part read as 0.04."""
    written = core.write_step(parts.bracket(), tmp_path / "bracket.step", timestamp=STAMP)
    with core_step.pinned({"xstep.cascade.unit": "M"}):
        back = core.read_step(written.path)
        assert Interface_Static.CVal_s("xstep.cascade.unit") == "M"
    assert core.volume_mm3(back) == pytest.approx(parts.bracket_volume(), rel=1e-9)


def test_an_assembly_written_twice_gives_the_same_bytes(tmp_path):
    """OCCT numbers assembly occurrences from a counter that lasts the whole process."""
    base, cover = parts.pair()
    assembly = Compound(children=[base, cover], label="pair")
    first = core.write_step(assembly, tmp_path / "a" / "pair.step", timestamp=STAMP)
    second = core.write_step(assembly, tmp_path / "b" / "pair.step", timestamp=STAMP)
    assert first.sha256 == second.sha256
    assert b"NEXT_ASSEMBLY_USAGE_OCCURRENCE('1'" in first.path.read_bytes()


def test_a_part_inside_an_assembly_is_refused_with_its_reason(tmp_path):
    base, cover = parts.pair()
    Compound(children=[base, cover], label="pair")
    with pytest.raises(ValueError, match="sits in an assembly"):
        core.write_step(base, tmp_path / "base.step", timestamp=STAMP)


def test_pinning_a_static_that_does_not_exist_names_it():
    with pytest.raises(core.ExportError, match="no static write.step.nothing"):
        with core_step.pinned({"write.step.nothing": "x"}):
            pass


def test_the_unit_reader_sees_a_file_that_is_not_in_millimetres(tmp_path):
    path = tmp_path / "inch.step"
    with quiet(), core_step.pinned({"write.step.unit": "INCH", "write.step.schema": "AP214IS"}):
        writer = STEPControl_Writer()
        writer.Transfer(parts.bracket().wrapped, STEPControl_StepModelType.STEPControl_AsIs)
        writer.Write(str(path))
    assert core.read_length_unit(path) == "INCH"


def test_a_file_not_in_millimetres_is_refused(tmp_path, monkeypatch):
    """Fault injection: were the pinned unit ever wrong, the read-back catches it."""
    monkeypatch.setitem(core_step.STATICS, "write.step.unit", "INCH")
    with pytest.raises(core.ExportError, match="length unit is INCH"):
        core.write_step(parts.bracket(), tmp_path / "bracket.step", timestamp=STAMP)
    assert list(tmp_path.iterdir()) == []


def test_build123d_export_step_is_the_known_bad_writer(tmp_path):
    path = tmp_path / "bracket.step"
    with quiet():
        export_step(parts.bracket(), str(path))
    schema = Result("step_schema", int(core.read_schema(path) == "AP242"), "bool")
    assert passes(schema, "==", 1) == FAIL                        # R03 §1, D-024


def test_header_leaks_are_found():
    clean = {"name": "p.step", "time_stamp": STAMP, "author": [""], "organization": [""],
             "preprocessor_version": "x", "originating_system": "y", "authorization": ""}
    assert core_step.header_leaks(clean) == []
    assert core_step.header_leaks({**clean, "name": "C:/jobs/p.step"})
    assert core_step.header_leaks({**clean, "author": ["someone"]})
    assert core_step.header_leaks({**clean, "authorization": "x"})
    assert core_step.header_leaks({**clean, "name": core_step._user() + "_bracket.step"})


@pytest.mark.parametrize("name", ["marya01_bracket.step", "maryaBracket.step", "bracket_by_marya2.step"])
def test_a_user_name_glued_to_other_words_is_still_found(monkeypatch, name):
    monkeypatch.setattr(core_step, "_user", lambda: "marya")
    head = {"name": name, "time_stamp": STAMP, "author": [""], "organization": [""],
            "preprocessor_version": "x", "originating_system": "y", "authorization": ""}
    assert core_step.header_leaks(head) == ["the user name"]


def test_a_user_or_machine_named_like_the_tools_is_no_leak(monkeypatch):
    """The header always names "Open CASCADE STEP processor" and "build123d": only the
    fields that name the file and its makers are searched, and whole words only."""
    monkeypatch.setattr(core_step, "_user", lambda: "build")
    monkeypatch.setattr(core_step.platform, "node", lambda: "Cascade")
    head = {"name": "bracket_v01.step", "time_stamp": STAMP, "author": [""], "organization": [""],
            "preprocessor_version": core_step.PREPROCESSOR, "originating_system": core_step.ORIGINATING_SYSTEM,
            "authorization": ""}
    assert core_step.header_leaks(head) == []
    assert core_step.header_leaks({**head, "name": "cascade-bracket.step"}) == ["the machine name"]


def test_header_leaks_run_where_the_user_name_is_unknown(monkeypatch):
    def nobody():
        raise KeyError("getpwuid(): uid not found")        # a bare container

    monkeypatch.setattr(core_step.getpass, "getuser", nobody)
    head = {"name": "p.step", "time_stamp": STAMP, "author": [""], "organization": [""],
            "preprocessor_version": "x", "originating_system": "y", "authorization": ""}
    assert core_step.header_leaks(head) == []


def test_a_refused_file_never_stays_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(core_step, "header_leaks", lambda head: ["the user name"])
    with pytest.raises(core.ExportError, match="user name"):
        core.write_step(parts.bracket(), tmp_path / "bracket.step", timestamp=STAMP)
    assert list(tmp_path.iterdir()) == []


def test_the_writer_refuses_what_would_not_be_reproducible_or_clean(tmp_path):
    with pytest.raises(ValueError, match="timestamp"):
        core.write_step(parts.bracket(), tmp_path / "p.step", timestamp="yesterday")
    with pytest.raises(ValueError, match="file name"):
        core.write_step(parts.bracket(), tmp_path / "p.step", timestamp=STAMP, name="C:/x/p.step")
    with pytest.raises(ValueError, match="file name"):
        core.write_step(parts.bracket(), tmp_path / "gövde.step", timestamp=STAMP)
    with pytest.raises(ValueError, match="schema"):
        core.write_step(parts.bracket(), tmp_path / "p.step", timestamp=STAMP, schema="AP203")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("label", ["cover v1.2", "GÖVDE", "kapak(üst)"])
def test_the_writer_refuses_part_names_that_do_not_come_back(tmp_path, label):
    """import_step turns a space, '.', '(' and ')' into '_', and build123d writes
    non-ASCII names without the multibyte flag, so such a name would fail the label
    check on a correct file (or pass on a mangled one)."""
    base, cover = parts.pair(label_b=label)
    with pytest.raises(ValueError, match="labels"):
        core.write_step(Compound(children=[base, cover], label="pair"), tmp_path / "pair.step",
                        timestamp=STAMP)


def test_the_round_trip_of_a_sound_part_passes(tmp_path):
    rt = core.step_roundtrip(parts.bracket(), tmp_path / "bracket.step", timestamp=STAMP)
    assert passes(rt["schema"], "==", 1) == PASS
    assert passes(rt["solids"], "==", 1) == PASS
    assert passes(rt["volume_delta"], "<=", 0.0, band=1e-6) == PASS
    assert passes(rt["faces_delta"], "==", 0) == PASS
    assert passes(rt["labels"], "==", 1) == PASS
    assert passes(rt["valid_after"], "==", 1) == PASS
    assert {r.name for r in rt.values()} == {name for name, _ in core_step.ROUNDTRIP.values()}


def test_the_round_trip_fails_when_the_file_comes_back_different(tmp_path, monkeypatch):
    """Fault injection: a reader that loses the top face stands in for a lossy writer
    or reader, the fault this check exists to catch."""
    monkeypatch.setattr(core_step, "read_step", lambda path: parts.without_top_face(parts.bracket(thickness=3)))
    rt = core.step_roundtrip(parts.bracket(), tmp_path / "bracket.step", timestamp=STAMP)
    assert passes(rt["solids"], "==", 1) == FAIL
    assert passes(rt["volume_delta"], "<=", 0.0, band=1e-6) == FAIL
    assert passes(rt["faces_delta"], "==", 0) == FAIL
    assert passes(rt["valid_after"], "==", 1) == PASS          # an open shell is BRep-valid
    assert passes(rt["labels"], "==", 1) == PASS               # the name survived the loss


def test_the_round_trip_fails_when_the_file_comes_back_invalid(tmp_path, monkeypatch):
    """Fault injection: a reader that returns a self-intersecting solid."""
    monkeypatch.setattr(core_step, "read_step", lambda path: parts.bow_tie())
    rt = core.step_roundtrip(parts.bracket(), tmp_path / "bracket.step", timestamp=STAMP)
    assert passes(rt["valid_after"], "==", 1) == FAIL


def test_an_unnamed_part_in_an_assembly_fails_the_label_check(tmp_path):
    base, cover = parts.pair(label_b="")
    assembly = Compound(children=[base, cover], label="pair")
    rt = core.step_roundtrip(assembly, tmp_path / "pair.step", timestamp=STAMP)
    assert passes(rt["labels"], "==", 1) == FAIL


def test_a_round_trip_that_cannot_run_is_inconclusive(tmp_path):
    rt = core.step_roundtrip(None, tmp_path / "x.step", timestamp=STAMP)
    assert set(rt) == set(core_step.ROUNDTRIP)
    assert all(r.status == INCONCLUSIVE for r in rt.values())
    assert {r.name for r in rt.values()} == {name for name, _ in core_step.ROUNDTRIP.values()}


# ------------------------------------------------------------------- STL writer

def stl_triangles(path) -> int:
    data = path.read_bytes()
    (count,) = struct.unpack("<I", data[80:84])
    assert len(data) == 84 + 50 * count, "not a well-formed binary STL"
    return count


def test_the_stl_writer_meets_its_tolerance_and_reports_what_it_wrote(tmp_path):
    written = core.write_stl(parts.tube(), tmp_path / "tube.stl", tolerance=0.01, angular_tolerance=0.1)
    detail, sagitta = written.detail, written.checks["max_sagitta"]
    assert detail["triangles"] == stl_triangles(written.path) > 0
    assert 0 < detail["max_sagitta_mm"] == sagitta.measured <= 0.01
    assert passes(sagitta, "<=", 0.01, band=1e-9) == PASS


def test_a_coarse_mesh_is_the_known_bad_stl(tmp_path):
    written = core.write_stl(parts.tube(), tmp_path / "tube.stl", tolerance=0.5, angular_tolerance=0.8)
    assert passes(written.checks["max_sagitta"], "<=", 0.01, band=1e-9) == FAIL


def test_the_sagitta_is_measured_because_the_mesher_can_miss_its_tolerance(tmp_path):
    """On a lofted B-spline face OCCT's mesher leaves a sagitta above the tolerance it
    was given (0.5145 mm by a 16 x 16 grid per triangle); the centroid and edge
    midpoints alone read 0.4755 and passed."""
    written = core.write_stl(parts.lofted(), tmp_path / "loft.stl", tolerance=0.5, angular_tolerance=0.8)
    sagitta = written.checks["max_sagitta"]
    assert 0.5 < sagitta.measured < 0.5145 + 1e-4
    assert passes(sagitta, "<=", 0.5, band=1e-9) == FAIL


def test_the_stl_writer_clears_a_stale_triangulation(tmp_path):
    """A stale mesh at the same linear tolerance but a coarser angle is kept by OCCT
    unless it is cleared: 924 triangles against 1008 fresh on this tube."""
    fresh = core.write_stl(parts.tube(), tmp_path / "fresh.stl", tolerance=0.01, angular_tolerance=0.1)
    reused = parts.tube()
    BRepMesh_IncrementalMesh(reused.wrapped, 0.01, False, 1.0, True)
    BRepMesh_IncrementalMesh(reused.wrapped, 0.01, False, 0.1, True)
    assert core.mesh_sagitta(reused).detail["triangles"] != fresh.detail["triangles"]
    stale = parts.tube()
    BRepMesh_IncrementalMesh(stale.wrapped, 0.01, False, 1.0, True)
    written = core.write_stl(stale, tmp_path / "stale.stl", tolerance=0.01, angular_tolerance=0.1)
    assert written.detail["triangles"] == fresh.detail["triangles"]
    assert written.sha256 == fresh.sha256


def test_a_sample_that_cannot_be_projected_makes_the_sagitta_inconclusive(monkeypatch):
    class Lost:
        def __init__(self, surface): pass
        def NextValueOfUV(self, start, point, precision, max_precision): return start
        def Gap(self): return -1.0

    shape = parts.tube()
    BRepMesh_IncrementalMesh(shape.wrapped, 0.1, False, 0.5, True)
    monkeypatch.setattr(core_mesh, "ShapeAnalysis_Surface", Lost)
    result = core.mesh_sagitta(shape)
    assert result.status == INCONCLUSIVE and "could not be projected" in result.reason


def test_a_shape_without_a_mesh_has_no_sagitta():
    shape = parts.tube()
    BRepTools.Clean_s(shape.wrapped)
    result = core.mesh_sagitta(shape)
    assert result.status == INCONCLUSIVE and "no triangles" in result.reason


def test_the_stl_writer_refuses_a_meaningless_tolerance(tmp_path):
    with pytest.raises(ValueError):
        core.write_stl(parts.tube(), tmp_path / "t.stl", tolerance=0, angular_tolerance=0.1)


# --------------------------------------------------------------- boolean volume

def test_common_volume_is_exact_and_touching_is_zero():
    a = parts.block()
    assert core.common_volume(a, parts.block(8.0)).measured == pytest.approx(200.0, abs=1e-6)
    assert core.common_volume(a, parts.block(9.9)).measured == pytest.approx(10.0, abs=1e-6)  # positive control
    assert core.common_volume(a, parts.block(10.0)).measured == 0.0
    assert core.common_volume(a, parts.block(10.3)).measured == 0.0


def test_common_volume_works_solid_by_solid():
    left = Compound(children=[parts.block(0.0), parts.block(30.0)])
    right = Compound(children=[parts.block(8.0), parts.block(37.0)])
    result = core.common_volume(left, right)
    assert result.measured == pytest.approx(200.0 + 300.0, abs=1e-6)
    assert result.detail["pairs_computed"] == 2 and result.detail["pairs_skipped_by_bbox"] == 2
    assert passes(result, "<=", 0.0, band=1e-6) == FAIL                  # a clash is a FAIL


def test_common_volume_without_solids_is_inconclusive_never_zero():
    for result in (core.common_volume(parts.open_box(), parts.block()),
                   core.common_volume(None, parts.block())):
        assert result.status == INCONCLUSIVE and result.measured is None


@pytest.mark.parametrize("unsound,other,why", [
    (parts.helix_sweep, lambda: Pos(4, 0, 2) * Box(2, 2, 2), "BOPAlgo_SelfIntersect"),
    (parts.inside_out, lambda: parts.block(8.0), "inside out"),
])
def test_common_volume_refuses_an_unsound_solid_instead_of_a_wrong_number(unsound, other, why):
    """A block inside the coils of a self-overlapping sweep: the boolean said 0 mm³.
    Against an inside-out box it said 800 mm³ for 200."""
    result = core.common_volume(unsound(), other())
    assert result.status == INCONCLUSIVE and why in result.reason
    assert passes(result, "<=", 0.0, band=1e-6) == INCONCLUSIVE


def test_a_null_boolean_result_is_inconclusive(monkeypatch):
    from OCP.TopoDS import TopoDS_Shape

    class NullCommon:
        def __init__(self, a, b): pass
        def IsDone(self): return True
        def Shape(self): return TopoDS_Shape()

    monkeypatch.setattr(core_boolean, "BRepAlgoAPI_Common", NullCommon)
    result = core.common_volume(parts.block(), parts.block(8.0))
    assert result.status == INCONCLUSIVE and "null" in result.reason


# ---------------------------------------------------------------- fillet ladder

def cylinder_radii(shape) -> set[float]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    return {round(BRepAdaptor_Surface(f.wrapped).Cylinder().Radius(), 6) for f in shape.faces()
            if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Cylinder}


def test_the_fillet_ladder_records_the_radius_the_solid_got():
    block = Box(20, 10, 5, align=(Align.MIN,) * 3)
    done = core.fillet_ladder(block, block.edges().filter_by(Axis.Z), [10, 6, 4.9, 3])
    assert done.radius == 4.9 and [r for r, _ in done.tried] == [10.0, 6.0]
    assert cylinder_radii(done.shape) == {4.9}
    assert passes(core.solid_count(done.shape), "==", 1) == PASS


def test_a_ladder_with_no_rung_that_fits_leaves_the_part_and_says_so():
    plate = Box(20, 10, 2, align=(Align.MIN,) * 3)
    done = core.fillet_ladder(plate, plate.edges().group_by(Axis.Z)[-1], [5, 3, 2.5])
    assert done.radius is None and done.shape is plate
    assert [r for r, _ in done.tried] == [5.0, 3.0, 2.5]
    with pytest.raises(ValueError):
        core.fillet_ladder(plate, plate.edges(), [1, 2])               # not descending
    with pytest.raises(ValueError):
        core.fillet_ladder(plate, [], [1])


def test_the_ladder_takes_only_the_shapes_own_edges():
    """OCCT fillets the edges it finds and skips the rest, so an edge from a copy or
    from before a boolean would give a partial fillet reported as done."""
    block = Box(20, 10, 5, align=(Align.MIN,) * 3)
    twin = Box(20, 10, 5, align=(Align.MIN,) * 3)
    with pytest.raises(ValueError, match="not an edge of this shape"):
        core.fillet_ladder(block, twin.edges().filter_by(Axis.Z), [2, 1])
    with pytest.raises(ValueError, match="takes edges"):
        core.fillet_ladder(block, block.faces(), [2, 1])


def test_a_rung_that_leaves_an_edge_unfilleted_is_rejected(monkeypatch):
    block = Box(20, 10, 5, align=(Align.MIN,) * 3)
    fillet = type(block).fillet
    monkeypatch.setattr(type(block), "fillet", lambda self, radius, edges: fillet(self, radius, list(edges)[:2]))
    done = core.fillet_ladder(block, block.edges().filter_by(Axis.Z), [2, 1])
    assert done.radius is None and done.shape is block
    assert [why for _, why in done.tried] == ["2 of 4 edge(s) not filleted"] * 2


# ------------------------------------------------------------------------ traps
# Each trap test pins a library behaviour the core works around. When one fails
# after an upgrade, the behaviour changed: update library/BUILD123D-NOTES.md.

def test_trap_export_step_ignores_the_schema_static(tmp_path):
    path = tmp_path / "x.step"
    with quiet(), core_step.pinned({"write.step.schema": "AP242DIS"}):
        export_step(parts.bracket(), str(path))
    assert core.read_schema(path) == "AP214"


def test_trap_export_stl_tolerance_is_relative(tmp_path):
    """build123d meshes with isRelative=True: at "tolerance=0.01" a 300 mm tube is
    0.7 mm off; write_stl's absolute 0.01 mm keeps under it."""
    big = parts.tube(od=300.0, bore=240.0, height=200.0)
    export_stl(big, str(tmp_path / "big.stl"), tolerance=0.01, angular_tolerance=1.0)
    assert core.mesh_sagitta(big).measured > 0.1
    written = core.write_stl(parts.tube(od=300.0, bore=240.0, height=200.0), tmp_path / "big2.stl",
                             tolerance=0.01, angular_tolerance=1.0)
    assert written.checks["max_sagitta"].measured <= 0.01


def test_trap_export_stl_reuses_a_cached_triangulation(tmp_path):
    shape = parts.tube()
    counts = []
    for angular in (0.5, 0.05):
        path = tmp_path / f"t{angular}.stl"
        export_stl(shape, str(path), tolerance=0.001, angular_tolerance=angular)
        counts.append(stl_triangles(path))
    assert counts[0] == counts[1]                                        # R04 §1


def test_trap_an_empty_boolean_is_a_valid_compound_with_no_volume():
    empty = parts.empty_boolean()
    assert type(empty).__name__ == "Compound" and empty.volume == 0 and empty.is_valid
    assert not empty.solids()


def test_trap_occp_boolean_has_no_error_flag():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    assert hasattr(BRepAlgoAPI_Common, "IsDone") and not hasattr(BRepAlgoAPI_Common, "HasErrors")


def test_trap_the_argument_analyzer_checks_nothing_until_its_modes_are_on():
    from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
    analyzer = BOPAlgo_ArgumentAnalyzer()
    analyzer.SetShape1(parts.helix_sweep().wrapped)
    analyzer.Perform()
    assert not analyzer.HasFaulty()


def test_trap_the_self_interference_check_fails_on_bezier_glyphs_until_a_step_round_trip(tmp_path):
    """build123d's Text draws Bezier edges; BOPAlgo's intersector fails on the faces
    extruded from them (BOPAlgo_AlertIntersectionFailed). A STEP round trip turns
    them into B-splines, and the check runs."""
    glyph = parts.glyph("O")
    assert core.brep_valid(glyph).status == INCONCLUSIVE
    core.write_step(glyph, tmp_path / "glyph.step", timestamp=STAMP)
    back = core.brep_valid(core.read_step(tmp_path / "glyph.step"))
    assert back.status != INCONCLUSIVE and back.measured == 1


def test_trap_part_names_change_on_a_round_trip(tmp_path):
    """import_step turns a space, '.', '(' and ')' into '_', and non-ASCII names come
    back double-encoded, because build123d writes them without the multibyte flag."""
    got = {}
    for name in ("cover v1.2", "kapak(1)", "GÖVDE"):
        base, cover = parts.pair(label_b=name)
        path = tmp_path / "names.step"
        with quiet():
            export_step(Compound(children=[base, cover], label="pair"), str(path))
        got[name] = [n for n in core_step.labels(core.read_step(path)) if n != "base"]
    assert got["cover v1.2"] == ["cover_v1_2"] and got["kapak(1)"] == ["kapak_1_"]
    assert got["GÖVDE"] != ["GÖVDE"]


def test_trap_global_projection_misses_points_on_a_cone():
    """GeomAPI_ProjectPointOnSurf finds no point for some sample points of a meshed
    cone; the sagitta projects with ShapeAnalysis_Surface, which finds every one."""
    from build123d import Cone
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt
    from OCP.TopLoc import TopLoc_Location
    cone = Cone(10, 3, 20)
    BRepMesh_IncrementalMesh(cone.wrapped, 0.5, False, 0.8, True)
    face = next(f.wrapped for f in cone.faces() if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Cone)
    location = TopLoc_Location()
    mesh = BRep_Tool.Triangulation_s(face, location)
    nodes = [mesh.Node(i).Transformed(location.Transformation()) for i in range(1, mesh.NbNodes() + 1)]
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    projector = GeomAPI_ProjectPointOnSurf()
    projector.Init(BRep_Tool.Surface_s(face), u0, u1, v0, v1)
    missed = 0
    for t in range(1, mesh.NbTriangles() + 1):
        a, b, c = (nodes[k - 1] for k in mesh.Triangle(t).Get())
        for wa, wb, wc in core_mesh.WEIGHTS:
            projector.Perform(gp_Pnt(wa * a.X() + wb * b.X() + wc * c.X(), wa * a.Y() + wb * b.Y() + wc * c.Y(),
                                     wa * a.Z() + wb * b.Z() + wc * c.Z()))
            missed += projector.NbPoints() == 0
    assert missed > 0
    assert core.mesh_sagitta(cone).status != INCONCLUSIVE


def test_every_test_the_notes_cite_exists():
    from conftest import ROOT
    notes = (ROOT / "docs" / "BUILD123D-NOTLARI.md").read_text(encoding="utf-8")
    here = ROOT / "tests"
    current, cited = None, 0
    for file, name in re.findall(r"`(test_\w+\.py)?::(test_\w+)`", notes):
        current = file or current
        assert f"def {name}(" in (here / current).read_text(encoding="utf-8"), f"{current}::{name}"
        cited += 1
    assert cited >= 10


def test_quiet_removes_the_printers_and_puts_them_back():
    from OCP.Message import Message
    messenger = Message.DefaultMessenger_s()
    before = messenger.Printers().Size()
    with quiet():
        assert messenger.Printers().Size() == 0
    assert messenger.Printers().Size() == before


def child_env():
    """A child Python sees the checkout (pocad) and the test fixtures, as the
    oguz-atolye launcher (tools/run.py) arranged with PYTHONPATH."""
    import os

    from conftest import ROOT
    paths = [str(ROOT), str(ROOT / "tests"), os.environ.get("PYTHONPATH", "")]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in paths if p)}


def test_the_core_is_quiet():
    code = ("from pocad import core\nfrom fixtures import parts\nimport tempfile, pathlib\n"
            "d = pathlib.Path(tempfile.mkdtemp())\n"
            "core.write_step(parts.bracket(), d / 'p.step', timestamp='2026-09-20T00:00:00')\n"
            "core.read_step(d / 'p.step')\n"
            "core.write_stl(parts.bracket(), d / 'p.stl', tolerance=0.01, angular_tolerance=0.1)\n"
            "print('done')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         env=child_env())
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "done", out.stdout


def process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259                                       # STILL_ACTIVE
    import os
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_the_analyzer_worker_dies_with_its_parent():
    """A parent killed hard (a closed terminal, a test runner's timeout) during a
    check once left the worker checking a thread for up to 25 minutes. An idle
    worker leaves when its input closes; a busy one must die with its parent."""
    import time
    code = ("import importlib\nfrom pocad import core\nfrom fixtures import parts\n"
            "core.brep_valid(parts.bracket())\n"
            "print(importlib.import_module('pocad.core.validity')._WORKER.process.pid, flush=True)\n"
            "core.brep_valid(parts.helix_sweep(pitch=3.2, tube=1.5, radius=8.0, turns=6))\n")
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=child_env())
    try:
        worker = int(parent.stdout.readline())
        time.sleep(1.0)                                  # the worker is busy with the spring
        assert process_alive(worker)
    finally:
        parent.kill()
        parent.wait()
    for _ in range(30):
        if not process_alive(worker):
            break
        time.sleep(0.1)
    assert not process_alive(worker)
