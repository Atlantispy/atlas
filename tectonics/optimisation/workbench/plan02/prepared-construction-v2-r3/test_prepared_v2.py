"""Generated-profile receiving and CLI refusal controls; no native store or interval."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE/'receivers'))
import run_prepared_restart as R
import run_fresh_interval as F
import historical_admission as H
import reopen_prepared_restart as READER
import launch_monitored_interval as L
import test_run_prepared_restart as TP

spec = importlib.util.spec_from_file_location('assembler_v2_controls', HERE/'assemble_resumable.py')
A = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = A
spec.loader.exec_module(A)

def encoded(row):
    return (json.dumps(row, sort_keys=True)+'\n').encode()

def digest(raw):
    return sha256(raw).hexdigest()

class Receiving(unittest.TestCase):
    def setUp(self):
        self.fixture = TP.SourceTests('test_inspection_only_has_no_outputs_or_native_imports')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        self.historical = TP.HERE/R.HISTORICAL_RELATIVE
        (self.historical/'native-composed-r7/tectonics/src').mkdir(parents=True, exist_ok=True)
        self.bindings = deepcopy(f.row)
        del self.bindings['schema']
        self.bindings['historical_source_root'] = R.HISTORICAL_RELATIVE+'/native-composed-r7/tectonics/src'
        self.reviewed = f.folder/'reviewed-inputs.json'
        self.reviewed_row = {'fixture':'SOURCE CONTROL ONLY'}
        self.reviewed.write_bytes(encoded(self.reviewed_row))
        self.selection = f.folder/'selection.json'
        self.selection_row = {'fixture':'SOURCE CONTROL ONLY'}
        self.selection.write_bytes(encoded(self.selection_row))
        self.constructor_profile = f.folder/'constructor-profile.json'
        self.fresh_profile = f.folder/'fresh-profile.json'
        self.bootstrap = f.folder/'bootstrap.py'
        self.bootstrap.write_bytes(b'# source-only fixture\n')
        self.composition = dict(stages=[dict(stage='plan31:final-source', module='fixture.py')],
            staged={'plan31:final-source':{}}, completed_query_store='files',
            reviewed_inputs=str(self.reviewed), reviewed_inputs_sha256=R.file_hash(self.reviewed))
        self.receipt = dict(status='PREPARED_SOURCE_NOT_QUALIFIED', input_finality=True, output_finality=True,
            reviewed_inputs=dict(path=str(self.reviewed),sha256=R.file_hash(self.reviewed)),
            bootstrap=dict(path=str(self.bootstrap),sha256=R.file_hash(self.bootstrap)))
        self.derivation = {}
        self.config = {}
        self.calls = 0
        self.repin()

    def store(self, name, row):
        path=self.fixture.folder/name
        path.write_bytes(encoded(row))
        return dict(path=self.fixture.relative(path),sha256=R.file_hash(path))

    def enable_paired(self):
        self.paired=True
        self.bindings['advance_driver']['module']=A.DRIVER_MODULE
        self.fresh_driver=self.fixture.folder/'fixture_fresh_driver.py'
        self.fresh_driver.write_bytes(b'def advance_first_interval(**kwargs):\n    return {"status":"PASS"}\n')
        self.fixture.extra.append(self.fresh_driver)
        self.fixture.write_manifest()
        self.repin()

    def repin(self):
        self.reviewed.write_bytes(encoded(self.reviewed_row))
        self.selection.write_bytes(encoded(self.selection_row))
        self.receipt['reviewed_inputs']=dict(path=str(self.reviewed),sha256=R.file_hash(self.reviewed))
        self.receipt['selection']=dict(path=str(self.selection),sha256=R.file_hash(self.selection))
        self.composition['reviewed_inputs_sha256']=R.file_hash(self.reviewed)
        comp = self.store('composition.json',self.composition)
        manifest=json.loads(self.fixture.manifest.read_bytes())
        manifest['composition']=dict(composition_json=comp['path'],composition_sha256=comp['sha256'])
        self.fixture.manifest.write_bytes(encoded(manifest))
        self.bindings['source_manifest']=dict(path=self.fixture.relative(self.fixture.manifest),
                                             sha256=R.file_hash(self.fixture.manifest))
        emitted_profile = dict(schema=R.PROFILE_SCHEMA, **deepcopy(self.bindings))
        emitted_profile.update(getattr(self,'producer_profile_changes',{}))
        self.constructor_profile.write_bytes(encoded(emitted_profile))
        primary=self.constructor_profile
        if getattr(self,'paired',False):
            fresh=dict(schema=F.PROFILE_SCHEMA,**{k:deepcopy(self.bindings[k]) for k in
                ('workspace','source_manifest','native_root','import_roots','completed_query_limits')},
                modules={name:self.bindings['modules'].get(name,self.fixture.relative(self.fixture.helper))
                         for name in F.FRESH_MODULES},
                advance_driver=dict(module=F.DRIVER,path=self.fixture.relative(self.fresh_driver),
                                    sha256=R.file_hash(self.fresh_driver)),
                output_directory=str(self.fixture.folder/'fresh-attempt'),
                store_directory=str(self.fixture.folder/'fresh-store'),
                completed_query_directory=self.fixture.relative(self.fixture.folder/'fresh-queries'))
            fresh['modules'][A.DRIVER_MODULE]=self.bindings['advance_driver']['path']
            fresh.update(getattr(self,'fresh_profile_changes',{}))
            self.fresh_profile.write_bytes(encoded(fresh))
            primary=self.fresh_profile
            self.receipt['completed_query_store']='files'
            self.receipt['prepared_profile']=getattr(self,'prepared_reference_override',
                dict(path=str(self.constructor_profile),sha256=R.file_hash(self.constructor_profile)))
        self.receipt['profile_sha256']=getattr(self,'receipt_profile_pin_override',R.file_hash(primary))
        self.receipt.update(composition_sha256=comp['sha256'],manifest_sha256=R.file_hash(self.fixture.manifest))
        self.derivation = dict(self.receipt, **{k:v for k,v in self.derivation.items() if k in ('purpose','control')})
        self.derivation.pop('derivation_sha256',None)
        derivation=self.store('derivation.json',self.derivation)
        self.receipt['derivation_sha256']=derivation['sha256']
        receipt=self.store('BUILD-RESULT.json',self.receipt)
        self.config=dict(schema='atlas.prepared-restart-construction.v2',construction_receipt=receipt,
            derivation=derivation,composition=comp,profile=deepcopy(self.bindings),
            constructor_profile=dict(path=self.fixture.relative(self.constructor_profile),
                                     sha256=R.file_hash(self.constructor_profile)),
            compatibility_policy=deepcopy(self.bindings['compatibility_policy']))
        if getattr(self,'paired',False):
            self.config['prepared_profile']=self.config['constructor_profile']
            self.config.update(constructor_profile=dict(path=str(self.fresh_profile),sha256=R.file_hash(self.fresh_profile)),
                fresh_runner=dict(path=str(Path(F.__file__)),sha256=R.file_hash(F.__file__)),
                prepared_runner=dict(path=str(Path(R.__file__)),sha256=R.file_hash(R.__file__)))

    def cli(self, *, writer=False, expected=0):
        self.calls+=1
        config=self.fixture.folder/f'input-{self.calls}.json'
        config.write_bytes(encoded(self.config))
        out=self.fixture.folder/f'generated-{self.calls}.json'
        script=HERE/('write_prepared_profile.py' if writer else 'assemble_resumable.py')
        argv=[sys.executable,'-B',str(script)]
        if writer:
            argv+=['--assembler-sha256',digest((HERE/'assemble_resumable.py').read_bytes())]
        argv+=['--selected-restart',str(config),'--selected-restart-sha256',R.file_hash(config),
               '--profile-output' if writer else '--out',str(out)]
        result=subprocess.run(argv,capture_output=True,text=True,timeout=15,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
        if expected==0:
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'],'PREPARED_RESTART_PROFILE_WRITTEN_NO_RUN_AUTHORITY')
            self.assertTrue(out.is_file())
        else:
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn('CompositionRefused',result.stderr)
            self.assertFalse(out.exists())
        self.assertFalse(Path(self.bindings['output_directory']).exists())
        return out

    def test_generated_profile_consumed_by_runner_reader_launcher(self):
        for writer in (False,True):
            out=self.cli(writer=writer)
            profile=R.RestartProfile.read(out,R.file_hash(out))
            sources=R.RestartSources(profile)
            sources.verify()
            self.assertEqual(sources.query_store(),'files')
            self.assertIs(READER.RUN,R)
            self.assertEqual(R._check_historical_root(sources,H,profile.record()),self.historical.resolve())
            selected,_,_=L.load_runner(out,R.file_hash(out))
            self.assertEqual(selected.PROFILE_SCHEMA,A.PROFILE_SCHEMA)
            self.assertEqual(profile.record()['schema'],'atlas.prepared-restart-launch.v2')
            self.assertEqual(out.read_bytes(),self.constructor_profile.read_bytes())
            class FilesOnly:
                def __init__(self, path): pass
            self.assertEqual(R.query_store_arguments(FilesOnly,sources.query_store()),{})

    def test_purpose_presence_refuses_all_false_values_before_output(self):
        for target in ('receipt','derivation'):
            for value in (None,'',False,0,'REHEARSAL_NOT_FOR_REPLAY'):
                with self.subTest(target=target,value=value):
                    self.receipt.pop('purpose',None)
                    self.derivation.pop('purpose',None)
                    getattr(self,target)['purpose']=value
                    self.repin()
                    self.cli(expected=1)

    def test_status_and_rehearsal_stages_refuse(self):
        self.receipt['status']='REHEARSAL_NOT_FOR_REPLAY'
        self.repin()
        self.cli(expected=1)
        self.receipt['status']='PREPARED_SOURCE_NOT_QUALIFIED'
        self.composition['stages'][0]['stage']='plan31:rehearsal-baseline-h1b'
        self.repin()
        self.cli(expected=1)
        self.composition['stages'][0]['stage']='plan31:final-source'
        self.composition['staged']={'plan31:rehearsal-width-h1w':{}}
        self.repin()
        self.cli(expected=1)

    def test_missing_unknown_and_unavailable_store_refuse(self):
        for value in (None,'unknown','columnar',[],False):
            with self.subTest(value=value):
                m=json.loads(self.fixture.manifest.read_bytes())
                if value is None: m.pop('completed_query_store',None)
                else: m['completed_query_store']=value
                self.fixture.manifest.write_bytes(encoded(m))
                self.repin()
                self.cli(expected=1)
        class Incapable:
            def __init__(self,path):pass
        with self.assertRaises(R.RestartRefused):
            R.query_store_arguments(Incapable,'columnar')

    def test_missing_wrong_outside_root_and_wrong_source_pins_refuse(self):
        original=deepcopy(self.config)
        for value in (None,'','..','elsewhere',str(self.historical)):
            self.config=deepcopy(original)
            if value is None:self.config['profile'].pop('historical_root')
            else:self.config['profile']['historical_root']=value
            self.cli(expected=1)
        for key in ('source_manifest','preparation','compatibility_policy'):
            self.config=deepcopy(original)
            self.config['profile'][key]['sha256']='0'*64
            self.cli(expected=1)

    def test_reparse_refused_before_profile_write(self):
        original=Path.lstat
        def reparse(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==self.historical:
                class Info:
                    st_mode=result.st_mode
                    st_file_attributes=getattr(result,'st_file_attributes',0)|0x400
                return Info()
            return result
        with patch.object(Path,'lstat',reparse), self.assertRaisesRegex(A.CompositionRefused,'reparsed'):
            A.selected_restart_profile(self.config)
        self.assertFalse(Path(self.bindings['output_directory']).exists())

    def test_source_drift_and_extra_native_member_refuse_before_profile_output(self):
        original=self.fixture.helper.read_bytes()
        self.fixture.helper.write_bytes(original+b'# changed source\n')
        self.cli(expected=1)
        self.fixture.helper.write_bytes(original)
        (self.fixture.native/'atlas_tectonics/unselected.py').write_bytes(b'# unselected native source\n')
        self.cli(expected=1)

    def test_external_owner_receipt_and_absolute_runtime_references(self):
        with tempfile.TemporaryDirectory(prefix='owner-W-',dir=HERE) as temporary:
            owner=Path(temporary)
            receipt=owner/'BUILD-RESULT.json'
            receipt.write_bytes(encoded(self.receipt))
            self.assertFalse(receipt.is_relative_to(Path(self.bindings['workspace'])))
            self.config['construction_receipt']=dict(path=str(receipt),sha256=R.file_hash(receipt))
            for key in ('derivation','composition','constructor_profile','compatibility_policy'):
                binding=self.config[key]
                binding['path']=str(Path(self.bindings['workspace'])/binding['path'])
            self.cli()
            # Only explicitly external owner/control records may lie outside T.
            self.config['derivation']=dict(path=str(receipt),sha256=R.file_hash(receipt))
            self.cli(expected=1)

    def test_actual_constructor_profile_pin_bytes_schema_and_bindings_are_required(self):
        original=deepcopy(self.config)
        for fault in ('missing-binding','missing-file','wrong-pin','changed-bytes','changed-binding'):
            with self.subTest(fault=fault):
                self.config=deepcopy(original)
                before=self.constructor_profile.read_bytes()
                if fault=='missing-binding':self.config.pop('constructor_profile')
                elif fault=='missing-file':
                    self.config['constructor_profile']['path']=self.fixture.relative(self.fixture.folder/'absent-profile.json')
                elif fault=='wrong-pin':self.config['constructor_profile']['sha256']='0'*64
                elif fault=='changed-bytes':self.constructor_profile.write_bytes(before+b' ')
                else:self.config['profile']['completed_query_limits']['max_entries']+=1
                self.cli(expected=1)
                self.constructor_profile.write_bytes(before)
        self.receipt_profile_pin_override='not-a-sha256-and-no-profile-exists'
        self.repin()
        self.cli(expected=1)
        del self.receipt_profile_pin_override
        self.producer_profile_changes={'schema':'atlas.fresh-interval-profile.v1'}
        self.repin()
        self.cli(expected=1)

    def test_recursive_generation_document_refusals(self):
        targets=('receipt','derivation','composition','selection','reviewed_inputs','manifest','profile')
        for target in targets:
            for marker in ({'purpose':False},{'Plan31:Rehearsal-h1':0},{'note':'Plan31:Rehearsal-h1'}):
                with self.subTest(target=target,marker=marker):
                    for row in (self.receipt,self.derivation,self.composition,self.selection_row,
                                self.reviewed_row,self.bindings['compression']):
                        row.pop('control',None)
                    manifest=json.loads(self.fixture.manifest.read_bytes())
                    manifest.pop('control',None)
                    nested=[{'nested':[marker]}]
                    rows=dict(receipt=self.receipt,derivation=self.derivation,composition=self.composition,
                              selection=self.selection_row,reviewed_inputs=self.reviewed_row,
                              manifest=manifest,profile=self.bindings['compression'])
                    rows[target]['control']=nested
                    self.fixture.manifest.write_bytes(encoded(manifest))
                    self.repin()
                    self.cli(expected=1)

    def test_authenticated_inherited_staged_root_and_malformed_other_stage(self):
        original=Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ac/p1820c-r4/composition.json')
        raw=original.read_bytes()
        self.assertEqual(digest(raw),'ddd44a8857d17b0ef7910a70e86cb55da04e222ccaa284931d216502612b0bea')
        root=json.loads(raw)['staged']['root']
        self.assertIs(type(root),str)
        self.assertTrue(Path(root).is_absolute())
        self.composition['staged']['root']=root
        self.repin()
        self.cli()
        self.composition['staged']['other-stage']=root
        self.repin()
        self.cli(expected=1)
        self.composition['staged'].pop('other-stage')
        self.composition['staged']['root']='relative-root'
        self.repin()
        self.cli(expected=1)

    def test_paired_profiles_preserve_both_actual_consumers_and_v2_bytes(self):
        self.enable_paired()
        for writer in (False,True):
            out=self.cli(writer=writer)
            self.assertEqual(out.read_bytes(),self.constructor_profile.read_bytes())
            fresh=F.FreshProfile.read(self.fresh_profile,R.file_hash(self.fresh_profile))
            F.FreshSources(fresh).verify()
            prepared=R.RestartProfile.read(out,R.file_hash(out))
            R.RestartSources(prepared).verify()
            self.assertNotEqual(self.receipt['profile_sha256'],self.receipt['prepared_profile']['sha256'])
            self.assertNotEqual(fresh.record()['advance_driver']['module'],prepared.record()['advance_driver']['module'])

    def test_paired_wrong_primary_companion_maps_and_common_fields_refuse(self):
        self.enable_paired()
        original=deepcopy(self.config)
        self.config['constructor_profile']['sha256']='0'*64
        self.cli(expected=1)
        self.config=deepcopy(original)
        self.config['fresh_runner']=deepcopy(self.config['prepared_runner'])
        self.cli(expected=1)
        self.prepared_reference_override=dict(path=str(self.fresh_profile),sha256=R.file_hash(self.fresh_profile))
        self.repin()
        self.cli(expected=1)
        del self.prepared_reference_override
        baseline=json.loads(self.fresh_profile.read_bytes())
        faults=[{'native_root':self.fixture.relative(self.fixture.folder)},
                {'completed_query_limits':dict(max_entries=False,max_store_bytes=1)}]
        missing=deepcopy(baseline['modules']);missing.pop(next(iter(missing)))
        faults.append({'modules':missing})
        wrong=deepcopy(baseline['modules']);wrong['historical_admission']=self.fixture.relative(Path(R.__file__))
        faults.append({'modules':wrong})
        wrong_driver=deepcopy(baseline['modules']);wrong_driver[A.DRIVER_MODULE]=self.fixture.relative(Path(R.__file__))
        faults.append({'modules':wrong_driver})
        for change in faults:
            self.fresh_profile_changes=change
            self.repin()
            self.cli(expected=1)

    def test_paired_fresh_profile_nested_rehearsal_refuses(self):
        self.enable_paired()
        driver=json.loads(self.fresh_profile.read_bytes())['advance_driver']
        driver['nested']=[{'purpose':False}]
        self.fresh_profile_changes={'advance_driver':driver}
        self.repin()
        self.cli(expected=1)

    def test_paired_fresh_path_boundaries_keep_absolute_construction_refs(self):
        self.enable_paired()
        with tempfile.TemporaryDirectory(prefix='owner-W-',dir=HERE) as temporary:
            receipt=Path(temporary)/'BUILD-RESULT.json'
            receipt.write_bytes(encoded(self.receipt))
            self.config['construction_receipt']=dict(path=str(receipt),sha256=R.file_hash(receipt))
            self.cli()
        self.fresh_profile_changes={'source_manifest':dict(path=str(self.fixture.manifest),
                                                         sha256=R.file_hash(self.fixture.manifest))}
        self.repin()
        self.cli(expected=1)
        fresh=F.FreshProfile.read(self.fresh_profile,R.file_hash(self.fresh_profile))
        with self.assertRaises(R.RestartRefused):F.FreshSources(fresh)
        self.fresh_profile_changes={'completed_query_directory':
            self.fixture.relative(self.fixture.folder/'fresh-attempt/queries')}
        self.repin()
        self.cli(expected=1)
if __name__=='__main__':unittest.main()
