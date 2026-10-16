"""Build the H5a D-b control layout and its generation note (16 Oct; coordinator ~15:15: "W4 D-b control in a
ticket after RESUME, folded into an existing heat ticket if possible").

Usage: python -B h5a_control_layout.py BASE OUT NOTE.md
BASE is a prepared layout (lf3 = lw + H1a r3 + H2 + H1c r3 + L1 r4). OUT and NOTE must not exist.

OUT is BASE copied byte for byte, except:
- control.json: BASE's three layout paths (runtime-src, helpers, ram) name OUT; nothing else changes;
- helpers/private_heat_functionals_kernel_r5.py holds transforms/h5a_prepare_reuse.functionals() of itself (the r6
  content); helpers/private_heat_forward_kernel_r13.py holds forward() of itself (the r14 content) with its one
  functionals import kept on the r5 module name, which now holds the r6 content. The file names stay, as for L1
  (the issuer imports the forward kernel by name; native_issuer_r13 is not touched);
- the 9 pin lines that name those two files, or a file whose digest changes because of them, name the new digest
  (6 pinners, CASCADE order). Every other line of every file is unchanged.
A copy is used instead of a fresh --prepare: prep_r3 showed --prepare is deterministic (fresh == lw apart from
control.json), and a copy keeps every other byte identical to BASE, which the checks below prove.

The checks are independent of the rewrite: same file set; exactly the expected files differ; each pinner differs
only on lines that swap a pinned file's old digest for its new one; no file anywhere in OUT still names an old
digest of a changed file, and each new digest appears exactly where the old one did; both sources equal the
transform output; every changed .py compiles; no path reaches 259 characters.

D-b basis: H5a changes no number. The same-call control on BASE and OUT must give identical array and metadata
leaves apart from 64-hex digests and layout paths (scripts/compare_ab_r2.py).
"""
import json
import re
import shutil
import sys
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'transforms'))
import h5a_prepare_reuse as X  # noqa: E402

FUNC = 'helpers/private_heat_functionals_kernel_r5.py'
FWD = 'helpers/private_heat_forward_kernel_r13.py'
CK = 'helpers/private_heat_checkpoint_consumer_r10.py'
JC = 'helpers/private_heat_joined_consumer_r6.py'
RB = 'helpers/private_heat_restored_binding_r10.py'
RC = 'ram/private_heat_restored_binding_ram_context_r1.py'
RR = 'ram/private_heat_restored_binding_ram_recovery_r1.py'
COLD = 'runtime-src/atlas_tectonics/integration_private_heat_cold.py'
CASCADE = ((CK, (FWD,)), (JC, (FWD, CK)), (RB, (FWD, CK, JC)), (RC, (FWD, CK, JC)), (RR, (RC,)), (COLD, (RB,)))
SOURCES = (FUNC, FWD)
CONTROL = 'control.json'
EXPECTED = sorted({FUNC, FWD, CONTROL} | {p for p, _ in CASCADE})
IMPORT_R5 = 'import private_heat_functionals_kernel_r5 as FUNCTIONS\n'
IMPORT_R6 = 'import private_heat_functionals_kernel_r6 as FUNCTIONS\n'
HEX = re.compile(r'[0-9a-f]{64}')


def _files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts)


def _sha(data):
    return sha256(data).hexdigest()


def _forward_in_place(text):
    out = X.forward(text)
    if out.count(IMPORT_R6) != 1:
        raise ValueError('forward r14 must import functionals r6 exactly once')
    return out.replace(IMPORT_R6, IMPORT_R5)


def _repin(text, pinned, before, after):
    """Swap the one pin line naming `pinned` at `before`; a dict entry or a _BINDING_SHA constant."""
    lines = [line for line in text.split('\n') if before in line]
    forms = ("    '%s': '%s'," % (Path(pinned).name, before), "_BINDING_SHA = '%s'" % before)
    if text.count(before) != 1 or len(lines) != 1 or lines[0] not in forms:
        raise ValueError('pin of %s at %s must be exactly one known pin line' % (pinned, before[:8]))
    return text.replace(before, after)


def build(base, out):
    info = json.loads((base/CONTROL).read_bytes())
    layout = [str(base/'runtime-src'), str(base/'helpers'), str(base/'ram')]
    if info['paths'][:3] != layout:
        raise SystemExit('BASE control.json does not name BASE: %s' % info['paths'][:3])
    out.mkdir(parents=False, exist_ok=False)
    for name in _files(base):
        (out/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base/name, out/name)
    raw = (out/CONTROL).read_bytes()
    for old, new in zip(layout, [str(out/'runtime-src'), str(out/'helpers'), str(out/'ram')], strict=True):
        old_j, new_j = json.dumps(old).encode(), json.dumps(new).encode()
        if raw.count(old_j) != 1:
            raise SystemExit('control.json must name %s exactly once' % old)
        raw = raw.replace(old_j, new_j)
    (out/CONTROL).write_bytes(raw)
    read = lambda n: (out/n).read_bytes().decode('utf8')                 # noqa: E731
    write = lambda n, t: (out/n).write_bytes(t.encode('utf8'))           # noqa: E731
    write(FUNC, X.functionals(read(FUNC)))
    write(FWD, _forward_in_place(read(FWD)))
    for pinner, pinned_files in CASCADE:
        text = read(pinner)
        for pinned in pinned_files:
            text = _repin(text, pinned, _sha((base/pinned).read_bytes()), _sha((out/pinned).read_bytes()))
        write(pinner, text)


