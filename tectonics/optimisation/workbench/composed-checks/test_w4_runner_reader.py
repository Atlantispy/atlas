"""W4 check 1: composed two-process runner path and independent root-only reader.

SYNTHETIC FIXTURE EVIDENCE ONLY. This is persistence, ownership, source-binding
and refusal verification of the frozen composed successor R/composed-r1, not
historical, scientific or production acceptance. Nothing under R/composed-r1 is
written; every helper and native module is selected from it through the actual
RestartSources fence with a fixture profile/manifest/policy in a scratch run
directory under T/_t/w4-runner-reader (never the real profile output).

Processes (one heavy process at a time, launch environment):

0. fixture writer: tiny real owners on the composed tree write a synthetic
   sequence-three historical ORIGINAL (native successor layout: full collar
   fields, exterior-fv, source audit, spatial records, differential geometry
   and a native-schema partition blob) plus pinned fixture evidence.
A. producer, under the composed successor guard: the runner path of
   run_prepared_restart with --stop-before-advance semantics. Authenticated
   copy, real materialise(working_store=...) with compact mesh + compact
   partition and the real runtime_compatibility.admit, initial workload,
   cancelled publication, publish_and_reopen, published root, then driver
   drills: textual PASS refused, CancelledError propagated, the real driver's
   early gates. Receipt status STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED.
B. independent reader, under the composed guard: the reopen_prepared_restart
   root-only core on a COPY of the producer checkpoint at another path, opened
   by historical_admission.open_successor_readonly; base reproduction with no
   writes, root identity, funding, history, six array groups, ArrayReference
   store_path tolerance.
Then the real reader CLI --finalise (store-free) and command-only inspections.

Fixture substitutions (each recorded in the receipts): the ORIGINAL is the
synthetic fixture database opened read-only by open_successor_readonly, never
open_original_readonly; admission is a fixture issuer mirroring
historical_admission._admit's capsule/binding shape (FIXTURE_ONLY, with the
real _audit, validate_historical_chain and store manifests); the plan-only case
is the tiny regional fixture, not i04_differential_fixture (whose preparation
is loaded and source-checked but not called); the 10 GiB start gate is recorded
and not enforced; ACTUATED_CONTROL.duration is shown to refuse the non-unit-box
fixture and a stand-in reading only the two authenticated workload arrays gates
the authenticated duration. The 12 GiB / 1 GiB guard and 16 GiB ledger are used
unchanged.
"""
from contextlib import contextmanager
from copy import deepcopy
from fractions import Fraction as Q
import gc
from hashlib import sha256
import importlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from types import SimpleNamespace
import unittest


HERE = Path(__file__).resolve().parent
R = HERE.parent
C = R/'compact-geometry-r1'
RC = R/'composed-r1'
T = R.parents[3]
H = T/'fidelity-integration-20261005'/'heat-repair-20261007'
H_TESTS = H/'source'/'tectonics'/'tests'
SCRATCH = T/'_t'/'w4-runner-reader'
GUARD = RC/'helpers'/'private_heat_continuation_guard_r3.py'
RUNNER = RC/'helpers'/'run_prepared_restart.py'
READER = RC/'helpers'/'reopen_prepared_restart.py'
FIXTURE_ONLY = 'SYNTHETIC W4 FIXTURE ONLY; NOT HISTORICAL, SCIENTIFIC OR PRODUCTION ACCEPTANCE'
FIXTURE_HISTORICAL_EXECUTION = 'a'*64
# Frozen W3 identities this check runs against; a difference is investigated, never repinned.
EXPECTED = dict(
    manifest='6a6f493353942ebd27f10c73105fe7d10f5ab1bef1f4d54e72094ac5dcfe4e9b',
    profile='fffa99257a4e946edd9fe32d926a7c96e2319eec180c7d13782dc927f876de84',
    policy='fbe4c5e798023ba7f4d78b7cab84c7a070cb5e8939ce7605209fcde991e17ffa',
    guard='9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772',
    runner='69b5bbb4f88fbb2655e57ae95e4cddc7a901cdd20f2b78ce3af028f5381918b0',
    reader='7e4ec5198adad1a02f6f45f3833dc8bac63ac0d0450077c92199eb1e51b179e3',
    execution_identity='86c819bb9c62d591f0c1e529baae717254f6fa21b28537348fe153146c40c906',
    historical_source_manifest='f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c',
    historical_native_source_digest='746eea53c8dc9c9c89c8f7db8474e579fd5d2a2b919615b287358ddd4cb29d28')
FIXTURE_SOURCES = (Path(__file__).resolve(), R/'test_spatial_transfer.py', R/'test_native_transfer.py',
                   C/'test_partition_tables.py', C/'test_mesh_tables.py')
