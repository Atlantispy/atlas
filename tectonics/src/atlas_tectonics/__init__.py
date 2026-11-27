"""Atlas remake: isolated mathematical foundations, WORKING NON-CANON.

Vibe-coded with OpenAI ChatGPT/Codex under the owner's direction.
No imports, migration or replacement of historical Atlas implementations.
"""
import importlib.util as _util
import sys as _sys
from pathlib import Path as _Path

if _util.find_spec('atlas_shared') is None:  # checkout and desktop payload both hold shared/src beside tectonics/
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'shared' / 'src'))
del _util, _sys, _Path

from ._validation import TectonicsError
from atlas_tectonics.planet.parameters import FlexureParameters, PeriodicGrid1D, ThermalParameters, PlateCoolingParameters, identity
from atlas_tectonics.kinematics import BoundaryMotion, Rotation, boundary_motion, rigid_velocity
from atlas_tectonics.crust.transport import TransportResult, advect_thickness
from atlas_tectonics.thermal.thermal import half_space_temperature
from atlas_tectonics.plates.cooling import (finite_plate_temperature, plate_cooling_heat,
                            ThermalAgeColumns, plate_cooling_columns)
from atlas_tectonics.thermal.thermal_support import (ThermalSupportParameters, thermal_density,
    thermal_column_response, plate_thermal_response, ThermalSupportColumns,
    thermal_support_columns)
from atlas_tectonics.mechanics.compaction import CompactionParameters, compaction_response
from atlas_tectonics.mechanics.compaction_columns import (GrainComponent, CompactionParcel, DrainedCompactionConditions,
    CompactionState, CompactionTransition, compaction_geometry, advance_compaction,
    compaction_from_geological_column, save_compaction_state, load_compaction_state)
from atlas_tectonics.mechanics.flexure import PeriodicFlexure
from atlas_tectonics.mechanics.column_loads import LoadSupport, LoadPhase, ColumnLoadState, column_load_change

__version__ = "0.1.0.dev66"
__all__ = ["TectonicsError", "FlexureParameters", "PeriodicGrid1D", "ThermalParameters",
           "identity", "BoundaryMotion", "Rotation", "boundary_motion", "rigid_velocity",
           "TransportResult", "advect_thickness", "half_space_temperature", "PeriodicFlexure"]
__all__ += ['PlateCoolingParameters', 'finite_plate_temperature', 'plate_cooling_heat',
            'ThermalAgeColumns', 'plate_cooling_columns']
__all__ += ['ThermalSupportParameters', 'thermal_density', 'thermal_column_response',
            'plate_thermal_response', 'ThermalSupportColumns', 'thermal_support_columns']
__all__ += ['CompactionParameters', 'compaction_response', 'GrainComponent', 'CompactionParcel',
    'DrainedCompactionConditions', 'CompactionState', 'CompactionTransition',
    'compaction_geometry', 'advance_compaction', 'compaction_from_geological_column',
    'save_compaction_state', 'load_compaction_state']
__all__ += ['LoadSupport', 'LoadPhase', 'ColumnLoadState', 'column_load_change']

from atlas_tectonics.regional.regional import (RegionalGrid1D, TransportBoundary, RegionalTransportResult,
                       TransportStepLimit, advect_regional, transport_timestep_limit)
__all__ += ["RegionalGrid1D", "TransportBoundary", "RegionalTransportResult",
            "TransportStepLimit", "advect_regional", "transport_timestep_limit"]

from atlas_tectonics.materials.materials import (MaterialCohort, MaterialState, MaterialBoundary, MaterialEvent,
                        MaterialTransportResult, MaterialEventResult, advect_materials,
                        apply_material_event, register_cohorts, save_material_state,
                        load_material_state, material_timestep_limit)
__all__ += ["MaterialCohort", "MaterialState", "MaterialBoundary", "MaterialEvent",
            "MaterialTransportResult", "MaterialEventResult", "advect_materials",
            "apply_material_event", "register_cohorts", "save_material_state", "load_material_state", "material_timestep_limit"]

