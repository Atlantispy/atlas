"""Refuter reproducers for ps/iv1/compare_arms.py: planted after-arm changes that should not PASS.

Usage: repro_cmp.py REAL_DUMP_DIR COMPARE_ARMS_PY NEW_OUT_DIR
Builds before/after fixture arms (copies only, never links) with fake but self-consistent stage records and
dump.json bindings, plants one change per case, runs compare_arms.py in a separate -B -I process and prints
the verdict. json/numpy only; never imports the runtime; never writes under REAL_DUMP_DIR.
"""
import gc
import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

PROFILE = 'a'*64


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canon(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True).encode()


def enc(q):
    q = Fraction(q)
    return [hex(q.numerator), hex(q.denominator)]


def dec(r):
    return Fraction(int(r[0], 16), int(r[1], 16))


def build_arm(root, tag, i0, i1, *, gate=True, partition1=None, arrays1=None):
    """i0/i1: {record name: bytes}. Returns (attempt, dumps)."""
    attempt, dumps = root/'attempt', root/'dumps'
    for d in ('reader-root', 'reader-interval', 'run-root', 'run-interval'):
        (attempt/d).mkdir(parents=True)
    for stage, interval, records, extra in (('root', 0, i0, {}), ('interval', 1, i1, {'width_gate': {
            'schema': 'atlas.exact-width-gate.v1', 'passed': gate, 'rows': []}})):
        fake = {k: sha(('%s-%s-%s' % (tag, stage, k)).encode()) for k in ('reader', 'finalise', 'adopt')}
        gate_value = gate if stage == 'interval' else None
        status = 'ADOPTED' if gate_value is not False else 'ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2'
        record = {'status': status, 'width_gate_passed': gate_value, 'steps': [
            {'name': 'runner', 'ok': True, 'receipt_sha256': '0'*64},
            {'name': 'reader', 'ok': True, 'receipt_sha256': fake['reader']},
            {'name': 'finalise', 'ok': True, 'verdict_sha256': fake['finalise'], 'width_gate_passed': gate_value},
            {'name': 'adopt', 'ok': True, 'adopted_sha256': fake['adopt']}]}
        (attempt/('stage-%s.json' % stage)).write_bytes(canon(record))
        folder = dumps/('i%d' % interval)
        (folder/'records').mkdir(parents=True)
        (folder/'arrays').mkdir()
        dump = {'schema': 'atlas.private.iv1-arm-dump.r1', 'status': 'PASS', 'interval': interval,
                'profile': {'sha256': PROFILE}, 'errors': [],
                'bindings': {'reader_receipt': {'path': str(attempt/('reader-'+stage)/'reopen.json'),
                                                'sha256': fake['reader']},
                             'verdict': {'path': 'verdict', 'sha256': fake['finalise']},
                             'adopted': {'path': 'adopted', 'sha256': fake['adopt']}},
                'records': {}, 'arrays': [], 'widths': None, **extra}
        if stage == 'interval':
            dump['partition'] = {'dumped': False, 'identity': partition1,
                                 'reason': 'descriptor statistics only (the reader proves it the same way)'}
        for name, data in records.items():
            (folder/'records'/(name+'.json')).write_bytes(data)
            dump['records'][name] = {'nbytes': len(data), 'sha256': sha(data)}
        if stage == 'interval' and arrays1 is not None:
            for i, (name, values) in enumerate(arrays1):
                raw = values.tobytes()
                (folder/'arrays'/('%04d.bin' % i)).write_bytes(raw)
                dump['arrays'].append({'name': name, 'file': '%04d.bin' % i, 'dtype': values.dtype.str,
                                       'shape': list(values.shape), 'nbytes': len(raw), 'sha256': sha(raw)})
        (folder/'dump.json').write_bytes(canon(dump))
    return attempt, dumps


SMALL_STATE = canon({'state_id': 'b'*64, 'note': 'unchanged'})


def case_dirs(out, name):
    case = out/name
    case.mkdir()
    return case


