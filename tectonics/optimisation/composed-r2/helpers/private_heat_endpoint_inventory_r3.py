"""Fast-rounding, zero-aware shape successor; executable assembly is unchanged.

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
import math
from pathlib import Path
import sys

import private_heat_interval_assembly_kernel_r1 as A
import private_heat_rounding_inventory_r1 as ROUND

ASSEMBLER_SHA = 'bdbd0f1e62668d48c958075ffb033e740ee147f163faa943893d01c24ae3de74'


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
    conversion: ROUND.ConversionGrowth
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    whole_method_admission: bool = False


def derive(rows, cells, boundary, *, witness, source_bindings, budget, cancel=None):
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
    if (type(rows) not in (tuple, list) or type(cells) is not int or cells <= 0
            or type(boundary) is not dict):
        raise ValueError('Typed owned rows, positive cells and plain boundary required')
    gmp = A._library()
    import private_heat_gmp_resources_r1 as R
    from atlas_tectonics.integration_spatial_transport import _json_encoding_capacity
    if hashlib.sha256(Path(A.__file__).read_bytes()).hexdigest() != ASSEMBLER_SHA:
        raise ValueError('Reviewed assembler changed')

    def owned_bytes(value):
        if type(value) is Fraction:
            return sys.getsizeof(value)+sys.getsizeof(value.numerator)+sys.getsizeof(value.denominator)
        if type(value) not in (int, float, gmp.mpq):
            raise ValueError('Only owned integer, binary64, Fraction or GMP rational endpoints supported')
        if type(value) is float and not math.isfinite(value):
            raise ValueError('Finite endpoint required')
        return sys.getsizeof(value)

    # Counts and scalar sizes only before any per-coefficient map is created.
    weights = owners = input_bytes = 0
    largest = 2048
    for row in rows:
        check()
        if type(row) is not dict or type(row.get('bounds')) is not dict:
            raise ValueError('Plain certified face dictionaries required')
        if type(row.get('owners')) not in (list, tuple) or len(row['owners']) not in (1, 2):
            raise ValueError('One/two physical owners required')
        if type(row.get('ordered_keys')) not in (list, tuple) or type(row.get('face_id')) is not str:
            raise ValueError('Owned ordered observation keys and face identifier required')
        weights += len(row['bounds'])
        owners += len(row['owners'])*len(row['bounds'])
        input_bytes += 2048+4*len(row['face_id'])+1024*len(row['ordered_keys'])
        for key, pair in row['bounds'].items():
            if type(key) is not tuple or len(key) != 2 or type(pair) not in (list, tuple) or len(pair) != 2:
                raise ValueError('Typed observation and endpoint pairs required')
            input_bytes += 512+sum(sys.getsizeof(item) for item in key)
            for value in pair:
                size = owned_bytes(value)
                input_bytes += size
                largest = max(largest, size)
    for key, entry in boundary.items():
        if type(key) is not str or type(entry) not in (tuple, list) or len(entry) != 2:
            raise ValueError('Typed physical boundary declarations required')
        size = owned_bytes(entry[1])
        input_bytes += 1024+4*len(key)+size
        largest = max(largest, size)
    scan_bytes = (1 << 20)+2048*(owners+cells+len(boundary))+16*largest
    with R.OwnedWorkspace(budget, scan_bytes, category='heat-endpoint-inventory-metadata', cancelled=cancel):
        witness_bytes, witness_codec = _json_encoding_capacity(witness, budget)
        source_bytes, source_codec = _json_encoding_capacity(source_bindings, budget)
        input_bytes += witness_codec+source_codec+sys.getsizeof(rows)+sys.getsizeof(boundary)

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
        max_bits = conversion_bits = conversion_part = 1
        tie_bits = tie_part = 0
        retained_endpoint_bytes = 0
        bshape = {key: shape(entry[1]) for key, entry in boundary.items()}
        for row in rows:
            for key, pair in row['bounds'].items():
                check()
                kind, index = key
                bounds = tuple(map(shape, pair))
                endpoint_zero = tuple(value == 0 for value in pair)
                for s in bounds:
                    conversion_bits = max(conversion_bits, s.numerator+s.denominator)
                    conversion_part = max(conversion_part, s.numerator, s.denominator)
                    if pair[0] != pair[1]:
                        tie_bits = max(tie_bits, s.numerator+s.denominator)
                        tie_part = max(tie_part, s.numerator, s.denominator)
                for owner, sign in row['owners']:
                    if type(owner) is not int or not 0 <= owner < cells or type(sign) is not int or sign not in (-1, 1):
                        raise ValueError('Original bounded integer owner and sign required')
                    if kind == 'cell':
                        if type(index) is not int or not 0 <= index < cells:
                            raise ValueError('Bounded cell observation required')
                        target = op.setdefault((owner, index), [zero, zero])
                        zero_incoming = endpoint_zero
                    elif kind in ('wall', 'power') and index in bshape:
                        source_bounds = tuple(map(shape, pair))
                        factor = bshape[index]
                        products = tuple(multiply_shape(s, factor) for s in source_bounds)
                        factor_zero = boundary[index][1] == 0
                        zero_incoming = tuple(factor_zero or item for item in endpoint_zero)
                        # Multiplication still executes in the unchanged assembler.
                        # Fund all original operand/product scratch BEFORE crediting
                        # the proved zero RESULT as canonical0/1. Per-face rounding
                        # still covers every original (possibly giant) endpoint.
                        for shape_in, is_zero in zip(source_bounds, zero_incoming, strict=True):
                            if is_zero:
                                max_bits = max(max_bits, 4*(shape_in.numerator+shape_in.denominator
                                    +factor.numerator+factor.denominator))
                        bounds = tuple(zero if flag else product for product, flag in zip(products, zero_incoming, strict=True))
                        if boundary[index][1] < 0:
                            bounds = tuple(reversed(bounds))
                            zero_incoming = tuple(reversed(zero_incoming))
                        target = wall[owner]
                    else:
                        raise ValueError('Complete declared physical observations required')
                    # Negative scale swaps endpoints. Both widths are covered.
                    incoming = bounds if sign == 1 else tuple(reversed(bounds))
                    known_zero = zero_incoming if sign == 1 else tuple(reversed(zero_incoming))
                    for j in (0, 1):
                        if known_zero[j]:
                            # Exact x+0=x, including denominator; no claim about
                            # cancellation of two nonzero contributions is made.
                            continue
                        a, b = target[j], incoming[j]
                        result = add_shape(a, b)
                        max_bits = max(max_bits, 4*(a.numerator+a.denominator+b.numerator+b.denominator))
                        conversion_bits = max(conversion_bits, result.numerator+result.denominator)
                        conversion_part = max(conversion_part, result.numerator, result.denominator)
                        target[j] = result
        for pair in list(op.values())+wall:
            for s in pair:
                retained_endpoint_bytes += R.native_slot_allowance(R.RationalShape(s.numerator, s.denominator))
                # Aggregate equality/cancellation is unknown to the shape pass.
                # Fund its complete neighbouring-Decimal branch conservatively.
                tie_bits = max(tie_bits, s.numerator+s.denominator)
                tie_part = max(tie_part, s.numerator, s.denominator)
        growth = ROUND.conversion_growth(conversion_bits, conversion_part,
            tie_part_bits=tie_bits, tie_maximum_part_bits=tie_part)
        scalar = R.native_workspace_allowance(max(max_bits, growth.exact_scalar_expression_bits), 64)
        decimal = growth.python_conversion_bytes
        containers = 2048*(weights+owners+cells+len(rows)+len(boundary)+1)
        codec = 2*(witness_codec+source_codec)+4*(witness_bytes+source_bytes)
        # CertifiedFace and RoundedFace generations, Decimal values/slots,
        # immutable operator/wall tuples, signatures, witness and plan records.
        result = (4096+2048*(2*len(rows)+cells+len(boundary)+len(source_bindings))
                  +1024*(weights+len(op)+cells)+2*(witness_bytes+source_bytes))
        work = scalar+decimal+containers+retained_endpoint_bytes+codec+scan_bytes
        inventory = A.DiagnosticInventory(max(1, input_bytes), work, result,
            'Derived per-coefficient exact growth with proved-zero results after operand scratch; '
            'fast converter and adjacent-tie scalar widths derived, no arithmetic changed; not allocator/RSS or whole-method admission.')
        inventory.total()
        check()
        return InventoryPlan(inventory, (('exact_accumulators', retained_endpoint_bytes),
            ('native_scalar_work', scalar), ('decimal_conversion', decimal), ('containers', containers),
            ('metadata_scan', scan_bytes), ('codec', codec)), len(op)+cells, conversion_bits, growth)
