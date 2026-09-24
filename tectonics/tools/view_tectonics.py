"""Read-only native W12 history and calculated cross-section view adapter.

SPDX-License-Identifier: AGPL-3.0-only
One bounded snapshot and one selected output; never runs physics or repins jobs.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time

import read_tectonics as reader

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'atlas.tectonics-view.v1'
FIELDS = ('void_ratio', 'porosity', 'bulk_thickness_m', 'grain_volume_m3')
CAPABILITIES = dict(catalogue=True, section=True, generate=False, globe=False)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _adapters():
    paths = (Path(__file__).resolve(), ROOT/'tools/w12_section_geometry.py',
             ROOT/'tools/read_tectonics.py')
    return {path.name: hashlib.sha256(reader._path(path).read_bytes()).hexdigest()
            for path in paths}


def _inputs(directory, report_name):
    if type(report_name) is not str or not re.fullmatch(r'run-[0-9]{5}\.json', report_name):
        raise reader.ReadError('INVALID_REPORT', 'Select a numbered native report, not a path.')
    directory = reader._path(directory, directory=True)
    configuration = reader._read_json(directory/'case.json', 65536)
    report = reader._read_json(directory/report_name, reader.MAX_REPORT)
    expected_sources = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT/'tools/run_tectonics.py', ROOT/'examples/w12_column_case.py')}
    if (type(configuration) is not dict or set(configuration) != {'schema', 'cells', 'example_sources'}
            or configuration['schema'] != 'atlas.w12-public-run.v1'
            or type(configuration['cells']) is not int or not 5 <= configuration['cells'] <= 64
            or configuration['example_sources'] != expected_sources):
        raise reader.ReadError('SOURCE_MISMATCH', 'Saved case sources differ; no automatic rebind is allowed.')
    if (type(report) is not dict or report.get('schema') != 'atlas.w12-public-run-report.v1'
            or report.get('configuration') != configuration
            or report.get('status') not in {'PASS_SUPPORTED_NATIVE_PREFIX', 'PASS_SUPPORTED_SYNTHETIC_ASSEMBLY'}):
        raise reader.ReadError('INVALID_REPORT', 'A matching completed native report is required.')
    return directory, configuration, report['product']


@contextmanager
def _store(directory):
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    budget = WorkBudget(128 << 20)
    limits = StoreLimits(4096, 8 << 20, reader.MAX_STORE, decoded_cache_bytes=65536,
                        max_manifest_bytes=1 << 20, verified_cache_entries=32, sqlite_cache_bytes=65536)
    with budget.reserve(16 << 20, category='ui-view-json-and-snapshot'), tempfile.TemporaryDirectory(prefix='atlas-view-') as tmp:
        copied = Path(tmp)/'native.sqlite'
        reader._snapshot(directory/'native.sqlite', copied)
        with ArrayStore(copied, limits=limits, budget=budget) as store:
            yield store, budget
    if budget.reserved_bytes:
        raise reader.ReadError('READER_ERROR', 'The view adapter did not release its owned resources.')


def _metadata(store, product, execution_id, definition=None):
    from atlas_tectonics.assembly import _context
    if (type(product) is not dict or product.get('schema') != 'atlas.tectonics-product.v1'
            or product.get('producer') != 'atlas-tectonics-column-assembly-v1'
            or product.get('route') != 'w04-support.v1'
            or product.get('execution_id') != execution_id):
        raise reader.ReadError('VERIFICATION_FAILED', 'Saved product source, runtime or route differs.')
    _context(product.get('context'))
    pid = product.get('product_id')
    if (pid != _hash({key: value for key, value in product.items() if key != 'product_id'})
            or store.metadata(pid) != product):
        raise reader.ReadError('VERIFICATION_FAILED', 'Saved product metadata differs from its native identity.')
    own_definition = product['definition']
    if (product['plan_id'] != _hash(own_definition) or own_definition['context'] != product['context']
            or definition is not None and own_definition != definition):
        raise reader.ReadError('CONTEXT_MISMATCH', 'Saved times belong to different assembly definitions.')
    index = product['output_index']
    if type(index) is not int or not 0 <= index <= 2 or len(own_definition['schedule']) != 2:
        raise reader.ReadError('UNSUPPORTED_RESULT', 'This adapter supports the three-output public column case.')
    return own_definition


def _catalogue(store, anchor, execution_id, configuration, budget):
    import numpy as np
    definition = _metadata(store, anchor, execution_id)
    initial_time = anchor['native_state_descriptor']['binding']['reference_time_s']
    times = [initial_time] + [step['time_s'] for step in definition['schedule']]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in times):
        raise reader.ReadError('INVALID_RESULT', 'Saved output times must be finite.')
    if not times[0] < times[1] < times[2]:
        raise reader.ReadError('INVALID_RESULT', 'Saved output times must be strictly ordered.')
    entries, products, missing = [], {}, False
    for index, value in enumerate(times):
        key = _hash(dict(schema='atlas.w12-column-checkpoint.v1', plan_id=anchor['plan_id'], index=index))
        marker = store.metadata(key)
        if marker is None:
            missing = True
            entries.append(dict(output_index=index, time_s=value, availability='missing', product_id=None))
            continue
        if missing:
            raise reader.ReadError('INCOMPLETE_RESULT', 'The saved checkpoint prefix has a gap.')
        if (type(marker) is not dict or set(marker) != {'schema', 'plan_id', 'output_index', 'product_id'}
                or marker['schema'] != 'atlas.w12-column-checkpoint.v1'
                or marker['plan_id'] != anchor['plan_id'] or marker['output_index'] != index):
            raise reader.ReadError('INVALID_RESULT', 'A saved output marker differs from its schedule.')
        commit = store.get(key, budget=budget)
        if (commit is None or set(commit) != {'commit'} or commit['commit'].shape != (0,)
                or commit['commit'].dtype != np.dtype('u1')):
            raise reader.ReadError('INCOMPLETE_RESULT', 'A saved output lacks its complete native marker.')
        product = store.metadata(marker['product_id'])
        _metadata(store, product, execution_id, definition)
        if (product['output_index'] != index or product['time_s'] != value
                or product['epoch_id'] != anchor['epoch_id']
                or product['restart']['checkpoint_id'] != key
                or index and product['native_state_descriptor']['parent_state_id'] != products[index-1]['native_state_id']):
            raise reader.ReadError('INVALID_RESULT', 'Saved native time, epoch or parent linkage differs.')
        entries.append(dict(output_index=index, time_s=value, availability='committed', product_id=product['product_id']))
        products[index] = product
    if anchor['output_index'] not in products or products[anchor['output_index']] != anchor:
        raise reader.ReadError('INCOMPLETE_RESULT', 'The nominated report has no matching native completed output.')
    catalogue = dict(plan_id=anchor['plan_id'], context=anchor['context'], epoch_id=anchor['epoch_id'],
        source_status=anchor['source_status'], source_cells=configuration['cells'], times=entries,
        fields=list(FIELDS), supported_views=['column-section'],
        time_semantics='Declared native seconds in the identified epoch; no interpolation.',
        verification='Product metadata, source/runtime and completed markers checked; full arrays and native closure checked on selection.')
    catalogue['catalogue_id'] = _hash(catalogue)
    return catalogue, products


def read_view(directory, report_name='run-00001.json', *, action='catalogue',
              output_index=None, field='void_ratio', cell_start=0, cell_stop=None,
              expected_plan_id=None):
    if action not in {'catalogue', 'section'} or field not in FIELDS:
        raise reader.ReadError('INVALID_SELECTION', 'Select a supported view action and field.')
    if (output_index is not None and (type(output_index) is not int or not 0 <= output_index <= 2)
            or type(cell_start) is not int or cell_start < 0
            or cell_stop is not None and (type(cell_stop) is not int or cell_stop <= cell_start)
            or expected_plan_id is not None and (type(expected_plan_id) is not str or not re.fullmatch('[0-9a-f]{64}', expected_plan_id))):
        raise reader.ReadError('INVALID_SELECTION', 'The saved time, cell interval or plan selector is invalid.')
    started = time.perf_counter()
    adapters = _adapters()
    directory, configuration, anchor = _inputs(directory, report_name)
    from atlas_tectonics.reuse import ExecutionContext
    with _store(directory) as (store, budget), ExecutionContext() as execution:
        catalogue, products = _catalogue(store, anchor, execution.identity, configuration, budget)
        if expected_plan_id is not None and expected_plan_id != catalogue['plan_id']:
            raise reader.ReadError('CONTEXT_MISMATCH', 'The selected source plan changed; reload its catalogue.')
        answer = dict(schema=SCHEMA, status='ok', capabilities=dict(CAPABILITIES), catalogue=catalogue)
        if action == 'section':
            index = anchor['output_index'] if output_index is None else output_index
            if index not in products:
                raise reader.ReadError('MISSING_OUTPUT', 'That declared output has not been saved; no simulation was started.')
            if cell_start >= configuration['cells'] or cell_stop is not None and cell_stop > configuration['cells']:
                raise reader.ReadError('INVALID_SELECTION', 'The selected cells are outside the native strip.')
            from w12_section_geometry import build_section
            native = reader._result(store, products[index], configuration, budget)
            geometry = build_section(native, field=field, cell_start=cell_start, cell_stop=cell_stop)
            answer['view'] = dict(output_index=index, time_s=native['time_s'], epoch_id=native['epoch_id'],
                product_id=native['product_id'], native_state_id=native['native_state_id'],
                geometry=geometry, explanation=native['explanation'],
                provenance=native['provenance'])
            answer['view']['view_id'] = _hash(dict(product_id=native['product_id'],
                selection=geometry['selection'], field=field, adapters=adapters))
        execution.verify()
    if adapters != _adapters():
        raise reader.ReadError('SOURCE_MISMATCH', 'The view adapter changed during the read.')
    answer['provenance'] = dict(read_only=True, simulation_run=False,
        store_access='one mode=ro snapshot; temporary copy removed after decoding',
        adapters=adapters, read_seconds=time.perf_counter()-started,
        peak_accounted_bytes=budget.statistics()['peak_reserved_bytes'],
        selected_output_full_verification=action == 'section',
        loading='Metadata/markers for three declared times; full verification of one selected native output; only selected field/cells returned.')
    if len(json.dumps(answer, allow_nan=False).encode()) > reader.MAX_RESPONSE:
        raise reader.ReadError('OUTPUT_LIMIT', 'The selected view exceeds its response limit.')
    return answer


def response(directory=None, report_name='run-00001.json', *, root=None, job_id=None, **selection):
    try:
        lock = nullcontext()
        if root is not None:
            if directory is not None or job_id is None:
                raise reader.ReadError('INVALID_SELECTION', 'Choose one configured result source.')
            import tectonics_job as jobs
            _, job = jobs._paths(root, job_id)
            lock = jobs._lock(job/'worker.lock')
        elif directory is None or job_id is not None:
            raise reader.ReadError('INVALID_SELECTION', 'A configured result source is required.')
        with lock:
            if root is not None:
                jobs._request(job)
                state = jobs._state(job)
                if state['report'] is None:
                    raise reader.ReadError('MISSING_OUTPUT', 'This job has no saved report to inspect.')
                directory, report_name = job/'run', state['report']
            return read_view(directory, report_name, **selection)
    except reader.ReadError as exc:
        code, message = exc.code, str(exc)
    except FileNotFoundError:
        code, message = 'MISSING_INPUT', 'A configured saved input is missing.'
    except (ImportError, ModuleNotFoundError):
        code, message = 'DEPENDENCY_UNAVAILABLE', 'A required view dependency is unavailable.'
    except sqlite3.Error:
        code, message = 'INVALID_STORE', 'The saved native store could not be read safely.'
    except OSError:
        code, message = 'READ_FAILED', 'The configured local result could not be read.'
    except Exception as exc:
        import tectonics_job as jobs
        if isinstance(exc, jobs.JobError):
            code, message = exc.code, str(exc)
        else:
            code, message = 'VERIFICATION_FAILED', 'Saved metadata, geometry or native dependencies failed verification; no view was produced.'
    return dict(schema=SCHEMA, status='error', error=dict(code=code, message=message))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('catalogue', 'section'))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--directory', type=Path)
    source.add_argument('--root', type=Path)
    parser.add_argument('--job-id')
    parser.add_argument('--report', default='run-00001.json')
    parser.add_argument('--output-index', type=int)
    parser.add_argument('--field', default='void_ratio', choices=FIELDS)
    parser.add_argument('--cell-start', type=int, default=0)
    parser.add_argument('--cell-stop', type=int)
    parser.add_argument('--expected-plan-id')
    args = parser.parse_args()
    answer = response(args.directory, args.report, root=args.root, job_id=args.job_id,
        action=args.action, output_index=args.output_index, field=args.field,
        cell_start=args.cell_start, cell_stop=args.cell_stop, expected_plan_id=args.expected_plan_id)
    print(json.dumps(answer, allow_nan=False, separators=(',', ':')))
    return 0 if answer['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
