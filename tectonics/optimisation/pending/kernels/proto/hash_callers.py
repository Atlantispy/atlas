"""Item 18 scoping (read-only): where Fraction hashing/comparison is spent, and who calls it.

Usage: python -B -I hash_callers.py OUT_PREFIX PROF [PROF ...]
Merges the pstats files, then for fractions.Fraction.__hash__, __eq__, _richcmp/__lt__/__le__/
__gt__/__ge__ and builtins hash/sorted prints total and self time and the top callers with their
own share. Profiler-inflated (cProfile); used only to rank where tuple keys are hashed/compared.
"""
import os
import pstats
import sys

stats = pstats.Stats(sys.argv[2])
for path in sys.argv[3:]:
    stats.add(path)
total = stats.total_tt
print('profiles', len(sys.argv)-2, 'total_tt %.1f s' % total)
wanted = {'__hash__', '__eq__', '_richcmp', '__lt__', '__le__', '__gt__', '__ge__'}
rows = []
for func, (cc, nc, tt, ct, callers) in stats.stats.items():
    filename, line, name = func
    if (filename.endswith('fractions.py') and name in wanted) or (filename == '~' and name in (
            "<built-in method builtins.hash>", "<built-in method builtins.sorted>")):
        rows.append((ct, tt, nc, func, callers))
rows.sort(key=lambda r: -r[0])
for ct, tt, nc, func, callers in rows:
    print('\n%s:%s %s  calls %d  self %.1f s  cum %.1f s (%.1f%% of total)' % (os.path.basename(func[0]), func[1], func[2], nc, tt, ct, 100*ct/total))
    top = sorted(callers.items(), key=lambda kv: -kv[1][3])[:8]
    for caller, (ccc, cnc, ctt, cct) in top:
        print('   %6.1f s cum  %9d calls  <- %s:%s %s' % (cct, cnc, os.path.basename(caller[0]), caller[1], caller[2]))
