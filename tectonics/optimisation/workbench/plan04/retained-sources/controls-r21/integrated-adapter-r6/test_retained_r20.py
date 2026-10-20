"""r20 adapter: retain 47 case bodies, the r17 focused gaps and the G1 causal cases on compare_arms_r20.

Future execution belongs to the owner. No Atlas package, real store, arm, queue,
child workload or scientific module is imported. Checked source bytes supply
the comparator and old fixture/case modules; predecessor suites never run.
The comparator's compare() is the intentional synthetic test seam; run() and
both live readiness guards are unchanged. Synthetic field contracts, observer
records and capture records are fixtures, not live authority or execution proof.
r18: the Causal group adds Copilot's causal-schema-r1 falsification cases for the
closed evidence bundles; its producer pins, approvals and events are synthetic.
r19: the component-review corrections (C1 observer VOID keeps FAIL checks, C2 invocation and termination
binding, guard first-trigger agreement) are re-asserted with an actual synthetic observer entry file.
r20: an unresolved peer keeps the claimant's own width gate and later stage rules (causal16); a trace-free
pre-start claim is an explicit no-workload outcome (causal12).
"""
import argparse
import ast
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType
import unittest

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = Path('C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan04')
BASE = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ac/n9')
PINS = {
    str(HERE/'compare_arms_r20.py'): '5f6d97aa222d7a06d12bf87a49d3c5a59a4d271301bb16dc887530e25d3c62cf',
    str(BASE/'test_compare_r13.py'): 'cf79824a55ed186967e959bd6f1b656a2c1c69ef2b384900fea018b050626255',
    str(BASE/'test_cases_r12.py'): '9f953a96575e29b7bcbce6c1c11a6fa559f1f33bd4770d7914c188c41d58eb5c',
    str(WORK/'dump-r4/test_descriptors_r2.py'): 'c8bbe2bce7b08fe9be9591e93f89e4e764d7f2b367d85682387f064548c0a53e',
    str(WORK/'test_obligations_r14.py'): '69a71a009c3163efb8a1c2d1d4cf927763f0bf0cc248a79f2ffec6444e5fb4f3',
}
PINS.update({'C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan04\\controls-r21\\integrated-adapter-r6\\fixture_migration.py': 'ec89793ac5bcd441a718c282d53a1443502b5b0ad53a47cbfa425e48507592df', 'C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan04\\controls-r21\\integrated-adapter-r6\\field_contracts.py': '6da34d2f6a847f1e6e45e9b10695348354d1c2a8730adce5aa50822c60cc5bd6', 'C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan04\\controls-r21\\integrated-adapter-r6\\array_bindings_r5.py': '943cde40e797fe566506d3d61121c9e253609699f7c9119c317ae92879d6baf1', 'C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan04\\controls-r21\\integrated-adapter-r6\\array_compare_r21.py': '2a3343e47caee415f131824b68c582d7182409e32ce27e07d1f053786ab515d5', 'C:\\Users\\LOCAL_USER\\Documents\\Codex\\agentchattr\\workspace\\work\\plan04\\controls-r21\\integrated-adapter-r6\\field_provenance.py': '02eef271744cc5e9f952cbcb0e167e181c078218c850f6c49e3e210db8e46a01', 'C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\ps\\c\\full6\\src\\atlas_tectonics\\integration_exterior_mesh.py': 'd338238e1abe11db8e01a4b4ee91f99443727fb082f9d9cb6799344e82d445f4'})
CHUNK_BYTES = 16
OBSERVATIONS = []


def checked(path):
    path = Path(path)
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != PINS[str(path)]:
        raise AssertionError('source pin differs: '+str(path))
    return raw


def verify_sources():
    for path in PINS:
        checked(path)


def source_module(name, path, replacements=None, injected=None):
    """No pyc/path resolution: execute exact pinned bytes, with named import-only substitutions."""
    raw = checked(path)
    text = raw.decode('utf-8')
    for old, new in (replacements or {}).items():
        if text.count(old) != 1:
            raise AssertionError('fixture import is no longer unique: '+old)
        text = text.replace(old, new)
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__spec__ = importlib.util.spec_from_file_location(name, path)
    module.__dict__.update(injected or {})
    sys.modules[name] = module
    exec(compile(text, str(path), 'exec'), module.__dict__)
    return module


verify_sources()
TOOL = HERE/'compare_arms_r20.py'
C = source_module('retained_r20_comparator', TOOL)
F = source_module('retained_r13_fixture', BASE/'test_compare_r13.py',
                  {'import compare_arms_r13 as C': '# C injected from checked r21 source',
                   "inventory = {'n/a.py': H('a-'+self.name), 'n/b.py': H('b')}":
                   "inventory = {'n/a.py': H('a-'+self.name), 'n/b.py': H('b'), 'n/integration_exterior_mesh.py': 'd338238e1abe11db8e01a4b4ee91f99443727fb082f9d9cb6799344e82d445f4'}",
                   "('tiny outward', total+total/2**70, 'PASS')":
                   "('tiny outward', total+total/2**70, 'REVIEW')",
                   "self.assertStatus(verdict, status, None if status == 'PASS' else 'Addendum E')":
                   "self.assertStatus(verdict, status, 'producer provenance unresolved' if status == 'REVIEW' else 'Addendum E')\n"
                   "                if status == 'REVIEW':\n"
                   "                    self.assertEqual(verdict['addendum_e']['after i1/mesh#0']['verdict'], 'PASS')"}, {'C': C})
M = source_module('integrated_fixture_migration', HERE/'fixture_migration.py')
M.install(C, F, checked(Path('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\ps\\c\\full6\\src\\atlas_tectonics\\integration_exterior_mesh.py')))


def retained_encoder():
    """Extract only the exact encoder checked against native _blob_id in passing r2 controls."""
    path = WORK/'dump-r4/test_descriptors_r2.py'
    tree = ast.parse(checked(path), filename=str(path))
    method, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'description']
    namespace = {'canonical': F.canonical, 'digest': lambda raw: sha256(raw).hexdigest(),
                 'CHUNK_BYTES': CHUNK_BYTES}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['description']


descriptor = retained_encoder()


OriginalArm = F.Arm