# The tiny two-process fixture's store limits; compression is the profile's raw codec.
STORE_LIMITS = dict(chunk_bytes=1024, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
    decoded_cache_bytes=0, max_manifest_bytes=2 << 20, max_chunks=100000, staging_memory_bytes=256*1024,
    max_staging_bytes=256*1024*1024, verified_cache_entries=2048, insert_batch_bytes=256*1024,
    sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
QUERY_LIMITS = dict(max_entries=4096, max_store_bytes=64 << 20)
MIN_AVAILABLE = 3 << 29   # 1.5 GiB before any heavy child; otherwise wait.
HEADER = ('source', 'funding_id', 'collar_plan_id', 'interval_id', 'parent_network_id',
          'endpoint_network_id', 'trajectory_id', 'start_time_s', 'end_time_s')
RESULT = 'W4_CHILD_RESULT '


class FixtureRefused(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise FixtureRefused(message)


def file_hash(path):
    digest = sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def rel(path):
    return Path(path).resolve().relative_to(T).as_posix()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


# --------------------------------------------------------------------------- shared child plumbing

def bootstrap(profile_path, profile_sha):
    """Import the composed runner exactly from RC/helpers, then build its fence."""
    entry = str(RC/'helpers')
    sys.path.insert(0, entry)
    try:
        import run_prepared_restart as RUN
    finally:
        sys.path.remove(entry)
    require(Path(RUN.__file__).resolve() == RUNNER, 'composed runner not selected')
    profile = RUN.RestartProfile.read(Path(profile_path), profile_sha)
    return RUN, profile, RUN.RestartSources(profile)


def fixture_modules(sources, budget):
    """Fixture builders only; their module/suite setup never runs. Call under selection.

    The two C table fixtures insert I/runtime-src at import; the native package
    and both table modules are bound from the composed tree first, and the
    insertion is removed again so sys.path stays the selected one.
    """
    for name in ('atlas_tectonics.integration_differential_geometry', 'atlas_tectonics.integration_volume',
                 'atlas_tectonics.integration_exterior_mesh', 'atlas_tectonics.integration_volume_bounds',
                 'atlas_tectonics.resources', 'atlas_tectonics.storage'):
        importlib.import_module(name)
    sources.module('mesh_tables')
    sources.module('partition_tables')
    saved = list(sys.path)
    import test_native_transfer as TN
    import test_spatial_transfer as TS
    import test_partition_tables as TP
    import test_mesh_tables as TM
    polluted = [entry for entry in sys.path if entry not in saved]
    sys.path[:] = saved
    TS.F = importlib.import_module('test_i04_regional_owner')
    TS.C = importlib.import_module('atlas_tectonics.regional_collar3d')
    TS.P = importlib.import_module('atlas_tectonics.integration_spatial_owner')
    TS.Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    TS.Registry = importlib.import_module('atlas_tectonics.integration_regional_inventory').ComponentRegistry
    TS.enc = importlib.import_module('atlas_tectonics.integration_mimetic_heat')._enc
    TS.TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError
    # The runner's single shared 16 GiB logical ledger, not a fixture-sized one.
    TS.WorkBudget = lambda _size: budget
    I3 = importlib.import_module('i03_fixtures')
    for module in (TN, TS, TP, TM):
        require(Path(module.__file__).resolve() in FIXTURE_SOURCES, 'fixture builder outside its declared file')
    return SimpleNamespace(TN=TN, TS=TS, TP=TP, TM=TM, I3=I3, polluted=polluted)


def release_fixture_class(TS):
    TS.SpatialTransferTests.tearDownClass()
    TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
    TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None


class FixturePlanOwner:
    """Identity-only stand-in for the radial case's plan-only owner (case['owner']).

    The tiny fixture has no plan-only regional owner; the runner reads only
    case['owner'].owner_id (preparation_ids) and the reader compares it. Its id
    is derived from the actual rebuilt fixture plans, so both processes must
    reproduce it independently.
    """
    __slots__ = ('owner_id',)

    def __init__(self, native, collar):
        record = dict(schema='w4.fixture-plan-owner.v1', authority=FIXTURE_ONLY, native_plan_id=native.plan_id,
                      collar_plan_id=collar.plan_id, volume_map_id=collar._map.volume_map_id)
        object.__setattr__(self, 'owner_id', sha256(canonical(record)).hexdigest())

    def __setattr__(self, name, value):
        raise AttributeError('fixture plan owner is immutable')


@contextmanager
def fixture_preparation(fx, budget):
    """The plan-only case analogue: tiny real native/collar plans; no funding, state or solve.

    Every object is on the shared budget and is closed at exit, as the
    preparation context closes the radial case.
    """
    TS = fx.TS
    TS.SpatialTransferTests.setUpClass()
    owners = TS.SpatialTransferTests
    try:
        require(owners.budget is budget, 'fixture plans must use the runner ledger')
        yield dict(native=owners.native, collar=owners.collar, owner=FixturePlanOwner(owners.native, owners.collar),
                   budget=budget, material=owners.native._material, fixture=FIXTURE_ONLY)
    finally:
        release_fixture_class(TS)


def loaded_report(sources):
    """Every loaded workspace module, grouped by tree; fixture files only from R/C."""
    groups = {}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if not filename or not filename.endswith('.py'):
            continue
        path = Path(filename).resolve()
        if not path.is_relative_to(T) or path.is_relative_to(T/'.r44-env'):
            continue
        if path.is_relative_to(RC/'runtime-src'):
            key = 'composed_native'
        elif path.is_relative_to(RC/'helpers'):
            key = 'composed_helpers'
        elif path.is_relative_to(RC/'ram'):
            key = 'composed_ram'
        elif path.is_relative_to(H_TESTS):
            key = 'historical_tests'
        else:
            require(path in FIXTURE_SOURCES, 'non-fixture module loaded outside the composed roots: '+str(path))
            key = 'fixture_sources'
        groups.setdefault(key, set()).add(rel(path))
    return {key: len(value) for key, value in sorted(groups.items())}, sorted(groups.get('fixture_sources', ()))


def real_mesh(fixture, TS, TM):
    """C/test_spatial_workflow_patch.real_mesh: a real two-box mesh record in the saved state."""
    import mesh_tables as M
    import spatial_transfer as S
    saved = fixture.args['historical_spatial_record']
    mesh = TM.small_mesh_record(fixture.budget)
    mesh.update(funding_id=saved['funding_id'], source=fixture.args['funding_record']['source'],
        grid_id=saved['grid_id'], support_id=saved['support_id'], time_s=TS.enc(saved['time_s']),
        trajectory_id=saved['trajectory_id'], trajectory_segments=saved['trajectory']['segments'])
    for geometric, stock in zip(mesh['cells'], saved['cells'], strict=True):
        geometric['kind'] = 'exterior'
        stock['cell_id'] = geometric['logical_cell_id']
    saved['thermal_mesh'], saved['thermal_mesh_id'] = mesh, M.digest(mesh)
    saved['state_id'] = S._snapshot_id({k: v for k, v in saved.items() if k != 'state_id'},
                                      S._bindings(fixture.args['spatial_arrays']))


def native_schema_parent(legacy, D, budget, TP):
    """C/test_partition_workflow_fresh_process.native_schema_parent: the archived header on tiny_partition."""
    body, supports = TP.tiny_partition(budget)
    for support in supports:
        support['components'][0]['constraints'] = [['carried:edge', 1], ['normal', -1]]
    for name in HEADER:
        body[name] = deepcopy(legacy[name])
    body['support_ids'] = [D._record_hash(row) for row in supports]
    for contact, ident in zip(body['native_contacts'][0]['contacts'], body['support_ids'], strict=True):
        contact['support_id'] = ident
    return dict(partition_id=D._record_hash(body), **body, supports=supports)


def array_rows(arrays):
    import numpy as np
    rows = []
    for name, value in sorted(arrays.items()):
        value = np.ascontiguousarray(value)
        rows.append(dict(name=name, dtype=value.dtype.str, shape=list(value.shape),
                         sha256=sha256(memoryview(value).cast('B')).hexdigest()))
    return rows


def fixture_admission(H, W, original, evidence, *, budget, check):
    """FIXTURE issuer mirroring historical_admission._admit's capsule and binding shape.

    The real _admit accepts only the reviewed ORIGINAL; this synthetic original is
    authenticated by its pinned bytes (open_successor_readonly hashed it), the
    real validate_historical_chain, its complete store manifests and the real
    historical_admission._audit. It grants nothing beyond this fixture.
    """
    require(getattr(original, '_historical_readonly', None) is not None, 'fixture original must be read-only')
    path = str(H._ordinary(original.path))
    require(H._ordinary(T/evidence['original']) == Path(path) and
            file_hash(path) == evidence['database_sha256'], 'fixture original differs from its evidence')
    with original._read_scope(budget=budget):
        token = original.change_token()
        chain = [original.metadata(key) for key in evidence['chain_keys']]
        W.validate_historical_chain(chain)
        manifests = {key: original._manifest(key)
                     for (key,) in original._db.execute('SELECT id FROM snapshots ORDER BY id')}
    head = chain[-1]
    store_token = dict(schema='atlas.historical-store-content-token.v1', database_sha256=evidence['database_sha256'],
                       fixture=FIXTURE_ONLY)
    source = dict(workflow_id=head['workflow_id'], root_key=chain[0]['key'], head_key=head['key'],
        sequence=head['sequence'], time_s=head['state']['fields']['time_s'], store_token=store_token,
        database_sha256=evidence['database_sha256'])
    capsule = dict(schema='atlas.restart-historical-endpoint.v1', authority=FIXTURE_ONLY, source=source,
        chain_metadata=chain, snapshot_manifests=manifests, producer=evidence['producer'])
    raw = H.canonical(capsule)
    binding = dict(schema='atlas.restart-historical-admission.v1', capsule_sha256=sha256(raw).hexdigest(),
        original_database_path=path, database_sha256=evidence['database_sha256'], origin=evidence['origin'],
        authority=FIXTURE_ONLY, historical_scientific_checks_reused=False, new_runtime_accepted=False,
        production_acceptance=False, continuation_authorised=False)
    binding_raw = H.canonical(binding)
    rows = evidence['producer']['array_records']['source_audit']
    owner = H._Allocation(budget, len(raw)+len(binding_raw)+sum(8*math.prod(r['shape']) for r in rows)+
                          len(H.canonical(head['source_audit']))+512*len(rows)+65536)
    with original._read_scope(budget=budget):
        audit = H._audit(original, head, dict(array_records=evidence['producer']['array_records'],
                         source_audit_id=head['advance']['source_audit_id']), owner, budget, check)
        require(original.change_token() == token, 'fixture original changed during admission')
    result = object.__new__(W.HistoricalEndpointAdmission)
    object.__setattr__(result, '_record', H._OwnedBytes(raw, owner))
    object.__setattr__(result, '_binding', H._OwnedBytes(binding_raw, owner))
    object.__setattr__(result, '_source_audit', audit)
    return result


class FixtureWorkloadControl:
    """Stand-in for ACTUATED_CONTROL.duration on the non-unit-box fixture.

    It reads exactly the two authenticated InitialWorkloadState arrays, checks
    them against the fixture's original root funding arrays, confirms any other
    access refuses, and returns the authenticated head duration it was given.
    """

    def __init__(self, expected, root_rows, IW):
        self.expected, self.rows, self.IW, self.seen = expected, root_rows, IW, None

    def duration(self, case):
        import numpy as np
        native = case['state'].native_state
        seen = {}
        for name in ('component_mass_kg', 'enthalpy_j'):
            array = native.array(name)
            require(not array.flags.writeable, 'initial workload array is writable')
            seen[name] = sha256(memoryview(np.ascontiguousarray(array)).cast('B')).hexdigest()
            require(seen[name] == self.rows[name], 'initial workload array differs from the original root')
        try:
            native.array('tracer:damage')
        except self.IW.InitialWorkloadRefused:
            seen['other_array_refused'] = True
        try:
            getattr(case['state'], 'fields')
        except self.IW.InitialWorkloadRefused:
            seen['other_attribute_refused'] = True
        require(seen.get('other_array_refused') and seen.get('other_attribute_refused'),
                'initial workload exposed more than its two arrays')
        self.seen = seen
        return self.expected


def failure_note(record, error):
    record.setdefault('fixture', {})['failure_traceback'] = ''.join(
        traceback.format_exception(type(error), error, error.__traceback__))[-12000:]


# --------------------------------------------------------------------------- process 0: fixture writer

def fixture_writer(profile_path, profile_sha, fixture_dir):
    import numpy as np
    RUN, profile, sources = bootstrap(profile_path, profile_sha)
    require(sys.dont_write_bytecode, 'run with -B')
    row = profile.record()
    fixture_dir = Path(fixture_dir).resolve()
    original, evidence_path = fixture_dir/'original.sqlite', fixture_dir/'evidence.json'
    require(fixture_dir.is_dir() and not original.exists() and not evidence_path.exists(),
            'fresh fixture directory required')
    with sources.selected():
        W = sources.module('workflow_transfer')
        N = sources.module('native_transfer')
        S = sources.module('spatial_transfer')
        sources.module('historical_admission')
        from atlas_tectonics.resources import WorkBudget
        from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
        from atlas_tectonics.integration_regional_workflow import CollarWorkflow
        from atlas_tectonics import integration_differential_geometry as D
        from atlas_tectonics import integration_wall_measures as WM
        budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
        fx = fixture_modules(sources, budget)
        TS = fx.TS
        limits, compression = StoreLimits(**row['store_limits']), Compression(**row['compression'])
        TS.SpatialTransferTests.setUpClass()
        owner = TS.SpatialTransferTests
        fixture = initial = None
        try:
            fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
            fixture.setUp()
            args, enc = fixture.args, TS.enc
            saved = args['historical_spatial_record']
            # A physical trajectory prefix and endpoint the native interval restore accepts.
            epoch = owner.source[0].network.network_id
            segments = [dict(parent_network_id=epoch, fixture=FIXTURE_ONLY, index=i) for i in (1, 2, 3)]
            trajectory_id, support_id = WM._hash(segments), WM._hash(dict(epoch_network_id=epoch, segments=segments))
            require(trajectory_id == N._hash(segments), 'trajectory hash conventions differ')
            saved.update(trajectory=dict(segments=segments), trajectory_id=trajectory_id, support_id=support_id)
            real_mesh(fixture, TS, fx.TM)
            with S.admit_migrated_spatial_owner(**args) as lease:
                initial = lease.adopt()
            native_record = fixture.native_owned.record()
            network = fx.I3.three_plates(sphere=fx.I3.sphere(radius=10.), time_s=12.5,
                                         longitudes_deg=(-240., -180., -120., -60., 0., 60.))
            body = dict(schema=D.SCHEMA, method='coaxial-physical-ownership-fan-v1', geometry_only=True,
                fixture=FIXTURE_ONLY, start_time_s=enc(8), end_time_s=enc(Q(25, 2)), duration_s=enc(Q(9, 2)),
                radius_m=enc(10), parent_network_id=epoch, endpoint_network_id=network.network_id,
                trajectory=dict(segments=segments), trajectory_id=trajectory_id,
                prior_trajectory_id=WM._hash(segments[:-1]),
                start_support_id=WM._hash(dict(epoch_network_id=epoch, segments=segments[:-1])),
                end_support_id=support_id, rays={}, boundary_paths=[], plate_angular_velocity_rad_s={},
                ownership_fans=[])
            interval = D._issue(D.DifferentialInterval, body, budget, network)
            require(interval.interval_id == D._record_hash(body), 'fixture interval identity convention differs')
            current = D.current_geometry_from_interval(interval, budget=budget)
            funding = initial.funding
            require(funding.funding_id == args['funding_record']['funding_id'], 'fixture funding identity differs')
            legacy = dict(source=funding._snapshot.descriptor()['source'], funding_id=funding.funding_id,
                collar_plan_id=owner.old['collar']['plan_id'], interval_id=interval.interval_id,
                parent_network_id=epoch, endpoint_network_id=network.network_id, trajectory_id=trajectory_id,
                start_time_s=enc(8), end_time_s=enc(Q(25, 2)))
            descriptor = native_schema_parent(legacy, D, budget, fx.TP)
            raw = W.canonical(descriptor)
            refs = {'partition': dict(array='partition-record:partition', bytes=len(raw), sha256=sha256(raw).hexdigest())}
            ident = '1'*64
            root = dict(schema=W.WORKFLOW_SCHEMA, kind='root', sequence=0, workflow_id=ident,
                key=W.workflow_key('root', ident), funding_id=funding.funding_id, funding=args['funding_record'],
                exterior_remainder=funding.exterior_remainder(), exterior_owner=args['historical_owner_definition'],
                collar_plan=owner.old['collar']['definition'],
                state=dict(result_id='2'*64, fields=dict(time_s=0.), native={}), native_state_id='3'*64,
                exterior_state=dict(state_id='4'*64), fixture=FIXTURE_ONLY)
            full = {k: np.array(v) for k, v in fixture.native_owned.state.arrays().items()}
            collar = owner.collar
            native_fields = {k: np.ascontiguousarray(collar._slice(k, v)) for k, v in full.items()}
            spatial_arrays = dict(args['spatial_arrays'])
            with CollarWorkflow._spatial_records(saved, None, budget) as (spatial_header, _, spatial_blobs), \
                    CollarWorkflow._differential_payload(interval, budget) as (geometry_header, geometry_arrays):
                restored = CollarWorkflow._restore_differential(geometry_header, geometry_arrays, budget)
                require(restored.interval_id == interval.interval_id, 'fixture interval does not restore natively')
                del restored
                chain, payloads = [root], {root['key']: dict(args['funding_arrays'])}
                for sequence, end in ((1, 4.), (2, 8.), (3, 12.5)):
                    previous, last = chain[-1], sequence == 3
                    state = native_record['input']['historical_collar'] if last else dict(
                        result_id=('c' if sequence == 2 else '5')*64,
                        fields=dict(time_s=end, parent_id=previous['state']['result_id']),
                        native=dict(parent_state_id=previous['native_state_id']))
                    audit = TS.Snapshot(dict(schema='fixture.synthetic-source-audit.v1',
                        parent_state_id=previous['native_state_id'], start_time_s=previous['state']['fields']['time_s'],
                        duration_s=end-previous['state']['fields']['time_s'], fixture=FIXTURE_ONLY),
                        {'fixture': np.array([float(sequence)])})
                    exterior = spatial_header if last else dict(state_id=('9' if sequence == 2 else '6')*64,
                        parent_state_id=previous['exterior_state']['state_id'], intervals=sequence, time_s=end,
                        collar_state_id=state['result_id'])
                    current_row = dict(schema=W.WORKFLOW_SCHEMA, kind='successor', sequence=sequence,
                        workflow_id=ident, key=W.workflow_key('successor', previous['key']),
                        parent_key=previous['key'], parent_digest=W.digest(previous), funding_id=root['funding_id'],
                        state=state, native_state_id=(native_record['input']['historical_native_id'] if last else
                                                     ('b' if sequence == 2 else '7')*64),
                        advance=dict(duration_s=audit.descriptor()['duration_s'], source_audit_id=audit.result_id),
                        source_audit=audit.descriptor(), exterior_state=exterior,
                        exterior_advance=dict(fixture=FIXTURE_ONLY, joined_heat_id=('e' if last else 'd')*64),
                        differential_geometry=geometry_header if last else dict(fixture=FIXTURE_ONLY, sequence=sequence),
                        differential_partition=(CollarWorkflow._partition_header(descriptor, refs) if last else
                                                dict(fixture=FIXTURE_ONLY, sequence=sequence)),
                        differential_certification=dict(endpoint_current_geometry_id=(current.geometry_id if last else
                                                                                      'f'*64)))
                    payload = {'source-audit:'+k: audit.array(k) for k in audit.array_names}
                    if last:
                        head_audit = audit
                        payload.update(full)
                        payload.update({'exterior-fv:'+k: v for k, v in spatial_arrays.items()})
                        payload['spatial-audit:fixture'] = np.array([3.])
                        payload.update(spatial_blobs)
                        payload.update(geometry_arrays)
                        payload['partition-record:partition'] = np.frombuffer(raw, dtype=np.uint8)
                    chain.append(current_row)
                    payloads[current_row['key']] = payload
                W.validate_historical_chain(chain)
                with ArrayStore(original, limits, compression, budget=budget) as store:
                    for current_row in chain:
                        store.put(current_row['key'], payloads[current_row['key']], current_row, budget=budget)
                del payloads, payload, spatial_blobs, geometry_arrays
            head = chain[-1]
            groups = dict(full_collar=array_rows(full), native=array_rows(native_fields),
                exterior=array_rows(spatial_arrays), collar=array_rows(full),
                source_audit=array_rows({k: head_audit.array(k) for k in head_audit.array_names}),
                spatial_audit=array_rows({'fixture': np.array([3.])}))
            producer = dict(execution_identity=FIXTURE_HISTORICAL_EXECUTION, execution_mode='strict',
                source_manifest_sha256=EXPECTED['historical_source_manifest'],
                native_source_digest=EXPECTED['historical_native_source_digest'],
                original_status='FIXTURE', original_finalisation_not_certified=True, array_records=groups,
                preparation_ids=dict(native=owner.old['native']['plan_id'], collar=owner.old['collar']['plan_id'],
                    map=collar._map.volume_map_id, owner='2'*64, spatial_owner=args['historical_owner_definition']['owner_id'],
                    funding=funding.funding_id), authority=FIXTURE_ONLY)
            origin = dict(producer_receipt_sha256=sha256(b'w4 fixture producer').hexdigest(),
                store_token_sha256=W.digest(dict(fixture=FIXTURE_ONLY)), endpoint_lineage_sha256=W.digest(chain))
            root_rows = {r['name']: r['sha256'] for r in array_rows(
                {k: v for k, v in args['funding_arrays'].items() if k in ('component_mass_kg', 'enthalpy_j')})}
            result = dict(interval_id=interval.interval_id, partition_id=descriptor['partition_id'],
                current_geometry_id=current.geometry_id, thermal_mesh_id=saved['thermal_mesh_id'],
                spatial_state_id=saved['state_id'], head_key=head['key'], root_key=root['key'],
                fixture_owner_definition_id=args['historical_owner_definition']['owner_id'],
                plan_ids=dict(old_native=owner.old['native']['plan_id'], old_collar=owner.old['collar']['plan_id'],
                              current_native=owner.current['native']['plan_id'],
                              current_collar=owner.current['collar']['plan_id']),
                current_execution=owner.current['native']['definition']['execution'])
            del interval, current, network, descriptor, raw, full, native_fields, spatial_arrays, head_audit, audit
            # Release every budgeted fixture owner reference before the ledger check.
            del args, saved, funding, collar, native_record, legacy, root, head, state, exterior, current_row
        finally:
            if initial is not None:
                initial.owner.close()
            initial = None
            if fixture is not None:
                fixture.args = fixture.native_owned = None
            fixture = None
            release_fixture_class(TS)
        gc.collect()
        require(budget.reserved_bytes == 0, 'fixture writer retained reservations: '+str(budget.reserved_bytes))
        loaded, fixture_files = loaded_report(sources)
        sources.check_imported()
    require(not any(Path(str(original)+s).exists() for s in ('-wal', '-journal', '-shm')), 'fixture original open')
    database_sha = file_hash(original)
    evidence = dict(schema='w4.fixture-historical-evidence.v1', authority=FIXTURE_ONLY, original=rel(original),
        database_sha256=database_sha, database_bytes=original.stat().st_size, chain_keys=[r['key'] for r in chain],
        producer=producer, origin=origin, root_workload_array_sha256=root_rows, store_limits=row['store_limits'],
        compression=row['compression'], fixture=result)
    with evidence_path.open('x', encoding='utf8') as stream:
        json.dump(evidence, stream, indent=1, sort_keys=True, allow_nan=False)
    print(RESULT+json.dumps(dict(role='fixture-writer', pid=os.getpid(), original=str(original),
        database_sha256=database_sha, evidence=str(evidence_path), evidence_sha256=file_hash(evidence_path),
        reserved_bytes=0, loaded=loaded, fixture_files=fixture_files, sys_path_pollution_removed=fx.polluted,
        fixture=result), sort_keys=True), flush=True)
    return 0


# --------------------------------------------------------------------------- process A: producer

def driver_drills(RUN, *, sources, workflow, base, case, execution, guard, output, driver, store, query_directory,
                  query_limits, check):
    """Driver stand-ins and the real driver's early gates; nothing may be persisted."""
    from concurrent.futures import CancelledError
    from atlas_tectonics.integration_endpoint_checkpoints import EndpointCheckpoints
    variable = 'ATLAS_FOCUSED_ARTIFACT_DIR'
    previous = os.environ.get(variable)
    before, token = workflow.inspect(), store.change_token()
    accepted = case['native'].statistics()['accepted_intervals']
    drills, fences = {}, []

    def fence():
        fences.append('fence')
        sources.check_imported()

    def unchanged(label):
        require(os.environ.get(variable) == previous, label+': artifact capture variable not restored')
        require(store.change_token() == token and workflow.inspect() == before and
                case['native'].statistics()['accepted_intervals'] == accepted,
                label+': store, head or native operations changed')

    calls = []

    def textual_pass(**kwargs):
        calls.append(sorted(kwargs))
        require(os.environ.get(variable) == str(RUN.ordinary(output, directory=True)), 'capture directory not set')
        return dict(status='PASS', production_acceptance=True)
    try:
        RUN._advance_checked(textual_pass, workflow=workflow, base=base, case=case, execution=execution,
            guard=guard, record={}, save=lambda: None, artifacts=output, query_checkpoints=None, fence=fence)
    except RUN.RestartRefused as error:
        drills['textual_pass'] = dict(refused=True, type=type(error).__name__, message=str(error))
    else:
        raise FixtureRefused('a textual PASS from the driver was accepted')
    require('exactly one valid successor' in drills['textual_pass']['message'] and fences == ['fence', 'fence'],
            'textual PASS refused for the wrong reason')
    unchanged('textual PASS')

    saves, fences[:] = [], []

    def cancelled(**kwargs):
        kwargs['save']()
        raise CancelledError('W4 cancellation drill after save()')
    try:
        RUN._advance_checked(cancelled, workflow=workflow, base=base, case=case, execution=execution,
            guard=guard, record={}, save=lambda: saves.append('save'), artifacts=output, query_checkpoints=None,
            fence=fence)
    except CancelledError as error:
        drills['cancellation'] = dict(propagated=True, type=type(error).__name__, message=str(error),
                                      saves=len(saves), fences=list(fences))
    else:
        raise FixtureRefused('driver cancellation was swallowed')
    require(saves == ['save'] and fences == ['fence'], 'cancellation drill did not run as expected')
    unchanged('cancellation')

    # The real composed driver with an active completed-query owner: it must stop
    # at its own early gates (this fixture is not the unit-box actuated case).
    fences[:] = []
    record = {}
    with EndpointCheckpoints(query_directory, context=execution, budget=case['budget'], cancel=check,
            max_store_bytes=query_limits['max_store_bytes'], max_entries=query_limits['max_entries']) as queries:
        try:
            RUN._advance_checked(driver, workflow=workflow, base=base, case=case, execution=execution,
                guard=guard, record=record, save=lambda: None, artifacts=output, query_checkpoints=queries,
                fence=fence)
        except Exception as error:
            text = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
            drills['real_driver_early_gate'] = dict(refused=True, type=type(error).__name__, message=str(error),
                at_actuated_duration='duration' in text and 'workload' in text,
                endpoint_checkpoints_gate_passed='completed-query owner is required' not in str(error),
                initial_state_gate_passed="must be the authenticated InitialWorkloadState" not in str(error),
                physical_work_started='original_target' in record,
                completed_queries=dict(hits=queries.hits, misses=queries.misses, written=queries.written))
        else:
            raise FixtureRefused('the real driver ran on a non-actuated fixture case')
    gate = drills['real_driver_early_gate']
    require(gate['at_actuated_duration'] and gate['endpoint_checkpoints_gate_passed'] and
            gate['initial_state_gate_passed'] and not gate['physical_work_started'] and fences == ['fence'],
            'real driver did not stop at the actuated duration gate before work')
    unchanged('real driver gate')
    drills['stand_in_call_keywords'] = calls[0]
    return drills


def root_evidence(REOPEN, D, W, workflow, store, base):
    """The producer's formulas on the published root, for the independent comparison."""
    from atlas_tectonics.storage import ArrayReference
    # endpoint_array_records is the successor formula; a migrated root carries no
    # spatial-audit arrays (spatial_audit_arrays is None), so that one group is
    # recorded as None and the other five use the identical D.snapshots/D.arrays.
    state, exterior, spatial_audit = workflow.state, workflow.exterior_state, workflow.spatial_audit_arrays
    groups = dict(collar=D.snapshots(state.fields), native=D.snapshots(state.native_state),
        exterior=D.snapshots(exterior._snapshot), source_audit=D.snapshots(workflow.source_audit),
        full_collar=D.arrays(state.arrays()),
        spatial_audit=None if spatial_audit is None else D.arrays(spatial_audit))
    del state, exterior, spatial_audit
    with W.migrated_root_payload(base, store=store) as (root, payload):
        references = sorted(name for name, value in payload.items() if type(value) is ArrayReference)
        paths = sorted({value.store_path for value in payload.values() if type(value) is ArrayReference})
        root_digest = W.digest(root)
    return dict(array_records=json.loads(json.dumps(groups)), inspect=workflow.inspect(),
        root_metadata_sha256=root_digest, collar_result_id=workflow.state.result_id,
        native_result_id=workflow.state.native_state.result_id, exterior_state_id=workflow.exterior_state.state_id,
        source_audit_id=workflow.source_audit.result_id, funding_id=workflow._funding.funding_id,
        funding_descriptor_sha256=W.digest(workflow._funding.descriptor()),
        partition_id=workflow.differential_partition.partition_id,
        interval_id=workflow.differential_interval.interval_id, compact_reference_arrays=len(references),
        compact_reference_names_sha256=W.digest(references), reference_store_paths=paths,
        compact_partition=json.loads(json.dumps(json.loads(workflow._root).get('compact_partition'))),
        compact_mesh=json.loads(json.dumps(json.loads(workflow._root)['exterior_state'].get('compact_mesh'))))


def fixture_runner(RUN, profile, *, sources, guard, record, save, evidence_path, evidence_sha):
    """run_prepared_restart (lines 641-797) with --stop-before-advance, fixture substitutions marked."""
    require(type(profile) is RUN.RestartProfile and type(sources) is RUN.RestartSources and
            sources.profile is profile and sources.selected_now, 'actual selected pinned sources required')
    row = profile.record()
    H = sources.module('historical_admission')
    M = sources.module('materialise_endpoint')
    W = sources.module('workflow_transfer')
    P = sources.module('plan_preparation')
    IW = sources.module('initial_workload')
    driver_module = sources.module(row['advance_driver']['module'])
    require('working_store' in inspect.signature(M.materialise).parameters, 'store-aware materialisation missing')
    driver = getattr(driver_module, 'advance_prepared_interval', None)
    require(inspect.isfunction(driver) and driver.__module__ == driver_module.__name__, 'named driver required')
    inspect.signature(driver).bind(**{k: None for k in ('case', 'workflow', 'base', 'execution', 'guard',
        'record', 'save', 'artifacts', 'query_checkpoints')})
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    bound = {name: sources.module(name) for name in RUN.REQUIRED_MODULES}
    control = bound['i04_differential_modes'].ACTUATED_CONTROL
    REOPEN = sources.module('reopen_prepared_restart') if 'reopen_prepared_restart' in row['modules'] else \
        importlib.import_module('reopen_prepared_restart')
    require(hasattr(CollarWorkflow, 'open_migrated'), 'composed migrated-root native reader is missing')
    require_strict_execution()
    record.update(RUN.interpreter_gate(), stop_before_advance=True)
    RUN._check_historical_root(sources, H, row)
    fixture = record.setdefault('fixture', {})
    fixture.update(authority=FIXTURE_ONLY, historical_root=str(H.HISTORICAL_ROOT),
        guard_pins=dict(GUARD_PIN=H.GUARD_PIN, JOB_PIN=H.JOB_PIN, DIAGNOSTICS_PIN=H.DIAGNOSTICS_PIN,
                        HISTORICAL_GUARD_PIN=H.HISTORICAL_GUARD_PIN))
    output = Path(row['output_directory'])
    require(RUN.ordinary(output, directory=True) == output and output.is_relative_to(sources.workspace) and
            guard.output == output/'run.json', 'guard and fresh restart output directory differ')
    destination = output/'checkpoint.sqlite'
    require(not destination.exists() and not any(output.glob('checkpoint.sqlite*')), 'checkpoint exists')
    query_directory = sources.workspace/row['completed_query_directory']
    RUN.ordinary(query_directory.parent, directory=True)
    require(query_directory.resolve().is_relative_to(sources.workspace) and
            not query_directory.is_relative_to(output), 'completed-query directory must be outside this attempt')
    query_directory.mkdir(exist_ok=True)
    RUN.ordinary(query_directory, directory=True)
    query_limits = row['completed_query_limits']
    import psutil
    available = psutil.virtual_memory().available
    # FIXTURE SUBSTITUTION: recorded, not enforced, for this tiny fixture.
    fixture['start_gate'] = dict(required_bytes=RUN.START_BYTES, available_bytes=available,
        would_pass=available >= RUN.START_BYTES, enforced=False,
        reason='tiny synthetic fixture under the unchanged 12 GiB / 1 GiB guard; the real launch keeps the gate')
    guard.budget = budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget)
    H._loaded_source_fence(driver_module, row['advance_driver']['sha256'], lambda: guard.check(force=True))
    receipt = H.guardian_fence(guard, budget=budget, check=lambda: guard.check(force=True))
    fixture['guardian_fence'] = dict(status=receipt['status'], limits=receipt['limits'])
    record.update(guard_limits=dict(rss_bytes=RUN.RSS_BYTES, free_floor_bytes=RUN.FREE_BYTES,
        start_available_bytes=RUN.START_BYTES, logical_budget_bytes=RUN.LOGICAL_BYTES),
        memory_at_start=dict(available_bytes=available), source_proof=sources.verify(),
        completed_query_limits=dict(query_limits), production_acceptance=False,
        original_producer_status_unchanged=True)
    limits, compression = StoreLimits(**row['store_limits']), Compression(**row['compression'])
    import shutil
    require(shutil.disk_usage(output).free >= 2*limits.max_store_bytes + limits.max_staging_bytes +
            query_limits['max_store_bytes'], 'insufficient disk headroom')
    preparation = P.load_preparation(sources.path(row['preparation']['path']))
    # FIXTURE SUBSTITUTION: the real radial preparation is loaded/source-checked, not called.
    fixture['preparation_loaded'] = dict(name=preparation.__name__, called=False)
    del preparation
    compatibility = RUN._compatibility(sources, row)
    check = lambda: guard.check(force=True)
    evidence = RUN.pinned_json(Path(evidence_path), evidence_sha)
    require(evidence.get('authority') == FIXTURE_ONLY, 'fixture evidence required')
    fx = fixture_modules(sources, budget)
    fixture['fixture_sys_path_pollution_removed'] = fx.polluted
    guard.phase('prepare-current-plans-without-funding')
    original_path = original_pin = None
    try:
        with ExecutionContext('scipy') as execution, fixture_preparation(fx, budget) as case:
            guard.phase('authenticate-historical-endpoint-readonly')
            # FIXTURE SUBSTITUTION: synthetic original, read-only, never the reviewed ORIGINAL.
            with H.open_successor_readonly(T/evidence['original'], expected_sha256=evidence['database_sha256'],
                    limits=limits, compression=compression, budget=budget, check=check) as original:
                admission = fixture_admission(H, W, original, evidence, budget=budget, check=check)
                require(type(admission) is W.HistoricalEndpointAdmission, 'historical issuer returned no admission')
                guard.phase('copy-authenticated-checkpoint-to-fresh-output')
                original_path, original_pin = RUN._copy_original(admission, destination, budget=budget, check=check)
                RUN.storage_point(record, 'original', checkpoint=original_path)
                RUN.storage_point(record, 'after-copy', checkpoint=destination, query_directory=query_directory,
                                  output=output)
                save()
                with ArrayStore(destination, limits, compression, budget=budget) as store:
                    guard.phase('transfer-authenticated-endpoint-to-current-owners')
                    with M.materialise(original_store=original, admission=admission, native=case['native'],
                            collar=case['collar'], execution=execution, compatibility=compatibility,
                            budget=budget, check=check, working_store=store, phase=guard.phase) as base:
                        require(type(base) is W.MigratedWorkflowBase and
                                type(base._runtime) is W.RuntimeCompatibilityAdmission,
                                'materialiser returned no authenticated current base')
                        sources.verify()
                        RUN._check_runtime_binding(base, row, execution, budget)
                        fixture['runtime_admission'] = base._runtime.record()
                        fixture['base_partition_compact'] = base._partition.compact_view() is not None
                        fixture['base_mesh_compact'] = type(base._spatial.state._snapshot).__name__
                        RUN.storage_point(record, 'after-materialise', checkpoint=destination, store=store)
                        guard.phase('authenticate-frozen-initial-workload')
                        state = IW.initial_workload_state(original_store=original, admission=admission,
                            collar=case['collar'], budget=budget, check=check)
                        continuation_case = dict(case, funding=base._spatial.funding,
                            created_tracers=('tracer:accumulated_strain_ii',), state=state)
                        expected = IW.authenticated_duration(admission, budget)
                        try:
                            IW.require_initial_duration(control, continuation_case, expected=expected)
                        except Exception as error:
                            fixture['actuated_control_on_fixture'] = dict(refused=True, type=type(error).__name__,
                                                                          message=str(error))
                        else:
                            raise FixtureRefused('ACTUATED_CONTROL accepted the non-unit-box fixture')
                        stand_in = FixtureWorkloadControl(expected, evidence['root_workload_array_sha256'], IW)
                        duration = IW.require_initial_duration(stand_in, continuation_case, expected=expected)
                        fixture['initial_workload_stand_in'] = stand_in.seen
                        record['initial_workload'] = dict(state=state.record(), duration_s=duration,
                            gate='equals the authenticated historical head advance duration_s')
                        del state
                        # Cancellation drill on the real publication route: nothing persists.
                        token = store.change_token()
                        cancel = threading.Event()
                        cancel.set()
                        with W.migrated_root_payload(base, store=store) as (expected_root, _payload):
                            root_key = expected_root['key']
                        try:
                            W.publish_migrated_root(store, base, budget=budget, cancel=cancel)
                        except Exception as error:
                            fixture['cancelled_publication'] = dict(type=type(error).__name__, message=str(error))
                        else:
                            raise FixtureRefused('a cancelled publication published the migrated root')
                        require(fixture['cancelled_publication']['type'] == 'CancelledError' and
                                store.change_token() == token and store.metadata(root_key) is None,
                                'cancelled publication changed the working store')
                        with RUN.publish_and_reopen(store, base, budget=budget, check=check,
                                                    phase=guard.phase) as workflow:
                            record['published_root'] = RUN._published_root(workflow, store, base, case,
                                                                           execution, budget)
                            RUN.storage_point(record, 'after-publish-reopen', checkpoint=destination, store=store)
                            save()
                            before, after = record['published_root']['inspect'], None
                            guard.phase('stopped-before-advance-root-published')
                            fixture['root'] = root_evidence(REOPEN, bound['probe_heat_original_connected_r9'], W,
                                                            workflow, store, base)
                            fixture['drills'] = driver_drills(RUN, sources=sources, workflow=workflow, base=base,
                                case=continuation_case, execution=execution, guard=guard, output=output,
                                driver=driver, store=store, query_directory=query_directory,
                                query_limits=query_limits, check=check)
                            save()
                        record.update(migrated_base=base.record(), previous_endpoint=before,
                            checkpoint=str(destination), same_process_cold_reopen=True,
                            independent_process_reopen=False)
                        if after is not None:
                            record['advanced_endpoint'] = after
                        del continuation_case, base, workflow, stand_in
                RUN.storage_point(record, 'after-store-close', checkpoint=destination,
                                  query_directory=query_directory, output=output)
                save()
                del admission
            execution.verify_boundary()
        fixture['loaded_modules'], fixture['fixture_files_loaded'] = loaded_report(sources)
        sources.check_imported()
        sources.verify()
        require(RUN.file_hash(original_path, check) == original_pin, 'original checkpoint changed')
        record['checkpoint_sha256'] = RUN.file_hash(destination, check)
        record['original_database_unchanged'] = True
        return budget
    finally:
        if original_path is not None:
            active_error = sys.exception()
            try:
                require(RUN.file_hash(original_path, check) == original_pin, 'original changed during failed work')
            except BaseException as verification_error:
                if active_error is None:
                    raise
                active_error.add_note('Original binding finalisation also failed: '+repr(verification_error))


def producer_main(profile_path, profile_sha, evidence_path, evidence_sha):
    """run_prepared_restart._workload with fixture_runner in place of run_prepared_restart."""
    RUN, profile, sources = bootstrap(profile_path, profile_sha)
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    output = Path(profile.record()['output_directory'])/'run.json'
    record = dict(schema=RUN.RESULT_SCHEMA, status='STARTED', pid=os.getpid(), profile_sha256=profile.sha256,
        errors=[], production_acceptance=False, stop_before_advance=True)
    guard = budget = None
    started = time.monotonic()
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    with sources.selected():
        G = sources.module('private_heat_continuation_guard_r3')
        save = lambda: G._write(output, record)
        try:
            guard = G.ContinuationGuard(output, record, save)
            budget = fixture_runner(RUN, profile, sources=sources, guard=guard, record=record, save=save,
                                    evidence_path=evidence_path, evidence_sha=evidence_sha)
            record['status'] = 'VERIFYING_FINALISATION'
        except BaseException as error:
            record['status'] = 'FAILED'
            record['errors'].append(dict(type=type(error).__name__, message=str(error)))
            failure_note(record, error)
            if guard is not None and guard.budget is not None:
                record['logical_budget_at_failure'] = guard.budget.statistics()
            save()
        finally:
            gc.collect()
            budget = budget if budget is not None else getattr(guard, 'budget', None)
            if budget is not None:
                record['final_reserved_bytes'] = budget.reserved_bytes
                statistics = budget.statistics()
                record['logical_budget_final'] = dict(peak_reserved_bytes=statistics['peak_reserved_bytes'],
                    category_peaks=statistics['category_peaks'])
                if budget.reserved_bytes:
                    record['errors'].append(dict(type='RetainedReservations', message=str(budget.reserved_bytes)))
            times = os.times()
            record['parent_cpu_seconds'] = dict(user=times.user, system=times.system)
            record.setdefault('fixture', {})['wall_seconds'] = time.monotonic()-started
            try:
                import psutil
                record['fixture']['remaining_children'] = [c.pid for c in psutil.Process().children(recursive=True)]
                sources.check_imported()
                sources.verify()
                if guard is not None:
                    guard.check(force=True)
                    guard.close()
            except BaseException as error:
                record['errors'].append(dict(type=type(error).__name__, message=str(error)))
            record['status'] = RUN.final_status(record['errors'], stop_before_advance=True)
            save()
    print(RESULT+json.dumps(dict(role='producer', pid=os.getpid(), status=record['status'],
        errors=record['errors']), sort_keys=True), flush=True)
    return 0 if not record['errors'] else 1


# --------------------------------------------------------------------------- process B: independent reader

def store_get_alias_probe(store, key, PW, *, budget):
    """What CollarWorkflow.spatial_audit_arrays does to a head: store.get(head_key).

    Measured here on the alias-carrying migrated root (a root returns None from
    the property itself); a migrated successor head carries the same partition
    and mesh alias families. Read-only: the token is unchanged afterwards.
    """
    token = store.change_token()
    with store._read_scope(budget=budget):
        arrays = dict(store._manifest(key)['arrays'])
    aliases = sorted(n for n in arrays if n.startswith(('partition-dag:', 'spatial-mesh:')))
    full = store.get(key, budget=budget)
    filtered = PW.workflow_arrays(store, key, budget=budget)
    result = dict(snapshot=key, manifest_arrays=len(arrays), alias_arrays=len(aliases),
        store_get_arrays=len(full), store_get_loads_every_alias=all(n in full for n in aliases),
        store_get_bytes=sum(v.nbytes for v in full.values()),
        store_get_alias_bytes=sum(full[n].nbytes for n in aliases),
        workflow_arrays_arrays=len(filtered), workflow_arrays_aliases=sorted(set(filtered) & set(aliases)),
        workflow_arrays_bytes=sum(v.nbytes for v in filtered.values()),
        max_array_bytes=store.limits.max_array_bytes)
    del full, filtered
    require(store.change_token() == token, 'store_get probe wrote to the reader store')
    return result


def readonly_without_tables(RUN, H, M, original, admission, case, execution, compatibility, evidence, output, *,
                            limits, compression, budget, check, phase):
    """W2-B request: a read-only store without converted compact tables refuses, writing nothing.

    Also: the successor read-only opener refuses the historical tree (a small
    JSON file there, never the historical database) before hashing anything.
    """
    try:
        H.open_successor_readonly(H.HISTORICAL_ROOT/'continuation-preparation-r3.json', expected_sha256='0'*64,
                                  limits=limits, compression=compression, budget=budget, check=check)
    except H.HistoricalAdmissionRefused as error:
        tree = dict(refused=True, message=str(error))
    else:
        raise FixtureRefused('open_successor_readonly accepted a path in the historical tree')
    require(tree['message'] == 'successor reader refuses the historical tree', 'historical tree refused for another reason')
    bare = output/'bare-original-copy.sqlite'
    RUN._copy_bound_file(T/evidence['original'], evidence['database_sha256'], bare, budget=budget, check=check)
    phases = []
    with H.open_successor_readonly(bare, expected_sha256=evidence['database_sha256'], limits=limits,
                                   compression=compression, budget=budget, check=check) as store:
        token, snapshots = store.change_token(), store.statistics()['snapshots']
        try:
            with M.materialise(original_store=original, admission=admission, native=case['native'],
                    collar=case['collar'], execution=execution, compatibility=compatibility, budget=budget,
                    check=check, working_store=store, phase=lambda name: (phases.append(name), phase(name))):
                raise FixtureRefused('materialise accepted a read-only store without converted compact tables')
        except M.EndpointMaterialisationRefused as error:
            refusal = dict(refused=True, type=type(error).__name__, message=str(error))
        require(refusal['message'] == 'readonly successor store lacks its converted compact mesh',
                'read-only store without compact tables refused for another reason: '+refusal['message'])
        require(store.change_token() == token and store.statistics()['snapshots'] == snapshots,
                'refused read-only materialisation wrote to the store')
    require(RUN.file_hash(bare, check) == evidence['database_sha256'], 'bare read-only copy changed')
    return dict(historical_tree=tree, materialise=refusal, conversion_phases_reached=phases,
                store_unchanged=True, copy_unchanged=True)


def fixture_reader(REOPEN, profile, *, sources, guard, record, save, producer, receipt, evidence_path, evidence_sha):
    """reopen_prepared_restart.reopen_prepared_restart (root-only), fixture substitutions marked."""
    RUN = REOPEN.RUN
    mode, store_route = 'root-only', 'readonly'
    require(type(profile) is RUN.RestartProfile and type(sources) is RUN.RestartSources and
            sources.profile is profile and sources.selected_now, 'actual selected pinned sources required')
    require(producer.get('mode') == mode, 'validated producer expectation for this mode required')
    row = profile.record()
    H = sources.module('historical_admission')
    M = sources.module('materialise_endpoint')
    W = sources.module('workflow_transfer')
    P = sources.module('plan_preparation')
    IW = sources.module('initial_workload')
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    bound = {name: sources.module(name) for name in RUN.REQUIRED_MODULES}
    D = bound['probe_heat_original_connected_r9']
    control = bound['i04_differential_modes'].ACTUATED_CONTROL
    import test_i04_spatial_workflow as FLOW
    REOPEN._own_pin(sources)
    require(hasattr(CollarWorkflow, 'open_migrated') and 'working_store' in inspect.signature(M.materialise).parameters,
            'composed migrated-root reader and store-aware materialisation required')
    require_strict_execution()
    RUN._check_historical_root(sources, H, row)
    output = guard.output.parent
    REOPEN.reader_output(profile, sources, str(output), exists=True)
    import psutil
    available = psutil.virtual_memory().available
    fixture = record.setdefault('fixture', {})
    fixture.update(authority=FIXTURE_ONLY, start_gate=dict(required_bytes=RUN.START_BYTES,
        available_bytes=available, would_pass=available >= RUN.START_BYTES, enforced=False))
    guard.budget = budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget)
    check = lambda: guard.check(force=True)
    record.update(guard_limits=dict(rss_bytes=RUN.RSS_BYTES, free_floor_bytes=RUN.FREE_BYTES,
        start_available_bytes=RUN.START_BYTES, logical_budget_bytes=RUN.LOGICAL_BYTES),
        memory_at_start=dict(available_bytes=available), source_proof=sources.verify(),
        launch_environment={name: os.environ.get(name) for name in sorted(RUN.LAUNCH_ENV)},
        production_acceptance=False)
    limits, compression = StoreLimits(**row['store_limits']), Compression(**row['compression'])
    source = RUN.ordinary(producer['checkpoint'])
    copy = output/REOPEN.CHECKPOINT
    import shutil
    require(shutil.disk_usage(output).free >= source.stat().st_size + limits.max_staging_bytes, 'disk headroom')
    guard.phase('copy-producer-checkpoint-to-reader-output')
    RUN._copy_bound_file(source, producer['checkpoint_sha256'], copy, budget=budget, check=check)
    P.load_preparation(sources.path(row['preparation']['path']))
    compatibility = RUN._compatibility(sources, row)
    published = producer['published_root']
    ids = published['preparation_ids']
    checks = dict.fromkeys(REOPEN.INDEPENDENT_CHECKS[mode], False)
    evidence = RUN.pinned_json(Path(evidence_path), evidence_sha)
    fx = fixture_modules(sources, budget)
    original_path = original_pin = None
    guard.phase('prepare-current-plans-without-funding')
    try:
        with ExecutionContext('scipy') as execution, fixture_preparation(fx, budget) as case:
            collar = case['collar']
            require(execution.provenance == published['execution_provenance'] and
                    case['owner'].owner_id == ids['owner'] and collar._native.plan_id == ids['native'] and
                    collar.plan_id == ids['collar'] and collar._map.volume_map_id == ids['map'],
                    'independently rebuilt runtime, plans or owner differ from the producer')
            checks['source_bound_preparation'] = True
            guard.phase('re-authenticate-historical-endpoint-readonly')
            with H.open_successor_readonly(T/evidence['original'], expected_sha256=evidence['database_sha256'],
                    limits=limits, compression=compression, budget=budget, check=check) as original:
                admission = fixture_admission(H, W, original, evidence, budget=budget, check=check)
                require(type(admission) is W.HistoricalEndpointAdmission, 'historical issuer returned no admission')
                scratch = W._decode_allocation(budget, admission._binding)
                binding = admission.binding()
                original_path, original_pin = RUN.ordinary(binding['original_database_path']), binding['database_sha256']
                del scratch, binding
                # FIXTURE: the fixture issuer re-ran here from the pinned original bytes.
                checks['original_reauthenticated'] = True
                with REOPEN._reader_store(H, ArrayStore, copy, route=store_route, pin=producer['checkpoint_sha256'],
                        limits=limits, compression=compression, budget=budget, check=check) as store:
                    require(getattr(store, '_historical_readonly', None) is not None and
                            Path(store.path).resolve() != Path(producer['checkpoint']).resolve(),
                            'reader must open its own copy read-only')
                    token, snapshots = store.change_token(), store.statistics()['snapshots']
                    guard.phase('reproduce-migrated-base-from-original')
                    with M.materialise(original_store=original, admission=admission, native=case['native'],
                            collar=collar, execution=execution, compatibility=compatibility,
                            budget=budget, check=check, working_store=store, phase=guard.phase) as base:
                        require(type(base) is W.MigratedWorkflowBase and base.record() == producer['migrated_base'],
                                'independently reproduced migrated base differs from the producer')
                        require(store.change_token() == token,
                                'base reproduction wrote to the reader store instead of finding compact tables')
                        RUN._check_runtime_binding(base, row, execution, budget)
                        checks['migrated_base_reproduced'] = True
                        state = IW.initial_workload_state(original_store=original, admission=admission,
                            collar=collar, budget=budget, check=check)
                        expected = IW.authenticated_duration(admission, budget)
                        stand_in = FixtureWorkloadControl(expected, evidence['root_workload_array_sha256'], IW)
                        workload_case = dict(case, funding=base._spatial.funding, state=state)
                        duration = IW.require_initial_duration(stand_in, workload_case, expected=expected)
                        try:
                            IW.require_initial_duration(control, workload_case, expected=expected)
                        except Exception as error:
                            fixture['actuated_control_on_fixture'] = dict(refused=True, type=type(error).__name__)
                        require(state.record() == producer['initial_workload']['state'] and
                                duration == producer['initial_workload']['duration_s'],
                                'independently read initial workload differs from the producer')
                        del state, workload_case, stand_in
                        checks['initial_workload_reproduced'] = True
                        operations, accepted = FLOW.operations(collar), case['native'].statistics()['accepted_intervals']
                        guard.phase('independent-open-migrated-workflow')
                        with CollarWorkflow.open_migrated(store, published['workflow_id'], base,
                                budget=budget) as workflow:
                            root = REOPEN._root_identity(workflow, store, base, producer, W=W, budget=budget)
                            checks.update(migrated_root_identity=True, funding_preserved=True)
                            inspected = workflow.inspect()
                            require(inspected == published['inspect'] and inspected['head'] == root['key'] and
                                    inspected['intervals'] == base.record()['sequence'],
                                    'root-only reopen differs from the published root')
                            evidence_out = dict(root=inspected)
                            history = REOPEN._history(store, base, admission, producer, W=W, budget=budget, mode=mode)
                            checks['history_preserved'] = True
                            # Beyond the root-only reader: the producer's six-group formulas,
                            # state/funding identities and ArrayReference store_path tolerance.
                            mine = root_evidence(REOPEN, D, W, workflow, store, base)
                            theirs = receipt['fixture']['root']
                            differs = sorted(k for k in mine if k != 'reference_store_paths' and mine[k] != theirs.get(k))
                            require(not differs, 'independent root comparison differs: '+', '.join(differs))
                            require(mine['reference_store_paths'] == [str(store.path)] and
                                    theirs['reference_store_paths'] == [str(Path(producer['checkpoint']))] and
                                    mine['compact_reference_arrays'] > 0,
                                    'compact references are not bound to each reopening store path')
                            fixture['independent_root_comparison'] = dict(compared=sorted(mine), differs=differs,
                                reader_store_path=str(store.path), producer_store_path=theirs['reference_store_paths'],
                                compact_reference_arrays=mine['compact_reference_arrays'],
                                six_groups={k: None if v is None else len(v)
                                            for k, v in mine['array_records'].items()})
                            fixture['store_get_alias_probe'] = store_get_alias_probe(
                                store, root['key'], bound['partition_workflow_patch'], budget=budget)
                            del root
                        require(store.change_token() == token and store.statistics()['snapshots'] == snapshots,
                                'independent reopen wrote to the reader store')
                        checks['store_unchanged'] = True
                        require(FLOW.operations(collar) == operations and
                                case['native'].statistics()['accepted_intervals'] == accepted,
                                'independent reopen replayed a native operator or accepted an interval')
                        checks['native_operations_unchanged'] = True
                        record.update(evidence=evidence_out, history=history, store_route=store_route,
                                      independent_checks=checks)
                        save()
                        del base, workflow
                fixture['readonly_without_compact_tables'] = readonly_without_tables(RUN, H, M, original,
                    admission, case, execution, compatibility, evidence, output, limits=limits,
                    compression=compression, budget=budget, check=check, phase=guard.phase)
                save()
                del admission
            execution.verify_boundary()
        fixture['loaded_modules'], fixture['fixture_files_loaded'] = loaded_report(sources)
        sources.check_imported()
        sources.verify()
        require(RUN.file_hash(copy, check) == producer['checkpoint_sha256'] == RUN.file_hash(source, check),
                'reader copy or producer checkpoint changed')
        checks['reader_copy_and_producer_checkpoint_unchanged'] = True
        require(RUN.file_hash(original_path, check) == original_pin, 'original checkpoint changed')
        checks['original_database_unchanged'] = True
        record.update(independent_checks=checks, checkpoint=str(copy), original_database_unchanged=True)
        return budget
    finally:
        if original_path is not None:
            active_error = sys.exception()
            try:
                require(RUN.file_hash(original_path, check) == original_pin, 'original changed during failed reopen')
            except BaseException as verification_error:
                if active_error is None:
                    raise
                active_error.add_note('Original binding finalisation also failed: '+repr(verification_error))


