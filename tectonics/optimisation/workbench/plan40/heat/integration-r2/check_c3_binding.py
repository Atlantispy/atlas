"""Standard-library binding controls, with opt-in actual receiver smoke; no workers."""
import ast
import argparse
from concurrent.futures import CancelledError
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
from importlib.machinery import ModuleSpec
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
HELPERS = HERE / 'source/helpers'
OLD = HERE.parent / 'implementation-r1/certificate/source/helpers'
NAMES = ('mpfr_zero_p', 'mpfr_number_p', 'mpfr_signbit', 'mpfr_set_zero')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def assignments(tree):
    result = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def funcs(tree):
    return {node.name: ast.dump(node, include_attributes=False)
            for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


def refused(call, error):
    try:
        call()
    except error:
        return
    raise AssertionError('Expected refusal: ' + error.__name__)


def real_receivers(source_tree):
    """Explicit optional two-row actual entry smoke; never starts workers."""
    source_tree = source_tree.resolve()
    sys.path[:0] = [str(source_tree / 'helpers'), str(source_tree / 'src')]
    import private_heat_certification_kernel_r1 as K
    import private_heat_certification_kernel_r3 as CERT
    import private_heat_functional_bounds_kernel_r2 as BOUND
    import private_heat_certification_resources_r1 as I
    from atlas_tectonics.resources import WorkBudget
    require(CERT.K is K and BOUND.K is K and BOUND.CERT is CERT
            and CERT.INVENTORY is I and BOUND.I is I, 'Receiver import split')
    require(Path(I.__file__).resolve() == source_tree / 'helpers' / Path(I.__file__).name,
            'Inventory imported outside receiving tree')
    I.verify_sources(None)
    import atlas_tectonics
    from atlas_tectonics import integration_mimetic_newton as POLICY
    with tempfile.TemporaryDirectory(prefix='plan40b-c3-policy-') as temporary:
        path = Path(temporary) / 'integration_mimetic_newton.py'
        path.write_bytes(Path(POLICY.__file__).read_bytes() + b'\nchanged')
        replacement = ModuleType(POLICY.__name__)
        replacement.__file__ = str(path)
        with patch.object(atlas_tectonics, 'integration_mimetic_newton', replacement):
            refused(lambda: I.D._runtime(None), RuntimeError)
    I.D._runtime(None)
    matrix = ((1, 0), (0, 1))
    target = (1, 2)
    keys = (('cell', 0), ('cell', 1))
    budget = WorkBudget(256 * 1024 * 1024)
    with CERT.assess_weights(matrix, target, keys, keys, 0, (1, 1),
                             budget=budget, precisions=(80,)) as owner:
        require(owner.value['status'] == 'CERTIFIED', 'Full assessment did not certify')
        require(bool(owner.value['result']['bounds']), 'Assessment omitted bounds')
    require(budget.reserved_bytes == 0, 'Assessment owner not released')
    with BOUND.functional_bounds(matrix, target, keys, keys, 0, (1, 1),
            gradient=target, base_observations=matrix, budget=budget,
            certification_precisions=(80,)) as owner:
        require(owner.value['status'] == 'CERTIFIED', 'Full bounds entry did not certify')
        require(bool(owner.value['row']['bounds']), 'Bounds entry omitted row')
    require(budget.reserved_bytes == 0, 'Bounds owner not released')
    import private_heat_functionals_parallel_r1 as PARALLEL
    native = K._h3_module()
    require(native is not None, 'Actual C3 native backend was not initialised')
    require(Path(PARALLEL.__file__).resolve() == source_tree / 'helpers' / Path(PARALLEL.__file__).name,
            'Parallel binding imported outside receiving tree')
    require(Path(PARALLEL._selected_mpfr_path()) == native._MPFR_PATH.resolve(),
            'Actual installed MPFR lookup differs from the initialised C3 backend')
    print('PASS: full r3 assessment and functional bounds through selected public inventory')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path,
                        help='Explicit materialised receiving tree; enables two-row real entry smoke')
    args = parser.parse_args()
    inventory = ast.parse((HELPERS / 'private_heat_certification_resources_r1.py').read_text())
    original = ast.parse((ROOT / 'tectonics/optimisation/workbench/plans13-14/source/helpers/private_heat_certification_resources_r1.py').read_text())
    current, old = funcs(inventory), funcs(original)
    require(set(current) == set(old) | {'source_paths'}, 'Unexpected inventory API change')
    for name in old.keys() - {'verify_sources'}:
        require(current[name] == old[name], 'Accounting/runtime function changed: ' + name)
    values = assignments(inventory)
    source_map = json.loads((ROOT / 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json').read_text())
    selected = {e['member']: ROOT / e['public_path'] for e in source_map['entries']}
    receiving_map = json.loads((HERE / 'SOURCE-MAP.json').read_text())
    receiving = {e['member']: ROOT / e['public_path'] for e in receiving_map['entries']}
    for name, pin in values['PINS'].items():
        path = receiving['source/helpers/' + name]
        require(sha256(path.read_bytes()).hexdigest() == pin, 'Public dependency pin differs: ' + name)

    decimal_tree = ast.parse((HELPERS / 'private_heat_decimal_inventory_r1.py').read_text())
    old_decimal_tree = ast.parse(selected['source/helpers/private_heat_decimal_inventory_r1.py'].read_text())
    new_functions, old_functions = funcs(decimal_tree), funcs(old_decimal_tree)
    require(set(new_functions) == set(old_functions), 'Decimal inventory API changed')
    for name in old_functions.keys() - {'_runtime'}:
        require(new_functions[name] == old_functions[name], 'Decimal accounting changed: ' + name)
    runtime = lambda tree: next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_runtime')
    require(ast.dump(runtime(decimal_tree).body[0]) == ast.dump(runtime(old_decimal_tree).body[0]),
            'Decimal/Python/binary64 runtime gate changed')
    decimal_values = assignments(decimal_tree)
    policy = selected['source/src/atlas_tectonics/integration_mimetic_newton.py']
    require(decimal_values['POLICY_SHA256'] == sha256(policy.read_bytes()).hexdigest(),
            'Selected public Decimal policy pin differs')

    # Execute only the binding functions against disposable stand-in modules.
    # No numerical/native source is imported or executed.
    nodes = [n for n in inventory.body if isinstance(n, ast.FunctionDef)
             and n.name in ('check', 'source_paths', 'verify_sources')]
    namespace = dict(Path=Path, sha256=sha256, CancelledError=CancelledError)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<binding-fixture>', 'exec'), namespace)
    with tempfile.TemporaryDirectory(prefix='plan40b-c3-binding-') as temporary:
        base = Path(temporary)
        imported = {}
        for index, name in enumerate(values['PINS']):
            directory = base / str(index)
            directory.mkdir()
            path = directory / name
            path.write_bytes(('fixture:' + name).encode())
            module = ModuleType(name[:-3])
            module.__file__ = str(path)
            imported[module.__name__] = module
        runtime_calls = []
        imported['private_heat_decimal_inventory_r1']._runtime = lambda cancel: runtime_calls.append(cancel)
        namespace.update(L=imported['private_heat_low_ledger_inventory_r1'],
                         I=imported['private_heat_interval_inventory_r1'],
                         D=imported['private_heat_decimal_inventory_r1'],
                         PINS={Path(m.__file__).name: sha256(Path(m.__file__).read_bytes()).hexdigest()
                               for m in imported.values()})
        with patch.dict(sys.modules, imported):
            namespace['verify_sources'](None)
            require(len(runtime_calls) == 1, 'Runtime guard skipped')
            refused(lambda: namespace['verify_sources'](lambda: True), CancelledError)
            for module in imported.values():
                path = Path(module.__file__)
                original_bytes = path.read_bytes()
                path.write_bytes(original_bytes + b'changed')
                refused(lambda: namespace['verify_sources'](None), ValueError)
                path.write_bytes(original_bytes)
            module = imported['private_heat_certification_kernel_r1']
            correct_path = module.__file__
            module.__file__ = str(base / 'wrong.py')
            refused(namespace['source_paths'], ValueError)
            module.__file__ = correct_path
            Path(correct_path).unlink()
            refused(lambda: namespace['verify_sources'](None), FileNotFoundError)

    parallel = ast.parse((HELPERS / 'private_heat_functionals_parallel_r1.py').read_text())
    previous = ast.parse((OLD / 'private_heat_functionals_parallel_r1.py').read_text())
    pf, of = funcs(parallel), funcs(previous)
    require(set(pf) == set(of) | {'_selected_mpfr_path'}, 'Unexpected parallel API change')
    for name in of.keys() - {'_native_binding_api', '_assembly_policy'}:
        require(pf[name] == of[name], 'Parallel custody/observer function changed: ' + name)
    new_values, old_values = assignments(parallel), assignments(previous)
    require(new_values['_MPFR_EXPORT_NAMES'] == old_values['_MPFR_EXPORT_NAMES'] + NAMES,
            'Outer export coverage differs')
    for key, digest, exports in (
            ('_NATIVE_BINDING_SOURCE', '_NATIVE_BINDING_SHA256', 'EXPORT_NAMES'),
            ('_ASSEMBLY_POLICY_SOURCE', '_ASSEMBLY_POLICY_SHA256', 'MPFR_EXPORTS')):
        new_tree, old_tree = ast.parse(new_values[key]), ast.parse(old_values[key])
        require(funcs(new_tree) == funcs(old_tree), 'Embedded validation changed: ' + key)
        new_assigns, old_assigns = assignments(new_tree), assignments(old_tree)
        require(new_assigns[exports] == old_assigns[exports] + NAMES, 'Embedded export coverage differs')
        require(sha256(new_values[key].encode()).hexdigest() == new_values[digest], 'Embedded source seal differs')
        changed = {exports, '_PINNED_PATH'} if key == '_NATIVE_BINDING_SOURCE' else {
            exports, 'MPFR_DLL_PATH', 'H3_SHA256', 'CERT_SHA256'}
        location = '_PINNED_PATH' if key == '_NATIVE_BINDING_SOURCE' else 'MPFR_DLL_PATH'
        require(new_assigns[location] is None, 'Embedded location must require verified injection')
        if key == '_ASSEMBLY_POLICY_SOURCE':
            require(new_assigns['H3_SHA256'] == new_values['_ASSEMBLY_H3_SHA256']
                    and new_assigns['CERT_SHA256'] == new_values['_ASSEMBLY_CERT_SHA256'],
                    'Embedded C3 source pins differ')
        # Only explicit export, source identity and location declarations change.
        strip = lambda tree: ast.dump(ast.Module(body=[n for n in tree.body
            if not (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                    and t.id in changed for t in n.targets))], type_ignores=[]), include_attributes=False)
        require(strip(new_tree) == strip(old_tree), 'Unexpected embedded policy change')
    nodes = [n for n in parallel.body if isinstance(n, ast.FunctionDef)
             and n.name in ('_selected_mpfr_path', '_digest', '_assembly_require')]
    lookup = dict(Path=Path, sys=sys, sha256=sha256)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<library-lookup-fixture>', 'exec'), lookup)
    with tempfile.TemporaryDirectory(prefix='plan40b-c3-library-') as temporary:
        base = Path(temporary).resolve()
        package = base / 'gmpy2'
        package.mkdir()
        origin = package / '__init__.py'
        origin.write_bytes(b'fixture')
        library = base / 'gmpy2.libs' / 'libmpfr-6.dll'
        library.parent.mkdir()
        library.write_bytes(b'fixture DLL, never loaded')
        lookup['_ASSEMBLY_MPFR_SHA256'] = sha256(library.read_bytes()).hexdigest()
        module = ModuleType('gmpy2')
        module.__file__ = str(origin)
        module.__path__ = [str(package)]
        module.__spec__ = ModuleSpec('gmpy2', loader=None, origin=str(origin))
        with patch.dict(sys.modules, {'gmpy2': module}):
            require(lookup['_selected_mpfr_path']() == str(library), 'Wrong sibling lookup')
            module.__path__.append(str(base))
            refused(lookup['_selected_mpfr_path'], ValueError)
            module.__path__.pop()
            module.__spec__.origin = str(library)
            refused(lookup['_selected_mpfr_path'], ValueError)
            module.__spec__.origin = str(origin)
            library.write_bytes(b'wrong DLL')
            refused(lookup['_selected_mpfr_path'], ValueError)
            library.unlink()
            refused(lookup['_selected_mpfr_path'], ValueError)
        with patch.dict(sys.modules, {'gmpy2': None}):
            refused(lookup['_selected_mpfr_path'], ValueError)
    print('PASS: C3 public pins, unchanged accounting/custody, binding fault controls, eighteen-export seals')
    if args.source_tree is not None:
        real_receivers(args.source_tree)


if __name__ == '__main__':
    main()
