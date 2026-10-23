"""The reconstruction of faces on worker processes: the same rows, sooner.

A face's row is a pure function of the observation points, the face's own
geometry entry and polygon, the boundary power faces that land in its shell,
the conductivity and the precision ladder. Nothing computed for one face is
read by another. ``reconstruct_faces`` hands the faces of one reconstruction
call to worker processes, one face at a time, and returns what the serial loop
of the functionals kernel builds: rows and census in the order of the faces
given, each completed row put through the kernel's unchanged retention in the
calling process and entered on the call's workspace.

A worker is a child interpreter that runs this file. It puts the caller's
runtime clone first on its import path, imports the caller's functionals kernel
by name and calls that kernel's own unchanged ``_face``. It is sent, once, every
observation point, the geometry entry and the polygon of every boundary power
face, the conductivity, the ladder and the caller's settings; a face's own
geometry entry and polygon come with the face. It never holds the decoded
mesh. Of a face record it is given the three fields the polygon moment reads
(``MOMENT_FIELDS``); the kernel reads nothing else of it.

The same code. Before a worker computes anything it compares with the
caller's: the interpreter (version, executable, flags, -X and -W options), the
selected exact backend with its native files, and the SHA256 of every private
heat module file and every file of the runtime package it has loaded; and it
checks that the runtime package came from the caller's clone. It repeats the
file check after a face that loaded another module. The caller compares the
worker's table of files with its own as well. A file the caller has not loaded
itself (a worker's first face loads runtime modules that a caller which has
computed no face may not have) is read by the caller where its own imports
would find it, the candidate folder for a private heat module and the clone for
a runtime module, and compared; a file from anywhere else is not the caller's.
A worker that differs is not used.

The same settings. A worker is given the caller's Decimal context, its limit
for converting integers to text and its recursion limit before it computes,
says what it is then set to, and is not used unless that is what the caller is
set to. The ambient MPFR context is not sent: the kernel's interval arithmetic
enters explicit contexts of its own.

Memory. A worker's ledger is a budget of its own for each face, with a ceiling
that never refuses: the calculated reservations of a face are a record there.
What the worker really holds is charged to the caller's ledger by the process
meter, from before it is started until after it has ended. For each collected
face the caller's ledger is also shown, and at once given back, the peak of the
worker's ledger for that face together with the polygon moments kept from
earlier faces, so that the meter's record of what the earlier rule would have
held includes the face. A worker validates a boundary polygon once, then keeps
its moment and drops its record, so it does not grow with the faces it has
seen. This module is used only while a forward call is metered: ``workers`` is
zero otherwise, and the serial loop runs.

When a worker cannot be used (it reports an exception for a face, ends, stops
answering, sends something unreadable, is not ready in time, or differs from
the caller), every worker is ended and released. If the problem was with a
face a worker held, that face is computed in the calling process first, by the
same calls as the kernel's serial loop: a genuine failure is then raised from
real frames on the caller's ledger. If that face succeeds here, the faces not
yet collected go to fresh workers, once; after a second problem, or when the
problem was not with a face, or too few faces are left, they are computed in
the calling process. ``fell_back`` is called for each problem, and
``report()`` keeps every call that had one, with the reason.

A worker that holds a face and has used no processor time for ``STALL_LOOKS``
looks in a row, ``STALL_LOOK_SECONDS`` apart (about a minute), has stopped
answering. One that computes is waited for, however long its face takes.

On cancellation, or any other exception in the calling process, every worker
is ended by its own process handles, waited for and released through the meter
before the exception continues. While workers compute, the calling thread only
waits: it calls the cancel callback and the meter on every pass of its loop,
at least twenty times a second, and never blocks on a pipe. ``completed`` is
called once for each face collected from a worker; a face computed in the
calling process returns from the kernel's ``_face`` there, as before.

What this does NOT guarantee:

- Equal bookkeeping. Rows are equal object for object by value, and census
  entries are equal except their wall-clock ``seconds``. The ledger's timeline
  and peaks differ: faces arrive out of order, and a rebuilt exact number
  reports its own allocated limbs, not the capacity of the worker's.
- Equal object sharing. A collected row holds its own copies of its keys and
  owners, where a row of the serial loop shares them with the prepared
  geometry. Retention counts shared objects once for each use, so the
  reservation covers both. Polygon moments stay in the workers.
- A reservation before a message is read. The bytes of an arriving message
  exist before the calling thread sees them; at most one message a worker is
  outstanding. The meter's margin covers them, as it covers the shared inputs
  while they are being written to the workers.
- That every process below the caller is on the meter. Where the interpreter
  is started through a launcher, the meter reads the interpreter; the launcher
  and the console host the system adds (about 2 MB a worker together) are left
  to the meter's margin. A guard that sums every process below the caller sees
  all three.
- That the caller's loaded modules equal their files. The comparison is of
  files on disk as each process finds them, not of code objects, and a file
  that changes between two readings of it is not noticed. Packages outside
  the candidate folder and the runtime clone (numpy, scipy, psutil and the
  like) are those of the same interpreter and environment and are not
  compared, except the exact backend's native files.
- Everything a process can be set to. The settings named above are sent;
  the hash seed is not (rows were equal under different seeds wherever they
  were compared), nor is anything else a caller might change in itself.
- Which failure is raised when more than one face cannot be reconstructed:
  the one whose problem reached the calling process first, which need not be
  the first in the order of the faces, where the serial loop stops.
- A limit on the time a face may take. A worker is given up only when it has
  ended or has used no processor time for about a minute; one that computes
  without end is waited for, as the serial loop would wait.
- Speed. Workers each compute the moments of the boundary faces they meet, a
  worker takes about two seconds to be ready, and a pass of few faces can cost
  more than it saves; ``MIN_FACES`` is a judgement, not a measured optimum.
  After a problem the faces in hand at the workers are computed again.
- Survival of an abrupt end of the calling process. A worker watches the
  caller and leaves within about a second of its disappearance, and at the
  latest when its pipe closes; nothing stronger is arranged.

No arithmetic, order of rows, support, precision or reservation formula of the
kernel is changed or repeated here, and no physical value is read.
"""
from hashlib import sha256
import os
from pathlib import Path
import pickle
import queue
import struct
import subprocess
import sys
import threading
from time import perf_counter, sleep

if __name__ != '__main__':
    # A worker runs this file as its script and selects the runtime clone
    # before any private import: see _select.
    import private_heat_process_meter_r1 as METER

SCHEMA = 'atlas.private.heat-functionals-parallel.r1'
MIN_FACES = 16                   # a call with fewer faces to reconstruct stays on the serial loop
LEDGER_HEADROOM = 1 << 30        # left free on the caller's ledger beside the workers' starting allowances
START_SLACK = 32 << 20           # a worker must be ready this far below the meter's starting allowance
WORKER_LEDGER = 1 << 62          # a worker's own ledger never refuses: its figures are a record
POLL = .05                       # seconds the collecting loop waits for a message
START_SECONDS = 180.             # a worker that is not ready by then is not used
GRACE_SECONDS = 10.              # an idle worker is given this long to leave by itself
END_SECONDS = 30.                # an ended worker must be gone within this
WATCH_SECONDS = 1.               # how often a worker looks for the calling process
STALL_LOOK_SECONDS = 5.          # how often the caller looks at the processor time of a worker that holds a face
STALL_LOOKS = 12                 # looks in a row without any before that worker has stopped answering
RESULT_BYTES = 262144            # fixed part of the reservation for one arriving result
RESULT_SCALE = 4                 # times the message: its bytes, the unpickler's table and slack
FACES_PER_FRAME = 128            # boundary faces in one message of the shared inputs
MOMENT_FIELDS = ('vertices_m', 'centroid_m', 'area_vector_m2')   # all the polygon moment reads of a face record
KEPT_CALLS = 16                  # call records kept for report()

# The ONE mutable object of this module. It is lower-case, not callable and
# never rebound; a driver or tool sets the count through configure().
_state = dict(workers=6, calls=[], fallbacks=[],
              totals=dict(calls=0, faces=0, collected=0, in_caller=0, fallbacks=0, restarts=0))


def configure(*, workers=None):
    """Set how many worker processes a metered reconstruction call may use; return the setting."""
    if workers is not None:
        if type(workers) is not int or workers < 0:
            raise ValueError('Worker count must be a nonnegative integer')
        _state['workers'] = workers
    return _state['workers']


def report():
    """The setting, the totals of this process, what each of the last calls used, and the calls that had a problem.

    ``calls`` holds the last ``KEPT_CALLS`` calls in full. ``fallbacks`` holds
    a short record of the first ``KEPT_CALLS`` calls in which a worker could
    not be used, whatever came after them; ``totals`` counts every call.
    """
    return dict(schema=SCHEMA, workers=_state['workers'], minimum_faces=MIN_FACES, totals=dict(_state['totals']),
                calls=[dict(call, processes=[dict(row) for row in call['processes']], release=list(call['release']))
                       for call in _state['calls']],
                fallbacks=[dict(item) for item in _state['fallbacks']])


def workers(budget, faces):
    """How many worker processes a reconstruction call may use.

    ``faces`` is the number of selected faces that have to be reconstructed. A
    face with a prescribed power is not counted: it costs one polygon moment,
    and a call of such faces alone is not worth a process.

    Zero means the unchanged serial loop. It is zero unless the call is a
    metered forward call (a meter that follows named categories only, or one
    that has failed and no longer judges the process, is not that), at least
    MIN_FACES faces are to be reconstructed and two or more workers are
    configured; and it is no more than the caller's ledger can take at the
    meter's starting allowance with LEDGER_HEADROOM left over.
    """
    meter = METER.active(budget)
    if meter is None or type(faces) is not int or faces < MIN_FACES:
        return 0
    if getattr(meter, 'categories', None) is not None or getattr(meter, 'failed', False):
        return 0
    count = min(_state['workers'], faces, max(0, budget.available_bytes-LEDGER_HEADROOM)//METER.CHILD_START)
    return count if count >= 2 else 0


def completed(index):
    """One face has been collected from a worker. A plain function, so that a driver can watch it."""
    return index


def fell_back(index):
    """The workers of a pass have been ended because one could not be used.

    ``index`` is the position of the face that worker held, or None. Called
    once for each such problem, before the calling process computes anything
    in their place. A plain function, so that a driver can watch it.
    """
    return index


# --------------------------------------------------------------------- messages
def _pack(head, body=b''):
    """One message: a pickled head of plain values, then a body the receiver may leave as bytes."""
    first = pickle.dumps(head, protocol=pickle.HIGHEST_PROTOCOL)
    return b''.join((struct.pack('>QI', 4+len(first)+len(body), len(first)), first, body))


def _receive(stream):
    """The next complete message of a pipe, without its length. EOFError when the other side has gone."""
    size = stream.read(8)
    if len(size) != 8:
        raise EOFError('The pipe ended')
    count = struct.unpack('>Q', size)[0]
    data = stream.read(count)
    if len(data) != count:
        raise EOFError('The pipe ended inside a message')
    return data


def _unpack(data):
    """(head, body) of one message. The body is a view of the message and is not unpickled here."""
    count = struct.unpack_from('>I', data)[0]
    return pickle.loads(data[4:4+count]), memoryview(data)[4+count:]


def _dump(value):
    return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)


# --------------------------------------------------------------------- identity
def _digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


_INDEXED_RUNTIME_HELPERS = frozenset(('compact_contracts', 'compact_restart_store', 'compact_store', 'content_cache', 'continuation_transfer', 'differential_mesh_patch', 'exchange_record_patch', 'exterior_mesh_patch', 'funding_transfer', 'geometry_transfer', 'heat_cold_patch', 'heat_ledger_issuer_patch', 'heat_ledger_tables', 'heat_payload_indexed_patch', 'historical_admission', 'historical_compact_heat', 'interval_catalog', 'interval_store_set', 'live_collar_patch', 'live_composite', 'live_finite_patch', 'live_mesh_patch', 'live_partition_patch', 'live_spatial_patch', 'live_transport_result', 'materialise_endpoint', 'mesh_tables', 'mimetic_patch', 'native_transfer', 'partition_native_patch', 'partition_routing_patch', 'partition_routing_transform', 'partition_store', 'partition_tables', 'partition_v2', 'partition_workflow_patch', 'pressure_indexed_patch', 'record_tables', 'record_views', 'runtime_compatibility', 'segment_store', 'spatial_indexed_patch', 'spatial_record_recipes', 'spatial_records_patch', 'spatial_transfer', 'spatial_validation_patch', 'spatial_workflow_patch', 'support_source', 'workflow_transfer'))


def _ours(name):
    """Whether a module name is a private heat module or part of the runtime package."""
    return name in _INDEXED_RUNTIME_HELPERS or name.startswith('private_heat_') or name == 'atlas_tectonics' or name.startswith('atlas_tectonics.')


def _files():
    """SHA256 of this file and of every private heat and runtime package file this process has loaded, by resolved path."""
    paths = {str(Path(__file__).resolve())}
    for name, module in tuple(sys.modules.items()):
        if _ours(name) and getattr(module, '__file__', None):
            paths.add(str(Path(module.__file__).resolve()))
    return {path: _digest(path) for path in sorted(paths)}


def _runtime():
    """What a worker must reproduce: the interpreter with its options, and the selected exact backend with its native files."""
    from atlas_tectonics import exact_arithmetic
    return dict(python=sys.version, executable=sys.executable, flags=tuple(sys.flags),
                options=sorted((str(name), str(value)) for name, value in sys._xoptions.items()),
                warnings=[str(item) for item in sys.warnoptions],
                backend=exact_arithmetic.BACKEND, exact=exact_arithmetic.runtime())


def _settings():
    """What a face can read of its process besides its inputs, and a process can be set to: as plain values."""
    import decimal
    context = decimal.getcontext()
    return dict(decimal=[context.prec, context.rounding, context.Emin, context.Emax, context.capitals, context.clamp,
                         sorted(signal.__name__ for signal, trapped in context.traps.items() if trapped)],
                integer_digits=sys.get_int_max_str_digits(), recursion=sys.getrecursionlimit())


def _set(context, settings):
    """Give this process the caller's Decimal context, integer-to-text limit and recursion limit."""
    import decimal
    decimal.setcontext(context)
    sys.set_int_max_str_digits(settings['integer_digits'])
    sys.setrecursionlimit(settings['recursion'])


def _clone():
    """The import path entry the runtime package of this process was loaded from."""
    import atlas_tectonics
    return str(Path(atlas_tectonics.__file__).resolve().parent.parent)


def _misplaced(clone):
    """Loaded runtime modules that did not come from ``clone``."""
    wrong = []
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if (name == 'atlas_tectonics' or name.startswith('atlas_tectonics.')) and path:
            if not Path(path).resolve().is_relative_to(clone):
                wrong.append(name)
    return sorted(wrong)


def _unlike(files, table, candidate, clone):
    """Names of the files a worker loaded that are not the caller's.

    ``table`` is the caller's own: what it has loaded, by path. A file the
    caller has not loaded is read here, where the caller's imports would find
    it (a private heat module in the candidate folder, a runtime module in
    the clone's package), and remembered in ``table`` for the rest of the
    pass. A file from anywhere else is not the caller's, whatever it holds.
    """
    if type(files) is not dict or not files:
        return ['(no table of files)']
    wrong = []
    for path, digest in files.items():
        if type(path) is not str or type(digest) is not str:
            wrong.append(Path(str(path)).name)
            continue
        if path not in table:
            place = Path(path)
            found = None
            if ((place.parent == candidate and (place.name.startswith('private_heat_') or
                    place.suffix == '.py' and place.stem in _INDEXED_RUNTIME_HELPERS))
                    or place.is_relative_to(clone/'atlas_tectonics')):
                try:
                    found = _digest(path)
                except OSError:
                    pass
            table[path] = found
        if table[path] != digest:
            wrong.append(Path(path).name)
    return sorted(wrong)


# ------------------------------------------------------------ the calling process
def _moment_part(face):
    return {name: face[name] for name in MOMENT_FIELDS}


def _inputs(kernel, prepared, ladder, table):
    """The messages every worker is sent once, in order.

    The geometry entry of a boundary power face shares its centre with the
    observation point of that face; it is sent without it and the worker joins
    the two again, so the coordinates travel and are held once.
    """
    import decimal
    points, geometry, records = prepared['points'], prepared['geometry'], prepared['face_data']
    yield _pack(('hello', dict(schema=SCHEMA, kernel=kernel.__name__, clone=_clone(),
                               candidate=str(Path(kernel.__file__).resolve().parent), files=table,
                               runtime=_runtime(), caller=os.getpid())))
    yield _pack(('points',), _dump(dict(points=points, conductivity=prepared['conductivity'], ladder=ladder,
                                        context=decimal.getcontext().copy(), settings=_settings())))
    group = {}
    for fid in sorted(prepared['neumann']):
        entry = geometry[fid]
        if entry['centre'] is points.get(('power', fid)):
            entry = {name: value for name, value in entry.items() if name != 'centre'}
        group[fid] = (entry, _moment_part(records[fid]))
        if len(group) == FACES_PER_FRAME:
            yield _pack(('faces',), _dump(group))
            group = {}
    if group:
        yield _pack(('faces',), _dump(group))
    yield _pack(('begin',))


