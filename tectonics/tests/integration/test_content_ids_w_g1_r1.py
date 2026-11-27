"""Unit W g1 (issue 96), T-2/T-3: workflow/history/process identifiers hash content, not code identity.
  python -B -I test_content_ids_w_g1_r1.py <package parent folder>
Constructed: w09_erosion (plan, state, T-3 store refusal), w09_water (plan, state), w08 output_id, underthrust._id.
Record-level (construction too heavy): the remaining sites go through the module's own id function, and the
issue/re-make pairs are checked to share one expression across their files."""
import inspect
import sys
import types
import unittest

import numpy as np

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))
from atlas_tectonics.mechanics import assembly, evolving_flexure  # noqa: E402
from atlas_tectonics.codecs import regional_checkpoint  # noqa: E402
from atlas_tectonics.regional import execution as regional_execution  # noqa: E402
from atlas_tectonics.history import tectonic_history  # noqa: E402
from atlas_tectonics.codecs import tectonic_history_codec  # noqa: E402
from atlas_tectonics.subduction import underthrust  # noqa: E402
from atlas_tectonics.integration.workflows import drained_column_workflow as w03_workflow, prescribed_support_workflow as w04_workflow, spreading_and_margin_workflow as w06_workflow, regional_mechanics_workflow as w07_workflow  # noqa: E402
from atlas_tectonics.history import finite_stock_history as w08_workflow  # noqa: E402
from atlas_tectonics.surface import erosion as w09_erosion, water as w09_water  # noqa: E402
from atlas_tectonics.integration.reuse import content_record  # noqa: E402

A, B = 'a'*64, 'b'*64


def _fake_context(identity):
    class Ctx:
        def __init__(self, *_): self.identity = identity
        def verify(self): pass
        def close(self): pass
    return Ctx


class _Store:
    def __init__(self): self.rows = {}
    def put(self, key, arrays, meta, publication_check=None): self.rows[key] = (dict(arrays), meta)
    def metadata(self, key): return self.rows.get(key, (None, None))[1]
    def get(self, key, budget=None): return self.rows.get(key, (None, None))[0]


class Patched:
    def __init__(self, module, identity): self.module, self.identity = module, identity
    def __enter__(self):
        self.old = self.module.ExecutionContext
        self.module.ExecutionContext = _fake_context(self.identity)
    def __exit__(self, *_): self.module.ExecutionContext = self.old


def _line(module, snippet):
    lines = [x for x in inspect.getsource(module).splitlines() if snippet in x]
    assert len(lines) == 1, (module.__name__, snippet, lines)
    return lines[0]


class Erosion(unittest.TestCase):
    def model(self, identity, porosity=0.4):
        tag = w09_erosion.ErosionTag('t', 2700., 0., 0., 'o', 'ref')
        with Patched(w09_erosion, identity):
            return w09_erosion.PreparedErosion([1., 0.], [1, -1], [1., 1.], [0., 0.], [tag],
                rock_erodibility=[[1e-3], [0.]], sediment_erodibility=[1e-3, 0.], porosity=porosity,
                frame_id='f', datum_id='d', source_id='s')

    def test_plan_and_state_ids_follow_content_only(self):
        a, b, c = self.model(A), self.model(B), self.model(A, porosity=0.3)
        self.assertEqual(a.plan_id, b.plan_id)
        self.assertNotEqual(a.plan_id, c.plan_id)
        rock = np.array([[[5.]], [[0.]]])
        self.assertEqual(a.initialise(rock).state_id, b.initialise(rock).state_id)
        self.assertNotEqual(a.initialise(rock).state_id, a.initialise(2*rock).state_id)

    def test_t3_checkpoint_of_another_code_identity_is_refused(self):
        a = self.model(A)
        store = _Store()
        object.__setattr__(a, 'store', store)
        key = a.checkpoint(a.initialise(np.array([[[5.]], [[0.]]])))
        self.assertEqual(store.metadata(key)['execution'], A)
        self.assertEqual(a.restore(key).state_id, store.metadata(key)['state_id'])


