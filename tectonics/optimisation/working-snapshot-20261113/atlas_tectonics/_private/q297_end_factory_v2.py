"""Uninstalled exact-source factory for the q297 END provider candidate.

This is preparation only. Its package modules must be included in the selected
native source manifest and imported through the selected source fence. The caller
supplies separately pinned evidence paths; nothing here authorises a run.
"""
import hashlib
import importlib
import json
import threading
import weakref
from types import MappingProxyType
from pathlib import Path

PINS = {
    'provider': ('q297_end_provider_v2.py', 'd6d04c42417f02bb73471003eb56c810a64ab0654c00205729d11fd1c4231800'),
    'pieces': ('q297_end_pieces_v2.py', '9542c8460d9a859868424f25837c5339846a69353abdd340b0cfc6a44d5e8fe8'),
    'piece_builder': ('interval_piece_candidate.py', 'ad034d0405e59850ec40133d3f7bae7e816381959777fb8542b974c63e8e299c'),
    'rays': ('interval_shared_ray_candidate.py', 'bd3608c72f8092791ffcb0c4c35b6df8e8d735193217d02d6abd9c4f4c1d7825'),
    'family': ('material_family_context_candidate.py', '6de91cedc3e1131ba51d49df0f7110d0767a3646f42026f24e2f8dda1a32730e'),
    'start': ('material_start_candidate.py', '03c0dba5331bc4702254a3dcffcc888ad7326dc70b4e2b692956a7e207e95acf'),
    'checkpoint': ('tile_checkpoint_candidate.py', '05aca97ba4b17357339895475a81b5cf67086f2563ee390671c6f461a5a0d135'),
}
GRID_SHA = '7365149f3f1b781e9abe5707ac44982d5595fbaee3eeeac8af22745b0cf94fe2'
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
    _guard(error.splitlines(), deadline)


