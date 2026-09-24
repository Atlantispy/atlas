"""Synchronous bounded W12 execution for the managed local job owner.

SPDX-License-Identifier: AGPL-3.0-only
The caller owns directory validation, exclusive execution and durable job state.
This adapter preserves the original public runner's case and native identities.
Cancellation is cooperative at native checks, not a timed interruption guarantee.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
TOTAL_OUTPUTS = 3
ACCOUNTED_BYTES = 128 << 20
STORE_BYTES = 32 << 20


class _Cancellation:
    """Adapt the owner's callable to the existing native event contract."""

    def __init__(self, callback):
        self.callback = callback

    def is_set(self):
        return bool(self.callback())

    def check(self):
        if self.is_set():
            raise CancelledError('W12 job cancelled at a cooperative checkpoint')


def _native():
    # Keep imports out of manager startup and the source-bound package itself.
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'examples'), str(ROOT/'tools')]
    from atlas_tectonics.assembly import PreparedColumnAssembly
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    from w12_column_case import make_column_case
    from w12_graph import run_graph
    import numpy as np
    import scipy
    import blosc2
    import numba
    import shapely

    return SimpleNamespace(PreparedColumnAssembly=PreparedColumnAssembly,
        WorkBudget=WorkBudget, ArrayStore=ArrayStore, StoreLimits=StoreLimits,
        make_column_case=make_column_case, run_graph=run_graph, np=np,
        runtime=dict(python=sys.version, platform=platform.platform(),
            numpy=np.__version__, scipy=scipy.__version__, blosc2=blosc2.__version__,
            numba=numba.__version__, shapely=shapely.__version__))


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate case configuration key')
        result[key] = value
    return result


