"""Self-test of parity.py (FOLD.md §6, §10.4, §11): positive cases pass; mutants M1-M10 and the refuter's
regressions (R..) fail; N1-N4 pass.

  python -B selftest.py [HELPERS_DIR]

The synthetic record has the real shapes (path-keyed `sources` and `source_bindings`, an F5 re-pin, a nested
'sha256:'-prefixed pin, F6 bookings including one under a path key, an external `consumer` ID and nested self
`result_id`s). B is built by `fold_record`, written here independently of parity.map_paths, so the checker is not
tested against itself. Record mutants recompute B's own IDs after the edit, so a mutant is caught by the edit and
not by a stale ID (except M8, which forges an ID). With HELPERS_DIR, parity.stream_hash is cross-checked against
the real private_heat_issuer_resources_r1.stream_hash. Exit 0 only if every case behaves as listed.
"""
import contextlib
import copy
from hashlib import sha256
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parity as P  # noqa: E402

HELP = 'C:\\w\\composed-r2\\helpers\\'
HSRC = 'C:\\w\\heat-repair\\src\\atlas_tectonics\\'
PRIV = 'atlas_tectonics/_private/'
FINISH = 'private_heat_finish_kernel_r10.py'
TREE = 'private_heat_tree_r1.py'


def h(text):
    return sha256(text.encode()).hexdigest()


HELPER_NAMES = (FINISH, 'private_heat_closed_owned_r4.py', 'private_heat_low_solver_kernel_r5.py', TREE)
MODULE_STEMS = ('private_heat_issuer_resources_r1', 'private_heat_finish_arithmetic_r1')
OLD = {HELP + n: h('old ' + n) for n in HELPER_NAMES}
NEW = {PRIV + n: h('new ' + n) for n in HELPER_NAMES}
H_ST, S_ST = h('heat-repair spatial_transport'), h('composed spatial_transport')


def _self_ids(record):
    record['inner']['result_id'] = P.stream_hash({k: v for k, v in record['inner'].items() if k != 'result_id'})
    record['result_id'] = P.stream_hash({k: v for k, v in record.items() if k != 'result_id'})
    return record


def consumer_preimage(tree):
    return {'label': 'checkpoint-consumer', 'tree': tree}


def record_a() -> dict[str, Any]:
    a = dict(arrays={'temperature_k': [300.0, 301.5, 0.1 + 0.2]}, refusal=None, count=3, path_bytes=412, sep='/',
             bytes_by_file={HELP + FINISH: 100},
             sources={HELP + FINISH: OLD[HELP + FINISH],
                      HELP + 'private_heat_closed_owned_r4.py': OLD[HELP + 'private_heat_closed_owned_r4.py']},
             source_bindings={HELP + 'private_heat_low_solver_kernel_r5.py':
                              OLD[HELP + 'private_heat_low_solver_kernel_r5.py'],
                              HSRC + 'integration_spatial_transport.py': H_ST},
             consumer=P.stream_hash(consumer_preimage({HELP + TREE: OLD[HELP + TREE]})),
             inner=dict(payload={'module': HELP + TREE, 'cells': 236, 'pin': 'sha256:' + OLD[HELP + TREE]}))
    return _self_ids(a)


def fold_record(a):
    """What a correct fold must produce, written out by hand."""
    b = copy.deepcopy(a)
    b['sources'] = {PRIV + FINISH: NEW[PRIV + FINISH],
                    PRIV + 'private_heat_closed_owned_r4.py': NEW[PRIV + 'private_heat_closed_owned_r4.py']}
    b['source_bindings'] = {PRIV + 'private_heat_low_solver_kernel_r5.py':
                            NEW[PRIV + 'private_heat_low_solver_kernel_r5.py'],
                            'atlas_tectonics/integration_spatial_transport.py': S_ST}
    b['path_bytes'] = 371
    b['bytes_by_file'] = {PRIV + FINISH: 90}
    b['consumer'] = P.stream_hash(consumer_preimage({PRIV + TREE: NEW[PRIV + TREE]}))
    b['inner']['payload']['module'] = PRIV + TREE
    b['inner']['payload']['pin'] = 'sha256:' + NEW[PRIV + TREE]
    return _self_ids(b)


