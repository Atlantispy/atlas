"""Bounded per-stage reuse using the unchanged authenticated R12 Store.

The caller supplies the complete stage-specific source/data/owner/frame/config
closure in ``binding`` and all remaining inputs in ``invocation``. Current R20
execution is added automatically, together with the actually executed adapter
and Store bytes. Changed downstream inputs need not invalidate earlier stages;
changed R20 code is conservatively invalidating through the execution identity.

This does not prove a scientific result correct or validate external input files:
the required caller validator does that on BOTH fresh and cached results. R12's
8 MiB record / 256 MiB default total limits, immutable authenticated records,
path checks and no-eviction policy are retained. Corruption is not a cache miss.
Certified infeasibility and fully solved ambiguity may be retained as explicit
diagnostic results; they never become successful maps. Unfinished searches are
not admitted by the pipeline's completion validator.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import warnings

from work.generator_runtime_r12 import store
from work.generator_runtime_r12.provenance import checked
from . import provenance as p


SCHEMA = 'diadem.political-stage-cache.r20'
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'c20'


class CacheWriteSkipped(RuntimeWarning):
    """A validated value was returned but its cache entry was not saved."""


def _json_dict(value, name, *, nonempty=False):
    if type(value) is not dict or (nonempty and not value):
        raise ValueError(name+': explicit JSON dictionary required')
    store._check_json(value)
    return deepcopy(value)


def _implementation():
    sources = {}
    for path, executed in ((Path(__file__).resolve(), globals().get('_R12_EXECUTED_SHA256')),
                           (Path(store.__file__).resolve(), getattr(store, '_R12_EXECUTED_SHA256', None))):
        current = hashlib.sha256(checked(path)).hexdigest()
        if executed != current:
            raise ValueError('Stage cache executed source differs from current file: '+str(path))
        sources[str(path)] = current
    return sources


class StageCache:
    """Default dedicated root is short task/c20; supply an absolute Path only.

``reuse(invocation, producer, validator)`` returns (value, hit_bool). The validator
must raise on rejection; explicit False also rejects. It receives an isolated
copy, and its return value otherwise does not replace the scientific result.
Skipped full/oversize writes emit CacheWriteSkipped and appear in ``warnings``
and ``stats``. A miss does not imply a subsequent successful cache write.
"""
    def __init__(self, stage: str, binding: dict, root: Path | None = None):
        if type(stage) is not str or not stage.strip() or len(stage) > 128:
            raise ValueError('Bounded nonblank stage identity required')
        binding = _json_dict(binding, 'complete stage dependency binding', nonempty=True)
        self._closure = {'schema': SCHEMA, 'stage': stage, 'binding': binding,
                         'implementation': _implementation(), 'execution': deepcopy(p.identity())}
        self.namespace = p.sha(self._closure)
        self._warnings = []
        self._verify()
        self._store = store.Store(DEFAULT_ROOT if root is None else root, self.namespace)
        self._verify()

    @property
    def warnings(self):
        return deepcopy(self._warnings)

    @property
    def stats(self):
        return dict(self._store.stats, stage=self._closure['stage'], namespace=self.namespace,
                    warnings=len(self._warnings))

    def _verify(self):
        if (_implementation() != self._closure['implementation']
                or p.encoded(p.identity()) != p.encoded(self._closure['execution'])
                or p.sha(self._closure) != self.namespace):
            raise ValueError('Stage cache source/runtime binding changed; no repin')

    @staticmethod
    def _validate(value, validator):
        if validator(deepcopy(value)) is False:
            raise ValueError('Stage cache scientific validator rejected the result')

    def reuse(self, invocation: dict, producer, validator):
        invocation = _json_dict(invocation, 'complete stage invocation')
        if not callable(producer) or not callable(validator):
            raise ValueError('Explicit stage producer and validator required')
        self._verify()
        key = p.sha({'schema': SCHEMA, 'invocation': invocation})
        record = self._store.get(key)
        if record is not None:
            if (type(record) is not dict or set(record) != {'schema', 'invocation', 'value'}
                    or record['schema'] != SCHEMA
                    or p.encoded(record['invocation']) != p.encoded(invocation)):
                raise store.CacheError('Cached stage invocation/schema differs')
            self._validate(record['value'], validator)
            self._verify()
            return deepcopy(record['value']), True
        value = producer()
        store._check_json(value)
        value = deepcopy(value)
        self._validate(value, validator)
        self._verify()
        record = {'schema': SCHEMA, 'invocation': invocation, 'value': value}
        before = self._store.stats
        self._store.put(key, record)
        saved = self._store.get(key)
        if saved is None:
            after = self._store.stats
            reason = ('record exceeds 8 MiB' if after['skipped_oversize'] > before['skipped_oversize']
                      else 'store full at its configured limit' if after['skipped_full'] > before['skipped_full']
                      else 'record absent after attempted write')
            message = 'R20 stage cache entry not saved ('+reason+'): '+key
            self._warnings.append({'stage': self._closure['stage'], 'key': key, 'reason': reason,
                                   'message': message})
            warnings.warn(message, CacheWriteSkipped, stacklevel=2)
        elif p.encoded(saved) != p.encoded(record):
            raise store.CacheConflictError('Stage cache readback differs from validated result')
        self._verify()
        return deepcopy(value), False
