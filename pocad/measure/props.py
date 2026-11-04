# kaynak: oguz-atolye tools/measure/props.py @ca27b1b (MIT, PoCAD'e taşındı)
"""Envelope and mass properties (R04 functions 9 and 12, L-12).

The envelope reports size and position separately: a cavity drifted off its
datum because one figure mixed the two (L-12). Bed fit is the caller's gate on the
sizes against a machine profile. Mass needs a density, which comes from the spec's
ledger; nothing here assumes a material.
"""
from __future__ import annotations

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from pocad.core.shapes import occ, solids
from pocad.result import Result, measurement_set

AXES = ("x", "y", "z")
ENVELOPE = {f"{what}_{axis}": (f"envelope_{what}_{axis}", "mm")
            for what in ("size", "min", "max") for axis in AXES}
MASS = {"volume": ("mass_volume", "mm3"), "mass": ("mass_mass", "g"),
        **{f"com_{axis}": (f"mass_com_{axis}", "mm") for axis in AXES}}


@measurement_set("envelope", ENVELOPE)
def envelope(shape) -> dict[str, Result]:
    """size_x/y/z and min_/max_x/y/z in mm, from the exact (optimal) bounding box."""
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(occ(shape), box, False, False)
    if box.IsVoid():
        raise ValueError("empty shape")
    low, high = box.CornerMin(), box.CornerMax()
    lo, hi = (low.X(), low.Y(), low.Z()), (high.X(), high.Y(), high.Z())
    out = {}
    for i, axis in enumerate(AXES):
        out[f"size_{axis}"] = Result(f"envelope_size_{axis}", hi[i] - lo[i], "mm")
        out[f"min_{axis}"] = Result(f"envelope_min_{axis}", lo[i], "mm")
        out[f"max_{axis}"] = Result(f"envelope_max_{axis}", hi[i], "mm")
    return out


@measurement_set("mass_properties", MASS)
def mass_properties(shape, density_kg_m3: float) -> dict[str, Result]:
    """volume (mm³), mass (g) at the given density, and the centre of mass (mm), of
    the shape's solids."""
    if not density_kg_m3 > 0:
        raise ValueError("density must be positive, in kg/m³")
    found = solids(shape)
    if not found:
        raise ValueError("no solid")
    props = GProp_GProps()                    # solids only: a stray face would add volume
    for solid in found:
        BRepGProp.VolumeProperties_s(solid, props)
    volume = float(props.Mass())
    centre = props.CentreOfMass()
    params = {"density_kg_m3": density_kg_m3}
    return {"volume": Result("mass_volume", volume, "mm3"),
            "mass": Result("mass_mass", volume * density_kg_m3 * 1e-6, "g", params=params),
            "com_x": Result("mass_com_x", centre.X(), "mm"),
            "com_y": Result("mass_com_y", centre.Y(), "mm"),
            "com_z": Result("mass_com_z", centre.Z(), "mm")}
