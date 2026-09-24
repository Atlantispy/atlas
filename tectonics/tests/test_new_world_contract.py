"""Focused configuration contracts, not generated-planet acceptance.

SPDX-License-Identifier: AGPL-3.0-only
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import new_world_contract as contract


class NewWorldContractTests(unittest.TestCase):
    def request(self, seed=41):
        return contract.new_request(f'{seed:032x}')

    def assertRefuses(self, operation, *args, **kwargs):
        with self.assertRaises(contract.ContractError):
            operation(*args, **kwargs)

    def test_fixed_settings_and_canonical_roundtrip(self):
        request = self.request()
        request['settings']['plate_count'] = dict(mode='fixed', value=12)
        request['settings']['continental_fraction'] = dict(mode='fixed', value=.4)
        plan = contract.resolve_request(request)
        self.assertEqual(plan['resolved_settings'], dict(radius_m=6371000.,
            gravity_m_s2=9.81, plate_count=12, continental_fraction=.4))
        self.assertEqual(contract.validate_plan(contract.parse_json(contract.canonical_bytes(plan))), plan)
        self.assertEqual(plan['status'], 'CONFIGURED_NOT_GENERATED')
        self.assertEqual(plan['capabilities'], dict(configure=True, generate_world=False,
            evolve_world=False, native_restart=False))
        self.assertNotIn('products', plan)

    def test_auto_varies_configuration_and_repeat_is_exact(self):
        plans = [contract.resolve_request(self.request(seed)) for seed in range(8)]
        for seed, plan in enumerate(plans):
            self.assertEqual(contract.resolve_request(self.request(seed)), plan)
            self.assertGreaterEqual(plan['resolved_settings']['plate_count'], 8)
            self.assertLessEqual(plan['resolved_settings']['plate_count'], 20)
            self.assertTrue(.25 <= plan['resolved_settings']['continental_fraction'] < .45)
        self.assertGreater(len({p['resolved_settings']['plate_count'] for p in plans}), 1)
        self.assertEqual(len({p['resolved_settings']['continental_fraction'] for p in plans}), 8)
        self.assertEqual(len({p['streams']['plate_layout'] for p in plans}), 8)

    def test_os_seed_generation_is_explicit_not_used_on_load(self):
        with patch.object(contract.secrets, 'token_hex', return_value='a' * 32) as entropy:
            request = contract.new_request()
            entropy.assert_called_once_with(16)
        with patch.object(contract.secrets, 'token_hex', side_effect=AssertionError('fresh entropy on load')):
            plan = contract.resolve_request(request)
            self.assertEqual(contract.validate_plan(plan), plan)
        self.assertEqual(plan['request']['seed'], 'a' * 32)

    def test_stream_definition_has_independent_known_answer(self):
        seed = '0' * 32
        message = b'atlas.new-world.stream.v1\0' + bytes(16) + b'\0plate_layout'
        expected = hashlib.sha256(message).hexdigest()[:32]
        self.assertEqual(contract.stream_seed(seed, 'plate_layout'), expected)
        first = contract.stream_seed(seed, 'plate_layout')
        contract.stream_seed(seed, 'thermal_structure')
        self.assertEqual(contract.stream_seed(seed, 'plate_layout'), first)
        self.assertNotEqual(contract.stream_seed(seed, 'plate_sizes'), first)
        self.assertRefuses(contract.stream_seed, seed, '../file')

    def test_random_stream_independence_never_implies_physical_cache_reuse(self):
        request = self.request()
        before = contract.resolve_request(request)
        request['settings']['continental_fraction'] = dict(mode='fixed', value=.42)
        after = contract.resolve_request(request)
        self.assertEqual(before['streams'], after['streams'])
        self.assertEqual(before['resolved_settings']['plate_count'], after['resolved_settings']['plate_count'])
        self.assertNotEqual(before['scientific_id'], after['scientific_id'])
        self.assertNotEqual(before['plan_id'], after['plan_id'])

    def test_resource_change_does_not_change_scientific_configuration(self):
        request = self.request()
        before = contract.resolve_request(request)
        request['resources']['max_work_bytes'] *= 2
        request['resources']['max_wall_seconds'] *= 2
        after = contract.resolve_request(request)
        self.assertEqual(before['scientific_id'], after['scientific_id'])
        self.assertEqual(before['resolved_settings'], after['resolved_settings'])
        self.assertNotEqual(before['request_id'], after['request_id'])
        self.assertNotEqual(before['plan_id'], after['plan_id'])

    def test_each_physical_context_change_invalidates_scientific_identity(self):
        original = self.request()
        before = contract.resolve_request(original)['scientific_id']
        changes = [lambda r: r['epoch'].update(time_s=1.),
                   lambda r: r['epoch'].update(id='another-epoch'),
                   lambda r: r['frame'].update(id='another-frame'),
                   lambda r: r['resolution'].update(support_cells=2048),
                   lambda r: r['settings']['radius_m'].update(value=6372000.),
                   lambda r: r.update(seed='f' * 32)]
        for change in changes:
            request = deepcopy(original)
            change(request)
            self.assertNotEqual(contract.resolve_request(request)['scientific_id'], before)

    def test_inputs_and_outputs_are_detached(self):
        request = self.request()
        before = deepcopy(request)
        plan = contract.resolve_request(request)
        plan['request']['frame']['id'] = 'mutated'
        plan['streams']['plate_layout'] = '0' * 32
        self.assertEqual(request, before)
        description = contract.contract_description()
        description['setting_domains']['plate_count']['maximum'] = 999
        self.assertEqual(contract.contract_description()['setting_domains']['plate_count']['maximum'], 52)
        output = contract.output_contract()
        output['required_products']['thermal'] = 'Celsius'
        self.assertEqual(contract.output_contract()['required_products']['thermal'], 'K')

    def test_bad_seed_and_request_keys_refuse(self):
        for seed in (None, 41, True, '', 'f' * 31, 'A' * 32, 'g' * 32):
            request = self.request()
            request['seed'] = seed
            self.assertRefuses(contract.validate_request, request)
        for key, value in [('mode', 'dynamic'), ('recipe', 'other'), ('schema', 'v0')]:
            request = self.request()
            request[key] = value
            self.assertRefuses(contract.validate_request, request)
        request = self.request()
        request['generate'] = True
        self.assertRefuses(contract.validate_request, request)

    def test_units_frames_epochs_and_resource_envelopes_refuse(self):
        cases = [('frame', 'length_unit', 'km'), ('frame', 'coordinate_system', 'latitude-longitude'),
                 ('frame', 'vertical_reference', 'sea-level'), ('frame', 'id', '../world'),
                 ('epoch', 'time_s', True), ('epoch', 'time_s', math.inf),
                 ('epoch', 'id', ''), ('resources', 'max_work_bytes', 128.),
                 ('resources', 'max_wall_seconds', 0), ('resolution', 'support_cells', 8)]
        for group, name, value in cases:
            with self.subTest(group=group, name=name, value=value):
                request = self.request()
                request[group][name] = value
                self.assertRefuses(contract.validate_request, request)

    def test_invalid_settings_and_auto_upper_bound_support(self):
        cases = [('plate_count', dict(mode='fixed', value=True)),
                 ('plate_count', dict(mode='fixed', value=12.)),
                 ('plate_count', dict(mode='auto', minimum=5, maximum=53)),
                 ('continental_fraction', dict(mode='auto', minimum=.5, maximum=.2)),
                 ('radius_m', dict(mode='fixed', value=-1)),
                 ('gravity_m_s2', dict(mode='auto', minimum=.1, maximum=math.nan)),
                 ('plate_count', dict(mode='auto', minimum=2, maximum=10, distribution='unknown'))]
        for name, value in cases:
            request = self.request()
            request['settings'][name] = value
            self.assertRefuses(contract.validate_request, request)
        request = self.request()
        request['resolution']['support_cells'] = 79
        self.assertRefuses(contract.validate_request, request)
        request['resolution']['support_cells'] = 80
        contract.validate_request(request)

    def test_auto_endpoint_roundoff_and_unbiased_integer_rejection(self):
        request = self.request()
        lower, upper = .5, math.nextafter(.5, 1.)
        request['settings']['continental_fraction'] = dict(mode='auto', minimum=lower, maximum=upper)
        with patch.object(contract, '_draw', return_value=(1 << 64) - 1):
            self.assertEqual(contract._sample(request['seed'], 'continental_fraction',
                request['settings']['continental_fraction'], False), lower)
        count = dict(mode='auto', minimum=2, maximum=4)
        with patch.object(contract, '_draw', side_effect=[(1 << 64) - 1, 1]) as draw:
            self.assertEqual(contract._sample(request['seed'], 'plate_count', count, True), 3)
            self.assertEqual(draw.call_count, 2)
        count = dict(mode='auto', minimum=7, maximum=7)
        self.assertEqual(contract._sample(request['seed'], 'plate_count', count, True), 7)

    def test_plan_tampering_and_source_changes_refuse(self):
        plan = contract.resolve_request(self.request())
        for key, value in [('plan_id', '0' * 64), ('status', 'GENERATED'),
                           ('resolved_settings', {}), ('scientific_id', '0' * 64),
                           ('capabilities', dict(configure=True, generate_world=True,
                                                evolve_world=False, native_restart=False))]:
            changed = deepcopy(plan)
            changed[key] = value
            self.assertRefuses(contract.validate_plan, changed)
        changed = deepcopy(plan)
        changed['binding']['contract_sha256'] = '0' * 64
        with self.assertRaises(contract.ContractError) as caught:
            contract.validate_plan(changed)
        self.assertEqual(caught.exception.code, 'SOURCE_MISMATCH')
        with patch.object(contract, '_LOADED_SOURCE_DIGEST', '0' * 64):
            self.assertRefuses(contract.resolve_request, self.request())

    def test_strict_json_bounds_and_types(self):
        for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', b'\xff',
                     '[' * 1000 + '0' + ']' * 1000):
            self.assertRefuses(contract.parse_json, data)
        self.assertRefuses(contract.parse_json, b' ' * 65537)
        self.assertRefuses(contract.canonical_bytes, {'bad': math.inf})
        self.assertRefuses(contract.canonical_bytes, {1: 'non-string'})
        self.assertRefuses(contract.canonical_bytes, {'tuple': (1, 2)})
        self.assertEqual(contract.parse_json('{"zero":0}'), {'zero': 0})

    def test_output_descriptor_checks_structure_not_physical_acceptance(self):
        plan = contract.resolve_request(self.request())
        request = plan['request']
        descriptor = dict(schema=contract.WORLD_SCHEMA, status='WORKING NON-CANON',
            plan_id=plan['plan_id'], scientific_id=plan['scientific_id'],
            epoch=deepcopy(request['epoch']), frame=deepcopy(request['frame']),
            origins=dict(recipe=request['recipe'], mode=request['mode']),
            products={name: dict(product_id='a' * 64, support_id='b' * 64,
                unit=unit, frame_id=request['frame']['id'], epoch_id=request['epoch']['id'],
                known_mask_id='c' * 64, origin='generated-assumption')
                for name, unit in contract.output_contract()['required_products'].items()})
        self.assertEqual(contract.validate_world_descriptor(descriptor, plan), descriptor)
        for key, value in [('unit', 'Celsius'), ('frame_id', 'other'), ('epoch_id', 'other'),
                           ('support_id', 'd' * 64), ('known_mask_id', None), ('origin', 'observed')]:
            changed = deepcopy(descriptor)
            changed['products']['thermal'][key] = value
            self.assertRefuses(contract.validate_world_descriptor, changed, plan)
        changed = deepcopy(descriptor)
        del changed['products']['material']
        self.assertRefuses(contract.validate_world_descriptor, changed, plan)
        changed = deepcopy(descriptor)
        changed['status'] = 'CANON'
        self.assertRefuses(contract.validate_world_descriptor, changed, plan)


if __name__ == '__main__':
    unittest.main()
