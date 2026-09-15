"""Bounded owner-point R18 checks; no full terrain, raster or year execution.

The caller runs these once after the source freeze. Saved class attributes are
available to the verification harness; this module itself writes no artefacts.
"""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r18 import consumer, geology, programme, working as w


def _key(row, column):
    return f'r{row}_c{column}'


def _height(resolved):
    return sum((F(layer['thickness_m']) for layer in resolved['layers']), F())


def _history(interpretation):
    return {row['stage_id']: row for row in interpretation['construction_stages']}


def _geometry(resolved, palette):
    """Exclude composition-bound IDs/K while retaining every physical contact."""
    return (resolved['basal_elevation_m'], resolved['translation_m'], [
        (layer['compartment_id'], layer['thickness_m'],
         palette[layer['material_id']]['constituents'],
         palette[layer['material_id']]['grain_density_kg_m3'],
         palette[layer['material_id']]['porosity'], palette[layer['material_id']]['phase'])
        for layer in resolved['layers']])


class WorkingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = w.inputs()
        cls.results = list(w.iter_cases())
        cls.supports = w.case_supports(cls.spec)
        cls.samples, cls.interpretations = {}, {}
        for result in cls.results:
            details = result['scientific']['regional_input']
            for key, row in details['sampling']['samples'].items():
                if key in cls.samples:
                    raise AssertionError('owner support constructed more than once')
                cls.samples[key] = row
                cls.interpretations[key] = details['interpretations'][key]
        cls.materials = w.materials(cls.spec)
        cls.plan = programme.build(cls.spec)

    def _interpret(self, key, alternative='DEFAULT'):
        plan = programme.build(self.spec, alternative)
        rows, palette = geology.interpret({key: self.samples[key]},
            {key: self.supports[key]}, plan, self.materials,
            k_mixing='harmonic' if alternative == 'HARMONIC_COMPOSITE_K' else 'arithmetic')
        return rows[key], palette

    def _closed(self, rows):
        for row in rows:
            for suffix in ('mass_kg', 'solid_volume_m3'):
                self.assertEqual(F(row['residual_'+suffix]), 0)
                self.assertEqual(F(row['imported_'+suffix])-F(row['exported_'+suffix]),
                                 F(row['final_'+suffix]))

    def test_owner_points_native_stocks_sources_and_controlled_incision(self):
        spec = self.spec
        self.assertEqual(len(self.samples), 39)
        self.assertEqual(set(self.samples), set(self.supports))
        self.assertEqual(len(self.materials), 27)
        self.assertEqual(set(spec['unit_catalogue']), set(self.materials) | {'SV-01'})
        self.assertNotIn('SV-01', self.materials)
        self.assertEqual(set(self.plan['field_ranges']), set(spec['field_inputs']))

        def field(role):
            return spec['verification_cases']['role_fields'].get(
                role, 'affinity_'+role.lower().replace('-', '_'))

        for role, row, column, expected in spec['verification_cases']['maxima']:
            with self.subTest(maximum=role):
                self.assertEqual(F(self.samples[_key(row, column)][field(role)]), F(expected))
        for name, a, b, row, column, av, bv in spec['verification_cases']['transitions']:
            with self.subTest(transition=name):
                self.assertEqual(F(self.samples[_key(row, column)][field(a)]), F(av))
                self.assertEqual(F(self.samples[_key(row, column)][field(b)]), F(bv))
        # Assigned decimal numbers, unlike source float32 samples, are exact
        # decimal quantities, not the binary64 approximation of those literals.
        for row in spec['materials']:
            for name in ('grain_density_kg_m3', 'porosity', 'k_per_year'):
                self.assertEqual(F(self.materials[row['material_id']][name]), F(str(row[name])))
        self.assertEqual(F(self.materials['BX-00']['porosity']), F(1, 50))
        self.assertEqual(F(self.materials['BX-00']['k_per_year']), F(1, 100000))

        represented_units = set()
        for result in self.results:
            science = result['scientific']; details = science['regional_input']
            self.assertEqual(science['source_status'], 'WORKING NON-CANON')
            self.assertEqual(details['retained_source_status'], spec['retained_source_status'])
            self.assertEqual(details['owner_input']['sha256'], w.INPUT_SHA)
            self.assertEqual(science['owner_source']['sha256'], w.CONTRACT_SHA)
            self.assertEqual(result['execution']['scientific_sha256'], w.p.sha(science))
            for flag in ('canon_changed', 'production_authorised', 'whole_diadem_year_verified',
                         'plate_motion_inferred', 'isostasy_solved', 'geology_calibrated'):
                self.assertIs(science[flag], False)
            for flag in ('current_dem_consumed', 'active_terrain_registration_claimed',
                         'hydrology_or_groundwater_connectivity_inferred'):
                self.assertIs(details[flag], False)
            self.assertIs(details['applicability']['crop_is_physical_boundary'], False)
            self.assertIs(details['applicability']['full_terrain_or_year_run'], False)
            self.assertLessEqual(len(science['supports']), geology.batch_limit(self.plan))
            self.assertLessEqual(len(science['construction']['events']), 256)

            actual = {row['unit_id']: row for row in details['geological_constituent_balances']}
            assembled = {row['unit_id']: row for row in details['constituent_balances']}
            self._closed(actual.values())
            for unit in set(actual) | set(assembled):
                for suffix in ('mass_kg', 'solid_volume_m3'):
                    self.assertEqual(F(actual.get(unit, {}).get('final_'+suffix, '0')),
                                     F(assembled.get(unit, {}).get('final_'+suffix, '0')))
            for unit, row in actual.items():
                if F(row['imported_mass_kg']) > 0:
                    represented_units.add(unit)

            for key, interpretation in details['interpretations'].items():
                native = science['stratigraphy'][key]['bottom_to_top']
                history = _history(interpretation)
                self.assertEqual(F(history['root']['thickness_m']), 10000)
                heights = [F(layer['top_m'])-F(layer['bottom_m']) for layer in native]
                self.assertTrue(all(value > 0 for value in heights))
                emplaced = sum((F(row['thickness_m']) for row in history.values()
                                if row['kind'] == 'emplace'), F())
                self.assertEqual(sum(heights, F()), emplaced)
                self.assertEqual(F(native[0]['bottom_m']),
                                 -10000+F(interpretation['derived_fields']['U']))
                self.assertEqual(F(native[0]['bottom_m'])+emplaced,
                                 F(science['stratigraphy'][key]['surface_m']))
                for lower, upper in zip(native, native[1:]):
                    self.assertEqual(lower['top_m'], upper['bottom_m'])
                ids = [row['compartment_id'] for row in interpretation['compartments']]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(interpretation['raw_independent_fields'], self.samples[key])
                overlay = interpretation['mechanical_overlay']
                self.assertEqual(overlay['unit_id'], 'SV-01')
                self.assertEqual(F(overlay['added_volume_m3']), 0)
                self.assertEqual(F(overlay['added_mass_kg']), 0)
                self._closed(interpretation['geological_constituent_balances'])
                # Independent sum directly from native layer mass and bound
                # mass fractions; deposited porosity never enters this formula.
                projected = {}
                for layer in native:
                    descriptor = details['palette'][layer['material_id']]
                    self.assertEqual(F(layer['grain_density_kg_m3']), F(descriptor['grain_density_kg_m3']))
                    bulk = self.supports[key]['area_m2']*(F(layer['top_m'])-F(layer['bottom_m']))
                    self.assertEqual(F(layer['mass_kg']), bulk*F(descriptor['grain_density_kg_m3'])*(1-F(descriptor['porosity'])))
                    for component in descriptor['constituents']:
                        unit = component['unit_id']; self.assertNotEqual(unit, 'SV-01')
                        mass = F(layer['mass_kg'])*F(component['mass_fraction'])
                        stock = projected.setdefault(unit, [F(), F()])
                        stock[0] += mass
                        stock[1] += mass/F(component['grain_density_kg_m3'])
                ledger = {row['unit_id']: row for row in interpretation['geological_constituent_balances']}
                for unit in set(ledger) | set(projected):
                    for index, suffix in enumerate(('mass_kg', 'solid_volume_m3')):
                        self.assertEqual(projected.get(unit, [F(), F()])[index],
                                         F(ledger.get(unit, {}).get('final_'+suffix, '0')))
        self.assertEqual(represented_units, set(self.materials))

        first = self.results[0]
        forcing = {key: {'discharge_m3_year': 1., 'hydraulic_slope': .001,
            'evidence': 'CONTROLLED LOCAL WORKING NON-CANON adapter check; not regional Water forcing or calibration',
            'source_status': 'WORKING NON-CANON'} for key in first['scientific']['supports']}
        result = consumer.incise(first, forcing, '1/1000')
        type(self).erosion_result = result
        self.assertGreater(sum((F(row['eroded_mass_kg']) for row in result['constituent_balances']), F()), 0)
        self.assertEqual(result['r18_input_scientific_sha256'], first['execution']['scientific_sha256'])
        for row in result['constituent_balances']:
            for suffix in ('mass_kg', 'solid_volume_m3'):
                self.assertEqual(F(row['residual_'+suffix]), 0)
                self.assertEqual(F(row['initial_'+suffix])+F(row['deposited_'+suffix])-
                                 F(row['eroded_'+suffix]), F(row['final_'+suffix]))

    def test_alternatives_zero_gate_and_adjoining_batch_continuity(self):
        default = self.plan
        before = programme.build(self.spec, 'BASIN_BEFORE_EARLY_VOLCANIC')
        stages = {row['stage_id']: row for row in default['stages']}
        moved = {row['stage_id']: row for row in before['stages']}
        self.assertEqual(stages, moved)
        old_order = [row['stage_id'] for row in default['stages']]
        new_order = [row['stage_id'] for row in before['stages']]
        expected = [name for name in old_order if name not in ('basin', 'basin_MH')]
        position = expected.index('early_volcanic_core')
        expected[position:position] = ['basin', 'basin_MH']
        self.assertEqual(new_order, expected)
        self.assertEqual(new_order.count('basin'), 1)
        self.assertEqual(new_order.count('basin_MH'), 1)
        self.assertEqual(default['derived_fields'], before['derived_fields'])
        self.assertEqual(default['translation_m'], before['translation_m'])

        def basin_score(key):
            history = _history(self.interpretations[key])
            return F(history['basin']['thickness_m'])*F(history['early_volcanic_cover']['thickness_m'])

        basin_key = max(self.samples, key=basin_score)
        self.assertGreater(basin_score(basin_key), 0, 'actual owner cases must exercise basin/early-volcanic overlap')
        basin_default, _ = self._interpret(basin_key)
        basin_before, _ = self._interpret(basin_key, 'BASIN_BEFORE_EARLY_VOLCANIC')
        self.assertEqual(_height(basin_default), _height(basin_before))
        self.assertEqual(basin_default['translation_m'], basin_before['translation_m'])
        self.assertEqual(basin_before['interpretation']['raw_independent_fields'], self.samples[basin_key])
        self.assertEqual(basin_before['interpretation']['chosen_order'], new_order)
        self._closed(basin_before['interpretation']['geological_constituent_balances'])

        def taper(key):
            raw = self.samples[key]
            vcore = max(F(raw['affinity_'+name]) for name in ('wv_02', 'nv_01', 'sv_02', 'pv_02'))
            return min(F(1), max(F(), (vcore-F(1, 4))/F(1, 2)))

        taper_key = max(self.samples, key=lambda key: taper(key)*F(_history(self.interpretations[key])['carbonate']['thickness_m']))
        base, _ = self._interpret(taper_key)
        tapered, _ = self._interpret(taper_key, 'TAPER_CARBONATE_UNDER_VOLCANIC_CORE')
        base_history, tapered_history = (_history(row['interpretation']) for row in (base, tapered))
        original_carbonate = F(base_history['carbonate']['thickness_m'])
        self.assertGreater(original_carbonate*taper(taper_key), 0)
        self.assertEqual(F(tapered_history['carbonate']['thickness_m']), original_carbonate*(1-taper(taper_key)))
        taper_plan = programme.build(self.spec, 'TAPER_CARBONATE_UNDER_VOLCANIC_CORE')
        for row in taper_plan['stages']:
            if row['stage_id'] == 'carbonate':
                self.assertEqual(row['weights'], stages['carbonate']['weights'])
            else:
                self.assertEqual(row, stages[row['stage_id']])
        for name, history in base_history.items():
            if history['kind'] == 'emplace' and name != 'carbonate':
                self.assertEqual(history['thickness_m'], tapered_history[name]['thickness_m'])
        self.assertEqual(_height(base)-_height(tapered), original_carbonate*taper(taper_key))
        self.assertEqual(base['translation_m'], tapered['translation_m'])
        self.assertEqual(tapered['interpretation']['raw_independent_fields'], self.samples[taper_key])
        self._closed(tapered['interpretation']['geological_constituent_balances'])

        def mixed(key):
            return any(len(set(row['constituent_k_per_year'].values())) > 1
                       for row in self.interpretations[key]['mechanical_overlay']['layers'])

        mixed_key = next(key for key in self.samples if mixed(key))
        arithmetic, ap = self._interpret(mixed_key)
        harmonic, hp = self._interpret(mixed_key, 'HARMONIC_COMPOSITE_K')
        self.assertEqual(_geometry(arithmetic, ap), _geometry(harmonic, hp))
        self.assertEqual(arithmetic['interpretation']['geological_constituent_balances'],
                         harmonic['interpretation']['geological_constituent_balances'])
        modifiers = {row['compartment_id']: row for row in arithmetic['interpretation']['mechanical_overlay']['layers']}
        strict = False
        for a, h in zip(arithmetic['layers'], harmonic['layers']):
            ad, hd = ap[a['material_id']], hp[h['material_id']]
            ak, hk = F(ad['k_per_year']), F(hd['k_per_year'])
            ks = [F(value) for value in modifiers[a['compartment_id']]['constituent_k_per_year'].values()]
            self.assertLessEqual(min(ks), hk)
            self.assertLessEqual(hk, ak)
            self.assertLessEqual(ak, max(ks))
            strict = strict or hk < ak
        self.assertTrue(strict, 'actual mixed probe must distinguish harmonic and arithmetic K')
        type(self).alternative_cases = {'basin': basin_key, 'carbonate_taper': taper_key, 'harmonic_k': mixed_key}
        type(self).alternative_evidence = {'cases': type(self).alternative_cases,
            'basin_default': basin_default, 'basin_before': basin_before,
            'carbonate_default': base, 'carbonate_tapered': tapered,
            'arithmetic': arithmetic, 'harmonic': harmonic,
            'arithmetic_palette': ap, 'harmonic_palette': hp,
            'scope': 'BOUND_ACTUAL_SOURCE_INTERPRETATION_ALTERNATIVES_NOT_FULL_TERRAIN_RUNS'}

        synthetic = deepcopy(default)
        synthetic['evidence'] = 'SYNTHETIC TEST: zero-support/Gate limit of the owner programme; not a Diadem location'
        zero = {name: 0 for name in synthetic['field_ranges']}
        point = {'synthetic': {'xy_m': [0, 0], 'area_m2': 1}}
        rows, palette = geology.interpret({'synthetic': zero}, point, synthetic, self.materials)
        row = rows['synthetic']
        self.assertEqual(len(row['layers']), 1)
        self.assertEqual(_height(row), 10000)
        self.assertEqual(F(row['basal_elevation_m']), -10000)
        self.assertEqual(F(row['translation_m']), 0)
        self.assertTrue(_history(row['interpretation'])['root']['fallback_used'])
        descriptor = palette[row['layers'][0]['material_id']]
        self.assertEqual([v['unit_id'] for v in descriptor['constituents']], ['BX-00'])
        self._closed(row['interpretation']['geological_constituent_balances'])

        gate = {name: 1 for name in zero}
        gate['crown_massif_support'] = 0
        rows, palette = geology.interpret({'synthetic': gate}, point, synthetic, self.materials)
        row = rows['synthetic']; history = _history(row['interpretation'])
        self.assertEqual(F(row['interpretation']['derived_fields']['g']), 1)
        self.assertEqual(_height(row), 10000)
        self.assertEqual(F(row['translation_m']), 800)
        for name, stage in history.items():
            if stage['kind'] == 'emplace' and name != 'root':
                self.assertEqual(F(stage['thickness_m']), 0)
        remaining = F(5000)
        for layer in reversed(row['layers']):
            if remaining <= 0:
                break
            descriptor = palette[layer['material_id']]
            self.assertEqual([v['unit_id'] for v in descriptor['constituents']], ['GT-01'])
            self.assertEqual(F(descriptor['k_per_year']), F(self.materials['GT-01']['k_per_year']))
            remaining -= F(layer['thickness_m'])
        self.assertLessEqual(remaining, 0)
        gt = next(v for v in row['interpretation']['geological_constituent_balances'] if v['unit_id'] == 'GT-01')
        self.assertEqual(F(gt['exported_mass_kg']), 0)
        self.assertEqual(F(gt['imported_mass_kg']), F(gt['final_mass_kg']))
        self._closed(row['interpretation']['geological_constituent_balances'])

        # Enumerate only lightweight schedule dictionaries, never geological
        # states or fields for the 255,750-point public crop.
        limit = geology.batch_limit(default)
        self.assertGreaterEqual(limit, 2)
        self.assertLessEqual(limit, 32)
        count = 0; first_key = last_key = None
        for batch in w.batches(self.spec):
            self.assertTrue(0 < len(batch) <= limit)
            first_key = first_key or next(iter(batch))
            last_key = next(reversed(batch))
            count += len(batch)
        self.assertEqual(count, 255750)
        self.assertEqual(first_key, 'r120_c80')
        self.assertEqual(last_key, 'r584_c629')
        for invalid in (0, True, limit+1):
            with self.assertRaises(ValueError):
                w.batches(self.spec, invalid)

        mask = w.previous._mask(w._reader_spec(self.spec))
        selected = self.spec['selection']; r = selected['row_start']
        c = next(c for c in range(selected['column_start'], selected['column_stop'])
                 if mask[r-1, c] == 1 and mask[r, c] == 1)
        frame = self.spec['frame']; x0, y0 = frame['first_centre_m']; dx, dy = frame['step_m']
        pair = {_key(rr, c): {'xy_m': [x0+c*dx, y0+rr*dy], 'area_m2': frame['native_area_m2']}
                for rr in (r-1, r)}
        edge = w._build(self.spec, pair, 'DEFAULT', mask)
        type(self).edge_result = edge
        details = edge['scientific']['regional_input']
        self.assertIs(details['applicability']['crop_is_physical_boundary'], False)
        combined, cp = geology.interpret(details['sampling']['samples'], pair, default, self.materials)
        for key in pair:
            alone, sp = geology.interpret({key: details['sampling']['samples'][key]},
                                          {key: pair[key]}, default, self.materials)
            self.assertEqual(alone[key], combined[key])
            self.assertEqual(_geometry(alone[key], sp), _geometry(combined[key], cp))
            saved = details['interpretations'][key]
            self.assertEqual(alone[key]['layers'], saved['compartments'])
            self.assertEqual(F(saved['expected_surface_m']),
                F(alone[key]['basal_elevation_m'])+F(alone[key]['translation_m'])+_height(alone[key]))


if __name__ == '__main__':
    unittest.main()
