"""Explicit prepared source-plan / generation preparation; never constructs Atlas.

Only stdlib source/JSON parsing. No imports of the assembler, runtime, transformers
or tests. Writes an exclusive metadata directory, never the planned T source box.
--source-plan needs no measured hashes and produces no reviewed-input seed.
The final mode requires a real pinned stage measurement and explicit selection.
"""
import argparse
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SELECTION_SHA256 = '0f2662815f38c4d1f82502d169e0e07ac9d583e51e28307389c402fd9254e163'
PROFILE_WRITER_SHA256 = '7d8c0e707ef963e0336e7fa36492d69d9e5a187dd006b3bce528ce9eb3ac587f'
ORIGINAL_CONSUMER_PINS = {
    'test_composed_manifest.py': 'a1c6e6b16f3348b8fb4bb8bc4d77dc9fe96a7be703efffead6163e88d92c38b8',
    'test_composed_import_fence.py': 'c47cc53f2b34209cac455aba236dae4c2c08fe29413c6b2e364a128756a15f1a',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode('utf8')


def pinned(path, expected):
    require(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected), 'exact selected SHA-256 required')
    raw = Path(path).read_bytes()
    require(digest(raw) == expected, 'selected source changed: '+str(path))
    return raw


def constants(raw):
    result = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass  # only literal constants; do not evaluate source expressions
    return result


