"""R1 fold transformer (FOLD.md §2, §3, §9 K1-K4, §10.4-10.5, §11 steps 1-6, §11.4).

  python -B fold.py candidates COMPOSED_ROOT OUT.json --trace TRACE.json [--sites SITES.json]
  python -B fold.py fold COMPOSED_ROOT OUT_DIR --trace TRACE.json --sites SITES.json [--a-helpers DIR] [--a-src DIR]
                    [--no-gates]

COMPOSED_ROOT holds src/atlas_tectonics (the package) and helpers/ (top-level helper modules); both are read only.
`candidates` lists every site that needs a decision in SITES.json (and which existing decisions no longer match).
`fold` writes, under OUT_DIR (which must not exist):
  folded/atlas_tectonics/...  the package, _identity.py, and _private/<helper>.py (flat, file names kept)
  MANIFEST.json               the parity.py manifest (key_map, sha_map, modules, pins, identity_name, ...)
  FOLD-REPORT.json            module set, every rewritten site, re-pins, exclusions, gate results
Every root comes from the arguments. Every rewrite is a span located by the parsed tree, never a text search over
the file. The fold refuses (exit 1, one FAIL JSON line) on: a site SITES.json does not classify or whose expression
no longer matches; a trace whose helper shas differ from the composition's (except declared harness patches); two
files claiming one module name; a helper the closure needs that is excluded or a test module; an import of an
excluded module at module level; a pin cycle; an embedded pin it cannot re-pin; any gate failure (ast, pins, scan).

Module set: the helpers the trace loaded, files loaded by path (K1), and the closure over helper imports (lazy ones
included), helper names held in strings and `<helper>.py` names (pins), minus SITES.json `exclude` (R2) and test_*.
An excluded module reached only lazily keeps its bare import and is listed in the report (it fails closed with
ImportError on the folded tree, where no helper is on sys.path).
SITES.json `wraps` ({`module:line:col:wrap`: {expr, do, why}}) declares the expressions the fold passes through the
identity module that no site search finds (a key built as `str(E)`, a path or module name that may now be a key or a
private name, a package walk that must leave out _private): do is relkey, as_path, helper_name, module_name, join or
members (see parity v2.3). `--a-helpers`/`--a-src` name the folders arm A runs the helpers and the package from
(default: the composition's own), so key_map holds A's spellings.

r2 (review r1, 23 Oct): checked by parity v2.4 (rm/fold/v24/parity.py). Every wrap the fold makes is declared in the
manifest with its full span and kind (relkey, as_path, join, helper_name, module_name, members), including a read
site's as_path. SITES.json `data_files` ({package key: {source, sha256}}, source relative to `--data-root`) are copied
byte-equal into the folded tree and listed in sha_map with old = new. A literal retargeted from a file whose sha
differs from the composition's file (F5 re-pin) is refused unless its decision carries `accept_repin`:
[the literal's file sha, the composition file's sha, why]. The manifest and report are built before anything is
written, and OUT_DIR is checked first. K3 runs through the gate's run_probe (`-s -P -B`, PYTHONHASHSEED=0).
SITES.json `roots` ({helper: why}) adds helpers that no traced call loads but a consumer needs folded (a standalone
script, a launcher-chain gate), with their closure; each needs a reason and must not already be traced or loaded by
path. The static gates and an import smoke cover them; the arms do not exercise them.
An `abs` site may be `carry` (R2 proposal): a machine path inside a literal that its own module pins by sha (an
embedded source the module execs after checking its sha), which the fold cannot change without breaking that pin.
The decision names the literal's sha256, the module must hold that sha as a string constant, and the literal stays
byte-equal. The manifest lists it under `carried`; the scan gate counts its lines apart, and a fold whose only scan
hits are carried lines is PRIVATE, not PASS: fit for private parity runs, refused for publication.
SITES.json `target.composition_json_sha256`, when present, must equal COMPOSED_ROOT/composition.json's sha; the
report carries that sha.

r3 (R2 proposal, 23 Oct): F5 covers directory literals. A directory literal outside the composition (neither the
composition's package folder nor arm A's) may only have constant file names joined onto it (`Path(lit)/'name.py'`);
any other use is refused. Each joined name must be a folded file; where the joined file's sha differs from the
composition file's, the site's decision needs `accept_repin_joins` {name: [joined file sha, composition sha, why]}.
A literal retargeted to a data file must name the declared bytes. The manifest's `f5_repins` lists, per re-pinned key,
both spellings arm A can record (the literal or joined path with its sha, A's package path with the composition's
sha) and the folded sha, so the records gate can map both and nothing else. A re-pinned key is always pinned.

r4 (R2 proposal, 23 Oct): K5, key readers. Smoke 3 showed arm B binding 90 private sources where A binds 91: the
F5 key 'atlas_tectonics/integration_exact_gmp.py' in interval_inventory_r4._PINS was joined onto HERE in another
module (interval_assembly_kernel_r5, `str(HERE/name) for name in I._PINS`) with no join wrap, so B recorded
'atlas_tectonics/_private/atlas_tectonics/integration_exact_gmp.py', a file that does not exist, and
forward_kernel_r13's `is_file()` filter dropped it without an error. The site search finds reads, not joins, so the
fold now refuses the class. A table holds keys when its module-level assignment contains a literal decided `key`, a
`str(E)` decided or wrapped `relkey`, or a reference to another table that holds keys (to a fixpoint). Every name
bound by iterating such a table (directly, through tuple/list/sorted/set/frozenset/dict/reversed, or .items()/.keys()),
or by iterating a getattr() whose table the fold cannot name, is a key reader. In each such loop or comprehension,
`a / reader` must be a decided `join` wrap, `Path(reader)` must be a decided `as_path` wrap or a read site decided
`resolve` or `as_path`, and `open(reader)` or `os.path.*(reader)` is refused. The report lists every table and
reader under `k5`.

r5 (Plan 20 r11, 23 Oct): data keys. r11 names the capture library by a relative task key that `task_file` finds in
the one ancestor of the module's folder holding it, not by a drive path. Left alone, the folded module would carry a
workspace path the USER_PATH scan cannot see, and B would load the workspace copy instead of the package copy. A str
literal that is not a drive or user path and equals, or ends with '/' plus, a declared data file's `source` is a
`datakey` site; its only decision is `retarget` with `key` the data file's package key. Only helper modules may hold
one. The fold finds the literal from the module's composition folder as task_file does (exactly one ancestor), refuses
unless that is the declared source under --data-root with the declared sha, rewrites the whole literal (adjacent
string tokens included) as one literal for the key, and adds literal -> key to key_map, where parity v2.4 maps it on
the original side. The records check (v26/records.py, r3) resolves the relative key_map path the same way from arm A's
helpers folder. The report lists each data key under `data_keys`.

r5 after the cold review (refuter r3, 23 Oct): a data file's source must be a plain relative POSIX path (another
spelling would turn classification off), and the fold refuses any constant str expression with a '/' (a literal, or a
'+' or f-string of literals) that finds a file outside the composition from its module's folder or an ancestor unless
it is a retargeted data key; the folded text is checked the same way from the folded module's folder against the fold
directory. Files inside the composition are folded with it and are not hazards. Paths built by calls (os.path.join and
the like) and single-part names are outside this static check; the private-literal step refuses dated workspace names.
"""
import argparse
import ast
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys
import tokenize

sys.path.insert(0, str(Path(__file__).resolve().parent/'v24'))
import parity as PC  # noqa: E402  the gate, parity v2.4 (rm/fold/v24/parity.py), which this fold is checked by

PACKAGE = 'atlas_tectonics'
PRIVATE = PC.PRIVATE
IDENTITY = PC.IDENTITY
IDENT = '_atlas_identity'  # FOLD §11.1: not `_identity` (a helper already defines a function of that name)
PRIVATE_DIR = PACKAGE + '/_private'
IMPORT_IDENTITY = 'import %s as %s' % (IDENTITY, IDENT)
READS = ('read_bytes', 'read_text', 'open')
LOADERS = ('spec_from_file_location', 'SourceFileLoader', 'SourcelessFileLoader', 'run_path', 'module_from_spec')
BUILTIN_LOADERS = ('exec', 'compile', 'eval')  # only as bare builtins (re.compile is not a loader)
DECISIONS = {'string': ('qualify', 'keep'), 'text': ('qualify', 'keep'), 'key': ('relkey', 'keep'),
             'read': ('resolve', 'as_path', 'keep'), 'abs': ('resolve', 'key', 'constant', 'keep', 'carry'),
             'syspath': ('keep',), 'bypath': ('keep',), 'anchor': ('keep',), 'datakey': ('retarget',)}
WRAPS = ('relkey', 'as_path', 'helper_name', 'module_name', 'join', 'members')