from atlas_tectonics.planet.mesh import ColumnGrid1D
from atlas_tectonics.planet.remapping import (RemapPlan, to_column_state, remap_materials, advect_ale, ale_timestep_limit)
from atlas_tectonics.planet.topology import (PlateRecord, BlockRecord, BoundaryRecord, PlateTopology1D, TectonicState1D,
    split_block, merge_blocks, reassign_blocks, change_boundary, move_partition, advance_plate_state,
    regrid_plate_state, apply_plate_material_event, save_tectonic_state, load_tectonic_state)
from atlas_tectonics.planet.markers import (MaterialMarkers1D, move_material_markers, save_material_markers, load_material_markers)
__all__ += ["ColumnGrid1D", "RemapPlan", "to_column_state", "remap_materials", "advect_ale", "ale_timestep_limit",
    "PlateRecord", "BlockRecord", "BoundaryRecord", "PlateTopology1D", "TectonicState1D",
    "split_block", "merge_blocks", "reassign_blocks", "change_boundary", "move_partition", "advance_plate_state",
    "regrid_plate_state", "apply_plate_material_event", "save_tectonic_state", "load_tectonic_state",
    "MaterialMarkers1D", "move_material_markers", "save_material_markers", "load_material_markers"]

# W01 stage 1: coordinate/unit conventions only, not plate polygons or forcing.
from atlas_tectonics.planet.coordinates import (SphericalFrame, LocalCartesianFrame, convert_angles,
                          convert_lengths, east_south_up_to_enu, enu_to_east_south_up)
from atlas_tectonics.planet.timebase import (TimeUnit, TimeAxis, EpochOffset, SECOND, JULIAN_YEAR,
                       JULIAN_MEGAYEAR, advance_time)
__all__ += ["SphericalFrame", "LocalCartesianFrame", "convert_angles", "convert_lengths",
            "east_south_up_to_enu", "enu_to_east_south_up", "TimeUnit", "TimeAxis",
            "EpochOffset", "SECOND", "JULIAN_YEAR", "JULIAN_MEGAYEAR", "advance_time"]

from atlas_tectonics.planet.geometry import PlanarGeometry, GeometryLimits, GeometryError, geometry_runtime
from atlas_tectonics.planet.spherical_geometry import SphericalChart, SphericalGeometry
from atlas_tectonics.planet.geometry_index import GeometryFeature, GeometryIndex, GeometryHits, CoverageReport, audit_coverage, save_geometry, load_geometry
__all__ += ["PlanarGeometry", "GeometryLimits", "GeometryError", "geometry_runtime",
    "SphericalChart", "SphericalGeometry", "GeometryFeature", "GeometryIndex",
    "GeometryHits", "CoverageReport", "audit_coverage", "save_geometry", "load_geometry"]

# W01 stage 3: static shared boundaries; no generated plate motion.
from atlas_tectonics.plates.boundaries import (BoundaryRegion, SharedBoundary, BoundaryJunction, BoundaryFrames,
    BoundaryKinematics, BoundaryNetwork, build_boundary_network,
    save_boundary_network, load_boundary_network)
__all__ += ["BoundaryRegion", "SharedBoundary", "BoundaryJunction", "BoundaryFrames",
    "BoundaryKinematics", "BoundaryNetwork", "build_boundary_network",
    "save_boundary_network", "load_boundary_network"]

# W01 stage 3B: complete static spherical ownership, not global material physics.
from atlas_tectonics.planet.spherical_atlas import (SphericalPatch, SphericalAtlas, AtlasHits, SphericalAtlasIndex,
    build_spherical_atlas, stitch_spherical_networks, save_spherical_atlas, load_spherical_atlas)
__all__ += ["SphericalPatch", "SphericalAtlas", "AtlasHits", "SphericalAtlasIndex",
    "build_spherical_atlas", "stitch_spherical_networks", "save_spherical_atlas", "load_spherical_atlas"]

