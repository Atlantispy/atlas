"""S6 (H5) read-only pstats query over the W4 worker profiles. Writes nothing."""
import glob, os, pstats, sys
D = sys.argv[1]
files = sorted(glob.glob(os.path.join(D, 'worker-*.prof')))
st = pstats.Stats(files[0])
for f in files[1:]:
    st.add(f)
S = st.stats  # key -> (cc, nc, tt, ct, callers)
def short(k):
    return '%s:%d(%s)' % (os.path.basename(k[0]), k[1], k[2])
rows = []
for k, (cc, nc, tt, ct, callers) in S.items():
    rows.append((ct, tt, nc, k))
rows.sort(reverse=True)
print('files', len(files))
print('== top cumulative (private_heat / functionals) ==')
n = 0
for ct, tt, nc, k in rows:
    if 'private_heat' in k[0] or 'functional' in k[0]:
        print('%9.1f cum %8.1f self %10d calls  %s' % (ct, tt, nc, short(k)))
        n += 1
        if n >= 60:
            break
print('== named prelude / route functions ==')
want = ('_face', 'reconstruct_faces', 'support', 'basis', 'second_moment', 'functional_bounds',
        'point', 'flux', 'target', 'full_ranking', 'assess_weights', 'reduce_observations',
        'exact_face', '_attempt', 'forced_coefficients', '_prepare', 'reconstruct', 'observation',
        'screen_plan', 'metadata_bytes', 'verify_sources', '_verify', 'multiply', 'total', 'op')
for ct, tt, nc, k in rows:
    if k[2] in want and ('private_heat' in k[0] or 'functional' in k[0]):
        print('%9.1f cum %8.1f self %10d calls  %s' % (ct, tt, nc, short(k)))
# callers of _face's direct callees: print callees of _face
print('== callees of _face ==')
for k in S:
    if k[2] == '_face' and 'functionals_kernel_r5' in k[0]:
        fk = k
        print('face key', short(fk), 'calls', S[fk][1], 'cum', round(S[fk][3], 1))
callees = []
for k, (cc, nc, tt, ct, callers) in S.items():
    for ck, v in callers.items():
        if ck[2] == '_face' and 'functionals_kernel_r5' in ck[0]:
            # v = (cc, nc, tt, ct) for this caller edge
            callees.append((v[3], v[2], v[1], k))
callees.sort(reverse=True)
for ct, tt, nc, k in callees[:30]:
    print('%9.1f cum %8.1f self %10d calls  %s' % (ct, tt, nc, short(k)))
print('== callees of _face.<locals>.observation and functional_bounds ==')
for name in ('observation', 'functional_bounds', '_build'):
    sub = []
    for k, (cc, nc, tt, ct, callers) in S.items():
        for ck, v in callers.items():
            if ck[2] == name and ('private_heat' in ck[0]):
                sub.append((v[3], v[2], v[1], k, ck))
    sub.sort(reverse=True)
    for ct, tt, nc, k, ck in sub[:12]:
        print('[%s<-%s] %9.1f cum %8.1f self %10d calls  %s' % (name, os.path.basename(ck[0]), ct, tt, nc, short(k)))
