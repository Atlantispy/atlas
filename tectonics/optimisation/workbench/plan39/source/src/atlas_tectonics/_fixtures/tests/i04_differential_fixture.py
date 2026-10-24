"""Shared synthetic radial material for differential pressure/flow controls.

This is a fresh authored verification source, not conversion of saved states.
All source cohorts use alpha=.02/K, rho0=1.1 kg/m3, Cp=1 J/(kg K), k=.1 W/(m K).
Their original declared T values1.25/1.75 K give independently checkable EOS
densities1.0945/1.0835 kg/m3 at Tref1 K. Creep is n1, A=.5/(Pa s), Q=1 J/mol;
eta=exp(1/(R T)) Pa s. Plasticity is explicitly disabled. These convenient
units are not Earth/lithosphere calibration or a resolution acceptance claim.

The native domain is the previously admitted 2^3 complete box; four genuinely
adjacent source prisms supply its natural z0 boundary. Global component coverage
must additionally be admitted by the differential assembly; this fixture does
not reinterpret a selected-source funding record as the whole planet.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from dataclasses import replace
from fractions import Fraction as Q
import gzip
import json

import numpy as np
from threadpoolctl import threadpool_limits

import test_i04_regional_owner as F
from test_integration_collar_geometry import fund
from atlas_tectonics import integration_material as M
from atlas_tectonics import integration_radial_strength as R
from atlas_tectonics import integration_regional_evolution as O
from atlas_tectonics.constitutive import BoussinesqMaterial, DiffusiveScales
from atlas_tectonics.integration_basal_inventory import carve_basal_inventory
from atlas_tectonics.integration_regional_inventory import (HaloReservoir, ComponentRegistry,
    birth_source_id, finite_birth_stocks, finite_export_stocks)
from atlas_tectonics.integration_transfer import Supply, Sink
from atlas_tectonics.integration_strength import CreepLaw
from atlas_tectonics.regional_collar3d import PreparedRegionalCollar3D
from atlas_tectonics.regional_evolution3d import PreparedRegionalEvolution3D
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import SIDES
from atlas_tectonics.resources import WorkBudget


def capture_ale_replay(path, *, partition, interval, native, projection, directed,
                       width, stream_width, max_leaves, budget, max_native_mask_leaves=None):
    """Failure-only, lossless operands; never an accepted/restorable world.

    Stream each already-issued JSON record once through bounded gzip scratch.
    Supports are referenced by their own IDs rather than copied per query.
    This avoids repeating native mechanics to investigate the next contact.
    """
    from atlas_tectonics import integration_volume as V
    def records():
        yield from (('partition', partition), ('interval', interval), ('native', native),
                    ('projection', projection), ('directed', directed))
        yield from (('support', support) for support in partition.supports)
    with budget.reserve(1 << 20, category='test-ale-replay-stream'):
        count, size = 0, 0
        for _, value in records():
            if type(value._json) is not bytes:
                raise ValueError('replay requires original encoded bytes')
            count += 1; size += len(value._json)
        if size > 256 << 20:
            raise ValueError('complete diagnostic exceeds explicit 256 MiB raw capture limit')
        header = dict(schema='atlas.ale-replay-inputs.v1', diagnostic_only=True,
            scientific_acceptance=False, records=count, original_record_bytes=size,
            max_volume_error_m3=V._encoded(width), max_stream_error_m3=V._encoded(stream_width),
            max_leaves=max_leaves)
        if max_native_mask_leaves is not None:
            header['max_native_mask_leaves'] = max_native_mask_leaves
        with path.open('xb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=1, mtime=0) as stream:
                stream.write(json.dumps(header, sort_keys=True, separators=(',', ':')).encode('ascii')+b'\n')
                for kind, value in records():
                    stream.write(b'{"kind":"'+kind.encode('ascii')+b'","record":')
                    data = memoryview(value._json)
                    for start in range(0, len(data), 65536):
                        stream.write(data[start:start+65536])
                    stream.write(b'}\n')
    return count, size


@contextmanager
def radial_differential_fixture(*, budget=None, reference_pa=0., pressure_space='q1',
                                material_quadrature=False):
    """Prepare a fresh source; dual admission is explicit, never a save migration."""
    budget = WorkBudget(256 << 20) if budget is None else budget
    original = list(F.physical_source(budget))
    original[-1] = (-.5, 1., -2.)
    sphere, moving = original[:2]
    records = tuple(replace(c, sublayers=tuple(replace(layer, alpha_per_k=.02)
                    for layer in c.sublayers)) for c in moving.cohorts)
    original[1] = M.declare_moving(sphere, records, enthalpy_reference_k=1., budget=budget)
    source = tuple(original)
    volume_map = F.physical_map(source, budget)
    law = CreepLaw((dict(a=.5, n=1., energy_j_mol=1., volume_m3_mol=0., grain_exponent=0.),),
                   'synthetic already-SI n1 Arrhenius law, not calibrated lithosphere')
    constitutive = R.radial_strength_source(source[1], sphere, volume_map,
        materials={'synthetic': R.RadialPlasticity3D(0., 0., None, 1., (0., 1.), 1., 1.,
            'explicit creep-only synthetic verification material')},
        creep_laws={'test:constant-creep': law},
        provenance='fresh source-wide thermal density and current radial geometry', budget=budget)
    material = BoussinesqMaterial('test:differential-radial', 'same source-wide declared material',
        1.1, 1., .1, .02, 1., 0., 0., (1., 2.))
    # Explicit new admission: every real patch/layer is distinct, including
    # zero-native components. No previously saved layout is reordered/migrated.
    patches = {p.patch_id: p for p in sphere.material.support.patches}
    keys = sorted((p.patch_id, j) for p in patches.values()
                  for j in range(len(source[1].cohort(p.cohort_id).sublayers)))
    ridge = next(b for b in sphere.network.boundaries if b.kind == 'ridge')
    # These are explicit NEW birth declarations, not resampled inherited heat.
    # Two finite one-square-metre reservoirs at T=1.5 K have virgin history.
    born_layer = M.Sublayer('synthetic', 'crust', 3., 1.1, .02, .1, 1., 0.,
                            1.5, 1.5, 'test:constant-creep', 0.)
    column = M.BirthColumn('test:differential-birth-profile', 'test:authored-T1.5',
        (born_layer,), 1.5, 1.5, volume_convention='physical_radial_shell',
        reference_radius_m=10., radial_depths_m=(0., 3.))
    factor = M.volume_per_area(column, budget=budget)[0]
    heat = M.declared_areal_heat(column, 1., budget=budget)[0]
    supplies = tuple(Supply(ridge.boundary_id, side, 'test:finite-ridge-'+side,
        'synthetic', 'test:explicit-ridge-birth', (('crust', float(Q(1.1)*factor)),),
        (('crust', float(factor)),), float(heat), 'test:virgin-birth-history', True)
        for side in ('left', 'right'))
    capacity = len(keys)+len(supplies)
    pattern = {s: ('traction',)*3 if s == 'z0' else ('velocity',)*3 for s in SIDES}
    with threadpool_limits(1), PreparedRegionalEvolution3D((2, 2, 2), source[4], material, None,
            DiffusiveScales('synthetic SI scales', 1., 1., 1., 1., 1., 1.),
            RegionalMechanicsScales(1., 1.), pattern, composition_values=(0.,)*capacity,
            frame_id=source[2].region_id, vertical_datum='actual contained radial Cartesian box',
            include_viscous_heating=True, divergence_rtol=1e-10,
            max_velocity_correction_m_s=1e-8, max_relative_correction=1e-6,
            budget=budget, mechanics_method='direct', radial_constitutive=constitutive,
            pressure_reference_pa=np.full(27, reference_pa),
            pressure_reference_source='explicit constant Q1 decomposition only; no physical body omitted',
            pressure_load_partition='full', max_components=capacity, pressure_space=pressure_space) as native:
        profile = ComponentRegistry.native_profile(native)
        rows = []
        for patch_id, j in keys:
            patch = patches[patch_id]; layer = source[1].cohort(patch.cohort_id).sublayers[j]
            rows.append(dict(lineage=dict(kind='initial-patch-layer', source_id=source[1].moving_id,
                patch_id=patch_id, sublayer=j), plate_id=sphere.network.face_plate(patch.face_id),
                material_id=layer.material_id, creep_law_id=layer.creep_law_id,
                composition_value=0., profile=profile))
        for supply in supplies:
            rows.append(dict(lineage=dict(kind='finite-supply', source_id=birth_source_id(supply, column),
                supply_id=supply.source, sublayer=0),
                plate_id=ridge.left_plate_id if supply.side == 'left' else ridge.right_plate_id,
                material_id=born_layer.material_id, creep_law_id=born_layer.creep_law_id,
                composition_value=0., profile=profile))
        registry = ComponentRegistry(rows, budget=budget, max_components=capacity,
                                     initial_source_plate_ids=tuple(sorted(sphere.network.plate_ids)))
        with O.PreparedRegionalOwner(native, sphere, source[1], source[2], plate_ids=('A', 'B'),
            creep_match=dict(creep_law_id='test:constant-creep', law=law.record()),
            map_source=volume_map.record()['request']['map_source'], volume_map=volume_map,
            basal_side='z0', budget=budget, component_registry=registry,
            material_quadrature=material_quadrature) as owner, \
             PreparedRegionalCollar3D(native, volume_map, ((0, 0),)*3,
                mechanics_scope='complete-grid', budget=budget, component_registry=registry) as collar:
            initial_funding = fund(source, owner, collar, budget)
            mapped_rows = volume_map.record()['cell_sources']
            reservoirs = tuple(HaloReservoir('z0', (i, j), mapped_rows[(i*2+j)*2]['patch_id'],
                mapped_rows[(i*2+j)*2]['sublayer'], Q(1, 4)) for i in range(2) for j in range(2))
            funding = carve_basal_inventory(initial_funding, *source[:2], collar, reservoirs,
                                           budget=budget, compartment_kind='reservoir')
            state = collar.initial_state_from_funding(funding, owner)
            finite_rows = [r for supply in supplies for r in finite_birth_stocks(registry, supply, column,
                native=native, sphere=sphere, finite_area_m2=Q(1), enthalpy_reference_k=1., budget=budget)]
            trench = next(b for b in sphere.network.boundaries if b.kind == 'trench')
            sink = Sink(trench.boundary_id, (('test:finite-slab-receiver', 1.),))
            finite_rows += finite_export_stocks(registry, sink, native=native, sphere=sphere,
                                               funding=funding, budget=budget)
            finite_rows += funding.descriptor()['basal_inventory']['stocks']
            if material_quadrature:
                # Fresh B is each actual source's booked volume, including the
                # empty export. Copy rows: immutable funding keeps its original
                # physical fields, debits and geometry unchanged.
                finite_rows = [dict(row, exact=dict(row['exact'],
                    material_quadrature_m3=row['volume_m3'])) for row in finite_rows]
            yield dict(source=source, volume_map=volume_map, material=material, law=law,
                native=native, owner=owner, collar=collar, funding=funding, state=state,
                reservoirs=reservoirs, budget=budget, registry=registry, supplies=supplies,
                birth_columns={s.source: column for s in supplies}, sinks=(sink,), finite_rows=finite_rows)
