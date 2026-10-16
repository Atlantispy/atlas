"""Owned optional results for exact moving-interface and fixed-wall execution.

The parent's own worker, live byte/work envelope, unchanged serial prefix and
exact source/runtime/request binding establish admissibility. A hash alone is
not scientific authority. Validation takes place inside prepaid capacity, then
the same immutable buffer and its lease transfer to the original measure type.
No arbitrary-JSON restore is exposed.

The dispatch owner must stop every worker before releasing its envelope; only
an exited child may mark a FitWitness complete. Serial mandatory pressure
revokes optional work before reattempting its original admission.
SPDX-License-Identifier: AGPL-3.0-only
"""
import hashlib
import json
import threading
import weakref

from .integration_routing_views import _decoded_json_capacity as decoded_capacity
from .integration_parallel_owner import nodes_for
from .integration_parallel_binding import (REQUEST_FIELDS, WALL_KIND, WALL_REQUEST_FIELDS,
    request_fields, VOLUME_SCHEMA, VOLUME_REQUEST_FIELDS)

# Algorithm-selection limit, not a scientific limit: beyond this depth the
# unchanged serial path is used. One cumulative entry per ancestor keeps the
# private return metadata bounded (no history per shrink or close retry).
# On the pinned 64-bit runtime, <=896 bytes per ancestor plus <=768 fixed
# bytes fit inside an adopted slot's existing 8192 retained allowance. The
# dispatcher's PARENT_STORAGE funds temporary slots and FitWitness metadata;
# owner-registration storage has its own retained owner lease. A standalone
# private-helper caller must supply that surrounding bookkeeping allowance.
RETURN_ANCESTORS = 8

def raw_capacity(length):
    """Immutable payload plus prepaid constant-state scanner workspace."""
    if type(length) is not int or length < 0:
        raise ValueError('nonnegative payload length required')
    return 8192+length+65536+4*length


def validation_capacity(payload):
    """R + decoded graph + max(sequential decoding, encoding workspace).

    D dominates the existing recursive _width contract. This covers the saved
    JSON result, not wire copies, caller-owned request/binding snapshots or their
    comparison temporaries, live-fit metadata, or module/transport setup.
    """
    length, decoded = len(payload), decoded_capacity(payload)
    return 8192+length+4096+decoded+max(65536+4*length, 65536+4*decoded)


def _receive_capacity(payload, owner):
    # Expected parse/scan errors and their exception objects die inside this
    # frame before its caller may release a slot. An escaping traceback retains
    # owner, which was allocated BEFORE the risky operation.
    try:
        return validation_capacity(payload)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None


