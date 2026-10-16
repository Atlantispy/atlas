"""WP10 source-bound adapters for the existing segment/interval components.

Return candidate source only. WP9 owns applying these transforms to a new
composition; this module never edits the shared components or frozen runtime.
Array names select policy but never enter decoded-content identities. Existing
chunks are authenticated and reused before encoding, as in the original code.
"""
from __future__ import annotations

import hashlib


# Re-pinned 16 Oct 2026 to the R1-batch storage generation (live 8888fcaa + the closing
# identity check's unverified-stat wording): every interval_source anchor occurs exactly
# once in this source and the result compiles.
INTERVAL_SHA256 = '699ae4438c7ab05e71994d30533096eb2d404d74315637c08181ea94536b1af7'
SEGMENT_SHA256 = 'ebaa2c3d513dfb7979af7a840adf04be9defa0e9a640350dd838e134e10f5a54'
# Step 7 added verified read/cache ownership while WP10 was in progress. The
# publish/put_chunk boundary was reread; no shared source is changed here.
SEGMENT_REVIEWED_SUCCESSOR = 'bed80cb700c439fffa3e0ac9ea209a3e098831d4bc4ece26043d50c4c4101ea5'
# Step 7b adds SegmentBlock and a sealed scan() only. The exact diff against
# its retained bed80 baseline leaves this publish/put_chunk transform unchanged.
SEGMENT_REVIEWED_SCAN_SUCCESSOR = 'db0aa9abb76dced45d5e1f78f0c810ab5bc14d579d02f99645d7758f97088386'
# The live storage generation (wave 2 + S1 read batching): the put_chunk call this
# transform rewrites is unchanged; its anchor occurs exactly once.
SEGMENT_REVIEWED_STORAGE_GEN = '1f503604cbe76e39c80ae2260a2e485d70c2ee047326488aa8d2baa620cde53a'
# B17 (backlog item 17, 16 Oct 2026): the per-view binding directory changes only the
# view's named lookups (SegmentView); publish/put_chunk is untouched, so the anchor
# this transform rewrites still occurs exactly once.
SEGMENT_REVIEWED_B17 = 'a90ef8f3e519ee77ea4332380428ce2694c16134ec69603ccaf93ce95cea6cd9'


def _require_source(source, expected):
    if type(source) is not str or hashlib.sha256(source.encode('utf-8')).hexdigest() != expected:
        raise ValueError('WP10 component source differs from the reviewed input')


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('WP10 component anchor is missing or ambiguous')
    return source.replace(old, new, 1)


