"""Tiny actual funding owners and exact optional pressure/caller source seams.

Archived operands are explicitly synthetic. Pressure tests exercise the real
entry points up to their unchanged physical refusals; no pressure solve or
scientific acceptance is claimed. No actual checkpoint or store is opened.
"""
import ast
from fractions import Fraction as Q
import gc
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import funding_transfer as X
import native_transfer as N
import spatial_transfer as S
import test_native_transfer as TN
import test_spatial_transfer as TS


HERE = Path(__file__).resolve().parent
CONTROL = TN.HEAT_TESTS/'i04_differential_continuation_control.py'
_temporary = None
_old_path = None


def setUpModule():
    global _temporary, _old_path, P, D, ForcePlan, RadialDatum, PressureRefused
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('clean process required; never replace a loaded runtime')
    _temporary = tempfile.TemporaryDirectory(prefix='funding-transfer-fixture-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(TN.BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, patch in (('regional_execution.py', N.retained_snapshot_source),
                        ('integration_spatial_owner.py', S.spatial_owner_source),
                        ('integration_differential_pressure.py', X.pressure_source)):
        path = package/name
        path.write_text(patch(path.read_text(encoding='utf8')), encoding='utf8')
    integration = HERE.parent/'runtime-integration-r1'
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(integration/'ram'), str(integration/'helpers'),
                   str(TN.HEAT_TESTS.parents[2]), str(TN.HEAT_TESTS)]
    TS.F = importlib.import_module('test_i04_regional_owner')
    TS.C = importlib.import_module('atlas_tectonics.regional_collar3d')
    TS.P = importlib.import_module('atlas_tectonics.integration_spatial_owner')
    TS.Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    TS.WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    TS.Registry = importlib.import_module('atlas_tectonics.integration_regional_inventory').ComponentRegistry
    TS.enc = importlib.import_module('atlas_tectonics.integration_mimetic_heat')._enc
    TS.TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError
    P = importlib.import_module('atlas_tectonics.integration_differential_pressure')
    D = importlib.import_module('atlas_tectonics.integration_differential_geometry')
    ForcePlan = importlib.import_module('atlas_tectonics.regional_execution3d').PreparedRegionalStokes3D
    RadialDatum = importlib.import_module('atlas_tectonics.integration_radial_pressure').RadialDatum
    PressureRefused = importlib.import_module('atlas_tectonics.integration_pressure_coupling').PressureCouplingRefused


def tearDownModule():
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == HERE
        _temporary.cleanup()


class FundingTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TS.SpatialTransferTests.setUpClass()
        cls.budget = TS.SpatialTransferTests.budget

    @classmethod
    def tearDownClass(cls):
        TS.SpatialTransferTests.tearDownClass()
        TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
        TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
        gc.collect()
        if cls.budget.reserved_bytes:
            raise AssertionError(cls.budget.statistics())

    def setUp(self):
        self.fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
        self.fixture.setUp()
        with S.admit_migrated_spatial_owner(**self.fixture.args) as lease:
            self.spatial = lease.adopt()
        self.collar = self.fixture.collar
        self.baseline = self.budget.reserved_bytes

    def tearDown(self):
        self.spatial.owner.close()
        self.spatial = self.collar = None
        gc.collect()
        self.fixture.tearDown()
        self.fixture = None

    def bind(self, spatial=None):
        return X.bind_original_funding(self.spatial if spatial is None else spatial,
                                       collar=self.collar, budget=self.budget)

    def matches(self, token, **changes):
        values = dict(record=self.spatial.funding.descriptor(), funding=self.spatial.funding,
            collar=self.collar, budget=self.budget, transfer=token)
        return X.funding_binding_matches(**dict(values, **changes))

    def test_original_funding_identity_and_actual_owner_are_bound_without_debit(self):
        original = self.spatial.funding.descriptor()
        token = self.bind()
        self.assertNotEqual(original['collar_plan_id'], self.collar.plan_id)
        self.assertTrue(self.matches(token))
        self.assertTrue(self.matches(token, state=self.fixture.native_owned.state, spatial_state=self.spatial.state))
        self.assertEqual(self.spatial.funding.descriptor(), original)
        proof = token.record()
        self.assertEqual(proof['funding_binding']['debit_count'], 1)
        self.assertEqual(proof['funding_debits_applied'], 0)
        self.assertFalse(proof['scientific_acceptance'])
        self.assertEqual(proof['spatial_transfer_id'], self.spatial.transfer_id)
        self.assertEqual(proof['native_transfer_id'], self.fixture.native_owned.transfer_id)
        self.assertEqual(self.budget.reserved_bytes-self.baseline, len(token._record)+4096)
        with self.assertRaises(X.FundingTransferRefused):
            token._spatial = None
        escaped = token._record
        del token
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes-self.baseline, len(escaped)+4096)
        del escaped
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_wrong_source_funding_proof_and_current_state_are_refused(self):
        token = self.bind()
        for invalid in (None, object(), {'funding_id': self.spatial.funding.funding_id}):
            self.assertFalse(self.matches(invalid))
        for key, value in (('funding_id', '0'*64), ('source', {'fixture': 'wrong'}),
                           ('collar_plan_id', '1'*64), ('time_s', 999.)):
            self.assertFalse(self.matches(token, record=dict(self.spatial.funding.descriptor(), **{key: value})))
        self.assertFalse(self.matches(token, budget=TS.WorkBudget(1 << 20)))
        with self.assertRaises(X.FundingTransferRefused):
            self.matches(token, state=self.fixture.native_owned.state)
        with self.assertRaises(X.FundingTransferRefused):
            self.matches(token, state=self.fixture.native_owned.state, spatial_state=object())
        # Inconsistent NEGATIVE provenance fixture, never changed live identities.
        record = self.spatial.record()
        record['funding_binding']['debit_count'] = 2
        fake = S.OwnedMigratedSpatial(self.spatial.owner, self.spatial.state, self.spatial.funding,
                                     self.fixture.native_owned, N._json(record))
        with self.assertRaises(X.FundingTransferRefused):
            self.bind(fake)
        del fake, token

    def test_real_pressure_entries_use_bridge_but_keep_unrelated_physical_guards(self):
        native = self.collar._native
        token = self.bind()
        with ForcePlan(native.cells, native.lengths_m, native._cs.viscosity_pa_s, native._pattern,
                scales=native._ms, reference_viscosity_pa_s=native._cs.viscosity_pa_s,
                frame_id=native._frame, vertical_datum=native._datum, material_source=native.plan_id,
                method='direct', physical_mean_pressure_pa=None, budget=self.budget,
                **native._pressure_reference_args) as force_plan:
            # This actual fixture has no radial/open-base constitutive contract.
            # Compatibility must not override that independent physical guard.
            with mock.patch.object(X, 'funding_binding_matches', wraps=X.funding_binding_matches) as called:
                with self.assertRaisesRegex(PressureRefused, 'open-base mechanical geometry'):
                    P.prescribe_reservoir_pressure(self.spatial.funding, self.collar, force_plan,
                        pressure_at_origin_pa=Q(5), gradient_pa_m=(0, 0, 0), origin_world_m=(0, 0, 0),
                        source='fixture: explicit 5 Pa; not acceptance', budget=self.budget,
                        _runtime_funding_transfer=token)
                self.assertEqual(called.call_count, 1)
                self.assertIs(called.call_args.args[4], token)
            # Exercise the actual patched helper with the live state pair.
            # The complete forcing entry below must refuse this regional-only
            # fixture's incomplete global coverage BEFORE reaching that helper.
            self.assertTrue(P._transferred_funding_binding(self.spatial.funding.descriptor(),
                self.spatial.funding, self.collar, self.budget, token,
                state=self.fixture.native_owned.state, spatial_state=self.spatial.state))
            # Tiny issued SYNTHETIC geometry/pressure for that negative entry
            # test, never a geometrical or pressure-acceptance certificate.
            sphere, moving = self.fixture.source[:2]
            current = D._issue(D.CurrentGeometry, dict(schema='fixture:synthetic-current',
                network_id=sphere.network.network_id, time_s=TS.enc(Q(25, 2))), self.budget)
            pressure = P._issue(P.ReservoirPressure, dict(funding_id=self.spatial.funding.funding_id,
                collar_plan_id=self.collar.plan_id, native_plan_id=force_plan.plan_id,
                volume_map_id=self.spatial.funding.descriptor()['volume_map_id']), {}, self.budget)
            datum = RadialDatum(10., 1., 1., 7., 1.1, 0., 'fixture: synthetic datum')
            with mock.patch.object(X, 'funding_binding_matches', wraps=X.funding_binding_matches) as called:
                with self.assertRaisesRegex(PressureRefused, 'global current pressure requires all real source layers'):
                    P.differential_pressure_forcing(sphere, sphere.network, current, self.spatial.funding,
                        self.collar, self.fixture.native_owned.state, self.spatial.state, force_plan, datum, pressure,
                        source_moving=moving, exterior_parent_state_id='fixture: original force parent',
                        max_torque_width_n_m=Q(1, 4), max_operator_error=Q(1, 100), max_leaves=1,
                        budget=self.budget, _runtime_funding_transfer=token)
                self.assertEqual(called.call_count, 0)
            del current, pressure
        del token


