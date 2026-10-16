"""Planted mutants for summarise_s9_w4.py: the clean fixture must PASS and every mutant must FAIL.

Usage: python -B mutants_summary.py WORKDIR     (WORKDIR must not exist)

Fixture: Runner's genuine control output L/arr-r2.json (read-only), with its frozen_check set to the
passing shape and its arrays set to the reference's, copied as arms 1-base 2-cand 3-cand 4-base; fake
layouts base/ and cand/ whose helpers hold the real base runtime (composed-r2) and the S9 candidate.
"""
import copy
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
REF = R/'probes/step8/claude-20261015/g13-same-call-live1.json'
HERE = Path(__file__).resolve().parent
RUNTIME = 'private_heat_indexed_runtime.py'
ARMS = ['base', 'cand', 'cand', 'base']


def build(root, mutate=None):
    w4, out = root/'w4', root/'out'
    raw = {'base': (R/'composed-r2/helpers'/RUNTIME).read_bytes(), 'cand': (HERE.parent/RUNTIME).read_bytes()}
    (w4/'cand-src').mkdir(parents=True)
    (w4/'cand-src'/RUNTIME).write_bytes(raw['cand'])
    other = b'# another helper\n'
    for name in ('base', 'cand'):
        (w4/name/'helpers').mkdir(parents=True)
        (w4/name/'helpers'/RUNTIME).write_bytes(raw[name])
        source = (w4/'cand-src'/RUNTIME) if name == 'cand' else (R/'composed-r2/helpers'/RUNTIME)
        info = {'copied_helpers': {RUNTIME: {'source': str(source), 'sha256': sha256(raw[name]).hexdigest()},
                                   'other.py': {'source': 'x', 'sha256': sha256(other).hexdigest()}}}
        (w4/name/'control.json').write_text(json.dumps(info), encoding='utf8')
    fixture = json.loads((R/'L/arr-r2.json').read_text(encoding='utf8'))
    fixture['arrays'] = json.loads(REF.read_text(encoding='utf8'))['arrays']
    fixture['frozen_check'].update(status='PASS', loaded_outside_frozen=[], differences_from_reference=[])
    out.mkdir()
    arms = {}
    for k, arm in enumerate(ARMS, 1):
        arms[(k, arm)] = [copy.deepcopy(fixture), {'status': 'PASS'}]
    if mutate:
        mutate(arms, w4)
    for (k, arm), (result, saved) in arms.items():
        if result is not None:
            (out/('%d-%s.json' % (k, arm))).write_text(json.dumps(result), encoding='utf8')
        (out/('%d-%s' % (k, arm))).mkdir()
        if saved is not None:
            (out/('%d-%s' % (k, arm))/'frozen_check.json').write_text(json.dumps(saved), encoding='utf8')
    return w4, out


def control(w4, name, change):
    path = w4/name/'control.json'
    info = json.loads(path.read_text(encoding='utf8'))
    change(info['copied_helpers'])
    path.write_text(json.dumps(info), encoding='utf8')


MUTANTS = {
    'clean': None,
    'arm3_control_fail': lambda a, w: a[(3, 'cand')][0].update(status='DIFFERS'),
    'arm2_json_missing': lambda a, w: a[(2, 'cand')].__setitem__(0, None),
    'arm1_save_missing': lambda a, w: a[(1, 'base')].__setitem__(1, None),
    'arm4_save_fail': lambda a, w: a[(4, 'base')][1].update(status='FAIL'),
    'arm2_frozen_fail': lambda a, w: a[(2, 'cand')][0]['frozen_check'].update(status='FAIL'),
    'arm3_leak': lambda a, w: a[(3, 'cand')][0]['frozen_check'].update(loaded_outside_frozen=['x.py']),
    'arm1_reference_difference': lambda a, w: a[(1, 'base')][0]['frozen_check'].update(
        differences_from_reference=['arrays']),
    'arm4_array_digest': lambda a, w: a[(4, 'base')][0]['arrays'].update(
        {sorted(a[(4, 'base')][0]['arrays'])[0]: '0'*64}),
    'arm2_compact_seconds_missing': lambda a, w: a[(2, 'cand')][0]['compact'].pop('seconds'),
    'arm3_elapsed_none': lambda a, w: a[(3, 'cand')][0].update(elapsed_seconds=None),
    'arm1_metadata_length': lambda a, w: a[(1, 'base')][0]['legacy'].update(
        metadata_bytes=a[(1, 'base')][0]['legacy']['metadata_bytes']+1),
    'arm4_cell_count': lambda a, w: a[(4, 'base')][0].update(cell_count=a[(4, 'base')][0]['cell_count']+1),
    'cand_layout_is_base': lambda a, w: (
        (w/'cand'/'helpers'/RUNTIME).write_bytes((w/'base'/'helpers'/RUNTIME).read_bytes()),
        control(w, 'cand', lambda c: c[RUNTIME].update(sha256=c[RUNTIME]['sha256'].replace('ec170fc4', 'deadbeef', 1)))),
    'layouts_differ_elsewhere': lambda a, w: control(w, 'cand', lambda c: c['other.py'].update(sha256='1'*64)),
    'cand_source_elsewhere': lambda a, w: control(w, 'cand', lambda c: c[RUNTIME].update(source='C:/elsewhere/'+RUNTIME)),
    'cand_disk_differs': lambda a, w: (w/'cand'/'helpers'/RUNTIME).write_bytes(b'changed'),
}


def main(workdir):
    workdir = Path(workdir)
    if workdir.exists():
        raise SystemExit('exists: %s' % workdir)
    failures = []
    for name, mutate in MUTANTS.items():
        root = workdir/name
        w4, out = build(root, mutate)
        done = subprocess.run([sys.executable, '-B', str(HERE/'summarise_s9_w4.py'), str(out), str(w4), str(REF), *ARMS],
                              capture_output=True, text=True)
        expected = 0 if mutate is None else 1
        verdict = 'ok' if done.returncode == expected else 'WRONG'
        last = [line for line in done.stdout.splitlines() if 'FAIL:' in line or line.startswith('STATUS')][:2]
        print('%-30s exit %d expected %d %s %s' % (name, done.returncode, expected, verdict, ' | '.join(last))[:220])
        if done.stderr.strip():
            print('   stderr:', done.stderr.strip().splitlines()[-1][:200])
        if verdict != 'ok':
            failures.append(name)
    print('MUTANTS', 'ALL OK' if not failures else 'WRONG: %s' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
