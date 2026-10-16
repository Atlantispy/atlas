"""Closed, space-time finite-volume transport with disappearing cut cells.

The geometry producer owns physical support and the interval flux certificate.
This operator checks its exact discrete GCL. Backward-Euler upwinding is an
explicitly selected FIRST-ORDER method, never a fallback from MUSCL/SSPRK2.
Reference: Schlichting & Seis (2018), doi:10.1007/s00211-017-0935-1,
implicit upwind method; moving geometry uses integrated ALE face measures.
The fixed-mesh paper does not establish accuracy of our geometry producer.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import weakref
import live_spatial_patch as LIVE_SPATIAL
import live_finite_patch as LIVE_FINITE
import live_transport_result as LIVE_TRANSPORT

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import gmres

from ._validation import TectonicsError
from .integration_mimetic_heat import _enc, _q
from .integration_regional_inventory import _width, _project
from .regional_execution import RegionalMechanicalSnapshot
from .regional_heat3d import _cancel
from .resources import WorkBudget, _GrowingLease
from .stokes_execution import _native_lease

# Iterative refinement of the implicit solve stops at this componentwise
# backward error, after this many corrections, when a correction does not
# converge or fails to halve the largest residual (one that does not reduce
# it is not kept), or when that residual is below the double range.
COMPONENTWISE_BACKWARD_ERROR = Q(1, 2**40)
MAX_REFINEMENTS = 32
# Refinement does not resolve what a double cannot hold. The floor is the
# smallest positive normal double, applied before the binary projection to a
# cell's concentration and, where it has an endpoint volume, to its stock.
_FLOOR = Q(1, 2**1022)

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _retain(obj, size, budget):
    lease = budget.reserve(size, category='spatial-transport-result')
    lease.__enter__()
    weakref.finalize(obj, lease.__exit__, None, None, None)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SpatialTransportResult:
    _snapshot: RegionalMechanicalSnapshot = field(repr=False)
    _budget: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('spatial transport results are issued by their prepared operator')

    @property
    def result_id(self):
        return self._snapshot.result_id

    def record(self):
        return LIVE_TRANSPORT.result_record(self)

    def arrays(self):
        return {name: self._snapshot.array(name) for name in self._snapshot.array_names}


class _EscapingWorkspace:
    """Keep admitted work charged while a failed frame retains its objects."""
    def __init__(self, stack):
        self._finalizer = weakref.finalize(self, stack.close)


def _preserve_workspace(error, stack):
    """Transfer existing leases without a new admission on the failure path."""
    owner = _EscapingWorkspace(stack.pop_all())
    previous = getattr(error, '_integration_workspace_owners', ())
    error._integration_workspace_owners = previous + (owner,)
    return owner


class _workspace:
    """Scoped leases survive an escaping exception or separately held traceback."""
    def __init__(self, budget, count, category):
        self.stack = ExitStack()
        self.budget, self.count, self.category = budget, count, category

    def __enter__(self):
        self.stack.enter_context(self.budget.reserve(self.count, category=self.category))
        return self.stack

    def __exit__(self, kind, error, traceback):
        if error is None:
            self.stack.close()
            return False
        # Explicit re-raise keeps this owner-bearing frame in a separately
        # retained traceback; contextlib's generator wrapper trims its frame.
        failure_owner = _preserve_workspace(error, self.stack)
        raise error.with_traceback(traceback)


def _integer_storage(bits):
    return 40 + sys.int_info.sizeof_digit * ((max(1, bits) +
        sys.int_info.bits_per_digit - 1) // sys.int_info.bits_per_digit)


def _hex_pair_bits(pair):
    # Existing _q remains the validator and numerical decoder.
    if type(pair) is not list or len(pair) != 2 or any(type(v) is not str for v in pair):
        return 1, 1
    return max(1, 4 * len(pair[0])), max(1, 4 * len(pair[1]))


def _exact_bits(value):
    if type(value) is Q:
        return max(1, abs(value.numerator).bit_length()), value.denominator.bit_length()
    if type(value) is int:
        return max(1, abs(value).bit_length()), 1
    return 1, 1


def _rational_storage(bits):
    return 64 + sum(_integer_storage(n) for n in bits)


def _rational_encoding_storage(bits):
    return 128 + sum(96 + (n + 3) // 4 for n in bits)


def _difference_bits(a, b):
    return max(a[0] + b[1], b[0] + a[1]) + 1, a[1] + b[1]


def _sum_profile_bits(profile):
    denominator, numerator, count = profile
    return denominator + numerator + (count + 1).bit_length() + 1, max(1, denominator)


def _add_profile(profile, bits):
    profile[0] += bits[1]
    profile[1] = max(profile[1], bits[0])
    profile[2] += 1


# Any character that ensure_ascii does not emit as itself in one byte: all but
# printable ASCII without the quotation mark and backslash. The pattern is raw
# so that its own parser reads the \x escapes: a literal 0x5d would end the class.
_JSON_ESCAPED = re.compile(r'[^\x20\x21\x23-\x5b\x5d-\x7e]')


def _json_encoding_capacity(value, budget):
    """Prospective capacity for this module's exact ensure_ascii JSON codec.

    No input graph is decoded/copied. ASCII escaping is counted character by
    character, including surrogate pairs. Integer decimal length is bounded
    from bit length without formatting it. The transient allowance covers the
    Unicode result, encoder accumulation/join buffers, scalar chunk headers,
    sort-key item tuples and marker tables. Returned bytes have a separate
    lifetime. The bounded traversal itself owns only its active ancestor set.
    """
    def string_size(text):
        # An exact str with no escaped character costs its two quotes and one
        # byte per character, exactly what the loop below counts; the scan
        # copies nothing. A str subclass may iterate differently from its
        # buffer, so it is always counted by the loop.
        if type(text) is str and _JSON_ESCAPED.search(text) is None:
            return 2 + len(text)
        size = 2
        for char in text:
            n = ord(char)
            size += (2 if char in '"\\\b\f\n\r\t' else 6 if n < 32 or 126 < n <= 65535
                     else 12 if n > 65535 else 1)
        return size

    def atom_size(atom, *, key=False):
        if isinstance(atom, str):
            return string_size(atom)
        if atom is None:
            size = 4
        elif isinstance(atom, bool):
            size = 4 if atom else 5
        elif isinstance(atom, int):
            size = max(1, (abs(atom).bit_length() * 30103) // 100000 + 1) + (atom < 0)
        elif isinstance(atom, float):
            if not math.isfinite(atom):
                raise ValueError('Out of range float values are not JSON compliant')
            size = 32
        else:
            raise TypeError('Object of type ' + type(atom).__name__ + ' is not JSON serializable')
        return size + (2 if key else 0)

    length = atoms = containers = entries = deepest = 0
    active = set()
    with _workspace(budget, 65536, 'graph-json-accounting-scan') as workspace:
        scan = workspace.enter_context(_GrowingLease(budget))

        def visit(node, depth):
            nonlocal length, atoms, containers, entries, deepest
            if depth > deepest:
                scan.add(2048 * (depth - deepest), category='graph-json-accounting-scan')
                deepest = depth
            if isinstance(node, (dict, list, tuple)):
                identity = id(node)
                if identity in active:
                    raise ValueError('Circular reference detected')
                active.add(identity)
                containers += 1
                length += 2 + max(0, len(node) - 1)
                try:
                    if isinstance(node, dict):
                        entries += len(node)
                        length += len(node)
                        for key, child in node.items():
                            length += atom_size(key, key=True)
                            atoms += 1
                            visit(child, depth + 1)
                    else:
                        for child in node:
                            visit(child, depth + 1)
                finally:
                    active.remove(identity)
            else:
                length += atom_size(node)
                atoms += 1

        visit(value, 1)
    encoded = 64 + length
    temporary = 65536 + 3 * length + 96 * atoms + 192 * containers + 96 * entries
    return encoded, temporary


def _transport_plan_capacity(rows, faces, budget):
    """Retained plan versus construction scratch, from actual row/arc shape.

    Per-node incoming/outgoing rational sums use denominator-product bit
    bounds for their own incident arcs. No global denominator is replicated
    over the graph. Floor/division products include the exact 2**1022 scale.
    """
    n, f = len(rows), len(faces)
    with _workspace(budget, 65536 + 1024 * n, 'transport-accounting-scan'):
        indices = {row.get('cell_id'): i for i, row in enumerate(rows)}
        starts = [_hex_pair_bits(row['start_volume_m3']) for row in rows]
        ends = [_hex_pair_bits(row['end_volume_m3']) for row in rows]
        incoming = [[1, 1, 0] for _ in rows]
        outgoing = [[1, 1, 0] for _ in rows]
        retained = 65536 + 512 * (n + f)
        largest = 1
        face_n = face_d = 1
        for row in rows:
            for name in ('start_volume_m3', 'end_volume_m3'):
                bits = _hex_pair_bits(row[name])
                retained += _rational_storage(bits)
                largest = max(largest, sum(bits))
        for face in faces:
            bits = _hex_pair_bits(face['volume_m3'])
            retained += _rational_storage(bits)
            face_n, face_d = max(face_n, bits[0]), max(face_d, bits[1])
            largest = max(largest, sum(bits))
            for field, profiles in (('donor', outgoing), ('receiver', incoming)):
                at = indices.get(face.get(field))
                if at is not None:
                    _add_profile(profiles[at], bits)
        sums = 0
        for start, end, inc, out in zip(starts, ends, incoming, outgoing):
            inc_sum, out_sum = _sum_profile_bits(inc), _sum_profile_bits(out)
            sums += _rational_storage(inc_sum) + _rational_storage(out_sum)
            # Exact GCL can form a+incoming-out even for a refused graph.
            gcl = _difference_bits(_difference_bits(start, inc_sum), out_sum)
            largest = max(largest, sum(inc_sum), sum(out_sum), sum(gcl))
            _add_profile(out, end)
            diagonal = _sum_profile_bits(out)
            floor = diagonal[0] + end[1] + 2, diagonal[1] + 1023 + end[0] + 2
            retained += _rational_storage(diagonal) + _rational_storage(floor)
            largest = max(largest, sum(diagonal), sum(floor),
                          face_n + diagonal[1] + face_d + diagonal[0])
        # CSR value/index/pointer storage; COO/conversion/sorting buffers are
        # transient. Eight-byte indices are allowed even on small fixtures.
        csr = 4096 + 48 * (n + f) + 16 * (n + 1)
        retained += csr
        transient = (65536 + 1024 * (n + f) + 4 * csr + sums +
                     64 * _integer_storage(2 * largest + 32))
        return retained, transient


class PreparedSpatialTransport:
    """One geometry interval, reusable for independent current material fields.

    M*c = old, M_ii=V_end+outflow, M_ji=-F(i->j).
    Columns sum to V_end, rows to V_start by the exact GCL. Each cell must
    reach a positive endpoint-volume cell, which makes M a nonsingular
    M-matrix. Thus the exact solve is nonnegative and conservative even when
    V_end=0. No cell-volume floor, sliver deletion or explicit tiny-cell CFL.

    Actual linear/projection error is calculated with rational arithmetic and
    remains a separate signed account. It is never hidden as added material.
    Caller-supplied absolute error bounds apply to the sum of absolute local
    residuals, not merely the global cancellation. Geometric error is separate.

    The Krylov solve is refined on its exact residual until every cell that
    a double can hold is resolved, not only the field norm. The declared
    error of a refined field is at the rounding level of its one binary
    projection; it is not guaranteed to be below the single solve's. A
    refined field that the positivity, projection or bound check refuses is
    replaced by the single solve's, so those checks pass every field that
    the single solve passes.
    """
    def __init__(self, geometry, *, budget, max_iterations=1000):
        self._closed, self._active, self._guard = False, False, None
        if type(budget) is not WorkBudget or not LIVE_SPATIAL.is_record(geometry):
            raise TectonicsError('explicit space-time graph and shared WorkBudget required')
        if type(max_iterations) is not int or max_iterations < 1:
            raise TectonicsError('positive bounded linear iteration count required')
        self._budget, self._max_iterations = budget, max_iterations
        rows = geometry.get('cells'); faces = geometry.get('transfers')
        if not LIVE_SPATIAL.is_rows(rows) or not rows or not LIVE_SPATIAL.is_rows(faces):
            raise TectonicsError('complete cell and directed transfer tables required')
        encoded_bytes, encoding_scratch = LIVE_SPATIAL.graph_encoding(geometry, budget, _json_encoding_capacity)
        plan_bytes, plan_scratch = _transport_plan_capacity(rows, faces, budget)
        self._guard = ExitStack()
        try:
            self._guard.enter_context(budget.reserve(encoded_bytes+plan_bytes,
                category='spatial-transport-plan'))
            self._guard_finalizer = weakref.finalize(self, self._guard.close)
            with _workspace(budget, encoding_scratch, 'spatial-transport-encoding'):
                self._encoded = LIVE_SPATIAL.graph_encoded(geometry, _json)
            self.geometry_id = LIVE_SPATIAL.graph_identity(geometry, lambda value: hashlib.sha256(self._encoded).hexdigest())
            with _workspace(budget, plan_scratch, 'spatial-transport-construction'):
                keys, start, end = {}, [], []
                for row in rows:
                    key = row.get('cell_id')
                    if type(key) is not str or not key or key in keys:
                        raise TectonicsError('unique persistent spatial cell IDs required')
                    a, b = _q(row['start_volume_m3']), _q(row['end_volume_m3'])
                    if min(a, b) < 0:
                        raise TectonicsError('negative space-time cell volume')
                    keys[key] = len(keys); start.append(a); end.append(b)
                nc = len(keys)
                out = [Q(0)]*nc; incoming = [Q(0)]*nc
                reverse = [[] for _ in keys]
                transfers, face_ids = [], set()
                for row in faces:
                    fid = row.get('face_id')
                    if type(fid) is not str or not fid or fid in face_ids:
                        raise TectonicsError('unique directed space-time face IDs required')
                    face_ids.add(fid)
                    donor, receiver = row.get('donor'), row.get('receiver')
                    if donor not in keys or receiver not in keys or donor == receiver:
                        raise TectonicsError('both finite distinct material owners required')
                    volume = _q(row['volume_m3'])
                    if volume <= 0:
                        raise TectonicsError('strictly positive directed face measure required')
                    i, j = keys[donor], keys[receiver]
                    transfers.append((i, j, volume)); out[i] += volume; incoming[j] += volume
                    reverse[j].append(i)
                if any(b != a+f-o for a, b, f, o in zip(start, end, incoming, out)):
                    raise TectonicsError('space-time graph violates exact GCL; do not renormalise it')
                anchored = {i for i, volume in enumerate(end) if volume > 0}
                pending = list(anchored)
                while pending:
                    for i in reverse[pending.pop()]:
                        if i not in anchored:
                            anchored.add(i); pending.append(i)
                if len(anchored) != nc:
                    raise TectonicsError('unanchored transient flow component has no unique endpoint solution')
                diagonal = tuple(b+f for b, f in zip(end, out))
                # Solve for w=D*c. Column scaling avoids division by the potentially
                # vanishing endpoint volume and needs no sparse direct factor.
                matrix_rows = list(range(nc)); matrix_cols = list(range(nc)); data = [1.]*nc
                for i, j, volume in transfers:
                    matrix_rows.append(j); matrix_cols.append(i); data.append(-_project(volume/diagonal[i]))
                self._matrix = sparse.coo_matrix((data, (matrix_rows, matrix_cols)), shape=(nc, nc)).tocsr()
                self._matrix.sum_duplicates()
                self._keys, self._start, self._end = tuple(keys), tuple(start), tuple(end)
                self._transfers, self._diagonal = tuple(transfers), diagonal
                # D*c at which a cell's concentration c and endpoint stock
                # V_end*c both reach the floor.
                self._floor = tuple(_FLOOR*d/(min(b, 1) or 1) for d, b in zip(diagonal, end))
                # Width of one exact residual evaluation: a share
                # volume/diagonal for every transfer and a floor for every cell.
                self._wide = sum(_width(v)+_width(diagonal[i]) for i, _, v in transfers)+_width(self._floor)
                self._stats = dict(advances=0, krylov_iterations=0, matrix_builds=1)
                self._verify()
                # Drop scratch containers before their construction lease.
                del keys, start, end, out, incoming, reverse, transfers, face_ids
                del anchored, pending, matrix_rows, matrix_cols, data
        except BaseException as error:
            # Locals still own plan arrays/bytes through the escaping frame.
            # Empty self's stack before close detaches its ordinary finalizer.
            failure_owner = _preserve_workspace(error, self._guard)
            self.close(); raise

    def _verify(self):
        if self._closed or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
            raise TectonicsError('closed or changed spatial transport operator')

    @contextmanager
    def _operation(self, cancel):
        self._verify(); _cancel(cancel)
        if self._active:
            raise TectonicsError('spatial transport operator already active')
        self._active = True
        try:
            with _native_lease():
                yield
            self._verify(); _cancel(cancel)
        finally:
            self._active = False

    def advance(self, stocks, *, state_id, source_stage_id, max_projection_errors,
                nonnegative_fields, cancel=None):
        """Exact extensive fields ordered by graph cell IDs, before any diffusion.

        max_projection_errors is an explicit absolute bound in each field's
        units. It cannot establish spatial/time accuracy or physical realism.
        Zero bound is permitted for exactly representable controls.

        field_errors[name] carries componentwise_refinements,
        componentwise_backward_error and componentwise_backward_error_limit
        exactly when the first Krylov solve left that field's componentwise
        backward error above COMPONENTWISE_BACKWARD_ERROR and MAX_REFINEMENTS
        is positive. No correction solve is made for a field without them,
        which has the stocks and record of the single solve. The count is of
        the corrections kept in the recorded stocks and can be zero. The
        error is that of the recorded stocks, the largest
        |account_i|/(|old_i|+|new_i|+sum|transfers of i|) over the cells
        whose old stock and inflow together reach the floor, and can exceed
        the limit recorded beside it when refinement stopped early.
        krylov_iterations counts every solve, kept or not.
        """
        if any(type(v) is not str or not v for v in (state_id, source_stage_id)):
            raise TectonicsError('actual parent and pre-advection source stage IDs required')
        if not LIVE_FINITE.is_stocks(stocks, self._budget) or not stocks or type(max_projection_errors) is not dict:
            raise TectonicsError('complete named extensive stocks and numerical bounds required')
        if set(stocks) != set(max_projection_errors) or not set(nonnegative_fields) <= set(stocks):
            raise TectonicsError('all fields need explicit numerical bounds and positivity declarations')
        if any(type(k) is not str or not k for k in stocks):
            raise TectonicsError('named extensive fields required')
        nc = len(self._keys); nf = len(self._transfers)
        size = _width(stocks)+_width(max_projection_errors)
        # Refinement holds exact residual arrays as wide as the plan's shares
        # and floors, with a few weights for every cell and transfer.
        allowance = 131072+24*size+512*(nc+nf)*(len(stocks)+2)+8*nc*(min(40, nc)+8)+4*self._wide
        with self._operation(cancel), ExitStack() as leases:
            leases.enter_context(self._budget.reserve(allowance, category='spatial-transport-step'))
            exact_old, exact_new, exact_faces, exact_residual, binary_residual, projected = {}, {}, {}, {}, {}, {}
            field_errors, iterations = {}, [0]
            for name in sorted(stocks):
                _cancel(cancel)
                try:
                    old = tuple(Q(v) for v in stocks[name]); bound = Q(max_projection_errors[name])
                except (ValueError, TypeError, OverflowError) as exc:
                    raise TectonicsError('finite exact spatial stocks and absolute bounds required') from exc
                if len(old) != nc or bound < 0:
                    raise TectonicsError('stock shape or numerical bound invalid')
                if any(v != 0 and vol == 0 for v, vol in zip(old, self._start)):
                    raise TectonicsError('an initially absent cell cannot contain invented material')
                if name in nonnegative_fields and any(v < 0 for v in old):
                    raise TectonicsError('negative declared nonnegative input stock')
                exact_old[name] = old
                refinements, refining, single = 0, False, None
                densities = {v/vol for v, vol in zip(old, self._start) if vol > 0}
                if len(densities) == 1:
                    # Exact free-stream preservation is implied by GCL, not a
                    # fitted solver exception. Empty transit cells are included.
                    concentration = (next(iter(densities)),)*nc
                else:
                    scale = max(map(abs, old), default=Q(0))
                    if not scale:
                        concentration = (Q(0),)*nc
                    else:
                        # Every exact right-hand side, floor, residual and
                        # size entry of this field is as wide as its scale.
                        leases.enter_context(self._budget.reserve(8*nc*_width(scale),
                                                                  category='spatial-transport-step'))
                        rhs = tuple(v/scale for v in old)
                        def callback(_):
                            iterations[0] += 1; _cancel(cancel)
                        def solve(values):
                            answer, info = gmres(self._matrix, np.asarray(values), rtol=1e-13, atol=0.,
                                restart=min(40, nc), maxiter=self._max_iterations,
                                callback=callback, callback_type='legacy')
                            if info or not np.isfinite(answer).all():
                                return None
                            return [Q(float(w)) for w in answer]
                        first = weights = solve([_project(v) for v in rhs])
                        if first is None:
                            raise TectonicsError('spatial transport linear solve did not converge')
                        # The Krylov residual is small in the norm of the
                        # WHOLE field. Material reaching a cell through a
                        # chain of small volumes can be below it and be lost
                        # entirely: a born cell left with no mass or heat.
                        # Iterative refinement on the exact rational residual
                        # r=b-Mw continues until the componentwise backward
                        # error max|r_i|/(|b_i|+(|M||w|)_i) is at rounding
                        # level. Each correction resolves what is above the
                        # Krylov tolerance of the CURRENT residual, so a chain
                        # of small volumes is resolved link by link while that
                        # error stays at one: progress is judged by the
                        # largest residual, which must at least halve, and an
                        # iterate that does not reduce it is not kept.
                        # Corrections are added exactly; a field the first
                        # solve resolves is unchanged. A correction solve
                        # that does not converge ends refinement with the
                        # iterate reached: only the first solve refuses.
                        # What a double cannot hold is not resolved. While
                        # all that enters a cell, |b_i|+sum|M_ij w_j| over
                        # j!=i, is below its floor, the cell is left out of
                        # the maximum and of the largest residual and its
                        # residual is not corrected. A refined weight below
                        # its floor is not introduced: the cell keeps the
                        # weight it had and the amount stays in its signed
                        # local account.
                        floor = [f/scale for f in self._floor]
                        previous = None
                        while True:
                            defect, size = list(rhs), list(map(abs, rhs))
                            for at, w in enumerate(weights):
                                defect[at] -= w; size[at] += abs(w)
                            for i, j, volume in self._transfers:
                                moved = volume/self._diagonal[i]*weights[i]
                                defect[j] += moved; size[j] += abs(moved)
                            fed = [s-abs(w) >= f for s, w, f in zip(size, weights, floor)]
                            backward = max((abs(r)/s for r, s, k in zip(defect, size, fed) if k), default=Q(0))
                            largest = max((abs(r) for r, k in zip(defect, fed) if k), default=Q(0))
                            if previous is None:
                                refining = backward > COMPONENTWISE_BACKWARD_ERROR and MAX_REFINEMENTS > 0
                            elif largest >= previous[0]:
                                weights = previous[1]; refinements -= 1
                                break
                            if (backward <= COMPONENTWISE_BACKWARD_ERROR or refinements == MAX_REFINEMENTS or
                                    previous is not None and 2*largest > previous[0] or not float(largest)):
                                break
                            # A power of two keeps every weight a short dyadic rational.
                            unit = Q(2)**math.frexp(float(largest))[1]
                            correction = solve([float(r/unit) if k else 0. for r, k in zip(defect, fed)])
                            if correction is None:
                                break
                            previous = largest, weights
                            refined = [w+c*unit for w, c in zip(weights, correction)]
                            weights = [v if abs(v) >= f or not v else w for w, v, f in zip(weights, refined, floor)]
                            refinements += 1
                        if refinements:
                            single = first
                        # One explicit binary projection bounds active-state
                        # rational width by current geometry, not number of
                        # preceding intervals. Its actual error is included
                        # in the exact local conservation residual below.
                        concentration = tuple(Q(_project(w*scale/d)) for w, d in zip(weights, self._diagonal))
                while True:
                    try:
                        if name in nonnegative_fields and any(c < 0 for c in concentration):
                            raise TectonicsError('negative implicit concentration; no clipping permitted')
                        new = tuple(v*c for v, c in zip(self._end, concentration))
                        moved = tuple(volume*concentration[i] for i, _, volume in self._transfers)
                        residual = [a-b for a, b in zip(old, new)]
                        for (i, j, _), amount in zip(self._transfers, moved):
                            residual[i] -= amount; residual[j] += amount
                        binary = np.asarray(list(map(_project, new)))
                        projection = tuple(v-Q(float(f)) for v, f in zip(new, binary))
                        error = sum(map(abs, residual), Q(0))+sum(map(abs, projection), Q(0))
                        if error > bound:
                            raise TectonicsError(f'{name} exact local projection residual exceeds declared bound')
                        break
                    except TectonicsError:
                        if single is None:
                            raise
                    # A refused refined candidate gives way to the single
                    # solve's, judged as without refinement: these checks
                    # never refuse a field that the single solve passes.
                    concentration = tuple(Q(_project(w*scale/d)) for w, d in zip(single, self._diagonal))
                    refinements, single = 0, None
                exact_new[name], exact_faces[name], exact_residual[name] = new, moved, tuple(residual)
                binary_residual[name] = projection
                # Refinement can fill these tables with exact values as wide
                # as the geometry's rationals. They and their record are
                # reserved by the width they have.
                leases.enter_context(self._budget.reserve(16*sum(map(_width, (old, new, moved, residual, projection))),
                                                          category='spatial-transport-step'))
                field_errors[name] = dict(sum_absolute_local_and_binary_residual=_enc(error), allowed=_enc(bound),
                                          signed_total_projection=_enc(sum(residual, Q(0))))
                if refining:
                    # The error of the RECORDED stocks, from their local
                    # accounts and over the same cells: those whose old stock
                    # and inflow together reach the floor.
                    feed = list(map(abs, old))
                    for (_, j, _), amount in zip(self._transfers, moved):
                        feed[j] += abs(amount)
                    backward = max((abs(r)/(s+abs(d*c)) for r, s, d, c, f in zip(
                        residual, feed, self._diagonal, concentration, self._floor) if s >= f), default=Q(0))
                    field_errors[name].update(componentwise_refinements=refinements,
                        componentwise_backward_error=float(backward),
                        componentwise_backward_error_limit=float(COMPONENTWISE_BACKWARD_ERROR))
                projected['stock:'+name] = binary
                projected['density:'+name] = np.asarray(list(map(_project, concentration)))
            metadata = dict(schema='atlas.spatial-implicit-transport.v1', geometry_id=self.geometry_id,
                state_id=state_id, source_stage_id=source_stage_id, cell_ids=list(self._keys),
                method='first-order backward-Euler upwind on exact-GCL integrated directed face measures',
                exact_input_stocks={k: list(map(_enc, v)) for k, v in exact_old.items()},
                exact_stocks={k: list(map(_enc, v)) for k, v in exact_new.items()},
                exact_face_transfers={k: list(map(_enc, v)) for k, v in exact_faces.items()},
                exact_projection_accounts={k: list(map(_enc, v)) for k, v in exact_residual.items()},
                binary_stock_projection_accounts={k: list(map(_enc, v)) for k, v in binary_residual.items()},
                field_errors=field_errors, nonnegative_fields=sorted(nonnegative_fields),
                krylov_iterations=iterations[0],
                numerical_contract='projection accounts are signed numerical errors, never physical sources',
                accuracy='first order; geometry and time/space refinement require independent acceptance')
            if LIVE_SPATIAL.EARLY_RELEASE:
                # The metadata now holds every exact table encoded; the
                # rational tuples would otherwise live through the pack.
                del exact_old, exact_new, exact_faces, exact_residual, binary_residual
                del old, new, moved, residual, projection, concentration, densities
            snapshot = LIVE_TRANSPORT.make_snapshot(metadata, projected, self._budget, RegionalMechanicalSnapshot, check=lambda: _cancel(cancel))
            result = object.__new__(SpatialTransportResult)
            object.__setattr__(result, '_snapshot', snapshot); object.__setattr__(result, '_budget', self._budget)
            LIVE_TRANSPORT.retain(result, 8192+3*_width(metadata)+sum(a.nbytes for a in projected.values()), self._budget, _retain)
            self._verify(); _cancel(cancel)
            self._stats['advances'] += 1; self._stats['krylov_iterations'] += iterations[0]
            return result

    def statistics(self):
        return dict(self._stats)

    def close(self):
        if self._active:
            raise TectonicsError('cannot close active spatial transport')
        if not self._closed:
            self._closed = True
            self._matrix = None
            # Closed plans retain identity/statistics, not uncharged bulk data.
            for name in ('_encoded', '_keys', '_start', '_end', '_transfers', '_diagonal', '_floor'):
                setattr(self, name, None)
            if self._guard is not None:
                self._guard.__exit__(None, None, None); self._guard = None
            finalizer = getattr(self, '_guard_finalizer', None)
            if finalizer is not None:
                finalizer.detach()

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
