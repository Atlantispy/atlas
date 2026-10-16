"""WP7 H-a: exact r13 packaging from the unchanged numerical heat producer.

Apply after the indexed issuer/projection transforms. The r12 logical method
and schema strings remain part of the old scientific identity; the generated
r13 module and source binding identify the packaging revision. No scope is
created here. WP8 supplies the existing owner's retained scope.
"""
from hashlib import sha256
import sys


ISSUER_SHA = '61efbd3fb20a4387a40adf1c7010e77b7ad63312fe9fc3f6f795b24925dbd847'
PROJECTION_SHA = '359545c76eb7309f20e6b0ba71b7c65fd2165529e0b4a8f721b4df0a95c9b1c1'
JOINED_SHA = '7adb786f80f02fb87d5d36140060c2371204ee434570ecde849baeff8faf2405'


def required_scope(origins, budget, *, fixture=False, supplied=None):
    """Bind the one existing owner scope; only explicit fixtures may supply it."""
    from compact_contracts import ContractError
    from content_cache import RetainedScope
    if type(fixture) is not bool or not origins:
        raise ContractError('heat packaging requires actual call origins')
    if not fixture and supplied is not None:
        raise ContractError('actual owner scope cannot be replaced by a supplied scope')
    scope = supplied if fixture else getattr(origins[0], '_record_scope', None)
    if (not isinstance(scope, RetainedScope) or scope._closed or
            scope.run_budget is not budget):
        raise ContractError('heat packaging requires the existing same-budget record scope')
    return scope


def verify_scope(call):
    scope = required_scope(call._origin_objects, call._budget,
        fixture=call._fixture, supplied=call._record_scope if call._fixture else None)
    if scope is not call._record_scope:
        raise ValueError('bound heat owner record scope changed')
    return scope


