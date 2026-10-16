"""Mutant proof of surfaces_stage_check.py and run_jets_parity.sh's exit capture (small lane, no runtime).

Usage: python -B -I surfaces_stage_check_proof.py WORK
WORK must not exist. Adapted from Exact kernels' q11 gpy_parity_proof.py (T/ck/scripts, 16 Oct).
Checker cases: a synthetic OUT built from real IV1 surface shards (evidence/jets-r1/iv1-surfaces-base-s0/s1,
read-only; first 1,500 data rows of each plus its done row, queries set to match): base = those rows;
jets = the same rows with the done row's runtime and package digest of the jets arm, as a real jets arm
would write them. The real pair and a digest-only change must PASS; every planted defect must FAIL.
Harness cases: run_jets_parity.sh's own waitall() records each shard's exit code (0, 3, 124) in its
.exit file. The rest run a copy of the harness whose only changes are its G= and PY= lines (a fake
tree and a stub interpreter, so nothing real can start): it refuses an existing folder, bad names
(trailing dot included) and missing inputs before launching anything, and its exit status follows
the stage checks (a failing check in any stage makes it exit 1 after all stages ran).
Refuter 16 Oct additions: empty shard in both arms, the pinned row count, one-sided caps, an error
behind a base cap, compare_surfaces sha mismatch, and the whole-harness exit cases. Round 2 (P3):
the CAPS rule (none refuses any cap; list: accepts only listed interface queries; a bad rule or list
fails), the pinned capped lists (edited, truncated, extended or swapped lists are refused; the fake
tree holds copies of the real ones), the Windows-only existence probe, and each stage's exact row
count and cap rule in the stub's record of the check calls. Round 3: the exactly: rule on
interface-only shards (the right number of wrong rows, a duplicate, a wall row, a list extra or
repeat, a cap, an empty or missing list all FAIL; rule none passing the same replaced rows is the
control that shows exactly: is what catches them); the sample and deep checks and every deep replay
read the hashed copies in OUT/inputs; a cp shim that edits a copy makes the harness refuse.
Writes WORK/proof.json; exit 0 only if every case is as expected.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
SRC = HERE.parent/'evidence'/'jets-r1'
CHECK = HERE/'surfaces_stage_check.py'
HARNESS = HERE/'run_jets_parity.sh'
BASH = 'C:/Program Files/Git/usr/bin/bash.exe'
STAGE, IDS, N = 'iv1-surfaces', (0, 1), 1500
BASE_RT, CAND_RT = 'rc1', 'test:%s/gg/jets-r1' % T.as_posix()
WORK = Path(sys.argv[1])
results = {}


def real(i):
    rows, done = [], None
    for line in open(SRC/('iv1-surfaces-base-s%d.jsonl' % i), encoding='utf8'):
        r = json.loads(line)
        if r.get('done'):
            done = r
        elif 'job_counts' not in r and len(rows) < N:
            rows.append(r)
    assert done is not None and len(rows) == N and done['runtime'] == BASE_RT
    return rows, dict(done, queries=N)


REAL = {i: real(i) for i in IDS}


def arms():
    """{(arm, i): [rows..., done]} for the clean pair (deep copies)."""
    data = {}
    for i in IDS:
        rows, done = REAL[i]
        data['base', i] = [dict(r) for r in rows] + [dict(done)]
        data['jets', i] = [dict(r) for r in rows] + [dict(done, runtime=CAND_RT, package_digest='c'*64)]
    return data


def write(out, data, exits):
    out.mkdir(parents=True)
    for (arm, i), lines in data.items():
        p = out/('%s-%s-s%d.jsonl' % (STAGE, arm, i))
        p.write_text(''.join(line if isinstance(line, str) else json.dumps(line)+'\n' for line in lines),
                     encoding='utf8')
        if exits.get((arm, i), '0') is not None:
            p.with_suffix('.exit').write_text(exits.get((arm, i), '0')+'\n', encoding='utf8')


def record(name, code, want_pass, tail):
    ok = (code == 0) == want_pass
    results[name] = dict(exit=code, want='PASS' if want_pass else 'FAIL', ok=ok, tail=tail)
    print('%-44s exit %d  %s  %s' % (name, code, 'as expected' if ok else 'WRONG', tail[:150]))


def case(name, want_pass, mutate=None, exits=None, shards=None, arm_names=('base', 'jets'), expect=None,
         check=CHECK, caps='none'):
    data = arms()
    if mutate:
        mutate(data)
    out = WORK/('c%02d' % (len(results)+1))   # short: long case names passed MAX_PATH under scratch
    write(out, data, exits or {})
    run = subprocess.run([sys.executable, '-B', '-I', str(check), str(out), STAGE,
                          ','.join(map(str, IDS)) if shards is None else shards,
                          arm_names[0], BASE_RT, arm_names[1], CAND_RT,
                          str(N*len(IDS)) if expect is None else expect, caps],
                         capture_output=True, text=True)
    record(name, run.returncode, want_pass, (run.stdout+run.stderr).strip()[-220:])


def first(kind, start=900):
    """Index (in shard 0's rows) of the first row of this kind at or after start."""
    return next(k for k, r in enumerate(REAL[0][0]) if k >= start and r['kind'] == kind)


IFACE, IFACE2, WALL = first('interface'), first('interface', first('interface')+1), first('wall')


def cap_list(name, *ks):
    """A capped-list file (the deep stage's input format) listing shard 0's rows ks; returns 'list:<path>'."""
    p = WORK/name
    p.write_text(''.join(json.dumps({f: REAL[0][0][k].get(f) for f in ('support_index', 'cell', 'other', 'constraint_name')})
                         + '\n' for k in ks), encoding='utf8')
    return 'list:' + str(p)


LIST_FIELDS = ('support_index', 'cell', 'other', 'constraint_name')
IF_ROWS = {i: [k for k, r in enumerate(REAL[i][0]) if r['kind'] == 'interface'][:20] for i in IDS}
N_IF = sum(map(len, IF_ROWS.values()))
IF = [REAL[i][0][k] for i in IDS for k in IF_ROWS[i]]
IF_SPARE = next(r for k, r in enumerate(REAL[0][0]) if r['kind'] == 'interface' and k > IF_ROWS[0][-1])


def iface_only(*then):
    """Keep only IF_ROWS in every shard (the deep stage runs interface queries only), then apply each
    of `then` to every shard's lines of both arms."""
    def m(data):
        for (arm, i), lines in list(data.items()):
            data[arm, i] = [lines[k] for k in IF_ROWS[i]] + [dict(lines[-1], queries=len(IF_ROWS[i]))]
            for fn in then:
                fn(data[arm, i])
    return m


def exact_list(name, rows):
    """'exactly:<path>' of a capped-list file listing these rows' queries."""
    p = WORK/name
    p.write_text(''.join(json.dumps({f: r.get(f) for f in LIST_FIELDS}) + '\n' for r in rows), encoding='utf8')
    return 'exactly:' + str(p)


def empty_both(data):
    for arm in ('base', 'jets'):
        data[arm, 1] = [dict(data[arm, 1][-1], queries=0)]


def pair_status(base, cand, k=IFACE):
    def m(data):
        data['base', 0][k]['status'] = base
        data['jets', 0][k]['status'] = cand
    return m


def shadow_compare():
    """Checker beside a compare_surfaces.py that differs by one trailing comment."""
    d = WORK/'shadow'
    d.mkdir()
    shutil.copy(CHECK, d/CHECK.name)
    (d/'compare_surfaces.py').write_bytes((HERE/'compare_surfaces.py').read_bytes() + b'\n# changed\n')
    return d/CHECK.name


def drop(*keys):
    def m(data):
        for k in keys:
            del data[k]
    return m


def row_edit(fn, arm='jets', i=1, k=700):
    def m(data):
        fn(data[arm, i], k)
    return m


def set_field(field, value):
    return lambda lines, k: lines[k].update({field: value})


def remove_row(lines, k):
    del lines[k]
    lines[-1]['queries'] -= 1


def extra_row(lines, k):
    r = dict(lines[k], cell='ffffffffffffffff')
    lines.insert(k, r)
    lines[-1]['queries'] += 1


def dup_row(lines, k):
    lines.insert(k, dict(lines[k]))
    lines[-1]['queries'] += 1


def digest_only(data):
    for i in IDS:
        for r in data['jets', i][:100]:
            r['measure_sha'] = 'f'*16 if r['measure_sha'] != 'f'*16 else 'e'*16


def all_capped(data):
    for lines in data.values():
        for r in lines[:-1]:
            r['status'] = 'capped'


def harness_waitall():
    """run_jets_parity.sh's own waitall(), cut from the script, on three fake shards."""
    text = HARNESS.read_text(encoding='utf8')
    body = re.search(r'^waitall \(\) \{.*?^\}$', text, re.S | re.M)
    out = WORK/'waitall'
    out.mkdir()
    if body is None:
        record('harness: waitall() found', 1, True, 'waitall() not found in the harness')
        return
    script = (body.group(0) + '\nOUT="%s"\n' % out.as_posix() +
              '(exit 0) & a=$!; (exit 3) & b=$!; (sleep 1; exit 124) & c=$!\n'
              'waitall st "$c" 5 "$a" 0 "$b" 2\n')
    run = subprocess.run([BASH, '-c', script], capture_output=True, text=True)
    got = {i: (out/('st-s%d.exit' % i)).read_text().strip() if (out/('st-s%d.exit' % i)).is_file() else None
           for i in (0, 2, 5)}
    ok = run.returncode == 0 and got == {0: '0', 2: '3', 5: '124'}
    record('harness: waitall keeps each shard exit', 0 if ok else 1, True, 'exit %d got %s' % (run.returncode, got))


STUB = b'''#!/usr/bin/env bash
# Stub interpreter: a stage check exits 1 for the stage named in STUB_FAIL_STAGE, everything else 0;
# the harness's Windows existence probe (-c) answers "exists" when STUB_LEXISTS is non-empty.
case "$3" in
  surfaces_stage_check.py) echo "STUB-CHECK $5 expect ${11} caps ${12}"; [ "$5" = "${STUB_FAIL_STAGE:-none}" ] && exit 1; exit 0;;
  -c) [ -n "${STUB_LEXISTS:-}" ] && exit 1; exit 0;;
esac
[ "$2" = replay_surfaces.py ] && echo "STUB-REPLAY $*"
exit 0
'''
CP_SHIM = b'''#!/usr/bin/env bash
# PATH shim: the real cp, then a line appended to a copied capped-list-5 (an edit between copy and use).
/usr/bin/cp "$@" || exit $?
for last; do :; done
[ -f "$last/capped-list-5.jsonl" ] && echo '{}' >> "$last/capped-list-5.jsonl"
exit 0
'''
REAL_F = HERE.parent/'evidence'/'final-f1'
INPUTS = ('work/iv1-supports.jsonl.gz', 'work/next-iv1-rc1-r1.json.gz', 'work/iv1-interval-r1.json.gz',
          'work/iv2-interval-only-r1.json.gz', 'evidence/final-f1/iv2-supports.jsonl.gz',
          'evidence/final-f1/iv2-partition.json.gz', 'evidence/final-f1/ref-iv2-surfaces-s0.jsonl',
          'evidence/final-f1/ref-iv2-surfaces-s1.jsonl') + tuple(
          'evidence/final-f1/capped-list-%d.jsonl' % i for i in range(6))


def fake_harness(tag, drop=(), tamper=None):
    """The harness with only its G= and PY= lines changed, on a fake tree holding non-empty inputs
    (minus `drop`; the capped lists are copies of the real, pinned ones, then `tamper` may edit them),
    an existing jets-r1 and a scripts folder."""
    root = WORK/tag
    g = root/'g'
    (g/'scripts').mkdir(parents=True)
    (g/'evidence'/'jets-r1').mkdir(parents=True)
    for rel in INPUTS:
        if rel not in drop:
            (g/rel).parent.mkdir(parents=True, exist_ok=True)
            if 'capped-list' in rel:
                (g/rel).write_bytes((REAL_F/Path(rel).name).read_bytes())
            else:
                (g/rel).write_text('{"x": 1}\n', encoding='utf8')
    if tamper:
        tamper(g/'evidence'/'final-f1')
    stub = root/'stub.sh'
    stub.write_bytes(STUB)
    text = HARNESS.read_text(encoding='utf8')
    text, n1 = re.subn(r'^G=.*$', 'G="%s"' % g.as_posix(), text, count=1, flags=re.M)
    text, n2 = re.subn(r'^PY=.*$', 'PY="%s"' % stub.as_posix(), text, count=1, flags=re.M)
    assert n1 == n2 == 1, (n1, n2)
    path = root/'harness.sh'
    path.write_bytes(text.encode('utf8'))
    return path


def harness_run(script, args, fail_stage=None, lexists=False, path_first=None):
    env = dict(os.environ, STUB_FAIL_STAGE=fail_stage or 'none', STUB_LEXISTS='1' if lexists else '')
    if path_first:
        env['PATH'] = str(path_first) + os.pathsep + env['PATH']
    run = subprocess.run([BASH, str(script), *args], capture_output=True, text=True, timeout=120, env=env)
    return run.returncode, (run.stdout+run.stderr).strip()


def harness_refuses(name, arg, script=None, lexists=False, path_first=None, want=''):
    code, out = harness_run(script or fake_harness('h%02d' % (len(results)+1)), arg, lexists=lexists,
                            path_first=path_first)
    fine = code == 2 and 'start' not in out and 'STUB-REPLAY' not in out and want in out
    record(name, 1 if fine else 0, False, 'exit %d: %s' % (code, out[-160:]))


def cp_shim():
    d = WORK/'cpshim'
    d.mkdir()
    (d/'cp').write_bytes(CP_SHIM)
    return d


def has(p, s):
    return p.is_file() and s in p.read_text(encoding='utf8')


def harness_status(name, want_code, fail_stage, want_text):
    """All three stages are checked with their pinned row counts and cap rules (refuter 16 Oct, P3-c).
    Round 3: both list rules and every deep replay name the hashed copies in OUT/inputs, which hold
    the pinned bytes."""
    script = fake_harness('h%02d' % (len(results)+1))
    out_dir = script.parent/'g'/'evidence'/'jets-r9'
    lst = ['%s/inputs/capped-list-%d.jsonl' % (out_dir.as_posix(), i) for i in range(6)]
    want = ['STUB-CHECK iv1-surfaces expect 40968 caps none',
            'STUB-CHECK iv2-sample expect 901 caps list:' + ','.join(lst),
            'STUB-CHECK iv2-deep expect 216 caps exactly:' + ','.join(lst)]
    code, out = harness_run(script, ['jets-r9'], fail_stage)
    lines = out.splitlines()
    seen = [w.split()[1] for w in want if w in lines]
    deep = sum(has(out_dir/('iv2-deep-%s-s%d.log' % (arm, i)), '--only-list %s ' % lst[i])
               for arm in ('base', 'jets') for i in range(6))
    copies = all((out_dir/'inputs'/('capped-list-%d.jsonl' % i)).read_bytes()
                 == (REAL_F/('capped-list-%d.jsonl' % i)).read_bytes() for i in range(6))
    fine = code == want_code and want_text in out and len(seen) == 3 and deep == 12 and copies
    record(name, 0 if fine else 1, True, 'exit %d stages %s deep replays on copies %d/12 copies %s: %s'
           % (code, seen, deep, copies, out.replace('\n', ' | ')[-120:]))


def edit_line(i, k, fn):
    """tamper: apply fn to line k of capped list i."""
    def m(f):
        p = f/('capped-list-%d.jsonl' % i)
        lines = p.read_text(encoding='utf8').splitlines(keepends=True)
        lines[k:k+1] = fn(lines[k])
        p.write_text(''.join(lines), encoding='utf8')
    return m


def swap_lists(f):
    a, b = f/'capped-list-0.jsonl', f/'capped-list-1.jsonl'
    x, y = a.read_bytes(), b.read_bytes()
    a.write_bytes(y)
    b.write_bytes(x)


WORK.mkdir(parents=True, exist_ok=False)
LIST1 = cap_list('caps1.jsonl', IFACE)
LIST_OTHER = cap_list('caps2.jsonl', IFACE2)
case('real pair', True)
case('real pair, digest-only change', True, digest_only)
case('jets shard missing', False, drop(('jets', 1)))
case('base shard missing', False, drop(('base', 1)))
case('both arms miss the same shard', False, drop(('base', 1), ('jets', 1)))
case('no shard files at all', False, drop(*[(a, i) for a in ('base', 'jets') for i in IDS]))
case('jets shard timed out (exit 124)', False, exits={('jets', 0): '124'})
case('base shard crashed (exit 1)', False, exits={('base', 0): '1'})
case('base exit file missing', False, exits={('base', 1): None})
case('jets done row missing', False, lambda d: d['jets', 1].pop())
case('jets last line cut mid-row', False, lambda d: d['jets', 1].__setitem__(-1, json.dumps(d['jets', 1][-1])[:40]))
case('two done rows', False, lambda d: d['jets', 0].insert(5, dict(d['jets', 0][-1])))
case('done.queries off by one', False, lambda d: d['jets', 0][-1].update(queries=N+1))
case('nodigest hash changed (VIOLATION)', False, row_edit(set_field('measure_sha_nodigest', '0'*16)))
case('nodigest hash None in jets', False, row_edit(set_field('measure_sha_nodigest', None)))
case('status met -> unmet, same hash', False, row_edit(set_field('status', 'unmet')))
case('jets row removed (queries kept true)', False, row_edit(remove_row))
case('jets extra row (queries kept true)', False, row_edit(extra_row))
case('jets duplicate row', False, row_edit(dup_row))
case('every pair capped', False, all_capped)
case('one base row capped, listed (counted)', True,
     row_edit(set_field('status', 'capped'), arm='base', i=0, k=IFACE), caps=LIST1)
case('same package digest both arms', False,
     lambda d: [d['jets', i][-1].update(package_digest=d['base', i][-1]['package_digest']) for i in IDS])
case('jets arm ran the base runtime', False, lambda d: d['jets', 0][-1].update(runtime=BASE_RT))
case('two package digests in one arm', False, lambda d: d['jets', 1][-1].update(package_digest='d'*64))
case('stray shard file', False, lambda d: d.__setitem__(('jets', 7), list(d['jets', 0])))
case('empty shard list', False, shards='')
case('same arm name twice', False, arm_names=('base', 'base'))
case('shard empty in both arms (done row, queries 0)', False, empty_both, expect=str(N))
case('rows below the pinned count', False, expect=str(N*len(IDS)+1))
case('expected count not a number', False, expect='many')
case('expected count zero', False, expect='0')
case('jets capped where base met (hang)', False, pair_status('met', 'capped'), caps=LIST1)
case('jets capped where base unmet', False, pair_status('unmet', 'capped'), caps=LIST1)
case('jets error where base capped', False, pair_status('capped', 'error'), caps=LIST1)
case('base error, jets capped', False, pair_status('error', 'capped'), caps=LIST1)
case('both capped, listed (accepted, counted)', True, pair_status('capped', 'capped'), caps=LIST1)
case('base capped, jets unmet, listed (accepted)', True, pair_status('capped', 'unmet'), caps=LIST1)
# refuter 16 Oct P3-a: a cap counts only for a query a deeper stage re-runs
case('no capped row under a list rule', True, caps=LIST1)
case('both capped, rule none (IV1/deep)', False, pair_status('capped', 'capped'))
case('base capped, jets met, rule none', False, pair_status('capped', 'met'))
case('both capped, another query listed', False, pair_status('capped', 'capped'), caps=LIST_OTHER)
case('both capped, listed in the second file', True, pair_status('capped', 'capped'),
     caps=LIST_OTHER + ',' + LIST1[len('list:'):])
case('wall pair capped, its cell listed (interface only)', False, pair_status('capped', 'capped', k=WALL),
     caps=cap_list('caps3.jsonl', WALL))
case('cap rule names a missing file', False, caps='list:' + str(WORK/'nope.jsonl'))
case('cap rule list is empty', False, caps=cap_list('caps4.jsonl'))
(WORK/'caps5.jsonl').write_text('x\n', encoding='utf8')
case('cap rule list not JSON', False, caps='list:' + str(WORK/'caps5.jsonl'))
case('cap rule neither none nor list', False, caps='all')
case('cap rule list: with no file', False, caps='list:')
case('compare_surfaces.py differs from the pinned sha', False, check=shadow_compare())
# round 3: the deep stage's rows must be exactly the listed queries
EXACT = exact_list('exact1.jsonl', IF)
NIF = str(N_IF)
case('exactly: listed interface rows', True, iface_only(), expect=NIF, caps=EXACT)
case('exactly: list split across two files', True, iface_only(), expect=NIF,
     caps=exact_list('exact2a.jsonl', IF[:7]) + ',' + exact_list('exact2b.jsonl', IF[7:])[len('exactly:'):])
REPLACED = iface_only(lambda lines: lines[3].update(cell='f'*16))
case('control: rule none passes rows replaced in both arms', True, REPLACED, expect=NIF)
case('exactly: a listed row replaced in both arms', False, REPLACED, expect=NIF, caps=EXACT)
case('exactly: a listed row duplicated over another', False,
     iface_only(lambda lines: lines.__setitem__(3, dict(lines[4]))), expect=NIF, caps=EXACT)
case('exactly: a wall row with a listed key', False,
     iface_only(lambda lines: lines.__setitem__(3, dict(REAL[0][0][WALL]))), expect=NIF,
     caps=exact_list('exact3.jsonl', IF[:3] + [REAL[0][0][WALL]] + IF[4:]))
case('exactly: list has a query not run', False, iface_only(), expect=NIF, caps=exact_list('exact4.jsonl', IF + [IF_SPARE]))
case('exactly: list repeats a query', False, iface_only(), expect=NIF, caps=exact_list('exact5.jsonl', IF + [IF[0]]))
case('exactly: a listed row capped in both arms', False,
     iface_only(lambda lines: lines[3].update(status='capped')), expect=NIF, caps=EXACT)
case('exactly: with no file', False, iface_only(), expect=NIF, caps='exactly:')
case('exactly: missing file', False, iface_only(), expect=NIF, caps='exactly:' + str(WORK/'nope.jsonl'))
harness_waitall()
harness_refuses('harness: existing folder refused', ['jets-r1'])
harness_refuses('harness: bad folder name refused', ['../x'])
harness_refuses('harness: no folder name refused', [])
harness_refuses('harness: trailing dot refused', ['jets-r1.'])
harness_refuses('harness: leading dot refused', ['.jets'])
harness_refuses('harness: two names refused', ['a', 'b'])
harness_refuses('harness: missing capped list refused',
                ['jets-r9'], fake_harness('hx1', drop=('evidence/final-f1/capped-list-3.jsonl',)))
harness_refuses('harness: no reference shards refused', ['jets-r9'], fake_harness(
    'hx2', drop=('evidence/final-f1/ref-iv2-surfaces-s0.jsonl', 'evidence/final-f1/ref-iv2-surfaces-s1.jsonl')))
harness_refuses('harness: capped list edited refused', ['jets-r9'],
                fake_harness('hx3', tamper=edit_line(3, 0, lambda s: [s.replace('"cell": "', '"cell": "0', 1)])))
harness_refuses('harness: capped list truncated refused', ['jets-r9'],
                fake_harness('hx4', tamper=edit_line(5, 35, lambda s: [])))
harness_refuses('harness: capped list line added refused', ['jets-r9'],
                fake_harness('hx5', tamper=edit_line(2, 0, lambda s: [s, s])))
harness_refuses('harness: capped lists swapped refused', ['jets-r9'], fake_harness('hx6', tamper=swap_lists))
harness_refuses('harness: folder seen only by Windows refused', ['jets-r9'], lexists=True)
harness_refuses('harness: copy edited after cp refused (round 3)', ['jets-r9'], fake_harness('hx7'),
                path_first=cp_shim(), want='copied capped lists are')
harness_status('harness: all checks pass -> exit 0', 0, None, 'JETS PARITY PASSED')
harness_status('harness: iv1 check fails -> exit 1, later stages still run', 1, 'iv1-surfaces', 'JETS PARITY FAILED')
harness_status('harness: deep check fails -> exit 1', 1, 'iv2-deep', 'JETS PARITY FAILED')
ok = all(r['ok'] for r in results.values())
(WORK/'proof.json').write_text(json.dumps(dict(source=str(SRC), check=str(CHECK), harness=str(HARNESS),
                                               results=results, ok=ok), indent=1), encoding='utf8')
print('PROOF', 'PASS' if ok else 'FAIL', '%d/%d as expected' % (sum(r['ok'] for r in results.values()), len(results)))
sys.exit(0 if ok else 1)
