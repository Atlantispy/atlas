"""Read-only: where SPATIAL.differential_source can sit against the geometry chat's transforms.

Applies to RC1's integration_differential_geometry.py in memory, for each Step 8 partition
stage (live_partition_patch.transform, the composition's choice; transform_lifetimes for
comparison):
  order A: RC1 -> partition stage -> SPATIAL.differential_source -> geometry six
  order B: RC1 -> partition stage -> geometry six -> SPATIAL.differential_source
The geometry six are the geometry chat's own list and order (its scripts/check_stacking.py),
applied with allow_unreviewed_input=True exactly as that check does. Prints each stage's
input/output SHA-256 (16 hex), the first failure, and whether A and B end in the same text.
Nothing is written.
"""
import importlib.util
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
GG = R/'geometry-growth-r1'
RC1 = R/'composed-r1'/'runtime-src'/'atlas_tectonics'/'integration_differential_geometry.py'
GEOMETRY = ('growth_successor.py', 'wp20_zero_certificate.py', 'items_11_15_off.py', 'wp23_rotation.py',
            'complementary_cut.py', 'progress_hooks.py')
sys.path[:0] = [str(C), str(R/'composed-r1'/'helpers'), str(R/'composed-r1'/'runtime-src')]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem+'_order_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def short(text):
    # --full prints whole digests (for pins); the default prints 16 hex.
    return sha256(text.encode()).hexdigest()[:64 if '--full' in sys.argv else 16]


def run(label, text, stages):
    for name, stage in stages:
        before = text
        try:
            text = stage(text)
        except Exception as error:  # noqa: BLE001 - the first failing stage is the finding
            print(f'  {label}: FAIL at {name}: {type(error).__name__}: {str(error)[:160]}')
            return None
        print(f'  {label}: {name:28s} {short(before)} -> {short(text)}')
    compile(text, 'integration_differential_geometry.py', 'exec')
    return text


def main():
    import live_partition_patch as LP
    import live_spatial_patch as SPATIAL
    geometry = [(name[:-3], (lambda module: lambda text: module.transform(text, allow_unreviewed_input=True))(
        load(GG/'transforms'/name))) for name in GEOMETRY]
    source = RC1.read_bytes().decode('utf8')
    print('RC1', short(source), '| live_partition_patch', short((C/'live_partition_patch.py').read_text(encoding='utf8')),
          '| live_spatial_patch', short((C/'live_spatial_patch.py').read_text(encoding='utf8')))
    spatial = ('SPATIAL.differential_source', SPATIAL.differential_source)
    for partition_name, partition in (('LP.transform', LP.transform), ('LP.transform_lifetimes', LP.transform_lifetimes)):
        print(partition_name)
        first = [(partition_name, partition)]
        a = run('A', source, first+[spatial]+geometry)
        b = run('B', source, first+geometry+[spatial])
        if a is not None and b is not None:
            print(f'  A and B final texts {"IDENTICAL" if a == b else "DIFFER"}: {short(a)} / {short(b)}')


if __name__ == '__main__':
    main()
