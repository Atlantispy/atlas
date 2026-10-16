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


_INDEXED_RUNTIME_HELPERS = frozenset(('heat_payload_indexed_patch', 'mesh_tables', 'native_transfer', 'spatial_transfer', 'exterior_mesh_patch', 'mimetic_patch', 'spatial_indexed_patch', 'compact_store', 'partition_tables', 'partition_native_patch', 'workflow_transfer', 'geometry_transfer', 'spatial_workflow_patch', 'partition_workflow_patch', 'partition_store', 'partition_routing_patch', 'partition_routing_transform', 'pressure_indexed_patch', 'funding_transfer', 'continuation_transfer', 'materialise_endpoint', 'historical_admission', 'runtime_compatibility'))


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
            value = _take(kernel, detail, body, len(data), face_ids[index], seen, budget=budget,
                          cancelled=cancelled, work=work, retain=retain)
            if type(value) is str:
                return index, value
            rows[index], census[index], done[index] = value['row'], value['diagnostics'], True
            facts, row = detail, worker.row
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
            send(('error', dict(index=index, face_id=fid, kind=type(error).__name__, text=str(error)[:2000],
                                traceback=traceback.format_exc()[-6000:])))
            continue
        send(('row', facts), value)
        head = body = entry = record = facts = value = None


if __name__ == '__main__':
    if sys.argv[1:] != ['worker'] or not sys.dont_write_bytecode:
        raise SystemExit('This file is a module; it runs as a script only as a worker of its own caller, with -B')
    raise SystemExit(_worker())
