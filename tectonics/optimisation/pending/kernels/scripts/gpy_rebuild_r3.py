"""Rebuild the three G-PY copies with transforms/gpy_q2_jets.py r3 (16 Oct, delta refuter DEFECT A).

Usage: python -B -I gpy_rebuild_r3.py
Refuses unless the input is c5f2a123 in both base trees and every copy still holds r2 (b752e7b5);
r2 copies and records are in T/ck/gpy-r2-backup. Updates the gpy entry and the file digest in each
tree's TEST_COMPOSITION.json, after checking that json.dumps(indent=1) with CRLF line ends (as written
in text mode on Windows) reproduces the old bytes.
"""
import importlib.util
import json
from hashlib import sha256
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
CK = T/'ck'
REL = 'atlas_tectonics/integration_moving_face_moments.py'
IN_SHA, R1_SHA = ('c5f2a1230f9e13633ad92f9a251ee01e08bac0b2905d9fed90c042402adb8075',
                  'b752e7b513031afb2bd99ea60bcd46d9188cca352f8afac6a7f91f56542115da')
TRANSFORM = CK/'transforms'/'gpy_q2_jets.py'


def digest(b):
    return sha256(b).hexdigest()


def render(rec):
    return json.dumps(rec, indent=1).replace('\n', '\r\n').encode()


source = (T/'gg'/'final-f2'/REL).read_bytes()
assert digest(source) == IN_SHA and digest((T/'gg'/'jets-r1'/REL).read_bytes()) == IN_SHA
spec = importlib.util.spec_from_file_location('gpy_q2_jets_r3', TRANSFORM)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
new = mod.transform(source.decode('utf8')).encode('utf8')
new_sha, module_sha = digest(new), digest(TRANSFORM.read_bytes())
copies = [CK/'gpy'/'integration_moving_face_moments.py', CK/'gpy-f2'/REL, CK/'gpy-jets'/REL]
records = [CK/'gpy-f2'/'TEST_COMPOSITION.json', CK/'gpy-jets'/'TEST_COMPOSITION.json']
for p in copies:
    assert digest(p.read_bytes()) == R1_SHA, p
updated = []
for p in records:
    raw = p.read_bytes()
    rec = json.loads(raw)
    assert render(rec) == raw, 'format of %s not reproduced' % p
    entries = [t for t in rec['transforms'] if t['transform'] == 'gpy']
    assert len(entries) == 1 and entries[0]['output_sha256'] == R1_SHA and rec['files'][REL] == R1_SHA
    entries[0].update(module_sha256=module_sha, output_sha256=new_sha)
    rec['files'][REL] = new_sha
    updated.append((p, render(rec)))
for p in copies:
    p.write_bytes(new)
for p, b in updated:
    p.write_bytes(b)
print('transform', module_sha[:12], 'output', IN_SHA[:8], '->', new_sha)
for p in copies + records:
    print(digest(p.read_bytes())[:12], p.relative_to(CK).as_posix())
