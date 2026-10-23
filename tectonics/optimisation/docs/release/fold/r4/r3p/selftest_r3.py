"""Synthetic selftests for the r3 re-fold tools: arms_r7's observer and save, v27 bookings/limbs_r3/cells_keyed,
mutants_r4's data-key preflight and hcf_prepare_r15's refusals. No heat run, no composition is read except the r2
fold manifest (read-only, for bookings.Translation) and HCF's bytes.

    python -B -I selftest_r3.py FOLD_DIR HCF WORK_DIR

WORK_DIR must not exist. Exit 0 iff every case is as expected.
"""
import ast
import contextlib
from fractions import Fraction
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import gmpy2
from gmpy2 import mpq, mpz
import numpy as np

RESULTS = []


def case(name, ok, detail=''):
    RESULTS.append(dict(case=name, ok=bool(ok), detail=str(detail)[:200]))
    print('%-4s %s %s' % ('ok' if ok else 'BAD', name, str(detail)[:120]), flush=True)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def raises(call, kind, text=''):
    try:
        call()
    except kind as error:
        return text in str(error), str(error)
    except Exception as error:
        return False, 'other %s: %s' % (type(error).__name__, error)
    return False, 'no exception'


def observer(A):
    r = A._Rationals()
    a, b = mpq(-3, 7), mpq(2**70, 3)
    for value in (a, a, b, Fraction(-1, 3), 7):
        r.add(value, sys.getsizeof(value))
    rows = {row[0]: row for row in r.table()}
    case('obs-8-columns', all(len(row) == 8 for row in rows.values()), rows.keys())
    q = rows['mpq']
    case('obs-count-distinct', q[1] == 3 and q[6] == 2, q)
    case('obs-tight-below', q[4] == A._tight(a)*2 + A._tight(b) and q[5] == 0 and q[2] >= q[4], q[2:6])
    case('obs-fraction-no-tight', rows['Fraction'][4] is None and rows['Fraction'][5] is None, rows['Fraction'])
    neg, pos = A._Rationals(), A._Rationals()
    neg.add(mpq(-3, 7), 88)
    pos.add(mpq(3, 7), 88)
    case('obs-signed-digest', neg.table()[0][3] != pos.table()[0][3])
    case('obs-tight-formula', A._tight(mpq(0, 1)) == mpq.__basicsize__ + 8 and A._tight(mpz(0)) == mpz.__basicsize__
         and A._tight(mpq(2**64, 1)) == mpq.__basicsize__ + 8*3)
    record = A._gmp_record()
    case('obs-gmp-record', record['loaded'] and record['version'] == gmpy2.version() and record['limb_bits'] == 64
         and 'gmpy2' in record['module_sha256'], {k: v for k, v in record.items() if k != 'module_sha256'})


GMP = dict(loaded=True, version='2.3.2', mp_version='GMP 6.3.0', limb_bits=64, basicsize=dict(mpq=56, mpz=40),
           module_sha256={'gmpy2': '0'*64})


