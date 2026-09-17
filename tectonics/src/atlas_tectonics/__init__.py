"""Atlas remake: isolated mathematical foundations, WORKING NON-CANON.

Vibe-coded with OpenAI ChatGPT/Codex under the owner's direction.
No imports, migration or replacement of historical Atlas implementations.
"""
from ._validation import TectonicsError
from .parameters import FlexureParameters, PeriodicGrid1D, ThermalParameters, identity
from .kinematics import BoundaryMotion, Rotation, boundary_motion, rigid_velocity
from .transport import TransportResult, advect_thickness
from .thermal import half_space_temperature
from .flexure import PeriodicFlexure

__version__ = "0.1.0.dev10"
__all__ = ["TectonicsError", "FlexureParameters", "PeriodicGrid1D", "ThermalParameters",
           "identity", "BoundaryMotion", "Rotation", "boundary_motion", "rigid_velocity",
           "TransportResult", "advect_thickness", "half_space_temperature", "PeriodicFlexure"]

from .regional import (RegionalGrid1D, TransportBoundary, RegionalTransportResult,
                       TransportStepLimit, advect_regional, transport_timestep_limit)
__all__ += ["RegionalGrid1D", "TransportBoundary", "RegionalTransportResult",
            "TransportStepLimit", "advect_regional", "transport_timestep_limit"]

from .materials import (MaterialCohort, MaterialState, MaterialBoundary, MaterialEvent,
                        MaterialTransportResult, MaterialEventResult, advect_materials,
                        apply_material_event, register_cohorts, save_material_state,
                        load_material_state, material_timestep_limit)
__all__ += ["MaterialCohort", "MaterialState", "MaterialBoundary", "MaterialEvent",
            "MaterialTransportResult", "MaterialEventResult", "advect_materials",
            "apply_material_event", "register_cohorts", "save_material_state", "load_material_state", "material_timestep_limit"]

from .mesh import ColumnGrid1D
from .remapping import (RemapPlan, to_column_state, remap_materials, advect_ale, ale_timestep_limit)
from .topology import (PlateRecord, BlockRecord, BoundaryRecord, PlateTopology1D, TectonicState1D,
    split_block, merge_blocks, reassign_blocks, change_boundary, move_partition, advance_plate_state,
    regrid_plate_state, apply_plate_material_event, save_tectonic_state, load_tectonic_state)
from .markers import (MaterialMarkers1D, move_material_markers, save_material_markers, load_material_markers)
__all__ += ["ColumnGrid1D", "RemapPlan", "to_column_state", "remap_materials", "advect_ale", "ale_timestep_limit",
    "PlateRecord", "BlockRecord", "BoundaryRecord", "PlateTopology1D", "TectonicState1D",
    "split_block", "merge_blocks", "reassign_blocks", "change_boundary", "move_partition", "advance_plate_state",
    "regrid_plate_state", "apply_plate_material_event", "save_tectonic_state", "load_tectonic_state",
    "MaterialMarkers1D", "move_material_markers", "save_material_markers", "load_material_markers"]
