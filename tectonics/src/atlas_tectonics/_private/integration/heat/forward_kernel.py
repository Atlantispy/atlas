"""Private forward heat with complete-output custody at completed stage seams.

Same issued metric, physical functionals, precision ladder, LOW/HIGH equations
and conservative FINISH as the fixed predecessors. A complete output (or a
still-needed proof) is admitted before its producer workspace retires. This is
accounted object ownership, NOT an allocator/RSS bound or a whole-case fit proof.

F10 is F9 with its startup stage taken from geometry inventory r2: the same
preparation, with a derived inventory for its one decode of the issued metric
record (issuer resources r4). No equation, stage order or other inventory differs.

F11 is F10 with one change to the selective refinement. F10 gave every selected
face one absolute precision (640, then 1280, then 2560 bits) whatever the face
had already used. A face first certified at 1280 bits cannot be certified at 640
and fell through to the exact fallback solver; a face already at 640 was
recomputed to the same enclosure. F11 gives each selected face the rest of the
same ladder above the rung that certified it, lowest rung first. A row that is
already exact is not recomputed. When no selected face has a rung left, the
refinement refuses as it did when the ladder was exhausted. The ladder, the
support, the functionals, the merge and the assembly are unchanged, and so is
every certified number: a certified assembly fixes each entry at the unique
Decimal80 rounding of its exact value, whichever enclosures proved it.

F12 is F11 on LOW solver r4, functionals kernel r4, finish kernel r9 and stage
lifetime r2. Those hold a result that exists at what it occupies, where their
predecessors held the worst case reserved for it; see each. No stage reserves
less before it computes, and no equation, order or certified number differs.

F13 is F12 with three additions, none of which changes an equation, the
ladder, the support, the merge, the assembly or a certified number.

The call is metered where process meter r1 supports the runtime: the caller's
ledger then holds what the process has really committed, plus a margin, while
this producer's own workspaces are admitted on the meter's side ledger at their
unchanged calculated figures. The meter is read at this kernel's safe points
and told its stages. Where the meter is absent every line that runs is F12's.

The orchestration reservation carries a standing allowance for what a returned
stage leaves that is in no result graph: the interpreter's free lists, the
exact library's object cache and first-call imports.

When no selected face has a rung left, a selected face that needed the top
rung in the first pass is offered the lowest rung alone, once. It failed there
in the first pass, so the unchanged fallback solves its row exactly, which is
where F10's refinement sent such a face. A face that climbed to the top rung
cannot be sent there and is left; with no such face the refinement refuses as
before. The number of assessments is unchanged.
"""

from concurrent.futures import CancelledError
from fractions import Fraction as Q
import sys
import threading
from time import perf_counter
from types import MethodType
from typing import cast

from atlas_tectonics._private import private_heat_geometry_inventory_r3 as GEOMETRY
from atlas_tectonics._private import private_heat_low_solver_kernel_r5 as LOW
from atlas_tectonics._private import private_heat_functionals_kernel_r5 as FUNCTIONS
from atlas_tectonics._private.integration.heat import owned_interval_assessment as ASSEMBLY
from atlas_tectonics._private.integration.heat import refinement_kernel as REFINEMENT
from atlas_tectonics._private import private_heat_decimal_sparse_core_r2 as SPARSE
from atlas_tectonics._private.integration.heat import decimal_inventory as INVENTORY  # noqa: F401  read as F.INVENTORY by native_issuer
from atlas_tectonics._private import private_heat_finish_kernel_r11 as FINISH
from atlas_tectonics._private.integration.heat import stage_lifetime as LIFE
from atlas_tectonics._private.integration.heat import process_meter as METER
from atlas_tectonics._private.integration.heat import physical_order as ORDER
from atlas_tectonics._private.integration.heat import door as DOOR
from atlas_tectonics._private.integration.heat import small_cell_rule as SMALL

# What a returned stage leaves that is in no result graph: tuple and other free
# lists of the interpreter (at most about 5.5 MB), the exact library's object
# cache (about 0.5 MB) and modules a process imports on its first call (0.7 MB).
RESIDUE = 8388608
# The predictor's working set while it runs beside the reconstruction, reserved on the run's ledger first
# (design s4 ruling 2): twice b0's 35,975,168 B growth across LOW.solve, rounded up to 64 MiB.
PREDICTOR_PIN = 128 << 20


