"""Plan40B C3 explicit public receiving inventory successor.

All phase accounting and runtime checks are retained. Only dependency binding
changes to the actual imported selected public files; this does not authenticate
a historical private execution or activate a worker/checkpoint route.

Phase-derived accounting for the interval certificate.

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
from itertools import chain
import sys

from atlas_tectonics._private.integration.heat import low_ledger_inventory as L
from atlas_tectonics._private.integration.heat import endpoint_assembly_inventory as I
from atlas_tectonics._private.integration.heat import decimal_inventory as D

PUBLIC_BINDING = 'plan40b.c3.public-receiving.r2'


def check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Interval certificate inventory cancelled')


def size(value):
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
        return sum(count for _, count in self.components)


def metadata_bytes(matrix, rhs, conversion, tau, G, cancel):
    """No rational getters/copies before this scalar-only metadata envelope."""
    _, _ = len(matrix), len(rhs)
    largest = objects = 1
    for values in chain(matrix, (rhs, conversion, (tau,))):
        for value in values:
            check(cancel)
            largest = max(largest, sys.getsizeof(value))
            objects += 1
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    # Shape matrices, scalar getter copies, source hash chunks and source-local
    # metadata generations. The incoming numeric objects remain caller-owned.
    return (262144+D.CONTAINER_UNIT*(4*objects+32)
                +R.native_workspace_allowance(8*largest, 32)), largest


def screen_plan(matrix, rhs, conversion, tau, G, R, cancel, *, _with_support=False):
    """Bound singleton constraint division, base jump and encoded witnesses."""
    ar = L.RationalGrowth(G, R, cancel)
    m, n = len(matrix), len(rhs)
    target = [ar.q(v) for v in rhs]
    factors, jump = [ar.q(v) for v in conversion], ar.q(tau)
    shapes = [[ar.q(v) for v in row] for row in matrix]
    exact_slots = codec = 0
    forced_shapes = []
    support = [] if _with_support else None
    for j in range(n):
        # Screen every possible singleton without selecting a tolerance rank.
        possible = []
        supported = None
        for i, row in enumerate(matrix):
            if row[j]:
                supported = i if supported is None else -1
                value = ar.op('divide', target[j], shapes[i][j])
                output = ar.op('multiply', ar.op('add', value, jump), factors[i])
                possible.append((value, output))
        if support is not None:
            support.append(supported)
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
    return (plan, support) if _with_support else plan


def interval_plan(m, n, precision, largest_owned_bytes, R):
    # All source-local generations overcharged simultaneously: m/b/columns,
    # a/r/ri/inverse-working rows/a_columns, xhat/residual/dual, physical result
    # maps, per-dot conversions and old/new inverse rows. Reference aliases are
    # counted as values, not used to claim a smaller allowance.
    slots = 4*m*n+18*n*n+32*n+12*(m+2)+128
    mpfr_slot = 256+8*max(64, (precision+63)//64+2)
    containers = D.CONTAINER_UNIT*(6*m*n+14*n*n+40*m+64*n+256)
    work_bits = (8*largest_owned_bytes+8*precision)
    return Plan('directed-interval-'+str(precision), (
        ('simultaneous_mpfr_slots', (slots*mpfr_slot)),
        ('container_reference_generations', containers),
        ('conversion_and_scalar_workspace', R.native_workspace_allowance(work_bits, slots))),
        (('observations', m), ('columns', n), ('precision_bits', precision), ('mpfr_slots', slots)))


def endpoint_shape(value, G, ar):
    """No MPFR->mpq conversion until this exponent-derived shape is funded."""
    if type(value) is G.mpq:
        return ar.q(value)  # caller already funds exact-screen getter workspace
    if not value:
        return L.ZERO
    precision, exponent = value.precision, G.get_exp(value)
    # x = integer_significand * 2**(exponent-precision); cancellation of powers
    # of two only reduces both parts. No large integer is materialised here.
    return I.Shape(precision+max(0, exponent-precision), max(0, precision-exponent)+1, True)


def export_plan(bounds, dual, proof, G, R, cancel, *, retain_decimal=True):
    ar = L.RationalGrowth(G, R, cancel)
    retained = scratch = largest_bits = 1
    count = 0
    for pair in (*bounds.values(), *dual):
        for value in pair:
            check(cancel)
            shape = endpoint_shape(value, G, ar)
            count += 1
            slot = ar.slot(shape)
            retained += slot
            bits = shape.numerator+shape.denominator
            largest_bits = max(largest_bits, bits)
            # Exact GMP export, mpz getter, Python-int/Decimal conversion used
            # by the ORIGINAL round_bounds; repeated copies explicitly funded.
            scratch += 6*slot+4*D.decimal_slot(max(shape.numerator, shape.denominator))
    for value in proof.values():
        if type(value) is G.mpfr:
            shape = endpoint_shape(value, G, ar)
            retained += ar.slot(shape)
            largest_bits = max(largest_bits, shape.numerator+shape.denominator)
    retained += D.CONTAINER_UNIT*(8*len(bounds)+4*len(dual)+64)
    if retain_decimal:
        retained += len(bounds)*D.decimal_slot(80)
    elif bounds:
        scratch += 2*D.decimal_slot(80)
    return Plan('exact-dyadic-export-and-original-rounding', (
        ('retained_values_and_output_containers', retained),
        ('simultaneous_export_decimal_copies', scratch),
        ('scalar_export_workspace', R.native_workspace_allowance(largest_bits, 32))),
        (('endpoint_values', count), ('largest_export_bits', largest_bits)))
