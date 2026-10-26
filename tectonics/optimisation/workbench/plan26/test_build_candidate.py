"""Bounded controls on the constructed public component; no science imports."""
import ast
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_candidate as B  # noqa: E402


def definitions(raw):
    return {node.name: node for node in ast.parse(raw).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


def same(node):
    return ast.dump(node, include_attributes=False)


class SourceComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(os.environ['ATLAS_REPO'])
        cls.parent_root = Path(os.environ['ATLAS_PLAN26_PARENT'])
        cls.candidate = Path(os.environ['ATLAS_PLAN26_CANDIDATE'])
        _, cls.u, cls.mapping, cls.applier = B.load(cls.repo)
        cls.parent_record = json.loads((cls.parent_root/'SOURCE-MANIFEST.json').read_bytes())
        cls.before = B.validate_parent(cls.parent_record, cls.mapping, cls.u)
        cls.after_record = json.loads((cls.candidate/'SOURCE-MANIFEST.json').read_bytes())
        cls.raws = {name:(cls.parent_root/name).read_bytes() for name in B.MEMBERS}
        cls.outputs = B.derive(cls.raws, cls.mapping, cls.u, cls.applier)

    def test_actual_694_member_construction_and_unrelated_bytes(self):
        actual = {p.relative_to(self.candidate).as_posix():B.digest(p.read_bytes())
                  for p in self.candidate.rglob('*') if p.is_file() and p!=self.candidate/'SOURCE-MANIFEST.json'}
        self.assertEqual(actual,self.after_record['files'])
        self.assertEqual(len(actual),694)
        self.assertEqual({n for n in actual if actual[n]!=self.before[n]},set(B.MEMBERS))
        self.assertTrue(all(actual[n]==pin for n,pin in self.before.items() if n not in B.MEMBERS))
        self.assertTrue(all(self.after_record[k] is False for k in B.FLAGS))
        self.assertEqual(self.after_record['status'],'INTEGRATED_SOURCE_COMPONENT_NOT_QUALIFIED')

    def test_wrong_parent_and_wrong_input_pins_refuse(self):
        forged=copy.deepcopy(self.parent_record)
        forged['selection_sha256']='0'*64
        with self.assertRaises(ValueError):B.validate_parent(forged,self.mapping,self.u)
        forged=copy.deepcopy(self.parent_record)
        forged['runtime_admission']=True
        with self.assertRaises(ValueError):B.validate_parent(forged,self.mapping,self.u)
        forged=dict(self.raws)
        forged[B.MEMBERS[0]]+=b'\n'
        with self.assertRaises(ValueError):B.derive(forged,self.mapping,self.u,self.applier)

    def test_changed_diff_pin_and_occupied_output_refuse(self):
        forged=copy.deepcopy(self.mapping)
        forged['rows'][0]['diff_sha256']='0'*64
        with self.assertRaises(ValueError):B.derive(self.raws,forged,self.u,self.applier)
        with tempfile.TemporaryDirectory(dir=self.candidate.parent) as folder:
            out=Path(folder)/'occupied';out.mkdir();(out/'keep').write_bytes(b'kept')
            with self.assertRaises((ValueError,FileExistsError)):B.materialise(self.repo,self.parent_root,out)
            self.assertEqual((out/'keep').read_bytes(),b'kept')

    def test_output_overlap_refuses_before_any_write_or_copy(self):
        for root in (self.parent_root, B.HERE, self.repo):
            for out in (root, root/'new'/'output',
                        root/'unused'/'..'/'new'/'output', root.parent):
                with self.subTest(root=root, output=out):
                    with (mock.patch.object(B, 'load') as load,
                          mock.patch.object(Path, 'mkdir') as mkdir,
                          mock.patch.object(B.tempfile, 'TemporaryDirectory') as temporary,
                          mock.patch.object(B.shutil, 'copytree') as copytree):
                        with self.assertRaisesRegex(ValueError, 'Output overlaps read-only source'):
                            B.materialise(self.repo, self.parent_root, out)
                        load.assert_not_called()
                        mkdir.assert_not_called()
                        temporary.assert_not_called()
                        copytree.assert_not_called()

    def test_nested_parent_manifest_refuses_before_staging(self):
        with tempfile.TemporaryDirectory(dir=self.candidate.parent) as folder:
            root=Path(folder)/'parent'
            B.shutil.copytree(self.parent_root,root)
            nested=root/'helpers'/'SOURCE-MANIFEST.json'
            nested.write_bytes(b'{}\n')
            out=Path(folder)/'out'
            with (mock.patch.object(Path, 'mkdir') as mkdir,
                  mock.patch.object(B.tempfile, 'TemporaryDirectory') as temporary,
                  mock.patch.object(B.shutil, 'copytree') as copytree):
                with self.assertRaisesRegex(ValueError, 'Parent file inventory'):
                    B.materialise(self.repo,root,out)
                mkdir.assert_not_called()
                temporary.assert_not_called()
                copytree.assert_not_called()
            self.assertFalse(out.exists())
            self.assertEqual(nested.read_bytes(),b'{}\n')

    def test_nested_stage_manifest_refuses_before_publication(self):
        real_copytree=B.shutil.copytree
        def inject_nested_manifest(source,target):
            with mock.patch.object(B.shutil, 'copytree', real_copytree):
                result=real_copytree(source,target)
            (Path(target)/'helpers'/'SOURCE-MANIFEST.json').write_bytes(b'{}\n')
            return result
        with tempfile.TemporaryDirectory(dir=self.candidate.parent) as folder:
            out=Path(folder)/'out'
            with mock.patch.object(B.shutil, 'copytree', side_effect=inject_nested_manifest):
                with self.assertRaisesRegex(ValueError, 'beyond its three declared members'):
                    B.materialise(self.repo,self.parent_root,out)
            self.assertFalse(out.exists())
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_unrelated_tier1_query_and_source_definitions_preserved(self):
        changed={'reopen_prepared_restart.py':{'validate_producer_receipt','validate_reopen_receipt'},
                 'reopen_fresh_restart.py':{'_producer_receipt','validate_reopen_receipt'},
                 'run_prepared_restart.py':{'RestartSources'}}
        for member in B.MEMBERS:
            before=definitions(self.raws[member]);after=definitions(self.outputs[member])
            for name,node in before.items():
                if name not in changed[Path(member).name]:self.assertEqual(same(node),same(after[name]),(member,name))
        before=definitions(self.raws[B.MEMBERS[2]])['RestartSources']
        after=definitions(self.outputs[B.MEMBERS[2]])['RestartSources']
        a={x.name:x for x in before.body if isinstance(x,ast.FunctionDef)}
        b={x.name:x for x in after.body if isinstance(x,ast.FunctionDef)}
        for name,node in a.items():
            if name!='check_imported':self.assertEqual(same(node),same(b[name]),name)

    def test_four_actual_callers_use_one_shared_validator(self):
        for member,names,target in [(B.MEMBERS[0],['validate_producer_receipt','validate_reopen_receipt'],'retained_release_agrees'),
                                    (B.MEMBERS[1],['_producer_receipt','validate_reopen_receipt'],'retained_release_agrees')]:
            tree=definitions(self.outputs[member])
            for name in names:
                calls=[n.func for n in ast.walk(tree[name]) if isinstance(n,ast.Call)]
                self.assertEqual(sum(isinstance(f,ast.Name) and f.id==target or
                                     isinstance(f,ast.Attribute) and f.attr==target for f in calls),1,(member,name))

    def test_generated_shared_validator_acceptance_and_refusals(self):
        names=('retained_peak_limit','retained_index_peak','retained_lease_bound','retained_release_agrees')
        nodes=definitions(self.outputs[B.MEMBERS[0]])
        scope={}
        exec(compile(ast.Module(body=[nodes[n] for n in names],type_ignores=[]),'<public retained-release functions>','exec'),scope)
        capacity=6*6336;index=8192+6*1024;fixed=index+5120
        before=dict(limit_bytes=(256<<20)+capacity,scope_id='scope',retained_bytes=6336,
                    peak_limit_bytes=(256<<20)+capacity,peak_retained_bytes=fixed+capacity,
                    fixed_peak_bytes=fixed,purpose_peak_bytes={'retained:partition-carrier-index':index},
                    partition_carrier_pools=[{'limit_bytes':capacity}])
        after=copy.deepcopy(before);after.update(limit_bytes=256<<20,retained_bytes=0,partition_carrier_pools=[])
        check=scope['retained_release_agrees'];self.assertTrue(check(before,after))
        for label,edit in [
            ('missing control charge',lambda a,b:(a.update(fixed_peak_bytes=index+5119),b.update(fixed_peak_bytes=index+5119))),
            ('off-grid capacity',lambda a,b:(a.update(peak_limit_bytes=(256<<20)+capacity+1),b.update(peak_limit_bytes=(256<<20)+capacity+1))),
            ('off-grid index',lambda a,b:(a['purpose_peak_bytes'].update({'retained:partition-carrier-index':index+1}),b['purpose_peak_bytes'].update({'retained:partition-carrier-index':index+1}))),
            ('retained after close',lambda a,b:b.update(retained_bytes=1)),
            ('floating limit',lambda a,b:a.update(limit_bytes=float(a['limit_bytes']))),
            ('before peak exceeds its lease',lambda a,b:(a.update(peak_retained_bytes=fixed+capacity+1),b.update(fixed_peak_bytes=fixed+1,peak_retained_bytes=fixed+capacity+1))),
        ]:
            a,b=copy.deepcopy(before),copy.deepcopy(after);edit(a,b)
            with self.subTest(label=label):self.assertFalse(check(a,b))

    def test_narrow_h3_route_is_connected_and_protected_pins_unchanged(self):
        raw=self.outputs[B.MEMBERS[2]];tree=ast.parse(raw);defs=definitions(raw)
        methods={n.name:n for n in defs['RestartSources'].body if isinstance(n,ast.FunctionDef)}
        self.assertIn('_sealed_h3',methods)
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='_sealed_h3'
                            for n in ast.walk(methods['check_imported'])))
        constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                   and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id.startswith('H3_')}
        self.assertEqual(constants['H3_SHA256'],'18317500e239fbd9c6359c0abe110969495bdd356f88d38b92b3c1f2510cd0d5')
        self.assertEqual(constants['H3_KERNEL_SHA256'],'6ae1a0ab413dd36f4544a147aedc0f58e3347bf52501a7f205a25e9c09b62eeb')
        self.assertEqual(self.before['helpers/private_heat_compiled_dot_r1.py'],constants['H3_SHA256'])
        self.assertEqual(self.before['helpers/private_heat_certification_kernel_r1.py'],constants['H3_KERNEL_SHA256'])


if __name__=='__main__':unittest.main()
