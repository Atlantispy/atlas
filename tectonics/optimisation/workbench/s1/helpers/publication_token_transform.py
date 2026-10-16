"""R2 option A, condition (i): WP-owned source transform of the composed workflow.

Applied at composition time to the text of atlas_tectonics/integration_regional_workflow.py
as one more authenticated stage after partition_workflow_transform.transform (RC1 output
b8175261...). I/ and RC1 files are never edited; this returns new text only.

Revision 2 (16 Oct 2026): transform() accepts ONLY the pinned RC1 text. The native
reference I text is no longer a production predecessor; the tests exercise the same seams
on it through their own test-only entry point (test_bounded_preseal.native_seam_transform).

Three seams, all on CollarWorkflow:
1. _publish's publication_check closure records store.change_token() INSIDE the writer
   transaction (it runs after the rows are inserted and before COMMIT / RELEASE).
2. After store.put returns, _publish adopts that in-transaction token only when exactly one
   was captured, it equals the token read after commit, the persisted head metadata hashes
   to the produced row (canonical JSON, the module's own _hash), and the token is still
   unchanged after that metadata read. The adopted head is the PERSISTED metadata (what a
   full _refresh would have set), so the next interval's parent comparison is unchanged.
   Otherwise the token stays None, exactly as today, and the next inspect() runs the full
   _refresh (slower, never weaker). No token is ever set after the fact.
3. A generated method _r2_metadata_chain(): the metadata-only chain loop of _refresh, copied
   verbatim from this same source text (root check, migrated-root/base checks, and every
   successor link/clock/audit/exterior/differential check), returning the head row. It reads
   no payload. The bounded pre-seal check calls it so the metadata link checks that the full
   _refresh used to run before the seal still run before the seal (gap G1 in DESIGN.md).
"""
from hashlib import sha256

# The one reviewed predecessor: the RC1 composition output after
# partition_workflow_transform.transform (assemble_resumable.py pin
# '...integration_regional_workflow.py@partition_workflow_transform.transform').
PREDECESSOR = 'b81752611b3860b26666467227582c3decee1ef7a1e91e5977ea6b04133542f9'

MARKER = '    def _r2_metadata_chain(self):\n'

REFRESH_ANCHOR = (
    '    def _refresh(self):\n'
    '        self._verify()\n'
    '        token = self._store.change_token()\n'
    '        if token == self._token:\n'
    '            return\n'
    '        root = json.loads(self._root)\n'
    "        if self._store.metadata(root['key']) != root:\n"
    "            raise RegionalOwnerRefused('funded collar root changed')\n")
SLICE_START = '        root = json.loads(self._root)\n'
SLICE_END = '            accepted_parent, previous = previous, current\n'

CHECK_OLD = (
    '        def check():\n'
    '            self._verify()\n'
    '            root = json.loads(self._root)\n'
    "            if self._store.metadata(parent['key']) != parent or self._store.metadata(root['key']) != root:\n"
    "                raise StoreConflict('funded collar parent/admission changed before publication')\n")
CHECK_NEW = (
    '        _r2_tokens = []\n'
    '\n'
    '        def check():\n'
    '            self._verify()\n'
    '            root = json.loads(self._root)\n'
    "            if self._store.metadata(parent['key']) != parent or self._store.metadata(root['key']) != root:\n"
    "                raise StoreConflict('funded collar parent/admission changed before publication')\n"
    '            # R2: the change token this writer produced, read inside its own transaction.\n'
    '            _r2_tokens.append(self._store.change_token())\n')

ADOPT_OLD = '        self._head, self._state, self._token = row, result.state, None\n'
ADOPT_NEW = (
    '        # R2: adopt only the in-transaction token, and only when no write intervened\n'
    '        # after commit; the adopted head is the persisted metadata. Otherwise None.\n'
    '        _r2_after = self._store.change_token()\n'
    '        _r2_head = None\n'
    '        if len(_r2_tokens) == 1 and _r2_tokens[0] == _r2_after:\n'
    "            _r2_head = self._store.metadata(row['key'])\n"
    '            if (_r2_head is None or _hash(_r2_head) != _hash(row) or\n'
    '                    self._store.change_token() != _r2_after):\n'
    '                _r2_head = None\n'
    "        self._published_identity = dict(key=row['key'], sha256=_hash(row),\n"
    '                                        token_adopted=_r2_head is not None)\n'
    '        if _r2_head is None:\n'
    '            self._head, self._state, self._token = row, result.state, None\n'
    '        else:\n'
    '            self._head, self._state, self._token = _r2_head, result.state, _r2_tokens[0]\n'
    '            # Mirror the full _refresh post-state for a successor head.\n'
    '            self._initial_current_geometry = None\n')


class TransformRefused(ValueError):
    pass


def _replace(source, old, new):
    if source.count(old) != 1:
        raise TransformRefused('R2 publication seam missing or ambiguous: ' + old[:80])
    return source.replace(old, new, 1)


def chain_slice(source):
    """The exact metadata-only chain text of CollarWorkflow._refresh (8-space body)."""
    if source.count(REFRESH_ANCHOR) != 1:
        raise TransformRefused('CollarWorkflow._refresh anchor missing or ambiguous')
    begin = source.index(REFRESH_ANCHOR)
    start = begin + REFRESH_ANCHOR.index(SLICE_START)
    if source.count(SLICE_END) != 1 or source.index(SLICE_END) < start:
        raise TransformRefused('chain-loop end anchor missing, ambiguous or misplaced')
    stop = source.index(SLICE_END) + len(SLICE_END)
    return begin, source[start:stop]


def apply_seams(source):
    """All three seams on any text carrying the exact anchors; unauthenticated, so used
    only by transform() below and by tests (fixture model, native I seam check)."""
    if type(source) is not str or MARKER in source or '_r2_tokens' in source:
        raise TransformRefused('R2 transform requires unapplied source text')
    begin, body = chain_slice(source)
    method = (MARKER +
              '        """R2 (WP-owned): _refresh\'s metadata-only chain loop, verbatim; no payload read."""\n'
              '        self._verify()\n' + body +
              '        return previous\n\n')
    source = source[:begin] + method + source[begin:]
    source = _replace(source, CHECK_OLD, CHECK_NEW)
    return _replace(source, ADOPT_OLD, ADOPT_NEW)


def transform(source):
    """Authenticated stage: the pinned RC1 text in, compiled text out; nothing else."""
    if type(source) is not str:
        raise TransformRefused('source text required')
    digest = sha256(source.encode('utf8')).hexdigest()
    if digest != PREDECESSOR:
        raise TransformRefused('workflow source differs from the reviewed R2 predecessor (RC1): ' + digest)
    result = apply_seams(source)
    compile(result, 'integration_regional_workflow.py', 'exec')
    return result
