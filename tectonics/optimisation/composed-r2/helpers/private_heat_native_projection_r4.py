"""Private exact integrated-transfer projection with actual-operation owners.

Same mathematical/provenance checks as frozen projection r2. Canonical integer
part equality avoids unused products; last-use scratch drops preserve output.
No numerical
solve, endpoint face trace, native issue or acceptance is inferred. Arithmetic
and output codec are separate owned lifetimes; no global interior denominator
growth estimate is used. Selected GMP is gated when the method is invoked.
JSON views follow resources r4; the metric decode is released after its one
cell-order check instead of being carried through projection and issuance.
"""
import hashlib
import math
import sys

import private_heat_finish_kernel_r3 as A
import private_heat_issuer_resources_r4 as R
import private_heat_public_float_r1 as PUBLIC
import heat_ledger_issuer_patch as HEAT_LEDGER
import live_spatial_patch as LIVE_SPATIAL
import private_heat_indexed_runtime as INDEXED
from atlas_tectonics.integration_mimetic_heat import MimeticGeometry


def _q(value):
    G = A.A.exact_library()
    if isinstance(value, (tuple, list)):
        if len(value) != 2 or any(type(v) is not str for v in value):
            raise ValueError('Exact private decimal rational pair required')
        return G.mpq(G.mpz(value[0]), G.mpz(value[1]))
    return G.mpq(value)


def _hex(value):
    return [hex(int(value.numerator)), hex(int(value.denominator))]


def _encode(record, exact, geometry, ordered_cell_ids, arrays, state_id, dt, cancel, record_scope=None):
    metadata = dict(schema='atlas.private.native-heat-contract.r1',
        native_issue_performed=False, native_resource_admitted=False, production_acceptance=False,
        private_result_id=record['result_id'], geometry_id=geometry.geometry_id,
        unverified_advance_context=dict(state_id=state_id, duration_s=dt),
        origin_binding_status='NOT_ESTABLISHED: native plan, state, duration and numerical geometry provenance must be bound by the native producer before adoption',
        cell_ids=ordered_cell_ids, face_ids=list(geometry._face_ids),
        endpoint_face_trace_status=A.TRACE_STATUS, method_id=record['method_id'],
        independently_supplied_absolute_residual_target=_hex(exact['target']),
        exact_corrected_enthalpy_j=(list(map(_hex, exact['new'])) if record_scope is None else HEAT_LEDGER.exact_rows(exact['new'], record_scope, lambda: R.check(cancel))),
        exact_retained_solver_residual_j=(list(map(_hex, exact['retained'])) if record_scope is None else HEAT_LEDGER.exact_rows(exact['retained'], record_scope, lambda: R.check(cancel))),
        exact_stock_projection_residual_j=(list(map(_hex, exact['projection'])) if record_scope is None else HEAT_LEDGER.exact_rows(exact['projection'], record_scope, lambda: R.check(cancel))),
        exact_cell_storage_residual_j=(list(map(_hex, exact['public'])) if record_scope is None else HEAT_LEDGER.exact_rows(exact['public'], record_scope, lambda: R.check(cancel))),
        exact_paired_face_energy_j=(list(map(_hex, exact['canonical'])) if record_scope is None else HEAT_LEDGER.exact_rows(exact['canonical'], record_scope, lambda: R.check(cancel))),
        exact_source_energy_j=_hex(exact['source_total']),
        exact_outward_boundary_energy_j=_hex(exact['outward']),
        accounting='Native storage residual is TOTAL public residual; signed exact face amounts are not projected to binary64.')
    # Native projection has already checked and captured these lists. Its
    # owner stays live until the independent immutable snapshot is admitted.
    output = dict(metadata=metadata, arrays=dict(enthalpy_j=record['enthalpy_j'],
        temperature_k=record['temperature_k'], input_enthalpy_j=LIVE_SPATIAL.float_list(arrays[0]),
        input_capacity_j_k=LIVE_SPATIAL.float_list(arrays[1]), input_source_w=LIVE_SPATIAL.float_list(arrays[2])))
    # The internal exact boundary view is not part of JSON or the result ID.
    # It remains borrowed from the numerical owner until issuance finishes.
    if record_scope is None:
        R.stream_hash(output, cancel)
    # Compact rows are authenticated once by the final ledger codec.
    output['boundary_exact'] = exact['boundary']
    return output


