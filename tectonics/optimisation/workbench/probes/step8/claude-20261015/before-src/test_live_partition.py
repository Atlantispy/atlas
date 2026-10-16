"""WP14 exact producer/ownership controls; synthetic authority, no interval solve."""
import ast
from dataclasses import fields
from copy import deepcopy
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

import live_partition_patch as L
import partition_native_patch as PN
import test_partition_native_patch as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
SOURCE = F.BASE/'integration_differential_geometry.py'


def setUpModule():
    original = PN.transform
    with patch.object(PN, 'transform', lambda s: L.transform(original(s))):
        F.setUpModule()
    global D, T, R
    D, T, R = F.D, F.T, F.R


def tearDownModule():
    F.tearDownModule()


def _legacy_functions():
    source = PN.transform(SOURCE.read_text(encoding='utf8'))
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and
             node.name in ('_assemble_partition', 'prepare_interval_partition')]
    namespace = dict(vars(D))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<unchanged-native-producer>', 'exec'), namespace)
    return namespace


def _stream(value):
    result = []
    with value.iter_json() as stream:
        for part in stream:
            with part:
                result.append(part.value)
    return b''.join(result)


def _build_rows(body, rows, scope, operands):
    batch = L.SupportBatch(scope)
    for row in rows:
        owned = L.owned_support(row, scope.run_budget)
        issued = batch.issue(owned.value)
        batch.append(issued)
        del owned, issued, row
    body_owner = L.owned_support(body, scope.run_budget)
    return L.finish(body_owner, batch, *operands)


def retained_partition_fixture(scope, *, count=2016, check=lambda: None):
    """Fund the measured logical partition for a later simultaneous-live phase.

    Uses the caller's existing imported runtime and exact scope; creates no
    package, scope, store or measurement. Synthetic authority only. The caller
    owns the returned PartitionV2 and must close it after the combined phase.
    At count2016 its exact descriptor has123,747,711 canonical bytes.
    """
    import mesh_tables as M
    import test_partition_tables as templates
    from content_cache import RetainedScope
    if type(scope) is not RetainedScope or scope._closed or type(count) is not int or not 1 <= count <= 2016:
        raise ValueError('open existing scope and fixture count1..2016 required')
    native = PN._native()
    # Explicit fixture staging covers its bounded body, template and one row.
    staging = M._Allocation(scope.run_budget, (8 << 20)+4096*count)
    body, sample = templates.tiny_partition(scope.run_budget, count=1, depth=16)
    template = sample[0]
    constraint = template['constraints']['carried:edge']
    while constraint['kind'] == 'snapshot-rotated':
        constraint = constraint['constraint']
    constraint['rays'][0]['prior_rotations'] *= 48
    body['support_ids'] = []; body['identity_start_cells'] = []
    body['native_contacts'][0]['contacts'] = []
    body['max_components'] = count+1
    body['interval_id'] = native._record_hash({'fixture': 'typed restore protocol only'})
    batch = L.SupportBatch(scope, check=check)
    for i in range(count):
        row = deepcopy(template)
        component = row['components'][0]
        component.update(logical_cell_id=templates.ident('measure-cell'+str(i)),
                         parent_cell_id=templates.ident('measure-parent'+str(i)))
        row['voxel_index'] = [i, 0, 0]
        row['max_components'] = count+1
        owned = L.owned_support(row, scope.run_budget)
        support = batch.issue(owned.value); batch.append(support)
        identity = support.support_id
        body['support_ids'].append(identity)
        body['identity_start_cells'].append(dict(parent_cell_id=component['parent_cell_id'],
                                                cell_id=component['logical_cell_id']))
        body['native_contacts'][0]['contacts'].append(dict(support_id=identity,
            logical_cell_id=component['logical_cell_id'], voxel_index=row['voxel_index'], axis=0, end=0))
        del owned, support, row, component
    view = batch.finish(body, native._record_hash(body))
    batch.close()
    del staging
    return view


