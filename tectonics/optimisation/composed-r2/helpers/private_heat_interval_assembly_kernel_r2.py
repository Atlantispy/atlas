"""Private complete aggregate-rounding census and unchanged exact assembly.

`assemble` retains the predecessor's fail-fast API/output. `assess` completes
all operator/wall rounding checks and returns an OWNED immutable refinement
request instead of a partial operator certificate. Per-face ambiguity still
refuses: only already face-certified rows reach an aggregate refinement census.

Both routes sum exact signed rational endpoints before Decimal80 rounding.
Fast conversion is the reviewed guard/sticky algorithm, backend-gated at use.
The census does not re-certify any row, select a stencil, change an equation or
accept an approximate zero/tie. Source/witness truth remains caller-attested.

The existing diagnostic inventory is NOT automatically a derived bound for
this successor's converter/census. `assess` additionally requires a positive
declared refinement allowance for simultaneous contribution/request storage.
All borrowed values, including a failed-rounding request, retain their owner.
This is a resource seam, not native dispatch or whole-method admission.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, localcontext
import json
import sys

import private_heat_interval_assembly_kernel_r1 as B
from private_heat_rational_decimal_kernel_r1 import dec

CertifiedAssembly = B.CertifiedAssembly
CertifiedFace = B.CertifiedFace
DiagnosticInventory = B.DiagnosticInventory
UnresolvedRounding = B.UnresolvedRounding


@dataclass(frozen=True)
class Contribution:
    face_id: str
    observation: tuple
    owner_sign: int
    signed_bounds: tuple


@dataclass(frozen=True)
class AmbiguousAggregate:
    label: str
    kind: str
    owner: int
    column: object
    bounds: tuple
    contributions: tuple
    detail: str


@dataclass(frozen=True)
class RefinementRequired:
    cells: int
    issues: tuple
    selected_face_ids: tuple
    context_signature: tuple
    boundary_signature: tuple
    witness_json: str
    source_bindings: tuple
    status: str = 'ALL_AGGREGATE_AMBIGUITIES_REPORTED_NO_OPERATOR_CERTIFICATE'
    complete_aggregate_scan: bool = True
    partial_operator_certificate: bool = False
    interval_validity: str = 'CALLER_WITNESSED_NOT_REPROVED_BY_ASSEMBLER'
    inventory_coverage_certified: bool = False
    native_workbudget_admitted: bool = False


class OwnedAssessment(B.OwnedAssembly):
    """Borrow a CertifiedAssembly OR RefinementRequired while this owner lives."""

    def rounded_system(self, boundary, *, cancel=None):
        B._check(cancel)
        if isinstance(self.value, RefinementRequired):
            raise UnresolvedRounding('Aggregate refinement request has no rounded operator to solve')
        return super().rounded_system(boundary, cancel=cancel)


def _rounded(bounds, label, gmp, cancel=None):
    lo, hi = bounds
    lower, upper = dec(lo, cancelled=cancel), dec(hi, cancelled=cancel)
    if not lower.is_finite() or not upper.is_finite() or lower != upper:
        raise UnresolvedRounding(label+': endpoint Decimal-80 rounding differs or is nonfinite')
    if lo == hi:
        return lower
    if not lower:
        raise UnresolvedRounding(label+': non-singleton zero is not an exact-zero proof')
    centre = B._q(lower, gmp)
    for neighbour in (lower.next_minus(), lower.next_plus()):
        B._check(cancel)
        if neighbour.is_finite():
            midpoint = (centre+B._q(neighbour, gmp))/2
            if lo <= midpoint <= hi:
                raise UnresolvedRounding(label+': non-singleton interval touches a rounding tie')
    return lower


def assemble(rows, cell_count, boundary, *, witness, source_bindings, budget,
             inventory, cancel=None):
    """Same fail-fast certificate API; all arithmetic/output ordering preserved."""
    return _run(rows, cell_count, boundary, witness=witness, source_bindings=source_bindings,
        budget=budget, inventory=inventory, refinement_bytes=0, collect=False, cancel=cancel)


def assess(rows, cell_count, boundary, *, witness, source_bindings, budget,
           inventory, refinement_bytes, cancel=None):
    """Return owned success OR the complete immutable aggregate request.

    The unique requested faces follow the ORIGINAL physical input row order,
    not lexical identifier order. Issues follow operator owner/column order,
    then wall owner order. Contributions retain face/key encounter order and
    their exact signed bounds. Keep this owner alive while using its request;
    drop/transfer borrowed values before closing it. A subsequent refinement
    must independently prove same-input functional identity and bound validity.
    Repeated assessment must independently admit all simultaneous generations.
    """
    if type(refinement_bytes) is not int or refinement_bytes <= 0:
        raise ValueError('Explicit positive diagnostic refinement storage allowance required')
    return _run(rows, cell_count, boundary, witness=witness, source_bindings=source_bindings,
        budget=budget, inventory=inventory, refinement_bytes=refinement_bytes, collect=True, cancel=cancel)


def _run(rows, cell_count, boundary, *, witness, source_bindings, budget,
         inventory, refinement_bytes, collect, cancel):
    B._check(cancel)
    if type(cell_count) is not int or cell_count <= 0:
        raise ValueError('Positive explicit cell count required')
    if type(inventory) is not DiagnosticInventory:
        raise ValueError('Explicit diagnostic inventory required; production sizing remains unresolved')
    amount = inventory.total()+refinement_bytes
    if amount > sys.maxsize:
        raise OverflowError('Combined diagnostic inventory exceeds addressable storage')
    gmp = B._library()
    import private_heat_gmp_resources_r1 as resources
    workspace = resources.OwnedWorkspace(budget, amount,
        category='heat-interval-assessment-private' if collect else 'heat-interval-assembly-private',
        cancelled=cancel)
    workspace.__enter__()
    try:
        result = _assemble(rows, cell_count, boundary, witness=witness,
            source_bindings=source_bindings, cancel=cancel, gmp=gmp, collect=collect)
        return OwnedAssessment(result, workspace) if collect else B.OwnedAssembly(result, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def _assemble(rows, cell_count, boundary, *, witness, source_bindings, cancel, gmp, collect):
    if not isinstance(witness, dict) or not witness or not isinstance(source_bindings, dict) or not source_bindings:
        raise ValueError('Explicit nonempty witness and source-binding metadata required')
    for name, digest in source_bindings.items():
        B._check(cancel)
        if (not isinstance(name, str) or not name or not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)):
            raise ValueError('Source bindings require named lowercase SHA256 digests')
    witness_json = json.dumps(witness, sort_keys=True, separators=(',', ':'), allow_nan=False)
    boundary_identity = B._boundary_signature(boundary, gmp, cancel)
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        zero = (gmp.mpq(0), gmp.mpq(0))
        op = [{} for _ in range(cell_count)]
        wall = [zero for _ in range(cell_count)]
        certified_rows, face_ids, face_order = [], set(), []
        contributors = {} if collect else None
        for row in rows:
            B._check(cancel)
            fid = row['face_id']
            owners = tuple(tuple(owner) for owner in row['owners'])
            keys = tuple(tuple(key) for key in row['ordered_keys'])
            if not isinstance(fid, str) or not fid or fid in face_ids:
                raise ValueError('One unique nonempty physical face identifier required')
            face_ids.add(fid)
            face_order.append(fid)
            if (len(owners) not in (1, 2) or any(len(owner) != 2 or type(owner[0]) is not int
                    or not 0 <= owner[0] < cell_count or type(owner[1]) is not int
                    or owner[1] not in (-1, 1) for owner in owners)
                    or len(owners) == 2 and (owners[0][0] == owners[1][0] or owners[0][1] != -owners[1][1])):
                raise ValueError('Valid one/two opposite physical face owners required')
            if len(set(keys)) != len(keys) or set(keys) != set(row['bounds']):
                raise ValueError('Ordered unique observation keys and complete matching bounds required')
            weights = []
            for key in keys:
                B._check(cancel)
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
                bounds = tuple(B._q(value, gmp) for value in row['bounds'][key])
                if len(bounds) != 2 or bounds[0] > bounds[1]:
                    raise ValueError('Ordered lower/upper exact coefficient bounds required')
                weights.append((key, _rounded(bounds, 'face '+fid, gmp, cancel)))
                for owner, sign in owners:
                    B._check(cancel)
                    if kind == 'cell':
                        contribution = B._scale(bounds, sign)
                        op[owner][index] = B._add(op[owner].get(index, zero), contribution)
                        label_key = ('operator', owner, index)
                    else:
                        contribution = B._scale(bounds, sign*B._q(boundary[index][1], gmp))
                        wall[owner] = B._add(wall[owner], contribution)
                        label_key = ('wall', owner, None)
                    if collect and contribution != zero:
                        contributors.setdefault(label_key, []).append(Contribution(fid, key, sign, contribution))
            certified_rows.append(CertifiedFace(fid, owners, tuple(weights)))
        rounded_op, issues = [], []
        def rounded_or_issue(bounds, label, kind, owner, column=None):
            try:
                return _rounded(bounds, label, gmp, cancel)
            except UnresolvedRounding as error:
                if not collect:
                    raise
                issues.append(AmbiguousAggregate(label, kind, owner, column, bounds,
                    tuple(contributors.get((kind, owner, column), ())), str(error)))
                return None  # Never exposed as a partial numerical certificate.
        for i, row in enumerate(op):
            entries = []
            for j in sorted(row):
                B._check(cancel)
                bounds = row[j]
                if bounds == zero:
                    continue
                entries.append((j, rounded_or_issue(bounds, 'operator '+str((i, j)), 'operator', i, j)))
            rounded_op.append(tuple(entries))
        rounded_wall = []
        for i, bounds in enumerate(wall):
            B._check(cancel)
            rounded_wall.append(rounded_or_issue(bounds, 'wall '+str(i), 'wall', i))
        bindings = tuple(sorted(source_bindings.items()))
        if issues:
            requested = {part.face_id for item in issues for part in item.contributions}
            return RefinementRequired(cell_count, tuple(issues),
                tuple(fid for fid in face_order if fid in requested), context_signature=B.context_signature(context),
                boundary_signature=boundary_identity, witness_json=witness_json, source_bindings=bindings)
        return CertifiedAssembly(cell_count, tuple(rounded_op), tuple(rounded_wall), tuple(certified_rows),
            sum(map(len, rounded_op)), B.context_signature(context), boundary_identity,
            witness_json, bindings)
