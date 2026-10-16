"""S6 (H5): callees of _face and _prepare in a W4 parent profile (refinement pass is serial there). Read-only."""
import os, pstats, sys
S = pstats.Stats(sys.argv[1]).stats
def short(k):
    return '%s:%d(%s)' % (os.path.basename(k[0]), k[1], k[2])
for parent in (('functionals_kernel_r5', '_face'), ('functionals_kernel_r5', '_prepare'),
               ('functionals_kernel_r5', 'reconstruct'), ('functionals_kernel_r5', 'observation')):
    print('== callees of', parent)
    sub = []
    for k, (cc, nc, tt, ct, callers) in S.items():
        for ck, v in callers.items():
            if ck[2] == parent[1] and parent[0] in ck[0]:
                sub.append((v[3], v[2], v[1], k))
    sub.sort(reverse=True)
    for ct, tt, nc, k in sub[:10]:
        print('  %8.3f cum %8.3f self %8d calls  %s' % (ct, tt, nc, short(k)))
