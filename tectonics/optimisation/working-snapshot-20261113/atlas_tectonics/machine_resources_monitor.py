"""This machine's resources and timings, as measured: one reading of cores, load and memory, the free-core rule, and
the holder of measured samples with its store. Every reader that sizes a pool, gates a start or prices a plan takes
its figures from here; resources_gate decides from a reading handed to it.

A figure is taken from samples in one order (this pass, then the run's earlier passes, then what is stored for this
machine) and none is assumed. Standard library and psutil only, and nothing of the package, so the chain driver and
the run queue can load this file by its path. Execution only: nothing here enters a result.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import deque
import json
import os
import platform

KEPT = 5    # samples kept for each name: the last five
STORE = 'machine-resources.json'
STORE_SCHEMA = 'atlas.machine-resources.r1'


def reported_cores():
    """psutil's count of physical cores, as it reports it (None where it cannot tell)."""
    import psutil
    return psutil.cpu_count(logical=False)


def machine_cores():
    """The machine's physical cores; half its logical CPUs where they cannot be told apart (only ever narrower)."""
    return reported_cores() or max(1, (os.cpu_count() or 1)//2)


def process_cpus():
    """The logical CPUs this process may use."""
    return getattr(os, 'process_cpu_count', os.cpu_count)() or 1


def launch_load(seconds=0.05):
    """One CPU sample of this length (percent busy); a launch takes it once and hands it to each of its pools."""
    import psutil
    return psutil.cpu_percent(interval=seconds)


def free_memory():
    """Free physical memory now, in bytes."""
    import psutil
    return psutil.virtual_memory().available


def machine_memory():
    """The machine's physical memory, in bytes."""
    import psutil
    return psutil.virtual_memory().total


def reading(load=None, seconds=0.05):
    """One reading of the machine: cores, logical CPUs, the load sample, the cores it keeps busy, and free and total
    memory. A caller that holds its launch's load sample hands it in, and only memory is read again.

    The free-core rule: each busy logical CPU is taken to occupy a physical core of its own, so eight busy threads
    on eight cores leave none free. A gate's free cores are the cores it counts less ``busy_cores``."""
    import psutil
    memory, logical = psutil.virtual_memory(), psutil.cpu_count() or 1
    load = launch_load(seconds) if load is None else load
    return {'physical_cores': machine_cores(), 'logical_cpus': logical, 'load_percent': load,
            'busy_cores': logical*load/100, 'available_bytes': memory.available, 'total_bytes': memory.total}


def median(values):
    ordered = sorted(values)
    return (ordered[(len(ordered)-1)//2]+ordered[len(ordered)//2])/2


_run = {}        # name: the last samples of this run's passes, this process's
_unsaved = {}    # name: this process's samples not yet in the store
_stored = None   # name: the store's samples for this machine, read once


class Timings:
    """One pass's measured samples, by name: (the pass's family, the kind of worker, the figure).

    A figure is the median of this pass's samples, else of the run's earlier passes', else of the stored ones; a
    peak is the largest of them, in the same order. None while there is none: the reader takes its neutral value.
    """
    def __init__(self):
        self._pass = {}

    def add(self, name, value):
        for kept in (self._pass, _run, _unsaved):
            kept.setdefault(name, deque(maxlen=KEPT)).append(value)

    def _seen(self, name, stored):
        for seen in (self._pass.get(name), _run.get(name), (_stored or {}).get(name) if stored is None else stored):
            if seen:
                return list(seen)
        return None

    def figure(self, name, stored=None):
        seen = self._seen(name, stored)
        return None if seen is None else median(seen)

    def peak(self, name, stored=None):
        seen = self._seen(name, stored)
        return None if seen is None else max(seen)


def _machine():
    """The facts that say which machine samples were measured on (those the profile records)."""
    try:
        cores, memory = reported_cores(), machine_memory() >> 30
    except Exception:
        cores = memory = None
    return dict(system=platform.system(), release=platform.release(), machine=platform.machine(),
                processor=platform.processor(), logical_cpus=os.cpu_count(), physical_cores=cores,
                memory_gib=memory)


def _key(name):
    return json.dumps(list(name) if isinstance(name, tuple) else name)


def _name(key):
    value = json.loads(key)
    return tuple(value) if isinstance(value, list) else value


def _read(path):
    """The store's samples by name if it is this machine's; empty if missing, unreadable or another machine's."""
    try:
        record = json.loads(path.read_bytes())
        if record.get('schema') != STORE_SCHEMA or record.get('machine') != _machine():
            return {}
        return {_name(key): [value for value in values[-KEPT:] if type(value) in (int, float)]
                for key, values in record['samples'].items() if type(values) is list}
    except Exception:
        return {}


def use_store(folder):
    """Read the store in ``folder`` once (the holder's third source); later calls change nothing."""
    global _stored
    if _stored is None:
        from pathlib import Path
        _stored = _read(Path(folder)/STORE)
    return _stored


def save_store(folder):
    """Add this process's new samples to the store in ``folder``: read again so that another process's samples
    survive, keep the last five a name, replace through this process's own temporary file. Never raises."""
    from pathlib import Path
    if not _unsaved:
        return True
    try:
        path = Path(folder)/STORE
        samples = {name: deque(values, maxlen=KEPT) for name, values in _read(path).items()}
        for name, values in _unsaved.items():
            samples.setdefault(name, deque(maxlen=KEPT)).extend(values)
        text = json.dumps({'schema': STORE_SCHEMA, 'machine': _machine(),
                           'samples': {_key(name): list(values) for name, values in samples.items()}},
                          sort_keys=True, indent=1, allow_nan=False)+'\n'
        temporary = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        temporary.write_text(text, encoding='utf-8', newline='\n')
        os.replace(temporary, path)
        _unsaved.clear()
        return True
    except Exception:
        return False
