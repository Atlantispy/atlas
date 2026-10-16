"""Guarded Step8 capacity projection; never a real IV2 scientific run.

All census-derived forecasts stay distinct from measured physical allocations.
Only this explicit fixture and its output directory are written.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from collections.abc import Mapping
from dataclasses import fields
from hashlib import sha256
import gc
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

import numpy as np
import psutil

HERE = Path(__file__).resolve().parent
R = HERE.parent
TASK = HERE.parents[4]
I = R.parent/'runtime-integration-r1/runtime-src'
CENSUS = R/'probes/structure-census-r3/structure-census.json'
CENSUS_SHA256 = '02f0a05a7f05855d7ef578b879666489e8b2711405da2031204df372b5e379ae'
PYTHON = TASK/'.r44-env/Scripts/python.exe'
GUARDS = dict(rss_bytes=12 << 30, free_floor_bytes=1 << 30,
              start_available_bytes=10 << 30, logical_budget_bytes=16 << 30)
# Explicit Step 8 capacity-test start gate (Michael, 15 Oct): the previous test's
# measured peak plus the 1 GiB floor and a stated margin, never below 4 GiB. It
# is recorded with its basis in prepare.json and capacity.json. GUARDS keeps the
# unchanged 10 GiB real-interval figure that the census pins; it is the default.
STEP8_TEST_START_GATE = 4 << 30
SCALE = 4
MAX_SECONDS = 1800
GRAPH = R/'probes/structure-census-r2/structure-scratch/record-004.json'
sys.path[:0] = [str(HERE), str(R), str(I)]


def require(value, message):
    if not value:
        raise ValueError(message)


def file_hash(path):
    digest = sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


def read_census():
    raw = CENSUS.read_bytes()
    require(sha256(raw).hexdigest() == CENSUS_SHA256, 'reviewed structural census changed')
    value = json.loads(raw)
    require(value['guard_limits'] == GUARDS, 'census guard limits differ')
    require(value['census']['support_overlap']['partition_supports'] == 2016,
            'historical support shape changed')
    return value


def census_profile(value):
    """Exact shape evidence plus explicitly estimated4x successor targets."""
    families = {}
    for name, record in value['census']['records'].items():
        families[name] = dict(iv1_canonical_bytes=record['filebytes'],
            projected_canonical_bytes=SCALE*record['filebytes'],
            iv1_counts=record['counts'], iv1_max_depth=record['max_depth'],
            rational_widths=record['rational_strings'],
            fields=[dict(path=f['path'], kind=f['kind'], items=f['items'], bytes=f['bytes'])
                    for f in record['fields']])
    numeric = {}
    for name, description in value['census']['head']['arrays'].items():
        if '-record:' in name:
            continue
        numeric[name] = {key: description[key] for key in ('dtype', 'shape', 'logical_bytes')}
    return dict(source_sha256=CENSUS_SHA256, iv1_measured=True,
        successor_growth_factor=SCALE, successor_growth_status='projection, not observed IV2',
        families=families, numeric_head_arrays=numeric,
        support_count=2016, thermal_cells=855, thermal_faces=8569,
        heat_fields=value['census']['heat']['native_field_bindings'],
        retained_scope_bytes=256 << 20,
        scope='storage/ownership capacity; exact synthetic outputs are not scientific admission')


def source_bindings(extra=()):
    names = ('measure_live_capacity.py', 'test_live_partition.py', 'live_partition_patch.py',
        'partition_native_patch.py', 'partition_v2.py', 'record_tables.py', 'record_views.py',
        'content_cache.py', 'mesh_tables.py', 'compact_store.py', 'support_source.py',
        'partition_store.py', 'heat_ledger_tables.py', 'private_heat_snapshot_store_r4.py',
        'segment_store.py', 'interval_store_set.py', 'interval_catalog.py',
        'measure_live_mesh_capacity.py', 'live_mesh_patch.py')+tuple(extra)
    result = {str((HERE/name).relative_to(R)): file_hash(HERE/name) for name in names}
    for name in ('resources.py', 'storage.py'):
        result[str((I/'atlas_tectonics'/name).relative_to(R.parent))] = file_hash(I/'atlas_tectonics'/name)
    return result


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf8')
    os.replace(temporary, path)


def guard_files():
    import resource_guard_patch as RG
    source = R/'probes/structure-census-r3/guard'
    pins = {RG.GUARD_NAME: RG.SUCCESSOR_PIN, RG.JOB_NAME: RG.JOB_PIN,
            RG.DIAGNOSTICS_NAME: RG.DIAGNOSTICS_PIN}
    files = {name: (source/name).read_bytes() for name in pins}
    require(all(sha256(raw).hexdigest() == pins[name] for name, raw in files.items()),
            'reviewed external guardian bytes changed')
    return files


def launch(output, *, smoke=False, start_gate=None, basis=None, script=None, extra_sources=(),
           plan_extra=None, max_seconds=None, max_seconds_basis=None, scale=SCALE, live_producer_bytes=None):
    """script/extra_sources/plan_extra let an extending harness reuse this launch.

    max_seconds raises the bounded workload time only with a recorded basis;
    it never lowers the default and it is not a memory or storage guard.
    scale is the number of independent authentic IV1 blocks (1 for an IV1-scale
    run; the default 4 is the projected IV2 pressure scenario).
    live_producer_bytes gives the run's scope its named live-producer child
    (coordinator decision D2-A); None keeps every charge on the 256 MiB retained
    aggregate, as before. Both are recorded in prepare.json and capacity.json.
    """
    require(type(scale) is int and 1 <= scale <= SCALE, 'scale is 1..4 independent IV1 blocks')
    require(live_producer_bytes is None or (type(live_producer_bytes) is int and live_producer_bytes > 0),
            'live producer allowance must be a positive int when given')
    output = Path(output).resolve()
    require(output.parent == (R/'probes/step8').resolve() and output.name.startswith('capacity'),
            'new capacity output must be directly inside the authorised Step8 probe directory')
    require(not output.exists(), 'exclusive new capacity output directory required')
    require(Path(sys.executable).resolve() == PYTHON.resolve(), 'task .r44-env interpreter required')
    gate = GUARDS['start_available_bytes'] if start_gate is None else start_gate
    require(type(gate) is int and gate >= STEP8_TEST_START_GATE, 'Step 8 test start gate starts at 4 GiB')
    require(start_gate is None or bool(basis), 'an explicit Step 8 start gate needs its recorded basis')
    bound = MAX_SECONDS if max_seconds is None else max_seconds
    require(type(bound) is int and bound >= MAX_SECONDS and (max_seconds is None or bool(max_seconds_basis)),
            'a longer workload bound needs its recorded basis and is never below the default')
    available = psutil.virtual_memory().available
    require(available >= gate, ('unchanged10GiB available-memory start gate refused' if start_gate is None
                                else 'Step 8 test start gate refused: available '+str(available)))
    value, files = read_census(), guard_files()
    output.mkdir()
    guard = output/'guard'; guard.mkdir()
    for name, raw in files.items():
        (guard/name).write_bytes(raw)
    # Builder spill files stay inside this run's own output (brief: write only in R).
    spill = output/'spill'; spill.mkdir()
    plan = dict(schema='atlas.step8.capacity-prepare.v1', guards=GUARDS,
        available_bytes_at_prepare=available, sources=source_bindings(extra_sources),
        extra_sources=list(extra_sources), census=census_profile(value),
        graph_source=dict(path=str(GRAPH), sha256=file_hash(GRAPH), bytes=GRAPH.stat().st_size),
        smoke=smoke, workload_timeout_seconds=bound,
        workload_timeout_basis=max_seconds_basis if max_seconds is not None else 'default bound',
        start_gate={'bytes': gate, 'step8_test_setting': start_gate is not None,
                    'basis': basis if start_gate is not None else 'unchanged 10 GiB real-interval gate',
                    'real_interval_gate_bytes_unchanged': GUARDS['start_available_bytes']},
        record_spill_directory=str(spill), scale=scale,
        live_producer={'bytes': live_producer_bytes,
                       'decision': ('coordinator D2-A, 16 Oct 2026: live producer records on a named run-budget child'
                                    if live_producer_bytes is not None else
                                    'none: every charge on the 256 MiB retained aggregate')},
        guard_sha256={name: sha256(raw).hexdigest() for name, raw in files.items()}, **(plan_extra or {}))
    write_json(output/'prepare.json', plan)
    command = [str(PYTHON), '-B', str(guard/'private_heat_continuation_guard_r3.py'),
        '--launch', '--output', str(output/'capacity.json'), '--', str(PYTHON), '-B',
        str(Path(script or __file__).resolve()), '--workload', str(output)]
    environment = {key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTHONHOME')}
    environment.update(PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
                       ATLAS_RECORD_SPILL_DIR=str(spill))
    print(json.dumps(dict(stage='guarded-launch', output=str(output))), flush=True)
    return subprocess.run(command, cwd=output, env=environment,
                          timeout=bound+60, check=False).returncode


def scope_sample(scope):
    if scope is None:
        return None
    stats = scope.stats()
    return {field.name: dict(value) if isinstance(value, Mapping) else value
            for field in fields(stats) for value in [getattr(stats, field.name)]}


def process_sample():
    info = psutil.Process().memory_info()
    return dict(rss_bytes=info.rss, private_bytes=getattr(info, 'private', info.vms),
                os_peak_rss_bytes=getattr(info, 'peak_wset', info.rss),
                available_bytes=psutil.virtual_memory().available)


def disk_bytes(directory):
    return sum(path.stat().st_size for path in Path(directory).rglob('*') if path.is_file())


class PaidArrays:
    """Count each independent numeric block before allocating it."""
    def __init__(self, budget, specifications, count):
        self.blocks = []
        size = sum(math.prod(row['shape'])*np.dtype(row['dtype']).itemsize
                   for row in specifications.values())
        self.lease = budget.reserve(count*(size+65536+1024*len(specifications)),
                                    category='capacity-live-numeric')
        self.lease.__enter__()
        self.logical_bytes = count*size
        for _ in range(count):
            self.blocks.append({name: np.empty(row['shape'], dtype=row['dtype'])
                                for name, row in specifications.items()})

    def close(self):
        self.blocks.clear()
        if self.lease is not None:
            lease, self.lease = self.lease, None
            lease.__exit__(None, None, None)


def fill_numeric(source, snapshot, arrays, check):
    """Authenticate native chunks without a whole-snapshot compatibility load."""
    hashes = {}
    for name, array in arrays.items():
        digest, end = sha256(), 0
        for start, chunk in source.iter_chunks(snapshot, name, budget=source._budget):
            check()
            require(start == end, 'numeric chunks have a gap')
            array.reshape(-1)[start:start+chunk.size] = chunk
            digest.update(memoryview(chunk).cast('B'))
            end += chunk.size
        require(end == array.size, 'numeric chunk extent differs')
        hashes[name] = digest.hexdigest()
    return hashes


def native_heat_fields(census, block, hashes):
    """The stored snapshot names its arrays field_0..; its identity binds the
    scientific names in the census native_field_bindings. Each field's bytes are
    checked against its binding before the rename, so a wrong mapping refuses."""
    named = {}
    for binding in census['heat']['native_field_bindings']:
        array = block[binding['array']]
        require(hashes[binding['array']] == binding['sha256'] and list(array.shape) == binding['shape'],
                'authentic heat field differs from its census binding')
        named[binding['name']] = array
    require(len(named) == len(block), 'every stored heat field needs exactly one binding')
    return named


class CheckToken:
    def __init__(self, check):
        self.check = check

    def is_set(self):
        self.check()
        return False


def publish_record(candidate, record, scope, producer, cancel):
    from segment_store import SegmentBackend
    from record_tables import SCHEMA
    identity = record.identity()
    with record.metadata_bytes() as metadata:
        return SegmentBackend().publish(candidate, record_schema=identity.record_schema,
            identity=identity, metadata=metadata.value, arrays=record.array_sources,
            producer=producer, representation_profile=SCHEMA, scope=scope, cancel=cancel)


def backing_inventory(record):
    """Payload lengths and private allocation identities; no decoded export."""
    # Trusted producer output: inspect immutable bytes solely to prove the four
    # copies own disjoint physical arrays, not aliases to the same record.
    arrays = record._owner.value[1]
    rows = {}
    for name, value in arrays.items():
        base = value
        while isinstance(getattr(base, 'base', None), np.ndarray):
            base = base.base
        backing = getattr(base, 'base', None)
        require(type(backing) is bytes, 'expected immutable produced column backing')
        rows[name] = dict(bytes=value.nbytes, allocation=id(backing))
    return rows


def failed_builder_evidence(error):
    """Small counters from the still-funded failed frames, never their records."""
    rows, seen = [], set()
    trace = error.__traceback__
    while trace is not None:
        # Do not materialise the executing fixture's f_locals: its cached dict
        # would retain the decoded source after the fast locals are released.
        if Path(trace.tb_frame.f_code.co_filename).name != 'record_tables.py':
            trace = trace.tb_next
            continue
        for value in trace.tb_frame.f_locals.values():
            if (type(value).__module__ == 'record_tables' and
                    type(value).__name__ == '_Builder' and id(value) not in seen):
                seen.add(id(value))
                rows.append(dict(tracked=value.work_budget.statistics(),
                    nodes=len(value.nodes), integers=len(value.integers), pairs=len(value.pairs),
                    ids=len(value.ids), tokens=len(value.tokens), shapes=len(value.shapes),
                    encoded_token_bytes=sum(map(len, value.tokens)),
                    emitted_logical_bytes=value.length))
        trace = trace.tb_next
    return rows


def retain_other_records(source, census, scope, candidate, owners, result, *, check, phase, token, scale=SCALE):
    """Further authentic families only after the graph/mesh overlap succeeds."""
    from record_tables import RecordCodec
    from measure_live_mesh_capacity import _read_record
    from heat_ledger_tables import CompactHeatSnapshot
    import private_heat_snapshot_store_r4 as heat_store
    output, snapshots = [], []
    result['other_families'] = output
    names = ('spatial-record:state', 'spatial-record:transport', 'spatial-record:exchange',
             'differential-record:geometry', 'certification-record:final')
    for name in names:
        binding = census['records'][name]
        row = dict(name=name, source_decodes=[], blocks=[])
        output.append(row)
        phase(name+'-source-decode')
        held = _read_record(source, binding, budget=scope.run_budget, check=check,
                            evidence=row['source_decodes'])
        allocations = set()
        for index in range(scale):
            phase(name+'-block-'+str(index+1)+'-pack')
            # The geometry and certification records carry no top-level schema
            # field; the census key names them (identity is content-checked below).
            packed = RecordCodec().pack_record(held.value, record_schema=held.value.get('schema', name),
                scope=scope, check=check)
            owners.callback(packed.close)
            identity = packed.identity()
            require(identity.sha256 == binding['sha256'] and
                    identity.canonical_bytes == binding['filebytes'], 'authentic family identity changed')
            inventory = backing_inventory(packed)
            current = {item['allocation'] for item in inventory.values() if item['bytes'] > 1}
            require(not current & allocations, 'cross-block family backing alias detected')
            allocations.update(current)
            ref = publish_record(candidate, packed, scope,
                sha256((name+str(index)).encode()).hexdigest(), token)
            row['blocks'].append(dict(identity=identity.to_wire(), reference=ref.to_wire(),
                packed_column_bytes=sum(item['bytes'] for item in inventory.values())))
            snapshots.append(ref.to_wire())
        del held, packed
        phase(name+'-retained-source-released')

    binding = census['records']['heat:metadata_utf8']
    row = dict(name='heat:metadata_utf8', source_decodes=[], blocks=[])
    output.append(row)
    phase('heat-source-decode')
    held = _read_record(source, binding, budget=scope.run_budget, check=check,
                        evidence=row['source_decodes'])
    metadata = source.metadata(binding['snapshot'])
    arrays = PaidArrays(scope.run_budget, census['heat']['native_fields'], 1)
    fields_hash = fill_numeric(source, binding['snapshot'], arrays.blocks[0], check)
    named = native_heat_fields(census, arrays.blocks[0], fields_hash)
    # Input ownership follows failed frames; successful input closes after the
    # compact snapshots have made their own immutable native field backings.
    owners.callback(arrays.close)
    allocations = set()
    for index in range(scale):
        phase('heat-block-'+str(index+1)+'-pack')
        snapshot = CompactHeatSnapshot.from_components(held.value, named, scope=scope,
            check=check, expected_result_id=metadata['result_id'])
        owners.callback(snapshot.close)
        require(snapshot.metadata_identity.sha256 == binding['sha256'] and
                snapshot.metadata_identity.canonical_bytes == binding['filebytes'],
                'authentic heat ledger identity changed')
        inventory = backing_inventory(snapshot.record)
        current = {item['allocation'] for item in inventory.values() if item['bytes'] > 1}
        require(not current & allocations, 'cross-block heat backing alias detected')
        allocations.update(current)
        receipt = heat_store.save(candidate, snapshot,
            bindings=dict(metadata['bindings'], capacity_block=sha256(str(index).encode()).hexdigest()),
            scope=scope, cancel=token)
        row['blocks'].append(dict(result_id=snapshot.result_id, receipt=receipt,
            packed_column_bytes=sum(item['bytes'] for item in inventory.values()),
            input_field_hashes=fields_hash))
    del held, snapshot, named
    arrays.close()
    phase('four-heat-ledgers-retained-source-released')
    return dict(record_blocks=snapshots, heat_blocks=[block['receipt'] for block in row['blocks']])


def workload(output, overlaps=None):
    """A partial structural stress, with every unavailable family explicit.

    overlaps, if given, is called once at the full-overlap point (every block
    retained and the numeric blocks committed, before the root publication and
    seal) with this run's context; whatever it returns is published in the root.
    """
    output = Path(output).resolve()
    plan = json.loads((output/'prepare.json').read_text(encoding='utf8'))
    require(plan['sources'] == source_bindings(plan.get('extra_sources', ())),
            'capacity source closure changed after launch')
    bound = plan.get('workload_timeout_seconds', MAX_SECONDS)
    scale = plan.get('scale', SCALE)
    producer_bytes = (plan.get('live_producer') or {}).get('bytes')
    value = read_census()
    expected = value['census']['records']['spatial-record:graph']
    require(file_hash(GRAPH) == expected['sha256'] and GRAPH.stat().st_size == expected['filebytes'],
            'existing read-only graph spool differs from authenticated census')
    sys.path.insert(0, str(output/'guard'))
    from private_heat_continuation_guard_r3 import ContinuationGuard
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet, LIMITS
    from record_tables import RecordCodec
    import historical_admission as H
    import mesh_tables as M
    from test_live_partition import retained_partition_fixture

    record = dict(schema='atlas.step8.capacity-result.v1', status='RUNNING',
        scientific_status='NOT_A_REAL_IV2_RUN', acceptance='INCOMPLETE',
        sources=plan['sources'], census_sha256=CENSUS_SHA256, guards=GUARDS,
        start_gate=plan.get('start_gate'), record_spill_directory=plan.get('record_spill_directory'),
        workload_timeout_seconds=bound, workload_timeout_basis=plan.get('workload_timeout_basis'),
        smoke=plan['smoke'], checkpoints=[], blocks=[], scale=scale, live_producer=plan.get('live_producer'),
        projection=dict(factor=scale, method='independently owned authentic IV1 graph blocks',
            physical_measure_receipt_rows_per_block=48391,
            total_receipt_rows=scale*48391,
            projected_graph_canonical_bytes=scale*expected['filebytes'],
            cross_block_identities='same authentic identities in disjoint block namespaces',
            no_cross_block_memory_aliasing=True,
            disk_limitations='native content-addressed deduplication may share equal block payloads; disk is observed output, not a 4x disk forecast'),
        limitations=[
            'Partial stress only: native indexed differential mesh, heat ledger, current partition, state, exchange and transport records are not yet retained.',
            'Parent is the measured 2016-support synthetic partition; exact historical partition rational distribution is not asserted.',
            'No scientific solver workspace or owner advance is exercised here; separate tiny actual-owner evidence cannot establish IV2 solver bounds.',
            'One charged whole graph source decode is a conservative fixture input cost, not the new producer allocation path.',
            'Worker processes and diagnostic capture are disabled. No cost is invented for them.',
            'Canonical logical byte counts are not RAM measurements.'],
        phases=[])
    result_path = output/'capacity.json'
    save = lambda: write_json(result_path, record)
    save()
    budget = WorkBudget(GUARDS['logical_budget_bytes'])
    guard = ContinuationGuard(result_path, record, save)
    guard.budget = budget
    started = time.monotonic()
    scope = None
    failed = False
    owners = ExitStack()
    graph = raw = raw_owner = decoded_owner = block = None

    def check():
        guard.check()
        if time.monotonic()-started > bound:
            raise TimeoutError('bounded capacity workload exceeded '+str(bound)+' seconds')

    def phase(name):
        check()
        row = dict(name=name, seconds=time.monotonic()-started,
                   process=process_sample(), tracked=budget.statistics(),
                   scope=scope_sample(scope),
                   output_disk_bytes=disk_bytes(output))
        record['checkpoints'].append(row)
        guard.phase(name)
        print(json.dumps(dict(phase=name, seconds=round(row['seconds'], 3),
                             rss_bytes=row['process']['rss_bytes'],
                             retained_bytes=0 if scope is None else scope.stats().retained_bytes)), flush=True)

    token = CheckToken(check)

    # No collection, explicit or automatic, during construction/retention/commit.
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        scope = create_retained_scope(budget, process_epoch='step8-capacity-graph-v1',
                                      live_producer_bytes=producer_bytes)
        owners.callback(scope.close)
        require(scope.retained_budget.max_bytes == 256 << 20, 'retained aggregate limit differs')
        phase('parent-partition-build')
        parent = retained_partition_fixture(scope, count=3 if plan['smoke'] else 2016, check=check)
        owners.callback(parent.close)
        record['parent'] = dict(identity=parent.record.identity().to_wire(),
                                partition_id=parent.partition_id)
        phase('parent-partition-retained')

        endpoint = value['census']['endpoint'] if 'endpoint' in value['census'] else value['endpoint']
        native_limits = StoreLimits(**endpoint['store_limits'])
        native_compression = Compression(**endpoint['store_compression'])
        source = owners.enter_context(H.open_original_readonly(limits=native_limits,
            compression=native_compression, budget=budget))
        require(source._db.execute('PRAGMA query_only').fetchone() == (1,), 'source must stay query-only')
        original_path = source.path
        expected_original = value['census']['original']['pinned_sha256']
        require(file_hash(original_path) == expected_original, 'original source bytes changed')
        record['original_readonly'] = dict(path=str(original_path), sha256=expected_original,
                                           query_only=True)
        specs = census_profile(value)['numeric_head_arrays']
        numeric = PaidArrays(budget, specs, scale+1)
        owners.callback(numeric.close)
        hashes = fill_numeric(source, endpoint['head_key'], numeric.blocks[0], check)
        for block in numeric.blocks[1:]:
            for name in block:
                np.copyto(block[name], numeric.blocks[0][name])
        record['numeric'] = dict(block_count=len(numeric.blocks), arrays_per_block=len(specs),
            physical_array_bytes=numeric.logical_bytes, original_hashes=hashes,
            shape=f'one IV1 parent block and {scale} independent IV1 current blocks')
        phase('parent-and-five-numeric-blocks-retained')

        stores = IntervalStoreSet.create_migration(output/'catalog.json',
            workflow_id=sha256(b'step8 capacity synthetic namespace').hexdigest(), scope=scope)
        owners.callback(stores.close)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        owners.callback(candidate.close)
        commits = owners.enter_context(ArrayStore(output/'numeric.sqlite', LIMITS,
            Compression(codec='raw', palette=False), budget=budget))

        refs, seen_allocations = [], set()
        smoke_raw = b'{"schema":"atlas.capacity-mechanics.v1","value":[1,2,3,4]}'
        source_size = len(smoke_raw) if plan['smoke'] else expected['filebytes']
        phase('authentic-graph-source-decode')
        raw_owner = M._Allocation(budget, 65536+2*source_size)
        raw = smoke_raw if plan['smoke'] else GRAPH.read_bytes()
        if not plan['smoke']:
            require(sha256(raw).hexdigest() == expected['sha256'], 'graph changed during read')
        decoded_charge = M._decode_charge(raw)
        decoded_owner = M._Allocation(budget, decoded_charge)
        record['source_decode'] = dict(raw_charge_bytes=65536+2*source_size,
            decoded_charge_bytes=decoded_charge, admission='mesh_tables._decode_charge',
            input_bytes=source_size)
        graph = json.loads(raw)
        del raw, raw_owner
        if not plan['smoke']:
            require(len(graph['physical_measure_receipts']) == 48391,
                    'authentic physical-measure receipt inventory differs')
        phase('authentic-graph-source-decoded')
        for index in range(scale):
            phase('graph-block-'+str(index+1)+'-pack')
            compact = RecordCodec().pack_record(graph, record_schema=graph['schema'],
                scope=scope, check=check)
            owners.callback(compact.close)
            identity = compact.identity()
            if not plan['smoke']:
                require(identity.sha256 == expected['sha256'] and
                        identity.canonical_bytes == expected['filebytes'],
                        'produced graph logical identity differs from authentic original')
            inventory = backing_inventory(compact)
            # CPython may intern the empty/single-byte singleton values;
            # every material column must have its own physical backing.
            allocations = {row['allocation'] for row in inventory.values() if row['bytes'] > 1}
            require(not allocations & seen_allocations, 'cross-block backing alias detected')
            seen_allocations.update(allocations)
            record['blocks'].append(dict(index=index,
                logical_identity=identity.to_wire(),
                packed_column_bytes=sum(row['bytes'] for row in inventory.values()),
                possible_singleton_bytes=sum(row['bytes'] for row in inventory.values() if row['bytes'] <= 1),
                independently_owned_columns=len(allocations)))
            phase('graph-block-'+str(index+1)+'-publish')
            ref = publish_record(candidate, compact, scope,
                sha256(('capacity graph block '+str(index)).encode()).hexdigest(), token)
            refs.append(ref)
            record['blocks'][-1]['reference'] = ref.to_wire()
            del compact, inventory, allocations, identity
        del graph, decoded_owner
        phase('four-authentic-graphs-retained-source-released')
        record['source_decode_released_before_commit'] = True

        mesh_refs, other_refs, mesh_partition, meshes = [], {}, None, None
        if not plan['smoke']:
            from measure_live_mesh_capacity import retain_mesh_blocks
            meshes = retain_mesh_blocks(scope, candidate, source, value['census'],
                count=scale, check=check, checkpoint=phase)
            owners.callback(meshes.close)
            record['meshes'] = meshes.evidence
            mesh_refs = [ref.to_wire() for ref in meshes.refs]
            mesh_partition = meshes.evidence['partition']['reference']
            phase('four-indexed-meshes-and-graphs-retained')
            other_refs = retain_other_records(source, value['census'], scope, candidate,
                owners, record, check=check, phase=phase, token=token, scale=scale)
            record['limitations'][0] = (
                f'All selected current record families are present as {scale} separate unchanged IV1 blocks; '
                'this is not a merged IV2 topology or a new solver state. Mesh blocks share one authentic2016-support partition.')

        keys = []
        for index, block in enumerate(numeric.blocks):
            phase('numeric-arraystore-commit-'+str(index))
            key = sha256(('capacity numeric block '+str(index)).encode()).hexdigest()
            require(commits.put(key, block, {'schema': 'atlas.capacity-numeric.v1', 'block': index},
                                budget=budget, cancel=token), 'numeric put did not publish')
            keys.append(key)
        overlap_refs = None
        if overlaps is not None:
            overlap_refs = overlaps(SimpleNamespace(scope=scope, budget=budget, candidate=candidate,
                source=source, census=value['census'], owners=owners, check=check, phase=phase,
                token=token, output=output, started=started, record=record, meshes=meshes))
        phase('all-records-numeric-and-publication-overlap')
        root = RecordCodec().pack_record(dict(schema='atlas.capacity-root.v1',
            graph_blocks=[ref.to_wire() for ref in refs], mesh_blocks=mesh_refs,
            mesh_partition=mesh_partition, other_blocks=other_refs, numeric_keys=keys,
            **({} if overlap_refs is None else {'overlap_blocks': overlap_refs})),
            record_schema='atlas.capacity-root.v1', scope=scope, check=check)
        owners.callback(root.close)
        root_ref = publish_record(candidate, root, scope, 'd'*64, token)
        phase('candidate-seal')
        sealed = candidate.seal(root_ref, cancel=token)
        stores.promote(sealed, expected_catalog_digest=stores.catalog_digest)
        phase('candidate-sealed-and-retained')
        record['committed_numeric_keys'] = keys
        record['numeric_store_statistics'] = commits.statistics()
        record['sealed_root'] = root_ref.to_wire()
        require(file_hash(original_path) == expected_original, 'original changed during capacity fixture')
        record['original_readonly']['after_sha256'] = expected_original
        record['status'] = 'PARTIAL_MEASUREMENT_COMPLETE' if not plan['smoke'] else 'MECHANICS_ONLY'
        record['measured_seconds'] = time.monotonic()-started
        phase('measured-region-complete')
        block = None
        owners.close()
        phase('all-owned-objects-released')
        require(budget.reserved_bytes == 0, 'capacity resources retained after explicit cleanup')
    except BaseException as error:
        failed = True
        record['status'] = 'REFUSED_OR_FAILED'
        record['failure'] = dict(type=type(error).__name__, message=str(error),
            phase=record.get('stage'), traceback=''.join(traceback.format_exception(error)),
            process=process_sample(), tracked=budget.statistics(),
            scope=scope_sample(scope), record_builders=failed_builder_evidence(error))
        # The held exception has now been recorded while its frames stayed paid.
        # Drop those frames explicitly; do not collect or retry the failed work.
        traceback.clear_frames(error.__traceback__)
        error.__traceback__ = None
        graph = raw = block = None
        raw_owner = decoded_owner = None
        del graph, raw, raw_owner, decoded_owner
        try:
            owners.close()
        except BaseException as cleanup_error:
            record['cleanup_failure'] = repr(cleanup_error)
        save()
    finally:
        if 'original_readonly' in record:
            after = file_hash(record['original_readonly']['path'])
            record['original_readonly']['after_sha256'] = after
            record['original_readonly']['unchanged'] = after == record['original_readonly']['sha256']
            if not record['original_readonly']['unchanged']:
                failed = True
                record['status'] = 'REFUSED_OR_FAILED'
                record['source_integrity_failure'] = 'original source identity changed'
        record['loaded_sources'] = {str(Path(module.__file__).resolve()): file_hash(module.__file__)
            for module in tuple(sys.modules.values())
            if getattr(module, '__file__', None) and str(module.__file__).endswith('.py')
            and (Path(module.__file__).resolve().is_relative_to(R) or
                 Path(module.__file__).resolve().is_relative_to(I))}
        record['elapsed_seconds'] = time.monotonic()-started
        record['final_process'] = process_sample()
        record['final_tracked'] = budget.statistics()
        record['output_disk_bytes'] = disk_bytes(output)
        record['gc_disabled_during_measurement'] = True
        record['acceptance'] = 'INCOMPLETE: material simultaneous-live families and IV2 solver bounds remain unmeasured'
        try:
            guard.close()
        finally:
            if gc_was_enabled:
                gc.enable()
            save()
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch', type=Path)
    group.add_argument('--workload', type=Path)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--start-gate-bytes', type=int, default=None,
                        help='explicit Step 8 test start gate (>= 4 GiB); default: the unchanged 10 GiB gate')
    parser.add_argument('--start-gate-basis', default=None,
                        help='recorded reason: previous measured peak + 1 GiB floor + stated margin')
    parser.add_argument('--scale', type=int, default=SCALE, help='independent IV1 blocks, 1..4 (default 4)')
    parser.add_argument('--live-producer-bytes', type=int, default=None,
                        help='named live-producer child for producer records (coordinator D2-A); default none')
    args = parser.parse_args()
    return (launch(args.launch, smoke=args.smoke, start_gate=args.start_gate_bytes, basis=args.start_gate_basis,
                   scale=args.scale, live_producer_bytes=args.live_producer_bytes)
            if args.launch else workload(args.workload))


if __name__ == '__main__':
    raise SystemExit(main())