def _task(prepared, index, fid):
    """The message that gives one face to a worker. A boundary power face is already with it."""
    if fid in prepared['neumann']:
        return _pack(('face', index, fid))
    return _pack(('face', index, fid), _dump((prepared['geometry'][fid], _moment_part(prepared['face_data'][fid]))))


def _read(stream, slot, results):
    """Move complete messages from one worker's pipe to the queue; None once the pipe has ended."""
    try:
        while True:
            results.put((slot, _receive(stream)))
    except (EOFError, OSError, ValueError):
        pass
    finally:
        results.put((slot, None))


def _write(stream, outbox):
    """Write queued messages to one worker's pipe. None closes it: leave for an idle worker to end."""
    try:
        while True:
            data = outbox.get()
            if data is None:
                break
            stream.write(data)
            stream.flush()
    except (OSError, ValueError):
        pass                      # the worker has gone; its reader says so
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


class _Worker:
    """One child interpreter and the two threads that move its messages."""
    def __init__(self, slot):
        self.slot, self.index, self.ready = slot, None, False
        self.process = None          # what was started: the interpreter, or a launcher in front of it
        self.real = None             # the interpreter itself, once it has said which process it is
        self.native_bound = None     # independent retained actual-interpreter query handle
        self.native_receipt = None
        self.threads = []
        self.outbox = queue.SimpleQueue()
        self.began = perf_counter()
        self.watched, self.still = None, 0   # the face and processor time at the last look; looks without any since
        self.row = dict(slot=slot, pid=None, ready_seconds=None, faces=0, busy_seconds=0., compute_seconds=0.,
                        moments=0, private_peak_bytes=0, working_set_peak_bytes=0, ended_by_caller=None,
                        exit_code=None)

    def launch(self, command, environment, results):
        self.process = subprocess.Popen(command, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for target, arguments in ((_read, (self.process.stdout, self.slot, results)),
                                  (_write, (self.process.stdin, self.outbox))):
            thread = threading.Thread(target=target, args=arguments, daemon=True)
            self.threads.append(thread)
            thread.start()

    def end(self, psutil, wait):
        """Preserve the original shutdown and always close the extra read-only handle."""
        try:
            self._end_process(psutil, wait)
        finally:
            _native_close_worker(self, preserve_error=sys.exc_info()[0] is not None)

    def _end_process(self, psutil, wait):
        """Wait ``wait`` seconds for the process to end by itself, then end it by its own handles."""
        process, members = self.process, []
        if process is None:
            return
        if self.real is not None:
            members.append(self.real)
        if process.poll() is None:
            try:
                # Whatever else is below the process that was started: behind a
                # launcher, the interpreter (which may not yet have said who it
                # is) and the console host the system gives them.
                members += [child for child in psutil.Process(process.pid).children(recursive=True)
                            if all(child.pid != known.pid for known in members)]
            except psutil.Error:
                pass
        forced = True
        if wait > 0:
            try:
                process.wait(timeout=wait)
                forced = bool(psutil.wait_procs(members, timeout=min(wait, 2.))[1])
            except subprocess.TimeoutExpired:
                pass
        if forced:
            for member in members:
                try:
                    member.kill()
                except psutil.Error:
                    pass                       # it has ended meanwhile
            if process.poll() is None:
                process.kill()
        process.wait(timeout=END_SECONDS)
        if psutil.wait_procs(members, timeout=END_SECONDS)[1]:
            raise RuntimeError('A worker process could not be ended')
        # An ended process can still be found for a moment, until its last
        # handle is closed. The meter releases a worker only once it is not.
        limit = perf_counter()+END_SECONDS
        while any(member.is_running() for member in members):
            if perf_counter() > limit:
                raise RuntimeError('An ended worker process is still listed')
            sleep(.005)
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(timeout=END_SECONDS)
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        self.row.update(ended_by_caller=forced, exit_code=process.returncode)


class _Pool:
    """The workers of one start and their charge on the meter."""
    def __init__(self, meter):
        import psutil
        self.psutil, self.meter = psutil, meter
        self.results = queue.SimpleQueue()
        self.workers, self.started, self.allowances = [], [], 0
        self.rows = []                         # one record a worker, for the call's report; filled as they are created
        self.stopped = False

    def start(self, count):
        """Charge ``count`` workers, then start them. Returns why one could not be started, or None."""
        self.meter.expect_workers(count)
        self.allowances = count
        # One BLAS thread: with the default sixteen, numpy and scipy commit
        # about a gigabyte of memory a process that is never touched.
        environment = dict(os.environ, OPENBLAS_NUM_THREADS='1')
        if not sys.executable:
            return 'this interpreter does not know its own path'
        command = [sys.executable, '-B', str(Path(__file__).resolve()), 'worker']
        for slot in range(count):
            worker = _Worker(slot)
            self.workers.append(worker)        # known to stop() before anything of it exists
            self.rows.append(worker.row)
            try:
                worker.launch(command, environment, self.results)
            except OSError as error:
                return 'a worker could not be started: %s' % error
        return None

    def admit(self, worker, facts, table, places):
        """A worker says it is ready. Returns why it cannot be used, or None once the meter reads it."""
        if type(facts) is not dict or type(facts.get('pid')) is not int:
            return 'a worker did not say which process it is'
        try:
            real = self.psutil.Process(facts['pid'])
            if facts['pid'] != worker.process.pid and real.ppid() != worker.process.pid:
                return 'a worker named a process that is not its own'
            worker.real = real
            info = real.memory_info()
        except self.psutil.Error:
            # It has ended since it spoke, or was never there: a worker problem, not a failure of the call.
            return 'a worker ended before it could be read'
        unlike = _unlike(facts.get('files'), table, *places)
        if unlike:
            return 'a worker loaded other files: '+', '.join(unlike[:8])
        if facts.get('settings') != _settings():
            return 'a worker is not set as this process is'
        if max(info.private, info.rss) > METER.CHILD_START-START_SLACK:
            return 'a worker was ready above its starting allowance'
        try:
            _native_admit_worker(worker, facts['pid'])
        except Exception as error:
            worker.row['native_binding_error'] = _native_error(error)
            return 'a worker native admission refused: '+str(error)[:400]
        self.started.append(facts['pid'])      # before the meter is told: it registers the process first
        try:
            self.meter.worker_started(facts['pid'])
        except self.psutil.Error:
            return 'a worker ended before the meter read it'
        self.allowances -= 1
        worker.ready = True
        worker.row.update(pid=facts['pid'], ready_seconds=round(perf_counter()-worker.began, 3))
        return None

    def stalled(self):
        """The first worker that holds a face and has used no processor time for STALL_LOOKS looks in a row, or None.

        Asked when nothing has arrived, STALL_LOOK_SECONDS apart at least. A
        worker that computes uses processor time without pause; one that is
        suspended, or waits for something that never comes, uses none. The
        count starts again with every face and with any processor time used.
        """
        for worker in self.workers:
            if not worker.ready or worker.index is None:
                continue
            try:
                times = worker.real.cpu_times()
            except self.psutil.Error:
                continue                           # it has ended: its reader says so
            now = worker.index, times.user+times.system
            if now != worker.watched:
                worker.watched, worker.still = now, 0
                continue
            worker.still += 1
            if worker.still >= STALL_LOOKS:
                return worker
        return None

    def stop(self, wait, *, quiet):
        """End every worker, wait for it and give its charge back through the meter.

        Every worker is attempted whatever happens to another. With ``quiet``
        nothing is raised: an exception is already on its way. Returns what
        went wrong, as text.
        """
        if self.stopped:
            return []
        self.stopped = True
        failures = []
        for worker in self.workers:
            worker.outbox.put(None)
        deadline = perf_counter()+wait
        for worker in self.workers:
            try:
                # With leave to end by itself, each is at least looked at before it is ended.
                worker.end(self.psutil, max(.1, deadline-perf_counter()) if wait else 0.)
            except BaseException as error:
                failures.append(error)
        for pid in self.started:
            try:
                self.meter.worker_stopped(pid)
            except BaseException as error:
                failures.append(error)
        left, self.started, self.allowances = min(self.allowances, self.meter.expected), [], 0
        if left:
            try:
                self.meter.unexpect_workers(left)
            except BaseException as error:
                failures.append(error)
        if failures and not quiet:
            raise failures[0]
        return ['%s: %s' % (type(error).__name__, error) for error in failures]


def _take(kernel, facts, body, size, fid, seen, *, budget, cancelled, work, retain):
    """Give one arriving result its own accounted lifetime, as the serial loop does for a face.

    Returns the retained value, or text when the message is not a result for
    this face (the caller then computes the face itself).
    """
    import private_heat_gmp_resources_r1 as R
    if (type(facts) is not dict or facts.get('face_id') != fid or type(facts.get('moments')) is not dict
            or any(type(facts.get(name)) is not int or facts[name] < 0 for name in ('ledger_peak', 'retained'))
            or any(type(key) is not str or type(count) is not int or count < 0
                   for key, count in facts['moments'].items())):
        return 'a worker sent a result this call did not ask for'
    # The earlier rule's figure for this face: what the worker's ledger reached,
    # and the moments the serial loop would still be holding from earlier faces.
    earlier = facts['ledger_peak']+sum(seen.values())
    with R.OwnedWorkspace(budget, earlier, category='heat-functional-worker-face', cancelled=cancelled):
        pass
    space = R.OwnedWorkspace(budget, RESULT_BYTES+RESULT_SCALE*size+facts['retained'],
                             category='heat-functional-face', cancelled=cancelled)
    space.__enter__()
    try:
        try:
            value = pickle.loads(body)
        except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError, KeyError,
                TypeError, ValueError):
            value = None
        if (type(value) is not dict or tuple(value) != ('row', 'diagnostics')
                or any(type(part) is not dict or part.get('face_id') != fid for part in value.values())):
            value = None
            space.__exit__(None, None, None)
            return 'a worker sent an unreadable result'
        temporary = kernel.P.OwnedSolve(value, space)
    except BaseException:
        space.__exit__(*sys.exc_info())
        raise
    try:
        retained = retain.transfer(temporary, budget=budget, cancelled=cancelled)
    except BaseException:
        temporary.__exit__(*sys.exc_info())
        raise
    work.stack.enter_context(retained)
    # Only now do the polygons this face validated count: its result is kept.
    for key, count in facts['moments'].items():
        seen.setdefault(key, count)
    return retained.value


def _collect(pool, kernel, prepared, face_ids, order, count, rows, census, done, seen, call, *, budget, cancelled,
             certification_precisions, work, retain):
    """Hand the faces at the positions ``order`` to ``count`` workers and collect them.

    Returns None when every one has been collected, or (position of the face
    a worker failed on or None, why) when the workers cannot be used.
    """
    try:
        table = _files()
    except OSError as error:
        # Nothing to hold a worker to: the loop runs here, as it would have without this module.
        return None, 'this process could not read its own module files: %s' % error
    places = Path(kernel.__file__).resolve().parent, Path(_clone())
    began = perf_counter()
    problem = pool.start(count)
    if problem is not None:
        return None, problem
    for data in _inputs(kernel, prepared, certification_precisions, table):
        kernel.I.check(cancelled)
        METER.tick(budget)
        call['shared_input_bytes'] += len(data)
        for worker in pool.workers:
            worker.outbox.put(data)
    data = None
    waiting = order[::-1]                               # not handed out yet; the next face is the last item
    remaining = len(order)
    look = perf_counter()+STALL_LOOK_SECONDS
    while remaining:
        # The only place the caller's guards and the cancel file are evaluated
        # during the pass, and where the meter reads this process and its workers.
        kernel.I.check(cancelled)
        METER.tick(budget)
        for worker in pool.workers:
            if worker.ready and worker.index is None and waiting:
                worker.index, worker.began = waiting.pop(), perf_counter()
                worker.outbox.put(_task(prepared, worker.index, face_ids[worker.index]))
        try:
            slot, data = pool.results.get(timeout=POLL)
        except queue.Empty:
            now = perf_counter()
            if now-began > START_SECONDS and not all(worker.ready for worker in pool.workers):
                return None, 'a worker was not ready in time'
            if now >= look:
                # Nothing has arrived: is a worker that holds a face still using its processor?
                look = now+STALL_LOOK_SECONDS
                worker = pool.stalled()
                if worker is not None:
                    return worker.index, 'a worker stopped answering'
            continue
        worker = pool.workers[slot]
        index = worker.index
        if data is None:
            return index, 'a worker ended'
        try:
            head, body = _unpack(data)
            kind, detail = head[0], head[1] if len(head) > 1 else None
        except Exception:
            return index, 'a worker sent an unreadable message'
        if kind == 'ready' and not worker.ready:
            problem = pool.admit(worker, detail, table, places)
            if problem is not None:
                return None, problem
            if call['ready_seconds'] is None:
                call['ready_seconds'] = round(perf_counter()-began, 3)
        elif kind == 'row' and index is not None and type(detail) is dict and detail.get('index') == index:
            if detail.get('loaded') is not None:
                # This face made the worker load module files it had not named before.
                unlike = _unlike(detail['loaded'], table, *places)
                if unlike:
                    return index, 'a worker loaded other files: '+', '.join(unlike[:8])
            if 'candidate_heat_route' in detail:
                _native_accept_worker(worker, detail['candidate_heat_route'])
            value = _take(kernel, detail, body, len(data), face_ids[index], seen, budget=budget,
                          cancelled=cancelled, work=work, retain=retain)
            if type(value) is str:
                return index, value
            rows[index], census[index], done[index] = value['row'], value['diagnostics'], True
            facts, row = detail, worker.row
            if 'candidate_heat_route' in facts:
                row['candidate_heat_route'] = facts['candidate_heat_route']
            spent = facts.get('seconds') if type(facts.get('seconds')) is float else 0.
            if spent > call['slowest_face_seconds']:
                call.update(slowest_face_seconds=round(spent, 3), slowest_face=face_ids[index])
            row.update(faces=row['faces']+1, busy_seconds=round(row['busy_seconds']+perf_counter()-worker.began, 3),
                       compute_seconds=round(row['compute_seconds']+spent, 3),
                       moments=row['moments']+len(facts['moments']),
                       private_peak_bytes=max(row['private_peak_bytes'], facts.get('private_peak', 0)),
                       working_set_peak_bytes=max(row['working_set_peak_bytes'], facts.get('working_set_peak', 0)))
            call.update(collected=call['collected']+1, result_bytes=call['result_bytes']+len(data),
                        largest_worker_ledger_peak_bytes=max(call['largest_worker_ledger_peak_bytes'],
                                                             facts['ledger_peak']))
            worker.index, remaining = None, remaining-1
            completed(index)
        elif kind == 'error':
            detail = detail if type(detail) is dict else {}
            if 'candidate_heat_route' in detail:
                worker.row['candidate_heat_route'] = detail['candidate_heat_route']
                try:
                    _native_accept_worker(worker, detail['candidate_heat_route'])
                except Exception as error:
                    worker.row['native_binding_error'] = _native_error(error)
            call['worker_traceback'] = str(detail.get('traceback'))[-6000:]
            return index, 'a worker reported %s: %s' % (detail.get('kind'), str(detail.get('text'))[:400])
        elif kind == 'refused':
            call['worker_traceback'] = str(head[2] if len(head) > 2 else None)[-6000:]
            return None, 'a worker refused: '+str(detail)[:400]
        else:
            return index, 'a worker sent a message out of turn'
        value = head = body = detail = data = None
    return None


def _serial(kernel, prepared, face_ids, order, rows, census, done, moments, *, budget, cancelled,
            certification_precisions, work, retain):
    """The faces at the positions ``order`` in the calling process: the calls of the kernel's serial loop, in that sequence.

    ``moments`` holds the polygon moments this process has computed for the
    call, and is added to.
    """
    def moment(fid):
        if fid not in moments:
            owned = work.stack.enter_context(kernel.MOMENT.second_moment(prepared['face_data'][fid],
                                                                         budget=budget, cancel=cancelled))
            moments[fid] = owned.value['moment']
        return moments[fid]
    for index in order:
        fid = face_ids[index]
        kernel.I.check(cancelled)
        temporary = kernel._face(fid, prepared['geometry'][fid], prepared, moment, budget=budget,
            cancelled=cancelled, certification_precisions=certification_precisions)
        try:
            retained = retain.transfer(temporary, budget=budget, cancelled=cancelled)
        except BaseException:
            temporary.__exit__(*sys.exc_info())
            raise
        work.stack.enter_context(retained)
        rows[index], census[index], done[index] = retained.value['row'], retained.value['diagnostics'], True


