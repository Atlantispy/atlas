"""Phase-derived accounting for the unchanged private interval certificate.

Owned exact observations precede this module. MPFR admission counts the source's
simultaneous rectangular, Gram, inverse and physical-bound generations at the
requested precision; dyadic export is a distinct, exponent-derived stage.
No exact rank/Gram fallback, geometry, imports or whole method is admitted.
The installed recycled-slot/scratch conventions are ACCOUNTED POLICIES, not
allocator or OS-RSS proofs. This module neither changes precision nor computes
coefficients while estimating sizes.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from hashlib import sha256
from itertools import chain
from pathlib import Path
import sys

import private_heat_low_ledger_inventory_r1 as L
import private_heat_interval_inventory_r1 as I
import private_heat_decimal_inventory_r1 as D

HERE = Path(__file__).resolve().parent
PINS = {
    'private_heat_certification_kernel_r1.py': '3be44650802e629bedeaf20ce2b70cd88a14f12ee83571e8560e10a5b1157241',
    'private_heat_gmp_resources_r1.py': '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca',
    'private_heat_low_ledger_inventory_r1.py': '2f85972e16c11d7a21a2ff6f94a996ddd37b543dcc4787d1142eff6c23c1bf60',
    'private_heat_interval_inventory_r1.py': '6ee4bf826a84efb236abd7fd42dfc4960ec0b1fc040bcbb59d0183a2d4428623',
    'private_heat_decimal_inventory_r1.py': 'ded95d895acd84dc3d6e858054a7b21d5a58cb45c9f07790b676c2ad926a02b5',
}


def check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Interval certificate inventory cancelled')


def size(value):
    if type(value) is not int or not 0 <= value <= sys.maxsize:
        raise OverflowError('Certificate accounting exceeds addressable storage')
    return value


@dataclass(frozen=True)
class Plan:
    phase: str
    components: tuple
    counts: tuple
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    exact_fallback_admitted: bool = False
    whole_method_admission: bool = False

    @property
    def total(self):
        return size(sum(count for _, count in self.components))


def metadata_bytes(matrix, rhs, conversion, tau, G, cancel):
    """No rational getters/copies before this scalar-only metadata envelope."""
    if (type(matrix) not in (list, tuple) or not matrix or type(rhs) not in (list, tuple)
            or not rhs or type(conversion) not in (list, tuple)):
        raise ValueError('Owned rectangular observations/target/conversion required')
    m, n = len(matrix), len(rhs)
    if any(type(row) not in (tuple, list) or len(row) != n for row in matrix) or len(conversion) != m:
        raise ValueError('Matching rectangular observation dimensions required')
    largest = objects = 1
    for values in chain(matrix, (rhs, conversion, (tau,))):
        for value in values:
            check(cancel)
            if type(value) not in (int, G.mpq):
                raise TypeError('Already owned exact int/GMP rational operands required')
            largest = max(largest, sys.getsizeof(value))
            objects += 1
    import private_heat_gmp_resources_r1 as R
    # Shape matrices, scalar getter copies, source hash chunks and source-local
    # metadata generations. The incoming numeric objects remain caller-owned.
    return size(262144+D.CONTAINER_UNIT*(4*objects+32)
                +R.native_workspace_allowance(8*largest, 32)), largest


def verify_sources(cancel):
    D._runtime(cancel)
    for name, expected in PINS.items():
        digest = sha256()
        with (HERE/name).open('rb') as stream:
            while block := stream.read(65536):
                check(cancel)
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError('Reviewed certificate dependency changed: '+name)


def screen_plan(matrix, rhs, conversion, tau, G, R, cancel):
    """Bound singleton constraint division, base jump and encoded witnesses."""
    ar = L.RationalGrowth(G, R, cancel)
    m, n = len(matrix), len(rhs)
    target = [ar.q(v) for v in rhs]
    factors, jump = [ar.q(v) for v in conversion], ar.q(tau)
    shapes = [[ar.q(v) for v in row] for row in matrix]
    exact_slots = codec = 0
    forced_shapes = []
    for j in range(n):
        # Screen every possible singleton without selecting a tolerance rank.
        possible = []
        for i, row in enumerate(matrix):
            if row[j]:
                value = ar.op('divide', target[j], shapes[i][j])
                output = ar.op('multiply', ar.op('add', value, jump), factors[i])
                possible.append((value, output))
        if possible:
            value, output = (ar.choice([pair[k] for pair in possible]) for k in (0, 1))
            forced_shapes.append(output)
            exact_slots += 8*(ar.slot(value)+ar.slot(output))
            # At most n witnesses, each containing coefficient/target/value.
            for shape in (ar.choice([row[j] for row in shapes]), target[j], value):
                rs = R.RationalShape(shape.numerator, shape.denominator)
                codec += 3*R.hex_buffers_allowance(rs, ascii_copies=2, utf8_copies=0)
    plan = Plan('exact-singleton-screen', (
        ('exact_values_and_generations', exact_slots), ('encoded_witnesses', codec),
        ('containers_and_all_attempt_audits', D.CONTAINER_UNIT*(12*m+40*n+256)),
        ('scalar_workspace', ar.scalar_work(rational_slots=32))), (('observations', m), ('columns', n)))
    return plan


def interval_plan(m, n, precision, largest_owned_bytes, R):
    if type(precision) is not int or precision <= 0:
        raise ValueError('Positive declared precision required')
    # All source-local generations overcharged simultaneously: m/b/columns,
    # a/r/ri/inverse-working rows/a_columns, xhat/residual/dual, physical result
    # maps, per-dot conversions and old/new inverse rows. Reference aliases are
    # counted as values, not used to claim a smaller allowance.
    slots = 4*m*n+18*n*n+32*n+12*(m+2)+128
    mpfr_slot = 256+8*max(64, (precision+63)//64+2)
    containers = D.CONTAINER_UNIT*(6*m*n+14*n*n+40*m+64*n+256)
    work_bits = size(8*largest_owned_bytes+8*precision)
    return Plan('directed-interval-'+str(precision), (
        ('simultaneous_mpfr_slots', size(slots*mpfr_slot)),
        ('container_reference_generations', size(containers)),
        ('conversion_and_scalar_workspace', R.native_workspace_allowance(work_bits, slots))),
        (('observations', m), ('columns', n), ('precision_bits', precision), ('mpfr_slots', slots)))


def endpoint_shape(value, G, ar):
    """No MPFR->mpq conversion until this exponent-derived shape is funded."""
    if type(value) is G.mpq:
        return ar.q(value)  # caller already funds exact-screen getter workspace
    if type(value) is not G.mpfr or not G.is_finite(value):
        raise ValueError('Finite owned MPFR or exact rational endpoint required')
    if not value:
        return L.ZERO
    precision, exponent = value.precision, G.get_exp(value)
    # x = integer_significand * 2**(exponent-precision); cancellation of powers
    # of two only reduces both parts. No large integer is materialised here.
    return I.Shape(precision+max(0, exponent-precision), max(0, precision-exponent)+1, True)


def export_plan(bounds, dual, proof, G, R, cancel):
    ar = L.RationalGrowth(G, R, cancel)
    retained = scratch = largest_bits = 1
    count = 0
    for pair in (*bounds.values(), *dual):
        for value in pair:
            check(cancel)
            shape = endpoint_shape(value, G, ar)
            count += 1
            retained += ar.slot(shape)
            bits = shape.numerator+shape.denominator
            largest_bits = max(largest_bits, bits)
            # Exact GMP export, mpz getter, Python-int/Decimal conversion used
            # by the ORIGINAL round_bounds; repeated copies explicitly funded.
            scratch += 6*ar.slot(shape)+4*D.decimal_slot(max(shape.numerator, shape.denominator))
    for value in proof.values():
        if type(value) is G.mpfr:
            shape = endpoint_shape(value, G, ar)
            retained += ar.slot(shape)
            largest_bits = max(largest_bits, shape.numerator+shape.denominator)
    retained += D.CONTAINER_UNIT*(8*len(bounds)+4*len(dual)+64)+len(bounds)*D.decimal_slot(80)
    return Plan('exact-dyadic-export-and-original-rounding', (
        ('retained_values_and_output_containers', size(retained)),
        ('simultaneous_export_decimal_copies', size(scratch)),
        ('scalar_export_workspace', R.native_workspace_allowance(largest_bits, 32))),
        (('endpoint_values', count), ('largest_export_bits', largest_bits)))