def manifest() -> dict[str, Any]:
    key_map = {HELP + n: PRIV + n for n in HELPER_NAMES}
    key_map[HSRC + 'integration_spatial_transport.py'] = 'atlas_tectonics/integration_spatial_transport.py'
    key_map[HSRC.rstrip('\\')] = 'atlas_tectonics'
    sha_map = {PRIV + n: [OLD[HELP + n], NEW[PRIV + n]] for n in HELPER_NAMES}
    sha_map['atlas_tectonics/integration_spatial_transport.py'] = [H_ST, S_ST]
    modules = {n: PRIV + n for n in HELPER_NAMES}
    modules.update({s + '.py': PRIV + s + '.py' for s in MODULE_STEMS})
    return dict(key_map=key_map, sha_map=sha_map, bookings=[['path_bytes'], ['bytes_by_file', PRIV + FINISH]],
                self_ids=[['inner', 'result_id'], ['result_id']],
                external=[dict(path=['consumer'], preimage_a=consumer_preimage({HELP + TREE: OLD[HELP + TREE]}))],
                modules=modules, identity_constants={'PACKAGE_DIR': 'atlas_tectonics',
                                                     'PRIVATE_DIR': 'atlas_tectonics/_private'})


def _with(**changes):
    return dict(manifest(), **changes)


def mutate(edit, reid=True):
    b = fold_record(record_a())
    edit(b)
    return _self_ids(b) if reid else b


def _set(b, key, value):
    b[key] = value


def _m1(b):
    b['arrays']['temperature_k'][1] = math.nextafter(301.5, math.inf)


def _m3(b):
    b['sources'][HELP + 'private_heat_closed_owned_r4.py'] = b['sources'].pop(PRIV + 'private_heat_closed_owned_r4.py')


def _n1(b):
    b['sources'] = dict(reversed(list(b['sources'].items())))


def _m6(b):
    b['sources'][PRIV + 'private_heat_ghost_r1.py'] = h('ghost')


def _r01b():
    """A already holds the new key; without a collision check the mapped value silently replaces it."""
    a = record_a()
    a['sources'] = dict([(PRIV + FINISH, 5)] + list(a['sources'].items()))
    return _self_ids(a), fold_record(record_a())


def _r04():
    a = record_a()
    pre = {'label': 'consumer', 'result': a['inner']['result_id']}
    a['consumer'] = P.stream_hash(pre)
    return _self_ids(a), fold_record(record_a()), _with(external=[dict(path=['consumer'], preimage_a=pre)])


def _leak(text):
    def build():
        a, b = record_a(), fold_record(record_a())
        a['inner']['payload']['note'] = b['inner']['payload']['note'] = text
        return _self_ids(a), _self_ids(b)
    return build


def _r06():
    sha_map = dict(manifest()['sha_map'], **{PRIV + 'copy_r1.py': [OLD[HELP + TREE], h('other')]})
    return record_a(), fold_record(record_a()), _with(sha_map=sha_map)


RECORD_CASES = [
    ('positive: correct fold', lambda: (record_a(), fold_record(record_a())), True),
    ('M1 one array value +1 ulp', lambda: (record_a(), mutate(_m1)), False),
    ('M2 non-identity count changed', lambda: (record_a(), mutate(lambda b: _set(b, 'count', 4))), False),
    ('M2b refusal code changed', lambda: (record_a(), mutate(lambda b: _set(b, 'refusal', 'R-HEAT-1'))), False),
    ('M3 absolute path left in a sources key', lambda: (record_a(), mutate(_m3)), False),
    ('M4 sibling pin dropped', lambda: (record_a(), mutate(lambda b: b['sources'].pop(
        PRIV + 'private_heat_closed_owned_r4.py'))), False),
    ('M5 F5 pin left on heat-repair bytes', lambda: (record_a(), mutate(lambda b: b['source_bindings'].__setitem__(
        'atlas_tectonics/integration_spatial_transport.py', H_ST))), False),
    ('M5b nested sha256:-prefixed pin left old', lambda: (record_a(), mutate(
        lambda b: b['inner']['payload'].__setitem__('pin', 'sha256:' + OLD[HELP + TREE]))), False),
    ('M6 stale key the fold did not emit (B side)', lambda: (record_a(), mutate(_m6)), False),
    ('M6b unmapped key on A side', lambda: (_self_ids(dict(record_a(), sources=dict(record_a()['sources'], **{
        'C:\\w\\elsewhere\\private_heat_ghost_r1.py': h('ghost')}))), fold_record(record_a())), False),
    ('M7 path booking grows', lambda: (record_a(), mutate(lambda b: _set(b, 'path_bytes', 413))), False),
    ('M7b booking under a path key grows', lambda: (record_a(), mutate(
        lambda b: b['bytes_by_file'].__setitem__(PRIV + FINISH, 101))), False),
    ('M8 forged result_id', lambda: (record_a(), mutate(lambda b: _set(b, 'result_id', h('forged')), reid=False)),
     False),
    ('M8b forged consumer ID', lambda: (record_a(), mutate(lambda b: _set(b, 'consumer', h('forged')))), False),
    ('M8c A carries a forged result_id', lambda: (dict(record_a(), result_id=h('forged')), fold_record(record_a())),
     False),
    ('N1 sources in a different insertion order', lambda: (record_a(), mutate(_n1)), True),
    ('R01 key_map not injective', lambda: (record_a(), fold_record(record_a()), _with(key_map=dict(
        manifest()['key_map'], **{'C:\\w\\other\\' + TREE: PRIV + TREE}))), False),
    ('R01b mapped key collides with a key already in A', _r01b, False),
    ('R04 external preimage contains a self-ID', _r04, False),
    ('R05 booking becomes bool', lambda: (record_a(), mutate(lambda b: _set(b, 'path_bytes', False))), False),
    ('R05b booking becomes negative', lambda: (record_a(), mutate(lambda b: _set(b, 'path_bytes', -1))), False),
    ('R05c ~/ user path carried into B', _leak('~/w/composed-r2/helpers/' + TREE), False),
    ('R05d UNC user path carried into B', _leak('\\\\server\\share\\LOCAL_USER\\x.py'), False),
    ('R05e ..\\Users\\ path carried into B', _leak('..\\..\\Users\\LOCAL_USER\\x.py'), False),
    ('R06 old sha with two different new shas', _r06, False),
    ('N3 URL text is not a user path', _leak('https://example.org/a'), True),
]

