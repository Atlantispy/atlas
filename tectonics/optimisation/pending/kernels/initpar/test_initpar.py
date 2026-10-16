"""Item 19 small identity test: serial vs parallel initial queries on a slice of the real admission.

Usage: python -B test_initpar.py OUTDIR NATIVE_ROOT IMPORT_ROOT [IMPORT_ROOT ...]
                                 [--supports=A:B] [--workers=W] [--batch=N] [--mutants | --serial-only]
  NATIVE_ROOT: a candidate tree built by build_runtime.py (e.g. T/ck/ip2/src).
  IMPORT_ROOTS: R/composed-r2/helpers and heat-repair source/tectonics/tests, as time_admission_parts.
Builds route (1)'s fixture and initial partition with the driver's literals, then measures the
components of supports[A:B] (serial order) with the admission's relative error, absolute width
(32000 m3 / all components) and leaf ceiling:
  serial          measure_initial_component, no pass;
  parallel        the same calls with an opened InitialParallel pass (W workers, batches of N);
  store-serial / store-parallel   cached_initial_component on two fresh raw stores;
  store-warm-serial / store-warm-parallel   no pass / the pass, each over its own byte copy of the
                  serial store: every query a hit; the pass must launch nothing; both stores unchanged;
  store-mixed-serial / store-mixed-parallel   no pass / the pass, each over its own store pre-filled
                  (no pass) with every third query: the pass skips hits, starts workers only after the
                  first miss (which the parent measures), retires passed batches; results and final
                  store bytes identical between the two;
  (hit results come back through JSON, so warm/mixed arms are compared with their own serial arm)
  --mutants adds checks that need no patching (a patched atlas_tectonics callable makes the
  execution context refuse the session: 'loaded implementation changed'):
  unmet-serial / unmet-parallel   leaf ceiling UNMET_LEAVES, so some components are genuinely unmet:
                  the serial call raises; the pass must refuse the unmet worker answer, close with
                  workers possibly running, and leave every later member serial (same results,
                  exceptions recorded as message + initial_accuracy);
  validator mutants   validated_initial_volume and InitialParallel._certified on the parallel arm's
                  real records, pristine (must accept) and altered one field at a time (must refuse);
  lifecycle       nested pass refused (outer stays active), re-entry refused, second start and a
                  foreign budget give None, an exception inside the pass closes it and clears active().
Every arm's results must equal its serial arm's: pickle bytes (types, key order, values) and
canonical JSON; both stores must be byte-identical. Writes OUTDIR/report.json. PYTHONHASHSEED=0.
--serial-only runs the serial arm alone and never imports the new module, so NATIVE_ROOT may be
an untransformed tree (e.g. R/composed-r2/src): its serial signature must equal the candidate's.
"""
import hashlib
import importlib
import json
import pickle
import shutil
import sys
import time
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace

import psutil

FIXTURE = {'pressure_space': 'q1-p0', 'material_quadrature': True}
MEASUREMENT_CACHE = {'chunk_bytes': 65536, 'max_array_bytes': 1 << 20, 'max_store_bytes': 128 << 20}
INITIAL_PARTITION = {'max_components': 4096}
PHYSICAL_VOLUME_ERROR = Q(32000)
MAX_LEAVES = 2**30
UNMET_LEAVES = 1000


