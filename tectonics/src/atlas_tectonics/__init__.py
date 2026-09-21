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

__version__ = "0.1.0.dev42"
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

# W01 stage 1: coordinate/unit conventions only, not plate polygons or forcing.
from .coordinates import (SphericalFrame, LocalCartesianFrame, convert_angles,
                          convert_lengths, east_south_up_to_enu, enu_to_east_south_up)
from .timebase import (TimeUnit, TimeAxis, EpochOffset, SECOND, JULIAN_YEAR,
                       JULIAN_MEGAYEAR, advance_time)
__all__ += ["SphericalFrame", "LocalCartesianFrame", "convert_angles", "convert_lengths",
            "east_south_up_to_enu", "enu_to_east_south_up", "TimeUnit", "TimeAxis",
            "EpochOffset", "SECOND", "JULIAN_YEAR", "JULIAN_MEGAYEAR", "advance_time"]

from .geometry import PlanarGeometry, GeometryLimits, GeometryError, geometry_runtime
from .spherical_geometry import SphericalChart, SphericalGeometry
from .geometry_index import GeometryFeature, GeometryIndex, GeometryHits, CoverageReport, audit_coverage, save_geometry, load_geometry
__all__ += ["PlanarGeometry", "GeometryLimits", "GeometryError", "geometry_runtime",
    "SphericalChart", "SphericalGeometry", "GeometryFeature", "GeometryIndex",
    "GeometryHits", "CoverageReport", "audit_coverage", "save_geometry", "load_geometry"]

# W01 stage 3: static shared boundaries; no generated plate motion.
from .boundaries import (BoundaryRegion, SharedBoundary, BoundaryJunction, BoundaryFrames,
    BoundaryKinematics, BoundaryNetwork, build_boundary_network,
    save_boundary_network, load_boundary_network)
__all__ += ["BoundaryRegion", "SharedBoundary", "BoundaryJunction", "BoundaryFrames",
    "BoundaryKinematics", "BoundaryNetwork", "build_boundary_network",
    "save_boundary_network", "load_boundary_network"]

# W01 stage 3B: complete static spherical ownership, not global material physics.
from .spherical_atlas import (SphericalPatch, SphericalAtlas, AtlasHits, SphericalAtlasIndex,
    build_spherical_atlas, stitch_spherical_networks, save_spherical_atlas, load_spherical_atlas)
__all__ += ["SphericalPatch", "SphericalAtlas", "AtlasHits", "SphericalAtlasIndex",
    "build_spherical_atlas", "stitch_spherical_networks", "save_spherical_atlas", "load_spherical_atlas"]

# W01 3C: valid starting partitions, not a geological-history generator.
from .planetary_generation import (PlanetPartitionSettings, PlanetaryPartitionPlan,
    PartitionCandidateError, PartitionGenerationError, prepare_planetary_partition,
    generate_planetary_partition, repatch_planetary_partition, generated_partition_id)
__all__ += ["PlanetPartitionSettings", "PlanetaryPartitionPlan", "PartitionCandidateError",
    "PartitionGenerationError", "prepare_planetary_partition", "generate_planetary_partition",
    "repatch_planetary_partition", "generated_partition_id"]

# W01 stage 4: geological input descriptions, not sampling or thermal evolution.
from .geological_records import (GeologyError, GeologySource, MaterialDefinition,
    CohortDescription, ThermalInitialProfile, LayerComponent, GeologicalLayer,
    ColumnDescription, SurfaceSelector, GeologicalProvince, FaultDescription,
    WeakZoneDescription, FeaturePrecedence)
from .geological_case import (GeologyLimits, FeatureGeometry, ProvinceResolution,
    UnresolvedGeology, GeologicalCase, save_geological_case, load_geological_case)
__all__ += ["GeologyError", "GeologySource", "MaterialDefinition", "CohortDescription",
    "ThermalInitialProfile", "LayerComponent", "GeologicalLayer", "ColumnDescription",
    "SurfaceSelector", "GeologicalProvince", "FaultDescription", "WeakZoneDescription",
    "FeaturePrecedence", "GeologyLimits", "FeatureGeometry", "ProvinceResolution",
    "UnresolvedGeology", "GeologicalCase", "save_geological_case", "load_geological_case"]

from .material_library import (MaterialLibraryError, MaterialReferenceSource, PropertyDatum,
    EarthMaterialProfile, EarthMaterialLibrary, SedimentMatrixRecipe, MaterialBlend,
    PreparedMaterialTable, RadiogenicAssay, earth_material_library, mix_materials,
    sediment_matrix, save_material_library, load_material_library, resolve_geological_layer)
__all__ += ["MaterialLibraryError", "MaterialReferenceSource", "PropertyDatum",
    "EarthMaterialProfile", "EarthMaterialLibrary", "SedimentMatrixRecipe", "MaterialBlend",
    "PreparedMaterialTable", "RadiogenicAssay", "earth_material_library", "mix_materials",
    "sediment_matrix", "save_material_library", "load_material_library", "resolve_geological_layer"]

from .plate_layout import (PlateLayoutSettings, generate_plate_layout, layout_metrics,
    plate_outline_cycles, evaluate_plate_kinematics, require_geological_layout_acceptance)
__all__ += ["PlateLayoutSettings", "generate_plate_layout", "layout_metrics",
    "plate_outline_cycles", "evaluate_plate_kinematics", "require_geological_layout_acceptance"]

