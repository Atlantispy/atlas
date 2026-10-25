"""Bounded stdlib fixtures for the Plan22 selection constructor, not Atlas runs."""
import contextlib
import copy
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('plan22_selection_under_test', HERE / 'build_selection.py')
assert SPEC is not None and SPEC.loader is not None
SELECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTION)
REAL_LOAD_BASE = SELECTION.load_base
CANDIDATE_FLAGS = SELECTION.GRANTED + SELECTION.WITHHELD
REPLACEMENTS = ('source/helpers/record_views.py', 'source/helpers/mesh_tables.py')
ADDITIONS = ('source/helpers/test_l3_carried_pages.py',)


def digest(raw):
    return sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode()


class Utilities:
    """Fixture implementations of the unchanged, pinned builder utility contract."""
    digest = staticmethod(digest)
    read_map = staticmethod(json.loads)

    @staticmethod
    def inside(root, relative):
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Fixture path escapes')
        return root / path

    @classmethod
    def read_source(cls, root, relative):
        return cls.inside(root, relative).read_bytes()

    @staticmethod
    def refuse_existing(path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)

    @staticmethod
    def generation(entries):
        rows = sorted(({'member': e['member'], 'public_sha256': e['public_sha256']}
                       for e in entries), key=lambda row: row['member'])
        return digest(encoded(rows))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.fixture-', dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.output = self.root / 'selection'
        parents = [f'source/src/module{i:03}.py' for i in range(240)]
        parents += list(REPLACEMENTS) + [f'source/helpers/helper{i:03}.py' for i in range(404)]
        self.parent = {}
        for index, member in enumerate(parents):
            raw = ('raise RuntimeError("Parent source must not execute: %d")\n' % index).encode()
            self.write('parent/' + member, raw)
            self.parent[member] = dict(member=member, public_path='parent/' + member, public_sha256=digest(raw))
        self.entries = []
        for member in REPLACEMENTS + ADDITIONS:
            path = SELECTION.PREFIX + member
            raw = ('raise RuntimeError("Candidate source must not execute: %s")\n' % member).encode()
            self.write(path, raw)
            prior = self.parent.get(member, {})
            self.entries.append(dict(member=member, public_path=path, public_sha256=digest(raw),
                                     public_base=prior.get('public_path'),
                                     public_base_sha256=prior.get('public_sha256'),
                                     selected_composition_member=False))
        self.candidate_map = dict(public_overlay_identity_sha256='1' * 64, entries=self.entries,
                                  candidate_private_composition_sha256='c' * 64,
                                  base_private_composition_sha256='b' * 64,
                                  **dict.fromkeys(CANDIDATE_FLAGS, False))
        self.write(SELECTION.PREFIX + 'SOURCE-MAP.json', encoded(self.candidate_map))
        for name in ('tools/candidate.py', 'tools/combined.py'):
            self.write(name, b'# Pinned fixture metadata tool; selected sources are never imported.\n')
        for index, name in enumerate(('content_cache', 'interval_store_set', 'record_tables'), 1):
            previous = self.parent.pop('source/helpers/helper00%d.py' % index)
            member = 'source/helpers/' + name + '.py'
            self.parent[member] = dict(previous, member=member)
        self.selected = dict(self.parent, **{e['member']: e for e in self.entries})
        self.manifest_edits = {}
        self.file_edits = {}
        shared = types.SimpleNamespace(shared=lambda repo: Utilities)
        self.candidate = types.SimpleNamespace(
            FROZEN=True, PREFIX=SELECTION.PREFIX, MAP_SHA=self.file_pin(SELECTION.PREFIX + 'SOURCE-MAP.json'),
            FLAGS=CANDIDATE_FLAGS, COUNTS={'selected_native_files': 240, 'selected_helper_files': 407},
            load_base=lambda repo: types.SimpleNamespace(combined=lambda repo: shared),
            materialise=self.materialise_candidate)
        reader = self.entries[0]
        self.results: dict[str, dict]
        self.results = dict(d10=dict(run=True, verdict='SELECTED', comparison='A/B ABBA', label='MEASURED',
                                     date='2026-10-24', all_conditions_true=True, inputs_unchanged=True,
                                     baseline_reader_sha256=reader['public_base_sha256'],
                                     candidate_reader_sha256=reader['public_sha256'],
                                     baseline_private_composition_sha256='b' * 64,
                                     candidate_private_composition_sha256='c' * 64,
                                     improvement_seconds=3.4021, improvement_fraction=0.2092,
                                     reopen_seconds={'A': [16.1983, 16.3328], 'B': [12.8539, 12.873]},
                                     page_misses={'A': [8322, 8322], 'B': [8321, 8321]},
                                     required_refusals={'A': [0, 0], 'B': [0, 0]}, carry_refusals=[0, 0],
                                     peak_rss_bytes={'A': [206635008, 206909440], 'B': [206721024, 206925824]},
                                     arm_compositions={'A': 'b' * 64, 'B': 'c' * 64},
                                     valid_run=dict(result_id_equal={'A': [True, True], 'B': [True, True]},
                                                    fields={'A': [5, 5], 'B': [5, 5]},
                                                    strict_source={'A': [True, True], 'B': [True, True]},
                                                    scope_closed={'A': [True, True], 'B': [True, True]},
                                                    budget_reserved_after_close={'A': [0, 0], 'B': [0, 0]},
                                                    carry_after_close_b={'booked': [0, 0], 'raw': [0, 0]}),
                                     differing_modules=sorted(SELECTION.DECLARED_DIFFERING_MODULES),
                                     timed_stack=dict(description='timed', modules=dict(
                                         record_views=reader['public_sha256'], content_cache='f'*64,
                                         interval_store_set='f'*64, record_tables='f'*64,
                                         helper000=self.parent['source/helpers/helper000.py']['public_sha256'])),
                                     selected_stack=dict(description='selected', modules=dict(
                                         record_views=reader['public_sha256'],
                                         **{name: self.parent['source/helpers/'+name+'.py']['public_sha256']
                                            for name in ('content_cache','interval_store_set','record_tables')},
                                         helper000=self.parent['source/helpers/helper000.py']['public_sha256']))))
        self.sync_digest = True
        self.write_results()
        self.mapping = dict(
            schema=SELECTION.SCHEMA, identity_kind=SELECTION.IDENTITY_KIND,
            candidate_source_map={'path': SELECTION.PREFIX + 'SOURCE-MAP.json', 'sha256': self.candidate.MAP_SHA},
            candidate_overlay_identity_sha256='1' * 64,
            candidate_selection_sha256=Utilities.generation(self.selected.values()),
            base_selection_sha256=Utilities.generation(self.parent.values()),
            members=[{k: e[k] for k in SELECTION.MEMBER_FIELDS} for e in self.entries],
            evidence=dict(d10=dict(record=SELECTION.RESULTS, d10_record_sha256='',
                                   **{k: self.results['d10'][k] for k in SELECTION.D10_FIELDS}),
                          mesh_tables='fixture'),
            **dict.fromkeys(SELECTION.GRANTED, True), **dict.fromkeys(SELECTION.WITHHELD, False))
        for attribute, value in (('BASE_TOOL', 'tools/candidate.py'),
                                 ('BASE_TOOL_SHA', self.file_pin('tools/candidate.py')),
                                 ('load_base', lambda repo: self.candidate)):
            patcher = patch.object(SELECTION, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.repin_map()

    def write(self, relative, raw):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def file_pin(self, relative):
        return digest((self.repo / relative).read_bytes())

    def repin_map(self):
        claimed = (self.mapping.get('evidence') or {}).get('d10')
        if self.sync_digest and isinstance(claimed, dict) and 'd10' in self.results:
            claimed['d10_record_sha256'] = SELECTION.d10_digest(self.results['d10'])
        self.write(SELECTION.SELECTION_MAP, encoded(self.mapping))
        patcher = patch.object(SELECTION, 'SELECTION_MAP_SHA', self.file_pin(SELECTION.SELECTION_MAP))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_results(self):
        self.write(SELECTION.RESULTS, encoded(self.results))

    def materialise_candidate(self, repo, stage):
        if stage.exists():
            raise FileExistsError(stage)
        stage.mkdir()
        files = {}
        for member, entry in sorted(self.selected.items()):
            name = member.removeprefix('source/')
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.file_edits.get(name, (repo / entry['public_path']).read_bytes()))
            files[name] = entry['public_sha256']
        manifest = dict(status='PREPARED_SOURCE_NOT_QUALIFIED', source_map_sha256=self.candidate.MAP_SHA,
                        base_selection_sha256=Utilities.generation(self.parent.values()),
                        selection_sha256=Utilities.generation(self.selected.values()), source_members=len(files),
                        overlay_identity_sha256='1' * 64, source_maps=[{'path': 'parent.json', 'sha256': '2' * 64}],
                        source_tools=[{'path': 'tools/combined.py', 'sha256': '3' * 64}],
                        replaced_public_sources={}, files=files, **dict.fromkeys(CANDIDATE_FLAGS, False))
        manifest.update(self.manifest_edits)
        (stage / 'SOURCE-MANIFEST.json').write_bytes(encoded(manifest))

    def assert_refused(self, message):
        with self.assertRaisesRegex((ValueError, OSError), message):
            SELECTION.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.plan22-selection-*')), [])

    def refused_after_map_change(self, change, message):
        saved = copy.deepcopy(self.mapping)
        change(self.mapping)
        self.repin_map()
        self.assert_refused(message)
        self.mapping = saved
        self.repin_map()

    def test_selection_enables_l3_and_preserves_the_candidate_closure(self):
        result = SELECTION.materialise(self.repo, self.output)
        self.assertEqual(result['files'], 647)
        self.assertEqual(result['status'], 'SELECTED_SOURCE_L3_ENABLED')
        raw = (self.output / 'SOURCE-MANIFEST.json').read_bytes()
        manifest = json.loads(raw)
        self.assertEqual(manifest['selection_sha256'], self.mapping['candidate_selection_sha256'])
        self.assertEqual(len(manifest['files']), 647)
        for member, pin in manifest['files'].items():
            self.assertEqual(digest((self.output / member).read_bytes()), pin)
        self.assertTrue(all(manifest[key] is True and result[key] is True for key in SELECTION.GRANTED))
        self.assertTrue(all(manifest[key] is False and result[key] is False for key in SELECTION.WITHHELD))
        self.assertEqual(manifest['selection_map'],
                         {'path': SELECTION.SELECTION_MAP, 'sha256': SELECTION.SELECTION_MAP_SHA})
        self.assertEqual(manifest['d10_record_sha256'], SELECTION.d10_digest(self.results['d10']))
        self.assertEqual(manifest['evidence']['d10']['d10_record_sha256'],
                         manifest['d10_record_sha256'])
        self.assertEqual(manifest['source_maps'][0], manifest['selection_map'])
        self.assertEqual(manifest['source_tools'][0]['path'], SELECTION.BASE_TOOL)
        self.assertEqual(manifest['evidence'], self.mapping['evidence'])
        self.assertEqual(len(manifest['candidate_manifest_sha256']), 64)

    def test_selection_map_and_tool_pins_fail_closed(self):
        with patch.object(SELECTION, 'SELECTION_MAP_SHA', '0' * 64):
            self.assert_refused('Pinned input changed')
        with patch.object(SELECTION, 'SELECTION_MAP_SHA', None):
            self.assert_refused('Reviewed SHA256 required')
        self.candidate.MAP_SHA = '0' * 64
        self.assert_refused('Pinned input changed')

    def test_loader_refuses_tampered_candidate_builder_before_execution(self):
        self.write(SELECTION.BASE_TOOL, b'raise RuntimeError("Unpinned tool executed")\n')
        with self.assertRaisesRegex(ValueError, 'Pinned input changed'):
            REAL_LOAD_BASE(self.repo)

    def test_unfrozen_candidate_builder_is_refused(self):
        self.candidate.FROZEN = False
        self.assert_refused('The candidate builder is not frozen')

    def test_selection_must_grant_selected_and_enablement(self):
        for key in SELECTION.GRANTED:
            for value in (False, None, 'true'):
                with self.subTest(key=key, value=value):
                    self.refused_after_map_change(lambda m, key=key, value=value: m.__setitem__(key, value),
                                                  'does not select and enable L3')

    def test_every_withheld_authority_flag_is_required_false(self):
        for key in SELECTION.WITHHELD:
            with self.subTest(key=key):
                self.refused_after_map_change(lambda m, key=key: m.__setitem__(key, True), 'grants withheld authority')
            with self.subTest(key=key, missing=True):
                self.refused_after_map_change(lambda m, key=key: m.pop(key), 'grants withheld authority')

    def test_flags_must_partition_the_candidate_flags(self):
        self.candidate.FLAGS = CANDIDATE_FLAGS + ('new_authority',)
        self.assert_refused('do not cover the candidate flags')
        self.candidate.FLAGS = CANDIDATE_FLAGS[1:]
        self.assert_refused('do not cover the candidate flags')

    def test_schema_and_candidate_map_reference_are_required(self):
        self.refused_after_map_change(lambda m: m.__setitem__('schema', 'other'), 'selection map is required')
        self.refused_after_map_change(lambda m: m.__setitem__('identity_kind', 'other'), 'selection map is required')
        for field in ('path', 'sha256'):
            with self.subTest(field=field):
                self.refused_after_map_change(lambda m, field=field: m['candidate_source_map'].__setitem__(field, 'x'),
                                              'does not name the reviewed candidate map')
        self.refused_after_map_change(lambda m: m.__setitem__('candidate_overlay_identity_sha256', '4' * 64),
                                      'Candidate overlay identity differs')

    def test_members_must_equal_the_candidate_entries(self):
        for index in range(3):
            for field in SELECTION.MEMBER_FIELDS:
                with self.subTest(index=index, field=field):
                    self.refused_after_map_change(
                        lambda m, index=index, field=field: m['members'][index].__setitem__(field, 'x'),
                        'Selected members differ')
        self.refused_after_map_change(lambda m: m['members'].pop(), 'Selected members differ')
        self.refused_after_map_change(lambda m: m['members'].reverse(), 'Selected members differ')
        self.refused_after_map_change(lambda m: m['members'].append(dict(m['members'][0])), 'Selected members differ')

    def test_recorded_d10_must_select_l3(self):
        for key, value in (('run', False), ('verdict', 'UNCERTAIN / NOT ENABLED'), ('verdict', 'REGRESSION'),
                           ('all_conditions_true', False), ('inputs_unchanged', False)):
            with self.subTest(key=key, value=value):
                saved = self.results['d10'][key]
                self.results['d10'][key] = value
                self.write_results()
                self.assert_refused('does not select L3')
                self.results['d10'][key] = saved
                self.write_results()
        self.results.pop('d10')
        self.write_results()
        self.assert_refused('does not select L3')

    def rule_refused(self, change, message):
        """Change the recorded rows and re-pin the map to them, so only the recomputed rule can refuse."""
        saved, saved_map = copy.deepcopy(self.results), copy.deepcopy(self.mapping)
        try:
            change(self.results['d10'])
            claimed = self.mapping['evidence']['d10']
            recorded = self.results['d10']
            claimed.update({key: recorded[key] for key in SELECTION.D10_FIELDS if key in recorded})
            self.write_results()
            self.repin_map()
            self.assert_refused(message)
        finally:
            self.results, self.mapping = saved, saved_map
            self.write_results()
            self.repin_map()

    def test_d10_record_must_match_the_pinned_digest(self):
        for key, value in (('page_misses', {'A': [1, 1], 'B': [2, 2]}), ('peak_rss_bytes', {'A': [1, 1], 'B': [1, 1]}),
                           ('first_attempt', 'added after the pin')):
            with self.subTest(key=key):
                saved = copy.deepcopy(self.results)
                self.results['d10'][key] = value
                self.write_results()
                self.assert_refused('differs from the pinned record')
                self.results = saved
                self.write_results()
        self.sync_digest = False
        for value in ('', 'x' * 64, '0' * 64):
            with self.subTest(value=value):
                self.refused_after_map_change(
                    lambda m, value=value: m['evidence']['d10'].__setitem__('d10_record_sha256', value),
                    'differs from the pinned record')
        self.refused_after_map_change(lambda m: m['evidence']['d10'].pop('d10_record_sha256'),
                                      'differs from the pinned record')

    def test_frozen_rule_is_recomputed_from_the_rows(self):
        rule = 'do not satisfy the frozen selection rule'
        cases = {
            'misses above baseline': (lambda d: d.__setitem__('page_misses', {'A': [1, 1], 'B': [2, 2]}), rule),
            'B not below both A': (lambda d: d['reopen_seconds'].__setitem__('A', [12.86, 19.6711]), rule),
            'gain within range': (lambda d: d.update(reopen_seconds={'A': [16.0, 16.5311], 'B': [11.0, 14.7269]}),
                                  rule),
            'new required refusal': (lambda d: d['required_refusals'].__setitem__('B', [1, 0]), rule),
            'carry refusal': (lambda d: d.__setitem__('carry_refusals', [0, 1]), rule),
            'rss above allowance': (lambda d: d['peak_rss_bytes'].__setitem__(
                'B', [206721024, 206909440 + SELECTION.RSS_ALLOWANCE + 1]), rule),
            'summary seconds': (lambda d: d.__setitem__('improvement_seconds', 3.5), 'summary differs'),
            'summary fraction': (lambda d: d.__setitem__('improvement_fraction', 0.25), 'summary differs'),
            'short row': (lambda d: d['page_misses'].__setitem__('A', [8322]), 'rows are malformed'),
            'string row': (lambda d: d['peak_rss_bytes'].__setitem__('B', ['1', 1]), 'rows are malformed'),
            'boolean row': (lambda d: d['required_refusals'].__setitem__('B', [False, 0]), 'rows are malformed'),
            'missing row': (lambda d: d.pop('reopen_seconds'), 'rows are malformed'),
            'third arm': (lambda d: d['page_misses'].__setitem__('C', [0, 0]), 'rows are malformed'),
            'carry malformed': (lambda d: d.__setitem__('carry_refusals', [0]), 'rows are malformed'),
            'NaN second sample': (lambda d: d['reopen_seconds'].__setitem__('A', [16.1983, float('nan')]),
                                  'rows are malformed'),
            'infinite second sample': (lambda d: d['reopen_seconds'].__setitem__('B', [12.8539, float('inf')]),
                                       'rows are malformed'),
            'zero seconds': (lambda d: d['reopen_seconds'].__setitem__('B', [0, 12.873]), 'rows are malformed'),
            'negative misses': (lambda d: d['page_misses'].__setitem__('B', [-1, 8321]), 'rows are malformed'),
            'float misses': (lambda d: d['page_misses'].__setitem__('A', [8322.0, 8322]), 'rows are malformed'),
            'negative rss': (lambda d: d['peak_rss_bytes'].__setitem__('A', [-1, 206909440]), 'rows are malformed'),
            'negative refusal': (lambda d: d['required_refusals'].__setitem__('A', [0, -1]), 'rows are malformed'),
            'boolean summary': (lambda d: d.__setitem__('improvement_seconds', True), 'summary differs'),
            'result identity differs': (lambda d: d['valid_run']['result_id_equal'].__setitem__('B', [True, False]),
                                        rule),
            'field count differs': (lambda d: d['valid_run']['fields'].__setitem__('B', [5, 4]), rule),
            'strict source failed': (lambda d: d['valid_run']['strict_source'].__setitem__('A', [True, False]), rule),
            'scope left open': (lambda d: d['valid_run']['scope_closed'].__setitem__('B', [False, True]), rule),
            'reserved after close': (lambda d: d['valid_run']['budget_reserved_after_close'].__setitem__(
                'B', [0, 1]), rule),
            'booked after close': (lambda d: d['valid_run']['carry_after_close_b'].__setitem__('booked', [0, 5]),
                                   rule),
            'raw after close': (lambda d: d['valid_run']['carry_after_close_b'].__setitem__('raw', [7, 0]), rule),
            'integer flag': (lambda d: d['valid_run']['result_id_equal'].__setitem__('A', [1, True]),
                             'rows are malformed'),
            'valid-run missing': (lambda d: d.pop('valid_run'), 'rows are malformed'),
            'after-close malformed': (lambda d: d['valid_run'].__setitem__('carry_after_close_b', {'booked': [0, 0]}),
                                      'rows are malformed'),
        }
        for name, (change, message) in cases.items():
            with self.subTest(name=name):
                self.rule_refused(change, message)
        self.assertTrue(SELECTION.frozen_rule(self.results['d10']))

    def test_arms_and_stacks_are_bound_to_the_record(self):
        cases = {
            'arms swapped': (lambda d: d.__setitem__('arm_compositions', {'A': 'c' * 64, 'B': 'b' * 64}),
                             'arms are not bound'),
            'arms missing': (lambda d: d.pop('arm_compositions'), 'arms are not bound'),
            'timed reader differs': (lambda d: d['timed_stack']['modules'].__setitem__('record_views', 'f' * 64),
                                     'timed stack does not hold'),
            'timed stack malformed': (lambda d: d['timed_stack']['modules'].pop('record_views'),
                                      'stack is malformed'),
            'selected stack non-digest': (lambda d: d['selected_stack']['modules'].__setitem__('helper000', 'x'),
                                          'stack is malformed'),
            'selected stack differs': (lambda d: d['selected_stack']['modules'].__setitem__('helper000', 'f' * 64),
                                       'selected stack differs|actual differing-module set differs'),
            'selected reader differs': (lambda d: d['selected_stack']['modules'].__setitem__(
                'record_views', 'e' * 64), 'selected stack differs|actual differing-module set differs'),
            'identity not a digest': (lambda d: d.__setitem__('baseline_private_composition_sha256', 'B' * 64),
                                      'identities are not digests'),
        }
        for name, (change, message) in cases.items():
            with self.subTest(name=name):
                self.rule_refused(change, message)


    def test_stack_key_sets_and_exact_declared_differences(self):
        cases = (
            (lambda d: d['timed_stack']['modules'].__setitem__('extra', 'd'*64), 'key sets differ'),
            (lambda d: d['selected_stack']['modules'].pop('helper000'), 'key sets differ'),
            (lambda d: d['selected_stack']['modules'].__setitem__('helper000','f'*64), 'actual differing-module set differs'),
            (lambda d: d['timed_stack']['modules'].__setitem__('content_cache', d['selected_stack']['modules']['content_cache']), 'actual differing-module set differs'),
            (lambda d: d.__setitem__('differing_modules', ['content_cache','interval_store_set','record_tables','extra']), 'declared differing-module set differs'),
            (lambda d: d.__setitem__('differing_modules', ['content_cache','interval_store_set','record_tables','record_tables']), 'declared differing-module set differs'),
        )
        for change,message in cases:
            with self.subTest(message=message):
                self.rule_refused(change, message)

    def test_d22r_minimum_gain_is_recomputed(self):
        def lower_gain(d):
            d['reopen_seconds']={'A':[20.0,20.0],'B':[16.1,16.1]}
            d['improvement_seconds']=3.9
            d['improvement_fraction']=0.195
        self.rule_refused(lower_gain, 'frozen selection rule')

    def test_selection_evidence_must_equal_the_record(self):
        for key in SELECTION.D10_FIELDS:
            with self.subTest(key=key):
                self.refused_after_map_change(lambda m, key=key: m['evidence']['d10'].__setitem__(key, 'x'),
                                              'Selection evidence differs')
        self.refused_after_map_change(lambda m: m['evidence']['d10'].__setitem__('record', 'elsewhere.json'),
                                      'Selection evidence differs')
        self.refused_after_map_change(lambda m: m.pop('evidence'), 'Selection evidence differs')
        saved = copy.deepcopy(self.results)
        self.results['d10'].pop('label')
        self.write_results()
        self.refused_after_map_change(lambda m: m['evidence']['d10'].pop('label'), 'Selection evidence differs')
        self.results = saved
        self.write_results()

    def test_selection_identities_must_be_digests(self):
        for key in ('candidate_selection_sha256', 'base_selection_sha256', 'candidate_overlay_identity_sha256'):
            with self.subTest(key=key):
                self.refused_after_map_change(lambda m, key=key: m.pop(key), 'lacks the candidate selection|'
                                              'overlay identity differs')

    def test_d10_must_measure_the_selected_reader_bytes(self):
        for key in ('candidate_reader_sha256', 'baseline_reader_sha256'):
            with self.subTest(key=key):
                saved = self.results['d10'][key]
                self.results['d10'][key] = '5' * 64
                self.write_results()
                self.refused_after_map_change(lambda m, key=key: m['evidence']['d10'].__setitem__(key, '5' * 64),
                                              'did not measure the selected reader bytes')
                self.results['d10'][key] = saved
                self.write_results()

    def test_d10_must_compare_the_candidate_compositions(self):
        for key in ('candidate_private_composition_sha256', 'baseline_private_composition_sha256'):
            with self.subTest(key=key):
                saved = self.results['d10'][key]
                self.results['d10'][key] = '6' * 64
                self.write_results()
                self.refused_after_map_change(lambda m, key=key: m['evidence']['d10'].__setitem__(key, '6' * 64),
                                              'did not compare the candidate compositions')
                self.results['d10'][key] = saved
                self.write_results()

    def test_materialised_candidate_drift_is_refused(self):
        for key, value in (('status', 'SELECTED'), ('source_map_sha256', '7' * 64), ('selection_sha256', '7' * 64),
                           ('base_selection_sha256', '7' * 64), ('overlay_identity_sha256', '7' * 64),
                           ('selected', True), ('runtime_admission', True)):
            with self.subTest(key=key):
                self.manifest_edits = {key: value}
                self.assert_refused('Materialised candidate differs')
        self.manifest_edits = {'source_members': 646}
        self.assert_refused('member count differs')
        self.manifest_edits = {}

    def test_materialised_file_drift_is_refused(self):
        for name in ('helpers/record_views.py', 'src/module000.py', 'helpers/test_l3_carried_pages.py'):
            with self.subTest(name=name):
                self.file_edits = {name: b'drifted source\n'}
                self.assert_refused('Pinned input changed: ' + name)
        self.file_edits = {}

    def test_existing_destination_and_late_failure_are_atomic(self):
        self.output.mkdir()
        marker = self.output / 'keep.txt'
        marker.write_text('untouched', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            SELECTION.materialise(self.repo, self.output)
        self.assertEqual(marker.read_text(encoding='utf-8'), 'untouched')
        self.output = self.root / 'other-selection'

        def fail_after_partial_write(repo, stage):
            stage.mkdir()
            (stage / 'partial').write_bytes(b'disposable')
            raise OSError('injected staging failure')

        self.candidate.materialise = fail_after_partial_write
        self.assert_refused('injected staging failure')

    def test_cli_turns_malformed_maps_into_refusals(self):
        path = self.repo / (SELECTION.PREFIX + 'SOURCE-MAP.json')
        candidate_map = json.loads(path.read_bytes())
        candidate_map.pop('entries')
        path.write_bytes(encoded(candidate_map))
        self.candidate.MAP_SHA = self.file_pin(SELECTION.PREFIX + 'SOURCE-MAP.json')
        self.mapping['candidate_source_map']['sha256'] = self.candidate.MAP_SHA
        self.repin_map()
        errors = io.StringIO()
        with patch('sys.argv', ['build_selection.py', '--repo', str(self.repo), '--output', str(self.output)]), \
                contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
            SELECTION.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('Plan22 selection construction refused:', errors.getvalue())
        self.assertFalse(self.output.exists())

    def test_cli_turns_arithmetic_errors_into_refusals(self):
        for error in (ZeroDivisionError('division by zero'), OverflowError('too large')):
            with self.subTest(error=type(error).__name__):
                errors = io.StringIO()
                argv = ['build_selection.py', '--repo', str(self.repo), '--output', str(self.output)]
                with patch.object(SELECTION, 'materialise', side_effect=error), patch('sys.argv', argv), \
                        contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
                    SELECTION.main()
                self.assertEqual(caught.exception.code, 1)
                self.assertIn('Plan22 selection construction refused:', errors.getvalue())

    def test_cli_reports_refusal_with_exit_one(self):
        errors = io.StringIO()
        self.candidate.FROZEN = False
        with patch('sys.argv', ['build_selection.py', '--repo', str(self.repo), '--output', str(self.output)]), \
                contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
            SELECTION.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('Plan22 selection construction refused: The candidate builder is not frozen', errors.getvalue())
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
