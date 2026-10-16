"""Exact cache-key isolation and certified-only admission, with synthetic facts."""
from concurrent.futures import CancelledError
import threading
import unittest

from atlas_tectonics.resources import WorkBudget
from certified_fact_cache import CertifiedFact, CertifiedFactCache, fact_key
from content_cache import ChargeSpec, create_retained_scope


def fields():
    return dict(process_epoch='process', predicate_kind='exact-plane-side',
        operands=(('point', b'1/3,2/7,-0'), ('plane', b'1,2,3,4')),
        parameters=(('duration', b'3/5'), ('level', b'7')),
        method_identity=b'method-sha', execution_identity=b'runtime-sha',
        certificate_schema=b'plane-proof-v1', verifier_schema=b'verifier-v1')


class FactTests(unittest.TestCase):
    def test_every_operand_role_order_parameter_and_method_is_bound(self):
        source = fields()
        baseline = fact_key(**source)
        for name in source:
            changed = dict(source)
            if name in ('operands', 'parameters'):
                pairs = list(changed[name])
                for index in range(len(pairs)):
                    edited = list(pairs)
                    edited[index] = (edited[index][0], edited[index][1] + b'changed')
                    changed[name] = tuple(edited)
                    self.assertNotEqual(baseline, fact_key(**changed), (name, index))
                changed[name] = tuple(reversed(pairs))
                self.assertNotEqual(baseline, fact_key(**changed), name + ' order')
                changed[name] = tuple((role + '-other', raw) for role, raw in pairs)
            else:
                changed[name] += 'changed' if isinstance(changed[name], str) else b'changed'
            self.assertNotEqual(baseline, fact_key(**changed), name)

    def test_ambiguous_nonexact_or_missing_identity_refuses(self):
        for name, replacement in (('method_identity', b''), ('operands', (('x', 0.1),)),
                                  ('operands', (('x', b'1'), ('x', b'2')))):
            changed = dict(fields(), **{name: replacement})
            with self.assertRaises((ValueError, TypeError)):
                fact_key(**changed)

    def test_false_certificate_and_on_off_parity_operational_declines_not_cached(self):
        outputs = []
        for enabled in (False, True):
            run = WorkBudget(1_000_000)
            scope = create_retained_scope(run, process_epoch='process')
            binding = fact_key(**fields())
            cache = CertifiedFactCache(scope, enabled=enabled,
                verifier=lambda key, fact: key == binding and fact.certificate == b'exact-proof')
            values = []
            for _ in range(3):
                got = cache.get(binding)
                if got is None:
                    with scope.reserve(ChargeSpec('fact', 128)) as reservation:
                        got = reservation.commit(CertifiedFact(False, b'exact-proof'))
                    cache.offer_verified(binding, got)
                values.append((got.value.result, got.value.certificate))
                got.close()
            outputs.append(values)
            for status in ('cancelled', 'budget-refusal', 'timeout', 'partial-proof', 'declined'):
                with scope.reserve(ChargeSpec('decline', 128)) as reservation:
                    declined = reservation.commit(CertifiedFact(False, b'exact-proof', status))
                self.assertFalse(cache.offer_verified(binding, declined))
                declined.close()
            self.assertEqual(scope.stats().insertions['facts'], 1 if enabled else 0)
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(CancelledError):
                cache.get(binding, cancel=cancelled)
            cache.close()
            scope.close()
            self.assertEqual(run.reserved_bytes, 0)
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
