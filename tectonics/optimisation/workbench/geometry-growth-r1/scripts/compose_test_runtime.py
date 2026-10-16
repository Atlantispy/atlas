"""Test-only composition: copy RC1 runtime-src to a new folder and apply named transforms.

RC1 itself is never written. The new folder gets a manifest with every file's
sha256, the input and output hash of each transformed file, and the transform
module hashes. Usage: compose_test_runtime.py <new-folder> <transform-name>...
"""
import importlib.util
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
GG = HERE.parent
RC1 = GG.parent / 'composed-r1' / 'runtime-src'
TRANSFORMS = {
    'wp20': ('transforms/wp20_zero_certificate.py', 'atlas_tectonics/integration_differential_geometry.py'),
    'growth': ('transforms/growth_successor.py', 'atlas_tectonics/integration_differential_geometry.py'),
    'nocube': ('transforms/test_nocube.py', 'atlas_tectonics/integration_differential_geometry.py'),
    'items_off': ('transforms/items_11_15_off.py', 'atlas_tectonics/integration_differential_geometry.py'),
    'wp23rot': ('transforms/wp23_rotation.py', 'atlas_tectonics/integration_differential_geometry.py'),
    'progress': ('transforms/progress_hooks.py', 'atlas_tectonics/integration_differential_geometry.py'),
    'cpcut': ('transforms/complementary_cut.py', 'atlas_tectonics/integration_differential_geometry.py'),
    'cpadopt': ('transforms/complementary_cut_adopt.py', 'atlas_tectonics/integration_parallel_results.py'),
    'q2fast': ('transforms/q2_zero_test.py', 'atlas_tectonics/integration_q2_directed.py'),
    'jetsfast': ('transforms/jets_convolution.py', 'atlas_tectonics/integration_moving_face_moments.py'),
    'workers6': ('transforms/workers_six.py', 'atlas_tectonics/integration_parallel_selection.py'),
    # Superseded by workers6clamp (16 Oct refuter); kept only to reproduce workers6-r1.
    'workers6ep': ('transforms/workers_six_endpoints.py', 'atlas_tectonics/integration_component_volume_parallel.py'),
    'workers6clamp': ('transforms/workers_six_endpoint_clamp.py', 'atlas_tectonics/integration_component_volume_auto.py'),
    'workers6rolling': ('transforms/workers_six_rolling_interfaces.py', 'atlas_tectonics/integration_parallel_selection.py'),
    'srchandles': ('transforms/source_handles.py', 'atlas_tectonics/reuse.py'),
    # WP18 part 1 (a)+(b): endpoint policy bounds and cross-support lookahead; after workers6clamp.
    'wp18': ('transforms/wp18_endpoint_lookahead.py', 'atlas_tectonics/integration_component_volume_auto.py'),
    # S4 (Small optimisations, backlog 20): a machine-gate-refused first open is retried later.
    # s4sel after workers6rolling; s4auto after workers6clamp (and after wp18 when both are used).
    's4roll': ('transforms/s4_retry_rolling.py', 'atlas_tectonics/integration_parallel_rolling.py'),
    's4sel': ('transforms/s4_retry_selection.py', 'atlas_tectonics/integration_parallel_selection.py'),
    's4auto': ('transforms/s4_retry_endpoints.py', 'atlas_tectonics/integration_component_volume_auto.py'),
    # q14 D1/D2 (coordinator 16 Oct): exact, digest-only. d2rot after jetsfast; G-PY after d2rot.
    'd1det': ('transforms/incidence_constant.py', 'atlas_tectonics/integration_moving_interface_moments.py'),
    'd2rot': ('transforms/rotated_hoist.py', 'atlas_tectonics/integration_moving_face_moments.py'),
    # Kernel twin G-PY r4: a byte copy of its owner's transform (sha 701456a0...), which reviews d2rot's
    # output f9f00364 as an input; stacked parity jetsfast -> d1det -> d2rot -> gpy4.
    'gpy4': ('transforms/gpy_q2_jets_r4.py', 'atlas_tectonics/integration_moving_face_moments.py'),
}


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    target = Path(sys.argv[1]).resolve()
    names = sys.argv[2:]
    if target.exists():
        raise SystemExit('target exists')
    unknown = [name for name in names if name not in TRANSFORMS]
    if unknown:
        raise SystemExit('unknown transforms (nothing copied): %s' % unknown)
    shutil.copytree(RC1, target, ignore=shutil.ignore_patterns('__pycache__'))
    applied = []
    for name in names:
        module_path, relative = TRANSFORMS[name]
        module = load(GG / module_path)
        file = target / relative
        before = file.read_bytes().decode('utf8')   # exact bytes; no newline translation
        # A later transform sees an already-transformed file: allowed in TEST
        # compositions only, whose outputs are then parity-checked as a whole.
        stacked = any(a['file'] == relative for a in applied)
        after = module.transform(before, allow_unreviewed_input=True) if stacked else module.transform(before)
        file.write_bytes(after.encode('utf8'))
        applied.append(dict(transform=name, module=module_path,
                            module_sha256=sha256((GG / module_path).read_bytes()).hexdigest(),
                            file=relative, input_sha256=sha256(before.encode()).hexdigest(),
                            output_sha256=sha256(after.encode()).hexdigest()))
    files = {str(p.relative_to(target)).replace('\\', '/'): sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob('*.py'))}
    manifest = dict(schema='atlas.private.test-composition.r1', base='RC1 composed-r1/runtime-src',
                    transforms=applied, files=files, test_only=True)
    (target / 'TEST_COMPOSITION.json').write_text(json.dumps(manifest, indent=1), encoding='utf8')
    print(json.dumps(dict(target=str(target), transforms=applied), indent=1))


if __name__ == '__main__':
    main()