def bookings_rules(B):
    def eqs(table, gmp=GMP):
        x = B.Eqs(SimpleNamespace(gmp=gmp, name='A'), 'w')
        x.rationals(table, 'owned values')
        return x
    good = ['mpq', 8, 640, 'd'*64, 512, 0, 8, 640]
    case('book-accepts-r7-row', eqs([good]).alloc['owned values mpq'][:5] == (8, 640, 'd'*64, True, 512))
    for name, table, gmp, text in (
            ('book-refuses-4-columns', [good[:4]], GMP, 'columns'),
            ('book-refuses-below-tight', [good[:5] + [1] + good[6:]], GMP, 'below their tight'),
            ('book-refuses-size-under-tight', [good[:2] + [500] + good[3:]], GMP, 'below their tight'),
            ('book-refuses-no-gmp-record', [good], None, 'gmpy2 record'),
            ('book-refuses-32-bit-limbs', [good], dict(GMP, limb_bits=32), 'gmpy2 record'),
            ('book-refuses-no-tight', [good[:4] + [None, None] + good[6:]], GMP, 'no tight record'),
            ('book-refuses-fraction-tight', [['Fraction', 2, 96, 'e'*64, 5, 0, 2, 96]], GMP, 'not gmpy2')):
        ok, why = raises(lambda t=table, g=gmp: eqs(t, g), B.BookingError, text)
        case(name, ok, why)

    def compare(row_a, row_b):
        xa, xb = eqs([row_a]), eqs([row_b])
        env = B.Env(dict(globals={}, locals={}), 'w')
        report = []
        problems = B.compare('site', 0, xa, env, xb, env, report, B.Sigma())
        return problems, report
    problems, report = compare(good, good)
    case('cmp-equal', not problems and report[0]['over_limbs'] == [['owned values mpq', 8, 16, 16, 8, 8]], report[0])
    problems, _ = compare(good, good[:2] + [624] + good[3:])
    case('cmp-b-smaller-passes', not problems, problems)
    problems, _ = compare(good, good[:2] + [648] + good[3:])
    case('cmp-b-one-limb-per-eight-passes', not problems, problems)
    problems, _ = compare(good, good[:2] + [656] + good[3:])
    case('cmp-b-growth-over-cap-fails', any('more than one limb' in p for p in problems), problems)
    problems, _ = compare(good, good[:2] + [644] + good[3:])
    case('cmp-part-limb-fails', any('whole limbs' in p for p in problems), problems)
    problems, _ = compare(good, good[:4] + [520] + good[5:])
    case('cmp-tight-differs-fails', any('tight sizes' in p for p in problems), problems)
    problems, _ = compare(good, good[:3] + ['f'*64] + good[4:])
    case('cmp-values-differ-fails', any('values differ' in p for p in problems), problems)


def bookings_check(B, fold, work):
    manifest = json.loads((fold/'p8'/'b'/'MANIFEST-h.json').read_text(encoding='utf8'))
    dirs = {}
    for name in ('al', 'ao', 'bl', 'bo'):
        dirs[name] = work/'bk'/name
        dirs[name].mkdir(parents=True)
    (dirs['al']/'arm.json').write_text('{}')
    (dirs['bl']/'arm.json').write_text(json.dumps(dict(package_parent=str(work))))
    for out in ('ao', 'bo'):
        (dirs[out]/'bookings.json').write_text('{}')

    def run(gmp_a, gmp_b):
        for out, gmp in (('ao', gmp_a), ('bo', gmp_b)):
            path = dirs[out]/'arm.json'
            path.unlink(missing_ok=True)
            if gmp is not False:
                path.write_text(json.dumps(dict(gmp=gmp)))
        return lambda: B.check(dirs['al'], dirs['ao'], dirs['bl'], dirs['bo'], manifest)
    ok, why = raises(run(GMP, dict(GMP, version='2.3.1')), B.BookingError, 'different gmpy2 builds')
    case('check-refuses-gmp-mismatch', ok, why)
    ok, why = raises(run(GMP, False), B.BookingError, 'no gmpy2 build record')
    case('check-refuses-missing-record', ok, why)
    ok, why = raises(run(GMP, GMP), B.BookingError, 'required booking sites')
    case('check-equal-records-reach-sites', ok, why)
    return dirs, run


def limbs(L, B, dirs, run):
    L.B = B
    base = dict(site='s', snapshot=0, name='owned values mpq', gmpy=True, values=1428, values_equal=True,
                tight_equal=True, size_x=0, size_y=0, over_x=10, over_y=10, distinct_x=714, distinct_y=714)
    s = L.summary([dict(base, delta=-800, distinct_delta=-400)], [])
    case('limbs-b-smaller-within-cap', s['within_cap'] and s['booked_limbs_net'] == -100
         and s['distinct_limbs_net'] == -50, s)
    s = L.summary([dict(base, delta=8*180, distinct_delta=8*90)], [])
    case('limbs-growth-over-cap', not s['within_cap'] and s['max_growth_limbs_per_value'] > 0.125, s)
    s = L.summary([dict(base, delta=8*179, distinct_delta=0)], [])
    case('limbs-growth-at-cap', s['within_cap'], s)
    s = L.summary([dict(base, delta=0, distinct_delta=0, tight_equal=False)], [])
    case('limbs-tight-unequal-reported', not s['tight_equal'], s)
    run(GMP, dict(GMP, mp_version='GMP 6.2.1'))
    ok, why = raises(lambda: L.rows(B.Translation(json.loads((Path(sys.argv[1])/'p8'/'b'/'MANIFEST-h.json')
                                                               .read_text(encoding='utf8'))),
                                    dirs['al'], dirs['ao'], 'A', dirs['bl'], dirs['bo'], 'B'),
                     B.BookingError, 'gmpy2 build records')
    case('limbs-refuses-gmp-mismatch', ok, why)


