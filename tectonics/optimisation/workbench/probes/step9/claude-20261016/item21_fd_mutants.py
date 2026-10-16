"""Item 21 planted mutants of fresh_interval_driver.advance_successor_interval.

Each mutant is one textual change to the driver source, written to a temporary folder here (never over the
real driver). test_fresh_interval_driver's WiringTests and MeasurementHookTests then run against it in a fresh
process through item21_fd_mutant_tests.py and must fail. The unmutated source must pass through the same
wrapper first, so a broken wrapper cannot look like a catch.
Prints one line per mutant; exit 1 if any mutant survives or does not apply exactly once.
Usage: python -B item21_fd_mutants.py   (writes only temporary folders under this folder)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESUMABILITY = HERE.parents[2]
SOURCE = (RESUMABILITY/'fresh_interval_driver.py').read_text(encoding='utf8')
WRAPPER = HERE/'item21_fd_mutant_tests.py'

# The successor's cheap lineage checks and its admission line, for the reordering mutant.
CHECKS = ('    _require(type(lineage) is dict and lineage.get(\'schema\') == LINEAGE_SCHEMA,\n'
          '             "an interval N >= 2 run needs the runner\'s sealed lineage record")\n'
          '    interval = lineage.get(\'interval\')\n'
          '    _require(type(interval) is int and interval >= 1,\n'
          '             \'a sealed lineage parent is interval 1 or later; the root advances through '
          'advance_first_interval\')\n'
          '    foreign = [name for name in (\'workflow_id\', \'root_key\') if lineage.get(name) != expected_root[name]]\n'
          '    _require(not foreign, "the sealed lineage is not of run A\'s root: "+\', \'.join(foreign))\n')
ADMIT = '    with admission(m, budget=budget, artifacts=artifacts, phase=phase, measurements=measurements) as a:\n'
ADVANCED = "'interval %d did not advance exactly once' % (interval+1))\n"
ROOT_CHECK = ("            _require({}, 'run B re-derived admission differs from run A sealed root: '\n"
              "                     + ', '.join(differing))\n            record['root_reproduced']")

# name: (exact original text, replacement). Each original must occur exactly once in the driver.
MUTANTS = {
    'seed_unpinned': ('    _seed_pinned()\n    # Cheap record checks first', '    # Cheap record checks first'),
    'lineage_schema_unchecked': ("_require(type(lineage) is dict and lineage.get('schema') == LINEAGE_SCHEMA,",
                                 '_require(type(lineage) is dict,'),
    'lineage_type_unchecked': ("_require(type(lineage) is dict and lineage.get('schema')",
                               "_require(lineage.get('schema')"),
    'interval_type_loose': ('_require(type(interval) is int and interval >= 1,', '_require(interval >= 1,'),
    'root_interval_admitted': ('type(interval) is int and interval >= 1,', 'type(interval) is int and interval >= 0,'),
    'foreign_root_key_unchecked': ("for name in ('workflow_id', 'root_key') if lineage.get(name)",
                                   "for name in ('workflow_id',) if lineage.get(name)"),
    'foreign_workflow_id_unchecked': ("for name in ('workflow_id', 'root_key') if lineage.get(name)",
                                      "for name in ('root_key',) if lineage.get(name)"),
    'checks_after_admission': (CHECKS+ADMIT, ADMIT+''.join('    '+line for line in CHECKS.splitlines(True))),
    'measurements_dropped': ("measurements=measurements) as a:\n        phase('reopen-adopted-successor-head')",
                             "measurements=None) as a:\n        phase('reopen-adopted-successor-head')"),
    'phase_unrecorded': ("        phase('reopen-adopted-successor-head')\n", ''),
    'root_identity_unchecked': (ROOT_CHECK.format('not differing'), ROOT_CHECK.format('True')),
    'root_reproduced_unrecorded': (
        "            record['root_reproduced'] = {name: found[name] for name in ROOT_IDENTITY}\n"
        '            head = workflow._head\n', '            head = workflow._head\n'),
    'head_interval_not_compared': ("opened = {'interval': before['intervals'], 'kind'", "opened = {'kind'"),
    'head_key_not_compared': ("'kind': head.get('kind'), 'head_key': head.get('key')}", "'kind': head.get('kind')}"),
    'head_kind_from_opened': ("parent_head = {'interval': interval, 'kind': 'successor',",
                              "parent_head = {'interval': interval, 'kind': head.get('kind'),"),
    'parent_head_key_from_opened': ("'head_key': lineage.get('head_key')}", "'head_key': head.get('key')}"),
    'base_not_none': ('workflow=workflow, base=None,', 'workflow=workflow, base=a.case,'),
    'checkpoint_factory_passed': ('query_checkpoints=checkpoints, lineage=lineage',
                                  'query_checkpoints=query_checkpoints, lineage=lineage'),
    'lineage_not_passed': ('lineage=lineage, joined_module=m.joined)', 'lineage=None, joined_module=m.joined)'),
    'joined_module_not_passed': ('joined_module=m.joined)', 'joined_module=None)'),
    'advance_count_unchecked': ("_require(after['intervals'] == interval+1 and after['funding_id']",
                                "_require(after['funding_id']"),
    'funding_unchecked': ("interval+1 and after['funding_id'] == before['funding_id'] and",
                          'interval+1 and'),
    'head_change_unchecked': ("after['head'] != before['head'] and workflow._root == root_bytes,\n"
                              '                         '+ADVANCED[:12],
                              'workflow._root == root_bytes,\n                         '+ADVANCED[:12]),
    'root_change_unchecked': ("after['head'] != before['head'] and workflow._root == root_bytes,\n"
                              '                         '+ADVANCED[:12],
                              "after['head'] != before['head'],\n                         "+ADVANCED[:12]),
    'save_dropped': (ADVANCED+'                save()\n', ADVANCED),
    'finish_after_checkpoints_close': (ADVANCED+'                save()\n                return finish(',
                                       ADVANCED+'            save()\n            return finish('),
}


def passes(folder):
    """True if the wrapper's tests all pass against the driver in ``folder`` (a fresh process each time)."""
    env = dict(os.environ, PYTHONHASHSEED='0')
    result = subprocess.run([sys.executable, '-B', str(WRAPPER), str(folder/'fresh_interval_driver.py')],
                            cwd=RESUMABILITY, env=env, capture_output=True, text=True, timeout=300)
    ran = (result.stdout.strip().splitlines() or ['?'])[-1]
    return result.returncode == 0, ran


