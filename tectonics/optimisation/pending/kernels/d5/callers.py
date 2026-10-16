"""D5 recon: who calls Fraction arithmetic in the q14 deep profile (read-only).

Usage: python -B -I callers.py merged.prof
Sums, over the Fraction operator entry points (forward/reverse wrappers, __new__, comparisons, hash, etc.),
each direct caller's cumulative time into that entry, grouped by caller (module:line:function) and by module.
Callers inside fractions.py itself are skipped, so a time is counted at the first non-fractions frame.
"""
import collections
import os
import pstats
import sys

st = pstats.Stats(sys.argv[1])
by_caller, by_module, n_calls = collections.Counter(), collections.Counter(), collections.Counter()
total = 0.0
for (file, line, name), (cc, nc, tt, ct, callers) in st.stats.items():
    if os.path.basename(file) != 'fractions.py':
        continue
    for (cfile, cline, cname), stat in callers.items():
        if os.path.basename(cfile) == 'fractions.py':
            continue
        ccum = stat[3]
        key = '%s:%d:%s' % (os.path.basename(cfile), cline, cname)
        by_caller[key] += ccum
        by_module[os.path.basename(cfile)] += ccum
        n_calls[key] += stat[1]
        total += ccum
print('Fraction entry time from non-fractions callers: %.1f s' % total)
for mod, t in by_module.most_common(12):
    print('  %-48s %7.1f s' % (mod, t))
print('top callers:')
for key, t in by_caller.most_common(30):
    print('  %-70s %7.1f s %9d calls' % (key[:70], t, n_calls[key]))
gcd = [v for k, v in st.stats.items() if k[2] == '<built-in method math.gcd>']
if gcd:
    print('math.gcd total %.1f s, %d calls' % (gcd[0][3], gcd[0][1]))