def row_part_bytes(bits):
    """(retained hex text, transient conversion) bytes for one exact part.

    CPython 3.12 sizes: an ASCII str is a 40-byte header, its characters and
    a NUL (sign and '0x' included); an int stores 30 bits per 4-byte digit;
    a gmpy2 mpz copy is a small header and 64-bit limbs. 64 bytes per object
    covers headers and allocator rounding. Conversion holds one GMP copy and
    one Python int; the int and the new text then overlap, and the text is
    already part of the retained row.
    """
    digits = max(1, (bits+3)//4)
    text = 64+digits+3
    work = (64+8*((bits+63)//64))+(64+4*((bits+29)//30))
    return text, work


ROW_FIXED_BYTES = 512


def exact_rows(values, scope, check):
    """Encode one exact kernel rational at a time, funded before hex allocation.

    The unchanged projection workspace owns the exact input list. A failed
    row retains its own charge in the traceback, including after that workspace
    exits. Successful rows are released by RecordCodec before the next row.
    Charges derive from the exact part bit lengths (S7IO-5), not a multiplier.
    """
    from compact_contracts import ContractError
    from content_cache import ChargeSpec
    from record_tables import MAX_ROW_WORK_BYTES, StreamingRows
    from atlas_tectonics.exact_arithmetic import library
    def rows():
        backend = library()
        for value in values:
            check()
            if backend is None or type(value) is not backend.mpq:
                raise ContractError('heat rows require the actual selected GMP exact kernel values')
            # GMP getters copy an integer part. sys.getsizeof(mpq) covers both
            # allocated parts without a copy, so it funds the one-at-a-time
            # copies that measure the exact bit lengths.
            probe = 4096+sys.getsizeof(value)
            if probe > MAX_ROW_WORK_BYTES:
                raise ContractError('heat rational row exceeds the fixed row workspace')
            with scope.reserve(ChargeSpec('heat-ledger-exact-row-width', probe)):
                bits = (value.numerator.bit_length(), value.denominator.bit_length())
            parts = tuple(map(row_part_bytes, bits))
            size = ROW_FIXED_BYTES+parts[0][0]+parts[1][0]
            work = 4096+max(parts[0][1], parts[1][1])
            if size+work > MAX_ROW_WORK_BYTES:
                raise ContractError('heat rational row exceeds the fixed row workspace')
            with scope.reserve(ChargeSpec('heat-ledger-exact-row', size)) as reservation:
                with scope.reserve(ChargeSpec('heat-ledger-exact-row-conversion', work)):
                    row = [hex(int(value.numerator)), hex(int(value.denominator))]
                if sum(sys.getsizeof(part) for part in row)+sys.getsizeof(row) > size:
                    raise ArithmeticError('heat rational row exceeded its admitted capacity')
                yield reservation.commit(row)
    return StreamingRows(len(values), rows)


def compact_codec_bytes(exact, resources, budget, cancel):
    """Compact-route lease for the codec stage of projection (M4/S7IO-2).

    The complete projection_output_plan has already inspected every output
    width for admission and supplies the recorded output components. On the
    compact route only the three scalar pairs (target, source total and
    outward) are built under this lease: ledger rows are funded one at a time
    by exact_rows and no whole-ledger hex lists or stream codec exist. The
    lease uses the same measured part costs as exact_rows: the three retained
    pairs plus one conversion at a time.
    """
    scalars = (exact['target'], exact['source_total'], exact['outward'])
    # One GMP part copy at a time measures the exact widths.
    with resources.workspace(budget, 4096+max(sys.getsizeof(value) for value in scalars), cancel=cancel):
        bits = [(value.numerator.bit_length(), value.denominator.bit_length()) for value in scalars]
    parts = [tuple(map(row_part_bytes, pair)) for pair in bits]
    retained = sum(ROW_FIXED_BYTES+numerator[0]+denominator[0] for numerator, denominator in parts)
    return retained+4096+max(work for pair in parts for _, work in pair)


def package_result(record, fields, call, *, cancel=None):
    from heat_ledger_tables import CompactHeatSnapshot, _ordered_mesh_binding
    from content_cache import ChargeSpec
    from compact_contracts import ContractError
    import private_heat_issuer_resources_r4 as resources
    import live_spatial_patch as live
    scope = verify_scope(call)
    # Legacy json.dumps serialises the projection policy's tuple values as
    # arrays. Normalise only containers, never encode the complete metadata.
    # Rational body rows remain explicit StreamingRows throughout this walk.
    check = lambda: resources.check(cancel)
    size = 65536+live.normalisation_capacity(record, check)
    if size > 32 << 20:
        raise ContractError('heat metadata header assembly exceeds fixed bound')
    with scope.reserve(ChargeSpec('heat-ledger-header-assembly', size)) as reservation:
        owner = reservation.commit(live.normalise_containers(record, check))
    mesh = getattr(call._geometry, '_indexed', None)
    # Fresh geometry has no authenticated persisted ID source yet. Keep its
    # exact IDs in this ledger so the completed heat result is checkpointable;
    # already persisted geometry retains the existing shared-column path.
    if mesh is not None and getattr(mesh, '_segment', None) is None:
        from mesh_tables import CompactMesh
        if (type(owner.value) is not dict or type(mesh) is not CompactMesh or
                mesh.budget is not scope.run_budget):
            raise ContractError('heat/mesh shared run budget required')
        _ordered_mesh_binding(owner.value, mesh)
        if mesh.scope is not None and mesh.scope is not scope:
            raise ContractError('foreign mesh scope')
        mesh = None
    with owner:
        return CompactHeatSnapshot.from_components(owner.value, fields, scope=scope,
            check=lambda: resources.check(cancel), mesh=mesh)


def snapshot_identity(snapshot, budget, cancel=None):
    from heat_ledger_tables import CompactHeatSnapshot
    import private_heat_issuer_resources_r4 as resources
    if type(snapshot) is not CompactHeatSnapshot or snapshot.scope.run_budget is not budget:
        raise TypeError('actual same-budget compact heat snapshot required')
    resources.check(cancel)
    return snapshot.verify_identity(check=lambda: resources.check(cancel))


def plan_id(snapshot):
    with snapshot.ledger as root, root.field('plan_id') as field, field.scalar(max_owned_bytes=16384) as value:
        return value.value


def seal_token(snapshot):
    from heat_ledger_tables import CompactHeatSnapshot
    return snapshot._record if type(snapshot) is CompactHeatSnapshot else snapshot._metadata


def metadata_sha256(snapshot):
    from heat_ledger_tables import CompactHeatSnapshot
    if type(snapshot) is CompactHeatSnapshot:
        return snapshot.metadata_identity.sha256
    return sha256(snapshot._metadata).hexdigest()


def require_candidate(store, owner, *, cancel=None):
    """Refuse an unusable checkpoint writer before the genuine solve starts."""
    from compact_contracts import ContractError
    from interval_store_set import UnlistedCandidate
    import private_heat_issuer_resources_r4 as resources
    resources.check(cancel)
    scope = required_scope((owner,), owner._budget)
    # The runner owns a stable facade across sealed intervals. Unwrap only its
    # actual current candidate; an arbitrary proxy cannot acquire this route.
    # The optional facade is absent from earlier compact-source inventories.
    # This name only gates discovery; its predicate below still admits exactly
    # the concrete facade class, never a proxy or subclass.
    if type(store) is not UnlistedCandidate and type(store).__module__ == 'compact_restart_store':
        facade_module = sys.modules.get('compact_restart_store')
        if facade_module is not None and facade_module.is_compact_restart_store(store):
            if store.scope is not scope or store.readonly:
                raise ContractError('heat checkpoint facade has no same-scope writer')
            store = store.candidate
    if (type(store) is not UnlistedCandidate or store.scope is not scope or
            store.stores._candidate is not store):
        raise ContractError('heat checkpoint requires the actual same-scope current interval writer')
    store.stores._live()
    store._writing()
    resources.check(cancel)
    return store


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('heat ledger source seam missing or ambiguous: '+old[:80])
    return source.replace(old, new, 1)


def _check(source, expected):
    if type(source) is not str or sha256(source.encode()).hexdigest() != expected:
        raise ValueError('heat ledger source differs from exact reviewed predecessor')


def issuer_source(source):
    _check(source, ISSUER_SHA)
    source = _replace(source, 'import private_heat_native_projection_r4 as N\n',
        'import private_heat_native_projection_r4 as N\n'
        'import heat_ledger_issuer_patch as HEAT_LEDGER\n'
        'import heat_ledger_tables as HEAT_TABLES\n')
    source = _replace(source, 'INDEXED_NATIVE_TRANSFER, INDEXED_SPATIAL_TRANSFER], {}',
        'INDEXED_NATIVE_TRANSFER, INDEXED_SPATIAL_TRANSFER, HEAT_LEDGER, HEAT_TABLES], {}')
    source = _replace(source, 'def _private_modules():\n',
        "_COMPACT_MODULE_NAMES = ('heat_ledger_issuer_patch', 'heat_ledger_tables',\n"
        "    'record_tables', 'record_views', 'compact_contracts', 'content_cache',\n"
        "    'heat_cold_patch', 'spatial_validation_patch', 'live_spatial_patch', 'live_finite_patch', 'live_transport_result', 'segment_store',\n"
        "    'interval_store_set', 'interval_catalog', 'live_composite')\n\n\n"
        'def _private_modules():\n')
    source = _replace(source, '    # Load fixed late numerical/resource dependencies before identity capture.\n',
        '    # Fixed compact dependency set is loaded before identity capture.\n'
        '    pending.extend(importlib.import_module(name) for name in _COMPACT_MODULE_NAMES)\n'
        '    # Load fixed late numerical/resource dependencies before identity capture.\n')
    source = _replace(source,
        "            elif isinstance(value, type) and value.__module__.startswith('private_heat_'):\n",
        "            elif isinstance(value, type) and (value.__module__.startswith('private_heat_')\n"
        "                    or value.__module__ in _COMPACT_MODULE_NAMES):\n")
    source = _replace(source,
        "    if isinstance(value, type) and value.__module__.startswith('private_heat_'))\n",
        "    if isinstance(value, type) and (value.__module__.startswith('private_heat_')\n"
        "        or value.__module__ in _COMPACT_MODULE_NAMES))\n")
    source = _replace(source, '    if type(snapshot) is INDEXED_SPATIAL.IndexedSpatialSnapshot:\n',
        '    if type(snapshot) is HEAT_TABLES.CompactHeatSnapshot:\n'
        '        return HEAT_LEDGER.snapshot_identity(snapshot, budget, cancel)\n'
        '    if type(snapshot) is INDEXED_SPATIAL.IndexedSpatialSnapshot:\n')
    source = _replace(source, '    _fixture: bool\n',
        '    _fixture: bool\n    _record_scope: object = field(repr=False)\n')
    source = _replace(source,
        'def _make_call(metadata, arrays, geometry, execution, plan, origins, *, fixture=False):\n',
        'def _make_call(metadata, arrays, geometry, execution, plan, origins, *, fixture=False, record_scope=None):\n')
    source = _replace(source, '        out = object.__new__(OwnerHeatCall)\n',
        '        scope = HEAT_LEDGER.required_scope(origins, budget, fixture=fixture, supplied=record_scope)\n'
        '        out = object.__new__(OwnerHeatCall)\n'
        '        object.__setattr__(out, "_record_scope", scope)\n')
    source = _replace(source, '    call._execution.verify_boundary()\n',
        '    HEAT_LEDGER.verify_scope(call)\n    call._execution.verify_boundary()\n')
    source = _replace(source,
        "        if hashlib.sha256(self._plan_definition).hexdigest() != self.descriptor()['plan_id']:\n",
        "        if hashlib.sha256(self._plan_definition).hexdigest() != HEAT_LEDGER.plan_id(self._snapshot):\n")
    source = _replace(source,
        "            absolute_residual_target=_q(plan['absolute_residual_target']), budget=call._budget, cancel=cancel)\n",
        "            absolute_residual_target=_q(plan['absolute_residual_target']), budget=call._budget,\n"
        "            cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call))\n")
    source = _replace(source,
        "            _new_snapshot(record, {key: np.asarray(value, dtype=np.float64)\n"
        "                          for key, value in projected['arrays'].items()}, call._budget, result, '_snapshot')\n",
        "            snapshot = HEAT_LEDGER.package_result(record, {key: np.asarray(value, dtype=np.float64)\n"
        "                          for key, value in projected['arrays'].items()}, call, cancel=cancel)\n"
        "            object.__setattr__(result, '_snapshot', snapshot)\n")
    return source


def projection_source(source):
    _check(source, PROJECTION_SHA)
    source = _replace(source, 'import private_heat_public_float_r1 as PUBLIC\n',
        'import private_heat_public_float_r1 as PUBLIC\n'
        'import heat_ledger_issuer_patch as HEAT_LEDGER\n')
    source = _replace(source,
        'def _encode(record, exact, geometry, ordered_cell_ids, arrays, state_id, dt, cancel):\n',
        'def _encode(record, exact, geometry, ordered_cell_ids, arrays, state_id, dt, cancel, record_scope=None):\n')
    for name in ('new', 'retained', 'projection', 'public', 'canonical'):
        old = "list(map(_hex, exact['"+name+"']))"
        source = _replace(source, old,
            "("+old+" if record_scope is None else HEAT_LEDGER.exact_rows(exact['"+name+
            "'], record_scope, lambda: R.check(cancel)))")
    source = _replace(source,
        "        work.stack.enter_context(R.workspace(budget, codec['bytes'], cancel=cancel,\n",
        "        work.stack.enter_context(R.workspace(budget, codec['bytes'] if record_scope is None else\n"
        "                                             HEAT_LEDGER.compact_codec_bytes(exact, R, budget, cancel), cancel=cancel,\n")
    source = _replace(source, '    R.stream_hash(output, cancel)\n',
        '    if record_scope is None:\n'
        '        R.stream_hash(output, cancel)\n'
        '    # Compact rows are authenticated once by the final ledger codec.\n')
    source = _replace(source,
        '            duration_s, state_id, absolute_residual_target, budget, cancel=None):\n',
        '            duration_s, state_id, absolute_residual_target, budget, cancel=None, record_scope=None):\n')
    return _replace(source,
        '        projected = _encode(record, exact, geometry, ordered, arrays, state_id, dt, cancel)\n',
        '        projected = _encode(record, exact, geometry, ordered, arrays, state_id, dt, cancel, record_scope)\n')


def joined_source(source):
    """After indexed mesh + WP5 producer; before the WP6 joined validator."""
    _check(source, JOINED_SHA)
    source = _replace(source, 'import private_heat_grouped_account_r1 as ACCOUNT\n',
        'import private_heat_grouped_account_r1 as ACCOUNT\n'
        'import heat_ledger_issuer_patch as HEAT_LEDGER\n'
        'import heat_cold_patch as HEAT_COLD\n')
    source = _replace(source,
        'return (result._snapshot, result._snapshot._metadata, result._snapshot._fields,',
        'return (result._snapshot, HEAT_LEDGER.seal_token(result._snapshot), result._snapshot._fields,')
    source = _replace(source,
        "    if type(store) is not CAS.STORE.ArrayStore:\n"
        "        raise TypeError('Actual checkpoint ArrayStore required before running joined heat')\n",
        "    HEAT_LEDGER.require_candidate(store, owner, cancel=cancel)\n")
    for obj, budget in (('result', 'call._budget'), ('value._result', 'owner._budget'), ('view', 'budget')):
        source = _replace(source,
            'with R.decoded('+obj+'._snapshot._metadata, budget='+budget+', cancel=cancel) as decoded:',
            'with HEAT_COLD.ledger_access('+obj+'._snapshot, budget='+budget+
            ', cancel=cancel, resources=R) as decoded:')
    source = _replace(source, 'sha256(view._snapshot._metadata).hexdigest()',
                      'HEAT_LEDGER.metadata_sha256(view._snapshot)')
    return source