class LivePartitionTests(unittest.TestCase):
    def setUp(self):
        from content_cache import create_retained_scope
        self.budget = T.WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='live-partition-test')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())

    def test_exact_transform_keeps_scientific_functions_and_native_fallback(self):
        before = PN.transform(SOURCE.read_text(encoding='utf8'))
        after = L.transform(before)
        def functions(source):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef)}
        a, b = functions(before), functions(after)
        self.assertEqual({name for name in a if a[name] != b[name]}, {
            'partition_physical_support', 'prepare_differential_partition', '_assemble_partition',
            'prepare_interval_partition'})
        self.assertEqual(set(b)-set(a), {'_carried_partition_regions'})
        with self.assertRaisesRegex(ValueError, 'reviewed'):
            L.transform(after)
        with self.assertRaisesRegex(ValueError, 'reviewed'):
            L.transform(before+'\n')
        self.assertIsNone(L.resolve_scope(self.budget))
        with self.assertRaises(D.V.VolumeError):
            L.resolve_scope(T.WorkBudget(1 << 20), self.scope)

    def test_complete_existing_geometry_chain_accepts_only_last_stage_transform(self):
        sys.path.insert(0, str(HERE.parent/'endpoint-checkpoints'))
        import patch_endpoint_seam as SEAM
        import geometry_transfer as G
        with tempfile.TemporaryDirectory(prefix='lp-chain-', dir=HERE.parents[4]) as directory:
            directory = Path(directory)
            (directory/'integration_differential_geometry.py').write_text(
                PN.transform(SOURCE.read_bytes().decode('utf8')), encoding='utf8', newline='\n')
            (directory/'integration_component_volume_batch.py').write_bytes(
                (F.BASE/'integration_component_volume_batch.py').read_bytes())
            seam = SEAM.candidate_sources(directory)['integration_differential_geometry.py']
        self.assertEqual(sha256(seam.encode()).hexdigest(),
                         '213d1ebb5ef4d072f65ae3c08b99a4537f61985e46fe802e54c58a1b6ac471fd')
        composed = G.transform(seam, compact=True)
        self.assertEqual(sha256(composed.encode()).hexdigest(), L.COMPOSED_INPUT_SHA256)
        for transform in (L.transform_lifetimes, L.transform):
            candidate = transform(composed)
            ast.parse(candidate)
            self.assertIn('_runtime_transfer=None', candidate)
            self.assertIn('_transferred_partition_binding(parent_partition, old, funding, collar, budget, _runtime_transfer)', candidate)
            with self.assertRaises(ValueError):
                transform(seam)

    def test_incremental_codec_exact_types_foreign_nodes_and_held_cancellation(self):
        from concurrent.futures import CancelledError
        import record_tables as RT
        values = [None, True, False, -0.0, 1.25, 1 << 300, '"\\\n\0\U0001f30d',
                  [hex((1 << 2000)+3), hex(1 << 1800)], {'x': [], 'y': {'a': 'same'}}]
        builder = RT.RecordBuilder(scope=self.scope)
        handles = [builder.append(value, record_schema='atlas.test-row.v1') for value in values]
        for value, handle in zip(values, handles, strict=True):
            self.assertEqual(handle.identity.sha256, sha256(RT.canonical(value)).hexdigest())
        record = builder.finish(dict(rows=handles, repeated=handles[-1]), record_schema='atlas.test-root.v1')
        expected = RT.canonical(dict(rows=values, repeated=values[-1]))
        self.assertEqual(_stream(record), expected)
        self.assertEqual(record.identity().canonical_bytes, len(expected))
        with self.assertRaises(ValueError):
            builder.append({}, record_schema='atlas.test-row.v1')
        other = RT.RecordBuilder(scope=self.scope)
        with self.assertRaisesRegex(ValueError, 'foreign'):
            other.finish(handles[0], record_schema='atlas.test-root.v1')
        other.close(); record.close()
        del record, other, builder, handles
        baseline = self.budget.reserved_bytes
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            if calls == 8:
                raise CancelledError('explicit codec cancellation')
        builder = RT.RecordBuilder(scope=self.scope, check=cancelled)
        error = None
        try:
            builder.append(values, record_schema='atlas.test-row.v1')
        except CancelledError as caught:
            error = caught
        self.assertIsNotNone(error)
        builder.close()
        held = self.budget.reserved_bytes
        self.assertGreater(held, baseline)
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, held)
        error.__traceback__ = None
        del error, builder
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, baseline)

    def test_batched_fresh_descriptor_and_support_identity_without_native_encoding(self):
        body, rows = T.tiny_partition(self.budget, count=35)
        operands = F.source_operands(body, self.budget)
        # Tuple normalisation used to be an incidental effect of native JSON.
        rows[0]['components'][0]['partition_path'] = tuple(rows[0]['components'][0]['partition_path'])
        body['support_ids'] = [D._record_hash(row) for row in rows]
        expected = D._encoded(dict(body, partition_id=D._record_hash(body), supports=rows))
        with patch.object(D, '_encoded', side_effect=AssertionError('whole native encoding forbidden')):
            result = _build_rows(body, rows, self.scope, operands)
        view = PN.compact_view(result)
        self.assertIs(view.scope, self.scope)
        self.assertIsNone(view.segment_ref)
        self.assertEqual(_stream(view), expected)
        self.assertEqual(view.identity().sha256, sha256(expected).hexdigest())
        for i, owned in enumerate(PN.support_records(result)):
            self.assertEqual(D._encoded(owned.value), D._encoded(rows[i]))
        del owned, result
        view.close()

    def test_deduplicated_incremental_handles_remain_paid_after_builder_close(self):
        import record_tables as RT
        baseline = self.budget.reserved_bytes
        builder = RT.RecordBuilder(scope=self.scope)
        handles = [builder.append(None, record_schema='atlas.test-row.v1') for _ in range(300)]
        self.assertEqual(len({handle.index for handle in handles}), 1)
        builder.close()
        del builder
        self.assertGreaterEqual(self.budget.reserved_bytes-baseline, 300*1024)
        del handles
        self.assertEqual(self.budget.reserved_bytes, baseline)

    def test_simultaneous_live_fixture_uses_existing_scope_and_releases_all_funding(self):
        baseline = self.budget.reserved_bytes
        view = retained_partition_fixture(self.scope, count=3)
        self.assertIs(view.scope, self.scope)
        self.assertEqual(view.support_count, 3)
        self.assertGreater(view.identity().canonical_bytes, 180000)
        self.assertGreater(self.budget.reserved_bytes, baseline)
        view.close()
        del view
        self.assertEqual(self.budget.reserved_bytes, baseline)

    def test_assembly_contact_and_output_parity_with_controlled_support_operand(self):
        body, rows = T.tiny_partition(self.budget, count=1)
        operands = F.source_operands(body, self.budget, initial=True)
        funding, _, geometry = operands
        current = dict(network_id=body['network_id'], start_time_s=T.q(0), end_time_s=T.q(0))
        geometry = D._issue(D.CurrentGeometry, current, self.budget)
        box = D.V.CartesianCell((-1, -1, -1), (1, 1, 1), budget=self.budget)
        collar = SimpleNamespace(plan_id=body['collar_plan_id'], _budget=self.budget,
                                 cell_geometries=lambda: (box,))
        sphere = SimpleNamespace(network=SimpleNamespace(plate_ids=('plate:A',),
                                 sphere=SimpleNamespace(radius_m=10)))
        region = dict(source_key=['patch', 0], plate_id='plate:A', source_face_id='face',
                      radial_band=0, chart=0, radial_layer=rows[0]['radial_layer'],
                      source_chart_id=T.ident('assembly-region'))
        original = dict(source=body['source'], volume_map_id=body['volume_map_id'],
                        component_keys=body['component_keys'])
        row_owners = []
        def support_operand(interval, plate, layer, voxel, *, _owned_result=False, **kwargs):
            row = deepcopy(rows[0])
            row.update(voxel=voxel.record(), current_geometry_id=interval.geometry_id,
                       interval_id=None, network_id=current['network_id'])
            row['components'][0].pop('parent_cell_id'); row['components'][0].pop('start_identity')
            if not _owned_result:
                return D._issue(D.DifferentialSupport, row, self.budget)
            owned = L.owned_support(row, self.budget)
            row_owners.append(weakref.ref(owned))
            return owned
        args = (funding, sphere, geometry, collar, original, [region])
        kwargs = dict(grid_lines=((-10, -1, 1, 10),)*3, max_components=1000, budget=self.budget)
        namespace = _legacy_functions()
        namespace['partition_physical_support'] = support_operand
        old = namespace['_assemble_partition'](*args, **kwargs)
        expected = D._encoded(old.descriptor())
        original_append = L.SupportBatch.append
        def checked_append(batch, support):
            self.assertIsNotNone(row_owners[-1](), 'working row funding released before its last use')
            return original_append(batch, support)
        with patch.object(D, 'partition_physical_support', support_operand), patch.object(L.SupportBatch, 'append', checked_append):
            new = D._assemble_partition(*args, **kwargs, compact_scope=self.scope)
        self.assertTrue(all(ref() is None for ref in row_owners))
        view = PN.compact_view(new)
        self.assertEqual(new.partition_id, old.partition_id)
        self.assertEqual(_stream(view), expected)
        del new, old, namespace
        view.close()

    def test_successor_chart_parity_detaches_only_needed_values_before_assembly(self):
        body, rows = T.tiny_partition(self.budget, count=3)
        for row in rows:
            row['components'][0]['constraints'] = [['carried:edge', 1], ['normal', -1]]
        body['support_ids'] = [D._record_hash(row) for row in rows]
        operands = F.source_operands(body, self.budget)
        parent = _build_rows(body, rows, self.scope, operands)
        view = PN.compact_view(parent)
        legacy = D.DifferentialPartition.restore(dict(body, partition_id=D._record_hash(body), supports=rows),
                                                  *operands, budget=self.budget)
        step = dict(parent_network_id=body['endpoint_network_id'], prior_trajectory_id=body['trajectory_id'],
                    start_time_s=body['end_time_s'], end_time_s=T.q(2), duration_s=T.q(1),
                    plate_angular_velocity_rad_s={'plate:A': [T.q(0)]*3}, boundary_paths=[])
        interval = D._issue(D.DifferentialInterval, step, self.budget)
        finite = R.PreparedFiniteStocks(T.ident('registry'), [dict(stock_id='sink', kind='sink',
            lineage={'fixture': 'finite restore control'}, volume_m3=T.q(1), exact={'mass': T.q(1)})],
            field_names=('mass',), nonnegative_fields=('mass',), budget=self.budget)
        captures = []
        def capture(funding, sphere, geometry, collar, original, regions, **kwargs):
            captures.append((D._encoded(regions), kwargs['grid_lines'], kwargs.get('_final_fields')))
            result = D._issue(D.DifferentialPartition, dict(body), self.budget)
            object.__setattr__(result, '_supports', ())
            return result
        namespace = _legacy_functions(); namespace['_assemble_partition'] = capture
        state = finite.initial()
        old = namespace['prepare_interval_partition'](legacy, interval, operands[0], object(), operands[1],
            finite_stock_state=state, max_components=1000, budget=self.budget)
        # Compact parent is never expanded or materialised as a JSON handle.
        with patch.object(PN, 'materialise_support', side_effect=AssertionError('native parent support forbidden')):
            with patch.object(D, '_assemble_partition', capture):
                new = D.prepare_interval_partition(parent, interval, operands[0], object(), operands[1],
                    finite_stock_state=state, max_components=1000, budget=self.budget)
            lifetime_source = L.transform_lifetimes(PN.transform(SOURCE.read_text(encoding='utf8')))
            names = {'prepare_interval_partition', '_carried_partition_regions'}
            nodes = [node for node in ast.parse(lifetime_source).body
                     if isinstance(node, ast.FunctionDef) and node.name in names]
            safe_namespace = dict(vars(D), _assemble_partition=capture)
            exec(compile(ast.Module(body=nodes, type_ignores=[]), '<partition-lifetimes-only>', 'exec'), safe_namespace)
            safe = safe_namespace['prepare_interval_partition'](parent, interval, operands[0], object(), operands[1],
                finite_stock_state=state, max_components=1000, budget=self.budget)
        self.assertEqual(captures[0][:2], captures[1][:2])
        self.assertEqual(captures[1][2], {key: old.record()[key]
            for key in ('finite_state_id', 'finite_owner_id', 'component_registry_id')})
        self.assertEqual(captures[2][:2], captures[0][:2])
        self.assertEqual(safe._json, old._json)
        del new, old, safe, legacy, parent, state, namespace, safe_namespace
        finite.close(); view.close()

    def test_held_pack_failure_keeps_row_and_scope_charges_until_traceback_release(self):
        body, rows = T.tiny_partition(self.budget, count=3)
        operands = F.source_operands(body, self.budget)
        rows[0]['unknown-science'] = 'deliberate schema refusal'
        body['support_ids'] = [D._record_hash(row) for row in rows]
        baseline = self.budget.reserved_bytes
        error = None
        try:
            _build_rows(body, rows, self.scope, operands)
        except ValueError as caught:
            error = caught
        self.assertIsNotNone(error)
        self.assertIn('scientific field', str(error))
        held = self.budget.reserved_bytes
        self.assertGreater(held, baseline)
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, held)
        error.__traceback__ = None
        del error
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, baseline)

    def test_successful_producer_release_does_not_depend_on_cyclic_collection(self):
        body, rows = T.tiny_partition(self.budget, count=4)
        operands = F.source_operands(body, self.budget)
        baseline = self.budget.reserved_bytes
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            part = _build_rows(body, rows, self.scope, operands)
            view = PN.compact_view(part)
            del part
            view.close()
            del view
            self.assertEqual(self.budget.reserved_bytes, baseline)
        finally:
            if was_enabled:
                gc.enable()