def _configuration(directory, cells, resume):
    if type(cells) is not int or not 5 <= cells <= 64:
        raise ValueError('cells must be an integer between 5 and 64')
    binding = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT/'tools/run_tectonics.py', ROOT/'examples/w12_column_case.py')}
    expected = dict(schema='atlas.w12-public-run.v1', cells=cells, example_sources=binding)
    path = directory/'case.json'
    if resume:
        with path.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('case configuration exceeds its bound')
        saved = json.loads(raw, object_pairs_hook=_pairs)
        if type(saved) is not dict or type(saved.get('cells')) is not int or saved != expected:
            raise ValueError('case/source binding differs; do not edit or repin the saved run')
        return saved
    directory.mkdir(parents=False, exist_ok=False)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(expected, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return expected


def _write_report(directory, report):
    # Serialise first: unsupported values must not leave a half-written report.
    encoded = json.dumps(report, indent=2, allow_nan=False)+'\n'
    if len(encoded.encode('utf-8')) > 2 << 20:
        raise ValueError('native run report exceeds the reader limit')
    for number in range(1, 10001):
        destination = directory/('run-%05d.json' % number)
        try:
            with destination.open('x', encoding='utf-8') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            return destination.name
        except FileExistsError:
            continue
    raise ValueError('run-report limit reached')


class _GraphPlan:
    """Pass native cancellation through the retained graph producer seam."""

    def __init__(self, plan, cancel, completed):
        self._plan, self._cancel, self._completed = plan, cancel, completed

    def __getattr__(self, name):
        return getattr(self._plan, name)

    def run(self, output_index=None):
        product = self._plan.run(output_index, cancel=self._cancel)
        self._plan.verify_product(product)
        self._completed(product)
        return product


def execute(directory: Path, *, cells: int, resume: bool, cancelled, progress) -> dict:
    """Execute three declared outputs and the existing final graph synchronously.

    Only verified completed commits produce report/progress references. Prefix
    reports remain immutable; graph success adds its own final report. Reports
    are consumable after this function closes its store, including on cancellation.
    Case construction, native verification and graph inspection have no callback
    inside every operation; cancellation therefore has no wall-clock latency bound.
    Native restored counts count visits, including prefix visits in later outputs.
    """
    if type(resume) is not bool or not callable(cancelled) or not callable(progress):
        raise TypeError('boolean resume and callable cancellation/progress are required')
    directory = Path(directory)
    config = _configuration(directory, cells, resume)
    cancel = _Cancellation(cancelled)
    started = time.perf_counter()
    budget = None
    statistics = dict(computed_outputs=0, restored_outputs=0)
    last_report = last_product = None
    completed_outputs = 0
    graph_result = None
    terminal = 'cancelled'

    def notify(phase):
        progress(dict(phase=phase, completed_outputs=completed_outputs,
            total_outputs=TOTAL_OUTPUTS, report=last_report,
            product_id=None if last_product is None else last_product['product_id']))

    try:
        cancel.check()
        native = _native()
        budget = native.WorkBudget(ACCOUNTED_BYTES)
        notify('preparing')
        cancel.check()
        case = native.make_column_case(cells=cells, budget=budget)
        cancel.check()
        source = case['provenance']
        context = dict(world_id='public-synthetic-control', snapshot_id='w12-columns-v1',
            calendar_id=source['epoch']['id'], spatial_frame_id=source['frame']['id'],
            vertical_reference=source['frame']['depth_reference_id'],
            scenario_id='stationary-cooling-compaction-support')
        limits = native.StoreLimits(4096, 8 << 20, STORE_BYTES, decoded_cache_bytes=65536,
            max_manifest_bytes=1 << 20, verified_cache_entries=32, sqlite_cache_bytes=65536)
        report = dict(schema='atlas.w12-public-run-report.v1',
            source_status='WORKING NON-CANON', public_example=source, configuration=config,
            runtime=native.runtime, limits=dict(accounted_bytes=ACCOUNTED_BYTES,
                store_bytes=STORE_BYTES, accepted_output_count=TOTAL_OUTPUTS,
                process_rss_measured=False), physical_acceptance=False,
            whole_world_generation=False)
        with native.ArrayStore(directory/'native.sqlite', limits=limits, budget=budget) as store:
            with native.PreparedColumnAssembly(case['initial'], case['initial_surface'],
                    case['support_policy'], case['schedule'], store=store, context=context,
                    source_id=source['source_id'], reservoir_weights=native.np.full(cells, 1./cells),
                    external_pressure_pa=native.np.zeros(cells), budget=budget, cancel=cancel) as plan:

                def committed(product):
                    nonlocal last_report, last_product, completed_outputs, statistics
                    # The graph may restore a cached producer without calling run.
                    # All publication paths explicitly reverify its native commit.
                    plan.verify_product(product)
                    index = product['output_index']
                    if type(index) is not int or not 0 <= index < TOTAL_OUTPUTS:
                        raise ValueError('native output outside the declared three-output case')
                    statistics = plan.statistics()
                    prefix = dict(report, status='PASS_SUPPORTED_NATIVE_PREFIX',
                        execution_path='committed native prefix; final graph not yet verified',
                        product=product, plan_statistics=statistics, storage=store.statistics(),
                        seconds=time.perf_counter()-started,
                        timing_scope='worker dependency loading, case construction, native execution and verification through this commit; excludes store close and report serialisation',
                        resources_at_commit=budget.statistics())
                    name = _write_report(directory, prefix)
                    last_product = deepcopy(product)
                    last_report = name
                    completed_outputs = index+1
                    notify('output_committed')

                try:
                    for index in (0, 1):
                        cancel.check()
                        notify('running_output_'+str(index))
                        committed(plan.run(index, cancel=cancel))
                    cancel.check()
                    notify('publishing_graph')
                    graph_result = native.run_graph(_GraphPlan(plan, cancel, committed),
                        graph_cache_root=directory/'g')
                    product = graph_result['product']
                    plan.verify_product(product)
                    if product['output_index'] != TOTAL_OUTPUTS-1:
                        raise ValueError('final graph did not publish the final native output')
                    if last_product is None or last_product['product_id'] != product['product_id']:
                        committed(product)
                    # Completion wins a late cancellation after the graph verified.
                    terminal = 'completed'
                finally:
                    statistics = plan.statistics()
            storage = store.statistics()
        if budget.reserved_bytes:
            raise AssertionError('assembly resource reservation leak')
        final = dict(report, status='PASS_SUPPORTED_SYNTHETIC_ASSEMBLY',
            execution_path='captured R11 contract / R24 executor / R12 graph cache',
            product=last_product, graph_result=graph_result, plan_statistics=statistics,
            storage=storage, seconds=time.perf_counter()-started,
            timing_scope='worker dependency loading, case construction, native/graph execution, verification and store close; excludes interpreter startup and report serialisation',
            released_resources=budget.statistics())
        last_report = _write_report(directory, final)
    except CancelledError:
        # Context managers have closed all native owners before this is returned.
        if budget is not None and budget.reserved_bytes:
            raise AssertionError('cancelled assembly resource reservation leak')
    notify(terminal)
    return dict(status=terminal, report=last_report,
        product_id=None if last_product is None else last_product['product_id'],
        completed_outputs=completed_outputs, total_outputs=TOTAL_OUTPUTS,
        computed_outputs=statistics['computed_outputs'], restored_outputs=statistics['restored_outputs'],
        statistics=statistics, plan_statistics=statistics, seconds=time.perf_counter()-started,
        peak_accounted_bytes=0 if budget is None else budget.statistics()['peak_reserved_bytes'])
