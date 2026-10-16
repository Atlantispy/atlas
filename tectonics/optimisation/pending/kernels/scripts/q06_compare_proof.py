"""q06 small-lane proof of the compare arguments (coordinator, 16 Oct): fail-closed evidence.

Usage: python -B q06_compare_proof.py WORK ROOT_A ROOT_B
WORK must not exist. ROOT_A/ROOT_B: the layout roots of q03's real arm-0 (T/hs/lw) and arm-1
(T/hs/lc), spelt by the same W() (cygpath -w) that job_h3r2.sh uses for l2/l3. Copies the two real
proof arms (T/hs/evidence/h12-r1, read-only) per case, plants one defect, and runs Heat's pinned
compare_ab_r2.py exactly as q06 calls it: ARM_0 ARM_1 ROOT_A ROOT_B. The real cross-layout pair and
a digest-only change must PASS; every other case must exit non-zero. check_arms.py is run with
q06's expected count (6). Writes WORK/proof.json; exit 0 only if every case is as expected.
"""
import json
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np

T = Path(__file__).resolve().parents[2]
HS = T/'hs'
SRC = HS/'evidence'/'h12-r1'
PINS = {'compare_ab_r2.py': 'f67dbb662b66fc0c8559a5df7f92c3f8789210fbe4cf3892a57f7bdb26f5e7da',
        'check_arms.py': 'b8e7fe7f29ee50c49886b0dba125760678311381a17cf3c3e09a64be85587139'}
WORK, ROOT_A, ROOT_B = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
PY = sys.executable
results = {}


def pinned(name):
    path = HS/'scripts'/name
    digest = sha256(path.read_bytes()).hexdigest()
    if digest != PINS[name]:
        raise SystemExit(f'{name} is {digest}, not the reviewed {PINS[name]}')
    return path


COMPARE, CHECK = pinned('compare_ab_r2.py'), pinned('check_arms.py')


def pair(case):
    root = WORK/case
    root.mkdir()
    for k in (0, 1):
        shutil.copytree(SRC/f'arm-{k}', root/f'arm-{k}')
        shutil.copy(SRC/f'arm-{k}.json', root/f'arm-{k}.json')
    return root/'arm-0', root/'arm-1'


def record(case, code, want_pass, tail=''):
    ok = (code == 0) == want_pass
    results[case] = dict(exit=code, want='PASS' if want_pass else 'FAIL', ok=ok, tail=tail)
    print('%-34s exit %d  %s' % (case, code, 'as expected' if ok else 'WRONG'))


def compare(case, mutate, want_pass, roots=None):
    a, b = pair(case)
    mutate(a, b)
    run = subprocess.run([PY, '-B', str(COMPARE), str(a), str(b), *([ROOT_A, ROOT_B] if roots is None else roots)],
                         capture_output=True, text=True)
    (WORK/case/'compare.txt').write_text(run.stdout+run.stderr, encoding='utf8')
    record(case, run.returncode, want_pass, (run.stdout.strip().splitlines() or [''])[-1][:120])


def meta(fn):
    def mutate(a, b):
        p = b/'legacy_metadata.json'
        m = json.loads(p.read_bytes())
        fn(m)
        p.write_bytes(json.dumps(m).encode())
    return mutate


def walk(obj, want):
    stack = [(obj, [])]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            stack.extend((v, path+[k]) for k, v in node.items())
        elif isinstance(node, list):
            stack.extend((v, path+[i]) for i, v in enumerate(node))
        elif want(node):
            return path, node
    raise SystemExit('no matching leaf')


def set_at(m, path, value):
    for k in path[:-1]:
        m = m[k]
    m[path[-1]] = value


def is_num(x):
    return type(x) in (int, float)


def is_hex(x):
    return isinstance(x, str) and len(x) == 64 and all(c in '0123456789abcdef' for c in x)


def bump(m):
    path, value = walk(m, is_num)
    set_at(m, path, value+1)


def num_to_str(m):
    path, value = walk(m, is_num)
    set_at(m, path, str(value))


def other_layout(m):
    # The layout root appears only in keys (caller_snapshot.private_sources is keyed by absolute path;
    # p1 looked for a value leaf and stopped): one key that names arm-1's layout now names another
    # layout (lc -> lcx), every key kept in its place.
    stack = [m]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            hit = next((k for k in node if ROOT_B in k), None)
            if hit is not None:
                items = list(node.items())
                node.clear()
                node.update((k.replace(ROOT_B, ROOT_B+'x') if k == hit else k, v) for k, v in items)
                return
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    raise SystemExit('no key names the layout root')