def identity_source(constants):
    """The identity module, exactly as the gate renders it (parity v2.3 identity_source)."""
    return PC.identity_source({name: key for name, (key, _) in constants.items()},
                              {name: runtime for name, (_, runtime) in constants.items()})


class FoldError(Exception):
    pass


def digest(raw):
    return sha256(raw).hexdigest()


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


# ------------------------------------------------------------------ one module's text and its span edits
class Source:
    """A module's text plus edits at spans taken from its parsed tree."""

    def __init__(self, name, raw):
        if raw.startswith(b'\xef\xbb\xbf'):
            raise FoldError('%s starts with a byte-order mark' % name)
        self.name, self.raw, self.text = name, raw, raw.decode('utf-8')
        self.tree = ast.parse(self.text)
        self.lines = [0] + [m.end() for m in re.finditer(r'\r\n|\r|\n', self.text)]
        self.parents = {child: node for node in ast.walk(self.tree) for child in ast.iter_child_nodes(node)}
        self.edits = []

    def offset(self, line, col):
        start = self.lines[line - 1]
        end = self.lines[line] if line < len(self.lines) else len(self.text)
        return start + len(self.text[start:end].encode('utf-8')[:col].decode('utf-8'))

    def span(self, node):
        start, end = self.offset(node.lineno, node.col_offset), self.offset(node.end_lineno, node.end_col_offset)
        if self.text[start:end] != ast.get_source_segment(self.text, node):
            raise FoldError('%s line %d: span does not match the parsed node' % (self.name, node.lineno))
        return start, end

    def segment(self, node):
        start, end = self.span(node)
        return self.text[start:end]

    def edit(self, start, end, new, kind, line, rank=(0, 0)):
        """`rank` orders insertions at one offset: closing text first (inner before outer), then opening text
        (outer before inner)."""
        self.edits.append((start, end, new, kind, line, rank))

    def result(self):
        out, last = [], 0
        for start, end, new, _, line, _ in sorted(self.edits, key=lambda e: (e[0], e[1], e[5])):
            if start < last:
                raise FoldError('%s line %d: overlapping edits' % (self.name, line))
            out += [self.text[last:start], new]
            last = end
        out.append(self.text[last:])
        return ''.join(out).encode('utf-8')


def _module_imports(tree):
    """(top-level name, line, at module level) for every absolute import."""
    top = set(map(id, tree.body))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(alias.name.split('.')[0], node.lineno, id(node) in top) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            out.append((node.module.split('.')[0], node.lineno, id(node) in top))
    return out


def _names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _anchors(tree):
    """Module-level names assigned from an expression that uses __file__ (HERE, ROOT, ...)."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if '__file__' in _names_in(node.value) or names & _names_in(node.value):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def _is_path_call(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Path' \
        and PC._single(node) is not None


def _key_form(node):
    """`str(Path(x).resolve())` (the gate's KEY form) -> x; `str(<other>.resolve())` -> False; else None."""
    if not (isinstance(node.func, ast.Name) and node.func.id == 'str' and PC._single(node) is not None):
        return None
    inner = node.args[0]
    if not (isinstance(inner, ast.Call) and not inner.args and not inner.keywords
            and isinstance(inner.func, ast.Attribute) and inner.func.attr == 'resolve'):
        return None
    base = inner.func.value
    return PC._single(base) if _is_path_call(base) else False


def _parent_walk(node, anchors):
    """A .parent/.parents/dirname step taken from __file__ or an anchor name, other than the module's own folder
    (`Path(__file__)[.resolve()].parent`, `os.path.dirname(__file__)`)."""
    if isinstance(node, ast.Attribute) and node.attr in ('parent', 'parents'):
        base = node.value
        if not ({'__file__'} | anchors) & _names_in(base):
            return False
        if node.attr == 'parent':
            plain = base.func.value if isinstance(base, ast.Call) and isinstance(base.func, ast.Attribute) \
                and base.func.attr == 'resolve' and not base.args else base
            if _is_path_call(plain) and isinstance(plain.args[0], ast.Name) and plain.args[0].id == '__file__':
                return False
        return True
    if isinstance(node, ast.Call) and ast.unparse(node.func).endswith('dirname') and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Name) and arg.id == '__file__':
            return False
        return bool(({'__file__'} | anchors) & _names_in(arg))
    return False


# ------------------------------------------------------------------ composition, trace and module set
class Composition:
    def __init__(self, root):
        self.root = Path(root)
        self.helpers_dir, self.package_dir = self.root/'helpers', self.root/'src'/PACKAGE
        if not self.helpers_dir.is_dir() or not self.package_dir.is_dir():
            raise FoldError('COMPOSED_ROOT needs helpers/ and src/%s/' % PACKAGE)
        self.helpers = {p.stem: p for p in sorted(self.helpers_dir.glob('*.py'))}
        self.package = {p.stem: p for p in sorted(self.package_dir.glob('*.py'))}
        lower = {}
        for stem in list(self.helpers) + list(self.package):
            if lower.setdefault(stem.lower(), stem) != stem or (stem in self.helpers and stem in self.package):
                raise FoldError('two files claim the module name %s' % stem)
        others = sorted(p.relative_to(self.root).as_posix() for p in (self.root/'src').rglob('*')
                        if p.is_file() and not (p.parent == self.package_dir and p.suffix == '.py'))
        if others:
            raise FoldError('src holds files the fold does not place: %s' % others[:5])


def module_set(comp, trace, sites):
    exclude = dict(sites.get('exclude', {}))
    patched = dict(sites.get('harness_patched', {}))
    traced = sorted(n for n, m in trace['modules'].items() if m['root'] == 'helpers')
    shas = {}
    for name in traced:
        if name not in comp.helpers:
            raise FoldError('traced helper %s is not in the composition' % name)
        sha = digest(comp.helpers[name].read_bytes())
        if sha != trace['modules'][name]['sha256']:
            if name not in patched:
                raise FoldError('traced helper %s differs from the composition (%s vs %s)'
                                % (name, trace['modules'][name]['sha256'][:8], sha[:8]))
            shas[name] = [trace['modules'][name]['sha256'], sha]
    for name, m in trace['modules'].items():
        if m['root'] == 'native' and name.startswith(PACKAGE + '.'):
            stem = name.split('.')[1]
            if stem in comp.package and digest(comp.package[stem].read_bytes()) != m['sha256']:
                raise FoldError('traced package module %s differs from the composition' % name)
    by_path = dict(sites.get('by_path_files', {}))
    roots = dict(sites.get('roots', {}))
    for name, reason in sorted(roots.items()):
        if not (isinstance(reason, str) and reason.strip()):
            raise FoldError('declared root %s needs a reason' % name)
        if name in traced or name in by_path:
            raise FoldError('declared root %s is already in the module set' % name)
    chosen = set(traced) | set(by_path) | set(roots)
    for name in chosen:
        if name in exclude or name.startswith('test_') or name not in comp.helpers:
            raise FoldError('module set needs %s, which is excluded, a test module or missing' % name)
    why = {name: 'trace' for name in traced}
    why.update({name: 'loaded by path (K1)' for name in by_path})
    why.update({name: 'declared root: ' + reason for name, reason in roots.items()})
    lazy_excluded, todo = [], sorted(chosen)
    while todo:
        name = todo.pop()
        tree = ast.parse(comp.helpers[name].read_text(encoding='utf8'))
        needs = [(n, line, top, 'import') for n, line, top in _module_imports(tree) if n in comp.helpers]
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if value in comp.helpers:
                    needs.append((value, node.lineno, False, 'string'))
                elif value.endswith('.py') and value[:-3] in comp.helpers and '/' not in value and '\\' not in value:
                    needs.append((value[:-3], node.lineno, False, 'pin name'))
        for other, line, top, how in needs:
            if other in exclude:
                if top:
                    raise FoldError('%s imports excluded %s at module level (line %d)' % (name, other, line))
                lazy_excluded.append(dict(module=name, line=line, excluded=other, how=how))
            elif other.startswith('test_'):
                raise FoldError('%s needs test module %s (line %d)' % (name, other, line))
            elif other not in chosen:
                chosen.add(other)
                why[other] = '%s by %s:%d' % (how, name, line)
                todo.append(other)
    return sorted(chosen), why, lazy_excluded, shas


# ------------------------------------------------------------------ candidate sites and their decisions
def site_id(module, node, kind):
    return '%s:%d:%d:%s' % (module, node.lineno, node.col_offset, kind)


def _expr(node):
    return ast.unparse(node)[:200]


def _names_data(value, sources):
    """r5: the relative literal names a declared data file's source (equal to it or ending with '/' plus it)."""
    return any(value == s or value.endswith('/' + s) for s in sources)


def _plain_rel(value):
    """r5 (refuter r3): a normalised relative POSIX path: no drive, root, backslash or empty, '.' or '..' part."""
    return (isinstance(value, str) and value != '' and '\\' not in value and not value.startswith('/')
            and not PC._is_abs(value) and not any(part in ('', '.', '..') for part in value.split('/')))


