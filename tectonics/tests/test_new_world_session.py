"""Bounded desktop bridge checks; one shared real native geometry fixture."""
from concurrent.futures import CancelledError
import copy
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TECTONICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TECTONICS / 'tools'))
sys.path.insert(0, str(TECTONICS / 'src'))

import new_world_contract as contract
import new_world_layout as layout
import new_world_project as project
import new_world_session as session
import new_world_structure as structure_api
import new_world_motion as motion_api


class WorldSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = dict(
            radius_m=dict(mode='fixed', value=6371000.),
            gravity_m_s2=dict(mode='fixed', value=9.81),
            plate_count=dict(mode='fixed', value=6),
            continental_fraction=dict(mode='fixed', value=.3),
        )
        cls.plan = contract.resolve_request(contract.new_request(
            f'{41:032x}', settings=settings, support_cells=192,
            resources=dict(max_work_bytes=128 << 20, max_wall_seconds=30.)))
        cls.candidate = layout.generate_layout_candidate(cls.plan)
        if cls.candidate.atlas is None:
            raise AssertionError('The fixed N6/support192/seed41 candidate refused: '
                                 + repr(cls.candidate.report['rejection']))
        cls.structure = structure_api.generate_structure(cls.plan)
        cls.motion = motion_api.generate_motion(cls.plan, cls.candidate, cls.structure)
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.saved_path = Path(temporary.name) / 'session.atlas'
        project.save_project(cls.saved_path, cls.plan, cls.candidate, title='Session fixture')
        cls.saved = project.load_project(cls.saved_path)
        cls.saved_bytes = cls.saved_path.read_bytes()
        cls.structured_path = Path(temporary.name) / 'structured-session.atlas'
        project.save_project(cls.structured_path, cls.plan, cls.candidate,
                             title='Session fixture', structure=cls.structure)
        cls.motion_path = Path(temporary.name) / 'motion-session.atlas'
        project.save_project(cls.motion_path, cls.plan, cls.candidate,
                             title='Session fixture', structure=cls.structure, motion=cls.motion)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'new.atlas'

    def body(self, **changes):
        record = dict(title='Session fixture', request=copy.deepcopy(self.plan['request']))
        record.update(changes)
        return record

    def call(self, *args, body=b''):
        if not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False).encode('utf-8')
        return session.response(list(args), io.BytesIO(body))

    def assert_error(self, result, code=None, private=None):
        record, exitcode = result
        self.assertEqual(exitcode, 2, record)
        self.assertEqual(set(record), {'schema', 'status', 'error'})
        self.assertEqual(record['schema'], 'atlas.world-session-response.v1')
        self.assertEqual(record['status'], 'error')
        self.assertEqual(set(record['error']), {'code', 'message'})
        self.assertIs(type(record['error']['code']), str)
        self.assertIs(type(record['error']['message']), str)
        if code is not None:
            self.assertEqual(record['error']['code'], code)
        if private is not None:
            self.assertNotIn(str(private), record['error']['message'])
            self.assertNotIn(str(private), record['error']['code'])

    def test_view_preserves_native_vertices_rings_and_only_interplate_edges(self):
        view = session.world_view(self.saved)
        atlas = self.saved.atlas
        self.assertEqual(set(view), {
            'schema', 'project_id', 'title', 'status', 'atlas_id', 'geometry_id',
            'request', 'resolved_settings', 'configuration_compatible', 'capabilities', 'geometry',
            'structure', 'motion',
        })
        self.assertEqual(view['schema'], 'atlas.world-view.v3')
        self.assertIsNone(view['structure'])
        self.assertIsNone(view['motion'])
        self.assertEqual(view['project_id'], self.saved.manifest['project_id'])
        self.assertEqual(view['atlas_id'], atlas.atlas_id)
        self.assertEqual(view['geometry_id'], atlas.geometry_id)
        self.assertEqual(view['title'], 'Session fixture')
        self.assertEqual(view['request'], self.plan['request'])
        self.assertEqual(view['resolved_settings'], self.plan['resolved_settings'])
        geometry = view['geometry']
        self.assertEqual(set(geometry), {'coordinate_system', 'vertices', 'plate_ids',
                                         'patches', 'boundary_edges', 'boundary_edge_indices'})
        self.assertEqual(geometry['coordinate_system'], 'unit-sphere')
        self.assertEqual(geometry['vertices'], atlas.vertex_directions.tolist())
        self.assertEqual(geometry['plate_ids'], list(atlas.plate_ids))
        vertices = {name: index for index, name in enumerate(atlas.vertex_ids)}
        plates = {name: index for index, name in enumerate(atlas.plate_ids)}
        expected = [dict(plate_index=plates[patch.plate_id],
                         rings=[[vertices[name] for name in ring] for ring in patch.rings])
                    for patch in atlas.patches]
        self.assertEqual(geometry['patches'], expected)
        # Determine ownership from the real native adjacency, independently of
        # the bridge's edge selection. Patch seams must not become plate edges.
        edges = [atlas.edge_vertices[index].tolist()
                 for index, (left, right) in enumerate(atlas.side_patches)
                 if atlas.patches[left].plate_id != atlas.patches[right].plate_id]
        self.assertGreater(len(edges), 0)
        self.assertLess(len(edges), len(atlas.edge_vertices))
        self.assertEqual(geometry['boundary_edges'], edges)
        self.assertEqual(geometry['boundary_edge_indices'], list(atlas.interplate_edges))
        self.assertEqual(len(geometry['boundary_edge_indices']), len(edges))
        self.assertTrue(all(type(index) is int for index in geometry['boundary_edge_indices']))

    def test_view_plain_types_detachment_and_inspection_only_capabilities(self):
        view = session.world_view(self.saved)
        self.assertEqual(view['status'], 'WORKING NON-CANON')
        self.assertEqual(view['capabilities'], dict(
            save_world=True, load_world=True, candidate_geometry=True,
            evolve_world=False, native_restart=False, initial_structure=False, initial_motion=False))
        self.assertIs(view['configuration_compatible'], True)
        for patch in view['geometry']['patches']:
            self.assertIs(type(patch['plate_index']), int)
            self.assertTrue(all(type(index) is int for ring in patch['rings'] for index in ring))
        self.assertTrue(all(type(index) is int for edge in view['geometry']['boundary_edges'] for index in edge))
        encoded = json.dumps(view, allow_nan=False).encode('utf-8')
        self.assertLessEqual(len(encoded), session.MAX_OUTPUT_BYTES)
        self.assertEqual(session.MAX_OUTPUT_BYTES, 2 << 20)
        self.assertEqual(session.RESPONSE_SCHEMA, 'atlas.world-session-response.v1')
        self.assertEqual(session.VIEW_SCHEMA, 'atlas.world-view.v3')
        stale = session.world_view(replace(self.saved, configuration_compatible=False))
        self.assertIs(stale['configuration_compatible'], False)
        self.assertFalse(stale['capabilities']['native_restart'])
        view['request']['seed'] = '0' * 32
        view['geometry']['vertices'][0][0] = 999.
        fresh = session.world_view(self.saved)
        self.assertEqual(fresh['request']['seed'], f'{41:032x}')
        self.assertEqual(fresh['geometry']['vertices'], self.saved.atlas.vertex_directions.tolist())

    def test_generate_resolves_exact_request_runs_once_and_saves_once(self):
        body = self.body()
        with mock.patch.object(session, 'resolve_request', wraps=contract.resolve_request) as resolve, \
             mock.patch.object(session, 'generate_structure', return_value=self.structure) as structure_generate, \
             mock.patch.object(session, 'generate_motion', return_value=self.motion) as motion_generate, \
             mock.patch.object(session, 'generate_layout_candidate', return_value=self.candidate) as generate, \
             mock.patch.object(session, 'save_project', wraps=project.save_project) as save:
            result, exitcode = self.call('generate', '--file', str(self.target), body=body)
        self.assertEqual(exitcode, 0, result)
        self.assertEqual(set(result), {'schema', 'status', 'data'})
        self.assertEqual(result['schema'], session.RESPONSE_SCHEMA)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['schema'], session.VIEW_SCHEMA)
        resolve.assert_called_once_with(body['request'])
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[0], self.plan)
        structure_generate.assert_called_once_with(self.plan)
        self.assertIsInstance(generate.call_args.kwargs['cancel'], session._GenerationDeadline)
        motion_generate.assert_called_once_with(
            self.plan, self.candidate, self.structure, cancel=generate.call_args.kwargs['cancel'])
        save.assert_called_once()
        self.assertEqual(Path(save.call_args.args[0]), self.target)
        self.assertEqual(save.call_args.args[1], self.plan)
        self.assertIs(save.call_args.args[2], self.candidate)
        self.assertEqual(save.call_args.kwargs.get('title'), 'Session fixture')
        self.assertIs(save.call_args.kwargs['structure'], self.structure)
        self.assertIs(save.call_args.kwargs['motion'], self.motion)
        self.assertEqual(result['data']['request']['seed'], f'{41:032x}')
        self.assertEqual(result['data']['atlas_id'], self.candidate.atlas.atlas_id)
        self.assertEqual(result['data']['structure'], structure_api.structure_view(self.structure))
        self.assertTrue(result['data']['capabilities']['initial_structure'])
        self.assertTrue(result['data']['capabilities']['initial_motion'])
        self.assertEqual(result['data']['motion'], motion_api.motion_view(self.motion))
        edge_indices = result['data']['geometry']['boundary_edge_indices']
        self.assertEqual(len(edge_indices), len(result['data']['geometry']['boundary_edges']))
        self.assertTrue({segment['edge_index'] for segment in result['data']['motion']['segments']}
                        <= set(edge_indices))
        self.assertTrue(self.target.is_file())
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_read_uses_saved_geometry_without_resolving_generating_or_saving(self):
        failure = AssertionError('Read must only reopen the saved project.')
        with mock.patch.object(session, 'resolve_request', side_effect=failure), \
             mock.patch.object(session, 'generate_structure', side_effect=failure), \
             mock.patch.object(session, 'generate_motion', side_effect=failure), \
             mock.patch.object(session, 'generate_layout_candidate', side_effect=failure), \
             mock.patch.object(session, 'save_project', side_effect=failure), \
             mock.patch.object(session, 'load_project', wraps=project.load_project) as load:
            result, exitcode = self.call('read', '--file', str(self.saved_path))
        self.assertEqual(exitcode, 0, result)
        load.assert_called_once()
        self.assertEqual(result['data'], session.world_view(self.saved))
        self.assertEqual(self.saved_path.read_bytes(), self.saved_bytes)

    def test_v2_read_restores_structure_without_any_generation(self):
        failure = AssertionError('Reading an S3 project must not generate native state.')
        before = self.structured_path.read_bytes()
        with mock.patch.object(session, 'generate_structure', side_effect=failure), \
             mock.patch.object(session, 'generate_motion', side_effect=failure), \
             mock.patch.object(session, 'generate_layout_candidate', side_effect=failure), \
             mock.patch.object(session, 'save_project', side_effect=failure):
            result, status = self.call('read', '--file', str(self.structured_path))
        self.assertEqual(status, 0, result)
        self.assertEqual(result['data']['schema'], 'atlas.world-view.v3')
        self.assertIsNone(result['data']['motion'])
        self.assertFalse(result['data']['capabilities']['initial_motion'])
        self.assertEqual(result['data']['structure'], structure_api.structure_view(self.structure))
        self.assertTrue(result['data']['capabilities']['initial_structure'])
        self.assertFalse(result['data']['capabilities']['native_restart'])
        self.assertEqual(self.structured_path.read_bytes(), before)

    def test_v3_read_restores_motion_without_any_generation(self):
        failure = AssertionError('Read must not generate initial motion or upstream fields.')
        before = self.motion_path.read_bytes()
        with mock.patch.object(session, 'generate_structure', side_effect=failure), \
             mock.patch.object(session, 'generate_layout_candidate', side_effect=failure), \
             mock.patch.object(session, 'generate_motion', side_effect=failure), \
             mock.patch.object(session, 'save_project', side_effect=failure):
            result, status = self.call('read', '--file', str(self.motion_path))
        self.assertEqual(status, 0, result)
        self.assertEqual(result['data']['schema'], 'atlas.world-view.v3')
        self.assertEqual(result['data']['motion'], motion_api.motion_view(self.motion))
        self.assertTrue(result['data']['capabilities']['initial_motion'])
        self.assertFalse(result['data']['capabilities']['native_restart'])
        self.assertLessEqual(len(session._encode(result)), session.MAX_OUTPUT_BYTES)
        self.assertEqual(self.motion_path.read_bytes(), before)

    def test_interactive_limits_refuse_before_generating_or_saving(self):
        for section, name, value in (
            ('resolution', 'support_cells', 2048),
            ('resources', 'max_wall_seconds', 121.),
            ('resources', 'max_work_bytes', (256 << 20) + 1),
        ):
            body = self.body()
            body['request'][section][name] = value
            with self.subTest(name=name), \
                 mock.patch.object(session, 'generate_layout_candidate') as generate, \
                 mock.patch.object(session, 'generate_structure') as structure_generate, \
                 mock.patch.object(session, 'save_project') as save:
                self.assert_error(self.call('generate', '--file', str(self.target), body=body),
                                  'INTERACTIVE_LIMIT', self.root)
            generate.assert_not_called(); save.assert_not_called()
            structure_generate.assert_not_called()
            self.assertFalse(self.target.exists())

    def test_strict_json_title_arguments_and_request_refuse_without_seed_fallback(self):
        unknown = self.body(extra=True)
        bad_request = self.body()
        bad_request['request']['seed'] = 'not-a-seed'
        bodies = [b'{', b'{"title":"a","title":"b"}', b'{"value":NaN}',
                  b' ' * (65536 + 1), b'\xff', unknown, bad_request]
        bodies.extend(self.body(title=title) for title in ('', '  ', 'x' * 161, 'line\nbreak', True))
        with mock.patch.object(session, 'generate_layout_candidate') as generate, \
             mock.patch.object(session, 'generate_structure') as structure_generate, \
             mock.patch.object(session, 'save_project') as save, \
             mock.patch.object(contract, 'new_request', side_effect=AssertionError('No random fallback.')):
            for index, body in enumerate(bodies):
                with self.subTest(index=index):
                    self.assert_error(self.call('generate', '--file', str(self.target), body=body), private=self.root)
            for args in ((), ('evolve',), ('generate', '--file'), ('read',)):
                with self.subTest(args=args):
                    self.assert_error(self.call(*args), private=self.root)
        generate.assert_not_called(); save.assert_not_called()
        structure_generate.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_and_unsafe_destinations_refuse_before_native_work(self):
        self.target.write_bytes(b'preserve existing project bytes')
        with mock.patch.object(session, 'generate_layout_candidate') as generate, \
             mock.patch.object(session, 'generate_structure') as structure_generate, \
             mock.patch.object(session, 'save_project') as save:
            self.assert_error(self.call('generate', '--file', str(self.target), body=self.body()),
                              'FILE_EXISTS', self.root)
            for path in ('../private.atlas', '\\\\host\\share\\private.atlas', 'NUL', 'bad\0path'):
                with self.subTest(path=path):
                    self.assert_error(self.call('generate', '--file', path, body=self.body()), private=path)
        generate.assert_not_called(); save.assert_not_called()
        structure_generate.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b'preserve existing project bytes')
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_rejected_candidate_returns_its_explicit_code_without_project(self):
        for code in ('MEMORY_LIMIT', 'TIME_LIMIT', 'GEOMETRY_REFUSED'):
            report = copy.deepcopy(self.candidate.report)
            report.update(status='REJECTED', atlas_id=None, geometry_id=None,
                          rejection=dict(code=code, message='No admissible candidate.'))
            candidate = replace(self.candidate, atlas=None, report=report)
            with self.subTest(code=code), \
                 mock.patch.object(session, 'generate_layout_candidate', return_value=candidate) as generate, \
                 mock.patch.object(session, 'generate_structure', return_value=self.structure), \
                 mock.patch.object(session, 'save_project') as save:
                self.assert_error(self.call('generate', '--file', str(self.target), body=self.body()),
                                  code, self.root)
            generate.assert_called_once(); save.assert_not_called()
            self.assertFalse(self.target.exists())

    def test_structure_and_source_refusals_do_not_run_layout_or_save(self):
        for code in ('STRUCTURE_REFUSED', 'SOURCE_MISMATCH'):
            failure = contract.ContractError(code, 'Private source path: ' + str(self.root))
            with self.subTest(code=code), \
                 mock.patch.object(session, 'generate_structure', side_effect=failure), \
                 mock.patch.object(session, 'generate_layout_candidate') as generate, \
                 mock.patch.object(session, 'save_project') as save:
                self.assert_error(self.call('generate', '--file', str(self.target), body=self.body()),
                                  code, self.root)
            generate.assert_not_called(); save.assert_not_called()
            self.assertFalse(self.target.exists())

    def test_all_generation_stages_share_one_unchanged_deadline(self):
        for expire_in in ('structure', 'layout', 'motion'):
            elapsed = [0.]
            layout_deadline = []
            clock = SimpleNamespace(perf_counter=lambda: elapsed[0])
            def make_structure(prepared):
                self.assertEqual(prepared, self.plan)
                elapsed[0] = 31. if expire_in == 'structure' else 20.
                return self.structure
            def make_layout(prepared, *, cancel):
                self.assertEqual(prepared, self.plan)
                self.assertEqual(cancel.end, 30.)
                self.assertFalse(cancel.is_set())
                layout_deadline.append(cancel)
                elapsed[0] = 31. if expire_in == 'layout' else 25.
                return self.candidate
            def make_motion(prepared, candidate, structure, *, cancel):
                self.assertEqual(prepared, self.plan)
                self.assertIs(candidate, self.candidate)
                self.assertIs(structure, self.structure)
                self.assertIs(cancel, layout_deadline[0])
                self.assertEqual(cancel.end, 30.)
                self.assertFalse(cancel.is_set())
                elapsed[0] = 31.
                return self.motion
            with self.subTest(expire_in=expire_in), \
                 mock.patch.object(session, 'time', clock), \
                 mock.patch.object(session, 'generate_structure', side_effect=make_structure), \
                 mock.patch.object(session, 'generate_layout_candidate', side_effect=make_layout) as generate, \
                 mock.patch.object(session, 'generate_motion', side_effect=make_motion) as motion_generate, \
                 mock.patch.object(session, 'save_project') as save:
                self.assert_error(self.call('generate', '--file', str(self.target), body=self.body()), 'TIME_LIMIT')
            self.assertEqual(generate.call_count, int(expire_in != 'structure'))
            self.assertEqual(motion_generate.call_count, int(expire_in == 'motion'))
            save.assert_not_called()
            self.assertFalse(self.target.exists())

    def test_motion_refusal_and_source_error_never_publish(self):
        for code in ('MOTION_REFUSED', 'SOURCE_MISMATCH'):
            failure = contract.ContractError(code, 'Private source path: ' + str(self.root))
            with self.subTest(code=code), \
                 mock.patch.object(session, 'generate_structure', return_value=self.structure), \
                 mock.patch.object(session, 'generate_layout_candidate', return_value=self.candidate), \
                 mock.patch.object(session, 'generate_motion', side_effect=failure) as generate, \
                 mock.patch.object(session, 'save_project') as save:
                self.assert_error(self.call('generate', '--file', str(self.target), body=self.body()),
                                  code, self.root)
            generate.assert_called_once(); save.assert_not_called()
            self.assertFalse(self.target.exists())

    def test_native_motion_deadline_cancellation_returns_time_limit_without_save(self):
        before = self.saved_path.read_bytes()
        elapsed = [0.]
        def cancelled_motion(plan, candidate, structure, *, cancel):
            self.assertEqual(plan, self.plan)
            self.assertIs(candidate, self.candidate)
            self.assertIs(structure, self.structure)
            elapsed[0] = 31.
            self.assertTrue(cancel.is_set())
            raise CancelledError('Private native path: ' + str(self.root))
        with mock.patch.object(session, 'time', SimpleNamespace(perf_counter=lambda: elapsed[0])), \
             mock.patch.object(session, 'generate_structure', return_value=self.structure), \
             mock.patch.object(session, 'generate_layout_candidate', return_value=self.candidate), \
             mock.patch.object(session, 'generate_motion', side_effect=cancelled_motion) as generate, \
             mock.patch.object(session, 'save_project') as save:
            self.assert_error(self.call('generate', '--file', str(self.target), body=self.body()),
                              'TIME_LIMIT', self.root)
        generate.assert_called_once(); save.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.saved_path.read_bytes(), before)

    def test_output_bound_and_io_errors_return_path_free_error_envelopes(self):
        with mock.patch.object(session, 'MAX_OUTPUT_BYTES', 1024), \
             mock.patch.object(session, 'load_project', return_value=self.saved):
            self.assert_error(self.call('read', '--file', str(self.saved_path)), private=self.saved_path)
        with mock.patch.object(session, 'load_project', side_effect=OSError('private path: ' + str(self.saved_path))):
            self.assert_error(self.call('read', '--file', str(self.saved_path)), private=self.saved_path)
        self.assertEqual(self.saved_path.read_bytes(), self.saved_bytes)


if __name__ == '__main__':
    unittest.main()