def _to_reconstruct(prepared, face_ids, order):
    return sum(1 for index in order if face_ids[index] not in prepared['neumann'])


def reconstruct_faces(kernel, prepared, face_ids, *, budget, cancelled, certification_precisions, work, retain):
    """Rows, census and validated polygon ids for ``face_ids``, which are in payload order.

    ``kernel`` is the functionals kernel module that calls this, ``prepared``
    the value of its ``_prepare``, ``work`` the workspace of its call and
    ``retain`` its retention module. Returns (rows, census, ids): rows and
    census in the order of ``face_ids``, as the kernel's serial loop appends
    them, and the ids of every face whose polygon moment was computed.
    """
    face_ids = list(face_ids)
    rows, census, done = [None]*len(face_ids), [None]*len(face_ids), [False]*len(face_ids)
    seen, moments = {}, {}                              # polygons validated by workers (with what each kept), and here
    began = perf_counter()
    meter = METER.active(budget)
    order = list(range(len(face_ids)))                  # the positions not yet done, in payload order
    wanted = _to_reconstruct(prepared, face_ids, order)
    count = workers(budget, wanted)
    call = dict(faces=len(face_ids), to_reconstruct=wanted, configured=_state['workers'], workers=count,
                collected=0, in_caller=0, fallback=None, failed_face=None, restarted=False, second_fallback=None,
                ready_seconds=None, seconds=None,
                shared_input_bytes=0, result_bytes=0, largest_worker_ledger_peak_bytes=0, polygon_moments=0,
                worker_polygon_moment_bytes=0, slowest_face=None, slowest_face_seconds=0., worker_traceback=None,
                release=[], processes=[])
    _state['calls'].append(call)
    del _state['calls'][:-KEPT_CALLS]
    arguments = dict(budget=budget, cancelled=cancelled, certification_precisions=certification_precisions,
                     work=work, retain=retain)
    try:
        while True:
            failed, started = (None, 'the call is not metered or has fewer than two workers'), False
            if meter is not None and count >= 2:
                started = True
                pool = _Pool(meter)
                pool.rows = call['processes']
                try:
                    failed = _collect(pool, kernel, prepared, face_ids, order, count, rows, census, done, seen, call,
                                      **arguments)
                except BaseException:
                    # Cancellation, a guard, the meter or anything else in this
                    # process: no worker outlives it, and it is not replaced.
                    call['release'] = pool.stop(0., quiet=True)
                    raise
                finally:
                    call['seconds'] = round(perf_counter()-began, 3)
                pool.stop(GRACE_SECONDS if failed is None else 0., quiet=False)
            if failed is None:
                break
            first, why = failed
            order = [index for index in order if not done[index]]
            again, earlier = False, call['fallback']
            call['fallback' if earlier is None else 'second_fallback'] = why
            if started:
                fell_back(first)
            if earlier is None and first is not None and not done[first]:
                # The face a worker failed on, here and first: a genuine failure is raised from these frames.
                call.update(failed_face=face_ids[first], in_caller=call['in_caller']+1)
                _serial(kernel, prepared, face_ids, [first], rows, census, done, moments, **arguments)
                order.remove(first)
                # It succeeded here, so the fault was the worker's: fresh workers for the rest, once.
                count = workers(budget, _to_reconstruct(prepared, face_ids, order))
                again = count >= 2
            if not again:
                call['in_caller'] += len(order)
                _serial(kernel, prepared, face_ids, order, rows, census, done, moments, **arguments)
                break
            call['restarted'] = True
    finally:
        call.update(polygon_moments=len(set(seen) | set(moments)), worker_polygon_moment_bytes=sum(seen.values()),
                    seconds=round(perf_counter()-began, 3))
        totals = _state['totals']
        totals.update(calls=totals['calls']+1, faces=totals['faces']+call['faces'],
                      collected=totals['collected']+call['collected'], in_caller=totals['in_caller']+call['in_caller'],
                      fallbacks=totals['fallbacks']+(call['fallback'] is not None),
                      restarts=totals['restarts']+call['restarted'])
        if call['fallback'] is not None and len(_state['fallbacks']) < KEPT_CALLS:
            _state['fallbacks'].append({name: call[name] for name in (
                'faces', 'to_reconstruct', 'workers', 'collected', 'in_caller', 'fallback', 'failed_face', 'restarted',
                'second_fallback', 'seconds')} | dict(call_number=totals['calls']))
    return rows, census, set(seen) | set(moments)


# ------------------------------------------------------------------- the worker
def _select(hello):
    """Select the caller's clone, import its kernel and refuse to be anything else. Returns the kernel."""
    import importlib
    candidate, clone = hello['candidate'], hello['clone']
    for path in (candidate, clone):
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    importlib.import_module('atlas_tectonics')
    if _clone() != clone:
        raise RuntimeError('The runtime package did not load from the caller\'s clone')
    kernel = importlib.import_module(hello['kernel'])
    # The kernel imports this one inside its functions: loaded now, so that
    # the file check covers it before the first face needs it.
    importlib.import_module('private_heat_gmp_resources_r1')
    if Path(kernel.__file__).resolve().parent != Path(candidate):
        raise RuntimeError('The functionals kernel did not load from the caller\'s folder')
    own, theirs = _runtime(), hello['runtime']
    wrong = sorted(name for name in set(own) | set(theirs) if own.get(name) != theirs.get(name))
    if wrong:
        raise RuntimeError('The interpreter is not the caller\'s in: '+', '.join(wrong))
    _confirm(hello)
    return kernel


def _confirm(hello):
    """Refuse a runtime module from outside the caller's clone and a loaded file that is not the caller's.

    Returns this process's table of files. A file the caller did not name
    cannot be judged here: the caller is told of it and reads it itself.
    """
    wrong = _misplaced(hello['clone'])
    if wrong:
        raise RuntimeError('Runtime modules from outside the caller\'s clone: '+', '.join(wrong[:8]))
    own, theirs = _files(), hello['files']
    wrong = sorted(Path(path).name for path, digest in own.items() if path in theirs and theirs[path] != digest)
    if wrong:
        raise RuntimeError('Module files that are not the caller\'s: '+', '.join(wrong[:8]))
    return own


def _watch(psutil, caller):
    """Leave when the calling process has gone: an orphan must not go on computing."""
    while caller.is_running():
        sleep(WATCH_SECONDS)
    os._exit(3)


def _face_result(kernel, budget, prepared, records, moments, fid, entry, record, ladder):
    """One face by the kernel's own calls. Returns (facts for the caller, pickled value).

    ``records`` holds the polygons of the boundary power faces not yet met and
    ``moments`` the moments of those already met. A boundary polygon is
    validated once by this worker: its moment is then kept and its record
    dropped, so the worker does not grow with the faces it has seen. The owner
    of every moment computed for this face stays open until the face is done,
    as its reservation does in the serial loop; the caller is told what each
    holds and accounts for them from then on.
    """
    fresh, owners, local = {}, [], {}

    def moment(key):
        if key in moments:
            return moments[key]
        if key in local:
            return local[key]
        shared = key in records
        if not shared and key != fid:
            raise KeyError('No polygon for observed face '+key)
        owned = kernel.MOMENT.second_moment(records[key] if shared else record, budget=budget, cancel=None)
        owners.append(owned)
        fresh[key] = owned._workspace.lease.count
        value = owned.value['moment']
        if shared:
            moments[key] = value
            del records[key]
        else:
            local[key] = value
        return value

    try:
        temporary = kernel._face(fid, entry, prepared, moment, budget=budget, cancelled=None,
                                 certification_precisions=ladder)
        try:
            retained = kernel.RETAIN.transfer(temporary, budget=budget, cancelled=None)
        except BaseException:
            temporary.__exit__(*sys.exc_info())
            raise
        try:
            body = _dump(retained.value)
            facts = dict(face_id=fid, moments=fresh, retained=retained._workspace.lease.count,
                         ledger_peak=budget.peak_reserved_bytes)
        finally:
            retained.close()
        return facts, body
    finally:
        for owner in owners:
            owner.close()


