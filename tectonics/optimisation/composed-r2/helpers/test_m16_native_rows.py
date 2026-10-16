"""M16: convert_native(scope) books each native support row once (decode bound), not twice.

Synthetic authority only (the test_live_partition 'baseline' route at small count);
no interval solve, no store writes. tracemalloc measures memory only, never time.
"""
import gc
import json
import sys
import time
import tracemalloc
import unittest
from copy import deepcopy
from unittest.mock import patch

import test_live_partition as LP

ROWS = 24


def setUpModule():
    LP.setUpModule()


def tearDownModule():
    LP.tearDownModule()


def _native_partition(count=ROWS):
    """The measure('baseline', count) construction: a fresh native shared-budget partition."""
    from content_cache import create_retained_scope
    T, D, F = LP.T, LP.D, LP.F
    budget = T.WorkBudget(2 << 30)
    scope = create_retained_scope(budget, process_epoch='m16-native-rows')
    body, sample = T.tiny_partition(budget, count=1, depth=16)
    template = sample[0]
    constraint = template['constraints']['carried:edge']
    while constraint['kind'] == 'snapshot-rotated':
        constraint = constraint['constraint']
    for ray in constraint['rays'][:1]:
        ray['prior_rotations'] = ray['prior_rotations']*48
    body['support_ids'] = []; body['identity_start_cells'] = []
    body['native_contacts'][0]['contacts'] = []
    body['max_components'] = count+1
    operands = F.source_operands(body, budget)
    del sample
    native = []
    for i in range(count):
        row = deepcopy(template)
        component = row['components'][0]
        component.update(logical_cell_id=T.ident('m16-cell'+str(i)), parent_cell_id=T.ident('m16-parent'+str(i)))
        row['voxel_index'] = [i, 0, 0]
        row['max_components'] = count+1
        first = D._issue(D.DifferentialSupport, row, budget)
        support = D._issue(D.DifferentialSupport, first.record(), budget)
        native.append(support)
        identity = support.support_id
        body['support_ids'].append(identity)
        body['identity_start_cells'].append({'parent_cell_id': component['parent_cell_id'],
                                             'cell_id': component['logical_cell_id']})
        body['native_contacts'][0]['contacts'].append({'support_id': identity,
            'logical_cell_id': component['logical_cell_id'], 'voxel_index': row['voxel_index'],
            'axis': 0, 'end': 0})
        del first, support, row, component
    first = D._issue(D.DifferentialPartition, body, budget)
    object.__setattr__(first, '_supports', tuple(native))
    decoded = first.record()
    part = D._issue(D.DifferentialPartition, decoded, budget)
    object.__setattr__(part, '_supports', first.supports)
    del first, decoded, native, body, template, constraint
    return part, budget, scope, operands


def _old_init(self, supports, budget, scope=None):
    # The origin behaviour: rows are plain dicts charged on the budget, whatever the scope.
    self._supports, self._budget, self._held, self._scope = supports, budget, (), None


class _SpecLog:
    def __init__(self, real):
        self.real, self.calls = real, []

    def __call__(self, purpose, *args, **kwargs):
        self.calls.append(purpose)
        return self.real(purpose, *args, **kwargs)


def _convert(old):
    import partition_v2 as P2
    import partition_workflow_patch as PW
    part, budget, scope, operands = _native_partition()
    log = _SpecLog(P2.ChargeSpec)
    started = time.perf_counter()
    with patch.object(P2, 'ChargeSpec', log):
        if old:
            with patch.object(PW._NativeSupportRows, '__init__', _old_init):
                view = PW.convert_native(part, budget, scope=scope)
        else:
            view = PW.convert_native(part, budget, scope=scope)
    seconds = time.perf_counter()-started
    result = {'identity': view.identity().to_wire(), 'partition_id': view.partition_id,
              'peak': budget.statistics()['peak_reserved_bytes'], 'seconds': seconds,
              'dict_carriers': log.calls.count('partition-input-support')}
    del part
    view.close(); del view, operands
    gc.collect()
    scope.close()
    result['released'] = budget.reserved_bytes == 0
    return result


class M16NativeRows(unittest.TestCase):
    def test_same_identity_one_carrier_per_row_and_lower_peak(self):
        old = _convert(old=True)
        new = _convert(old=False)
        print('M16 old:', {k: v for k, v in old.items() if k != 'identity'}, file=sys.stderr)
        print('M16 new:', {k: v for k, v in new.items() if k != 'identity'}, file=sys.stderr)
        self.assertEqual(new['identity'], old['identity'])
        self.assertEqual(new['partition_id'], old['partition_id'])
        self.assertEqual(old['dict_carriers'], ROWS)   # origin: a second carrier per row
        self.assertEqual(new['dict_carriers'], 0)      # new: rows arrive Owned and are retained
        self.assertLess(new['peak'], old['peak'])
        self.assertTrue(old['released'] and new['released'])

    def test_row_booking_covers_traced_decode(self):
        import mesh_tables as M
        part, _budget, scope, operands = _native_partition()
        ratios = []
        for support in part.supports:
            booked = M._decode_charge(support._json)+65536
            gc.collect()
            tracemalloc.start()
            row = json.loads(support._json)
            real = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            del row
            self.assertGreaterEqual(booked, real)
            ratios.append(booked/real)
        print(f'M16 row booked/real: min {min(ratios):.2f} max {max(ratios):.2f} '
              f'(row bytes {len(part.supports[0]._json)})', file=sys.stderr)
        del part, operands
        gc.collect(); scope.close()

    def test_held_failure_keeps_row_charges_until_traceback_release(self):
        import partition_workflow_patch as PW
        part, budget, scope, operands = _native_partition()
        baseline = budget.reserved_bytes
        seen = []

        def check():
            seen.append(1)
            if len(seen) == 5:
                raise ValueError('m16 deliberate stop')
        error = None
        try:
            PW.convert_native(part, budget, scope=scope, check=check)
        except ValueError as caught:
            error = caught
        self.assertIsNotNone(error)
        held = budget.reserved_bytes
        self.assertGreater(held, baseline)
        gc.collect()
        self.assertEqual(budget.reserved_bytes, held)
        error.__traceback__ = None
        del error
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        del part, operands
        gc.collect(); scope.close()


if __name__ == '__main__':
    unittest.main()
