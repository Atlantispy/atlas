"""Plan40B C8: exact unit-owner scaling in the complete r2 assembler.

Additive successor of selected r2, preserving its API, checks and ownership.
Only validated cell-owner +/-1 scaling changes. No source selection, inventory
reduction, production dispatch or acceptance is implied by this module.

Private complete aggregate-rounding census and exact assembly.

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

from atlas_tectonics._private.integration.heat import endpoint_assembly as B
from atlas_tectonics._private.integration.heat.rational_decimal_kernel import dec

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
    lower = dec(lo, cancelled=cancel)
    equal = lo == hi
    upper = lower if equal else dec(hi, cancelled=cancel)    # an equal pair is decoded once
    if not lower.is_finite() or not upper.is_finite() or lower != upper:
        raise UnresolvedRounding(label+': endpoint Decimal-80 rounding differs or is nonfinite')
    if equal:
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


def assemble(rows, cell_count, boundary, *, witness, budget,
             inventory, cancel=None):
    """Same fail-fast certificate API; all arithmetic/output ordering preserved."""
    return _run(rows, cell_count, boundary, witness=witness,
        budget=budget, inventory=inventory, refinement_bytes=0, collect=False, cancel=cancel)


def assess(rows, cell_count, boundary, *, witness, budget,
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
    return _run(rows, cell_count, boundary, witness=witness,
        budget=budget, inventory=inventory, refinement_bytes=refinement_bytes, collect=True, cancel=cancel)


def _run(rows, cell_count, boundary, *, witness, budget,
         inventory, refinement_bytes, collect, cancel):
    B._check(cancel)
    amount = inventory.total()+refinement_bytes
    gmp = B._library()
    from atlas_tectonics._private.integration.heat import gmp_resources as resources
    workspace = resources.OwnedWorkspace(budget, amount,
        category='heat-interval-assessment-private' if collect else 'heat-interval-assembly-private',
        cancelled=cancel)
    workspace.__enter__()
    try:
        result = _assemble(rows, cell_count, boundary, witness=witness,
            cancel=cancel, gmp=gmp, collect=collect)
        return OwnedAssessment(result, workspace) if collect else B.OwnedAssembly(result, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise


def _face_settings(context, gmp):
    # Only the private unobserved context may omit Decimal operations.
    # Flags die with this local context; traps and every effective setting do not.
    return (dec, gmp, gmp.mpq, context.prec, context.rounding, context.Emin,
            context.Emax, context.clamp, context.capitals, tuple(context.traps.items()))


def _assemble(rows, cell_count, boundary, *, witness, cancel, gmp, collect, owned=False,
              _face_pass=None, _refined=None):
    if not isinstance(witness, dict) or not witness:
        raise ValueError('Explicit nonempty witness required')
    witness_json = json.dumps(witness, sort_keys=True, separators=(',', ':'), allow_nan=False)
    boundary_identity = B._boundary_signature(boundary, gmp, cancel)
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        record_pass = owned and _face_pass is not None
        stamp = _face_settings(context, gmp) if record_pass else None
        reuse_faces = record_pass and _refined is not None and _face_pass[0] == stamp
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
            face_ids.add(fid)
            face_order.append(fid)
            # The private merge preserves every original row absent from used.
            # Previously selected rows always receive the complete check again.
            reuse_row = reuse_faces and fid not in _refined
            if reuse_row:
                _face_pass[1] += 1
            face_label = 'face '+fid    # built once a face, not once a key
            weights = []
            for key in keys:
                B._check(cancel)
                kind, index = key
                if kind == 'cell':
                    if not owned and (type(index) is not int or not 0 <= index < cell_count):
                        raise ValueError('Cell observation outside the original cell ordering')
                elif not owned and kind not in ('wall', 'power'):
                    raise ValueError('Observation kind must be cell, wall or power')
                elif not owned and index not in boundary:
                    raise ValueError('Boundary observation has no explicit prescribed value')
                elif boundary[index][0] != ('temperature' if kind == 'wall' else 'power'):
                    raise ValueError('Boundary observation kind does not match its declaration')
                bounds = tuple(B._q(value, gmp) for value in row['bounds'][key])
                word = (dec(bounds[0], cancelled=cancel) if reuse_row else
                        _rounded(bounds, face_label, gmp, cancel))
                weights.append((key, word))
                for owner, sign in owners:
                    B._check(cancel)
                    if kind == 'cell':
                        # Owners were validated as exact integer +/-1 above;
                        # _q has already made both endpoints immutable GMP rationals.
                        contribution = bounds if sign == 1 else (-bounds[1], -bounds[0])
                        if not owned or index in op[owner]:
                            op[owner][index] = B._add(op[owner].get(index, zero), contribution)
                        else:
                            op[owner][index] = contribution
                        label_key = ('operator', owner, index)
                    else:
                        contribution = B._scale(bounds, sign*B._q(boundary[index][1], gmp))
                        wall[owner] = B._add(wall[owner], contribution)
                        label_key = ('wall', owner, None)
                    if collect and contribution != zero:
                        contributors.setdefault(label_key, []).append(Contribution(fid, key, sign, contribution))
            certified_rows.append(CertifiedFace(fid, owners, tuple(weights)))
        if record_pass:
            # All faces passed before any aggregate request can be returned.
            # No old row, Decimal word or assessment owner is retained.
            _face_pass[0] = stamp
        rounded_op, issues = [], []
        def rounded_or_issue(bounds, kind, owner, column=None):
            try:
                return _rounded(bounds, '', gmp, cancel)
            except UnresolvedRounding as error:
                # the label is built only on failure; the message text is unchanged.
                label = kind+' '+str(owner if column is None else (owner, column))
                error.args = (label+error.args[0],)
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
                entries.append((j, rounded_or_issue(bounds, 'operator', i, j)))
            rounded_op.append(tuple(entries))
        rounded_wall = []
        for i, bounds in enumerate(wall):
            B._check(cancel)
            rounded_wall.append(rounded_or_issue(bounds, 'wall', i))
        if issues:
            requested = {part.face_id for item in issues for part in item.contributions}
            return RefinementRequired(cell_count, tuple(issues),
                tuple(fid for fid in face_order if fid in requested), context_signature=B.context_signature(context),
                boundary_signature=boundary_identity, witness_json=witness_json)
        return CertifiedAssembly(cell_count, tuple(rounded_op), tuple(rounded_wall), tuple(certified_rows),
            sum(map(len, rounded_op)), B.context_signature(context), boundary_identity,
            witness_json)