_ASSEMBLY_POLICY_SHA256 = '0f43075fe062597c48c911ef47895fd93fee7f5a71ba46ecc926d810f12d6b8a'
_ASSEMBLY_H3_SHA256 = '18317500e239fbd9c6359c0abe110969495bdd356f88d38b92b3c1f2510cd0d5'
_ASSEMBLY_CERT_SHA256 = '6ae1a0ab413dd36f4544a147aedc0f58e3347bf52501a7f205a25e9c09b62eeb'
_NATIVE_BINDING_SOURCE = '"""Read-only, source-pinned MPFR bindings. Importing this source queries nothing.\n\nThis component supplies evidence, not scientific acceptance. Windows system API\nlibraries are resolved lazily; MPFR/H3 is never loaded or initialised here.\n"""\nimport ctypes as c\nfrom ctypes import wintypes as w\nimport hashlib\nimport os\nfrom pathlib import Path\nimport struct\nimport sys\nimport time\n\n\nEXPORT_NAMES = (\'mpfr_mul\', \'mpfr_add\', \'mpfr_set\', \'mpfr_less_p\', \'mpfr_greater_p\', \'mpfr_lessequal_p\', \'mpfr_regular_p\', \'mpfr_sgn\', \'mpfr_get_exp\', \'mpfr_flags_save\', \'mpfr_flags_clear\', \'mpfr_flags_restore\', \'mpfr_get_emin\', \'mpfr_get_emax\', \'mpfr_zero_p\', \'mpfr_number_p\', \'mpfr_signbit\', \'mpfr_set_zero\')\n# gmpy2\'s MPFR DLL in this interpreter\'s own environment (exec_prefix\\Lib\\site-packages, platlib under the\n# venv and nt schemes), computed with no IO, so no machine path is written here. The sha256 pin below\n# authenticates the bytes; the assembly contract\'s pinned native_library path fixes the environment.\n_PINNED_PATH = os.path.join(sys.exec_prefix, \'Lib\', \'site-packages\', \'gmpy2.libs\', \'libmpfr-6.dll\')\n_PINNED_SHA256 = \'b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8\'\n_MAX_FILE = 64 << 20\n_MAX_EXPORTS = 65536\n_MAX_JOB_PIDS = 65536\n_MAX_MODULES = 4096\n_READ_RIGHTS = 0x00100000 | 0x0400 | 0x0010  # SYNCHRONIZE, QUERY_INFORMATION, VM_READ.\n_EXPECTED_CACHE = {}\n\n\nclass BindingRefused(ValueError):\n    """Bounded error identity; callers retain their own operation/finality record."""\n    def __init__(self, code, message):\n        self.code = str(code)[:64]\n        self.message = str(message)[:320]\n        super().__init__(self.code + \': \' + self.message)\n\n\ndef _require(condition, code, message):\n    if not condition:\n        raise BindingRefused(code, message)\n\n\ndef _positive(value):\n    return type(value) is int and 0 < value < (1 << 64)\n\n\ndef _keys(value, names, code):\n    _require(type(value) is dict and set(value) == set(names), code, \'Closed object keys required\')\n\n\ndef _path(value):\n    _require(isinstance(value, (str, Path)), \'SOURCE_PATH\', \'Path must name the pinned MPFR DLL\')\n    text = str(Path(value))\n    _require(os.path.isabs(text) and text == str(Path(_PINNED_PATH)),\n             \'SOURCE_PATH\', \'Exact pinned absolute MPFR path required\')\n    return text\n\n\ndef _copy_expected(value):\n    return dict(schema=value[\'schema\'], path=value[\'path\'], sha256=value[\'sha256\'],\n                size=value[\'size\'], exports=dict(value[\'exports\']))\n\n\ndef _validate_expected(expected):\n    _keys(expected, (\'schema\', \'path\', \'sha256\', \'size\', \'exports\'), \'EXPECTED_SCHEMA\')\n    _require(expected[\'schema\'] == \'plan15.mpfr-exports.r1\', \'EXPECTED_SCHEMA\', \'Wrong metadata schema\')\n    _require(type(expected[\'path\']) is str, \'SOURCE_PATH\', \'Expected path must be a string\')\n    _path(expected[\'path\'])\n    _require(expected[\'sha256\'] == _PINNED_SHA256, \'SOURCE_SHA\', \'Wrong pinned MPFR hash\')\n    _require(_positive(expected[\'size\']) and expected[\'size\'] <= 0xffffffff,\n             \'EXPECTED_SIZE\', \'Invalid PE SizeOfImage\')\n    _keys(expected[\'exports\'], EXPORT_NAMES, \'EXPECTED_EXPORTS\')\n    rvas = list(expected[\'exports\'].values())\n    _require(all(_positive(v) and v < expected[\'size\'] for v in rvas),\n             \'EXPECTED_RVA\', \'Export RVA must lie inside the image\')\n    _require(len(set(rvas)) == len(EXPORT_NAMES), \'EXPORT_ALIAS\', \'Export aliases are forbidden\')\n\n\ndef _parse_pe(data, path, sha256):\n    """Private bounded byte parser; only read_expected_exports establishes its pin."""\n    _require(type(data) is bytes and 512 <= len(data) <= _MAX_FILE, \'PE_SIZE\', \'PE file bounds\')\n\n    def span(offset, count):\n        _require(type(offset) is int and type(count) is int and offset >= 0 and count >= 0\n                 and offset + count <= len(data), \'PE_BOUNDS\', \'Out-of-file PE span\')\n        return offset\n\n    def number(fmt, offset):\n        span(offset, struct.calcsize(fmt))\n        return struct.unpack_from(fmt, data, offset)[0]\n\n    _require(data[:2] == b\'MZ\', \'PE_DOS\', \'DOS signature required\')\n    pe = number(\'<I\', 0x3c)\n    span(pe, 24)\n    _require(data[pe:pe + 4] == b\'PE\\0\\0\', \'PE_SIGNATURE\', \'PE signature required\')\n    _require(number(\'<H\', pe + 4) == 0x8664, \'PE_MACHINE\', \'AMD64 required\')\n    count, optional_size = number(\'<H\', pe + 6), number(\'<H\', pe + 20)\n    _require(1 <= count <= 96 and 120 <= optional_size <= 4096,\n             \'PE_HEADERS\', \'Bounded section/optional headers required\')\n    optional = pe + 24\n    span(optional, optional_size)\n    _require(number(\'<H\', optional) == 0x20b, \'PE_OPTIONAL\', \'PE32+ required\')\n    image_size, header_size = number(\'<I\', optional + 56), number(\'<I\', optional + 60)\n    _require(0 < header_size <= len(data) and header_size < image_size <= 0xffffffff,\n             \'PE_IMAGE\', \'Invalid image/header size\')\n    _require(number(\'<I\', optional + 108) >= 1, \'PE_EXPORT_DIRECTORY\', \'Export directory missing\')\n    export_rva, export_size = number(\'<I\', optional + 112), number(\'<I\', optional + 116)\n    _require(export_rva > 0 and 40 <= export_size and export_rva + export_size <= image_size,\n             \'PE_EXPORT_DIRECTORY\', \'Invalid export directory bounds\')\n    sections = []\n    table = optional + optional_size\n    span(table, count * 40)\n    _require(table + count * 40 <= header_size, \'PE_HEADERS\', \'Section headers exceed SizeOfHeaders\')\n    for index in range(count):\n        base = table + index * 40\n        virtual_size, va, raw_size, raw = struct.unpack_from(\'<IIII\', data, base + 8)\n        flags = number(\'<I\', base + 36)\n        mapped = max(virtual_size, raw_size)\n        _require(mapped > 0 and va >= header_size and va + mapped <= image_size,\n                 \'PE_SECTION\', \'Section image bounds\')\n        if raw_size:\n            span(raw, raw_size)\n            _require(raw >= header_size, \'PE_SECTION\', \'Section overlaps headers\')\n        for old in sections:\n            _require(va + mapped <= old[0] or old[0] + old[1] <= va,\n                     \'PE_SECTION_OVERLAP\', \'Overlapping virtual sections\')\n            if raw_size and old[3]:\n                _require(raw + raw_size <= old[2] or old[2] + old[3] <= raw,\n                         \'PE_SECTION_OVERLAP\', \'Overlapping raw sections\')\n        sections.append((va, mapped, raw, raw_size, flags))\n\n    def offset(rva, size):\n        _require(_positive(rva) and type(size) is int and size >= 0 and rva + size <= image_size,\n                 \'PE_RVA\', \'Invalid RVA span\')\n        matches = [(a, raw, rs) for a, mapped, raw, rs, flags in sections\n                   if a <= rva and rva + size <= a + mapped]\n        _require(len(matches) == 1, \'PE_RVA\', \'RVA must belong to exactly one section\')\n        va, raw, raw_size = matches[0]\n        _require(rva - va + size <= raw_size, \'PE_RVA\', \'RVA has no complete backing bytes\')\n        return span(raw + rva - va, size)\n\n    def string(rva):\n        start = offset(rva, 1)\n        end = start\n        while end - start <= 512:\n            offset(rva + end - start, 1)\n            if data[end] == 0:\n                try:\n                    text = data[start:end].decode(\'ascii\')\n                except UnicodeDecodeError:\n                    raise BindingRefused(\'PE_STRING\', \'Non-ASCII export name\') from None\n                _require(bool(text), \'PE_STRING\', \'Empty export name\')\n                return text\n            end += 1\n        raise BindingRefused(\'PE_STRING\', \'Unterminated or oversized export name\')\n\n    directory = offset(export_rva, 40)\n    string(number(\'<I\', directory + 12))\n    functions, names = number(\'<I\', directory + 20), number(\'<I\', directory + 24)\n    _require(1 <= functions <= _MAX_EXPORTS and 1 <= names <= _MAX_EXPORTS,\n             \'PE_EXPORT_COUNT\', \'Export count outside bound\')\n    function_table = offset(number(\'<I\', directory + 28), functions * 4)\n    name_table = offset(number(\'<I\', directory + 32), names * 4)\n    ordinal_table = offset(number(\'<I\', directory + 36), names * 2)\n    all_rvas = [number(\'<I\', function_table + 4 * i) for i in range(functions)]\n    found, seen_names, named_rvas = {}, set(), []\n    for index in range(names):\n        name = string(number(\'<I\', name_table + 4 * index))\n        _require(name not in seen_names, \'PE_DUPLICATE_NAME\', \'Duplicate export name\')\n        seen_names.add(name)\n        ordinal = number(\'<H\', ordinal_table + 2 * index)\n        _require(ordinal < functions, \'PE_ORDINAL\', \'Export ordinal out of range\')\n        rva = all_rvas[ordinal]\n        named_rvas.append(rva)\n        if name in EXPORT_NAMES:\n            _require(rva > 0 and not export_rva <= rva < export_rva + export_size,\n                     \'PE_FORWARDED\', \'Null/forwarded export forbidden\')\n            code = [s for s in sections if s[0] <= rva < s[0] + s[1]]\n            _require(len(code) == 1 and code[0][4] & 0x20000000 and code[0][4] & 0x20,\n                     \'PE_NON_CODE\', \'Export must target an executable code section\')\n            offset(rva, 1)\n            found[name] = rva\n    _require(set(found) == set(EXPORT_NAMES), \'PE_EXPORT_MISSING\', \'Required named export missing\')\n    for rva in found.values():\n        _require(all_rvas.count(rva) == 1 and named_rvas.count(rva) == 1,\n                 \'EXPORT_ALIAS\', \'Aliased function RVA forbidden\')\n    expected = dict(schema=\'plan15.mpfr-exports.r1\', path=path, sha256=sha256,\n                    size=image_size, exports={name: found[name] for name in EXPORT_NAMES})\n    _validate_expected(expected)\n    return expected\n\n\ndef read_expected_exports(path, expected_sha256):\n    """Read pinned metadata once per configured source; return a defensive copy."""\n    path = _path(path)\n    _require(expected_sha256 == _PINNED_SHA256, \'SOURCE_SHA\', \'Exact MPFR pin required\')\n    key = (path, expected_sha256)\n    if key not in _EXPECTED_CACHE:\n        try:\n            with open(path, \'rb\') as stream:\n                before = os.fstat(stream.fileno())\n                _require(512 <= before.st_size <= _MAX_FILE, \'PE_SIZE\', \'Pinned file size outside bound\')\n                data = stream.read(_MAX_FILE + 1)\n                after = os.fstat(stream.fileno())\n            _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)\n                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)\n                     and len(data) == before.st_size, \'SOURCE_CHANGED\', \'Pinned file changed during read\')\n        except OSError as exc:\n            raise BindingRefused(\'SOURCE_READ\', \'Pinned file read failed: \' + str(exc.winerror if hasattr(exc, \'winerror\') else exc.errno)) from exc\n        _require(hashlib.sha256(data).hexdigest() == expected_sha256, \'SOURCE_SHA\', \'Pinned file bytes differ\')\n        parsed = _parse_pe(data, path, expected_sha256)\n        _EXPECTED_CACHE[key] = (parsed[\'size\'], tuple(parsed[\'exports\'].items()))\n    size, exports = _EXPECTED_CACHE[key]\n    return dict(schema=\'plan15.mpfr-exports.r1\', path=path, sha256=expected_sha256,\n                size=size, exports=dict(exports))\n\n\ndef validate_receipt(receipt, expected):\n    """Pure closed-schema validation; expected must come from the pinned parser."""\n    _validate_expected(expected)\n    _keys(receipt, (\'schema\', \'pid\', \'creation_filetime\', \'module\', \'exports\'), \'RECEIPT_SCHEMA\')\n    _require(receipt[\'schema\'] == \'plan15.native-binding.r1\', \'RECEIPT_SCHEMA\', \'Wrong binding schema\')\n    _require(_positive(receipt[\'pid\']) and receipt[\'pid\'] <= 0xffffffff\n             and _positive(receipt[\'creation_filetime\']), \'PROCESS_IDENTITY\', \'Exact process identity required\')\n    module = receipt[\'module\']\n    _keys(module, (\'path\', \'sha256\', \'base\', \'size\'), \'MODULE_SCHEMA\')\n    _require(module[\'path\'] == expected[\'path\'] and module[\'sha256\'] == expected[\'sha256\']\n             and type(module[\'size\']) is int and module[\'size\'] == expected[\'size\'],\n             \'MODULE_SOURCE\', \'Module path/hash/image size mismatch\')\n    _require(_positive(module[\'base\']) and module[\'base\'] + module[\'size\'] <= (1 << 64),\n             \'MODULE_BASE\', \'Invalid module address interval\')\n    _keys(receipt[\'exports\'], EXPORT_NAMES, \'RECEIPT_EXPORTS\')\n    for name in EXPORT_NAMES:\n        value = receipt[\'exports\'][name]\n        _keys(value, (\'address\', \'rva\'), \'RECEIPT_EXPORT\')\n        _require(_positive(value[\'rva\']) and value[\'rva\'] == expected[\'exports\'][name]\n                 and _positive(value[\'address\']) and value[\'address\'] == module[\'base\'] + value[\'rva\'],\n                 \'EXPORT_BINDING\', \'Export address/RVA mismatch: \' + name)\n\n\nclass _WindowsAPI:\n    """Lazy query-only Win32 adapter. Handles never include mutation rights."""\n    def __init__(self):\n        _require(os.name == \'nt\' and c.sizeof(c.c_void_p) == 8,\n                 \'PLATFORM\', \'64-bit Windows required; no fallback\')\n        self.k = c.WinDLL(\'kernel32\', use_last_error=True)\n        self.n = c.WinDLL(\'ntdll\', use_last_error=True)\n        specs = {\n            \'OpenProcess\': (w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),\n            \'GetProcessId\': (w.DWORD, [w.HANDLE]),\n            \'GetProcessTimes\': (w.BOOL, [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4),\n            \'WaitForSingleObject\': (w.DWORD, [w.HANDLE, w.DWORD]),\n            \'QueryInformationJobObject\': (w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]),\n            \'K32EnumProcessModulesEx\': (w.BOOL, [w.HANDLE, c.POINTER(w.HMODULE), w.DWORD, c.POINTER(w.DWORD), w.DWORD]),\n            \'K32GetModuleFileNameExW\': (w.DWORD, [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]),\n            \'K32GetModuleInformation\': (w.BOOL, [w.HANDLE, w.HMODULE, c.c_void_p, w.DWORD]),\n            \'CloseHandle\': (w.BOOL, [w.HANDLE]),\n        }\n        for name, (restype, argtypes) in specs.items():\n            function = getattr(self.k, name)\n            function.restype, function.argtypes = restype, argtypes\n        self.n.NtQueryInformationProcess.restype = c.c_long\n        self.n.NtQueryInformationProcess.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.ULONG, c.POINTER(w.ULONG)]\n\n    def _ok(self, result, code):\n        _require(bool(result), code, \'Windows query failed: \' + str(c.get_last_error()))\n\n    def open(self, pid):\n        handle = self.k.OpenProcess(_READ_RIGHTS, False, pid)\n        self._ok(handle, \'PROCESS_OPEN\')\n        return handle\n\n    def identity(self, handle):\n        pid = int(self.k.GetProcessId(handle))\n        self._ok(pid, \'HANDLE_PID\')\n        times = [w.FILETIME() for _ in range(4)]\n        self._ok(self.k.GetProcessTimes(handle, *(c.byref(v) for v in times)), \'PROCESS_TIMES\')\n        creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime\n        _require(_positive(creation), \'PROCESS_TIMES\', \'Missing process creation time\')\n        # Zero-time state query only: never wait or poll.\n        _require(self.k.WaitForSingleObject(handle, 0) == 258, \'PROCESS_DEAD\', \'Process must still be alive\')\n        return pid, creation\n\n    def parent_pid(self, handle):\n        class Basic(c.Structure):\n            _fields_ = [(\'exit_status\', c.c_long), (\'peb\', c.c_void_p),\n                        (\'affinity\', c.c_size_t), (\'priority\', c.c_long),\n                        (\'pid\', c.c_size_t), (\'parent\', c.c_size_t)]\n        info, returned = Basic(), w.ULONG()\n        status = self.n.NtQueryInformationProcess(handle, 0, c.byref(info), c.sizeof(info), c.byref(returned))\n        _require(status == 0 and returned.value == c.sizeof(info),\n                 \'PROCESS_ANCESTRY\', \'Incomplete/failed live process ancestry query\')\n        return int(info.parent)\n\n    def job_pids(self):\n        # NULL queries the calling controller\'s current retained job. A fixed\n        # bounded buffer refuses truncation rather than resizing/polling.\n        size = 8 + _MAX_JOB_PIDS * c.sizeof(c.c_size_t)\n        buffer, returned = c.create_string_buffer(size), w.DWORD()\n        self._ok(self.k.QueryInformationJobObject(None, 3, buffer, size, c.byref(returned)), \'JOB_QUERY\')\n        assigned, listed = struct.unpack_from(\'<II\', buffer.raw)\n        _require(0 < assigned == listed <= _MAX_JOB_PIDS\n                 and 8 + listed * c.sizeof(c.c_size_t) <= returned.value <= size,\n                 \'JOB_INCOMPLETE\', \'Current-job PID snapshot is incomplete/unknown\')\n        pids = [int(c.c_size_t.from_buffer(buffer, 8 + i * c.sizeof(c.c_size_t)).value)\n                for i in range(listed)]\n        _require(len(set(pids)) == listed and all(_positive(p) and p <= 0xffffffff for p in pids),\n                 \'JOB_INCOMPLETE\', \'Invalid/duplicate current-job PID snapshot\')\n        return sorted(pids)\n\n    def module(self, handle, path):\n        modules, needed = (w.HMODULE * _MAX_MODULES)(), w.DWORD()\n        self._ok(self.k.K32EnumProcessModulesEx(handle, modules, c.sizeof(modules), c.byref(needed), 3),\n                 \'MODULE_ENUM\')\n        _require(0 < needed.value <= c.sizeof(modules) and needed.value % c.sizeof(w.HMODULE) == 0,\n                 \'MODULE_INCOMPLETE\', \'Module enumeration incomplete/unknown\')\n        class Info(c.Structure):\n            _fields_ = [(\'base\', c.c_void_p), (\'size\', w.DWORD), (\'entry\', c.c_void_p)]\n        found = []\n        for index in range(needed.value // c.sizeof(w.HMODULE)):\n            text = c.create_unicode_buffer(32768)\n            length = self.k.K32GetModuleFileNameExW(handle, modules[index], text, len(text))\n            _require(0 < length < len(text) - 1, \'MODULE_PATH\', \'Unknown/truncated live module path\')\n            if text.value == path:\n                info = Info()\n                self._ok(self.k.K32GetModuleInformation(handle, modules[index], c.byref(info), c.sizeof(info)),\n                         \'MODULE_INFO\')\n                found.append(dict(path=text.value, base=int(info.base or 0), size=int(info.size)))\n        _require(len(found) == 1, \'MODULE_NOT_UNIQUE\', \'Exactly one pinned live module required\')\n        return found[0]\n\n    def close(self, handle):\n        self._ok(self.k.CloseHandle(handle), \'HANDLE_CLOSE\')\n\n\ndef _api_factory():\n    try:\n        return _WindowsAPI()\n    except (OSError, AttributeError) as exc:\n        raise BindingRefused(\'WINDOWS_API\', \'Required read-only Windows API unavailable\') from exc\n\n\ndef _job_proof(api, required):\n    pids = api.job_pids()\n    _require(type(pids) is list and pids and len(pids) <= _MAX_JOB_PIDS\n             and len(set(pids)) == len(pids) and all(_positive(p) for p in pids)\n             and set(required).issubset(pids), \'JOB_MEMBERSHIP\', \'Actual/launch/controller current-job membership unproved\')\n    return dict(schema=\'plan15.current-job-proof.r1\', complete=True,\n                caller_pid=os.getpid(), required_pids=sorted(set(required)),\n                member_count=len(pids), member_pids=sorted(pids),\n                authority=\'QueryInformationJobObject(NULL), calling controller current retained job\')\n\n\ndef _checked_expected(expected):\n    _validate_expected(expected)\n    trusted = read_expected_exports(expected[\'path\'], expected[\'sha256\'])\n    _require(expected == trusted, \'EXPECTED_TAMPER\', \'Supplied metadata differs from pinned parsed bytes\')\n    return trusted\n\n\ndef _receipt(api, handle, pid, creation, expected, costs=None):\n    _require(api.identity(handle) == (pid, creation), \'PROCESS_CHANGED\', \'Retained process identity changed\')\n    if costs is not None:\n        costs[\'module_query_calls\'] += 1\n    module = api.module(handle, expected[\'path\'])\n    _keys(module, (\'path\', \'base\', \'size\'), \'LIVE_MODULE_SCHEMA\')\n    _require(type(module[\'path\']) is str and _positive(module[\'base\'])\n             and _positive(module[\'size\']), \'LIVE_MODULE_VALUE\', \'Invalid live module metadata\')\n    receipt = dict(schema=\'plan15.native-binding.r1\', pid=pid, creation_filetime=creation,\n                   module=dict(module, sha256=expected[\'sha256\']),\n                   exports={name: dict(address=module[\'base\'] + rva, rva=rva)\n                            for name, rva in expected[\'exports\'].items()})\n    validate_receipt(receipt, expected)\n    _require(api.identity(handle) == (pid, creation), \'PROCESS_CHANGED\', \'Process exited/changed during module query\')\n    return receipt\n\n\nclass BoundProcess:\n    """Authenticated actual interpreter, holding only a read-only process handle."""\n    def __init__(self, api, handle, pid, creation, owner_record):\n        self.pid, self.creation_filetime = pid, creation\n        self.owner_record = owner_record\n        self._api, self._handle = api, handle\n        self._cached = None\n\n    def query(self, expected):\n        started = time.perf_counter()\n        costs = self.owner_record[\'costs\']\n        costs[\'query_calls\'] += 1\n        try:\n            _require(self._handle is not None, \'PROCESS_CLOSED\', \'Bound process is closed\')\n            _require(self.owner_record[\'query_failure\'] is None,\n                     \'BINDING_FAILED\', \'Earlier binding query failed; no retry/recapture\')\n            expected = _checked_expected(expected)\n            proof = _job_proof(self._api, (os.getpid(), self.pid))\n            receipt = _receipt(self._api, self._handle, self.pid, self.creation_filetime, expected, costs)\n            if self._cached is not None:\n                _require(receipt == self._cached, \'MODULE_LIFETIME_CHANGED\', \'Previously bound source/module changed; no recapture\')\n                costs[\'cached_receipt_reuses\'] += 1\n            self._cached = receipt\n            self.owner_record[\'last_query_job_proof\'] = proof\n            self.owner_record[\'query_failure\'] = None\n            return dict(receipt, module=dict(receipt[\'module\']),\n                        exports={n: dict(v) for n, v in receipt[\'exports\'].items()})\n        except BindingRefused as exc:\n            if self.owner_record[\'query_failure\'] is None:\n                self.owner_record[\'query_failure\'] = dict(code=exc.code, message=exc.message)\n            raise\n        finally:\n            costs[\'query_seconds\'] += time.perf_counter() - started\n\n    def close(self):\n        if self._handle is None:\n            return\n        started = time.perf_counter()\n        try:\n            self._api.close(self._handle)\n            self._handle = None\n            self.owner_record[\'closed\'] = True\n            self.owner_record[\'close_failure\'] = None\n        except BindingRefused as exc:\n            self.owner_record[\'close_failure\'] = dict(code=exc.code, message=exc.message)\n            raise\n        finally:\n            self.owner_record[\'costs\'][\'close_seconds\'] += time.perf_counter() - started\n\n\ndef open_admitted(pid, launch_pid, launch_handle):\n    """Authenticate at existing ready admission; close every partial own handle."""\n    started = time.perf_counter()\n    _require(_positive(pid) and pid <= 0xffffffff and _positive(launch_pid) and launch_pid <= 0xffffffff,\n             \'PROCESS_PID\', \'Exact positive DWORD PIDs required\')\n    _require(isinstance(launch_handle, int) and type(launch_handle) is not bool\n             and 0 < launch_handle < (1 << 64),\n             \'LAUNCH_HANDLE\', \'Retained launch handle required\')\n    api, actual, launch = _api_factory(), None, None\n    try:\n        borrowed_identity = api.identity(launch_handle)\n        _require(borrowed_identity[0] == launch_pid, \'LAUNCH_IDENTITY\', \'Launch handle PID mismatch\')\n        launch = api.open(launch_pid)\n        launch_identity = api.identity(launch)\n        _require(launch_identity == borrowed_identity, \'LAUNCH_IDENTITY\', \'Launch handle creation mismatch\')\n        actual = api.open(pid)\n        actual_identity = api.identity(actual)\n        _require(actual_identity[0] == pid, \'PROCESS_IDENTITY\', \'Actual interpreter handle PID mismatch\')\n        parent = api.parent_pid(actual)\n        relationship = \'same-process\' if pid == launch_pid else \'live-immediate-child\'\n        _require((pid == launch_pid and actual_identity == launch_identity)\n                 or (pid != launch_pid and parent == launch_pid and actual_identity[1] > launch_identity[1]),\n                 \'PROCESS_ANCESTRY\', \'Actual interpreter is not the live launcher/immediate child\')\n        proof = _job_proof(api, (os.getpid(), launch_pid, pid))\n        _require(api.identity(launch_handle) == launch_identity and api.identity(actual) == actual_identity,\n                 \'PROCESS_CHANGED\', \'Process changed during admission\')\n        api.close(launch)\n        launch = None\n        record = dict(schema=\'plan15.native-admission.r1\', pid=pid,\n                      creation_filetime=actual_identity[1], launch_pid=launch_pid,\n                      launch_creation_filetime=launch_identity[1], actual_parent_pid=parent,\n                      relationship=relationship, read_only_actual_handle=True,\n                      job_proof=proof, closed=False, close_failure=None, query_failure=None,\n                      costs=dict(open_seconds=time.perf_counter() - started, query_seconds=0.0,\n                                 query_calls=0, module_query_calls=0, cached_receipt_reuses=0,\n                                 close_seconds=0.0))\n        result = BoundProcess(api, actual, pid, actual_identity[1], record)\n        actual = None\n        return result\n    finally:\n        errors = []\n        for handle in (launch, actual):\n            if handle is not None:\n                try:\n                    api.close(handle)\n                except BindingRefused as exc:\n                    errors.append(exc.code)\n        if errors:\n            raise BindingRefused(\'ADMISSION_CLEANUP\', \',\'.join(errors))\n\n\ndef capture_self(expected, bound_exports):\n    """Observe already-loaded ctypes pointers; never resolve/load MPFR or H3."""\n    expected = _checked_expected(expected)\n    _keys(bound_exports, EXPORT_NAMES, \'BOUND_EXPORTS\')\n    api, handle = _api_factory(), None\n    try:\n        pid = os.getpid()\n        handle = api.open(pid)\n        actual_pid, creation = api.identity(handle)\n        _require(actual_pid == pid, \'PROCESS_IDENTITY\', \'Self handle does not name current process\')\n        receipt = _receipt(api, handle, pid, creation, expected)\n        for name in EXPORT_NAMES:\n            function = bound_exports[name]\n            _require(isinstance(function, c._CFuncPtr), \'BOUND_POINTER\', \'Actual ctypes function required: \' + name)\n            address = c.cast(function, c.c_void_p).value\n            _require(type(address) is int and address == receipt[\'exports\'][name][\'address\'],\n                     \'BOUND_POINTER\', \'Loaded function differs from pinned export: \' + name)\n        return receipt\n    finally:\n        if handle is not None:\n            api.close(handle)\n'
_NATIVE_BINDING_SHA256 = '8a7f741e3ac054f4c8e48b23d6b1b9429f0a80f4237f828adc23c6bb7be26138'
_ASSEMBLY_MPFR_SHA256 = 'b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8'
# gmpy2's MPFR DLL in this interpreter's own environment (exec_prefix\Lib\site-packages), injected into the
# embedded policy, which imports nothing that could compute it. The contract's pinned path fixes the environment.
_ASSEMBLY_MPFR_PATH = os.path.join(sys.exec_prefix, 'Lib', 'site-packages', 'gmpy2.libs', 'libmpfr-6.dll')
_MPFR_EXPORT_NAMES = ('mpfr_mul', 'mpfr_add', 'mpfr_set', 'mpfr_less_p', 'mpfr_greater_p', 'mpfr_lessequal_p', 'mpfr_regular_p', 'mpfr_sgn', 'mpfr_get_exp', 'mpfr_flags_save', 'mpfr_flags_clear', 'mpfr_flags_restore', 'mpfr_get_emin', 'mpfr_get_emax', 'mpfr_zero_p', 'mpfr_number_p', 'mpfr_signbit', 'mpfr_set_zero')
_ASSEMBLY_POLICY_SOURCE = '"""Source-only Plan15 assembly comparison policy; no scientific eligibility.\n\nThe caller verifies actual source bytes and injects _POLICY_SOURCE_SHA256 and\nMPFR_DLL_PATH (gmpy2\'s MPFR DLL in the caller\'s own interpreter environment).\nThis module has no IO, compilation, process inspection, pickle decoding or cache.\nOnly observe() constructs evidence; validation reconstructs it from retained raw\ntext. A comparison identity concerns emitted text under this explicit policy,\nnever numerical equivalence or literal diagnostic-byte equivalence.\n"""\n\n_POLICY_SOURCE_SHA256 = None\nPOLICY_VERSION = "plan15.assembly-comparison.r2"\nCONTEXT_SCHEMA = "plan15.assembly-context.r1"\nRECORD_SCHEMA = "plan15.assembly-observation.r1"\nMAX_ASSEMBLY_BYTES = 2097152\nH3_SHA256 = \'18317500e239fbd9c6359c0abe110969495bdd356f88d38b92b3c1f2510cd0d5\'\nCERT_SHA256 = \'6ae1a0ab413dd36f4544a147aedc0f58e3347bf52501a7f205a25e9c09b62eeb\'\nNATIVE_BINDING_SCHEMA = "plan15.native-binding.r1"\nMPFR_DLL_SHA256 = "b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8"\nMPFR_DLL_PATH = None  # injected by the caller; no machine path is written here\nMPFR_EXPORTS = (\'mpfr_mul\', \'mpfr_add\', \'mpfr_set\', \'mpfr_less_p\', \'mpfr_greater_p\', \'mpfr_lessequal_p\', \'mpfr_regular_p\', \'mpfr_sgn\', \'mpfr_get_exp\', \'mpfr_flags_save\', \'mpfr_flags_clear\', \'mpfr_flags_restore\', \'mpfr_get_emin\', \'mpfr_get_emax\', \'mpfr_zero_p\', \'mpfr_number_p\', \'mpfr_signbit\', \'mpfr_set_zero\')\nEMITTER_PINS = {\n    "cpu.py": "646ae6bd4170786750299571f03db0bf4d7832fd1954c4047239a809c7f406b1",\n    "pythonapi.py": "bf5548155e0750c3d0073be0b913e4b4f2749482a2b23304e20602073a6b2836",\n    "base.py": "7c834586dbb58358420b88c0ce3a73037fa0318bd4ece501762cd83892d5f33b",\n    "config.py": "cf057d6e36976c7422e36ebc24d7c45d359760d0cb0422c22f75cfee49d1927d",\n}\nFUNCTIONS = ("_classes", "_four", "_product", "_pair_dots")\nSIGNATURE_TEXTS = (\n    "(Array(int64, 2, \'C\', False, aligned=True), Array(int64, 2, \'C\', False, aligned=True))",\n    "(Array(int64, 1, \'C\', False, aligned=True), int64, int64, int64, int64)",\n    "(Array(int64, 1, \'C\', False, aligned=True), int8, int8, int64, int64, int64, int64)",\n    "(Array(int64, 2, \'C\', False, aligned=True), Array(int64, 2, \'C\', False, aligned=True), Array(int8, 2, \'C\', False, aligned=True), Array(bool, 1, \'C\', False, aligned=True), Array(int64, 2, \'C\', False, aligned=True), Array(int64, 2, \'C\', False, aligned=True), Array(int8, 2, \'C\', False, aligned=True), Array(int64, 1, \'C\', False, aligned=True), Array(int64, 1, \'C\', False, aligned=True), Array(int32, 1, \'C\', False, aligned=True), Array(int32, 1, \'C\', False, aligned=True), Array(int64, 1, \'C\', False, aligned=True), bool, int64, int64)",\n)\nCONTEXT_KEYS = (\n    "schema", "process_id", "source_generation", "module_sha256",\n    "certificate_sha256", "emitter_pins", "source_pins", "route", "build",\n    "native_runtime", "native_binding",\n)\nBUILD_KEYS = (\n    "compiled_assembly_sha256", "disk_jit_cache", "fastmath", "gmpy2",\n    "llvmlite", "load_seconds", "module_sha256", "mpfr", "mpfr_dll",\n    "mpfr_dll_sha256", "nogil", "numba", "signatures",\n)\nSIGNATURE_KEYS = (\n    "byte_end", "byte_start", "function", "function_index", "sha256",\n    "signature", "signature_index",\n)\nRECORD_KEYS = (\n    "schema", "status", "scientific_eligibility", "equivalence_claim",\n    "policy", "context", "signatures", "raw_text", "raw_sha256",\n    "raw_utf8_bytes", "joins", "units", "transformations", "comparison_sha256",\n)\nEXCLUDED_PROCESS_FIELDS = (\n    "context.process_id", "context.build.compiled_assembly_sha256",\n    "context.build.load_seconds", "signatures[].sha256", "raw_text",\n    "raw_sha256", "raw_utf8_bytes", "transformations",\n    "units[].raw_sha256", "units[].raw_utf8_bytes", "units[].consumer_evidence",\n    "context.native_binding.pid", "context.native_binding.creation_filetime",\n    "context.native_binding.module.base", "context.native_binding.exports.*.address",\n)\n\n\nclass AssemblyIdentityError(ValueError):\n    """Fail-closed refusal with a stable machine-readable reason code."""\n\n    def __init__(self, code, detail):\n        self.code = code\n        self.detail = detail\n        super().__init__(code + ": " + detail)\n\n\ndef _require(condition, code, detail):\n    if not condition:\n        raise AssemblyIdentityError(code, detail)\n\n\ndef _keys(value, expected, label):\n    _require(type(value) is dict and set(value) == set(expected),\n             "SCHEMA", label + " has missing/unknown keys or is not a dict")\n\n\ndef _hash(text):\n    import hashlib\n    return hashlib.sha256(text.encode("utf-8")).hexdigest()\n\n\ndef _json(value):\n    import json\n\n    def supported(item, depth=0):\n        _require(depth <= 64, "JSON", "data exceeds bounded JSON nesting")\n        if type(item) is dict:\n            _require(all(type(key) is str for key in item), "JSON", "JSON object keys must be strings")\n            for child in item.values():\n                supported(child, depth + 1)\n        elif type(item) in (list, tuple):\n            for child in item:\n                supported(child, depth + 1)\n        else:\n            _require(type(item) in (str, int, float, bool, type(None)),\n                     "JSON", "unsupported exact JSON value type")\n\n    supported(value)\n    try:\n        return json.dumps(value, sort_keys=True, separators=(",", ":"),\n                          ensure_ascii=True, allow_nan=False)\n    except (TypeError, ValueError, OverflowError) as exc:\n        raise AssemblyIdentityError("JSON", "non-canonical JSON data") from exc\n\n\ndef _copy(value):\n    import json\n    return json.loads(_json(value))\n\n\ndef _sha(value, label):\n    _require(type(value) is str and len(value) == 64\n             and all(c in "0123456789abcdef" for c in value),\n             "SHA256", label + " is not a lowercase SHA256")\n\n\ndef _strings(value, label):\n    _require(type(value) is dict and bool(value), "SCHEMA", label + " is empty/not a dict")\n    for key, item in value.items():\n        _require(type(key) is str and bool(key) and type(item) is str and bool(item),\n                 "SCHEMA", label + " requires nonempty string keys/values")\n\n\ndef _policy():\n    _sha(_POLICY_SOURCE_SHA256, "loader policy source pin")\n    return {\n        "version": POLICY_VERSION,\n        "source_sha256": _POLICY_SOURCE_SHA256,\n        "emitter_pins": dict(EMITTER_PINS),\n        "grammar": "numba-0.65.1-llvmlite-0.47.0-x86_64-elf-text.r2",\n        "exceptions": ["pickle-object-id-symbols", "cpucontext-symbol-and-reporting-asciz-address",\n                       "independently-bound-mpfr-export-dynamic-globals-and-linked-quad"],\n        "excluded_process_fields": list(EXCLUDED_PROCESS_FIELDS),\n    }\n\n\ndef _native_binding(value, process_id, build):\n    """Validate the closed receipt without discovering native authority.\n\n    The receiver\'s independently reconstructed expected context supplies the\n    parsed pinned-byte size/RVAs and live process mapping.  Complete receipt\n    equality is mandatory in validate_evidence; this structural check alone\n    cannot establish executable-section membership, forwarding or ownership.\n    """\n    _keys(value, ("schema", "pid", "creation_filetime", "module", "exports"), "native_binding")\n    _require(value["schema"] == NATIVE_BINDING_SCHEMA,\n             "BINDING_SCHEMA", "unsupported native binding")\n    for name in ("pid", "creation_filetime"):\n        _require(type(value[name]) is int and 0 < value[name] < 2**64,\n                 "BINDING_PROCESS", "positive exact native " + name + " required")\n    _require(value["pid"] == process_id, "BINDING_PROCESS", "binding/context PID differs")\n    module = value["module"]\n    _keys(module, ("path", "sha256", "base", "size"), "native_binding.module")\n    _require(type(MPFR_DLL_PATH) is str and module["path"] == MPFR_DLL_PATH == build["mpfr_dll"]\n             and module["sha256"] == MPFR_DLL_SHA256 == build["mpfr_dll_sha256"],\n             "BINDING_MODULE", "native module/build pin differs")\n    _require(type(module["base"]) is int and 0 < module["base"] < 2**64\n             and type(module["size"]) is int and 0 < module["size"] < 2**32\n             and module["base"] + module["size"] <= 2**64,\n             "BINDING_MODULE", "invalid native image range")\n    _keys(value["exports"], MPFR_EXPORTS, "native_binding.exports")\n    seen = set()\n    for name in MPFR_EXPORTS:\n        item = value["exports"][name]\n        _keys(item, ("address", "rva"), "native_binding.exports." + name)\n        _require(type(item["rva"]) is int and 0 < item["rva"] < module["size"]\n                 and type(item["address"]) is int and 0 < item["address"] < 2**64\n                 and item["address"] == module["base"] + item["rva"],\n                 "BINDING_EXPORT", "invalid/out-of-image native export " + name)\n        _require(item["rva"] not in seen, "BINDING_ALIAS", "aliased native exports refused")\n        seen.add(item["rva"])\n    return value\n\n\ndef _context(context):\n    # The native reporter uses tuples; transport uses JSON arrays. Canonicalise\n    # those containers only, preserving every key/value and all numeric types.\n    _require(type(context) is dict, "SCHEMA", "context is not a dict")\n    value = _copy(context)\n    _keys(value, CONTEXT_KEYS, "context")\n    _require(value["schema"] == CONTEXT_SCHEMA, "CONTEXT_VERSION", "unsupported context")\n    _require(type(value["process_id"]) is int and value["process_id"] > 0,\n             "PROCESS", "actual positive process PID required")\n    _keys(value["source_generation"],\n          ("composition_sha256", "profile_sha256", "manifest_sha256", "contract_sha256"),\n          "source_generation")\n    for name, sha in value["source_generation"].items():\n        _sha(sha, name)\n    _require(value["module_sha256"] == H3_SHA256\n             and value["certificate_sha256"] == CERT_SHA256,\n             "SEALED_SOURCE", "H3/certificate pin differs")\n    _require(value["emitter_pins"] == EMITTER_PINS,\n             "EMITTER_SOURCE", "unsupported/incomplete emitter pins")\n    pins = value["source_pins"]\n    _strings(pins, "source_pins")\n    for name, sha in pins.items():\n        _sha(sha, name)\n    required_pins = dict(EMITTER_PINS)\n    required_pins.update({\n        "assembly_identity.py": _POLICY_SOURCE_SHA256,\n        "private_heat_compiled_dot_r1.py": H3_SHA256,\n        "private_heat_certification_kernel_r1.py": CERT_SHA256,\n    })\n    for name, sha in required_pins.items():\n        matches = [item for path, item in pins.items()\n                   if path.replace("\\\\", "/").rsplit("/", 1)[-1] == name]\n        _require(matches == [sha], "EMITTER_SOURCE", "source_pins must contain unique " + name)\n    _require(value["route"] == "compiled", "ROUTE", "compiled observation required")\n    build = value["build"]\n    _keys(build, BUILD_KEYS, "build")\n    for name in ("compiled_assembly_sha256", "module_sha256", "mpfr_dll_sha256"):\n        _sha(build[name], "build." + name)\n    _require(build["module_sha256"] == H3_SHA256, "SEALED_SOURCE", "build module differs")\n    for name, expected in (("fastmath", False), ("disk_jit_cache", False), ("nogil", True)):\n        _require(type(build[name]) is bool and build[name] is expected,\n                 "BUILD_FLAGS", "unsupported " + name)\n    for name, expected in (("numba", "0.65.1"), ("llvmlite", "0.47.0"),\n                           ("gmpy2", "2.3.2"), ("mpfr", "MPFR 4.2.2")):\n        _require(type(build[name]) is str and build[name] == expected,\n                 "TOOLCHAIN", "unsupported " + name)\n    _require(type(build["signatures"]) is int and build["signatures"] == 4,\n             "SIGNATURE", "four compiled signatures required")\n    _require(type(build["mpfr_dll"]) is str and bool(build["mpfr_dll"]),\n             "NATIVE", "MPFR DLL path required")\n    _require(type(build["load_seconds"]) is float and build["load_seconds"] >= 0,\n             "BUILD_COST", "nonnegative finite float load_seconds required")\n    native = value["native_runtime"]\n    _keys(native, ("backend", "exact", "executable", "flags", "options", "python", "warnings"),\n          "native_runtime")\n    _require(native["backend"] == "gmpy2", "NATIVE", "gmpy2 backend required")\n    for name in ("executable", "python"):\n        _require(type(native[name]) is str and bool(native[name]), "NATIVE", name + " required")\n    _keys(native["exact"], ("binaries", "versions"), "native_runtime.exact")\n    _keys(native["exact"]["binaries"],\n          ("gmpy2:libgcc_s_seh-1.dll", "gmpy2:libgmp-10.dll", "gmpy2:libmpc-3.dll",\n           "gmpy2:libmpfr-6.dll", "gmpy2:libwinpthread-1.dll", "gmpy2_extension"),\n          "native binaries")\n    _strings(native["exact"]["binaries"], "native binaries")\n    _keys(native["exact"]["versions"],\n          ("exact_arithmetic", "gmp", "gmp_binary_scope", "gmpy2"), "native versions")\n    _strings(native["exact"]["versions"], "native versions")\n    _require(native["exact"]["binaries"]["gmpy2:libmpfr-6.dll"] == build["mpfr_dll"],\n             "NATIVE", "MPFR binary/build paths disagree")\n    _require(type(native["flags"]) is list and len(native["flags"]) == 18,\n             "NATIVE", "complete Python flags required")\n    for index, flag in enumerate(native["flags"]):\n        _require(type(flag) is (bool if index in (13, 16) else int),\n                 "NATIVE", "Python flag type differs")\n    for name in ("options", "warnings"):\n        _require(type(native[name]) is list and all(type(x) is str for x in native[name]),\n                 "NATIVE", name + " must contain strings")\n    _native_binding(value["native_binding"], value["process_id"], build)\n    return value\n\n\ndef _signatures(signatures):\n    _require(type(signatures) is list and len(signatures) == 4,\n             "SIGNATURE", "four ordered signature records required")\n    result = _copy(signatures)\n    for index, item in enumerate(result):\n        _keys(item, SIGNATURE_KEYS, "signature")\n        _require(item["function"] == FUNCTIONS[index]\n                 and item["signature"] == SIGNATURE_TEXTS[index],\n                 "SIGNATURE", "function/signature ABI or ordering differs")\n        for name in ("byte_start", "byte_end", "function_index", "signature_index"):\n            _require(type(item[name]) is int and item[name] >= 0,\n                     "SIGNATURE", name + " must be a nonnegative int")\n        _require(item["function_index"] == index and item["signature_index"] == 0,\n                 "SIGNATURE", "function/signature indices differ")\n        _require(item["byte_end"] > item["byte_start"], "SIGNATURE", "empty/reversed unit")\n        _sha(item["sha256"], "signature sha256")\n    return result\n\n\ndef source_signature_key(context, signatures):\n    """Exact cache guard; reuse only if this key and actual loader pins match.\n\n    The caller must supply the actual PID, current sealed source/build metadata\n    and dispatcher signatures; the observer does not discover or trust a cache.\n    """\n    return _hash(_json({"policy": _policy(), "context": _context(context),\n                        "signatures": _signatures(signatures)}))\n\n\ndef _unit(text, signature, process_id, native_binding):\n    import re\n    # ASCII was checked by observe; character offsets are exact UTF-8 offsets.\n    lines = text.splitlines(keepends=True)\n    starts = []\n    offset = 0\n    for line in lines:\n        starts.append(offset)\n        offset += len(line)\n    pickle_token = re.compile(r"\\.const\\.(pickledata|picklebuf)\\.([1-9][0-9]*)(\\.sha1)?")\n    cpu_token = re.compile(r"<numba\\.core\\.cpu\\.CPUContext object at 0x([0-9A-Fa-f]{16})>")\n    dynamic_token = re.compile(r"numba\\.dynamic\\.globals\\.([1-9a-f][0-9a-f]{0,15})(\\.[1-9][0-9]{0,3})?")\n    native_targets = {item["address"]: (name, item["rva"])\n                      for name, item in native_binding["exports"].items()}\n    dynamic_occurrences = {}\n    dynamic_targets = {}\n    pickle_ids = {}\n    pickle_occurrences = {}\n    cpu_occurrences = {}\n    replacements = []\n    definitions = {}\n    consumer_evidence = []\n    wrapper = None\n\n    def replacement(line_index, match, group, canonical, kind, role, symbol, target=None):\n        start = starts[line_index] + match.start(group)\n        end = starts[line_index] + match.end(group)\n        replacements.append({\n            "process_id": process_id,\n            "function_index": signature["function_index"],\n            "function": signature["function"],\n            "signature_index": signature["signature_index"],\n            "unit_byte_start": start, "unit_byte_end": end,\n            "byte_start": signature["byte_start"] + start,\n            "byte_end": signature["byte_start"] + end,\n            "line": line_index + 1, "kind": kind, "role": role,\n            "before": match.group(group), "after": canonical, "symbol": symbol,\n        })\n        if target is not None:\n            replacements[-1].update(export_name=target[0], export_rva=target[1],\n                                     instance=target[2])\n\n    for index, line in enumerate(lines):\n        body = line[:-1] if line.endswith("\\n") else line\n        # Wrapper ownership is taken from the actual assembly, not a summary.\n        if body.startswith("cfunc.") and body.endswith(":"):\n            wrapper = body[:-1]\n        if body.startswith(".Lfunc_end"):\n            wrapper = None\n        dm = list(dynamic_token.finditer(body))\n        if "numba.dynamic.globals" in body:\n            _require(len(dm) == 1 and body.count("numba.dynamic.globals") == 1,\n                     "DYNAMIC_GRAMMAR", "unrecognised/ambiguous dynamic global")\n            match = dm[0]\n            address_text, instance = match.groups()\n            symbol = match.group(0)\n            address = int(address_text, 16)\n            _require(address in native_targets, "DYNAMIC_TARGET", "unproved native target")\n            name, rva = native_targets[address]\n            target = (name, rva, instance or "")\n            canonical = name + "_rva_" + format(rva, "x")\n            role = None\n            if body == symbol + ":":\n                role = "definition"\n            elif body == "\\t.type\\t" + symbol + ",@object":\n                role = "type"\n            elif body == "\\t.weak\\t" + symbol:\n                role = "weak"\n            elif body == "\\t.size\\t" + symbol + ", 8":\n                role = "size"\n            elif re.fullmatch(r"\\tmovabsq\\t\\$" + re.escape(symbol) + r", %(rax|r15)", body):\n                role = "instruction-reference"\n            _require(role is not None, "DYNAMIC_GRAMMAR", "unsupported native global use/alias")\n            dynamic_occurrences.setdefault(symbol, []).append((index, role))\n            dynamic_targets[symbol] = (address, target)\n            replacement(index, match, 1, canonical, "mpfr-export-address", role, symbol, target)\n        pm = list(pickle_token.finditer(body))\n        if ".const.pickle" in body:\n            _require(len(pm) == 1 and body.count(".const.pickle") == 1,\n                     "PICKLE_GRAMMAR", "unrecognised/ambiguous pickle occurrence")\n            match = pm[0]\n            family, object_id, suffix = match.groups()\n            symbol = match.group(0)\n            _require(not suffix or family == "pickledata", "PICKLE_GRAMMAR", "buf.sha1 unsupported")\n            # Only entire, source-observed symbol positions are recognised.\n            role = None\n            if body == symbol + ":":\n                role = "definition"\n            elif body == "\\t.type\\t" + symbol + ",@object":\n                role = "type"\n            elif re.fullmatch(r"\\t.size\\t" + re.escape(symbol) + r", [1-9][0-9]*", body):\n                role = "size"\n            elif body == "\\t.quad\\t" + symbol:\n                role = "quad-reference"\n            elif body == "\\tmovabsq\\t$" + symbol + ", %" + (\n                    "rax" if family == "picklebuf" else "r8" if suffix else "rcx"):\n                role = "instruction-reference"\n            _require(role is not None, "PICKLE_GRAMMAR", "unsupported symbol use/alias: " + body)\n            pickle_ids.setdefault(object_id, str(len(pickle_ids) + 1))\n            pickle_occurrences.setdefault(symbol, []).append((index, role))\n            if role == "definition":\n                _require(symbol not in definitions, "PICKLE_DEFINITION", "duplicate definition")\n                definitions[symbol] = index\n            replacement(index, match, 2, pickle_ids[object_id], "pickle-object-id", role, symbol)\n        cm = list(cpu_token.finditer(body))\n        if "CPUContext" in body:\n            _require(len(cm) == 1 and body.count("CPUContext") == 1,\n                     "CPU_GRAMMAR", "unrecognised/ambiguous CPUContext occurrence")\n            match = cm[0]\n            address = match.group(1)\n            _require(int(address, 16) > 0, "CPU_GRAMMAR", "null object representation unsupported")\n            representation = match.group(0)\n            symbol = \'".const.\' + representation + \'"\'\n            role = None\n            if body == symbol + ":":\n                role = "definition"\n            elif body == "\\t.type\\t" + symbol + ",@object":\n                role = "type"\n            elif body == "\\t.size\\t" + symbol + ", 57":\n                role = "size"\n            elif body == \'\\t.asciz\\t"\' + representation + \'"\':\n                role = "reporting-payload"\n            elif body == "\\tmovabsq\\t$" + symbol + ", %rcx":\n                role = "reporting-reference"\n                wrapper_prefix = ("cfunc._ZN28private_heat_compiled_dot_r1"\n                                  + str(len(signature["function"])) + signature["function"] + "B")\n                _require(wrapper is not None and wrapper.startswith(wrapper_prefix),\n                         "CPU_CONSUMER", "reference outside corresponding cfunc wrapper")\n                tails = (\n                    "\\tmovabsq\\t$PyUnicode_FromString, %rax\\n\\tcallq\\t*%rax\\n"\n                    "\\tmovabsq\\t$PyErr_WriteUnraisable, %rbx\\n\\tmovq\\t%rax, %rdi\\n"\n                    "\\tmovq\\t%rdi, %rcx\\n\\tcallq\\t*%rbx\\n",\n                    "\\tmovabsq\\t$PyUnicode_FromString, %rax\\n\\tcallq\\t*%rax\\n"\n                    "\\tmovabsq\\t$PyErr_WriteUnraisable, %r14\\n\\tmovq\\t%rax, %rbx\\n"\n                    "\\tmovq\\t%rbx, %rcx\\n\\tcallq\\t*%r14\\n",\n                )\n                tail = "".join(lines[index + 1:index + 7])\n                _require(tail in tails, "CPU_CONSUMER", "reporting consumer sequence differs")\n                consumer_evidence.append({\n                    "process_id": process_id, "wrapper": wrapper,\n                    "symbol": symbol, "unit_byte_start": starts[index],\n                    "unit_byte_end": starts[index] + len(line) + len(tail),\n                    "byte_start": signature["byte_start"] + starts[index],\n                    "byte_end": signature["byte_start"] + starts[index] + len(line) + len(tail),\n                    "raw_text": line + tail,\n                    "consumer": ["PyUnicode_FromString", "PyErr_WriteUnraisable"],\n                })\n            _require(role is not None, "CPU_GRAMMAR", "unsupported CPUContext use/alias")\n            cpu_occurrences.setdefault(address, []).append((index, role))\n            replacement(index, match, 1, "0000000000000001", "cpucontext-address", role, symbol)\n\n    # Only source-observed declaration forms, with one exact pointer payload.\n    instances = {}\n    for symbol, occurrences in dynamic_occurrences.items():\n        for role in ("type", "weak", "definition", "size"):\n            _require(sum(found == role for _, found in occurrences) == 1,\n                     "DYNAMIC_DEFINITION", "missing/duplicate native " + role)\n        references = [i for i, role in occurrences if role == "instruction-reference"]\n        _require(bool(references), "DYNAMIC_REFERENCE", "unconsumed native global")\n        at = next(i for i, role in occurrences if role == "definition")\n        type_at = next(i for i, role in occurrences if role == "type")\n        address, target = dynamic_targets[symbol]\n        name, rva, instance = target\n        instances.setdefault(address, set()).add(instance)\n        prefix = ["\\t.type\\t" + symbol + ",@object\\n"]\n        if type_at + 1 < len(lines) and lines[type_at + 1] == \'\\t.section\\t.ldata,"awl",@progbits\\n\':\n            prefix.append(lines[type_at + 1])\n        declaration = prefix + ["\\t.weak\\t" + symbol + "\\n", "\\t.p2align\\t3, 0x0\\n",\n                                symbol + ":\\n", "\\t.quad\\t" + str(address) + "\\n",\n                                "\\t.size\\t" + symbol + ", 8\\n"]\n        _require(at == type_at + len(prefix) + 2\n                 and lines[type_at:type_at + len(declaration)] == declaration,\n                 "DYNAMIC_PAYLOAD", "native declaration/pointer/size/alignment link differs")\n        _require(next(i for i, role in occurrences if role == "weak") == at - 2\n                 and next(i for i, role in occurrences if role == "size") == at + 2,\n                 "DYNAMIC_DEFINITION", "native directives outside linked declaration")\n        payload = re.fullmatch(r"\\t.quad\\t([1-9][0-9]*)\\n", lines[at + 1])\n        _require(payload is not None, "DYNAMIC_PAYLOAD", "unsupported native pointer payload")\n        replacement(at + 1, payload, 1, name + "_rva_" + format(rva, "x"),\n                    "mpfr-export-pointer", "linked-quad-payload", symbol, target)\n        end = type_at + len(declaration)\n        consumer_evidence.append({\n            "process_id": process_id, "function_index": signature["function_index"],\n            "function": signature["function"], "signature_index": signature["signature_index"],\n            "symbol": symbol, "export_name": name, "export_rva": rva, "instance": instance,\n            "unit_byte_start": starts[type_at], "unit_byte_end": starts[end - 1] + len(lines[end - 1]),\n            "byte_start": signature["byte_start"] + starts[type_at],\n            "byte_end": signature["byte_start"] + starts[end - 1] + len(lines[end - 1]),\n            "raw_text": "".join(lines[type_at:end]), "consumer": "pinned-mpfr-function-address",\n            "references": [{"unit_byte_start": starts[i], "unit_byte_end": starts[i] + len(lines[i]),\n                            "byte_start": signature["byte_start"] + starts[i],\n                            "byte_end": signature["byte_start"] + starts[i] + len(lines[i]),\n                            "line": i + 1, "raw_text": lines[i]} for i in references],\n        })\n    for family in instances.values():\n        numbered = sorted(int(item[1:]) for item in family if item)\n        _require("" in family and numbered == list(range(1, len(numbered) + 1)),\n                 "DYNAMIC_INSTANCE", "missing/ambiguous native global instance linkage")\n\n    # Exact object declaration/body relationship, without interpreting payloads.\n    for object_id in pickle_ids:\n        data = ".const.pickledata." + object_id\n        sha1 = data + ".sha1"\n        buf = ".const.picklebuf." + object_id\n        _require(data in definitions and sha1 in definitions,\n                 "PICKLE_DEFINITION", "data/SHA1 definitions missing")\n        sizes = {}\n        for symbol in (data, sha1, buf):\n            occurrences = pickle_occurrences.get(symbol, [])\n            if symbol == buf and not occurrences:\n                continue\n            for role in ("definition", "type", "size"):\n                _require(sum(r == role for _, r in occurrences) == 1,\n                         "PICKLE_DEFINITION", "missing/duplicate " + role + " for " + symbol)\n            at = definitions[symbol]\n            _require(at >= 2 and lines[at - 2] == "\\t.type\\t" + symbol + ",@object\\n"\n                     and lines[at - 1] == "\\t.p2align\\t4, 0x0\\n",\n                     "PICKLE_DEFINITION", "unsupported declaration/alignment")\n            size_rows = [i for i, role in occurrences if role == "size"]\n            end = size_rows[0]\n            size_match = re.fullmatch(r"\\t.size\\t" + re.escape(symbol) + r", ([1-9][0-9]*)\\n", lines[end])\n            _require(size_match is not None, "PICKLE_DEFINITION", "malformed size")\n            sizes[symbol] = int(size_match.group(1))\n            if symbol != buf:\n                _require(end == at + 2 and re.fullmatch(r\'\\t.ascii\\t"(?:[^"\\\\\\n]|\\\\[^\\n])*"\\n\', lines[at + 1]) is not None,\n                         "PICKLE_PAYLOAD", "unsupported literal payload grammar")\n                if symbol == sha1:\n                    _require(sizes[symbol] == 20, "PICKLE_PAYLOAD", "SHA1 size must remain 20")\n            else:\n                expected = ["\\t.quad\\t" + data + "\\n", "\\t.long\\t" + str(sizes[data]) + "\\n",\n                            "\\t.zero\\t4\\n", "\\t.quad\\t" + sha1 + "\\n", "\\t.quad\\t0\\n",\n                            "\\t.long\\t0\\n", "\\t.zero\\t4\\n"]\n                _require(sizes[symbol] == 40 and lines[at + 1:end] == expected,\n                         "PICKLE_ALIAS", "buffer layout/data/SHA1 link differs")\n        for symbol in (data, sha1):\n            references = [(i, role) for i, role in pickle_occurrences[symbol]\n                          if role in ("quad-reference", "instruction-reference")]\n            expected_role = "quad-reference" if buf in definitions else "instruction-reference"\n            _require(len(references) == 1 and references[0][1] == expected_role,\n                     "PICKLE_REFERENCE", "missing/duplicate/unsupported data/SHA1 reference")\n            if buf in definitions:\n                expected_at = definitions[buf] + (4 if symbol == sha1 else 1)\n                _require(references[0][0] == expected_at,\n                         "PICKLE_ALIAS", "reference outside corresponding buffer")\n        if buf in definitions:\n            references = [role for _, role in pickle_occurrences[buf]\n                          if role in ("instruction-reference", "quad-reference")]\n            _require(references == ["instruction-reference"],\n                     "PICKLE_REFERENCE", "missing/duplicate/unsupported buffer reference")\n\n    expected_cpu = 0 if signature["function"] == "_four" else 1\n    _require(len(cpu_occurrences) == expected_cpu, "CPU_DEFINITION", "missing/extra context object")\n    for address, occurrences in cpu_occurrences.items():\n        _require(sorted(role for _, role in occurrences)\n                 == sorted(("type", "definition", "size", "reporting-payload", "reporting-reference")),\n                 "CPU_DEFINITION", "context def/ref/payload not one-to-one")\n        at = [i for i, role in occurrences if role == "definition"][0]\n        representation = "<numba.core.cpu.CPUContext object at 0x" + address + ">"\n        symbol = \'".const.\' + representation + \'"\'\n        expected = ["\\t.type\\t" + symbol + ",@object\\n", "\\t.p2align\\t4, 0x0\\n",\n                    symbol + ":\\n", \'\\t.asciz\\t"\' + representation + \'"\\n\',\n                    "\\t.size\\t" + symbol + ", 57\\n"]\n        _require(at >= 2 and lines[at - 2:at + 3] == expected,\n                 "CPU_DEFINITION", "context body/size/alignment differs")\n    _require(len(pickle_ids) == (4 if signature["function"] == "_classes" else 0),\n             "PICKLE_DEFINITION", "unexpected object family coverage")\n    replacements.sort(key=lambda item: item["unit_byte_start"])\n    transformed = []\n    cursor = 0\n    for item in replacements:\n        start, end = item["unit_byte_start"], item["unit_byte_end"]\n        _require(start >= cursor and text[start:end] == item["before"],\n                 "TRANSFORM", "overlap or raw offset mismatch")\n        transformed.extend((text[cursor:start], item["after"]))\n        cursor = end\n    transformed.append(text[cursor:])\n    return "".join(transformed), replacements, consumer_evidence\n\n\ndef _comparison_parts(policy, context, signatures, joins, units):\n    strict_context = _copy(context)\n    del strict_context["process_id"]\n    del strict_context["build"]["compiled_assembly_sha256"]\n    del strict_context["build"]["load_seconds"]\n    del strict_context["native_binding"]["pid"]\n    del strict_context["native_binding"]["creation_filetime"]\n    del strict_context["native_binding"]["module"]["base"]\n    for item in strict_context["native_binding"]["exports"].values():\n        del item["address"]\n    strict_signatures = _copy(signatures)\n    for item in strict_signatures:\n        del item["sha256"]\n    return {\n        "schema": "plan15.assembly-identity.r2", "policy": _copy(policy),\n        "context": strict_context, "signatures": strict_signatures,\n        "joins": _copy(joins),\n        "units": [{"function_index": item["function_index"],\n                   "function": item["function"], "signature_index": item["signature_index"],\n                   "comparison_sha256": item["comparison_sha256"]} for item in units],\n        "scientific_eligibility": False, "equivalence_claim": "NONE",\n    }\n\n\ndef observe(assembly: str, signatures: list[dict], context: dict) -> dict:\n    """Observe already-captured text; refuse unknown/missing grammar or identity.\n\n    Offsets are exact half-open UTF-8 byte ranges from the capture, not inferred\n    by splitting on function names. The actual one-byte LF joins are retained.\n    No permission to run this function or to compile science is implied by its\n    existence as a source candidate.\n    """\n    _require(type(assembly) is str and 0 < len(assembly) <= MAX_ASSEMBLY_BYTES and assembly.isascii(),\n             "RAW_TEXT", "nonempty ASCII emitted assembly required")\n    _require("\\r" not in assembly and "\\x00" not in assembly, "RAW_TEXT", "unsupported text encoding/newlines")\n    policy = _policy()\n    ctx = _context(context)\n    sigs = _signatures(signatures)\n    raw_sha = _hash(assembly)\n    _require(ctx["build"]["compiled_assembly_sha256"] == raw_sha,\n             "RAW_SHA256", "build/captured raw hash differs")\n    units, transformations, joins = [], [], []\n    cursor = 0\n    for index, item in enumerate(sigs):\n        start, end = item["byte_start"], item["byte_end"]\n        _require(end <= len(assembly) and start == cursor,\n                 "SIGNATURE_BOUNDARY", "gap/overlap/incomplete boundary")\n        piece = assembly[start:end]\n        _require(piece.startswith(\'\\t.file\\t"<string>"\\n\')\n                 and piece.endswith(\'\\t.section\\t".note.GNU-stack","",@progbits\\n\'),\n                 "SIGNATURE_BOUNDARY", "unit start/end emitter grammar differs")\n        _require(_hash(piece) == item["sha256"], "SIGNATURE_SHA256", "piece hash differs")\n        transformed, changes, consumers = _unit(piece, item, ctx["process_id"], ctx["native_binding"])\n        units.append({"function_index": item["function_index"], "function": item["function"],\n                      "signature_index": item["signature_index"], "raw_sha256": item["sha256"],\n                      "raw_utf8_bytes": len(piece), "comparison_sha256": _hash(transformed),\n                      "consumer_evidence": consumers})\n        transformations.extend(changes)\n        cursor = end\n        if index < len(sigs) - 1:\n            next_start = sigs[index + 1]["byte_start"]\n            _require(next_start == end + 1 and assembly[end:next_start] == "\\n",\n                     "SIGNATURE_BOUNDARY", "unsupported/missing joined-piece separator")\n            joins.append({"byte_start": end, "byte_end": next_start, "raw_text": "\\n"})\n            cursor = next_start\n    _require(cursor == len(assembly), "SIGNATURE_BOUNDARY", "uncovered raw suffix")\n    identity = _comparison_parts(policy, ctx, sigs, joins, units)\n    return {\n        "schema": RECORD_SCHEMA, "status": "OBSERVED", "scientific_eligibility": False,\n        "equivalence_claim": "NONE", "policy": policy, "context": ctx,\n        "signatures": sigs, "raw_text": assembly, "raw_sha256": raw_sha,\n        "raw_utf8_bytes": len(assembly), "joins": joins, "units": units,\n        "transformations": transformations, "comparison_sha256": _hash(_json(identity)),\n    }\n\n\ndef validate_evidence(record: dict, expected_context: dict) -> dict:\n    """Rebuild full evidence; expected_context comes from the actual process.\n\n    Return the complete validated record. There is no partial-valid state and\n    no trust in a caller-provided digest, transform map or process identity.\n    """\n    _keys(record, RECORD_KEYS, "observation record")\n    _require(record["schema"] == RECORD_SCHEMA and record["status"] == "OBSERVED",\n             "RECORD_VERSION", "unsupported status/schema")\n    expected = _context(expected_context)\n    _require(_json(record["context"]) == _json(expected), "CONTEXT_MISMATCH", "actual context differs")\n    rebuilt = observe(record["raw_text"], record["signatures"], expected)\n    _require(_json(record) == _json(rebuilt), "EVIDENCE_MISMATCH", "record differs from complete reconstruction")\n    return rebuilt\n\n\ndef comparison_identity(record: dict, expected_context: dict) -> dict:\n    """Return only a completely reconstructed emitted-text policy identity.\n\n    Receivers must supply the actual independently reconstructed expected_context;\n    the saved worker receipt cannot authorise itself. Raw signature ranges remain\n    exact identity fields, so an address/ID width change refuses comparison too.\n    """\n    _keys(record, RECORD_KEYS, "observation record")\n    value = validate_evidence(record, expected_context)\n    return _comparison_parts(value["policy"], value["context"], value["signatures"],\n                             value["joins"], value["units"])\n'


