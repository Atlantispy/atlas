"""Focused H-a controls, genuine tiny solves with explicit fixture provenance.

The legacy packaging reference is a verbatim original function compiled before
the immutable module identity is captured. No live implementation is patched.
"""
import ast
from concurrent.futures import CancelledError
from contextlib import ExitStack
import gc
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import exterior_mesh_patch as EP
import heat_ledger_issuer_patch as PATCH
import mimetic_patch as MP
import private_heat_bundle as B
import private_heat_indexed_runtime as P
import test_private_heat_indexed_runtime as FIXTURE


HERE = Path(__file__).resolve().parent
R, T, BASE, H = FIXTURE.R, FIXTURE.T, FIXTURE.BASE, FIXTURE.H
_temporary = _path = None


def _reference_functions(original):
    tree = ast.parse(original)
    parts = []
    for name in ('advance', '_advance_verified'):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        text = ast.get_source_segment(original, node)
        text = text.replace('_advance_verified', '_advance_legacy_packaging_verified')
        if name == 'advance':
            text = text.replace('def advance(', 'def advance_legacy_packaging(', 1)
        parts.append(text)
    return '\n\n'.join(parts)+'\n\n'


def setUpModule():
    global _temporary, _path, I, E, M, WorkBudget, create_retained_scope, composed
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('fresh source-selected test process required')
    manifest, inputs = FIXTURE.authenticated_inputs()
    outputs, _ = B.construct(inputs, reference_root=H, reference_pins=B.REFERENCE_PINS)
    predecessor = P.issuer_source((H/'private_heat_native_issuer_r12.py').read_text(encoding='utf8'))
    issuer = PATCH.issuer_source(predecessor)
    marker = '# Capture already imported dependencies ONCE, before a caller can request an\n'
    if issuer.count(marker) != 1:
        raise ValueError('test-only reference declaration boundary changed')
    issuer = issuer.replace(marker, _reference_functions(predecessor)+marker)
    outputs['private_heat_native_issuer_r13.py'] = issuer.encode()
    outputs['private_heat_native_projection_r4.py'] = PATCH.projection_source(
        P.projection_source((H/'private_heat_native_projection_r4.py').read_text(encoding='utf8'))).encode()
    _temporary = tempfile.TemporaryDirectory(prefix='compact-heat-issuer-', dir=T/'_t')
    root = Path(_temporary.name)
    for name, digest in manifest['source_hashes'].items():
        raw = (BASE/'runtime-src'/name).read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError('native fixture source changed')
        if name.endswith('/integration_exterior_mesh.py'):
            raw = EP.transform(raw.decode()).encode()
        elif name.endswith('/integration_mimetic_heat.py'):
            raw = MP.mimetic_source(raw.decode()).encode()
        outputs[name] = raw
    for name, raw in outputs.items():
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    composed = outputs
    _path = list(sys.path)
    sys.path[:0] = [str(root), str(HERE), str(R), str(BASE/'ram'), str(BASE/'helpers'), str(H),
                   str(H/'source/tectonics/tests')]
    I = importlib.import_module('private_heat_native_issuer_r13')
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    M = importlib.import_module('atlas_tectonics.integration_mimetic_heat')
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    create_retained_scope = importlib.import_module('content_cache').create_retained_scope
    FIXTURE.FIXTURE.E = E
    FIXTURE.FIXTURE.T.E = E


def tearDownModule():
    if _path is not None:
        sys.path[:] = _path
    if _temporary is not None:
        _temporary.cleanup()


