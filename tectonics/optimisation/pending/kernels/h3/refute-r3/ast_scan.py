import ast, sys
def scan(path):
    src = open(path, encoding='utf8').read()
    tree = ast.parse(src)
    top = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets]
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                top.setdefault((a.asname or a.name).split('.')[0], node.lineno)
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    top.setdefault(n.id, node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            top.setdefault(node.name, node.lineno)
    upper = {k: v for k, v in top.items() if k.isupper()}
    print(path)
    print(' module-level isupper() names:', sorted(upper.items(), key=lambda x: x[1]))
    # writes inside functions to any top-level name
    mut_methods = {'append','extend','insert','pop','remove','clear','update','setdefault','add','discard','sort','reverse','popitem'}
    class V(ast.NodeVisitor):
        def __init__(s): s.fn=[]; s.loc=[]
        def visit_FunctionDef(s, n):
            s.fn.append(n.name)
            local = {a.arg for a in n.args.args+n.args.kwonlyargs}
            for m in ast.walk(n):
                if isinstance(m, ast.Name) and isinstance(m.ctx, ast.Store): local.add(m.id)
            glob = set()
            for m in ast.walk(n):
                if isinstance(m,(ast.Global,ast.Nonlocal)): glob |= set(m.names); print('  GLOBAL/NONLOCAL in',n.name,m.names)
            for m in ast.walk(n):
                # subscript store / del
                if isinstance(m,(ast.Subscript,)) and isinstance(m.ctx,(ast.Store,ast.Del)) and isinstance(m.value,ast.Name):
                    nm=m.value.id
                    if nm in top and (nm not in local):
                        print('  subscript write to module name',nm,'in',n.name,'line',m.lineno)
                if isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute) and isinstance(m.func.value, ast.Name):
                    nm=m.func.value.id
                    if nm in top and nm not in local and m.func.attr in mut_methods:
                        print('  mutating call',nm+'.'+m.func.attr,'in',n.name,'line',m.lineno)
                if isinstance(m, ast.AugAssign) and isinstance(m.target, ast.Name) and m.target.id in glob:
                    print('  augassign global', m.target.id, n.name)
                if isinstance(m,(ast.Assign,)) :
                    for t in m.targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id in top and t.value.id not in local:
                            print('  attr write to module name', t.value.id+'.'+t.attr, 'in', n.name, 'line', m.lineno)
            s.generic_visit(n)
            s.fn.pop()
        visit_AsyncFunctionDef=visit_FunctionDef
    V().visit(tree)
    # module-level (non-def) mutations after first assignment
    for node in tree.body:
        for m in ast.walk(node) if not isinstance(node,(ast.FunctionDef,ast.ClassDef)) else []:
            if isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute) and isinstance(m.func.value, ast.Name) and m.func.value.id in top and m.func.attr in mut_methods:
                print('  module-level mutating call', m.func.value.id+'.'+m.func.attr, 'line', m.lineno)
            if isinstance(m, ast.Subscript) and isinstance(m.ctx, ast.Store) and isinstance(m.value, ast.Name):
                print('  module-level subscript write', m.value.id, 'line', m.lineno)
for p in sys.argv[1:]: scan(p)