def reader_main(profile_path, profile_sha, evidence_path, evidence_sha, receipt_sha, output_directory):
    """reopen_prepared_restart._workload with fixture_reader in place of its core."""
    RUN, profile, sources = bootstrap(profile_path, profile_sha)
    entry = str(RC/'helpers')
    sys.path.insert(0, entry)
    try:
        import reopen_prepared_restart as REOPEN
    finally:
        sys.path.remove(entry)
    require(Path(REOPEN.__file__).resolve() == READER and REOPEN.RUN is RUN, 'composed reader not selected')
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    mode, store_route = 'root-only', 'readonly'
    output = REOPEN.reader_output(profile, sources, output_directory, exists=True)/'reopen.json'
    record = dict(schema=REOPEN.READER_SCHEMA, status='STARTED', pid=os.getpid(), profile_sha256=profile.sha256,
        producer_receipt_sha256=receipt_sha, mode=mode, store_route=store_route, errors=[],
        production_acceptance=False, independent_process_reopen=True)
    guard = budget = None
    started = time.monotonic()
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    with sources.selected():
        G = sources.module('private_heat_continuation_guard_r3')
        save = lambda: G._write(output, record)
        try:
            guard = G.ContinuationGuard(output, record, save)
            producer = REOPEN.producer_inputs(profile, sources=sources, receipt_sha256=receipt_sha,
                                              mode=mode, consumer_pid=os.getpid())
            receipt = RUN.pinned_json(Path(profile.record()['output_directory'])/'run.json', receipt_sha,
                                      REOPEN.MAX_RECEIPT)
            budget = fixture_reader(REOPEN, profile, sources=sources, guard=guard, record=record, save=save,
                producer=producer, receipt=receipt, evidence_path=evidence_path, evidence_sha=evidence_sha)
            del producer, receipt
            record['status'] = 'VERIFYING_FINALISATION'
        except BaseException as error:
            record['status'] = 'FAILED'
            record['errors'].append(dict(type=type(error).__name__, message=str(error)))
            failure_note(record, error)
            if guard is not None and guard.budget is not None:
                record['logical_budget_at_failure'] = guard.budget.statistics()
            save()
        finally:
            gc.collect()
            budget = budget if budget is not None else getattr(guard, 'budget', None)
            if budget is not None:
                record['final_reserved_bytes'] = budget.reserved_bytes
                statistics = budget.statistics()
                record['logical_budget_final'] = dict(peak_reserved_bytes=statistics['peak_reserved_bytes'],
                    category_peaks=statistics['category_peaks'])
                if budget.reserved_bytes:
                    record['errors'].append(dict(type='RetainedReservations', message=str(budget.reserved_bytes)))
            times = os.times()
            record['parent_cpu_seconds'] = dict(user=times.user, system=times.system)
            record.setdefault('fixture', {})['wall_seconds'] = time.monotonic()-started
            try:
                import psutil
                children = psutil.Process().children(recursive=True)
                record['remaining_children'] = [child.pid for child in children]
                require(not children, 'reader worker processes remain after the reopen')
                sources.check_imported()
                sources.verify()
                if guard is not None:
                    guard.check(force=True)
                    guard.close()
            except BaseException as error:
                record['errors'].append(dict(type=type(error).__name__, message=str(error)))
            record['status'] = 'FAILED' if record['errors'] else REOPEN.WORKLOAD_STATUS[mode]
            save()
    print(RESULT+json.dumps(dict(role='reader', pid=os.getpid(), status=record['status'],
        errors=record['errors']), sort_keys=True), flush=True)
    return 0 if not record['errors'] else 1


