"""Write the declared r12 site changes for rekey_sites.py from a candidates file on a composition holding RF2's
private_heat_functionals_parallel_r1 (554e68b7); refuses other bytes.
    python -B mk_declared_r12.py COMPOSITION_ROOT CANDIDATES_JSON OUT_JSON

p20c-r4 (Plan 20 r12 and RF2 on Plan 18 r5) changes five folded helpers. Every decision in four of them, and all but
two in the fifth, moves along its file's own line map (rekey_sites.py). Only RF2's two `carry` decisions have no
move: RF2 rewrote both embedded sources, so their lines changed. The rewritten sources hold no machine path (the
MPFR path is now _ASSEMBLY_MPFR_PATH, joined from sys.exec_prefix), so neither line is an abs site any more and
both carries retire. No site is added. Refused unless the candidates file has no site at either retired id and no
abs site anywhere in the module. (Rehearsed on p20c-r3 as r3p-rehearsal/mk_declared_r12.py, same declaration.)
"""
from hashlib import sha256
import json
from pathlib import Path
import sys
root, cand, out = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_bytes()), Path(sys.argv[3])
MODULE, WANT = 'private_heat_functionals_parallel_r1', '554e68b78da4'
got = sha256((root/'helpers'/(MODULE + '.py')).read_bytes()).hexdigest()
if not got.startswith(WANT):
    sys.exit('FAIL: %s is %s, not RF2 %s' % (MODULE, got[:12], WANT))
WHY = ('RF2 (Plan 20 r3/r4) rewrote this embedded source without its machine path: the MPFR library path is now '
       '_ASSEMBLY_MPFR_PATH, joined from sys.exec_prefix and injected. The line changed and is no longer an abs '
       'site, so the R2 carry of %s retires')
retire = {
    MODULE + ':999:25:abs': WHY % '_NATIVE_BINDING_SOURCE (FP:999)',
    MODULE + ':1006:26:abs': WHY % '_ASSEMBLY_POLICY_SOURCE (FP:1006)',
}
sites = {r['site'] for r in cand['sites']}
if sites & set(retire):
    sys.exit('FAIL: the candidates still have %s' % sorted(sites & set(retire)))
left = sorted(s for s in sites if s.startswith(MODULE + ':') and s.endswith(':abs'))
if left:
    sys.exit('FAIL: %s still has abs sites %s' % (MODULE, left))
with open(out, 'x', encoding='utf8', newline='\n') as f:
    json.dump(dict(why='Plan 20 RF2 (%s %s), declared for the r4 fold' % (MODULE, WANT[:8]),
                   retire=retire, add={}), f, indent=1, sort_keys=True)
    f.write('\n')
print(json.dumps(dict(retire=len(retire), add=[])))
