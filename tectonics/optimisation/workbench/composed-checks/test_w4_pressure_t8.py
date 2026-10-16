"""W4 check 4 (optional D T8): genuine full differential_pressure_forcing parity on composed-r1.

One fresh child process selects the FROZEN composed tree only through the composed
runner's RestartProfile/RestartSources (the W3 import-fence route; launch flags as
the real runner: -B, PYTHONHASHSEED=0, single BLAS/OMP thread, no PYTHONPATH). In it
the H pressure-path fixture is built once on its declared 1 GiB logical budget:
radial_differential_fixture, initial_partition(max_components=4096), initial_metrics
(32 r^3 volume errors, 64 leaves, 8 witness refinements) and initial_spatial_owner.

The ordinary initial spatial state and native partition are then converted with the
composed codecs on a SYNTHETIC temporary ArrayStore (never the historical database):

* indexed spatial state: mesh_tables.pack_mesh -> CompactMeshStore.publish/open, then
  the native owner's restore_compact (every original restore gate, identity recomputed
  from the compact logical stream; logical metadata taken from the ORDINARY body);
* compact partition: partition_tables.pack_partition -> CompactPartitionStore
  publish/open, then DifferentialPartition.from_compact (native admission gates);
  its supports are materialised one at a time with _compact_ref.

The real differential_pressure_forcing (composed 8d3d8f3d) then runs on the legacy
route (ordinary state + native supports) and on the compact route (indexed state +
compact-partition supports) with identical other operands. forcing_id, the canonical
descriptor bytes and every array's dtype/shape/bytes must be identical. During the
compact call whole-mesh/whole-partition exports are counted, and the three pressure
budget categories must be back at zero once the call returns.

i04_differential_spatial_fixture is a manifest data_only reference: the runtime
never imports it. The child executes its manifest-pinned bytes (f13d48b6) as a
test-side fixture module that is not registered in sys.modules; everything it
imports goes through the composed finder and the end-of-selection import check.

Run: python -B test_w4_pressure_t8.py --dry   (setup/conversion timing only)
     python -B -m unittest -v test_w4_pressure_t8   (full parity; time-boxed)
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
R = HERE.parent
WORKSPACE = R.parents[3]
TARGET = R/'composed-r1'
PROFILE = TARGET/'review'/'restart-profile-s2-r1.json'
RUNNER = TARGET/'helpers'/'run_prepared_restart.py'
SCRATCH = WORKSPACE/'_t'/'w4-pressure-t8'

# Frozen W3 composition (R/test-results/w3.json); a mismatch is investigated, never repinned.
PROFILE_SHA256 = 'fffa99257a4e946edd9fe32d926a7c96e2319eec180c7d13782dc927f876de84'
MANIFEST_SHA256 = '6a6f493353942ebd27f10c73105fe7d10f5ab1bef1f4d54e72094ac5dcfe4e9b'
PRESSURE_SHA256 = '8d3d8f3dd11d632ce6a75380a17fdcd19b281fafa03b68401a2726d228c02a33'
SPATIAL_FIXTURE_SHA256 = 'f13d48b68e0b6f0b2de92e2bb903c71fe6beb92e56f2795be131ea2488b760ee'
# Same values as assemble_resumable.LAUNCH_ENVIRONMENT (the runner's launch env).
LAUNCH_ENVIRONMENT = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                      'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0'}
MIN_AVAILABLE = 3 << 29          # 1.5 GiB before launch
FREE_FLOOR = 1 << 30             # unchanged project free-memory floor while running
TIMEOUT_S = int(os.environ.get('W4_T8_TIMEOUT_S', '720'))

CHILD = r'''
import gc, hashlib, importlib.util, json, os, sys, tempfile, time, types
from collections import Counter
from pathlib import Path
import psutil

runner, profile_path, profile_sha, mode, scratch = sys.argv[1:6]
PROC = psutil.Process()
T0 = time.perf_counter()
stages = []

def mark(name, **extra):
    row = dict(stage=name, s=round(time.perf_counter()-T0, 3), rss=PROC.memory_info().rss,
               available=psutil.virtual_memory().available, **extra)
    stages.append(row)
    print('T8_STAGE '+json.dumps(row, sort_keys=True), file=sys.stderr, flush=True)

spec = importlib.util.spec_from_file_location('run_prepared_restart', runner)
RUN = importlib.util.module_from_spec(spec)
sys.modules['run_prepared_restart'] = RUN
spec.loader.exec_module(RUN)
profile = RUN.RestartProfile.read(Path(profile_path), profile_sha)
sources = RUN.RestartSources(profile)
result = dict(mode=mode, proof=sources.verify(), stages=stages,
              interpreter=dict(PYTHONHASHSEED=os.environ.get('PYTHONHASHSEED'),
                               hash_randomization=sys.flags.hash_randomization, executable=sys.executable))
manifest = json.loads(sources.manifest_path.read_bytes())
FIXTURE = 'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests/i04_differential_spatial_fixture.py'
mark('sources-verified')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

with sources.selected():
    from fractions import Fraction as Q
    from unittest import mock
    import numpy as np
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_differential_pressure as P
    from atlas_tectonics.integration_radial_pressure import RadialDatum
    from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D
    import i04_differential_fixture as FX
    from i04_differential_modes import ORIGINAL_CONTROL
    import mesh_tables as M
    import partition_tables as PT
    import spatial_indexed_patch as X
    import spatial_transfer as S
    import pressure_indexed_patch as PI
    from compact_store import CompactMeshStore
    from partition_store import CompactPartitionStore
    used = {}
    for module in (P, G, FX, M, PT, X, S, PI, sys.modules['compact_store'], sys.modules['partition_store']):
        path = Path(module.__file__).resolve()
        used[module.__name__] = dict(path=path.relative_to(sources.workspace).as_posix(),
                                     sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    result['modules'] = used
    raw = (sources.workspace/FIXTURE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['data_only'][FIXTURE]:
        raise RuntimeError('data-only spatial fixture differs from its manifest pin')
    SF = types.ModuleType('w4_t8_spatial_fixture')
    exec(compile(raw, str(sources.workspace/FIXTURE), 'exec', dont_inherit=True), SF.__dict__)
    result['spatial_fixture'] = dict(path=FIXTURE, sha256=hashlib.sha256(raw).hexdigest(),
                                     executed_as='authenticated data_only bytes, not registered in sys.modules')
    del raw
    mark('imports')

    budget = WorkBudget(1 << 30)
    with FX.radial_differential_fixture(budget=budget) as case:
        mark('fixture')
        ORIGINAL_CONTROL.validate_case(case)
        sphere, moving = case['source'][:2]
        funding, collar, native = case['funding'], case['collar'], case['native']
        radius = Q(sphere.network.sphere.radius_m)
        current, partition = SF.initial_partition(case, max_components=4096)
        mark('initial-partition', supports=len(partition.supports))
        bounds, mesh = SF.initial_metrics(case, partition, physical_volume_error_m3=32*radius**3,
            thermal_volume_error_m3=32*radius**3, max_leaves=64, max_witness_refinements=8)
        mark('initial-metrics')
        with SF.initial_spatial_owner(case, partition, bounds, mesh) as owner:
            state = owner.initial_state
            mark('initial-owner')
            with tempfile.TemporaryDirectory(prefix='s', dir=scratch) as tmp:
                store = ArrayStore(Path(tmp)/'t8.sqlite', StoreLimits(chunk_bytes=1 << 20,
                    max_array_bytes=512 << 20, max_store_bytes=2 << 30), budget=budget)
                try:
                    producer = {'fixture': 'W4 T8 synthetic H pressure-path fixture',
                                'source_manifest_sha256': profile.record()['source_manifest']['sha256']}
                    # Indexed spatial state through the native owner's compact restore.
                    record = state.record()
                    geometry_id = record['thermal_mesh_id']
                    if M.digest(record['thermal_mesh']) != geometry_id:
                        raise RuntimeError('ordinary thermal mesh does not hash to its carried ID')
                    logical = S._stream_stats({k: v for k, v in record.items() if k != 'state_id'})[0]
                    small = {k: v for k, v in record.items() if k not in ('state_id', 'thermal_mesh')}
                    meshes = CompactMeshStore(store, budget=budget)
                    metadata, arrays = M.pack_mesh(record['thermal_mesh'], support_writer=meshes.support_writer,
                                                   budget=budget)
                    result['mesh'] = dict(geometry_id=geometry_id, cells=len(record['thermal_mesh']['cells']),
                        faces=len(record['thermal_mesh']['faces']),
                        legacy_bytes=len(canonical(record['thermal_mesh'])),
                        support_tables={k: len(v) for k, v in record['thermal_mesh']['support_tables'].items()},
                        array_bytes=sum(a.nbytes for a in arrays.values()))
                    del record
                    key = meshes.publish(metadata, arrays, expected_geometry_id=geometry_id, source_producer=producer)
                    del metadata, arrays
                    view = meshes.open(key, expected_geometry_id=geometry_id)
                    root_manifest, root = meshes._root(key)
                    reference = dict(schema=root['schema'], snapshot_key=key, geometry_id=view.geometry_id,
                                     source_producer=root['source_producer'], array_bindings=root_manifest['arrays'])
                    del root_manifest, root
                    envelope = dict(schema=X.SCHEMA, state_id=state.state_id, state=small,
                                    mesh_reference=reference, logical_metadata=logical)
                    indexed = owner.restore_compact(envelope, state.arrays(), compact_mesh=view,
                                                    expected_mesh_reference=reference)
                    del envelope, small
                    if type(indexed._snapshot) is not X.IndexedSpatialSnapshot or not PI.is_indexed(indexed):
                        raise RuntimeError('compact restore did not issue an indexed spatial state')
                    result['spatial'] = dict(ordinary_state_id=state.state_id, indexed_state_id=indexed.state_id,
                        same_state_id=indexed.state_id == state.state_id,
                        ordinary_snapshot_nbytes=state._snapshot.nbytes, indexed_snapshot_nbytes=indexed._snapshot.nbytes,
                        logical_metadata=logical)
                    mark('indexed-state')
                    # Compact partition through the partition store and native admission.
                    body = partition.record()
                    pid = partition.partition_id
                    packed = PT.pack_partition(body, (s.record() for s in partition.supports),
                                               expected_partition_id=pid, budget=budget)
                    built = PT.CompactPartition(*packed, expected_partition_id=pid, budget=budget)
                    del packed, body
                    partitions = CompactPartitionStore(store, budget=budget)
                    pref = partitions.publish(built, source_producer=producer)
                    del built
                    opened = partitions.open(pref, expected_partition_id=pid)
                    compact_partition = G.DifferentialPartition.from_compact(opened, funding, collar, current,
                                                                             budget=budget)
                    if compact_partition.compact_view() is not opened or compact_partition.partition_id != pid:
                        raise RuntimeError('compact partition admission differs')
                    result['partition'] = dict(partition_id=pid, supports=len(partition.supports),
                        compact_supports=len(compact_partition.supports), nodes=opened.node_count,
                        support_ids_equal=[s.support_id for s in compact_partition.supports] ==
                                          [s.support_id for s in partition.supports])
                    del pref
                    gc.collect()
                    mark('compact-partition')
                    if mode == 'full':
                        datum = RadialDatum(10., 1., 1., 7., 1.1, 0.,
                            'synthetic constant-magnitude radial gravity; zero outer load; fixed support sphere')
                        with PreparedRegionalStokes3D(native.cells, native.lengths_m, native._cs.viscosity_pa_s,
                                native._pattern, scales=native._ms, reference_viscosity_pa_s=native._cs.viscosity_pa_s,
                                frame_id=native._frame, vertical_datum=native._datum, material_source=native.plan_id,
                                method='direct', physical_mean_pressure_pa=None, budget=budget,
                                **native._pressure_reference_args) as prototype:
                            reservoir = P.prescribe_reservoir_pressure(funding, collar, prototype,
                                pressure_at_origin_pa=Q(5), gradient_pa_m=(0, 0, 0), origin_world_m=(0, 0, 0),
                                source='synthetic explicit5Pa finite-compartment boundary pressure', budget=budget)

                            def forcing(spatial_state, supports):
                                return P.differential_pressure_forcing(sphere, sphere.network, current, funding,
                                    collar, case['state'], spatial_state, prototype, datum, reservoir,
                                    source_moving=moving, supports=supports,
                                    exterior_parent_state_id=sphere.state_id, max_torque_width_n_m=Q(1, 4),
                                    max_operator_error=Q(1, 10**20), max_leaves=4096, budget=budget)

                            def summary(force):
                                described = force.descriptor()
                                names = list(force._snapshot.array_names)
                                values = {n: np.ascontiguousarray(force.array(n)) for n in names}
                                return described, values, dict(forcing_id=force.forcing_id,
                                    descriptor_sha256=hashlib.sha256(canonical(described)).hexdigest(),
                                    descriptor_bytes=len(canonical(described)),
                                    spatial_state_id=described['spatial_state_id'],
                                    integration_leaves=described['integration_leaves'],
                                    arrays={n: dict(dtype=a.dtype.str, shape=list(a.shape),
                                                    sha256=hashlib.sha256(a.tobytes()).hexdigest())
                                            for n, a in values.items()})

                            pressure_categories = ('pressure-constraint-retained', 'pressure-indexed-entries',
                                                   'pressure-indexed-scratch')
                            gc.collect()
                            before = budget.reserved_bytes
                            started = time.perf_counter()
                            legacy = forcing(state, partition.supports)
                            legacy_s = time.perf_counter()-started
                            legacy_desc, legacy_arrays, legacy_summary = summary(legacy)
                            mark('legacy-forcing', seconds=round(legacy_s, 3))
                            counts = Counter()

                            def counted(cls, name, whole):
                                original = getattr(cls, name)
                                def wrapper(self, *args, **kwargs):
                                    if whole(args, kwargs):
                                        counts[cls.__name__+'.'+name] += 1
                                    return original(self, *args, **kwargs)
                                return mock.patch.object(cls, name, wrapper)

                            always = lambda args, kwargs: True
                            root_ref = lambda args, kwargs: (args[0] if args else kwargs.get('ref')) is None
                            # Budget category labels are capped at 63 (resources.py); count the
                            # compact consumer's own leases and owner stats directly instead.
                            leases = Counter()

                            class RecordingLease(PI._Lease):
                                def __init__(self, budget, size, category):
                                    super().__init__(budget, size, category)
                                    leases[category+':booked'] += 1
                                    leases[category+':bytes'] += size

                                def __del__(self):
                                    if self._guard is not None:
                                        leases[self.__class__.__name__+':released'] += 1
                                    super().__del__()

                            owner_stats = []

                            class RecordingOwner(PI.PressureConstraintOwner):
                                def __init__(self, budget):
                                    super().__init__(budget)
                                    owner_stats.append(self.stats)

                            gc.collect()
                            held_legacy = budget.reserved_bytes
                            started = time.perf_counter()
                            with counted(M.CompactMesh, 'legacy_record', always), \
                                 counted(M.CompactMesh, 'iter_legacy_json', always), \
                                 counted(PT.CompactPartition, 'legacy_record', root_ref), \
                                 counted(PT.CompactPartition, 'iter_legacy_json', root_ref), \
                                 mock.patch.object(PI, '_Lease', RecordingLease), \
                                 mock.patch.object(PI, 'PressureConstraintOwner', RecordingOwner):
                                compact = forcing(indexed, compact_partition.supports)
                            compact_s = time.perf_counter()-started
                            gc.collect()
                            held_both = budget.reserved_bytes
                            after_compact = budget.statistics()
                            compact_desc, compact_arrays, compact_summary = summary(compact)
                            mark('compact-forcing', seconds=round(compact_s, 3))
                            arrays_equal = (list(legacy_arrays) == list(compact_arrays) and all(
                                legacy_arrays[n].dtype == compact_arrays[n].dtype and
                                legacy_arrays[n].shape == compact_arrays[n].shape and
                                legacy_arrays[n].tobytes() == compact_arrays[n].tobytes() for n in legacy_arrays))
                            result['forcing'] = dict(legacy=legacy_summary, compact=compact_summary,
                                legacy_seconds=round(legacy_s, 3), compact_seconds=round(compact_s, 3),
                                forcing_id_equal=legacy.forcing_id == compact.forcing_id,
                                descriptor_equal=canonical(legacy_desc) == canonical(compact_desc),
                                arrays_equal=arrays_equal,
                                whole_export_calls_during_compact=dict(counts),
                                pressure_categories_after_compact={k: after_compact['categories'].get(k, 0)
                                                                   for k in pressure_categories},
                                pressure_category_peaks={k: after_compact['category_peaks'].get(k)
                                                         for k in pressure_categories},
                                category_labels=len(after_compact['categories']),
                                pressure_categories_observable=any(k in after_compact['category_peaks']
                                                                   for k in pressure_categories),
                                compact_leases=dict(leases),
                                compact_leases_live_after_call=sum(v for k, v in leases.items()
                                    if k.endswith(':booked'))-leases['RecordingLease:released'],
                                constraint_owner_stats=[dict(s) for s in owner_stats],
                                reserved_before=before, reserved_holding_legacy=held_legacy,
                                reserved_holding_both=held_both)
                            del legacy, compact, legacy_desc, compact_desc, legacy_arrays, compact_arrays
                            gc.collect()
                            result['forcing']['reserved_after_release'] = budget.reserved_bytes
                            del reservoir
                    del indexed, compact_partition, opened, view, reference
                    gc.collect()
                finally:
                    store.close()
                    store = None
            mark('store-closed')
        del state, owner
    case = sphere = moving = funding = collar = native = current = partition = bounds = mesh = None
    gc.collect()
    result['budget'] = dict(reserved_end=budget.reserved_bytes, peak_reserved=budget.peak_reserved_bytes)
    result['imported_workspace_sources'] = len(sources.check_imported())
result['proof_after'] = sources.verify()
result['peak_wset'] = getattr(PROC.memory_info(), 'peak_wset', None)
mark('done')
print('T8_RESULT '+json.dumps(result, sort_keys=True), flush=True)
'''


def launch_environment():
    environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    environment.update(LAUNCH_ENVIRONMENT)
    environment['TMP'] = environment['TEMP'] = str(SCRATCH)
    return environment


def wait_for_memory(minimum=MIN_AVAILABLE, polls=6, pause=20):
    import psutil
    seen = []
    for attempt in range(polls):
        available = psutil.virtual_memory().available
        seen.append(available)
        if available >= minimum:
            return available, seen
        if attempt < polls-1:
            time.sleep(pause)
    return None, seen


def kill_tree(pid):
    import psutil
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    victims = parent.children(recursive=True)+[parent]
    for proc in victims:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(victims, timeout=30)
    return [p.pid for p in victims]


def run_child(mode, *, timeout=TIMEOUT_S):
    """One fresh child against the frozen composed tree; returns (result|None, record)."""
    for path, pin in ((PROFILE, PROFILE_SHA256), (TARGET/'manifest.json', MANIFEST_SHA256),
                      (TARGET/'runtime-src'/'atlas_tectonics'/'integration_differential_pressure.py', PRESSURE_SHA256)):
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != pin:
            raise AssertionError('frozen composed input differs: %s %s' % (path, actual))
    available, seen = wait_for_memory()
    record = dict(mode=mode, timeout_s=timeout, available_polls=seen)
    if available is None:
        record['status'] = 'NOT_RUN_LOW_MEMORY'
        return None, record
    SCRATCH.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', '-P', '-c', CHILD, str(RUNNER), str(PROFILE), PROFILE_SHA256, mode, str(SCRATCH)]
    import psutil
    started = time.perf_counter()
    child = subprocess.Popen(command, cwd=str(SCRATCH), env=launch_environment(), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    record['min_available'] = available
    while True:
        try:
            out, err = child.communicate(timeout=5)
            record['status'] = 'EXITED'
            break
        except subprocess.TimeoutExpired:
            # Shared machine: stop at the project's 1 GiB free floor rather than page.
            now = psutil.virtual_memory().available
            record['min_available'] = min(record['min_available'], now)
            stop = ('KILLED_FREE_FLOOR' if now < FREE_FLOOR else
                    'TIMEOUT' if time.perf_counter()-started > timeout else None)
            if stop is not None:
                record['killed'] = kill_tree(child.pid)
                out, err = child.communicate()
                record['status'] = stop
                break
    record['wall_s'] = round(time.perf_counter()-started, 3)
    record['returncode'] = child.returncode
    record['stage_log'] = [json.loads(line[9:]) for line in err.splitlines() if line.startswith('T8_STAGE ')]
    record['stderr_tail'] = '\n'.join(l for l in err.splitlines() if not l.startswith('T8_STAGE '))[-4000:]
    lines = [line for line in out.splitlines() if line.startswith('T8_RESULT ')]
    result = json.loads(lines[-1][len('T8_RESULT '):]) if lines and child.returncode == 0 else None
    # Evidence copy for the receipt; never overwrites an earlier run.
    output = SCRATCH/('t8-%s-%s-%d.json' % (mode, time.strftime('%Y%m%dT%H%M%S'), os.getpid()))
    with output.open('x', encoding='utf-8') as stream:
        json.dump(dict(result=result, record=record), stream, sort_keys=True, indent=1)
    record['evidence'] = str(output)
    print('T8_EVIDENCE '+str(output), file=sys.stderr, flush=True)
    return result, record


class ComposedPressureForcingParity(unittest.TestCase):
    def test_full_forcing_parity_indexed_state_compact_partition(self):
        result, record = run_child('full')
        if result is None and record['status'] in ('NOT_RUN_LOW_MEMORY', 'KILLED_FREE_FLOOR'):
            self.skipTest('shared-machine memory: %s, available polls %r, minimum %r' % (
                record['status'], record['available_polls'], record.get('min_available')))
        self.assertEqual(record['status'], 'EXITED', record)
        self.assertIsNotNone(result, record['stderr_tail'])
        self.assertEqual(result['proof'], result['proof_after'])
        self.assertEqual(result['proof']['source_manifest_sha256'], MANIFEST_SHA256)
        self.assertEqual(result['modules']['atlas_tectonics.integration_differential_pressure']['sha256'],
                         PRESSURE_SHA256)
        self.assertEqual(result['spatial_fixture']['sha256'], SPATIAL_FIXTURE_SHA256)
        self.assertEqual(result['interpreter']['hash_randomization'], 0)
        self.assertTrue(result['spatial']['same_state_id'])
        self.assertTrue(result['partition']['support_ids_equal'])
        forcing = result['forcing']
        self.assertTrue(forcing['forcing_id_equal'])
        self.assertTrue(forcing['descriptor_equal'])
        self.assertTrue(forcing['arrays_equal'])
        self.assertEqual(forcing['legacy'], forcing['compact'])
        self.assertEqual(forcing['legacy']['spatial_state_id'], result['spatial']['ordinary_state_id'])
        self.assertEqual(forcing['whole_export_calls_during_compact'].get('CompactMesh.legacy_record', 0), 0)
        self.assertEqual(forcing['whole_export_calls_during_compact'].get('CompactPartition.legacy_record', 0), 0)
        self.assertEqual(forcing['whole_export_calls_during_compact'].get('CompactPartition.iter_legacy_json', 0), 0)
        # The fixture already uses the 63 category labels, so the three pressure
        # categories normally fold into 'other'; check them only when observable.
        if forcing['pressure_categories_observable']:
            self.assertEqual(set(forcing['pressure_categories_after_compact'].values()), {0})
        # Lease-level proof that the indexed consumer ran and released everything.
        self.assertGreater(forcing['compact_leases'].get('pressure-constraint-retained:booked', 0), 0)
        self.assertGreater(forcing['compact_leases'].get('pressure-indexed-entries:booked', 0), 0)
        self.assertEqual(forcing['compact_leases_live_after_call'], 0)
        self.assertEqual(len(forcing['constraint_owner_stats']), 1)
        self.assertGreater(forcing['constraint_owner_stats'][0]['regions'], 0)
        # Each held result funds one identical retained forcing; nothing else survives the call.
        self.assertEqual(forcing['reserved_holding_both']-forcing['reserved_holding_legacy'],
                         forcing['reserved_holding_legacy']-forcing['reserved_before'])
        self.assertEqual(forcing['reserved_after_release'], forcing['reserved_before'])


if __name__ == '__main__':
    if '--dry' in sys.argv:
        dry, info = run_child('dry')
        print(json.dumps(dict(result=dry, record=info), sort_keys=True, indent=1))
    else:
        unittest.main(verbosity=2)
