"""Real selected source guards only; no checkpoint restoration or heat solve."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import traceback


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def exercise(source_tree, report):
    source_tree = source_tree.resolve(strict=True)
    selection_path = Path(__file__).resolve().parent / 'SOURCE-MAP.json'
    selection_bytes = selection_path.read_bytes()
    selection = json.loads(selection_bytes)
    report['source_map_sha256'] = sha256(selection_bytes).hexdigest()
    hashes = {}
    for entry in selection['entries']:
        member = entry['member']
        relative = Path(member.removeprefix('source/'))
        require(member.startswith('source/') and not relative.is_absolute()
                and '..' not in relative.parts, 'Invalid selected member')
        path = source_tree / relative
        require(path.resolve().is_relative_to(source_tree), 'Source escapes selected tree')
        require(member not in hashes, 'Duplicate selected member')
        actual = sha256(path.read_bytes()).hexdigest()
        require(actual == entry['public_sha256'], 'Materialised source drift: ' + member)
        hashes[member] = actual
    report['selected_members_verified'] = len(hashes)
    require(not any(name == 'atlas_tectonics' or name.startswith(('atlas_tectonics.', 'private_heat_'))
                    for name in sys.modules), 'Fresh process required')
    sys.path[:0] = [str(source_tree / 'helpers'), str(source_tree / 'src')]
    import private_heat_native_issuer_r13 as issuer
    import private_heat_checkpoint_consumer_r10 as checkpoint
    import private_heat_joined_consumer_r6 as joined
    import private_heat_restored_binding_r10 as restored
    import private_heat_restored_binding_ram_context_r1 as ram_context
    import private_heat_restored_binding_ram_recovery_r1 as recovery
    import private_heat_certification_resources_r1 as c3
    import private_heat_certification_kernel_r3 as certificate
    import private_heat_functional_bounds_kernel_r2 as bounds
    import private_heat_interval_assessment_plan40b_c8_r1 as c8
    from atlas_tectonics.reuse import ExecutionContext

    execution = ExecutionContext('scipy')
    require(checkpoint.I is issuer and joined.I is issuer and joined.CAS is checkpoint,
            'Issuer/checkpoint/joined graph split')
    for module in (restored, ram_context, recovery):
        require(module.I is issuer and module.C is checkpoint, 'Restoration graph split')
    require(recovery.B1 is ram_context, 'Recovery RAM context split')
    require(certificate.INVENTORY is c3 and bounds.I is c3 and bounds.CERT is certificate,
            'C3 receiver graph split')
    forward = issuer.F
    life = forward.LIFE
    require(forward.ASSEMBLY is c8 and life.A is c8, 'C8 receiver graph split')
    require(c8.A.Contribution in life.RECORD_TYPES and c8.RefinementRequired in life.RECORD_TYPES,
            'C8 lifetime lacks selected record types')
    imported = {module.__name__: module for module in issuer._private_modules()}
    for module in (c3, certificate, bounds, forward, life, c8):
        require(imported.get(module.__name__) is module,
                'Issuer omitted live selected dependency: ' + module.__name__)
    for name, module in tuple(sys.modules.items()):
        if name == 'atlas_tectonics' or name.startswith('atlas_tectonics.'):
            require(Path(module.__file__).resolve().is_relative_to(source_tree / 'src'),
                    'Native import outside selected graph: ' + name)
        elif name.startswith('private_heat_'):
            require(Path(module.__file__).resolve().parent == source_tree / 'helpers',
                    'Helper import outside selected graph: ' + name)
    report['live_dependencies'] = sorted(module.__name__ for module in
                                       (c3, certificate, bounds, forward, life, c8))
    guards = {
        'issuer': issuer._verify_implementation,
        'checkpoint': lambda: checkpoint._verify(None),
        'joined': lambda: joined._verify(None),
        'restored': lambda: restored._verify(execution, None),
        'ram_context': lambda: ram_context._verify(execution, None),
        'recovery': lambda: recovery._verify(execution, None),
        'recovery_sources': lambda: recovery.source_bindings(None),
        'c3_sources': lambda: c3.verify_sources(None),
        'c8_forward_sources': lambda: forward._check_sources(lambda: None),
        'c8_lifetime_sources': lambda: life._sources(None),
    }
    for label, guard in guards.items():
        guard()
        report['passed_guards'].append(label)

    def reject(label, target, key, replacement, guard, *, mapping=False):
        previous = target[key] if mapping else getattr(target, key)
        try:
            if mapping:
                target[key] = replacement
            else:
                setattr(target, key, replacement)
            try:
                guard()
            except ValueError as error:
                report['negative_controls'].append(dict(
                    control=label, error_type=type(error).__name__, error=str(error)))
            else:
                raise AssertionError('Corrupted expected binding accepted: ' + label)
        finally:
            if mapping:
                target[key] = previous
            else:
                setattr(target, key, previous)
        guard()

    reject('issuer_loaded_expected_identity', issuer._LOADED_IMPLEMENTATION, '_encoded',
           b'corrupted expected identity', guards['issuer'])
    reject('checkpoint_issuer_pin', checkpoint, '_ISSUER_SHA', '0' * 64, guards['checkpoint'])
    for label, mapping, guard in (
            ('joined_pin', joined._PINS, guards['joined']),
            ('restored_pin', restored._SOURCES, guards['restored']),
            ('ram_context_pin', ram_context._SOURCES, guards['ram_context']),
            ('c3_pin', c3.PINS, guards['c3_sources']),
            ('c8_forward_pin', forward._SOURCES, guards['c8_forward_sources']),
            ('c8_lifetime_pin', life._SOURCES, guards['c8_lifetime_sources'])):
        reject(label, mapping, next(iter(mapping)), '0' * 64, guard, mapping=True)
    reject('recovery_binding_pin', recovery, '_BINDING_SHA', '0' * 64, guards['recovery'])
    reject('recovery_source_binding_pin', recovery, '_BINDING_SHA', '0' * 64,
           guards['recovery_sources'])
    # Recheck the whole graph after all temporary mutations, not merely each leaf.
    for guard in guards.values():
        guard()
    report['post_control_graph_verified'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Output must be a new file')
    report = dict(schema='atlas.plan40b.receiving-source-guards.r1', status='FAIL',
                  scope='REAL_SOURCE_BINDING_ENTRIES_ONLY',
                  checkpoint_store_opened=False, checkpoint_restoration=False,
                  heat_solve=False, workers_started=False, scientific_acceptance=False,
                  passed_guards=[], negative_controls=[])
    try:
        require(__debug__, 'Normal Python required')
        exercise(args.source_tree, report)
        report['status'] = 'PASS'
    except Exception as error:
        report['failure'] = dict(error_type=type(error).__name__, error=str(error),
                                 traceback=traceback.format_exc())
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(report['status'] + ': actual receiving source guards; no checkpoint restoration')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