def save(directory, cells, arrays, key_fields=True):
    directory.mkdir(parents=True)
    table = {}
    for name, array in arrays.items():
        np.save(directory/(name + '.npy'), array, allow_pickle=False)
        table[name] = dict(shape=list(array.shape), dtype=array.dtype.str, sha256=sha256(array.tobytes()).hexdigest())
    (directory/'arrays.json').write_text(json.dumps(table))
    fields = ['cell_id', 'logical_cell_id', 'voxel_index', 'radial_band', 'chart', 'kind'] + (
        ['physical_cell_id'] if key_fields else [])
    (directory/'cell_keys.json').write_text(json.dumps(dict(key_fields=fields, cells=cells)))


def cells(K, work):
    n_ext, n_col = 4, 2
    rows = [dict(cell_id='c%d' % i, logical_cell_id='L%d' % i, voxel_index=[i, 0, 0], radial_band=0, chart=0,
                 kind='exterior') for i in range(n_ext)]
    rows += [dict(cell_id='c%d' % (n_ext + i), logical_cell_id='F1-%d' % i, physical_cell_id='P%d' % i, kind='collar')
             for i in range(n_col)]
    values = {name: np.linspace(1.0 + k, 2.0 + k, n_ext + n_col) for k, name in enumerate('abcde')}
    save(work/'ref', rows, values)
    order = [5, 2, 0, 4, 1, 3]

    def variant(label, edit=lambda rs, vs: None, key_fields=True):
        rs = [dict(rows[i]) for i in order]
        for j, r in enumerate(rs):
            r['cell_id'] = 'n%d' % j
            if 'physical_cell_id' in r:
                r['logical_cell_id'] = r['logical_cell_id'].replace('F1', 'F2')
        vs = {name: array[order].copy() for name, array in values.items()}
        edit(rs, vs)
        save(work/label, rs, vs, key_fields)
        return K.compare(work/'ref', work/label)
    r = variant('same')
    case('cells-renumbered-match', r['status'] == 'PASS' and r['mixed_key_match'] == dict(
        exterior=4, collar=2, total=6, cells=[6, 6], unmatched=[0, 0]) and not r['cell_ids_equal']
        and not r['logical_ids_equal'] and r['rows_multiset_equal'], r)
    r = K.compare(work/'ref', work/'same', (4, 2))
    case('cells-expected-counts', r['status'] == 'PASS' and r['counts_as_expected'], r['expected'])
    r = K.compare(work/'ref', work/'same', (5, 1))
    case('cells-unexpected-counts-fail', r['status'] == 'FAIL' and not r['counts_as_expected'], r['mixed_key_match'])
    with contextlib.redirect_stdout(io.StringIO()):
        usage = K.main([str(work/'ref'), str(work/'same'), str(work/'o.json'), 'x', '2'])
        good = K.main([str(work/'ref'), str(work/'same'), str(work/'o.json'), '4', '2'])
    report = json.loads((work/'o.json').read_text())
    case('cells-cli-counts', usage == 2 and good == 0 and report['counts_as_expected'], (usage, good))

    def ulp(rs, vs):
        vs['c'][3] = np.nextafter(vs['c'][3], np.inf)
    r = variant('ulp', ulp)
    case('cells-one-ulp-fails', r['status'] == 'FAIL' and r['rows_mismatched'] == 1, r)

    def content(rs, vs):
        next(x for x in rs if 'voxel_index' in x)['radial_band'] = 1
    r = variant('content', content)
    case('cells-key-field-fails', r['status'] == 'FAIL' and 'key fields' in r['mismatched'][0], r)
    for label, edit, kf, text in (
            ('nophys', lambda rs, vs: next(x for x in rs if 'physical_cell_id' in x).pop('physical_cell_id'), True,
             'without physical_cell_id'),
            ('dup', lambda rs, vs: [x.update(physical_cell_id='P0') for x in rs if 'physical_cell_id' in x], True,
             'repeated'),
            ('nofield', lambda rs, vs: None, False, 'does not record kind and physical_cell_id'),
            ('nokind', lambda rs, vs: rs[0].pop('kind'), True, 'has kind None'),
            ('otherkind', lambda rs, vs: rs[0].update(kind='interior'), True, "has kind 'interior'")):
        ok, why = raises(lambda e=edit, k=kf, lb=label: variant(lb, e, k), K.Refusal, text)
        case('cells-refuses-' + label, ok, why)
    save(work/'empty', [], {name: np.zeros(0) for name in 'abcde'})
    ok, why = raises(lambda: K.compare(work/'empty', work/'empty'), K.Refusal, 'no cells')
    case('cells-refuses-empty', ok, why)
    np.save(work/'same'/'c.npy', np.zeros(6), allow_pickle=False)
    ok, why = raises(lambda: K.compare(work/'ref', work/'same'), K.Refusal, 'is not the array')
    case('cells-refuses-bad-array', ok, why)


