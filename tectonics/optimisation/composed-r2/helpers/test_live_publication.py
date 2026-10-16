"""Step 8 last-use/exception ownership at actual compact publication boundaries."""
import gc
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import test_spatial_records_patch as F

P = F.P


def certification_fixture(budget, count=3):
    records = dict(solution=dict(solution_id='a'*64, cells=F.fixture_records(count)['state']['cells'], evidence='x'*100000),
                   proposal={}, iteration={}, force={}, bindings={})
    field = np.arange(3, dtype='<f8')
    force = SimpleNamespace(nbytes=field.nbytes, array_names=('omega',), array=lambda name: field)
    raw = json.dumps(records).encode()
    solution = SimpleNamespace(_resource=budget, _json=raw,
        proposal=SimpleNamespace(_json=b'{}', _owner=SimpleNamespace(_definition={}),
                                 force_exchange=force))
    # The producer returns fresh decoded dictionaries just as the native
    # certification producer does; the fixture is not scientific acceptance.
    cls = SimpleNamespace(_certification_required=lambda *args: None,
        _certification_records=lambda value: json.loads(raw),
        _certification_header=lambda value, ref: dict(solution_id=value['solution']['solution_id'],
                                                      record_blob=ref))
    return solution, cls, raw, field


class LifetimeTests(unittest.TestCase):
    setUp = F.PublicationTests.setUp
    tearDown = F.PublicationTests.tearDown

    def test_certification_decode_released_before_commit_and_header_owned(self):
        solution, cls, raw, field = certification_fixture(self.budget)
        with P.certification_payload(cls, solution, self.budget, store=self.candidate,
                                     source_producer=F.PRODUCER) as (header, arrays):
            self.assertIs(arrays['certification-force:omega'], field)
            self.assertLess(self.budget.statistics()['categories'].get('record-workspace', 0),
                            len(raw) * 10)
            with F.ArrayStore(self.root/'head.sqlite', self.candidate.limits, budget=self.budget) as head:
                head.put('7'*64, arrays, dict(certification=header), budget=self.budget)
            with P.export_record(self.candidate, header['record_blob'], 'certification',
                                 budget=self.budget) as restored:
                self.assertEqual(restored, json.loads(raw))
        self.assertGreater(self.budget.statistics()['categories'].get('record-workspace', 0), 0)
        del header, restored
        self.assertEqual(self.budget.statistics()['categories'].get('record-workspace', 0), 0)

    def test_failed_publication_traceback_keeps_decoded_record_paid(self):
        solution, cls, raw, _ = certification_fixture(self.budget)
        held = None
        with patch.object(P, 'publish_records', side_effect=RuntimeError('publication failure')):
            try:
                with P.certification_payload(cls, solution, self.budget, store=self.candidate,
                                             source_producer=F.PRODUCER):
                    self.fail('failure did not propagate')
            except RuntimeError as error:
                held = error
        self.assertIsNotNone(held)
        self.assertGreaterEqual(self.budget.statistics()['categories']['record-workspace'], len(raw)*10)
        del held
        gc.collect()  # A retained exception is deliberately cyclic.
        self.assertEqual(self.budget.statistics()['categories'].get('record-workspace', 0), 0)

    def test_geometry_decode_released_before_commit_and_exact_arrays(self):
        class Interval:
            def descriptor(self):
                return json.loads(self._json)
        interval = Interval()
        interval._resource = self.budget
        values = {key: 'a'*64 for key in P.DIFFERENTIAL_NAMES}
        values.update(start_time_s=['0x0', '0x1'], end_time_s=['0x1', '0x1'],
                      large_body='x'*100000)
        interval._json = json.dumps(values).encode()
        field = np.arange(6, dtype='<f8')
        interval.endpoint_network = SimpleNamespace(nbytes=field.nbytes,
            descriptor=lambda: dict(network_id='c'*64), arrays=lambda: dict(positions=field))
        with patch('atlas_tectonics.integration_differential_geometry.DifferentialInterval', Interval):
            with P.differential_payload(interval, self.budget, store=self.candidate,
                                        source_producer=F.PRODUCER) as (header, arrays):
                self.assertIs(arrays['differential-network:positions'], field)
                self.assertLess(self.budget.statistics()['categories'].get('record-workspace', 0),
                                len(interval._json)*8)
                with P.export_record(self.candidate, header['record_blob'], 'differential',
                                     budget=self.budget) as restored:
                    self.assertEqual(restored['interval'], values)
        del header, restored
        self.assertEqual(self.budget.statistics()['categories'].get('record-workspace', 0), 0)


if __name__ == '__main__':
    unittest.main()

