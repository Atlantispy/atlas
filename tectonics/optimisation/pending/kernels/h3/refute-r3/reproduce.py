import importlib.util, sys
from hashlib import sha256
from pathlib import Path
CK = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('t', CK/'transforms/h3_compiled_dot.py'); T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
kin = (CK/'l2/helpers/private_heat_certification_kernel_r1.py').read_bytes()
rin = (CK/'l2/helpers/private_heat_certification_resources_r1.py').read_bytes()
print('l2 kernel in', sha256(kin).hexdigest()[:8], 'resources in', sha256(rin).hexdigest()[:8])
kout = T.transform(kin.decode('utf8')).encode('utf8')
rout = T.repin(rin.decode('utf8'), sha256(kin).hexdigest(), sha256(kout).hexdigest()).encode('utf8')
for name, data, other in (('kernel', kout, 'l3r3/helpers/private_heat_certification_kernel_r1.py'), ('resources', rout, 'l3r3/helpers/private_heat_certification_resources_r1.py')):
    print(name, 'transform(l2) == l3r3:', data == (CK/other).read_bytes(), '== work/h3out-r3:', data == (CK/'work/h3out-r3'/Path(other).name).read_bytes())
print('work/h3out-r3 helper == h3 helper:', (CK/'work/h3out-r3/private_heat_compiled_dot_r1.py').read_bytes() == (CK/'h3/private_heat_compiled_dot_r1.py').read_bytes())
# helper r3 vs r2 token-level diff: only the renamed identifier
import tokenize, io
def toks(p):
    return [(t.type, t.string) for t in tokenize.generate_tokens(io.StringIO(Path(p).read_text(encoding='utf8')).readline) if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE)]
a = toks(CK/'h3/archive/private_heat_compiled_dot_r1.62c100cf.py'); b = toks(CK/'h3/private_heat_compiled_dot_r1.py')
print('helper token count r2/r3', len(a), len(b), 'diff positions', [(x[1], y[1]) for x, y in zip(a, b) if x != y][:20], 'distinct pairs')
# docstring differs (string token); list differing tokens
print(set((x[1][:40], y[1][:40]) for x, y in zip(a, b) if x != y))
a = toks(CK/'l2/helpers/private_heat_certification_kernel_r1.py')
