"""r2-only regression: H1c r2's mutable upper-case module lists are captured by the issuer's
LoadedIdentity constants, so the first inlined rational() call changes the loaded identity and
a later verify() (as private_heat_native_issuer_r13._verify_implementation does) refuses.
Control: the original module and H1a r2 alone keep a stable identity."""
import importlib.util
import sys
import time
from pathlib import Path

import common_r2 as C
import private_heat_loaded_identity_r1 as LOADED

t0 = time.process_time()
OUT = Path(__file__).resolve().parent/'loaded_r2'
for label, text in (('original', C.SOURCE), ('h1a_r2', C.AFTER_A), ('h1a_h1c_r2', C.AFTER_C)):
    name = 'refute_identity_'+label
    path = OUT/(name+'.py')
    path.write_bytes(text.encode('utf8'))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    guard = LOADED.LoadedIdentity([module])
    a = module.Arithmetic(C.Work(), C.G, scalar_slots=77, container_bytes=999, initial_bits=8)
    before = C.outcome(lambda: guard.verify([module]))
    a.rational('add', C.G.mpq(1, 3), 2)
    after = C.outcome(lambda: guard.verify([module]))
    print('%-11s verify before rational: %-6s after: %s' % (label, before[0], after))
print('cpu s', round(time.process_time()-t0, 2))
