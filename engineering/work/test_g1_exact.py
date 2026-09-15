"""Focused exact-geology successor parity, mutation and bounded timing checks."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import unittest
from unittest.mock import patch

from work.generator_upgrade_r18 import accounts as old_accounts, geology as old_geology
from work.generator_upgrade_r18 import replacement as old_replacement, rules as old_rules
from work import test_r18_rules, test_r18_replacement, test_r18_composite
from work.geology_r1 import accounts, composite, geology, replacement, rules


class RetainedRuleTests(test_r18_rules.RuleTests):
    def setUp(self):
        self.guard = patch.object(test_r18_rules, 'rules', rules)
        self.guard.start(); self.addCleanup(self.guard.stop)


class RetainedReplacementTests(test_r18_replacement.ReplacementTests):
    def setUp(self):
        self.guard = patch.object(test_r18_replacement, 'replacement', replacement)
        self.guard.start(); self.addCleanup(self.guard.stop)


class RetainedCompositeTests(test_r18_composite.CompositeTests):
    def setUp(self):
        self.guard = patch.object(test_r18_composite, 'composite', composite)
        self.guard.start(); self.addCleanup(self.guard.stop)


def _expression():
    constant, field = test_r18_rules.constant, test_r18_rules.product
    return {'operation': 'quotient', 'terms': [
        {'operation': 'difference', 'terms': [
            {'operation': 'sum', 'terms': [constant('1/3'), field(2, 'a')]},
            {'operation': 'minimum', 'terms': [field(1, 'b'), constant('1/7')]}]},
        {'operation': 'product', 'terms': [constant(3), field(1, 'c')]}]}


def _layers():
    return [dict(compartment_id='root', thickness_m='6', weights={'A': '1/2', 'GT': '1/2'}),
            dict(compartment_id='cover', thickness_m='4', weights={'C': '1'})]


def _replacement_work(new=False, supports=13):
    answer = []
    for _ in range(supports):
        layers, history = _layers(), []
        for depth in (3, 7, 0, 10, 8, 1, 0, 5, 10, 3, 7):
            method = replacement._replace if new else old_replacement.replace
            layers, transfers = method(layers, depth, {'X': '1/2', 'Y': '1/2'}, protected_units=('GT',))
            history.append(replacement._plain_transfers(transfers) if new else transfers)
        answer.append((replacement._plain_layers(layers) if new else layers, history))
    return answer


def _account_fixture():
    descriptor = composite.create(test_r18_composite.constituents(), '1/10',
        phase='bedrock', evidence='SYNTHETIC TEST exact accounting')
    mid = descriptor['material_id']
    density = F(descriptor['grain_density_kg_m3'])
    rows = []
    for _ in range(13):
        row = {'material_id': mid}
        for _, mass_key, solid_key, _ in accounts.CONSTRUCTION_STAGES:
            mass = F(110) if mass_key in ('external_import_mass_kg', 'final_mass_kg') else F(0)
            row[mass_key], row[solid_key] = str(mass), str(mass/density)
        rows.append(row)
    return rows, {mid: descriptor}


def _programme():
    constant, field = test_r18_rules.constant, test_r18_rules.product
    return {'field_ranges': {'a': ['0', '1'], 's': ['0', '1']},
        'derived_fields': [{'name': 'height', 'expression': field(10, 'a')}],
        'stages': [
            {'stage_id': 'root', 'kind': 'emplace', 'thickness_m': constant(6),
             'weights': {'A': constant('1/2'), 'GT': constant('1/2')}},
            {'stage_id': 'cover', 'kind': 'emplace', 'thickness_m': field(1, 'height'),
             'weights': {'C': constant(1)}},
            {'stage_id': 'replace', 'kind': 'replace', 'depth_m': constant(3),
             'supports': {'A': constant('1/2')}, 'protected_units': ['GT']},
            {'stage_id': 'none', 'kind': 'replace', 'depth_m': constant(0),
             'supports': {'C': constant('1/2')}}],
        'base_m': constant(-20), 'translation_m': field(2, 'a'),
        'mechanical_overlay': {'unit_id': 'S', 'field': 's', 'eligible_units': ['A'],
                               'target_k_per_year': '1/50'},
        'evidence': 'SYNTHETIC TEST finite geology exact parity'}


class PreparedTests(unittest.TestCase):
    def test_prepared_formula_detached_immutable_and_runtime_guards(self):
        source = _expression(); unchanged = deepcopy(source)
        prepared = rules.prepare(source)
        for samples in ({'a': '1/2', 'b': '1/5', 'c': '2/3'},
                        {'a': .375, 'b': .8, 'c': .125}):
            self.assertEqual(rules.evaluate(prepared, samples), old_rules.evaluate(source, samples))
        self.assertEqual(rules.referenced_fields(prepared), old_rules.referenced_fields(source))
        source.clear()
        self.assertEqual(rules.evaluate(prepared, {'a': '1/2', 'b': '1/5', 'c': '2/3'}), F(25, 42))
        with self.assertRaises(FrozenInstanceError):
            prepared.root = ()
        for samples in ({}, {'a': 1, 'b': 1, 'c': 0}, {'a': True, 'b': 1, 'c': 1},
                        {'a': 1 << 8192, 'b': 1, 'c': 1}):
            with self.subTest(samples=list(samples)), self.assertRaises(ValueError):
                rules.evaluate(prepared, samples)
        zero = rules.prepare(test_r18_rules.product(0, 'missing'))
        with self.assertRaisesRegex(ValueError, 'missing formula field'):
            rules.evaluate(zero, {})
        self.assertNotEqual(source, unchanged)

    def test_replacement_exact_chain_and_noop_validation_parity(self):
        self.assertEqual(_replacement_work(False, 1), _replacement_work(True, 1))
        bad = _layers(); bad[0]['weights']['A'] = '1/3'
        for depth, coverage in ((0, None), (100, 0)):
            with self.assertRaisesRegex(ValueError, 'sum exactly'):
                replacement.replace(bad, depth, {'X': 0}, coverage=coverage)
        layers = _layers(); exact, _ = replacement._replace(layers, 0, {'X': 1})
        exact[0]['weights']['A'] = 0
        self.assertEqual(layers, _layers())

    def test_full_descriptor_reuse_accounts_and_metadata_mutation(self):
        rows, palette = _account_fixture(); original = deepcopy(palette)
        self.assertEqual(accounts.project_balances(rows, palette, accounts.CONSTRUCTION_STAGES),
                         old_accounts.project_balances(rows, palette, accounts.CONSTRUCTION_STAGES))
        mid = next(iter(palette)); prepared = composite._prepare_palette(palette)
        palette[mid]['evidence'] = 'SYNTHETIC TEST different evidence, same material ID'
        self.assertEqual(palette[mid]['material_id'], mid)
        with self.assertRaisesRegex(ValueError, 'changed during operation'):
            composite._check_palette(palette, prepared)
        self.assertEqual(composite.project_mass(mid, 110, prepared),
                         composite.project_mass(mid, 110, original))
        palette = deepcopy(original)
        palette[mid]['omitted_zero_weight_unit_ids'].append('A')
        with self.assertRaisesRegex(ValueError, 'duplicate omitted'):
            accounts.project_balances(rows, palette, accounts.CONSTRUCTION_STAGES)
        palette = deepcopy(original)
        palette[mid]['constituents'][0]['mass_fraction'] = '1/2'
        with self.assertRaisesRegex(ValueError, 'descriptor or identity changed'):
            accounts.project_balances(rows, palette, accounts.CONSTRUCTION_STAGES)

    def test_prepared_programme_exact_output_detachment_and_ranges(self):
        plan = _programme(); prepared = geology.prepare(plan)
        samples = {'west': {'a': '1/2', 's': '1/3'}, 'east': {'a': 0, 's': 0}}
        supports = {key: {'xy_m': [index, 0], 'area_m2': '3/2'} for index, key in enumerate(samples)}
        materials = {unit: {'grain_density_kg_m3': 2700+index, 'porosity': '1/20',
            'k_per_year': '1/10', 'phase': 'bedrock'} for index, unit in enumerate(('A', 'GT', 'C'))}
        for mix in ('arithmetic', 'harmonic'):
            old = old_geology.interpret(samples, supports, plan, materials, k_mixing=mix)
            new = geology.interpret(samples, supports, prepared, materials, k_mixing=mix)
            self.assertEqual(json.dumps(old), json.dumps(new))
        plan['stages'][0]['thickness_m']['value'] = 900
        self.assertEqual(geology.interpret(samples, supports, prepared, materials),
                         geology.interpret(samples, supports, geology.prepare(_programme()), materials))
        with self.assertRaises(TypeError):
            prepared.data['stages'][0]['kind'] = 'other'
        bad = deepcopy(samples); bad['west']['a'] = 2
        with self.assertRaisesRegex(ValueError, 'outside owner physical range'):
            geology.interpret(bad, supports, prepared, materials)


def measure(output):
    """Three alternating pairs; isolated synthetic workloads, not end-to-end."""
    source_root = Path(__file__).resolve().parent
    files = [source_root/'geology_r1'/name for name in
             ('rules.py', 'replacement.py', 'composite.py', 'accounts.py', 'geology.py',
              'programme.py', 'model.py', 'consumer.py')]
    files += [source_root/'generator_upgrade_r18'/name.name for name in files[:]]
    pins = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    rows, palette = _account_fixture()
    expression = _expression(); samples = {'a': '1/2', 'b': '1/5', 'c': '2/3'}

    def exact_work(new):
        replacement_result = _replacement_work(new)
        method = accounts.project_balances if new else old_accounts.project_balances
        account_result = method(rows, palette, accounts.CONSTRUCTION_STAGES)
        return replacement_result, account_result

    def formula_work(new):
        method = rules.evaluate if new else old_rules.evaluate
        # Include one preparation per workload, then the measured native-profile
        # evaluation count. Neither old nor new skips runtime arithmetic checks.
        expr = rules.prepare(expression) if new else expression
        return [method(expr, samples) for _ in range(769)]

    report = {'schema': 'diadem.geology-exact-optimisation-measurement.r1',
              'scope': 'ISOLATED_SYNTHETIC_WORKLOADS_NOT_FULL_CATEGORY_OR_WORLD',
              'sources': pins, 'checks': {}, 'timings': {}}
    for name, method in (('candidate4_exact_material_and_replacement', exact_work),
                         ('candidate5_prepared_rules', formula_work)):
        assert method(False) == method(True), name
        before, after = [], []
        for pair in range(3):
            for new in ((False, True) if pair % 2 == 0 else (True, False)):
                started = time.perf_counter(); method(new)
                (after if new else before).append(time.perf_counter()-started)
        b, a = statistics.median(before), statistics.median(after)
        report['checks'][name] = 'EXACT_PARITY_PASS'
        report['timings'][name] = {'before_raw_seconds': before, 'after_raw_seconds': after,
            'before_median_seconds': b, 'after_median_seconds': a,
            'saved_seconds': b-a, 'saved_percent': 100*(b-a)/b}
    report['workloads'] = {'candidate4': '13 supports x11 finite replacements plus13 rows x4 account stages',
                           'candidate5': '769 nested exact formula evaluations; includes one preparation'}
    assert pins == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'path': str(target), 'timings': report['timings']}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--measure':
        measure(sys.argv[2])
    else:
        unittest.main()