class OwnedAdvance:
    """One compact result owner; no second destructor shares its workspace."""
    def __init__(self, output, geometry):
        self._output, self._geometry = output, geometry

    @property
    def value(self):
        return cast('LIFE.OwnedValue', self._output).value

    @property
    def accounted_bytes(self):
        self.value
        return self._output.accounted_bytes

    @property
    def retention(self):
        self.value
        return self._output.retention

    def close(self):
        output, self._output = self._output, None
        self._geometry = None
        if output is not None:
            output.close()

    def __enter__(self):
        self.value
        return self

    def __exit__(self, kind, error, traceback):
        output, self._output = self._output, None
        self._geometry = None
        if output is not None:
            return output.__exit__(kind, error, traceback)
        return False

    def __del__(self):
        self.close()


def _certified_at(entry):
    """Precision of a completed face's interval certificate; None if its row is exact."""
    if entry.get('prescribed_power_exact') or entry.get('two_point_exact'):
        return None
    last = entry['functional_attempts'][-1]
    if last['route'] in ('interval', 'interval-reduced'):
        bits = last['precision_bits']
        return bits
    if last['route'] in ('exact-fallback', 'exact-reduced-zero'):
        return None
    raise AssertionError('Completed face without a certified route')


def _next_rungs(selected, census, used, first, ladder, check):
    """Group selected faces by the first rung above the one each has used.

    ``used`` holds the current precision of every face selected before (None
    for an exact row). A face selected for the first time is found in the
    first-pass census, which has the original face order of ``selected``.
    Returns ascending (rung, faces) pairs, faces in original order. Exact rows
    and faces already at the top rung are left out. ``first`` keeps the rung
    of each face's first-pass certificate.
    """
    pending = [fid for fid in selected if fid not in used]
    if pending:
        wanted = iter(pending)
        target = next(wanted)
        for entry in census:
            check()
            if entry['face_id'] == target:
                used[target] = first[target] = _certified_at(entry)
                target = next(wanted, None)
                if target is None:
                    break
    groups = {}
    for fid in selected:
        check()
        bits = used[fid]
        if bits is None:
            continue
        higher = [rung for rung in ladder if rung > bits]
        if higher:
            groups.setdefault(higher[0], []).append(fid)
    return [(rung, tuple(groups[rung])) for rung in sorted(groups)]


def _settle(used, first, census, faces, rung):
    """Record what each refined face is now certified at; never below its offer."""
    for entry in census:
        bits = _certified_at(entry)
        if rung is None:
            # The exact route. An exact row has no precision. A face certified
            # again at the lowest rung keeps the rung it had: its enclosure was
            # intersected, not replaced. Neither is offered this route twice.
            first[entry['face_id']] = None
            if bits is not None:
                continue
        elif bits is not None and bits < rung:
            raise AssertionError('Refined certificate is below its offered rung')
        used[entry['face_id']] = bits


def _exact_route(selected, used, first, ladder):
    """Selected faces with no rung left that needed the top rung in the first pass.

    Such a face failed every lower rung, so offered the lowest rung alone it
    falls to the unchanged exact fallback. Returns the one (None, faces) group,
    or nothing when there is no such face.
    """
    top = ladder[-1]
    stuck = tuple(fid for fid in selected if used[fid] == top and first[fid] == top)
    return [(None, stuck)] if stuck and len(ladder) > 1 else []


def _beside(solve, stop):
    """Start the predictor in one thread. The caller joins before using box[0]."""
    import contextvars
    import decimal
    import gmpy2
    contexts = decimal.getcontext().copy(), gmpy2.get_context().copy()
    events, box = [], []

    def stopped():
        if stop.is_set():
            raise CancelledError('Private composed heat cancelled')
        return False

    def body():
        # A thread starts with default numeric contexts, not this thread's.
        decimal.setcontext(contexts[0])
        gmpy2.set_context(contexts[1])
        try:
            box.append(solve(stopped, lambda *event: events.append(event)))
        except BaseException as error:
            box.append(error)

    thread = threading.Thread(target=contextvars.copy_context().run, args=(body,), name='heat-predictor')
    thread.start()
    return thread, box, events