class AdaptedArm(OriginalArm):
    """Supply the real proof slots used by r14/r16 without inventing reader routes.

    A nonempty collar fixture replaces the old empty/unpublished root. The
    published root digest and completed endpoint bind the same root metadata.
    This mirrors the passing descriptor-controls root route; it is not a claim
    about the availability of a real selected arm/composition/field contract.
    """
    root_kind = 'root'

    def __init__(self, root, name, **kw):
        if kw.get('root_arrays') is None:
            kw['root_arrays'] = {'retained-root-mass': np.array([1., 2.], dtype='<f8')}
        kw['records'] = M.records(F, kw.get('records'))
        super().__init__(root, name, **kw)

    def build(self):
        fields = {'grid': 'synthetic-retained-root', 'plan_id': 'synthetic-collar-plan'}
        native = F.H('retained-native-root')
        identity = {'fields_id': F.force_id(fields, self.arrays[0]), 'native_state_id': native}
        metadata = {'kind': self.root_kind, 'sequence': 0, 'key': 'root:'+F.H('head-'+self.name+'-0'),
                    'native_state_id': native,
                    'state': {'schema': C.COLLAR_STATE_SCHEMA, 'fields': fields,
                              'native': {'plan_id': 'synthetic-native-plan'},
                              'result_id': sha256(F.canonical(identity)).hexdigest()}}
        self._root_metadata = metadata
        M.before_build(F, self)
        original_patch = self.patch
        patch = dict(original_patch)

        def runner(value, interval):
            if interval == 0:
                value['root'] = {'kind': self.root_kind, 'root_key': metadata['key'],
                                 'root_metadata_sha256': sha256(F.canonical(metadata)).hexdigest(),
                                 'store_limits': {'chunk_bytes': CHUNK_BYTES}}
            if 'runner' in original_patch:
                original_patch['runner'](value, interval)

        def producer(value, interval):
            if interval == 1:
                value['completed_endpoint']['root_metadata'] = copy.deepcopy(metadata)
                value['completed_endpoint']['store_limits'] = {'chunk_bytes': CHUNK_BYTES}
            if 'producer' in original_patch:
                original_patch['producer'](value, interval)

        patch.update(runner=runner, producer=producer)
        self.patch = patch
        try:
            super().build()
        finally:
            self.patch = original_patch

    def stage(self, mode, interval, root_runner):
        digest = super().stage(mode, interval, root_runner)
        path = self.dumps/('i%d' % interval)/'dump.json'
        record = json.loads(path.read_bytes())
        record.update(schema=C.DUMP_SCHEMA_R4, store_limits={'chunk_bytes': CHUNK_BYTES})
        for row in record['arrays']:
            desc = descriptor(self.arrays[interval][row['name']])
            row.update(descriptor=desc, descriptor_sha256=sha256(F.canonical(desc)).hexdigest())
        M.observation(F, self, record, self._root_metadata)
        F.write(path, record)
        return digest


# Set before compiling Cases, so its default after_class and PartitionArm base
# both use this fixture. The original47 method bodies remain byte-for-byte source.
F.Arm = AdaptedArm
K = source_module('retained_original_cases', BASE/'test_cases_r12.py', {
    'import compare_arms_r12 as C': '# C injected from checked r16 source',
    'import test_compare_r12 as F': '# F injected from checked r13 fixture',
    "all(row['bytes_equal'] for row in verdict['records'].values())":
    "all(row['bytes_equal'] for name, row in verdict['records'].items() if not name.endswith('/root_metadata'))",
    "verdict = self.check(self.verdict(*self.arms()), 'PASS')":
    "verdict = self.check(self.verdict(*self.arms()), 'REVIEW', 'producer provenance unresolved')",
    "verdict = self.check(self.verdict(*self.arms(*self.pair(mutate=unreduced))), 'PASS')":
    "verdict = self.check(self.verdict(*self.arms(*self.pair(mutate=unreduced))), 'REVIEW', 'producer provenance unresolved')",
    "verdict = self.check(self.verdict(*self.arms(before, after)), 'PASS')":
    "verdict = self.check(self.verdict(*self.arms(before, after)), 'REVIEW', 'producer provenance unresolved')"}, {'C': C, 'F': F})
RETAINED_NAMES = tuple(sorted(name for name in vars(K.Cases) if name.startswith('test_')))
if len(RETAINED_NAMES) != 47 or sum(name.startswith('test_s') for name in RETAINED_NAMES) != 33:
    raise AssertionError('retained47 identity set changed')


class Checks:
    allow_unbound = False

    @classmethod
    def tearDownClass(cls):
        verify_sources()
        if C.REPAIRS_COMPLETE is not False:
            raise AssertionError('readiness guard changed')

    def stopped(self, arm, *args, **kw):
        """Reuse real r13 stop fixtures plus the r14 final-stage capture binding."""
        F.R6.stopped(self, arm, *args, **kw)
        stage, step = kw.get('stage', 'interval'), kw.get('step', args[0] if args else 'runner')
        p = C.step_paths(arm.attempt, stage, step)
        if not p['capture'].is_file():
            return
        path = arm.attempt/('stage-'+stage+'.json')
        record = json.loads(path.read_bytes())
        record.update(stage=stage, interval=dict(C.STAGES)[stage], profile={'sha256': arm.sha})
        record['steps'] = [{'name': step, 'ok': False, 'launch_sha256': C.file_sha(p['launch']),
                            'capture': {'ok': True, 'sha256': C.file_sha(p['capture'])}}]
        F.write(path, record)

    def verdict(self, a, b, contract=None, observer=F.OBSERVER_PIN):
        # The old harness already calls compare() and serialises ProofError.
        # Retain that seam; add complete finite output and progression checks.
        return self.finish(F.R6.verdict(self, a, b, contract, observer), a, b)

    def finish(self, value, a, b):
        if 'schema' not in value:
            self.assertEqual(set(value), {'status', 'fail'})
            value = dict(value, schema=C.SCHEMA, inputs={'before': a.args(), 'after': b.args()})
        # Match the guarded main() error envelope and actual selected tool pin,
        # without claiming that this unit seam invoked its guarded CLI.
        value['compare_tool'] = {'path': str(TOOL), 'sha256': PINS[str(TOOL)]}
        self.assertTrue({'schema', 'status', 'inputs', 'compare_tool'} <= set(value))
        if 'proof' in value:
            self.assertTrue({'fail', 'void', 'review', 'records', 'arrays', 'stages', 'widths',
                             'width_gate', 'addendum_e', 'thresholds'} <= set(value))
        encoded = C.verdict_text(value)
        parsed = json.loads(encoded, parse_constant=lambda word: self.fail('nonfinite JSON: '+word))
        self.assertEqual(parsed, C.finite_report(value))
        self.assertEqual(C.exit_code(parsed['status']),
                         {'PASS': 0, 'REVIEW': 3, 'FAIL': 1, 'VOID-SUSPECT': 4, 'VOID-ENVIRONMENT': 4,
                          'VOID-OBSERVER': 4}[parsed['status']])
        if 'proof' in value and not value['void']:
            self.assertEqual({side: set(proof) for side, proof in value['proof'].items()},
                             {'before': {'root', 'interval'}, 'after': {'root', 'interval'}})
            self.assertTrue({'i0/mesh', 'i0/state', 'i1/mesh', 'i1/state'} <= set(value['records']))
            if not self.allow_unbound:
                self.assertFalse(any('unbound' in row.get('binding', [])
                                     for rows in value['arrays'].values() for row in rows.values()), value)
                self.assertFalse(any('root route:' in row for row in value['review']), value)
        OBSERVATIONS.append({'test': self.id(), 'verdict': parsed, 'exit': C.exit_code(parsed['status'])})
        self.last_verdict = value
        return value

    def check(self, verdict, status, needle=None, where=None):
        value = K.Cases.check(self, verdict, status, needle, where)
        exact_integrity = {
            'test_s18_gate_disagree': 'dump widths or width gate differ from the reader verdict',
            'test_s23_tamper': 'dumped record changed since the dump: mesh',
            'test_s24_unbound_dump': 'dump verdict binding differs from the re-derived proof',
            'test_s25_wrong_profile': 'after profile bytes differ from the given sha256',
        }
        if self._testMethodName in exact_integrity:
            self.assertIn(exact_integrity[self._testMethodName], json.dumps(value['fail']))
        if self._testMethodName == 'test_s22_missing_stage' and status == 'FAIL':
            self.assertIn('missing proof file after interval: adopted', json.dumps(value['fail']))
        if self._testMethodName == 'test_s28_array_int':
            # r17: integer arrays carry no float diagnostics (r16 1939: max_abs only for binary64).
            row = value['arrays']['i1']['count']
            self.assertEqual((row['equal'], row['changed'], row['dtype']), (False, 1, '<i8'))
            self.assertNotIn('max_abs', row)
        if self._testMethodName == 'test_s32_int_change':
            row = self.field(value, 'i1/state', 'state.count')
            self.assertEqual((row['changed'], row['max_abs'], row['max_rel']), (1, 1.0, 1/8))
        if self._testMethodName == 'test_s29_weak_change':
            row = self.field(value, 'i1/state', 'state.steps.[].residual')
            self.assertEqual((row['changed'], row['weak_changed'], row['max_abs']), (1, 1, 0.5))
        relative = {'test_r_D_kind_sticky_int_change': 2/9,
                    # This heterogeneous list retains the existing vector
                    # scale: max magnitude is the first, changed float.
                    'test_r_D2_kind_sticky_rational_doubles':
                        float(C.Fraction(1, 3)/C.Fraction.from_float(K.NEXT/2))}
        if self._testMethodName in relative:
            self.assertEqual(self.field(value, 'i1/state', 'state.vals.[]')['max_rel'],
                             relative[self._testMethodName])
        return value


