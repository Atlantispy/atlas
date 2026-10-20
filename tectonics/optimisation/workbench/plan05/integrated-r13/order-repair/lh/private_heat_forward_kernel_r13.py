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
from hashlib import sha256
import math
from pathlib import Path
import sys
from time import perf_counter
from types import ModuleType

import private_heat_geometry_inventory_r3 as GEOMETRY
import private_heat_low_solver_kernel_r5 as LOW
import private_heat_functionals_kernel_r5 as FUNCTIONS
import private_heat_interval_assembly_kernel_r5 as ASSEMBLY
import private_heat_refinement_kernel_r1 as REFINEMENT
import private_heat_decimal_sparse_core_r2 as SPARSE
import private_heat_decimal_inventory_r1 as INVENTORY
import private_heat_finish_kernel_r10 as FINISH
import private_heat_stage_lifetime_r3 as LIFE
import private_heat_process_meter_r1 as METER
import private_heat_physical_order_r1 as ORDER

HERE = Path(__file__).resolve().parent
# What a returned stage leaves that is in no result graph: tuple and other free
# lists of the interpreter (at most about 5.5 MB), the exact library's object
# cache (about 0.5 MB) and modules a process imports on its first call (0.7 MB).
RESIDUE = 8388608


def _source_paths():
    pending = [GEOMETRY, LOW, FUNCTIONS, ASSEMBLY, REFINEMENT, SPARSE, INVENTORY, FINISH, LIFE, ORDER]
    roots = {HERE, Path(FUNCTIONS.__file__).resolve().parent, Path(ORDER.__file__).resolve().parent}
    modules, paths = set(), {Path(__file__).resolve()}
    while pending:
        module = pending.pop()
        if module.__name__ in modules:
            continue
        modules.add(module.__name__)
        paths.add(Path(module.__file__).resolve())
        for value in tuple(vars(module).values()):
            if (type(value) is ModuleType and value.__name__.startswith('private_heat_')
                    and Path(value.__file__).resolve().parent in roots):
                pending.append(value)
        for name in ('_SOURCE_PATHS', 'SOURCE_PATHS', '_SOURCES'):
            for value in getattr(module, name, ()):
                if isinstance(value, (str, Path)):
                    path = Path(value)
                    if path.is_absolute() and path.is_file():
                        paths.add(path.resolve())
        value = getattr(module, 'POLICY_PATH', None)
        if value is not None:
            paths.add(Path(value).resolve())
    return tuple(sorted(paths))


_SOURCES = {str(p): sha256(p.read_bytes()).hexdigest() for p in _source_paths()}


def _check_sources(cancel):
    for path, expected in _SOURCES.items():
        cancel()
        if sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Private composed dependency changed after import: '+path)


class OwnedAdvance:
    """One compact result owner; no second destructor shares its workspace."""
    def __init__(self, output, geometry):
        self._output, self._geometry = output, geometry

    @property
    def value(self):
        if self._output is None:
            raise RuntimeError('Private forward result owner is closed')
        return self._output.value

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
    if entry.get('prescribed_power_exact'):
        return None
    last = entry['functional_attempts'][-1]
    if last['route'] in ('interval', 'interval-reduced'):
        bits = last['precision_bits']
        if type(bits) is not int or bits <= 0:
            raise AssertionError('Interval certificate without its precision')
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
        if target is not None:
            raise AssertionError('Selected face absent from the first-pass census or out of order')
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
    if tuple(entry['face_id'] for entry in census) != faces:
        raise AssertionError('Refinement census differs from its request')
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


