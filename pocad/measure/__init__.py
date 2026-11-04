# kaynak: oguz-atolye tools/measure/__init__.py @ca27b1b (MIT, PoCAD'e taşındı)
"""pocad.measure: the measurement toolkit v1 (D-026, D-075): R04's twelve functions,
with validity and the STEP round trip in pocad.core, plus feature_census and
bore_census (R02), the mesh checks the reviewer needs for V-05, and the contact
and radial probes of L-22 (engaged_area, radial_extent, radial_profile), and the
print checks of GATES D-03a, D-03b and U-06 (overhang_census, flat_ceiling_spans,
min_wall_wide), a keep-in envelope about an axis (keepin_cone_free), and the arc a
slotted cylindrical band retains (retained_arc). Every function
measures the B-rep of a part that passed pocad.core.validity (a check script gates
that first), returns pocad.result.Result values, and reads no threshold; compare
with pocad.result.gate."""
from pocad.measure.assembly import clearance, engaged_area, interference
from pocad.measure.band import retained_arc
from pocad.measure.bridge import flat_ceiling_spans
from pocad.measure.draft import draft_angles, overhang_census, undercuts
from pocad.measure.features import (
                                    bore_census,
                                    feature_census,
                                    locate_bore,
                                    min_internal_radius,
                                    sharp_concave_edge_count,
                                    sharp_concave_edges,
)
from pocad.measure.keepin import keepin_cone_free
from pocad.measure.props import envelope, mass_properties
from pocad.measure.radial import radial_extent, radial_profile
from pocad.measure.wall import mesh_census, mesh_deviation, min_wall, min_wall_mesh, min_wall_wide

__all__ = ["bore_census", "clearance", "draft_angles", "engaged_area", "envelope", "feature_census",
           "flat_ceiling_spans", "interference", "keepin_cone_free", "locate_bore", "mass_properties",
           "mesh_census", "mesh_deviation", "min_internal_radius", "min_wall", "min_wall_mesh", "min_wall_wide",
           "overhang_census", "radial_extent", "radial_profile", "retained_arc", "sharp_concave_edge_count",
           "sharp_concave_edges", "undercuts"]
