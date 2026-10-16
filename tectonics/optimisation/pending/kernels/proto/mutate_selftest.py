"""Seeded mutants of the compiled helper: each must fail its import self-test.

Usage: python -B mutate_selftest.py <helper.py> <scratch dir>
Each mutant is written to its own folder and imported in a fresh interpreter.
"""
import os
import subprocess
import sys

SOURCE, SCRATCH = sys.argv[1], sys.argv[2]
text = open(SOURCE, encoding='utf8').read()
MUTANTS = {
    'four-rd-1': ('\n    if mpfr_less_p(tmp[1], m) != 0:', '\n    if mpfr_lessequal_p(tmp[1], m) != 0:'),
    'four-rd-2': ('if mpfr_less_p(tmp[2], m) != 0:', 'if mpfr_lessequal_p(tmp[2], m) != 0:'),
    'four-rd-3': ('if mpfr_less_p(tmp[3], m) != 0:', 'if mpfr_lessequal_p(tmp[3], m) != 0:'),
    'four-ru-5': ('\n    if mpfr_greater_p(tmp[5], M) != 0:', '\n    if mpfr_lessequal_p(M, tmp[5]) != 0:'),
    'four-ru-6': ('if mpfr_greater_p(tmp[6], M) != 0:', 'if mpfr_lessequal_p(M, tmp[6]) != 0:'),
    'four-ru-7': ('if mpfr_greater_p(tmp[7], M) != 0:', 'if mpfr_lessequal_p(M, tmp[7]) != 0:'),
    'class-pos-neg': ('            lx, ly, hx, hy = a1, b0, a0, b1\n', '            lx, ly, hx, hy = a0, b0, a0, b1\n'),
    'class-mixed-pos': ('            lx, ly, hx, hy = a0, b1, a1, b1\n', '            lx, ly, hx, hy = a0, b0, a1, b1\n'),
    'gram-rc': ('                rcs_lo[k] = rcs_lo[source]\n', '                rcs_lo[k] = 0\n'),
    'acc-rnd': ('rl = np.int32(mpfr_add(acc_lo, acc_lo, m, RNDD))', 'rl = np.int32(mpfr_add(acc_lo, acc_lo, m, RNDU))'),
    'band': ('EXP_BAND = 1 << 28', 'EXP_BAND = 1 << 31'),
}
results = {}
for name, (old, new) in MUTANTS.items():
    if text.count(old) != 1:
        results[name] = 'anchor count %d' % text.count(old)
        continue
    folder = os.path.join(SCRATCH, 'mut-'+name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, os.path.basename(SOURCE)), 'w', encoding='utf8') as fh:
        fh.write(text.replace(old, new))
    probe = ('try:\n import private_heat_compiled_dot_r1\n print("IMPORTED")\n'
             'except ImportError as e:\n print("REJECTED", e)')
    out = subprocess.run([sys.executable, '-B', '-c', probe], cwd=folder, capture_output=True, text=True)
    results[name] = (out.stdout.strip() or out.stderr.strip()[-200:])
for name, verdict in results.items():
    print('%-16s %s' % (name, verdict))
