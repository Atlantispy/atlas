"""Harness only (T/hs): cProfile inside heat reconstruction WORKER processes, nothing else.

Active only when HS_PROF_DIR is set and this process is `python -B
.../private_heat_functionals_parallel_r1.py worker`. It profiles the whole worker and
dumps <HS_PROF_DIR>/worker-<pid>.prof at normal interpreter exit; the worker leaves by
itself at EOF of its pipe. No module, attribute or code object of the heat stack is touched.
"""
import os
import sys

_dir = os.environ.get('HS_PROF_DIR')
if (_dir and len(sys.argv) == 2 and sys.argv[1] == 'worker'
        and os.path.basename(sys.argv[0]) == 'private_heat_functionals_parallel_r1.py'):
    import atexit
    import cProfile

    _profiler = cProfile.Profile()

    def _dump():
        _profiler.disable()
        _profiler.dump_stats(os.path.join(_dir, 'worker-%d.prof' % os.getpid()))

    atexit.register(_dump)
    _profiler.enable()
