"""Derived accounted policy for exact endpoint assembly, not an RSS theorem.

The supplied rows already exist under their caller's lease. This streaming
metadata pass bounds the exact sum/product sizes separately for every assembled
coefficient, exploiting only proved power-of-two denominators. It changes no
arithmetic or rounding. GMP/Decimal scratch uses the installed native accounting
policy, not a guarantee about an allocator, caches, imports or reconstruction.
"""

from concurrent.futures import CancelledError
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import sys

from atlas_tectonics._private.integration.heat import endpoint_assembly as A


@dataclass(frozen=True)
class Shape:
    numerator: int
    denominator: int
    dyadic: bool


def add_shape(a, b):
    if a.dyadic and b.dyadic:
        d = max(a.denominator, b.denominator)
        return Shape(max(a.numerator+d-a.denominator,
                         b.numerator+d-b.denominator)+1, d, True)
    return Shape(max(a.numerator+b.denominator, b.numerator+a.denominator)+1,
                 a.denominator+b.denominator, False)


def multiply_shape(a, b):
    dyadic = a.dyadic and b.dyadic
    # For dyadic shapes keep the EXACT virtual power-of-two denominator,
    # even if the real arithmetic reduces it. An overstated denominator
    # without a matching numerator rescale would invalidate later alignment.
    return Shape(a.numerator+b.numerator, a.denominator+b.denominator-int(dyadic), dyadic)


@dataclass(frozen=True)
class InventoryPlan:
    inventory: A.DiagnosticInventory
    components: tuple
    coefficients: int
    maximum_accumulator_bits: int
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    whole_method_admission: bool = False


def derive(rows, cells, boundary, *, witness, budget, cancel=None):
    """Inspect typed owned rows; return inventory for unchanged A.assemble.

    No rows/coefficients/Decimal digit arrays are copied. Temporary shape maps
    have an admitted contribution-count bound. Admitted metadata work survives
    escaped failures using the native workspace rule. Caller must not mutate
    input objects between this inspection and the immediately following solve.
    """
    def check():
        if cancel is not None and cancel():
            raise CancelledError('Endpoint inventory cancelled')

    check()
    gmp = A._library()
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    from atlas_tectonics.integration.coupling.spatial_transport import _json_encoding_capacity

    def owned_bytes(value):
        if type(value) is Fraction:
            return sys.getsizeof(value)+sys.getsizeof(value.numerator)+sys.getsizeof(value.denominator)
        return sys.getsizeof(value)

    # Counts and scalar sizes only before any per-coefficient map is created.
    weights = owners = input_bytes = 0
    largest = 2048
    for row in rows:
        check()
        weights += len(row['bounds'])
        owners += len(row['owners'])*len(row['bounds'])
        input_bytes += 2048+4*len(row['face_id'])+1024*len(row['ordered_keys'])
        for key, pair in row['bounds'].items():
            input_bytes += 512+sum(sys.getsizeof(item) for item in key)
            for value in pair:
                size = owned_bytes(value)
                input_bytes += size
                largest = max(largest, size)
    for key, entry in boundary.items():
        size = owned_bytes(entry[1])
        input_bytes += 1024+4*len(key)+size
        largest = max(largest, size)
    scan_bytes = (1 << 20)+2048*(owners+cells+len(boundary))+16*largest
    with R.OwnedWorkspace(budget, scan_bytes, category='heat-endpoint-inventory-metadata', cancelled=cancel):
        witness_bytes, witness_codec = _json_encoding_capacity(witness, budget)
        input_bytes += witness_codec+sys.getsizeof(rows)+sys.getsizeof(boundary)

        def shape(value):
            check()
            if type(value) in (Fraction, gmp.mpq):
                n, d = value.numerator, value.denominator
            elif type(value) is int:
                n, d = value, 1
            elif type(value) is float:
                n, d = value.as_integer_ratio()
            else:
                raise ValueError('Unsupported owned rational type')
            return Shape(max(1, n.bit_length()), d.bit_length(), d.bit_count() == 1)

        zero = Shape(1, 1, True)
        wall = [[zero, zero] for _ in range(cells)]
        op = {}
        max_bits = conversion_bits = 1
        retained_endpoint_bytes = 0
        bshape = {key: shape(entry[1]) for key, entry in boundary.items()}
        for row in rows:
            for key, pair in row['bounds'].items():
                check()
                kind, index = key
                bounds = tuple(map(shape, pair))
                for s in bounds:
                    conversion_bits = max(conversion_bits, s.numerator+s.denominator)
                for owner, sign in row['owners']:
                    if kind == 'cell':
                        target = op.setdefault((owner, index), [zero, zero])
                    elif kind in ('wall', 'power') and index in bshape:
                        bounds = tuple(multiply_shape(s, bshape[index]) for s in map(shape, pair))
                        if boundary[index][1] < 0:
                            bounds = tuple(reversed(bounds))
                        target = wall[owner]
                    else:
                        raise ValueError('Complete declared physical observations required')
                    # Negative scale swaps endpoints. Both widths are covered.
                    incoming = bounds if sign == 1 else tuple(reversed(bounds))
                    for j in (0, 1):
                        a, b = target[j], incoming[j]
                        result = add_shape(a, b)
                        max_bits = max(max_bits, 4*(a.numerator+a.denominator+b.numerator+b.denominator))
                        conversion_bits = max(conversion_bits, result.numerator+result.denominator)
                        target[j] = result
        for pair in list(op.values())+wall:
            for s in pair:
                retained_endpoint_bytes += R.native_slot_allowance(R.RationalShape(s.numerator, s.denominator))
        # Both endpoint quotients, exact integer copies, Decimal coefficients,
        # and neighbouring rounding-cell midpoints coexist. A bit is a safe
        # upper bound for a decimal digit count. Decimal80-generated exponents
        # cannot exceed the inspected rational bit scales plus precision.
        round_bits = 8*(conversion_bits+1024)
        scalar = R.native_workspace_allowance(max(max_bits, round_bits), 64)
        decimal = 16*512*max(1, (conversion_bits+1024+79)//80)
        containers = 2048*(weights+owners+cells+len(rows)+len(boundary)+1)
        codec = 2*witness_codec+4*witness_bytes
        # CertifiedFace and RoundedFace generations, Decimal values/slots,
        # immutable operator/wall tuples, signatures, witness and plan records.
        result = (4096+2048*(2*len(rows)+cells+len(boundary))
                  +1024*(weights+len(op)+cells)+2*witness_bytes)
        work = scalar+decimal+containers+retained_endpoint_bytes+codec+scan_bytes
        inventory = A.DiagnosticInventory(max(1, input_bytes), work, result,
            'Derived per-coefficient exact growth and installed GMP/Decimal/container policy; '
            'dyadic denominator sharing proved, no arithmetic changed; not allocator/RSS or whole-method admission.')
        inventory.total()
        check()
        return InventoryPlan(inventory, (('exact_accumulators', retained_endpoint_bytes),
            ('native_scalar_work', scalar), ('decimal_conversion', decimal), ('containers', containers),
            ('metadata_scan', scan_bytes), ('codec', codec)), len(op)+cells, conversion_bits)
