"""UNEXECUTED focused stdlib seam controls; no scientific candidate import.

At a future authorised run only, selected helper function definitions are compiled
from pinned source AST into a mock namespace. No native helper or science module
is imported, and no process/native query is made by these tests.
"""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

HERE = Path(__file__).resolve().parent
FUNCTIONS = {'_native_error', '_native_admit_worker', '_native_accept_worker',
    '_native_close_worker', 'parent_native_binding', 'native_binding_provenance', '_native_capture_self'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def receipt(pid=42, creation=123):
    return dict(schema='plan15.native-binding.r1', pid=pid, creation_filetime=creation,
        module=dict(path='pinned.dll', sha256='a'*64, base=1000, size=10000),
        exports={'mpfr_mul': dict(address=1100, rva=100)})


def status(value):
    return dict(route='compiled', assembly_observation=dict(status='OBSERVED',
        evidence=dict(context=dict(native_binding=value))))


class BindingSeams(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((HERE/'private_heat_functionals_parallel_r1.py').read_bytes())
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
        require({node.name for node in nodes} == FUNCTIONS, 'helper definitions missing')
        self.api = {name: Mock() for name in ('open_admitted', 'validate_receipt', 'capture_self')}
        self.expected = dict(path=str(Path('pinned.dll').resolve()))
        self.ns = dict(_state={}, _assembly_require=require,
            _assembly_json=lambda value: json.loads(json.dumps(value)),
            _native_binding_api=lambda: self.api, _native_expected=lambda: self.expected,
            _native_live_token=Mock(return_value=('sealed',)), _MPFR_EXPORT_NAMES=('mpfr_mul',),
            perf_counter=Mock(side_effect=range(100)), os=os, Path=Path)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<mock-observer-binding-seams>', 'exec'), self.ns)
        self.bound = SimpleNamespace(pid=42, creation_filetime=123, owner_record={'proof': 'parent-owned'},
            query=Mock(return_value=receipt()), close=Mock())
        self.worker = SimpleNamespace(native_bound=None, native_receipt=None, row={'pid': 42},
            process=SimpleNamespace(pid=41, _handle=999))
        self.api['open_admitted'].return_value = self.bound

    def admit(self):
        self.ns['_native_admit_worker'](self.worker, 42)

    def test_admission_uses_actual_ready_pid_and_retained_launch_handle(self):
        self.admit()
        self.api['open_admitted'].assert_called_once_with(42, 41, 999)
        self.assertIs(self.worker.native_bound, self.bound)
        self.assertEqual(self.worker.row['native_binding_parent']['owner_record'], {'proof': 'parent-owned'})

    def test_missing_registry_cannot_use_child_payload(self):
        self.worker.row['candidate_heat_route'] = status(receipt())
        with self.assertRaisesRegex(ValueError, 'independent parent'):
            self.ns['parent_native_binding'](42)

    def test_independent_query_once_and_registry_is_copied(self):
        self.admit()
        self.ns['_native_accept_worker'](self.worker, status(receipt()))
        self.ns['_native_accept_worker'](self.worker, status(receipt()))
        self.bound.query.assert_called_once_with(self.expected)
        result = self.ns['parent_native_binding'](42)
        result['module']['base'] = 999
        self.assertEqual(self.ns['parent_native_binding'](42), receipt())
        self.assertEqual(self.worker.row['native_binding_costs']['receiver_query_calls'], 1)

    def test_forged_child_receipt_refuses_before_registry(self):
        self.admit()
        wrong = receipt(); wrong['module']['base'] += 1
        with self.assertRaisesRegex(ValueError, 'worker pointers differ'):
            self.ns['_native_accept_worker'](self.worker, status(wrong))
        self.assertNotIn(42, self.ns['_state'].get('native_parent_registry', {}))
        self.assertIn('native_binding_error', self.worker.row)
        self.assertEqual(self.worker.row['candidate_heat_route'], status(wrong))
        self.assertEqual(self.worker.row['native_binding_parent']['receipt'], receipt())

    def test_partial_admission_remains_owned_for_cleanup(self):
        self.bound.pid = 99
        with self.assertRaisesRegex(ValueError, 'actual admitted native process'):
            self.admit()
        self.assertIs(self.worker.native_bound, self.bound)
        self.ns['_native_close_worker'](self.worker)
        self.bound.close.assert_called_once()

    def test_missing_actual_handle_refuses(self):
        with self.assertRaisesRegex(ValueError, 'independently admitted'):
            self.ns['_native_accept_worker'](self.worker, status(receipt()))

    def test_query_failure_retains_cost_and_error(self):
        self.admit(); self.bound.query.side_effect = ValueError('dead actual process')
        with self.assertRaisesRegex(ValueError, 'dead actual process'):
            self.ns['_native_accept_worker'](self.worker, status(receipt()))
        self.assertEqual(self.worker.row['native_binding_costs']['receiver_query_calls'], 1)
        self.assertIn('native_binding_error', self.worker.row)

    def test_pid_reuse_with_other_creation_refuses(self):
        self.admit()
        self.ns['_state']['native_parent_registry'] = {42: {'receipt': receipt(creation=122)}}
        with self.assertRaisesRegex(ValueError, 'PID reused'):
            self.ns['_native_accept_worker'](self.worker, status(receipt()))

    def test_not_observed_stays_passive(self):
        self.ns['_native_accept_worker'](self.worker, {'route': 'NOT_OBSERVED'})
        self.bound.query.assert_not_called()
        self.api['capture_self'].assert_not_called()

    def test_failed_observation_refuses(self):
        with self.assertRaisesRegex(ValueError, 'compiled observation refused'):
            self.ns['_native_accept_worker'](self.worker, {'route': 'OBSERVATION_FAILED'})

    def test_close_idempotent_and_preserves_original_failure(self):
        self.admit(); self.bound.close.side_effect = ValueError('close fault')
        self.ns['_native_close_worker'](self.worker, preserve_error=True)
        self.ns['_native_close_worker'](self.worker, preserve_error=True)
        self.bound.close.assert_called_once()
        self.assertIn('native_binding_cleanup_error', self.worker.row)

    def test_close_fault_without_original_failure_raises(self):
        self.admit(); self.bound.close.side_effect = ValueError('close fault')
        with self.assertRaisesRegex(ValueError, 'close fault'):
            self.ns['_native_close_worker'](self.worker)

    def test_local_capture_once_and_changed_seal_refuses(self):
        own = receipt(pid=os.getpid())
        self.api['capture_self'].return_value = own
        module = SimpleNamespace(_MPFR_PATH=Path('pinned.dll'), mpfr_mul=object())
        self.assertEqual(self.ns['_native_capture_self'](module), own)
        self.assertEqual(self.ns['_native_capture_self'](module), own)
        self.api['capture_self'].assert_called_once()
        self.ns['_native_live_token'].return_value = ('changed',)
        with self.assertRaisesRegex(ValueError, 'local MPFR binding changed'):
            self.ns['_native_capture_self'](module)


class SourceBoundaries(unittest.TestCase):
    def setUp(self):
        self.new = ast.parse((HERE/'private_heat_functionals_parallel_r1.py').read_bytes())
        self.old = ast.parse((HERE.parent/'r11/private_heat_functionals_parallel_r1.py').read_bytes())

    def test_existing_pre_take_boundary(self):
        collect = next(node for node in self.new.body if isinstance(node, ast.FunctionDef) and node.name == '_collect')
        calls = [(node.lineno, node.func.id) for node in ast.walk(collect)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertLess(min(line for line, name in calls if name == '_native_accept_worker'),
                        min(line for line, name in calls if name == '_take'))

    def test_math_selectors_worker_and_ipc_unchanged(self):
        names = {'workers', 'completed', 'fell_back', '_pack', '_receive', '_unpack', '_dump',
                 '_take', '_serial', '_face_result', '_worker', 'reconstruct_faces', 'report', '_inputs', '_task'}
        for name in names:
            before = next(node for node in self.old.body if isinstance(node, ast.FunctionDef) and node.name == name)
            after = next(node for node in self.new.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(ast.dump(before), ast.dump(after), name)

    def test_original_shutdown_body_preserved_inside_cleanup_wrapper(self):
        old = next(node for node in self.old.body if isinstance(node, ast.ClassDef) and node.name == '_Worker')
        new = next(node for node in self.new.body if isinstance(node, ast.ClassDef) and node.name == '_Worker')
        before = deepcopy(next(node for node in old.body if isinstance(node, ast.FunctionDef) and node.name == 'end'))
        after = next(node for node in new.body if isinstance(node, ast.FunctionDef) and node.name == '_end_process')
        before.name = '_end_process'
        self.assertEqual(ast.dump(before), ast.dump(after))
        wrapper = next(node for node in new.body if isinstance(node, ast.FunctionDef) and node.name == 'end')
        self.assertTrue(any(isinstance(node, ast.Try) and node.finalbody for node in ast.walk(wrapper)))

    def test_configure_has_no_native_query_or_h3_activation(self):
        configure = next(node for node in self.new.body if isinstance(node, ast.FunctionDef)
                         and node.name == 'configure_assembly_observer')
        forbidden = {'capture_self', 'open_admitted', '_native_capture_self', '_native_binding_api', 'h3_status'}
        for node in ast.walk(configure):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden)


if __name__ == '__main__':
    unittest.main()
