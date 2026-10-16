"""D5 recon: direct callers of named functions in a profile (read-only).

Usage: python -B -I who.py merged.prof MODULE:FUNC [MODULE:FUNC ...]
MODULE is a file basename without .py; prints each match's own totals and its callers by cumulative time.
"""
import os
import pstats
import sys

st = pstats.Stats(sys.argv[1])
for want in sys.argv[2:]:
    mod, func = want.split(':')
    for (file, line, name), (cc, nc, tt, ct, callers) in st.stats.items():
        if os.path.basename(file) != mod+'.py' or name != func:
            continue
        print('%s:%d:%s  calls %d  tottime %.1f  cumtime %.1f' % (mod, line, name, nc, tt, ct))
        rows = sorted(callers.items(), key=lambda kv: -kv[1][3])[:8]
        for (cfile, cline, cname), stat in rows:
            print('    <- %-60s calls %9d cum %7.1f' % ('%s:%d:%s' % (os.path.basename(cfile), cline, cname),
                                                         stat[1], stat[3]))
