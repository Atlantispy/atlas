"""Review bridge regressions: reconstructed records must obey fresh extraction admission."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest

from threadpoolctl import threadpool_limits
import i03_fixtures as F
import i02_workflow_fixtures as F2
import test_i03_bridges as TB
from atlas_tectonics import integration_bridges as B, integration_transfer as T
from atlas_tectonics import integration_clock as K, integration_ledger as L, integration_events as E

CONTROL = json.loads((F.CASES/'i03_controls_v4.json').read_text(encoding='utf-8'))['controls']['bridge_admission']


class AdmissionTests(unittest.TestCase):
    def test_self_consistent_map_and_3d_records_cannot_bypass_finite_velocity_admission(self):
        # Exact supplied review reproducer; duration is adversarial data, not a new acceptance bound.
        state = F.crust(F.three_plates(time_s=0.))
        proposal = F.one_plate_motion(TB.control('bridge_return_commit')['turn_deg'])
        for representation in ('3d', 'map'):
            with self.subTest(representation=representation):
                fp = TB.footprint(TB.control('bridge_return_commit'), representation,
                                  tolerance=CONTROL['map_declared_distortion'] if representation == 'map' else None)
                extracted = B.extract(state, fp, proposal, F.MYR_S)
                record = B.carried(extracted, TB.unchanged(extracted)).record()
                duration = CONTROL['duration_s']
                record['duration_s'] = duration
                record['extract_id'] = B._identity(state.state_id, fp, extracted.projection, proposal.motion_id, duration)
                carried = B.RegionalReturn.from_record(record)
                with self.assertRaisesRegex(B.BridgeRefused, 'velocities are not finite'):
                    T.advance(state, replace(proposal, regional_returns=(carried,)), end_time_s=duration)

    def test_binding_includes_events_mesh_supplies_and_sinks(self):
        state = F.crust(F.three_plates())
        proposal = F.one_plate_motion(TB.control('bridge_return_commit')['turn_deg'])
        fp = TB.footprint(TB.control('bridge_return_commit'))
        extracted = B.extract(state, fp, proposal, F.MYR_S)
        carried = B.carried(extracted, TB.unchanged(extracted))
        endpoint = T.advance(state, proposal, end_time_s=F.MYR_S).state
        variants = {
            'events': replace(proposal, events=(E.Merge('merge-bc', ('B', 'C'), 'BC', F.MYR_S),)),
            'mesh': replace(proposal, mesh=T.Mesh(endpoint.network.faces)),
            'supplies': replace(proposal, supplies=(replace(proposal.supplies[0], origin_id='different-origin'), *proposal.supplies[1:])),
            'sinks': replace(proposal, sinks=()),
        }
        for name, actual in variants.items():
            with self.subTest(field=name), self.assertRaises(B.BridgeRefused) as caught:
                # Inspect the commit's binding seam before unrelated source/sink availability admission.
                B._returned_at_end(state, endpoint.network, endpoint.material, (carried,), actual)
            self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)

    def test_section_return_reopens_and_accepts_the_next_moving_interval(self):
        with threadpool_limits(limits=1, user_api='blas'), tempfile.TemporaryDirectory() as folder:
            column = F2.root(F.control('clock_commit')['column_steps'])
            state = F.crust(F.three_plates(epoch=F2.EPOCH, time_s=F2.START))
            path = Path(folder)/'section.sqlite'
            store = F2.store(path)
            deadline = lambda: time.perf_counter()+F.CASE['resources']['clock_deadline_s']
            try:
                ledger, _ = L.Ledger.create(store, column, sphere=state)
                clock = K.Clock(ledger)
                proposal = F.one_plate_motion(TB.control('bridge_return_commit')['turn_deg'])
                rule = TB.control('bridge_identity') | {'centre_lon_lat_deg': CONTROL['section_centre_lon_lat_deg']}
                fp = TB.footprint(rule, 'section', azimuth_deg=CONTROL['section_azimuth_deg'],
                                  faces=tuple(CONTROL['section_faces']))
                extracted = B.extract(state, fp, proposal, clock.time_at(1)-state.network.time_s)
                carrying = replace(proposal, regional_returns=(B.carried(extracted, TB.unchanged(extracted)),))
                result = clock.advance(steps=1, deadline=deadline(), transfers=(carrying,))
                self.assertEqual(result.status, K.COMPLETED, result.reason)
                saved = ledger.sphere(result.head).state_id
                ledger_id = ledger.ledger_id
            finally:
                store.close()
            store = F2.store(path)
            try:
                ledger = L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
                self.assertEqual(ledger.verify_chain().key, result.head.key)
                self.assertEqual(ledger.sphere(result.head).state_id, saved)
                result = K.Clock(ledger).advance(steps=1, deadline=deadline(), transfers=(replace(proposal, start_step=1, end_step=2),))
                self.assertEqual(result.status, K.COMPLETED, result.reason)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
