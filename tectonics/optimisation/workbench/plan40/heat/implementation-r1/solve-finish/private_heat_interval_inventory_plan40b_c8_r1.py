"""Plan40B C8 inventory successor with explicit selected-public source pins.

Every r4 inventory formula and admission is preserved conservatively. Only
the assembly import and dependency identity binding change; there is no
historical-private execution or reduced-memory claim.

Derived extra census/conversion inventory for exact assembly.

Reuse the fast-rounding, zero-aware endpoint inventory r3. Add every retained
signed contribution endpoint and census container, plus a separate exact
guard/sticky conversion envelope. No text length becomes a rational width.

Integer growth bounds are exact; CPython object/container and installed GMP
workspace/recycled-block conventions are accounted policies, NOT allocator or
RSS theorems. Existing rows are already owned by the caller during inspection.
The eventual result owner retains all declared input/work/result generations.
No reconstruction, factorisation, native origin or whole-method admission.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import struct
import sys

import private_heat_endpoint_inventory_r3 as BASE
import private_heat_interval_assembly_kernel_plan40b_c8_r1 as A

HERE = Path(__file__).resolve().parent
_PINS = {'private_heat_endpoint_inventory_r3.py': '00ac1c88c8d6c61b82147349bda2c80f0442b2431271e83df87bb2661a373a1c', 'private_heat_rounding_inventory_r1.py': '5db9dd5616c20907d627a915a457be5267dbda0baab0c4c1dcf2d5348bc3d500', 'private_heat_interval_assembly_kernel_r1.py': 'bdbd0f1e62668d48c958075ffb033e740ee147f163faa943893d01c24ae3de74', 'private_heat_rational_decimal_kernel_r1.py': '1b6182c8a2b2dc8e7a051b8fd078b0cb58cec6f104f3b9587e2e4eab751f232f', 'private_heat_gmp_resources_r1.py': '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca', 'integration_exact_gmp.py': '5f3be654f70bd56c33df8c2c2f6f065347d7375b62c42bc840d3c496d61ab79f', 'private_heat_interval_assembly_kernel_plan40b_c8_r1.py': '248afad46838af857c1170c3083b7a0558fb2c85921e54b9011f3b024816d7f5'}


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Aggregate refinement inventory cancelled')


def _size(value):
    if type(value) is not int or not 0 <= value <= sys.maxsize:
        raise OverflowError('Aggregate inventory exceeds addressable storage')
    return value


def source_paths():
    """Actual imported dependency files, with explicit public-source pins."""
    import private_heat_gmp_resources_r1 as R
    import private_heat_rational_decimal_kernel_r1 as D
    from atlas_tectonics import integration_exact_gmp as X
    modules = (BASE, BASE.ROUND, A.B, A, D, R, X)
    paths = {Path(module.__file__).name: Path(module.__file__).resolve() for module in modules}
    if set(paths) != set(_PINS):
        raise ValueError('Unexpected C8 assessment dependency identity')
    return paths


def verify_sources(cancel=None):
    paths = source_paths()
    for name, expected in _PINS.items():
        _check(cancel)
        if sha256(paths[name].read_bytes()).hexdigest() != expected:
            raise ValueError('Reviewed aggregate inventory dependency changed: '+name)


ConversionGrowth = BASE.ROUND.ConversionGrowth
conversion_growth = BASE.ROUND.conversion_growth


@dataclass(frozen=True)
class AssessmentInventory:
    base: BASE.InventoryPlan
    refinement_bytes: int
    components: tuple
    contributions: int
    retained_contributions: int
    known_zero_contributions: int
    aggregate_bound: int
    conversion: ConversionGrowth
    metadata_admission_bytes: int
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    whole_method_admission: bool = False

    @property
    def total_bytes(self):
        return _size(self.base.inventory.total()+self.refinement_bytes)


def derive(rows, cells, boundary, *, witness, source_bindings, budget, cancel=None):
    """Derived current-generation plan, never a caller-supplied byte guess.

    The base plan is reused verbatim. The metadata scan is funded before GMP
    numerator/denominator getters or shape arithmetic. All repeated contribution
    endpoints are charged, including aliases. Only products provably equal to the
    exact zero pair skip retained Contribution storage, matching A2 precisely.
    Their transient products, additions and all face rounding remain funded.
    Strings/JSON remain in base text/container accounting, never arithmetic.
    Inputs must not mutate between this inspection and the immediate assembly.
    """
    _check(cancel)
    verify_sources(cancel)
    base = BASE.derive(rows, cells, boundary, witness=witness,
                       source_bindings=source_bindings, budget=budget, cancel=cancel)
    if sys.implementation.name != 'cpython' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise RuntimeError('Aggregate container accounting requires reviewed CPython3.12 x64')
    gmp = A.B._library()
    import private_heat_gmp_resources_r1 as R
    contribution_count = sum(len(row['owners'])*len(row['bounds']) for row in rows)
    # Scalar shallow-size inspection copies no rational parts and parses no text.
    largest = 2048
    for row in rows:
        _check(cancel)
        for pair in row['bounds'].values():
            for value in pair:
                largest = max(largest, sys.getsizeof(value))
    for item in boundary.values():
        largest = max(largest, sys.getsizeof(item[1]))
    metadata = _size((1 << 20)+16*largest+1024*(len(boundary)+len(rows)+16))
    with R.OwnedWorkspace(budget, metadata, category='heat-aggregate-inventory-metadata', cancelled=cancel):
        def shape(value):
            _check(cancel)
            if type(value) in (Fraction, gmp.mpq):
                n, d = value.numerator, value.denominator
            elif type(value) is int:
                n, d = value, 1
            elif type(value) is float:
                n, d = value.as_integer_ratio()
            else:
                raise ValueError('Only typed owned numeric endpoints are admitted')
            return BASE.Shape(max(1, n.bit_length()), d.bit_length(), d.bit_count() == 1)
        boundary_shapes = {key: shape(item[1]) for key, item in boundary.items()}
        endpoint_storage = retained_count = 0
        for row in rows:
            for key, pair in row['bounds'].items():
                _check(cancel)
                known_zero = (all(value == 0 for value in pair)
                    or key[0] in ('wall', 'power') and boundary[key[1]][1] == 0)
                if known_zero:
                    # Exact existing branch: A2 retains a Contribution only
                    # when signed_bounds != (0,0). No near-zero cancellation
                    # or contains-zero interval gets this credit. BASE keeps
                    # every transient operation and per-face conversion.
                    continue
                retained_count += len(row['owners'])
                for value in pair:
                    item = shape(value)
                    if key[0] in ('wall', 'power'):
                        # BASE already funds original operand/product scratch.
                        # Only the exact zero retained RESULT gets a small slot;
                        # original endpoint storage/rounding remains charged.
                        item = (BASE.Shape(1, 1, True) if value == 0 or boundary[key[1]][1] == 0
                                else BASE.multiply_shape(item, boundary_shapes[key[1]]))
                    # Retain the UNREDUCED product envelope; gcd reduction must
                    # not erase the allocation required by its intermediates.
                    slot = R.native_slot_allowance(R.RationalShape(item.numerator, item.denominator))
                    endpoint_storage += len(row['owners'])*max(slot, sys.getsizeof(value))
        aggregate_count = base.coefficients
        pointer = struct.calcsize('P')
        tuple_header, list_header, dict_header = map(sys.getsizeof, ((), [], {}))
        def tuple_bytes(n):
            return tuple_header+pointer*n
        def list_bytes(n):
            # CPython append growth is <=2n+8 allocated pointer slots. Charge
            # both mutable lists and their simultaneously formed frozen tuples.
            return list_header+pointer*(2*n+8)
        def record_bytes(value):
            return sys.getsizeof(value)+sys.getsizeof(vars(value))
        c_record = record_bytes(A.Contribution('', (), 1, ()))
        i_record = record_bytes(A.AmbiguousAggregate('', '', 0, None, (), (), ''))
        r_record = record_bytes(A.RefinementRequired(1, (), (), (), (), '', ()))
        contribution_objects = retained_count*(c_record+tuple_bytes(2)+tuple_bytes(2))
        contributor_lists = aggregate_count*(list_header+8*pointer)+2*pointer*retained_count
        # 1024/key is the existing conservative native Python map/set policy,
        # not a string width and not a claim about arbitrary Python allocators.
        contributor_map = dict_header+aggregate_count*(1024+tuple_bytes(3))
        issue_text = 2*(sys.getsizeof('')+160+2*len(str(cells)))
        issues = (aggregate_count*(i_record+tuple_bytes(2)+tuple_header+issue_text)
                  +pointer*retained_count+list_bytes(aggregate_count)+tuple_bytes(aggregate_count))
        order_and_union = list_bytes(len(rows))+1024*len(rows)+tuple_bytes(len(rows))
        request = r_record+4096  # owner/input tuple/plan/snapshot record headers
        growth = base.conversion
        # Converter AND tie-guard expression/Python storage are now derived
        # in BASE itself. Do not retain the superseded giant-Decimal envelope
        # or count the same replacement phase twice.
        components = (('retained_signed_contribution_endpoints', endpoint_storage),
            ('contribution_records_and_endpoint_key_tuples', contribution_objects),
            ('contributor_lists_and_map', contributor_lists+contributor_map),
            ('aggregate_issue_records_text_and_frozen_sequences', issues),
            ('original_order_union_and_request_owner', order_and_union+request),
            ('additional_guard_sticky_exact_scalar_workspace', 0),
            ('additional_bounded_decimal_surrogate_objects', 0),
            ('inventory_metadata_envelope_retained', metadata))
        extra = _size(sum(value for _, value in components))
        result = AssessmentInventory(base, extra, components, contribution_count,
            retained_count, contribution_count-retained_count, aggregate_count, growth, metadata)
        result.total_bytes
        _check(cancel)
        return result