class Water(unittest.TestCase):
    def state(self, execution_id, water=1.):
        return w09_water.WaterState([water], time_s=0., subsurface_m3=0., evaporated_m3=0., exported_m3=0.,
            supplied_m3=0., initial_total_m3=water, accepted_intervals=0, geometry_id='g', execution_id=execution_id)

    def test_state_id(self):
        self.assertEqual(self.state(A).state_id, self.state(B).state_id)
        self.assertNotEqual(self.state(A).state_id, self.state(A, 2.).state_id)
        self.assertNotEqual(self.state(A).descriptor(), self.state(B).descriptor())  # record keeps the field

    def test_plan_id(self):
        def model(identity, bed=1.):
            with Patched(w09_water, identity):
                return w09_water.PreparedWater([bed, 0.], [1., 0.], [(0, 1)], [1.], [1],
                                               frame_id='f', datum_id='d', source_id='s')
        self.assertEqual(model(A).plan_id, model(B).plan_id)
        self.assertNotEqual(model(A).plan_id, model(A, 2.).plan_id)


class W08Output(unittest.TestCase):
    def test_output_id(self):
        def out(execution, plan='p'):
            g = types.SimpleNamespace(geometry_id='g')
            return types.SimpleNamespace(descriptor=lambda: dict(plan_id=plan, execution=execution),
                inventory=types.SimpleNamespace(inventory_id='i'), polygons=[g], reference_polygons=[g])
        f = w08_workflow.W08Output._output_id
        self.assertEqual(f(out(A), 'd'), f(out(B), 'd'))
        self.assertNotEqual(f(out(A), 'd'), f(out(A, 'q'), 'd'))
        self.assertIn('content_record(self._binding)', _line(w08_workflow, 'self.plan_id = _hash('))


class Underthrust(unittest.TestCase):
    def test_helper_issues_and_codec_remakes_content_ids(self):
        for f in (underthrust._id, tectonic_history_codec._under_id):  # plan :407, state :533, codec :152
            self.assertEqual(f(dict(execution_id=A, t=1.), b'x'), f(dict(execution_id=B, t=1.), b'x'))
            self.assertNotEqual(f(dict(execution_id=A, t=1.), b'x'), f(dict(execution_id=A, t=1.), b'y'))


class RecordLevel(unittest.TestCase):
    """Inline issue sites: the module's id function over the converted record; pairs share one expression."""
    def same(self, f, field, **content):
        self.assertEqual(f(content_record(dict(content, **{field: A}))), f(content_record(dict(content, **{field: B}))))
        self.assertNotEqual(f(content_record(dict(content, **{field: A}))),
                            f(content_record(dict(content, x=2, **{field: A}))))

    def test_w03_w04_w06_w07_history_inline_sites(self):
        for module, snippet, f, field in (
                (w03_workflow, "'state_id', _id(", w03_workflow._id, 'execution_id'),
                (w04_workflow, 'self.plan_id = _id(', w04_workflow._id, 'execution'),
                (w04_workflow, 'result_id=_id(', lambda r: w04_workflow._id(r, b'p'), 'execution_id'),
                (evolving_flexure, 'result_id=_id(', lambda r: w04_workflow._id(r, b'p'), 'execution_id'),
                (w06_workflow, 'self.plan_id = ', lambda r: w06_workflow.hashlib.sha256(w06_workflow._json(r)).hexdigest(),
                 'execution'),
                (w07_workflow, 'self.plan_id=_hash(', w07_workflow._hash, 'execution'),
                (w09_erosion, 'self.plan_id = _hash(', w09_erosion._hash, 'execution'),
                (tectonic_history, 'self.plan_id = _hash(', tectonic_history._hash, 'execution'),
                (tectonic_history, '_hash(content_record(record))', tectonic_history._hash, 'execution')):
            with self.subTest(module=module.__name__, snippet=snippet):
                self.assertIn('content_record(', _line(module, snippet))
                self.same(f, field, a=1)
        # Re-makes use the issuer's expression.
        self.assertIn('_w04_id(content_record(d),', _line(tectonic_history_codec, 'W04 intrinsic') and
                      _line(tectonic_history_codec, 'out._payload+out._wet+out._absolute'))

    def test_regional_plan_id_same_value_at_all_four_sites(self):
        definition = dict(nx=4, material_source='m')
        issue = regional_execution._hash(content_record({'definition': definition, 'context': A}))
        codec = regional_checkpoint._hash(regional_checkpoint._json(content_record(dict(definition=definition, context=B))))
        w07 = w07_workflow._hash(content_record(dict(definition=definition, context=B)))
        self.assertEqual(issue, codec); self.assertEqual(issue, w07)
        self.assertNotEqual(issue, regional_execution._hash(content_record({'definition': dict(definition, nx=5),
                                                                            'context': A})))
        src = inspect.getsource(regional_execution)
        self.assertEqual(src.count("_plan_id = _hash(content_record({'definition'"), 1)
        self.assertEqual(src.count("_plan_id=_hash(content_record({'definition'"), 1)
        self.assertIn("content_record(dict(definition=definition,context=m['context_id']))",
                      _line(tectonic_history_codec, "mr['plan_id'] !="))

    def test_assembly_context_record_is_kept_and_ids_are_content_only(self):
        # E-15: the world/scenario record under 'context' is content and stays in the hash.
        ctx = assembly._context(dict.fromkeys(assembly.CONTEXT_KEYS, 'w'))
        rec = lambda code, c: dict(schema='s', context=c, execution_id=code, native_owner_binding=dict(execution_id=code))
        self.assertEqual(assembly._hash(content_record(rec(A, ctx))), assembly._hash(content_record(rec(B, ctx))))
        other = assembly._context(dict.fromkeys(assembly.CONTEXT_KEYS, 'v'))
        self.assertNotEqual(assembly._hash(content_record(rec(A, ctx))), assembly._hash(content_record(rec(A, other))))
        for snippet in ('product_id=_hash(content_record(record))', 'pid = _hash(content_record(record))',
                        'self.plan_id = _hash(content_record(json.loads(self._definition)))',
                        'product_id=_hash(content_record(base))'):
            _line(assembly, snippet)


