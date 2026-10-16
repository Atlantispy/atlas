"""R1 fold parity checker and gates (FOLD.md §5, §6, §10.4, §11). "Derive, don't trust": apply exactly the
manifest's declared changes to the original side, then require byte equality. Nothing is erased.

  python -B parity.py records A.json B.json MANIFEST.json        fold parity of one heat record
  python -B parity.py noise A.json A2.json                       noise arm: byte-identical canonical JSON
  python -B parity.py ast ORIGINAL_ROOT FOLDED_SRC MANIFEST.json  AST gate over every folded module
  python -B parity.py pins FOLDED_SRC MANIFEST.json              G-PIN plus the folded-tree shas
Exit 0 = PASS; otherwise one FAIL JSON line naming the first problem (errors included, never a traceback).

MANIFEST (written by the fold tool):
  key_map     {old path (file or directory): new package-relative key}; injective; a new key may not collide with
              a key already present in the same dict
  sha_map     {new key: [old sha256, new sha256]}; `pins` mode checks every new sha against FOLDED_SRC/<new key>
  bookings    [[path in B's key space...], ...]  F6: ints, 0 <= B <= A, then B's value is taken
  external    [{"path": [...B space], "preimage_a": ...}]  F2/F4: ID = stream_hash(preimage); preimage mapped, rehashed
  self_ids    [[path in B's key space...], ...]  F7: ID = stream_hash(enclosing dict without it); deepest first
  modules     {original file relative to ORIGINAL_ROOT: folded file relative to FOLDED_SRC}  (AST gate)
  identity_name       the name folded code binds atlas_tectonics._identity to (default `_identity`); refused where
                      the original module already uses that identifier
  identity_constants  {NAME: key}  what `<identity_name>.NAME` stands for in key space
  pins        {module name: sha256}  G-PIN; each must be sha_map's new sha for the file a clean `python -I` imports
Pins: a hex-64 string (optionally 'sha256:'-prefixed) equal to an old sha in sha_map becomes the new sha wherever it
occurs; directly under a mapped key it must be that key's old sha. An old sha with two different new shas is refused
where it occurs. Bookings are byte counts: a float or bool booking fails closed. A drive or UNC path anywhere in A
must be in key_map; other strings (including ones starting with '/') are compared exactly.
"""
import ast
import copy
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any

USER_PATH = re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/]|^\\\\|[\\/]users[\\/]|/home/|^~[\\/]|%userprofile%|the-diadem'
                       r'|codex[\\/]', re.IGNORECASE)
HEX64 = re.compile(r'^(sha256:)?([0-9a-f]{64})$')
PRIVATE = 'atlas_tectonics._private'
IDENTITY = 'atlas_tectonics._identity'
IMPORTERS = ('import_module', 'find_spec', '__import__')


