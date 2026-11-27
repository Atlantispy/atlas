"""Small explicitly synthetic R2 inputs; no Earth calibration or plate prior.

The 300 K constants are test values, not inferred properties of hot lithosphere.
Use source-bound library tests separately for normal Earth-reference retrieval.
"""
from dataclasses import replace
import math
from atlas_tectonics import (
    GeologySource, MaterialDefinition, CohortDescription, MaterialCohort,
    ThermalInitialProfile, LayerComponent, GeologicalLayer, ColumnDescription,
    GeologicalProvince, SurfaceSelector, FeaturePrecedence, FeatureGeometry,
    GeologicalDomain, GeologicalCase, PrecursorState, MaterialVolumeBasis,
    InputOrigin, CoolingHistory, PlanarGeometry, InitialSamplingCell,
)

FRAME = 'r2-fixture-metres'
REQUEST = dict(frame_id=FRAME, epoch_id='r2-epoch', depth_reference_id='reference-surface')
SOURCE = GeologySource('fixture', 'synthetic', 'R2 verification-only authored input; no physical acceptance.')
ROCK = MaterialDefinition('grain_a', 'solid', 'fixture', 3000., 3., 1000., 0., 3e-5, 300., (0., 2000.))
ROCK_B = replace(ROCK, material_id='grain_b', density_kg_m3=2000.)
WATER = MaterialDefinition('fluid', 'fluid', 'fixture', 1000., .6, 4000., 0., 0., 300.)
OLD = CohortDescription(MaterialCohort('old', 'grain_a', 'continental-origin', -100.), 'fixture')
YOUNG = CohortDescription(MaterialCohort('young', 'grain_b', 'oceanic-origin', -20.), 'fixture')
TEMP = ThermalInitialProfile('initial', 'fixture', 'constant', temperatures_k=(300.,))


def rectangle(x0=0., x1=10., y0=0., y1=10., *, frame=FRAME):
    return PlanarGeometry.polygon([(x0,y0),(x1,y0),(x1,y1),(x0,y1)], frame_id=frame)


def layer(name='crust', thickness=10., role='crust', cohort='old', porosity=0., components=None):
    return GeologicalLayer(name, role, thickness, (LayerComponent(cohort, 1.),) if components is None else components,
        porosity, 'fixture', 'unmeasured porosity' if porosity is None else None)


def column(name='continent', *, layers=None, profile='initial', crust_type='continental', fluid=None):
    ls = (layer(), layer('mantle', 20., 'lithospheric_mantle')) if layers is None else layers
    return ColumnDescription(name, crust_type, ls, math.fsum(x.bulk_thickness_m for x in ls), profile, 'fixture', fluid)


def ingredients(surface=None):
    return dict(case_id='r2-synthetic', topology=GeologicalDomain(rectangle() if surface is None else surface, 'fixture'),
        time_s=0., epoch_id=REQUEST['epoch_id'], depth_reference_id=REQUEST['depth_reference_id'], source_id='fixture',
        sources=(SOURCE,), materials=(ROCK,), cohorts=(OLD,), thermal_profiles=(TEMP,), columns=(column(),),
        provinces=(GeologicalProvince('background', 'continent', SurfaceSelector('domain'), 'fixture'),),
        precedence=FeaturePrecedence(('background',)))


def case(surface=None, **changes):
    d = ingredients(surface); d.update(changes)
    return GeologicalCase(**d)


def state(c=None, **changes):
    c = case() if c is None else c
    args = dict(origins=tuple(InputOrigin(s.source_id, 'authored', 'r2-synthetic-scenario') for s in c.sources),
        cooling_history=tuple(CoolingHistory(t.profile_id, t.source_id,
            t.cooling_start_time_s if t.mode == 'half_space' else -10.) for t in c.thermal_profiles),
        material_bases=tuple(MaterialVolumeBasis(m.material_id, 'fluid' if m.material_class == 'fluid' else 'grain',
                                               m.source_id) for m in c.materials))
    args.update(changes)
    return PrecursorState(c, **args)


def mixed_case(*, edge=4., temperature_b=500.):
    other = column('ocean', crust_type='oceanic', profile='other', layers=(layer('ocean-crust', 30., cohort='young'),))
    hot = replace(TEMP, profile_id='other', temperatures_k=(temperature_b,))
    return case(materials=(ROCK,ROCK_B), cohorts=(OLD,YOUNG), thermal_profiles=(TEMP,hot),
        columns=(column(),other), geometries=(FeatureGeometry('patch', rectangle(0,edge), 'fixture'),),
        provinces=(GeologicalProvince('background','continent',SurfaceSelector('domain'),'fixture'),
                   GeologicalProvince('ocean-region','ocean',SurfaceSelector('geometry',('patch',)),'fixture')),
        precedence=FeaturePrecedence(('ocean-region','background')))


def cell(name='whole', footprint=None, top=0., bottom=30.):
    return InitialSamplingCell(name, rectangle() if footprint is None else footprint, top, bottom)