def check(base, out):
    names = _files(base)
    if names != _files(out):
        raise SystemExit('file sets differ')
    old = {n: _sha((base/n).read_bytes()) for n in names}
    new = {n: _sha((out/n).read_bytes()) for n in names}
    changed = sorted(n for n in names if old[n] != new[n])
    if changed != EXPECTED:
        raise SystemExit('unexpected changed files: %s' % changed)
    # control.json: only the three layout paths.
    a, b = json.loads((base/CONTROL).read_bytes()), json.loads((out/CONTROL).read_bytes())
    mapped = [p.replace(str(base), str(out), 1) if i < 3 else p for i, p in enumerate(a['paths'])]
    if {**a, 'paths': mapped} != b or any(not p.startswith(str(out)) for p in b['paths'][:3]):
        raise SystemExit('control.json differs beyond the layout paths')
    # Sources equal the reviewed transform output (forward: one import line kept on r5).
    if (out/FUNC).read_bytes().decode('utf8') != X.functionals((base/FUNC).read_bytes().decode('utf8')):
        raise SystemExit('functionals is not the H5a transform output')
    fwd_t = X.forward((base/FWD).read_bytes().decode('utf8')).split('\n')
    fwd_o = (out/FWD).read_bytes().decode('utf8').split('\n')
    diff = [(x, y) for x, y in zip(fwd_t, fwd_o, strict=True) if x != y]
    if diff != [(IMPORT_R6.rstrip('\n'), IMPORT_R5.rstrip('\n'))]:
        raise SystemExit('forward differs from the H5a transform output beyond the import line: %s' % diff[:3])
    for name in SOURCES:
        text = (out/name).read_bytes().decode('utf8')
        if 'functionals_kernel_r6' in text or 'forward_kernel_r14' in text:
            raise SystemExit('%s names an r6/r14 module that is not in the layout' % name)
    # Pinners: only pin lines changed, each swapping one pinned file's old digest for its new one.
    rows = []
    for pinner, pinned_files in CASCADE:
        lines_b = (base/pinner).read_bytes().decode('utf8').split('\n')
        lines_a = (out/pinner).read_bytes().decode('utf8').split('\n')
        diff = [(x, y) for x, y in zip(lines_b, lines_a, strict=True) if x != y]
        swaps = {old[p]: new[p] for p in pinned_files}
        if len(diff) != len(pinned_files) or any(
                not any(d in x and x.replace(d, swaps[d]) == y for d in swaps) for x, y in diff):
            raise SystemExit('%s: changed lines are not exactly its %d pin lines' % (pinner, len(pinned_files)))
        rows.append((pinner, ', '.join(Path(p).name for p in pinned_files), old[pinner], new[pinner]))
    # No stale digest anywhere; every new digest sits exactly where the old one did.
    for name in changed:
        if name == CONTROL:
            continue
        where_b = sorted(n for n in names if old[name] in (base/n).read_bytes().decode('utf8', 'replace'))
        where_a = sorted(n for n in names if new[name] in (out/n).read_bytes().decode('utf8', 'replace'))
        stale = sorted(n for n in names if old[name] in (out/n).read_bytes().decode('utf8', 'replace'))
        if stale or where_a != where_b:
            raise SystemExit('%s: stale %s, pinned before by %s, after by %s' % (name, stale, where_b, where_a))
    for name in changed:
        if name.endswith('.py'):
            compile((out/name).read_bytes(), str(out/name), 'exec')
    longest = max(len(str(p)) for p in out.rglob('*'))
    if longest >= 259:
        raise SystemExit('a path in OUT is %d characters' % longest)
    return old, new, rows, longest


def note(base, out, path, old, new, rows, longest):
    text = ['# H5a generation note r1 (D-b control layout; explicit pin rewrites)', '',
            'Before: `%s` (lf3: H1a r3 + H2 + H1c r3 + L1 r4). After: `%s` (+ H5a in place).' % (base, out), '',
            'Generator: scripts/h5a_control_layout.py (sha %s); transform: transforms/h5a_prepare_reuse.py (sha %s).' % (
                _sha(Path(__file__).read_bytes()), _sha(Path(X.__file__).read_bytes())), '',
            '| file | role | sha before | sha after |', '|---|---|---|---|',
            '| %s | source: functionals r5 -> r6 content (H5a) | %s | %s |' % (FUNC, old[FUNC], new[FUNC]),
            '| %s | source: forward r13 -> r14 content, import kept on r5 name | %s | %s |' % (FWD, old[FWD], new[FWD])]
    text += ['| %s | pins %s | %s | %s |' % r for r in rows]
    text += ['| %s | the three layout paths only | %s | %s |' % (CONTROL, old[CONTROL], new[CONTROL]),
             '', 'Checked by the generator: every other file is byte-identical to BASE; each pinner changed only',
             'its pin lines, each from the pinned file\'s old digest to its new one; no file names an old digest',
             'of a changed file and each new digest sits exactly where the old one did; both sources equal the',
             'transform output (forward: its one functionals import stays on the r5 name); every changed .py',
             'compiles; longest path %d characters.' % longest, '',
             'D-b basis: H5a changes no number. The issuer binds absolute helper paths and digests at run time,',
             'so record and result IDs change by digest only. The same-call control compares BASE and OUT: every',
             'array and metadata leaf must be identical apart from 64-hex digests and layout paths',
             '(scripts/compare_ab_r2.py).']
    path.write_bytes(('\n'.join(text)+'\n').encode('utf8'))
    print('\n'.join(text))


def main():
    base, out, path = (Path(a).resolve() for a in sys.argv[1:4])
    if path.exists():
        raise SystemExit('note exists: %s' % path)
    build(base, out)
    note(base, out, path, *check(base, out))


if __name__ == '__main__':
    main()