# W01 3C: valid starting partitions, not a geological-history generator.
from atlas_tectonics.planet.planetary_generation import (PlanetPartitionSettings, PlanetaryPartitionPlan,
    PartitionCandidateError, PartitionGenerationError, prepare_planetary_partition,
    generate_planetary_partition, repatch_planetary_partition, generated_partition_id)
__all__ += ["PlanetPartitionSettings", "PlanetaryPartitionPlan", "PartitionCandidateError",
    "PartitionGenerationError", "prepare_planetary_partition", "generate_planetary_partition",
    "repatch_planetary_partition", "generated_partition_id"]

# W01 stage 4: geological input descriptions, not sampling or thermal evolution.
from atlas_tectonics.history.geological_records import (GeologyError, GeologySource, MaterialDefinition,
    CohortDescription, ThermalInitialProfile, LayerComponent, GeologicalLayer,
    ColumnDescription, SurfaceSelector, GeologicalProvince, FaultDescription,
    WeakZoneDescription, FeaturePrecedence)
from atlas_tectonics.history.geological_case import (GeologyLimits, FeatureGeometry, ProvinceResolution,
    UnresolvedGeology, GeologicalCase, save_geological_case, load_geological_case)
__all__ += ["GeologyError", "GeologySource", "MaterialDefinition", "CohortDescription",
    "ThermalInitialProfile", "LayerComponent", "GeologicalLayer", "ColumnDescription",
    "SurfaceSelector", "GeologicalProvince", "FaultDescription", "WeakZoneDescription",
    "FeaturePrecedence", "GeologyLimits", "FeatureGeometry", "ProvinceResolution",
    "UnresolvedGeology", "GeologicalCase", "save_geological_case", "load_geological_case"]

from atlas_tectonics.materials.material_library import (MaterialLibraryError, MaterialReferenceSource, PropertyDatum,
    EarthMaterialProfile, EarthMaterialLibrary, SedimentMatrixRecipe, MaterialBlend,
    PreparedMaterialTable, RadiogenicAssay, earth_material_library, mix_materials,
    sediment_matrix, save_material_library, load_material_library, resolve_geological_layer)
__all__ += ["MaterialLibraryError", "MaterialReferenceSource", "PropertyDatum",
    "EarthMaterialProfile", "EarthMaterialLibrary", "SedimentMatrixRecipe", "MaterialBlend",
    "PreparedMaterialTable", "RadiogenicAssay", "earth_material_library", "mix_materials",
    "sediment_matrix", "save_material_library", "load_material_library", "resolve_geological_layer"]

from atlas_tectonics.plates.layout import (PlateLayoutSettings, generate_plate_layout, layout_metrics,
    plate_outline_cycles, evaluate_plate_kinematics, require_geological_layout_acceptance)
__all__ += ["PlateLayoutSettings", "generate_plate_layout", "layout_metrics",
    "plate_outline_cycles", "evaluate_plate_kinematics", "require_geological_layout_acceptance"]

# 3C-R2: plate-independent initial geology and bounded W01 stage-5 sampling.
# These inputs/samplers are not thermal evolution, rheology or generated plates.
from atlas_tectonics.history.geological_domain import GeologicalDomain
from atlas_tectonics.crust.precursor import (InputOrigin, CoolingHistory, MaterialVolumeBasis,
    SeededSpatialPrior, InitialScalarField, SubsurfaceBody, PrecursorState, InitialConditionState,
    save_precursor_state, load_precursor_state)
from atlas_tectonics.crust.precursor_sampling import (PrecursorSamplingLimits, InitialSamplingCell,
    InitialSamples, PreparedPrecursor, save_initial_samples, load_initial_samples)
