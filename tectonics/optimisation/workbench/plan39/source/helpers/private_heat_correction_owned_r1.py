"""Fixed exact FCT/public-bound correction with incremental owned admission.

Only this numerical route is supported: no supplied arithmetic callback or
saved result is admitted. Actual live array entries have individual GMP sizes;
the largest operand is used only for 64 current scalar/getter/product slots,
not multiplied across every cell. Reserve unreduced operation growth BEFORE
each call. Array replacement settles after dropping that array's old reference.
The private owner retains arrays, scratch and failed frames; no native origin,
allocator/RSS theorem or whole-method admission is asserted.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
import math
from pathlib import Path
import sys

import private_heat_finish_arithmetic_r1 as A
import private_heat_public_float_r1 as PUBLIC
from private_heat_decimal_sparse_core_r1 import OwnedSolve

HERE = Path(__file__).resolve().parent
PINS = {
    'private_heat_finish_arithmetic_r1.py': 'a5473f2993016d40b13587fd8948ce732f4c8fcd78f1ac61584ba0c8e702da66',
    'private_heat_public_float_r1.py': '9ce024ccc0922034b25ea578fadf6e99c403c7132a5f91066d11f0190f1f39a1',
    'private_heat_gmp_resources_r1.py': '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca',
}
_SOURCES = {str(HERE/name): pin for name, pin in PINS.items()}
_SOURCES[str(Path(__file__).resolve())] = sha256(Path(__file__).read_bytes()).hexdigest()


class _OwnerWorkspace:
    """Drop owned arrays before release; retain them with escaping frames."""
    def __init__(self, workspace):
        self.workspace, self.arithmetic = workspace, None

    def __exit__(self, kind, error, traceback):
        if error is None:
            if self.arithmetic is not None:
                self.arithmetic.arrays.clear()
            self.arithmetic = None
        # On error this wrapper's frame keeps arithmetic and arrays alive.
        return self.workspace.__exit__(kind, error, traceback)


class CorrectionOwner(OwnedSolve):
    @property
    def inventory(self):
        self.value
        ar = self._workspace.arithmetic
        return dict(route='FIXED_EXACT_OPERATIONS_WITH_ACTUAL_LIVE_ARRAY_WIDTHS',
            operations=ar.operations, retained_array_bytes=ar.live,
            scalar_peak_bits=ar.peak_bits, scalar_slots=64,
            reserved_bytes=ar.workspace.lease.count,
            allocator_or_rss_bound=False, native_origin_bound=False)


class _Arithmetic:
    """Internal fixed-route arrays and at most 64 current exact temporaries."""
    def __init__(self, workspace, gmp, resources, n, f, initial_bits, check, *, extra_fixed_bytes=0):
        if type(extra_fixed_bytes) is not int or extra_fixed_bytes < 0:
            raise ValueError('Nonnegative explicit fixed inventory required')
        self.workspace, self.G, self.R, self.check = workspace, gmp, resources, check
        self.arrays, self.live, self.peak_bits, self.operations = [], 0, 1, 0
        # Counts cover array values/count vectors, indices, floats, six bound
        # checks, corrections/evidence, and 66 scalar-history dictionaries.
        # This is the existing conservative 1024-byte container-unit policy.
        self.containers = 1024*(512+32*n+32*f)+extra_fixed_bytes
        self.history = 70*resources.native_slot_allowance(resources.RationalShape(65, 65))
        self.reserve(initial_bits)

    def reserve(self, bits):
        self.check()
        peak = max(self.peak_bits, bits, 1)
        slot = self.R.native_slot_allowance(self.R.RationalShape(peak, peak))
        amount = self.containers+self.history+self.live+64*slot+self.R.native_workspace_allowance(8*peak, 64)
        if amount > sys.maxsize:
            raise OverflowError('Fixed correction exceeds addressable memory')
        self.workspace.resize_before_allocation_or_after_drop(amount)
        self.peak_bits = peak

    def settle(self, retained=None):
        # The fixed numerical producer frame is gone before this is called.
        # When a fixed producer supplies its complete returned graph, retain
        # each ACTUAL immutable GMP object once by identity, including objects
        # referenced only by dictionaries/proofs. This is not value equality
        # deduplication or an assumption about caller sharing. Fund the new
        # reference vector while all old arrays remain alive; only then drop
        # private scratch arrays. No arbitrary callback is invoked here.
        if retained is not None:
            known, pending, rationals = set(), [retained], []
            while pending:
                self.check()
                value = pending.pop()
                key = id(value)
                if key in known:
                    continue
                known.add(key)
                if type(value) is self.G.mpq:
                    rationals.append(value)
                elif type(value) is dict:
                    pending.extend(value.values())
                elif type(value) in (tuple, list):
                    pending.extend(value)
            result = self.copy(rationals)
            kept = self.arrays[result[0]]
            self.arrays[:] = [kept]
            self.live = sum(kept[1])
            del result, kept, rationals, known, pending, value
        # Current scalar/native workspace no longer exists after the fixed
        # producer frame is gone. Exception paths never take this return credit.
        self.check()
        self.workspace.resize_before_allocation_or_after_drop(
            self.containers+self.history+self.live)

    def shape(self, value):
        if type(value) is int:
            return self.R.RationalShape(max(1, value.bit_length()), 1)
        if type(value) is not self.G.mpq:
            raise TypeError('Owned exact GMP correction inputs required')
        # Getters fit the already-admitted current scalar envelope, including
        # the shallow-size-derived first envelope before any getter is used.
        return self.R.RationalShape(max(1, value.numerator.bit_length()), value.denominator.bit_length())

    def op(self, operation, left, right):
        growth = self.R.operation_growth(operation, self.shape(left), self.shape(right), divisor_is_nonzero=True)
        self.reserve(max(growth.expression_integer_bits+(growth.result.numerator_bits, growth.result.denominator_bits)))
        self.operations += 1
        if operation == 'add':
            return left+right
        if operation == 'subtract':
            return left-right
        if operation == 'multiply':
            return left*right
        return left/right

    def less(self, left, right):
        a, b = self.shape(left), self.shape(right)
        self.reserve(max(a.numerator_bits+b.denominator_bits, b.numerator_bits+a.denominator_bits))
        self.operations += 1
        return left < right

    def equal(self, left, right):
        a, b = self.shape(left), self.shape(right)
        self.reserve(max(a.numerator_bits+b.denominator_bits, b.numerator_bits+a.denominator_bits))
        self.operations += 1
        return left == right

    def minimum(self, left, right):
        return left if self.less(left, right) else right

    def neg(self, value):
        s = self.shape(value)
        self.reserve(max(s.numerator_bits, s.denominator_bits))
        return -value

    def charge(self, value):
        if type(value) is self.G.mpq:
            return max(sys.getsizeof(value), self.R.native_slot_allowance(self.shape(value)))
        if type(value) is tuple:
            return sys.getsizeof(value)+sum(self.charge(v) for v in value)
        if type(value) in (int, type(None)):
            return sys.getsizeof(value)
        raise TypeError('Only fixed correction array entries supported')

    def array(self, count):
        self.check()
        # Exact array/container maxima were reserved before constructing any.
        values, charges = [None]*count, [0]*count
        self.arrays.append((values, charges))
        return len(self.arrays)-1, values

    def put(self, array, at, value):
        index, values = array
        charges = self.arrays[index][1]
        size = self.charge(value)
        previous = charges[at]
        # New value is still in the 64-slot scalar envelope until admission.
        # Fund both array references while replacing, then settle the removed
        # reference. Other live aliases are charged in their own array entries.
        self.live += size
        try:
            self.reserve(self.peak_bits)
        except BaseException:
            self.live -= size
            raise
        values[at] = value
        charges[at] = size
        self.live -= previous
        self.reserve(self.peak_bits)

    def copy(self, values):
        result = self.array(len(values))
        for at, value in enumerate(values):
            self.put(result, at, value)
        return result

    def drop_to(self, mark):
        # Only used after predicate-local arrays have been explicitly deleted;
        # the known predicate returns a bool, never a borrowed numeric value.
        freed = sum(sum(item[1]) for item in self.arrays[mark:])
        del self.arrays[mark:]
        self.live -= freed
        self.reserve(self.peak_bits)

    def public(self, value):
        shape = self.shape(value)
        self.reserve(max(shape.numerator_bits, shape.denominator_bits, 1075))
        return PUBLIC.public_float(value)

    def bounds(self, energy, cap, bounds):
        exact = True
        for e, c in zip(energy, cap, strict=True):
            self.check()
            if self.less(e, self.op('multiply', c, bounds[0])) or self.less(self.op('multiply', c, bounds[1]), e):
                exact = False
                break
        stocks = [self.public(e) for e in energy]
        temperatures = [e/self.public(c) for e, c in zip(stocks, cap, strict=True)]
        public = True
        for t in temperatures:
            self.check()
            if not math.isfinite(t):
                public = False
                break
            self.reserve(max(self.peak_bits, 1075))
            q = self.G.mpq(t)
            if self.less(q, bounds[0]) or self.less(bounds[1], q):
                public = False
                break
        return dict(exact_pass=exact, actual_public_pass=public,
                    enthalpy_j=stocks, temperature_k=temperatures)

    def residual(self, energy, faces):
        result = self.copy(energy)
        for i, j, amount in faces:
            self.put(result, i, self.op('add', result[1][i], amount))
            if j is not None:
                self.put(result, j, self.op('subtract', result[1][j], amount))
        return result


def _public_guard(ar, low, candidate, cap, lo_faces, faces, alphas, bounds):
    final = ar.bounds(candidate, cap, bounds)
    if not final['exact_pass']:
        raise ValueError('Signwise correction fails unchanged exact bounds')
    if final['actual_public_pass']:
        return candidate, faces, alphas, final, None
    low_check = ar.bounds(low, cap, bounds)
    if not low_check['exact_pass'] or not low_check['actual_public_pass']:
        raise ValueError('Low endpoint fails exact or actual public bounds')
    difference = ar.array(len(low))
    for i, (e, l) in enumerate(zip(candidate, low, strict=True)):
        ar.put(difference, i, ar.op('subtract', e, l))
    failing = []
    for i, t in enumerate(final['temperature_k']):
        ar.check()
        if not math.isfinite(t):
            failing.append(i)
        else:
            q = ar.G.mpq(t)
            if ar.less(q, bounds[0]) or ar.less(bounds[1], q):
                failing.append(i)
    selected_cap = [cap[i] for i in failing]
    def admissible(theta):
        mark = len(ar.arrays)
        values = ar.array(len(failing))
        for at, i in enumerate(failing):
            ar.put(values, at, ar.op('add', low[i], ar.op('multiply', theta, difference[1][i])))
        checked = ar.bounds(values[1], selected_cap, bounds)
        passed = checked['exact_pass'] and checked['actual_public_pass']
        del values, checked
        ar.drop_to(mark)
        return passed
    theta, selection = A.feasible_scalar(admissible)
    corrected, paired, scaled = ar.array(len(low)), ar.array(len(faces)), ar.array(len(alphas))
    for i, value in enumerate(low):
        ar.put(corrected, i, ar.op('add', value, ar.op('multiply', theta, difference[1][i])))
    for f, (before, after) in enumerate(zip(lo_faces, faces, strict=True)):
        q = ar.op('add', before[2], ar.op('multiply', theta, ar.op('subtract', after[2], before[2])))
        ar.put(paired, f, (before[0], before[1], q))
    for f, alpha in enumerate(alphas):
        ar.put(scaled, f, ar.op('multiply', theta, alpha))
    final = ar.bounds(corrected[1], cap, bounds)
    if not final['exact_pass'] or not final['actual_public_pass']:
        raise ArithmeticError('Certified public-rounding contraction failed')
    return corrected[1], paired[1], scaled[1], final, dict(
        schema='atlas.conservative-public-rounding-contraction.r1', theta=theta,
        selection=selection, original_bounds=bounds, clipping_used=False, tolerance_changed=False,
        exact_cell_ledger_preserved_by_common_face_scalar=True)


def _correct(ar, low, cap, low_faces, high_faces, bounds, permitted):
    if len(low_faces) != len(high_faces):
        raise ValueError('Low/high physical faces must match')
    exterior = {f for f, (_, j, _) in enumerate(low_faces) if j is None}
    if not set(permitted).issubset(exterior):
        raise ValueError('Only actual exterior reservoirs may be corrected')
    zero, one = ar.G.mpq(0), ar.G.mpq(1)
    n, nf = len(low), len(low_faces)
    full, full_faces, full_alphas, corrections = ar.copy(low), ar.array(nf), ar.array(nf), ar.array(nf)
    for f, ((i, j, lo), (hi, hj, high)) in enumerate(zip(low_faces, high_faces, strict=True)):
        ar.check()
        if (i, j) != (hi, hj) or not 0 <= i < n or j is not None and (not 0 <= j < n or i == j):
            raise ValueError('Physical face owner/order mismatch')
        allowed = j is not None or f in permitted
        delta = ar.op('subtract', lo, high) if allowed else zero
        ar.put(corrections, f, (i, j, delta))
        ar.put(full, i, ar.op('add', full[1][i], delta))
        if j is not None:
            ar.put(full, j, ar.op('subtract', full[1][j], delta))
        ar.put(full_faces, f, (i, j, ar.op('subtract', lo, delta)))
        ar.put(full_alphas, f, one if allowed else zero)
    full_check = ar.bounds(full[1], cap, bounds)
    if full_check['exact_pass'] and full_check['actual_public_pass']:
        energy, faces, alphas = full[1], full_faces[1], full_alphas[1]
        branch = 'COMPLETE_PHYSICAL_CORRECTION_ADMISSIBLE'
    else:
        positive, negative = ar.copy([zero]*n), ar.copy([zero]*n)
        for i, j, delta in corrections[1]:
            for owner, incoming in ((i, delta),) if j is None else ((i, delta), (j, ar.neg(delta))):
                ar.put(positive, owner, ar.op('add', positive[1][owner], incoming if ar.less(zero, incoming) else zero))
                ar.put(negative, owner, ar.op('add', negative[1][owner], incoming if ar.less(incoming, zero) else zero))
        up, down = ar.array(n), ar.array(n)
        for i, (c, e) in enumerate(zip(cap, low, strict=True)):
            bottom, top = ar.op('multiply', c, bounds[0]), ar.op('multiply', c, bounds[1])
            if ar.less(e, bottom) or ar.less(top, e):
                raise ValueError('Low state fails unchanged exact temperature bounds')
            ar.put(up, i, ar.minimum(one, ar.op('divide', ar.op('subtract', top, e), positive[1][i])) if positive[1][i] else one)
            ar.put(down, i, ar.minimum(one, ar.op('divide', ar.op('subtract', bottom, e), negative[1][i])) if negative[1][i] else one)
        limited, limited_faces, limited_alphas = ar.copy(low), ar.array(nf), ar.array(nf)
        for f, ((i, j, delta), (_, _, lo)) in enumerate(zip(corrections[1], low_faces, strict=True)):
            nonnegative = not ar.less(delta, zero)
            alpha = up[1][i] if nonnegative else down[1][i]
            if j is not None:
                alpha = ar.minimum(alpha, down[1][j] if nonnegative else up[1][j])
            if ar.less(alpha, zero) or ar.less(one, alpha):
                raise ArithmeticError('Invalid signwise correction scalar')
            ar.put(limited, i, ar.op('add', limited[1][i], ar.op('multiply', alpha, delta)))
            if j is not None:
                ar.put(limited, j, ar.op('subtract', limited[1][j], ar.op('multiply', alpha, delta)))
            ar.put(limited_faces, f, (i, j, ar.op('subtract', lo, ar.op('multiply', alpha, delta))))
            ar.put(limited_alphas, f, alpha)
        energy, faces, alphas = limited[1], limited_faces[1], limited_alphas[1]
        branch = 'UNCHANGED_SIGNWISE_FCT_FALLBACK'
    energy, faces, alphas, final, guard = _public_guard(ar, low, energy, cap, low_faces, faces, alphas, bounds)
    residual, prior = ar.residual(energy, faces), ar.residual(low, low_faces)
    if not all(ar.equal(a, b) for a, b in zip(residual[1], prior[1], strict=True)):
        raise ArithmeticError('Physical correction changed the exact low ledger')
    if any(not ar.equal(q, low_faces[f][2]) for f, (_, j, q) in enumerate(faces) if j is None and f not in permitted):
        raise ArithmeticError('A fixed exterior transfer changed')
    evidence = dict(branch=branch, unchanged_bounds=bounds, full_candidate=full[1],
        full_candidate_check=full_check, final_check=final, public_rounding_contraction=guard,
        exact_low_ledger_preserved=True, fixed_exterior_transfers_preserved=True,
        one_antisymmetric_transfer_per_physical_face=True,
        full_admission_preserves_all_permitted_high_face_transfers=all(
            ar.equal(faces[f][2], high_faces[f][2]) for f, (_, j, _) in enumerate(faces)
            if j is not None or f in permitted) if branch.startswith('COMPLETE') else None,
        no_change_to_reconstruction_or_exact_degree3_moments=True)
    return energy, faces, alphas, evidence


def correct(low, capacity, low_faces, high_faces, bounds, permitted, *, budget, cancelled=None):
    """Owned exact fixed correction; caller retains original input ownership."""
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Fixed incremental heat correction cancelled')
        return False
    check()
    G = A.exact_library()
    import private_heat_gmp_resources_r1 as R
    n, nf = len(low), len(low_faces)
    if not n or len(capacity) != n or len(bounds) != 2:
        raise ValueError('Complete original correction state required')
    largest = 1
    for values in (low, capacity, bounds, (q for _, _, q in low_faces), (q for _, _, q in high_faces)):
        for q in values:
            check()
            if type(q) is not G.mpq:
                raise TypeError('Exact owned GMP input arrays required')
            largest = max(largest, sys.getsizeof(q))
    workspace = R.OwnedWorkspace(budget, 65536, category='heat-fixed-correction-incremental', cancelled=check)
    workspace.__enter__()
    owner_workspace = _OwnerWorkspace(workspace)
    try:
        ar = _Arithmetic(workspace, G, R, n, nf, 8*largest+64, check)
        owner_workspace.arithmetic = ar
        if any(not ar.less(0, c) for c in capacity):
            raise ValueError('Positive exact capacities required')
        for path, pin in _SOURCES.items():
            check()
            if sha256(Path(path).read_bytes()).hexdigest() != pin:
                raise ValueError('Fixed correction source changed')
        value = _correct(ar, low, capacity, low_faces, high_faces, bounds, permitted)
        # The fixed numerical frame has returned. Transfer its complete actual
        # result graph to the owner before discarding private scratch arrays.
        ar.settle(value)
        return CorrectionOwner(value, owner_workspace)
    except BaseException:
        owner_workspace.__exit__(*sys.exc_info())
        raise
