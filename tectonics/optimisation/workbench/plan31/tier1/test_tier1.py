"""Bounded controls on the actual public transformation and generated query code."""
import ast
from contextlib import contextmanager
import copy
from pathlib import Path
import sys
import types
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(HERE))
import build_candidate as B  # noqa: E402


def query_scope(raw):
    names = {'QUERY_STAGE_FIELDS', 'QUERY_SPLIT_FIELDS', 'QUERY_STORES',
             'QueryStages', 'completed_queries'}
    nodes = [n for n in ast.parse(raw).body if getattr(n, 'name', None) in names or
             isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in names for t in n.targets)]
    def require(ok, reason):
        if not ok:
            raise ValueError(reason)
    scope = dict(require=require, contextmanager=contextmanager, sys=sys)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<generated query code>', 'exec'), scope)
    return scope


def owner():
    return types.SimpleNamespace(hits=0, misses=0, written=0, incomplete=0,
        hits_restart=0, hits_after_write=0, hits_warm=0, split_status='COMPLETE', entries_at_open=0)


class Tier1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, utilities, cls.mapping, cls.tier, cls.prerequisite = B.load(REPO)
        cls.raws = {row['member']: utilities.read_source(REPO, row['public_base'])
                    for row in cls.mapping['rows']}
        cls.outputs = B.derive(cls.raws, cls.mapping, cls.tier, cls.prerequisite)

    def scenario(self, statuses, separate=False):
        for member in B.MEMBERS[1:]:
            with self.subTest(member=member):
                record = {'stage': 'advance'}
                stages = query_scope(self.outputs[member])['QueryStages'](record)
                for index, status in enumerate(statuses):
                    if separate and index:
                        record['stage'] = 'seal'
                        stages.observe()
                    value = owner()
                    stages.opened(value)
                    value.hits = 5
                    value.hits_restart = 2 if status == 'TRUNCATED' else 5
                    value.split_status = status
                    stages.closed(value)
                stages.finish()
                rows = record['completed_queries_by_stage']['rows']
                self.assertEqual([r['split_status'] for r in rows], statuses if separate else
                                 ['TRUNCATED' if 'TRUNCATED' in statuses else 'COMPLETE'])
                self.assertEqual(sum(r['hits'] for r in rows), 5 * len(statuses))
                self.assertEqual(sum(r['hits_restart'] for r in rows),
                                 sum(2 if s == 'TRUNCATED' else 5 for s in statuses))

    def test_truncated_then_complete(self):
        self.scenario(['TRUNCATED', 'COMPLETE'])

    def test_complete_then_truncated(self):
        self.scenario(['COMPLETE', 'TRUNCATED'])

    def test_complete_reopens(self):
        self.scenario(['COMPLETE', 'COMPLETE'])

    def test_separate_stage_completeness(self):
        self.scenario(['TRUNCATED', 'COMPLETE'], separate=True)

    def test_flush_precedes_recording_after_workload_failure(self):
        class FakeOwner:
            def __init__(self, *args, **kwargs):
                self.__dict__.update(owner().__dict__)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def flush(self):
                self.hits = self.hits_restart = 5
                self.split_status = 'TRUNCATED'
        for member in B.MEMBERS[1:]:
            with self.subTest(member=member):
                scope = query_scope(self.outputs[member])
                record = {'stage': 'advance'}
                stages = scope['QueryStages'](record)
                with self.assertRaisesRegex(RuntimeError, 'workload failure'):
                    with scope['completed_queries'](FakeOwner, Path('queries'), declared='files',
                            arguments={}, execution=None, budget=None, cancel=None,
                            limits=dict(max_store_bytes=1, max_entries=1), record=record,
                            save=lambda: None, query_stages=stages):
                        raise RuntimeError('workload failure')
                stages.finish()
                self.assertEqual(record['completed_queries']['hits'], 5)
                self.assertEqual(record['completed_queries_by_stage']['rows'][0]['split_status'], 'TRUNCATED')

    def test_restart_caller_is_wired_and_profile_is_preserved(self):
        old = ast.parse(self.raws[B.MEMBERS[2]])
        new = ast.parse(self.outputs[B.MEMBERS[2]])
        def assignment(tree, name):
            return next(ast.dump(n, include_attributes=False) for n in tree.body
                        if isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == name for t in n.targets))
        self.assertEqual(assignment(old, 'PROFILE_SCHEMA'), assignment(new, 'PROFILE_SCHEMA'))
        run = next(n for n in new.body if getattr(n, 'name', None) == 'run_prepared_restart')
        calls = [n for n in ast.walk(run) if isinstance(n, ast.Call)]
        wrapped = [n for n in calls if getattr(n.func, 'id', None) == 'completed_queries']
        self.assertEqual(len(wrapped), 1)
        self.assertEqual(next(ast.unparse(k.value) for k in wrapped[0].keywords if k.arg == 'query_stages'),
                         'query_stages')
        self.assertFalse(any(getattr(n.func, 'id', None) == 'EndpointCheckpoints' for n in calls))
        work = next(n for n in new.body if getattr(n, 'name', None) == '_workload')
        operations = {(ast.unparse(n.func)) for n in ast.walk(work) if isinstance(n, ast.Call)}
        self.assertTrue({'QueryStages', 'query_stages.observe', 'query_stages.finish'} <= operations)

    def test_input_drift_refuses(self):
        raws = dict(self.raws)
        raws[B.MEMBERS[1]] += b'\n'
        with self.assertRaisesRegex(ValueError, 'Pinned source changed'):
            B.derive(raws, self.mapping, self.tier, self.prerequisite)

    def test_wrong_output_pin_refuses(self):
        mapping = copy.deepcopy(self.mapping)
        mapping['rows'][1]['public_output_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Pinned source changed'):
            B.derive(self.raws, mapping, self.tier, self.prerequisite)

    def test_missing_input_refuses(self):
        with self.assertRaisesRegex(ValueError, 'Exactly the three'):
            B.derive({}, self.mapping, self.tier, self.prerequisite)

    def test_second_application_refuses(self):
        with self.assertRaisesRegex(ValueError, 'Pinned source changed'):
            B.derive(self.outputs, self.mapping, self.tier, self.prerequisite)


if __name__ == '__main__':
    unittest.main()
