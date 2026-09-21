"""Declared species sources on public graph/cache boundaries; no private model."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

from work.generator_upgrade_r11 import snapshot
from work.generator_upgrade_r22 import species
from work.generator_runtime_r12 import executor as r12, store
from work.generator_upgrade_r24 import executor as r24


def document(path, raw=b'owner selection A', status='WORKING NON-CANON'):
    context = dict(life_stage='ADULT', cohort_id='cohort', scope_id='scope',
        support_id='support', snapshot_id='snapshot', physical_scenario_id='scenario',
        time_basis='EXPLICIT_PHASE', calendar_id='calendar', phase_id='phase',
        within_period_aggregation='HELD_CONSTANT', joint_scenario_id='selection',
        natural_or_managed='NATURAL', counting_unit='entities', native_measure_unit='m2',
        start_seconds='0', duration_seconds='10', time_units_seconds={})
    ref = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), locator='selection',
               raw_source_status=status)
    rows = [dict(record_id=field, organism_id='TEST', kind='ANIMAL', field_id=field,
        value=value, unit=unit, source_status=status, model_use='SELECTED_FOR_R22',
        evidence='Synthetic code-review fixture; no actual organism claim',
        source_refs=[deepcopy(ref)], use_decision_ref=deepcopy(ref), context=deepcopy(context))
        for field, value, unit in [('residence.scoped_cohort_entities', 2, 'entities'),
                                   ('residence.fraction', '1/2', '1')]]
    return dict(schema=species.SCHEMA, scope=status,
        source_bindings=[{key: ref[key] for key in ('path', 'sha256')}], records=rows), context


class SpeciesSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='atlas-species-source-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'selection.txt'
        self.source.write_bytes(b'owner selection A')
        self.document, self.context = document(self.source)

    def test_working_sources_require_current_bytes(self):
        register = species.Registry(self.document)
        register.verify_sources()
        before = self.source.stat()
        self.source.write_bytes(b'owner selection B')
        os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'source changed'):
            register.verify_sources()
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'regular source required'):
            register.verify_sources()

    def test_native_species_invocation_authenticates_declared_sources(self):
        from work.generator_upgrade_r22 import registry
        arguments = dict(register_document=self.document, organism_id='TEST', context=self.context)
        result = registry.invoke('species_residence', arguments, cache=False)
        self.assertEqual(result['entity_seconds'], '10')
        self.source.write_bytes(b'owner selection B')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            registry.invoke('species_residence', arguments, cache=False)
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'regular source required'):
            registry.invoke('species_residence', arguments, cache=False)

    def test_synthetic_marker_is_explicit_and_never_exempts_file_sources(self):
        synthetic, _ = document('SYNTHETIC_ONLY_SOURCE', status='SYNTHETIC TEST')
        species.Registry(synthetic).verify_sources()
        for change in ('scope', 'field', 'reference'):
            bad = deepcopy(synthetic)
            if change == 'scope':
                bad['scope'] = 'WORKING NON-CANON'
            elif change == 'field':
                bad['records'][0]['source_status'] = 'WORKING NON-CANON'
            else:
                bad['records'][0]['source_refs'][0]['raw_source_status'] = 'CANON'
            with self.subTest(change=change), self.assertRaises(ValueError):
                species.Registry(bad).verify_sources()
        missing, _ = document(self.root / 'missing.txt', status='SYNTHETIC TEST')
        with self.assertRaisesRegex(ValueError, 'regular source required'):
            species.Registry(missing).verify_sources()

    def test_references_without_path_and_hash_are_not_bound(self):
        for key in ('source_refs', 'use_decision_ref'):
            bad = deepcopy(self.document)
            ref = bad['records'][0][key][0] if key == 'source_refs' else bad['records'][0][key]
            del ref['path']; del ref['sha256']
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'unbound field source'):
                species.Registry(bad)

    def graph(self, dependency=False):
        ctx = dict(zip(snapshot.FRAME_FIELDS,
                       ('world', 'snapshot', 'calendar', 'frame', 'datum', 'scenario')))
        port = dict(quantity='BOUND_COMPONENT_RECEIPT', unit='1', support_id='support',
                    temporal_support='phase')
        # This is a new synthetic producer identity, not a historical native seal.
        pins = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                (Path(__file__), Path(species.__file__))}
        signature = snapshot.sha(dict(pins=pins, python=sys.version, executable=sys.executable))
        calls = []

        def verify():
            for path, digest in pins.items():
                self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)

        def produce(context, inputs, incoming):
            arguments = {**inputs, **incoming}
            register = species.Registry(arguments['register_document'])
            register.verify_sources()
            calls.append('species')
            result = species.residence_exposure(register, 'TEST', self.context)
            register.verify_sources()
            return snapshot.emission(context, {'result': port}, {'result': result},
                                     evidence='Synthetic source-bound component fixture')

        def supply(context, inputs, incoming):
            calls.append('register')
            return snapshot.emission(context, {'result': port},
                {'result': inputs['document']}, evidence='Synthetic upstream register fixture')

        def stage(ident, operation, inputs, dependencies):
            return dict(stage_id=ident, category='plant_animal_ranges', producer_id=operation,
                producer_sha256=signature, inputs=inputs, dependencies=dependencies,
                outputs={'result': deepcopy(port)}, missing_inputs=[], mode='GENERATED',
                acceptance=dict(status='PENDING', evidence='Synthetic fixture only'))

        stages = [stage('species', 'species_residence',
                        {} if dependency else {'register_document': self.document},
                        {'register_document': dict(stage_id='register', output='result',
                            port=deepcopy(port))} if dependency else {})]
        if dependency:
            stages.insert(0, stage('register', 'supply_register', {'document': self.document}, {}))
        recipe = dict(schema='diadem.snapshot-graph-recipe.r11', context=ctx, stages=stages,
                      required_categories=['plant_animal_ranges'], evidence='Synthetic fixture only')
        registry = {'species_residence': dict(sha256=signature, run=produce, verify=verify),
                    'supply_register': dict(sha256=signature, run=supply, verify=verify)}
        return recipe, registry, calls, signature

    def test_authenticated_warm_and_resume_reject_source_drift(self):
        for executor in (r12, r24):
            for dependency in (False, True):
                with self.subTest(executor=executor.__name__, dependency=dependency):
                    self.source.write_bytes(b'owner selection A')
                    recipe, registry, calls, signature = self.graph(dependency)
                    cache = store.Store(self.root / ('cache-' + executor.__name__.split('.')[1]
                                                    + str(dependency)), signature)
                    restored, computed = [], []
                    def on_computed(ident, row):
                        computed.append(ident)
                        return {'artifacts': {}, 'diagnostics': {}}
                    def execute(resume=None):
                        hooks = species.source_hooks(recipe,
                            on_restore=lambda ident, record: restored.append(ident),
                            on_computed=on_computed)
                        return executor.run(snapshot, recipe, registry, store=cache,
                                            resume=resume, **hooks)
                    cold = execute()
                    checkpoint = snapshot.checkpoint(cold)
                    count = len(calls)
                    self.assertEqual(execute(), cold)
                    self.assertEqual(execute(checkpoint), cold)
                    self.assertEqual(len(calls), count)
                    self.assertEqual(len(computed), len(recipe['stages']))
                    self.assertEqual(len(restored), 2 * len(recipe['stages']))
                    self.assertEqual(cold['state']['rows']['species']['product']['values']
                                     ['result']['entity_seconds'], '10')
                    for missing in (False, True):
                        if missing:
                            self.source.unlink()
                        else:
                            before = self.source.stat()
                            self.source.write_bytes(b'owner selection B')
                            os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
                        for resume in (None, checkpoint):
                            with self.subTest(missing=missing, resumed=resume is not None):
                                with self.assertRaises(ValueError):
                                    execute(resume)
                                self.assertEqual(len(calls), count)

    def test_missing_input_still_abstains_without_source_claim(self):
        recipe, registry, calls, signature = self.graph()
        recipe['stages'][0]['inputs'] = {}
        recipe['stages'][0]['missing_inputs'] = ['owner register unavailable']
        result = r24.run(snapshot, recipe, registry, **species.source_hooks(recipe))
        self.assertEqual(result['state']['rows']['species']['product']['status'], 'UNKNOWN')
        self.assertEqual(calls, [])

    def test_streamed_result_source_drift_is_refused_before_cache_commit(self):
        recipe, registry, calls, signature = self.graph()
        cache = store.Store(self.root / 'stream-cache', signature)
        source = self.source

        class CompletionBackend:
            capacity = 1

            def submit(self, jobs):
                self.records = {job['stage_id']: {
                    'product': registry[job['producer_id']]['run'](
                        job['context'], job['inputs'], job['incoming']),
                    'artifacts': {}, 'diagnostics': {}} for job in jobs}

            def receive(self):
                # The completed calculation used the original bound bytes.
                # A changed source must still block coordinator acceptance.
                source.write_bytes(b'owner selection B')
                return self.records

        with self.assertRaisesRegex(ValueError, 'source changed') as caught:
            r24.run(snapshot, recipe, registry, store=cache,
                    backend=CompletionBackend(), **species.source_hooks(recipe))
        self.assertEqual(calls, ['species'])
        self.assertEqual(cache.stats['writes'], 0)
        self.assertEqual(caught.exception.snapshot_checkpoint['state']['completed_stages'], 0)


if __name__ == '__main__':
    unittest.main()
