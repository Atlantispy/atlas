"""R3 (coordinator decision, binding option): keep the workflow's store token current
across ITS OWN heat checkpoint save. WP-owned source transform of the composed workflow.

Finding X1 (Steps 8-9 audit, 16 Oct 2026): _publish -> _validate_differential_solution ->
current_geometry -> _refresh() runs a FULL parent restore before every put, because the
private heat step's checkpoint save (advance_spatial, checkpoint_store=self._store) wrote
into the interval candidate and so changed the store token. In interval 1 that restore is
the root's (route (1): the fresh kind 'root' Workflow.create wrote; the migrated route:
restore_migrated_root); from interval 2 on, the full cold restore of the previous successor.

Chain (coordinator-accepted Step 10 chain, 16 Oct 2026; revision 2 is a re-pin only, the
seam text is unchanged): partition_workflow_transform.transform -> transform_v2 ->
spatial_workflow_patch.transform_v3 -> spatial_records_patch.transform ->
spatial_validation_patch.workflow_source -> compact_restart_patch.workflow_source ->
publication_token_transform (R2) -> this stage (R3) -> publish_mesh_patch. It accepts
exactly one input text, R2's pinned output, and must produce exactly OUTPUT. I/ and RC1
files are never edited; this returns new text only. R3 calls R2's generated
_r2_metadata_chain(), so R2 must precede it.

The compact interval candidate is one SQLite writer transaction for the whole interval
(BEGIN IMMEDIATE at creation, COMMIT only at seal), so no other connection can write it,
and the heat save has no commit of its own: the token the save produced is the token at
the end of its last insert, read before anything else runs. Two seams on CollarWorkflow:

1. advance_spatial, private heat branch: _r3_write_mark() before the heat call records the
   workflow's token (only if it is current and the store is a compact restart facade with
   a writing candidate), the candidate's insert counters and its last chunk/manifest rowids;
   _r3_after_heat_checkpoint(heat, mark) after it.
2. Generated methods (inserted before _publish). The token read after the save is adopted
   only when ALL hold, else nothing is set and the stale token makes the next _refresh()
   run in full, exactly as today (no token is ever set for a write the workflow did not
   make):
   - the workflow token still equals the mark, same candidate, same catalog digest/file
     token, same interval;
   - the candidate's change count rose by exactly the rows it counted as inserted
     (put_chunk / put_manifest are append-only and immutable; an UPDATE, DELETE, rolled-back
     savepoint or raw write breaks the equality);
   - every manifest inserted since the mark is an index page stored under its own
     content-derived page key, or one of the heat checkpoint's own two segment roots stored
     under its derived root key (another put, a raw sidecar, a mesh/partition publish, any
     other root, or any row under a chosen key such as a restart alias the restore reads by
     key, refuses), and the chunk rows inserted since the mark match the counter;
   - the heat receipt is self-consistent (its invocation is the canonical hash of its
     metadata, compact r4 schema), its ledger and field roots are in this interval, and each
     persisted root manifest (verified by the candidate's native manifest validator) binds
     exactly the reference the save returned;
   - the metadata chain from the root, re-run by R2's _r2_metadata_chain() (every link,
     clock, audit, exterior and differential check of _refresh), still ends at this
     workflow's head (so the head has no successor and every chain node is unchanged);
   - the token re-read after these reads is unchanged.
   Any KeyError/ValueError/TypeError/AttributeError/sqlite3.Error during the checks is a
   fall-back, never a new refusal. The outcome is kept in self._r3_heat_checkpoint.

Final revision (16 Oct 2026, fixes/r3/final/DESIGN-r3-final.md): the manifest-row check
binds each accepted row's key to its content with segment_store's own key derivations
(an index page's key is h('atlas.binding-page-key.v1', {digest: h(PAGE_SCHEMA, page)}), a
segment root's key is h(ROOT_SCHEMA, {identity, producer, representation_profile})), so
no row under a chosen key, such as a derived restart alias that today's full restore reads
candidate-first, can pass; and the generated code uses dict literals.
"""
import ast
from hashlib import sha256

# R2 rev4 output on the Step 10 chain (RC1 -> v2 -> transform_v3 -> records -> validation
# -> compact_restart_patch -> R2 rev4).
PREDECESSOR = '4ef1894f29aa992ac3c89a0f3f04ddf8021d494b37a9cb3dcb3c463d9cb00538'
# Revision 2 output (the final seams on the Step 10 chain); 507942b2 (R3 final on the
# superseded D2 chain) and the build's 0bb64ded are superseded.
OUTPUT = '7914531e1118c31b2a11dd24b5087fa76a4a1aa726078866d074e9a95e079dc5'

R2_MARKER = '    def _r2_metadata_chain(self):\n'
MARKER = '    def _r3_write_mark(self):\n'
PUBLISH_ANCHOR = '    def _publish(self, parent, result, exterior_advance, *, differential_interval=None,\n'
HEAT_OLD = (
    '        if private_heat:\n'
    '            heat = self._exterior_owner.heat(step, mesh, boundary=heat_boundary, cancel=cancel,\n'
    '                execution=heat_execution, absolute_residual_target=absolute_heat_residual_target,\n'
    '                checkpoint_store=self._store)\n')
