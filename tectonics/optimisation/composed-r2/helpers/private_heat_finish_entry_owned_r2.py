"""Getter-safe fixed arithmetic with exact canonical-component equality.

GMP mpq values from the supported constructors and arithmetic are canonical:
coprime numerator/denominator, positive denominator and unique zero0/1.
Two such values are equal exactly when both integer components are equal.
No rational cross products are computed by this override. Getter copies are
funded before extraction, and the existing64 scalar slots and128*bits native
policy cover the four simultaneous mpz parts. No tolerance or ambient MPFR
precision participates; ordering comparisons retain their previous policy.

The proof is the GMP canonical-rational contract; no projection decoder,
saved-output acceptance or backend selection is imported here.
"""
from hashlib import sha256
from pathlib import Path

import private_heat_finish_entry_owned_r1 as BASE

getter_envelope = BASE.getter_envelope
_SOURCES = dict(BASE._SOURCES)
_SOURCES[str(Path(__file__).resolve())] = sha256(Path(__file__).read_bytes()).hexdigest()


class Arithmetic(BASE.Arithmetic):
    def equal(self, left, right):
        if any(type(value) not in (int, self.G.mpq) for value in (left, right)):
            raise TypeError('Already owned canonical mpq or exact int equality operands required')
        # BASE.shape owns its transient getters and drops them before return.
        # Renew a full scalar envelope for the actual component widths before
        # the following four getter copies can coexist. Do not add opposite
        # denominator widths: no such products are executed here.
        a, b = self.shape(left), self.shape(right)
        parts = (a.numerator_bits, a.denominator_bits,
                 b.numerator_bits, b.denominator_bits)
        self.reserve(max(parts))
        self.equality_evidence = dict(part_bits=parts, required_part_bits=max(parts),
            unused_cross_product_bits=max(a.numerator_bits+b.denominator_bits,
                                          b.numerator_bits+a.denominator_bits))
        ln, ld = (left, 1) if type(left) is int else (left.numerator, left.denominator)
        rn, rd = (right, 1) if type(right) is int else (right.numerator, right.denominator)
        self.operations += 1
        return ln == rn and ld == rd
