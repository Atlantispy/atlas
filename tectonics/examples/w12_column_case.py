"""Public, bounded W01 -> W02 -> W03 case for the W12 assembly route.

All numbers are authored synthetic controls, not calibrated geology or Diadem
canon. The four-by-two metre strip and 100 km thermal plate deliberately serve
different supports. Only the top 100 m sediment stack is represented in W02.
Import with the public ``tectonics/src`` package available; no test helpers,
private data, saved states, downloads or implicit files are required.
"""
from __future__ import annotations

import numpy as np

from atlas_tectonics import (
    BoundaryRegion, BoussinesqMaterial, CohortDescription, ColumnDescription,
    CoolingHistory, FeaturePrecedence, GeologicalCase, GeologicalLayer,
    GeologicalProvince, GeologySource, InitialConditionState, InputOrigin,
    LayerComponent, MaterialCohort, MaterialDefinition, MaterialVolumeBasis,
    PlanarGeometry, PlanarRegionalSection, PlateCoolingParameters,
    PrescribedPlateMotion, RegionalColumnSupport, RegionalGrid1D,
    RegionalMotionDefinition, RegionalReduction, SurfaceSelector,
    ThermalInitialProfile, ThermalParameters, ThermalSupportParameters,
    build_boundary_network,
)
from atlas_tectonics.compaction import CompactionParameters
from atlas_tectonics.compaction_columns import DrainedCompactionConditions
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.regional_workflow import PoreFluidCohort, PreparedRegionalWorkflow
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.w03_workflow import initialise_w03_columns
from atlas_tectonics.w04_workflow import W04SurfaceInputs, W04SupportPolicy