class RegionalResult(unittest.TestCase):
    """E-16/E-17: result_id is made from content_metadata at the issuer and at both checkpoint re-makers."""
    def snapshot(self, code, value=0.0, schema='atlas.regional-mechanical-snapshot.v1', **extra):
        meta = dict(schema=schema, iterations=3, context_id=code, **extra)
        return regional_execution.RegionalMechanicalSnapshot(meta, {'f': np.full(2, value)})

    def test_code_identity_leaves_result_id_and_content_does_not(self):
        self.assertEqual(self.snapshot(A).result_id, self.snapshot(B).result_id)
        self.assertNotEqual(self.snapshot(A).result_id, self.snapshot(A, 1.0).result_id)

    def test_heat_call_table_drops_code_under_other_names(self):
        call = lambda code, src=A: self.snapshot(code, schema='atlas.private.composed-owner-call.r1',
            execution=dict(execution_identity=code), private_sources={'m.py': src},
            loaded_dependencies=dict(identity=code, schema='x'))
        self.assertEqual(call(A).result_id, call(B, src=B).result_id)
        heat = lambda code: self.snapshot(None, schema='atlas.private.composed-heat-advance.r12',
            caller_snapshot=dict(execution=dict(execution_identity=code),
                                 private_sources={'m.py': code}, loaded_dependencies=dict(identity=code)),
            loaded_dependencies=dict(identity=code))
        self.assertEqual(heat(A).result_id, heat(B).result_id)
        saved = regional_execution.CONTENT_DROPPED.pop('atlas.private.composed-owner-call.r1')
        try:  # with the row taken out the code identity moves the id again
            self.assertNotEqual(call(A).result_id, call(B, src=B).result_id)
        finally:
            regional_execution.CONTENT_DROPPED['atlas.private.composed-owner-call.r1'] = saved

    def test_identity_metadata_is_unchanged_for_admission(self):
        meta = dict(schema='atlas.regional-mechanical-snapshot.v1', iterations=3, context_id=A)
        self.assertEqual(regional_execution.identity_metadata(meta), dict(schema=meta['schema'], context_id=A))

    def test_checkpoint_remakers_use_content_metadata(self):
        self.assertEqual(inspect.getsource(regional_checkpoint).count("content_metadata("), 2)
        self.assertNotIn('identity_metadata', inspect.getsource(regional_checkpoint))

if __name__ == '__main__':
    unittest.main()
