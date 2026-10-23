"""Open the existing fresh-profile import/worker boundary, without running a workload.

The selected inherited outer HelperFinder and FreshSources.selected perform all
imports. This module supplies no Atlas loader, package stub or fallback source.
An explicit pinned binding makes the route opt-in without changing old defaults.
"""
from contextlib import contextmanager
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import sys


def checked(path, expected):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError('runtime entry source pin differs: ' + str(path))
    return raw


def read_binding(path, pin):
    row = json.loads(checked(path, pin))
    if set(row) != {'schema', 'profile', 'composition', 'bootstrap', 'entry', 'source_selection'} or \
            row['schema'] != 'atlas.private.plan40.pressure-runtime-binding.r1':
        raise ValueError('closed explicit pressure runtime binding required')
    return row


@contextmanager
def selected_sources(binding_path, binding_pin):
    """Yield actual typed FreshSources with pressure worker startup configured.

    Interpreter/environment guards are the unchanged outer bootstrap's. Start a
    fresh selected Atlas Python with -B -s -P, hash seed zero and single threads.
    No process launch, ledger, root, interval, store or query is created here.
    """
    row = read_binding(binding_path, binding_pin)
    if Path(row['entry']['path']) != Path(__file__).resolve():
        raise ValueError('runtime binding selected a different entry')
    checked(row['entry']['path'], row['entry']['sha256'])
    path, pin = row['bootstrap']['path'], row['bootstrap']['sha256']
    spec = importlib.util.spec_from_file_location('_pressure_outer_bootstrap', path)
    outer = importlib.util.module_from_spec(spec)
    exec(compile(checked(path, pin), path, 'exec', dont_inherit=True), outer.__dict__)
    outer.validate_runtime()
    composition = outer.validate_composition(Path(row['composition']['path']), row['composition']['sha256'])
    if any(name in sys.modules for name in composition.helpers) or 'atlas_tectonics' in sys.modules:
        raise ValueError('runtime entry requires a fresh process')
    finder = outer.HelperFinder(composition)
    meta_before = list(sys.meta_path)
    sys.meta_path.insert(0, finder)
    original = None
    try:
        runner = importlib.import_module('run_fresh_interval')
        profile = runner.FreshProfile.read(Path(row['profile']['path']), row['profile']['sha256'])
        sources = runner.FreshSources(profile)
        with sources.selected():
            sources.configure_pressure_workers()
            yield sources
    except BaseException as error:
        original = error
        raise
    finally:
        failures = []
        try:
            finder.verify_loaded()
            if sys.meta_path != [finder, *meta_before]:
                raise ValueError('outer helper boundary changed')
        except BaseException as failure:
            failures.append(failure)
        try:
            composition.recheck()
        except BaseException as failure:
            failures.append(failure)
        finally:
            sys.meta_path[:] = meta_before
        if failures:
            failure = failures[0] if len(failures) == 1 else BaseExceptionGroup('source finality failures', failures)
            outer._combined_failure(original, failure, 'pressure runtime entry and source finality failed')
