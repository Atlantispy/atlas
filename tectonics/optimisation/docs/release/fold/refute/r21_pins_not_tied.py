"""FALSE PASS across the gates: no gate ties a pin sha to file bytes except manifest['pins'].
- the pin literal in the folded module can be any hex64 (AST gate erases it; check_pins never reads code);
- sha_map's new sha (what B's re-pin must equal) is never compared with the folded file or with manifest['pins']."""
from hashlib import sha256
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

root = Path(__file__).resolve().parent/'case_pins'
shutil.rmtree(root, ignore_errors=True)
priv = root/'src'/'atlas_tectonics'/'_private'
priv.mkdir(parents=True)
(root/'src'/'atlas_tectonics'/'__init__.py').write_text('', encoding='utf8')
(priv/'__init__.py').write_text('', encoding='utf8')
(root/'src'/'atlas_tectonics'/'integration_spatial_transport.py').write_bytes(b'K = 1\n')
true_sha = sha256(b'K = 1\n').hexdigest()
wrong = sha256(b'some other bytes').hexdigest()
old = sha256(b'heat-repair copy').hexdigest()

orig = "PIN = '%s'\n" % old
folded = "PIN = '%s'\n" % wrong                       # wrong pin literal in the folded helper
(priv/'user_r1.py').write_bytes(folded.encode())
manifest = dict(pins={'atlas_tectonics.integration_spatial_transport': true_sha,
                      'atlas_tectonics._private.user_r1': sha256(folded.encode()).hexdigest()},
                key_map={'C:\\w\\heat-repair\\src\\atlas_tectonics\\integration_spatial_transport.py':
                         'atlas_tectonics/integration_spatial_transport.py'},
                sha_map={'atlas_tectonics/integration_spatial_transport.py': [old, wrong]},
                bookings=[], external=[], self_ids=[], modules={})
a = {'bindings': {'C:\\w\\heat-repair\\src\\atlas_tectonics\\integration_spatial_transport.py': old}}
b = {'bindings': {'atlas_tectonics/integration_spatial_transport.py': wrong}}   # wrong re-pin in the record
print('ast_equivalent(wrong pin literal) ->', P.ast_equivalent(orig, folded))
print('check_records(wrong re-pin in B)  ->', P.check_records(a, b, manifest)['status'])
print('check_pins                        ->', P.check_pins(root/'src', manifest)['status'])
print('true sha of the imported file     ->', true_sha[:16], '| pinned in code and B:', wrong[:16])
shutil.rmtree(root, ignore_errors=True)