# ---------------------------------------------------------------- cases on the real interval-0 mesh
def real_mesh_cases(out, real_dir, plan):
    raw = (real_dir/'records'/'mesh.json').read_bytes()
    state = (real_dir/'records'/'state.json').read_bytes()
    mesh = json.loads(raw)
    base = canon(mesh)
    cells = {c['cell_id'] for c in mesh['cells']}

    def emit(name, mutate, undo, expect):
        case = case_dirs(out, name)
        before = build_arm(case/'b', name+'-b', {'mesh': base, 'state': state}, {'state': SMALL_STATE})
        detail = mutate()
        after_bytes = canon(mesh)
        undo()
        after = build_arm(case/'a', name+'-a', {'mesh': after_bytes, 'state': state}, {'state': SMALL_STATE})
        plan.append((name, before, after, expect, detail))

    # A1: a face's second owner now points at a different, existing and otherwise unchanged cell
    face = next(f for f in mesh['faces'] if len(f['owners']) == 2)
    old = list(face['owners'])
    other = sorted(cells - set(old))[0]

    def a1():
        face['owners'][1] = other
        return {'face_id': face['face_id'], 'owner_before': old[1], 'owner_after': other}

    def a1_undo():
        face['owners'][:] = old
    emit('A1_face_owner_rereferenced', a1, a1_undo, 'not PASS (topology changed: a face re-points to another cell)')

    # A2: an input identity (material model) differs between the arms; nothing else changes
    material = mesh['source']['material_id']

    def a2():
        mesh['source']['material_id'] = sha(b'another material table')
        return {'material_id_before': material, 'after': mesh['source']['material_id']}

    def a2_undo():
        mesh['source']['material_id'] = material
    emit('A2_input_identity_changed', a2, a2_undo, 'not PASS (the arms ran on different material inputs)')

    # B: radial layer depth judged against the layer's geometric radius_m as if it were an uncertainty
    support = mesh['support_tables']['differential_supports'][sorted(mesh['support_tables']['differential_supports'])[0]]
    layer = support['radial_layer']
    saved = dict(layer)

    def b():
        layer['bottom_depth_m'] = enc(dec(layer['bottom_depth_m'])*(1+Fraction(1, 800)))
        layer['radius_m'] = enc(dec(layer['radius_m'])*(1+Fraction(1, 4096)))
        return {'bottom_depth_m': [float(dec(saved['bottom_depth_m'])), float(dec(layer['bottom_depth_m']))],
                'radius_m': [float(dec(saved['radius_m'])), float(dec(layer['radius_m']))],
                'relative': [1/800, 1/4096]}

    def b_undo():
        layer.clear()
        layer.update(saved)
    emit('B_radial_layer_vs_radius_m', b, b_undo, 'REVIEW (exact config values changed by 1.25e-3 and 2.4e-4 relative)')

    # C: the mesh-wide certified deviation grows 5% (judged against the 32000 m3 error budget)
    dev = mesh['geometry_volume_max_deviation_m3']

    def c():
        mesh['geometry_volume_max_deviation_m3'] = enc(dec(dev)*Fraction(105, 100))
        return {'before': float(dec(dev)), 'after': float(dec(dev)*Fraction(105, 100)),
                'budget': float(dec(mesh['max_geometry_volume_error_m3']))}

    def c_undo():
        mesh['geometry_volume_max_deviation_m3'] = dev
    emit('C_certified_deviation_up_5pct', c, c_undo, 'REVIEW (a radius field changed by 5% > 2**-11)')
    del mesh, raw, base
    gc.collect()


