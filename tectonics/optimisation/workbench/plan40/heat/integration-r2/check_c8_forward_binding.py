"""Exercise the actual C8 assessment-to-forward lifetime seam; no forward run."""
import argparse
import ast
from concurrent.futures import CancelledError
from hashlib import sha256
import json
from pathlib import Path
import sys

MAP_SHA = '1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf'
C8_PINS = {
    'private_heat_interval_assembly_kernel_plan40b_c8_r1': '248afad46838af857c1170c3083b7a0558fb2c85921e54b9011f3b024816d7f5',
    'private_heat_interval_inventory_plan40b_c8_r1': '28d3bf9c604309e402d4e979ef3bba07d5ff78900038af53bf862cbb0a1672a0',
    'private_heat_interval_assessment_plan40b_c8_r1': '3347757f84789019b7b326de293be6617aa817c09efa6682c426f1876742af33',
}
SUCCESSORS = {
    'private_heat_forward_kernel_r13': '3300494dc1c65f616c93b6c925b73ef40a4a185c2ce19e2440bd3fd7eda263f6',
    'private_heat_stage_lifetime_r3': '7e7733139cd19fda7a71c6222f177b372f138a6c4a04db7452f8fdd2e58815a3',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--source-tree', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    require(__debug__, 'Normal Python required')
    require(args.output is None or not args.output.exists(), 'Result must be new')
    repo = args.repo.resolve()
    root = Path(__file__).resolve().parent
    source_tree = args.source_tree.resolve()
    map_path = repo/'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
    require(sha256(map_path.read_bytes()).hexdigest() == MAP_SHA, 'Selected map changed')
    entries = {Path(e['member']).name: e for e in json.loads(map_path.read_bytes())['entries']}
    consumed = {}

    def bind(path, digest):
        require(sha256(path.read_bytes()).hexdigest() == digest, 'Source drift: '+str(path))
        consumed[path.relative_to(repo).as_posix()] = digest
        return path

    def selected(name):
        entry = entries[name]
        return bind(repo/entry['public_path'], entry['public_sha256'])

    # The complete producer/consumer implementations remain unchanged. Only
    # imports and the relocated lifetime's explicit source closure may differ.
    for name, digest in SUCCESSORS.items():
        old = ast.parse(selected(name+'.py').read_text())
        new = ast.parse(bind(root/'source/helpers'/(name+'.py'), digest).read_text())
        functions = lambda tree: {n.name: ast.dump(n) for n in tree.body
                                 if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        require(functions(old) == functions(new), 'Producer/lifetime implementation changed: '+name)

    # Root's constructor verifies and materialises the complete new selection.
    # Check that exact manifest again before importing the real package.
    integration_map = root/'SOURCE-MAP.json'
    selection = json.loads(integration_map.read_bytes())
    materialised = {}
    for entry in selection['entries']:
        member = entry['member']
        require(member.startswith('source/'), 'Unexpected selected member')
        relative = member.removeprefix('source/')
        path = source_tree/relative
        require(sha256(path.read_bytes()).hexdigest() == entry['public_sha256'],
                'Materialised source drift: '+relative)
        materialised[relative] = entry['public_sha256']
    for name, digest in {**SUCCESSORS, **C8_PINS}.items():
        require(materialised.get('helpers/'+name+'.py') == digest, 'Wrong C8 selection: '+name)
    sys.path[:0] = [str(source_tree/'helpers'), str(source_tree/'src')]
    import private_heat_forward_kernel_r13 as forward
    import private_heat_interval_assessment_plan40b_c8_r1 as receiver
    from atlas_tectonics.resources import WorkBudget, MemoryLimitError
    life = forward.LIFE
    for module in (forward, life, receiver):
        require(Path(module.__file__).resolve().parent == source_tree/'helpers', 'Wrong imported route')
    require(forward.ASSEMBLY is receiver and life.A is receiver, 'Split receiver identity')
    require(receiver.A.Contribution in life.RECORD_TYPES and receiver.RefinementRequired in life.RECORD_TYPES,
            'Lifetime retains predecessor record types')
    expected_sources = {str(Path(p).resolve()) for p in receiver.SOURCE_PATHS}
    require(expected_sources <= set(forward._SOURCES), 'Forward omitted accepted receiver source closure')
    require(expected_sources <= set(life._SOURCES), 'Lifetime omitted accepted receiver source closure')
    forward._check_sources(lambda: None)
    life._sources(None)
    gmp = receiver.A.B._library()
    require(gmp is not None, 'Actual selected GMP backend unavailable')

    def row(face, owners, bounds):
        return dict(face_id=face, owners=owners, ordered_keys=tuple(bounds), bounds=bounds)

    # Reuse the accepted receiver's two-cell fixture, through actual public
    # methods and real WorkBudget/OwnedWorkspace; no extracted numerical body.
    rows = [row('a', ((0, 1), (1, -1)), {('cell', 0): (gmp.mpq(2),)*2,
            ('cell', 1): (gmp.mpq(-3),)*2}),
            row('b', ((1, 1),), {('cell', 1): (gmp.mpq(0),)*2,
            ('wall', 'w'): (gmp.mpq(2),)*2})]
    boundary = {'w': ('temperature', 1.25)}
    metadata = dict(witness={'fixture': True}, source_bindings={'source': 'a'*64})
    budget = WorkBudget(64*2**20)
    checks = []
    owner = forward.ASSEMBLY.assess(rows, 2, boundary, budget=budget, **metadata)
    expected = owner.value
    compact = life.compact_assessment(owner, boundary, budget=budget)
    require(compact.value is expected, 'Compaction copied/replaced result')
    require(compact.rounded_system(boundary).operator == expected.operator, 'Rounded consumer changed')
    require(compact.rounded_system(boundary) is compact.rounded_system(boundary), 'View not reused')
    try:
        owner.value
    except RuntimeError:
        pass
    else:
        raise RuntimeError('Transferred producer remains live')
    compact.close()
    require(budget.reserved_bytes == 0, 'Completed assessment leaked charge')
    checks.append('actual_forward_receiver_and_lifetime_certificate_transfer')

    tiny = gmp.mpq(1, 10**100)
    ambiguous = [row('p', ((0, 1),), {('cell', 0): (gmp.mpq(1), 1+tiny)}),
                 row('m', ((0, 1),), {('cell', 0): (gmp.mpq(-1), -1+tiny)})]
    owner = receiver.assess(ambiguous, 2, boundary, budget=budget, **metadata)
    require(type(owner.value) is receiver.RefinementRequired, 'Expected refinement')
    compact = life.compact_assessment(owner, boundary, budget=budget)
    try:
        compact.rounded_system(boundary)
    except receiver.UnresolvedRounding:
        pass
    else:
        raise RuntimeError('Refinement exposed numerical view')
    selected_faces = compact.value.selected_face_ids
    projection = life.compact(compact, budget=budget, path=('selected_face_ids',))
    require(projection.value == selected_faces, 'Refinement projection changed')
    projection.close()
    require(budget.reserved_bytes == 0, 'Refinement transfer leaked charge')
    checks.append('actual_refinement_transfer_and_forward_projection')

    owner = receiver.assess(rows, 2, boundary, budget=budget, **metadata)
    held = budget.reserved_bytes
    try:
        life.compact_assessment(owner, boundary, budget=budget, cancelled=lambda: True)
    except CancelledError:
        pass
    else:
        raise RuntimeError('Lifetime cancellation accepted')
    require(budget.reserved_bytes == held and owner.value is not None, 'Cancellation retired producer')
    owner.close()
    require(budget.reserved_bytes == 0, 'Cancelled transfer leaked charge')
    try:
        receiver.assess(rows, 2, boundary, budget=WorkBudget(1), **metadata)
    except MemoryLimitError:
        pass
    else:
        raise RuntimeError('Receiver admission bypassed')
    checks.append('cancellation_preserves_producer_and_admission_refuses')
    for path, digest in list(consumed.items()):
        bind(repo/path, digest)
    for relative, digest in materialised.items():
        require(sha256((source_tree/relative).read_bytes()).hexdigest() == digest,
                'Materialised source changed: '+relative)
    result = dict(schema='plan40b-c8-forward-binding/v1', status='PASS', checks=checks,
                  source_map_sha256=MAP_SHA, sources=consumed, materialised_sources=materialised,
                  integration_map_sha256=sha256(integration_map.read_bytes()).hexdigest(),
                  control_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  full_forward_executed=False, workers_launched=False,
                  production_selected=False, timing_executed=False)
    if args.output is not None:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
    print(json.dumps({'status': 'PASS', 'checks': len(checks)}))


if __name__ == '__main__':
    main()
