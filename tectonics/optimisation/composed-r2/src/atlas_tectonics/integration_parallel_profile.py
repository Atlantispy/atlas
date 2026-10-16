"""Source-bound timing observations for optional exact interfaces and walls.

Elapsed times choose execution only. Nothing here enters an issued record, a
receipt row, a measure or any identity, and nothing here calls a ledger, an
arena or a decoder. An observation is usable only under an equal binding of
the package source, interpreter, machine, hash seed, ledger mode and
instrumentation; every other binding is stale and ignored, never converted.

The store is small, bounded, caller-owned unfunded bookkeeping, like the reuse
controller's cost table: at most four bindings, 256 classes of sixteen samples,
1,024 exact requests and 32 dispatch outcomes each, ordered by a sequence
number and never by a clock. A file store is optional and caller-chosen. It
must lie outside the source tree, is read once per process, and is replaced
atomically; a file that is not a current store is neither used nor overwritten.

A binding is read from the source on disk, but timings are taken by the code a
process has LOADED. The inventory found when this module is imported is kept
as that process's reference (``loaded_digest``): a caller whose disk source
has since changed must neither plan from the profile nor add to it.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import OrderedDict, deque
import copy
import hashlib
import heapq
import json
import os
from pathlib import Path
import platform
import stat
import sys
import threading
import time
import types

from . import integration_volume_overlap as O
from .integration_parallel_binding import canonical

BINDING_SCHEMA = 'atlas.interface-cost-binding.v2'
FEATURE_SCHEMA = 'atlas.interface-cost-features.v1'
STORE_SCHEMA = 'atlas.interface-cost-store.v1'
MAX_BINDINGS = 4
MAX_CLASSES = 256
MAX_SAMPLES = 16
MAX_EXACT = 1024
MAX_DISPATCH = 32
MAX_FILE_BYTES = 2 << 20
MAX_PATHS = 4
MAX_DECISIONS = 8
# A store whose counter has reached this is refused: it leaves ample room below
# the bound a count may have, so a file this code writes is one it reads again.
MAX_SEQUENCE = 1 << 60
READ_TRIES = 5
_UNREADABLE = 'profile store cannot be read: '
# A serial observation is one of the first two. An adopted contact, or one that
# waited for a worker before running serially, is only counted for the report.
ROUTES = ('shortcut', 'integrator')
REPORTED = ROUTES+('adopted', 'waited')
_THREADS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')

# The ONE mutable object of this module. It is lower-case, not callable and
# never rebound, so the execution identity neither captures nor guards it
# (precedent: reuse._release_state). Every reader and writer takes its lock.
_state = types.SimpleNamespace(lock=threading.RLock(), stores=OrderedDict(), machine=None,
                               decisions=deque(maxlen=MAX_DECISIONS), issued=0, loaded=None)


def seed_flag():
    """'0' only for an interpreter that STARTED with PYTHONHASHSEED=0.

    Recorded work counts follow set traversal, so timings taken under another
    hash seed describe different work.
    """
    return '0' if os.environ.get('PYTHONHASHSEED') == '0' and sys.flags.hash_randomization == 0 else 'random'


def instrumented():
    """Whether timing hooks have an identity we cannot safely reuse.

    sys.monitoring does not expose all callbacks or local event masks. Even
    a registered tool with no global events may instrument selected code;
    none of its timings may train or select from a persistent profile.
    """
    monitoring = getattr(sys, 'monitoring', None)
    return (sys.gettrace() is not None or sys.getprofile() is not None or
            monitoring is not None and any(monitoring.get_tool(index) is not None for index in range(6)))


def ledger_mode(budget):
    return 'legacy' if budget.max_predicate_work_units is None else 'predicate'


def code_digest():
    """Digest of the package source inventory that the dispatcher binds jobs to."""
    from .reuse import _source_bytes
    return hashlib.sha256(canonical({name: record.decode('ascii')
                                     for name, record in _source_bytes().items()})).hexdigest()


def loaded_digest():
    """The source inventory digest found when this process imported this module, or None.

    It stands for the code the process runs. An edit made after a module was
    imported changes the disk inventory, not the loaded code, so only a call
    whose disk inventory still equals this digest may bind its timings to it.
    It is exact for everything imported from then on. A module imported
    earlier and edited before this one was imported is not covered: binding
    the loaded code itself needs an execution context, which the unfunded
    decision does not create. None when that first inventory failed.
    """
    return _state.loaded


def runtime_facts():
    """Interpreter and machine facts that timings depend on; no path, time or PID."""
    from . import exact_arithmetic
    from .reuse import _loaded_binary
    exact = exact_arithmetic.runtime()
    # Use the same native byte identities and process-lifetime binary cache as
    # execution contexts; repeatedly hashing GMP at each enclosure is needless.
    arithmetic = dict(versions=dict(exact['versions']),
                      binaries={label: _loaded_binary(path) for label, path in exact['binaries'].items()})
    with _state.lock:
        if _state.machine is None:
            try:
                import psutil
                cores, memory = psutil.cpu_count(logical=False), psutil.virtual_memory().total >> 30
            except Exception:
                cores = memory = None
            _state.machine = dict(python=sys.version, implementation=sys.implementation.name,
                system=platform.system(), release=platform.release(), machine=platform.machine(),
                processor=platform.processor(), logical_cpus=os.cpu_count(), physical_cores=cores,
                memory_gib=memory)
        return dict(_state.machine, threads={name: os.environ.get(name) for name in _THREADS},
                    exact_arithmetic=arithmetic)


def binding_record(*, code, runtime, seed, ledger, instrumented, family='interface'):
    return dict(schema=BINDING_SCHEMA, code=code, runtime=runtime, seed=seed, ledger=ledger,
                instrumented=instrumented, features=FEATURE_SCHEMA, family=family)


def binding_digest(record):
    return hashlib.sha256(canonical(record)).hexdigest()


def current_binding(budget, code=None, family='interface'):
    return binding_record(code=code_digest() if code is None else code, runtime=runtime_facts(),
                          seed=seed_flag(), ledger=ledger_mode(budget), instrumented=instrumented(), family=family)


def width_bucket(width):
    """floor(log2(width)) of an exact positive rational; 'zero' for a zero width."""
    top, bottom = width.numerator, width.denominator
    if top < 0:
        raise ValueError('nonnegative width required')
    if not top:
        return 'zero'
    exponent = top.bit_length()-bottom.bit_length()
    # 2**(exponent-1) < width < 2**(exponent+1): one exact comparison decides.
    if (bottom << exponent if exponent >= 0 else bottom) <= (top if exponent >= 0 else top << -exponent):
        return exponent
    return exponent-1


def walls_centre(cell):
    """How many of the voxel's six planes pass through the sphere centre.

    These are the planes the interface body treats as homogeneous halfspaces
    of the ray cone. Only the placed cell is read: no budget, arena or decode.
    """
    return sum(1 for plane in O._box_planes(cell) if not plane[3])


def component_walls(row, boxes, cache):
    """walls_centre of the voxel holding one routing-view row, cached per voxel."""
    at = tuple(row['voxel_index'])
    found = cache.get(at)
    if found is None:
        found = cache[at] = walls_centre(boxes[at])
    return found


def class_key(max_leaves, bucket, paired, walls):
    """Readable canonical class: the numerical settings, then the structure."""
    return canonical([max_leaves, bucket, bool(paired), walls]).decode('ascii')


def class_digest(key):
    return hashlib.sha256(key.encode('ascii')).hexdigest()[:16]


def exact_key(support_id, logical_cell_id, constraint_name, other_support_id,
              other_logical_cell_id, max_width_m3, max_leaves):
    return hashlib.sha256(canonical([support_id, logical_cell_id, constraint_name, other_support_id,
                                     other_logical_cell_id, max_width_m3, max_leaves])).hexdigest()


def wall_class_key(max_leaves, bucket, axis, end, walls):
    return canonical(['wall', max_leaves, bucket, axis, end, walls]).decode('ascii')


def wall_exact_key(support_id, logical_cell_id, axis, end, max_width_m3, max_leaves):
    """Only full-interval rigid walls with no moments or supplied normal."""
    return hashlib.sha256(canonical(['wall', support_id, logical_cell_id, axis, end,
                                     max_width_m3, max_leaves])).hexdigest()


def aggregate():
    return dict(count=0, seconds=0.0, work_units=0, max_seconds=0.0)


def new_observations():
    """One call's empty observation set: the unit that fold and the file merge.

    classes[key] = dict(shortcut, integrator, samples=[[seconds, work units,
    leaves]]); exact[key] = [route, seconds, work units, leaves]; dispatch rows
    are [start-up seconds or None, body seconds or None, total seconds,
    adopted]; walls and interfaces[route] are aggregate counters for reports.
    A contact adopted from a worker is a wait, not a serial observation: it
    belongs in dispatch only.
    """
    return dict(classes={}, exact={}, dispatch=[], walls=aggregate(), interfaces={})


def _entry():
    return dict(new_observations(), sequence=0)


def _oldest(rows, order, limit):
    """Drop the least recently updated rows beyond ``limit``; equal sequences fall to the key.

    One selection pass. A file is cleaned before any bound applies to it, so
    one scan of every row per evicted row would let a foreign store inside
    the size cap stall the first enclosure of a process for half a minute.
    """
    excess = len(rows)-limit
    if excess > 0:
        for key in heapq.nsmallest(excess, rows, key=lambda key: (order(rows[key]), key)):
            del rows[key]


def _add(held, row):
    held['count'] += row['count']
    held['seconds'] += row['seconds']
    held['work_units'] += row['work_units']
    held['max_seconds'] = max(held['max_seconds'], row['max_seconds'])


def _merge(entry, observed, sequence):
    """Add one observation set (or another entry) to an entry; apply every bound."""
    entry['sequence'] = sequence
    for key, row in observed['classes'].items():
        held = entry['classes'].setdefault(key, dict(sequence=sequence, shortcut=0, integrator=0, samples=[]))
        held['sequence'] = sequence
        held['shortcut'] += row['shortcut']
        held['integrator'] += row['integrator']
        held['samples'] = (held['samples']+[list(sample) for sample in row['samples']])[-MAX_SAMPLES:]
    for key, row in observed['exact'].items():
        entry['exact'][key] = [*row[:4], sequence]
    entry['dispatch'] = (entry['dispatch']+[list(row) for row in observed['dispatch']])[-MAX_DISPATCH:]
    _add(entry['walls'], observed['walls'])
    for route, row in observed['interfaces'].items():
        if route in REPORTED:
            _add(entry['interfaces'].setdefault(route, aggregate()), row)
    _oldest(entry['classes'], lambda row: row['sequence'], MAX_CLASSES)
    _oldest(entry['exact'], lambda row: row[4], MAX_EXACT)


def _merge_bindings(bindings, digest, observed, sequence):
    _merge(bindings.setdefault(digest, _entry()), observed, sequence)
    _oldest(bindings, lambda entry: entry['sequence'], MAX_BINDINGS)


def _seconds(value):
    # The range alone: it refuses NaN and infinity, and an integer beyond
    # float range is compared exactly where math.isfinite would raise on it.
    return type(value) in (int, float) and 0 <= value <= 1e9


def _count(value):
    return type(value) is int and 0 <= value < 1 << 62


def _clean_aggregate(row):
    if (type(row) is dict and _count(row.get('count')) and _count(row.get('work_units'))
            and _seconds(row.get('seconds')) and _seconds(row.get('max_seconds'))):
        return dict(count=row['count'], seconds=float(row['seconds']), work_units=row['work_units'],
                    max_seconds=float(row['max_seconds']))
    return aggregate()


def _clean(record):
    """Bounded, typed copy of a decoded store; anything malformed is dropped."""
    bindings = {}
    for digest, entry in record['bindings'].items():
        if len(digest) != 64 or type(entry) is not dict or not _count(entry.get('sequence')):
            continue
        clean = dict(_entry(), sequence=entry['sequence'], walls=_clean_aggregate(entry.get('walls')))
        classes, exact, dispatch, interfaces = (entry.get(name) for name in
                                                ('classes', 'exact', 'dispatch', 'interfaces'))
        for key, row in (classes.items() if type(classes) is dict else ()):
            if (len(key) <= 128 and type(row) is dict and type(row.get('samples')) is list
                    and all(_count(row.get(name)) for name in ('sequence', 'shortcut', 'integrator'))):
                samples = [[float(s[0]), s[1], s[2]] for s in row['samples'] if type(s) is list
                           and len(s) == 3 and _seconds(s[0]) and _count(s[1]) and _count(s[2])]
                clean['classes'][key] = dict(sequence=row['sequence'], shortcut=row['shortcut'],
                    integrator=row['integrator'], samples=samples[-MAX_SAMPLES:])
        for key, row in (exact.items() if type(exact) is dict else ()):
            if (len(key) == 64 and type(row) is list and len(row) == 5 and row[0] in ROUTES
                    and _seconds(row[1]) and all(map(_count, row[2:]))):
                clean['exact'][key] = [row[0], float(row[1]), *row[2:]]
        for row in (dispatch if type(dispatch) is list else ()):
            if (type(row) is list and len(row) == 4 and all(v is None or _seconds(v) for v in row[:2])
                    and _seconds(row[2]) and type(row[3]) is bool):
                clean['dispatch'].append(row)
        for route in REPORTED:
            if type(interfaces) is dict and route in interfaces:
                clean['interfaces'][route] = _clean_aggregate(interfaces[route])
        del clean['dispatch'][:-MAX_DISPATCH]
        _oldest(clean['classes'], lambda row: row['sequence'], MAX_CLASSES)
        _oldest(clean['exact'], lambda row: row[4], MAX_EXACT)
        bindings[digest] = clean
    _oldest(bindings, lambda entry: entry['sequence'], MAX_BINDINGS)
    return bindings


def _read(path):
    """(bindings, sequence, None) of a current store file, or (None, 0, reason).

    A missing file, or one with no bytes at all, is an empty store. Unknown
    schema, corrupt, oversize or special files are ignored with a reason and
    are never overwritten. A file that could not be opened or read says
    nothing about its content: its reason starts with ``_UNREADABLE``, and a
    later save may read it again. A sharing violation is retried briefly:
    Windows refuses the open while another process replaces the file.
    """
    for attempt in range(READ_TRIES):
        try:
            with open(path, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    return None, 0, 'profile store is not a regular file'
                raw = stream.read(MAX_FILE_BYTES+1)
            break
        except FileNotFoundError:
            return {}, 0, None
        except PermissionError as error:
            if attempt+1 >= READ_TRIES:
                return None, 0, _UNREADABLE+type(error).__name__
            time.sleep(0.02)
        except OSError as error:
            return None, 0, _UNREADABLE+type(error).__name__
    if not raw:
        return {}, 0, None
    if len(raw) > MAX_FILE_BYTES:
        return None, 0, 'profile store is larger than its 2 MiB bound'
    try:
        record = json.loads(raw)
        if (type(record) is not dict or record.get('schema') != STORE_SCHEMA
                or type(record.get('bindings')) is not dict or not _count(record.get('sequence'))):
            return None, 0, 'profile store has an unknown schema'
        bindings = _clean(record)
        # A foreign or edited file may carry row sequences above its own
        # counter. New observations must still be the newest, or the current
        # binding would be the first evicted: count on from the highest held.
        sequence = max([record['sequence']]+[held for entry in bindings.values() for held in (
            entry['sequence'], *(row['sequence'] for row in entry['classes'].values()),
            *(row[4] for row in entry['exact'].values()))])
        if sequence >= MAX_SEQUENCE:
            return None, 0, 'profile store has no sequence numbers left'
        return bindings, sequence, None
    except (ValueError, TypeError, ArithmeticError, AttributeError, LookupError, RecursionError) as error:
        return None, 0, 'profile store is corrupt: '+type(error).__name__


def _store_path(path):
    """Normalised file name of a caller-chosen store; the source tree is refused.

    The tree is hashed by the verifiers and copied by snapshots, so a profile
    written there would look like a source change during a run.
    """
    name = os.path.normcase(os.path.abspath(os.fspath(path)))
    tree = os.path.normcase(str(Path(__file__).absolute().parents[2]))
    if name == tree or name.startswith(tree+os.sep):
        raise ValueError('profile store must lie outside the source tree')
    return name


def open_store(path=None):
    """This process's store for one file (None: process memory only), and a note.

    The file is read on first use only; later calls reuse the copy held here
    together with this process's own observations. A refused path gives the
    memory-only store. A file that is not a current store gives an empty one
    that is never written. A file that could not be read at all gives an
    empty one too, but its observations are kept for a later save, which
    reads and checks the file again before it writes. The note says why.
    Never raises.
    """
    note = name = None
    if path is not None:
        try:
            name = _store_path(path)
        except (ValueError, TypeError, OSError) as refusal:
            note = str(refusal) or type(refusal).__name__
    with _state.lock:
        store = _state.stores.get(name)
        if store is None:
            bindings, sequence, reason = ({}, 0, None) if name is None else _read(name)
            store = _state.stores[name] = dict(path=name, sequence=sequence, bindings=bindings or {},
                pending={}, error=reason, writable=name is not None and (
                    bindings is not None or reason.startswith(_UNREADABLE)))
            while len(_state.stores) > MAX_PATHS+1:
                del _state.stores[next(key for key in _state.stores if key is not None and key != name)]
        _state.stores.move_to_end(name)
        return store, note or store['error']


def summary(store, digest):
    """Counts for the decision record: what is held and what is stale."""
    with _state.lock:
        entry = store['bindings'].get(digest)
        return dict(path=store['path'], bindings=len(store['bindings']),
            stale_bindings=len(store['bindings'])-(entry is not None),
            classes=0 if entry is None else len(entry['classes']),
            exact=0 if entry is None else len(entry['exact']),
            dispatch=0 if entry is None else len(entry['dispatch']))


def class_rows(store, digest):
    """Detached {class key: row} of one binding; empty when it is unknown."""
    with _state.lock:
        entry = store['bindings'].get(digest)
        return {} if entry is None else copy.deepcopy(entry['classes'])


def exact_row(store, digest, key):
    with _state.lock:
        entry = store['bindings'].get(digest)
        row = None if entry is None else entry['exact'].get(key)
        return None if row is None else list(row)


def exact_rows(store, digest):
    """Detached exact-request rows of one binding, without their request keys."""
    with _state.lock:
        entry = store['bindings'].get(digest)
        return [] if entry is None else [list(row) for row in entry['exact'].values()]


def dispatch_rows(store, digest):
    with _state.lock:
        entry = store['bindings'].get(digest)
        return [] if entry is None else [list(row) for row in entry['dispatch']]


def fork_store(store, digest, *, empty=False):
    """Bounded provisional observations, never saved before the enclosure validates."""
    with _state.lock:
        entry = None if empty else store['bindings'].get(digest)
        return dict(path=None, sequence=store['sequence'],
                    bindings={} if entry is None else {digest: copy.deepcopy(entry)},
                    pending={}, error=None, writable=False)


def entry_observations(store, digest):
    with _state.lock:
        return copy.deepcopy(store['bindings'].get(digest, new_observations()))


def fold(store, digest, observed):
    """Merge one call's observations into memory and into the unsaved file delta."""
    with _state.lock:
        store['sequence'] += 1
        _merge_bindings(store['bindings'], digest, observed, store['sequence'])
        if store['writable']:
            _merge_bindings(store['pending'], digest, observed, store['sequence'])


