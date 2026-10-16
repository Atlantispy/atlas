#!/usr/bin/env python3
"""Map what each test unit executes and opens, and select the tests a change can affect (conservatively).

WORKING NON-CANON development tool (docs/DEVELOPMENT_TOOLS.md). Standard library only; recording, the environment
fingerprint and the compile check use the tested interpreter given by ``--python``. Keep the map outside tracked files.

``record`` runs every test unit of the recorded suite (``tectonics/tests``: a class, or a whole module where module
fixtures exist) in its OWN fresh process through run_tests_parallel.py, with ``sys.monitoring`` and an audit hook from
before the unit is loaded. Per unit it keeps: the repository files whose functions ran (``executed``: functions,
methods, lambdas, generator expressions), whose module or class bodies ran (``modules``: imported), whose bytes were
read (``opened``: data, source read by code -- the execution-identity guard reads every package source on every
verify -- and the sources of shutil copies, sqlite and ctypes loads; the import system compiling a module it imports is
the import, not a read), the directories it listed (``scanned``), whether it started a process, compiled a numba
dispatcher, ran code that can inspect code objects (``observes_code``) or skipped a test. The map also records the
interpreter, installed distributions and ATLAS_/NUMBA_/PYTHON environment (the fingerprint).

``select`` returns the units (or whole test modules) of the recorded suite that a change can affect. False positives are
allowed; a false negative is not. Per changed file (git diff BASE HEAD, or ``--files`` against the root's HEAD):

* everything: added, deleted, renamed, copied or type-changed files; a ``.gitattributes``/``.gitmodules`` change; a
  file not in the map; a non-Python file no recorded unit opened; a map whose tree differs from BASE in membership; a
  fingerprint that differs from the recording;
* a tracked file whose content at BASE differs from the map counts as a structural change;
* a Python file whose change is confined to function and method bodies (the module skeleton -- every statement
  outside function bodies, every signature, default, decorator, annotation, docstring and whether a function is a
  generator or coroutine -- is unchanged) and that still compiles under the tested interpreter with warnings as
  errors -> the units that executed code of the file, opened it or listed its folder, and the code-observing units
  that imported it;
* any other change to a Python file -> also every unit that imported it, and those units' whole test modules;
* a non-Python file -> the units that opened it or listed its folder;
* a file that imports numba, names a numba decorator, or held a dispatcher that compiled while recording -> also
  every unit that compiled any dispatcher (compiled and inlined kernels emit no Python events);
* always: units that started a process, failed, timed out, skipped a test or have no trace;
* a changed test file of the recorded suite selects its whole module. A changed test file elsewhere, and any changed
  file no recorded unit touched, are reported (``outside_scope``, ``untouched``): other suites must cover them.

Assumptions (docs/DEVELOPMENT_TOOLS.md): tests are deterministic given the tree and the fingerprint; a unit's outcome
does not depend on other units run before it in the same process (selected units can be run with ``--fresh`` to match
the recording exactly); a test observes a repository file only by executing its code, importing it, reading its bytes,
listing its folder or (code-observing units) inspecting code objects of modules it imported.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import fnmatch
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

SCHEMA = 'atlas.dev.test-impact-map.v4'
NUMBA_DECORATORS = {'njit', 'jit', 'vectorize', 'guvectorize', 'stencil', 'cfunc', 'generated_jit', 'overload',
                    'register_jitable', 'intrinsic', 'jitclass', 'overload_method', 'overload_attribute'}
# Syntax through which code can observe another function's code object, body or line numbers without running it.
CODE_ATTRIBUTES = {'__code__', 'f_code', 'gi_code', 'cr_code', 'ag_code', 'func_code', 'f_lineno', 'tb_lineno',
                   'lineno'}
CODE_FUNCTIONS = {'getsource', 'getsourcelines', 'getsourcefile', 'findsource', 'getclosurevars', 'getblock',
                  'isgeneratorfunction', 'iscoroutinefunction', 'isasyncgenfunction', 'getcomments', 'getmembers',
                  'get_referents', 'getattr_static', 'currentframe', '_getframe', 'stack', 'extract_stack',
                  'getframeinfo', 'getouterframes', 'getinnerframes', 'format_stack'}
CODE_MODULES = {'marshal', 'dis'}                              # any use observes
INTROSPECTION_MODULES = {'inspect', 'sys', 'traceback', 'gc'}    # only their CODE_FUNCTIONS observe
EVERYTHING_NAMES = {'.gitattributes', '.gitmodules'}
SUITE_DIR = 'tectonics/tests'
SUITE_PATTERNS = ('test_*.py', 'check_native_transport.py')

_runner_spec = importlib.util.spec_from_file_location('impact_runner', Path(__file__).with_name('run_tests_parallel.py'))
_runner = importlib.util.module_from_spec(_runner_spec)
_runner_spec.loader.exec_module(_runner)
COMPILES = r'''
import base64, json, sys, warnings
out = []
for name, data in json.loads(sys.stdin.read()):
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        try:
            compile(base64.b64decode(data), name, 'exec', dont_inherit=True)
            out.append(True)
        except BaseException:
            out.append(False)
print(json.dumps(out))
'''


def _git(root, *args, binary=False):
    proc = subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(root), *args], capture_output=True)
    if proc.returncode:
        raise RuntimeError('git %s failed: %s' % (' '.join(args), proc.stderr.decode(errors='replace')[-2000:]))
    return proc.stdout if binary else proc.stdout.decode('utf-8', errors='replace')


def tracked_blobs(root, revision=None):
    """{repo-relative path: git blob id} of a commit (``revision``) or of the clean working tree."""
    if revision is None:
        if _git(root, 'status', '--porcelain', '--untracked-files=no').strip():
            raise RuntimeError('the tree has uncommitted changes: record from a clean commit')
        revision = 'HEAD'
    out = {}
    for line in _git(root, 'ls-tree', '-r', revision).splitlines():
        meta, path = line.split('\t', 1)
        out[path] = meta.split()[2]
    return out


def fingerprint(python, root):
    return _runner.runtime_fingerprint(python, root)


def _parse(root, path):
    try:
        return ast.parse((Path(root)/path).read_bytes())
    except (SyntaxError, ValueError, OSError):
        return None


def _numba_files(root, blobs):
    """Python files that import numba or name a numba decorator or wrapper; unparsable files count (fail closed)."""
    out = []
    for path in blobs:
        if not path.endswith('.py'):
            continue
        tree = _parse(root, path)
        if tree is None:
            out.append(path)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split('.')[0] == 'numba' for a in node.names):
                break
            if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'numba':
                break
            if isinstance(node, (ast.Name, ast.Attribute)) and \
                    (node.id if isinstance(node, ast.Name) else node.attr) in NUMBA_DECORATORS:
                break
        else:
            continue
        out.append(path)
    return sorted(out)


def _aliases(tree):
    """(names whose every use observes: marshal, dis and introspection functions imported by name; names bound to the
    introspection modules) for one module, from its imports anywhere."""
    code_names, module_names = set(CODE_MODULES), set(INTROSPECTION_MODULES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top, bound = alias.name.split('.')[0], (alias.asname or alias.name).split('.')[0]
                if top in CODE_MODULES:
                    code_names.add(bound)
                if top in INTROSPECTION_MODULES:
                    module_names.add(bound)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or '').split('.')[0]
            for alias in node.names:
                if module in CODE_MODULES or (module in INTROSPECTION_MODULES and alias.name in CODE_FUNCTIONS):
                    code_names.add(alias.asname or alias.name)
    return code_names, module_names


def _observes(node, names=(frozenset(CODE_MODULES), frozenset(INTROSPECTION_MODULES))):
    """Code in ``node`` uses a code-object or line-number attribute (also as a string, e.g. getattr(f, '__code__')),
    marshal or dis, or an introspection function of inspect/sys/traceback/gc (by attribute or imported name). An import
    alone observes nothing."""
    code_names, module_names = names
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            if sub.attr in CODE_ATTRIBUTES or sub.attr.startswith('co_'):
                return True
            if sub.attr in CODE_FUNCTIONS and isinstance(sub.value, ast.Name) and sub.value.id in module_names:
                return True
        if isinstance(sub, ast.Name) and sub.id in code_names:
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and (
                sub.value in CODE_ATTRIBUTES or sub.value.startswith('co_') or sub.value in CODE_MODULES):
            return True
    return False


def _code_observers(root, blobs):
    """{path: [qualified names]} of the outermost functions (and '<module>' for module-level code) whose source can
    observe code objects. Nested code runs only after its outermost function ran, so charging that one is sound. An
    unparsable file is charged whole ('<module>')."""
    out = {}
    for path in blobs:
        if not path.endswith('.py'):
            continue
        tree = _parse(root, path)
        if tree is None:
            out[path] = ['<module>']
            continue
        found, names = set(), _aliases(tree)

        def visit(body, prefix, in_class=False):
            if in_class and any(isinstance(n, ast.Global) for n in body):
                found.add('<module>')                 # a 'global' def in a class body is named outside the class
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # decorators and defaults run where the def is; the body when the function runs
                    if any(_observes(part, names) for part in (*node.decorator_list, node.args)):
                        found.add('<module>')
                    if _observes(node, names):
                        found.add(prefix+node.name)
                elif isinstance(node, ast.ClassDef):
                    if any(_observes(part, names) for part in (*node.decorator_list, *node.bases, *node.keywords)):
                        found.add('<module>')
                    visit(node.body, prefix+node.name+'.', in_class=True)
                else:
                    # Module- or class-level statements run on import. Compound statements may hold definitions
                    # (qualified names unchanged), so their bodies are visited; everything else is charged whole.
                    blocks = [getattr(node, f) for f in ('body', 'orelse', 'finalbody') if
                              isinstance(getattr(node, f, None), list)]
                    handlers = getattr(node, 'handlers', [])
                    cases = getattr(node, 'cases', [])
                    blocks += [h.body for h in handlers] + [c.body for c in cases]
                    if not blocks:
                        if _observes(node, names):
                            found.add('<module>')
                        continue
                    header = copy.copy(node)
                    for f in ('body', 'orelse', 'finalbody', 'handlers', 'cases'):
                        if hasattr(header, f):
                            setattr(header, f, [])
                    parts = [header] + [h.type for h in handlers if h.type is not None]
                    parts += [c.pattern for c in cases] + [c.guard for c in cases if c.guard is not None]
                    if any(_observes(part, names) for part in parts):
                        found.add('<module>')
                    for block in blocks:
                        visit(block, prefix, in_class)
        visit(tree.body, '')
        if found:
            out[path] = sorted(found)
    return out


# ---------------------------------------------------------------------------------------------------------------
# The module skeleton: everything outside function bodies. Docstrings stay (__doc__ is visible without a call), and so
# does whether a function is a generator or coroutine (the code flags change what a call does).

def _body_kinds(body):
    found, stack = set(), list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            found.add('yield')
        elif isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            found.add('await')
        stack.extend(ast.iter_child_nodes(node))
    return found


class _Hollow(ast.NodeTransformer):
    def _hollow(self, node):
        kinds = _body_kinds(node.body)
        node = self.generic_visit(node)
        first = node.body[0] if node.body else None
        keep = [first] if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                           and isinstance(first.value.value, str)) else []
        markers = [ast.Expr(ast.Name('__%s__' % kind, ast.Load())) for kind in sorted(kinds)]
        node.body = keep + markers + [ast.Pass()]
        return node

    visit_FunctionDef = _hollow
    visit_AsyncFunctionDef = _hollow


def skeleton(source):
    """The module's AST with every function body replaced by its docstring, generator/coroutine markers and ``pass``
    (signatures, defaults, decorators, annotations, class bodies and module statements kept), without line numbers.
    None if it does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    return ast.dump(_Hollow().visit(copy.deepcopy(tree)), include_attributes=False)


