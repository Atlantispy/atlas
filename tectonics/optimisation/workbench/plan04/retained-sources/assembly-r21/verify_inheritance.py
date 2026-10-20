"""Prove inherited statements unchanged after removing the declared additive seam."""
import ast
from hashlib import sha256
import json
from pathlib import Path

BASE = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace/work/plan06/r3/'
            'integration/assemble_r3_plan06.py')
EXPECTED = 'c84f98bf62116553b92103bd16a2d6f0fbf5d027c8273f6f90ab8fadfa80f45d'
CANDIDATE = Path(__file__).with_name('assemble_r3_plan04.py')
ADDED_FUNCTIONS = {
    'plan04_inventory', 'plan04_validate_name', 'plan04_select', 'plan04_recheck',
    'plan04_add_helpers', 'plan04_check_reviewed',
}
ADDED_GLOBALS = {
    'PLAN04_SCHEMA', 'PLAN04_FOLDER', 'PLAN04_LAUNCHER', 'PLAN04_SELECTION', 'PLAN04_ASSETS',
}


def is_call(node, name):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and \
        isinstance(node.value.func, ast.Name) and node.value.func.id == name


def strip_seam(tree, baseline):
    original = {node.name: node for node in baseline.body if isinstance(node, ast.FunctionDef)}
    result = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ADDED_FUNCTIONS:
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name) and node.targets[0].id in ADDED_GLOBALS:
            continue
        if isinstance(node, ast.FunctionDef) and node.name == 'pin':
            node.body = [n for n in node.body if not is_call(n, 'plan04_add_helpers')]
        if isinstance(node, ast.FunctionDef) and node.name == 'compose_target':
            node.body = [n for n in node.body if not is_call(n, 'plan04_check_reviewed')]
            # The final tuple loop writes helpers.
            loops = [n for n in node.body if isinstance(n, ast.For) and
                     isinstance(n.target, ast.Tuple)]
            old_loops = [n for n in original[node.name].body if isinstance(n, ast.For) and
                         isinstance(n.target, ast.Tuple)]
            loop, old_loop = loops[-1], old_loops[-1]
            expected = ast.parse(
                "destination = helpers / name\n"
                "destination.parent.mkdir(parents=True, exist_ok=True)\n"
                "destination.write_bytes(data)\n").body
            assert ast.dump(ast.Module(body=loop.body[-3:], type_ignores=[])) == \
                ast.dump(ast.Module(body=expected, type_ignores=[])), 'undeclared write seam'
            loop.body[-3:] = [old_loop.body[-1]]
        if isinstance(node, ast.FunctionDef) and node.name == 'main':
            kept = []
            for statement in node.body:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and \
                        isinstance(statement.value.func, ast.Attribute) and \
                        statement.value.func.attr == 'add_argument' and \
                        statement.value.args and isinstance(statement.value.args[0], ast.Constant) and \
                        statement.value.args[0].value in ('--plan04-contract', '--plan04-contract-sha256'):
                    continue
                if isinstance(statement, ast.Assign) and \
                        isinstance(statement.targets[0], ast.Name) and statement.targets[0].id == 'plan04':
                    continue
                if isinstance(statement, ast.If) and ast.dump(statement.test) == \
                        ast.dump(ast.parse('plan04 is not None', mode='eval').body):
                    continue
                kept.append(statement)
            node.body = kept
        result.append(node)
    tree.body = result
    return tree


def main():
    raw = BASE.read_bytes()
    assert sha256(raw).hexdigest() == EXPECTED, 'inherited source pin differs'
    baseline = ast.parse(raw)
    candidate = strip_seam(ast.parse(CANDIDATE.read_bytes()), baseline)
    assert ast.dump(candidate) == ast.dump(baseline), 'undeclared inherited change'
    print(json.dumps({
        'status': 'PASS',
        'base_sha256': EXPECTED,
        'candidate_sha256': sha256(CANDIDATE.read_bytes()).hexdigest(),
        'claim': 'All inherited AST unchanged outside explicit additive payload seam.',
    }, indent=2))


if __name__ == '__main__':
    main()