class RetainedCases(Checks, K.Cases):
    """All33 smoke +14 reproducer bodies inherited unchanged, including D01 migrations."""


M.override_retained(C, F, K, RetainedCases)


class Focused(Checks, K.Cases):
    """Only new gaps below are selected; inherited Cases methods are never re-run here."""

    def test_extra_typed_owner_selfmaps_and_order(self):
        # The retained A1/A3 cases use plain c0/c1. This adds the original
        # 64-hex identity mechanism while unchanged tokens force self-maps.
        owners = ['cell:'+F.H('typed-cell-'+str(i)) for i in range(2)]
        for targets, labels in (([owners[0], owners[0]], 1), (owners[::-1], 2)):
            with self.subTest(targets=targets):
                def setup(records):
                    records[1]['mesh']['cells'] = [{'cell_id': owner, C.DEVIATION_FIELD: F.enc(0)}
                                                  for owner in owners]
                    records[1]['mesh'][C.DEVIATION_FIELD] = F.enc(0)
                    records[1]['mesh']['faces'] = [{'face_id': 'f'+str(i), 'owner': owner}
                                                  for i, owner in enumerate(owners)]
                def change(records):
                    for face, target in zip(records[1]['mesh']['faces'], targets, strict=True):
                        face['owner'] = target
                value = self.check(self.verdict(*self.arms(*self.pair(setup, change))), 'REVIEW', 'label changes')
                counts = value['records']['i1/mesh']['counts']
                self.assertEqual((counts['identity_changes'], counts['labels']), (0, labels))

    def test_extra_overflow_mixed_kinds(self):
        # Reach the actual overflow bucket at its unchanged limit. This is a
        # direct numeric boundary, not another full proof/descriptor traversal.
        sub = C.Comparer({}, {})
        for i in range(C.MAX_FIELDS):
            sub.field(('filler', str(i)), 'binary64')
        sub.compare(1.0, float(np.nextafter(1.0, 2.0)), ('overflow-float',))
        sub.compare(7, 9, ('overflow-int',))
        sub.compare(F.enc(C.Fraction(1, 3)), F.enc(C.Fraction(2, 3)), ('overflow-rational',))
        row = sub.fields['<overflow>']
        self.assertEqual(set(row['kinds']), {'binary64', 'int', 'rational'})
        self.assertEqual((row['changed'], row['max_ulps']), (3, 1))
        self.assertGreater(sub.overflow, 0)
        self.assertEqual(row['max_abs'], 2.0)
        self.assertEqual(row['unbound_changes'], 3)
        review, fail = [], []
        C.judge_fields(sub.fields, review, fail, 'overflow fixture')
        self.assertEqual(fail, [])
        self.assertTrue(any('<overflow>' in row and 'without an applicable bound' in row for row in review))
        json.loads(C.verdict_text({'status': 'REVIEW', 'review': review, 'fields': sub.fields}))

    def test_extra_honest_unbound_route(self):
        class Migrated(AdaptedArm):
            root_kind = 'migrated-root'
        self.allow_unbound = True
        a, b = self.arms(after_class=Migrated)
        value = self.check(self.verdict(a, b), 'REVIEW', 'migrated-root route has no implemented independent family binding')
        self.assertEqual(value['fail'], [])
        self.assertEqual(value['void'], [])
        self.assertEqual(value['arrays']['i0']['retained-root-mass']['binding'], ['bound', 'unbound'])
        self.assertTrue(all(row['bytes_equal'] for name, row in value['records'].items()
                            if not name.endswith('/root_metadata')))

    def test_extra_r7_tiny_exact_and_over_bound(self):
        # Reuse the existing boundary method, with this adapter/verdict seam;
        # only add the absent strictly-over-bound excess mutation.
        class ExistingR7(Checks, F.R6):
            pass
        existing = ExistingR7('test_addendum_e_tiny_exact_bound_over_bound')
        existing.root = self.root/'r7-existing'
        existing.root.mkdir()
        existing.test_addendum_e_tiny_exact_bound_over_bound()
        total = C.Fraction(2, 1000)
        before, after = self.pair(mutate=lambda values: values[1].update(
            mesh=F.mesh(['1/1000', '1/1000'], stored=total+total/C.Fraction(2**63))))
        self.check(self.verdict(*self.arms(before, after)), 'FAIL', 'Addendum E after i1/mesh')

    def test_extra_proved_row_permutation_positive(self):
        # Reuse r13's true exterior row-mapping fixture. The retained A4 case
        # supplies the unchanged-bytes/wrong-order negative separately.
        before, after = F.R6.cell_arms(self, ['k2', 'k0', 'k1'], [3.0, 1.0, 2.0])
        value = self.verdict(*self.arms(before, after))
        row = value['arrays']['i1']['exterior-fv:volume']
        # r17: an equal joined row has exactly equal/paired/binding (r16 1931); no changed count.
        self.assertEqual((row['equal'], row['paired'], set(row)), (True, 'cell_id', {'equal', 'paired', 'binding'}))
        self.assertEqual(value['fail'], [])
        self.assertEqual(value['void'], [])
        self.assertFalse(any('array exterior-fv:volume' in issue for issue in value['review']))
        # Other positional state-record ordering may remain REVIEW; do not
        # relabel that as a whole-arm PASS or invent a cell rename authority.

    def test_extra_independent_store_and_profile_collisions(self):
        a, b = self.arms()
        self.check(self.verdict(a, b), 'REVIEW', 'producer provenance unresolved')
        arms = {side: C.load_arm(side, *arm.args()) for side, arm in (('before', a), ('after', b))}
        proofs, dumps = {}, {}
        for side, arm in arms.items():
            proofs[side] = {mode: C.prove_stage(arm, mode, interval) for mode, interval in C.STAGES}
            dumps[side] = {interval: C.load_dump(arm, interval, proofs[side][mode], F.OBSERVER_PIN)
                           for mode, interval in C.STAGES}
        C.distinct_arms(arms, proofs, dumps)
        # Mutate the already-proved comparator inputs at this function's
        # boundary. No disk proof is forged to impersonate another arm.
        for key, needle in (('store', 'arms share their store'), ('sha256', 'arms share one profile')):
            changed = dict(arms, after=dict(arms['after'], **{key: arms['before'][key]}))
            with self.subTest(key=key), self.assertRaisesRegex(C.ProofError, needle):
                C.distinct_arms(changed, proofs, dumps)

    assertStatus = K.Cases.check


