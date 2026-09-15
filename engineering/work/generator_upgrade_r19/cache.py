"""Thin source-bound coastal reuse over the unchanged authenticated R12 Store.

Native results bind R18/native execution plus this executed adapter, so unrelated
coastal edits do not invalidate them. Coastal results/checkpoints bind all R19
execution and the Water/Physical owner inputs. The R18 ancestry includes R13's
R12 source inventory and executed-module checks; Store is imported BEFORE either
binding is taken. Nothing here changes its authentication, 8 MiB record limit,
256 MiB default total, immutable keys, path safeguards or no-eviction policy.

Sequential single-writer use only. Callers supply complete JSON invocations and
scientific validators; source identity alone does not validate input data or
physics. Runtime/provenance diagnostics remain outside the reused scientific
value. Cache corruption/conflicts fail closed, never become ordinary misses.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import warnings

from work.generator_runtime_r12 import store
from . import provenance as p, owner


SCHEMA = 'diadem.coastal-cache-adapter.r19'
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'c19'
CHUNK_MAX_RECEIPTS = 32
CHUNK_MAX_BYTES = 4 * 1024 * 1024


class CacheWriteSkipped(RuntimeWarning):
    """The result remains valid but no complete cache entry was saved."""


def _json(value):
    store._check_json(value)
    return deepcopy(value)


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise store.CacheError('Invalid coastal cache '+label)


def _digest(value):
    return store._sha(value, 'coastal content hash')


def _chunk_record(receipts):
    return {'schema': SCHEMA+'.receipt_chunk', 'content_sha256': p.sha(receipts),
            'receipts': receipts}


def _chunks(receipts):
    """Stable prefix packing; encode each receipt only once for byte sizing."""
    overhead = len(store._encode({'schema': SCHEMA+'.receipt_chunk',
                                 'content_sha256': '0'*64, 'receipts': []}))
    chunk, size = [], overhead
    for receipt in receipts:
        if type(receipt) is not dict:
            raise ValueError('Checkpoint receipt must be a JSON dictionary')
        try:
            length = len(store._encode(receipt, limit=CHUNK_MAX_BYTES))
            if overhead+length > CHUNK_MAX_BYTES:
                raise store._Oversize('Single coastal receipt exceeds the 4 MiB chunk bound')
        except store._Oversize:
            if chunk:
                yield _chunk_record(chunk)
            raise
        if chunk and (len(chunk) == CHUNK_MAX_RECEIPTS or size+1+length > CHUNK_MAX_BYTES):
            yield _chunk_record(chunk)
            chunk, size = [], overhead
        size += length+bool(chunk)  # Exact comma count in the compact JSON list.
        chunk.append(receipt)
    if chunk:
        yield _chunk_record(chunk)


class CoastalCache:
    """``root`` is a dedicated absolute Path; default is short task ``c19``.