def arms_save(A, work):
    class Value:
        array_names = ('e', 'f')

        def array(self, name):
            return np.arange(3.0) + (0 if name == 'e' else 10)
    metadata = json.dumps(dict(cell_ids=['c2', 'c0', 'c1'])).encode()
    old = SimpleNamespace(_snapshot=SimpleNamespace(_metadata=metadata))
    mesh = {'c0': dict(cell_id='c0', logical_cell_id='L0', voxel_index=[0, 0, 0], kind='exterior', extra=1),
            'c1': dict(cell_id='c1', logical_cell_id='L1', voxel_index=[1, 0, 0], kind='exterior'),
            'c2': dict(cell_id='c2', logical_cell_id='F-2', physical_cell_id='P2', kind='collar')}
    order = ['c0', 'c1', 'c2']
    view = SimpleNamespace(cell_count=3, cell=lambda i: SimpleNamespace(value=mesh[order[i]]))
    work.mkdir(parents=True)

    def advance(directory, state):
        return A._save_advance(directory, state, advance.__code__, sys._getframe(0), Value())

    def child_with_locals(directory, state, old=old, view=view):  # the saver reads old and view from this frame
        return advance(directory, state)

    def fresh():
        return dict(saved=False, error=None, arrays={}, cells=None, advance_returns=0,
                    caller_code=child_with_locals.__code__)
    state = fresh()
    result = child_with_locals(work/'save', state)
    keys = json.loads((work/'save'/'cell_keys.json').read_text())
    table = json.loads((work/'save'/'arrays.json').read_text())
    case('save-writes-keys', state['saved'] and state['cells'] == 3 and keys['key_fields'][-2:] == [
        'kind', 'physical_cell_id'] and keys['cells'][0]['kind'] == 'collar'
         and [c['cell_id'] for c in keys['cells']] == ['c2', 'c0', 'c1'] and keys['cells'][0]['physical_cell_id'] == 'P2'
         and 'extra' not in keys['cells'][1] and keys['mesh_row_order_equal'] is False, keys)
    case('save-array-digest', table['f']['sha256'] == sha256((np.arange(3.0) + 10).tobytes()).hexdigest()
         and result == sys.monitoring.DISABLE, table['f'])
    good = dict(arrays={name: entry['sha256'] for name, entry in table.items()}, cell_count=3)
    case('save-problems-none', A._save_problems(state, good) == [], A._save_problems(state, good))
    case('save-problems-digest', A._save_problems(state, dict(good, arrays=dict(good['arrays'], e='0'*64))) != [])
    case('save-problems-cells', A._save_problems(state, dict(good, cell_count=4)) != [])
    other = fresh()
    advance(work/'save2', other)
    case('save-wrong-caller-recorded', other['error'] and 'did not return to the control child' in other['error']
         and A._save_problems(other, good) != [], other['error'])
    unsaved = fresh()
    case('save-not-saved-reported', any('not saved' in p for p in A._save_problems(unsaved, good)))


