"""S8: the readers report their live-producer child beside the unchanged retained accounting."""
import copy
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPACT = HERE/'compact-geometry-r1'
RUNTIME = HERE.parent/'runtime-integration-r1'/'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

from atlas_tectonics.resources import WorkBudget
from content_cache import ChargeSpec, OWNER_BYTES, PRODUCER_PURPOSES, create_retained_scope
import reopen_prepared_restart as RO


class ProducerAccountingTests(unittest.TestCase):
    def scope(self, producer):
        budget = WorkBudget(64 << 20)
        scope = create_retained_scope(budget, process_epoch='prepared-restart-'+str(os.getpid()),
                                      live_producer_bytes=(32 << 20) if producer else None)
        return budget, scope

    def test_producer_purposes_are_reported_and_reconcile(self):
        budget, scope = self.scope(True)
        held = [scope.reserve(ChargeSpec('record-tables', 1 << 20)).commit(bytearray(8)),
                scope.reserve(ChargeSpec('mesh-memory-columns', 3 << 20)).commit(bytearray(8)),
                scope.reserve(ChargeSpec('view', 2 << 20)).commit(bytearray(8))]
        retained, producer = RO.retained_accounting(scope), RO.producer_accounting(scope)
        RO.validate_retained_accounting(retained, pid=os.getpid())
        RO.validate_producer_accounting(producer, scope_id=retained['scope_id'])
        self.assertEqual(producer['producer_limit_bytes'], 32 << 20)
        self.assertEqual(producer['producer_bytes'], (4 << 20) + 2*OWNER_BYTES)
        self.assertEqual(producer['producer_purpose_bytes'],
                         {'live-producer:record-tables': (1 << 20)+OWNER_BYTES,
                          'live-producer:mesh-memory-columns': (3 << 20)+OWNER_BYTES})
        # The non-producer purpose stays in the 256 MiB aggregate, which the existing record already shows.
        self.assertEqual(retained['purpose_bytes'].get('retained:view'), (2 << 20)+OWNER_BYTES)
        self.assertEqual(retained['retained_bytes'], sum(retained['purpose_bytes'].values()))
        self.assertNotIn('retained:record-tables', retained['purpose_bytes'])
        self.assertNotIn('retained:mesh-memory-columns', retained['purpose_bytes'])
        held[0].close()
        later = RO.producer_accounting(scope)
        self.assertEqual(later['producer_bytes'], (3 << 20)+OWNER_BYTES)
        self.assertEqual(later['producer_peak_bytes'], (4 << 20)+2*OWNER_BYTES)
        for owner in held[1:]:
            owner.close()
        scope.close()
        closed = RO.producer_accounting(scope)
        RO.validate_producer_accounting(closed, scope_id=retained['scope_id'])
        self.assertEqual(closed['producer_bytes'], 0)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(set(PRODUCER_PURPOSES) >= {'record-tables', 'mesh-memory-columns'}, True)

    def test_cold_scope_reports_zeros(self):
        _, scope = self.scope(False)
        owner = scope.reserve(ChargeSpec('record-tables', 1 << 20)).commit(bytearray(8))
        value = RO.producer_accounting(scope)
        RO.validate_producer_accounting(value, scope_id=scope.scope_id)
        self.assertEqual({k: value[k] for k in RO.PRODUCER_SCALARS}, dict.fromkeys(RO.PRODUCER_SCALARS, 0))
        # Without a producer child the same purpose stays in the retained aggregate.
        self.assertEqual(RO.retained_accounting(scope)['purpose_bytes'].get('retained:record-tables'),
                         (1 << 20)+OWNER_BYTES)
        owner.close()
        scope.close()

    def test_validation_refuses_inconsistent_records(self):
        _, scope = self.scope(True)
        owner = scope.reserve(ChargeSpec('transport-result-field', 1 << 20)).commit(bytearray(8))
        good = RO.producer_accounting(scope)
        sid = scope.scope_id
        bad = []
        for change in (lambda v: v.update(producer_bytes=v['producer_bytes']+1),
                       lambda v: v.update(producer_peak_bytes=v['producer_limit_bytes']+1),
                       lambda v: v.update(producer_refusals=-1),
                       lambda v: v.update(scope_id='0'*64),
                       lambda v: v.pop('producer_purpose_peak_bytes'),
                       lambda v: v.update(extra=1),
                       lambda v: v['producer_purpose_bytes'].update({'x': -1})):
            value = copy.deepcopy(good)
            change(value)
            bad.append(value)
        for value in bad:
            with self.assertRaises(RO.ReopenRefused):
                RO.validate_producer_accounting(value, scope_id=sid)
        retained = {'before_close': {'scope_id': sid}}
        self.assertIsNone(RO.validate_retained_producer({}, retained))
        self.assertIsNotNone(RO.validate_retained_producer(
            {'retained_producer': {'before_close': good, 'after_close': good}}, retained))
        for broken in ({'before_close': good}, {'before_close': good, 'after_close': good, 'x': good}, [], None):
            with self.assertRaises(ValueError):
                RO.validate_retained_producer({'retained_producer': broken}, retained)
        owner.close()
        scope.close()


class FreshAdoptionWiring(unittest.TestCase):
    """The field through the fresh reader's whole receipt check, not the helper alone."""

    def setUp(self):
        import test_reopen_fresh_restart as TF
        self.owner = TF.ReaderReceiptAndAdoptionTests('test_reader_receipt_closed_checks')
        self.owner.setUp()

    def producer(self, **change):
        value = dict(scope_id='scope', producer_limit_bytes=2 << 30, producer_bytes=0, producer_peak_bytes=4096,
                     producer_refusals=0, producer_purpose_bytes={}, producer_purpose_peak_bytes={})
        value.update(change)
        return value

    def test_receipt_check_reads_the_field(self):
        reopen = self.owner.reopen()
        self.owner.validate(reopen)  # older receipt: no field
        reopen['retained_producer'] = {'before_close': self.producer(), 'after_close': self.producer()}
        self.owner.validate(reopen)
        cases = (
            ('incomplete', lambda r: r['retained_producer'].pop('after_close')),
            ('incomplete', lambda r: r.update(retained_producer=None)),
            ('does not reconcile', lambda r: r['retained_producer']['before_close'].update(producer_bytes=1)),
            ('does not reconcile', lambda r: r['retained_producer']['after_close'].update(scope_id='other')),
        )
        for message, change in cases:
            with self.subTest(message=message):
                broken = copy.deepcopy(reopen)
                change(broken)
                with self.assertRaisesRegex(ValueError, message):
                    self.owner.validate(broken)


if __name__ == '__main__':
    unittest.main()
