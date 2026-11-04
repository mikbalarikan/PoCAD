# kaynak: oguz-atolye tools/core/validity.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Validity is three checks, not one (R04 recommendation 5, D-026).

`BRepCheck_Analyzer.IsValid()` is true for a box missing a face and for an empty
compound (what a failed boolean returns), so topology validity alone proves
nothing. A part is sound when all three hold, each compared by its own gate:
exactly one solid, a valid solid, and no naked edges.
"""
from __future__ import annotations

import atexit
import collections
import itertools
import json
import math
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_FormatVersion

from pocad._ocp import IndexedDataMapOfShapeListOfShape, downcast
from pocad.core import _analyzer
from pocad.core.shapes import occ, solids, volume_mm3
from pocad.env import env_path
from pocad.result import Result, inconclusive, measurement

# The checks of BOPAlgo_ArgumentAnalyzer that find defects in one solid. Each is off
# until switched on, and with none on the analyzer reports nothing. Left off:
# TangentMode, MergeVertexMode, and MergeEdgeMode test touching and mergeable
# sub-shapes, a question for a boolean between two arguments; ContinuityMode flags
# C0 geometry, which is legal and only makes booleans fragile.
BOP_MODES = ("ArgumentTypeMode", "SelfInterMode", "SmallEdgeMode", "RebuildFaceMode",
             "CurveOnSurfaceMode")
ANALYZER_BUDGET_S = 120.0  # a 24 mm thread takes 42 s; a 32 mm one 25 minutes
# The longest budget accepted, one day, the same on every platform: threading.TIMEOUT_MAX
# is about 50 days on Windows and 292 years on Linux.
MAX_BUDGET_S = min(86400.0, threading.TIMEOUT_MAX)
# A pcurve counts as off its edge beyond 1e-4 mm (0.1 µm) or a millionth of the part's
# size, whichever is larger: a STEP round trip moves pcurves by up to 1.3e-4 mm on a
# thread 600 mm long. A pcurve really out of place, BRepCheck finds at stage 1.
CURVE_ON_SURFACE_MM = 1e-4
CURVE_ON_SURFACE_PER_MM = 1e-6
MIN_VOLUME_MM3 = 1e-9      # far below any part; a cancelled bow tie measures about 1e-14
STARTUP_S = 60.0


@measurement("solid_count", "count")
def solid_count(shape) -> Result:
    """How many solids the shape holds. A part file holds exactly one (PLAYBOOK D3,
    `exactly_one_solid`); an empty compound from a failed boolean holds none."""
    found = solids(shape)
    return Result("solid_count", len(found), "count",
                  detail={"volume_mm3": volume_mm3(shape), "solid_volumes_mm3":
                          [volume_mm3(s) for s in found]})


@measurement("brep_valid", "bool")
def brep_valid(shape, *, analyzer: bool = True, budget_s: float = ANALYZER_BUDGET_S) -> Result:
    """1 when the shape is sound in three stages, run in this order because the last
    can be slow (R04 recommendation 6):

    1. BRepCheck_Analyzer finds the topology valid;
    2. every solid encloses a positive volume: an inside-out solid passes BRepCheck
       and turns a boolean volume wrong, and a self-intersecting profile whose lobes
       cancel encloses none, yet passes BRepCheck once a STEP round trip has
       rebuilt it;
    3. BOPAlgo_ArgumentAnalyzer, solid by solid (and any loose shell or face on
       its own) with the modes in BOP_MODES on, finds no self-intersection, small
       edge, face it cannot rebuild, or pcurve off its edge by more than 1e-4 mm or
       a millionth of the part's size. A solid that overlaps itself passes the
       first two. It runs in a worker process within `budget_s` seconds.

    A third stage that runs out of time, aborts, or cannot check is INCONCLUSIVE,
    not a pass. analyzer=False skips it for quick screening inside a loop; a gated
    check keeps the default.
    """
    shape_occ = occ(shape)
    first = bool(BRepCheck_Analyzer(shape_occ).IsValid())
    volumes = [volume_mm3(s) for s in solids(shape)]
    no_volume = sum(1 for v in volumes if v <= MIN_VOLUME_MM3)
    params = {"analyzer": analyzer, "budget_s": budget_s}
    detail = {"brepcheck": first, "solids_without_volume": no_volume, "bop_faults": None,
              "bop_seconds": None, "curve_on_surface_mm": None}
    if first and not no_volume and analyzer and volumes:
        answer = _WORKER.ask(shape_occ, budget_s, _pcurve_limit(shape_occ))
        if answer is not None and answer["solids"] != len(volumes):
            raise RuntimeError(f"the analyzer checked {answer['solids']} solid(s) of {len(volumes)}")
        if answer is None:
            return inconclusive("brep_valid", "bool", f"BOPAlgo's argument analyzer did not finish "
                                f"within {budget_s:g} s", **params)
        detail.update(bop_faults=answer["faults"], bop_seconds=answer["seconds"],
                      curve_on_surface_mm=answer["curve_on_surface_mm"],
                      curve_on_surface_limit_mm=answer["curve_on_surface_limit_mm"],
                      loose_shells=answer["loose_shells"], loose_faces=answer["loose_faces"])
        if not answer["faults"] and answer["unknown"]:
            return inconclusive("brep_valid", "bool", "BOPAlgo's argument analyzer could not check "
                                f"the shape ({', '.join(answer['unknown'])})", **params)
    valid = first and not no_volume and not detail["bop_faults"]
    return Result("brep_valid", int(valid), "bool", params=params, detail=detail)


def _pcurve_limit(shape_occ) -> float:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape_occ, box, False)
    diagonal = 0.0 if box.IsVoid() else math.sqrt(box.SquareExtent())
    return max(CURVE_ON_SURFACE_MM, CURVE_ON_SURFACE_PER_MM * diagonal)


class _Worker:
    """One child process that runs the analyzer (pocad/core/_analyzer.py), started
    on first use and replaced when a check runs out of time or is interrupted.
    Every request carries an id the answer must echo, so an answer can never be
    taken for another shape's."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.answers: queue.Queue | None = None
        self.errors: collections.deque = collections.deque(maxlen=20)
        self.job = None
        self.ids = itertools.count(1)
        self.lock = threading.Lock()

    def ask(self, shape_occ, budget_s: float, pcurve_limit: float) -> dict | None:
        """The analyzer's answer for the shape, or None when it ran out of time."""
        if (not isinstance(budget_s, (int, float)) or isinstance(budget_s, bool) or not math.isfinite(budget_s)
                or not 0 < budget_s <= MAX_BUDGET_S):
            raise ValueError(f"budget_s is a number of seconds above 0, not {budget_s!r}")
        with self.lock:
            try:
                if self.process is None or self.process.poll() is not None:
                    self._start()
                with tempfile.TemporaryDirectory(prefix="pocad-analyzer-", dir=_scratch(),
                                                 ignore_cleanup_errors=True) as folder:
                    path = Path(folder) / "shape.brep"
                    if not BRepTools.Write_s(shape_occ, str(path), False, False,
                                             TopTools_FormatVersion.TopTools_FormatVersion_CURRENT):
                        raise RuntimeError("the shape could not be written for the analyzer")
                    request = {"id": next(self.ids), "path": str(path), "modes": list(BOP_MODES),
                               "curve_on_surface_mm": pcurve_limit}
                    self.process.stdin.write(json.dumps(request) + "\n")
                    self.process.stdin.flush()
                    try:
                        answer = self._next(budget_s, request["id"])
                    except queue.Empty:
                        self.stop()
                        return None
            except BaseException:
                self.stop()                  # never leave an answer queued for the next request
                raise
        if "error" in answer:
            raise RuntimeError(f"the analyzer failed: {answer['error']}")
        return {**answer, "curve_on_surface_limit_mm": pcurve_limit}

    def _next(self, timeout: float, want: int) -> dict:
        line = self.answers.get(timeout=timeout)
        if line is None:
            tail = " | ".join(self.errors) or "no message"
            self.stop()
            raise RuntimeError(f"the analyzer process stopped: {tail}")
        answer = json.loads(line[len(_analyzer.PREFIX):])
        if answer.get("id") != want:
            raise RuntimeError(f"the analyzer answered request {answer.get('id')} while {want} was waiting")
        return answer

    def _start(self) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.process = subprocess.Popen([sys.executable, _analyzer.__file__], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
        self.job = _kill_with_parent(self.process)
        self.answers, self.errors = queue.Queue(), collections.deque(maxlen=20)
        threading.Thread(target=_pump, args=(self.process.stdout, self.answers), daemon=True).start()
        threading.Thread(target=_collect, args=(self.process.stderr, self.errors), daemon=True).start()
        try:
            self._next(STARTUP_S, 0)
        except queue.Empty:
            self.stop()
            raise RuntimeError("the analyzer process did not start") from None

    def stop(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.wait()
            self.process = None
        if self.job is not None:
            import ctypes
            from ctypes import wintypes
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(self.job))
            self.job = None


def _scratch() -> str | None:
    """${POCAD_WORK}/tmp (the system temp folder when unset) for the analyzer's temporary files, off AppData (D-072)."""
    work = env_path("POCAD_WORK")
    if work is None:
        return None
    folder = work / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def _kill_with_parent(process: subprocess.Popen):
    """On Windows, put the worker in a job object that is killed when this process
    ends, however it ends; returns the job handle, or None. (On Linux the worker
    asks the kernel for the same when it starts.)"""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000                   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
            or not kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(process._handle))):
        kernel32.CloseHandle(wintypes.HANDLE(job))
        return None
    return job


