"""P2 refuter: names bound inside the preparation loop and read after it (function scope).

Reads the candidate source only. Lists, for moving_wall_integrals, every name stored by the
`for original in ...` loop body (function scope; comprehensions and nested defs excluded) and
every load of that name after the loop, in the function scope or as a free variable of a
nested def/lambda/comprehension defined after the loop. For each such load the nearest
preceding binding of that name after the loop (if any) is shown.
"""
import ast
import sys

path = sys.argv[1]
tree = ast.parse(open(path, encoding='utf-8').read())
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'moving_wall_integrals')
loop = next(s for s in fn.body if isinstance(s, ast.For) and isinstance(s.target, ast.Name) and s.target.id == 'original')
print('prep loop lines', loop.lineno, loop.end_lineno)

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp, ast.SetComp,
          ast.DictComp, ast.GeneratorExp, ast.ClassDef)


def stores(node, out, top=True):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, SCOPES):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(child.name)
            # comprehension targets are local to the comprehension
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            out.add(child.id)
        if isinstance(child, ast.ExceptHandler) and child.name:
            out.add(child.name)
        stores(child, out, False)


loop_names = set()
stores(loop, loop_names)
loop_names.add('original')
print('names bound in loop:', sorted(loop_names))

# every Name load after the loop, at any depth (nested scopes included: free vars resolve here
# unless the nested scope binds them itself)
after = [s for s in fn.body if s.lineno > loop.end_lineno]


def nested_binds(scope):
    out = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        for a in scope.args.args + scope.args.kwonlyargs + scope.args.posonlyargs:
            out.add(a.arg)
        body = scope.body if isinstance(scope.body, list) else [scope.body]
        for b in body:
            for n in ast.walk(b):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    out.add(n.id)
    else:
        for gen in scope.generators:
            for n in ast.walk(gen.target):
                if isinstance(n, ast.Name):
                    out.add(n.id)
    return out


hits = []


def visit(node, shadow):
    for child in ast.iter_child_nodes(node):
        s = shadow
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp,
                              ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            s = shadow | nested_binds(child)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id in loop_names \
                and child.id not in shadow:
            hits.append((child.lineno, child.id))
        visit(child, s)


for stmt in after:
    visit(ast.Module(body=[stmt], type_ignores=[]), frozenset())

# function-scope stores after the loop, with line numbers
post_stores = []
for stmt in after:
    tmp = set()
    for n in ast.walk(stmt):
        pass
for n in ast.walk(ast.Module(body=after, type_ignores=[])):
    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
        post_stores.append((n.lineno, n.id))
    if isinstance(n, ast.ExceptHandler) and n.name:
        post_stores.append((n.lineno, n.name))

for line, name in sorted(set(hits)):
    prior = [l for l, nm in post_stores if nm == name and l <= line]
    print('load %-14s line %4d  nearest post-loop store line: %s' % (name, line, max(prior) if prior else 'NONE'))