def interval_source(source):
    """Thread an immutable, explicitly selected policy into an unlisted writer.

    Validation precedes file creation. Sealed readers need no policy: the stored
    label fully determines lossless decoding. No old file is recompressed.
    The candidate's chunk encode, verification decode and own-chunk decode run
    inside the writer's existing codec reservation (caller_funded), never booked
    on the run budget twice. So does a sealed interval's chunk decode
    (IntervalStoreSet.resolve_chunk), on its reader's own codec ledger.
    """
    _require_source(source, INTERVAL_SHA256)
    source = _replace(source,
        '    def begin_interval(self, parent, *, producer_identity, runtime_identity, cancel=None):\n',
        '    def configure_codec_backend(self, backend):\n'
        '        from storage_codec_runtime import validate_backend\n'
        '        backend = validate_backend(backend)\n'
        '        with self._lock:\n'
        '            self._live()\n'
        '            if hasattr(self, "_codec_backend") or self._candidate is not None:\n'
        '                raise ContractError("codec backend must be configured once before writing")\n'
        '            for owner in self._handles.values():\n'
        '                owner.assert_unborrowed()\n'
        '            self._codec_backend = backend\n'
        '            for owner in self._handles.values():\n'
        '                owner.value._codec_backend = backend\n'
        '\n'
        '    @_serial\n'
        '    def begin_interval(self, parent, *, producer_identity, runtime_identity, cancel=None):\n')
    source = _replace(source,
        '                reader = ReadOnlyNative(path, scope=self.scope)\n',
        '                reader = ReadOnlyNative(path, scope=self.scope)\n'
        '                reader._codec_backend = getattr(self, "_codec_backend", None)\n')
    source = _replace(source,
        '            reader = ReadOnlyNative(self.path, scope=self.scope, require_immutable=False)\n',
        '            reader = ReadOnlyNative(self.path, scope=self.scope, require_immutable=False)\n'
        '            reader._codec_backend = getattr(self, "_codec_backend", None)\n')
    source = _replace(source,
        '    def begin_interval(self, parent, *, producer_identity, runtime_identity, cancel=None):\n',
        '    def begin_interval(self, parent, *, producer_identity, runtime_identity, cancel=None, codec_policy=None):\n')
    source = _replace(source,
        '        candidate = UnlistedCandidate(self, producer_identity, runtime_identity, cancel=cancel)\n',
        '        candidate = UnlistedCandidate(self, producer_identity, runtime_identity,\n'
        '                                      cancel=cancel, codec_policy=codec_policy)\n')
    source = _replace(source,
        '    def __init__(self, stores, producer_identity, runtime_identity, *, cancel=None):\n',
        '    def __init__(self, stores, producer_identity, runtime_identity, *, cancel=None, codec_policy=None):\n')
    source = _replace(source,
        '        self.compression = native.Compression()\n',
        '        self.compression = native.Compression()\n'
        '        self._codec_backend = getattr(stores, "_codec_backend", None)\n'
        '        if codec_policy is not None:\n'
        '            from storage_codec_runtime import normalise_policy\n'
        '            self._codec_policy = normalise_policy(codec_policy)\n')
    source = _replace(source,
        '    def put_chunk(self, descriptor, raw, *, cancel=None):\n',
        '    def put_chunk(self, descriptor, raw, *, cancel=None, array_name=None):\n')
    source = _replace(source,
        '        owner = self._find_chunk_location(key, descriptor, cancel=cancel)\n'
        '        if owner is not None:\n',
        '        owner = self._find_chunk_location(key, descriptor, cancel=cancel)\n'
        '        if owner is not None:\n'
        '            if array_name == "__wp10_dictionary__":\n'
        '                database = self._db if owner == self.interval else self.stores._handle(owner, cancel=cancel).value._db\n'
        '                stored_codec = database.execute("SELECT codec FROM chunks WHERE id=?", (key,)).fetchone()\n'
        '                if stored_codec != ("raw",):\n'
        '                    raise ContractError("dictionary bootstrap requires an existing raw chunk")\n')
    # put_chunk reserves codec_workspace_bytes + 32 chunks on the run budget around
    # its encode and verification decode, and the candidate's own chunk decode
    # (reached by put_chunk for a chunk it already holds) reserves
    # codec_workspace_bytes + 8 chunks. WP10 books that work on the candidate's
    # codec ledger only, so the run budget carries exactly those reservations.
    source = _replace(source,
        '            codec, payload = native.ArrayStore._encode(self, raw, dt)\n'
        "            if native.ArrayStore._decode(self, codec, payload, dt, meta['count']) != raw:\n",
        '            from storage_codec_runtime import caller_funded\n'
        '            with caller_funded(self):\n'
        '                codec, payload = native.ArrayStore._encode(self, raw, dt, array_name=array_name)\n'
        "                verified = native.ArrayStore._decode(self, codec, payload, dt, meta['count']) == raw\n"
        '            if not verified:\n')
    source = _replace(source,
        "            raw = native.ArrayStore._decode(self, codec, payload, dt, meta['count'])\n"
        '            if native.ArrayStore._blob_id(self, descriptor, raw) != chunk_id:\n',
        '            from storage_codec_runtime import caller_funded\n'
        '            with caller_funded(self):\n'
        "                raw = native.ArrayStore._decode(self, codec, payload, dt, meta['count'])\n"
        '            if native.ArrayStore._blob_id(self, descriptor, raw) != chunk_id:\n')
    # A sealed interval's chunk decode: resolve_chunk reserves codec_workspace_bytes + 8
    # chunks on the run budget ('interval-chunk-decode') around the reader's decode
    # (ReadOnlyNative.chunk decodes on the reader itself). Inside, WP10 books on that
    # reader's codec ledger only, as for the candidate's own-chunk decode above.
    source = _replace(source,
        '        with _workspace(self.scope.run_budget, LIMITS.codec_workspace_bytes + 8 * NATIVE_CHUNK_BYTES,\n'
        "                        'interval-chunk-decode'):\n",
        '        from storage_codec_runtime import caller_funded\n'
        '        with _workspace(self.scope.run_budget, LIMITS.codec_workspace_bytes + 8 * NATIVE_CHUNK_BYTES,\n'
        "                        'interval-chunk-decode'), caller_funded(handle.value):\n")
    compile(source, '<wp10-interval-candidate>', 'exec')
    return source


def segment_source(source):
    """Pass schema-qualified compact stream names through the bounded chunk writer.

    The policy key is '<record_schema>/<column>': records share column names
    (partition v2 and the heat ledger both have node.kind), so a bare name
    could not tell a hot partition column from a cold ledger column. The schema
    is read from identity.record_schema, which publish() requires to equal its
    record_schema argument and which stays in scope after the storage generation
    moved the chunk loop into _publish_arrays.
    """
    if type(source) is not str or hashlib.sha256(source.encode('utf-8')).hexdigest() not in (
            SEGMENT_SHA256, SEGMENT_REVIEWED_SUCCESSOR, SEGMENT_REVIEWED_SCAN_SUCCESSOR,
            SEGMENT_REVIEWED_STORAGE_GEN, SEGMENT_REVIEWED_B17):
        raise ValueError('WP10 component source differs from the reviewed input')
    source = _replace(source,
        '                owner, chunk_id = candidate.put_chunk(descriptor, raw, cancel=cancel)\n',
        '                owner, chunk_id = candidate.put_chunk(descriptor, raw, cancel=cancel,\n'
        "                                                      array_name=identity.record_schema + '/' + info.name)\n")
    compile(source, '<wp10-segment-candidate>', 'exec')
    return source
