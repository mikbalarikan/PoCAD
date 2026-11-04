# kaynak: oguz-atolye tools/core/shapes.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Shape plumbing shared by core and measure: the OCCT shape under a build123d
object, its solids, its exact volume, its faces and edges, and a way to keep
OCCT's console chatter out of tool output."""
from __future__ import annotations

import contextlib

from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Message import Message
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shape

from pocad._ocp import downcast


def occ(shape) -> TopoDS_Shape:
    """The TopoDS_Shape of a build123d object, or the shape itself."""
    wrapped = getattr(shape, "wrapped", shape)
    if not isinstance(wrapped, TopoDS_Shape):
        raise TypeError(f"not a shape: {type(shape).__name__}")
    if wrapped.IsNull():
        raise ValueError("null shape")
    return wrapped


def _explore(shape, kind, cast) -> list:
    out = []
    explorer = TopExp_Explorer(occ(shape), kind)
    while explorer.More():
        out.append(cast(explorer.Current()))
        explorer.Next()
    return out


def solids(shape) -> list:
    """Every OCCT solid in the shape, nested compounds included."""
    return _explore(shape, TopAbs_SOLID, downcast.Solid)


def faces(shape) -> list:
    return _explore(shape, TopAbs_FACE, downcast.Face)


def edges(shape) -> list:
    return _explore(shape, TopAbs_EDGE, downcast.Edge)


def vertices(shape) -> list:
    return _explore(shape, TopAbs_VERTEX, downcast.Vertex)


def volume_mm3(shape) -> float:
    """Exact B-rep volume (R04: relative error 1.8e-16 on a tube)."""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(occ(shape), props)
    return float(props.Mass())


@contextlib.contextmanager
def quiet():
    """Silence OCCT while it works. Its transfer statistics and the output path go
    through the default messenger's printers; with them removed, nothing is written.
    File descriptors are left alone."""
    messenger = Message.DefaultMessenger_s()
    printers = list(messenger.Printers())
    for printer in printers:
        messenger.RemovePrinter(printer)
    try:
        yield
    finally:
        for printer in printers:
            messenger.AddPrinter(printer)