``reuse`` returns (unchanged value, hit). Its validator must raise on rejection
(an explicit False also rejects); the validator receives a defensive copy and
cannot alter the cached scientific value. Any return other than False is ignored.
Oversize/full writes emit CacheWriteSkipped and are also recorded in ``warnings``.
``save_checkpoint`` additionally returns an explicit saved/warning receipt.
"""
    def __init__(self, root=None, component='coastal'):
        if component not in ('coastal', 'native'):
            raise ValueError('CoastalCache component must be coastal or native')
        self.component = component
        self._source_path = Path(__file__).resolve()
        self._source_sha = hashlib.sha256(p.checked(self._source_path)).hexdigest()
        if globals().get('_R12_EXECUTED_SHA256') != self._source_sha:
            raise ValueError('Executed coastal cache adapter differs from current source')
        if component == 'coastal':
            self._binding = {'execution': p.identity(), 'owner': owner.binding()}
        else:
            self._binding = {'execution': p.parent.identity(),
                             'cache_source': {'path': str(self._source_path), 'sha256': self._source_sha}}
        self.namespace = p.sha(self._binding)
        self._warnings = []
        self._verify()
        self._store = store.Store(DEFAULT_ROOT if root is None else root, self.namespace)
        self._verify()

    @property
    def warnings(self):
        return deepcopy(self._warnings)

    @property
    def stats(self):
        return dict(self._store.stats, component=self.component,
                    warnings=len(self._warnings), namespace=self.namespace)

    def _verify(self):
        if (hashlib.sha256(p.checked(self._source_path)).hexdigest() != self._source_sha
                or globals().get('_R12_EXECUTED_SHA256') != self._source_sha):
            raise ValueError('Coastal cache adapter changed; no source repin')
        if self.component == 'coastal':
            p.verify(self._binding['execution'])
            if owner.binding() != self._binding['owner']:
                raise ValueError('Coastal cache owner inputs changed; no repin')
        else:
            p.parent.verify(self._binding['execution'])
        if p.sha(self._binding) != self.namespace:
            raise ValueError('Coastal cache namespace binding changed')

    def _key(self, kind, invocation):
        return p.sha({'schema': SCHEMA, 'kind': kind, 'invocation': invocation})

    def _warning(self, key, reason):
        message = 'R19 cache entry not saved ('+reason+'): '+key
        self._warnings.append({'key': key, 'reason': reason, 'message': message})
        warnings.warn(message, CacheWriteSkipped, stacklevel=3)
        return message

    def _write(self, key, value):
        """Store.put deliberately returns None on skips; authenticate readback."""
        before = self._store.stats
        self._store.put(key, value)
        saved = self._store.get(key)
        if saved is None:
            after = self._store.stats
            reason = ('record exceeds 8 MiB' if after['skipped_oversize'] > before['skipped_oversize']
                      else '256 MiB store full' if after['skipped_full'] > before['skipped_full']
                      else 'record absent after write')
            return self._warning(key, reason)
        if p.encoded(saved) != p.encoded(value):
            raise store.CacheConflictError('Coastal cache readback differs from validated value')
        return None

    @staticmethod
    def _validate(value, validator):
        if not callable(validator):
            raise ValueError('Explicit coastal cache validator required')
        if validator(deepcopy(value)) is False:
            raise ValueError('Coastal cache scientific validator rejected the result')

    def reuse(self, invocation, producer, validator):
        """Validate both hits/misses; compute only a missing complete invocation.

Native validators must freshly check source-data/owner hashes themselves. All
relevant supports, source identities, options, forcing and seeds belong in the
caller-supplied invocation. Original producer timings are retained unchanged.
"""
        invocation = _json(invocation)
        if not callable(producer) or not callable(validator):
            raise ValueError('Explicit producer and validator required')
        self._verify()
        key = self._key('value', invocation)
        record = self._store.get(key)
        if record is not None:
            _exact(record, ('schema', 'invocation', 'value'), 'result record')
            if record['schema'] != SCHEMA+'.value' or p.encoded(record['invocation']) != p.encoded(invocation):
                raise store.CacheError('Coastal cache invocation differs')
            value = record['value']
            self._validate(value, validator)
            self._verify()
            return deepcopy(value), True
        value = _json(producer())
        self._validate(value, validator)
        self._verify()
        self._write(key, {'schema': SCHEMA+'.value', 'invocation': invocation, 'value': value})
        self._verify()
        return deepcopy(value), False

    def _checkpoint(self, checkpoint):
        if self.component != 'coastal':
            raise ValueError('Coastal checkpoints require the coastal component namespace')
        _exact(checkpoint, ('scientific', 'execution', 'scientific_sha256'), 'checkpoint')
        if checkpoint['execution'] != self._binding['execution']:
            raise ValueError('Checkpoint execution differs from coastal cache binding')
        from .driver import CoastalRun
        # Existing source/history/packet/account validation, without physics.
        CoastalRun.restore(deepcopy(checkpoint))

    def save_checkpoint(self, invocation, checkpoint):
        """Publish a thin checkpoint only after ALL receipt chunks read back.