__all__ += ['GeologicalDomain', 'InputOrigin', 'CoolingHistory', 'MaterialVolumeBasis',
    'SeededSpatialPrior', 'InitialScalarField', 'SubsurfaceBody', 'PrecursorState', 'InitialConditionState',
    'save_precursor_state', 'load_precursor_state', 'PrecursorSamplingLimits',
    'InitialSamplingCell', 'InitialSamples', 'PreparedPrecursor',
    'save_initial_samples', 'load_initial_samples']

from atlas_tectonics.crust.precursor_execution import PrecursorExecutionPolicy
__all__ += ["PrecursorExecutionPolicy"]

# R3: local physical closure and tested execution; no coupled PDE solver.
from atlas_tectonics.materials.constitutive import (ConstitutiveLimits, DiffusiveScales, RheologyProfile,
    reference_rheology, evaluate_rheology, advance_memory, strain_rate_invariant,
    BoussinesqMaterial, boussinesq_response, stress_and_dissipation)
from atlas_tectonics.materials.constitutive_execution import PreparedRheology, LawResult, save_law_result, load_law_result
from atlas_tectonics.materials.damage_regularisation import DamageLengthScale, PreparedDamageRegularisation
__all__ += ["ConstitutiveLimits", "DiffusiveScales", "RheologyProfile", "reference_rheology",
    "evaluate_rheology", "advance_memory", "strain_rate_invariant", "BoussinesqMaterial", "stress_and_dissipation",
    "boussinesq_response", "PreparedRheology", "LawResult", "save_law_result", "load_law_result",
    "DamageLengthScale", "PreparedDamageRegularisation"]

# R4 is in progress: constant-viscosity mechanical increment only.
from atlas_tectonics.mechanics.stokes import StokesBox2D, StokesSolvePolicy, face_force_from_density
from atlas_tectonics.mechanics.stokes_execution import (PreparedStokes2D, StokesSolution,
                               save_stokes_solution, load_stokes_solution)
__all__ += ["StokesBox2D", "StokesSolvePolicy", "face_force_from_density",
            "PreparedStokes2D", "StokesSolution", "save_stokes_solution", "load_stokes_solution"]

from atlas_tectonics.thermal.thermochemical import ThermalBoundary2D, ThermochemicalPolicy, ThermochemicalProblem
from atlas_tectonics.thermal.thermochemical_execution import (ThermochemicalState, ThermochemicalStep,
    PrescribedMACVelocity, PreparedThermochemical2D, CourantLimitError,
    save_thermochemical_state, load_thermochemical_state)
__all__ += ["ThermalBoundary2D", "ThermochemicalPolicy", "ThermochemicalProblem",
    "ThermochemicalState", "ThermochemicalStep", "PrescribedMACVelocity",
    "PreparedThermochemical2D", "CourantLimitError", "save_thermochemical_state", "load_thermochemical_state"]

# R4.3 variable-stress and yielding mechanics; full R4 benchmark acceptance remains open.
from atlas_tectonics.mechanics.variable_stokes import NonlinearStokesPolicy
from atlas_tectonics.mechanics.variable_stokes_execution import (PreparedVariableStokes2D, VariableStokesSolution, NonlinearStokesGuess,
    save_variable_stokes_solution, load_variable_stokes_solution)
__all__ += ['NonlinearStokesPolicy', 'PreparedVariableStokes2D', 'VariableStokesSolution', 'NonlinearStokesGuess',
            'save_variable_stokes_solution', 'load_variable_stokes_solution']

# R4.4 diagnostics and explicit published cases; acceptance remains independently gated.
from atlas_tectonics.thermal.convection_benchmark import (TosiCase, tosi_initial_temperature, tosi_endpoint_flow,
    convection_diagnostics, tosi_state_diagnostics, steady_window, periodic_window,
    refinement_differences)
__all__ += ['TosiCase', 'tosi_initial_temperature', 'tosi_endpoint_flow',
    'convection_diagnostics', 'tosi_state_diagnostics', 'steady_window',
    'periodic_window', 'refinement_differences']

# Explicit safeguarded acceleration; Picard remains the default.
from atlas_tectonics.mechanics.anderson import AndersonPolicy
from atlas_tectonics.mechanics.preconditioner_reuse import PreconditionerReusePolicy
__all__ += ["AndersonPolicy"]

