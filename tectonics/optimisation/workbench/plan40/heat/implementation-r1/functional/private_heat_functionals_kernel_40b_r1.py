"""Connected owned uniform-k physical-face reconstruction, private successor.

Same polygons, point/power observations, dyadic basis, exact complete-shell
policy, jump, rank fallback and precision defaults as FUNCTIONALS r1. A caller
must own the supplied decoded payload and full native geometry validation.
Every created stage has prospective accounted ownership; this is not a GMP
allocator/RSS proof, native route or whole-forward resource certificate.

The observer receives only before-face metadata and completed owned rows, not
transient matrices. Completed rows are borrowed until the returned owner closes.
No raw temporary may escape and silently invalidate a released-stage claim.

R4 retains completed rows through owned value r3. It also shrinks the
reservation of the call's prepared geometry once ``_prepare`` has returned:
that reservation is sized for the widest intermediate of the preparation in
every slot, and it used to be held for the whole call. What ``_prepare`` built
then exists and is counted (counted blocks r1); the reservation falls to that.
No arithmetic, order, support or precision differs.

R5 can hand the loop over the selected faces to worker processes (functionals
parallel r1). It does so only while the call is metered (process meter r1), at
least that module's minimum of faces has to be reconstructed (a face with a
prescribed power is not counted) and no observer is given; otherwise the loop
runs here as in R4. A worker calls this module's own
``_face`` with the same inputs, so the rows, their order and every census field
but the wall-clock seconds are R4's, and so is every reservation formula. What
is not the same (the ledger's timeline, object sharing between rows and the
prepared geometry) is listed in that module.
"""
from fractions import Fraction
import sys
from time import perf_counter

import private_heat_functionals_kernel_r1 as F
import private_heat_certification_resources_r1 as I
import private_heat_counted_blocks_r2 as COUNT
import private_heat_exact_growth_r1 as E
import private_heat_support_basis_resources_r2 as B
import private_heat_polygon_moment_40b_r1 as MOMENT
import private_heat_functional_bounds_kernel_r2 as FUNCTIONAL
import private_heat_owned_value_r4 as RETAIN
import private_heat_decimal_sparse_core_r1 as P
import private_heat_functionals_parallel_r1 as PARALLEL

G = F.G
PRECISIONS = F.K.PRECISIONS


