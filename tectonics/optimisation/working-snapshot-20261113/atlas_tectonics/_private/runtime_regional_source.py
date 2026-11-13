from fractions import Fraction

import i03_fixtures as F

from atlas_tectonics import integration_sphere as S, integration_material as M

from atlas_tectonics import integration_bridges as B, integration_regional_evolution as O

from atlas_tectonics import integration_volume as V

def physical_source(budget):
    """Fresh shell source, not conversion of an old prism or saved history."""
    network = F.three_plates(sphere=F.sphere(radius=10.), time_s=0.,
        longitudes_deg=(-240., -180., -120., -60., 0., 60.))
    shell = V.RadialLayer(10., 0., 3., budget=budget)
    factor = shell.volume_per_area_m
    density = 1.1
    material = F.material(network, phases=('crust',), basis=None,
        mass_per_area_kg_m2={'crust': float(Fraction(density)*factor)},
        thickness_m={'crust': float(factor)})
    sphere = S.initial_sphere(network, material)
    records = []
    for cohort in material.cohorts:
        temperature = 1.25 if cohort.cohort_id == 'inherited-A' else 1.75
        layer = M.Sublayer('synthetic', 'crust', 3., density, 0., .1, 1., 0., temperature,
                           temperature, 'test:constant-creep', 0.)
        records.append(M.CohortRecord(cohort.cohort_id, 'test:physical-profile', 'test:thermal', (layer,),
            1., None, None, (.3,), M.BondRecord(cohort.cohort_id, False, 'UNKNOWN'),
            volume_convention=V.PHYSICAL_RADIAL_SHELL, reference_radius_m=10., radial_depths_m=(0., 3.)))
    moving = M.declare_moving(sphere, tuple(records), enthalpy_reference_k=1., budget=budget)
    faces = ('s03-b02', 's04-b02')
    footprint = B.Footprint('test:regional-owner', faces, 0., 0., 0., 0., 3., '3d')
    patches = {p.face_id: p for p in sphere.material.support.patches}
    sources = tuple((patches[faces[x]].patch_id, 0) for x in range(2) for _ in range(4))
    return sphere, moving, footprint, sources, (1., 1., 1.), (-.5, .25, -2.)

def physical_map(fixture, budget, **changes):
    sphere, moving, footprint, sources, lengths, origin = fixture
    values = dict(cells=(2, 2, 2), lengths_m=lengths, origin_local_m=origin,
                  cell_sources=sources, map_source='test:contained-radial-box', budget=budget)
    values.update(changes)
    return O.RegionalVolumeMap(sphere, moving, footprint, **values)