def _assembly_require(ok, message):
    if not ok:
        raise ValueError('Plan15 assembly observer: ' + message)


def _assembly_json(value):
    import json
    return json.loads(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False))


def _native_error(error):
    return dict(kind=type(error).__name__, code=str(getattr(error, 'code', 'NATIVE_BINDING'))[:100],
                message=str(error)[:1000])


def _native_binding_api():
    """Load only the source-frozen stdlib helper; import performs no query."""
    _assembly_binding()
    namespace = _state.get('native_binding_namespace')
    if namespace is None:
        _assembly_require(type(_NATIVE_BINDING_SOURCE) is str
            and sha256(_NATIVE_BINDING_SOURCE.encode('utf8')).hexdigest() == _NATIVE_BINDING_SHA256,
            'native binding helper is not source-frozen')
        namespace = {'__name__': 'plan15_native_binding_observer'}
        exec(compile(_NATIVE_BINDING_SOURCE, '<plan15-pinned-native-binding>', 'exec'), namespace)
        _state['native_binding_namespace'] = namespace
    return namespace


def _native_expected():
    """Read the contract-pinned PE metadata once; never load MPFR or H3."""
    expected = _state.get('native_expected_exports')
    if expected is None:
        ref = _assembly_binding()['observer']['native_library']
        started = perf_counter()
        expected = _native_binding_api()['read_expected_exports'](ref['path'], ref['sha256'])
        _state['native_expected_metadata_seconds'] = perf_counter()-started
        _state['native_expected_exports'] = expected
    return expected