from atlas_tectonics.mechanics.adaptive_inner import AdaptiveInnerPolicy

# W01 Stage 6: explicit checked kinematic reduction, not geological evolution.
from atlas_tectonics.regional.forcing import (
    MotionReductionError, PrescribedPlateMotion, PlanarRegionalSection,
    SphericalRegionalSection, RegionalReduction, RegionalMotionDefinition,
    SectionMotionSamples, RegionalFaceForcing, PreparedRegionalForcing,
    save_regional_forcing, load_regional_forcing,
)
__all__ += ["MotionReductionError", "PrescribedPlateMotion", "PlanarRegionalSection",
            "SphericalRegionalSection", "RegionalReduction", "RegionalMotionDefinition",
            "SectionMotionSamples", "RegionalFaceForcing", "PreparedRegionalForcing",
            "save_regional_forcing", "load_regional_forcing"]

# W01 Stage 7: source-bound initialisation and bounded cohort transport.
from atlas_tectonics.regional.workflow_geometry import RegionalColumnSupport
from atlas_tectonics.regional.workflow import (PoreFluidCohort, RegionalWorkflowState,
    PreparedRegionalWorkflow, save_regional_workflow, load_regional_workflow)
__all__ += ["RegionalColumnSupport", "PoreFluidCohort", "RegionalWorkflowState",
            "PreparedRegionalWorkflow", "save_regional_workflow", "load_regional_workflow"]

from atlas_tectonics.integration.workflows.drained_column_workflow import (W03ExecutionContext, W03ThermalBinding, W03ColumnState, initialise_w03_columns,
    advance_w03_columns, evolve_w03_columns, save_w03_columns, load_w03_columns)
__all__ += ["W03ExecutionContext", "W03ThermalBinding", "W03ColumnState", "initialise_w03_columns",
            "advance_w03_columns", "evolve_w03_columns", "save_w03_columns", "load_w03_columns"]

from atlas_tectonics.mechanics.finite_flexure import FiniteRegionFlexure, FlexureBoundary1D
from atlas_tectonics.mechanics.variable_flexure import RigidityProfile1D, VariableFlexureAccuracy, VariableRigidityFlexure
__all__ += ['RigidityProfile1D','VariableFlexureAccuracy','VariableRigidityFlexure']
from atlas_tectonics.integration.workflows.prescribed_support_workflow import (W04SurfaceInputs, W04ExteriorLoads, W04SupportPolicy, W04SupportResult,
                          PreparedW04Support, project_w04_support)
__all__ += ["FiniteRegionFlexure", "FlexureBoundary1D", "W04SurfaceInputs", "W04ExteriorLoads", "W04SupportPolicy", "W04SupportResult",
            "PreparedW04Support", "project_w04_support"]

from atlas_tectonics.crust.extension import ListricGeometry, hangingwall_cell_means, PreparedListricExtension, ExtensionState
__all__ += ['ListricGeometry', 'hangingwall_cell_means', 'PreparedListricExtension', 'ExtensionState']
from atlas_tectonics.crust.extension_support import (ExtensionSupportPolicy, PreparedExtensionSupport,
                                ExtensionSupportResult, ContinuousCellMeanFlexure)
__all__ += ['ExtensionSupportPolicy', 'PreparedExtensionSupport',
            'ExtensionSupportResult', 'ContinuousCellMeanFlexure']
from atlas_tectonics.crust.extension_workflow import PreparedExtensionWorkflow, ExtensionWorkflowCheckpoint
__all__ += ['PreparedExtensionWorkflow', 'ExtensionWorkflowCheckpoint']

from atlas_tectonics.spreading.spreading import (RidgeMotion, SpreadingPhase, BirthStrip, SpreadingState,
                        ridge_cell_geometry, PreparedRidgeSpreading)