def measure(mode, count):
    """Matched support construction/body packaging; excludes scientific solve.

    Repeated deep charts and rational widths model the measured partition class;
    rows are produced independently, not held as an input list. No store writes.
    """
    from content_cache import create_retained_scope
    import partition_workflow_patch as PW
    import psutil
    budget = T.WorkBudget(2 << 30)
    scope = create_retained_scope(budget, process_epoch='live-partition-measure')
    body, sample = T.tiny_partition(budget, count=1, depth=16)
    template = sample[0]
    constraint = template['constraints']['carried:edge']
    while constraint['kind'] == 'snapshot-rotated':
        constraint = constraint['constraint']
    for ray in constraint['rays'][:1]:
        ray['prior_rotations'] = ray['prior_rotations']*48
    body['support_ids'] = []; body['identity_start_cells'] = []
    body['native_contacts'][0]['contacts'] = []
    body['max_components'] = count+1
    operands = F.source_operands(body, budget)
    del sample
    process = psutil.Process()
    memory_before = process.memory_info()._asdict()
    started = time.perf_counter()
    native = [] if mode == 'baseline' else None
    batch = L.SupportBatch(scope) if mode == 'candidate' else None
    raw_support_bytes = 0
    for i in range(count):
        if i % 256 == 0:
            print(f'{mode}: support {i}/{count}, elapsed {time.perf_counter()-started:.3f}s', file=sys.stderr, flush=True)
        row = deepcopy(template)
        component = row['components'][0]
        component.update(logical_cell_id=T.ident('measure-cell'+str(i)), parent_cell_id=T.ident('measure-parent'+str(i)))
        row['voxel_index'] = [i, 0, 0]
        row['max_components'] = count+1
        if mode == 'baseline':
            first = D._issue(D.DifferentialSupport, row, budget)
            row = first.record()
            support = D._issue(D.DifferentialSupport, row, budget)
            native.append(support)
            raw_support_bytes += len(support._json)
            identity = support.support_id
            del first, support
        else:
            owned = L.owned_support(row, budget)
            support = batch.issue(owned.value); batch.append(support)
            identity = support.support_id
            del owned, support
        body['support_ids'].append(identity)
        body['identity_start_cells'].append(dict(parent_cell_id=component['parent_cell_id'], cell_id=component['logical_cell_id']))
        body['native_contacts'][0]['contacts'].append(dict(support_id=identity,
            logical_cell_id=component['logical_cell_id'], voxel_index=row['voxel_index'], axis=0, end=0))
        del row, component
    print(f'{mode}: final compact packaging, elapsed {time.perf_counter()-started:.3f}s', file=sys.stderr, flush=True)
    if mode == 'baseline':
        first = D._issue(D.DifferentialPartition, body, budget)
        object.__setattr__(first, '_supports', tuple(native))
        decoded = first.record()
        part = D._issue(D.DifferentialPartition, decoded, budget)
        object.__setattr__(part, '_supports', first.supports)
        del first, decoded, native
        view = PW.convert_native(part, budget, scope=scope)
    else:
        body_owner = L.owned_support(body, budget)
        part = L.finish(body_owner, batch, *operands)
        del body_owner, batch
        view = PN.compact_view(part)
    elapsed = time.perf_counter()-started
    print(f'{mode}: packaging complete, elapsed {elapsed:.3f}s', file=sys.stderr, flush=True)
    memory_after = process.memory_info()._asdict()
    identity = view.identity()
    packed_bytes = sum(array.nbytes for array in view.record._owner.value[1].values())
    result = dict(mode=mode, count=count, wall_seconds=elapsed,
        partition_id=view.partition_id, descriptor_identity=identity.to_wire(),
        packed_array_bytes=packed_bytes, native_support_bytes_held=raw_support_bytes,
        retained={field.name: getattr(scope.stats(), field.name) for field in fields(scope.stats())}, budget=budget.statistics(),
        process_memory_before=memory_before, process_memory_after=memory_after,
        disk_output_bytes=0, scope='matched support construction and compact body finish; no science solve or store publication')
    del part
    view.close()
    del view, operands, body, template, constraint, ray
    gc.collect(); scope.close()
    result['reserved_after_close'] = budget.reserved_bytes
    assert result['reserved_after_close'] == 0, budget.statistics()
    return result


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--measure':
        setUpModule()
        try:
            print(json.dumps(measure(sys.argv[2], int(sys.argv[3])), sort_keys=True, default=dict), flush=True)
        finally:
            tearDownModule()
    else:
        unittest.main()