ORIGINAL = '''import private_heat_issuer_resources_r1 as R
from private_heat_finish_arithmetic_r1 import exact_sum
from pathlib import Path
import importlib
_SOURCE_PATHS = (__file__, Path('C:\\\\w\\\\heat-repair\\\\src\\\\atlas_tectonics')/'integration_spatial_transport.py')
_SOURCES = {str(Path(p).resolve()): R.digest(p) for p in _SOURCE_PATHS}
PIN = '%s'
SEED = '%s'
SEP = '/'
K = importlib.import_module('private_heat_tree_r1')
def total(xs):
    return exact_sum(xs) + 1
''' % (H_ST, h('seed'))

FOLDED = '''from atlas_tectonics._private import private_heat_issuer_resources_r1 as R
from atlas_tectonics._private.private_heat_finish_arithmetic_r1 import exact_sum
from pathlib import Path
import importlib
from atlas_tectonics import _identity
_SOURCE_PATHS = (__file__, Path(_identity.PACKAGE_DIR)/'integration_spatial_transport.py')
_SOURCES = {_identity.relkey(p): R.digest(p) for p in _SOURCE_PATHS}
PIN = '%s'
SEED = '%s'
SEP = '/'
K = importlib.import_module('atlas_tectonics._private.private_heat_tree_r1')
def total(xs):
    return exact_sum(xs) + 1
''' % (S_ST, h('seed'))

CLASH = 'def _identity(s):\n    return s\n'

AST_CASES = [
    ('positive: import, path, pin and key rewrites only', ORIGINAL, FOLDED, True),
    ('M9 code edit outside import/pin/key nodes', ORIGINAL, FOLDED.replace('exact_sum(xs) + 1', 'exact_sum(xs) + 2'),
     False),
    ('M9b import retargeted to another module', ORIGINAL, FOLDED.replace(
        'private_heat_finish_arithmetic_r1 import', 'private_heat_finish_arithmetic_r2 import'), False),
    ('M9c import_module name retargeted', ORIGINAL, FOLDED.replace(
        "_private.private_heat_tree_r1'", "_private.private_heat_tree_r2'"), False),
    ('M9d alias renamed', ORIGINAL, FOLDED.replace('_resources_r1 as R', '_resources_r1 as Q').replace(
        'R.digest', 'Q.digest'), False),
    ('M9e pin literal not the manifest new sha', ORIGINAL, FOLDED.replace(S_ST, h('wrong')), False),
    ('M9f seed hex-64 changed', ORIGINAL, FOLDED.replace(h('seed'), h('seed2')), False),
    ('M9g path literal replaced by another declared constant', ORIGINAL, FOLDED.replace(
        '_identity.PACKAGE_DIR', '_identity.PRIVATE_DIR'), False),
    ('M9h identity import shadows an existing name', ORIGINAL, FOLDED.replace(
        'from atlas_tectonics import _identity\n', 'from atlas_tectonics import _identity\n'
        'from atlas_tectonics import _identity as R\n'), False),
    ('M9i key call with an extra keyword', ORIGINAL, FOLDED.replace(
        '_identity.relkey(p)', "_identity.relkey(p, base='x')"), False),
    ('M9j helper import left unqualified', ORIGINAL, FOLDED.replace(
        'from atlas_tectonics._private import private_heat_issuer_resources_r1 as R',
        'import private_heat_issuer_resources_r1 as R'), False),
    ('M9k "/" separator edited', ORIGINAL, FOLDED.replace("SEP = '/'", "SEP = '/x/'"), False),
    ('M9l identity name already used in the original', ORIGINAL + CLASH, FOLDED + CLASH, False),
    ('M9m absolute path literal left in folded code', ORIGINAL, FOLDED.replace(
        '_identity.PACKAGE_DIR', "'C:\\\\w\\\\heat-repair\\\\src\\\\atlas_tectonics'"), False),
]