def _native_admit_worker(worker, process_id):
    """Bind the actual ready interpreter, preserving existing launch admission."""
    _assembly_require(worker.native_bound is None, 'worker native handle already admitted')
    started = perf_counter()
    costs = worker.row.setdefault('native_binding_costs', dict(admission_seconds=0.,
        receiver_query_seconds=0., receiver_query_calls=0, component_times_overlap=True))
    try:
        bound = _native_binding_api()['open_admitted'](process_id, worker.process.pid,
                                                      worker.process._handle)
        worker.native_bound = bound  # cleanup owns it before any later operation can fail
        _assembly_require(bound.pid == process_id and type(bound.creation_filetime) is int
            and bound.creation_filetime > 0, 'actual admitted native process identity differs')
        worker.row['native_binding_parent'] = dict(receipt=None,
            owner_record=_assembly_json(bound.owner_record))
    finally:
        costs['admission_seconds'] = perf_counter()-started


def _native_accept_worker(worker, status):
    """At the existing pre-take row boundary, use only the retained live handle."""
    try:
        _assembly_require(type(status) is dict, 'worker candidate status absent')
        worker.row['candidate_heat_route'] = status  # retain full raw/partial evidence even if pre-take validation fails
        route = status.get('route')
        if route == 'NOT_OBSERVED' or type(route) is str and route.startswith('unavailable: '):
            return
        _assembly_require(route == 'compiled'
            and status.get('assembly_observation', {}).get('status') == 'OBSERVED',
            'worker compiled observation refused')
        bound = worker.native_bound
        _assembly_require(bound is not None and bound.pid == worker.row['pid'],
            'worker has no independently admitted native handle')
        expected, api = _native_expected(), _native_binding_api()
        supplied = status['assembly_observation']['evidence']['context']['native_binding']
        api['validate_receipt'](supplied, expected)
        if worker.native_receipt is None:
            costs = worker.row['native_binding_costs']
            started = perf_counter()
            try:
                receipt = bound.query(expected)
            finally:
                costs['receiver_query_seconds'] += perf_counter()-started
                costs['receiver_query_calls'] += 1
                worker.row['native_binding_parent']['owner_record'] = _assembly_json(bound.owner_record)
            worker.row['native_binding_parent']['receipt'] = _assembly_json(receipt)
            api['validate_receipt'](receipt, expected)
            _assembly_require(receipt['pid'] == bound.pid
                and receipt['creation_filetime'] == bound.creation_filetime,
                'live native receipt process identity differs')
            _assembly_require(supplied == receipt, 'worker pointers differ from live parent binding')
            registry = _state.setdefault('native_parent_registry', {})
            previous = registry.get(bound.pid)
            _assembly_require(previous is None or previous['receipt'] == receipt,
                'PID reused or parent native binding changed within this report')
            worker.native_receipt = _assembly_json(receipt)
            registry[bound.pid] = dict(receipt=_assembly_json(receipt),
                ownership=worker.row['native_binding_parent']['owner_record'], costs=costs)
        _assembly_require(supplied == worker.native_receipt,
            'worker changed its captured native binding')
    except Exception as error:
        worker.row['native_binding_error'] = _native_error(error)
        raise


