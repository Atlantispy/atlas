"""Uninstalled exact-source factory for the q297 END provider candidate.

This is preparation only. Its package modules must be included in the selected
native source manifest and imported through the selected source fence. The caller
supplies separately pinned evidence paths; nothing here authorises a run.
"""
import importlib
import json
import threading
import weakref
from types import MappingProxyType
from typing import cast
from pathlib import Path

MODULES = {
    'provider': 'atlas_tectonics._private.integration.geometry.endpoint_geometry_provider',
    'pieces': 'atlas_tectonics._private.integration.geometry.endpoint_support_pieces',
    'piece_builder': 'atlas_tectonics._private.integration.geometry.interval_piece',
    'rays': 'atlas_tectonics._private.integration.geometry.interval_shared_rays',
    'family': 'atlas_tectonics._private.integration.geometry.material_family_pose',
    'start': 'atlas_tectonics._private.integration.geometry.material_start',
    'checkpoint': 'atlas_tectonics._private.codecs.completed_tile_checkpoint',
}
GRID_SHA = '0afc36b4b7e13d2422b34c02ea1704b099c062101e793344223ed6109939871f'
RUNS = (
    ('q297-q336-production-attempt-g-r1', '06b9cb35-ee24-4796-bf15-1b8395390514',
     'da4027b5a8e6b61b0e5b88a14cd1b2de113050643e4b1f59dd6656d4ea5e4283',
     'a3ff5a2df968d17ea33bf77452f0a5c53dfda9d40482d16a249e16a991cb9046',
     '6a6bd4e1703429fcf181c8159340c446ff7d2266e4d953ef18354d6c3592273c', 4546),
    ('q297-q336-production-physical-r1', '0560fb3b-bea5-4629-9c7e-bdd32508cdcc',
     'e1c84553a4f489d29d5d6ca46dcd1120e87cfe214c9445b563a5b7f31cfceda9',
     'e66b9500d93b4115daebffd97835222b327ab82f502266af58c7b3ed903b9376',
     'e80aad2b147c09ef63fd1a9e1ec0a0667a7e32582e52988e14b9f5798549a00d', 7200),
)