def synthetic_call(execution, geometry, scope):
    cap = np.asarray([float(c[0])*3 for c in geometry._cells])
    arrays = dict(enthalpy_j=cap*300, capacity_j_k=cap, source_w=np.zeros(len(cap)))
    snapshot = I.RegionalMechanicalSnapshot(dict(schema='EXPLICIT_H_A_PACKAGING_FIXTURE'), arrays)
    target = '1e-24'
    plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id=I.METHOD,
        geometry_id=geometry.geometry_id, conductivity_w_m_k=[1.]*len(cap),
        absolute_residual_target=I._enc(I.Fraction(target)), absolute_residual_target_decimal=target,
        original_target=dict(kind='decimal-string', value=target), boundary={})
    meta = dict(schema='atlas.private.composed-owner-call.r1', state_id=snapshot.result_id,
        duration_s=.125, cell_ids=list(P.ordered_cell_ids(geometry)),
        source_policy='EXPLICIT_SYNTHETIC_FIXTURE_NOT_OWNER_ACCEPTANCE')
    return I._make_call(meta, arrays, geometry, execution, plan, (snapshot,), fixture=True,
                        record_scope=scope)


class PackagingTests(unittest.TestCase):
    def test_fixed_compact_module_loaded_functions_and_classes_are_bound(self):
        import record_tables
        import heat_ledger_tables
        expected = set(I._COMPACT_MODULE_NAMES)
        self.assertTrue(expected <= {module.__name__ for module in I._private_modules()})
        self.assertTrue(expected <= {Path(path).stem for path, _ in I._IMPORTED_SOURCES})
        I._verify_implementation()
        for module, name in ((PATCH, 'exact_rows'), (record_tables, 'RecordCodec'),
                             (heat_ledger_tables.CompactHeatSnapshot, 'array')):
            with patch.object(module, name, lambda *args, **kwargs: None):
                with self.assertRaises(ValueError):
                    I._verify_implementation()
        I._verify_implementation()

    def test_source_exact_once_and_numerical_kernel_unchanged(self):
        import exchange_record_patch as X
        issuer = P.issuer_source((H/'private_heat_native_issuer_r12.py').read_text(encoding='utf8'))
        projection = P.projection_source((H/'private_heat_native_projection_r4.py').read_text(encoding='utf8'))
        joined = X.producer_source(P.joined_source((H/'private_heat_joined_consumer_r6.py').read_text(
            encoding='utf8'), expected_sha256=X.JOINED_SHA))
        for source, transform in ((issuer, PATCH.issuer_source), (projection, PATCH.projection_source),
                                   (joined, PATCH.joined_source)):
            result = transform(source)
            compile(result, '<source-exact-packaging>', 'exec')
            for invalid in (source+'\n', result, source.replace('import ', '# import ', 1)):
                with self.assertRaises(ValueError):
                    transform(invalid)
        kernel = 'private_heat_forward_kernel_r13.py'
        self.assertEqual(ast.dump(ast.parse(composed[kernel])),
                         ast.dump(ast.parse((H/kernel).read_bytes())))
        old_tree, new_tree = ast.parse(issuer), ast.parse(PATCH.issuer_source(issuer))
        for name in ('advance', '_verify_implementation', '_verified_call', '_verify_call',
                     '_origin_signature', '_target_text', '_validate_target_plan'):
            get = lambda tree: next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(ast.dump(get(old_tree)), ast.dump(get(new_tree)), name)
        self.assertNotIn('R.decoded(value._result._snapshot._metadata', PATCH.joined_source(joined))

    def test_full_logical_metadata_result_and_arrays_equal_legacy_packaging(self):
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='h-a-parity')
        record = FIXTURE.FIXTURE.two_cell_record(budget)
        geometry = M.MimeticGeometry(record, budget=budget)
        with I.ExecutionContext('scipy') as execution:
            call = synthetic_call(execution, geometry, scope)
            old = I.advance_legacy_packaging(call)
            new = I.advance(call)
            self.assertEqual(new.result_id, old.result_id)
            with new._snapshot.ledger as ledger, ledger.iter_json() as stream:
                parts = []
                for block in stream:
                    with block:
                        parts.append(block.value)
                raw = b''.join(parts)
            self.assertEqual(raw, old._snapshot._metadata)
            self.assertEqual(new._snapshot.metadata_identity.sha256, sha256(raw).hexdigest())
            for name in old.array_names:
                self.assertEqual(new.array(name).tobytes(), old.array(name).tobytes(), name)
            self.assertEqual(new.plan_descriptor(), json.loads(old._plan_definition))
            self.assertEqual(I._snapshot_identity(new._snapshot, budget), old.result_id)
            self.assertFalse(json.loads(raw)['genuine_forward_origin'])
            with self.assertRaises(ValueError):
                new.descriptor()
            del new, old, call, parts, raw
        del geometry, record
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_direct_exact_rows_are_paid_bounded_and_keep_failure_funding(self):
        import gmpy2
        from content_cache import ChargeSpec
        from record_tables import RecordCodec, StreamingRows
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='h-a-rows')
        value = gmpy2.mpq((1 << 200000)+1, (1 << 200003)+7)
        rows = PATCH.exact_rows([value, -value], scope, lambda: None)
        self.assertIs(type(rows), StreamingRows)
        packed = RecordCodec().pack_record(rows, record_schema='fixture.exact-rows', scope=scope,
                                           check=lambda: None)
        with packed.root() as root, root.at(0) as first, first.export(
                max_logical_bytes=1 << 20, max_owned_bytes=1 << 20) as out:
            self.assertEqual(out.value, [hex(int(value.numerator)), hex(int(value.denominator))])
        packed.close()
        def cancelled():
            raise CancelledError('explicit test cancellation')
        with self.assertRaises(CancelledError):
            next(PATCH.exact_rows([value], scope, cancelled).rows_factory())
        held = []
        baseline = budget.reserved_bytes
        def fail_with_row(rows=rows):
            with scope.reserve(ChargeSpec('held-test', 1)):
                row = next(rows.rows_factory())
                self.assertIsNotNone(row.value)
                raise RuntimeError('hold exact row')
        try:
            fail_with_row()
        except RuntimeError as error:
            held.append(error)
        self.assertGreater(budget.reserved_bytes, baseline)
        held.clear()
        del packed, rows
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_scope_missing_foreign_replaced_and_result_mutation_refuse(self):
        from compact_contracts import ContractError
        from types import SimpleNamespace
        budget, foreign = WorkBudget(1 << 30), WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='h-a-owner')
        other = create_retained_scope(foreign, process_epoch='h-a-foreign')
        owner = SimpleNamespace(_budget=budget, _record_scope=scope)
        self.assertIs(PATCH.required_scope((owner,), budget), scope)
        for origins, supplied, fixture in (((object(),), None, False), ((owner,), other, True),
                                            ((owner,), scope, False)):
            with self.assertRaises(ContractError):
                PATCH.required_scope(origins, budget, fixture=fixture, supplied=supplied)
        from heat_ledger_tables import CompactHeatSnapshot
        snap = CompactHeatSnapshot.from_components({'plan_id': 'p'}, {'x': np.asarray([1.])}, scope=scope)
        original = snap.result_id
        object.__setattr__(snap, 'result_id', '0'*64)
        with self.assertRaises(ContractError):
            PATCH.snapshot_identity(snap, budget)
        object.__setattr__(snap, 'result_id', original)
        snap.close()
        del snap, owner
        gc.collect()
        scope.close(); other.close()
        self.assertEqual((budget.reserved_bytes, foreign.reserved_bytes), (0, 0))

    def test_joined_writer_guard_refuses_invalid_foreign_and_sealed_candidates(self):
        from compact_contracts import ContractError, SegmentRef
        from heat_ledger_tables import CompactHeatSnapshot
        from interval_store_set import IntervalStoreSet
        from types import SimpleNamespace
        import private_heat_snapshot_store_r4 as STORE
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='h-a-store')
        foreign_budget = WorkBudget(1 << 30)
        foreign = create_retained_scope(foreign_budget, process_epoch='h-a-store-foreign')
        owner = SimpleNamespace(_budget=budget, _record_scope=scope)
        other = SimpleNamespace(_budget=foreign_budget, _record_scope=foreign)
        with tempfile.TemporaryDirectory(dir=T/'_t', prefix='heat-writer-') as directory, ExitStack() as cleanup:
            stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'),
                workflow_id='a'*64, scope=scope)
            cleanup.callback(stores.close)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            cleanup.callback(candidate.close)
            import builtins
            ordinary_import = builtins.__import__
            def without_restart_facade(name, *args, **kwargs):
                if name == 'compact_restart_store':
                    raise ImportError('Step 7 candidate must not require the later restart facade')
                return ordinary_import(name, *args, **kwargs)
            with patch('builtins.__import__', side_effect=without_restart_facade):
                self.assertIs(PATCH.require_candidate(candidate, owner), candidate)
                for target, source in ((None, owner), (stores, owner), (candidate, other)):
                    with self.assertRaises(ContractError):
                        PATCH.require_candidate(target, source)
                with self.assertRaises(CancelledError):
                    PATCH.require_candidate(candidate, owner, cancel=lambda: True)
            snapshot = CompactHeatSnapshot.from_components({'plan_id': 'p'}, {'x': np.asarray([1.])},
                                                            scope=scope)
            receipt = STORE.save(candidate, snapshot, bindings={'fixture': 'd'*64}, budget=budget)
            candidate.seal(SegmentRef.from_wire(receipt['metadata']['ledger']))
            with patch('builtins.__import__', side_effect=without_restart_facade):
                with self.assertRaisesRegex(ContractError, 'usable writer'):
                    PATCH.require_candidate(candidate, owner)
            snapshot.close(); candidate.close(); stores.close()
            del snapshot, candidate, stores
        del owner, other
        gc.collect()
        scope.close(); foreign.close()
        self.assertEqual((budget.reserved_bytes, foreign_budget.reserved_bytes), (0, 0))

    def test_optional_restart_facade_preserves_writer_scope_and_readonly_guards(self):
        from compact_contracts import ContractError
        from compact_restart_store import CompactRestartStore
        from types import SimpleNamespace
        budget, foreign_budget = WorkBudget(1 << 30), WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='heat-facade')
        foreign = create_retained_scope(foreign_budget, process_epoch='heat-facade-foreign')
        owner = SimpleNamespace(_budget=budget, _record_scope=scope)
        other = SimpleNamespace(_budget=foreign_budget, _record_scope=foreign)
        with tempfile.TemporaryDirectory(dir=T/'_t', prefix='heat-facade-') as directory:
            with CompactRestartStore.create_migration(str(Path(directory)/'catalog.json'),
                    workflow_id='a'*64, scope=scope, producer_identity='b'*64,
                    runtime_identity='c'*64) as store:
                self.assertIs(PATCH.require_candidate(store, owner), store.candidate)
                # An actual facade implies a loaded defining module. Missing
                # registration must refuse, never dynamically import WP9.
                with patch.dict(sys.modules):
                    sys.modules.pop('compact_restart_store')
                    with self.assertRaisesRegex(ContractError, 'actual same-scope'):
                        PATCH.require_candidate(store, owner)
                with self.assertRaisesRegex(ContractError, 'same-scope writer'):
                    PATCH.require_candidate(store, other)
                proxy = SimpleNamespace(candidate=store.candidate, scope=scope, readonly=False)
                with self.assertRaisesRegex(ContractError, 'actual same-scope'):
                    PATCH.require_candidate(proxy, owner)
                store.put('d'*64, {'marker': np.empty(0, dtype='u1')}, {'fixture': True})
                store.seal_and_promote('d'*64)
                with self.assertRaisesRegex(ContractError, 'same-scope writer'):
                    PATCH.require_candidate(store, owner)
        del owner, other, proxy, store
        scope.close(); foreign.close()
        self.assertEqual((budget.reserved_bytes, foreign_budget.reserved_bytes), (0, 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