EXTRA_NAMES = tuple(sorted(name for name in vars(Focused) if name.startswith('test_extra_')))


APPROVERS = ['OWNER', 'claude', 'codex', 'gemini']   # private retained case record: Copilot left the roster
PINS_R2 = dict(F.PINS, schema=C.SELECTED_PINS_SCHEMA_R2,
               evidence_producers={kind: F.H('producer-'+kind) for kind in C.EVIDENCE_KINDS},
               repeat_approvers=APPROVERS)
OBSERVER_PROCESS = {'pid': 77, 'created_ticks': 3}


class Causal(Checks, K.Cases):
    """r18 G1 / r19: Copilot causal-schema-r1 falsification cases against closed, pinned evidence bundles.

    Cases 7-9 (RSS latch, operation-bound ledger refusal, guardian overwrite) keep their retained r8 bodies;
    here they are re-asserted only where evidence could otherwise excuse them. Every producer pin,
    approval, event and termination record below is a synthetic fixture.
    """
    CANCEL = {'reason': 'user_cancel', 'status': 'COOPERATIVE_ABORT'}
    # r19: the only guard receipt an operator_cancel can explain: first trigger user_cancel, exit confirmed and
    # cleanup complete (the r13 fixture's default workload_exit_confirmed/cleanup)
    CANCEL_DONE = {'reason': 'user_cancel', 'status': 'HARD_STOPPED'}

    def setUp(self):
        super().setUp()
        self.pins = PINS_R2
        self.serial = 0

    def verdict(self, a, b, contract=None, observer=F.OBSERVER_PIN, evidence=None):
        maps = [[side, str(arm.dir/'captures.json'), C.file_sha(arm.dir/'captures.json')]
                for side, arm in (('before', a), ('after', b)) if (arm.dir/'captures.json').is_file()]
        pins = self.path('pins')
        args = argparse.Namespace(before=a.args(), after=b.args(), observer_sha256=observer, field_contract=contract,
                                  captures=maps, selected_pins=[str(pins), F.write(pins, self.pins)],
                                  causal_evidence=evidence or [])
        try:
            value = C.compare(args)
        except C.ProofError as error:
            value = {'status': 'FAIL', 'fail': ['proof/integrity: %s' % error]}
        return self.finish(value, a, b)

    def path(self, label):
        self.serial += 1
        folder = self.root/'evidence'
        folder.mkdir(exist_ok=True)
        return folder/('%03d-%s.json' % (self.serial, label))

    def retained(self, label, content=None):
        path = self.path(label)
        return {'path': str(path), 'sha256': F.write(path, content or {'retained': label})}

    def record(self, arm, kind, payload, stage='interval', step='runner', process=None, guard='n1'):
        self.serial += 1
        return {'schema': C.EVIDENCE_KINDS[kind], 'evidence_id': '%s-%s-%d' % (arm.name, kind, self.serial),
                'kind': kind,
                'binding': {'arm': arm.name, 'attempt': str(arm.attempt), 'profile_sha256': arm.sha,
                            'source_manifest_sha256': arm.manifest_sha, 'stage': stage,
                            'interval': None if stage is None else dict(C.STAGES)[stage], 'step': step},
                'process': process or {'pid': 41, 'created_ticks': 7},
                'guard': {'nonce': guard} if guard else None,
                'producer': {'schema': C.EVIDENCE_KINDS[kind], 'entry_path': 'producer-'+kind+'.py',
                             'entry_sha256': PINS_R2['evidence_producers'][kind], 'pid': 900},
                'source_evidence': [self.retained('source-'+kind)], 'payload': payload}

    def event(self, arm, event_type='operator_cancel', outcome='acknowledged', **kw):
        return self.record(arm, 'external_event', {
            'event_type': event_type, 'occurred_utc': '2026-10-19T12:00:00Z', 'actor_or_source': 'OWNER',
            'action_or_event_id': 'act-%d' % self.serial, 'request_outcome': outcome}, **kw)

    def store(self, value):
        path = self.path('record')
        return {'path': str(path), 'sha256': F.write(path, value)}

    def bundle(self, arm, records, side='after'):
        refs = [row if set(row) == {'path', 'sha256'} else self.store(row) for row in records]
        path = self.path('bundle-'+side)
        return [side, str(path), F.write(path, {'schema': C.EVIDENCE_BUNDLE_SCHEMA, 'arm': arm.name,
                                                'profile_sha256': arm.sha, 'records': refs})]

    def stop(self, records=None, **kw):
        a, b = self.arms()
        self.stopped(b, **kw)
        records = records(b) if callable(records) else records
        return a, b, self.verdict(a, b, evidence=[self.bundle(b, records)] if records else None)

    def assertClass(self, value, classification):
        self.assertEqual(value['stages']['interval']['after']['classification'], classification, value)

    def test_causal_00_r2_pins_without_evidence_match_r16(self):
        self.check(self.verdict(*self.arms()), 'REVIEW', 'producer provenance unresolved')
        _, _, value = self.stop(guard=self.CANCEL, cancel=True)
        self.check(value, 'VOID-SUSPECT', "guard reason 'user_cancel'")
        self.assertEqual(value['causal_evidence']['after'], {'bundle': None, 'events': 0,
                                                           'observer_interruptions': [], 'repeat': None})

    # Cases 1, 3, 4: only an acknowledged/observed operator cancellation explains its own unresolved stop
    def test_causal_01_external_event_explains_only_unresolved_stop(self):
        for outcome in ('acknowledged', 'independently_observed'):
            with self.subTest(outcome):
                _, _, value = self.stop(lambda b, o=outcome: [self.event(b, 'operator_cancel', o)],
                                        guard=self.CANCEL_DONE, cancel=True)
                self.check(value, 'VOID-ENVIRONMENT', 'external operator_cancel', 'stages')
                self.assertClass(value, 'VOID-ENVIRONMENT')
                self.assertEqual(value['causal_evidence']['after']['events'], 1)
        for label, kw in (('requested', {'outcome': 'requested'}), ('delivered', {'outcome': 'delivered'}),
                          ('automatic launcher action', {'event_type': 'automatic_launcher_action'})):
            with self.subTest(label):
                _, _, value = self.stop(lambda b, kw=kw: [self.event(b, **kw)], guard=self.CANCEL_DONE, cancel=True)
                self.check(value, 'VOID-SUSPECT', 'does not establish an external cause', 'stages')
        # r19 (Gemini T5): a host restart claim has no independent host/execution binding in this schema
        for outcome in ('acknowledged', 'independently_observed'):
            with self.subTest('host_restart '+outcome):
                _, _, value = self.stop(lambda b, o=outcome: [self.event(b, 'host_restart', o)],
                                        guard=self.CANCEL_DONE, cancel=True)
                self.check(value, 'VOID-SUSPECT', 'no independent host/execution binding', 'stages')
                self.assertClass(value, 'VOID-SUSPECT')
        with self.subTest('free-floor stop with a host claim only requested'):
            _, _, value = self.stop(lambda b: [self.event(b, 'host_restart', 'requested')],
                                    guard={'reason': 'free_memory_floor', 'status': 'HARD_STOPPED'})
            self.check(value, 'VOID-SUSPECT')

    def test_causal_01b_event_for_another_step_or_stage_explains_nothing(self):
        # An observer-step event of this stage or of the adopted root stage names
        # another step/stage than the unresolved interval runner stop.
        for label, kw in (('observer step', {'step': 'observer'}), ('root stage observer', {'stage': 'root',
                                                                                            'step': 'observer'})):
            with self.subTest(label):
                _, _, value = self.stop(lambda b, kw=kw: [self.event(b, process=OBSERVER_PROCESS, guard=None,
                                                                     **kw)], guard=self.CANCEL_DONE)
                self.check(value, 'VOID-SUSPECT')
                self.assertClass(value, 'VOID-SUSPECT')

    # Case 2: any misbinding or changed retained byte is a proof/integrity FAIL, never an excuse
    def test_causal_02_misbound_evidence_fails(self):
        mutations = {
            'attempt': (lambda v, b: v['binding'].update(attempt=str(b.dir/'other-attempt')), 'bound to another'),
            'profile': (lambda v, b: v['binding'].update(profile_sha256=F.H('x')), 'bound to another'),
            'manifest': (lambda v, b: v['binding'].update(source_manifest_sha256=F.H('x')), 'bound to another'),
            'arm': (lambda v, b: v['binding'].update(arm='before'), 'bound to another'),
            'nonce': (lambda v, b: v.update(guard={'nonce': 'n2'}), 'guard nonce differs'),
            'pid': (lambda v, b: v['process'].update(pid=42), 'process differs'),
            'created ticks': (lambda v, b: v['process'].update(created_ticks=8), 'process differs'),
            'pre-start claim': (lambda v, b: v.update(process={'pre_start': True}, guard=None), 'claims pre-start'),
            'producer': (lambda v, b: v['producer'].update(entry_sha256=F.H('self-declared')),
                         'differs from the selected pin'),
            'producer schema': (lambda v, b: v['producer'].update(schema='other'), 'producer identity'),
            'extra key': (lambda v, b: v.update(note='x'), 'not a closed causal evidence record'),
            'open binding': (lambda v, b: v['binding'].update(extra=1), 'binding not closed'),
            'no source evidence': (lambda v, b: v.update(source_evidence=[]), 'no retained source evidence'),
            'unknown event': (lambda v, b: v['payload'].update(event_type='rumour'), 'payload not closed'),
        }
        for label, (change, needle) in mutations.items():
            with self.subTest(label):
                def build(b, change=change):
                    value = self.event(b)
                    change(value, b)
                    return [value]
                _, _, value = self.stop(build, guard=self.CANCEL, cancel=True)
                self.check(value, 'FAIL', needle)
        with self.subTest('retained file changed after reference'):
            a, b = self.arms()
            self.stopped(b, guard=self.CANCEL, cancel=True)
            event = self.event(b)
            spec = self.bundle(b, [event])
            Path(event['source_evidence'][0]['path']).write_bytes(b'changed')
            self.check(self.verdict(a, b, evidence=[spec]), 'FAIL', 'retained file bytes differ')
        with self.subTest('bundle digest'):
            a, b = self.arms()
            self.stopped(b, guard=self.CANCEL, cancel=True)
            spec = self.bundle(b, [self.event(b)])
            self.check(self.verdict(a, b, evidence=[spec[:2]+[F.H('x')]]), 'FAIL', 'bundle bytes differ')
        with self.subTest('bundle supplied for the other arm'):
            a, b = self.arms()
            self.stopped(b, guard=self.CANCEL, cancel=True)
            self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.event(b)], side='before')]), 'FAIL',
                       "not this arm's closed bundle")
        with self.subTest('r1 pins name no producers'):
            self.pins = F.PINS
            _, _, value = self.stop(lambda b: [self.event(b)], guard=self.CANCEL, cancel=True)
            self.check(value, 'FAIL', 'without selected r2 producer pins')

    # Cases 7, 8: a proven candidate FAIL, or one whose capture provenance is unproved, is never excused
    def test_causal_07_08_events_never_downgrade_resource_fail(self):
        _, _, value = self.stop(lambda b: [self.event(b)], guard=self.RSS, abort=F.R6.ABORT)
        self.check(value, 'FAIL', 'unchanged RSS limit')
        _, _, value = self.stop(lambda b: [self.event(b)],
                                receipt={'errors': [self.BYTE_ERROR], 'logical_budget_at_failure': self.ledger()})
        self.check(value, 'FAIL', 'logical byte ledger')
        _, _, value = self.stop(lambda b: [self.event(b)], guard=self.RSS, abort=F.R6.ABORT, capture=False)
        self.check(value, 'VOID-SUSPECT', 'capture provenance')
        self.assertClass(value, 'VOID-SUSPECT')

    def test_causal_08b_missing_stage_is_not_explained(self):
        a, b = self.arms()
        self.stopped(b, guard=self.CANCEL_DONE)
        evidence = [self.bundle(b, [self.event(b)])]
        (b.attempt/'stage-interval.json').unlink()
        self.check(self.verdict(a, b, evidence=evidence), 'VOID-SUSPECT', 'interval: no usable outcome')

    # Cases 5, 6: observer interruptions
    def real_observer(self, *arms):
        """r19: an actual synthetic observer entry file; every present dump names its bytes, not the token pin."""
        pin = F.write(Path(arms[0].observer), b'# synthetic observer entry\n')
        for arm in arms:
            for dump in arm.dumps.glob('i*/dump.json'):
                F.edit_json(dump, lambda v: (v['observer'].update(sha256=pin),
                                             v['loaded_audit']['exempt'].update(sha256=pin)))
        return pin

    def interruption(self, b, event, change=None, stage='interval', pin=None):
        interval = dict(C.STAGES)[stage]
        sealed = C.prove_stage(C.load_arm('after', *b.args()), stage, interval)['pins']
        ref = self.store(event)
        invocation = {'path': b.observer, 'sha256': pin, 'interval': interval,
                      'output': str(b.dumps/('i%d' % interval)), 'process': OBSERVER_PROCESS}
        termination = {'observed_by': 'queue-supervisor', 'exit_or_signal': 'SIGKILL'}
        echo = dict(termination, schema=C.OBSERVER_TERMINATION_SCHEMA, invocation=copy.deepcopy(invocation))
        payload = {'observer_invocation': invocation,
                   'termination': dict(termination, record=self.retained('termination', echo)),
                   'external_event_ref': ref['sha256'], 'sealed_arm_refs': sealed}
        value = self.record(b, 'observer_interruption', payload, stage=stage, step='observer',
                            process=OBSERVER_PROCESS, guard=None)
        if change:
            change(value, b)
        return self.bundle(b, [ref, value])

    def observer_event(self, b, process=OBSERVER_PROCESS, **kw):
        return self.event(b, step='observer', process=process, guard=None, **kw)

    def test_causal_05_observer_interruption_is_void_observer(self):
        # Gemini C1e: a candidate-only interruption is VOID-OBSERVER; the unobserved interval is never compared
        a, b = self.arms()
        pin = self.real_observer(a, b)
        spec = self.interruption(b, self.observer_event(b), pin=pin)
        (b.dumps/'i1'/'dump.json').unlink()
        value = self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'VOID-OBSERVER',
                           'i1 observer interrupted by external operator_cancel')
        self.assertEqual(value['fail'], [])
        self.assertEqual(value['causal_evidence']['after']['observer_interruptions'], [1])
        self.assertNotIn('i1', value['arrays'])
        self.assertFalse(any(key.startswith('i1/') for key in value['records']), value['records'])
        self.assertEqual({side: row['passed'] for side, row in value['width_gate'].items()},
                         {'before': True, 'after': True})

    def test_causal_05b_observer_evidence_rejections(self):
        cases = (
            ('event for another process', {'process': {'pid': 78, 'created_ticks': 3}}, None,
             'targeted another process or step'),
            ('requested-only event', {'outcome': 'requested'}, None, 'missing'),
            ('sealed refs', {}, lambda v, b: v['payload']['sealed_arm_refs'].update(adopted=F.H('x')),
             'names another sealed arm'),
            ('observer pin', {}, lambda v, b: v['payload']['observer_invocation'].update(sha256=F.H('x')),
             'not the pinned observer'),
            ('output folder', {}, lambda v, b: v['payload']['observer_invocation'].update(output=str(b.dumps/'i0')),
             'interval dump folder'),
            ('no event', {}, lambda v, b: v['payload'].update(external_event_ref=F.H('x')),
             'names no external event'))
        for label, event_kw, change, needle in cases:
            with self.subTest(label):
                a, b = self.arms()
                pin = self.real_observer(a, b)
                spec = self.interruption(b, self.observer_event(b, **event_kw), change, pin=pin)
                (b.dumps/'i1'/'dump.json').unlink()
                self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'FAIL', needle)

    def root_interruption(self, a, b):
        pin = self.real_observer(a, b)
        spec = self.interruption(b, self.observer_event(b, stage='root'), stage='root', pin=pin)
        (b.dumps/'i0'/'dump.json').unlink()
        return spec, pin

    def test_causal_05c_observer_void_never_hides_a_later_proof_failure(self):
        a, b = self.arms()
        spec, pin = self.root_interruption(a, b)
        value = self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'VOID-OBSERVER',
                           'i0 observer interrupted')
        self.assertEqual(value['fail'], [])
        self.assertIn('i1', value['arrays'])      # r19 C1: the observed later interval is still compared
        self.assertNotIn('i0', value['arrays'])
        F.edit_json(b.store/'adopted-interval-0001.json', lambda v: v.update(tampered=True))
        self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'FAIL', 'after interval: stage record does not name exactly these receipts, verdict and adoption')

    def test_causal_05d_void_precedence_suspect_first(self):
        a, b = self.arms()
        self.stopped(a, guard=self.CANCEL)
        self.stopped(b, guard=self.CANCEL_DONE, cancel=True)
        value = self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.event(b)])]), 'VOID-SUSPECT')
        self.assertEqual((value['stages']['interval']['before']['classification'],
                          value['stages']['interval']['after']['classification']),
                         ('VOID-SUSPECT', 'VOID-ENVIRONMENT'))

    def test_causal_06_present_failed_or_mispinned_dump_stays_fail(self):
        with self.subTest('present dump, wrong observer pin'):
            a, b = self.arms()
            spec = self.interruption(b, self.observer_event(b), pin=self.real_observer(a, b))
            self.check(self.verdict(a, b, evidence=[spec], observer=F.H('other-observer')), 'FAIL')
        with self.subTest('present FAILED dump'):
            a, b = self.arms()
            pin = self.real_observer(a, b)
            spec = self.interruption(b, self.observer_event(b), pin=pin)
            F.edit_json(b.dumps/'i1'/'dump.json', lambda v: v.update(status='FAILED'))
            self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'FAIL', 'dump did not pass')
        with self.subTest('absent dump without observer evidence'):
            a, b = self.arms()
            (b.dumps/'i1'/'dump.json').unlink()
            self.check(self.verdict(a, b), 'FAIL', 'missing')

    # Cases 10, 11: at most one diagnostic repeat, fully eligible, capped at REVIEW
    def repeat(self, b, approvers=APPROVERS, change=None):
        original = self.root/'original-after'
        row = json.loads(b.profile.read_bytes())
        row['output_directory'] = str(original/'attempt')
        payload = {'repeat_id': 'rep-1', 'repeat_ordinal': 1,
                   'original': {'attempt': str(original/'attempt'), 'profile': self.retained('profile', row),
                                'outcome': self.retained('outcome', {'status': 'VOID-SUSPECT'})},
                   'eligibility': {'machine_conditions': self.retained('machine'),
                                   'no_cheaper_reproduction': self.retained('no-cheaper')},
                   'approvals': [{'principal': p, 'decision': 'approve', 'utc': '2026-10-19T12:00:00Z',
                                  'record': self.retained('approval-'+p)} for p in approvers]}
        if change:
            change(payload, b)
        return self.record(b, 'diagnostic_repeat', payload, stage=None, step='arm',
                           process={'pid': 300, 'created_ticks': 1}, guard=None)

    def test_causal_11_eligible_repeat_is_review_not_pass(self):
        a, b = self.arms()
        value = self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.repeat(b)])]), 'REVIEW',
                           'diagnostic repeat rep-1')
        self.assertEqual(value['fail'], [])
        self.assertEqual(value['causal_evidence']['after']['repeat']['approvers'], sorted(APPROVERS))
        with self.subTest('proven regression stays FAIL'):
            a, b = self.arms(after={'gate': False})
            self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.repeat(b)])]), 'FAIL', 'width gate')
        with self.subTest('unresolved repeat stays VOID-SUSPECT'):
            a, b = self.arms()
            self.stopped(b, guard=self.CANCEL)
            self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.repeat(b)])]), 'VOID-SUSPECT')
        with self.subTest('evidenced external event stays VOID'):
            a, b = self.arms()
            self.stopped(b, guard=self.CANCEL_DONE, cancel=True)
            self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.repeat(b), self.event(b)])]),
                       'VOID-ENVIRONMENT')

    def test_causal_10_ineligible_repeat_fails(self):
        def budget(p, b):
            row = json.loads(b.profile.read_bytes())
            row['completed_query_limits'] = {'max': 99}
            p['original']['profile'] = self.retained('profile-budget', row)
        cases = (
            ('two approvals', ['OWNER', 'codex'], None, 'exactly one from each pinned approver'),
            ('OWNER absent', APPROVERS[1:], None, 'exactly one from each pinned approver'),
            ('duplicate approval', APPROVERS+['codex'], None, 'exactly one from each pinned approver'),
            ('ordinal 2', APPROVERS, lambda p, b: p.update(repeat_ordinal=2), 'only one diagnostic repeat'),
            ('same attempt', APPROVERS, lambda p, b: p['original'].update(attempt=str(b.attempt)),
             'must be a new attempt'),
            ('changed budget', APPROVERS, budget, 'changes source/input/profile/budget keys'),
            ('no machine conditions', APPROVERS, lambda p, b: p['eligibility'].pop('machine_conditions'),
             'eligibility not closed'),
            ('rejection', APPROVERS, lambda p, b: p['approvals'][0].update(decision='reject'), 'is not an approval'))
        for label, approvers, change, needle in cases:
            with self.subTest(label):
                a, b = self.arms()
                value = self.repeat(b, approvers, change)
                self.check(self.verdict(a, b, evidence=[self.bundle(b, [value])]), 'FAIL', needle)
        with self.subTest('second repeat record'):
            a, b = self.arms()
            self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.repeat(b), self.repeat(b)])]), 'FAIL',
                       'second diagnostic repeat')
        for label, approvers, needle in (('fewer than three', ['OWNER', 'codex'], 'at least three'),
                                         ('without OWNER', ['claude', 'codex', 'gemini'], 'including OWNER')):
            with self.subTest('pins '+label):
                self.pins = dict(PINS_R2, repeat_approvers=approvers)
                self.check(self.verdict(*self.arms()), 'FAIL', needle)
        self.pins = PINS_R2

    # Case 12: a pre-start record and an interrupted process are separate cases
    def test_causal_12_pre_start_is_not_a_process_interruption(self):
        a, b = self.arms()
        self.stopped(b, guard=self.CANCEL, capture=False)
        for name in ('run-interval/run.guard.json', 'run-interval/run.guard-control.json',
                     'run-interval/run.json', 'run-interval.tracking.json'):
            (b.attempt/name).unlink()
        value = self.verdict(a, b, evidence=[self.bundle(b, [self.event(b, process={'pre_start': True},
                                                                        guard=None)])])
        self.check(value, 'VOID-SUSPECT', 'is a pre-start claim: no workload outcome', 'stages')
        self.assertClass(value, 'VOID-SUSPECT')
        self.assertEqual(value['stages']['interval']['after']['workload_outcome']['outcome'],
                         'no_workload_started')
        self.assertIs(value['stages']['interval']['after']['workload_outcome']['cause_established'], False)
        OBSERVATIONS.append({'test': self.id(), 'pre_start_status': value['status'],
                             'classification': value['stages']['interval']['after']['classification']})
        for trace in ('capture', 'receipt'):
            with self.subTest('pre-start refuted by '+trace):
                a, b = self.arms()
                self.stopped(b, guard=self.CANCEL, capture=trace == 'capture')
                names = ['run-interval/run.guard.json', 'run-interval/run.guard-control.json',
                         'run-interval.tracking.json'] + (['run-interval/run.json'] if trace == 'capture' else [])
                for name in names:
                    (b.attempt/name).unlink()
                self.check(self.verdict(a, b, evidence=[self.bundle(b, [self.event(b, process={'pre_start': True},
                                                                                   guard=None)])]),
                           'FAIL', 'claims pre-start')

    # r19: the guard's retained first trigger governs (guard r3 trigger(); guardian_failure overwrites)
    def test_causal_13_guard_first_trigger_governs_cancellation(self):
        _, _, value = self.stop(lambda b: [self.event(b)], guard=self.CANCEL_DONE, cancel=True)
        self.check(value, 'VOID-ENVIRONMENT', 'external operator_cancel', 'stages')
        cases = (
            ('free floor first', {'reason': 'free_memory_floor', 'status': 'HARD_STOPPED'},
             "first trigger 'free_memory_floor'"),
            ('exit without close', {'reason': 'parent_exited_without_guard_close', 'status': 'PARENT_EXITED'},
             "first trigger 'parent_exited_without_guard_close'"),
            ('live descendants', {'reason': 'live_descendants_at_exit', 'status': 'PARENT_EXITED'},
             "first trigger 'live_descendants_at_exit'"),
            ('guardian failure overwrote', {'reason': 'guardian_failure', 'status': 'GUARDIAN_FAILED'},
             "first trigger 'guardian_failure'"),
            ('no trigger', {'reason': None, 'status': 'STOPPED'}, 'first trigger None'),
            ('cancel not exited', self.CANCEL, 'cleanup is not complete'),
            ('exit unconfirmed', dict(self.CANCEL_DONE, workload_exit_confirmed=False), 'cleanup is not complete'),
            ('descendants remain', dict(self.CANCEL_DONE, cleanup={'remaining': [{'pid': 5}], 'action_errors': []}),
             'cleanup is not complete'),
            ('cleanup errors', dict(self.CANCEL_DONE, cleanup={'remaining': [], 'action_errors': ['denied']}),
             'cleanup is not complete'))
        for label, guard, needle in cases:
            with self.subTest(label):
                _, _, value = self.stop(lambda b: [self.event(b)], guard=guard,
                                        cancel=guard['reason'] == 'user_cancel')
                self.check(value, 'VOID-SUSPECT', needle, 'stages')
                self.assertClass(value, 'VOID-SUSPECT')

    # r19 C1: an observer VOID never hides the width gate, a later resource stop or the cross-stage chain
    def test_causal_14_observer_void_keeps_gate_stop_and_chain_failures(self):
        def gate(reader, i):
            if i == 1:
                reader['width_gate']['rows'] = []
        for label, after, needle in (('after width gate false', {'gate': False}, 'after arm interval width gate'),
                                     ('cross-stage chain', {'patch': {'reader': gate}},
                                      'after: interval width gate is not the gate of the recorded')):
            with self.subTest(label):
                a, b = self.arms(after=after)
                spec, pin = self.root_interruption(a, b)
                self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'FAIL', needle)
        with self.subTest('candidate-only resource stop after the interruption'):
            a, b = self.arms()
            spec, pin = self.root_interruption(a, b)
            self.stopped(b, guard=self.RSS, abort=F.R6.ABORT)
            self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'FAIL', 'candidate-only stop')

    # r19 C2: the interrupted invocation is the pinned entry file, echoed by the retained termination record
    def test_causal_15_observer_invocation_and_termination_binding(self):
        def path(value):
            return lambda v, b: v['payload']['observer_invocation'].update(
                path=value(b) if callable(value) else value)

        def other_bytes(b):
            F.write(b.dir/'other_observer.py', b'# another observer\n')
            return str(b.dir/'other_observer.py')

        def termination(change):
            def apply(v, b):
                row = v['payload']['termination']
                content = json.loads(Path(row['record']['path']).read_bytes())
                change(content)
                row['record'] = self.retained('termination-changed', content)
            return apply
        entry, unbound = 'not an ordinary file with the pinned observer bytes', 'does not bind this observer'
        cases = (
            ('path None', path(None), entry), ('path empty', path(''), entry),
            ('path missing', path(lambda b: str(b.dir/'absent_observer.py')), entry),
            ('path other bytes', path(other_bytes), entry),
            ('path a directory', path(lambda b: str(b.dir)), 'observer entry path is not ordinary'),
            ('termination interval', termination(lambda c: c['invocation'].update(interval=0)), unbound),
            ('termination process', termination(lambda c: c['invocation'].update(process={'pid': 78,
                                                                                       'created_ticks': 3})),
             unbound),
            ('termination path', termination(lambda c: c['invocation'].update(path='elsewhere.py')), unbound),
            ('termination schema', termination(lambda c: c.update(schema='other')), unbound),
            ('termination extra key', termination(lambda c: c.update(note=1)), unbound),
            ('termination exit', termination(lambda c: c.update(exit_or_signal=0)), unbound),
            ('termination not echoed', lambda v, b: v['payload']['termination'].update(
                record=self.retained('plain')), unbound))
        for label, change, needle in cases:
            with self.subTest(label):
                a, b = self.arms()
                pin = self.real_observer(a, b)
                spec = self.interruption(b, self.observer_event(b), change, pin=pin)
                (b.dumps/'i1'/'dump.json').unlink()
                self.check(self.verdict(a, b, evidence=[spec], observer=pin), 'FAIL', needle)

    # r20 (Codex r19 review): an unresolved peer never hides the claimant's own mandatory failures, and never
    # supplies a missing reference for a candidate-only comparison
    UNATTRIBUTED = {'errors': [{'type': 'MemoryError', 'message': ''}]}

    def reference_root_stop(self, a):
        for path in (a.attempt/'stage-interval.json', a.attempt/'run-interval', a.attempt/'reader-interval',
                     a.dumps/'i1', a.store/C.CATALOG, *(a.store/(kind+'-interval-0001.json') for kind in
                                                       ('adopted', 'reader-verdict', 'runner-record',
                                                        'sealed-awaiting-reader'))):
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        self.stopped(a, stage='root', receipt=self.UNATTRIBUTED)

    def test_causal_16_unresolved_peer_keeps_claimant_failures(self):
        with self.subTest('reference interval unresolved, candidate gate false'):
            a, b = self.arms(after={'gate': False})
            self.stopped(a, receipt=self.UNATTRIBUTED)
            value = self.check(self.verdict(a, b), 'FAIL', 'after arm interval width gate')
            self.assertTrue(any('cause not established' in v for v in value['void']), value['void'])
            self.assertFalse(any('refusal flip' in v for v in value['fail']), value['fail'])
        with self.subTest('reference interval unresolved, clean candidate'):
            a, b = self.arms()
            self.stopped(a, receipt=self.UNATTRIBUTED)
            value = self.check(self.verdict(a, b), 'VOID-SUSPECT')
            self.assertEqual(value['fail'], [])
            self.assertEqual({side: row['passed'] for side, row in value['width_gate'].items()}, {'after': True})
            self.assertNotIn('i1', value['arrays'])
        with self.subTest('reference root unresolved, candidate gate false'):
            a, b = self.arms(after={'gate': False})
            self.reference_root_stop(a)
            self.check(self.verdict(a, b), 'FAIL', 'after arm interval width gate')
        with self.subTest('reference root unresolved, later candidate resource stop'):
            # conditional scope: no reference reached the interval, so no candidate-only regression is invented
            a, b = self.arms()
            self.reference_root_stop(a)
            self.stopped(b, guard=self.RSS, abort=F.R6.ABORT)
            value = self.check(self.verdict(a, b), 'VOID-SUSPECT', 'interval: no usable outcome')
            self.assertEqual(value['fail'], [])
            self.assertEqual(value['stages']['interval']['after']['class'], 'resource_fail')
            self.assertEqual(value['stages']['interval']['before']['class'], 'missing')
        with self.subTest('stale reference interval files after its own root stop'):
            # an unreached reference's later adoption file is never a reference for a candidate-only stop
            a, b = self.arms()
            self.stopped(a, stage='root', receipt=self.UNATTRIBUTED)
            self.stopped(b, guard=self.RSS, abort=F.R6.ABORT)
            value = self.check(self.verdict(a, b), 'VOID-SUSPECT')
            self.assertEqual(value['fail'], [])
            self.assertEqual(value['stages']['interval']['before']['class'], 'adopted')

    assertStatus = K.Cases.check