def write(folder, text):
    folder.mkdir()
    with open(folder/'fresh_interval_driver.py', 'w', encoding='utf8', newline='\n') as handle:
        handle.write(text)


def main():
    survived, unapplied = [], []
    with tempfile.TemporaryDirectory(prefix='m21f-', dir=HERE) as root:
        write(Path(root)/'baseline', SOURCE)
        ok, ran = passes(Path(root)/'baseline')
        print('baseline', 'passes' if ok else 'FAILED', ran, flush=True)
        if not ok:
            print('item21 FD mutants: the unmutated driver must pass through the wrapper; nothing judged')
            return 1
        for index, (name, (old, new)) in enumerate(MUTANTS.items()):
            count = SOURCE.count(old)
            if count != 1 or old == new:
                unapplied.append(name)
                print(name, 'DOES NOT APPLY (%d matches)' % count, flush=True)
                continue
            folder = Path(root)/('m%02d' % index)
            write(folder, SOURCE.replace(old, new))
            ok, ran = passes(folder)
            print(name, 'SURVIVED' if ok else 'caught', ran, flush=True)
            if ok:
                survived.append(name)
    caught = len(MUTANTS)-len(survived)-len(unapplied)
    print('item21 FD mutants: %d caught, %d survived %s, %d did not apply %s' % (
        caught, len(survived), survived, len(unapplied), unapplied))
    return 1 if survived or unapplied else 0


if __name__ == '__main__':
    sys.exit(main())