def _pinned(path, pin, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    return raw


def _process_record(run_root, spec):
    name, run_id, result_sha, request_sha, stderr_sha, deadline = spec
    root = run_root / name
    json.loads(_pinned(root/'result.json', result_sha, 1 << 20))
    json.loads(_pinned(root/'request.json', request_sha, 1 << 20))
    error = _pinned(root/'process'/'stderr.log', stderr_sha, 1 << 20)
    _guard(error.splitlines(), deadline)


def _guard(lines, deadline):
    guards = [json.loads(line[len(b'heat_h3_guard: '):]) for line in lines
              if line.startswith(b'heat_h3_guard: ')]
    g = guards[0]
    mask = g.get('affinity_mask')
    if (g.get('outcome') != 'succeeded' or g.get('launched') is not True or
            g.get('released') is not True or g.get('limits_verified') is not True or
            g.get('exit_code') != 0 or g.get('child_exit_code') != 0 or
            g.get('tree_final') is not True or g.get('active_members') != 0 or
            g.get('memory_limit_bytes') != 3 << 30 or g.get('wall_limit_seconds') != deadline or
            type(mask) is not int or mask <= 0 or mask & (mask - 1)):
        raise ValueError('q297 source guard did not satisfy its admitted limits')


def make_factory(*, run_root, grid_path, selected_observer=None):
    """Bind selected manifest-loaded modules and exact qualification evidence."""
    run_root = Path(run_root)
    grid_path = Path(grid_path)
    for spec in RUNS:
        _process_record(run_root, spec)
    proof_root=run_root/'landing-gp-correspondence-r1'
    json.loads(_pinned(proof_root/'command.json',
        'c730441f6ada091cf67aa3888cd4298da85ff7e4ba5cf132f382bec976e0074c',1 << 20))
    entry=run_root.parent/'iv1-diagnostic-prep/landing-gp-r1/gp_end_proof_r1.py'
    _pinned(entry,'283aefd417a349c5b4b30c99330bb7ba2dc6e4372f6423d65f9e263a063177a0',2 << 20)
    output=_pinned(proof_root/'queue.out',
        'aa4636fa63f46df74ad5ae591ab42e31ffc8c4de380a7db4db41512fd1be6566',4096).splitlines()
    _guard(output, 7200)
    modules = {key: importlib.import_module(name) for key, name in MODULES.items()}
    provider = modules['provider']
    if provider.GRID_SHA != GRID_SHA:
        raise ValueError('q297 factory and provider grid identities differ')
    used = False
    def factory(*, interval, partition, funding, bounds, closed_graph, budget, ale_parallel=None):
        nonlocal used
        with _LOCK:
            used = True
        from atlas_tectonics.integration.geometry import differential_geometry as D, differential_mesh as H
        from atlas_tectonics.integration.geometry import wall_measures as W, volume as V
        from atlas_tectonics.integration.geometry import volume_bounds as B
        from atlas_tectonics.integration.coupling import exterior_mesh as E
        from atlas_tectonics.integration.coupling.spatial_transport import _workspace
        dependencies = MappingProxyType({key: modules[key] for key in
            ('pieces', 'piece_builder', 'rays', 'family', 'start', 'checkpoint')})
        # Grid bytes are read only when the shared budget exists; the provider
        # takes a separate reservation before decoding and retaining the grid.
        with _workspace(budget, 8 << 20, 'q297-provider-grid-read'):
            limit = 4 << 20
            with grid_path.open('rb') as stream:
                grid = stream.read(limit + 1)
            if len(grid) > limit:
                raise ValueError('q297 successor grid exceeds its size limit')
            result = provider.EndGeometryProvider(interval=interval, partition=partition,
                funding=funding, bounds=bounds, closed_graph=closed_graph, budget=budget,
                grid_bytes=grid, D=D, H=H, W=W, V=V, B=B, E=E, dependencies=dependencies,
                sweep_output=run_root/RUNS[0][0]/'process'/'stdout.log',
                physical_output=run_root/RUNS[1][0]/'process'/'stdout.log', ale_parallel=ale_parallel)
            del grid
        with _LOCK:
            _REGISTRY[result] = {'type': type(result), 'core': dict(vars(result)),
                                 'prepare': type(result).prepare, 'support': type(result).support_cells,
                                 'state': 'NEW', 'active': None}
        try:
            if selected_observer is not None:
                selected_observer(dict(graph_id=closed_graph.geometry_id, grid_sha256=GRID_SHA,
                    sweep_payload_sha256='290d83c1afc94a0917078b01175d0f5aa3ee18edb8561d373a9d311de054accc',
                    carry_proof_sha256='cae83be7428db8c3a7a9a48bfcb0ab9e1c870c9949dbaf585c911c3ded70fc93',
                    inherited_witness_refinements=1, qualification_grid_split='-33/8'))
        except BaseException:
            release(result)
            raise
        return result
    return factory


# Only providers issued by the exact source-bound factory are accepted. The
# weak registry is not an authority to forge issued spatial objects; it binds
# the factory's private inputs and is removed at the end of the geometry phase.
_REGISTRY = weakref.WeakKeyDictionary()
_LOCK = threading.RLock()


def _entry(provider):
    try:
        row = _REGISTRY.get(provider)
    except TypeError as error:
        raise ValueError('foreign q297 provider refused') from error
    return cast(dict, row)


def _core(provider, row, *, allow_active=False):
    expected = set(row['core'])
    if allow_active or row['state'] == 'ACTIVE':
        expected.update(('_arena', '_measures', '_booked', '_shared', '_totals', '_contexts', '_rays'))


def _release_registered(provider, row):
    _REGISTRY.pop(provider, None)
    finalizer = row['core']['_finalizer']
    vars(provider).clear()
    provider._state = 'CLOSED'
    finalizer()

def claim(provider, *, funding, bounds, supports, closed_graph, budget, endpoint):
    with _LOCK:
        row = _entry(provider)
        try:
            _core(provider, row)
            row['state'] = provider._state = 'CLAIMED'
        except BaseException:
            _release_registered(provider, row)
            raise


def require_claim(provider, *, funding, bounds, supports, closed_graph, budget, endpoint):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row)


def activate(provider):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row, allow_active=True)
        row['active'] = {name: vars(provider)[name] for name in
                         ('_arena', '_measures', '_booked', '_shared', '_totals', '_contexts', '_rays')}
        row['state'] = 'ACTIVE'


def validate_active(provider):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row)


def prepare(provider, **kwargs):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row)
        return row['prepare'](provider, **kwargs)


def support_cells(provider, support, **kwargs):
    with _LOCK:
        row = _entry(provider)
        return row['support'](provider, support, **kwargs)


def release(provider):
    # Called only after a successful claim or as an arena callback. The wrapper
    # may call it again after the arena already released the registered object.
    with _LOCK:
        try:
            row = _REGISTRY.get(provider)
        except TypeError as error:
            raise ValueError('foreign q297 provider refused') from error
        if row is None:
            if getattr(provider, '_state', None) == 'CLOSED':
                return
            raise ValueError('foreign or stale q297 provider refused')
        _release_registered(provider, row)