def _option(argv, name, default):
    return next((item.split('=', 1)[1] for item in argv if item.startswith(name+'=')), default)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    argv = sys.argv[1:]
    span = _option(argv, '--supports', '17:31')
    workers, batch = int(_option(argv, '--workers', '2')), int(_option(argv, '--batch', '8'))
    mutants, serial_only = '--mutants' in argv, '--serial-only' in argv
    argv = [a for a in argv if not a.startswith('--')]
    out, native, roots = Path(argv[0]), Path(argv[1]).resolve(), [Path(p).resolve() for p in argv[2:]]
    out.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(native), *map(str, roots)]
    import atlas_tectonics
    if not Path(atlas_tectonics.__file__).resolve().is_relative_to(native):
        raise SystemExit('atlas_tectonics did not load from the native root')
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_dual_geometry as DG
    IP = None if serial_only else importlib.import_module('atlas_tectonics.integration_initial_parallel')
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.integration_dual_measures import policy_record
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    import i04_differential_fixture as F
    import private_heat_original_spatial_r1 as spatial
    import probe_heat_original_connected_r9 as D
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    report = dict(native=str(native), roots=list(map(str, roots)), supports=span, workers=workers, batch=batch,
                  max_workers=None if IP is None else IP.MAX_WORKERS, arms={})
    a, b = map(int, span.split(':'))
    with ExecutionContext('reference') as reference, \
            F.radial_differential_fixture(budget=budget, **FIXTURE) as case:
        current, partition = spatial.initial_partition(case, **INITIAL_PARTITION)
        relative = W._decode(policy_record(D.POLICY)['initial_relative_error'])
        count = sum(len(s.record()['components']) for s in partition.supports)
        width = PHYSICAL_VOLUME_ERROR/max(1, count)
        supports = list(partition.supports)[a:b]
        jobs = [(s, part['logical_cell_id']) for s in supports for part in s.record()['components']]
        report.update(components_total=count, jobs=len(jobs), relative_error=str(relative), width=str(width))
        print('jobs', len(jobs), 'of', count, flush=True)

        def measure(pass_=None, store=None, leaves=MAX_LEAVES):
            started = None
            if pass_ is not None:
                started = pass_.start(SimpleNamespace(supports=supports), budget=budget, relative_error=relative,
                                      max_width_m3=width, max_leaves=leaves)
                if started is None:
                    raise SystemExit('pass did not open: %s' % pass_.report['note'])
            results = []
            for support, cell in jobs:
                extra = {} if started is None else dict(_volume=started)
                try:
                    if store is None:
                        results.append(DG.measure_initial_component(support, cell, relative_error=relative,
                            absolute_width_m3=width, max_leaves_per_query=leaves, budget=budget, **extra))
                    else:
                        results.append(DG.cached_initial_component(support, cell, relative_error=relative,
                            absolute_width_m3=width, max_leaves_per_query=leaves, budget=budget,
                            store=store, context=reference, **extra))
                except V.VolumeError as error:
                    results.append(('VolumeError', str(error), getattr(error, 'initial_accuracy', None)))
            if started is not None:
                started.finish()
            return results

        def signature(results):
            return dict(pickle=hashlib.sha256(pickle.dumps(results, protocol=5)).hexdigest(),
                        json=hashlib.sha256(json.dumps(results, default=str, sort_keys=True,
                                                       separators=(',', ':')).encode()).hexdigest())

        def arm(name, pass_=None, store_path=None, leaves=MAX_LEAVES, ref='serial', keep=None):
            begun, cpu = time.perf_counter(), time.process_time()
            if store_path is None:
                results = measure(pass_, leaves=leaves)
            else:
                with ArrayStore(store_path, StoreLimits(**MEASUREMENT_CACHE), Compression(codec='raw'),
                                budget=budget) as store:
                    results = measure(pass_, store)
            row = dict(signature(results), wall_s=round(time.perf_counter()-begun, 2),
                       parent_cpu_s=round(time.process_time()-cpu, 2), ref=ref,
                       errors=sum(type(item) is tuple for item in results))
            if keep is not None:
                keep.extend(results)
            if store_path is not None:
                row['store_sha256'] = _sha(store_path)
            if pass_ is not None:
                row['pass'] = pass_.report
            report['arms'][name] = row
            print(name, {k: v for k, v in row.items() if k != 'pass'},
                  None if pass_ is None else {k: pass_.report.get(k) for k in (
                      'batches', 'first_launch', 'adopted', 'serial', 'skipped', 'retired', 'refused', 'note',
                      'cause')}, flush=True)
            return row

        def opened():
            return IP.InitialParallel(workers=workers, budget=budget, context=reference, batch_jobs=batch)

        def validators(results):
            from atlas_tectonics.integration_parallel_results import canonical
            fit = SimpleNamespace(admits_work=lambda work: True)
            other = hashlib.sha256(b'another').hexdigest()
            rows, picked = {}, {}
            for (support, cell), result in zip(jobs, results, strict=True):
                query = result['queries'][-1]
                kind = 'positive' if W._decode(query['upper_m3']) > 0 else 'empty'
                picked.setdefault(kind, (support, cell, query))
            for kind, (support, cell, query) in picked.items():
                raw = support.record()
                request = canonical(IP.initial_request(support, cell, raw['start_time_s'], width,
                                                       MAX_LEAVES, relative))
                low = W._decode(query['lower_m3'])
                record_mutants = {
                    'pristine': {}, 'extra-key': {'unexpected': 1}, 'cell': {'logical_cell_id': other},
                    'support': {'support_id': other}, 'time': {'time_s': G._qtext(Q(1))},
                    'relative': {'relative_error': G._qtext(2*relative)}, 'width': {'max_width_m3': G._qtext(2*width)},
                    'max-leaves': {'max_leaves': MAX_LEAVES-1}, 'leaves-over': {'leaves': MAX_LEAVES+1},
                    'leaves-zero': {'leaves': 0}, 'met-text': {'met': 'true'}, 'work-negative': {'work_units': -1},
                    'lower-negative': {'lower_m3': G._qtext(Q(-1))},
                    'bound-negative': {'relative_error_bound': G._qtext(Q(-1, 3))}}
                missing = {'missing-met': 'met', 'missing-bound': 'relative_error_bound'}
                certified_mutants = {
                    'pristine': {}, 'cell': {'logical_cell_id': other}, 'support': {'support_id': other},
                    'endpoint': {'endpoint': 'end'}, 'time': {'time_s': G._qtext(Q(1))},
                    'relative': {'relative_error': G._qtext(2*relative)}, 'width': {'max_width_m3': G._qtext(2*width)},
                    'met': {'met': False}, 'max-leaves': {'max_leaves': MAX_LEAVES-1},
                    'leaves-over': {'leaves': MAX_LEAVES+1}, 'leaves-zero': {'leaves': 0},
                    'bound': {'relative_error_bound': G._qtext(Q(1, 3))},
                    }
                if query['lower_m3'] != query['upper_m3']:  # swapping equal bounds is no mutation
                    certified_mutants['inverted'] = {'lower_m3': query['upper_m3'], 'upper_m3': query['lower_m3']}
                if kind == 'positive':
                    certified_mutants.update({
                        'witness-over': {'positive_witness_m3': G._qtext(low+1)},
                        'witness-zero': {'positive_witness_m3': G._qtext(Q(0))},
                        'witness-point': {'positive_witness_point_m': None}})
                validated = {}
                for name, change in record_mutants.items():
                    validated[name] = IP.validated_initial_volume({**query, **change}, request, fit)
                for name, key in missing.items():
                    validated[name] = IP.validated_initial_volume(
                        {k: v for k, v in query.items() if k != key}, request, fit)
                certified = {name: IP.InitialParallel._certified({**query, **change}, support, cell, raw, width,
                                                                 MAX_LEAVES, relative)
                             for name, change in certified_mutants.items()}
                rows[kind] = dict(cell=cell, validated=validated, certified=certified,
                                  ok=all(value is (name == 'pristine') for name, value in validated.items())
                                  and all(value is (name == 'pristine') for name, value in certified.items()))
            print('validators', {k: v['ok'] for k, v in rows.items()}, flush=True)
            return rows

        def lifecycle():
            checks = {}
            outer = opened()
            with outer:
                checks['active_is_outer'] = IP.active() is outer
                try:
                    with opened():
                        checks['nested_refused'] = False
                except RuntimeError:
                    checks['nested_refused'] = True
                checks['outer_still_active'] = IP.active() is outer
                try:
                    with outer:
                        checks['reentry_refused'] = False
                except RuntimeError:
                    checks['reentry_refused'] = True
                checks['still_active_after_reentry'] = IP.active() is outer
                checks['foreign_budget_none'] = outer.start(
                    SimpleNamespace(supports=supports[:1]), budget=WorkBudget(1 << 30), relative_error=relative,
                    max_width_m3=width, max_leaves=MAX_LEAVES) is None
                first = outer.start(SimpleNamespace(supports=supports[:1]), budget=budget, relative_error=relative,
                                    max_width_m3=width, max_leaves=MAX_LEAVES)
                checks['second_start_none'] = outer.start(
                    SimpleNamespace(supports=supports[:1]), budget=budget, relative_error=relative,
                    max_width_m3=width, max_leaves=MAX_LEAVES) is None
                checks['first_start_opened'] = first is outer
            checks['closed_after_exit'] = outer.closed and outer.session is None
            checks['active_none_after_exit'] = IP.active() is None
            failing = opened()
            try:
                with failing:
                    failing.start(SimpleNamespace(supports=supports[:2]), budget=budget, relative_error=relative,
                                  max_width_m3=width, max_leaves=MAX_LEAVES)
                    raise KeyError('inside the pass')
            except KeyError:
                pass
            checks['closed_after_exception'] = failing.closed and failing.session is None
            checks['active_none_after_exception'] = IP.active() is None
            print('lifecycle', checks, flush=True)
            return checks

        serial = arm('serial')
        if serial_only:
            reference.verify_boundary()
            report['loaded_new_module'] = 'atlas_tectonics.integration_initial_parallel' in sys.modules
            (out/'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf8')
            print(json.dumps(dict(serial={k: serial[k] for k in ('pickle', 'json')},
                                  loaded_new_module=report['loaded_new_module'])))
            return
        parallel_results = []
        with opened() as pass_:
            arm('parallel', pass_, keep=parallel_results)
        arm('store-serial', store_path=out/'serial.sqlite')
        with opened() as pass_:
            arm('store-parallel', pass_, store_path=out/'parallel.sqlite')
        for sidecar in ('-wal', '-journal', '-shm'):
            if (out/('serial.sqlite'+sidecar)).exists():
                raise SystemExit('serial store not closed: ' + sidecar)
        shutil.copyfile(out/'serial.sqlite', out/'warm-s.sqlite')
        shutil.copyfile(out/'serial.sqlite', out/'warm-p.sqlite')
        warm_serial = arm('store-warm-serial', store_path=out/'warm-s.sqlite', ref='store-warm-serial')
        with opened() as pass_:
            warm = arm('store-warm-parallel', pass_, store_path=out/'warm-p.sqlite', ref='store-warm-serial')
        serial_store = report['arms']['store-serial']['store_sha256']
        report['warm_stores_unchanged'] = warm['store_sha256'] == warm_serial['store_sha256'] == serial_store
        report['warm_nothing_launched'] = (warm['pass']['batches'] == 0 and warm['pass']['adopted'] == 0
                                           and warm['pass']['stats']['started'] == 0)
        for name in ('mixed-s', 'mixed-p'):
            with ArrayStore(out/(name+'.sqlite'), StoreLimits(**MEASUREMENT_CACHE), Compression(codec='raw'),
                            budget=budget) as store:
                for support, cell in jobs[::3]:
                    DG.cached_initial_component(support, cell, relative_error=relative, absolute_width_m3=width,
                        max_leaves_per_query=MAX_LEAVES, budget=budget, store=store, context=reference)
        mixed_serial = arm('store-mixed-serial', store_path=out/'mixed-s.sqlite', ref='store-mixed-serial')
        with opened() as pass_:
            mixed = arm('store-mixed-parallel', pass_, store_path=out/'mixed-p.sqlite', ref='store-mixed-serial')
        first_miss = next(index for index in range(len(jobs)) if index % 3)
        report['mixed_first_miss'] = first_miss
        report['mixed_stores_identical'] = mixed['store_sha256'] == mixed_serial['store_sha256']
        report['mixed_starts_after_first_miss'] = (mixed['pass']['first_launch'] == first_miss+1
                                                   and mixed['pass']['skipped'] == first_miss
                                                   and mixed['pass']['retired'] > 0 and mixed['pass']['adopted'] > 0)
        if mutants:
            arm('unmet-serial', leaves=UNMET_LEAVES, ref='unmet-serial')
            with opened() as pass_:
                arm('unmet-parallel', pass_, leaves=UNMET_LEAVES, ref='unmet-serial')
            report['validators'] = validators(parallel_results)
            report['lifecycle'] = lifecycle()
        reference.verify_boundary()
    names = list(report['arms'])
    report['identical'] = {name: {key: report['arms'][name][key] == report['arms'][report['arms'][name]['ref']][key]
                                  for key in ('pickle', 'json')} for name in names}
    report['stores_identical'] = report['arms']['store-serial']['store_sha256'] == report['arms']['store-parallel']['store_sha256']
    report['stores_results_identical'] = (report['arms']['store-serial']['pickle'] == report['arms']['store-parallel']['pickle'])
    report['peak_working_set_mib'] = round(psutil.Process().memory_info().peak_wset/2**20)
    (out/'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf8')
    print(json.dumps(dict(identical=report['identical'], stores_identical=report['stores_identical'],
                          validators={k: v['ok'] for k, v in report.get('validators', {}).items()},
                          lifecycle=all(report.get('lifecycle', {}).values()),
                          warm_stores_unchanged=report.get('warm_stores_unchanged'),
                          warm_nothing_launched=report.get('warm_nothing_launched'),
                          mixed_stores_identical=report.get('mixed_stores_identical'),
                          mixed_starts_after_first_miss=report.get('mixed_starts_after_first_miss'),
                          stores_results_identical=report['stores_results_identical'],
                          peak_working_set_mib=report['peak_working_set_mib'])))


if __name__ == '__main__':
    main()
