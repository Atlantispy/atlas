"""WP7 H-a: exact r13 packaging from the unchanged numerical heat producer.

Apply after the indexed issuer/projection transforms. The r12 logical method
and schema strings remain part of the old scientific identity; the generated
r13 module and source binding identify the packaging revision. No scope is
created here. WP8 supplies the existing owner's retained scope.
"""
from hashlib import sha256
import sys
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from atlas_tectonics._private.codecs.content_cache import RetainedScope

def required_scope(origins, budget, *, fixture=False, supplied=None):
    """Bind the one existing owner scope; only explicit fixtures may supply it."""
    scope = supplied if fixture else getattr(origins[0], '_record_scope', None)
    return cast('RetainedScope', scope)


def verify_scope(call):
    scope = required_scope(call._origin_objects, call._budget,
        fixture=call._fixture, supplied=call._record_scope if call._fixture else None)
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
    from atlas_tectonics._private.codecs.content_cache import ChargeSpec
    from atlas_tectonics._private.codecs.record_tables import StreamingRows
    from atlas_tectonics._exact_runtime import selected
    def rows():
        selected.library()
        for value in values:
            check()
            # GMP getters copy an integer part. sys.getsizeof(mpq) covers both
            # allocated parts without a copy, so it funds the one-at-a-time
            # copies that measure the exact bit lengths.
            probe = 4096+sys.getsizeof(value)
            with scope.reserve(ChargeSpec('heat-ledger-exact-row-width', probe)):
                bits = (value.numerator.bit_length(), value.denominator.bit_length())
            parts = tuple(map(row_part_bytes, bits))
            size = ROW_FIXED_BYTES+parts[0][0]+parts[1][0]
            work = 4096+max(parts[0][1], parts[1][1])
            with scope.reserve(ChargeSpec('heat-ledger-exact-row', size)) as reservation:
                with scope.reserve(ChargeSpec('heat-ledger-exact-row-conversion', work)):
                    row = [hex(int(value.numerator)), hex(int(value.denominator))]
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
    from atlas_tectonics._private.codecs.heat_ledger_tables import CompactHeatSnapshot, _ordered_mesh_binding
    from atlas_tectonics._private.codecs.content_cache import ChargeSpec
    from atlas_tectonics._private import private_heat_issuer_resources_r4 as resources
    from atlas_tectonics._private.integration.geometry import live_spatial_patch as live
    scope = verify_scope(call)
    # Legacy json.dumps serialises the projection policy's tuple values as
    # arrays. Normalise only containers, never encode the complete metadata.
    # Rational body rows remain explicit StreamingRows throughout this walk.
    check = lambda: resources.check(cancel)
    size = 65536+live.normalisation_capacity(record, check)
    with scope.reserve(ChargeSpec('heat-ledger-header-assembly', size)) as reservation:
        owner = reservation.commit(live.normalise_containers(record, check))
    mesh = getattr(call._geometry, '_indexed', None)
    # Fresh geometry has no authenticated persisted ID source yet. Keep its
    # exact IDs in this ledger so the completed heat result is checkpointable;
    # already persisted geometry retains the existing shared-column path.
    if mesh is not None and getattr(mesh, '_segment', None) is None:
        _ordered_mesh_binding(owner.value, mesh)
        mesh = None
    with owner:
        return CompactHeatSnapshot.from_components(owner.value, fields, scope=scope,
            check=lambda: resources.check(cancel), mesh=mesh)


def snapshot_identity(snapshot, budget, cancel=None):
    from atlas_tectonics._private import private_heat_issuer_resources_r4 as resources
    resources.check(cancel)
    return snapshot.verify_identity(check=lambda: resources.check(cancel))


def plan_id(snapshot):
    with snapshot.ledger as root, root.field('plan_id') as field, field.scalar(max_owned_bytes=16384) as value:
        return value.value


def seal_token(snapshot):
    from atlas_tectonics._private.codecs.heat_ledger_tables import CompactHeatSnapshot
    return snapshot._record if type(snapshot) is CompactHeatSnapshot else snapshot._metadata


def metadata_sha256(snapshot):
    from atlas_tectonics._private.codecs.heat_ledger_tables import CompactHeatSnapshot
    if type(snapshot) is CompactHeatSnapshot:
        return snapshot.metadata_identity.sha256
    return sha256(snapshot._metadata).hexdigest()


def require_candidate(store, owner, *, cancel=None):
    """Refuse an unusable checkpoint writer before the genuine solve starts."""
    from atlas_tectonics._private.codecs.interval_store_set import UnlistedCandidate
    from atlas_tectonics._private import private_heat_issuer_resources_r4 as resources
    resources.check(cancel)
    required_scope((owner,), owner._budget)
    # The runner owns a stable facade across sealed intervals. Unwrap only its
    # actual current candidate; an arbitrary proxy cannot acquire this route.
    # The optional facade is absent from earlier compact-source inventories.
    # This name only gates discovery; its predicate below still admits exactly
    # the concrete facade class, never a proxy or subclass.
    if type(store) is not UnlistedCandidate and type(store).__module__ == 'atlas_tectonics._private.codecs.compact_restart_store':
        facade_module = sys.modules.get('atlas_tectonics._private.codecs.compact_restart_store')
        if facade_module is not None and facade_module.is_compact_restart_store(store):
            store = store.candidate
    store.stores._live()
    store._writing()
    resources.check(cancel)
    return store