def change_kind(old, new):
    """'body' when only function bodies (not docstrings or generator/coroutine status) differ, or nothing at all;
    else 'structural'. The caller must still check that the new source compiles (compiles())."""
    a, b = skeleton(old), skeleton(new)
    if a is None or b is None:
        return 'structural'
    return 'body' if a == b else 'structural'


def compiles(python, sources):
    """[bool] per (name, bytes): compiles under ``python`` with every warning an error."""
    if not sources:
        return []
    payload = json.dumps([[name, base64.b64encode(data).decode()] for name, data in sources])
    proc = subprocess.run([python, '-I', '-c', COMPILES], input=payload, capture_output=True, text=True)
    if proc.returncode:
        return [False]*len(sources)
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------------------------------------------
# Recording.

def _relative(root, path):
    try:
        full = os.path.normcase(os.path.abspath(path))
    except (TypeError, ValueError):
        return None
    base = os.path.normcase(os.path.abspath(root))
    if full == base:
        return '.'
    if not full.startswith(base+os.sep):
        return None
    return Path(os.path.relpath(full, base)).as_posix()


def record(args):
    root = Path(args.root).resolve()
    current_source = _runner.source_snapshot(root)
    blobs = current_source['files']
    if args.from_run:
        # Rebuild the map from an earlier traced run of this same clean commit (after a change to these rules).
        run_dir = Path(args.from_run).resolve()
        trace_dir = run_dir/'traces'
        summary = json.loads((run_dir/'run'/'summary.json').read_text(encoding='utf-8'))
        if (not summary.get('fresh_process_per_unit') or not trace_dir.is_dir()
                or os.path.normcase(str(Path(summary['root']).resolve())) != os.path.normcase(str(root))):
            raise SystemExit('--from-run needs a traced fresh-process run of this root')
        runner_exit = None
    else:
        run_dir = Path(args.run_dir or tempfile.mkdtemp(prefix='atlas-impact-')).resolve()
        if run_dir.exists() and any(run_dir.iterdir()):
            raise SystemExit('the run folder must be new or empty: ' + str(run_dir))
        trace_dir = run_dir/'traces'
        trace_dir.mkdir(parents=True, exist_ok=True)
        runner = Path(__file__).with_name('run_tests_parallel.py')
        command = [args.python, '-B', str(runner), '--root', str(root), '--python', args.python, '--fresh',
                   '--trace-dir', str(trace_dir), '--run-dir', str(run_dir/'run'), '--workers', str(args.workers)]
        for pattern in SUITE_PATTERNS:
            command += ['--pattern', pattern]
        if args.durations:
            command += ['--durations', args.durations]
        runner_exit = subprocess.run(command, capture_output=True, text=True).returncode
        summary = json.loads((run_dir/'run'/'summary.json').read_text(encoding='utf-8'))
    provenance = summary.get('provenance') or {}
    before, after = provenance.get('before'), provenance.get('after')
    if (not before or before != after or not provenance.get('unchanged')
            or before.get('source') != current_source):
        raise ValueError('traced run source provenance is missing, changed or from another commit: re-record')
    if (before.get('fingerprint') != fingerprint(args.python, root)
            or before.get('cwd') != str(root) or before.get('src') != str(root/'tectonics'/'src')
            or before.get('tests_dir') != str(root/SUITE_DIR)):
        raise ValueError('traced run runtime, environment or execution paths changed: re-record')
    if (not summary.get('fresh_process_per_unit') or summary.get('quick') or summary.get('only')
            or summary.get('patterns') != list(SUITE_PATTERNS)):
        raise ValueError('traced run is not the complete fresh-process impact selection: re-record')
    case = {os.path.normcase(p): p for p in blobs}           # traces from a case-insensitive filesystem

    def mapped(paths):
        out = set()
        for p in paths:
            rel = _relative(root, p)
            if rel is not None:
                out.add(case.get(os.path.normcase(rel), rel))
        return sorted(out)

    def under(paths):
        """Tracked files equal to or inside the given paths (the sources of copies)."""
        prefixes = mapped(paths)
        return sorted(p for p in blobs if any(p == q or q == '.' or p.startswith(q.rstrip('/')+'/') for q in prefixes))
    observers = _code_observers(root, blobs)
    observed = {p+'::'+q for p, names in observers.items() for q in names if q != '<module>'}
    module_observers = {p for p, names in observers.items() if '<module>' in names}
    by_unit = {}
    for line in (run_dir/'run'/'results.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            by_unit[row['unit']] = row
    units, compiled = {}, set()
    for unit, row in by_unit.items():
        trace_path = trace_dir/(unit+'.json')
        trace = json.loads(trace_path.read_text(encoding='utf-8')) if trace_path.is_file() else None
        outcomes = [t['outcome'] for t in row['tests'].values()]
        units[unit] = dict(tests=sorted(row['tests']), skipped='skipped' in outcomes,
                           complete=(trace is not None and not row.get('crashed') and not row.get('timeout')
                                     and all(o in ('success', 'skipped', 'expected_failure') for o in outcomes)))
        if trace is not None:
            functions = set()
            for item in trace['functions']:
                filename, _, qualname = item.partition('::')
                rel = mapped([filename])
                if rel:
                    functions.add(rel[0]+'::'+qualname)
            modules = mapped(trace['modules'])
            numba_files = mapped(trace['numba_compiled'])
            compiled.update(numba_files)
            units[unit].update(executed=mapped(trace['executed']), modules=modules,
                               opened=sorted(set(mapped(trace['opened'])) | set(under(trace.get('copied', [])))),
                               identity_reads=mapped(trace['identity_reads']), scanned=mapped(trace['scanned']),
                               spawned=bool(trace['spawned']), numba=bool(trace['numba_compiled']),
                               observes_code=bool(functions & observed or module_observers & set(modules)))
    # Every discovered test belongs to a unit; a unit with no recorded row is incomplete (always selected).
    recorded = {t for row in units.values() for t in row['tests']}
    for test_id in summary['tests']:
        if test_id not in recorded and ' (' not in test_id:
            unit = test_id.rsplit('.', 1)[0]
            units.setdefault(unit, dict(tests=[], skipped=False, complete=False))['tests'].append(test_id)
    numba = sorted(set(_numba_files(root, blobs)) | (compiled & set(blobs)))
    if _runner.source_snapshot(root) != current_source or fingerprint(args.python, root) != before['fingerprint']:
        raise ValueError('source or runtime changed while constructing the map: re-record')
    out = dict(schema=SCHEMA, commit=before['source']['commit'], scope=dict(tests_dir=SUITE_DIR, patterns=list(SUITE_PATTERNS)),
               fingerprint=before['fingerprint'], files=before['source']['files'], provenance=provenance,
               numba_files=numba, code_observers=observers,
               units=units, recorded_with=dict(runner_exit=runner_exit, run=str(run_dir),
                                               wall_seconds=summary['wall_seconds'], counts=summary['counts'],
                                               tests_selected=summary['tests_selected']))
    Path(args.map).write_text(json.dumps(out, indent=1), encoding='utf-8')
    incomplete = sorted(u for u, v in units.items() if not v['complete'])
    print(json.dumps(dict(map=args.map, units=len(units), incomplete_units_always_selected=incomplete,
                          wall_seconds=round(summary['wall_seconds'], 1), counts=summary['counts'])))
    return 0


# ---------------------------------------------------------------------------------------------------------------
# Selection.

def changed_files(root, base, head):
    """[(status letter, path)] between two revisions; renames and copies report both paths."""
    out = []
    for line in _git(root, 'diff', '--name-status', '--no-renames', base, head).splitlines():
        parts = line.split('\t')
        out.extend((parts[0][0], p) for p in parts[1:])
    for line in _git(root, 'diff', '--name-status', '-M', '-C', base, head).splitlines():
        parts = line.split('\t')
        if parts[0][0] in 'RC':
            out.extend((parts[0][0], p) for p in parts[1:])
    return out


def _in_suite(the_map, path):
    scope = the_map.get('scope', dict(tests_dir=SUITE_DIR, patterns=list(SUITE_PATTERNS)))
    folder = PurePosixPath(path).parent.as_posix()
    name = PurePosixPath(path).name
    return folder == scope['tests_dir'] and any(fnmatch.fnmatchcase(name, p) for p in scope['patterns'])


def select(the_map, root, base, head=None, files=None, python=None):
    """{'all', 'all_reasons', 'reasons', 'always', 'units', 'modules', 'outside_scope', 'untouched'} for the change BASE
    -> HEAD, or for ``files`` (working-tree changes against the root's HEAD). ``units`` are run_tests_parallel units;
    ``modules`` are test modules to run whole. ``python`` is the tested interpreter (fingerprint and compile check);
    it is required for a recorded map."""
    root = Path(root)
    units = the_map['units']
    reasons, chosen, modules, everything, outside, untouched = {}, set(), set(), [], [], []
    if 'fingerprint' in the_map:
        if python is None:
            raise ValueError('select needs the tested interpreter (--python) for a recorded map')
        if fingerprint(python, root) != the_map['fingerprint']:
            everything.append('the interpreter, installed distributions or ATLAS_/NUMBA_/PYTHON environment differ '
                              'from the recording')
    if files is not None:
        base, head = 'HEAD', None
        at_head = tracked_blobs(root, 'HEAD')
        changes = []
        for path in files:
            path = PurePosixPath(path.replace('\\', '/')).as_posix()
            exists = (root/path).is_file() and not (root/path).is_symlink()
            changes.append(('A' if path not in at_head else 'M' if exists else 'D', path))
    else:
        changes = changed_files(root, base, head)
    try:
        at_base = tracked_blobs(root, base)
    except RuntimeError:
        at_base = None
    if at_base is None:
        everything.append('BASE is not available to compare with the map')
    else:
        for path in sorted(set(at_base) | set(the_map['files'])):
            if at_base.get(path) != the_map['files'].get(path):
                if path not in the_map['files'] or path not in at_base:
                    everything.append('the map and BASE differ in membership: '+path)
                else:
                    changes.append(('S', path))              # stale map entry: treat as a structural change
    numba = set(the_map['numba_files'])
    python_changes = []
    for status, path in changes:
        if status not in 'MS':
            everything.append('%s file: %s' % ({'A': 'added', 'D': 'deleted', 'R': 'renamed', 'C': 'copied',
                                                 'T': 'type-changed'}.get(status, 'changed (%s)' % status), path))
            continue
        if PurePosixPath(path).name in EVERYTHING_NAMES:
            everything.append('a git attribute or module file changed: '+path)
            continue
        if path not in the_map['files']:
            everything.append('a file not in the map: '+path)
            continue
        if PurePosixPath(path).name.startswith('test_') and path.endswith('.py'):
            if _in_suite(the_map, path):
                modules.add(PurePosixPath(path).stem)
            else:
                outside.append(path)
        elif _in_suite(the_map, path):
            modules.add(PurePosixPath(path).stem)
        if path.endswith('.py'):
            if status == 'S':
                python_changes.append([path, 'structural', None])
            else:
                old = _git(root, 'show', '%s:%s' % (base, path), binary=True)
                new = (root/path).read_bytes() if head is None else _git(root, 'show', '%s:%s' % (head, path),
                                                                          binary=True)
                python_changes.append([path, change_kind(old, new), new])
        else:
            folder = PurePosixPath(path).parent.as_posix()
            hit = {u for u, row in units.items() if 'opened' in row and (path in row['opened']
                                                                       or folder in row.get('scanned', ()))}
            if not hit:
                everything.append('a non-Python file no recorded unit opened: '+path)
                continue
            reasons[path] = dict(kind='data', units=len(hit))
            chosen |= hit
    # A body edit must still compile under the tested interpreter (some errors appear only after parsing).
    body = [c for c in python_changes if c[1] == 'body']
    for change, ok in zip(body, compiles(python or 'python', [(c[0], c[2]) for c in body])):
        if not ok:
            change[1] = 'structural'
    for path, kind, _ in python_changes:
        folder = PurePosixPath(path).parent.as_posix()
        hit = set()
        for unit, row in units.items():
            if 'executed' not in row:
                continue
            if (path in row['executed'] or path in row['opened'] or folder in row.get('scanned', ())
                    or ((kind == 'structural' or row['observes_code']) and path in row['modules'])
                    or (path in numba and row['numba'])):
                hit.add(unit)
        if kind == 'structural':
            modules |= {u.split('.', 1)[0] for u in hit if path in units[u]['modules']}
        reasons[path] = dict(kind=kind, units=len(hit))
        if not hit and path not in outside:
            untouched.append(path)
        chosen |= hit
    always = {u for u, row in units.items() if not row.get('complete') or row.get('spawned') or row.get('skipped')}
    return dict(all=bool(everything), all_reasons=everything, reasons=reasons, always=sorted(always),
                units=sorted(chosen | always), modules=sorted(modules), outside_scope=sorted(outside),
                untouched=sorted(untouched))


def summarise(the_map, result):
    tests = {u: sum(' (' not in t for t in r['tests']) for u, r in the_map['units'].items()}   # not subtest records
    if result['all']:
        return dict(selected_units=len(tests), selected_tests=sum(tests.values()))
    chosen = set(result['units']) | {u for u in tests if u.split('.', 1)[0] in result['modules']}
    return dict(selected_units=len(chosen), selected_tests=sum(tests[u] for u in chosen))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    rec = sub.add_parser('record', help='record the map from a clean commit')
    rec.add_argument('--root', default='.')
    rec.add_argument('--python', required=True, help='the tested interpreter')
    rec.add_argument('--map', required=True, help='output JSON (keep it outside tracked files)')
    rec.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2)-2))
    rec.add_argument('--durations', help='a previous results.jsonl, to start long units first')
    rec.add_argument('--run-dir', help='a new or empty folder for the traced run')
    rec.add_argument('--from-run', help='rebuild from an earlier traced run (RUN_DIR) of this clean commit')
    sel = sub.add_parser('select', help='the units a change can affect')
    sel.add_argument('--map', required=True)
    sel.add_argument('--root', default='.')
    sel.add_argument('--python', required=True, help='the tested interpreter (fingerprint and compile check)')
    sel.add_argument('base', nargs='?')
    sel.add_argument('head', nargs='?')
    sel.add_argument('--files', nargs='+', help='working-tree changes against the root\'s HEAD (no BASE HEAD)')
    sel.add_argument('--only-args', action='store_true', help='print run_tests_parallel --only arguments')
    args = parser.parse_args(argv)
    if args.command == 'record':
        return record(args)
    the_map = json.loads(Path(args.map).read_text(encoding='utf-8'))
    if the_map.get('schema') != SCHEMA:
        raise SystemExit('not a test-impact map of this schema: re-record')
    if (args.files is None) == (args.base is None or args.head is None) or (args.files and args.base):
        raise SystemExit('give either BASE HEAD or --files')
    result = select(the_map, Path(args.root).resolve(), args.base, args.head, args.files, python=args.python)
    if args.only_args:
        print('' if result['all'] else ' '.join('--only '+u for u in result['units']+result['modules']))
        return 0
    result.update(summarise(the_map, result), total_units=len(the_map['units']),
                  total_tests=summarise(the_map, dict(all=True))['selected_tests'])
    print(json.dumps(result, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