def _run(geometry, old, capacity, dt, source, boundary, k, target, budget, check, stage, observe, issued=False,
         owned_guard=False, counts=None, sealed_output=None):
    """Own all producer frames until success; return before final union transfer.

The outer ``advance`` frame never borrows producer temporaries. On an escaping
failure this frame and its workspace stay charged together. On success this
frame disappears before the returned result graph replaces its entire stack.
"""
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    from threadpoolctl import threadpool_limits
    began = perf_counter()
    # Same protective orchestration inventory as F6: snapshots, boundary sets,
    # sources and the finite ladder's owner/metadata references. Numerical stage
    # operands and complete retained output graphs have their own reservations.
    # F11 also holds each selected face's current rung and one request's
    # groups. Per face at most: a dictionary entry (44 B, 66 B while its table
    # grows), and 8-byte references in the pending list, a group list, its
    # tuple and the census check (each list up to 17 B while it grows).
    amount = (262144+1024*(16*len(capacity)+8*len(geometry._face_ids)+16*len(boundary)+256)
              +8*sum(len(fid) for fid in geometry._face_ids)
              +8192+128*len(geometry._face_ids)+RESIDUE)
    work = R.OwnedWorkspace(budget, amount, category='heat-composed-orchestration', cancelled=check)
    work.__enter__()

    def retain(owner):
        # The old handle stays on the stack even when retired; close is
        # idempotent and its numerical graph has then been cleared.
        return work.stack.enter_context(owner)

    def complete(owner):
        # Fixed producer has returned before inspection. No omitted projection
        # here: the COMPLETE output graph receives independent custody.
        return retain(LIFE.compact(retain(owner), budget=budget, cancelled=check))

    def proof_only(owner):
        # Caller has first dropped/re-owned every row borrow. Both tuple output
        # shapes (FUNCTIONS and REFINEMENT) put the retained proof at index1.
        return retain(LIFE.compact(owner, budget=budget, path=(1,), cancelled=check,
                                   category='heat-completed-reconstruction-proof'))

    try:
        stage('prepare-issued-metric-low')
        startup = complete(GEOMETRY.prepare(geometry, k, boundary, budget=budget, cancel=check))
        normalized = startup.value['prepared']['boundary']
        temperatures = {fid for fid, (kind, _) in normalized.items() if kind == 'temperature'}
        powers = set(normalized)-temperatures
        order_owner = retain(ORDER._prepare_issued(geometry, startup, old, capacity, source,
            budget, check, len(powers)))
        ordered = order_owner.value
        prepared, payload = ordered['prepared'], ordered['payload']
        old, capacity, source = ordered['old'], ordered['capacity'], ordered['source']
        small = SMALL.shares(prepared, capacity, dt, cancel=check)
        refinements = []
        with threadpool_limits(1), FUNCTIONS.PARALLEL.hold():     # H4: one pool for both reconstructions
            # Errata r2: beside only where the pool can start workers (FP's three tests); otherwise base order.
            meter = METER.active(budget)
            beside = (meter is not None and getattr(meter, 'categories', None) is None
                      and not getattr(meter, 'failed', False))
            if not beside:
                low = complete(LOW.solve(prepared, old, capacity, dt, source,
                    target=target, budget=budget, cancel=check, observe=observe))
                stage('certify-full-polygon-functionals')
                row_owner = complete(FUNCTIONS.reconstruct(payload,
                    boundary_point_faces=temperatures, boundary_power_faces=powers,
                    two_point_rows=small['exact_rows'], conductivity=k, budget=budget, cancelled=check))
            else:
                stage('certify-full-polygon-functionals')
                stop = threading.Event()
                side = type(budget)(METER.SIDE_BYTES)     # as the meter builds its side ledger (MT:181)
                with budget.reserve(PREDICTOR_PIN, category='predictor-beside-pin'):
                    thread, box, events = _beside(lambda stopped, note: LOW.solve(prepared, old, capacity, dt,
                        source, target=target, budget=side, cancel=stopped,
                        observe=note), stop)

                    def guarded():
                        if box and isinstance(box[0], BaseException):
                            raise box[0]          # the predictor failed: end the reconstruction now
                        return check()

                    try:
                        row_owner = complete(FUNCTIONS.reconstruct(payload,
                            boundary_point_faces=temperatures, boundary_power_faces=powers,
                            two_point_rows=small['exact_rows'], conductivity=k, budget=budget,
                            cancelled=guarded))
                        while True:
                            thread.join(timeout=FUNCTIONS.PARALLEL.POLL)
                            if not thread.is_alive():
                                break
                            check()
                    except BaseException:
                        stop.set()
                        thread.join()
                        if box and not isinstance(box[0], BaseException):
                            retain(box[0])        # a finished predictor stays in this frame's custody
                        raise
                    if not isinstance(box[0], BaseException):
                        retain(box[0])            # custody first: the fresh guard below may raise
                    check()                       # the caller's guard, fresh, before the result is used
                    if isinstance(box[0], BaseException):
                        raise box[0]
                    if observe is not None:
                        for event in events:
                            observe(*event)
                    # Errata r3: the run's ledger takes the result before the side lease is released.
                    low = retain(LIFE.compact(box[0], budget=budget, source=side, cancelled=check))
            rows, proof = row_owner.value
            witness = proof
            assessment = None
            ladder = tuple(FUNCTIONS.PRECISIONS)
            used, first = {}, {}
            # One scalar/settings proof, owned by this invocation, no saved words.
            face_pass = [None, 0] if owned_guard else None     # [stamp, rows not checked again]
            assess = ASSEMBLY._assess_owned if issued else ASSEMBLY.assess
            for attempt in range(len(ladder)):
                if attempt:
                    # No request-value alias is kept. Only the selection is
                    # needed now; retire the obsolete contributor census before
                    # reconstruction. Its aggregate decision has already failed
                    # closed, and the next assessment is a new complete one.
                    original_maximum = None
                    if issued and cast('ASSEMBLY.OwnedAssessment', assessment).inventory.base.refinement_original_eligible:
                        original_maximum = cast('ASSEMBLY.OwnedAssessment', assessment).inventory.base.refinement_original_maximum
                    selection = retain(LIFE.compact(assessment, budget=budget,
                        path=('selected_face_ids',), cancelled=check,
                        category='heat-completed-refinement-selection'))
                    assessment = None
                    selected = selection.value
                    # Each face climbs from its own rung; see the module note.
                    groups = _next_rungs(selected, proof['census'], used, first, ladder, check)
                    if not groups:
                        # Nothing can climb: the exact route for a face that needed the top rung.
                        groups = _exact_route(selected, used, first, ladder)
                    if not groups:
                        raise ASSEMBLY.UnresolvedRounding('Aggregate rounding unresolved after unchanged finite precision ladder')
                    for rung, faces in groups:
                        offered = (ladder[0],) if rung is None else tuple(bits for bits in ladder if bits >= rung)
                        stage('refine-aggregate-faces-'+('exact' if rung is None else str(rung)))
                        refined = complete(FUNCTIONS.reconstruct(payload,
                            boundary_point_faces=temperatures, boundary_power_faces=powers,
                            conductivity=k, budget=budget, cancelled=check,
                            selected_faces=faces, certification_precisions=offered))
                        refined_rows, refined_proof = refined.value
                        merged = complete(REFINEMENT._intersect(rows, refined_rows,
                            faces, budget, check, original_maximum))
                        # A second group sees the merged generation.
                        original_maximum = None
                        # Complete merged custody includes every shared endpoint.
                        # Rebind/drop the two omitted row borrows BEFORE projecting
                        # their owners. All proof aliases remain separately owned.
                        rows, merge_proof = merged.value
                        refined_rows = None
                        proof_only(row_owner)
                        proof_only(refined)
                        row_owner, refined = merged, None
                        merged = None
                        _settle(used, first, refined_proof['census'], faces, rung)
                        refinements.append(dict(precision_bits=offered[0], offered_precision_bits=list(offered),
                                                proof=refined_proof, merge=merge_proof))
                        witness = dict(initial=proof, refinements=refinements)
                    groups = faces = offered = None
                    selected = None
                    selection.close()  # each merge proof independently owns its tuple
                    selection = None
                stage('assemble-certified-high')
                if owned_guard:
                    assessment = retain(ASSEMBLY._assess_owned(rows, len(capacity), normalized,
                        witness=witness, budget=budget, cancel=check,
                        _face_pass=face_pass, _refined=used))
                else:
                    assessment = retain(assess(rows, len(capacity), normalized,
                        witness=witness, budget=budget, cancel=check))
                if isinstance(assessment.value, ASSEMBLY.CertifiedAssembly):
                    # Construct/cache the rounded view while its original
                    # assessment reservation still funds that construction.
                    assessment = retain(LIFE.compact_assessment(assessment, normalized,
                        budget=budget, cancelled=check))
                    break
            else:
                raise ASSEMBLY.UnresolvedRounding('Aggregate rounding unresolved after unchanged finite precision ladder')
            if counts is not None:
                counts['face_rows_reused'] = face_pass[1]
            used = first = ladder = face_pass = None  # only borrowed face identifiers and rungs
            rows = None
            proof_only(row_owner)
            row_owner = None
            # Exact geometry payload is no longer consumed. Keep only the
            # prepared LOW boundary/face identity (including conservative spare
            # LOW rows) until FINISH; caller still owns the issued native metric.
            payload = None
            # Canonical scratch borrows original prepared/payload leaves.
            # Retain their complete original startup owner through FINISH.
            system = assessment.rounded_system(normalized, cancel=check)
            stage('small-cell-rule')
            system, small_counts = SMALL.apply(system, small, capacity, dt, normalized, cancel=check)
            small = None
            stage('solve-certified-high')
            old64, capacity64, source64 = (tuple(map(float, values)) for values in (old, capacity, source))
            solve = SPARSE._solve_issued if issued else SPARSE.solve_rounded
            high = complete(solve(system, old64, capacity64, float(dt),
                source64, normalized, target, budget=budget, cancel=check, observe=observe))
            # solve_rounded AND complete have returned. Any result witness
            # alias is included in complete HIGH custody before assembly retires.
            system = None
            assessment.close()
            assessment = None
            stage('finish-conservative-ledger')
            finish_inputs = retain(ORDER._finish_issued_inputs(order_owner, low, high,
                budget=budget, cancel=check))
            original_old, original_capacity, original_source = ordered['original_inputs']
            DOOR.offer(original_old, original_capacity, dt, original_source, normalized, prepared['face_ids'],
                finish_inputs.value['low'], finish_inputs.value['high'], target, budget=budget)
            finished = retain(FINISH.finish(original_old, original_capacity, dt, original_source, normalized,
                prepared['face_ids'], finish_inputs.value['low'], finish_inputs.value['high'], target,
                cancelled=check, budget=budget, observe=observe, _sealed_output=sealed_output))
            result, info = finished.value
        info.update(physical_scratch_order=ORDER.POLICY,
            public_cell_and_face_order_preserved=True,
            connected_seconds=perf_counter()-began, reconstruction=proof,
            selective_refinements=refinements, small_cell_rule=small_counts, numerical_pipeline='ISSUED_METRIC_DERIVED_LOW_CERTIFIED_HIGH_CONSERVATIVE_FINISH',
            native_forward_origin=False, production_acceptance=False, native_heat_dispatch_enabled=False,
            prospective_stage_ownership=True, caller_diagnostic_byte_allowances=False,
            allocator_or_rss_bound=False, whole_method_memory_inventory_certified=False,
            orchestration_accounted_bytes=amount, completed_stage_output_custody=True,
            high_backend='MPFR512_PARTIAL_PIVOT_SAME_DECIMAL80_SYSTEM',
            result_owner_contract='Borrow only while returned owner and caller input owners remain live')
        # Plain fixed owner is the lifetime helper's recognised type. This
        # value joins independently owned stage/proof graphs. No stage closes
        # here: the complete union is admitted AFTER this producer frame exits.
        return SPARSE.P.OwnedSolve((result, info), work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


class _IssuedInputs(tuple):
    """References borrowed from one verified native issue for the duration of advance."""
    __slots__ = ()


_GUARD_WRAPPER = ('atlas_tectonics._private.integration.heat.heat_interval_spec', '_Cancel')
_GUARD_CLASS = ('atlas_tectonics._private.integration.heat.continuation_guard', 'ContinuationGuard')


def _own_guard(hook):
    """True only for the drivers' guard: heat_interval_r9_spec._Cancel holding ContinuationGuard's own check.

Identity alone: the exact wrapper type, the exact guard type and the class's own check
function, each by ``is``; never a subclass, an attribute anyone can set, or being callable. That guard reads its
clock and two files and never answers true, so it can stop the call but cannot change a result that completes.
A class whose module is not loaded cannot have made the hook, so nothing is imported here.
"""
    spec, owner = sys.modules.get(_GUARD_WRAPPER[0]), sys.modules.get(_GUARD_CLASS[0])
    if spec is None or owner is None:
        return False
    wrapper, guard = vars(spec).get(_GUARD_WRAPPER[1]), vars(owner).get(_GUARD_CLASS[1])
    if type(wrapper) is not type or type(guard) is not type or type(hook) is not wrapper:
        return False
    check = hook._check
    return (type(check) is MethodType and type(check.__self__) is guard
            and check.__func__ is vars(guard).get('check'))


def advance(geometry, old, capacity, dt, source, boundary, *, conductivity,
            absolute_residual_target, budget, cancelled=None, observe=None, _issued_inputs=None,
            _sealed_output=None):
    """Return a compact owner of (sealed result, diagnostics), with fixed physics.

Caller inputs/native metric stay caller-owned and immutable. Precision-only
refinement retains the same support, Decimal80 operator and absolute target.
Drop borrowed outputs before closing. Failure tracebacks retain all still-live
work; no old-generation credit precedes independent output admission.
"""
    issued = False
    if type(_issued_inputs) is _IssuedInputs and observe is None:
        actual = (geometry, old, capacity, dt, source, boundary, conductivity, absolute_residual_target, budget)
        issued = len(_issued_inputs) == len(actual) and all(x is y for x, y in zip(_issued_inputs, actual, strict=True))
        del actual
    del _issued_inputs
    # Internal meter/predictor guards remain real callables; eligibility refers
    # to the original external hook, independently of those wrappers. The
    # package's own guard is the one hook admitted, by identity (_own_guard).
    owned_guard = issued and observe is None and (cancelled is None or _own_guard(cancelled))
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Private composed heat cancelled')
        return False

    def stage(name):
        check()
        if observe is not None:
            observe(name)

    check()
    value = float(conductivity)
    # F13: None where the meter does not support the runtime; nothing below then differs from F12.
    meter = METER.open(budget)
    if meter is not None:
        unmetered = check

        def check():
            if perf_counter() >= meter.next:
                meter.read()
            return unmetered()

        def stage(name):
            check()
            meter.stage(name)
            if observe is not None:
                observe(name)
    counts = dict(face_rows_reused=0) if owned_guard else None
    try:
        raw = _run(geometry, old, capacity, dt, source, boundary, Q(value),
                   absolute_residual_target, budget, check, stage, observe, issued, owned_guard, counts,
                   _sealed_output)
        try:
            # _run has gone: no omitted LOW/HIGH/prepared/proof temporaries survive
            # in a producer frame when its entire old stack closes atomically.
            output = LIFE.compact(raw, budget=budget, cancelled=check,
                                  category='heat-completed-forward-result')
        except BaseException:
            raw.__exit__(*sys.exc_info())
            raise
        try:
            # Every producer workspace has gone with the old stack; the result is
            # admitted on the caller's ledger. The meter returns its share.
            METER.finish(meter)
        except BaseException:
            output.close()
            raise
        if counts is not None and cancelled is not None:
            # The admitted guard's own record, its trace of effort; read only, never a stop.
            cancelled._check.__self__.record.setdefault('f13_paths', []).append(counts)
        return OwnedAdvance(output, geometry)
    except BaseException:
        if _sealed_output is not None:
            _sealed_output.clear()
        if meter is not None:
            meter.fail()
        raise