def _native_close_worker(worker, *, preserve_error=False):
    bound = worker.native_bound
    if bound is None:
        return
    worker.native_bound = None
    failure = None
    try:
        bound.close()
    except Exception as error:
        failure = error
    try:
        owner_record = _assembly_json(bound.owner_record)
        if 'native_binding_parent' in worker.row:
            worker.row['native_binding_parent']['owner_record'] = owner_record
        registered = _state.get('native_parent_registry', {}).get(bound.pid)
        if registered is not None and registered['receipt'].get('creation_filetime') == bound.creation_filetime:
            registered['ownership'] = owner_record
    except Exception as error:
        if failure is None:
            failure = error
    if failure is not None:
        worker.row['native_binding_cleanup_error'] = _native_error(failure)
        if not preserve_error:
            raise failure


def parent_native_binding(process_id):
    """Return independently captured authority, never a worker-supplied context."""
    _assembly_require(type(process_id) is int and process_id > 0, 'actual process PID required')
    if process_id == os.getpid():
        receipt = _state.get('native_self_binding')
    else:
        record = _state.get('native_parent_registry', {}).get(process_id)
        receipt = None if record is None else record['receipt']
    _assembly_require(receipt is not None and receipt['pid'] == process_id,
        'independent parent native binding missing')
    return _assembly_json(receipt)


def native_binding_provenance(process_id):
    """Separate measured costs/ownership from the closed public binding receipt."""
    parent_native_binding(process_id)
    if process_id == os.getpid():
        return _assembly_json(dict(costs=_state['native_self_costs'],
            expected_metadata_seconds=_state.get('native_expected_metadata_seconds')))
    record = _state['native_parent_registry'][process_id]
    return _assembly_json(dict(owner_record=record['ownership'], costs=record['costs']))


def _native_live_token(module):
    import ctypes
    functions = []
    for name in _MPFR_EXPORT_NAMES:
        function = getattr(module, name)
        address = ctypes.cast(function, ctypes.c_void_p).value
        _assembly_require(type(address) is int and address > 0, 'loaded MPFR pointer absent')
        functions.append((name, id(function), address,
            tuple(id(kind) for kind in function.argtypes), id(function.restype)))
    return (id(module._MPFR), module._MPFR._handle, str(Path(module._MPFR_PATH).resolve()), tuple(functions))


