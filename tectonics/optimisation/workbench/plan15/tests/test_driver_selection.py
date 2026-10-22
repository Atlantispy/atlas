"""Focused, isolated driver behaviour checks; execution requires exact GO.

Only the selected source's two changed functions and their refusal class are
compiled. Fakes stop admission before any execution context or fixture opens.
The endpoint fixture exercises passive report capture without scientific imports.
"""
import ast
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'source/helpers/fresh_interval_driver.py'
PIN = '9103629802281dd55d4f0d1541eaaf9fa369e841fdc0fef0b87db0ce19b39640'


def source_bytes(expected=PIN):
    raw = SOURCE.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError('SOURCE_IDENTITY: selected driver bytes differ')
    return raw


def isolated(raw):
    tree = ast.parse(raw)
    names = {'FreshIntervalRefused', '_require', '_admission', '_completed'}
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    if len(nodes) != len(names):
        raise ValueError('Selected driver seam definitions incomplete')
    namespace = dict(json=json, os=os, asdict=asdict, sha256=sha256,
        preparation_ids=lambda case, owner: dict(prepared=True))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


class StopBeforeContext(Exception):
    pass


def admission_trace(namespace, *, initial_workers=0, configure_error=False):
    trace = []

    def configure(**kwargs):
        trace.append(('configure', kwargs))
        if configure_error:
            raise RuntimeError('configuration refused')

    def context(name):
        trace.append(('context', name))
        raise StopBeforeContext()

    module = NS(J=NS(I=NS(F=NS(FUNCTIONS=NS(PARALLEL=NS(configure=configure))))), ExecutionContext=context)
    generator = namespace['_admission'](module, budget=None, artifacts=None,
        phase=lambda name: trace.append(('phase', name)), initial_workers=initial_workers)
    try:
        next(generator)
    except StopBeforeContext:
        pass
    return trace


@dataclass
class Metadata:
    fixture: bool = True


class Temperatures:
    size = 2

    def min(self):
        return 2

    def max(self):
        return 3

    def tobytes(self):
        return b'fixture-temperature-bytes'


def completed_fixture(namespace, *, report_error=False):
    trace, record = [], {}
    expected_report = dict(workers=8, totals=dict(calls=2), calls=[dict(workers=8)], fallbacks=[])

    def report():
        trace.append('report')
        if report_error:
            raise RuntimeError('report refused')
        return expected_report

    module = NS(J=NS(I=NS(F=NS(FUNCTIONS=NS(PARALLEL=NS(report=report))))),
        D=NS(snapshots=lambda value: 'snapshot', arrays=lambda value: 'arrays'))
    store = NS(limits=Metadata(), compression=Metadata(), metadata=lambda key: dict(key=key))
    workflow = NS(_store=store, _root=json.dumps(dict(key='root')), workflow_id='workflow',
        _head=dict(key='head', sequence=1))
    admission = NS(case={}, owner=None, heat_execution=NS(provenance='execution'))
    native_state = NS(result_id='native')
    result = NS(collar=NS(source_stage=NS(source_audit=NS(result_id='audit'))),
        state=NS(result_id='collar', native_state=native_state, fields='fields', arrays=lambda: []),
        exterior=NS(state=NS(state_id='exterior', _snapshot='snapshot'),
            _heat=NS(result_id='heat', _result=NS(array=lambda name: Temperatures())), audit_arrays=lambda: []))
    callback = namespace['_completed'](module, admission, workflow, record,
        lambda name: trace.append(name))
    return callback, result, record, trace, expected_report


def require_eight_worker_admission(namespace):
    trace = admission_trace(namespace)
    expected = [('phase', 'begin-fresh-native-admission'), ('configure', dict(workers=8)), ('context', 'reference')]
    if trace != expected:
        raise AssertionError('selected heat workers must be configured before any context opens')


def require_completed_report(namespace):
    callback, result, record, trace, expected = completed_fixture(namespace)
    callback(result)
    if record.get('heat_first_pass') != expected:
        raise AssertionError('first interval must retain the passive heat report')
    if trace != ['report', 'actual-heat-endpoint-committed']:
        raise AssertionError('completion marker must follow report capture')
    if record['completed_endpoint']['native_result_id'] != 'native':
        raise AssertionError('existing endpoint identity changed')
    if record['public_temperature_k']['array_sha256'] != sha256(Temperatures().tobytes()).hexdigest():
        raise AssertionError('existing temperature identity changed')


class DriverSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = source_bytes()
        cls.namespace = isolated(cls.raw)

    def test_configure_precedes_context_for_reader_and_producer(self):
        require_eight_worker_admission(self.namespace)
        self.assertEqual(admission_trace(self.namespace, initial_workers=2)[1], ('configure', dict(workers=8)))

    def test_invalid_initial_workers_still_refuse(self):
        with self.assertRaises(self.namespace['FreshIntervalRefused']):
            admission_trace(self.namespace, initial_workers=1)

    def test_configuration_refusal_propagates(self):
        with self.assertRaisesRegex(RuntimeError, 'configuration refused'):
            admission_trace(self.namespace, configure_error=True)

    def test_completed_report_is_passive_and_keeps_endpoint(self):
        require_completed_report(self.namespace)

    def test_report_refusal_does_not_mark_completion(self):
        callback, result, record, trace, _ = completed_fixture(self.namespace, report_error=True)
        with self.assertRaisesRegex(RuntimeError, 'report refused'):
            callback(result)
        self.assertEqual(trace, ['report'])
        self.assertNotIn('heat_first_pass', record)

    def test_wrong_worker_fixture_is_detected(self):
        old, new = b'PARALLEL.configure(workers=8)', b'PARALLEL.configure(workers=7)'
        self.assertEqual(self.raw.count(old), 1)
        with self.assertRaisesRegex(AssertionError, 'selected heat workers'):
            require_eight_worker_admission(isolated(self.raw.replace(old, new)))

    def test_missing_report_fixture_is_detected(self):
        line = b"        record['heat_first_pass'] = m.J.I.F.FUNCTIONS.PARALLEL.report()\n"
        self.assertEqual(self.raw.count(line), 1)
        with self.assertRaisesRegex(AssertionError, 'passive heat report'):
            require_completed_report(isolated(self.raw.replace(line, b'')))


if __name__ == '__main__':
    if sys.argv[1:] == ['--fault-stale-source']:
        try:
            source_bytes('0'*64)
        except ValueError as error:
            print(json.dumps(dict(status='REFUSED', code='SOURCE_IDENTITY', message=str(error),
                candidate_functions_evaluated=False, scientific_calls=0)))
            raise SystemExit(2)
        raise SystemExit('stale source identity unexpectedly accepted')
    unittest.main(verbosity=2)