def _guard(lines, deadline):
    guards = [json.loads(line[len(b'heat_h3_guard: '):]) for line in lines
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


def make_factory(*, run_root, grid_path, selected_observer=None):
    """Bind selected manifest-loaded modules and exact qualification evidence."""
    if selected_observer is not None and not callable(selected_observer):
        raise ValueError('provider selection observer must be callable or None')
    run_root = Path(run_root)
    grid_path = Path(grid_path)
    for spec in RUNS:
        _process_record(run_root, spec)
    proof_root=run_root/'landing-p2-correspondence-r1'
    command=json.loads(_pinned(proof_root/'command.json',
        'af57b16ed846cf70d919801d48958c80a785c048af640fd63fda0f4445d17993',1 << 20))
    entry=run_root.parent/'iv1-diagnostic-prep/landing-p2-r1/p2_end_proof_r1.py'
    _pinned(entry,'e08c661846cfd63b2652a242d74ff730e82dc973c470a8d08758238c9babce2e',2 << 20)
    if (command.get('ticket')!='q1073' or len(command['argv'])!=14 or
            Path(command['argv'][12]).resolve()!=entry.resolve() or
            Path(command['argv'][13]).resolve()!=(proof_root/'result-data.json').resolve()):
        raise ValueError('correspondence producer command differs')
    output=_pinned(proof_root/'queue.out',
        '1605e0c50a21dd9e8dbd508df865199a3cb65a00abeaac35c714db0bbee5a50b',4096).splitlines()
    if (sum(line[9:].startswith(b'q1073 started') for line in output)!=1 or
            sum(line[9:].startswith(b'q1073 exit 0,') for line in output)!=1):
        raise ValueError('correspondence producer ticket differs')
    _guard(output, 7200)
    records=[json.loads(line) for line in output if line.startswith(b'{')]
    if len(records)!=1 or records[0].get('sha256')!='05a44721c11cac5e0533bcccbe42072d4d1c742aecec258c139c1b5ca732facb':
        raise ValueError('correspondence producer output differs')
    _pinned(grid_path, GRID_SHA, 4 << 20)
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
        with _LOCK:
            if used:
                raise ValueError('q297 provider factory is single use')
            used = True
        from atlas_tectonics import integration_differential_geometry as D, integration_differential_mesh as H
        from atlas_tectonics import integration_wall_measures as W, integration_volume as V
        from atlas_tectonics import integration_volume_bounds as B, integration_exterior_mesh as E
        from atlas_tectonics.resources import WorkBudget
        if type(budget) is not WorkBudget:
            raise ValueError('issued shared WorkBudget required')
        dependencies = MappingProxyType({key: modules[key] for key in
            ('pieces', 'piece_builder', 'rays', 'family', 'start', 'checkpoint')})
        # Grid bytes are read only when the shared budget exists; the provider
        # takes a separate reservation before decoding and retaining the grid.
        with budget.reserve(8 << 20, category='q297-provider-grid-read'):
            grid = _pinned(grid_path, GRID_SHA, 4 << 20)
            result = modules['provider'].EndGeometryProvider(interval=interval, partition=partition,
                funding=funding, bounds=bounds, closed_graph=closed_graph, budget=budget,
                grid_bytes=grid, D=D, H=H, W=W, V=V, B=B, E=E, dependencies=dependencies,
                sweep_output=run_root/RUNS[0][0]/'process'/'stdout.log',
                physical_output=run_root/RUNS[1][0]/'process'/'stdout.log')
        with _LOCK:
            _REGISTRY[result] = {'type': type(result), 'core': dict(vars(result)),
                                 'prepare': type(result).prepare, 'support': type(result).support_cells,
                                 'state': 'NEW', 'active': None}
        try:
            if selected_observer is not None:
                selected_observer(dict(graph_id=closed_graph.geometry_id, grid_sha256=GRID_SHA,
                    sweep_payload_sha256='290d83c1afc94a0917078b01175d0f5aa3ee18edb8561d373a9d311de054accc',
                    carry_proof_sha256='05a44721c11cac5e0533bcccbe42072d4d1c742aecec258c139c1b5ca732facb',
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
    if row is None or type(provider) is not row['type']:
        raise ValueError('foreign or stale q297 provider refused')
    return row


def _core(provider, row, *, allow_active=False):
    expected = set(row['core'])
    if allow_active or row['state'] == 'ACTIVE':
        expected.update(('_arena', '_measures', '_booked', '_shared', '_totals', '_contexts', '_rays'))
    if set(vars(provider)) != expected:
        raise ValueError('q297 provider attributes changed')
    for key, value in row['core'].items():
        if key != '_state' and vars(provider).get(key) is not value:
            raise ValueError('q297 provider binding changed')


def _release_registered(provider, row):
    _REGISTRY.pop(provider, None)
    finalizer = row['core']['_finalizer']
    vars(provider).clear()
    provider._state = 'CLOSED'
    finalizer()

def claim(provider, *, funding, bounds, supports, closed_graph, budget, endpoint):
    with _LOCK:
        row = _entry(provider)
        if row['state'] != 'NEW':
            raise ValueError('q297 provider already claimed')
        try:
            _core(provider, row)
            if (provider._state != 'NEW' or endpoint != 'end' or
                    provider.funding is not funding or provider.bounds is not bounds or
                    provider.partition.supports is not supports or provider.closed_graph is not closed_graph or
                    provider.budget is not budget):
                raise ValueError('q297 provider issuer or lifetime binding differs')
            row['state'] = provider._state = 'CLAIMED'
        except BaseException:
            _release_registered(provider, row)
            raise


def require_claim(provider, *, funding, bounds, supports, closed_graph, budget, endpoint):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row)
        if (row['state'] != 'CLAIMED' or provider._state != 'CLAIMED' or endpoint != 'end' or
                provider.funding is not funding or provider.bounds is not bounds or
                provider.partition.supports is not supports or provider.closed_graph is not closed_graph or
                provider.budget is not budget):
            raise ValueError('q297 provider claim differs')


def activate(provider):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row, allow_active=True)
        if row['state'] != 'CLAIMED' or provider._state != 'ACTIVE':
            raise ValueError('q297 provider activation differs')
        row['active'] = {name: vars(provider)[name] for name in
                         ('_arena', '_measures', '_booked', '_shared', '_totals', '_contexts', '_rays')}
        row['state'] = 'ACTIVE'


def validate_active(provider):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row)
        if row['state'] != 'ACTIVE' or provider._state != 'ACTIVE' or any(
                vars(provider).get(key) is not value for key, value in row['active'].items()):
            raise ValueError('q297 provider active context differs')


def prepare(provider, **kwargs):
    with _LOCK:
        row = _entry(provider)
        _core(provider, row)
        if row['state'] != 'CLAIMED' or provider._state != 'CLAIMED':
            raise ValueError('q297 provider is not claimed')
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