__all__ += ['RidgeMotion', 'SpreadingPhase', 'BirthStrip', 'SpreadingState',
            'ridge_cell_geometry', 'PreparedRidgeSpreading']

from atlas_tectonics.spreading.integrals import spreading_thermal_means
from atlas_tectonics.spreading.cooling import (OceanCoolingParameters, ThermalExport,
                               SpreadingThermalState, PreparedSpreadingCooling)
__all__ += ['spreading_thermal_means', 'OceanCoolingParameters', 'ThermalExport',
            'SpreadingThermalState', 'PreparedSpreadingCooling']

from atlas_tectonics.spreading.margin_cooling import PreparedMarginCooling, MarginThermalResult, MarginSupportResult
__all__ += ['PreparedMarginCooling', 'MarginThermalResult', 'MarginSupportResult']

from atlas_tectonics.spreading.history import (PlateReassignment, RidgeHistoryEvent, HistoryBirthStrip,
    HistoryExport, HistorySpreadingState, PreparedSpreadingHistory)
from atlas_tectonics.spreading.history_cooling import (HistoryThermalExport, HistoryThermalState,
    PreparedHistoryCooling)
__all__ += ['PlateReassignment', 'RidgeHistoryEvent', 'HistoryBirthStrip', 'HistoryExport',
            'HistorySpreadingState', 'PreparedSpreadingHistory', 'HistoryThermalExport',
            'HistoryThermalState', 'PreparedHistoryCooling']

from atlas_tectonics.integration.workflows.spreading_and_margin_workflow import MarginWorkflowPolicy, W06WorkflowCheckpoint, PreparedW06Workflow
__all__ += ['MarginWorkflowPolicy', 'W06WorkflowCheckpoint', 'PreparedW06Workflow']

# W07 step 2: source-bound steady regional mechanics, not geological evolution.
from atlas_tectonics.regional.execution import (RegionalMechanicsScales, RegionalReferencePressure,
    RegionalMechanicalSnapshot, PreparedRegionalStokes2D)
__all__ += ['RegionalMechanicsScales', 'RegionalReferencePressure',
            'RegionalMechanicalSnapshot', 'PreparedRegionalStokes2D']

from atlas_tectonics.regional.transport import (RectangularTransportGrid, HeatBoundary,
    PreparedHeatTransport, MaterialRegion2D, translate_material_regions)
from atlas_tectonics.regional.rheology import RegionalRheologyResult, solve_regional_rheology
from atlas_tectonics.regional.thermomechanical import (RegionalThermalBodyForce,
    RegionalThermomechanicalResult, temperature_stress_sites, advance_regional_thermomechanics)
__all__ += ['RectangularTransportGrid','HeatBoundary','PreparedHeatTransport',
    'MaterialRegion2D','translate_material_regions','RegionalRheologyResult',
    'solve_regional_rheology','RegionalThermalBodyForce','RegionalThermomechanicalResult',
    'temperature_stress_sites','advance_regional_thermomechanics']

from atlas_tectonics.regional.strength import DryStrengthProfile, RegionalStrengthResult, evaluate_dry_strength, solve_regional_strength
from atlas_tectonics.mechanics.free_surface import PreparedFreeSurface2D, FreeSurfaceAdvance
__all__ += ['DryStrengthProfile','RegionalStrengthResult','evaluate_dry_strength',
    'solve_regional_strength','PreparedFreeSurface2D','FreeSurfaceAdvance']

from atlas_tectonics.regional.geology import (GeologicalMaterialLaw, RegionalPhysicsOwnership,
    RegionalGeologicalInputs, bind_regional_geology)
from atlas_tectonics.integration.workflows.regional_mechanics_workflow import W07BoundaryMotion, W07WorkflowOutput, PreparedW07Workflow
__all__ += ['GeologicalMaterialLaw','RegionalPhysicsOwnership','RegionalGeologicalInputs',
    'bind_regional_geology','W07BoundaryMotion','W07WorkflowOutput','PreparedW07Workflow']
