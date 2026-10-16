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


def exact_rows(values, scope, check):
    """Encode one exact kernel rational at a time, funded before hex allocation.

    The unchanged projection workspace owns the exact input list. A failed
    row retains its own charge in the traceback, including after that workspace
    exits. Successful rows are released by RecordCodec before the next row.
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
            # GMP getters may allocate integer parts. The existing projection
            # plan already funds those copies; fund the resulting row before
            # creating Python integers/hex strings, conservatively at 16x.
            size = 4096 + 16*sys.getsizeof(value)
            if size > MAX_ROW_WORK_BYTES:
                raise ContractError('heat rational row exceeds the fixed row workspace')
            with scope.reserve(ChargeSpec('heat-ledger-exact-row', size)) as reservation:
                row = [hex(int(value.numerator)), hex(int(value.denominator))]
                if sum(sys.getsizeof(part) for part in row)+sys.getsizeof(row) > size:
                    raise ArithmeticError('heat rational row exceeded its admitted capacity')
                yield reservation.commit(row)
    return StreamingRows(len(values), rows)


def package_result(record, fields, call, *, cancel=None):
    from heat_ledger_tables import CompactHeatSnapshot
    from content_cache import ChargeSpec
    from compact_contracts import ContractError
    import private_heat_issuer_resources_r4 as resources
    scope = verify_scope(call)
    # Legacy json.dumps serialises the projection policy's tuple values as
    # arrays. Normalise only containers, never encode the complete metadata.
    # Rational body rows remain explicit StreamingRows throughout this walk.
    def capacity(value, depth=0):
        resources.check(cancel)
        if depth > 128:
            raise ContractError('heat metadata container depth exceeds bound')
        if type(value) is dict:
            return 2*sys.getsizeof(value)+sum(capacity(v, depth+1) for v in value.values())
        if type(value) in (list, tuple):
            return 256+16*len(value)+sum(capacity(v, depth+1) for v in value)
        return 0
    def normalise(value):
        if type(value) is dict:
            return {key: normalise(item) for key, item in value.items()}
        if type(value) in (list, tuple):
            return [normalise(item) for item in value]
        return value
    size = 65536+capacity(record)
    if size > 32 << 20:
        raise ContractError('heat metadata header assembly exceeds fixed bound')
    with scope.reserve(ChargeSpec('heat-ledger-header-assembly', size)) as reservation:
        owner = reservation.commit(normalise(record))
    with owner:
        return CompactHeatSnapshot.from_components(owner.value, fields, scope=scope,
            check=lambda: resources.check(cancel), mesh=getattr(call._geometry, '_indexed', None))


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
        from compact_restart_store import is_compact_restart_store
        if is_compact_restart_store(store):
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
        "    'heat_cold_patch', 'spatial_validation_patch', 'segment_store',\n"
        "    'interval_store_set', 'interval_catalog')\n\n\n"
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