def _const_str(node):
    """The str value of a constant expression: a str literal, or a '+' or f-string of str literals only."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _const_str(node.left), _const_str(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [_const_str(value) for value in node.values]
        return None if any(part is None for part in parts) else ''.join(parts)
    return None


def _resolving_literals(tree, start, inside):
    """r5 (refuter r3): [(line, value)] for every constant str expression in TREE with a '/' that names an existing
    file OUTSIDE the folder INSIDE from START or one of its ancestors, as task_file would find it. Names of files
    inside (the composition's own package or helpers, such as native_root / 'atlas_tectonics/x.py') are not hazards:
    they are folded with it. Single-part names are not checked."""
    out = []
    for node in ast.walk(tree):
        value = _const_str(node) if isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr)) else None
        if value is None or '/' not in value or '\n' in value or len(value) > 400 or PC._is_abs(value):
            continue
        for parent in (start, *start.parents):
            try:
                hit = parent/value
                if hit.is_file() and not hit.resolve().is_relative_to(inside):
                    out.append((getattr(node, 'lineno', 0), value))
                    break
            except (OSError, ValueError):
                break
    return out


def find_sites(src, module, names, data_sources=()):
    """Every site that needs a decision: (id, kind, node)."""
    out, anchors = [], _anchors(src.tree)
    for node in ast.walk(src.tree):
        kind = None
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            value = node.value
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][\w.]*', value) and value.split('.')[0] in names:
                kind = 'string'
            elif any(n.split('.')[0] in names for n in PC._imported_names(value)):
                kind = 'text'
            if isinstance(value, str) and (PC._is_abs(value) or PC.USER_PATH.search(value)):
                if kind:
                    raise FoldError('%s line %d: one literal is both a %s site and a path' % (module, node.lineno, kind))
                kind = 'abs'
            elif isinstance(value, str) and _names_data(value, data_sources):
                if kind:
                    raise FoldError('%s line %d: one literal is both a %s site and a data key'
                                    % (module, node.lineno, kind))
                kind = 'datakey'
        elif isinstance(node, ast.Call):
            func = ast.unparse(node.func)
            if _key_form(node) is not None:
                kind = 'key'
            elif isinstance(node.func, ast.Attribute) and node.func.attr in READS and _is_path_call(node.func.value) \
                    and not isinstance(node.func.value.args[0], ast.Constant) \
                    and not ({'__file__'} | anchors) & _names_in(node.func.value.args[0]):
                kind = 'read'
            elif func.startswith('sys.path.') or func in ('os.putenv', 'os.environ.update'):
                kind = 'syspath'
            elif func.split('.')[-1] in LOADERS or isinstance(node.func, ast.Name) and func in BUILTIN_LOADERS:
                kind = 'bypath'
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(ast.unparse(t).startswith('sys.path') or 'PYTHONPATH' in ast.unparse(t) for t in targets):
                kind = 'syspath'
        if kind is None and _parent_walk(node, anchors) and not _parent_walk(src.parents.get(node), anchors):
            kind = 'anchor'
        if kind:
            out.append((site_id(module, node, kind), kind, node))
    return out


# ------------------------------------------------------------------ rewrites
def rewrite_imports(src, module, folded, exclude, helpers, report):
    for node in ast.walk(src.tree):
        if isinstance(node, ast.Import):
            parts, hit = [], False
            for alias in node.names:
                top, alias_as = alias.name.split('.')[0], (' as ' + alias.asname if alias.asname else '')
                if top in folded:
                    if '.' in alias.name:
                        raise FoldError('%s line %d: dotted import of helper %s' % (module, node.lineno, alias.name))
                    parts.append('from %s import %s%s' % (PRIVATE, alias.name, alias_as))
                    hit = True
                    continue
                if top in exclude:
                    report['bare_excluded'].append('%s:%d %s' % (module, node.lineno, alias.name))
                elif top in helpers:
                    report['outside_scope'].append('%s:%d %s' % (module, node.lineno, alias.name))
                parts.append('import %s%s' % (alias.name, alias_as))
            if hit:
                start, end = src.span(node)
                src.edit(start, end, '; '.join(parts), 'import', node.lineno)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            top = node.module.split('.')[0]
            if top in folded:
                if '.' in node.module:
                    raise FoldError('%s line %d: dotted import of helper %s' % (module, node.lineno, node.module))
                start, _ = src.span(node)
                match = re.match(r'from([ \t]+)%s(?![\w.])' % re.escape(node.module), src.segment(node))
                if not match:
                    raise FoldError('%s line %d: cannot locate the module name' % (module, node.lineno))
                src.edit(start + match.end(1), start + match.end(0), PRIVATE + '.' + node.module, 'import',
                         node.lineno)
            elif top in exclude:
                report['bare_excluded'].append('%s:%d from %s' % (module, node.lineno, node.module))
            elif top in helpers:
                report['outside_scope'].append('%s:%d from %s' % (module, node.lineno, node.module))


def _requote(src, node, value):
    """A literal for `value` in the quote style of the original literal (one single-line token, escapes allowed)."""
    segment = src.segment(node)
    if not re.fullmatch(r"[rRuU]?('(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\")", segment) \
            or ast.literal_eval(segment) != node.value:
        raise FoldError('%s line %d: literal too complex to rewrite in place: %s'
                        % (src.name, node.lineno, segment[:60]))
    quote = segment[-1]
    if quote in value or '\\' in value or '\n' in value:
        raise FoldError('%s line %d: replacement does not fit the literal' % (src.name, node.lineno))
    return quote + value + quote


def _requote_joined(src, node, value):
    """r5: _requote for a literal written as adjacent string tokens (implicit concatenation, possibly over lines
    inside brackets). Each token must be one a _requote would take, all in one quote style, with only whitespace and
    line breaks between them (a comment is refused); the whole span becomes one literal for `value`."""
    segment = src.segment(node)
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO('(' + segment + ')').readline)
                  if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER)]
    except (tokenize.TokenError, SyntaxError) as exc:
        raise FoldError('%s line %d: literal does not tokenize: %s' % (src.name, node.lineno, exc)) from None
    parts = tokens[1:-1]
    plain = re.compile(r"[rRuU]?('(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\")")
    if len(tokens) < 3 or tokens[0].string != '(' or tokens[-1].string != ')' \
            or any(t.type != tokenize.STRING or not plain.fullmatch(t.string) for t in parts) \
            or len({t.string[-1] for t in parts}) != 1 or ast.literal_eval('(' + segment + ')') != node.value:
        raise FoldError('%s line %d: literal too complex to rewrite in place: %s'
                        % (src.name, node.lineno, segment[:60]))
    quote = parts[0].string[-1]
    if quote in value or '\\' in value or '\n' in value:
        raise FoldError('%s line %d: replacement does not fit the literal' % (src.name, node.lineno))
    return quote + value + quote


def _task_file(key, folder):
    """r5: what task_file(key, folder) finds: the one ancestor of `folder` (itself included) holding the file `key`,
    or None when none or several do."""
    start = Path(folder).resolve()
    found = [parent/key for parent in (start, *start.parents) if (parent/key).is_file()]
    return found[0] if len(found) == 1 else None


def _text_rewrite(src, node, names):
    """Helper imports inside a source-text literal -> `import P.X as Y` / `from P.X import ...`."""
    segment = src.segment(node)
    # A keyword starts the text, follows a non-word character, or follows an escape such as \n in the literal.
    pattern = re.compile(r'(?:(?<![\w])|(?<=\\[nrtf]))(import|from)([ \t]+)(%s)(?=([ \t]+)(as|import)\b)'
                         % '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True)))

    def fix(match):
        if (match.group(1), match.group(5)) not in (('import', 'as'), ('from', 'import')):
            raise FoldError('%s line %d: text import without the dotted `as` form' % (src.name, node.lineno))
        return match.group(1) + match.group(2) + PRIVATE + '.' + match.group(3)

    new_segment = pattern.sub(fix, segment)
    value = node.value if isinstance(node.value, str) else node.value.decode('latin-1')
    expected = pattern.sub(fix, value)
    # Parenthesised: an implicitly concatenated literal may span lines, which only parses inside brackets.
    got = ast.literal_eval('(' + new_segment + ')')
    got = got if isinstance(got, str) else got.decode('latin-1')
    if got != expected:
        raise FoldError('%s line %d: text rewrite does not round-trip' % (src.name, node.lineno))
    left = [n for n in PC._imported_names(got) if n.split('.')[0] in names]
    if left:
        raise FoldError('%s line %d: text still imports %s bare' % (src.name, node.lineno, left[:3]))
    return new_segment


PROBE_TEXT = re.compile(r'(import|from)([ \t]+)(\w+)((?:[ \t]+(?:as|import))?)')


def _probe(src, node, names):
    """A membership probe for a helper import (`'import X' in source`, also `'import X as'`, `'from X'` and
    `'from X import'`), qualified so that it still finds the import the fold writes into generated source (parity
    v2.4 reads it back); None for any other text."""
    parent = src.parents.get(node)
    match = PROBE_TEXT.fullmatch(node.value) if isinstance(node.value, str) else None
    if not (match and match.group(3) in names and (match.group(1), match.group(4).strip()) in PC.PROBE_PAIRS
            and isinstance(parent, ast.Compare) and parent.left is node and len(parent.ops) == 1
            and isinstance(parent.ops[0], (ast.In, ast.NotIn))):
        return None
    return _requote(src, node, match.group(1) + match.group(2) + PRIVATE + '.' + match.group(3) + match.group(4))


def _wrap_call(src, node, inner, head, kind):
    """`node` becomes `head` + inner's text + `)`: the text before and after `inner` is replaced, so edits inside
    `inner` stay."""
    start, end = src.span(node)
    inner_start, inner_end = src.span(inner)
    src.edit(start, inner_start, head, kind, node.lineno)
    src.edit(inner_end, end, ')', kind, node.lineno)


def _surround(src, node, head, kind):
    """`node` becomes `head` + its text + `)`, by insertion. A generator that is a call's sole argument has the call's
    parentheses as its own span, so the call gets a new pair: `f(x for x in y)` -> `f(head(x for x in y))`."""
    start, end = src.span(node)
    call, tail = src.parents.get(node), ')'
    if isinstance(node, ast.GeneratorExp) and isinstance(call, ast.Call) and call.args == [node] \
            and src.span(call)[1] == end:
        head, tail = '(' + head, '))'
    src.edit(start, start, head, kind, node.lineno, (1, start - end))
    src.edit(end, end, tail, kind, node.lineno, (0, end - start))


def _wrapped(report, module, node, kind):
    """Record a wrap for the manifest: the original node's full span and the identity function applied to it."""
    report['wraps'].append((module, node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, kind))


def _resolve_base(node):
    """`B.resolve()` -> B; anything else -> None."""
    if isinstance(node, ast.Call) and not node.args and not node.keywords and isinstance(node.func, ast.Attribute) \
            and node.func.attr == 'resolve':
        return node.func.value
    return None


def _carry(src, sid, node, decision):
    """A carried literal: the decision names its sha256 and its own module pins it by that sha (a string constant)."""
    pin = PC.literal_sha(node.value)
    if pin is None:
        raise FoldError('site %s: a literal with lone surrogates cannot be carried' % sid)
    if decision.get('sha256') != pin:
        raise FoldError('site %s: carry needs the literal sha256 %s' % (sid, pin))
    if not any(isinstance(other, ast.Constant) and other.value == pin for other in ast.walk(src.tree)):
        raise FoldError('site %s: a carried literal must be pinned by its own module' % sid)
    return pin


def _joined(src, node):
    """The constant names joined onto `node` by `/` (`Path(lit)/'a'/'b.py'` -> 'a/b.py'), or None when `node` is
    used any other way or a name is not a plain relative part."""
    parts = []
    while True:
        parent = src.parents.get(node)
        if not (isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Div) and parent.left is node
                and isinstance(parent.right, ast.Constant) and isinstance(parent.right.value, str)):
            break
        parts.extend(parent.right.value.split('/'))
        node = parent
    if not parts or any(part in ('', '.', '..') or '\\' in part or ':' in part for part in parts):
        return None
    return '/'.join(parts)


