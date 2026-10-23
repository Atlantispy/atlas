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
AST gate: the private helpers are the key_map and modules entries whose new key is a .py file under
atlas_tectonics/_private/; a private name is replaced by the name the original imports, and folded code may import
neither bare (statement, importer call, or source text in a string, which is parsed or else screened by regex).
Source text must import a helper as `import atlas_tectonics._private.X as Y` or `from atlas_tectonics._private.X
import ...`. `Path(...)` rules apply only where Path is bound solely by `from pathlib import Path`; a mapped literal
read is RESOLVE(key), which folded code reaches only through `<identity_name>.resolve(key)` or `Path(<constant>)`.

v2.3 (FOLD §11.4) adds, for the R1 fold of a real composition:
  wraps       [{"module": original file as in `modules`, "line": int, "col": int, "kind": "relkey"}]  the original
              `str(E)` or `str(E.resolve())` call at that position is KEY(E), the form folded `<ident>.relkey(E)` has;
              every declared wrap must be found, and only declared positions are read this way
  identity_runtime    {NAME: "str" | "path"}  how each identity constant is bound (default "str")
  Folded `<ident>.as_path(x)` is Path(x) (Path rules apply), `<ident>.join(a, b)` is `a / b`, and
  `<ident>.helper_name(e)`, `<ident>.module_name(e)` and `<ident>.members(e)` are e: each is the fold's declared
  key, module-name or membership change (see IDENTITY_SOURCE). The Windows prefix literals in WINDOWS_PREFIXES are
  not path literals. `pins` also requires the identity module to be exactly identity_source() of the manifest.