def _prepare(payload, boundary_point_faces, boundary_power_faces, conductivity, *, budget, cancelled):
    if type(payload) is not dict or type(payload.get('cells')) is not list or type(payload.get('faces')) is not list:
        raise ValueError('Caller-owned decoded geometry payload required')
    cells, faces = payload['cells'], payload['faces']
    if type(boundary_point_faces) not in (tuple, list, set, frozenset) or type(boundary_power_faces) not in (tuple, list, set, frozenset):
        raise ValueError('Explicit finite original boundary partitions required')
    if type(conductivity) not in (int, Fraction, G.mpq):
        raise TypeError('Exact represented uniform conductivity required')
    # Counts and hex widths only; no int/mpq decode before admission.
    incidence = largest_bits = 1
    for cell in cells:
        I.check(cancelled)
        incidence += len(cell['faces'])
    for records, fields in ((cells, ('centroid_m',)), (faces, ('centroid_m', 'area_vector_m2'))):
        for record in records:
            for field in fields:
                raw = record[field]
                if type(raw) not in (list, tuple) or len(raw) != 3:
                    raise ValueError('Exact three-dimensional encoded vector required')
                for pair in raw:
                    if type(pair) not in (list, tuple) or len(pair) != 2 or any(type(s) is not str or not s for s in pair):
                        raise ValueError('Original signed-hex rational pair required')
                    largest_bits = max(largest_bits, 4*len(pair[0]), 4*len(pair[1]))
    import private_heat_gmp_resources_r1 as R
    metadata = 262144+I.D.CONTAINER_UNIT*(24*len(cells)+48*len(faces)+16*incidence+256)
    work = R.OwnedWorkspace(budget, metadata, category='heat-functional-geometry', cancelled=cancelled)
    work.__enter__()
    try:
        B.B._verify(cancelled)
        arena = E.Arithmetic(work, G, scalar_slots=3*len(cells)+8*len(faces)+128,
            container_bytes=metadata, initial_bits=max(largest_bits, 8*B.B._coordinate(conductivity)), cancelled=cancelled)
        def decode(pair):
            arena.reserve(max(4*len(pair[0]), 4*len(pair[1]), 1))
            return G.mpq(int(pair[0], 16), int(pair[1], 16))
        def vector(raw):
            return tuple(decode(pair) for pair in raw)
        def total(values):
            result = arena.q(0)
            for value in values:
                result = arena.rational('add', result, value)
            return result
        ids = {cell['cell_id']: i for i, cell in enumerate(cells)}
        face_ids = {face['face_id'] for face in faces}
        if not cells or len(ids) != len(cells) or len(face_ids) != len(faces):
            raise ValueError('Distinct nonempty cell and face inventories required')
        boundary_ids = {face['face_id'] for face in faces if len(face['owners']) == 1}
        dirichlet, neumann = set(boundary_point_faces), set(boundary_power_faces)
        if dirichlet & neumann or dirichlet | neumann != boundary_ids:
            raise ValueError('Point-temperature and outward-power sets must partition exterior faces')
        if type(conductivity) is Fraction:
            k = G.mpq(conductivity.numerator, conductivity.denominator)
        else:
            k = arena.q(conductivity)
        if k <= 0:
            raise ValueError('Positive uniform conductivity required')
        points, linked, owners_of = {}, {}, {}
        for i, cell in enumerate(cells):
            I.check(cancelled)
            points['cell', i] = vector(cell['centroid_m'])
            for fid, sign in cell['faces']:
                if sign not in (-1, 1) or (fid, i) in linked:
                    raise ValueError('Unique signed cell incidence required')
                linked[fid, i] = sign
                owners_of.setdefault(fid, set()).add(i)
        if set(owners_of) != face_ids:
            raise ValueError('Cell references and declared faces disagree')
        geometry, face_data = {}, {}
        for face in faces:
            I.check(cancelled)
            fid = face['face_id']
            if not 1 <= len(face['owners']) <= 2 or len(set(face['owners'])) != len(face['owners']):
                raise ValueError('One or two distinct physical owners required')
            owners = sorted((ids[cid], linked[fid, ids[cid]]) for cid in face['owners'])
            if len(owners) == 2 and sum(sign for _, sign in owners):
                raise ValueError('Interior incidence must be opposite')
            if owners_of[fid] != {i for i, _ in owners}:
                raise ValueError('Face and cell ownership disagree')
            centre, normal = vector(face['centroid_m']), vector(face['area_vector_m2'])
            squared = total(arena.rational('multiply', a, a) for a in normal)
            if not squared:
                raise ValueError('Nondegenerate three-dimensional face vectors required')
            geometry[fid] = dict(centre=centre, normal=normal, owners=owners)
            face_data[fid] = face
            if fid in dirichlet:
                points['wall', fid] = centre
            elif fid in neumann:
                points['power', fid] = centre
                i, sign = owners[0]
                distance = arena.rational('multiply', sign, total(
                    arena.rational('multiply', a, arena.rational('subtract', b, c))
                    for a, b, c in zip(normal, centre, points['cell', i], strict=True)))
                if distance <= 0:
                    raise ValueError('Positive boundary normal distance required')
                geometry[fid]['beta'] = arena.rational('divide', distance, arena.rational('multiply', k, squared))
        return P.OwnedSolve(dict(points=points, geometry=geometry, face_data=face_data,
            face_ids=face_ids, dirichlet=dirichlet, neumann=neumann, conductivity=k), work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


PREPARED_KEYS = frozenset(('points', 'geometry', 'face_data', 'face_ids', 'dirichlet', 'neumann', 'conductivity'))
PREPARED_OWNER = 8192


def _prepared_bytes(prepared, cancelled):
    """What the objects ``_prepare`` created occupy, once it has returned.

    Its arithmetic arena, scratch and local maps are gone by then; what is left
    is this graph. The points and the per-face geometry are counted object by
    object, aliases each time. The face records and the identifiers held by the
    sets belong to the caller's decoded payload: only the containers that hold
    them are counted. Returns None for a graph this count does not know.
    """
    if type(prepared) is not dict or set(prepared) != PREPARED_KEYS:
        return None
    total = COUNT.own_bytes(prepared, G)+PREPARED_OWNER
    for name in prepared:
        total += COUNT.own_bytes(name, G)
    for name in ('points', 'geometry'):
        pending = [prepared[name]]
        while pending:
            item = pending.pop()
            I.check(cancelled)
            if type(item) not in (dict, list, tuple, str, int, G.mpq):
                return None
            total += COUNT.own_bytes(item, G)
            if type(item) is dict:
                for key, child in item.items():
                    pending.append(key)
                    pending.append(child)
            elif type(item) in (list, tuple):
                pending.extend(item)
    for name in ('face_data', 'face_ids', 'dirichlet', 'neumann'):
        if type(prepared[name]) not in (dict, set, frozenset):
            return None
        total += COUNT.own_bytes(prepared[name], G)
    if type(prepared['conductivity']) is not G.mpq:
        return None
    return total+COUNT.own_bytes(prepared['conductivity'], G)


def _face(fid, data, prepared, moment, *, budget, cancelled, certification_precisions):
    """All per-face numerical frames vanish before transfer of completed row."""
    import private_heat_gmp_resources_r1 as R
    points, geometry = prepared['points'], prepared['geometry']
    metadata = 262144+I.D.CONTAINER_UNIT*(24*len(points)+256)
    work = R.OwnedWorkspace(budget, metadata, category='heat-functional-face', cancelled=cancelled)
    work.__enter__()
    try:
        centre, normal, owners = data['centre'], data['normal'], data['owners']
        target_moment = moment(fid)
        if fid in prepared['neumann']:
            key, value = ('power', fid), G.mpq(owners[0][1])
            return P.OwnedSolve(dict(row=dict(face_id=fid, owners=owners, ordered_keys=[key], bounds={key: (value, value)}),
                diagnostics=dict(face_id=fid, prescribed_power_exact=True, samples=1,
                                 moment_identity_kind='prescribed-exact-transfer')), work)
        screen_owner = work.stack.enter_context(B.support(list(points.items()), centre, budget=budget,
                                                        minimum=40, cancelled=cancelled))
        screen = screen_owner.value
        ranked, full_order = list(screen.shell), False
        count = len(ranked)
        basis_owner = work.stack.enter_context(B.basis(centre, [p for _, _, p in ranked], budget=budget, cancelled=cancelled))
        basis, k = basis_owner.value, prepared['conductivity']
        def observation(key):
            I.check(cancelled)
            if key[0] != 'power':
                return basis.point(points[key])
            observed = geometry[key[1]]
            oriented = basis.flux(observed['centre'], observed['normal'], moment(key[1]), k)
            factor = basis.op('multiply', observed['beta'], observed['owners'][0][1])
            return basis.multiply(oriented, factor)
        gradient = basis.flux(centre, normal, target_moment, k)
        i, sign = owners[0]
        ki = ('cell', i)
        kj = ('cell', owners[1][0]) if len(owners) == 2 else ('wall', fid)
        denominator = basis.op('multiply', sign, basis.total(basis.op('multiply', a, basis.op('subtract', b, c))
            for a, b, c in zip(normal, points[kj], points[ki], strict=True)))
        if denominator <= 0:
            raise ValueError('No positive geometric transmissibility')
        tau = basis.op('divide', basis.op('multiply', k, basis.total(basis.op('multiply', a, a) for a in normal)), denominator)
        signed_tau = basis.op('multiply', sign, tau)
        pi, pj = basis.point(points[ki]), basis.point(points[kj])
        target = basis.target(gradient, pi, pj, signed_tau)
        matrix = [observation(key) for _, key, _ in ranked[:count]]
        attempts, expansions = [], 0
        while True:
            I.check(cancelled)
            # Attempts retain their audits; reserve new keys/conversion/list
            # generations before constructing this declared complete shell.
            metadata += I.D.CONTAINER_UNIT*(4*count+64)
            work.resize_before_allocation_or_after_drop(metadata)
            keys = [key for _, key, _ in ranked[:count]]
            conversion = [geometry[key[1]]['beta'] if key[0] == 'power' else G.mpq(1) for key in keys]
            owner = work.stack.enter_context(FUNCTIONAL.functional_bounds(matrix, target, keys,
                (ki, kj), signed_tau, conversion, gradient=gradient, base_observations=(pi, pj),
                budget=budget, cancelled=cancelled, certification_precisions=certification_precisions))
            audit = owner.value['evidence']
            attempts.append(audit)
            if owner.value['status'] == 'CERTIFIED':
                result = owner.value['row']
                break
            if not full_order:
                original_keys = keys
                ranked, full_order = list(screen.full_ranking()), True
                if [key for _, key, _ in ranked[:count]] != original_keys:
                    raise AssertionError('Broadphase changed the original complete exact shell')
            if count == len(ranked):
                raise ValueError(f'Available point/power observations cannot represent face {fid}')
            cutoff, end = ranked[count][0], count+1
            while end < len(ranked) and ranked[end][0] == cutoff:
                end += 1
            matrix.extend(observation(key) for _, key, _ in ranked[count:end])
            count, expansions = end, expansions+1
        row = dict(face_id=fid, owners=owners, **result)
        census = dict(face_id=fid, samples=count, rank=audit['rank'], expanded_shells=expansions,
            power_observations=sum(key[0] == 'power' for _, key, _ in ranked[:count]),
            support_screen=dict(screen.diagnostics), functional_attempts=attempts,
            moment_identity_kind=audit['moment_identity_kind'])
        return P.OwnedSolve(dict(row=row, diagnostics=census), work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def reconstruct(payload, *, boundary_point_faces, boundary_power_faces, budget,
                conductivity=1, cancelled=None, selected_faces=None, observe=None,
                certification_precisions=PRECISIONS):
    """Owner.value is (rows, evidence); selected rows preserve payload order.

The decoded payload/full geometry are caller-owned. This covers newly created
geometry metadata, moments, supports, basis rows, rank/interval/exact work and
retained rows/proofs. Observers may borrow completed rows only while owner lives.
"""
    F.K._require_gmp()
    I.check(cancelled)
    began = perf_counter()
    if type(payload) is not dict or type(payload.get('faces')) is not list:
        raise ValueError('Caller-owned decoded physical geometry required')
    if type(certification_precisions) not in (tuple, list) or not certification_precisions:
        raise ValueError('Explicit finite nonempty precision ladder required')
    import private_heat_gmp_resources_r1 as R
    metadata = 262144+I.D.CONTAINER_UNIT*(24*len(payload['faces'])+256)
    work = R.OwnedWorkspace(budget, metadata, category='heat-functional-retained-rows', cancelled=cancelled)
    work.__enter__()
    try:
        prepared_owner = work.stack.enter_context(_prepare(payload, boundary_point_faces,
            boundary_power_faces, conductivity, budget=budget, cancelled=cancelled))
        prepared = prepared_owner.value
        if COUNT.supported(G):
            # _prepare has returned: its arena, scratch and local maps are gone,
            # and what it built exists. Hold that, not the worst case for it.
            settled = _prepared_bytes(prepared, cancelled)
            if settled is not None and settled < prepared_owner._workspace.lease.count:
                prepared_owner._workspace.resize_before_allocation_or_after_drop(settled)
        face_ids, partial = prepared['face_ids'], selected_faces is not None
        if partial:
            if type(selected_faces) not in (tuple, list, set, frozenset):
                raise ValueError('Explicit finite distinct selected faces required')
            requested = tuple(selected_faces)
            if any(type(fid) is not str for fid in requested):
                raise ValueError('Selected face identifiers must be strings')
            selected = set(requested)
            if len(selected) != len(requested) or not selected.issubset(face_ids):
                raise ValueError('Duplicate or unknown selected face identifier')
        else:
            selected = face_ids
        moments = {}
        def moment(fid):
            if fid not in moments:
                owned = work.stack.enter_context(MOMENT.second_moment(prepared['face_data'][fid], budget=budget, cancel=cancelled))
                moments[fid] = owned.value['moment']
            return moments[fid]
        rows, census = [], []
        # Zero is the unchanged loop. An observer is promised its faces in order, one at a time.
        # A face with a prescribed power needs no reconstruction and is not counted.
        shared = PARALLEL.workers(budget, len(selected-prepared['neumann'])) if observe is None else 0
        if shared >= 2:
            rows, census, validated = PARALLEL.reconstruct_faces(sys.modules[__name__], prepared,
                [face['face_id'] for face in payload['faces'] if face['face_id'] in selected],
                budget=budget, cancelled=cancelled, certification_precisions=certification_precisions,
                work=work, retain=RETAIN)
        else:
            validated = moments
        for face in payload['faces'] if shared < 2 else ():
            fid = face['face_id']
            if fid not in selected:
                continue
            I.check(cancelled)
            if observe is not None:
                observe('before-face', dict(face_id=fid, rows_completed=len(rows)))
            temporary = _face(fid, prepared['geometry'][fid], prepared, moment, budget=budget,
                cancelled=cancelled, certification_precisions=certification_precisions)
            try:
                retained = RETAIN.transfer(temporary, budget=budget, cancelled=cancelled)
            except BaseException:
                temporary.__exit__(*sys.exc_info())
                raise
            work.stack.enter_context(retained)
            rows.append(retained.value['row'])
            census.append(retained.value['diagnostics'])
            if observe is not None:
                observe('certified-row', dict(row=rows[-1], diagnostics=census[-1]))
        if not partial and set(validated) != face_ids:
            raise AssertionError('Complete reconstruction omitted a polygon validation')
        interval_faces = exact_faces = exact_attempts = 0
        for entry in census:
            if entry.get('prescribed_power_exact'):
                continue
            attempts = entry['functional_attempts']
            exact_attempts += sum(bool(item['exact_fallback']) for item in attempts)
            interval_faces += attempts[-1]['route'] in ('interval', 'interval-reduced')
            exact_faces += attempts[-1]['route'] in ('exact-fallback', 'exact-reduced-zero')
        evidence = dict(seconds=perf_counter()-began, basis_dimension=20,
            all_twenty_integrated_moment_identities_certified=True,
            all_twenty_integrated_moment_checks_exact=interval_faces == 0, census=census,
            interval_certified_faces=interval_faces, exact_fallback_faces=exact_faces,
            exact_fallback_attempts=exact_attempts, coefficient_output='exact-rational-enclosures',
            assembly_requirement='Enclose exact cross-face sums before Decimal80 rounding',
            moment_certificate_note='Interval route is an algebraic identity, not materialised rational coefficient checks',
            nearest_shell_rule='conservative interval screening, exact complete shell, full exact rank-expansion fallback',
            power_input_convention='outward face-integrated watts',
            power_scaling='normal_distance/(conductivity*face_area), exact area-vector ratio',
            exterior_temperature_samples=len(prepared['dirichlet']), prescribed_power_faces=len(prepared['neumann']),
            general_planar_convex_face_moments=True, stability_proven=False,
            production_resource_accounting=False, partial_reconstruction=partial,
            physical_functional_equations_and_precision_unchanged=True,
            exact_cubic_basis_frame='nearby binary64 dyadic origin and power-of-two scale',
            physical_geometry_rounded=False, functional_cancellation_per_scalar=True,
            reconstruction_scope='SELECTED_FACES_ONLY' if partial else 'ALL_PHYSICAL_FACES',
            full_incidence_metadata_checked=True, full_polygon_geometry_validated=not partial,
            full_geometry_acceptance=False, selected_face_ids=[row['face_id'] for row in rows],
            total_physical_faces=len(payload['faces']), polygon_moments_computed=len(validated),
            prospective_stage_ownership=True, allocator_or_rss_bound=False,
            decoded_payload_and_full_native_geometry_caller_owned=True, whole_forward_admission=False,
            observer_scope='before-face metadata and completed owned rows; no transient matrices')
        I.check(cancelled)
        return P.OwnedSolve((rows, evidence), work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