class SourceSeamTests(unittest.TestCase):
    def test_pressure_patch_is_exactly_two_optional_guards(self):
        original = (TN.BASE/'integration_differential_pressure.py').read_text(encoding='utf8')
        modified = X.pressure_source(original)
        compile(modified, 'pressure-funding-transfer', 'exec')
        old, new = ast.parse(original), ast.parse(modified)
        self.assertEqual(new.body.pop().name, '_transferred_funding_binding')
        names, guards = [], 0
        for node in ast.walk(new):
            if isinstance(node, ast.FunctionDef):
                for index, arg in enumerate(node.args.kwonlyargs):
                    if arg.arg == '_runtime_funding_transfer':
                        self.assertIsNone(node.args.kw_defaults[index].value)
                        del node.args.kwonlyargs[index], node.args.kw_defaults[index]
                        names.append(node.name)
                        break
            if isinstance(node, ast.BoolOp):
                for index, value in enumerate(node.values):
                    if (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not)
                            and isinstance(value.operand, ast.Call)
                            and ast.unparse(value.operand.func) == '_transferred_funding_binding'):
                        self.assertEqual([ast.unparse(a) for a in value.operand.args],
                                         ['f', 'funding', 'collar', 'budget', '_runtime_funding_transfer'])
                        node.values[index] = ast.parse("f['collar_plan_id'] != collar.plan_id", mode='eval').body
                        guards += 1
        self.assertEqual(sorted(names), ['differential_pressure_forcing', 'prescribe_reservoir_pressure'])
        self.assertEqual(guards, 2)
        self.assertEqual(ast.dump(old), ast.dump(new))
        with self.assertRaises(X.FundingTransferRefused):
            X.pressure_source(modified)

    def test_continuation_caller_changes_only_binding_creation_and_two_keywords(self):
        original = CONTROL.read_text(encoding='utf8')
        modified = X.continuation_control_source(original)
        compile(modified, 'continuation-funding-transfer', 'exec')
        old, new = ast.parse(original), ast.parse(modified)
        removed, calls = 0, []
        for node in ast.walk(new):
            if isinstance(node, ast.FunctionDef) and node.name == 'continuation_pressure_force':
                kept = []
                for statement in node.body:
                    if isinstance(statement, ast.ImportFrom) and statement.module == 'funding_transfer':
                        removed += 1
                    elif (isinstance(statement, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == '_funding_transfer' for t in statement.targets)):
                        self.assertEqual(ast.unparse(statement.value), 'for_workflow(workflow)')
                        removed += 1
                    else:
                        kept.append(statement)
                node.body = kept
            if isinstance(node, ast.Call):
                for keyword in list(node.keywords):
                    if keyword.arg == '_runtime_funding_transfer':
                        self.assertEqual(ast.unparse(keyword.value), '_funding_transfer')
                        calls.append(ast.unparse(node.func))
                        node.keywords.remove(keyword)
        self.assertEqual(removed, 2)
        self.assertEqual(sorted(calls), ['P.differential_pressure_forcing', 'P.prescribe_reservoir_pressure'])
        self.assertEqual(ast.dump(old), ast.dump(new))
        with self.assertRaises(X.FundingTransferRefused):
            X.continuation_control_source(modified)


if __name__ == '__main__':
    unittest.main(verbosity=2)
