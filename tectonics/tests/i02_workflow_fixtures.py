"""Shared fixtures of the I02.3-I02.7 checks: the real layered finite-strain column declared as a common state.

Built from the package and the reviewed case files only, as the package-only process of test_i02_evolution does, so
child processes need no campaign tool. The order-8 layered column of the I01 weakening, column-heat and motion cases
with a declared signed initial departure and the reviewed inherited history. The finite reservoirs are two declared
exterior stocks with two components and signed enthalpy. A bounded control, not a generated world.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from atlas_tectonics import _integration_heat as H, _integration_motion as M, _integration_weakening as W
from atlas_tectonics import integration_state as I
from atlas_tectonics.materials import MaterialCohort, MaterialState
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits

ROOT = Path(__file__).resolve().parents[1]
EPOCH, FRAME, START = 'i02-workflow-epoch', 'i02-workflow-strip', 2.5e6
BASIS = 'declared-exterior-enthalpy'
SOURCE_ID = hashlib.sha256(b'declared producer: tectonics/tests/i02_workflow_fixtures.py').hexdigest()
RUNTIME_ID = hashlib.sha256(json.dumps(dict(numpy=np.__version__), sort_keys=True).encode()).hexdigest()


def case(name):
    return json.loads((ROOT/'cases'/name).read_text(encoding='utf-8'))


WEAK, HEAT, MOTION, FINITE = (case(name) for name in ('i01_weakening_v1.json', 'i01_column_heat_v1.json',
                                                       'i01_motion_coupling_v1.json', 'i01_finite_strain_v1.json'))
REP, POLICY = FINITE['representation'], FINITE['policy']
DURATION = FINITE['drive']['duration_s']
LAW = W.WeakeningLaw.from_spec(WEAK['weakening'])
DRIVE = M.Drive(MOTION['drive_n_m'], MOTION['drag_pa_s'], MOTION['width_m'])
SQUEEZE = M.Drive(-MOTION['drive_n_m'], MOTION['drag_pa_s'], MOTION['width_m'])


def preparation(order=8):
    """The reviewed layered preparation, its paired thermal support, the pinned key and thermal inputs."""
    rep = WEAK['representation']
    layers = copy.deepcopy(WEAK['layers'])
    for layer in layers:                     # the retained fixture's zero temperature offset, which yields floats
        layer['temperature_k'] = [t+0. for t in layer['temperature_k']]
    key = (layers, order, W.LITHOSTATIC, rep['gravity_m_s2'])
    inputs = dict(thicknesses=[layer['thickness_m'] for layer in layers], props=HEAT['thermal_layers'],
                  densities=[layer['density_kg_m3'] for layer in layers], boundaries=HEAT['boundaries'],
                  reference_temperature=None)
    base = W.prepare(layers, order, closure=rep['pressure_closure'], gravity=rep['gravity_m_s2'])
    thermal = H.prepare_thermal(base.layer, base.depth_m, base.weight, inputs['thicknesses'], inputs['props'],
                                inputs['densities'], inputs['boundaries'], mechanical_fingerprint=base.fingerprint)
    return base, thermal, key, inputs


def reference(base, thermal, key, inputs):
    return I.ColumnReference(
        mechanical=dict(key=key, fingerprint=base.fingerprint, layer=base.layer, depth_m=base.depth_m,
                        weight=base.weight, reference_pa=base.reference_pa, density=base.density,
                        thickness_m=base.thickness_m),
        thermal=dict(provider=I.COLUMN_THERMAL_BASIS, inputs=inputs, fingerprint=thermal.fingerprint,
                     mechanical_fingerprint=thermal.mechanical_fingerprint, layer=thermal.layer,
                     depth_m=thermal.depth_m, volume_m=thermal.volume_m,
                     reference_density_kg_m3=thermal.reference_density_kg_m3, capacity=thermal.capacity,
                     radiogenic=thermal.radiogenic, steady_k=thermal.steady_k,
                     boundary_temperature=thermal.boundary_temperature, thickness_m=thermal.thickness_m))


def settings(steps, duration, drive=DRIVE, **representation):
    return I.ColumnSettings(representation=dict(REP, **representation),
                            law=dict(start=LAW.start, end=LAW.end, cohesion_factor=LAW.cohesion_factor,
                                     friction_factor=LAW.friction_factor),
                            drive=dict(force_n_m=drive.force_n_m, drag_pa_s=drive.drag_pa_s, width_m=drive.width_m),
                            heat_fractions=(1., 1.), policy=POLICY,
                            schedule=dict(duration_s=duration, steps=steps))


def reservoirs(time_s=START, **changes):
    """Two declared exterior stocks, two components, signed enthalpy of both signs in one declared basis."""
    from atlas_tectonics.w08_inventory import W08Inventory
    values = dict(node_ids=('store-a', 'store-b'), node_kinds=('reservoir', 'reservoir'), component_ids=('A', 'B'),
                  component_mass_kg=[[5., 2.], [1., .5]], enthalpy_j=[-3., 4.], source_id='declared-exterior-stock',
                  enthalpy_source=BASIS, time_s=time_s, formation_time_s=[time_s-10., time_s-20.],
                  origin_ids=('declared-origin-a', 'declared-origin-b'))
    values.update(changes)
    return W08Inventory(**values)


def theta_signed(base, amplitude=2.):
    """A nonzero departure of both signs: warmer above mid-depth, cooler below, inside the declared window."""
    return amplitude*np.sin(2.*math.pi*np.asarray(base.depth_m)/base.thickness_m)


def root(steps=8, duration=None, *, drive=DRIVE, stocks=None, basis=None, prepared=None, source_id=SOURCE_ID,
         runtime_id=RUNTIME_ID, scenario='tests/i02_workflow_fixtures.py#layered-order-8', start=START,
         **representation):
    """A declared initial common state of the layered column: dt = duration/steps (default 6.25e12 s)."""
    base, thermal, key, inputs = preparation() if prepared is None else prepared
    duration = DURATION*steps/16 if duration is None else duration
    layers = key[0]
    ids = tuple('layer-%d-%s' % (k, layer['name']) for k, layer in enumerate(layers))
    cohorts = {cohort: (MaterialCohort(cohort, layer['name'], 'cases/i01_weakening_v1.json#layers/%d' % k, None),
                        float(layer['thickness_m'])) for k, (cohort, layer) in enumerate(zip(ids, layers))}
    ordered = sorted(cohorts)
    materials = MaterialState(ColumnGrid1D([0., drive.width_m], frame_id=FRAME),
                              tuple(cohorts[c][0] for c in ordered), [[cohorts[c][1]] for c in ordered],
                              time_s=start, epoch_id=EPOCH)
    identity = I.StateIdentity(world_id='atlas-bounded-control:not-a-generated-world', scenario_id=scenario,
                               epoch_id=EPOCH, source_id=source_id, runtime_id=runtime_id, unit_system=I.UNIT_SYSTEM)
    kappa0 = np.asarray(WEAK['campaign']['initial_history_by_layer'], dtype=float)[base.layer]
    return I.initial_state(identity=identity, start_time_s=start, frame_id=FRAME,
                           reference=reference(base, thermal, key, inputs),
                           settings=settings(steps, duration, drive, **representation), theta0_k=theta_signed(base),
                           kappa0=kappa0, materials=materials, layer_cohorts=ids, reservoirs=stocks,
                           reservoir_basis=basis)


def limits(**changes):
    values = dict(chunk_bytes=65536, max_array_bytes=16 << 20, max_store_bytes=256 << 20)
    values.update(changes)
    return StoreLimits(**values)


def store(path, compression=None, **changes):
    """A lossless store in its own dedicated directory; raw payloads keep the fixtures dependency-free."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return ArrayStore(path, limits(**changes), Compression(codec='raw') if compression is None else compression)