def canonical(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class SlotLease:
    """Single-owner optional capacity, charged to every ancestor before receive.

    A successful transfer keeps the SAME charge and bytes, then shrinks after
    decode/validation temporaries disappear. It does not admit a second copy.
    Category telemetry intentionally differs from the unchanged serial issuer.
    """
    def __init__(self, resources, budget, capacity, charged):
        self.resources, self.budget = resources, budget
        self.count, self.charged = capacity, charged
        self._ticket = resources._ReturnTicket(charged)
        self._returned, self._pending = 0, None

    @classmethod
    def attempt(cls, resources, budget, capacity):
        if len(nodes_for((budget,))) > RETURN_ANCESTORS:
            return None
        charged = resources._admit_budgets(
            capacity, budget, category='parallel-result-slot', _optional=True)
        if charged is None:
            return None
        try:
            return cls(resources, budget, capacity, charged)
        except BaseException:
            # Ownership starts only after construction succeeds.
            resources._release(charged, capacity)
            raise

    def shrink(self, capacity):
        if type(capacity) is not int or not 0 <= capacity <= self.count:
            raise ValueError('a transfer may only shrink its existing charge')
        self._finish_return()
        if capacity > self.count:
            raise ValueError('an interrupted shrink already returned this capacity')
        if capacity != self.count:
            self._pending = (capacity, self._returned+self.count-capacity)
            self._finish_return()

    def _finish_return(self):
        if self._pending is not None:
            capacity, returned = self._pending
            self.resources._release(self.charged, returned, _ticket=self._ticket)
            self.count, self._returned = capacity, returned
            self._pending = None

    def grow_optional(self, capacity):
        self._finish_return()
        if type(capacity) is not int or capacity < self.count:
            raise ValueError('optional growth cannot shrink a slot')
        if capacity == self.count:
            return True
        delta = capacity-self.count
        added = self.resources._admit_budgets(
            delta, self.budget, category='parallel-result-slot', _optional=True)
        if added is None:
            return False
        if added != self.charged:
            self.resources._release(added, delta)
            raise RuntimeError('slot ancestry/category changed during receive')
        self.count = capacity
        return True

    def close(self):
        self.shrink(0)


class _BufferOwner:
    """Plain diagnostic bytes; intentionally NOT DifferentialMeasure."""
    __slots__ = ('encoded', '_finalizer', '__weakref__')

    def __init__(self, encoded, lease):
        self.encoded = encoded
        self._finalizer = weakref.finalize(self, lease.close)


class Hint:
    """Fixed funded payload slot with an explicit serial-position claim.

    `fit` identifies the still-live byte/unit envelope witness. `room` is the
    existing diagnostic RevocableOwner. Its condition serialises claim versus
    revoke; validation performs NO mandatory budget calls while holding it.
    """
    def __init__(self, slot, *, max_payload, request, binding, fit):
        self.slot, self.max_payload = slot, max_payload
        self.request, self.binding, self.fit = canonical(request), canonical(binding), fit
        self.payload = self.digest = None
        self.consumed = False

    def receive(self, payload, digest):
        # In production the wire length is checked before allocating/receiving.
        if self.consumed or self.payload is not None or self.slot is None:
            raise RuntimeError('one result per live slot')
        if type(payload) is not bytes or len(payload) > self.max_payload:
            return False
        if self.slot.count < raw_capacity(len(payload)):
            return False
        owner = _BufferOwner(payload, self.slot)
        try:
            required = _receive_capacity(payload, owner)
            if required is None or not self.slot.grow_optional(max(required, self.slot.count)):
                owner._finalizer.detach()  # raw slot still belongs to the hint
                return False
            self.payload, self.digest = payload, digest
            owner._finalizer.detach()  # hint resumes ownership, without release
            return True
        except BaseException:
            # The escaping traceback owns owner and the entire lease. Revoke
            # must not release it while scanner/decoder descendants survive.
            self.slot = self.payload = self.digest = None
            self.consumed = True
            raise

    def close(self):
        self.payload = self.digest = None
        if self.slot is not None:
            self.slot.close()
            self.slot = None
        self.consumed = True


RETAINED_FIXED = 8192  # the unchanged _issue constant (G 96)
ENVELOPE = 'parallel-body-envelope'
ZERO_AREA, MOMENTS = 'zero_area_certificate', 'moving_interface_moments'
RESULT_FIELDS = frozenset((
    'inward_volume_bounds_m3', 'outward_volume_bounds_m3', 'leaves', 'met', 'rule', 'work_units'))
# Every rule the serial body can issue, and its only optional certificate key
# (G 3027-3084). Zero rules always carry leaves == 1 and met is True.
CERTIFICATE = {
    'exact-zero-area-from-actual-voxel-radial-cap': ZERO_AREA,
    'exact-zero-area-from-actual-halfspace-pair': ZERO_AREA,
    'exact-zero-area-from-actual-fixed-voxel-wall': ZERO_AREA,
    'exact-zero-area-from-actual-moving-halfspace': ZERO_AREA,
    'exact-zero-area-from-complementary-moving-cuts': ZERO_AREA,  # geometry transform complementary_cut
    'exact-zero-relative-flux-on-material-transported-plane': None,
    'exact-zero-relative-flux-on-rigid-material-fan-edge': None,
    'material-velocity-minus-actual-two-ray-face-velocity': MOMENTS,
}
DIGEST_KEYS = frozenset((ZERO_AREA, MOMENTS))
VOLUME_RESULT_FIELDS = frozenset((
    'lower_m3', 'upper_m3', 'leaves', 'met', 'positive_witness_m3', 'work_units'))
VOLUME_WITNESS_FIELDS = frozenset(('positive_witness_point_m', 'positive_witness_point_rule'))
VOLUME_POSES = 'whole_voxel_pose_levels'
VOLUME_WITNESS_RULE = 'exact vertex barycentre of a positive-volume certified inner convex polyhedron'
WALL_TEMPORAL = 'temporal_integration'
WALL_DIGEST_KEYS = frozenset((WALL_TEMPORAL,))
WALL_RESULT_FIELDS = frozenset((
    'physical_cell_id', 'face', 'moment_polynomials', 'moment_bounds', 'max_widths',
    'inward_volume_bounds_m3', 'outward_volume_bounds_m3', 'leaves', 'met', 'work_units',
    'moment_time_measure'))
WALL_ZERO = 'exact_zero_normal_flux'
WALL_ZERO_RULE = 'all three exact world-space rigid normal coefficients vanish'
WALL_ZERO_MEASURE = 'exact_zero_wall_measure'
WALL_OUTER_FIELDS = frozenset(('method', 'pose_level', 'angular_literals_examined',
    'radial_outer_halfplanes', 'scope'))
WALL_CONE_FIELDS = frozenset(('method', 'pose_level', 'triangle_literals',
    'determinant_bounds', 'face_normal', 'generator_projection_bounds', 'scope'))
WALL_FACE_FIELDS = frozenset(('origin_m', 'tangent_u', 'tangent_v', 'outward_normal',
    'coordinate_bounds_m', 'area_jacobian'))
_OVERRIDES = frozenset(('reserve', 'reserve_predicate_work', 'try_reserve', '_settle'))


def _complete_request(request):
    return request_fields(request)


class FitWitness:
    """Optional envelope of E bytes (and U predicate units) on every ancestor.

    The worker must run the unchanged call under exactly
    WorkBudget(max_bytes, max_predicate_work_units=max_units). The witness
    counts only after complete() and only while its charges are still live.
    release() belongs to a stop callback AFTER the child is confirmed stopped,
    or to the serial position after the transfer. A failed stop must not call
    it. A persistent worker needs a new envelope for its next job. This method
    is not a GC finalizer: callers must hold no resource-ledger lock. Pending
    predicate returns are settled before the callback may drop its prepaid
    parent storage, which funds these byte/unit return receipts.
    """
    def __init__(self, resources, budget, max_bytes, max_units, byte_charge, unit_charge):
        self.resources, self.budget = resources, budget
        self.max_bytes, self.max_units = max_bytes, max_units
        self._charges = byte_charge, unit_charge
        self._tickets = (resources._ReturnTicket(byte_charge),
                         None if unit_charge is None else resources._ReturnTicket(unit_charge))
        self.guard = threading.Lock()
        self._live, self.completed = True, False

    @classmethod
    def attempt(cls, resources, budget, max_bytes, max_units=None):
        """None means no worker for this request; never a refusal or an error."""
        # A1: an overridden or subclassed ledger changes how _Arena admits
        # (cumulative lease versus stacked reservations); no witness for it.
        if type(budget) is not resources.WorkBudget or _OVERRIDES.intersection(vars(budget)):
            return None
        work = budget._predicate_work
        ledgers = (budget,) if work is None else (budget, work)
        if any(len(nodes_for((ledger,))) > RETURN_ANCESTORS for ledger in ledgers):
            return None
        if any(type(node) is not resources.WorkBudget or _OVERRIDES.intersection(vars(node))
               for node in nodes_for(ledgers)):
            return None
        if (max_units is None) != (work is None):
            raise ValueError('the envelope must use the ledger mode of its budget')
        charged = resources._admit_budgets(max_bytes, budget, category=ENVELOPE, _optional=True)
        if charged is None:
            return None
        units = None
        if work is not None:
            try:
                units = resources._admit_budgets(max_units, work, category=ENVELOPE, _optional=True)
            except BaseException:
                resources._release(charged, max_bytes)
                raise
            if units is None:
                resources._release(charged, max_bytes)
                return None
        try:
            return cls(resources, budget, max_bytes, max_units, charged, units)
        except BaseException:
            # No witness owns either admission until construction succeeds.
            resources._release(charged, max_bytes)
            if units is not None:
                resources._release(units, max_units)
            raise

    def complete(self):
        """The child body returned successfully under this envelope."""
        with self.guard:
            self.completed = self._live
            return self.completed

    @property
    def live(self):
        return self._live and self.completed

    def covers(self, budget):
        # Call with guard held: release() flips _live under the same guard
        # BEFORE it returns the charges, so True means E is still charged.
        return self._live and self.completed and budget is self.budget

    def admits_work(self, units):
        """A result reporting more work than the envelope cannot be its child's."""
        return units <= self.max_units if self.max_units is not None else 32*units <= self.max_bytes

    def release(self):
        with self.guard:
            # Disable adoption immediately, but retain both cumulative return
            # receipts until cleanup has been completed or explicitly retried.
            self._live = False
            byte_charge, unit_charge = self._charges
            if unit_charge is not None:
                self.resources._release(unit_charge, self.max_units, _ticket=self._tickets[1])
                with self.resources._BudgetLocks([node for node, _ in unit_charge]):
                    for node, _ in unit_charge:
                        node._settle()
            self.resources._release(byte_charge, self.max_bytes, _ticket=self._tickets[0])


class FundedMeasure:
    """Private validated funded object taken by the issuer instead of a record.

    Minted only by MeasureHint.claim_measure. It owns exactly the retained
    charge R of its bytes until adopt() moves that same lease to the measure;
    an unadopted token returns the charge when it dies.
    """
    __slots__ = ('cls', 'budget', 'encoded', '_lease', '_finalizer', '__weakref__')

    def __init__(self, *args, **kwargs):
        raise TypeError('FundedMeasure is minted by a validated live-worker claim')

    @classmethod
    def _mint(cls, measure_class, budget, encoded, lease):
        token = object.__new__(cls)
        token.cls, token.budget, token.encoded, token._lease = measure_class, budget, encoded, None
        token._finalizer = weakref.finalize(token, lease.close)
        return token


def _wall_scalar(value):
    # The issuer stores exact rationals as two canonical hexadecimal strings.
    # This checks the wire shape without allocating large exact arithmetic or
    # trying to certify the child's already source-bound physical calculation.
    if type(value) is not list or len(value) != 2:
        return False
    for index, text in enumerate(value):
        if type(text) is not str:
            return False
        negative = text.startswith('-')
        if negative:
            if index == 1:
                return False
            text = text[1:]
        if not text.startswith('0x'):
            return False
        digits = text[2:]
        if (not digits or any(char not in '0123456789abcdef' for char in digits)
                or len(digits) > 1 and digits[0] == '0'
                or digits == '0' and (negative or index == 1)):
            return False
    return True


def _validated_wall(record, request, digests, fit):
    fields = WALL_REQUEST_FIELDS | WALL_RESULT_FIELDS
    extra = record.keys()-fields
    if not fields <= record.keys() or extra not in (set(), {WALL_ZERO}, {WALL_ZERO_MEASURE}, {WALL_TEMPORAL}):
        return False
    request_fields({key: record[key] for key in WALL_REQUEST_FIELDS})
    if canonical({key: record[key] for key in WALL_REQUEST_FIELDS}) != request:
        return False
    work, leaves, met = record['work_units'], record['leaves'], record['met']
    if (type(work) is not int or work < 0 or not fit.admits_work(work)
            or type(record['max_leaves']) is not int or record['max_leaves'] < 1
            or type(leaves) is not int or not 1 <= leaves <= record['max_leaves'] or type(met) is not bool):
        return False
    if (record['moment_polynomials'] != [] or record['moment_bounds'] != []
            or record['moment_time_measure'] != 'integrated over the complete physical interval'
            or not _wall_scalar(record['max_width_m3'])
            or canonical(record['max_widths']) != canonical([record['max_width_m3']]*2)):
        return False
    physical = record['physical_cell_id']
    if type(physical) is not str or len(physical) != 64 or any(c not in '0123456789abcdef' for c in physical):
        return False
    for key in ('inward_volume_bounds_m3', 'outward_volume_bounds_m3'):
        pair = record[key]
        if type(pair) is not list or len(pair) != 2 or not all(_wall_scalar(value) for value in pair):
            return False
    face = record['face']
    if type(face) is not dict or face.keys() != WALL_FACE_FIELDS or face['area_jacobian'] != ['0x1', '0x1']:
        return False
    for key in ('origin_m', 'tangent_u', 'tangent_v', 'outward_normal'):
        vector = face[key]
        if type(vector) is not list or len(vector) != 3 or not all(_wall_scalar(value) for value in vector):
            return False
    bounds = face['coordinate_bounds_m']
    if (type(bounds) is not list or len(bounds) != 2
            or any(type(pair) is not list or len(pair) != 2
                   or not all(_wall_scalar(value) for value in pair) for pair in bounds)):
        return False
    if WALL_ZERO in extra or WALL_ZERO_MEASURE in extra:
        zero = [['0x0', '0x1'], ['0x0', '0x1']]
        if (leaves != 1 or met is not True
                or record['inward_volume_bounds_m3'] != zero or record['outward_volume_bounds_m3'] != zero):
            return False
    if WALL_ZERO in extra and record[WALL_ZERO] != WALL_ZERO_RULE:
        return False
    if WALL_ZERO_MEASURE in extra and not _wall_zero_certificate(record[WALL_ZERO_MEASURE], face):
        return False
    if WALL_TEMPORAL in extra:
        certificate = record[WALL_TEMPORAL]
        if (type(certificate) is not dict
                or certificate.get('source_sha256') != digests[WALL_TEMPORAL]
                or certificate.get('method') != 'fixed-topology-interval-Taylor'):
            return False
    return True


def _wall_zero_certificate(certificate, face):
    # These proofs are emitted by the source-bound geometry call, not by an
    # independently restored certificate. Keep their exact supported shapes;
    # full worker/source binding remains the authority for the physical proof.
    if (type(certificate) is not dict or type(certificate.get('pose_level')) is not int
            or certificate['pose_level'] != 0):
        return False
    method = certificate.get('method')
    if method == 'whole-interval-outer-face-zero-area':
        return (certificate.keys() == WALL_OUTER_FIELDS
            and certificate['scope'] == 'zero fixed-face area throughout the complete time interval'
            and all(type(certificate[key]) is int and certificate[key] >= 0
                    for key in ('angular_literals_examined', 'radial_outer_halfplanes')))
    if method != 'whole-interval-ray-cone-zero-area' or certificate.keys() != WALL_CONE_FIELDS:
        return False
    if (certificate['scope'] != 'fixed-face intersection lies in at most one ray throughout the complete time interval'
            or canonical(certificate['face_normal']) != canonical(face['outward_normal'])):
        return False
    literals = certificate['triangle_literals']
    if (type(literals) is not list or len(literals) != 3
            or any(type(row) is not list or len(row) != 2 or type(row[0]) is not str or not row[0]
                   or type(row[1]) is not int or row[1] not in (-1, 1) for row in literals)):
        return False
    projections = certificate['generator_projection_bounds']
    if type(projections) is not list or len(projections) != 3:
        return False
    return all(type(pair) is list and len(pair) == 2 and all(_wall_scalar(value) for value in pair)
               for pair in (certificate['determinant_bounds'], *projections))


def _validated_volume(record, request, fit):
    # Structural admission only: no rational reconstruction or numerical proof
    # under the claim lock. The complete source-bound child supplies the proof.
    fields = VOLUME_REQUEST_FIELDS | VOLUME_RESULT_FIELDS
    extra = record.keys()-fields
    if (not fields <= record.keys()
            or extra not in (set(), VOLUME_WITNESS_FIELDS, {VOLUME_POSES},
                            VOLUME_WITNESS_FIELDS | {VOLUME_POSES})):
        return False
    carried = {key: record[key] for key in VOLUME_REQUEST_FIELDS}
    request_fields(carried)
    if canonical(carried) != request:
        return False
    work, leaves = record['work_units'], record['leaves']
    if (type(work) is not int or work < 0 or not fit.admits_work(work)
            or type(leaves) is not int or not 1 <= leaves <= record['max_leaves']
            or type(record['met']) is not bool):
        return False
    for key in ('lower_m3', 'upper_m3', 'positive_witness_m3'):
        value = record[key]
        if not _wall_scalar(value) or value[0].startswith('-'):
            return False
    if VOLUME_WITNESS_FIELDS <= extra:
        point = record['positive_witness_point_m']
        if (record['positive_witness_point_rule'] != VOLUME_WITNESS_RULE
                or type(point) is not list or len(point) != 3
                or not all(_wall_scalar(value) for value in point)):
            return False
    if VOLUME_POSES in extra:
        poses = record[VOLUME_POSES]
        if (type(poses) is not list or not all(type(level) is int for level in poses)
                or poses not in ([0, 16], [0, 16, 32]) or len(poses) > leaves):
            return False
    return True


def _validated(encoded, digest, request, digests, fit, owner):
    """Structural admission of one worker record; no decoded object escapes.

    `owner` is retained by an escaping traceback and owns the whole slot, as
    in the diagnostic _matches. No ledger call is made, so the ValueError
    filter below cannot swallow a resource refusal. The numerical bounds are
    NOT re-certified here: they are the live child's output for this request.
    """
    try:
        if type(digest) is not str or hashlib.sha256(encoded).hexdigest() != digest:
            return False
        record = json.loads(encoded)
        if type(record) is not dict or canonical(record) != encoded:
            return False
        if record.get('schema') == VOLUME_SCHEMA:
            return _validated_volume(record, request, fit)
        if record.get('kind') == WALL_KIND:
            return _validated_wall(record, request, digests, fit)
        rule = record.get('rule')
        if type(rule) is not str or rule not in CERTIFICATE:
            return False
        extra = CERTIFICATE[rule]
        if record.keys() != REQUEST_FIELDS | RESULT_FIELDS | ({extra} if extra else frozenset()):
            return False
        # Byte comparison keeps 1, 1.0 and true distinct.
        if canonical({key: record[key] for key in REQUEST_FIELDS}) != request:
            return False
        work, leaves, met = record['work_units'], record['leaves'], record['met']
        if (type(work) is not int or work < 0 or not fit.admits_work(work)
                or type(leaves) is not int or leaves < 1 or type(met) is not bool):
            return False
        if extra != MOMENTS and (leaves != 1 or met is not True):
            return False
        for key in ('inward_volume_bounds_m3', 'outward_volume_bounds_m3'):
            if type(record[key]) is not list or len(record[key]) != 2:
                return False
        if extra is not None:
            detail = record[extra]
            # The PARENT's loaded module digest, not one echoed by the worker.
            expected = digests[extra]
            if rule == 'exact-zero-area-from-complementary-moving-cuts':
                # Issued by the geometry module's certificate helper: the parent's loaded constant.
                from . import integration_differential_geometry as _geometry
                expected = getattr(_geometry, '_CP_SOURCE_SHA256', None)
            if type(expected) is not str or type(detail) is not dict or detail.get('source_sha256') != expected:
                return False
        return True
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False


class MeasureHint(Hint):
    """One funded worker result for one exact request and one envelope."""
    def __init__(self, slot, *, max_payload, request, binding, fit):
        if type(fit) is not FitWitness or slot is None or fit.budget is not slot.budget:
            raise TypeError('a measure hint needs its own envelope witness on the slot budget')
        _complete_request(request)
        super().__init__(slot, max_payload=max_payload, request=request, binding=binding, fit=fit)

    def claim(self, *args, **kwargs):
        raise TypeError('a measure hint is claimed only through claim_measure')

    def receive_under(self, room, payload, digest):
        """Serialise receipt with revocation; the optional growth never blocks.

        Lock order is room.condition, then ledger locks. The mandatory path
        drops every ledger lock before it revokes, so the order is acyclic.
        """
        with room.condition:
            if room.state != 'ACTIVE' or self.consumed or self.slot is None:
                return False
            return self.receive(payload, digest)

    def claim_measure(self, room, *, cls, budget, request, binding, fit, digests):
        fields = _complete_request(request)
        digest_keys = (frozenset() if fields == VOLUME_REQUEST_FIELDS else
                       WALL_DIGEST_KEYS if fields == WALL_REQUEST_FIELDS else DIGEST_KEYS)
        if (type(digests) is not dict or digests.keys() != digest_keys
                or any(type(value) is not str or len(value) != 64 for value in digests.values())):
            raise ValueError('exact parent certificate source digests for this request kind are required')
        # Caller-owned snapshots; built before any lock is taken.
        wanted, bound = canonical(request), canonical(binding)
        with room.condition:
            if (room.state != 'ACTIVE' or self.consumed or self.slot is None or self.payload is None
                    or self.slot.budget is not budget or fit is not self.fit
                    or wanted != self.request or bound != self.binding
                    or self.slot.count < RETAINED_FIXED+len(self.payload)):
                return None
            with fit.guard:
                if not fit.covers(budget):
                    return None
                token = FundedMeasure._mint(cls, budget, self.payload, self.slot)
                try:
                    if not _validated(self.payload, self.digest, self.request, digests, fit, token):
                        token._finalizer.detach()  # the hint keeps the whole slot
                        return None
                except BaseException:
                    # The escaping traceback owns token and so the entire slot.
                    self.slot = self.payload = self.digest = None
                    self.consumed = True
                    raise
                # Decoded graph and comparison copy are gone. E is still
                # charged (guard held). Keep the bytes funded: shrink, never
                # release and re-reserve. _release cannot block or revoke.
                self.payload = self.digest = None
                lease, self.slot = self.slot, None
                self.consumed = True
                lease.shrink(RETAINED_FIXED+len(token.encoded))
                token._lease = lease
                return token


def adopt(cls, funded, budget):
    """Private sibling of _issue (G 91-108) for an already funded buffer.

    Same object layout as _issue: one immutable byte buffer, the caller's
    budget and a finalizer returning the retained charge. It makes no
    reservation, so it cannot refuse; the charge it takes over is exactly R.
    """
    if type(funded) is not FundedMeasure or funded.cls is not cls or funded.budget is not budget:
        raise TypeError('validated funded token of exactly this class and budget required')
    lease, encoded = funded._lease, funded.encoded
    if lease is None or type(encoded) is not bytes or lease.count != RETAINED_FIXED+len(encoded):
        raise RuntimeError('funded token is unvalidated or already adopted')
    result = object.__new__(cls)
    object.__setattr__(result, '_json', encoded)
    object.__setattr__(result, '_resource', budget)
    weakref.finalize(result, lease.close)
    # Both finalizers briefly name the same lease; close() is idempotent.
    funded._finalizer.detach()
    funded._lease = funded.encoded = None
    return result