# 3C-R2: plate-independent initial geology and bounded W01 stage-5 sampling.
# These inputs/samplers are not thermal evolution, rheology or generated plates.
from .geological_domain import GeologicalDomain
from .precursor import (InputOrigin, CoolingHistory, MaterialVolumeBasis,
    SeededSpatialPrior, InitialScalarField, SubsurfaceBody, PrecursorState, InitialConditionState,
    save_precursor_state, load_precursor_state)
from .precursor_sampling import (PrecursorSamplingLimits, InitialSamplingCell,
    InitialSamples, PreparedPrecursor, save_initial_samples, load_initial_samples)
__all__ += ['GeologicalDomain', 'InputOrigin', 'CoolingHistory', 'MaterialVolumeBasis',
    'SeededSpatialPrior', 'InitialScalarField', 'SubsurfaceBody', 'PrecursorState', 'InitialConditionState',
    'save_precursor_state', 'load_precursor_state', 'PrecursorSamplingLimits',
    'InitialSamplingCell', 'InitialSamples', 'PreparedPrecursor',
    'save_initial_samples', 'load_initial_samples']

from .precursor_execution import PrecursorExecutionPolicy
__all__ += ["PrecursorExecutionPolicy"]

# R3: local physical closure and tested execution; no coupled PDE solver.
from .constitutive import (ConstitutiveLimits, DiffusiveScales, RheologyProfile,
    reference_rheology, evaluate_rheology, advance_memory, strain_rate_invariant,
    BoussinesqMaterial, boussinesq_response, stress_and_dissipation)
from .constitutive_execution import PreparedRheology, LawResult, save_law_result, load_law_result
from .damage_regularisation import DamageLengthScale, PreparedDamageRegularisation
__all__ += ["ConstitutiveLimits", "DiffusiveScales", "RheologyProfile", "reference_rheology",
    "evaluate_rheology", "advance_memory", "strain_rate_invariant", "BoussinesqMaterial", "stress_and_dissipation",
    "boussinesq_response", "PreparedRheology", "LawResult", "save_law_result", "load_law_result",
    "DamageLengthScale", "PreparedDamageRegularisation"]

# R4 is in progress: constant-viscosity mechanical increment only.
from .stokes import StokesBox2D, StokesSolvePolicy, face_force_from_density
from .stokes_execution import (PreparedStokes2D, StokesSolution,
                               save_stokes_solution, load_stokes_solution)
__all__ += ["StokesBox2D", "StokesSolvePolicy", "face_force_from_density",
            "PreparedStokes2D", "StokesSolution", "save_stokes_solution", "load_stokes_solution"]

from .thermochemical import ThermalBoundary2D, ThermochemicalPolicy, ThermochemicalProblem
from .thermochemical_execution import (ThermochemicalState, ThermochemicalStep,
    PrescribedMACVelocity, PreparedThermochemical2D, CourantLimitError,
    save_thermochemical_state, load_thermochemical_state)
__all__ += ["ThermalBoundary2D", "ThermochemicalPolicy", "ThermochemicalProblem",
    "ThermochemicalState", "ThermochemicalStep", "PrescribedMACVelocity",
    "PreparedThermochemical2D", "CourantLimitError", "save_thermochemical_state", "load_thermochemical_state"]

# R4.3 variable-stress and yielding mechanics; full R4 benchmark acceptance remains open.
from .variable_stokes import NonlinearStokesPolicy
from .variable_stokes_execution import (PreparedVariableStokes2D, VariableStokesSolution, NonlinearStokesGuess,
    save_variable_stokes_solution, load_variable_stokes_solution)
__all__ += ['NonlinearStokesPolicy', 'PreparedVariableStokes2D', 'VariableStokesSolution', 'NonlinearStokesGuess',
            'save_variable_stokes_solution', 'load_variable_stokes_solution']

# R4.4 diagnostics and explicit published cases; acceptance remains independently gated.
from .convection_benchmark import (TosiCase, tosi_initial_temperature, tosi_endpoint_flow,
    convection_diagnostics, tosi_state_diagnostics, steady_window, periodic_window,
    refinement_differences)
__all__ += ['TosiCase', 'tosi_initial_temperature', 'tosi_endpoint_flow',
    'convection_diagnostics', 'tosi_state_diagnostics', 'steady_window',
    'periodic_window', 'refinement_differences']

# Explicit safeguarded acceleration; Picard remains the default.
from .anderson import AndersonPolicy
from .preconditioner_reuse import PreconditionerReusePolicy
__all__ += ["AndersonPolicy"]

from .adaptive_inner import AdaptiveInnerPolicy

# W01 Stage 6: explicit checked kinematic reduction, not geological evolution.
from .regional_forcing import (
    MotionReductionError, PrescribedPlateMotion, PlanarRegionalSection,
    SphericalRegionalSection, RegionalReduction, RegionalMotionDefinition,
    SectionMotionSamples, RegionalFaceForcing, PreparedRegionalForcing,
    save_regional_forcing, load_regional_forcing,
)
__all__ += ["MotionReductionError", "PrescribedPlateMotion", "PlanarRegionalSection",
            "SphericalRegionalSection", "RegionalReduction", "RegionalMotionDefinition",
            "SectionMotionSamples", "RegionalFaceForcing", "PreparedRegionalForcing",
            "save_regional_forcing", "load_regional_forcing"]
