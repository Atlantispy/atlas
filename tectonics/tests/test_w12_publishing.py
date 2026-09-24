"""All supported W12 typed output publication seams, not physical revalidation."""
import hashlib
from dataclasses import fields as dataclass_fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from atlas_tectonics.assembly import (publish_workflow_output, read_product, _verify_native_bindings,
                                     _native_frame_binding)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
from atlas_tectonics.workflow_ports import describe_workflow_output
from atlas_tectonics.w04_workflow import PreparedW04Support
from atlas_tectonics.w06_workflow import PreparedW06Workflow
from atlas_tectonics.extension_workflow import PreparedExtensionWorkflow
from test_w03_workflow import workflow_fixture, initialise
from test_w04_workflow import surface, POLICY as W04_POLICY
import test_w05_workflow as w05_fixture
from test_w07_workflow import make_workflow_fixture as w07_fixture
from test_w08_workflow import make_workflow_fixture as w08_fixture
from test_tectonic_history import make_history_fixture
from w06_workflow_case import route_fixture


CONTEXT = dict(world_id='synthetic-fixture',snapshot_id='w12-publication-seam',calendar_id='declared-native-epoch',
               spatial_frame_id='native-support',vertical_reference='native-datum',scenario_id='typed-export-test')
SCOPE = 'bounded supplied fixture; preserve native support and ownership; no added scientific acceptance'
LIMITS = StoreLimits(4096,8<<20,32<<20,max_manifest_bytes=1<<20,sqlite_cache_bytes=65536,verified_cache_entries=32)