def apply_sites(src, module, sites, decisions, names, report, uses_identity):
    for sid, kind, node in sites:
        decision = decisions.get(sid)
        if decision is None:
            raise FoldError('unclassified site %s: %s' % (sid, _expr(node)))
        if decision.get('expr') != _expr(node):
            raise FoldError('site %s no longer matches its decision: %s' % (sid, _expr(node)))
        do = decision.get('do')
        if do not in DECISIONS[kind]:
            raise FoldError('site %s: %r is not a decision for a %s site' % (sid, do, kind))
        if kind == 'abs' and do == 'keep' and node.value not in PC.WINDOWS_PREFIXES:
            raise FoldError('site %s: only a Windows path prefix literal can be kept' % sid)
        report['sites'].append(dict(site=sid, do=do, why=decision.get('why', '')))
        if do == 'carry':
            report['carried'].append(dict(site=sid, module=module, sha256=_carry(src, sid, node, decision)))
            continue
        if do == 'keep':
            continue
        if kind == 'datakey':
            # r5: the relative task key -> the declared data file's package key, found as task_file finds it.
            key = decision.get('key')
            data = report['data_sources']
            if key not in data or not _names_data(node.value, (data[key],)):
                raise FoldError('site %s: key %r is not the declared data file this literal names' % (sid, key))
            if module.startswith(PACKAGE + '.'):
                raise FoldError('site %s: a data key is resolved from a helper module only' % sid)
            target = _task_file(node.value, report['module_dirs'][module])
            if target is None:
                raise FoldError('site %s: the key is not under exactly one ancestor of %s' % (sid, module))
            if report['key_map'].setdefault(node.value, key) != key \
                    or report['data_keys'].setdefault(node.value, dict(key=key, target=str(target), sites=[]))[
                        'target'] != str(target):
                raise FoldError('site %s: literal already mapped differently' % sid)
            report['data_keys'][node.value]['sites'].append(sid)
            start, end = src.span(node)
            src.edit(start, end, _requote_joined(src, node, key), kind, node.lineno)
        elif kind == 'string':
            if '.' in node.value or node.value not in names:
                raise FoldError('site %s: only a folded helper name can be qualified' % sid)
            start, end = src.span(node)
            src.edit(start, end, _requote(src, node, PRIVATE + '.' + node.value), kind, node.lineno)
        elif kind == 'text':
            start, end = src.span(node)
            probe = _probe(src, node, names)
            src.edit(start, end, probe or _text_rewrite(src, node, names), 'probe' if probe else kind, node.lineno)
        elif kind == 'key':
            # str(Path(x).resolve()) -> relkey(x), the gate's KEY form; str(B.resolve()) -> relkey(B), a declared
            # wrap in the manifest.
            x = _key_form(node)
            _wrap_call(src, node, x if x else _resolve_base(node.args[0]), IDENT + '.relkey(', kind)
            if not x:
                _wrapped(report, module, node, 'relkey')
            uses_identity.add(module)
        elif kind == 'read':
            inner = node.func.value
            _wrap_call(src, inner, inner.args[0], '%s.%s(' % (IDENT, do), kind)
            if do == 'as_path':
                _wrapped(report, module, inner, 'as_path')
            uses_identity.add(module)
        elif kind == 'abs':
            key = decision.get('key')
            if not isinstance(key, str) or PC._is_abs(key) or PC.USER_PATH.search(key) \
                    or not key.startswith(PACKAGE + '/') and key != PACKAGE:
                raise FoldError('site %s: key %r is not package-relative' % (sid, key))
            if report['key_map'].setdefault(node.value, key) != key:
                raise FoldError('site %s: literal already mapped to %s' % (sid, report['key_map'][node.value]))
            parent = src.parents.get(node)
            report['abs_uses'].append((sid, node.value, key, _joined(src, parent if _is_path_call(parent)
                                                                   and parent.args[0] is node else node)))
            if do == 'resolve':
                call = src.parents.get(node)
                if not (_is_path_call(call) and call.args[0] is node):
                    raise FoldError('site %s: a resolve literal must be the argument of Path(...)' % sid)
                start, end = src.span(call)
                src.edit(start, end, "%s.resolve('%s')" % (IDENT, key), kind, node.lineno)
            elif do == 'key':
                start, end = src.span(node)
                src.edit(start, end, _requote(src, node, key), kind, node.lineno)
            else:
                const = decision.get('const')
                if not (isinstance(const, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', const)):
                    raise FoldError('site %s: constant needs an upper-case `const`' % sid)
                if decision.get('runtime') not in ('str', 'path'):
                    raise FoldError('site %s: constant runtime must be "str" or "path"' % sid)
                if report['identity_constants'].setdefault(const, [key, decision.get('runtime')]) \
                        != [key, decision.get('runtime')]:
                    raise FoldError('identity constant %s declared twice differently' % const)
                start, end = src.span(node)
                src.edit(start, end, '%s.%s' % (IDENT, const), kind, node.lineno)
            if do != 'key':
                uses_identity.add(module)


def parse_wraps(sites):
    """{module: [(wrap id, line, col, do, entry)]} from SITES.json `wraps`, each id checked."""
    out = {}
    for wid, entry in sites.get('wraps', {}).items():
        parts = wid.rsplit(':', 3)
        if len(parts) != 4 or not parts[1].isdigit() or not parts[2].isdigit() or parts[3] not in WRAPS \
                or not isinstance(entry, dict) or entry.get('do') != parts[3] or not isinstance(entry.get('expr'), str):
            raise FoldError('malformed wrap %s' % wid)
        out.setdefault(parts[0], []).append((wid, int(parts[1]), int(parts[2]), parts[3], entry))
    return out


def find_wrap(src, wid, line, col, expr):
    hits = [node for node in ast.walk(src.tree) if isinstance(node, ast.expr) and node.lineno == line
            and node.col_offset == col and _expr(node) == expr]
    if len(hits) != 1:
        raise FoldError('wrap %s: %d expressions match (needs exactly one)' % (wid, len(hits)))
    return hits[0]


def apply_wraps(src, module, wraps, report, uses_identity):
    seen = set()
    for wid, line, col, do, entry in wraps:
        node = find_wrap(src, wid, line, col, entry['expr'])
        if id(node) in seen:
            raise FoldError('wrap %s: the expression is wrapped twice' % wid)
        if node in PC._docstrings(src.tree):
            raise FoldError('wrap %s: a docstring is never wrapped' % wid)
        seen.add(id(node))
        if do == 'relkey':
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'str'
                    and PC._single(node) is not None):
                raise FoldError('wrap %s: relkey wraps a str(E) call' % wid)
            inner = node.args[0]
            _wrap_call(src, node, _resolve_base(inner) or inner, IDENT + '.relkey(', 'wrap')
        elif do == 'as_path':
            if not _is_path_call(node):
                raise FoldError('wrap %s: as_path wraps a Path(x) call' % wid)
            _wrap_call(src, node, node.args[0], IDENT + '.as_path(', 'wrap')
        elif do == 'join':
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
                raise FoldError('wrap %s: join wraps a / b' % wid)
            left_end, right_start = src.span(node.left)[1], src.span(node.right)[0]
            if not re.fullmatch(r'[ \t]*/[ \t]*', src.text[left_end:right_start]):
                raise FoldError('wrap %s: the operands of / are not bare' % wid)
            _surround(src, node, IDENT + '.join(', 'wrap')
            src.edit(left_end, right_start, ', ', 'wrap', node.lineno)
        else:
            _surround(src, node, '%s.%s(' % (IDENT, do), 'wrap')
        _wrapped(report, module, node, do)
        uses_identity.add(module)
        report['sites'].append(dict(site=wid, do=do, why=entry.get('why', '')))


def add_identity_import(src, module):
    if IDENT in PC._identifiers(src.tree):
        raise FoldError('%s already uses the identifier %s' % (module, IDENT))
    body = src.tree.body
    first_use = min(e[4] for e in src.edits if IDENT in e[2])
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not (isinstance(node, ast.ImportFrom)
                                                                    and node.module == '__future__'):
            if node.lineno > first_use:
                break
            _, end = src.span(node)
            src.edit(end, end, '; ' + IMPORT_IDENTITY, 'identity', node.lineno)
            return
    raise FoldError('%s: no module-level import before the first identity use' % module)


# ------------------------------------------------------------------ pins (F5, F8)
HEX_ANY = re.compile(r'[0-9a-f]{64}')


def repin(sources, old_to_key, final_sha, order_report):
    """Bottom-up re-pin over the pin graph; refuses a cycle and any embedded pin it cannot rewrite."""
    edges, embedded = {}, {}
    for key, src in sources.items():
        edges[key], embedded[key] = set(), []
        for node in ast.walk(src.tree):
            if not (isinstance(node, (ast.Constant)) and isinstance(node.value, (str, bytes))):
                continue
            value = node.value if isinstance(node.value, str) else node.value.decode('latin-1')
            match = PC.HEX64.match(value) if isinstance(node.value, str) else None
            if match and match.group(2) in old_to_key:
                target = old_to_key[match.group(2)]
                if target == key:
                    raise FoldError('%s pins its own sha' % key)
                edges[key].add(target)
                continue
            for old in HEX_ANY.findall(value):
                if old in old_to_key:
                    edges[key].add(old_to_key[old])
                    embedded[key].append((node.lineno, old))
    done, order = {}, []

    def visit(key, stack):
        if key in done:
            return
        if key in stack:
            raise FoldError('pin cycle: %s' % ' -> '.join(stack + [key]))
        for target in sorted(edges.get(key, ())):
            visit(target, stack + [key])
        for line, old in embedded[key]:
            if final_sha[old_to_key[old]] != old:
                raise FoldError('%s line %d: pin %s of a changed file inside a longer string or bytes'
                                % (key, line, old[:8]))
        src = sources.get(key)
        if src is not None:
            for node in ast.walk(src.tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    match = PC.HEX64.match(node.value)
                    if match and match.group(2) in old_to_key:
                        new = final_sha[old_to_key[match.group(2)]]
                        if new != match.group(2):
                            start, end = src.span(node)
                            src.edit(start, end, _requote(src, node, (match.group(1) or '') + new), 'pin',
                                     node.lineno)
                            order_report.append('%s:%d %s -> %s' % (key, node.lineno, match.group(2)[:8], new[:8]))
            final_sha[key] = digest(src.result())
        done[key] = True
        order.append(key)

    for key in sorted(edges):
        visit(key, [])
    return order


# ------------------------------------------------------------------ the fold
def collect(comp, trace, sites):
    folded, why, lazy_excluded, patched = module_set(comp, trace, sites)
    exclude = set(sites.get('exclude', {}))
    names = set(folded) | exclude
    data_sources = {key: entry['source'] for key, entry in sites.get('data_files', {}).items()
                    if isinstance(entry, dict) and isinstance(entry.get('source'), str) and entry['source']}
    for key, entry in sites.get('data_files', {}).items():
        # r5 (refuter r3): another spelling of the same source ('./x', 'a//x') would turn data-key classification off.
        if not _plain_rel(entry.get('source') if isinstance(entry, dict) else None):
            raise FoldError('data file %s: the source must be a plain relative POSIX path' % key)
    report = dict(sites=[], bare_excluded=[], outside_scope=[], key_map={}, identity_constants={}, wraps=[],
                  carried=[], abs_uses=[], data_sources=data_sources, data_keys={},
                  module_dirs={name: comp.helpers[name].parent for name in folded})
    sources, found = {}, {}
    for name in folded:
        sources[PRIVATE_DIR + '/' + name + '.py'] = (name, Source(name, comp.helpers[name].read_bytes()))
    for stem, path in comp.package.items():
        sources[PACKAGE + '/' + stem + '.py'] = (PACKAGE + '.' + stem, Source(PACKAGE + '.' + stem, path.read_bytes()))
    for key, (module, src) in sources.items():
        found[key] = find_sites(src, module, names, tuple(data_sources.values()))
    return folded, why, lazy_excluded, patched, exclude, names, report, sources, found


def candidates(comp, trace, sites):
    folded, why, lazy_excluded, patched, exclude, names, _, sources, found = collect(comp, trace, sites)
    decisions = sites.get('sites', {})
    rows, stale = [], []
    for key, entries in sorted(found.items()):
        for sid, kind, node in entries:
            decision = decisions.get(sid)
            if decision is not None and decision.get('expr') != _expr(node):
                stale.append(sid)
            rows.append(dict(site=sid, kind=kind, file=key, expr=_expr(node),
                             decided=None if decision is None else decision.get('do')))
    known = {row['site'] for row in rows}
    by_module = {module: src for module, src in sources.values()}
    matches = {}
    for module, entries in parse_wraps(sites).items():
        for wid, line, col, _, entry in entries:
            tree = by_module[module].tree if module in by_module else ast.Module(body=[], type_ignores=[])
            matches[wid] = sum(1 for node in ast.walk(tree) if isinstance(node, ast.expr) and node.lineno == line
                               and node.col_offset == col and _expr(node) == entry['expr'])
    return dict(module_set=len(folded), added_by_closure={n: w for n, w in why.items() if w != 'trace'},
                lazy_excluded=lazy_excluded, harness_patched=patched, sites=rows, stale=stale,
                orphan_decisions=sorted(set(decisions) - known),
                counts={k: sum(r['kind'] == k for r in rows) for k in DECISIONS},
                wraps=len(matches), bad_wraps=sorted(w for w, n in matches.items() if n != 1))


def _origin(module):
    """The module's file in the composition, as the manifest's `modules` names it."""
    if module.startswith(PACKAGE + '.'):
        return 'src/%s/%s.py' % (PACKAGE, module.split('.', 1)[1])
    return 'helpers/%s.py' % module


def data_files(sites, data_root, taken):
    """{package key: bytes} for SITES.json `data_files`, each read from under DATA_ROOT and checked against its
    declared sha256."""
    entries = sites.get('data_files', {})
    if entries and not data_root:
        raise FoldError('data_files need --data-root')
    out = {}
    for key, entry in sorted(entries.items()):
        parts = key.split('/')
        if not (isinstance(entry, dict) and set(entry) == {'source', 'sha256'} and parts[0] == PACKAGE
                and len(parts) > 1 and not key.endswith('.py') and '\\' not in key and ':' not in key
                and not any(part in ('', '.', '..') for part in parts) and key not in taken):
            raise FoldError('malformed data file %s' % key)
        source = Path(entry['source'])
        if source.anchor or '..' in source.parts:
            raise FoldError('data file %s: source must be relative to --data-root' % key)
        raw = (Path(data_root)/source).read_bytes()
        if digest(raw) != entry['sha256']:
            raise FoldError('data file %s: source sha %s is not the declared sha' % (key, digest(raw)[:8]))
        out[key] = raw
    return out


def _accept_repin(decisions, key, literal_sha, old):
    """F5 (decision 2): a literal whose file differs from the composition's file is re-pinned only when every
    decision retargeting it to `key` names both shas and a reason."""
    sids = sorted(sid for sid, d in decisions.items() if d.get('key') == key and d.get('do') in DECISIONS['abs'])
    if not sids:
        raise FoldError('re-pin of %s has no deciding site' % key)
    for sid in sids:
        accepted = decisions[sid].get('accept_repin')
        if not (isinstance(accepted, list) and len(accepted) == 3 and accepted[:2] == [literal_sha, old]
                and isinstance(accepted[2], str) and accepted[2].strip()):
            raise FoldError('site %s: re-pin of %s from %s to %s needs accept_repin [%s, %s, why]'
                            % (sid, key, literal_sha[:8], old[:8], literal_sha, old))
    return sids


def _joins(report, decisions, sources, old_sha, comp, a_package, literal, key, joined, accepted, spelled):
    """F5 for a folder literal (r3). The composition's or arm A's own folder needs nothing. Any other folder may only
    have file names joined onto it; each must be a folded file, and one whose sha differs from the composition file's
    is re-pinned only when that site's decision carries accept_repin_joins {name: [joined sha, composition sha, why]}.
    """
    target = Path(literal)
    if not target.is_dir():
        raise FoldError('F5 literal for %s names no file or folder here' % key)
    rest = key.split('/')[1:]
    if target.resolve() in {Path(base, *rest).resolve() for base in (comp.package_dir, a_package)}:
        return
    for sid, value, _, name in report['abs_uses']:
        if value != literal:
            continue
        if name is None:
            raise FoldError('site %s: a folder literal from outside the composition may only have file names joined '
                            'onto it' % sid)
        fkey = key + '/' + name
        if fkey not in sources:
            raise FoldError('site %s: %s joined onto an outside folder is not a folded file' % (sid, fkey))
        path = target/name
        if not path.is_file():
            raise FoldError('site %s: %s names no file here' % (sid, name))
        sha = digest(path.read_bytes())
        if joined.setdefault(fkey, sha) != sha:
            raise FoldError('F5 key %s is joined from two folders with different shas' % fkey)
        spelled.setdefault(fkey, {})[str(path.resolve())] = sha
        if sha == old_sha[fkey]:
            continue
        given = decisions[sid].get('accept_repin_joins')
        given = given.get(name) if isinstance(given, dict) else None
        if not (isinstance(given, list) and len(given) == 3 and given[:2] == [sha, old_sha[fkey]]
                and isinstance(given[2], str) and given[2].strip()):
            raise FoldError('site %s: re-pin of %s from %s to %s needs accept_repin_joins {%s: [%s, %s, why]}'
                            % (sid, fkey, sha[:8], old_sha[fkey][:8], name, sha, old_sha[fkey]))
        accepted.setdefault(fkey, dict(literal_sha=sha, composition_sha=old_sha[fkey], sites=[], via='join'))
        accepted[fkey]['sites'].append(sid)


def _stale_accepts(decisions, accepted):
    """An acceptance no re-pin needs is refused, so a decision cannot carry a stale or misplaced one."""
    used = {(sid, key) for key, row in accepted.items() for sid in row['sites']}
    stale = []
    for sid, decision in sorted(decisions.items()):
        if 'accept_repin' in decision and (sid, decision.get('key')) not in used:
            stale.append(sid)
        for name in decision.get('accept_repin_joins') or {}:
            if (sid, '%s/%s' % (decision.get('key'), name)) not in used:
                stale.append(sid)
    if stale:
        raise FoldError('acceptances that no re-pin needs: %s' % sorted(set(stale))[:5])


# ------------------------------------------------------------------ K5 (r4): key readers
_UNWRAP = ('tuple', 'list', 'sorted', 'set', 'frozenset', 'dict', 'reversed')


def _module_aliases(module, tree, known):
    """{local name: folded module} for `import M [as a]`, `from P import M [as a]` and, in the package, `from . import
    M [as a]`."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module + '.' if node.module else ''
            elif node.level == 1 and module.startswith(PACKAGE + '.'):
                base = PACKAGE + '.' + (node.module + '.' if node.module else '')
            else:
                continue
            for alias in node.names:
                out[alias.asname or alias.name] = base + alias.name
    return {name: target for name, target in out.items() if target in known}


def _module_statements(body):
    """Statements that run at import: the module body and the bodies of its compound statements, not of defs."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield stmt
        for field in ('body', 'orelse', 'finalbody'):
            yield from _module_statements(getattr(stmt, field, ()) or ())
        for handler in getattr(stmt, 'handlers', ()) or ():
            yield from _module_statements(handler.body)


def _assigned(stmt):
    """Names a statement assigns; `T[k] = v` assigns T."""
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    else:
        return []
    names = []
    for target in targets:
        while isinstance(target, ast.Subscript):
            target = target.value
        names += [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]
    return names


def key_readers(sources, decisions, wraps):
    """K5: every name bound by iterating a table that holds keys must reach a path only through a decided join,
    as_path or read decision. Returns the report entry; refuses an uncovered reader."""
    by_module = {module: src for module, src in sources.values()}
    marks = {}
    for sid, entry in decisions.items():
        module, line, col, kind = sid.rsplit(':', 3)
        if (kind == 'abs' and entry.get('do') == 'key') or (kind == 'key' and entry.get('do') == 'relkey'):
            marks.setdefault(module, set()).add((int(line), int(col)))
    covered = set()
    for module, rows in wraps.items():
        for _, line, col, do, _ in rows:
            covered.add((module, line, col, do))
            if do == 'relkey':
                marks.setdefault(module, set()).add((line, col))
    for sid, entry in decisions.items():
        module, line, col, kind = sid.rsplit(':', 3)
        if kind == 'read' and entry.get('do') in ('resolve', 'as_path'):
            covered.add((module, int(line), int(col), 'as_path'))
    aliases = {module: _module_aliases(module, src.tree, by_module) for module, src in by_module.items()}

    def ref(module, node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            return (module, node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases[module]:
            return (aliases[module][node.value.id], node.attr)
        return None

    statements = {module: list(_module_statements(src.tree.body)) for module, src in by_module.items()}
    tables = set()
    for module, stmts in statements.items():
        for stmt in stmts:
            names = _assigned(stmt)
            if names and any(isinstance(n, ast.expr) and (n.lineno, n.col_offset) in marks.get(module, ())
                             for n in ast.walk(stmt)):
                tables.update((module, name) for name in names)
    while True:
        grown = set(tables)
        for module, stmts in statements.items():
            for stmt in stmts:
                names = _assigned(stmt)
                if names and any(ref(module, n) in tables for n in ast.walk(stmt)):
                    grown.update((module, name) for name in names)
        if grown == tables:
            break
        tables = grown

    def table_of(module, node):
        while isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords \
                and isinstance(node.func, ast.Name) and node.func.id in _UNWRAP:
            node = node.args[0]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('items', 'keys') \
                and not node.args:
            node = node.func.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'getattr':
            return 'getattr'
        found = ref(module, node)
        return '%s.%s' % found if found in tables else None

    readers, refused = [], []
    for module, src in sorted(by_module.items()):
        for node in ast.walk(src.tree):
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                loops = [(g, [node]) for g in node.generators]
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                loops = [(node, node.body + node.orelse)]
            else:
                continue
            for loop, scope in loops:
                table = table_of(module, loop.iter)
                if table is None:
                    continue
                bound = {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}
                for use in (u for part in scope for u in ast.walk(part)):
                    names = None
                    if isinstance(use, ast.BinOp) and isinstance(use.op, ast.Div) and isinstance(use.right, ast.Name) \
                            and use.right.id in bound:
                        need = 'join'
                    elif isinstance(use, ast.Call) and any(isinstance(a, ast.Name) and a.id in bound for a in use.args):
                        func = use.func
                        if isinstance(func, ast.Name) and func.id == 'Path':
                            need = 'as_path' if len(use.args) == 1 and not use.keywords else None
                        elif (isinstance(func, ast.Name) and func.id == 'open') or (
                                isinstance(func, ast.Attribute) and (func.attr == 'joinpath' or (
                                    isinstance(func.value, ast.Attribute) and func.value.attr == 'path'
                                    and isinstance(func.value.value, ast.Name) and func.value.value.id == 'os'))):
                            need = None
                        else:
                            continue
                        names = ast.unparse(use)
                    else:
                        continue
                    site = '%s:%d:%d' % (module, use.lineno, use.col_offset)
                    ok = need is not None and (module, use.lineno, use.col_offset, need) in covered
                    readers.append(dict(site=site, use=names or ast.unparse(use), table=table, needs=need, covered=ok))
                    if not ok:
                        refused.append(site)
    if refused:
        raise FoldError('K5: key readers that reach a path with no join/as_path/read decision: %s'
                        % sorted(set(refused))[:5])
    return dict(tables=sorted('%s.%s' % t for t in tables), readers=readers)


def fold(comp, trace, sites, out_dir, a_helpers, a_src=None, data_root=None):
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FoldError('OUT_DIR exists; the fold never writes over earlier output')
    folded, why, lazy_excluded, patched, exclude, names, report, sources, found = collect(comp, trace, sites)
    decisions = sites.get('sites', {})
    known = {sid for entries in found.values() for sid, _, _ in entries}
    orphans = sorted(set(decisions) - known)
    if orphans:
        raise FoldError('decisions for sites that no longer exist: %s' % orphans[:5])
    wraps = parse_wraps(sites)
    stray = sorted(set(wraps) - {module for module, _ in sources.values()})
    if stray:
        raise FoldError('wraps for modules outside the fold: %s' % stray[:5])
    by_path = set(sites.get('by_path_files', {}))
    uses_identity = set()
    for key, (module, src) in sources.items():
        rewrite_imports(src, module, set(folded), exclude, set(comp.helpers), report)
        apply_sites(src, module, found[key], decisions, set(folded), report, uses_identity)
        apply_wraps(src, module, wraps.get(module, ()), report, uses_identity)
        if module in by_path and src.edits:
            raise FoldError('%s is loaded by path and must fold byte-equal (K1)' % module)
    k5 = key_readers(sources, decisions, wraps)
    for key, (module, src) in sources.items():
        if module in uses_identity:
            add_identity_import(src, module)
    # F5: a literal that named a heat-repair file now names the package file that runs; its old sha is the H file's.
    old_sha = {key: digest(src.raw) for key, (_, src) in sources.items()}
    a_package = (Path(a_src) if a_src else comp.root/'src')/PACKAGE
    declared = {key: entry.get('sha256') for key, entry in sites.get('data_files', {}).items()
                if isinstance(entry, dict)}
    f5, accepted, joined, spelled = {}, {}, {}, {}
    for literal, key in report['key_map'].items():
        target = Path(report['data_keys'][literal]['target']) if literal in report['data_keys'] else Path(literal)
        if key in declared:
            if not target.is_file() or digest(target.read_bytes()) != declared[key]:
                raise FoldError('F5 literal for data file %s does not name the declared bytes' % key)
            continue
        if not key.endswith('.py'):
            _joins(report, decisions, sources, old_sha, comp, a_package, literal, key, joined, accepted, spelled)
            continue
        if key not in sources:
            raise FoldError('F5 key %s is not a folded file' % key)
        if not target.is_file():
            raise FoldError('F5 literal for %s names no file here: %s' % (key, target.name))
        sha = digest(target.read_bytes())
        if f5.setdefault(key, sha) != sha:
            raise FoldError('F5 key %s is named by two literals with different shas' % key)
        spelled.setdefault(key, {})[literal] = sha
    for key, sha in sorted(f5.items()):
        if sha != old_sha[key]:
            accepted[key] = dict(literal_sha=sha, composition_sha=old_sha[key],
                                 sites=_accept_repin(decisions, key, sha, old_sha[key]), via='literal')
    _stale_accepts(decisions, accepted)
    both = sorted(set(f5) & set(joined))
    if both:
        raise FoldError('F5 keys named both by a file literal and by a join: %s' % both[:5])
    old_to_key = {}
    for key, sha in list(old_sha.items()) + list(f5.items()) + list(joined.items()):
        if old_to_key.setdefault(sha, key) != key:
            raise FoldError('two folded files share the old sha %s (%s, %s)' % (sha[:8], old_to_key[sha], key))
    final_sha, repins = {}, []
    order = repin({key: src for key, (_, src) in sources.items()}, old_to_key, final_sha, repins)
    # The tree, held in memory; nothing is written until the manifest and the report are built.
    root = out_dir/'folded'
    files = {}
    for key, (_, src) in sources.items():
        files[key] = src.result()
    files[PACKAGE + '/_identity.py'] = identity_source(report['identity_constants'])
    files[PRIVATE_DIR + '/__init__.py'] = b''
    data = data_files(sites, data_root, set(files))
    files.update(data)
    for literal, row in sorted(report['data_keys'].items()):
        # r5: the file task_file finds is the declared source itself, not a copy elsewhere with the same bytes.
        if not data_root:
            raise FoldError('data keys need --data-root')
        source = (Path(data_root)/sites['data_files'][row['key']]['source']).resolve()
        if Path(row['target']).resolve() != source:
            raise FoldError('data key %s finds %s, not the declared source' % (row['sites'][0], Path(row['target']).name))
    # r5 (refuter r3): no relative literal that finds a file outside the composition from its module's folder may
    # escape classification. On the original side only the classified data keys may (they are retargeted); on the
    # folded side none may find a file outside the fold.
    comp_root, fold_root = comp.root.resolve(), out_dir.resolve()
    for key, (module, src) in sources.items():
        origin = (comp.package[module.split('.', 1)[1]] if module.startswith(PACKAGE + '.')
                  else comp.helpers[module]).parent.resolve()
        stray = [(line, value) for line, value in _resolving_literals(src.tree, origin, comp_root)
                 if value not in report['data_keys']]
        stray += [(line, value) for line, value in
                  _resolving_literals(ast.parse(files[key]), (root/key).parent.resolve(), fold_root)]
        if stray:
            raise FoldError('%s line %d: an unclassified relative literal finds a file: %s'
                            % (module, stray[0][0], stray[0][1][:120]))
    unknown = sorted({key for key in report['key_map'].values() if key != PACKAGE and key not in files})
    if unknown:
        raise FoldError('literals retargeted to keys that are not folded or data files: %s' % unknown[:5])
    # Manifest.
    a_dir = Path(a_helpers) if a_helpers else comp.helpers_dir
    key_map = {str((a_dir/(name + '.py')).resolve()): PRIVATE_DIR + '/' + name + '.py' for name in folded}
    for literal, key in report['key_map'].items():
        if key_map.setdefault(literal, key) != key:
            raise FoldError('literal %s maps to two keys' % literal)
    # A's spelling of each package file, unless a mapped literal already names that key (key_map stays injective;
    # f5_repins carries the other spelling for the records gate).
    claimed = set(key_map.values())
    for stem in comp.package:
        key = PACKAGE + '/' + stem + '.py'
        if key not in claimed and key_map.setdefault(str((a_package/(stem + '.py')).resolve()), key) != key:
            raise FoldError('package file %s maps to two keys' % stem)
    if len(set(key_map.values())) != len(key_map):
        raise FoldError('key_map is not injective')
    sha_map = {}
    for key, raw in files.items():
        new = digest(raw)
        old = f5.get(key, old_sha.get(key, new))
        sha_map[key] = [old, new]
    modules = {_origin(module): key for key, (module, _) in sources.items()}
    if len({wrap[:5] for wrap in report['wraps']}) != len(report['wraps']):
        raise FoldError('two wraps on one expression')
    wrap_entries = [dict(module=_origin(module), line=line, col=col, end_line=end_line, end_col=end_col, kind=kind)
                    for module, line, col, end_line, end_col, kind in sorted(report['wraps'])]
    pins = {}
    for key, (module, src) in sources.items():
        if module in by_path:
            continue
        changed = sha_map[key][0] != sha_map[key][1]
        if not module.startswith(PACKAGE + '.') or changed or key in f5 or key in joined:
            pins[(PRIVATE + '.' + module) if not module.startswith(PACKAGE + '.') else module] = sha_map[key][1]
    pins[IDENTITY] = sha_map[PACKAGE + '/_identity.py'][1]
    # Both spellings arm A can record for an F5 key: the literal (or joined) path with its sha, and A's own path with
    # the composition's sha. key_map keeps one of them (it stays injective); the records gate maps both, nothing else.
    f5_repins = {}
    for key, paths in sorted(spelled.items()):
        name = key.split('/', 1)[1]
        own = (a_dir/name[len('_private/'):]) if key.startswith(PRIVATE_DIR + '/') else a_package/name
        both = dict(paths)
        if both.setdefault(str(own.resolve()), old_sha[key]) != old_sha[key]:
            raise FoldError("F5 literal for %s names A's own file with a different sha" % key)
        if len(both) > 1:
            f5_repins[key] = dict(spellings=both, new=sha_map[key][1], repinned=key in accepted,
                                  via='join' if key in joined else 'literal')
    manifest = dict(key_map=key_map, sha_map=sha_map, bookings=[], self_ids=[], external=[], modules=modules,
                    pins=pins, identity_name=IDENT, f5_repins=f5_repins,
                    identity_constants={k: v[0] for k, v in report['identity_constants'].items()},
                    identity_runtime={k: v[1] for k, v in report['identity_constants'].items()},
                    wraps=wrap_entries,
                    carried=[dict(module=_origin(c['module']), sha256=c['sha256']) for c in report['carried']])
    edits = {}
    for key, (_, src) in sources.items():
        for edit in src.edits:
            edits[edit[3]] = edits.get(edit[3], 0) + 1
    summary = dict(
        module_set=len(folded), added_by_closure={n: w for n, w in why.items() if w != 'trace'},
        excluded=sites.get('exclude', {}), lazy_excluded=lazy_excluded, harness_patched=patched,
        bare_excluded=report['bare_excluded'], outside_scope=report['outside_scope'], f5=f5, f5_joined=joined,
        f5_repins=f5_repins,
        repins=repins, repin_order=[k for k in order if any(r.startswith(k + ':') for r in repins)],
        edits=edits, changed_files=sorted(k for k, (o, n) in sha_map.items() if o != n),
        identity_users=sorted(uses_identity), site_decisions=report['sites'],
        identity_constants=report['identity_constants'], wraps=wrap_entries,
        k2_exclusions=[s['site'] for s in report['sites'] if s['do'] == 'keep' and s['site'].endswith(':string')],
        accepted_repins=accepted, data_files={key: digest(raw) for key, raw in sorted(data.items())},
        unmatched_pins=_unmatched_pins(sources, decisions, old_to_key),
        residual_hazards=[s for s in report['sites'] if s['why'].startswith('kept: worker')],
        carried=report['carried'], k5=k5,
        data_keys={literal: dict(key=row['key'], sites=row['sites']) for literal, row in report['data_keys'].items()})
    # Write last: the tree, then the manifest.
    out_dir.mkdir(parents=True)
    for key, raw in sorted(files.items()):
        (root/key).parent.mkdir(parents=True, exist_ok=True)
        (root/key).write_bytes(raw)
    (out_dir/'MANIFEST.json').write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding='utf8')
    return manifest, summary, root


def _unmatched_pins(sources, decisions, old_to_key):
    """Per module with a retargeted literal: the sha literals in it that name no folded file. These pins are left as
    they are, so the module's own check decides whether the folded file still matches them."""
    modules = {sid.split(':')[0] for sid, d in decisions.items() if sid.endswith(':abs') and d.get('do') != 'keep'}
    out = {}
    for key, (module, src) in sorted(sources.items()):
        if module not in modules:
            continue
        found = sorted({match.group(2) for node in ast.walk(src.tree) if isinstance(node, ast.Constant)
                        and isinstance(node.value, str) for match in [PC.HEX64.match(node.value)]
                        if match and match.group(2) not in old_to_key})
        out[module] = found
    return out


# ------------------------------------------------------------------ gates
def check_target(sites, record_sha):
    """SITES.json's target.composition_json_sha256, when given, must be the folded composition record's sha."""
    target = sites.get('target', {}).get('composition_json_sha256')
    if target is not None and target != record_sha:
        raise FoldError('SITES.json is for composition %s, not %s' % (target[:8], (record_sha or 'none')[:8]))


def scan(root, carried=()):
    """FOLD §3: no drive letter, user folder, the-diadem or Codex/ in the folded tree. Lines inside a string literal
    whose sha256 is in `carried` (the manifest's carried literals) are listed apart, not as hits."""
    hits, kept, carried = [], [], set(carried)
    for path in sorted(root.rglob('*')):
        if path.is_file():
            raw = path.read_bytes()
            spans = set()
            if carried and path.suffix == '.py':
                for node in ast.walk(ast.parse(raw)):
                    if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                            and PC.literal_sha(node.value) in carried):
                        spans.update(range(node.lineno, node.end_lineno + 1))
            for number, line in enumerate(raw.decode('utf-8', 'replace').splitlines(), 1):
                if PC.USER_PATH.search(line):
                    (kept if number in spans else hits).append('%s:%d' % (path.relative_to(root).as_posix(), number))
    return hits, kept


def gates(comp, out_dir, manifest, root):
    results = {}
    try:
        results['ast'] = PC.check_ast(str(comp.root), str(root), manifest)
    except (PC.ParityError, OSError, SyntaxError) as error:
        results['ast'] = dict(status='FAIL', reason=str(error))
        return results
    try:
        results['pins'] = PC.check_pins(str(root), manifest)
    except (PC.ParityError, OSError, ValueError, KeyError) as error:
        results['pins'] = dict(status='FAIL', reason=str(error))
        return results
    hits, kept = scan(root, [c['sha256'] for c in manifest.get('carried', ())])
    results['scan'] = dict(status='FAIL' if hits else 'PRIVATE' if kept else 'PASS', hits=hits[:40], count=len(hits),
                           carried_lines=kept)
    if results['scan']['status'] != 'FAIL':
        results['k3'] = k3(root)
    return results


K3_PROBE = ('import importlib, json, sys\nsys.path.insert(0, sys.argv[1])\n'
            'module = importlib.import_module(sys.argv[2])\nprint(json.dumps(module.h3_status(), default=str))\n')


def k3(root):
    """FOLD §9 K3: the H3 kernel loads its compiled route on the folded tree (a fallback to Python fails)."""
    owners = sorted(path for path in root.rglob('*.py')
                    if any(isinstance(node, ast.FunctionDef) and node.name == 'h3_status'
                           for node in ast.parse(path.read_bytes()).body))
    if not owners:
        return dict(status='ABSENT', reason='no module in this composition defines h3_status')
    results = []
    for path in owners:
        name = '.'.join(path.relative_to(root).with_suffix('').parts)
        run = PC.run_probe(sys.executable, K3_PROBE, [root, name], root.parent, timeout=600)
        route = None
        if run.returncode == 0:
            route = json.loads(run.stdout.strip().splitlines()[-1]).get('route')
        results.append(dict(module=name, route=route, exit=run.returncode, stderr=run.stderr[-400:]))
    ok = all(r['route'] == 'compiled' for r in results)
    return dict(status='PASS' if ok else 'FAIL', owners=results)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('mode', choices=('candidates', 'fold'))
    parser.add_argument('composed_root')
    parser.add_argument('out')
    parser.add_argument('--trace', required=True)
    parser.add_argument('--sites')
    parser.add_argument('--a-helpers')
    parser.add_argument('--a-src')
    parser.add_argument('--data-root')
    parser.add_argument('--no-gates', action='store_true')
    args = parser.parse_args(argv)
    try:
        comp = Composition(args.composed_root)
        trace = _load_json(args.trace)
        sites = _load_json(args.sites) if args.sites else {}
        if args.mode == 'candidates':
            result = candidates(comp, trace, sites)
            Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf8')
            print(json.dumps(dict(status='OK', module_set=result['module_set'], counts=result['counts'],
                                  undecided=sum(r['decided'] is None for r in result['sites']),
                                  stale=len(result['stale']), orphans=len(result['orphan_decisions']),
                                  wraps=result['wraps'], bad_wraps=len(result['bad_wraps']))))
            return 0
        if not args.sites:
            raise FoldError('fold needs --sites')
        record = comp.root/'composition.json'
        record_sha = digest(record.read_bytes()) if record.is_file() else None
        check_target(sites, record_sha)
        manifest, summary, root = fold(comp, trace, sites, args.out, args.a_helpers, args.a_src, args.data_root)
        summary['composition_json_sha256'] = record_sha
        summary['gates'] = {} if args.no_gates else gates(comp, args.out, manifest, root)
        out = Path(args.out)
        summary['manifest_sha256'] = digest((out/'MANIFEST.json').read_bytes())
        (out/'FOLD-REPORT.json').write_text(json.dumps(summary, indent=1, sort_keys=True), encoding='utf8')
        failed = [name for name, result in summary['gates'].items() if result.get('status') not in ('PASS', 'PRIVATE')]
        private = [name for name, result in summary['gates'].items() if result.get('status') == 'PRIVATE']
        print(json.dumps(dict(status='FAIL' if failed else 'PRIVATE' if private else 'PASS', failed=failed,
                              private=private, module_set=summary['module_set'],
                              changed=len(summary['changed_files']), edits=summary['edits'],
                              manifest=summary['manifest_sha256'])))
        return 1 if failed else 0
    except (FoldError, PC.ParityError, OSError, SyntaxError, ValueError, KeyError) as error:
        print(json.dumps(dict(status='FAIL', reason='%s: %s' % (type(error).__name__, error))))
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
