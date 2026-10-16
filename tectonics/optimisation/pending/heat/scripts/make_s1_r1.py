"""Generate S1 (closed-guard endpoint certificate reuse) as NEW files from the pinned r4/r10 texts.

Usage: python -B make_s1_r1.py HELPERS_DIR OUT_DIR
HELPERS_DIR holds private_heat_closed_owned_r4.py (62b7ffc42c82...) and private_heat_finish_kernel_r10.py
(31ed7a29c5ee...); OUT_DIR must not exist. Every edit is an exact-once replacement, so a moved anchor refuses.
Writes private_heat_closed_owned_r5.py and private_heat_finish_kernel_r11.py (LF, UTF-8) and prints their digests.
"""
from hashlib import sha256
from pathlib import Path
import sys

R4 = 'private_heat_closed_owned_r4.py'
R10 = 'private_heat_finish_kernel_r10.py'
PINS = {R4: '62b7ffc42c82', R10: '31ed7a29c5ee'}


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit('anchor not found exactly once: %r' % old[:80])
    return text.replace(old, new)


def closed_r5(text):
    text = once(text, '''endpoint proofs, scalar slots, containers and history stay additive.
"""
''', '''endpoint proofs, scalar slots, containers and history stay additive.

R5 is R4 with exact endpoint reuse in the guard. The theta 0 and theta 1
certificates are computed in full first; the scalar search and the result
certificate reuse them for an equal exact theta instead of recomputing them.
A reused certificate is accepted only for the exact theta it was computed at
and only when the state it certified equals the result's freshly computed
state, value by value; otherwise the guard refuses. Values, the selection
history and all three returned certificates are unchanged.
"""
''')
    text = once(text, '''def _guard(ar, old, cap, low, candidate, low_faces, candidate_faces, bounds):
''', '''def _reused_certificate(ar, theta, reused, energies, faces):
    """Return a copy of an endpoint certificate only for its own exact state.

    A certificate is a deterministic function of the guard's owned inputs and
    the exact theta. It is reused only for the theta it was computed at, and
    only when the energies and face transfers it certified equal the freshly
    computed result state exactly; anything else is stale and refused. The
    shallow copy keeps the endpoint certificate unchanged when the result
    certificate gains its stock-conservation entry.
    """
    tested, tested_energies, tested_faces, certificate = reused
    if type(tested) is not type(theta) or tested != theta:
        raise ArithmeticError('Stale closed-guard certificate: computed at another theta')
    if len(tested_energies) != len(energies) or len(tested_faces) != len(faces):
        raise ArithmeticError('Stale closed-guard certificate: certified state has another shape')
    if not _equal_arrays(ar, tested_energies, energies):
        raise ArithmeticError('Stale closed-guard certificate: certified energies differ')
    for before, after in zip(tested_faces, faces, strict=True):
        ar.check()
        if before[:2] != after[:2] or not ar.equal(before[2], after[2]):
            raise ArithmeticError('Stale closed-guard certificate: certified face transfers differ')
    return dict(certificate)


def _guard(ar, old, cap, low, candidate, low_faces, candidate_faces, bounds):
''')
    text = once(text, '''    def certificate(theta):
        energies, _, stocks, temperatures = state(theta)
''', '''    def certificate(theta, states=None):
        energies, faces, stocks, temperatures = state(theta)
        if states is not None:
            states[theta] = (theta, energies, faces)
''')
    text = once(text, '''    low_check, full_check = certificate(G.mpq(0)), certificate(G.mpq(1))
    def admissible(theta):
        mark = len(ar.arrays)
        cert = certificate(theta)
        passed = cert['passed']
        del cert
        ar.drop_to(mark)
        return passed
''', '''    states, zero, one = {}, G.mpq(0), G.mpq(1)
    low_check, full_check = certificate(zero, states), certificate(one, states)
    issued = {zero: (*states[zero], low_check), one: (*states[one], full_check)}
    del states
    # Each bool is the passed flag of a certificate computed directly at that
    # exact theta, so only a directly tested state replaces the lower endpoint.
    known = {zero: low_check['passed'], one: full_check['passed']}
    def admissible(theta):
        if theta in known:
            return known[theta]
        mark = len(ar.arrays)
        cert = certificate(theta)
        passed = cert['passed']
        del cert
        ar.drop_to(mark)
        known[theta] = passed
        return passed
''')
    text = once(text, '''    checked = certificate(theta)
    energies, faces, _, _ = state(theta)
''', '''    reused = issued.get(theta)
    checked = certificate(theta) if reused is None else None
    energies, faces, _, _ = state(theta)
    if reused is not None:
        checked = _reused_certificate(ar, theta, reused, energies, faces)
    del issued, reused
''')
    return text


def finish_r11(text):
    text = once(text, '''step of a metered call, and on stage lifetime r3. Nothing else differs.
"""
''', '''step of a metered call, and on stage lifetime r3. Nothing else differs.

R11 is R10 on closed owned r5 (exact endpoint certificate reuse in the closed
guard). Nothing else differs.
"""
''')
    return once(text, 'import private_heat_closed_owned_r4 as Q\n', 'import private_heat_closed_owned_r5 as Q\n')


def main():
    helpers, out = Path(sys.argv[1]), Path(sys.argv[2])
    texts = {}
    for name, pin in PINS.items():
        raw = (helpers/name).read_bytes()
        if not sha256(raw).hexdigest().startswith(pin) or b'\r' in raw:
            raise SystemExit('unexpected source %s' % name)
        texts[name] = raw.decode('utf8')
    made = {'private_heat_closed_owned_r5.py': closed_r5(texts[R4]),
            'private_heat_finish_kernel_r11.py': finish_r11(texts[R10])}
    out.mkdir(parents=True, exist_ok=False)
    for name, text in made.items():
        compile(text, name, 'exec')
        data = text.encode('utf8')
        (out/name).write_bytes(data)
        print(name, sha256(data).hexdigest())


if __name__ == '__main__':
    main()
