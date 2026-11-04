# kaynak: oguz-atolye tools/core/_analyzer.py @ca27b1b (MIT, PoCAD'e taşındı)
"""The worker process behind the third stage of brep_valid (pocad/core/validity.py).

BOPAlgo_ArgumentAnalyzer can run for many minutes on a helical part (25 minutes on
a 32 mm thread), and OCP offers no way to interrupt it: Message_ProgressIndicator
cannot be subclassed from Python, and the call holds the GIL. So it runs here, in
a child process that the parent stops when its time budget runs out. The worker
imports OCP only.

Protocol, one line each way. The parent writes a JSON request {"id": n, "path":
BREP file, "modes": analyzer modes, "curve_on_surface_mm": limit}; the worker
answers with a line that starts with PREFIX, followed by JSON that echoes the id.
It answers once, with id 0, when it is ready. Each solid is checked on its own, so
solids that touch in an assembly are not a self-intersection (clashes between
parts are pocad.core.common_volume's question); shells and faces outside any solid
are checked on their own too.
"""
from __future__ import annotations

import json
import os
import sys
import time

from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.Message import Message
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shape

PREFIX = "@@analyzer "
UNKNOWN = {"BOPAlgo_OperationAborted", "BOPAlgo_CheckUnknown"}      # the check did not run
CURVE_ON_SURFACE = "BOPAlgo_InvalidCurveOnSurface"


def _pieces(shape):
    """(kind, sub-shape) for every solid, every shell outside a solid, and every
    face outside a shell."""
    for kind, what, avoid in (("solid", TopAbs_SOLID, None), ("shell", TopAbs_SHELL, TopAbs_SOLID),
                              ("face", TopAbs_FACE, TopAbs_SHELL)):
        explorer = TopExp_Explorer(shape, what) if avoid is None else TopExp_Explorer(shape, what, avoid)
        while explorer.More():
            yield kind, explorer.Current()
            explorer.Next()


def analyze(request: dict) -> dict:
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, request["path"], BRep_Builder()):
        raise RuntimeError("the shape could not be read back")
    faults, unknown, worst_pcurve = set(), set(), 0.0
    counts = {"solid": 0, "shell": 0, "face": 0}
    start = time.perf_counter()
    for kind, piece in _pieces(shape):
        counts[kind] += 1
        analyzer = BOPAlgo_ArgumentAnalyzer()
        analyzer.SetShape1(piece)
        for mode in request["modes"]:
            setattr(analyzer, mode, True)
        analyzer.Perform()
        if not analyzer.HasFaulty():
            continue
        for result in analyzer.GetCheckResult():
            status = str(result.GetCheckStatus()).rsplit(".", 1)[-1]
            if status in UNKNOWN:
                unknown.add(status)
            elif status == CURVE_ON_SURFACE:
                # OCCT compares with the edge's own tolerance (1e-7 mm), so a sound
                # part fails by picometres after a STEP round trip: count real gaps only.
                distance = max(result.GetMaxDistance1(), result.GetMaxDistance2())
                worst_pcurve = max(worst_pcurve, distance)
                if distance > request["curve_on_surface_mm"]:
                    faults.add(status)
            else:
                faults.add(status)
    return {"faults": sorted(faults), "unknown": sorted(unknown), "curve_on_surface_mm": worst_pcurve,
            "solids": counts["solid"], "loose_shells": counts["shell"], "loose_faces": counts["face"],
            "seconds": round(time.perf_counter() - start, 3)}


def _die_with_parent() -> None:
    """On Linux, ask the kernel to kill this process when its parent dies; on
    Windows the parent puts it in a job object that does the same."""
    if not sys.platform.startswith("linux"):
        return
    import ctypes
    import signal
    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL)    # PR_SET_PDEATHSIG
    if os.getppid() == 1:                                         # the parent is already gone
        sys.exit(0)


def main() -> None:
    _die_with_parent()
    messenger = Message.DefaultMessenger_s()                 # stdout carries the protocol only
    for printer in list(messenger.Printers()):
        messenger.RemovePrinter(printer)
    print(PREFIX + json.dumps({"id": 0, "ready": True}), flush=True)
    for line in sys.stdin:
        request: dict = {}
        try:
            request = json.loads(line)
            answer = analyze(request)
        except Exception as exc:                             # noqa: BLE001: reported to the parent
            answer = {"error": f"{type(exc).__name__}: {exc}"}
        print(PREFIX + json.dumps({"id": request.get("id"), **answer}), flush=True)


if __name__ == "__main__":
    main()