def observer_save(A, K, work):
    """arms_r7's own observer: a synthetic r13 issuer's advance() returns None and then a value to a control child
    whose locals hold old and view; the PY_RETURN callback's frame depth picks the returning frame. cells_keyed then
    reads the save."""
    class Value:
        array_names = ('e', 'f')

        def array(self, name):
            return np.arange(3.0) + (0 if name == 'e' else 10)
    metadata = json.dumps(dict(cell_ids=['c2', 'c0', 'c1'])).encode()
    old = SimpleNamespace(_snapshot=SimpleNamespace(_metadata=metadata))
    mesh = [dict(cell_id='c0', logical_cell_id='L0', voxel_index=[0, 0, 0], kind='exterior'),
            dict(cell_id='c1', logical_cell_id='L1', voxel_index=[1, 0, 0], kind='exterior'),
            dict(cell_id='c2', logical_cell_id='F-2', physical_cell_id='P2', kind='collar')]
    view = SimpleNamespace(cell_count=3, cell=lambda i: SimpleNamespace(value=mesh[i]))
    (work/'issuer').mkdir(parents=True)
    (work/'out').mkdir()
    (work/'issuer'/A.ISSUER).write_text('def advance(value):\n    return value\n', encoding='utf8')
    issuer = load('selftest_issuer_r13', work/'issuer'/A.ISSUER)

    def control_child(old=old, view=view):  # the saver reads old and view from this frame
        return issuer.advance(None), issuer.advance(Value())
    state = dict(events=0, saved=False, error=None, booking_error=None, closed_guard_returns={}, bookings={})
    state['save'] = dict(saved=False, error=None, arrays={}, cells=None, advance_returns=0,
                         caller_code=control_child.__code__)
    _, stop = A._observer(work/'out', state)
    try:
        control_child()
    finally:
        stop()
    save = state['save']
    case('observer-saves-at-advance', save['saved'] and save['error'] is None and save['advance_returns'] == 2
         and save['cells'] == 3, save)
    r = K.compare(work/'out'/'save', work/'out'/'save', (2, 1))
    case('observer-save-keyed', r['status'] == 'PASS' and r['mixed_key_match']['total'] == 3, r)