# --------------------------------------------------------------------------- parent harness

def load_composed_runner_view():
    """Stdlib-only constants of the composed runner, without registering its module name."""
    spec = importlib.util.spec_from_file_location('w4_runner_reader_parent_view', RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for_memory(log):
    import psutil
    for attempt in range(40):
        available = psutil.virtual_memory().available
        if available >= MIN_AVAILABLE:
            log.append(dict(available_bytes=available, waited_polls=attempt))
            return available
        time.sleep(15)
    raise FixtureRefused('available RAM stayed below 1.5 GiB for 10 minutes; not starting a heavy process')


def tree_digest(root):
    rows = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = file_hash(path)
    return rows


def child(arguments, *, cwd, env, timeout, steps, label, memory, guarded_output=None):
    wait_for_memory(memory)
    command = [sys.executable, '-B', str(Path(__file__).resolve()), *arguments]
    if guarded_output is not None:
        command = [sys.executable, '-B', str(GUARD), '--launch', '--output', str(guarded_output), '--', *command]
    return run_command(command, cwd=cwd, env=env, timeout=timeout, steps=steps, label=label)


def run_command(command, *, cwd, env, timeout, steps, label):
    started = time.monotonic()
    completed = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
    seconds = time.monotonic()-started
    steps.append(dict(label=label, command=command, cwd=str(cwd), returncode=completed.returncode,
                      seconds=round(seconds, 3)))
    return completed


def result_line(completed):
    rows = [line for line in completed.stdout.splitlines() if line.startswith(RESULT)]
    require(len(rows) == 1, 'one child result line required: '+completed.stdout[-3000:]+completed.stderr[-6000:])
    return json.loads(rows[0].removeprefix(RESULT))


def write_exclusive(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, indent=1, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return file_hash(path)


def fixture_configuration(run, RUNVIEW):
    """Fixture manifest, policy and profile: the frozen RC entries plus declared fixture sources."""
    rc_manifest_raw = (RC/'manifest.json').read_bytes()
    require(sha256(rc_manifest_raw).hexdigest() == EXPECTED['manifest'], 'frozen composed manifest changed')
    real_profile_raw = (RC/'review'/'restart-profile-s2-r1.json').read_bytes()
    require(sha256(real_profile_raw).hexdigest() == EXPECTED['profile'], 'frozen composed profile changed')
    real_policy_raw = (RC/'review'/'runtime-compatibility-policy.json').read_bytes()
    require(sha256(real_policy_raw).hexdigest() == EXPECTED['policy'], 'frozen composed policy changed')
    require(file_hash(GUARD) == EXPECTED['guard'] and file_hash(RUNNER) == EXPECTED['runner'] and
            file_hash(READER) == EXPECTED['reader'], 'frozen composed guard, runner or reader changed')
    rc_manifest, real_profile = json.loads(rc_manifest_raw), json.loads(real_profile_raw)
    real_policy = json.loads(real_policy_raw)
    files = dict(rc_manifest['files'])
    extra = {rel(path): file_hash(path) for path in FIXTURE_SOURCES}
    require(not set(extra) & set(files) and not set(extra) & set(rc_manifest['data_only']),
            'fixture sources overlap the composed manifest')
    files.update(extra)
    manifest = dict(schema='w4.fixture-composed-manifest.v1', authority=FIXTURE_ONLY,
        base_manifest=dict(path=rel(RC/'manifest.json'), sha256=EXPECTED['manifest']),
        files=files, source_hashes=rc_manifest['source_hashes'], data_only=rc_manifest['data_only'],
        fixture_files=extra)
    manifest_sha = write_exclusive(run/'m.json', manifest)
    prefix = 'fidelity-integration-20261005/'
    policy = dict(schema=real_policy['schema'], constraints=real_policy['constraints'],
        historical=dict(real_policy['historical'], execution_identity=FIXTURE_HISTORICAL_EXECUTION,
                        source_manifest_path=prefix+real_policy['historical']['source_manifest_path']),
        current=dict(real_policy['current'], source_manifest_path=rel(run/'m.json'),
                     source_manifest_sha256=manifest_sha),
        reviewed_changes={name: dict(change, evidence=[prefix+e for e in change['evidence']])
                          for name, change in real_policy['reviewed_changes'].items()},
        evidence={prefix+path: pin for path, pin in real_policy['evidence'].items()})
    require(policy['current']['execution_identity'] == EXPECTED['execution_identity'] and
            policy['historical']['source_manifest_sha256'] == EXPECTED['historical_source_manifest'],
            'fixture policy must keep the measured current identity and historical manifest')
    policy_sha = write_exclusive(run/'pol.json', policy)
    profile = dict(schema=real_profile['schema'], workspace=str(T),
        source_manifest=dict(path=rel(run/'m.json'), sha256=manifest_sha),
        native_root=real_profile['native_root'],
        import_roots=[*real_profile['import_roots'], rel(R), rel(C)],
        modules=real_profile['modules'], preparation=real_profile['preparation'],
        compatibility_policy=dict(path=rel(run/'pol.json'), sha256=policy_sha), evidence_root='.',
        historical_source_root=real_profile['historical_source_root'], advance_driver=real_profile['advance_driver'],
        output_directory=str(run/'out'), store_limits=dict(STORE_LIMITS), compression=real_profile['compression'],
        completed_query_directory=rel(run)+'/cq', completed_query_limits=dict(QUERY_LIMITS))
    require(set(profile['modules']) == set(RUNVIEW.REQUIRED_MODULES), 'profile modules differ from REQUIRED_MODULES')
    profile_sha = write_exclusive(run/'prof.json', profile)
    return dict(manifest=(run/'m.json', manifest_sha), policy=(run/'pol.json', policy_sha),
                profile=(run/'prof.json', profile_sha), fixture_files=extra,
                import_roots=profile['import_roots'])


def run_check():
    RUNVIEW = load_composed_runner_view()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    number = 1
    while (SCRATCH/('r'+str(number))).exists():
        number += 1
    run = SCRATCH/('r'+str(number))
    run.mkdir()
    steps, memory = [], []
    summary = dict(schema='w4.runner-reader-summary.v1', authority=FIXTURE_ONLY, run=str(run), steps=steps,
                   memory_before_heavy_children=memory, parent_pid=os.getpid())
    rc_before = tree_digest(RC)
    original_sha = None
    try:
        configuration = fixture_configuration(run, RUNVIEW)
        profile_path, profile_sha = configuration['profile']
        summary['configuration'] = {k: [str(v[0]), v[1]] for k, v in configuration.items()
                                    if k in ('manifest', 'policy', 'profile')}
        summary['fixture_files'] = configuration['fixture_files']
        summary['import_roots'] = configuration['import_roots']
        env = dict(os.environ, **RUNVIEW.LAUNCH_ENV)
        env.pop('PYTHONPATH', None)
        pins = ['--profile', str(profile_path), '--profile-sha256', profile_sha]

        # 0. fixture writer
        fixture_dir = run/'fx'
        fixture_dir.mkdir()
        completed = child(['--fixture-writer', *pins, '--fixture-dir', str(fixture_dir)], cwd=fixture_dir,
                          env=env, timeout=600, steps=steps, label='fixture-writer', memory=memory)
        require(completed.returncode == 0, 'fixture writer failed: '+completed.stdout[-4000:]+completed.stderr[-12000:])
        written = result_line(completed)
        summary['fixture_writer'] = written
        original_sha = written['database_sha256']
        evidence = ['--evidence', written['evidence'], '--evidence-sha256', written['evidence_sha256']]

        # Runner command-only inspection: store-free, creates nothing.
        output = run/'out'
        completed = run_command([sys.executable, '-B', str(RUNNER), *pins, '--stop-before-advance'], cwd=run,
                                env=env, timeout=120, steps=steps, label='runner-command-only')
        require(completed.returncode == 0, 'runner inspection failed: '+completed.stderr[-6000:])
        inspection = json.loads(completed.stdout.strip().splitlines()[-1])
        require(inspection['status'] == 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION' and
                inspection['command'][2] == str(GUARD) and inspection['command'][-1] == '--stop-before-advance' and
                not output.exists(), 'runner inspection did not bind the composed guard and stop flag')
        summary['runner_command_only'] = inspection

        # A. producer under the composed guard
        output.mkdir()
        completed = child(['--producer', *pins, *evidence], cwd=output, env=env, timeout=1200, steps=steps,
                          label='producer-under-composed-guard', memory=memory, guarded_output=output/'run.json')
        receipt = json.loads((output/'run.json').read_bytes())
        summary['producer'] = dict(returncode=completed.returncode, status=receipt.get('status'),
            errors=receipt.get('errors'), stdout_tail=completed.stdout[-2000:], stderr_tail=completed.stderr[-4000:])
        require(completed.returncode == 0 and receipt['status'] == RUNVIEW.STOPPED_STATUS and
                receipt['errors'] == [] and receipt['final_reserved_bytes'] == 0,
                'producer failed: '+json.dumps(receipt.get('errors'))+receipt.get('fixture', {}).get('failure_traceback', ''))
        guard_receipt = json.loads((output/'run.guard.json').read_bytes())
        receipt_sha = file_hash(output/'run.json')
        summary['producer'].update(receipt_sha256=receipt_sha, pid=receipt['pid'],
            guardian_pid=guard_receipt['guardian']['pid'], guard_status=guard_receipt['status'],
            guard_sampled_peak_bytes=guard_receipt.get('sampled_peak_bytes'),
            phases=receipt.get('phases'), storage=receipt.get('storage'), fixture=receipt.get('fixture'),
            published_root=receipt.get('published_root'), migrated_base=receipt.get('migrated_base'),
            initial_workload=receipt.get('initial_workload'), checkpoint_sha256=receipt.get('checkpoint_sha256'),
            logical_budget_final=receipt.get('logical_budget_final'))

        # Reader command-only inspection: store-free producer preflight in its own process.
        reader_output = run/'rd'
        reader_pins = [*pins, '--producer-receipt-sha256', receipt_sha, '--output-directory', str(reader_output),
                       '--mode', 'root-only', '--store-route', 'readonly']
        completed = run_command([sys.executable, '-B', str(READER), *reader_pins], cwd=run, env=env, timeout=120,
                                steps=steps, label='reader-command-only')
        require(completed.returncode == 0, 'reader inspection failed: '+completed.stderr[-6000:])
        inspection = json.loads(completed.stdout.strip().splitlines()[-1])
        require(inspection['status'] == 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION' and
                inspection['command'][2] == str(GUARD) and not reader_output.exists(),
                'reader inspection did not validate the producer or bind the composed guard')
        summary['reader_command_only'] = inspection

        # B. independent reader under the composed guard, on a copy at another path
        reader_output.mkdir()
        completed = child(['--reader', *pins, *evidence, '--producer-receipt-sha256', receipt_sha,
                           '--output-directory', str(reader_output)], cwd=reader_output, env=env, timeout=1200,
                          steps=steps, label='reader-under-composed-guard', memory=memory,
                          guarded_output=reader_output/'reopen.json')
        reopen = json.loads((reader_output/'reopen.json').read_bytes())
        summary['reader'] = dict(returncode=completed.returncode, status=reopen.get('status'),
            errors=reopen.get('errors'), stdout_tail=completed.stdout[-2000:], stderr_tail=completed.stderr[-4000:])
        require(completed.returncode == 0 and reopen['status'] == 'PASS_ROOT_REOPENED_PENDING_FINALISE' and
                reopen['errors'] == [] and reopen['final_reserved_bytes'] == 0,
                'reader failed: '+json.dumps(reopen.get('errors'))+reopen.get('fixture', {}).get('failure_traceback', ''))
        reader_guard = json.loads((reader_output/'reopen.guard.json').read_bytes())
        reopen_sha = file_hash(reader_output/'reopen.json')
        summary['reader'].update(receipt_sha256=reopen_sha, pid=reopen['pid'],
            guardian_pid=reader_guard['guardian']['pid'], guard_status=reader_guard['status'],
            guard_sampled_peak_bytes=reader_guard.get('sampled_peak_bytes'), phases=reopen.get('phases'),
            independent_checks=reopen.get('independent_checks'), history=reopen.get('history'),
            evidence=reopen.get('evidence'), fixture=reopen.get('fixture'),
            remaining_children=reopen.get('remaining_children'), logical_budget_final=reopen.get('logical_budget_final'))

        # Store-free acceptance of the guarded reader with the real CLI.
        completed = run_command([sys.executable, '-B', str(READER), *reader_pins, '--finalise',
                                 '--reopen-receipt-sha256', reopen_sha], cwd=run, env=env, timeout=120,
                                steps=steps, label='reader-finalise')
        final = json.loads((reader_output/'reopen-final.json').read_bytes())
        summary['finalise'] = dict(returncode=completed.returncode, final=final,
                                   final_sha256=file_hash(reader_output/'reopen-final.json'))
        require(completed.returncode == 0 and final['status'] ==
                'PASS_MIGRATED_ROOT_INDEPENDENT_REOPEN_NOT_INTERVAL_ACCEPTANCE' and final['errors'] == [] and
                final['production_acceptance'] is False, 'finalise did not accept the fixture reader')

        pids = {summary['parent_pid'], written['pid'], receipt['pid'], reopen['pid'],
                guard_receipt['guardian']['pid'], reader_guard['guardian']['pid']}
        require(len(pids) == 6, 'parent, fixture writer, producer, reader and both guardians must be distinct')
        checkpoint = output/'checkpoint.sqlite'
        copy = reader_output/'checkpoint-reopen.sqlite'
        final_hashes = dict(original=file_hash(T/json.loads(Path(written['evidence']).read_bytes())['original']),
            producer_checkpoint=file_hash(checkpoint), reader_copy=file_hash(copy),
            producer_receipt=file_hash(output/'run.json'), reader_receipt=file_hash(reader_output/'reopen.json'))
        require(final_hashes['original'] == original_sha and
                final_hashes['producer_checkpoint'] == final_hashes['reader_copy'] == receipt['checkpoint_sha256'] and
                final_hashes['producer_receipt'] == receipt_sha and final_hashes['reader_receipt'] == reopen_sha,
                'original fixture, producer checkpoint, reader copy or receipts changed')
        summary['final_hashes'] = final_hashes
        summary['distinct_pids'] = sorted(pids)
    finally:
        rc_after = tree_digest(RC)
        summary['composed_tree_unchanged'] = rc_after == rc_before
        summary['composed_tree_files'] = len(rc_after)
        summary['composed_tree_pycache'] = sorted(p for p in rc_after if '__pycache__' in p or p.endswith('.pyc'))
        write_exclusive(run/'summary.json', summary)
    require(summary['composed_tree_unchanged'] and not summary['composed_tree_pycache'],
            'the frozen composed tree changed during the check')
    print('W4_RUNNER_READER_PASS '+json.dumps(dict(run=str(run), summary=str(run/'summary.json'),
        steps=[(s['label'], s['returncode'], s['seconds']) for s in steps]), sort_keys=True), flush=True)
    return summary


class ComposedRunnerReaderTests(unittest.TestCase):
    def test_composed_runner_then_independent_root_only_reader(self):
        summary = run_check()
        self.assertTrue(summary['composed_tree_unchanged'])
        self.assertEqual(summary['finalise']['final']['status'],
                         'PASS_MIGRATED_ROOT_INDEPENDENT_REOPEN_NOT_INTERVAL_ACCEPTANCE')


def main(argv):
    import argparse
    parser = argparse.ArgumentParser()
    role = parser.add_mutually_exclusive_group(required=True)
    role.add_argument('--fixture-writer', action='store_true')
    role.add_argument('--producer', action='store_true')
    role.add_argument('--reader', action='store_true')
    parser.add_argument('--profile', required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--fixture-dir')
    parser.add_argument('--evidence')
    parser.add_argument('--evidence-sha256')
    parser.add_argument('--producer-receipt-sha256')
    parser.add_argument('--output-directory')
    args = parser.parse_args(argv)
    if args.fixture_writer:
        return fixture_writer(args.profile, args.profile_sha256, args.fixture_dir)
    if args.producer:
        return producer_main(args.profile, args.profile_sha256, args.evidence, args.evidence_sha256)
    return reader_main(args.profile, args.profile_sha256, args.evidence, args.evidence_sha256,
                       args.producer_receipt_sha256, args.output_directory)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('--fixture-writer', '--producer', '--reader'):
        raise SystemExit(main(sys.argv[1:]))
    unittest.main(verbosity=2)