CAUSAL_NAMES = tuple(sorted(name for name in vars(Causal) if name.startswith('test_causal_')))


def selected_suite(group):
    suite = unittest.TestSuite()
    if group in ('retained', 'all'):
        suite.addTests(RetainedCases(name) for name in RETAINED_NAMES)
    if group in ('focused', 'all'):
        suite.addTests(Focused(name) for name in EXTRA_NAMES)
    if group in ('causal', 'all'):
        suite.addTests(Causal(name) for name in CAUSAL_NAMES)
    return suite


def load_tests(loader, standard_tests, pattern):
    """Standard unittest discovery must not duplicate the inherited 47 cases."""
    return selected_suite('all')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=('retained', 'focused', 'causal', 'all'), default='all')
    parser.add_argument('--evidence', type=Path, help='exclusive JSON result path; parent directory must exist')
    args = parser.parse_args(argv)
    # Own the evidence output before any fixtures. Collision is a nonzero error.
    stream = args.evidence.open('x', encoding='utf-8', newline='\n') if args.evidence else None
    try:
        verify_sources()
        result = unittest.TextTestRunner(verbosity=2).run(selected_suite(args.group))
        verify_sources()
        expected = (len(RETAINED_NAMES) if args.group in ('retained', 'all') else 0) + (
            len(EXTRA_NAMES) if args.group in ('focused', 'all') else 0) + (
            len(CAUSAL_NAMES) if args.group in ('causal', 'all') else 0)
        passed = result.wasSuccessful() and not result.skipped and result.testsRun == expected
        payload = {'status': 'PASS' if passed else 'FAIL', 'tests_run': result.testsRun,
                   'expected_tests': expected,
                   'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
                   'sources': PINS, 'group': args.group, 'retained_names': RETAINED_NAMES,
                   'focused_names': EXTRA_NAMES, 'causal_names': CAUSAL_NAMES, 'observations': OBSERVATIONS,
                   'limits': 'synthetic fixtures only; not runtime observer or scientific acceptance'}
        if stream:
            json.dump(payload, stream, indent=1, allow_nan=False)
            stream.write('\n')
        return 0 if passed else 1
    finally:
        if stream:
            stream.close()


if __name__ == '__main__':
    raise SystemExit(main())