def _native_capture_self(module):
    """Capture only the MPFR functions belonging to an already-used H3 module."""
    token = _native_live_token(module)
    receipt = _state.get('native_self_binding')
    if receipt is not None:
        _assembly_require(_state['native_self_token'] == token, 'local MPFR binding changed')
        return _assembly_json(receipt)
    expected, api = _native_expected(), _native_binding_api()
    _assembly_require(str(Path(module._MPFR_PATH).resolve()) == expected['path'],
        'loaded H3 MPFR path differs from pinned native library')
    started = perf_counter()
    try:
        receipt = api['capture_self'](expected, {name: getattr(module, name) for name in _MPFR_EXPORT_NAMES})
        api['validate_receipt'](receipt, expected)
        _assembly_require(receipt['pid'] == os.getpid() and token == _native_live_token(module),
            'local native binding changed while captured')
        _state['native_self_binding'] = _assembly_json(receipt)
        _state['native_self_token'] = token
    finally:
        _state['native_self_costs'] = dict(capture_seconds=perf_counter()-started,
            expected_metadata_seconds=_state.get('native_expected_metadata_seconds'),
            component_times_overlap=True)
    return _assembly_json(receipt)


def configure_assembly_observer(path, expected):
    """Bind passive reporting to the caller's already verified exact contract."""
    import json
    location = Path(path).resolve()
    _assembly_require(type(expected) is str and len(expected) == 64, 'contract hash missing')
    raw = location.read_bytes()
    _assembly_require(sha256(raw).hexdigest() == expected, 'contract bytes differ')
    request = json.loads(raw)
    _assembly_require(request['schema'] == 'plan15.current-control.r3'
        and request['comparison_policy_candidate'] is True
        and request['H3'] == 'CANDIDATE_NOT_ENABLED' and request['default_changed'] is False,
        'contract schema/authority differs')
    observer = request['assembly_observer']
    _assembly_require(set(observer) == {'schema', 'policy', 'emitter_sources', 'source_pins',
        'generation_files', 'adapter', 'native_binding_source', 'native_library',
        'prospective_native_bindings', 'prospective_rule_version'}
        and observer['schema'] == 'plan15.assembly-observer-binding.r2'
        and observer['prospective_native_bindings'] is True
        and observer['prospective_rule_version'] == 'plan15.native-binding.r1',
        'observer binding schema differs')
    native = observer['native_binding_source']
    library = observer['native_library']
    _assembly_require(set(native) == {'path', 'sha256'}
        and type(_NATIVE_BINDING_SOURCE) is str
        and native['sha256'] == _NATIVE_BINDING_SHA256
        and sha256(_NATIVE_BINDING_SOURCE.encode('utf8')).hexdigest() == _NATIVE_BINDING_SHA256,
        'embedded native binding differs or is not frozen')
    _assembly_require(set(library) == {'path', 'sha256'}
        and library['sha256'] == _ASSEMBLY_MPFR_SHA256
        and Path(library['path']).name.lower() == 'libmpfr-6.dll', 'native library differs')
    policy = observer['policy']
    _assembly_require(set(policy) == {'path', 'sha256'}
        and policy['sha256'] == _ASSEMBLY_POLICY_SHA256
        and sha256(_ASSEMBLY_POLICY_SOURCE.encode('utf8')).hexdigest() == _ASSEMBLY_POLICY_SHA256,
        'embedded policy differs')
    generation = request['generation_binding']
    _assembly_require(set(observer['generation_files']) == {'composition', 'profile', 'manifest'},
        'generation files incomplete')
    for kind, ref in observer['generation_files'].items():
        _assembly_require(ref['sha256'] == generation[kind + '_sha256'], 'generation reference differs')
    _assembly_require(observer['adapter']['sha256'] == generation['adapter_sha256'], 'adapter differs')
    emitters = observer['emitter_sources']
    _assembly_require(set(emitters) == {'cpu', 'pythonapi', 'base', 'config'}, 'emitter set differs')
    refs = [policy, native, library, observer['adapter'],
        *observer['generation_files'].values(), *emitters.values()]
    required = {str(Path(ref['path']).resolve()): ref['sha256'] for ref in refs}
    siblings = Path(__file__).resolve().parent
    required.update({str(Path(__file__).resolve()): generation['telemetry_sha256'],
        str(siblings / 'private_heat_compiled_dot_r1.py'): _ASSEMBLY_H3_SHA256,
        str(siblings / 'private_heat_certification_kernel_r1.py'): _ASSEMBLY_CERT_SHA256})
    _assembly_require(observer['source_pins'] == required, 'observer source closure differs')
    _assembly_require(all(request['pins'].get(name) == pin for name, pin in required.items()),
        'observer source outside contract closure')
    for name, pin in required.items():
        _assembly_require(_digest(name) == pin, 'source differs: ' + name)
    binding = dict(path=str(location), sha256=expected, observer=observer,
        source_generation={**{kind + '_sha256': generation[kind + '_sha256']
            for kind in ('composition', 'profile', 'manifest')}, 'contract_sha256': expected})
    previous = _state.get('assembly_binding')
    _assembly_require(previous is None or previous == binding, 'process cannot retarget its observer')
    for key, value in (('ATLAS_PLAN15_ASSEMBLY_CONTRACT', str(location)),
                       ('ATLAS_PLAN15_ASSEMBLY_CONTRACT_SHA256', expected)):
        _assembly_require(os.environ.get(key) in (None, value), 'inherited observer binding differs')
        os.environ[key] = value
    _state['assembly_binding'] = binding
    return binding


def _assembly_binding():
    """Workers inherit only the exact passive-observer reference, not new settings."""
    path = os.environ.get('ATLAS_PLAN15_ASSEMBLY_CONTRACT')
    expected = os.environ.get('ATLAS_PLAN15_ASSEMBLY_CONTRACT_SHA256')
    _assembly_require(path and expected, 'observer not explicitly bound')
    binding = _state.get('assembly_binding')
    if binding is None:
        return configure_assembly_observer(path, expected)
    _assembly_require(binding['path'] == str(Path(path).resolve()) and binding['sha256'] == expected,
        'observer reference changed')
    return binding


def _assembly_policy():
    namespace = _state.get('assembly_policy_namespace')
    if namespace is None:
        _assembly_require(sha256(_ASSEMBLY_POLICY_SOURCE.encode('utf8')).hexdigest() == _ASSEMBLY_POLICY_SHA256,
            'embedded policy bytes differ')
        namespace = {'__name__': 'plan15_assembly_identity_observer'}
        exec(compile(_ASSEMBLY_POLICY_SOURCE, '<plan15-pinned-assembly-policy>', 'exec'), namespace)
        namespace['_POLICY_SOURCE_SHA256'] = _ASSEMBLY_POLICY_SHA256
        namespace['MPFR_DLL_PATH'] = _ASSEMBLY_MPFR_PATH
        _state['assembly_policy_namespace'] = namespace
    return namespace


def _assembly_context(build, process_id, native_binding=None):
    binding = _assembly_binding()
    observer = binding['observer']
    native_runtime = _runtime()  # existing actual-runtime context read, never configure-time discovery
    _assembly_require(str(Path(native_runtime['exact']['binaries']['gmpy2:libmpfr-6.dll']).resolve())
        == str(Path(observer['native_library']['path']).resolve()), 'actual runtime MPFR path differs')
    return _assembly_json(dict(schema='plan15.assembly-context.r1', process_id=process_id,
        source_generation=binding['source_generation'], module_sha256=_ASSEMBLY_H3_SHA256,
        certificate_sha256=_ASSEMBLY_CERT_SHA256,
        emitter_pins={Path(ref['path']).name: ref['sha256'] for ref in observer['emitter_sources'].values()},
        source_pins=observer['source_pins'], route='compiled', build=build, native_runtime=native_runtime,
        native_binding=parent_native_binding(process_id) if native_binding is None else native_binding))


def _assembly_live_token(kernel, module):
    """Cheap loaded-seal/signature guard; disk pins are checked at trust boundaries."""
    root = Path(__file__).resolve().parent
    _assembly_require(Path(kernel.__file__).resolve() == root / 'private_heat_certification_kernel_r1.py'
        and kernel._H3_SHA256 == _ASSEMBLY_H3_SHA256, 'selected certificate differs')
    _assembly_require(getattr(module, '_H3_SEAL', None)
        == (str(root / 'private_heat_compiled_dot_r1.py'), _ASSEMBLY_H3_SHA256)
        and module._LOADED_SHA256 == _ASSEMBLY_H3_SHA256, 'loaded H3 seal differs')
    functions = module._COMPILED
    _assembly_require(len(functions) == 4 and sum(len(f.signatures) for f in functions) == 4
        and all(not f._can_compile for f in functions), 'compiled signature set differs')
    return (id(kernel), id(module), tuple((id(f), id(f.py_func.__code__),
        tuple((str(sig), id(f.overloads[sig])) for sig in f.signatures)) for f in functions),
        _native_live_token(module))


def _assembly_failure(error, partial):
    return dict(route='OBSERVATION_FAILED', pinned_sha256=_ASSEMBLY_H3_SHA256, build=None,
        assembly_observation=dict(status='FAIL', scientific_eligibility=False,
            error=dict(kind=type(error).__name__, message=str(error)), partial=partial))


def _candidate_heat_route():
    """Observe only existing H3 state; capture once, retain raw evidence on refusal."""
    kernel = sys.modules.get('private_heat_certification_kernel_r1')
    if kernel is None or not getattr(kernel, '_h3_route', None):
        return dict(route='NOT_OBSERVED', build=None)
    module, _ = kernel._h3_route[0]
    if module is None:
        return kernel.h3_status()  # cached unavailable state; never invokes a new initialisation
    cache = _state.get('assembly_cache')
    if cache is not None:
        if cache['status']['route'] == 'OBSERVATION_FAILED':
            return cache['status']
        try:
            _assembly_binding()
            _assembly_require(cache['token'] == _assembly_live_token(kernel, module),
                'loaded source/signatures changed after observation')
        except Exception as error:
            cache['status'] = _assembly_failure(error, cache['partial'])
        return cache['status']
    started = perf_counter()
    partial = dict(process_id=os.getpid(), scientific_eligibility=False, raw_capture_complete=False)
    cache = dict(status=_assembly_failure(ValueError('observation incomplete'), partial), partial=partial)
    _state['assembly_cache'] = cache  # no automatic retry, including after partial failure
    try:
        token = _assembly_live_token(kernel, module)
        binding = _assembly_binding()
        status = kernel.h3_status()
        partial['raw_build'] = status
        pieces, signatures, offset = [], [], 0
        for function_index, function in enumerate(module._COMPILED):
            for signature_index, signature in enumerate(function.signatures):
                text = function.inspect_asm(signature)
                raw = text.encode('utf8')
                signatures.append(dict(function_index=function_index, function=function.__name__,
                    signature_index=signature_index, signature=str(signature), byte_start=offset,
                    byte_end=offset + len(raw), sha256=sha256(raw).hexdigest()))
                pieces.append(text)
                offset += len(raw) + 1
        assembly = '\n'.join(pieces)
        partial.update(raw_text=assembly, signatures=signatures,
            raw_sha256=sha256(assembly.encode('utf8')).hexdigest(), source_generation=binding['source_generation'],
            raw_capture_complete=True)
        _assembly_require(partial['raw_sha256'] == status['build']['compiled_assembly_sha256'],
            'raw assembly differs from unchanged build_info')
        native_binding = _native_capture_self(module)
        partial['native_binding'] = native_binding
        partial['native_binding_costs'] = _assembly_json(_state['native_self_costs'])
        context = _assembly_context(status['build'], os.getpid(), native_binding)
        evidence = _assembly_policy()['observe'](assembly, signatures, context)
        partial['policy_evidence_without_raw_text'] = {key: value for key, value in evidence.items() if key != 'raw_text'}
        _assembly_require(token == _assembly_live_token(kernel, module), 'signatures changed while observing')
        for name, pin in binding['observer']['source_pins'].items():
            _assembly_require(_digest(name) == pin, 'source changed while observing: ' + name)
        partial['observation_seconds'] = perf_counter()-started
        cache.update(token=token, status=dict(status, assembly_observation=dict(status='OBSERVED',
            evidence=evidence, observation_seconds=partial['observation_seconds'],
            raw_utf8_bytes=len(assembly.encode('utf8')), new_compilations=0,
            native_binding_costs=_assembly_json(_state['native_self_costs']),
            includes_binding_capture_and_policy=True, scientific_eligibility=False)))
    except Exception as error:
        partial['observation_seconds'] = perf_counter()-started
        cache['status'] = _assembly_failure(error, partial)
    return cache['status']


def assembly_comparison_identity(evidence, build, process_id):
    """Receiver validates full evidence against its actual binding and admitted PID."""
    context = _assembly_context(build, process_id)
    policy = _assembly_policy()
    return policy['comparison_identity'](evidence, context)


def _worker():
    import traceback
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr                      # nothing but messages may reach the pipe

    def send(head, body=b''):
        stdout.write(_pack(head, body))
        stdout.flush()

    try:
        hello = _unpack(_receive(stdin))[0][1]
    except EOFError:
        return 0
    try:
        import psutil
        own, caller = psutil.Process(), psutil.Process(hello['caller'])
        threading.Thread(target=_watch, args=(psutil, caller), daemon=True).start()
        kernel = _select(hello)
        from atlas_tectonics.resources import WorkBudget
        head, body = _unpack(_receive(stdin))
        if head[0] != 'points':
            raise RuntimeError('Shared inputs out of order')
        shared = pickle.loads(body)
        points, ladder = shared['points'], shared['ladder']
        _set(shared['context'], shared['settings'])
        geometry, records = {}, {}
        while True:
            head, body = _unpack(_receive(stdin))
            if head[0] != 'faces':
                break
            for fid, (entry, record) in pickle.loads(body).items():
                if 'centre' not in entry:
                    entry['centre'] = points['power', fid]
                geometry[fid], records[fid] = entry, record
        if head[0] != 'begin':
            raise RuntimeError('Shared inputs out of order')
        prepared = dict(points=points, geometry=geometry, neumann=set(geometry), conductivity=shared['conductivity'])
        shared = head = body = None
        named = _confirm(hello)                  # every file loaded so far: the caller judges those it did not name
        loaded = len(sys.modules)
        info = own.memory_info()
        send(('ready', dict(pid=os.getpid(), files=named, settings=_settings(), private=info.private,
                            working_set=info.rss)))
    except EOFError:
        return 0
    except BaseException as error:
        send(('refused', '%s: %s' % (type(error).__name__, error), traceback.format_exc()[-6000:]))
        return 1
    moments = {}
    candidate_heat_route = None
    while True:
        try:
            head, body = _unpack(_receive(stdin))
        except EOFError:
            return 0
        _, index, fid = head
        try:
            began = perf_counter()
            entry, record = pickle.loads(body) if len(body) else (geometry[fid], records.get(fid))
            facts, value = _face_result(kernel, WorkBudget(WORKER_LEDGER), prepared, records, moments,
                                        fid, entry, record, ladder)
            facts['seconds'] = perf_counter()-began
            if candidate_heat_route is None or candidate_heat_route['route'] == 'NOT_OBSERVED':
                observed = _candidate_heat_route()
                if observed != candidate_heat_route:
                    facts['candidate_heat_route'] = observed
                    candidate_heat_route = observed
            elif candidate_heat_route['route'] == 'compiled':
                # Reuse only while the loaded seal and fixed signature objects agree.
                observed = _candidate_heat_route()
                if observed is not candidate_heat_route:
                    facts['candidate_heat_route'] = observed
                    candidate_heat_route = observed
            if len(sys.modules) != loaded:
                # A face loaded another module: a file the caller named must be the caller's,
                # and the caller is told of every other one before it takes this row.
                table = _confirm(hello)
                fresh = {path: digest for path, digest in table.items() if path not in named}
                if fresh:
                    facts['loaded'] = fresh
                    named.update(fresh)
                loaded = len(sys.modules)
            info = own.memory_info()
            facts.update(index=index, private_peak=info.peak_pagefile, working_set_peak=info.peak_wset)
        except BaseException as error:
            # Reported, never decided here: the caller computes this face itself.
            # Preserve passive partial evidence even when the scientific face failed.
            observed = _candidate_heat_route()
            send(('error', dict(index=index, face_id=fid, kind=type(error).__name__, text=str(error)[:2000],
                                traceback=traceback.format_exc()[-6000:], candidate_heat_route=observed)))
            continue
        send(('row', facts), value)
        head = body = entry = record = facts = value = None


if __name__ == '__main__':
    if sys.argv[1:] != ['worker'] or not sys.dont_write_bytecode:
        raise SystemExit('This file is a module; it runs as a script only as a worker of its own caller, with -B')
    raise SystemExit(_worker())
