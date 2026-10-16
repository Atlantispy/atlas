"""q06 arm-1 stop: does the H3 kernel's per-process route cache change Heat's loaded identity?

Usage: python -B repro.py LAYOUT [CACHE_NAME]. Imports the layout's certification kernel, captures
private_heat_loaded_identity_r1.LoadedIdentity over it, records on the cache what _h3_module() records on
the compiled route (without loading or compiling the helper) and verifies again.
"""
import json
import sys
import types
from pathlib import Path

layout = Path(sys.argv[1]).resolve()
cache = sys.argv[2] if len(sys.argv) > 2 else '_H3'
sys.path[:0] = json.loads((layout/'control.json').read_text(encoding='utf8'))['paths']
import private_heat_certification_kernel_r1 as K  # noqa: E402
import private_heat_loaded_identity_r1 as LI  # noqa: E402

identity = LI.LoadedIdentity([K])
identity.verify([K])
getattr(K, cache).append((types.ModuleType(K._H3_NAME), 'compiled'))
try:
    identity.verify([K])
    after = 'unchanged'
except ValueError as error:
    after = 'ValueError: %s' % error
print(json.dumps(dict(kernel=K.__file__, cache=cache, upper=cache.isupper(), verify_after_load=after)))
