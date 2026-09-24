"""Bounded UI adapter for actual new-world candidate projects.

SPDX-License-Identifier: AGPL-3.0-only

Managed local paths belong to the calling server, never browser-supplied paths.
Generation is explicit; reading returns the saved geometry without regenerating.
The adapter stays outside the source-bound scientific package.
The v1 response envelope carries an atlas.world-view.v3 view. Legacy projects
have null structure and/or motion, with the corresponding capabilities false.
New projects include native initial structure and motion. All three stages share
one cooperative deadline; no request identity or resource limit is rewritten.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
import json
import os
from pathlib import Path
import sys
import time

from new_world import _bounded_read, _checked_path, _Directory
from new_world_contract import ContractError, resolve_request
from new_world_layout import generate_layout_candidate
from new_world_project import SavedProject, save_project, load_project
from new_world_structure import generate_structure, structure_view

RESPONSE_SCHEMA = 'atlas.world-session-response.v1'
VIEW_SCHEMA = 'atlas.world-view.v3'
MAX_OUTPUT_BYTES = 2 << 20
MAX_SUPPORT_CELLS = 1024
MAX_WORK_BYTES = 256 << 20
MAX_WALL_SECONDS = 120
MESSAGES = {
    'INVALID_ARGUMENTS': 'Use generate --file PATH or read --file PATH.',
    'INVALID_REQUEST': 'A title and valid New World request are required.',
    'INVALID_TITLE': 'Use a nonempty title of at most 160 characters without control characters.',
    'INVALID_JSON': 'The New World request contains invalid JSON.',
    'INPUT_TOO_LARGE': 'The New World request exceeds 64 KiB.',
    'INTERACTIVE_LIMIT': 'Interactive worlds support up to 1024 support cells, 256 MiB work and 120 seconds.',
    'OUTPUT_LIMIT': 'The saved world is too large for this interactive view.',
    'FILE_EXISTS': 'The destination already exists; no world was replaced.',
    'FILE_NOT_FOUND': 'The world file or its managed directory is missing.',
    'INVALID_PATH': 'The managed world path is invalid.',
    'UNSAFE_PATH': 'The managed world path changed or contains a link.',
    'INVALID_PROJECT': 'The world file is damaged, inconsistent or unsupported.',
    'SOURCE_MISMATCH': 'The source changed during generation; nothing was rebound.',
    'MEMORY_LIMIT': 'The requested initial world exceeds its work-memory limit.',
    'TIME_LIMIT': 'World generation exceeded its time limit.',
    'CANCELLED': 'World generation was cancelled.',
    'GEOMETRY_REFUSED': 'This seed and settings could not form a valid layout within their limits.',
    'STRUCTURE_REFUSED': 'This seed and settings could not form a valid initial structure within their limits.',
    'MOTION_REFUSED': 'These upstream fields could not form valid initial motion within their limits.',
    'IO_ERROR': 'The local world file operation could not be completed.',
    'INTERNAL_ERROR': 'The world operation failed; the current world should be retained.',
}


def _fail(code):
    raise ContractError(code, MESSAGES[code])


def _encode(value):
    # Geometry can contain more nodes than the deliberately small S1 JSON limit.
    # All numbers come from a verified native atlas; reject non-finite values.
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('ascii')


def _interactive_request(plan):
    request = plan['request']
    if (request['resolution']['support_cells'] > MAX_SUPPORT_CELLS
            or request['resources']['max_work_bytes'] > MAX_WORK_BYTES
            or request['resources']['max_wall_seconds'] > MAX_WALL_SECONDS):
        _fail('INTERACTIVE_LIMIT')


def generate_motion(plan, candidate, structure, *, cancel=None):
    """Load the motion producer only for an explicit generation request."""
    from new_world_motion import generate_motion as generate
    return generate(plan, candidate, structure, cancel=cancel)


def motion_view(motion):
    from new_world_motion import motion_view as view
    return view(motion)


class _GenerationDeadline:
    """One cooperative wall limit shared by all native generation stages."""
    def __init__(self, seconds):
        self.end = time.perf_counter() + seconds

    def is_set(self):
        return time.perf_counter() >= self.end

    def check(self):
        if self.is_set():
            _fail('TIME_LIMIT')


def world_view(project):
    """Indexed unit-sphere geometry, including real plate rather than tile edges.

    Ring cycles omit a repeated closing vertex; close the last vertex to the
    first along the minor great-circle arc. Outer rings and holes retain native
    orientation. Structure is the restored/generated native S3 record when
    present; legacy projects return null, without manufacturing missing fields.
    """
    if type(project) is not SavedProject:
        _fail('INVALID_PROJECT')
    if project.motion is not None and project.structure is None:
        _fail('INVALID_PROJECT')
    atlas, manifest = project.atlas, project.manifest
    if len(atlas.patches) > MAX_SUPPORT_CELLS:
        _fail('INTERACTIVE_LIMIT')
    vertices = {name: index for index, name in enumerate(atlas.vertex_ids)}
    plates = {name: index for index, name in enumerate(atlas.plate_ids)}
    geometry = dict(coordinate_system='unit-sphere',
        vertices=atlas.vertex_directions.tolist(), plate_ids=list(atlas.plate_ids),
        patches=[dict(plate_index=plates[patch.plate_id],
                      rings=[[vertices[name] for name in ring] for ring in patch.rings])
                 for patch in atlas.patches],
        boundary_edges=[atlas.edge_vertices[index].tolist() for index in atlas.interplate_edges],
        boundary_edge_indices=[int(index) for index in atlas.interplate_edges])
    # Detach public JSON, and omit private local paths and verbose native reports.
    view = dict(schema=VIEW_SCHEMA, project_id=manifest['project_id'],
        title=manifest['title'], status=manifest['status'], atlas_id=atlas.atlas_id,
        geometry_id=atlas.geometry_id, request=manifest['plan']['request'],
        resolved_settings=manifest['plan']['resolved_settings'],
        configuration_compatible=project.configuration_compatible,
        capabilities=dict(save_world=True, load_world=True, candidate_geometry=True,
                          evolve_world=False, native_restart=False,
                          initial_structure=project.structure is not None,
                          initial_motion=project.motion is not None), geometry=geometry,
        structure=None if project.structure is None else structure_view(project.structure),
        motion=None if project.motion is None else motion_view(project.motion))
    encoded = _encode(view)
    if len(encoded) + 256 > MAX_OUTPUT_BYTES:
        _fail('OUTPUT_LIMIT')
    return json.loads(encoded)


def _new_destination(raw_path):
    path, parents = _checked_path(os.fspath(raw_path))
    with _Directory(path.parent, parents) as directory:
        try:
            directory.inspect(path.name)
        except FileNotFoundError:
            return
        _fail('FILE_EXISTS')


def response(argv, stdin):
    """Complete path-free response; server retains its old world on every error."""
    try:
        if len(argv) != 3 or argv[1] != '--file' or argv[0] not in ('generate', 'read'):
            _fail('INVALID_ARGUMENTS')
        action, raw_path = argv[0], argv[2]
        if action == 'read':
            project = load_project(raw_path)
            data = world_view(project)
        else:
            body = _bounded_read(stdin)
            if type(body) is not dict or set(body) != {'title', 'request'}:
                _fail('INVALID_REQUEST')
            title = body['title']
            if (type(title) is not str or not title.strip() or len(title) > 160
                    or any(ord(char) < 32 for char in title)):
                _fail('INVALID_TITLE')
            plan = resolve_request(body['request'])
            _interactive_request(plan)
            _new_destination(raw_path)
            # Native imports are normally supplied by the server's runtime. Also
            # support direct local invocation, matching the project reader.
            source = str(Path(__file__).resolve().parents[1] / 'src')
            if source not in sys.path:
                sys.path.insert(0, source)
            deadline = _GenerationDeadline(plan['request']['resources']['max_wall_seconds'])
            structure = generate_structure(plan)
            deadline.check()
            if structure is None:
                _fail('STRUCTURE_REFUSED')
            try:
                candidate = generate_layout_candidate(plan, cancel=deadline)
            except CancelledError:
                # This adapter supplies only its own deadline cancellation token.
                _fail('TIME_LIMIT')
            deadline.check()
            if candidate.atlas is None:
                code = candidate.report.get('rejection', {}).get('code', 'INTERNAL_ERROR')
                _fail(code if code in MESSAGES else 'INTERNAL_ERROR')
            try:
                motion = generate_motion(plan, candidate, structure, cancel=deadline)
            except CancelledError:
                _fail('TIME_LIMIT')
            deadline.check()
            if motion is None:
                _fail('MOTION_REFUSED')
            # Refuse an oversized view before publishing a project. A real ID is
            # substituted after atomic save; all other view fields are unchanged.
            preview_manifest = dict(title=title, plan=plan, status='WORKING NON-CANON', project_id='0'*64)
            data = world_view(SavedProject(preview_manifest, candidate.atlas, True, structure, motion))
            deadline.check()
            manifest = save_project(raw_path, plan, candidate, title=title,
                                    structure=structure, motion=motion)
            data['project_id'] = manifest['project_id']
        answer = dict(schema=RESPONSE_SCHEMA, status='ok', data=data)
        if len(_encode(answer)) > MAX_OUTPUT_BYTES:
            _fail('OUTPUT_LIMIT')
        return answer, 0
    except ContractError as exc:
        # S1 exposes more precise validation codes. Preserve known safe codes;
        # their detailed messages are deliberately not reflected to the browser.
        code = exc.code if exc.code in MESSAGES else 'INVALID_REQUEST'
    except FileNotFoundError:
        code = 'FILE_NOT_FOUND'
    except FileExistsError:
        code = 'FILE_EXISTS'
    except OSError:
        code = 'IO_ERROR'
    except (ValueError, KeyError, TypeError):
        code = 'INVALID_PROJECT'
    except Exception:
        code = 'INTERNAL_ERROR'
    return dict(schema=RESPONSE_SCHEMA, status='error',
                error=dict(code=code, message=MESSAGES[code])), 2


def main(argv=None):
    answer, status = response(sys.argv[1:] if argv is None else argv,
                              getattr(sys.stdin, 'buffer', sys.stdin))
    sys.stdout.buffer.write(_encode(answer) + b'\n')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
