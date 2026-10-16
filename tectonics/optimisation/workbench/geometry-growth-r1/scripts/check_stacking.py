"""Read-only: do the geometry-chat transforms anchor exactly once after the Step 8 partition transform?

Applies C/live_partition_patch.transform and .transform_lifetimes (each separately)
to the RC1 geometry source in memory, then this chat's transforms in the intended
order (growth -> WP20 -> items_off -> WP23 rotation -> complementary cut -> progress hooks) with allow_unreviewed_input,
and reports success or the first failing anchor. Also compiles each result.
Nothing is written.
"""
import importlib.util
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
GG = HERE.parent
R = GG.parent
C = R / 'compact-geometry-r1'
RC1 = R / 'composed-r1' / 'runtime-src' / 'atlas_tectonics' / 'integration_differential_geometry.py'
sys.path[:0] = [str(C), str(R / 'composed-r1' / 'helpers'), str(R / 'composed-r1' / 'runtime-src')]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem + '_chk', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source = RC1.read_bytes().decode('utf8')
mine = [load(GG / 'transforms' / name) for name in
        ('growth_successor.py', 'wp20_zero_certificate.py', 'items_11_15_off.py', 'wp23_rotation.py', 'complementary_cut.py', 'progress_hooks.py')]
live = load(C / 'live_partition_patch.py')
print('live_partition_patch sha256', sha256((C / 'live_partition_patch.py').read_bytes()).hexdigest()[:16])
for label, step8 in (('none', None), ('transform', live.transform), ('transform_lifetimes', live.transform_lifetimes)):
    text = source if step8 is None else step8(source)
    try:
        for module in mine:
            text = module.transform(text, allow_unreviewed_input=True)
        compile(text, 'integration_differential_geometry.py', 'exec')
        print('%-20s OK  output sha256 %s' % (label, sha256(text.encode()).hexdigest()[:16]))
    except Exception as error:
        print('%-20s FAIL in %s: %s' % (label, module.__name__, str(error)[:160]))