def _pump(stream, answers: queue.Queue) -> None:
    for line in stream:
        if line.startswith(_analyzer.PREFIX):
            answers.put(line.rstrip("\n"))
    answers.put(None)


def _collect(stream, errors: collections.deque) -> None:
    for line in stream:
        errors.append(line.rstrip())


_WORKER = _Worker()
atexit.register(_WORKER.stop)


@measurement("naked_edges", "count")
def naked_edges(shape) -> Result:
    """Edges used by fewer than two faces: one face (an open boundary) or none (a
    stray edge, which a delivered file must not carry either). Zero means the
    boundary is closed. Degenerate edges (a sphere's poles, a cone's apex, a drill
    point's tip) have no length and are not boundary."""
    ancestry = IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(occ(shape), TopAbs_EDGE, TopAbs_FACE, ancestry)
    naked = free = shared_by_more = degenerate = 0
    for i in range(1, ancestry.Extent() + 1):
        if BRep_Tool.Degenerated_s(downcast.Edge(ancestry.FindKey(i))):
            degenerate += 1
            continue
        count = ancestry.FindFromIndex(i).Extent()
        if count == 0:
            free += 1
        elif count == 1:
            naked += 1
        elif count > 2:
            shared_by_more += 1
    return Result("naked_edges", naked + free, "count",
                  detail={"edges": ancestry.Extent(), "free_edges": free,
                          "edges_on_3plus_faces": shared_by_more, "degenerate_edges": degenerate})


def validity(shape) -> dict[str, Result]:
    """The three checks of a part file, keyed by name. Gate each one: solid_count == 1,
    brep_valid == 1, naked_edges == 0."""
    return {"solid_count": solid_count(shape), "brep_valid": brep_valid(shape),
            "naked_edges": naked_edges(shape)}