def digest_to_text(m):
    path, _ = walk(m, is_hex)
    set_at(m, path, 'not a digest')


def digest_only(m):
    path, value = walk(m, is_hex)
    set_at(m, path, 'f'*64 if value != 'f'*64 else 'e'*64)


def array_edit(fn):
    def mutate(a, b):
        p = b/'temperature_k.npy'
        np.save(p, fn(np.load(p)))
    return mutate


def flip(x):
    raw = bytearray(x.tobytes())
    raw[len(raw)//2] ^= 1
    return np.frombuffer(bytes(raw), dtype=x.dtype).reshape(x.shape)


def arm_json(fn, k=1):
    def mutate(a, b):
        p = (a, b)[k].parent/f'arm-{k}.json'
        res = json.loads(p.read_text(encoding='utf8'))
        fn(res)
        p.write_text(json.dumps(res), encoding='utf8')
    return mutate


def names(fn):
    def mutate(a, b):
        p = b/'arrays.json'
        p.write_text(json.dumps(fn(json.loads(p.read_text(encoding='utf8')))), encoding='utf8')
    return mutate


WORK.mkdir(parents=True, exist_ok=False)
def nothing(a, b):
    return None


compare('real pair, q06 roots', nothing, True)
compare('real pair, no roots', nothing, False, roots=[])
compare('real pair, roots swapped', nothing, False, roots=[ROOT_B, ROOT_A])
compare('real pair, digest-only change', meta(digest_only), True)
compare('array byte flipped', array_edit(flip), False)
compare('array dtype reinterpreted', array_edit(lambda x: x.view(np.int64) if x.itemsize == 8 else x.view(np.int32)),
        False)
compare('array reshaped, same bytes', array_edit(lambda x: x.reshape(-1)[:, None] if x.ndim == 1 else x.reshape(-1)),
        False)
compare('array names reordered', names(lambda n: dict(reversed(list(n.items())))), False)
compare('one side empty capture', names(lambda n: {}), False)
compare('metadata number bumped', meta(bump), False)
compare('metadata number as string', meta(num_to_str), False)
compare('metadata path names another layout', meta(other_layout), False)
compare('metadata digest replaced by text', meta(digest_to_text), False)
compare('metadata extra key', meta(lambda m: m.update(unexpected_extra_key=1)), False)
compare('arm-1 status FAIL', arm_json(lambda r: r.update(status='FAIL')), False)
compare('arm-0 leak', arm_json(lambda r: r['ab'].update(leaks=['C:/elsewhere.py']), k=0), False)
compare('arm-1 folder missing', lambda a, b: shutil.rmtree(b), False)

good = dict(arm=0, mode='time', label='h2', status='PASS', leaks=0, exit_code=0, used=[6, 6],
            fallback=[None, None], arm_wall_seconds=1.0)
six = [dict(good, arm=k) for k in range(6)]
for case, arms, want_pass in (('check_arms: 6 good', six, True),
                              ('check_arms: 5 of 6', six[:5], False),
                              ('check_arms: time arm fallback', six[:5]+[dict(good, arm=5, used=[6, 1],
                                                                              fallback=[None, 'cpu gate'])], False),
                              ('check_arms: proof arm stopped', [dict(good, stopped='guard')]+six[1:], False)):
    d = WORK/case.replace(':', '').replace(' ', '-')
    d.mkdir()
    (d/'summary.json').write_text(json.dumps(dict(arms=arms)), encoding='utf8')
    run = subprocess.run([PY, '-B', str(CHECK), str(d), '6'], capture_output=True, text=True)
    record(case, run.returncode, want_pass, (run.stdout.strip().splitlines() or [''])[-1][:120])

ok = all(r['ok'] for r in results.values())
(WORK/'proof.json').write_text(json.dumps(dict(roots=[ROOT_A, ROOT_B], pins=PINS, source=str(SRC), results=results,
                                               ok=ok), indent=1), encoding='utf8')
print('PROOF', 'PASS' if ok else 'FAIL', '%d/%d as expected' % (sum(r['ok'] for r in results.values()), len(results)))
sys.exit(0 if ok else 1)
