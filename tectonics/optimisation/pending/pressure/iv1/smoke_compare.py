"""Smoke for compare_arms.py: fixture arms built from one real interval-0 dump, planted cases, expected verdicts.

Usage: smoke_compare.py REAL_DUMP_DIR REAL_STAGE_ROOT_JSON NEW_OUT_DIR
Each case builds a before and an after arm (attempt with stage records, dumps i0 and i1), applies its planted
change, runs compare_arms.py as the ticket job would (a separate -B -I process) and checks the verdict status
and, for some cases, the reported field. i0 holds the real mesh and state records and arrays (hard links where
unchanged); i1 is synthetic (the real state record, a small certification record and two arrays) and its stage
record is a fixture. Exit 0 only if every case gives its expected verdict. Never imports the runtime.
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
COMPARE = HERE/'compare_arms.py'
FAKE = {'reader': '1'*64, 'finalise': '2'*64, 'adopt': '3'*64}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def enc(q):
    q = Fraction(q)
    return [hex(q.numerator), hex(q.denominator)]


def dec(r):
    return Fraction(int(r[0], 16), int(r[1], 16))


def dumps(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True).encode()


class Arm:
    """In-memory fixture of one arm; write() lays it out on disk."""

    def __init__(self, real, stage_root):
        self.dump0 = copy.deepcopy(real['dump'])
        self.stage_root = copy.deepcopy(stage_root)
        self.records0 = {}            # name -> object (mutated) or None (hard link of the real file)
        self.real = real
        self.state1 = None
        self.cert = copy.deepcopy(real['cert'])
        self.f64 = np.linspace(-3.0, 7.0, 64)
        self.i64 = np.arange(32, dtype=np.int64)
        self.stage_interval = {'status': 'ADOPTED', 'width_gate_passed': True, 'steps': [
            {'name': 'runner', 'ok': True, 'receipt_sha256': '0'*64},
            {'name': 'reader', 'ok': True, 'receipt_sha256': FAKE['reader']},
            {'name': 'finalise', 'ok': True, 'verdict_sha256': FAKE['finalise']},
            {'name': 'adopt', 'ok': True, 'adopted_sha256': FAKE['adopt']}]}
        self.gate1 = {'schema': 'atlas.exact-width-gate.v1', 'passed': True, 'rows': []}
        self.extra = []               # (relative path, bytes) written under the attempt
        self.no_stage_interval = False
        self.pretty = False           # write mutated records indented (new bytes, same content)
        self.post = []                # callables(arm_dir) run after writing (tamper, unbinding)

    def record(self, name):
        if self.records0.get(name) is None:
            self.records0[name] = json.loads((self.real['dir']/'records'/(name+'.json')).read_bytes())
        return self.records0[name]

    def state_i1(self):
        if self.state1 is None:
            self.state1 = json.loads((self.real['dir']/'records'/'state.json').read_bytes())
        return self.state1

    def write(self, root, profile_sha):
        attempt, dumps_dir = root/'attempt', root/'dumps'
        for d in (attempt/'reader-root', attempt/'reader-interval', attempt/'run-interval', dumps_dir/'i0'/'records',
                  dumps_dir/'i0'/'arrays', dumps_dir/'i1'/'records', dumps_dir/'i1'/'arrays'):
            d.mkdir(parents=True)
        (attempt/'stage-root.json').write_bytes(dumps(self.stage_root))
        if not self.no_stage_interval:
            (attempt/'stage-interval.json').write_bytes(dumps(self.stage_interval))
        for rel, data in self.extra:
            (attempt/rel).write_bytes(data)
        # i0: the real dump, paths moved under this attempt
        d0 = self.dump0
        d0['profile']['sha256'] = profile_sha
        for key, sub in (('reader_receipt', 'reader-root/reopen.json'), ('verdict', 'verdict-0.json'),
                         ('adopted', 'adopted-0.json'), ('runner_record', 'runner-0.json')):
            d0['bindings'][key]['path'] = str(attempt/sub)
        for name in d0['records']:
            target = dumps_dir/'i0'/'records'/(name+'.json')
            if self.records0.get(name) is None:
                os.link(self.real['dir']/'records'/(name+'.json'), target)
            else:
                value = self.records0[name]
                data = json.dumps(value, indent=1, sort_keys=True).encode() if self.pretty else dumps(value)
                target.write_bytes(data)
                d0['records'][name] = {'nbytes': len(data), 'sha256': sha(data)}
        for array in d0['arrays']:
            os.link(self.real['dir']/'arrays'/array['file'], dumps_dir/'i0'/'arrays'/array['file'])
        (dumps_dir/'i0'/'dump.json').write_bytes(dumps(d0))
        # i1: synthetic
        d1 = copy.deepcopy(d0)
        d1.update(interval=1, width_gate=self.gate1, records={}, arrays=[])
        d1['widths'] = copy.deepcopy(d0['widths'])
        d1['widths']['interval'] = 1
        for key, sub, fake in (('reader_receipt', 'reader-interval/reopen.json', 'reader'),
                               ('verdict', 'verdict-1.json', 'finalise'), ('adopted', 'adopted-1.json', 'adopt')):
            d1['bindings'][key] = {'path': str(attempt/sub), 'sha256': FAKE[fake]}
        if self.state1 is None:
            os.link(self.real['dir']/'records'/'state.json', dumps_dir/'i1'/'records'/'state.json')
            d1['records']['state'] = d0['records']['state'] if self.records0.get('state') is None else \
                self.real['dump']['records']['state']
        else:
            data = dumps(self.state1)
            (dumps_dir/'i1'/'records'/'state.json').write_bytes(data)
            d1['records']['state'] = {'nbytes': len(data), 'sha256': sha(data)}
        data = dumps(self.cert)
        (dumps_dir/'i1'/'records'/'certification.json').write_bytes(data)
        d1['records']['certification'] = {'nbytes': len(data), 'sha256': sha(data)}
        for i, (name, values) in enumerate((('residual_f64', self.f64), ('count_i64', self.i64))):
            raw = values.tobytes()
            (dumps_dir/'i1'/'arrays'/('%04d.bin' % i)).write_bytes(raw)
            d1['arrays'].append({'name': name, 'file': '%04d.bin' % i, 'dtype': values.dtype.str,
                                 'shape': list(values.shape), 'nbytes': len(raw), 'sha256': sha(raw)})
        (dumps_dir/'i1'/'dump.json').write_bytes(dumps(d1))
        for step in self.post:
            step(root)
        return attempt, dumps_dir


# ---- planted changes (after arm unless stated)
def cell0(arm):
    return arm.record('mesh')['cells'][0]


def shift_volume(factor):
    def change(before, after):
        c = cell0(after)
        c['volume_m3'] = enc(dec(c['volume_m3'])+factor*dec(c['geometry_volume_max_deviation_m3']))
    return change


def scale_field(key, factor):
    def change(before, after):
        c = cell0(after)
        c[key] = enc(dec(c[key])*(1+factor))
    return change


def scale_centroid(factor):
    def change(before, after):
        c = cell0(after)
        c['centroid_m'][0] = enc(dec(c['centroid_m'][0])*(1+factor))
    return change


def stock_lineage(arm):
    return arm.record('state')['finite_stock_state']['stocks'][0]['lineage']


def float_ulps(n):
    def change(before, after):
        column = stock_lineage(after)['birth_column']
        bits = np.array([column['base_temperature_k']], dtype=np.float64).view(np.int64)+n
        column['base_temperature_k'] = float(bits.view(np.float64)[0])
    return change


def flip_bool(before, after):
    lin = stock_lineage(after)
    lin['scalar_heat_roundoff_owner'] = not lin['scalar_heat_roundoff_owner']


def drop_key(before, after):
    del cell0(after)['source_key']


def rewritten_equal(before, after):
    after.record('mesh')        # same content written back indented: new bytes, nothing changed
    after.pretty = True


def shuffle_rehash(before, after):
    mesh, state = after.record('mesh'), after.record('state')
    new = {c['cell_id']: sha(c['cell_id'].encode()) for c in mesh['cells']}
    for c in mesh['cells']:
        c['cell_id'] = new[c['cell_id']]
    mesh['cells'].reverse()
    for c in state['cells']:
        c['cell_id'] = new.get(c['cell_id'], c['cell_id'])
    state['cells'].reverse()
    after.cert['by_cell'] = {new.get(k, k): v for k, v in after.cert['by_cell'].items()}
    ref = after.cert['record_ref'].split(':')
    after.cert['record_ref'] = ref[0]+':'+new.get(ref[1], ref[1])
    after.state1 = copy.deepcopy(state)


def stage_interval(arm, **values):
    arm.stage_interval.update(values)


def flip_interval(before, after):
    stage_interval(after, status='FAILED', failed_step='runner', reason='planted refusal', width_gate_passed=None)


def flip_root(before, after):
    after.stage_root.update(status='FAILED', failed_step='runner', reason='planted refusal')


def gate_stop(before, after):
    stage_interval(after, status='ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2', width_gate_passed=False)
    after.gate1['passed'] = False


def gate_disagree(before, after):
    after.gate1['passed'] = False


def before_gate_stop(before, after):
    stage_interval(before, status='ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2', width_gate_passed=False)
    before.gate1['passed'] = False


def guard_abort(before, after):
    stage_interval(after, status='FAILED', failed_step='runner', reason='guarded runner did not seal cleanly')
    after.extra.append(('run-interval/run.guard-abort.json', b'{"reason": "planted free-memory floor"}'))


def both_refused(before, after):
    flip_interval(before, after)
    stage_interval(before, status='FAILED', failed_step='runner', reason='planted refusal')


def missing_stage(before, after):
    after.no_stage_interval = True


def tamper(before, after):
    def step(root):
        with open(root/'dumps'/'i0'/'records'/'mesh.json', 'ab') as stream:
            stream.write(b' ')
    after.record('mesh')
    after.post.append(step)


def unbind(before, after):
    def step(root):
        path = root/'dumps'/'i1'/'dump.json'
        d = json.loads(path.read_bytes())
        d['bindings']['verdict']['sha256'] = '4'*64
        path.write_bytes(dumps(d))
    after.post.append(step)


def array_ulps(n):
    def change(before, after):
        after.f64 = after.f64.copy()
        after.f64[5:6] = (after.f64[5:6].view(np.int64)+n).view(np.float64)
    return change


def array_int(before, after):
    after.i64 = after.i64.copy()
    after.i64[3] += 1


def weak_change(before, after):
    r = after.cert['iterations'][0]
    r['residual'] = enc(dec(r['residual'])*3)


def refstring_id(before, after):
    after.cert['record_ref'] = 'spatial-record:'+'9'*64


def label_change(before, after):
    after.cert['kind'] = 'other'


def int_change(before, after):
    after.cert['count'] += 1


def stats_fail(before, after):
    s = after.cert['stats']
    s['value_m3'] = enc(dec(s['value_m3'])+2*dec(s['residual_error_m3']))


def field(verdict, where, name):
    return verdict['records'][where]['fields'].get(name, {})


def ratio_near(where, name, log2):
    def check(v):
        r = field(v, where, name).get('max_ratio')
        return r is not None and 2**(log2-0.1) <= r <= 2**(log2+0.1), r
    return check


CASES = (
    # name, change(before, after), expected status, optional check(verdict) -> (ok, detail), options
    ('identical', None, 'PASS', None, {}),
    ('rewritten_equal', rewritten_equal, 'PASS',
     lambda v: (not v['records']['i0/mesh']['bytes_equal'] and not v['records']['i0/mesh']['fields'] and
                not any(v['records']['i0/mesh']['counts'].values()), v['records']['i0/mesh'].get('counts')), {}),
    ('vol_fail', shift_volume(2), 'FAIL', ratio_near('i0/mesh', 'mesh.cells.[].volume_m3', 1), {}),
    ('vol_review', shift_volume(Fraction(1, 256)), 'REVIEW', ratio_near('i0/mesh', 'mesh.cells.[].volume_m3', -8), {}),
    ('vol_pass', shift_volume(Fraction(1, 2**14)), 'PASS', ratio_near('i0/mesh', 'mesh.cells.[].volume_m3', -14), {}),
    ('dev_rel_review', scale_field('geometry_volume_max_deviation_m3', Fraction(1, 2**9)), 'REVIEW', None, {}),
    ('dev_rel_pass', scale_field('geometry_volume_max_deviation_m3', Fraction(1, 2**13)), 'PASS', None, {}),
    ('centroid_rel_review', scale_centroid(Fraction(1, 2**15)), 'REVIEW', None, {}),
    ('centroid_rel_pass', scale_centroid(Fraction(1, 2**25)), 'PASS', None, {}),
    ('float_1ulp', float_ulps(1), 'PASS', None, {}),
    ('float_1000ulps', float_ulps(1000), 'REVIEW', None, {}),
    ('bool_flip', flip_bool, 'REVIEW', None, {}),
    ('key_removed', drop_key, 'REVIEW', None, {}),
    ('shuffle_rehash', shuffle_rehash, 'PASS',
     lambda v: (v['records']['i0/mesh']['counts']['identity_changes'] > 0 and v['identity_translations'] > 0,
                v['records']['i0/mesh']['counts']), {}),
    ('root_flip', flip_root, 'FAIL', None, {}),
    ('interval_flip', flip_interval, 'FAIL', None, {}),
    ('after_gate_stop', gate_stop, 'FAIL', None, {}),
    ('gate_disagree', gate_disagree, 'FAIL', None, {}),
    ('before_gate_stop', before_gate_stop, 'PASS',
     lambda v: (v['width_gate']['before']['passed'] is False and v['width_gate']['after']['passed'] is True,
                v.get('info')), {}),
    ('guard_abort', guard_abort, 'VOID', None, {}),
    ('both_refused', both_refused, 'VOID', None, {}),
    ('missing_stage', missing_stage, 'VOID', None, {}),
    ('tamper', tamper, 'FAIL', None, {}),
    ('unbound_dump', unbind, 'FAIL', None, {}),
    ('wrong_profile', None, 'FAIL', None, {'after_profile': 'f'*64}),
    ('array_1ulp', array_ulps(1), 'PASS', lambda v: (v['arrays']['i1']['residual_f64']['max_ulps'] == 1,
                                                     v['arrays']['i1']['residual_f64']), {}),
    ('array_1000ulps', array_ulps(1000), 'REVIEW', None, {}),
    ('array_int', array_int, 'REVIEW', None, {}),
    ('weak_change', weak_change, 'REVIEW', None, {}),
    ('refstring_id', refstring_id, 'PASS', None, {}),
    ('label_change', label_change, 'REVIEW', None, {}),
    ('int_change', int_change, 'REVIEW', None, {}),
    ('stats_fail', stats_fail, 'FAIL', ratio_near('i1/certification', 'certification.stats.value_m3', 1), {}),
)


def main():
    real_dir, stage_root_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir()
    dump = json.loads((real_dir/'dump.json').read_bytes())
    stage_root = json.loads(stage_root_path.read_bytes())
    mesh = json.loads((real_dir/'records'/'mesh.json').read_bytes())
    ids = [c['cell_id'] for c in mesh['cells'][:5]]
    del mesh
    cert = {'kind': 'proposal', 'count': 7, 'converged': True, 'record_ref': 'spatial-record:'+ids[0],
            'by_cell': {k: enc(Fraction(i+1, 3)) for i, k in enumerate(ids)},
            'iterations': [{'step': 'a', 'residual': enc(Fraction(1, 7))},
                           {'step': 'a', 'residual': enc(Fraction(2, 7))}],
            'stats': {'value_m3': enc(Fraction(1000, 3)), 'residual_error_m3': enc(Fraction(1, 9))}}
    real = {'dir': real_dir, 'dump': dump, 'cert': cert}
    profile = dump['profile']['sha256']
    results, python = [], sys.executable
    for name, change, expected, check, options in CASES:
        before, after = Arm(real, stage_root), Arm(real, stage_root)
        if change is not None:
            change(before, after)
        case = out/name
        pb = before.write(case/'b', profile)
        pa = after.write(case/'a', profile)
        verdict_path = case/'verdict.json'
        argv = [python, '-B', '-I', str(COMPARE), '--before', str(pb[0]), str(pb[1]), profile,
                '--after', str(pa[0]), str(pa[1]), options.get('after_profile', profile), '--out', str(verdict_path)]
        done = subprocess.run(argv, capture_output=True, text=True)
        verdict = json.loads(verdict_path.read_bytes()) if verdict_path.is_file() else {'status': 'NO VERDICT'}
        ok = verdict['status'] == expected
        detail = None
        if ok and check is not None:
            try:
                ok, detail = check(verdict)
            except Exception as error:  # noqa: BLE001 - a failed check is reported, never passed
                ok, detail = False, repr(error)
        line = {'case': name, 'expected': expected, 'got': verdict['status'], 'ok': bool(ok), 'exit': done.returncode,
                'fail': verdict.get('fail', [])[:2], 'void': verdict.get('void', [])[:1],
                'review': verdict.get('review', [])[:2], 'detail': detail}
        results.append(line)
        first = (line['fail'] or line['void'] or line['review'] or [''])[0][:110]
        mark = 'ok' if ok else 'WRONG'
        print('%-20s expected %-6s got %-6s %s %s' % (name, expected, verdict['status'], mark, first),
              flush=True)
    for name, identity in dump['records'].items():       # the real dump must be untouched (hard links)
        data = (real_dir/'records'/(name+'.json')).read_bytes()
        if sha(data) != identity['sha256']:
            results.append({'case': 'real dump unchanged: '+name, 'ok': False})
    for array in dump['arrays']:
        if sha((real_dir/'arrays'/array['file']).read_bytes()) != array['sha256']:
            results.append({'case': 'real dump unchanged: '+array['file'], 'ok': False})
    wrong = [r['case'] for r in results if not r['ok']]
    summary = {'schema': 'atlas.private.iv1-compare-smoke.r1', 'compare_sha256': sha(COMPARE.read_bytes()),
               'smoke_sha256': sha(Path(__file__).read_bytes()), 'cases': len(results), 'wrong': wrong,
               'results': results}
    (out/'smoke.json').write_text(json.dumps(summary, indent=1, default=str), encoding='utf8')
    print('COMPARE SMOKE %s: %d cases, %d wrong %s' % ('PASS' if not wrong else 'FAIL', len(results), len(wrong),
                                                        wrong or ''))
    return 1 if wrong else 0


if __name__ == '__main__':
    sys.exit(main())
