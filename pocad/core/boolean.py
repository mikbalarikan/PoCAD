# kaynak: oguz-atolye tools/core/boolean.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Fail-closed boolean volume (REFERENCE-LIBRARY §3.1, R04 §7).

v1's interference check turned a failed boolean into 0.0, a pass. Here a boolean
that raises, does not finish, or returns a null shape is INCONCLUSIVE, and only a
finished boolean with nothing left is a confirmed zero. The shapes are split into
solids first, with a bounding-box prefilter: a boolean against a multi-solid
compound measured a connector band 3.38 mm short (L-22). Every solid that takes
part in a boolean is checked first, because a boolean on an unsound solid returns
a confident wrong number: 0 against a solid that overlaps itself, 800 mm³ for 200
against one that is inside out.
"""
from __future__ import annotations

from OCP.Bnd import Bnd_Box
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib

from pocad.core.shapes import solids, volume_mm3
from pocad.core.validity import brep_valid, naked_edges
from pocad.result import MEASURED, Result, inconclusive, measurement


def _box(shape) -> Bnd_Box:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    return box


def unsound(solid) -> str | None:
    """Why a solid cannot take part in a boolean, or None when it is sound: valid
    (brep_valid, all three stages) and closed (no naked edges)."""
    valid = brep_valid(solid)
    if valid.status != MEASURED:
        return f"brep_valid is INCONCLUSIVE ({valid.reason})"
    if not valid.measured:
        d = valid.detail
        why = ("BRepCheck finds it invalid" if not d["brepcheck"] else
               "it encloses no positive volume (inside out)" if d["solids_without_volume"] else
               "BOPAlgo finds " + ", ".join(d["bop_faults"] or []))
        return f"brep_valid is 0: {why}"
    naked = naked_edges(solid)
    if naked.status != MEASURED:
        return f"naked_edges is INCONCLUSIVE ({naked.reason})"
    if naked.measured:
        return f"it has {naked.measured} naked edge(s)"
    return None


@measurement("common_volume", "mm3")
def common_volume(a, b) -> Result:
    """Volume in mm³ that the solids of `a` and `b` share. Touching solids share
    none: a contact is not a volume (measure the engaged area for that, L-22)."""
    left, right = solids(a), solids(b)
    if not left or not right:
        return inconclusive("common_volume", "mm3", "a shape without solids")
    right_boxes = [_box(y) for y in right]
    checked: dict[tuple[str, int], str | None] = {}
    total, computed, skipped = 0.0, 0, 0
    for i, x in enumerate(left):
        box_x = _box(x)
        for j, y in enumerate(right):
            if box_x.IsOut(right_boxes[j]):
                skipped += 1
                continue
            for side, index, solid in (("a", i, x), ("b", j, y)):
                if (side, index) not in checked:
                    checked[side, index] = unsound(solid)
                if checked[side, index]:
                    return inconclusive("common_volume", "mm3",
                                        f"solid {index + 1} of {side}: {checked[side, index]}")
            op = BRepAlgoAPI_Common(x, y)
            if not op.IsDone():                   # OCP exposes IsDone only, no HasErrors
                return inconclusive("common_volume", "mm3", "the boolean did not finish")
            result = op.Shape()
            if result.IsNull():
                return inconclusive("common_volume", "mm3", "the boolean returned a null shape")
            computed += 1
            total += sum(volume_mm3(s) for s in solids(result))
    return Result("common_volume", total, "mm3",
                  detail={"solids_a": len(left), "solids_b": len(right), "pairs_computed": computed,
                          "pairs_skipped_by_bbox": skipped, "solids_checked": len(checked)})
