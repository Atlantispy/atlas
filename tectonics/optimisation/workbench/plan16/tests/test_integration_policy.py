"""Actual candidate-function controls; synthetic receipts, no native workload."""
import ast
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent / 'source/helpers'
spec = importlib.util.spec_from_file_location('interface_worker_selection', CANDIDATE / 'interface_worker_selection.py')
WS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(WS)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    require({node.name for node in body} == set(names), 'actual candidate function coverage')
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class Policy:
    child_bytes = 1 << 29
    ram_reserve_bytes = 2 << 30
    budget_fraction = 0.5
    def __init__(self, workers=2):
        if type(workers) is not int or not 1 <= workers <= 6:
            raise ValueError('workers')


class Policies(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = SimpleNamespace(sha256='p', record=lambda: dict(
            output_directory=str(self.root), store_directory=str(self.root / 'store')))
        self.machine = dict(physical_cores=8, logical_cpus=16, available_bytes=20 << 30, load_percent=0)
        def select_composed(parent, logical_budget_bytes):
            return WS.select(policy_type=Policy, child_baseline_bytes=1 << 28,
                parent_storage_bytes=8192, raw_result_bytes=8 << 20, parent=parent,
                machine=self.machine, logical_budget_bytes=logical_budget_bytes)
        self.selector = SimpleNamespace(PARENT_SELECTION_SCHEMA=WS.PARENT_SELECTION_SCHEMA,
            select_composed=select_composed, policy_from_selection=WS.policy_from_selection)
        def pinned(path, pin, limit):
            raw = path.read_bytes()
            require(len(raw) <= limit and sha256(raw).hexdigest() == pin, 'receipt bytes changed')
            return json.loads(raw)
        self.namespace = functions(CANDIDATE / 'run_fresh_interval.py',
            ('interval_number', 'mode_output', '_pin_sha', 'measured_successor_workers'),
            dict(Path=Path, require=require, MODES=('root', 'interval'), INTERVALS={'root': 0, 'interval': 1},
                 RUN=SimpleNamespace(_sha=lambda pin: pin, pinned_json=pinned, LOGICAL_BYTES=16 << 30),
                 MAX_RECEIPT=1 << 20, RESULT_SCHEMA='result', REVIEW_STATUS='review',
                 SEALED_STATUS={'interval': 'sealed'}))
        self.prepared = functions(CANDIDATE / 'prepared_interval_driver.py', ('selected_ale_policy',),
                                  dict(_require=require))['selected_ale_policy']
        self.receipt = dict(schema='result', mode='interval', interval=1, profile_sha256='p',
            runner_record={'sha256': 'r'}, sealed_awaiting_reader={'sha256': 's'},
            final_reserved_bytes=0, production_acceptance=False, status='sealed', errors=[],
            resources={'sampled_peak_bytes': {'parent_rss': 253 << 20}},
            logical_budget_final={'peak_reserved_bytes': 1 << 30})
        self.lineage = dict(lineage=dict(interval=1, records=[dict(runner_sha256='r', sealed_sha256='s')]),
                            parent_verdict={}, parent_adopted={})

    def write(self):
        path = self.root / 'run-interval/run.json'
        path.parent.mkdir(exist_ok=True)
        raw = json.dumps(self.receipt).encode()
        path.write_bytes(raw)
        self.lineage['parent_verdict']['producer_receipt_sha256'] = sha256(raw).hexdigest()
        return path

    def choose(self):
        self.write()
        return self.namespace['measured_successor_workers'](self.profile, self.lineage, 2, self.selector)

    def test_six_only_from_authenticated_measured_parent(self):
        choice = self.choose()
        self.assertEqual(WS.policy_from_selection(choice), {'mode': 'auto', 'workers': 6})
        self.assertEqual(choice['parent'], dict(real_peak_bytes=253 << 20, logical_peak_bytes=1 << 30))

    def test_default_four_retains_resource_cuts(self):
        self.machine['load_percent'] = 12.5
        choice = self.choose()
        self.assertEqual(choice['decision']['chosen'], 4)
        self.assertFalse(choice['decision']['checks']['six']['cores'])

    def test_changed_parent_bytes_refuse(self):
        path = self.write()
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'receipt bytes changed'):
            self.namespace['measured_successor_workers'](self.profile, self.lineage, 2, self.selector)

    def test_profile_runner_seal_and_missing_measurements_refuse(self):
        original = copy.deepcopy(self.receipt)
        for key, value in (('profile_sha256', 'foreign'), ('runner_record', {'sha256': 'foreign'}),
                           ('sealed_awaiting_reader', {'sha256': 'foreign'}), ('resources', {}),
                           ('logical_budget_final', {}), ('final_reserved_bytes', 1)):
            self.receipt = copy.deepcopy(original)
            self.receipt[key] = value
            with self.assertRaises(ValueError):
                self.choose()

    def test_review_recovery_requires_existing_approval(self):
        self.receipt.update(status='review', errors=[{'type': 'PresealSealedForReview'}],
                            review_only={'state': 'review'})
        with self.assertRaises(ValueError):
            self.choose()
        self.lineage['parent_adopted']['review_approval_sha256'] = 'accepted-by-lineage-gate'
        self.assertEqual(self.choose()['decision']['chosen'], 6)

    def test_serial_and_migrated_routes_unchanged_and_no_ambiguous_override(self):
        serial = {'mode': 'serial', 'workers': 2}
        self.assertEqual(self.prepared(serial, ordinary=True), serial)
        self.assertEqual(self.prepared(None, ordinary=False), {'mode': 'auto', 'workers': 2})
        choice = self.choose()
        with patch.dict(sys.modules, {'interface_worker_selection': WS}):
            self.assertEqual(self.prepared(None, ordinary=True, worker_selection=choice),
                             {'mode': 'auto', 'workers': 6})
            for policy, ordinary in ((serial, True), (None, False)):
                with self.assertRaises(ValueError):
                    self.prepared(policy, ordinary=ordinary, worker_selection=choice)

    def test_forged_six_gate_or_bare_override_refuses(self):
        choice = self.choose()
        choice['decision']['checks']['six']['memory'] = False
        with self.assertRaises(ValueError):
            WS.policy_from_selection(choice)
        with self.assertRaises(ValueError):
            WS.policy_from_selection({'mode': 'auto', 'workers': 6})


if __name__ == '__main__':
    unittest.main()