def save(store):
    """Merge the unsaved observations into the file; None, or why it was not saved.

    The file is read again so that another process's observations survive, then
    replaced through this process's own temporary file. A failed save keeps
    its observations pending for the next one. Never raises an Exception.
    """
    with _state.lock:
        if store['path'] is None or not store['pending'] and store['writable']:
            return None
        if not store['writable']:
            return 'not saved: '+str(store['error'])
        name = store['path']
        bindings, sequence, reason = _read(name)
        if bindings is None:
            return 'not saved: '+reason
        temporary = '%s.%d.next' % (name, os.getpid())
        try:
            sequence = max(sequence, store['sequence'])
            for digest, entry in sorted(store['pending'].items(), key=lambda item: item[1]['sequence']):
                sequence += 1
                _merge_bindings(bindings, digest, entry, sequence)
            encoded = canonical(dict(schema=STORE_SCHEMA, sequence=sequence, bindings=bindings))
            if len(encoded) > MAX_FILE_BYTES:
                raise ValueError('bounded store exceeds its file limit')
            with open(temporary, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                try:
                    # The replace below must never leave a store with no bytes
                    # after a crash. Best effort: not every file system syncs.
                    os.fsync(stream.fileno())
                except OSError:
                    pass
            os.replace(temporary, name)
        except (OSError, ValueError, TypeError) as error:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            return 'not saved: %s: %s' % (type(error).__name__, error)
        store['pending'] = {}
        store['sequence'] = sequence
        return None


def record_decision(decision):
    """Keep a detached copy of one finished decision; returns its sequence number."""
    with _state.lock:
        _state.issued += 1
        _state.decisions.append(dict(copy.deepcopy(decision), sequence=_state.issued))
        return _state.issued


def last_decision():
    with _state.lock:
        return copy.deepcopy(_state.decisions[-1]) if _state.decisions else None


def decisions():
    with _state.lock:
        return copy.deepcopy(list(_state.decisions))


def clear():
    """Forget this process's observations and decisions; files are not touched.

    The digest of the source this process loaded is a fact about the process,
    not an observation, and stays.
    """
    with _state.lock:
        _state.stores.clear()
        _state.decisions.clear()


def _loaded():
    try:
        return code_digest()
    except Exception:
        return None


# Once, when this module is imported, as regional_evolution3d keeps the digest
# of its own file. The attribute is set on the one state object; nothing is
# rebound, and the identity neither captures nor guards it.
_state.loaded = _loaded()
