"""Source-bound indexed heat adapters; exact arithmetic and checks are retained.

This is an additive source transformer, not a running-module patch. The actual
issuer still authenticates the owner, transport, execution and fixed numerical
producer. A compact metric is hashed once through bounded canonical streaming,
when its view is sealed, and that process-local seal is reused afterwards;
there is no whole legacy record decode in the numerical/projection route.
"""
from hashlib import sha256


def metric_identity(geometry, *, cancel=None):
    """Return the logical identity: hashed here from an encoding, read from the seal of an indexed view."""
    from atlas_tectonics._private import private_heat_issuer_resources_r4 as R
    R.check(cancel)
    view = getattr(geometry, '_indexed', None)
    if view is None:
        return sha256(geometry._encoded).hexdigest()
    if view.scope is None:
        import numpy as np
        # Unscoped views come only from CompactMesh.__init__, whose tables are views of immutable bytes.
        if any(type(a) is not np.ndarray or a.flags.writeable for a in view._arrays.values()):
            raise ValueError('unscoped indexed geometry tables are not read-only')
    # Every seal site streamed exactly one full logical identity first (mesh_tables CompactMesh.__init__,
    # mesh_from_segment, bind_published). Reuse only that process-local seal, after file/cancel checks.
    identity = view.identity()
    R.check(cancel)
    return identity.sha256


def ordered_cell_ids(geometry, *, cancel=None):
    """One cell identity at a time, retaining the decoded row while borrowed."""
    from atlas_tectonics._private import private_heat_issuer_resources_r4 as R
    view = getattr(geometry, '_indexed', None)
    if view is None:
        with R.decoded(geometry._encoded, budget=geometry._budget, cancel=cancel) as owned:
            for row in owned.value['cells']:
                R.check(cancel)
                yield row['cell_id']
    else:
        for index in range(view.cell_count):
            R.check(cancel)
            owned = view.cell(index)
            yield owned.value['cell_id']


class _Cell:
    __slots__ = ('owner',)

    def __init__(self, owner):
        self.owner = owner

    def __getitem__(self, name):
        return self.owner.value[name]

    def get(self, name, default=None):
        return self.owner.value.get(name, default)


class _Cells:
    __slots__ = ('view',)

    def __init__(self, view):
        self.view = view

    def __len__(self):
        return self.view.cell_count

    def __iter__(self):
        for index in range(len(self)):
            yield _Cell(self.view.cell(index))


class _MeshRows:
    __slots__ = ('mesh', 'header', 'cells')

    def __init__(self, mesh):
        self.mesh, self.header = mesh, mesh.header()
        self.cells = _Cells(mesh._compact)

    def __getitem__(self, name):
        if name == 'cells':
            return self.cells
        return self.header.value[name]

    def get(self, name, default=None):
        if name == 'cells':
            return self.cells
        return self.header.value.get(name, default)


def mesh_rows(mesh):
    """Bounded native consumer view, never JSON-persistable disguised dict."""
    return _MeshRows(mesh) if mesh.is_compact else mesh.record()


def stored_mesh(mesh):
    """The spatial issuer owns compact persistence and logical-ID validation."""
    return mesh._compact if mesh.is_compact else mesh.record()


def spatial_record(state):
    """Retain compact mesh ownership while exporting only the small state body."""
    from atlas_tectonics._private.integration.geometry.spatial_indexed_patch import logical_record
    return logical_record(state)


def compare_spatial_records(test, state, expected):
    """Exact logical comparison, including every geometry byte, without expansion.

    Compact values, the thermal mesh and compact state cells, are compared by
    their exact canonical byte streams in order. A RecordRef borrow has no value
    equality by design, so ``==`` on two borrows of identical cells is False
    (audit D4(i), 16 Oct 2026); every other field keeps ordinary equality.
    """
    from atlas_tectonics._private.codecs.mesh_tables import CompactMesh
    from atlas_tectonics._private.codecs.record_views import RecordRef
    from atlas_tectonics._private.integration import native_transfer as N
    import json
    actual = spatial_record(state)

    def compact(value):
        return type(value) is CompactMesh or isinstance(value, RecordRef)
    streamed = sorted(key for key in set(actual) | set(expected)
                      if compact(actual.get(key)) or compact(expected.get(key)))
    if not streamed:
        test.assertEqual(actual, expected)
        return
    scratch = N._Allocation(state._budget, 65536+128*(len(actual)+len(expected)),
                            category='indexed-reopen-state-comparison')
    test.assertEqual(set(actual), set(expected))
    test.assertEqual({k: v for k, v in actual.items() if k not in streamed},
                     {k: v for k, v in expected.items() if k not in streamed})

    def chunks(value):
        if type(value) is CompactMesh:
            yield from value.iter_legacy_json()
        elif isinstance(value, RecordRef):
            with value.iter_json() as stream:
                for held in stream:
                    with held:
                        yield bytes(held.value)
        else:
            for piece in json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).iterencode(value):
                yield piece.encode()
    # Chunk boundaries need not match (legacy JSON vs compact streams). Compare
    # bounded byte slices in order rather than weakening equality to a hash.
    for key in streamed:
        readers = (iter(chunks(actual[key])), iter(chunks(expected[key])))
        a = b = memoryview(b'')
        while True:
            if not a:
                a = memoryview(next(readers[0], b''))
            if not b:
                b = memoryview(next(readers[1], b''))
            if not a or not b:
                test.assertEqual(bool(a), bool(b), key)
                break
            size = min(len(a), len(b))
            test.assertEqual(a[:size], b[:size], key)
            a, b = a[size:], b[size:]
        del readers, a, b
    _ = scratch