def prepare(assembler_sha256, *, consumer_pins, measurement=None, measurement_sha256=None,
            stage_selection=None, stage_selection_sha256=None):
    selection_path = HERE/'prepared-source-selection.json'
    selection = json.loads(pinned(selection_path, SELECTION_SHA256))
    source = pinned(HERE/'assemble_resumable.py', assembler_sha256)
    c = constants(source)
    files = {name: row['sha256'] for name, row in selection['files'].items()}
    require(c['SELECTED_INPUT_PINS'] == files and c['SOURCE_SELECTION_SHA256'] == SELECTION_SHA256 and
            c['ROUTE'] == selection['route'], 'assembler does not bind the selected prepared source map')
    gref, oldref = selection['generation'], selection['predecessor_reviewed_inputs']
    generation = json.loads(pinned(gref['path'], gref['sha256']))
    old = json.loads(pinned(oldref['path'], oldref['sha256']))
    rows = deepcopy(generation['files'])
    require(type(consumer_pins) is dict and set(consumer_pins) == set(ORIGINAL_CONSUMER_PINS),
            'explicit selection of both changed consumer candidates required')
    for name, expected in ORIGINAL_CONSUMER_PINS.items():
        require(rows[name]['sha256'] == expected, 'consumer predecessor changed: '+name)
        pinned(HERE/name, consumer_pins[name])
    gdir = Path(gref['path']).parent/'gen-r3'
    # Deliberate replacements, never auto-select current bytes on source drift.
    plan = {name: dict(source=str(gdir/name), sha256=row['sha256']) for name, row in rows.items()
            if name not in ('assemble_resumable.py', 'reviewed-inputs.json')}
    plan['assemble_resumable.py'] = dict(source=str(HERE/'assemble_resumable.py'), sha256=assembler_sha256)
    for name, expected in consumer_pins.items():
        plan[name] = dict(source=str(HERE/name), sha256=expected,
                          scope='proposed authenticated child bootstrap; selected only by explicit supplied pin')
    for name, row in selection['files'].items():
        if name in plan:
            require(plan[name]['sha256'] == row['sha256'] or (row.get('delta') == 'selected-change' and
                    plan[name]['sha256'] == row.get('predecessor_sha256')),
                    'generation/selected source collision: '+name)
        plan[name] = dict(source=row['source'], sha256=row['sha256'])
    plan['prepared-source-selection.json'] = dict(source=str(selection_path), sha256=SELECTION_SHA256)
    writer = HERE/'write_prepared_profile.py'
    pinned(writer, PROFILE_WRITER_SHA256)
    plan[writer.name] = dict(source=str(writer), sha256=PROFILE_WRITER_SHA256)
    retained_root = Path(selection['layout']['future_box']).parent/'resumability-r1'
    for name, expected in c['RETAINED_RECEIPT_PINS'].items():
        relative = 'test-results/'+name+'.json'
        plan[relative] = dict(source=str(retained_root/relative), sha256=expected,
                              scope='historical-delivery-only')
    relative = 'endpoint-checkpoints/test-results-w2k.json'
    plan[relative] = dict(source=str(retained_root/relative), sha256=c['RETAINED_AUXILIARY_PINS']['w2k-suite'],
                          scope='historical-delivery-only')
    # The caller selects this tool/writer and both consumers along with the
    # candidate. No automatic refresh of a selected file's current hash.
    base_plan = dict(schema='atlas.private.prepared-source-copy-plan.v1',
        status='PREPARATION_ONLY_NO_COPY_OR_BUILD', route=c['ROUTE'], future_box=selection['layout']['future_box'],
        target=selection['layout']['target'], generation_predecessor=gref,
        retained_old_reviewed_inputs=oldref, files=plan,
        unavailable=['complete selected reviewed-inputs record', 'final generation'] if measurement is None else [])
    require(set(plan)-{'prepared-source-selection.json', writer.name} >= set(files), 'input source plan incomplete')
    if measurement is None:
        require(measurement_sha256 is None and stage_selection is None and stage_selection_sha256 is None,
                'no partial measurement/selection arguments')
        return {'source-copy-plan.json': encode(base_plan)}

    mraw = pinned(measurement, measurement_sha256)
    draw = pinned(stage_selection, stage_selection_sha256)
    measured, decision = json.loads(mraw), json.loads(draw)
    package = c['PACKAGE_DIGESTS']
    package_sha = digest(json.dumps(package, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    require(type(measured) is dict and set(measured) == {'schema', 'status', 'route', 'assembler_sha256',
            'source_selection_sha256', 'files', 'package_baseline_sha256', 'stage_digests', 'package_stage_drift'} and
            measured.get('schema') == 'atlas.private.prepared-stage-measurement.v1' and
            measured.get('status') == 'MEASURED_NOT_SELECTED' and measured.get('route') == c['ROUTE'] and
            measured.get('assembler_sha256') == assembler_sha256 and measured.get('files') == files and
            measured.get('source_selection_sha256') == SELECTION_SHA256 and
            measured.get('package_baseline_sha256') == package_sha, 'measurement identity mismatch')
    stages = measured.get('stage_digests')
    require(type(stages) is dict and set(package) <= set(stages) and 'composition@outputs' in stages,
            'complete stage measurement required')
    require(all(type(v) is str and re.fullmatch('[0-9a-f]{64}', v) for v in stages.values()), 'bad measured digest')
    drift = {k: dict(before=v, after=stages[k]) for k, v in package.items() if v != stages[k]}
    require(measured.get('package_stage_drift') == drift, 'incomplete measured package drift')
    require(type(decision) is dict and set(decision) == {'schema', 'status', 'measurement_sha256',
            'assembler_sha256', 'source_selection_sha256', 'package_stage_changes', 'authority', 'accuracy'} and
            decision['schema'] == 'atlas.private.prepared-stage-selection.v1' and
            decision['status'] == 'SELECTED_FOR_SOURCE_BUILD' and decision['measurement_sha256'] == measurement_sha256 and
            decision['assembler_sha256'] == assembler_sha256 and decision['source_selection_sha256'] == SELECTION_SHA256,
            'explicit stage selection required; do not manufacture review authority')
    changes = decision['package_stage_changes']
    require(type(changes) is dict and set(changes) == set(drift), 'select each actual package-stage change')
    for key, row in changes.items():
        require(type(row) is dict and set(row) == {'before', 'after', 'reason'} and
                {k: v for k, v in row.items() if k != 'reason'} == drift[key] and
                type(row['reason']) is str and bool(row['reason'].strip()), 'unexplained measured package change: '+key)
    require(all(type(decision[k]) is str and bool(decision[k].strip()) for k in ('authority', 'accuracy')),
            'honest authority and accuracy statements required')
    document = {key: deepcopy(old[key]) for key in
                ('predecessor_manifest_sha256', 'filtered_manifest_sha256', 'external_files', 'layout')}
    document.update(schema=c['DOCUMENT_SCHEMA'], files=files, stage_digests=stages, target=selection['layout']['target'],
        authority=decision['authority'], accuracy=decision['accuracy'], source_selection_sha256=SELECTION_SHA256,
        package_stage_changes=changes, stage_measurement=dict(path='stage-measurement.json', sha256=measurement_sha256),
        stage_selection=dict(path='stage-selection.json', sha256=stage_selection_sha256))
    outputs = {'reviewed-inputs.json': encode(document)}
    plan['stage-measurement.json'] = dict(source=str(Path(measurement).resolve()), sha256=measurement_sha256)
    plan['stage-selection.json'] = dict(source=str(Path(stage_selection).resolve()), sha256=stage_selection_sha256)
    # resolved output metadata paths are filled by main after the exclusive output directory is chosen
    plan['reviewed-inputs.json'] = dict(source_output='reviewed-inputs.json', sha256=digest(outputs['reviewed-inputs.json']))
    for name, item in plan.items():
        previous = rows.get(name)
        if previous is not None and previous['sha256'] == item['sha256']:
            continue  # retain the entire unchanged row, not just its hash
        rows[name] = dict(sha256=item['sha256'], origin='prepared-construction-v2-r2',
                          predecessor_sha256=previous['sha256'] if previous else None)
    successor = dict(schema='atlas.private.plan02-prepared-generation.r1', status='SOURCE_SELECTED_PENDING_PREPARED_C2',
        predecessor=gref, source_selection_sha256=SELECTION_SHA256, route=c['ROUTE'], files=rows,
        changed_rows=sorted(name for name in generation['files'] if rows[name] != generation['files'][name]),
        added_rows=sorted(set(rows)-set(generation['files'])),
        retained_unchanged_rows=sorted(name for name in generation['files'] if rows[name] == generation['files'][name]),
        prepared_reviewed_inputs_sha256=digest(outputs['reviewed-inputs.json']),
        stage_measurement_sha256=measurement_sha256, stage_selection_sha256=stage_selection_sha256)
    outputs['GENERATION-prepared-r1.json'] = encode(successor)
    outputs['source-copy-plan.json'] = encode(base_plan)
    return outputs


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assembler-sha256', required=True)
    p.add_argument('--manifest-test-sha256', required=True)
    p.add_argument('--fence-test-sha256', required=True)
    p.add_argument('--out-directory', type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source-plan', action='store_true')
    mode.add_argument('--measurement', type=Path)
    for name in ('measurement-sha256', 'stage-selection-sha256'):
        p.add_argument('--'+name)
    p.add_argument('--stage-selection', type=Path)
    args = p.parse_args(argv)
    require(not args.out_directory.exists(), 'exclusive metadata output directory required')
    outputs = prepare(args.assembler_sha256, consumer_pins={
        'test_composed_manifest.py': args.manifest_test_sha256,
        'test_composed_import_fence.py': args.fence_test_sha256}, measurement=args.measurement,
        measurement_sha256=args.measurement_sha256, stage_selection=args.stage_selection,
        stage_selection_sha256=args.stage_selection_sha256)
    plan = json.loads(outputs['source-copy-plan.json'])
    for row in plan['files'].values():
        if 'source_output' in row:
            row['source'] = str((args.out_directory/row.pop('source_output')).resolve())
    outputs['source-copy-plan.json'] = encode(plan)
    args.out_directory.mkdir(parents=False)
    for name, raw in outputs.items():
        with (args.out_directory/name).open('xb') as stream:
            stream.write(raw)
    print(json.dumps({name: digest(raw) for name, raw in outputs.items()}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
