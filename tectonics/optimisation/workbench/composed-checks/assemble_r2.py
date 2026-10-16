"""Step 10 (WP9) reviewed composition r2: RC1 base + the agreed per-file chains. Authenticated.

Usage:
  python -B assemble_r2.py --pin REVIEWED_INPUTS_JSON DRY_COMPOSITION_JSON TARGET
      Record the reviewed inputs, including TARGET's absolute path as the composition's
      permanent root (heat result IDs bind absolute helper paths; coordinator 16 Oct): sha256 of every input file (RC1 runtime-src, the I file
      re-pinned through mimetic_patch, the endpoint companion, every transform module, every
      module the transforms import from the live trees, every helper) and the expected
      output digest of every stage (from the reviewed dry run's TEST_COMPOSITION.json).
      Refuses if REVIEWED_INPUTS_JSON exists.
  python -B assemble_r2.py --compose REVIEWED_INPUTS_JSON TARGET
      Re-verify every pinned input BEFORE use, compose, assert every stage's input and output
      digest equals the record, audit sys.modules (every module loaded from the live trees or
      the geometry folder during composition must be pinned, with the pinned bytes), and
      write TARGET once (it must not exist). Writes TARGET/composition.json.

Base: composed-r1/runtime-src (RC1, the reviewed composition r1; coordinator decision 16 Oct
11:00). Chains (wp9-inventory-notes.md):
  workflow   RC1 -> transform_v2 -> transform_v3 -> spatial records -> spatial validation ->
             compact_restart_patch -> R2 rev4 -> R3 rev2 -> publish_mesh_patch
  spatial_owner  RC1 -> exchange_record_patch.holder_source -> spatial_validation_patch.owner_source
  mimetic_heat   I -> current mimetic_patch.mimetic_source (re-pin of RC1's)
  endpoint_checkpoints  the current companion file
  differential_mesh  differential_mesh_patch.transform
  the 11 live_memory_composition STAGES (apply_native)
  differential_geometry  the geometry six, order A (allow_unreviewed_input; parity on this output)
  parallel_results / q2_directed / moving_face_moments / reuse.py: the four pinned geometry transforms
Nothing here reads a store, launches science or grants admission. Text in, text out.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys

T = Path(r'C:\Users\LOCAL_USER\Documents\Codex\2026-09-02\the-diadem-local-tasks-10')
R = T / 'fidelity-integration-20261005' / 'continuation-repair-20261013' / 'optimisation-20261014' / 'resumability-r1'
C = R / 'compact-geometry-r1'
G = R / 'geometry-growth-r1'
RC1 = R / 'composed-r1'
S1 = R / 's1'
I_RUNTIME = R.parent / 'runtime-integration-r1' / 'runtime-src'
PKG = 'atlas_tectonics'
SCHEMA = 'atlas.private.resumable-reviewed-inputs.r2'
GEOMETRY_SIX = ('growth_successor', 'wp20_zero_certificate', 'items_11_15_off', 'wp23_rotation',
                'complementary_cut', 'progress_hooks')
GEOMETRY_PINNED = (('integration_parallel_results.py', 'complementary_cut_adopt'),
                   ('integration_q2_directed.py', 'q2_zero_test'),
                   ('integration_moving_face_moments.py', 'jets_convolution'),
                   ('reuse.py', 'source_handles'))
EXTRA_HELPERS = ('private_heat_original_joined_r8.py', 'original_joined_r8_transform.py',
                 'publish_mesh_patch.py', 'heat_token_transform.py', 'publication_token_transform.py')
LIVE_TREES = (C, R, G)
H_ROOT = T / 'fidelity-integration-20261005' / 'heat-repair-20261007'
# The compact heat successor (coordinator + Steps 8-9, 16 Oct ~11:20): production heat route,
# live_memory=True. Its emitted helpers must equal the g13 live-memory-on layout (g13l1), the
# reviewed same-call re-proof composition; checked here by 8-hex prefix. The r13 issuer value is
# g13l1's composed_r13_sha256_before_reference_insert (the layout's file 549dbc86 carries the
# control-only r12 reference functions, which production does not).
EXPECTED_HEAT = {'private_heat_native_issuer_r13.py': 'dbaeecae', 'private_heat_checkpoint_consumer_r10.py': 'aa4a3f8e',
                 'private_heat_restored_binding_r10.py': '53bd2c58', 'private_heat_snapshot_store_r4.py': '8d206973',
                 'private_heat_joined_consumer_r6.py': '86c30c5c', 'private_heat_functionals_parallel_r1.py': 'c2325429'}
EXPECTED_COLD = '6dad6f06'
# Coordinator, 16 Oct (from the Steps 8-9 finding): heat result IDs and metadata bind the ABSOLUTE
# paths of the helper sources, so a composition is used only from the root recorded here.
ROOT_RULE = ('permanent root: heat result IDs bind absolute helper source paths; never move or copy this '
             'composition for use; launchers refuse to run from any other root')


class Refused(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Refused(message)


def file_sha(path):
    return sha256(path.read_bytes()).hexdigest()


def text_sha(text):
    return sha256(text.encode('utf8')).hexdigest()


def rel(path):
    return path.resolve().relative_to(T).as_posix()


def lf(path):
    return path.read_bytes().decode('utf8').replace('\r\n', '\n')


def helper_sources():
    """(name -> source path): every top-level *.py of the s1 import roots, flattened in their
    order with the first match winning (Steps 8-9 rule, 16 Oct 11:12): R, C, composed-r1/helpers,
    composed-r1/ram. The live R/C copy wins for every name that also exists in RC1's folders,
    and the route (1) runner family (launch/run/reopen/driver/width gate/ledger/worker
    selection) and every FRESH_MODULE are included, so the frozen helpers are self-contained."""
    chosen = {}
    for root in (R, C, RC1 / 'helpers', RC1 / 'ram'):
        for path in sorted(root.glob('*.py')):
            chosen.setdefault(path.name, path)
    missing = [name for name in EXTRA_HELPERS if name not in chosen]
    require(not missing, 'required helpers missing from the roots: ' + ', '.join(missing))
    return chosen


def compose(pins=None):
    """Compose in memory. With pins, assert each stage's input/output against them.
    Returns (sources, stages, loaded modules, emitted heat helpers name -> bytes)."""
    sys.path[:0] = [str(C), str(I_RUNTIME), str(R), str(R / 'endpoint-checkpoints')]
    sys.dont_write_bytecode = True
    before_modules = set(sys.modules)
    import compact_restart_patch as P
    import differential_mesh_patch as DP
    import exchange_record_patch as E
    import heat_token_transform as H
    import live_memory_composition as LMC
    import mimetic_patch as MP
    import partition_workflow_transform as PWT
    import publication_token_transform as TT
    import publish_mesh_patch as PM
    import spatial_records_patch as SR
    import spatial_validation_patch as V
    import spatial_workflow_patch as Y
    base = RC1 / 'runtime-src'
    sources = {}
    for path in sorted(base.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            key = path.relative_to(base).as_posix()
            sources[key] = lf(path) if path.suffix == '.py' else path.read_bytes()
    stages = []
    expected = None if pins is None else iter(pins['stages'])

    def record(name, label, before, after, note=None):
        row = dict(module=name, stage=label, input_sha256=None if before is None else text_sha(before),
                   output_sha256=text_sha(after))
        if note:
            row['note'] = note
        if expected is not None:
            want = next(expected, None)
            require(want is not None and {k: want.get(k) for k in row} == row,
                    f'stage differs from the reviewed record: {name} {label}')
        stages.append(row)

    def stage(name, label, fn):
        key = f'{PKG}/{name}'
        before = sources[key]
        after = fn(before)
        compile(after, name, 'exec')
        sources[key] = after
        record(name, label, before, after)

    def replace(name, label, text):
        key = f'{PKG}/{name}'
        compile(text, name, 'exec')
        before = sources.get(key)
        sources[key] = text
        record(name, label, before, text, 'file replaced, not transformed')

    def load(module):
        path = G / 'transforms' / f'{module}.py'
        spec = importlib.util.spec_from_file_location(f'_g_{module}', path)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        sys.modules[f'_g_{module}'] = loaded
        return loaded.transform

    for label, fn in (('partition_workflow_transform.transform_v2', PWT.transform_v2),
                      ('spatial_workflow_patch.transform_v3', Y.transform_v3),
                      ('spatial_records_patch.transform', SR.transform),
                      ('spatial_validation_patch.workflow_source', V.workflow_source),
                      ('compact_restart_patch.workflow_source', P.workflow_source),
                      ('publication_token_transform.transform (R2 rev4)', TT.transform),
                      ('heat_token_transform.transform (R3 rev2)', H.transform),
                      ('publish_mesh_patch.transform', PM.transform)):
        stage('integration_regional_workflow.py', label, fn)
    stage('integration_spatial_owner.py', 'exchange_record_patch.holder_source', E.holder_source)
    stage('integration_spatial_owner.py', 'spatial_validation_patch.owner_source', V.owner_source)
    replace('integration_mimetic_heat.py', 'mimetic_patch.mimetic_source on I (re-pin)',
            MP.mimetic_source(lf(I_RUNTIME / PKG / 'integration_mimetic_heat.py')))
    replace('integration_endpoint_checkpoints.py', 'current endpoint companion',
            lf(R / 'endpoint-checkpoints' / 'integration_endpoint_checkpoints.py'))
    stage('integration_differential_mesh.py', 'differential_mesh_patch.transform', DP.transform)
    names = sorted({name for name, _, _ in LMC.STAGES})
    inputs = {name: sources[f'{PKG}/{name}'] for name in names}
    native, _applied = LMC.apply_native(inputs)
    # Re-derive each STAGES step's input/output text in order so the record carries both
    # digests, then require the replay to equal apply_native's own result.
    current = dict(inputs)
    for name, label, transform in LMC.STAGES:
        before = current[name]
        after = transform(before)
        compile(after, name, 'exec')
        current[name] = after
        record(name, 'live_memory_composition:' + label, before, after)
    require(all(current[name] == native[name] for name in names), 'apply_native differs from its STAGES replay')
    for name in names:
        sources[f'{PKG}/{name}'] = current[name]
    for module in GEOMETRY_SIX:
        transform = load(module)
        stage('integration_differential_geometry.py', f'geometry:{module} (allow_unreviewed_input)',
              lambda text, transform=transform: transform(text, allow_unreviewed_input=True))
    for name, module in GEOMETRY_PINNED:
        stage(name, f'geometry:{module}', load(module))
    # The compact heat successor (step7_same_call_heat_control.prepare's reviewed recipe, without
    # the control-only r12 reference insert), live_memory=True; no inventory additions allowed.
    import heat_cold_patch as COLD
    import private_heat_bundle as B
    import test_step7_bundle as SB
    import workflow_transfer as WT
    _, inputs, external, ram, helpers_in, compact = SB.compact_inputs()
    helper_out, ram_out, report = B.construct_compact_successor(
        inputs, reference_root=H_ROOT, reference_pins=B.REFERENCE_PINS, external=external, ram=ram,
        helpers=helpers_in, compact_helpers=compact, live_memory=True)
    emitted = dict(helper_out)
    for name, raw in ram_out.items():
        require(name not in emitted, 'compact successor helper/ram name clash: ' + name)
        emitted[name] = raw
    for name, prefix in EXPECTED_HEAT.items():
        require(name in emitted and sha256(emitted[name]).hexdigest().startswith(prefix),
                f'compact heat helper differs from the g13 live-memory layout: {name}')
    replace('integration_private_heat_cold.py', 'I text (RC1 chain replaced by the compact heat route)',
            lf(I_RUNTIME / PKG / 'integration_private_heat_cold.py'))
    stage('integration_private_heat_cold.py', 'workflow_transfer.private_heat_cold_source', WT.private_heat_cold_source)
    stage('integration_private_heat_cold.py', 'partition_workflow_transform.cold_source', PWT.cold_source)
    stage('integration_private_heat_cold.py', 'heat_cold_patch.transform', COLD.transform)
    stage('integration_private_heat_cold.py', 'private_heat_bundle.cold_binding_source (compact report)',
          lambda text: B.cold_binding_source(text, report))
    require(text_sha(sources[f'{PKG}/integration_private_heat_cold.py']).startswith(EXPECTED_COLD),
            'private_heat_cold differs from the g13 live-memory composition')
    loaded = {}
    for name in sorted(set(sys.modules) - before_modules):
        path = getattr(sys.modules[name], '__file__', None)
        if path and any(Path(path).resolve().is_relative_to(tree) for tree in LIVE_TREES):
            loaded[rel(Path(path))] = file_sha(Path(path))
    return sources, stages, loaded, emitted


def same_root(a, b):
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def pin(out, dry, target):
    require(not out.exists(), 'reviewed inputs already exist; a new revision needs a new file')
    require(not target.exists(), 'target exists; a composition is written once')
    sources, stages, loaded, emitted = compose()
    # Every composed source equals the reviewed dry run d2 (whose geometry parity is the
    # evidence), except private_heat_cold, which the compact heat route replaces.
    dry_files = json.loads(dry.read_text(encoding='utf8'))['src_files']
    cold = f'{PKG}/integration_private_heat_cold.py'
    for key, value in sources.items():
        digest = text_sha(value) if isinstance(value, str) else sha256(value).hexdigest()
        require(key == cold or dry_files.get(key) == digest, 'composition differs from the reviewed dry run: ' + key)
    require(set(dry_files) == set(sources), 'composition file set differs from the reviewed dry run')
    files = {rel(p): file_sha(p) for p in sorted((RC1 / 'runtime-src').rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts}
    for path in (I_RUNTIME / PKG / 'integration_mimetic_heat.py', I_RUNTIME / PKG / 'integration_private_heat_cold.py',
                 R / 'endpoint-checkpoints' / 'integration_endpoint_checkpoints.py'):
        files[rel(path)] = file_sha(path)
    files.update(loaded)
    helpers = {name: dict(path=None, source='compact-successor', sha256=sha256(raw).hexdigest())
               for name, raw in sorted(emitted.items())}
    conflicts = []
    for name, path in helper_sources().items():
        if name in helpers:
            if helpers[name]['sha256'] != file_sha(path):
                conflicts.append(dict(name=name, emitted=helpers[name]['sha256'][:8], root_copy=rel(path)))
            continue
        helpers[name] = dict(path=rel(path), sha256=file_sha(path))
    document = dict(schema=SCHEMA, base='composed-r1/runtime-src (RC1)', target='composed-r2',
                    target_root=str(target), root_rule=ROOT_RULE,
                    files=files, helpers=helpers, stages=stages, emitted_overrides_root_copies=conflicts,
                    heat_route='private_heat_bundle.construct_compact_successor, live_memory=True',
                    outputs={k: text_sha(v) if isinstance(v, str) else sha256(v).hexdigest()
                             for k, v in sorted(sources.items())},
                    completed_query_store='files', codec_policy=None,
                    decisions='coordinator 16 Oct: RC1 base (11:00), chain (09:00), (b\') (07:52), '
                              'R2/R3 re-pin, geometry order A (10:28), WP17 files (10:08), no codec policy')
    out.write_text(json.dumps(document, indent=1, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps(dict(files=len(files), helpers=len(helpers), emitted=len(emitted), stages=len(stages),
                          outputs=len(sources), emitted_overrides_root_copies=conflicts), indent=1))


def compose_target(reviewed, target):
    require(not target.exists(), 'target exists; a composition is written once')
    pins = json.loads(reviewed.read_text(encoding='utf8'))
    require(pins.get('schema') == SCHEMA, 'reviewed inputs schema differs')
    require(same_root(target, pins['target_root']), 'target is not the reviewed permanent root: ' + pins['target_root'])
    for path, want in pins['files'].items():
        require(file_sha(T / path) == want, 'reviewed input changed: ' + path)
    for name, row in pins['helpers'].items():
        if row['path'] is not None:
            require(file_sha(T / row['path']) == row['sha256'], 'reviewed helper changed: ' + name)
    sources, stages, loaded, emitted = compose(pins)
    for name, row in pins['helpers'].items():
        if row['path'] is None:
            require(name in emitted and sha256(emitted[name]).hexdigest() == row['sha256'],
                    'compact heat successor emitted different bytes: ' + name)
    require({n for n, r in pins['helpers'].items() if r['path'] is None} == set(emitted),
            'compact heat successor emitted a different helper set')
    for path, sha in loaded.items():
        require(pins['files'].get(path) == sha, 'unpinned or changed module took part: ' + path)
    outputs = {k: text_sha(v) if isinstance(v, str) else sha256(v).hexdigest() for k, v in sorted(sources.items())}
    require(outputs == pins['outputs'], 'composed outputs differ from the reviewed record')
    src, helpers = target / 'src', target / 'helpers'
    for key, value in sources.items():
        path = src / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode('utf8') if isinstance(value, str) else value)
    helpers.mkdir(parents=True)
    for name, row in sorted(pins['helpers'].items()):
        data = emitted[name] if row['path'] is None else (T / row['path']).read_bytes()
        require(sha256(data).hexdigest() == row['sha256'], 'helper changed during composition: ' + name)
        (helpers / name).write_bytes(data)
    record = dict(schema='atlas.private.resumable-composition.r2', reviewed_inputs=rel(reviewed),
                  reviewed_inputs_sha256=file_sha(reviewed), stages=stages, outputs=outputs,
                  helpers={k: v['sha256'] for k, v in pins['helpers'].items()},
                  root=str(target), root_rule=ROOT_RULE,
                  completed_query_store='files', codec_policy=None, frozen=False)
    (target / 'composition.json').write_text(json.dumps(record, indent=1, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps(dict(stages=len(stages), outputs=len(outputs), helpers=len(pins['helpers'])), indent=1))
    print('composition-r2-written')


def main():
    if sys.argv[1] == '--pin':
        pin(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve())
    elif sys.argv[1] == '--compose':
        compose_target(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
