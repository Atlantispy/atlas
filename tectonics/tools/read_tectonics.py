"""Bounded read-only W12 saved-result bridge; no simulation or HTTP server.

SPDX-License-Identifier: AGPL-3.0-only
Keep this tool outside the source-bound scientific package. The original SQLite
store is opened mode=ro; the existing ArrayStore reads a temporary consistent
snapshot because its constructor intentionally performs schema writes.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'atlas.tectonics-ui-result.v1'
MAX_REPORT = 2 << 20
MAX_STORE = 32 << 20
MAX_RESPONSE = 2 << 20
CAPABILITIES = dict(inspect=True, generate=False, cancel=False, resume=False)
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'src'))


class ReadError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _path(path, *, directory=False, maximum=None):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ReadError('INVALID_PATH', 'Parent traversal is not allowed.')
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ReadError('INVALID_PATH', 'Linked or reparse paths are not supported.')
    info = path.stat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ReadError('INVALID_PATH', 'The configured run directory is unavailable.')
    elif not stat.S_ISREG(info.st_mode) or maximum is not None and info.st_size > maximum:
        raise ReadError('INPUT_LIMIT', 'A required file is not regular or exceeds the reader limit.')
    return path


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ReadError('INVALID_REPORT', 'Repeated JSON keys are not supported.')
        result[key] = value
    return result


def _constant(_value):
    raise ReadError('INVALID_REPORT', 'Non-finite JSON values are not supported.')


def _read_json(path, maximum):
    path = _path(path, maximum=maximum)
    with path.open('rb') as stream:
        raw = stream.read(maximum+1)
    if len(raw) > maximum:
        raise ReadError('INPUT_LIMIT', 'The JSON input exceeds the reader limit.')
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)


def _snapshot(source, destination):
    """Bounded, consistent SQLite backup; never open the original for writing."""
    source = _path(source, maximum=MAX_STORE)
    if any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ReadError('RUN_BUSY', 'Close the native run before inspecting this saved result.')
    started = time.perf_counter()
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, timeout=2)) as original:
        original.execute('PRAGMA query_only=ON')
        original.execute('PRAGMA trusted_schema=OFF')
        original.execute('PRAGMA cache_size=-64')
        tables = original.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view','trigger')").fetchall()
        if set(tables) != {('settings','table'),('chunks','table'),('snapshots','table')}:
            raise ReadError('INVALID_STORE', 'The configured database is not a native ArrayStore.')
        page = original.execute('PRAGMA page_size').fetchone()[0]
        count = original.execute('PRAGMA page_count').fetchone()[0]
        if page*count > MAX_STORE:
            raise ReadError('INPUT_LIMIT', 'The native store exceeds the reader limit.')
        def progress(_status, _remaining, total):
            if total*page > MAX_STORE or time.perf_counter()-started > 10:
                raise ReadError('INPUT_LIMIT', 'The native snapshot exceeded its size or time limit.')
        with closing(sqlite3.connect(destination)) as temporary:
            temporary.execute('PRAGMA cache_size=-64')
            original.backup(temporary, pages=64, progress=progress, sleep=.01)


def _explanation():
    return dict(
        summary='Saved stationary column cooling, compaction and elastic-support result; no new simulation was run.',
        inputs=['Authored synthetic geology and stationary planar material columns.',
                'Prescribed cooling history, effective compaction traction and separate additional surface pressure.',
                'A finite pore-water/reservoir inventory and an explicit elastic support policy.'],
        calculations=['W01/W02 identify and sample the material columns.',
                      'W03 updates the declared cooling and drained compaction history.',
                      'W04 calculates one total elastic response relative to the initial reference.',
                      'This reader verifies saved fields, their completed-output marker and native dependencies.'],
        outputs=['Load components in pascals; displacement and surface change in metres.',
                 'Material thickness, grain volumes, void ratios and finite reservoir allocation.',
                 'The water-surface change is unknown where its saved validity mask is false.'],
        limits=['This is a synthetic 4 m by 2 m strip, not a global plate map or a calibrated region.',
                'The represented sediment stack and the supplied thermal plate have different depth supports.',
                'A saved scientific result is not the same thing as a browser project or a runnable restart.',
                'No generation, cancellation, resume, preset calibration or source migration is exposed.'],
        method_guide='tectonics/docs/HOW_TECTONICS_IS_MADE.md')


def _result(store, product, configuration, budget):
    import numpy as np
    from atlas_tectonics.assembly import read_product
    from atlas_tectonics.materials import _json
    from atlas_tectonics.w03_workflow import load_w03_columns

    if (type(product) is not dict or product.get('producer') != 'atlas-tectonics-column-assembly-v1'
            or product.get('route') != 'w04-support.v1'):
        raise ReadError('UNSUPPORTED_RESULT', 'This connection supports saved W12 column-assembly results only.')
    fields = read_product(store, product, budget=budget, expected_context=product['context'])
    definition = product['definition']
    plan_id = hashlib.sha256(_json(definition)).hexdigest()
    index = product['output_index']
    schedule = definition['schedule']
    if (plan_id != product['plan_id'] or type(index) is not int or not 0 <= index <= len(schedule)
            or definition['context'] != product['context']):
        raise ReadError('INVALID_RESULT', 'The saved assembly definition or output index differs.')
    key = hashlib.sha256(_json(dict(schema='atlas.w12-column-checkpoint.v1',plan_id=plan_id,index=index))).hexdigest()
    expected = dict(schema='atlas.w12-column-checkpoint.v1',plan_id=plan_id,
                    output_index=index,product_id=product['product_id'])
    marker = store.get(key, budget=budget)
    if (store.metadata(key) != expected or marker is None or set(marker) != {'commit'}
            or marker['commit'].shape != (0,) or marker['commit'].dtype != np.dtype('u1')
            or product['restart']['checkpoint_id'] != key):
        raise ReadError('INCOMPLETE_RESULT', 'The saved result has no matching completed native checkpoint.')
    state = load_w03_columns(store, product['native_state_id'], budget=budget)
    if state is None or json.loads(_json(state.descriptor())) != product['native_state_descriptor']:
        raise ReadError('INCOMPLETE_RESULT', 'A required native state is missing or differs.')
    if (state.time_s != product['time_s'] or state.material.epoch_id != product['epoch_id']
            or index and schedule[index-1]['time_s'] != state.time_s):
        raise ReadError('INVALID_RESULT', 'The saved result time or epoch differs from its native state.')
    for name, native in (('cohort_thickness_m',state.material.thickness_m),
            ('grain_volume_m3',state.compaction.grain_volume_m3),('void_ratio',state.compaction.void_ratio)):
        if not np.array_equal(fields[name],native):
            raise ReadError('INVALID_RESULT', 'Saved fields disagree with their native material state.')
    required = {'cohort_thickness_m','grain_volume_m3','void_ratio','reservoir_volume_m3',
                'support.values','support.reservoir_surface_known'}
    grid = state.material.grid
    if (set(fields) != required or grid.cells != configuration['cells']
            or fields['support.values'].shape != (grid.cells,8)
            or fields['support.reservoir_surface_known'].shape != (grid.cells,)
            or fields['support.reservoir_surface_known'].dtype.kind != 'b'):
        raise ReadError('UNSUPPORTED_RESULT', 'The saved field layout does not match this column viewer.')
    sampled = state.source_workflow.initial_samples.descriptor()
    context = product['context']
    if (context['spatial_frame_id'] != sampled['frame_id']
            or context['vertical_reference'] != state.compaction.depth_reference_id):
        raise ReadError('CONTEXT_MISMATCH', 'The result frame or vertical datum differs from native support.')
    support = dict(kind='planar-strip',frame_id=sampled['frame_id'],
        depth_reference_id=state.compaction.depth_reference_id,width_m=state.reference_width_m,
        cell_ids=[cell['cell_id'] for cell in sampled['cells']],
        cell_edges_m=(grid.origin_m+np.arange(grid.cells+1)*grid.spacing_m).tolist(),
        cell_centres_m=(grid.origin_m+(np.arange(grid.cells)+.5)*grid.spacing_m).tolist(),
        material_cohorts=[asdict(cohort) for cohort in state.material.cohorts],
        compaction_rows=[asdict(parcel) for parcel in state.compaction.parcels])
    result = {name:product[name] for name in ('product_id','producer','route','source_status','context',
        'time_s','epoch_id','output_index','native_state_id','plan_id')}
    result.update(support=support,fields={name:dict(spec=product['fields'][name],values=value.tolist())
        for name,value in fields.items()},provenance=dict(
            execution_id=product['execution_id'],definition=definition,
            native_descriptor=product['native_descriptor'],native_state_descriptor=product['native_state_descriptor'],
            accounts=product['accounts'],restart=product['restart'],restart_semantics=product['restart_semantics'],
            verified=dict(product=True,native_state=True,completed_output=True,source_runtime=True),
            read_only=True,simulation_run=False,store_access='mode=ro snapshot; temporary copy removed after decoding'),
        explanation=_explanation())
    return result


def read_run(directory, report_name='run-00001.json'):
    """Read one configured, closed native run; paths never come from HTTP here."""
    started = time.perf_counter()
    if type(report_name) is not str or re.fullmatch(r'run-[0-9]{5}\.json', report_name) is None:
        raise ReadError('INVALID_REPORT', 'Select a numbered native run report, not a path.')
    directory = _path(directory, directory=True)
    configuration = _read_json(directory/'case.json',65536)
    report = _read_json(directory/report_name,MAX_REPORT)
    expected_sources = {path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT/'tools/run_tectonics.py',ROOT/'examples/w12_column_case.py')}
    if (type(configuration) is not dict or set(configuration) != {'schema','cells','example_sources'}
            or configuration['schema'] != 'atlas.w12-public-run.v1'
            or type(configuration['cells']) is not int or not 5 <= configuration['cells'] <= 64
            or configuration['example_sources'] != expected_sources):
        raise ReadError('SOURCE_MISMATCH', 'The public case or example sources changed; saved results cannot be repinned.')
    if (type(report) is not dict or report.get('schema') != 'atlas.w12-public-run-report.v1'
            or report.get('status') not in ('PASS_SUPPORTED_NATIVE_PREFIX','PASS_SUPPORTED_SYNTHETIC_ASSEMBLY')
            or report.get('configuration') != configuration):
        raise ReadError('INVALID_REPORT', 'A matching completed native run report is required.')
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    budget = WorkBudget(128<<20)
    limits = StoreLimits(4096,8<<20,MAX_STORE,decoded_cache_bytes=65536,
                        max_manifest_bytes=1<<20,verified_cache_entries=32,sqlite_cache_bytes=65536)
    with budget.reserve(16<<20,category='ui-read-json-and-snapshot'), tempfile.TemporaryDirectory(prefix='atlas-read-') as temp:
        copied = Path(temp)/'native.sqlite'
        _snapshot(directory/'native.sqlite',copied)
        with ArrayStore(copied,limits=limits,budget=budget) as store:
            result = _result(store,report['product'],configuration,budget)
    if budget.reserved_bytes:
        raise ReadError('READER_ERROR', 'The reader did not release its owned resources.')
    result['provenance'].update(read_seconds=time.perf_counter()-started,
        peak_accounted_bytes=budget.statistics()['peak_reserved_bytes'],
        reader_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    response = dict(schema=SCHEMA,status='ok',capabilities=dict(CAPABILITIES),result=result)
    if len(json.dumps(response,ensure_ascii=True,allow_nan=False).encode('utf-8')) > MAX_RESPONSE:
        raise ReadError('OUTPUT_LIMIT', 'The result exceeds the bounded viewer response size.')
    return response


def response(directory, report_name='run-00001.json'):
    try:
        return read_run(directory,report_name)
    except ReadError as exc:
        code,message = exc.code,str(exc)
    except (ImportError,ModuleNotFoundError):
        code,message = 'DEPENDENCY_UNAVAILABLE','The configured scientific Python environment is unavailable.'
    except FileNotFoundError:
        code,message = 'MISSING_INPUT','The configured run report, case or native store is missing.'
    except (json.JSONDecodeError,UnicodeError,RecursionError,KeyError,TypeError,OverflowError):
        code,message = 'INVALID_REPORT','The saved report or native descriptor has an invalid format.'
    except sqlite3.Error:
        code,message = 'INVALID_STORE','The saved native database could not be read safely.'
    except OSError:
        code,message = 'READ_FAILED','The configured local result could not be read.'
    except Exception as exc:
        # Preserve failure, not a fabricated result. Do not expose arbitrary
        # local paths, SQL text or a traceback through the browser contract.
        from atlas_tectonics._validation import TectonicsError
        from atlas_tectonics.resources import MemoryLimitError
        from atlas_tectonics.storage import StoreError
        if isinstance(exc,MemoryLimitError):
            code,message = 'RESOURCE_LIMIT','The saved result exceeds the reader resource budget.'
        elif isinstance(exc,(TectonicsError,StoreError)):
            code,message = 'VERIFICATION_FAILED','Native source, runtime, fields or dependencies failed verification; no result was displayed.'
        else:
            code,message = 'READER_ERROR','The local result reader failed; no result was displayed.'
    return dict(schema=SCHEMA,status='error',error=dict(code=code,message=message))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True,type=Path)
    parser.add_argument('--report',default='run-00001.json')
    args = parser.parse_args()
    value = response(args.directory,args.report)
    print(json.dumps(value,ensure_ascii=True,allow_nan=False,separators=(',',':')))
    return 0 if value['status']=='ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