def preflight(M, work):
    key = 'atlas_tectonics/_private/native/lib.dll'
    head = ("from pathlib import Path\nCAPTURE_LIBRARY_KEY = '%s'\n"
            "def task_file(key, folder=None):\n"
            "    start = Path(__file__).resolve().parent if folder is None else Path(folder).resolve()\n"
            "    found = [p/key for p in (start, *start.parents) if (p/key).is_file()]\n"
            "    return found[0] if len(found) == 1 else None\n"
            "CAPTURE_LIBRARY = task_file(CAPTURE_LIBRARY_KEY)\n" % key)
    lay = work/'pf'
    (lay/'helpers').mkdir(parents=True)
    (lay/'helpers'/'unguarded.py').write_text(head + "def reader():\n    return CAPTURE_LIBRARY\n")
    (lay/'helpers'/'other.py').write_text(head + "def capture_backend():\n    raise FileNotFoundError('elsewhere')\n")
    verdict, why = M._datakey_preflight(lay/'helpers'/'unguarded.py', key)
    case('preflight-unguarded-error', verdict == 'ERROR', why)
    verdict, why = M._datakey_preflight(lay/'helpers'/'other.py', key)
    case('preflight-other-refusal-error', verdict == 'ERROR', why)
    (lay/key).parent.mkdir(parents=True)
    (lay/key).write_bytes(b'x')
    verdict, why = M._datakey_preflight(lay/'helpers'/'unguarded.py', key)
    case('preflight-found', verdict == 'FOUND' and Path(why).resolve() == (lay/key).resolve(), why)
    verdict, why = M._datakey_preflight(lay/'helpers'/'unguarded.py', 'atlas_tectonics/other.dll')
    case('preflight-key-mismatch-error', verdict == 'ERROR', why)
    lay = work/'pf2'
    (lay/'helpers').mkdir(parents=True)
    (lay/'helpers'/'backend.py').write_text(head + (
        "def capture_backend():\n"
        "    if CAPTURE_LIBRARY is None:\n"
        "        raise FileNotFoundError('%s: ' + CAPTURE_LIBRARY_KEY)\n"
        "    return CAPTURE_LIBRARY\n" % M.REFUSAL))
    (lay/'helpers'/'guarded.py').write_text(head + (
        "def require(ok, why):\n"
        "    if not ok:\n"
        "        raise RuntimeError(why)\n"
        "def reader():\n"
        "    require(CAPTURE_LIBRARY is not None, 'no capture library')\n"
        "    return CAPTURE_LIBRARY\n"))
    (lay/'helpers'/'nested.py').write_text(head + (
        "def reader(flag):\n"
        "    if flag:\n"
        "        require(CAPTURE_LIBRARY is not None, 'no capture library')\n"
        "    return CAPTURE_LIBRARY\n"))
    for name, expect, text in (('backend', 'REFUSED', 'capture_backend'), ('guarded', 'REFUSED', 'reader'),
                               ('nested', 'ERROR', 'nothing refuses')):
        verdict, why = M._datakey_preflight(lay/'helpers'/(name + '.py'), key)
        case('preflight-%s-%s' % (name, expect.lower()), verdict == expect and text in why, why)
    # r4.1: task_file calling a module-level helper, as r12's calls _holds; and a name nothing defines
    helper = ("from pathlib import Path\nCAPTURE_LIBRARY_KEY = '%s'\n"
              "def _holds(path):\n    try:\n        return path.is_file()\n    except OSError:\n        return False\n"
              "def task_file(key, folder=None):\n"
              "    start = Path(__file__).resolve().parent if folder is None else Path(folder).resolve()\n"
              "    found = [p/key for p in (start, *start.parents) if %s(p/key)]\n"
              "    return found[0] if len(found) == 1 else None\n"
              "CAPTURE_LIBRARY = task_file(CAPTURE_LIBRARY_KEY)\n"
              "def capture_backend():\n"
              "    if CAPTURE_LIBRARY is None:\n"
              "        raise FileNotFoundError('%s: ' + CAPTURE_LIBRARY_KEY)\n")
    (lay/'helpers'/'holds.py').write_text(helper % (key, '_holds', M.REFUSAL))
    (lay/'helpers'/'unresolved.py').write_text(helper % (key, '_probe', M.REFUSAL))
    verdict, why = M._datakey_preflight(lay/'helpers'/'holds.py', key)
    case('preflight-helper-call-refused', verdict == 'REFUSED' and 'capture_backend' in why, why)
    verdict, why = M._datakey_preflight(lay/'helpers'/'unresolved.py', key)
    case('preflight-unresolved-name-error', verdict == 'ERROR' and 'NameError' in why, why)
    (lay/key).parent.mkdir(parents=True)
    (lay/key).write_bytes(b'x')
    verdict, why = M._datakey_preflight(lay/'helpers'/'holds.py', key)
    case('preflight-helper-call-found', verdict == 'FOUND' and Path(why).resolve() == (lay/key).resolve(), why)


def hcf_prepare(H, hcf, fold, work):
    fake = work/'fake_hcf.py'
    fake.write_text('x = 1\n')
    ok, why = raises(lambda: H.main(str(fake), str(fake), str(work/'w'), str(work), str(work)), SystemExit,
                     'not the reviewed harness')
    case('hcf15-refuses-other-harness', ok, why)
    comp = work/'composition.json'
    comp.write_text('{}')
    ok, why = raises(lambda: H.main(str(hcf), str(comp), str(work/'w'), str(work), str(work)), SystemExit,
                     'not the reviewed one')
    case('hcf15-refuses-other-record', ok, why)
    tree = ast.parse((fold/'hcf_prepare_r14.py').read_text(encoding='utf8'))
    r14 = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'COMPOSITION_SHA256')
    pins = H.COMPOSITION_SHA256
    case('hcf15-pins', len(r14) == 2 and pins[:2] == r14 and len(pins) in (2, 3)   # r1, r2 (r14's), then r3
         and all(len(s) == 64 and set(s) <= set('0123456789abcdef') for s in pins), pins)