HEAT_NEW = (
    '        if private_heat:\n'
    '            # R3: where this workflow\'s own heat checkpoint save starts (None: today\'s path).\n'
    '            _r3_mark = self._r3_write_mark()\n'
    '            heat = self._exterior_owner.heat(step, mesh, boundary=heat_boundary, cancel=cancel,\n'
    '                execution=heat_execution, absolute_residual_target=absolute_heat_residual_target,\n'
    '                checkpoint_store=self._store)\n'
    '            self._r3_after_heat_checkpoint(heat, _r3_mark)\n')
METHODS = '''    def _r3_write_mark(self):
        """R3 (WP-owned): where this workflow's own next store write starts, or None.

        Only a compact restart facade with a writing interval candidate, and only while
        this workflow's token is current; anything else keeps today's behaviour."""
        import sqlite3
        import sys
        try:
            from interval_store_set import UnlistedCandidate
            facade = sys.modules.get('compact_restart_store')
            candidate = getattr(self._store, 'candidate', None)
            if (self._token is None or facade is None or not facade.is_compact_restart_store(self._store) or
                    type(candidate) is not UnlistedCandidate):
                return None
            token = self._store.change_token()
            if token != self._token:
                return None
            with candidate._lock:
                chunks = candidate._db.execute('SELECT max(rowid) FROM chunks').fetchone()[0] or 0
                manifests = candidate._db.execute('SELECT max(rowid) FROM snapshots').fetchone()[0] or 0
            return {'token': token, 'candidate': candidate, 'stats': candidate.local_statistics(),
                    'chunks': chunks, 'manifests': manifests}
        except (KeyError, ValueError, TypeError, AttributeError, sqlite3.Error):
            return None

    def _r3_heat_checkpoint_reason(self, heat, mark):
        """R3: why the token this workflow's own heat checkpoint save produced cannot be
        kept, or None. Reads tokens, counters, the kinds of the rows inserted since the
        mark and two root manifests; decodes no payload and reads no record."""
        import segment_store
        from compact_contracts import SEGMENT_MANIFEST_BYTES, SegmentRef
        candidate, before = mark['candidate'], mark['token']
        after = self._store.change_token()
        if self._token != before or self._store.candidate is not candidate:
            return 'workflow token or candidate changed during the heat step', after, None
        if after[:2] != before[:2] or after[2][0] != before[2][0]:
            return 'catalog or interval changed during the heat step', after, None
        stats = candidate.local_statistics()
        rows = {'chunks': stats['local_chunks'] - mark['stats']['local_chunks'],
                'manifests': stats['manifests'] - mark['stats']['manifests'],
                'changes': after[2][1] - before[2][1]}
        if rows['changes'] != rows['chunks'] + rows['manifests']:
            return 'store changes not counted as inserted rows', after, rows
        receipt = heat.reference()['checkpoint']
        meta = receipt['metadata']
        if (type(receipt) is not dict or set(receipt) != {'invocation', 'metadata'} or type(meta) is not dict or
                meta.get('schema') != 'atlas.private.exact-snapshot-compact-store.r4' or
                _hash(meta) != receipt['invocation']):
            return 'heat checkpoint receipt is not the compact record it names', after, rows
        roots = {}
        for name in ('ledger', 'field_payload'):
            locator = SegmentRef.from_wire(meta[name]).root_key
            if locator.workflow_id != candidate.workflow_id or locator.interval != candidate.interval:
                return 'heat checkpoint root is not in this interval', after, rows
            roots[locator.snapshot_key] = (locator, meta[name])
        with self._store._workspace(4*SEGMENT_MANIFEST_BYTES+(1 << 20), self._budget,
                                    category='r3-heat-token-check'):
            with candidate._lock:
                if candidate._db.execute('SELECT count(*) FROM chunks WHERE rowid>?',
                                         (mark['chunks'],)).fetchone()[0] != rows['chunks']:
                    return 'chunk rows inserted since the mark differ from the counter', after, rows
                cursor = candidate._db.execute('SELECT id,body FROM snapshots WHERE rowid>? ORDER BY rowid',
                                               (mark['manifests'],))
                try:
                    seen = 0
                    for key, body in cursor:
                        seen += 1
                        if len(body) > SEGMENT_MANIFEST_BYTES:
                            return 'oversized manifest inserted during the heat step', after, rows
                        metadata = json.loads(body)['metadata']
                        del body
                        # A row is the save's own only under the key segment_store derives
                        # from its content (_IndexBuilder._page; SegmentBackend.publish), never
                        # under a chosen key such as a restart alias read candidate-first.
                        kind = metadata.get('schema')
                        if kind == segment_store.PAGE_SCHEMA:
                            derived = segment_store.h('atlas.binding-page-key.v1',
                                                      {'digest': segment_store.h(segment_store.PAGE_SCHEMA, metadata)})
                        elif kind == segment_store.ROOT_SCHEMA and key in roots:
                            derived = segment_store.h(segment_store.ROOT_SCHEMA, {
                                name: metadata[name] for name in ('identity', 'producer', 'representation_profile')})
                        else:
                            derived = None
                        del metadata
                        if key != derived:
                            return 'a write other than the heat checkpoint intervened', after, rows
                finally:
                    cursor.close()
            if seen != rows['manifests']:
                return 'manifests inserted since the mark differ from the counter', after, rows
            for locator, wire in roots.values():
                with candidate.resolve_manifest(locator) as held:
                    bound = json.loads(held.value)['metadata']
                if (type(bound) is not dict or bound.get('schema') != 'atlas.segment-root.v1' or
                        _json(bound.get('reference')) != _json(wire)):
                    return 'persisted heat checkpoint root differs from the produced reference', after, rows
                del bound
        if self._r2_metadata_chain() != self._head:
            return 'workflow chain changed during the heat step', after, rows
        if self._store.change_token() != after:
            return 'store changed during the R3 checks', after, rows
        return None, after, rows

    def _r3_after_heat_checkpoint(self, heat, mark):
        """R3 (WP-owned): keep the token across this workflow's OWN heat checkpoint save.

        Adopted only when _r3_heat_checkpoint_reason finds nothing; otherwise nothing is
        set and the next _refresh() runs in full, exactly as today."""
        import sqlite3
        reason, rows = 'workflow not current on a compact candidate before the save', None
        if mark is not None:
            try:
                reason, after, rows = self._r3_heat_checkpoint_reason(heat, mark)
            except (KeyError, ValueError, TypeError, AttributeError, sqlite3.Error) as error:
                reason = 'check refused: ' + type(error).__name__
            if reason is None:
                self._token = after
        self._r3_heat_checkpoint = {'token_kept': reason is None, 'reason': reason, 'rows': rows}

'''
CHANGED = frozenset(('CollarWorkflow.advance_spatial',))
ADDED = frozenset(('CollarWorkflow._r3_write_mark', 'CollarWorkflow._r3_heat_checkpoint_reason',
                   'CollarWorkflow._r3_after_heat_checkpoint'))