def project(result, geometry, *, cell_ids, enthalpy_j, capacity_j_k, source_w,
            duration_s, state_id, absolute_residual_target, budget, cancel=None, record_scope=None):
    """Own (projection, verified record); internal exact boundaries are borrowed.

    Only the original current finisher class and issued geometry are accepted.
    Source/identity and input ordering are checked before and after projection.
    This is not a constructor for a native or forward-issued result.
    """
    if type(geometry) is not MimeticGeometry or geometry._budget is not budget:
        raise TypeError('Original issued metric and same resource owner required')
    if type(result) is not A.PrivateNumericalResult:
        raise TypeError('Actual fixed private numerical result required')
    if type(state_id) is not str or not state_id:
        raise ValueError('Actual transported state identity required')
    work = R.workspace(budget, 0, cancel=cancel, category='private-heat-projection-r3-owner')
    work.__enter__()
    try:
        n = len(geometry._cells)
        work.stack.enter_context(R.workspace(budget, 65536+R.UNIT*(4*n+16), cancel=cancel,
                                             category='private-heat-projection-input-capture'))
        def capture(values):
            result = []
            for value in values:
                R.check(cancel)
                if len(result) == n:
                    raise ValueError('Complete original input coverage required')
                result.append(value)
            if len(result) != n:
                raise ValueError('Complete original input coverage required')
            return result
        ordered = capture(cell_ids)
        arrays = list(map(capture, (enthalpy_j, capacity_j_k, source_w)))
        if any(any(type(v) not in (int, float) or not math.isfinite(v) for v in values) for values in arrays):
            raise ValueError('Complete original represented finite input arrays required')
        dt = float(duration_s)
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError('Positive represented duration required')
        blob = result._sealed
        record_owner = work.stack.enter_context(R.verified_private(result, A, budget=budget, cancel=cancel))
        record = record_owner.value
        # The complete metric decode serves this one order check; it is not
        # carried through exact projection, codec and issuance.
        if (record.get('schema') != A.SCHEMA or record.get('private_only') is not True
                or record.get('production_acceptance') is not False
                or record.get('endpoint_face_trace_status') != A.TRACE_STATUS):
            raise ValueError('Expected distinct private integrated-transfer result')
        # This workspace already funds the ordered identity list. Indexed
        # access replaces only the formerly whole-mesh decode/order check.
        if ordered != list(INDEXED.ordered_cell_ids(geometry, cancel=cancel)):
            raise ValueError('Original cell order differs from the actual metric complex')
        if record['face_ids'] != list(geometry._face_ids):
            raise ValueError('Original face order differs from the actual metric complex')
        if (len(record['enthalpy_j']) != n or len(record['temperature_k']) != n
                or any(not math.isfinite(e) or e <= 0 or not math.isfinite(t) or t <= 0
                       for e, t in zip(record['enthalpy_j'], record['temperature_k'], strict=True))):
            raise ValueError('Finite positive complete public enthalpy and temperature required')
        numerical = work.stack.enter_context(R.calculate(record, geometry, *arrays, dt,
            absolute_residual_target, budget=budget, cancel=cancel))
        exact = numerical.value
        groups = tuple(exact[key] for key in ('new', 'retained', 'projection', 'public', 'canonical'))
        groups += ((exact['target'], exact['source_total'], exact['outward']),)
        # Native mpq getters can allocate part copies. Fund those from owned
        # object allocation before inspecting bit lengths in the codec plan.
        largest = max(sys.getsizeof(value) for group in groups for value in group)
        with R.workspace(budget, 65536+4*largest, cancel=cancel):
            codec = R.projection_output_plan(groups, budget=budget, cancel=cancel)
        work.stack.enter_context(R.workspace(budget, codec['bytes'] if record_scope is None else
                                             HEAT_LEDGER.compact_codec_bytes(exact, R, budget, cancel), cancel=cancel,
                                             category='private-heat-projection-actual-codec'))
        projected = _encode(record, exact, geometry, ordered, arrays, state_id, dt, cancel, record_scope)
        if result._sealed is not blob or geometry.geometry_id != INDEXED.metric_identity(geometry, cancel=cancel):
            raise ValueError('Private result or actual metric identity changed during projection')
        if any(R.source_hash(path, cancel) != digest for path, digest in record['sources'].items()):
            raise ValueError('Private corrected result source binding changed during projection')
        projected['metadata']['projection_resource_policy'] = dict(
            derived_before_each_exact_operation=True, numerical=numerical.inventory,
            output_components=codec['components'], output_widths_derived_after_validation_before_encoding=True,
            allocator_or_rss_bound=False, native_admission=False, single_verified_private_decode=True)
        return R.P.OwnedSolve((projected, record), work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
