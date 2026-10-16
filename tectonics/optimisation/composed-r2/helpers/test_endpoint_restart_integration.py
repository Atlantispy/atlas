"""Actual queries and durable storage through the composed scheduler adapter.

The scheduling parent is a bounded control fixture; no workers or full workflow
are launched. The geometry, query validation, source identity, bytes, cache and
rolling schedule are actual successor implementations loaded from real files.
"""
from fractions import Fraction as Q
import gc
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
BASE = HERE.parent/'runtime-integration-r1'
WORKSPACE = HERE.parents[3]
HEAT = HERE.parents[2]/'heat-repair-20261007'
PARTS = HERE/'endpoint-checkpoints'
sys.path.insert(0, str(PARTS))
from patch_endpoint_seam import candidate_sources as query_sources
from patch_endpoint_scheduler import candidate_sources as scheduler_sources
from patch_ale_checkpoints import candidate_source as ale_source

temporary = None


def setUpModule():
    global temporary, G, V, E, S, Checkpoints, Queries, Budget, Context
    if 'atlas_tectonics' in sys.modules:
        raise RuntimeError('fresh process required for composed checkpoint integration')
    temporary = tempfile.TemporaryDirectory(prefix='.endpoint-compose-', dir=WORKSPACE)
    destination = Path(temporary.name)/'src/atlas_tectonics'
    source = BASE/'runtime-src/atlas_tectonics'
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    edits = {**query_sources(source), **scheduler_sources(source),
             'integration_differential_ale.py': ale_source(source)}
    for name, text in edits.items():
        (destination/name).write_text(text, encoding='utf8')
    sys.path[:0] = [str(destination.parent), str(BASE/'ram'), str(BASE/'helpers'), str(HEAT)]
    G = importlib.import_module('atlas_tectonics.integration_differential_geometry')
    V = importlib.import_module('atlas_tectonics.integration_volume')
    E = importlib.import_module('atlas_tectonics.integration_component_volume_auto')
    S = importlib.import_module('atlas_tectonics.integration_parallel_selection')
    Checkpoints = importlib.import_module('atlas_tectonics.integration_endpoint_checkpoints').EndpointCheckpoints
    Queries = importlib.import_module('atlas_tectonics.integration_component_volume_batch').ComponentVolumeQueries
    Budget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    Context = importlib.import_module('atlas_tectonics.reuse').ExecutionContext


def tearDownModule():
    if temporary is not None:
        temporary.cleanup()


def fixture(budget):
    box = V.CartesianCell((Q(-1, 10), 9, Q(-1, 10)), (Q(1, 10), Q(46, 5), Q(1, 10)), budget=budget)
    layer = V.RadialLayer(10, 0, 3, budget=budget)
    return G._issue(G.DifferentialSupport, dict(voxel=box.record(), radial_layer=layer.record(),
        duration_s=G._qtext(Q(1)), start_time_s=G._qtext(Q(0)), end_time_s=G._qtext(Q(1)),
        constraints={'cut': dict(kind='fixed-plane', normal=G._store_vec((1, 0, 0)), offset=G._qtext(Q(0)))},
        components=[dict(logical_cell_id=key, parent_cell_id=key,
            constraints=[['cut', sign]], partition_path=[])
            for key, sign in zip(('a'*64, 'b'*64), (1, -1), strict=True)]), budget)


def controller(budget, context):
    parent = SimpleNamespace(policy=S.InterfaceParallelPolicy(minimum_seconds=1e9),
        budget=budget, code='0'*64, admitted=True,
        observer=SimpleNamespace(instrumented=False), store={'bindings': {}},
        leaves=1, context=lambda: context,
        decision={'notes': [], 'route': 'serial', 'reason': None, 'detail': None})
    return E.AutomaticEndpoints(parent, Q(1))


class EndpointRestartIntegrationTests(unittest.TestCase):
    def test_actual_hit_miss_next_support_and_exact_bytes(self):
        budget = Budget(64 << 20, max_predicate_work_units=1000000)
        support = fixture(budget)
        directory = Path(temporary.name)/'saved'
        directory.mkdir()
        keys = ('a'*64, 'b'*64)
        results = {}
        with Context('reference') as context:
            with Checkpoints(directory, context=context, budget=budget) as checkpoint:
                with Queries(support, budget=budget) as queries:
                    for key in keys:
                        for endpoint in ('start', 'end'):
                            results[key, endpoint] = queries.measure(key, endpoint=endpoint,
                                max_width_m3=Q(1), max_leaves=1, positive_witness=True,
                                _checkpoint=checkpoint if key == keys[0] else None)._json
                self.assertEqual(checkpoint.written, 2)
            with Checkpoints(directory, context=context, budget=budget) as checkpoint:
                control = controller(budget, context)
                self.assertIsNotNone(control.schedule)
                control.prepare((support,))
                for pass_number in range(2):
                    control.bind_support(support, support.record())
                    with Queries(support, budget=budget) as queries:
                        for key in keys:
                            for endpoint in ('start', 'end'):
                                raw = E.measure_endpoint(queries, control, key, endpoint=endpoint,
                                    max_width_m3=Q(1), max_leaves=1, positive_witness=True,
                                    _funded=control.claim, _checkpoint=checkpoint)._json
                                self.assertEqual(raw, results[key, endpoint])
                    self.assertEqual(len(control.order), 0)
                    self.assertEqual(control.schedule.position, 4*(pass_number+1))
                self.assertEqual((checkpoint.hits, checkpoint.written), (6, 2))
                self.assertEqual(control.checkpoint_hits, 6)
                self.assertEqual(sum(row[1] for row in control.rows.values()), 2)
                self.assertIsNone(control.session)
                control.close()
                self.assertIsNone(control.schedule.stopped)
        support = checkpoint = queries = control = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0, budget.statistics())


if __name__ == '__main__':
    unittest.main()