class W12PublishingTests(unittest.TestCase):
    def output_context(self, description, owner=None):
        frames = set()
        def visit(value):
            if type(value) is dict:
                for key,item in value.items():
                    if key == 'frame_id' and type(item) is str and item:
                        frames.add(item)
                    visit(item)
            elif type(value) is list:
                for item in value:
                    visit(item)
        visit(description['descriptor'])
        if owner is not None and not owner.is_margin:
            frames.add(owner.prepared.spreading.grid.frame_id)
        self.assertLessEqual(len(frames),1,'fixture needs an explicit multi-frame mapping')
        return dict(CONTEXT,spatial_frame_id=next(iter(frames)) if frames else 'native-frame-unexposed')

    def roundtrip(self, output, route, *, budget=None, native_owner=None):
        """Compare every descriptor/spec and byte with the declared store codec policy."""
        expected = describe_workflow_output(output)
        self.assertEqual(expected['route'],route)
        context = self.output_context(expected,native_owner)
        budget = WorkBudget(128<<20) if budget is None else budget
        baseline = budget.reserved_bytes
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'exports.sqlite'
            with ArrayStore(path,limits=LIMITS,compression=Compression(),budget=budget) as store:
                product = publish_workflow_output(output,store,context=context,scope=SCOPE,budget=budget,native_owner=native_owner)
                self.assertEqual(store.metadata(product['product_id']),product)
            # A newly opened store exercises durable decode rather than its live LRU.
            with ArrayStore(path,limits=LIMITS,compression=Compression(),budget=budget) as store:
                actual = read_product(store,product,budget=budget,expected_context=context)
                self.assertEqual(set(actual),set(expected['fields']))
                self.assertEqual(product['route'],route)
                self.assertEqual(product['source_output_id'],expected['source_output_id'])
                self.assertEqual(product['native_descriptor'],expected['descriptor'])
                self.assertEqual(product['dependencies'],expected['dependencies'])
                self.assertFalse(product['dependencies']['export_is_restart'])
                if native_owner is not None:
                    self.assertEqual(product['native_owner_binding']['execution_id'],native_owner.execution_id)
                    self.assertEqual(product['native_owner_binding']['plan_id'],native_owner.plan_id)
                self.assertEqual(product['native_frame_binding']['frame_identity_checked'],
                                 context['spatial_frame_id'] != 'native-frame-unexposed')
                for name,native in expected['fields'].items():
                    stored = actual[name]
                    # ArrayStore's established normal form preserves numerical
                    # values but canonicalises byte order and floating signed zero.
                    canonical = np.array(native,dtype=native.dtype.newbyteorder('<'),order='C',copy=True)
                    if canonical.dtype.kind == 'f':
                        canonical[canonical == 0] = 0.
                    self.assertEqual(stored.dtype,canonical.dtype,name)
                    self.assertEqual(stored.shape,canonical.shape,name)
                    self.assertEqual(stored.tobytes(),canonical.tobytes(),name)
                    self.assertFalse(stored.flags.writeable,name)
                    self.assertEqual(product['fields'][name],dict(expected['field_specs'][name],
                        dtype=canonical.dtype.str,shape=list(canonical.shape),
                        sha256=hashlib.sha256(canonical.tobytes()).hexdigest()),name)
        self.assertEqual(budget.reserved_bytes,baseline)

    def test_w01_w02_and_w03_native_bindings_and_fields(self):
        state = workflow_fixture(cells=2,length_m=2.)
        self.roundtrip(state,'w01-w02-regional.v1')
        self.roundtrip(initialise(state),'w03-columns.v1')

    def test_w04_dry_water_mask_and_absolute_reference_output(self):
        state = initialise(workflow_fixture(cells=8))
        supplied = surface(state,volumes=np.r_[np.zeros(4),np.full(4,state.reservoir_fluid_m3/4)])
        with PreparedW04Support(state,supplied,W04_POLICY) as plan:
            result = plan.solve(state,supplied)
        self.roundtrip(result,'w04-support.v1')

    def test_w05_motion_exchange_support_and_execution_alias(self):
        budget = WorkBudget(128<<20)
        helper = w05_fixture.W05WorkflowTests()
        with ExecutionContext('reference') as context:
            helper.context = context
            with helper.motion(budget) as motion:
                with PreparedExtensionWorkflow(motion,w05_fixture.POLICY,(0.,1.),budget=budget) as plan:
                    self.roundtrip(plan.run(through=0),'w05-extension.v1',budget=budget)

    def test_w06_constant_history_and_inherited_margin(self):
        for route in ('constant','history','margin'):
            with self.subTest(route=route):
                budget = WorkBudget(128<<20)
                with route_fixture(route,budget=budget,cells=4) as (producer,policy,times):
                    with PreparedW06Workflow(producer,times,budget=budget,margin_policy=policy) as plan:
                        self.roundtrip(plan.run(through=0),'w06-'+route+'.v1',budget=budget,native_owner=plan)

    def test_w06_missing_foreign_closed_unretained_and_changed_output_refuse(self):
        budget = WorkBudget(128<<20)
        with TemporaryDirectory() as tmp, route_fixture('constant',budget=budget,cells=4) as (producer,policy,times):
            with ArrayStore(Path(tmp)/'export.sqlite',limits=LIMITS,compression=Compression(),budget=budget) as store:
                with PreparedW06Workflow(producer,times,budget=budget) as plan:
                    out = plan.run(through=0)
                    context = self.output_context(describe_workflow_output(out),plan)
                    args = dict(context=context,scope=SCOPE,budget=budget)
                    with self.assertRaisesRegex(TectonicsError,'native_owner'):
                        publish_workflow_output(out,store,**args)
                    with self.assertRaisesRegex(TectonicsError,'exact W06'):
                        publish_workflow_output(out,store,native_owner=object(),**args)
                    with PreparedW06Workflow(producer,times[:2],budget=budget) as other:
                        with self.assertRaisesRegex(TectonicsError,'different native owner'):
                            publish_workflow_output(out,store,native_owner=other,**args)
                    missing = replace(out,output_index=1,checkpoint_id=plan.checkpoint_id(1))
                    with self.assertRaisesRegex(TectonicsError,'not retained or stored'):
                        publish_workflow_output(missing,store,native_owner=plan,**args)
                    changed = object.__new__(type(out.state))
                    for field in dataclass_fields(out.state):
                        object.__setattr__(changed,field.name,getattr(out.state,field.name))
                    payload = np.frombuffer(out.state._cells,dtype=np.float64).copy()
                    payload[0] += 1.
                    object.__setattr__(changed,'_cells',payload.tobytes())
                    with self.assertRaisesRegex(TectonicsError,'field differs'):
                        publish_workflow_output(replace(out,state=changed),store,native_owner=plan,**args)
                    self.assertIs(plan._current,out)
                with self.assertRaisesRegex(TectonicsError,'closed'):
                    publish_workflow_output(out,store,native_owner=plan,**args)

    def test_explicit_native_frame_conflicts_refuse_without_inferred_mapping(self):
        output = workflow_fixture(cells=2,length_m=2.)
        context = self.output_context(describe_workflow_output(output))
        context['spatial_frame_id'] += '-wrong'
        with TemporaryDirectory() as tmp:
            budget = WorkBudget(128<<20)
            with ArrayStore(Path(tmp)/'export.sqlite',limits=LIMITS,compression=Compression(),budget=budget) as store:
                with self.assertRaisesRegex(TectonicsError,'spatial frame differs'):
                    publish_workflow_output(output,store,context=context,scope=SCOPE,budget=budget)
        with self.assertRaisesRegex(TectonicsError,'multiple native frames'):
            _native_frame_binding(dict(first=dict(frame_id='a'),second=dict(frame_id='b')),CONTEXT)

    def test_w07_steady_thermal_and_surface(self):
        for route in ('steady','thermal','surface'):
            with self.subTest(route=route):
                with w07_fixture(route,nx=4,nz=4,thermal=route=='thermal') as plan:
                    self.roundtrip(plan.run(through=0),'w07-'+route+'.v1')

    def test_w08_joined_stock_geometry_and_execution_alias(self):
        with w08_fixture(parcels=2) as plan:
            self.roundtrip(plan.run(through=0),'w08-joined.v1')

    def test_final_histories_and_standalone_native_results(self):
        for route,kind in (('underthrust','underthrust'),('w04','evolving-w04'),('regional','evolving-regional')):
            with self.subTest(route=route):
                with make_history_fixture(route,cells=4,regional_n=4) as history:
                    out = history.run(through=0)
                    self.roundtrip(out,'tectonic-history-'+kind+'.v1')
                    self.roundtrip(out.result,'tectonic-'+kind+'.v1')

    def test_schema_aliases_do_not_accept_foreign_or_unknown_runtime_bindings(self):
        with ExecutionContext('reference') as reference:
            for schema,key in (('atlas.w05-support-result.v1','execution'),
                               ('atlas.w08-output.v1','execution'),
                               ('atlas.tectonic-history-output.v1','execution'),
                               ('atlas.regional-mechanical-snapshot.v1','context_id')):
                with self.subTest(schema=schema):
                    with self.assertRaisesRegex(TectonicsError,'differs'):
                        _verify_native_bindings(dict(schema=schema,**{key:'0'*64}),reference.identity)
            with self.assertRaisesRegex(TectonicsError,'no verifiable'):
                _verify_native_bindings(dict(schema='unknown-schema',context_id=reference.identity),reference.identity)


if __name__ == '__main__':
    unittest.main()
