"""Own observer with a hook-free scope around the joined ALE compute call.

Execution instrumentation only; no native function, selector, budget, policy,
scientific argument or source-identity gate is replaced. The caller must keep
the existing external Windows-job guardian. During geometry its independent
cancel/RSS/free-memory enforcement remains active, but per-component Python
return counts and cooperative checks are intentionally not collected.
"""
from contextlib import contextmanager
import sys


class _Observer:
    def __init__(self, guard, stages, ticks, geometry):
        self.guard = guard
        self.monitoring = sys.monitoring
        self.tool = 3
        self.name = 'private-original-heat-control'
        self.started = {fn.__code__: name for fn, name in stages}
        self.returned = {fn.__code__: name for fn, name in ticks}
        self.geometry_code = geometry.__code__
        if self.geometry_code not in self.started:
            raise ValueError('The actual geometry function needs its original phase marker')
        self.codes = set(self.started) | set(self.returned)
        self.active = False
        self.suspended = False

    def on_start(self, code, offset):
        self.guard.phase(self.started[code])

    def on_return(self, code, offset, value):
        name = self.returned[code]
        self.guard.counts[name] = self.guard.counts.get(name, 0) + 1
        self.guard.check()

    def install(self):
        monitoring, tool = self.monitoring, self.tool
        if self.active or monitoring.get_tool(tool) is not None:
            raise RuntimeError('Local monitoring slot already occupied; no foreign tool removed')
        monitoring.use_tool_id(tool, self.name)
        self.active = True
        try:
            monitoring.register_callback(tool, monitoring.events.PY_START, self.on_start)
            monitoring.register_callback(tool, monitoring.events.PY_RETURN, self.on_return)
            for code in self.codes:
                events = monitoring.events.PY_START if code in self.started else 0
                events |= monitoring.events.PY_RETURN if code in self.returned else 0
                monitoring.set_local_events(tool, code, events)
        except BaseException:
            self.remove()
            raise

    def remove(self):
        if not self.active:
            return
        monitoring, tool = self.monitoring, self.tool
        if monitoring.get_tool(tool) != self.name:
            self.active = False
            raise RuntimeError('Local monitoring ownership changed; foreign tool left untouched')
        for code in self.codes:
            monitoring.set_local_events(tool, code, 0)
        monitoring.register_callback(tool, monitoring.events.PY_START, None)
        monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
        monitoring.free_tool_id(tool)
        self.active = False

    @contextmanager
    def geometry_scope(self):
        if not self.active or self.suspended:
            raise RuntimeError('One active, non-nested geometry observation scope required')
        # This is exactly the phase that PY_START would have recorded. Publish
        # it while the guardian and our ordinary observer are still active.
        self.guard.phase(self.started[self.geometry_code])
        self.remove()
        self.suspended = True
        try:
            self.guard.check(force=True)
            yield
        finally:
            self.suspended = False
            # A foreign tool claiming our released slot fails closed; never
            # clear its callbacks. Other slots/trace/profile hooks are never
            # touched and remain visible to the unchanged native selector.
            self.install()
        # On a body exception restore first, then preserve that exception.
        # On normal return honour cancellation before subsequent work.
        self.guard.check(force=True)


@contextmanager
def observe(guard, stages, ticks, *, joined, geometry):
    """Observe stages, releasing only our tool inside the explicit ALE seam.

    ``joined`` must be the actual module that owns _advance_current_interval,
    including a private derivative when one is used. A separately imported
    public fixture has a different ContextVar and cannot scope that derivative.
    """
    if (joined._advance_current_interval.__globals__.get('_ALE_COMPUTE_CONTEXT')
            is not joined._ALE_COMPUTE_CONTEXT):
        raise ValueError('Joined ALE context does not own the advancing function')
    observer = _Observer(guard, stages, ticks, geometry)
    observer.install()
    try:
        with joined.ale_compute_context(observer.geometry_scope):
            yield
    finally:
        observer.remove()