def native(A, S, fold, work):
    """r8 (RF2 condition c): arms_r8's native record in this process, which imported gmpy2; wobs2's worker record,
    with the same log and module list as wobs (r1) for the same worker; and v27/mpfr_same.py's verdicts."""
    import os
    import subprocess
    record = A._native_record()
    mpfr = S._mpfr(record)
    case('native-child-one-mpfr', 'error' not in record and len(mpfr) == 1
         and mpfr[0][0] == S._key(record['expected_mpfr'])
         and mpfr[0][1] == sha256(Path(record['expected_mpfr']).read_bytes()).hexdigest(), record)
    case('native-child-gmp-seen', any(Path(p).name.lower().startswith('libgmp') for p in record['modules']), record)
    (work/'w').mkdir(parents=True)
    script = work/'w'/'worker.py'
    script.write_text('import gmpy2\nprint(gmpy2.mpq(1, 3) + 1)\n', encoding='utf8')
    logs, snaps = {}, {}
    for label, obs in (('r1', fold/'wobs'), ('r2', fold/'wobs2')):
        out = work/'w'/label
        out.mkdir()
        env = dict(os.environ, PYTHONPATH=str(obs), RM_FOLD_WORKER_OBS=str(out), PYTHONHASHSEED='0')
        run = subprocess.run([sys.executable, '-B', str(script), 'worker'], env=env, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=120)
        case('wobs-%s-worker-ran' % label, run.returncode == 0 and run.stdout.strip() == '4/3', run.stderr[-300:])
        logs[label] = [line for line in next(out.glob('w*.log')).read_text(encoding='utf8').splitlines()
                       if not line.startswith('s ')]
        snaps[label] = json.loads(next(out.glob('w*.json')).read_bytes())
    case('wobs2-log-as-r1', logs['r1'] == logs['r2'] and bool(logs['r2']), (len(logs['r1']), len(logs['r2'])))
    case('wobs2-modules-as-r1', set(snaps['r1']['modules']) == set(snaps['r2']['modules']),
         sorted(set(snaps['r1']['modules']) ^ set(snaps['r2']['modules']))[:5])
    worker = snaps['r2'].get('native', {})
    case('wobs2-worker-one-mpfr', 'error' not in worker and S._mpfr(worker) == mpfr, worker)
    case('wobs2-r1-has-no-native', 'native' not in snaps['r1'], sorted(snaps['r1']))
    problems = []   # the path from wobs2's snapshot through arms_r8's workers row to the judge
    rows = A._workers(dict(arm='A'), work/'w'/'r2', [('subprocess.Popen', None, True)], problems)
    case('workers-row-carries-native', not problems and len(rows) == 1 and rows[0]['snapshot']
         and rows[0]['native'] == worker, (problems, rows))
    for i in range(5):
        (work/'chain'/str(i)).mkdir(parents=True)
        (work/'chain'/str(i)/'arm.json').write_text(json.dumps(dict(native=record, workers=rows)), encoding='utf8')
    with contextlib.redirect_stdout(io.StringIO()):
        rc = S.main([str(work/'chain'/'out.json')] + [str(work/'chain'/str(i)) for i in range(5)])
    case('mpfr-same-real-records-pass', rc == 0, json.loads((work/'chain'/'out.json').read_bytes())['problems'])

    def judge(name, children):
        top = work/'mpfr'/name
        for i, (rec, workers) in enumerate(children):
            (top/str(i)).mkdir(parents=True)
            (top/str(i)/'arm.json').write_text(json.dumps(dict(native=rec, workers=workers)), encoding='utf8')
        with contextlib.redirect_stdout(io.StringIO()):
            rc = S.main([str(top/'out.json')] + [str(top/str(i)) for i in range(len(children))])
        return rc, json.loads((top/'out.json').read_bytes())
    prefix = str(work/'env')
    good = str(Path(prefix)/'Lib'/'site-packages'/'gmpy2.libs'/'libmpfr-6.dll')
    gmp = str(Path(prefix)/'Lib'/'site-packages'/'gmpy2.libs'/'libgmp-10.dll')

    def rec(modules):
        return dict(exec_prefix=prefix, expected_mpfr=good, modules=modules)
    one = rec({good: 'a' * 64, gmp: 'b' * 64})
    workers = [dict(pid=1, snapshot=False, native=None), dict(pid=2, snapshot=True, native=rec({})),
               dict(pid=3, snapshot=True, native=rec({good: 'a' * 64}))]
    rc, out = judge('pass', [(one, workers)] * 5)
    case('mpfr-same-pass', rc == 0 and out['status'] == 'PASS'
         and out['workers'] == dict(total=15, snapshot=10, with_mpfr=5), out)
    other = str(Path(prefix)/'elsewhere'/'libmpfr-6.dll')
    for name, children, text in (
            ('two-in-child', [(one, [])] * 4 + [(rec({good: 'a' * 64, other: 'a' * 64}), [])], '2 libmpfr'),
            ('sha-differs', [(one, [])] * 4 + [(rec({good: 'c' * 64}), [])], '2 distinct'),
            ('wrong-path', [(rec({other: 'a' * 64}), [])] * 5, 'not'),
            ('none-in-child', [(one, [])] * 4 + [(rec({gmp: 'b' * 64}), [])], '0 libmpfr'),
            ('worker-other-file', [(one, [dict(pid=4, native=rec({other: 'a' * 64}))])] + [(one, [])] * 4,
             '2 distinct'),
            ('worker-two', [(one, [dict(pid=5, native=rec({good: 'a' * 64, other: 'a' * 64}))])], '2 libmpfr'),
            ('child-error', [(dict(exec_prefix=prefix, error='OSError: x'), [])], 'no native record'),
            ('worker-error', [(one, [dict(pid=6, native=dict(exec_prefix=prefix, error='OSError: y'))])],
             'no native record'),
            ('child-missing', [(None, [])], 'no native record'),
            ('snapshot-no-native', [(one, [dict(pid=7, snapshot=True, modules=300, native=None)])] + [(one, [])] * 4,
             'a snapshot without a native record'),
            ('four-children', [(one, [])] * 4, '4 child folders')):
        rc, out = judge(name, children)
        case('mpfr-same-%s-fails' % name, rc == 1 and out['status'] == 'FAIL'
             and any(text in p for p in out['problems']), out['problems'])
    with contextlib.redirect_stdout(io.StringIO()):
        rc = S.main([str(work/'mpfr'/'repeat.json')] + [str(work/'mpfr'/'pass'/i) for i in '00123'])
    out = json.loads((work/'mpfr'/'repeat.json').read_bytes())
    case('mpfr-same-repeated-child-fails', rc == 1 and any('4 distinct' in p for p in out['problems']), out['problems'])


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__)
    fold, hcf, work = Path(argv[0]).resolve(), Path(argv[1]).resolve(), Path(argv[2]).resolve()
    work.mkdir(parents=True)
    A = load('arms_r8', fold/'arms_r8.py')
    sys.path.insert(0, str(fold/'v27'))
    import bookings as B
    L = load('limbs_r3', fold/'v27'/'limbs_r3.py')
    K = load('cells_keyed', fold/'v27'/'cells_keyed.py')
    M = load('mutants_r4', fold/'mutants_r4.py')
    H = load('hcf_prepare_r15', fold/'hcf_prepare_r15.py')
    observer(A)
    bookings_rules(B)
    dirs, run = bookings_check(B, fold, work)
    limbs(L, B, dirs, run)
    cells(K, work/'cells')
    arms_save(A, work/'arms')
    observer_save(A, K, work/'observer')
    preflight(M, work)
    hcf_prepare(H, hcf, fold, work)
    native(A, load('mpfr_same', fold/'v27'/'mpfr_same.py'), fold, work/'native')
    bad =[r['case'] for r in RESULTS if not r['ok']]
    (work/'selftest.json').write_text(json.dumps(dict(cases=len(RESULTS), bad=bad, results=RESULTS), indent=1))
    print(json.dumps(dict(status='PASS' if not bad else 'FAIL', cases=len(RESULTS), bad=bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
