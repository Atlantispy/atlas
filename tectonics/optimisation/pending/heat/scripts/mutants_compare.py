"""Planted mutants for compare_ab_r2.py and check_arms.py ("review before you queue", item 2).

Copies q03's proof arm-0 (evidence/h12-r1/arm-0 + arm-0.json) into a scratch folder given on the
command line, plants one defect per case, and runs the real scripts. The identical copy and a
digest-only change must PASS; every other case must exit non-zero. Exit 0 only if all hold.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path


HS = Path(__file__).resolve().parents[1]
SRC = HS/'evidence'/'h12-r1'
WORK = Path(sys.argv[1])
WORK.mkdir(parents=True, exist_ok=False)
PY = sys.executable
results = []


def arm(case, label):
    root = WORK/case
    root.mkdir(exist_ok=True)
    shutil.copytree(SRC/'arm-0', root/label)
    shutil.copy(SRC/'arm-0.json', root/(label+'.json'))
    return root/label


def compare(case, mutate, want_pass):
    a, b = arm(case, 'arm-0'), arm(case, 'arm-1')
    mutate(a, b)
    code = subprocess.run([PY, '-B', str(HS/'scripts'/'compare_ab_r2.py'), str(a), str(b)],
                          capture_output=True, text=True).returncode
    ok = (code == 0) == want_pass
    results.append(ok)
    print('%-28s exit %d  %s' % (case, code, 'as expected' if ok else 'WRONG'))


def flip_byte(a, b):
    p = b/'temperature_k.npy'
    data = bytearray(p.read_bytes())
    data[-1] ^= 1
    p.write_bytes(bytes(data))


def drop_array(a, b):
    names = json.loads((b/'arrays.json').read_text())
    names.pop(next(iter(names)))
    (b/'arrays.json').write_text(json.dumps(names))


def empty_both(a, b):
    for x in (a, b):
        (x/'arrays.json').write_text('{}')


def meta_edit(fn):
    def mutate(a, b):
        p = b/'legacy_metadata.json'
        meta = json.loads(p.read_bytes())
        fn(meta)
        p.write_bytes(json.dumps(meta).encode())
    return mutate


def first_number_path(obj):
    stack = [(obj, [])]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            stack.extend((v, path+[k]) for k, v in node.items())
        elif isinstance(node, list):
            stack.extend((v, path+[i]) for i, v in enumerate(node))
        elif type(node) in (int, float) and not isinstance(node, bool):
            return path
    raise SystemExit('no numeric leaf')


def set_at(meta, path, value):
    node = meta
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value


def bump_number(meta):
    path = first_number_path(meta)
    node = meta
    for k in path:
        node = node[k]
    set_at(meta, path, node+1)


def null_number(meta):
    set_at(meta, first_number_path(meta), None)


def drop_key(meta):
    meta.pop(next(iter(meta)))


def digest_only(meta):
    stack = [(meta, [])]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            stack.extend((v, path+[k]) for k, v in node.items())
        elif isinstance(node, list):
            stack.extend((v, path+[i]) for i, v in enumerate(node))
        elif isinstance(node, str) and len(node) == 64 and all(c in '0123456789abcdef' for c in node):
            set_at(meta, path, 'f'*64 if node != 'f'*64 else 'e'*64)
            return
    raise SystemExit('no digest leaf')


def status_fail(a, b):
    p = b.parent/(b.name+'.json')
    res = json.loads(p.read_text())
    res['status'] = 'FAIL'
    p.write_text(json.dumps(res))


def leak(a, b):
    p = b.parent/(b.name+'.json')
    res = json.loads(p.read_text())
    res['ab']['leaks'] = ['C:/somewhere/else.py']
    p.write_text(json.dumps(res))


def no_status(a, b):
    p = b.parent/(b.name+'.json')
    res = json.loads(p.read_text())
    del res['status']
    p.write_text(json.dumps(res))


def missing_dir(a, b):
    shutil.rmtree(b)


ROOT_A = str(HS/'lw')                     # q03 arm-0 ran on lw
ROOT_B = str(HS/'lx-fake-root')


def relayout(a, b):
    # B as if run from another layout root: plain, JSON-escaped and forward-slash spellings.
    p = b/'legacy_metadata.json'
    text = p.read_bytes().decode('utf8')
    for old, new in ((ROOT_A.replace('\\', '\\\\'), ROOT_B.replace('\\', '\\\\')),
                     (ROOT_A.replace('\\', '/'), ROOT_B.replace('\\', '/')), (ROOT_A, ROOT_B)):
        text = text.replace(old, new)
    assert text != p.read_bytes().decode('utf8'), 'root not found in metadata'
    p.write_bytes(text.encode('utf8'))


def relayout_plus_key(a, b):
    relayout(a, b)
    p = b/'legacy_metadata.json'
    meta = json.loads(p.read_bytes())
    meta['unexpected_extra_key'] = 1
    p.write_bytes(json.dumps(meta).encode())


def compare_roots(case, mutate, want_pass, roots):
    a, b = arm(case, 'arm-0'), arm(case, 'arm-1')
    mutate(a, b)
    code = subprocess.run([PY, '-B', str(HS/'scripts'/'compare_ab_r2.py'), str(a), str(b), *roots],
                          capture_output=True, text=True).returncode
    ok = (code == 0) == want_pass
    results.append(ok)
    print('%-28s exit %d  %s' % (case, code, 'as expected' if ok else 'WRONG'))


compare_roots('cross-layout with roots', relayout, True, [ROOT_A, ROOT_B])
compare_roots('cross-layout without roots', relayout, False, [])
compare_roots('cross-layout plus extra key', relayout_plus_key, False, [ROOT_A, ROOT_B])
compare_roots('cross-layout wrong roots', relayout, False, [ROOT_A, str(HS/'ly-other')])
compare('identical', lambda a, b: None, True)
compare('digest-only metadata', meta_edit(digest_only), True)
compare('array byte flipped', flip_byte, False)
compare('array dropped', drop_array, False)
compare('empty capture both sides', empty_both, False)
compare('metadata number bumped', meta_edit(bump_number), False)
compare('metadata number to null', meta_edit(null_number), False)
compare('metadata key dropped', meta_edit(drop_key), False)
compare('arm status FAIL', status_fail, False)
compare('arm status missing', no_status, False)
compare('arm leak', leak, False)
compare('arm folder missing', missing_dir, False)

good = dict(arm=0, mode='time', label='x', status='PASS', leaks=0, exit_code=0, used=[6, 6], fallback=[None, None],
            arm_wall_seconds=1.0)
for case, arms, count, want_pass in (
        ('arms: all good', [good, dict(good, arm=1)], 2, True),
        ('arms: one missing', [good], 2, False),
        ('arms: stopped', [good, dict(good, arm=1, stopped='guard')], 2, False),
        ('arms: serial fallback', [good, dict(good, arm=1, used=[6, 1], fallback=[None, 'cpu gate'])], 2, False),
        ('arms: status None', [good, dict(good, arm=1, status=None)], 2, False),
        ('arms: leak', [good, dict(good, arm=1, leaks=1)], 2, False)):
    d = WORK/case.replace(':', '').replace(' ', '-')
    d.mkdir()
    (d/'summary.json').write_text(json.dumps(dict(arms=arms)))
    code = subprocess.run([PY, '-B', str(HS/'scripts'/'check_arms.py'), str(d), str(count)],
                          capture_output=True, text=True).returncode
    ok = (code == 0) == want_pass
    results.append(ok)
    print('%-28s exit %d  %s' % (case, code, 'as expected' if ok else 'WRONG'))
print('MUTANTS', 'PASS' if all(results) else 'FAIL', '%d/%d as expected' % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