Receipt chunks hold at most 32 receipts and 4 MiB of encoded record content.
Packing is deterministic from the start: completed prefix chunks are reused;
an old final short chunk remains when a later checkpoint extends that chunk.
Oversized single receipts or thin checkpoints remain explicitly unsaved.
Earlier chunks/checkpoints remain intact on any later failure. The
invocation must identify this endpoint/prefix: immutable keys cannot stand for
several different successive states. There is no mutable/latest pointer here.
"""
        invocation, checkpoint = _json(invocation), _json(checkpoint)
        self._verify()
        self._checkpoint(checkpoint)
        scientific = checkpoint['scientific']
        if type(scientific.get('receipts')) is not list:
            raise ValueError('Checkpoint requires an explicit receipt list')
        key = self._key('checkpoint', invocation)
        refs = []
        try:
            for record in _chunks(scientific['receipts']):
                digest = record['content_sha256']
                record_key = self._key('receipt_chunk', digest)
                existing = self._store.get(record_key)
                if existing is not None:
                    if p.encoded(existing) != p.encoded(record):
                        raise store.CacheConflictError('Content-addressed coastal receipt chunk differs')
                else:
                    warning = self._write(record_key, record)
                    if warning is not None:
                        self._verify()
                        return {'saved': False, 'key': key, 'warning': warning}
                refs.append(digest)
        except store._Oversize:
            warning = self._warning(key, 'single receipt exceeds the 4 MiB chunk bound')
            self._verify()
            return {'saved': False, 'key': key, 'warning': warning}
        thin = deepcopy(checkpoint)
        del thin['scientific']['receipts']
        record = {'schema': SCHEMA+'.checkpoint', 'invocation': invocation,
                  'checkpoint': thin, 'receipt_chunk_refs': refs,
                  'receipt_count': len(scientific['receipts']),
                  'complete_checkpoint_sha256': p.sha(checkpoint)}
        self._verify()
        warning = self._write(key, record)
        self._verify()
        return {'saved': warning is None, 'key': key, 'warning': warning}

    def load_checkpoint(self, invocation):
        """Authenticate every referenced record, reconstruct, then restore-check.

Only an absent checkpoint returns None. A published checkpoint with missing or
corrupt chunks is an integrity failure, never a silent cache miss. The existing
restore validator checks unique, contiguous positive-duration receipt clocks.
"""
        if self.component != 'coastal':
            raise ValueError('Coastal checkpoints require the coastal component namespace')
        invocation = _json(invocation)
        self._verify()
        record = self._store.get(self._key('checkpoint', invocation))
        if record is None:
            self._verify()
            return None
        _exact(record, ('schema', 'invocation', 'checkpoint', 'receipt_chunk_refs', 'receipt_count',
                        'complete_checkpoint_sha256'), 'thin checkpoint')
        if record['schema'] != SCHEMA+'.checkpoint' or p.encoded(record['invocation']) != p.encoded(invocation):
            raise store.CacheError('Cached checkpoint invocation differs')
        _digest(record['complete_checkpoint_sha256'])
        if (type(record['receipt_chunk_refs']) is not list or type(record['receipt_count']) is not int
                or not len(record['receipt_chunk_refs']) <= record['receipt_count']
                       <= len(record['receipt_chunk_refs'])*CHUNK_MAX_RECEIPTS):
            raise store.CacheError('Cached checkpoint chunk references/count differ')
        checkpoint = deepcopy(record['checkpoint'])
        if type(checkpoint.get('scientific')) is not dict or 'receipts' in checkpoint['scientific']:
            raise store.CacheError('Invalid thin scientific checkpoint')
        receipts, seen = [], set()
        for digest in record['receipt_chunk_refs']:
            _digest(digest)
            # Accepted positive-duration receipts have distinct start clocks.
            # Reject repeated references before allocating repeated payloads.
            if digest in seen:
                raise store.CacheError('Duplicate accepted coastal receipt chunk reference')
            seen.add(digest)
            chunk = self._store.get(self._key('receipt_chunk', digest))
            if chunk is None:
                raise store.CacheError('Published coastal checkpoint has a missing receipt chunk')
            _exact(chunk, ('schema', 'content_sha256', 'receipts'), 'receipt chunk')
            if (chunk['schema'] != SCHEMA+'.receipt_chunk' or chunk['content_sha256'] != digest
                    or type(chunk['receipts']) is not list or not 1 <= len(chunk['receipts']) <= CHUNK_MAX_RECEIPTS
                    or any(type(row) is not dict for row in chunk['receipts'])
                    or p.sha(chunk['receipts']) != digest):
                raise store.CacheError('Cached coastal receipt chunk content differs')
            store._encode(chunk, limit=CHUNK_MAX_BYTES)
            receipts.extend(chunk['receipts'])
        if len(receipts) != record['receipt_count']:
            raise store.CacheError('Reconstructed coastal receipt count differs')
        checkpoint['scientific']['receipts'] = receipts
        if p.sha(checkpoint) != record['complete_checkpoint_sha256']:
            raise store.CacheError('Reconstructed coastal checkpoint differs from complete saved content')
        self._checkpoint(checkpoint)
        self._verify()
        return checkpoint
