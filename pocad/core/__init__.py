# kaynak: oguz-atolye tools/core/__init__.py @ca27b1b (MIT, PoCAD'e taşındı)
"""pocad.core: the three-part validity check, the one STEP writer, the STL writer,
the fail-closed boolean volume, and the fillet ladder. Imports build123d and OCP
(requirements-cad.txt). OCP 8 names come from pocad._ocp.

Comment ids such as D-024, R04, L-21 or U-17 refer to oguz-atolye's decision log and
research reports, kept so each rule can be traced to its source."""
from pocad.core.boolean import common_volume
from pocad.core.fillet import Filleted, fillet_ladder
from pocad.core.mesh import mesh_sagitta, write_stl
from pocad.core.shapes import solids, volume_mm3
from pocad.core.step import (
                             ExportError,
                             Written,
                             compare_step,
                             read_header,
                             read_length_unit,
                             read_schema,
                             read_step,
                             step_roundtrip,
                             write_step,
)
from pocad.core.validity import brep_valid, naked_edges, solid_count, validity

__all__ = ["ExportError", "Filleted", "Written", "brep_valid", "common_volume", "compare_step",
           "fillet_ladder", "mesh_sagitta", "naked_edges", "read_header", "read_length_unit",
           "read_schema", "read_step", "solid_count", "solids", "step_roundtrip", "validity",
           "volume_mm3", "write_step", "write_stl"]