class TransformRefused(ValueError):
    pass


def _require(ok, message):
    if not ok:
        raise TransformRefused(message)


def _once(source, old, new):
    # Line-start anchoring: the anchor must not match as the tail of a longer line.
    _require(source.count(old) == 1 and source.count('\n' + old) == 1,
             'R3 seam missing or ambiguous: ' + old.strip()[:80])
    return source.replace(old, new, 1)


def functions(tree):
    """Qualified function name -> AST dump; duplicate qualified names refused."""
    result = {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if not isinstance(child, ast.ClassDef):
                    _require(name not in result, 'ambiguous qualified function name: ' + name)
                    result[name] = ast.dump(child, include_attributes=False)
                visit(child, name + '.')
            else:
                visit(child, prefix)
    visit(tree, '')
    return result


def _skeleton(tree, names):
    """Dump with the named functions removed (changed or added ones)."""
    def visit(node, prefix):
        keep = []
        for child in getattr(node, 'body', []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and prefix + child.name in names:
                continue
            if isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + '.')
            keep.append(child)
        if hasattr(node, 'body'):
            node.body = keep
    visit(tree, '')
    return ast.dump(tree, include_attributes=False)


def apply_seams(source):
    """Both seams on any text carrying the exact anchors and R2's generated chain method;
    unauthenticated, so used only by transform() below and by tests."""
    _require(type(source) is str and MARKER not in source and '_r3_' not in source,
             'R3 transform requires unapplied source text')
    _require(source.count(R2_MARKER) == 1, 'R3 requires the R2 stage (_r2_metadata_chain) before it')
    try:
        before = ast.parse(source)
    except SyntaxError as error:
        raise TransformRefused('R3 input does not parse') from error
    result = _once(source, PUBLISH_ANCHOR, METHODS + PUBLISH_ANCHOR)
    result = _once(result, HEAT_OLD, HEAT_NEW)
    try:
        after = ast.parse(result)
    except SyntaxError as error:
        raise TransformRefused('R3 output does not parse') from error
    a, b = functions(before), functions(after)
    owner = {name.rsplit('.', 1)[0] for name in ADDED}
    _require(len(owner) == 1 and all(name.rsplit('.', 1)[0] in owner for name in CHANGED) and
             set(b) - set(a) == ADDED and set(a) - set(b) == set() and
             {n for n in a if a[n] != b[n]} == CHANGED,
             'R3 seams changed functions outside the reviewed set')
    _require(_skeleton(before, CHANGED) == _skeleton(after, CHANGED | ADDED),
             'R3 seams changed statements outside the reviewed functions')
    return result


def transform(source):
    """Authenticated stage: R2's pinned output in, the pinned R3 output out; nothing else."""
    _require(type(source) is str, 'source text required')
    digest = sha256(source.encode('utf8')).hexdigest()
    _require(digest == PREDECESSOR, 'workflow source differs from the reviewed R3 predecessor (R2 output): ' + digest)
    result = apply_seams(source)
    compile(result, 'integration_regional_workflow.py', 'exec')
    _require(sha256(result.encode('utf8')).hexdigest() == OUTPUT, 'R3 seams produced unreviewed output')
    return result
