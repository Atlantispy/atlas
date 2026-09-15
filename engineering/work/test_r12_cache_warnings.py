"""Small warning/receipt tests; no scientific runs or cache policy changes."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from work.generator_runtime_r12 import __main__ as cli, integration, provenance, store


class CacheWarningTests(unittest.TestCase):
    def test_disabled_or_healthy_cache_is_quiet(self):
        for stats in (None, {}, {'hits': 3, 'writes': 4, 'skipped_full': 0, 'skipped_oversize': 0}):
            self.assertEqual(integration.cache_warnings(stats), [])

    def test_one_summary_per_cause_preserves_counts_scope_and_stats(self):
        stats = {'skipped_full': 12, 'skipped_oversize': 3}
        before = deepcopy(stats)
        warnings = integration.cache_warnings(stats)
        self.assertEqual([row['skipped_writes'] for row in warnings], [12, 3])
        self.assertEqual([row['code'] for row in warnings], ['CACHE_CAPACITY', 'CACHE_RECORD_SIZE'])
        self.assertTrue(all(row['scope'] == 'COORDINATOR_STORE_INSTANCE_ONLY' for row in warnings))
        self.assertIn('configured cache capacity', warnings[0]['message'])
        self.assertEqual(stats, before)

    def test_real_capacity_skip_is_reported_without_changing_store_policy(self):
        with tempfile.TemporaryDirectory(prefix='r12-cw-') as directory:
            cache = store.Store(Path(directory) / 'c', 'a' * 64, max_bytes=33)
            cache.put('b' * 64, {'result': 1})
            self.assertIsNone(cache.get('b' * 64))
            self.assertEqual(integration.cache_warnings(cache.stats)[0]['code'], 'CACHE_CAPACITY')
            self.assertEqual(cache.stats['skipped_full'], 1)

    def test_actual_oversize_skip_branch_is_reported(self):
        with tempfile.TemporaryDirectory(prefix='r12-cw-') as directory:
            cache = store.Store(Path(directory) / 'c', 'a' * 64)
            # Exercise the existing skip branch without allocating an 8 MiB test value.
            with patch.object(store, '_encode', side_effect=store._Oversize()):
                cache.put('b' * 64, {'result': 1})
            self.assertEqual(integration.cache_warnings(cache.stats)[0]['code'], 'CACHE_RECORD_SIZE')
            self.assertEqual(cache.stats['skipped_oversize'], 1)

    def test_api_receipt_has_warnings_without_mutating_science(self):
        scientific = {'status': 'EXECUTED', 'values': [1, 2]}
        before = deepcopy(scientific)
        storage = SimpleNamespace(encoded=provenance.encoded, decoded=json.loads)
        bundle = SimpleNamespace(source_sha256=provenance.SCIENCE_SHA, storage=storage,
                                 module=lambda _: SimpleNamespace(run=lambda: None))
        built = {'artifacts': SimpleNamespace(decode_stats={})}
        cache = SimpleNamespace(stats={'skipped_full': 2, 'skipped_oversize': 0})
        with patch.object(provenance, 'execution_identity', return_value={'example': True}), \
                patch.object(provenance, 'verify_execution'), patch.object(integration, 'assemble', return_value=built), \
                patch.object(integration, 'Store', return_value=cache), \
                patch.object(integration.parents, 'reuse', return_value=contextlib.nullcontext()), \
                patch.object(integration, 'adapted', return_value=lambda *a, **k: scientific):
            result = integration.run_workflow({}, bundle=bundle, cache_root=Path(tempfile.gettempdir()) / 'unused')
        self.assertEqual(result['scientific'], before)
        self.assertEqual(result['execution']['cache_warnings'][0]['skipped_writes'], 2)

    def test_cli_emits_and_saves_warnings_without_changing_success(self):
        for warnings in ([], integration.cache_warnings({'skipped_full': 3, 'skipped_oversize': 1})):
            with self.subTest(warnings=bool(warnings)), tempfile.TemporaryDirectory(prefix='r12-cw-') as directory:
                output = Path(directory) / 'result'
                scientific = {'status': 'EXECUTED', 'values': [1, 2]}
                execution = {'elapsed_wall_seconds': 0.1, 'cache_warnings': warnings,
                             'cache_statistics_scope': 'COORDINATOR_STORE_INSTANCE_ONLY'}
                storage = SimpleNamespace(plain_path=Path,
                    write_json=lambda path, value: Path(path).write_text(json.dumps(value), encoding='utf-8'))
                verifier = SimpleNamespace(persist_workflow=Mock(return_value={'saved': True}),
                                           read_workflow=Mock(return_value=scientific))
                bundle = SimpleNamespace(storage=storage, reference=SimpleNamespace(recipe=lambda _: {}),
                                         module=lambda _: verifier)
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(provenance, 'load_science', return_value=bundle), \
                        patch.object(integration, 'run_workflow', return_value={'scientific': scientific, 'execution': execution}), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    cli.main(['--output', str(output)])
                self.assertEqual(json.loads(stdout.getvalue())['status'], 'EXECUTED')
                self.assertEqual(json.loads(stdout.getvalue())['cache_warnings'], warnings)
                self.assertEqual(stderr.getvalue().count('Warning:'), len(warnings))
                self.assertEqual(json.loads((output / 'execution.json').read_text(encoding='utf-8')), execution)
                self.assertEqual(verifier.persist_workflow.call_args.args[2], scientific)
