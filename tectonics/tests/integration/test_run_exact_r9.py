"""Run-exact speed plan r2, R-9 (H4 unit r3 test a): a pool kept inside `hold()` serves the next call.

Two reconstructions inside one hold give the same results and call counters as two without, on the same
worker processes. Synthetic sheared grid only.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import gc
import unittest

import numpy as np
import psutil

from atlas_tectonics.integration.resources import WorkBudget
from atlas_tectonics._private import private_heat_functionals_kernel_r5 as KERNEL
from atlas_tectonics._private.integration.heat import functionals_parallel as PARALLEL
from atlas_tectonics._private.integration.heat import process_meter as METER
from atlas_tectonics._private.integration.heat.counted_blocks import RECORD_CLASS

GIB = 1 << 30
ME = psutil.Process()


def enc(q):
    return [hex(q.numerator), hex(q.denominator)]


def declared_grid(n=2, shear=Q(1, 4)):
    """An affine image of the unit grid with each face's corners (the heat-repair fixture, inlined)."""
    h = Q(1, n)
    faces, cells = {}, []
    point = lambda x: (x[0]+shear*x[1], x[1], x[2])
    columns = [(h, Q(0), Q(0)), (shear*h, h, Q(0)), (Q(0), Q(0), h)]
    for index in np.ndindex((n, n, n)):
        cid = 'cell:'+','.join(map(str, index))
        linked = []
        for axis in range(3):
            for end in (0, 1):
                fi = tuple(i+end if j == axis else i for j, i in enumerate(index))
                fid = f'face:{axis}:'+','.join(map(str, fi))
                if fid not in faces:
                    area = h*h
                    normal = ((area, -shear*area, Q(0)), (Q(0), area, Q(0)), (Q(0), Q(0), area))[axis]
                    centre = point(tuple((i if j == axis else i+Q(1, 2))*h for j, i in enumerate(fi)))
                    a, b = [columns[j] for j in range(3) if j != axis]
                    faces[fid] = dict(face_id=fid, centroid_m=list(map(enc, centre)),
                        area_vector_m2=list(map(enc, normal)), owners=[], kind='declared test planar face',
                        vertices_m=[[enc(c+s*x/2+t*y/2) for c, x, y in zip(centre, a, b, strict=True)]
                                    for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
                faces[fid]['owners'].append(cid)
                linked.append([fid, -1 if end == 0 else 1])
        centre = point(tuple((i+Q(1, 2))*h for i in index))
        cells.append(dict(cell_id=cid, volume_m3=enc(h**3), centroid_m=list(map(enc, centre)), faces=linked))
    return dict(schema='test.exact-planar-metric-complex.v1', source='analytical affine image of unit grid',
                cells=cells, faces=list(faces.values()))


def call(budget, ladder=None):
    payload = declared_grid()
    outside = [face['face_id'] for face in payload['faces'] if len(face['owners']) == 1]
    extra = {} if ladder is None else dict(certification_precisions=ladder)
    owner = KERNEL.reconstruct(payload, boundary_point_faces=outside[0::2], boundary_power_faces=outside[1::2],
                               conductivity=Q(1), budget=budget, cancelled=lambda: False, **extra)
    value = strip(owner.value)
    owner.close()
    return value


def strip(value):
    """The result without wall-clock entries, as plain nested values."""
    if type(value) is dict:
        return {key: strip(item) for key, item in value.items() if key != 'seconds'}
    if type(value) in (list, tuple):
        return type(value)(strip(item) for item in value)
    return value


def children():
    return [child for child in ME.children(recursive=True) if child.is_running()]


# The expected differences between a call record with and without a hold, plus wall-clock keys and process ids.
# Design section 3a: result and polygon-moment bytes are bounded below, the ledger peak is recorded unbounded.
CALL_DIFFER = {'shared_input_bytes', 'ready_seconds', 'seconds', 'slowest_face', 'slowest_face_seconds',
               'largest_worker_ledger_peak_bytes', 'result_bytes', 'worker_polygon_moment_bytes'}
ROW_DIFFER = {'pid', 'ready_seconds', 'ready_private_bytes', 'ready_working_set_bytes', 'private_peak_bytes',
              'working_set_peak_bytes', 'busy_seconds', 'compute_seconds'}
SHARED = ('faces', 'moments')       # which worker takes which face is scheduling: compared as totals


def differ(a, b):
    found = sorted('%s %r != %r' % (k, a.get(k), b.get(k)) for k in set(a) | set(b)
                   if k not in CALL_DIFFER | {'processes'} and a.get(k) != b.get(k))
    rows_a, rows_b = (sorted(r['processes'], key=lambda row: row['slot']) for r in (a, b))
    if len(rows_a) != len(rows_b):
        return found + ['processes (count)']
    for x, y in zip(rows_a, rows_b, strict=True):
        found += sorted('processes.'+k for k in set(x) | set(y)
                        if k not in ROW_DIFFER | set(SHARED) and x.get(k) != y.get(k))
    found += ['processes.%s (total)' % k for k in SHARED
              if sum(row.get(k) or 0 for row in rows_a) != sum(row.get(k) or 0 for row in rows_b)]
    return found


def pids(record):
    return sorted(row['pid'] for row in record['processes'])


class Hold(unittest.TestCase):
    # Default and a shorter certifying ladder. A ladder that fails to certify sends faces to the exact fallback,
    # which on this tree names a helper file (`private_heat_functionals_kernel_r1.py`) absent since dev52.
    LADDERS = (None, (640, 1280, 2560))

    def setUp(self):
        PARALLEL.configure(workers=2)
        self.addCleanup(PARALLEL.configure, workers=6)
        self.assertEqual(children(), [])

    def metered(self):
        gc.collect()
        budget = WorkBudget(16*GIB)
        meter = METER.open(budget)
        self.assertIsNotNone(meter, METER.runtime(budget))
        return budget, meter

    def clean(self, budget, meter):
        gc.collect()
        self.assertEqual(children(), [])
        self.assertEqual(meter.children, {})
        self.assertEqual(meter.expected, 0)
        self.assertEqual(meter.side.reserved_bytes, 0)
        METER.finish(meter)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_a_two_calls_in_a_hold_equal_two_without(self):
        budget, meter = self.metered()
        call(budget)        # warms the process: the hello's file table grows with what the first call loads
        expected = [call(budget, ladder) for ladder in self.LADDERS]
        self.clean(budget, meter)
        fresh = PARALLEL.report()['calls'][-2:]
        budget, meter = self.metered()
        with PARALLEL.hold():
            found = [call(budget, self.LADDERS[0])]
            self.assertGreaterEqual(len(children()), 2)         # the kept workers between calls
            found.append(call(budget, self.LADDERS[1]))
        self.clean(budget, meter)
        self.assertEqual(found, expected)
        first, second = PARALLEL.report()['calls'][-2:]
        self.assertEqual(differ(first, fresh[0]), [])
        self.assertEqual(differ(second, fresh[1]), [])
        # The kept call sends ('call',) in place of the hello it no longer needs.
        self.assertEqual(first['shared_input_bytes'], fresh[0]['shared_input_bytes'])
        self.assertLess(second['shared_input_bytes'], fresh[1]['shared_input_bytes'])
        for kept, plain in ((first, fresh[0]), (second, fresh[1])):
            self.assertLessEqual(kept['result_bytes'], plain['result_bytes'])
            self.assertLessEqual(abs(kept['worker_polygon_moment_bytes']-plain['worker_polygon_moment_bytes']),
                                 RECORD_CLASS*2)
        self.assertEqual(pids(first), pids(second))
        self.assertNotEqual(pids(fresh[0]), pids(fresh[1]))     # without a hold each call starts its own
        for record in (*fresh, first, second):
            self.assertIsNone(record['fallback'])
            self.assertFalse(record['restarted'])
            self.assertEqual(len(record['processes']), 2)
            self.assertTrue(all(row['exit_code'] == 0 and row['ready_seconds'] is not None
                                for row in record['processes']))
        print('\n  kept call: shared input %d B (fresh %d B); result %+d B; polygon moments %+d B; ledger peak %d B'
              ' (fresh %d B); ready %s s (fresh %s s)' % (
            second['shared_input_bytes'], fresh[1]['shared_input_bytes'],
            second['result_bytes']-fresh[1]['result_bytes'],
            second['worker_polygon_moment_bytes']-fresh[1]['worker_polygon_moment_bytes'],
            second['largest_worker_ledger_peak_bytes'], fresh[1]['largest_worker_ledger_peak_bytes'],
            [row['ready_seconds'] for row in second['processes']],
            [row['ready_seconds'] for row in fresh[1]['processes']]), flush=True)


if __name__ == '__main__':
    unittest.main()
