# kaynak: oguz-atolye tools/core/fillet.py @ca27b1b (MIT, PoCAD'e taşındı)
"""The descending-radius fillet ladder (PLAYBOOK §3 D4, REFERENCE-LIBRARY §3.5).

Fillets fail where concave edges share a vertex, and a radius has a geometric
ceiling, so the designer asks for a list of radii, largest first, and records the
radius the solid actually got. A rung counts only when every edge was filleted and
the result is still exactly one valid solid: OCCT can "succeed" and hand back
something else, and it fillets only the edges it finds in the shape, silently
skipping an edge taken from a copy or from before a boolean.
"""
from __future__ import annotations

from dataclasses import dataclass

from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp

from pocad._ocp import IndexedMapOfShape
from pocad.core.shapes import occ
from pocad.core.validity import brep_valid, solid_count
from pocad.result import MEASURED


@dataclass(frozen=True)
class Filleted:
    shape: object
    radius: float | None                  # None: every rung failed, shape is the input
    tried: tuple[tuple[float, str], ...]  # (radius, why it was rejected)


def _edge_map(shape) -> IndexedMapOfShape:
    found = IndexedMapOfShape()
    TopExp.MapShapes_s(occ(shape), TopAbs_EDGE, found)
    return found


def fillet_ladder(shape, edges, radii) -> Filleted:
    """Fillet `edges` of `shape` with the first radius in `radii` (largest first)
    that fillets every edge and leaves exactly one valid solid. Returns the input
    unchanged, radius None, when none does; the caller reports the unfilleted edges
    (D8: radii achieved).

    ERR  ValueError when the radii are not positive and descending, or an edge is
         not an edge of `shape` (select edges on the shape being filleted, D-027).
    """
    ladder = [float(r) for r in radii]
    if not ladder or any(r <= 0 for r in ladder) or ladder != sorted(ladder, reverse=True):
        raise ValueError("radii must be positive and in descending order")
    edges = list(edges)
    if not edges:
        raise ValueError("no edges to fillet")
    own = _edge_map(shape)
    for edge in edges:
        wrapped = getattr(edge, "wrapped", None)
        if wrapped is None or wrapped.ShapeType() != TopAbs_EDGE:
            raise ValueError(f"fillet_ladder takes edges, not {type(edge).__name__}")
        if not own.Contains(wrapped):
            raise ValueError("an edge is not an edge of this shape: it comes from a copy, or from "
                             "before a boolean; select it on the shape being filleted")
    tried: list[tuple[float, str]] = []
    for radius in ladder:
        try:
            result = shape.fillet(radius, edges)
        except Exception as exc:                            # noqa: BLE001: the next rung
            tried.append((radius, f"{type(exc).__name__}"))
            continue
        left = _edge_map(result)
        unfilleted = sum(1 for edge in edges if left.Contains(edge.wrapped))
        if unfilleted:
            tried.append((radius, f"{unfilleted} of {len(edges)} edge(s) not filleted"))
            continue
        count, valid = solid_count(result), brep_valid(result)
        if valid.status != MEASURED:
            tried.append((radius, f"brep_valid INCONCLUSIVE: {valid.reason}"))
            continue
        if count.measured == 1 and valid.measured == 1:
            return Filleted(result, radius, tuple(tried))
        tried.append((radius, f"{count.measured} solid(s), brep_valid {valid.measured}"))
    return Filleted(shape, None, tuple(tried))