# ---------------------------------------------------------------- synthetic interval-1 cases
def synthetic_cases(out, plan):
    def pair(name, before_i1, after_i1, expect, kb=None, ka=None):
        case = case_dirs(out, name)
        kb, ka = kb or {}, ka or {}
        before = build_arm(case/'b', name+'-b', {'state': SMALL_STATE}, before_i1, **kb)
        after = build_arm(case/'a', name+'-a', {'state': SMALL_STATE}, after_i1, **ka)
        plan.append((name, before, after, expect, None))

    # D: field kind fixed by its first leaf: a changed float first, then an int change of 29% is never judged
    cert_b = {'iterations': [{'step': 'a', 'value': 0.5}, {'step': 'b', 'value': 7}]}
    cert_a = {'iterations': [{'step': 'a', 'value': 0.5000000000000001}, {'step': 'b', 'value': 9}]}
    pair('D_kind_sticky_int_change', {'certification': canon(cert_b)}, {'certification': canon(cert_a)},
         'REVIEW (int 7 -> 9 under a keyed pairing)')

    # D2: the same with a rational: first leaf a changed float, then a rational doubles
    cert_b = {'rows': [{'cell': 'x', 'q': 1.0}, {'cell': 'y', 'q': enc(Fraction(1, 3))}]}
    cert_a = {'rows': [{'cell': 'x', 'q': 1.0000000000000002}, {'cell': 'y', 'q': enc(Fraction(2, 3))}]}
    pair('D2_kind_sticky_rational_doubles', {'certification': canon(cert_b)}, {'certification': canon(cert_a)},
         'REVIEW (rational 1/3 -> 2/3)')

    # E: the interval-1 partition identity differs; it is never compared
    pair('E_partition_identity_changed', {'state': SMALL_STATE}, {'state': SMALL_STATE},
         'not PASS (partition record differs between arms)',
         kb={'partition1': {'sha256': 'c'*64, 'nbytes': 100}}, ka={'partition1': {'sha256': 'd'*64, 'nbytes': 140}})

    # F: a standalone exact integer with exactly 64 hex digits is taken for a 64-hex identity
    v = 0x40 << 248 | 12345
    assert len(hex(v)) == 66 and len(hex(v + (v >> 1))) == 66
    pair('F_hexint_64_digits_grows_50pct', {'certification': canon({'residual_numerator': hex(v)})},
         {'certification': canon({'residual_numerator': hex(v + (v >> 1))})},
         'REVIEW (an exact integer changed by 50%)')

    # J: equality shortcut hides type changes (bool -> int, int -> float, 0.0 -> -0.0)
    pair('J_type_changes_hidden', {'certification': canon({'converged': True, 'count': 7, 'offset_m': 0.0})},
         {'certification': canon({'converged': 1, 'count': 7.0, 'offset_m': -0.0})},
         'REVIEW (three JSON type/sign changes)')

    # K: an array element overflowing max_abs to inf: the verdict file cannot be written (allow_nan=False)
    pair('K_array_inf_max_abs', {'state': SMALL_STATE}, {'state': SMALL_STATE}, 'a complete verdict file',
         kb={'arrays1': [('flux_f64', np.array([1e308, 1.0]))]}, ka={'arrays1': [('flux_f64', np.array([-1e308, 1.0]))]})


def run(plan, out):
    results = []
    for name, (attempt_b, dumps_b), (attempt_a, dumps_a), expect, detail in plan:
        verdict_path = out/name/'verdict.json'
        args = [sys.executable, '-B', '-I', COMPARE, '--before', str(attempt_b), str(dumps_b), PROFILE,
                '--after', str(attempt_a), str(dumps_a), PROFILE, '--out', str(verdict_path)]
        done = subprocess.run(args, capture_output=True, text=True)
        try:
            verdict = json.loads(verdict_path.read_bytes())
            status = verdict['status']
        except Exception as error:  # noqa: BLE001
            verdict, status = {}, 'NO VALID VERDICT (%s)' % type(error).__name__
        mesh = (verdict.get('records') or {}).get('i0/mesh') or {}
        line = {'case': name, 'got': status, 'exit': done.returncode, 'expected': expect, 'detail': detail,
                'fail': verdict.get('fail', [])[:2], 'review': verdict.get('review', [])[:3],
                'counts': mesh.get('counts'), 'stderr_tail': done.stderr[-300:]}
        results.append(line)
        print('%-34s got %-8s exit %s  expected %s' % (name, status, done.returncode, expect), flush=True)
        if line['review'] or line['fail']:
            print('    ', (line['fail'] or line['review'])[:2], flush=True)
        if detail:
            print('    planted:', json.dumps(detail)[:300], flush=True)
        if mesh.get('counts'):
            print('    i0/mesh counts:', mesh['counts'], flush=True)
        if status.startswith('NO VALID'):
            print('    stderr:', done.stderr.strip().splitlines()[-1:], flush=True)
    return results


def same_arm_case(out, plan):
    """G: the before arm passed as both arms (an argument slip): nothing refuses it."""
    case = case_dirs(out, 'G_same_arm_twice')
    arm = build_arm(case/'x', 'G', {'state': SMALL_STATE}, {'state': SMALL_STATE})
    plan.append(('G_same_arm_twice', arm, arm, 'refusal (before and after are the same attempt)', None))


if __name__ == '__main__':
    real_dir, COMPARE, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    out.mkdir()
    plan = []
    synthetic_cases(out, plan)
    same_arm_case(out, plan)
    real_mesh_cases(out, real_dir, plan)
    results = run(plan, out)
    summary = {'compare_sha256': sha(Path(COMPARE).read_bytes()), 'self_sha256': sha(Path(__file__).read_bytes()),
               'results': results}
    (out/'summary.json').write_text(json.dumps(summary, indent=1, default=str), encoding='utf8')