def _tree(base, name):
    src = Path(base)/name/'src'
    pkg = src/'atlas_tectonics'/'_private'
    pkg.mkdir(parents=True)
    (src/'atlas_tectonics'/'__init__.py').write_text('', encoding='utf8')
    (pkg/'__init__.py').write_text('', encoding='utf8')
    (pkg/'mod_r1.py').write_bytes(b'VALUE = 1\n')
    return src


def run_g_pin(tmp):
    good, stale = h('VALUE = 1\n'), h('VALUE = 0\n')
    key, name = 'atlas_tectonics/_private/mod_r1.py', 'atlas_tectonics._private.mod_r1'

    def pins_manifest(new, pin):
        return dict(sha_map={key: [h('old mod_r1'), new]}, pins={name: pin})

    def pyc(src):
        (src/'atlas_tectonics'/'_private'/'__pycache__').mkdir()
        (src/'atlas_tectonics'/'_private'/'__pycache__'/'mod_r1.cpython-312.pyc').write_bytes(b'\0')

    cases = (('positive: pin equals the imported file and sha_map', good, good, None, True),
             ('M10 pin and sha_map name a stale copy (G-PIN)', stale, stale, None, False),
             ('M10b pin differs from sha_map new sha', good, stale, None, False),
             ('M10c stale bytecode beside the pinned source', good, good, pyc, False),
             ('M10d helper importable at top level', good, good,
              lambda src: (src/'mod_r1.py').write_bytes(b'VALUE = 0\n'), False))
    out = []
    for i, (label, new, pin, extra, expect) in enumerate(cases):
        src = _tree(tmp, 'g%d' % i)
        if extra:
            extra(src)
        try:
            P.check_pins(src, pins_manifest(new, pin))
            out.append((label, True, expect))
        except P.ParityError as error:
            out.append((label + ' [' + str(error)[:60] + ']', False, expect))
    return out


def run_main_nan(tmp):
    """Fail closed with FAIL JSON, never a traceback: NaN in A (canonical JSON refuses it)."""
    files = []
    for i, value in enumerate(({'x': float('nan')}, {'x': float('nan')}, dict(key_map={}, sha_map={}))):
        files.append(str(Path(tmp)/('nan%d.json' % i)))
        Path(files[-1]).write_text(json.dumps(value), encoding='utf8')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = P.main(['records'] + files)
    return [('R03 NaN record gives FAIL JSON, not a traceback',
             code == 0 or json.loads(out.getvalue())['status'] != 'FAIL', False)]


def real_stream_hash(helpers):
    spec = importlib.util.spec_from_file_location('_rm_issuer_resources', Path(helpers)/'private_heat_issuer_resources_r1.py')
    if spec is None or spec.loader is None:
        raise SystemExit('cannot load issuer_resources_r1 from %s' % helpers)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.stream_hash


def main(argv):
    results = []
    for name, build, expect in RECORD_CASES:
        built = build()
        a, b, m = built if len(built) == 3 else built + (manifest(),)
        try:
            P.check_records(a, b, m)
            results.append((name, True, expect))
        except (P.ParityError, KeyError, ValueError, TypeError) as error:
            results.append((name + ' [' + str(error)[:70] + ']', False, expect))
    m = manifest()
    for name, original, folded, expect in AST_CASES:
        problem = P.ast_diff(original, folded, m)
        results.append((name + ('' if problem is None else ' [' + problem[:60] + ']'), problem is None, expect))
    a = record_a()
    results.append(('N2 noise arm: identical canonical bytes', P.canonical(a) == P.canonical(copy.deepcopy(a)), True))
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
        results += run_g_pin(tmp)
        results += run_main_nan(tmp)
    if argv:
        real = real_stream_hash(argv[0])
        samples = [record_a(), fold_record(record_a()), {'x': [1.5, None, 'é', {'b': 2, 'a': 1}]}]
        results.append(('stream_hash equals issuer_resources_r1.stream_hash',
                        all(real(s) == P.stream_hash(s) for s in samples), True))
    bad = [r for r in results if r[1] != r[2]]
    for name, passed, expect in results:
        print('%-4s %-6s %s' % ('ok' if passed == expect else 'BAD', 'PASS' if passed else 'FAIL', name))
    print(json.dumps(dict(cases=len(results), wrong=len(bad))))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
