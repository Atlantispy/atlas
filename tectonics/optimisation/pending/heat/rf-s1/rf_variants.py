"""Run the AUTHOR'S test suite against deliberately wrong r5 variants; report which are detected."""
import importlib.util
import io
import json
import sys
import contextlib
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
LAYOUT, S1 = T/'hs'/'lh', T/'hs'/'s1'
HERE = T/'hs'/'rf-s1'
TEST = T/'hs'/'tests'/'test_s1_closed_reuse.py'
base = (S1/'private_heat_closed_owned_r5.py').read_text(encoding='utf8')
r11 = (S1/'private_heat_finish_kernel_r11.py').read_bytes()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


UNPACK = "    tested, tested_energies, tested_faces, certificate = reused\n"
FACES = "    for before, after in zip(tested_faces, faces, strict=True):\n"
VARIANTS = {
    'V0-control-unmodified': [],
    'V1-no-shallow-copy': [("    return dict(certificate)\n\n\ndef _guard", "    return certificate\n\n\ndef _guard")],
    'V2-no-staleness-checks': [(UNPACK, UNPACK+"    return dict(certificate)\n")],
    'V3-no-face-check': [(FACES, "    return dict(certificate)\n"+FACES)],
    'V4-energies-first-only': [("if not _equal_arrays(ar, tested_energies, energies):",
                                "if not _equal_arrays(ar, tested_energies[:1], energies[:1]):")],
    'V5-faces-first-only': [(FACES, "    for before, after in zip(tested_faces[:1], faces[:1], strict=True):\n")],
    'V6-module-level-flag-cache': [("known = {zero: low_check['passed'], one: full_check['passed']}",
        "known = _KNOWN\n    known.setdefault(zero, low_check['passed'])\n    known.setdefault(one, full_check['passed'])"),
        ("def _proof_numbers(value):", "_KNOWN = {}\n\n\ndef _proof_numbers(value):")],
    'V7-swapped-endpoint-flags': [("known = {zero: low_check['passed'], one: full_check['passed']}",
                                   "known = {zero: full_check['passed'], one: low_check['passed']}")],
    'V8-energies-compare-self': [("if not _equal_arrays(ar, tested_energies, energies):",
                                  "if not _equal_arrays(ar, tested_energies, tested_energies):")],
}

results = {}
for name, edits in VARIANTS.items():
    d = HERE/('var_'+name.split('-')[0])
    d.mkdir(exist_ok=True)
    text = base
    for old, new in edits:
        text = once(text, old, new)
    (d/'private_heat_closed_owned_r5.py').write_bytes(text.encode('utf8'))
    (d/'private_heat_finish_kernel_r11.py').write_bytes(r11)
    for mod in [m for m in sys.modules if m in ('private_heat_closed_owned_r5', 'private_heat_finish_kernel_r11')]:
        del sys.modules[mod]
    sys.argv = ['t', str(LAYOUT), str(d)]
    spec = importlib.util.spec_from_file_location('s1test_'+name.split('-')[0], TEST)
    m = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    crashed = None
    try:
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(m)
            for step in (m.differential, m.mutants, m.finish_kernel):
                try:
                    step()
                except BaseException as e:  # noqa: BLE001
                    crashed = (step.__name__, type(e).__name__, str(e)[:100])
                    break
    finally:
        pass
    bad = [n for n, ok in m.REPORT if not ok]
    results[name] = (len(m.REPORT), bad, crashed)
    print('%-30s cases %2d failed %s crashed %s' % (name, len(m.REPORT), bad, crashed))

# real r5: staleness at the LAST index must also be refused (author's mutants only perturb index 0)
for mod in [m_ for m_ in sys.modules if m_ in ('private_heat_closed_owned_r5', 'private_heat_finish_kernel_r11')]:
    del sys.modules[mod]
sys.argv = ['t', str(LAYOUT), str(S1)]
spec = importlib.util.spec_from_file_location('s1test_last', TEST)
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m)
import tempfile
G = m.G
LAST = {
    'energies-last-cell': ("    del states\n", "    del states\n    ar.put(difference, 5, ar.op('add', difference[1][5], G.mpq(1, 7)))\n"),
    'faces-last-interior': ("    del states\n", "    del states\n    ar.put(dq, 6, ar.op('add', dq[1][6], G.mpq(1, 7)))\n"),
    'faces-exterior-last': ("    del states\n", "    del states\n    ar.put(dq, 7, ar.op('add', dq[1][7], G.mpq(1, 7)))\n"),
    'energy+face-consistent-shift (ledger preserving)': ("    del states\n",
        "    del states\n    ar.put(difference, 0, ar.op('add', difference[1][0], G.mpq(1, 7)))\n"
        "    ar.put(difference, 1, ar.op('subtract', difference[1][1], G.mpq(1, 7)))\n"
        "    ar.put(dq, 0, ar.op('add', dq[1][0], G.mpq(-1, 7)))\n"),
}
with tempfile.TemporaryDirectory() as folder:
    for k, (name, (old, new)) in enumerate(LAST.items()):
        path = Path(folder)/('last_%d.py' % k)
        path.write_bytes(m.once(base, old, new).encode('utf8'))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                out = m.run(m.load(path, 'last_mod_%d' % k), 'full')
            print('LAST-INDEX', name, '-> NOT REFUSED', out[0][0])
        except Exception as e:  # noqa: BLE001
            print('LAST-INDEX', name, '->', type(e).__name__, str(e)[:90])