class ParityError(AssertionError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def stream_hash(value):
    """Same bytes as private_heat_issuer_resources_r1.stream_hash (sort_keys, compact separators, no NaN)."""
    return sha256(canonical(value)).hexdigest()


def _get(record, path) -> Any:
    for step in path:
        record = record[step]
    return record


def _set(record, path, value):
    _get(record, path[:-1])[path[-1]] = value


def _is_abs(text):
    """Drive or UNC path. POSIX-looking strings are compared exactly (and B is still screened by USER_PATH)."""
    return isinstance(text, str) and bool(re.match(r'^([A-Za-z]:[\\/]|\\\\)', text))


class Context:
    """The manifest's declared changes, validated once."""

    def __init__(self, manifest):
        self.key_map = dict(manifest.get('key_map', {}))
        if len(set(self.key_map.values())) != len(self.key_map):
            raise ParityError('key_map is not injective')
        self.inverse = {new: old for old, new in self.key_map.items()}
        self.sha_map = {key: tuple(pair) for key, pair in manifest.get('sha_map', {}).items()}
        self.pin_table = {}
        for old, new in self.sha_map.values():
            self.pin_table.setdefault(old, set()).add(new)
        self.ident = manifest.get('identity_name', '_identity')
        self.constants = dict(manifest.get('identity_constants', {}))
        for name, value in self.constants.items():
            if not isinstance(value, str) or _is_abs(value) or USER_PATH.search(value):
                raise ParityError('identity constant %s is not a package-relative key' % name)
        self.stems = {re.split(r'[\\/]', key)[-1][:-3] for key in self.key_map if key.endswith('.py')}
        self.stems |= {re.split(r'[\\/]', key)[-1][:-3] for key in manifest.get('modules', {}) if key.endswith('.py')}

    def pin(self, text, where):
        match = HEX64.match(text)
        if not match or match.group(2) not in self.pin_table:
            return text
        news = self.pin_table[match.group(2)]
        if len(news) != 1:
            raise ParityError('old sha at %s maps to %d different new shas' % (where, len(news)))
        return (match.group(1) or '') + next(iter(news))

    def a_path(self, path):
        """A path in B's key space, translated back to A's keys."""
        return [self.inverse.get(step, step) if isinstance(step, str) else step for step in path]


def map_paths(value, ctx, where='$'):
    """Rename mapped keys and strings, re-pin old shas, refuse collisions and unmapped drive/UNC paths."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            new, pinned = key, None
            if key in ctx.key_map:
                new = ctx.key_map[key]
                match = isinstance(item, str) and HEX64.match(item)
                if match:
                    old_sha, new_sha = ctx.sha_map.get(new, (None, None))
                    if match.group(2) != old_sha:
                        raise ParityError("pin under %s at %s is not the manifest's old sha" % (new, where))
                    pinned = (match.group(1) or '') + new_sha
            elif _is_abs(key):
                raise ParityError('unmapped absolute key at %s: %s' % (where, key))
            if new in out:
                raise ParityError('two keys map to %s at %s' % (new, where))
            out[new] = pinned if pinned is not None else map_paths(item, ctx, '%s[%s]' % (where, new))
        return out
    if isinstance(value, list):
        return [map_paths(item, ctx, '%s[%d]' % (where, i)) for i, item in enumerate(value)]
    if isinstance(value, str):
        if value in ctx.key_map:
            return ctx.key_map[value]
        if _is_abs(value):
            raise ParityError('unmapped absolute path at %s: %s' % (where, value))
        return ctx.pin(value, where)
    return value


def user_paths(value, where='$'):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if USER_PATH.search(str(key)):
                found.append('%s key %s' % (where, key))
            found += user_paths(item, '%s.%s' % (where, key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found += user_paths(item, '%s[%d]' % (where, i))
    elif isinstance(value, str) and USER_PATH.search(value):
        found.append('%s = %s' % (where, value[:80]))
    return found


def first_difference(a, b, where='$'):
    if type(a) is not type(b):
        return '%s: type %s vs %s' % (where, type(a).__name__, type(b).__name__)
    if isinstance(a, dict):
        if set(a) != set(b):
            return '%s: keys differ (A only %s; B only %s)' % (where, sorted(set(a)-set(b))[:3], sorted(set(b)-set(a))[:3])
        for key in sorted(a):
            found = first_difference(a[key], b[key], '%s.%s' % (where, key))
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return '%s: length %d vs %d' % (where, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, '%s[%d]' % (where, i))
            if found:
                return found
        return None
    return None if canonical(a) == canonical(b) else '%s: %r vs %r' % (where, a, b)


def check_records(a, b, manifest):
    """PASS returns a summary; any failure raises ParityError (or KeyError/ValueError/TypeError) naming the problem."""
    ctx = Context(manifest)
    leaks = user_paths(b)
    if leaks:
        raise ParityError('user path in B: %s' % leaks[0])
    self_ids = manifest.get('self_ids', ())
    a_ids = set()
    for path in self_ids:
        enclosing = dict(_get(a, ctx.a_path(path[:-1])))
        own = enclosing.pop(path[-1])
        if stream_hash(enclosing) != own:
            raise ParityError('A self-ID %s does not match its own preimage (hash recipe wrong?)' % path)
        a_ids.add(own)
    t = map_paths(copy.deepcopy(a), ctx)
    for path in manifest.get('bookings', ()):
        before, after = _get(a, ctx.a_path(path)), _get(b, path)
        if not (type(before) is int and type(after) is int and 0 <= after <= before):
            raise ParityError('booking %s grew or is not a non-negative int: %r -> %r' % (path, before, after))
        _set(t, path, after)
    for entry in manifest.get('external', ()):
        path, pre = entry['path'], entry['preimage_a']
        text = canonical(pre).decode('utf-8')
        if any(own in text for own in a_ids):
            raise ParityError('external preimage %s contains a self-ID (ordering not supported)' % path)
        if stream_hash(pre) != _get(a, ctx.a_path(path)):
            raise ParityError('A external ID %s is not stream_hash of its declared preimage' % path)
        _set(t, path, stream_hash(map_paths(pre, ctx)))
    for path in sorted(self_ids, key=len, reverse=True):
        enclosing = dict(_get(t, path[:-1]))
        enclosing.pop(path[-1])
        _set(t, path, stream_hash(enclosing))
    if canonical(t) != canonical(b):
        # Name the root cause: a changed field shows up before the self-IDs that merely inherit it.
        t2, b2 = copy.deepcopy(t), copy.deepcopy(b)
        for path in self_ids:
            _set(t2, path, None)
            _set(b2, path, None)
        raise ParityError('transformed A differs from B at %s' % (first_difference(t2, b2) or first_difference(t, b)))
    return dict(status='PASS', bytes=len(canonical(b)), mapped_keys=len(ctx.key_map), self_ids=len(self_ids),
                external=len(manifest.get('external', ())))


# ------------------------------------------------------------------ AST gate (M9)
def _unqualify(name):
    return name[len(PRIVATE) + 1:] if name.startswith(PRIVATE + '.') else name


def _marker(kind, *parts):
    # A NUL in the name: no parsed source can contain this node, so a marker cannot be forged by a string.
    return ast.Call(ast.Name('\0' + kind), [ast.Constant(p) for p in parts], [])


def _identifiers(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split('.')[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
    return names


class _Normalise(ast.NodeTransformer):
    """Original side: apply the manifest (key_map to string literals, old pins to new). Folded side: remove the
    private prefix from imports and dotted module names, replace `<ident>.NAME` by its declared key, drop only an
    import that binds <ident> to atlas_tectonics._identity, and list violations (unqualified helper imports, path
    literals). Both sides: one IMPORT(bound, target) marker per alias; str(Path(x).resolve()) and folded
    <ident>.relkey(x) -> KEY(x); folded <ident>.resolve(x) -> Path(x). Everything else must already be identical."""

    def __init__(self, ctx, folded):
        self.ctx, self.folded, self.violations, self.binds_identity = ctx, folded, [], False

    def _markers(self, node, pairs):
        nodes = []
        for bound, target in pairs:
            if self.folded and target.split('.')[0] in self.ctx.stems:
                self.violations.append('line %d: helper %s imported outside %s' % (node.lineno, target, PRIVATE))
            if self.folded and bound == self.ctx.ident and target == IDENTITY:
                self.binds_identity = True
                continue
            nodes.append(ast.Expr(_marker('IMPORT', bound, _unqualify(target) if self.folded else target)))
        return nodes or None

    def visit_Import(self, node):
        return self._markers(node, [(alias.asname or alias.name.split('.')[0], alias.name) for alias in node.names])

    def visit_ImportFrom(self, node):
        base = '.' * node.level + (node.module or '')
        return self._markers(node, [(alias.asname or alias.name, base + '.' + alias.name) for alias in node.names])

    def visit_Constant(self, node):
        if not isinstance(node.value, str):
            return node
        if self.folded:
            if _is_abs(node.value) or USER_PATH.search(node.value):
                self.violations.append('line %d: path literal in folded code' % node.lineno)
            return ast.Constant(_unqualify(node.value))
        if node.value in self.ctx.key_map:
            return ast.Constant(self.ctx.key_map[node.value])
        return ast.Constant(self.ctx.pin(node.value, 'line %d' % node.lineno))

    def visit_Attribute(self, node):
        if self.folded and isinstance(node.value, ast.Name) and node.value.id == self.ctx.ident \
                and node.attr in self.ctx.constants:
            return ast.Constant(self.ctx.constants[node.attr])
        return self.generic_visit(node)

    def visit_Call(self, node):
        if self.folded and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str) and ast.unparse(node.func).split('.')[-1] in IMPORTERS \
                and node.args[0].value.split('.')[0] in self.ctx.stems:
            self.violations.append('line %d: helper %s imported by name outside %s'
                                   % (node.lineno, node.args[0].value, PRIVATE))
        self.generic_visit(node)
        f = node.func
        inner = node.args[0] if len(node.args) == 1 else None
        if (isinstance(f, ast.Name) and f.id == 'str' and not node.keywords and isinstance(inner, ast.Call)
                and not inner.args and not inner.keywords and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == 'resolve' and isinstance(inner.func.value, ast.Call)
                and isinstance(inner.func.value.func, ast.Name) and inner.func.value.func.id == 'Path'
                and len(inner.func.value.args) == 1 and not inner.func.value.keywords):
            return ast.Call(ast.Name('\0KEY'), [inner.func.value.args[0]], [])
        if self.folded and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == self.ctx.ident and len(node.args) == 1 and not node.keywords:
            if f.attr == 'relkey':
                return ast.Call(ast.Name('\0KEY'), [node.args[0]], [])
            if f.attr == 'resolve':
                return ast.Call(ast.Name('Path'), [node.args[0]], [])
        return node


def ast_diff(original_text, folded_text, manifest=None):
    """None when the folded text is the original with only the declared changes; else the first problem."""
    ctx = Context(manifest or {})
    original_tree = ast.parse(original_text)
    folded = _Normalise(ctx, True)
    b = ast.dump(folded.visit(ast.parse(folded_text)), annotate_fields=False)
    if folded.violations:
        return folded.violations[0]
    if folded.binds_identity and ctx.ident in _identifiers(original_tree):
        return 'identity name %s is already an identifier in the original' % ctx.ident
    a = ast.dump(_Normalise(ctx, False).visit(original_tree), annotate_fields=False)
    return None if a == b else 'code differs beyond the declared imports, pins, paths and keys'


def ast_equivalent(original_text, folded_text, manifest=None):
    return ast_diff(original_text, folded_text, manifest) is None


def check_ast(original_root, folded_src, manifest):
    bad = []
    for old, new in sorted(manifest['modules'].items()):
        problem = ast_diff((Path(original_root)/old).read_text(encoding='utf8'),
                           (Path(folded_src)/new).read_text(encoding='utf8'), manifest)
        if problem:
            bad.append('%s (%s)' % (old, problem))
    if bad:
        raise ParityError('AST gate: %d module(s) changed beyond the declared fold: %s' % (len(bad), bad[:5]))
    return dict(status='PASS', modules=len(manifest['modules']))


# ------------------------------------------------------------------ G-PIN (FOLD §10.4, M10)
_PROBE = ('import hashlib, importlib, importlib.util, json, sys\n'
          'names, stems = json.loads(sys.argv[2]), json.loads(sys.argv[3])\n'
          'out = {"files": {}, "top_level": []}\n'
          'for name in names:\n'
          '    origin = importlib.import_module(name).__spec__.origin\n'
          '    out["files"][name] = [origin, hashlib.sha256(open(origin, "rb").read()).hexdigest()]\n'
          'out["top_level"] = sorted(s for s in stems if importlib.util.find_spec(s) is not None)\n'
          'print(json.dumps(out))\n')


def check_pins(folded_src, manifest, python=sys.executable):
    """Every sha_map new sha is the sha of FOLDED_SRC/<key>; no bytecode is present; a clean interpreter (-I -B)
    imports each pinned module from FOLDED_SRC/<key> with sha_map's new sha, which equals the pin; no helper stem is
    importable at top level."""
    import subprocess
    root = Path(folded_src).resolve()
    ctx = Context(manifest)
    for key, (_, new) in sorted(ctx.sha_map.items()):
        path = root/key
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != new:
            raise ParityError("folded file %s does not have the manifest's new sha" % key)
    stale = sorted(p.relative_to(root).as_posix() for p in root.rglob('*.pyc'))
    if stale:
        raise ParityError('bytecode in the folded tree could shadow the pinned source: %s' % stale[:3])
    pins = manifest['pins']
    stems = sorted({name.split('.')[-1] for name in pins} | ctx.stems)
    run = subprocess.run([python, '-I', '-B', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); exec(%r)' % _PROBE,
                          str(root), json.dumps(sorted(pins)), json.dumps(stems)],
                         capture_output=True, text=True, cwd=str(root.parent), check=False)
    if run.returncode:
        raise ParityError('G-PIN import failed: %s' % run.stderr.strip()[-300:])
    seen = json.loads(run.stdout)
    wrong = []
    for name, sha in sorted(pins.items()):
        origin, executed = seen['files'][name]
        try:
            key = Path(origin).resolve().relative_to(root).as_posix()
        except (TypeError, ValueError):
            key = None
        if key is None or not key.endswith('.py') or executed != sha or ctx.sha_map.get(key, (None, None))[1] != sha:
            wrong.append('%s (imported %s)' % (name, key or origin))
    if wrong:
        raise ParityError('G-PIN: %d pin(s) differ from the imported file or sha_map: %s' % (len(wrong), wrong[:5]))
    if seen['top_level']:
        raise ParityError('G-PIN: helper(s) importable at top level: %s' % seen['top_level'][:5])
    return dict(status='PASS', pins=len(pins), files=len(ctx.sha_map))


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def main(argv):
    try:
        if argv[:1] == ['records'] and len(argv) == 4:
            print(json.dumps(check_records(_load(argv[1]), _load(argv[2]), _load(argv[3]))))
        elif argv[:1] == ['noise'] and len(argv) == 3:
            a, b = _load(argv[1]), _load(argv[2])
            if canonical(a) != canonical(b):
                raise ParityError('noise arm differs at %s' % first_difference(a, b))
            print(json.dumps(dict(status='PASS', bytes=len(canonical(a)))))
        elif argv[:1] == ['ast'] and len(argv) == 4:
            print(json.dumps(check_ast(argv[1], argv[2], _load(argv[3]))))
        elif argv[:1] == ['pins'] and len(argv) == 3:
            print(json.dumps(check_pins(argv[1], _load(argv[2]))))
        else:
            raise SystemExit(__doc__)
    except (ParityError, KeyError, IndexError, TypeError, ValueError, OSError) as error:
        print(json.dumps(dict(status='FAIL', reason='%s: %s' % (type(error).__name__, error))))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