def _run(geometry, old, capacity, dt, source, boundary, k, target, budget, check, stage, observe):
    """Own all producer frames until success; return before final union transfer.

The outer ``advance`` frame never borrows producer temporaries. On an escaping
failure this frame and its workspace stay charged together. On success this
frame disappears before the returned result graph replaces its entire stack.
"""
    import private_heat_gmp_resources_r1 as R
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
              +8*sum(len(path)+len(digest) for path, digest in _SOURCES.items())
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
        order_owner = retain(ORDER.prepare(geometry, startup, old, capacity, source,
            budget=budget, cancel=check))
        ordered = order_owner.value
        prepared, payload = ordered['prepared'], ordered['payload']
        old, capacity, source = ordered['old'], ordered['capacity'], ordered['source']
        normalized = prepared['boundary']
        temperatures = {fid for fid, (kind, _) in normalized.items() if kind == 'temperature'}
        powers = set(normalized)-temperatures
        refinements = []
        with threadpool_limits(1):
            low = complete(LOW.solve(prepared, old, capacity, dt, source,
                target=target, budget=budget, source_bindings=_SOURCES, cancel=check, observe=observe))
            stage('certify-full-polygon-functionals')
            # R14 (H5a): one prepared geometry for every reconstruction of this
            # call, on this frame's stack; closed below once the payload is no
            # longer consumed. It is used only for this payload, these sets and k.
            prepared_shared = retain(FUNCTIONS.prepare_shared(payload, temperatures, powers, k,
                budget=budget, cancelled=check))
            row_owner = complete(FUNCTIONS.reconstruct(payload,
                boundary_point_faces=temperatures, boundary_power_faces=powers,
                conductivity=k, budget=budget, cancelled=check, prepared_shared=prepared_shared))
            rows, proof = row_owner.value
            witness = proof
            assessment = None
            ladder = tuple(FUNCTIONS.PRECISIONS)
            if (not ladder or any(type(rung) is not int or rung <= 0 for rung in ladder)
                    or any(a >= b for a, b in zip(ladder, ladder[1:], strict=False))):
                raise AssertionError('Strictly increasing finite precision ladder required')
            used, first = {}, {}
            for attempt in range(len(ladder)):
                if attempt:
                    if assessment is None or not isinstance(assessment.value, ASSEMBLY.RefinementRequired):
                        raise AssertionError('Refinement requires a complete preceding request')
                    # No request-value alias is kept. Only the selection is
                    # needed now; retire the obsolete contributor census before
                    # reconstruction. Its aggregate decision has already failed
                    # closed, and the next assessment is a new complete one.
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
                            selected_faces=faces, certification_precisions=offered,
                            prepared_shared=prepared_shared))
                        refined_rows, refined_proof = refined.value
                        merged = complete(REFINEMENT.intersect(rows, refined_rows,
                            faces, budget=budget, cancel=check))
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
                assessment = retain(ASSEMBLY.assess(rows, len(capacity), normalized,
                    witness=witness, source_bindings=_SOURCES, budget=budget, cancel=check))
                if isinstance(assessment.value, ASSEMBLY.CertifiedAssembly):
                    # Construct/cache the rounded view while its original
                    # assessment reservation still funds that construction.
                    assessment = retain(LIFE.compact_assessment(assessment, normalized,
                        budget=budget, cancelled=check))
                    break
            else:
                raise ASSEMBLY.UnresolvedRounding('Aggregate rounding unresolved after unchanged finite precision ladder')
            used = first = ladder = None  # only borrowed face identifiers and rungs
            rows = None
            proof_only(row_owner)
            row_owner = None
            # Exact geometry payload is no longer consumed. Keep only the
            # prepared LOW boundary/face identity (including conservative spare
            # LOW rows) until FINISH; caller still owns the issued native metric.
            prepared_shared.close()  # R14: no reconstruction follows; idempotent on the stack
            prepared_shared = None
            payload = None
            # Canonical scratch borrows original prepared/payload leaves.
            # Retain their complete original startup owner through FINISH.
            system = assessment.rounded_system(normalized, cancel=check)
            stage('solve-certified-high')
            old64, capacity64, source64 = (tuple(map(float, values)) for values in (old, capacity, source))
            high = complete(SPARSE.solve_rounded(system, old64, capacity64, float(dt),
                source64, normalized, target, budget=budget, cancel=check, observe=observe))
            # solve_rounded AND complete have returned. Any result witness
            # alias is included in complete HIGH custody before assembly retires.
            system = None
            assessment.close()
            assessment = None
            stage('finish-conservative-ledger')
            finish_inputs = retain(ORDER.finish_inputs(order_owner, low, high,
                budget=budget, cancel=check))
            original_old, original_capacity, original_source = ordered['original_inputs']
            finished = retain(FINISH.finish(original_old, original_capacity, dt, original_source, normalized,
                prepared['face_ids'], finish_inputs.value['low'], finish_inputs.value['high'], _SOURCES, target,
                cancelled=check, budget=budget, observe=observe))
            result, info = finished.value
        _check_sources(check)
        info.update(physical_scratch_order=ORDER.POLICY,
            public_cell_and_face_order_preserved=True,
            connected_seconds=perf_counter()-began, reconstruction=proof,
            selective_refinements=refinements, numerical_pipeline='ISSUED_METRIC_DERIVED_LOW_CERTIFIED_HIGH_CONSERVATIVE_FINISH',
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


def advance(geometry, old, capacity, dt, source, boundary, *, conductivity,
            absolute_residual_target, budget, cancelled=None, observe=None):
    """Return a compact owner of (sealed result, diagnostics), with fixed physics.

Caller inputs/native metric stay caller-owned and immutable. Precision-only
refinement retains the same support, Decimal80 operator and absolute target.
Drop borrowed outputs before closing. Failure tracebacks retain all still-live
work; no old-generation credit precedes independent output admission.
"""
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Private composed heat cancelled')
        return False

    def stage(name):
        check()
        if observe is not None:
            observe(name)

    check()
    from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
    if type(geometry) is not MimeticGeometry or geometry._budget is not budget:
        raise TypeError('Issued immutable metric with same caller budget required')
    if (type(boundary) is not dict or any(type(v) not in (list, tuple) for v in (old, capacity, source))
            or len(old) != len(capacity) or len(source) != len(capacity)
            or len(capacity) != len(geometry._cells)):
        raise ValueError('Matching caller-owned arrays and explicit boundary dictionary required')
    value = float(conductivity)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Positive uniform scalar conductivity required')
    _check_sources(check)
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
    try:
        raw = _run(geometry, old, capacity, dt, source, boundary, Q(value),
                   absolute_residual_target, budget, check, stage, observe)
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
        return OwnedAdvance(output, geometry)
    except BaseException:
        if meter is not None:
            meter.fail()
        raise