v2.4 (R1 fold review r1, F2 and F3):
  wraps       [{"module", "line", "col", "end_line", "end_col", "kind"}]  kind is one of WRAP_KINDS and the position
              is the original node's full span. relkey reads as in v2.3. For every other kind the original node at that
              span (as_path: a `Path(x)` call; join: an `a / b`; the rest: any expression) and the folded
              `<ident>.<kind>(...)` call both become one WRAP marker, so a wrap that is undeclared, missing or on
              another node makes the trees differ.
  Import probes: a folded `'import P.X' in s` (also `'import P.X as'`, `'from P.X'`, `'from P.X import'`, and
              `not in`), a membership test for the import the fold writes into generated source, reads as the
              original `'import X' in s` for a declared helper X. It is only read so as the left side of one
              `in`/`not in`; anywhere else the text is screened as before.
  Fragments: source text that does not parse as a whole (a patch's replacement text) is read back line by line:
              each line the rewrite changes must parse on its own and differ only in its aliased and from-imports.
              Text that parses as a whole is read as in v2.2.
  Probes (G-PIN, and the fold's K3) import the runtime, so they run as the real run does: `-s -P -B`, never `-I`,
  PYTHON* variables removed from the environment, PYTHONHASHSEED=0, and the probe refuses to run when
  sys.flags.hash_randomization is set.
  carried     [{"module": original file as in `modules`, "sha256": hex}]  (R2 proposal) a string literal whose
              UTF-8 sha256 is listed may hold a machine path in the folded module: an embedded source that its own
              module pins by that sha. The folded module must hold the sha as a string constant and the literal
              itself; it is compared like any other constant. The fold's scan gate counts its lines apart (PRIVATE).
  R2 proposals from the v2.4 refuter: a probe is read only when its comparator is a name, attribute or subscript
  (never a literal, f-string or concatenation), when no other string in the folded module names the helper bare,
  and, for the forms without `as`/`import`, when no module the gate can see (the composition's, the standard
  library's) has a name that extends the helper's. Fragments are read by logical line (tokenize): every logical
  line holding a changed row must parse alone and differ only in its aliased and from-imports; text that does not
  tokenize, holds a lone CR or changes a row outside a logical line is not read. `str(...)` is read as KEY only
  where neither side binds `str`. The identity import must come before every module-level statement naming it.
"""
import ast
import copy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import sys
import textwrap
import tokenize
from typing import Any
import unicodedata
import warnings

USER_PATH = re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/]|^\\\\|[\\/]users[\\/]|/home/|^~[\\/]|%userprofile%|the-diadem'
                       r'|codex[\\/]', re.IGNORECASE)
HEX64 = re.compile(r'^(sha256:)?([0-9a-f]{64})$')
PRIVATE = 'atlas_tectonics._private'
IDENTITY = 'atlas_tectonics._identity'
IMPORTERS = ('import_module', 'find_spec', '__import__')
IDENTITY_KEY = 'atlas_tectonics/_identity.py'
# The identity module's functions the gate reads through (see _Normalise), plus its declared constants.
IDENTITY_FUNCTIONS = ('relkey', 'resolve', 'as_path', 'join', 'helper_name', 'module_name', 'members')
# The identity functions a fold applies only at a declared position (manifest `wraps`).
WRAP_KINDS = ('relkey', 'as_path', 'join', 'helper_name', 'module_name', 'members')
# Win32 path-prefix syntax (no folder in it): `\\`, `\\?\` and `\\?\UNC\`.
WINDOWS_PREFIXES = ('\\\\', '\\\\?\\', '\\\\?\\UNC\\')

IDENTITY_SOURCE = '''\
"""Package-relative source identity (R1 fold, FOLD.md §2-§3, §11.4). Every recorded source key is built by relkey
and every file read by key goes through resolve, so no record and no check depends on the folder the package sits
in. Written by the fold; the parity gate requires these exact bytes."""
import os
from pathlib import Path

PKG_PARENT = Path(__file__).resolve().parent.parent
_PACKAGE = PKG_PARENT/'atlas_tectonics'
_PRIVATE = 'atlas_tectonics._private.'
_REPARSE_POINT = 0x400


class IdentityError(ValueError):
    pass


def _inside(real):
    return real == _PACKAGE or _PACKAGE in real.parents


def _is_key(value):
    return isinstance(value, str) and value.startswith('atlas_tectonics/') and '\\\\' not in value and ':' not in value


def resolve(key):
    """The real path of a package-relative key; anything that is not such a key is refused."""
    if not isinstance(key, str) or '\\\\' in key or ':' in key or key.startswith('/'):
        raise IdentityError('not a package-relative key: %r' % (key,))
    parts = key.split('/')
    if parts[0] != 'atlas_tectonics' or any(part in ('', '.', '..') for part in parts):
        raise IdentityError('not a package-relative key: %r' % (key,))
    real = (PKG_PARENT/key).resolve()
    if not _inside(real):
        raise IdentityError('key leaves the package: %r' % (key,))
    return real


def as_path(value):
    """A package-relative key as the file it names; any other value exactly as Path(value)."""
    return resolve(value) if _is_key(value) else Path(value)


def relkey(path):
    """The POSIX key of a path (or a key) inside the package, relative to the folder that contains the package."""
    real = as_path(path).resolve()
    if not _inside(real):
        raise IdentityError('not inside the atlas_tectonics package: %s' % Path(path).name)
    return real.relative_to(PKG_PARENT).as_posix()


def join(base, name):
    """base/name, except that a key names its package file; a name with a drive or root is refused."""
    if _is_key(name):
        return resolve(name)
    if Path(name).anchor:
        raise IdentityError('an absolute name cannot be joined: %s' % Path(name).name)
    return base/name


def helper_name(name):
    """A folded helper's module name as the unfolded composition named it; any other name unchanged."""
    return name[len(_PRIVATE):] if isinstance(name, str) and name.startswith(_PRIVATE) else name


def module_name(stem):
    """The module name of the folded helper whose file stem is `stem`."""
    if not (isinstance(stem, str) and stem.isidentifier()):
        raise IdentityError('not a helper stem: %r' % (stem,))
    return _PRIVATE + stem


def members(items):
    """The items of a package source walk outside atlas_tectonics/_private: the folded helpers are bound by their
    pins, as the unfolded helpers were, not by package membership. A reparse point at that folder is refused."""
    for item in items:
        parts = [os.path.normcase(part) for part in Path(os.fspath(item)).parts]
        if any(a == 'atlas_tectonics' and b == '_private' for a, b in zip(parts, parts[1:])):
            if isinstance(item, os.DirEntry) and \\
                    getattr(item.stat(follow_symlinks=False), 'st_file_attributes', 0) & _REPARSE_POINT:
                raise IdentityError('the private helper folder is a reparse point')
            continue
        yield item
'''


class ParityError(AssertionError):
    pass


def identity_source(constants, runtime=None):
    """The identity module's bytes: IDENTITY_SOURCE, then each declared constant as the real path of its key, as a
    str (runtime "str", the default) or a Path (runtime "path")."""
    runtime = runtime or {}
    lines = [IDENTITY_SOURCE, '\n'] if constants else [IDENTITY_SOURCE]
    for name, key in sorted(constants.items()):
        kind = runtime.get(name, 'str')
        if kind not in ('str', 'path') or not re.fullmatch(r'[A-Z][A-Z0-9_]*', name):
            raise ParityError('identity constant %s: bad name or runtime %r' % (name, kind))
        lines.append(('%s = str(resolve(%r))\n' if kind == 'str' else '%s = resolve(%r)\n') % (name, key))
    return ''.join(lines).encode('utf-8')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def literal_sha(value):
    """sha256 of a string literal's strict UTF-8 bytes; None for a literal with lone surrogates, which has no such
    bytes and so can never be a carried literal."""
    try:
        return sha256(value.encode('utf-8')).hexdigest()
    except UnicodeEncodeError:
        return None


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
        self.carried = set()
        for entry in manifest.get('carried', ()):
            if not (isinstance(entry, dict) and set(entry) == {'module', 'sha256'}
                    and entry['module'] in manifest.get('modules', {})
                    and isinstance(entry['sha256'], str) and re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
                raise ParityError('malformed carried literal: %r' % (entry,))
            self.carried.add(entry['sha256'])
        for name, value in self.constants.items():
            if not isinstance(value, str) or _is_abs(value) or USER_PATH.search(value):
                raise ParityError('identity constant %s is not a package-relative key' % name)
        # Private helpers: {module name under the private package: the top-level name the original imports}, from
        # every key_map or modules entry whose new key is a .py file under atlas_tectonics/_private/.
        self.private = {}
        for old, new in list(self.key_map.items()) + list(manifest.get('modules', {}).items()):
            parts = re.split(r'[\\/]', new)
            if parts[:2] != ['atlas_tectonics', '_private'] or len(parts) < 3 or not new.endswith('.py'):
                continue
            name, stem = '.'.join(parts[2:])[:-3], re.split(r'[\\/]', old)[-1][:-3]
            if not old.endswith('.py') or self.private.setdefault(name, stem) != stem:
                raise ParityError('private helper %s has no single original module name' % name)
        if len(set(self.private.values())) != len(self.private):
            raise ParityError('two private helpers fold from the same original module name')
        # Names folded code may not import bare: each helper's original name and its new top-level name.
        self.bare = set(self.private.values()) | {name.split('.')[0] for name in self.private}
        # Top-level module names the gate can see, for the probe forms that match by prefix.
        self.module_names = set(sys.stdlib_module_names) | {
            re.split(r'[\\/]', old)[-1][:-3] for old in manifest.get('modules', {}) if old.endswith('.py')}
        self.private_text = re.compile(r'%s\.(%s)(?!\w)' % (re.escape(PRIVATE), '|'.join(
            re.escape(name) for name in sorted(self.private, key=len, reverse=True)))) if self.private else None

    def unqualify(self, name):
        """`atlas_tectonics._private.<helper>[.rest]` -> `<original name>[.rest]`; any other name is unchanged."""
        rest = name[len(PRIVATE) + 1:] if name.startswith(PRIVATE + '.') else None
        for new in sorted(self.private, key=len, reverse=True):
            if rest is not None and (rest == new or rest.startswith(new + '.')):
                return self.private[new] + rest[len(new):]
        return name

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
# Import statements inside string literals (source text a module builds and then runs, e.g. workflow_source) are
# outside the import rules, so the folded side parses each string that mentions an import and screens what it would
# import; text that does not parse is screened by regex over a normalised copy.
TEXT_IMPORT = re.compile(r'(?:^|[;:(\'"])[ \t]*(import|from)[ \t]+([^;\n]*)', re.M)
TEXT_IMPORTER = re.compile(r'(?:%s)[ \t]*\([ \t]*[rRbBuU]{0,2}[\'"]([\w.]+)' % '|'.join(IMPORTERS))
IMPORT_PROBE = re.compile(r'(import|from)([ \t]+)%s\.(\w+)((?:[ \t]+(?:as|import))?)' % re.escape(PRIVATE))
PROBE_PAIRS = (('import', ''), ('from', ''), ('import', 'as'), ('from', 'import'))
NESTING = 4


def _name(name):
    # ctx given explicitly: Python 3.12 leaves it unset (dumping unlike a parsed Name), 3.13 defaults it to Load.
    return ast.Name(name, ast.Load())


def _call(kind, *args):
    # A NUL in the name: no parsed source can contain this node, so a marker cannot be forged by a string.
    return ast.Call(_name('\0' + kind), list(args), [])


def _single(node):
    """The one positional argument of a call with no keywords and no unpacking, else None."""
    if len(node.args) == 1 and not node.keywords and not isinstance(node.args[0], ast.Starred):
        return node.args[0]
    return None


def _where(node):
    """A node's full span, the key of a declared wrap."""
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _wrap_shape(kind, node):
    """Whether an original node can carry a declared wrap of this kind."""
    if kind in ('relkey', 'as_path'):
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == ('str' if kind == 'relkey' else 'Path') and _single(node) is not None
    if kind == 'join':
        return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    return True


def _bound_names(node):
    """(bound name, imported dotted name) for each alias of an import statement; a star import binds '*'."""
    if isinstance(node, ast.Import):
        return [(alias.asname or alias.name.split('.')[0], alias.name) for alias in node.names]
    base = '.' * node.level + (node.module or '')
    return [(alias.asname or alias.name, base + '.' + alias.name) for alias in node.names]


def _bindings(tree, name):
    """Every node that binds `name`: assignment or deletion target, def, class, argument, import (a star import
    counts for any name), except or match capture, type parameter, global or nonlocal declaration."""
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            hit = node.id == name and not isinstance(node.ctx, ast.Load)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            hit = any(bound in (name, '*') for bound, _ in _bound_names(node))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            hit = name in node.names
        elif isinstance(node, ast.arg):
            hit = node.arg == name
        elif isinstance(node, ast.MatchMapping):
            hit = node.rest == name
        else:
            hit = not isinstance(node, ast.alias) and getattr(node, 'name', None) == name
        if hit:
            sites.append(node)
    return sites


def _only_imports(tree, name, target, top_level):
    """True when `name` is bound at least once and only by imports of `target` (module-level ones if top_level)."""
    sites = _bindings(tree, name)
    return bool(sites) and all(
        isinstance(site, (ast.Import, ast.ImportFrom)) and (not top_level or site in tree.body)
        and all(imported == target for bound, imported in _bound_names(site) if bound in (name, '*'))
        for site in sites)


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


def _identity_in_play(tree, ctx):
    """Whether folded code imports the identity module as ctx.ident or uses a name the gate rewrites through it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == ctx.ident \
                and (node.attr in ctx.constants or node.attr in IDENTITY_FUNCTIONS):
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)) and (ctx.ident, IDENTITY) in _bound_names(node):
            return True
    return False


def _parse_text(value):
    """The module a str or bytes value would be as Python source, or None when it is not valid Python."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return ast.parse(textwrap.dedent(value) if isinstance(value, str) else value)
    except (SyntaxError, ValueError, RecursionError):
        return None


def _flat(value):
    """A copy for the regex screen: NFKC (as the tokenizer reads identifiers), one line end, form feeds as spaces,
    backslash continuations joined."""
    text = value if isinstance(value, str) else value.decode('utf-8', 'replace')
    text = unicodedata.normalize('NFKC', text).replace('\r\n', '\n').replace('\r', '\n').replace('\f', ' ')
    return re.sub(r'\\[ \t]*\n', ' ', text)


def _logical_lines(text):
    """[(first row, last row)] (1-based) of each logical line of a text, as the tokenizer joins rows (brackets,
    backslashes, multi-line strings); None when the text does not tokenize. Rows are read without their leading
    blanks: indentation never moves a logical line's ends, and a fragment cut from a function body may dedent below
    its first row. A text that ends inside open brackets keeps the logical lines closed before them (a row of the
    open statement is in no span, so it is refused); any other failure, such as a string left open, is None."""
    spans, start, last, depth = [], None, None, 0
    skip = (tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER)
    rows = '\n'.join(row.lstrip(' \t') for row in text.split('\n'))
    try:
        for token in tokenize.generate_tokens(io.StringIO(rows).readline):
            if token.type == tokenize.OP and token.string in ('(', '[', '{'):
                depth += 1
            elif token.type == tokenize.OP and token.string in (')', ']', '}'):
                depth -= 1
            if token.type == tokenize.NEWLINE:
                if start is not None:
                    spans.append((start, last))
                start = None
            elif token.type not in skip:
                start = token.start[0] if start is None else start
                last = token.end[0]
    except tokenize.TokenError as exc:
        return spans if depth > 0 and exc.args[0] == 'unexpected EOF in multi-line statement' else None
    except SyntaxError:
        return None
    return spans


def _docstrings(tree):
    """The docstring nodes of a module and of its functions and classes."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            out.add(node.body[0].value)
    return out


def _imported_names(value, depth=0):
    """Dotted module names a string would import if run as Python: import statements, importer calls with a literal
    name, and the same inside strings it contains (to NESTING levels). Text that does not parse is screened by regex,
    so a fragment that is joined to others before it runs is still screened."""
    text = value.decode('ascii', 'replace') if isinstance(value, bytes) else value
    if value.isascii() and 'import' not in text and 'find_spec' not in text:
        return []
    tree = _parse_text(value)
    if tree is None:
        flat, names = _flat(value), []
        for keyword, rest in TEXT_IMPORT.findall(flat):
            items = rest.split(',') if keyword == 'import' else rest.split()[:1]
            names += [item.split()[0] for item in items if item.split()]
        return names + TEXT_IMPORTER.findall(flat)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str) and ast.unparse(node.func).split('.')[-1] in IMPORTERS:
            names.append(node.args[0].value)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)) and depth < NESTING:
            names += _imported_names(node.value, depth + 1)
    return names


class _Unqualify(ast.NodeTransformer):
    """A parsed text with `import P.X as Y` and `from P.X import ...` given the names the original imports;
    nothing else changes (`import P.X` alone binds P and keeps its prefix)."""

    def __init__(self, ctx):
        self.ctx = ctx

    def visit_Import(self, node):
        for alias in node.names:
            if alias.asname:
                alias.name = self.ctx.unqualify(alias.name)
        return node

    def visit_ImportFrom(self, node):
        if not node.level and node.module:
            node.module = self.ctx.unqualify(node.module)
        return node


class _Normalise(ast.NodeTransformer):
    """Original side: key_map applied to string literals, old pins re-pinned, `Path(<mapped literal>)` marked
    RESOLVE(key). Folded side: violations listed (a helper imported bare in code, by importer name or in source text;
    a drive, UNC or user path literal); a declared helper's private name replaced by the name the original imports
    (aliased `import P.X as Y`, `from P import X`, `from P.X import ...`, an exact module-name string, and source text
    whose rewrite parses to the same tree); `<ident>.NAME` -> its declared key; `Path(<ident>.NAME)` and
    `<ident>.resolve(<key_map value>)` -> RESOLVE(key); `<ident>.resolve(x)` for an expression x -> Path(x), a read by
    key (resolve refuses a non-key at run time); `<ident>.relkey(x)` -> KEY(x). Both sides: one MODULE or ATTR marker
    per import alias, and `str(Path(x).resolve())` -> KEY(x). The Path rules apply only when every binding of Path on
    both sides is `from pathlib import Path`. Everything else must already be identical."""

    def __init__(self, ctx, folded, path_ok, wraps=None, str_ok=True, strings=()):
        self.ctx, self.folded, self.path_ok, self.violations = ctx, folded, path_ok, []
        self.wraps, self.consumed = dict(wraps or {}), set()
        # str_ok: `str` is the builtin on both sides. strings: the folded module's non-docstring str constants, as
        # written (before any is read back), for the probe's bare-name screen.
        self.str_ok, self.strings, self.docstrings = str_ok, tuple(strings), set()

    def visit(self, node):
        # Original side: the node at a declared non-relkey wrap's span becomes WRAP(kind, node), the form the folded
        # call takes. relkey is read in visit_Call (its original form is KEY, not a WRAP marker).
        if self.folded or not isinstance(node, ast.expr):
            return super().visit(node)
        where = _where(node)
        kind = self.wraps.get(where)
        # R2: a docstring is never wrapped (wrapped, it is no longer the docstring).
        if kind in (None, 'relkey') or where in self.consumed or not _wrap_shape(kind, node) \
                or node in self.docstrings:
            return super().visit(node)
        self.consumed.add(where)
        return _call('WRAP', ast.Constant(kind), super().visit(node))

    def _violation(self, node, text):
        self.violations.append('line %d: %s' % (getattr(node, 'lineno', 0), text))

    def _markers(self, node, entries):
        nodes = []
        for kind, bound, name, target in entries:
            if self.folded and name.split('.')[0] in self.ctx.bare:
                self._violation(node, 'helper %s imported outside %s' % (name, PRIVATE))
            if self.folded and (bound, name) == (self.ctx.ident, IDENTITY):
                continue
            nodes.append(ast.Expr(_call(kind, ast.Constant(bound), ast.Constant(target))))
        return nodes or None

    def visit_Import(self, node):
        # `import P.X as Y` binds the module P.X; `import P.X` alone binds P, so only the aliased form is unqualified.
        entries = []
        for alias in node.names:
            target = self.ctx.unqualify(alias.name) if self.folded and alias.asname else alias.name
            entries.append(('MODULE', alias.asname or alias.name.split('.')[0], alias.name, target))
        return self._markers(node, entries)

    def visit_ImportFrom(self, node):
        # `from P import X` binds the helper module X; `from P.X import n` binds the attribute n of X.
        entries = []
        for bound, name in _bound_names(node):
            kind, target = 'ATTR', name
            if self.folded and not node.level:
                rest = name[len(PRIVATE) + 1:] if name.startswith(PRIVATE + '.') else None
                if rest in self.ctx.private:
                    kind, target = 'MODULE', self.ctx.private[rest]
                else:
                    target = self.ctx.unqualify(name)
            entries.append((kind, bound, name, target))
        return self._markers(node, entries)

    def _text(self, value):
        """Text naming a private helper, rewritten to the original names only when the rewrite parses to exactly the
        text's own tree with its `import P.X as Y` and `from P.X import` statements unqualified; else unchanged."""
        if self.ctx.private_text is None or not self.ctx.private_text.search(value):
            return value
        unqualify = lambda text: self.ctx.private_text.sub(lambda match: self.ctx.private[match.group(1)], text)
        rewritten = unqualify(value)
        tree, again = _parse_text(value), _parse_text(rewritten)
        if tree is not None and again is not None:
            return rewritten if ast.dump(_Unqualify(self.ctx).visit(tree)) == ast.dump(again) else value
        if tree is not None or again is not None:
            return value
        # v2.4 + R2: a fragment that does not parse as a whole (a patch's replacement text) is read by logical line,
        # as the tokenizer joins rows: every logical line holding a row the rewrite changes must parse on its own,
        # with only its aliased and from-imports unqualified. A changed row in a string, a comment or a continued
        # statement is read with all of its logical line, so data or a different statement is never read as an import.
        lines, spans = value.split('\n'), None if '\r' in value else _logical_lines(value)
        if spans is None:
            return value
        changed = {row for row, line in enumerate(lines, 1) if unqualify(line) != line}
        held = [(first, last) for first, last in spans if any(first <= row <= last for row in changed)]
        if any(not any(first <= row <= last for first, last in held) for row in changed):
            return value
        for first, last in held:
            text = '\n'.join(lines[first - 1:last]).lstrip(' \t')
            tree, again = _parse_text(text), _parse_text(unqualify(text))
            if tree is None or again is None or ast.dump(_Unqualify(self.ctx).visit(tree)) != ast.dump(again):
                return value
        return rewritten

    def visit_Constant(self, node):
        value = node.value
        if not isinstance(value, (str, bytes)):
            return node
        if not self.folded:
            if isinstance(value, bytes):
                return node
            if value in self.ctx.key_map:
                return ast.Constant(self.ctx.key_map[value])
            return ast.Constant(self.ctx.pin(value, 'line %d' % node.lineno))
        if (isinstance(value, str) and value not in WINDOWS_PREFIXES and (_is_abs(value) or USER_PATH.search(value))
                and literal_sha(value) not in self.ctx.carried):
            self._violation(node, 'path literal in folded code')
        for name in _imported_names(value):
            if name.split('.')[0] in self.ctx.bare:
                self._violation(node, 'helper %s imported in source text outside %s' % (name, PRIVATE))
        if isinstance(value, bytes):
            return node
        rest = value[len(PRIVATE) + 1:] if value.startswith(PRIVATE + '.') else None
        if rest in self.ctx.private:
            return ast.Constant(self.ctx.private[rest])  # a module name passed to an importer
        return ast.Constant(self._text(value))

    def visit_Compare(self, node):
        # Folded `'import P.X' in s`: a probe for the import the fold writes into generated source, read as the
        # original `'import X' in s`. The fragment imports nothing bare, so it needs no screen.
        left = node.left
        if self.folded and isinstance(left, ast.Constant) and isinstance(left.value, str) and len(node.ops) == 1 \
                and isinstance(node.ops[0], (ast.In, ast.NotIn)):
            match = IMPORT_PROBE.fullmatch(left.value)
            if match and match.group(3) in self.ctx.private \
                    and (match.group(1), match.group(4).strip()) in PROBE_PAIRS \
                    and self._probe_ok(node.comparators[0], self.ctx.private[match.group(3)], match.group(4)):
                node.comparators = [self.visit(item) for item in node.comparators]
                node.left = ast.Constant(match.group(1) + match.group(2) + self.ctx.private[match.group(3)]
                                         + match.group(4))
                return node
        return self.generic_visit(node)

    def _probe_ok(self, subject, name, tail):
        """Whether a probe for the original helper `name` can be read as the original one. The text it searches must
        come from elsewhere (a name, attribute or subscript), since a literal, f-string or concatenation here holds
        text the fold did not write; no other string in the module may name the helper bare (text the module builds
        at run time, such as `'import %s as T' % name`, would keep it); and a form without `as`/`import` matches by
        prefix, so no name the gate can see (a module of the composition or the standard library, or a word in the
        module's strings) may extend the helper's."""
        if not isinstance(subject, (ast.Name, ast.Attribute, ast.Subscript)):
            return False
        bare = re.compile(r'(?<![\w.])%s(?!\w)' % re.escape(name))
        if any(bare.search(text) for text in self.strings):
            return False
        if tail.strip():
            return True
        longer = re.compile(r'(?<![\w.])%s\w' % re.escape(name))
        return not any(longer.search(text) for text in self.strings) and not any(
            other != name and other.startswith(name) and re.match(r'\w', other[len(name)])
            for other in self.ctx.module_names)

    def visit_Attribute(self, node):
        if self.folded and isinstance(node.value, ast.Name) and node.value.id == self.ctx.ident \
                and node.attr in self.ctx.constants:
            return ast.Constant(self.ctx.constants[node.attr])
        return self.generic_visit(node)

    def visit_Call(self, node):
        f, arg = node.func, _single(node)
        where = _where(node)
        if not self.folded and self.str_ok and self.wraps.get(where) == 'relkey' and where not in self.consumed \
                and _wrap_shape('relkey', node) and arg is not None:
            # A declared relkey wrap: str(E) or str(E.resolve()) is the key of E.
            self.consumed.add(where)
            if isinstance(arg, ast.Call) and not arg.args and not arg.keywords \
                    and isinstance(arg.func, ast.Attribute) and arg.func.attr == 'resolve':
                arg = arg.func.value
            return _call('KEY', self.visit(arg))
        if self.folded and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str) and ast.unparse(f).split('.')[-1] in IMPORTERS \
                and node.args[0].value.split('.')[0] in self.ctx.bare:
            self._violation(node, 'helper %s imported by name outside %s' % (node.args[0].value, PRIVATE))
        if self.path_ok and self.str_ok and isinstance(f, ast.Name) and f.id == 'str' and isinstance(arg, ast.Call) \
                and not arg.args and not arg.keywords and isinstance(arg.func, ast.Attribute) \
                and arg.func.attr == 'resolve' and isinstance(arg.func.value, ast.Call) \
                and isinstance(arg.func.value.func, ast.Name) and arg.func.value.func.id == 'Path':
            inner = _single(arg.func.value)
            if inner is not None:
                return _call('KEY', self.visit(inner))
        if self.path_ok and isinstance(f, ast.Name) and f.id == 'Path' and arg is not None:
            if not self.folded and isinstance(arg, ast.Constant) and arg.value in self.ctx.key_map:
                return _call('RESOLVE', ast.Constant(self.ctx.key_map[arg.value]))
            if self.folded and isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) \
                    and arg.value.id == self.ctx.ident and arg.attr in self.ctx.constants:
                return _call('RESOLVE', ast.Constant(self.ctx.constants[arg.attr]))
        self.generic_visit(node)
        f, arg = node.func, _single(node)
        if self.folded and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == self.ctx.ident and arg is not None:
            if f.attr == 'relkey':
                return _call('KEY', arg)
            if f.attr == 'resolve' and self.path_ok:
                if not isinstance(arg, ast.Constant):
                    return ast.Call(_name('Path'), [arg], [])
                if isinstance(arg.value, str) and arg.value in self.ctx.inverse:
                    return _call('RESOLVE', arg)
            if f.attr == 'as_path' and self.path_ok:
                return _call('WRAP', ast.Constant('as_path'), ast.Call(_name('Path'), [arg], []))
            if f.attr in ('helper_name', 'module_name', 'members'):
                return _call('WRAP', ast.Constant(f.attr), arg)
        if self.folded and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == self.ctx.ident and f.attr == 'join' and len(node.args) == 2 and not node.keywords \
                and not any(isinstance(a, ast.Starred) for a in node.args):
            return _call('WRAP', ast.Constant('join'), ast.BinOp(node.args[0], ast.Div(), node.args[1]))
        return node


def ast_diff(original_text, folded_text, manifest=None, wraps=None):
    """None when the folded text is the original with only the declared changes; else the first problem. `wraps`
    maps the full span of each of this module's declared wraps on the original side to its kind."""
    ctx = Context(manifest or {})
    original_tree, folded_tree = ast.parse(original_text), ast.parse(folded_text)
    if _identity_in_play(folded_tree, ctx):
        if ctx.ident in _identifiers(original_tree):
            return 'identity name %s is already an identifier in the original' % ctx.ident
        if not _only_imports(folded_tree, ctx.ident, IDENTITY, True):
            return 'identity name %s is bound other than by a module-level import of %s' % (ctx.ident, IDENTITY)
        # R2: the import must run before any module-level statement that names the identity module.
        imports = _bindings(folded_tree, ctx.ident)
        first = min(i for i, stmt in enumerate(folded_tree.body) if stmt in imports)
        for stmt in folded_tree.body[:first]:
            if any(isinstance(node, ast.Name) and node.id == ctx.ident for node in ast.walk(stmt)):
                return 'identity name %s is used at line %d before its import' % (ctx.ident, stmt.lineno)
    path_ok = all(_only_imports(tree, 'Path', 'pathlib.Path', False) for tree in (original_tree, folded_tree))
    # R2: `str(...)` reads as KEY only where `str` is the builtin on both sides.
    str_ok = not _bindings(original_tree, 'str') and not _bindings(folded_tree, 'str')
    if not str_ok and 'relkey' in (wraps or {}).values():
        return 'a declared relkey wrap in a module that binds str'
    docstrings = _docstrings(folded_tree)
    strings = [node.value for node in ast.walk(folded_tree) if isinstance(node, ast.Constant)
               and isinstance(node.value, str) and node not in docstrings]
    folded = _Normalise(ctx, True, path_ok, str_ok=str_ok, strings=strings)
    b = ast.dump(folded.visit(folded_tree), annotate_fields=False)
    if folded.violations:
        return folded.violations[0]
    original = _Normalise(ctx, False, path_ok, wraps, str_ok=str_ok)
    original.docstrings = _docstrings(original_tree)
    a = ast.dump(original.visit(original_tree), annotate_fields=False)
    missing = sorted(set(original.wraps) - original.consumed)
    if missing:
        return 'declared %s wrap at line %d col %d is not found with its shape' % (
            original.wraps[missing[0]], missing[0][0], missing[0][1])
    return None if a == b else 'code differs beyond the declared imports, pins, paths, keys and wraps'


def ast_equivalent(original_text, folded_text, manifest=None, wraps=None):
    return ast_diff(original_text, folded_text, manifest, wraps) is None


WRAP_FIELDS = ('module', 'line', 'col', 'end_line', 'end_col', 'kind')


def _wraps(manifest):
    """{original module: {span: kind}} from the manifest's declared wraps, each checked."""
    out = {}
    for entry in manifest.get('wraps', ()):
        if not (isinstance(entry, dict) and set(entry) == set(WRAP_FIELDS) and entry['kind'] in WRAP_KINDS
                and entry['module'] in manifest['modules']
                and all(type(entry[name]) is int for name in WRAP_FIELDS[1:5])):
            raise ParityError('malformed wrap: %r' % (entry,))
        where = tuple(entry[name] for name in WRAP_FIELDS[1:5])
        if where in out.setdefault(entry['module'], {}):
            raise ParityError('wrap declared twice: %r' % (entry,))
        out[entry['module']][where] = entry['kind']
    return out


def _check_carried(folded_src, manifest):
    """Every carried literal is in its folded module, and that module pins it by its sha."""
    for entry in manifest.get('carried', ()):
        tree = ast.parse((Path(folded_src)/manifest['modules'][entry['module']]).read_bytes())
        values = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        if entry['sha256'] not in values:
            raise ParityError('carried literal %s is not pinned by %s' % (entry['sha256'][:8], entry['module']))
        if not any(literal_sha(value) == entry['sha256'] for value in values):
            raise ParityError('carried literal %s is absent from %s' % (entry['sha256'][:8], entry['module']))


def check_ast(original_root, folded_src, manifest):
    """Every module folds to the original's AST. A carried literal is exempt from the path-literal rule only in the
    module that declares it."""
    bad, wraps = [], _wraps(manifest)
    Context(manifest)  # validates the carried entries before they are used
    _check_carried(folded_src, manifest)
    carried = manifest.get('carried', [])
    for old, new in sorted(manifest['modules'].items()):
        own = dict(manifest, carried=[e for e in carried if e['module'] == old]) if carried else manifest
        problem = ast_diff((Path(original_root)/old).read_text(encoding='utf8'),
                           (Path(folded_src)/new).read_text(encoding='utf8'), own, wraps.get(old))
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
_SEED_GUARD = ('import sys\n'
               'if sys.flags.hash_randomization:\n'
               '    sys.exit("probe refused: hash randomisation is on (PYTHONHASHSEED must be 0)")\n')


def run_probe(python, code, args, cwd, timeout=None, seed='0'):
    """Run probe code the way the real run imports the runtime: `-s -P -B` (never -I, which would drop the hash seed),
    every PYTHON* variable removed, PYTHONHASHSEED=seed. A guard before the code exits non-zero under hash
    randomisation, so a probe never passes in an environment the run cannot have. `seed` is for the selftest only."""
    import subprocess
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith('PYTHON')}
    env['PYTHONHASHSEED'] = seed
    return subprocess.run([python, '-s', '-P', '-B', '-c', _SEED_GUARD + code] + [str(a) for a in args], env=env,
                          capture_output=True, text=True, cwd=str(cwd), timeout=timeout, check=False)


def check_pins(folded_src, manifest, python=sys.executable):
    """Every sha_map new sha is the sha of FOLDED_SRC/<key>; no bytecode is present; a clean interpreter (run_probe)
    imports each pinned module from FOLDED_SRC/<key> with sha_map's new sha, which equals the pin; no helper stem is
    importable at top level."""
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
    if IDENTITY in pins or (root/IDENTITY_KEY).exists():
        expected = identity_source(ctx.constants, manifest.get('identity_runtime'))
        if not (root/IDENTITY_KEY).is_file() or (root/IDENTITY_KEY).read_bytes() != expected:
            raise ParityError('the identity module is not the gate\'s identity source for this manifest')
        if IDENTITY not in pins or ctx.sha_map.get(IDENTITY_KEY, (None, None))[1] != sha256(expected).hexdigest():
            raise ParityError('the identity module is not pinned at its sha')
    stems = sorted({name.split('.')[-1] for name in pins} | ctx.bare)
    run = run_probe(python, 'sys.path.insert(0, sys.argv[1]); exec(%r)' % _PROBE,
                    [root, json.dumps(sorted(pins)), json.dumps(stems)], root.parent)
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
