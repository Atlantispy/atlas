"""Uninstalled exact-source factory for the q297 END provider candidate.

This is preparation only. Its package modules must be included in the selected
native source manifest and imported through the selected source fence. The caller
supplies separately pinned evidence paths; nothing here authorises a run.
"""
import hashlib
import importlib
import json
from pathlib import Path

PINS = {
    'provider': ('q297_end_provider_integration_candidate.py', 'b7b6579b1a24537ee40a4ada7f977ccf9d2229f98098cd4c3a4ba081a73a2996'),
    'pieces': ('q297_end_pieces_candidate.py', '819aee896ab58d335488351db410c0791bb25c61288ce8f74837a1964a9b91ae'),
    'piece_builder': ('interval_piece_candidate.py', '9d59425bc25a312e5f5c2455f070068a298906c3a9604a008cf84d0cf4f0531e'),
    'rays': ('interval_shared_ray_candidate.py', 'bd3608c72f8092791ffcb0c4c35b6df8e8d735193217d02d6abd9c4f4c1d7825'),
    'family': ('material_family_context_candidate.py', '6de91cedc3e1131ba51d49df0f7110d0767a3646f42026f24e2f8dda1a32730e'),
    'start': ('material_start_candidate.py', '03c0dba5331bc4702254a3dcffcc888ad7326dc70b4e2b692956a7e207e95acf'),
    'checkpoint': ('tile_checkpoint_candidate.py', '05aca97ba4b17357339895475a81b5cf67086f2563ee390671c6f461a5a0d135'),
}
GRID_SHA = '1ccb672f21b51502edc06663eda7b079628d256cef3e0064f9f8fd677db68bac'
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
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('q297 factory source or evidence identity differs: ' + path.name)
    return raw


def _process_record(run_root, spec):
    name, run_id, result_sha, request_sha, stderr_sha, deadline = spec
    root = run_root / name
    result = json.loads(_pinned(root/'result.json', result_sha, 1 << 20))
    request = json.loads(_pinned(root/'request.json', request_sha, 1 << 20))
    error = _pinned(root/'process'/'stderr.log', stderr_sha, 1 << 20)
    process = result.get('process', {})
    if (result.get('run_id') != run_id or request.get('run_id') != run_id or
            process.get('outcome') != 'succeeded' or process.get('exit_code') != 0 or
            process.get('tree_final') is not True or process.get('active_members') != 0):
        raise ValueError('q297 source process was not cleanly completed')
    guards = [json.loads(line[len(b'heat_h3_guard: '):]) for line in error.splitlines()
              if line.startswith(b'heat_h3_guard: ')]
    if len(guards) != 1:
        raise ValueError('q297 guard receipt missing or ambiguous')
    g = guards[0]
    mask = g.get('affinity_mask')
    if (g.get('outcome') != 'succeeded' or g.get('launched') is not True or
            g.get('released') is not True or g.get('limits_verified') is not True or
            g.get('exit_code') != 0 or g.get('child_exit_code') != 0 or
            g.get('tree_final') is not True or g.get('active_members') != 0 or
            g.get('memory_limit_bytes') != 3 << 30 or g.get('wall_limit_seconds') != deadline or
            type(mask) is not int or mask <= 0 or mask & (mask - 1)):
        raise ValueError('q297 source guard did not satisfy its admitted limits')


def make_factory(*, run_root, grid_path):
    """Bind selected manifest-loaded modules and exact qualification evidence."""
    run_root = Path(run_root)
    grid_path = Path(grid_path)
    for spec in RUNS:
        _process_record(run_root, spec)
    grid = _pinned(grid_path, GRID_SHA, 4 << 20)
    modules = {}
    for key, (filename, digest) in PINS.items():
        name = 'atlas_tectonics._private.' + Path(filename).stem
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        if path.name != filename:
            raise ValueError('q297 candidate module identity differs')
        _pinned(path, digest, 2 << 20)
        modules[key] = module
    used = False
    def factory(*, interval, partition, funding, bounds, closed_graph, budget):
        nonlocal used
        if used:
            raise ValueError('q297 provider factory is single use')
        from atlas_tectonics import integration_differential_geometry as D, integration_differential_mesh as H
        from atlas_tectonics import integration_wall_measures as W, integration_volume as V
        from atlas_tectonics import integration_volume_bounds as B, integration_exterior_mesh as E
        dependencies = {key: modules[key] for key in ('pieces', 'piece_builder', 'rays', 'family', 'start', 'checkpoint')}
        result = modules['provider'].EndGeometryProvider(interval=interval, partition=partition,
            funding=funding, bounds=bounds, closed_graph=closed_graph, budget=budget,
            grid_bytes=grid, D=D, H=H, W=W, V=V, B=B, E=E, dependencies=dependencies,
            sweep_output=run_root/RUNS[0][0]/'process'/'stdout.log',
            physical_output=run_root/RUNS[1][0]/'process'/'stdout.log')
        used = True
        return result
    return factory