def make_column_case(*, cells=8, budget=None):
    """Construct a stationary column root and two explicit continuation requests.

    ``budget`` is one shared finite WorkBudget (128 MiB by default), accounting
    component work rather than imposing an operating-system RSS limit. Returned
    states are caller-owned. Continuation and W04 projection belong to the caller;
    no scheduled interval is computed here. W03 effective stress is distinct from
    the additional external W04 pressure, which starts explicitly at zero.
    """
    if type(cells) is not int or not 5 <= cells <= 64:
        raise ValueError('cells must be an integer from 5 through 64 (W04 periodic minimum)')
    if budget is None:
        budget = WorkBudget(128 << 20)
    if not isinstance(budget, WorkBudget):
        raise TypeError('budget must be a finite WorkBudget')

    source_id = 'w12-public-synthetic'
    source_note = 'Authored synthetic W12 column control; uncalibrated WORKING NON-CANON.'
    source = GeologySource(source_id, 'synthetic', source_note)
    frame, epoch, datum = 'w12-synthetic-plane', 'w12-synthetic-epoch', 'local-surface'
    length_m, width_m, step_s = 4., 2., 1e12
    units = dict(length_unit='m', velocity_unit='m/s', angular_velocity_unit='rad/s')

    domain = PlanarGeometry.polygon(
        ((0., 0.), (length_m, 0.), (length_m, width_m), (0., width_m)),
        frame_id=frame, budget=budget)
    topology = build_boundary_network(
        domain, (BoundaryRegion('whole', 'stationary-plate', domain),), budget=budget)
    rock = MaterialDefinition('rock', 'solid', source_id, 2650., 3., 1000.,
                              0., 3e-5, 300., (0., 2000.))
    water = MaterialDefinition('water', 'fluid', source_id, 1000., .6, 4000.,
                               0., 0., 300.)
    upper = MaterialCohort('upper-solid', 'rock', 'authored-upper', -100.)
    lower = MaterialCohort('lower-solid', 'rock', 'authored-lower', -50.)
    pore = MaterialCohort('pore-water', 'water', 'authored-water', -100.)
    layers = (
        GeologicalLayer('upper', 'sediment', 40.,
                        (LayerComponent(upper.cohort_id, 1.),), .4, source_id),
        GeologicalLayer('lower', 'sediment', 60.,
                        (LayerComponent(lower.cohort_id, 1.),), .25, source_id),
        GeologicalLayer('crust', 'crust', 29900.,
                        (LayerComponent(upper.cohort_id, 1.),), 0., source_id),
        GeologicalLayer('mantle', 'lithospheric_mantle', 70000.,
                        (LayerComponent(upper.cohort_id, 1.),), 0., source_id),
    )
    column = ColumnDescription('column', 'continental', layers, 100000.,
                               'initial-thermal', source_id, fluid_material_id='water')
    initial_profile = ThermalInitialProfile(
        'initial-thermal', source_id, 'half_space', temperatures_k=(300., 1300.),
        diffusivity_m2_s=1e-6, cooling_start_time_s=0.)
    geology = GeologicalCase(
        'w12-public-column-v1', topology, time_s=0., epoch_id=epoch,
        depth_reference_id=datum, source_id=source_id, sources=(source,),
        materials=(rock, water),
        cohorts=(CohortDescription(upper, source_id), CohortDescription(lower, source_id)),
        columns=(column,), thermal_profiles=(initial_profile,),
        provinces=(GeologicalProvince('background', column.column_id,
                                      SurfaceSelector('domain'), source_id),),
        precedence=FeaturePrecedence(('background',)), budget=budget)
    described = InitialConditionState(
        geology, origins=(InputOrigin(source_id, 'authored', 'w12-public-column-v1'),),
        cooling_history=(CoolingHistory(initial_profile.profile_id, source_id, 0., None),),
        material_bases=(MaterialVolumeBasis('rock', 'grain', source_id),
                        MaterialVolumeBasis('water', 'fluid', source_id)), budget=budget)

    # W03 accepts stationary, unmixed W01/W02 roots. Zero motion is an explicit
    # supplied field, not an inferred force solution or an omitted W02 stage.
    motion = PrescribedPlateMotion(
        'stationary-plate', frame, epoch, 0., 'planar-rigid',
        (0., 0., 0.), (0., 0., 0.), (0., 0., 0.), source, **units)
    definition = RegionalMotionDefinition(
        topology, (motion,), epoch, 0., 2*step_s, 's', source)
    section = PlanarRegionalSection(
        'section', frame, epoch, 0., (0., width_m/2, 0.), (1., 0.), length_m,
        (0., 0., 0.), (0., 0., 0.), source, **units)
    fluid_cohorts = tuple(PoreFluidCohort(unit.unit_id, pore, source)
                          for unit in described.units if unit.layer.role == 'sediment')
    with PreparedRegionalWorkflow(
        described, definition, section,
        RegionalReduction('planar-columns', 'frozen-at-start', source, width_m),
        RegionalGrid1D(cells, length_m),
        RegionalColumnSupport('planar-strip', 0., 100., source),
        fluid_cohorts=fluid_cohorts, include_temperature=True,
        backend='reference', budget=budget,
    ) as workflow:
        material_root = workflow.initialise()

    compaction = CompactionParameters('w12-compaction', source_note,
                                     .1, .02, 1e5, 1e8, 0., .8)
    cooling = PlateCoolingParameters(
        ThermalParameters('w12-cooling', source_note, 300., 1300., 1e-6), 100000., 3.3)
    buoyancy = BoussinesqMaterial('w12-thermal-density', source_note,
        3300., 1000., 3.3, 3e-5, 1300., 0., 0., (300., 1300.), .05)
    diagnostic_support = ThermalSupportParameters(
        'initial-column-reference', source_note, datum, 'column-isostasy',
        3300., 1000., 10., .1)
    initial = initialise_w03_columns(
        material_root, column.column_id, {'upper': compaction, 'lower': compaction},
        subdivisions={'upper': 4, 'lower': 6},
        maximum_effective_stress_pa='normally-consolidated', top_effective_stress_pa=0.,
        conditions=DrainedCompactionConditions('finite-water', source_note, 'water', 1000., 10.),
        reservoir_fluid_m3=100., cooling_model=cooling, buoyancy_material=buoyancy,
        support_parameters=diagnostic_support,
        depth_edges_m=(0., 100., 1000., 10000., 100000.),
        temperature_tolerance_k=1e-9, budget=budget)

    cell_ids = tuple(cell['cell_id'] for cell in
                     material_root.initial_samples.descriptor()['cells'])
    initial_surface = W04SurfaceInputs(
        initial, cell_ids, np.full(cells, initial.reservoir_fluid_m3/cells),
        np.zeros(cells), source_id=source_id, budget=budget)
    support_policy = W04SupportPolicy(
        source_id, 'periodic-repetition', 'flexure', 0., 100., .1, .01,
        FlexureParameters('w12-periodic-control', source_note, 12., 1., 0., 3300., 10.))
    schedule = (
        {'time_s': step_s, 'top_effective_stress_pa': 1e6},
        {'time_s': 2*step_s, 'top_effective_stress_pa': 0.},
    )
    provenance = {
        'schema': 'atlas.w12-public-column-case.v1',
        'status': 'WORKING NON-CANON', 'source_id': source_id, 'source': source_note,
        'physical_calibration': False,
        'scope': 'Stationary planar W01/W02 sediment columns, W03 cooling and drained '
                 'compaction, periodic one-way W04 support; no terrain feedback.',
        'frame': {'id': frame, 'kind': 'planar', 'length_m': length_m, 'width_m': width_m,
                  'cells': cells, 'sampled_sediment_depth_m': [0., 100.],
                  'thermal_plate_depth_m': [0., 100000.], 'depth_reference_id': datum},
        'epoch': {'id': epoch, 'origin': 'Authored synthetic time zero',
                  'initial_time_s': 0., 'cooling_start_time_s': 0.},
        'units': {'length': 'm', 'time': 's', 'temperature': 'K', 'stress': 'Pa',
                  'volume': 'm3', 'density': 'kg/m3', 'gravity': 'm/s2',
                  'velocity': 'm/s', 'angular_velocity': 'rad/s',
                  'thermal_diffusivity': 'm2/s', 'thermal_conductivity': 'W/(m K)',
                  'specific_heat': 'J/(kg K)'},
        'water': 'Finite shared pore-water origin and 100 m3 initial reservoir, '
                 'distributed equally over the sampled surface cells.',
        'thermal_support_owner': 'W04 flexure; W03 local isostasy remains diagnostic only.',
        'external_pressure': 'Explicit zero additional W04 pressure at the reference; '
                             'W03 effective stress does not supply an external W04 load.',
    }
    return {'initial': initial, 'initial_surface': initial_surface,
            'support_policy': support_policy, 'schedule': schedule, 'provenance': provenance}
