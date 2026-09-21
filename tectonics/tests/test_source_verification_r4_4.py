"""Independent legacy-oracle and adversarial checks for exact live verification.

These are provenance/invalidation tests, not a hostile-Python security boundary.
The full inventory capture is retained as a separately executed comparison oracle.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import copy
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from atlas_tectonics import reuse, thermal
from atlas_tectonics._validation import TectonicsError


def legacy_verify(context):
    if context._closed:
        raise TectonicsError('execution context is closed')
    if reuse._source_bytes() != context._sources:
        raise TectonicsError('source changed')
    _, tokens, constants = reuse._callable_inventory(context.backend)
    if constants != context._constants or len(tokens) != len(context._tokens):
        raise TectonicsError('loaded implementation changed')
    for now, old in zip(tokens, context._tokens):
        if now[0] != old[0] or now[1] is not old[1] or now[2] is not old[2] or now[3] != old[3]:
            raise TectonicsError('loaded implementation changed')


def sample(value=([1, {'x': [2]}],), *, policy={'x': [3]}):
    return value


def alternative(value=None):
    return value


@dataclass
class SampleConstant:
    values: list


class CallableValue:
    def __call__(self):
        return 1


class FakeDispatcher:
    def __init__(self):
        self.py_func = types.FunctionType(sample.__code__, globals(), 'origin', copy.deepcopy(sample.__defaults__))
        self.py_func.__kwdefaults__ = copy.deepcopy(sample.__kwdefaults__)
        self.targetoptions = {'fastmath': False, 'nested': {'checks': [1, 2]}}

    def __call__(self):
        return 1


class ExactInventoryTests(unittest.TestCase):
    def setUp(self):
        self.function = types.FunctionType(sample.__code__, globals(), 'sample', copy.deepcopy(sample.__defaults__))
        self.function.__kwdefaults__ = copy.deepcopy(sample.__kwdefaults__)
        self.cls = type('GuardClass', (), {
            '__module__': thermal.__name__, 'method': self.function,
            'static': staticmethod(self.function), 'class_method': classmethod(self.function),
            'property_value': property(self.function), 'ignored': 1})
        self.dispatcher = FakeDispatcher()
        self.stack = __import__('contextlib').ExitStack()
        self.addCleanup(self.stack.close)
        additions = {'guard_sample': self.function, 'GuardClass': self.cls,
                     'guard_dispatcher': self.dispatcher, 'guard_callable': CallableValue(),
                     'GUARD_CONSTANT': SampleConstant([1, {'values': [2]}]),
                     'GUARD_TUPLE': (1, [2, {'a': 3}]), 'guard_unused': object(),
                     'GUARD_NONE': None}
        for key, value in additions.items():
            self.stack.enter_context(mock.patch.object(thermal, key, value, create=True))
        self.context = reuse.ExecutionContext('scipy')
        self.addCleanup(self.context.close)

    def check(self, accepted):
        for verifier in (legacy_verify, lambda c: c.verify()):
            if accepted:
                verifier(self.context)
            else:
                with self.assertRaises(TectonicsError):
                    verifier(self.context)

    def test_unchanged_and_repeated_identity(self):
        identity = self.context.identity
        for _ in range(3):
            self.check(True)
            self.assertEqual(identity, self.context.identity)

    def test_replaced_function_with_identical_code(self):
        fn = types.FunctionType(self.function.__code__, globals(), 'other', self.function.__defaults__)
        fn.__kwdefaults__ = self.function.__kwdefaults__
        with mock.patch.object(thermal, 'guard_sample', fn): self.check(False)
        self.check(True)

    def test_changed_code_on_same_function(self):
        old = self.function.__code__
        try:
            self.function.__code__ = old.replace(co_filename='<changed>')
            self.check(False)
        finally: self.function.__code__ = old

    def test_nested_positional_default_mutation(self):
        values = self.function.__defaults__[0][0]
        old = copy.deepcopy(values)
        try:
            values[1]['x'][0] = 9
            self.check(False)
        finally: values[:] = old

    def test_keyword_default_mutation(self):
        values = self.function.__kwdefaults__['policy']['x']
        try:
            values.append(8); self.check(False)
        finally: values.pop()

    def test_default_none_transition(self):
        old = self.function.__defaults__
        try:
            self.function.__defaults__ = None; self.check(False)
        finally: self.function.__defaults__ = old

    def test_keyword_none_transition(self):
        old = self.function.__kwdefaults__
        try:
            self.function.__kwdefaults__ = None; self.check(False)
        finally: self.function.__kwdefaults__ = old

    def test_new_function_alias(self):
        with mock.patch.object(thermal, 'guard_new', self.function, create=True): self.check(False)

    def test_removed_function(self):
        fn = thermal.guard_sample
        try:
            del thermal.guard_sample; self.check(False)
        finally: thermal.guard_sample = fn

    def test_function_replaced_by_noncallable(self):
        with mock.patch.object(thermal, 'guard_sample', None): self.check(False)

    def test_builtin_alias_replacement(self):
        with mock.patch.object(thermal, 'guard_callable', len): self.check(False)

    def test_new_class_method(self):
        with mock.patch.object(self.cls, 'added', alternative, create=True): self.check(False)

    def test_removed_class_method(self):
        old = vars(self.cls)['static']
        try:
            del self.cls.static; self.check(False)
        finally: self.cls.static = old

    def test_staticmethod_change(self):
        with mock.patch.object(self.cls, 'static', staticmethod(alternative)): self.check(False)

    def test_classmethod_change(self):
        with mock.patch.object(self.cls, 'class_method', classmethod(alternative)): self.check(False)

    def test_property_getter_change(self):
        with mock.patch.object(self.cls, 'property_value', property(alternative)): self.check(False)

    def test_descriptor_equivalence_preserved(self):
        # Legacy capture unwraps these descriptors to the same function.
        with mock.patch.object(self.cls, 'static', classmethod(self.function)): self.check(True)

    def test_class_origin_change(self):
        with mock.patch.object(self.cls, '__module__', 'foreign_module'): self.check(False)

    def test_class_noncallable_member_change_is_untracked(self):
        with mock.patch.object(self.cls, 'ignored', [1, 2, 3]): self.check(True)

    def test_native_options_mutation(self):
        opts = self.dispatcher.targetoptions
        try:
            opts['fastmath'] = True; self.check(False)
        finally: opts['fastmath'] = False

    def test_native_nested_options_mutation(self):
        values = self.dispatcher.targetoptions['nested']['checks']
        try:
            values.append(10); self.check(False)
        finally: values.pop()

    def test_native_python_code_change(self):
        old = self.dispatcher.py_func.__code__
        try:
            self.dispatcher.py_func.__code__ = old.replace(co_filename='<changed>'); self.check(False)
        finally: self.dispatcher.py_func.__code__ = old

    def test_native_default_mutation(self):
        old = self.dispatcher.py_func.__kwdefaults__
        try:
            self.dispatcher.py_func.__kwdefaults__ = {'policy': 12}; self.check(False)
        finally: self.dispatcher.py_func.__kwdefaults__ = old

    def test_plain_function_gains_native_wrapper_attributes(self):
        with mock.patch.object(self.function, 'py_func', alternative, create=True), mock.patch.object(self.function, 'targetoptions', {}, create=True):
            self.check(False)

    def test_native_definition_lost(self):
        with mock.patch.object(self.dispatcher, 'py_func', None): self.check(False)

    def test_dataclass_constant_nested_mutation(self):
        values = thermal.GUARD_CONSTANT.values[1]['values']
        try:
            values.append(9); self.check(False)
        finally: values.pop()

    def test_tuple_constant_nested_mutation(self):
        values = thermal.GUARD_TUPLE[1]
        try:
            values[1]['a'] = 8; self.check(False)
        finally: values[1]['a'] = 3

    def test_constant_type_distinction_in_json(self):
        with mock.patch.object(thermal, 'GUARD_TUPLE', (1.0, [2, {'a': 3}])): self.check(False)

    def test_new_registered_constant(self):
        with mock.patch.object(thermal, 'GUARD_NEW', 1, create=True): self.check(False)

    def test_none_constant_becomes_registered(self):
        with mock.patch.object(thermal, 'GUARD_NONE', 1): self.check(False)

    def test_ignored_objects_and_new_untracked_members(self):
        with mock.patch.object(thermal, 'guard_unused', object()), mock.patch.object(thermal, 'untracked_added', [], create=True):
            self.check(True)

    def test_runtime_lease_transients_remain_untracked(self):
        from atlas_tectonics import execution
        with mock.patch.object(execution, '_POOL_SLOTS', execution._POOL_SLOTS+1): self.check(True)

    def test_dictionary_insertion_order_is_not_identity(self):
        fn = thermal.guard_sample
        del thermal.guard_sample
        thermal.guard_sample = fn
        self.check(True)

    def test_duplicate_current_name_cannot_replace_missing_member(self):
        fn = thermal.guard_sample
        try:
            del thermal.guard_sample
            with mock.patch.object(thermal, 'GuardClass.method', self.function, create=True): self.check(False)
        finally: thermal.guard_sample = fn

    def test_private_expected_table_never_consumed(self):
        original = dict(self.context._expected)
        for _ in range(3): self.context.verify()
        self.assertEqual(original.keys(), self.context._expected.keys())
        self.assertTrue(all(self.context._expected[k] is v for k, v in original.items()))

    def test_failed_check_does_not_rebaseline(self):
        with mock.patch.object(thermal, 'guard_sample', alternative):
            for _ in range(2): self.check(False)
        self.check(True)

    def test_verification_is_safe_for_concurrent_readers(self):
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: self.context.verify(), range(12)))
        self.assertEqual(results, [None]*12)
        self.check(True)

    def test_no_op_verifier_replacement_is_refused(self):
        with mock.patch.object(reuse, '_verify_callable_inventory', lambda *args: None): self.check(False)

    def test_module_qualified_name_change_is_refused(self):
        with mock.patch.object(reuse, '__name__', 'atlas_tectonics.changed'):
            self.check(False)

    def test_removed_constant_is_refused(self):
        old = thermal.GUARD_TUPLE
        try:
            del thermal.GUARD_TUPLE; self.check(False)
        finally: thermal.GUARD_TUPLE = old

    def test_verifier_code_change_is_refused(self):
        fn = reuse._verify_callable_inventory
        old = fn.__code__
        try:
            fn.__code__ = (lambda *args: None).__code__; self.check(False)
        finally: fn.__code__ = old


class VerificationLifecycleTests(unittest.TestCase):
    def test_full_capture_not_repeated_on_normal_verify(self):
        with mock.patch.object(reuse, '_callable_inventory', wraps=reuse._callable_inventory) as spy:
            with reuse.ExecutionContext() as context:
                count = spy.call_count
                for _ in range(4): context.verify()
                self.assertEqual(count, spy.call_count)
                self.assertEqual(count, 1)

    def test_source_reader_still_called_on_every_verify(self):
        with mock.patch.object(reuse, '_source_bytes', wraps=reuse._source_bytes) as spy:
            with reuse.ExecutionContext() as context:
                count = spy.call_count
                for _ in range(4): context.verify()
                self.assertEqual(spy.call_count-count, 4)

    def test_duplicate_capture_retains_full_legacy_checks(self):
        cls = type('Duplicate', (), {'__module__':thermal.__name__, 'call':sample})
        with mock.patch.object(thermal, 'Duplicate', cls, create=True), mock.patch.object(thermal, 'Duplicate.call', sample, create=True):
            with reuse.ExecutionContext() as context:
                self.assertIsNone(context._expected)
                legacy_verify(context); context.verify()
                with mock.patch.object(cls, 'call', alternative):
                    for fn in (legacy_verify, lambda c:c.verify()):
                        with self.assertRaises(TectonicsError): fn(context)

    def test_actual_source_content_same_size_and_mtime(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'unit.py'; path.write_bytes(b'x = 1\n'); stamp = path.stat()
            with mock.patch.object(reuse, '__file__', str(Path(temp)/'reuse.py')):
                with reuse.ExecutionContext() as context:
                    try:
                        path.write_bytes(b'x = 2\n'); os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                        for fn in (legacy_verify, lambda c:c.verify()):
                            with self.assertRaises(TectonicsError): fn(context)
                    finally: path.write_bytes(b'x = 1\n')

    def test_actual_source_membership_add_remove_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'unit.py'; path.write_bytes(b'x = 1\n')
            extra = Path(temp)/'extra.py'
            with mock.patch.object(reuse, '__file__', str(Path(temp)/'reuse.py')):
                with reuse.ExecutionContext() as context:
                    for mode in ('add', 'remove', 'symlink'):
                        try:
                            if mode=='add': extra.write_bytes(b'')
                            elif mode=='remove': path.unlink()
                            else: extra.symlink_to(path)
                            for fn in (legacy_verify, lambda c:c.verify()):
                                with self.assertRaises(TectonicsError): fn(context)
                        finally:
                            extra.unlink(missing_ok=True)
                            if not path.exists(): path.write_bytes(b'x = 1\n')
                    context.verify()

    def test_closed_context_rejects_and_close_is_idempotent(self):
        context = reuse.ExecutionContext(); context.close(); context.close()
        for fn in (legacy_verify, lambda c:c.verify()):
            with self.assertRaises(TectonicsError): fn(context)

    def test_all_backends_match_oracle(self):
        for backend in ('reference', 'scipy', 'numba'):
            with self.subTest(backend=backend), reuse.ExecutionContext(backend) as context:
                legacy_verify(context); context.verify()
                self.assertEqual(context.identity, reuse.execution_identity(backend))

    def test_identity_matches_independent_full_inventory_reconstruction(self):
        import marshal
        with reuse.ExecutionContext('numba') as context:
            signatures, _, constants = reuse._callable_inventory('numba')
            loaded = {key: {"code": reuse._digest(marshal.dumps(reuse._normal_code(code), 2)),
                            "defaults": reuse._digest(reuse._json(defaults))}
                      for key, (code, defaults) in signatures.items()}
            identity = reuse._digest(reuse._json({"schema": "atlas.kernel-execution.v3",
                "code_marshal_format": 2, "backend": 'numba',
                "sources": {k:reuse._digest(v) for k,v in reuse._source_bytes().items()},
                "loaded_code": loaded, "constants": reuse._digest(constants),
                "runtime": context._runtime}))
            self.assertEqual(context.identity, identity)

    def test_close_failure_still_closes_context(self):
        context = reuse.ExecutionContext()
        with mock.patch.object(thermal, 'half_space_temperature', alternative):
            with self.assertRaises(TectonicsError): context.close()
        self.assertTrue(context._closed)
        context.close()
        with self.assertRaises(TectonicsError): context.verify()

    def test_real_native_options_checked_each_time(self):
        from atlas_tectonics import _mechanics_native
        fn = _mechanics_native.stress_saddle
        with reuse.ExecutionContext('numba') as context:
            old = fn.targetoptions['fastmath']
            try:
                fn.targetoptions['fastmath'] = not old
                for verifier in (legacy_verify, lambda c:c.verify()):
                    with self.assertRaises(TectonicsError): verifier(context)
            finally: fn.targetoptions['fastmath'] = old
