"""Private endpoint assembly, independent of experiment/control imports.

Given CALLER-PROVED rational enclosures, accumulate exact GMP endpoints across
all physical faces BEFORE Decimal-80 HALF_EVEN operator/wall rounding. Face
weights are separately rounded in their original order. Only singleton exact
zero is deleted. Ambiguous rounding/ties/non-singleton zero explicitly refuse.
This is the frozen assembler's arithmetic, not midpoint or per-face-rounded
assembly. Unknown terminating Decimal quantum is not certified by an interval.

Imports are stdlib/private-stdlib only; selected GMP is gated at invocation.
The required diagnostic inventory reserves caller-declared bytes, NOT a proved
bound for dynamic GMP denominators, gcd scratch, Decimal/JSON conversion or
retained objects. No production entry point or complete admission is claimed.
Those workset bounds remain an explicit integration seam. Imports/allocator
baseline and already allocated inputs need separate caller headroom/admission.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from decimal import Decimal as D, ROUND_HALF_EVEN, localcontext
from fractions import Fraction as Q
import json
import sys

from private_heat_decimal_sparse_core_r1 import OwnedSolve, RoundedFace, RoundedSystem


class UnresolvedRounding(ValueError):
    """The interval does not prove the required exact Decimal rounding."""


@dataclass(frozen=True)
class CertifiedFace:
    face_id: str
    owners: tuple
    weights: tuple


@dataclass(frozen=True)
class CertifiedAssembly:
    cells: int
    operator: tuple
    wall: tuple
    rows: tuple
    exact_operator_nnz: int
    context_signature: tuple
    boundary_signature: tuple
    witness_json: str
    source_bindings: tuple
    interval_validity: str = 'CALLER_WITNESSED_NOT_REPROVED_BY_ASSEMBLER'
    inventory_coverage_certified: bool = False
    native_workbudget_admitted: bool = False


@dataclass(frozen=True)
class DiagnosticInventory:
    """Explicit private allowance; no inference that its sizes are sufficient.

    input_bytes covers all retained source rows/endpoints/metadata and boundary.
    work_bytes covers simultaneous exact accumulators/operands/intermediates,
    native scratch, Python/Decimal conversion and witness JSON generations.
    result_bytes covers certificate AND any rounded-system view simultaneously.
    Full prospective derivation is intentionally NOT asserted by these fields.
    """
    input_bytes: int
    work_bytes: int
    result_bytes: int
    justification: str

    def total(self):
        counts = (self.input_bytes, self.work_bytes, self.result_bytes)
        if any(type(value) is not int or value <= 0 for value in counts):
            raise ValueError('Explicit positive input, exact/Decimal work and result allowances required')
        if type(self.justification) is not str or not self.justification.strip():
            raise ValueError('Explicit diagnostic inventory justification required')
        value = sum(counts)
        if value > sys.maxsize:
            raise OverflowError('Diagnostic inventory exceeds addressable storage')
        return value


class OwnedAssembly(OwnedSolve):
    """Certificate owner using the existing private result/traceback lease.

    Borrowed certificate and rounded-system view must not outlive this owner.
    Its full declared allowance remains charged until all such values are
    dropped/transferred and the owner is closed; no transient-release estimate.
    """

    def rounded_system(self, boundary, *, cancel=None):
        """Bind exact observations BEFORE exposing the numerical-only view.

        Unlike the sparse core's binary64 signature, this checks exact rational
        boundary identity too. Caller inventory must include the view's new
        face/tuple containers. Keep this owner alive while the view is borrowed.
        """
        _check(cancel)
        value = self.value
        self._workspace.checkpoint()
        gmp = _library()
        if value.boundary_signature != _boundary_signature(boundary, gmp, cancel):
            raise ValueError('Prescribed observations changed after certified assembly')
        rows = []
        for row in value.rows:
            _check(cancel)
            rows.append(RoundedFace(row.face_id, row.owners, row.weights))
        numerical_signature = tuple((key, kind, public)
                                    for key, kind, _, public in value.boundary_signature)
        return RoundedSystem(value.cells, value.operator, value.wall, tuple(rows),
            value.exact_operator_nnz, value.context_signature, numerical_signature,
            value.source_bindings, value.witness_json)


def _library():
    from atlas_tectonics import exact_arithmetic
    result = exact_arithmetic.library()
    if result is None:
        raise RuntimeError('Certified endpoint assembly requires the selected GMP backend')
    return result


def _q(value, gmp):
    if isinstance(value, gmp.mpq):
        return value
    try:
        value = Q(value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError) as error:
        raise ValueError('Finite exact rational endpoint/value required') from error
    return gmp.mpq(value.numerator, value.denominator)


def _dec(value):
    # Exact same conversion and quotient as the frozen helper. In particular,
    # never format giant integer parts as decimal strings (4300-digit limit).
    return D(int(value.numerator))/D(int(value.denominator))


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Certified interval assembly cancelled')


def context_signature(context):
    return (context.prec, context.rounding, context.Emin, context.Emax, context.clamp)


def _boundary_signature(boundary, gmp, cancel):
    result = []
    for key, (kind, value) in boundary.items():
        _check(cancel)
        if not isinstance(key, str) or not key:
            raise ValueError('Boundary observations require nonempty string identifiers')
        public = D.from_float(float(value))
        if not public.is_finite():
            raise ValueError('Finite prescribed boundary observations required')
        result.append((key, kind, _q(value, gmp), public))
    return tuple(sorted(result))


def _rounded(bounds, label, gmp):
    lo, hi = bounds
    lower, upper = _dec(lo), _dec(hi)
    if not lower.is_finite() or not upper.is_finite() or lower != upper:
        raise UnresolvedRounding(label+': endpoint Decimal-80 rounding differs or is nonfinite')
    if lo == hi:
        return lower
    if not lower:
        raise UnresolvedRounding(label+': non-singleton zero is not an exact-zero proof')
    centre = _q(lower, gmp)
    for neighbour in (lower.next_minus(), lower.next_plus()):
        if neighbour.is_finite():
            midpoint = (centre+_q(neighbour, gmp))/2
            if lo <= midpoint <= hi:
                raise UnresolvedRounding(label+': non-singleton interval touches a rounding tie')
    return lower


def _scale(bounds, value):
    lo, hi = bounds
    return (lo*value, hi*value) if value >= 0 else (hi*value, lo*value)


def _add(left, right):
    return (left[0]+right[0], left[1]+right[1])


def assemble(rows, cell_count, boundary, *, witness, source_bindings, budget,
             inventory, cancel=None):
    """Return OwnedAssembly, not an unowned production-issued certificate.

    Row schema and arithmetic match the frozen assembler: face_id, one/two
    opposite owners, ordered_keys, and complete exact lower/upper bounds.
    Wall/power keys must match their declared temperature/power observation;
    observations use the globally oriented solver convention. Public outward-
    power conversion is still caller responsibility.
    Witness/source metadata are required but their truth is NOT inferred.
    All metadata serialisation and coefficient arithmetic occur after reserving
    the explicit diagnostic allowance; it is not a derived arithmetic ceiling.
    """
    _check(cancel)
    if type(cell_count) is not int or cell_count <= 0:
        raise ValueError('Positive explicit cell count required')
    if type(inventory) is not DiagnosticInventory:
        raise ValueError('Explicit diagnostic inventory required; production sizing remains unresolved')
    amount = inventory.total()
    gmp = _library()
    # Only after selected-backend gate; no probe/test dependency path.
    import private_heat_gmp_resources_r1 as resources
    workspace = resources.OwnedWorkspace(budget, amount,
        category='heat-interval-assembly-private', cancelled=cancel)
    workspace.__enter__()
    try:
        result = _assemble(rows, cell_count, boundary, witness=witness,
                           source_bindings=source_bindings, cancel=cancel, gmp=gmp)
        return OwnedAssembly(result, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def _assemble(rows, cell_count, boundary, *, witness, source_bindings, cancel, gmp):
    if not isinstance(witness, dict) or not witness or not isinstance(source_bindings, dict) or not source_bindings:
        raise ValueError('Explicit nonempty witness and source-binding metadata required')
    for name, digest in source_bindings.items():
        _check(cancel)
        if (not isinstance(name, str) or not name or not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)):
            raise ValueError('Source bindings require named lowercase SHA256 digests')
    witness_json = json.dumps(witness, sort_keys=True, separators=(',', ':'), allow_nan=False)
    boundary_identity = _boundary_signature(boundary, gmp, cancel)
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        zero = (gmp.mpq(0), gmp.mpq(0))
        op = [{} for _ in range(cell_count)]
        wall = [zero for _ in range(cell_count)]
        certified_rows, face_ids = [], set()
        for row in rows:
            _check(cancel)
            fid = row['face_id']
            owners = tuple(tuple(owner) for owner in row['owners'])
            keys = tuple(tuple(key) for key in row['ordered_keys'])
            if not isinstance(fid, str) or not fid or fid in face_ids:
                raise ValueError('One unique nonempty physical face identifier required')
            face_ids.add(fid)
            if (len(owners) not in (1, 2) or any(len(owner) != 2 or type(owner[0]) is not int
                    or not 0 <= owner[0] < cell_count or type(owner[1]) is not int
                    or owner[1] not in (-1, 1) for owner in owners)
                    or len(owners) == 2 and (owners[0][0] == owners[1][0] or owners[0][1] != -owners[1][1])):
                raise ValueError('Valid one/two opposite physical face owners required')
            if len(set(keys)) != len(keys) or set(keys) != set(row['bounds']):
                raise ValueError('Ordered unique observation keys and complete matching bounds required')
            weights = []
            for key in keys:
                _check(cancel)
                if len(key) != 2:
                    raise ValueError('Observation keys must be (kind,key) pairs')
                kind, index = key
                if kind == 'cell':
                    if type(index) is not int or not 0 <= index < cell_count:
                        raise ValueError('Cell observation outside the original cell ordering')
                elif kind not in ('wall', 'power'):
                    raise ValueError('Observation kind must be cell, wall or power')
                elif index not in boundary:
                    raise ValueError('Boundary observation has no explicit prescribed value')
                elif boundary[index][0] != ('temperature' if kind == 'wall' else 'power'):
                    raise ValueError('Boundary observation kind does not match its declaration')
                bounds = tuple(_q(value, gmp) for value in row['bounds'][key])
                if len(bounds) != 2 or bounds[0] > bounds[1]:
                    raise ValueError('Ordered lower/upper exact coefficient bounds required')
                weights.append((key, _rounded(bounds, 'face '+fid, gmp)))
                for owner, sign in owners:
                    _check(cancel)
                    if kind == 'cell':
                        op[owner][index] = _add(op[owner].get(index, zero), _scale(bounds, sign))
                    else:
                        wall[owner] = _add(wall[owner], _scale(bounds, sign*_q(boundary[index][1], gmp)))
            certified_rows.append(CertifiedFace(fid, owners, tuple(weights)))
        rounded_op = []
        for i, row in enumerate(op):
            entries = []
            for j in sorted(row):
                _check(cancel)
                bounds = row[j]
                if bounds == zero:
                    continue
                entries.append((j, _rounded(bounds, 'operator '+str((i, j)), gmp)))
            rounded_op.append(tuple(entries))
        rounded_wall = []
        for i, bounds in enumerate(wall):
            _check(cancel)
            rounded_wall.append(_rounded(bounds, 'wall '+str(i), gmp))
        return CertifiedAssembly(cell_count, tuple(rounded_op), tuple(rounded_wall), tuple(certified_rows),
            sum(map(len, rounded_op)), context_signature(context), boundary_identity,
            witness_json, tuple(sorted(source_bindings.items())))
