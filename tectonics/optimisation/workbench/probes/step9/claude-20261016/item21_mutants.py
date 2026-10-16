"""Item 21 planted mutants of prepared_interval_driver's ordinary-head branch.

Each mutant is one textual change to the driver source, written to a temporary folder here (never over the
real driver). OrdinaryHeadScenarios then runs against it through item21_mutant_scenario.py and must fail.
The unmutated source must pass through the same wrapper first, so a broken wrapper cannot look like a catch.
Prints one line per mutant; exit 1 if any mutant survives or does not apply exactly once.
Usage: python -B item21_mutants.py   (writes only temporary folders under this folder)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESUMABILITY = HERE.parents[2]
sys.path.insert(0, str(RESUMABILITY))

import test_prepared_interval_driver as T  # noqa: E402

SOURCE = (RESUMABILITY/'prepared_interval_driver.py').read_text(encoding='utf8')
WRAPPER = HERE/'item21_mutant_scenario.py'
ORIGINAL = T.run_scenario
INDENT = '\n' + ' '*16

# name: (exact original text, replacement). Each original must occur exactly once in the driver.
MUTANTS = {
    'head_key_not_compared': (
        "root_kind='root', head_key=lineage.get('head_key'), kind='successor', sequence=interval)",
        "root_kind='root', kind='successor', sequence=interval)"),
    'type_blind_compare': (
        'if type(found[name]) is not type(expected[name]) or found[name] != expected[name]]',
        'if found[name] != expected[name]]'),
    'root_kind_from_found': (
        "root_kind='root', head_key=lineage.get('head_key')",
        "root_kind=root_record.get('kind'), head_key=lineage.get('head_key')"),
    'successor_kind_from_found': (
        "head_key=lineage.get('head_key'), kind='successor', sequence=interval)",
        "head_key=lineage.get('head_key'), kind=head.get('kind'), sequence=interval)"),
    'lineage_schema_unchecked': (
        "_require(type(lineage) is dict and lineage.get('schema') == LINEAGE_SCHEMA,",
        '_require(type(lineage) is dict,'),
    'root_head_admitted': (
        '_require(type(interval) is int and interval >= 1,',
        '_require(type(interval) is int and interval >= 0,'),
    'ordinary_duration_unchecked': (
        '_require(duration == first_duration,\n                 "fixture initial workload duration differs',
        '_require(True,\n                 "fixture initial workload duration differs'),
    'r6_on_ordinary': (
        '        joined = joined_module\n',
        '        import private_heat_original_joined_r6 as joined\n'),
    'ordinary_query_owner_parameter_unchecked': (
        '        joined = joined_module\n        # Fail before any physical work, never after hours of geometry.\n'
        "        _require('endpoint_checkpoints' in inspect.signature(joined._advance_current_interval).parameters,",
        '        joined = joined_module\n        # Fail before any physical work, never after hours of geometry.\n'
        '        _require(True,'),
    'joined_identity_by_name_only': (
        '_require(joined_module is sys.modules.get(FRESH_JOINED) and\n',
        '_require(True and\n'),
    'frozen_state_admitted': (
        "_require(type(case.get('state')) is not IW.InitialWorkloadState,",
        '_require(True,'),
    'lineage_gate_unrecorded': (
        "        record['lineage_gate'] = dict(found, lineage_schema=LINEAGE_SCHEMA, "
        'parent_advance_duration_s=first_duration)\n',
        ''),
    'commit_stages_dropped': (
        '        stages += _commit_stages(SimpleNamespace(J=J, Workflow=CollarWorkflow))\n',
        ''),
    'commit_stages_on_migrated': (
        "    if ordinary:\n        # Item 11's commit-window stages",
        "    if True:\n        # Item 11's commit-window stages"),
    'route_by_lineage_only': (
        '    ordinary = base is None and lineage is not None\n',
        '    ordinary = lineage is not None\n'),
    'migrated_accepts_route_inputs': (
        'query_checkpoints.context is not execution or' + INDENT + 'lineage is not None or joined_module is not None):',
        'query_checkpoints.context is not execution):'),
    'ordinary_workflow_type_unchecked': (
        "if (type(workflow) is not CollarWorkflow or getattr(workflow, '_migration', None) is not None or\n",
        "if (getattr(workflow, '_migration', None) is not None or\n"),
    'ordinary_migration_unchecked': (
        "if (type(workflow) is not CollarWorkflow or getattr(workflow, '_migration', None) is not None or\n",
        'if (type(workflow) is not CollarWorkflow or\n'),
    'ordinary_workflow_budget_unchecked': (
        "getattr(workflow, '_migration', None) is not None or" + INDENT + 'workflow._budget is not budget or\n',
        "getattr(workflow, '_migration', None) is not None or\n"),
    'ordinary_checkpoint_type_unchecked': (
        INDENT + 'workflow._budget is not budget or' + INDENT + 'type(query_checkpoints) is not EndpointCheckpoints or\n',
        INDENT + 'workflow._budget is not budget or\n'),
    'ordinary_checkpoint_active_unchecked': (
        INDENT + 'not query_checkpoints._active or query_checkpoints.budget is not budget or' + INDENT +
        'query_checkpoints.context is not execution):',
        INDENT + 'query_checkpoints.budget is not budget or' + INDENT + 'query_checkpoints.context is not execution):'),
    'ordinary_checkpoint_budget_unchecked': (
        INDENT + 'not query_checkpoints._active or query_checkpoints.budget is not budget or' + INDENT +
        'query_checkpoints.context is not execution):',
        INDENT + 'not query_checkpoints._active or' + INDENT + 'query_checkpoints.context is not execution):'),
    'ordinary_checkpoint_context_unchecked': (
        'query_checkpoints.budget is not budget or' + INDENT + 'query_checkpoints.context is not execution):',
        'query_checkpoints.budget is not budget):'),
}


def scenario_runner(folder):
    """T.run_scenario with the wrapper in place of the test file; the same environment and timeout."""
    def run_scenario(name, *, seeded=True):
        env = {k: v for k, v in T.R.launch_environment().items() if seeded or k != 'PYTHONHASHSEED'}
        with tempfile.TemporaryDirectory(prefix='pd-', dir=folder) as directory:
            result = subprocess.run([sys.executable, '-B', str(WRAPPER), str(folder), name, directory],
                                    cwd=T.HERE, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise AssertionError(result.stdout[-3000:]+result.stderr[-6000:])
        return json.loads(result.stdout.strip().splitlines()[-1])
    return run_scenario


def passes(folder):
    T.run_scenario = scenario_runner(folder)
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(T.OrdinaryHeadScenarios)
        with open(os.devnull, 'w') as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=0, failfast=True).run(suite)
        return result.wasSuccessful(), result.testsRun
    finally:
        T.run_scenario = ORIGINAL


def write(folder, text):
    folder.mkdir()
    with open(folder/'prepared_interval_driver.py', 'w', encoding='utf8', newline='\n') as handle:
        handle.write(text)


def main():
    survived, unapplied = [], []
    with tempfile.TemporaryDirectory(prefix='m21-', dir=HERE) as root:
        write(Path(root)/'baseline', SOURCE)
        ok, ran = passes(Path(root)/'baseline')
        print('baseline', 'passes' if ok else 'FAILED', ran, 'tests', flush=True)
        if not ok:
            print('item21 mutants: the unmutated driver must pass through the wrapper; nothing judged')
            return 1
        for index, (name, (old, new)) in enumerate(MUTANTS.items()):
            count = SOURCE.count(old)
            if count != 1:
                unapplied.append(name)
                print(name, 'DOES NOT APPLY (%d matches)' % count, flush=True)
                continue
            folder = Path(root)/('m%02d' % index)
            write(folder, SOURCE.replace(old, new))
            ok, ran = passes(folder)
            print(name, 'SURVIVED' if ok else 'caught', ran, 'tests run', flush=True)
            if ok:
                survived.append(name)
    caught = len(MUTANTS)-len(survived)-len(unapplied)
    print('item21 mutants: %d caught, %d survived %s, %d did not apply %s' % (
        caught, len(survived), survived, len(unapplied), unapplied))
    return 1 if survived or unapplied else 0


if __name__ == '__main__':
    sys.exit(main())
