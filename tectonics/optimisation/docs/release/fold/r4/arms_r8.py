"""R1 fold parity arms, revision 8 (FOLD.md §5, §9 K4, §10.5; review r1 decisions 1 and 5, finding F6).

  python -B arms_r8.py prepare-a A_DIR COMPOSED_ROOT HCF CONTROL_PY [COMPOSITION_JSON]
  python -B arms_r8.py prepare-b B_DIR FOLD_OUT A_DIR
  python -B arms_r8.py child LAYOUT OUT_DIR [REFERENCE_JSON]

Revision 8 (23 Oct) = revision 7 with the native library record (RF2 condition c, FOLD.md §14):
- child's arm.json gains native: sys.exec_prefix, the path RF2's _ASSEMBLY_MPFR_PATH is joined to (exec_prefix
  /Lib/site-packages/gmpy2.libs/libmpfr-6.dll) and {path: sha256} of each module this process has loaded whose file
  name starts libmpfr or libgmp (K32EnumProcessModules, GetModuleFileNameW). It is read after the control call, the
  audit, the observer and the digests are finished, and the sha256 is the untapped one, so no record changes.
- The workers' observer is wobs2/sitecustomize.py, which writes the same record into each worker's exit snapshot;
  each workers row carries it (None for a worker that left no snapshot).
v27/mpfr_same.py judges the records across the arms and their workers.

Revision 7 (23 Oct) = revision 6 with the r3 bookings items (FOLD.md §13 items 1, 2, 4 and 5):
- prepare-a's wrapper for a later r13 is hcf_prepare_r15.py, which also takes p20c-r3's composition record (the
  cell key is not its job: child saves it, below).
- Each rational is digested as signed (numerator, denominator), not (|numerator|, denominator).
- For gmpy2 values each rationals row also records the tight size summed over the row, and the number of values
  whose getsizeof is below their own tight size. The tight size is the type's __basicsize__ plus |numerator| and the
  denominator in whole limbs, the least getsizeof gmpy2 can report for that value. Fraction rows record None for both.
- Each row also records how many distinct objects it counts, by id within one walk over objects the frame holds
  alive, and their size sum. The interval inventory's singleton pairs count each object twice
  (R3-STEP-NOTE.md item 5).
- child's arm.json records the gmpy2 build this process loaded: version(), mp_version(), mp_limbsize(), the mpq and
  mpz basic sizes and the sha256 of each loaded gmpy2 module file; loaded=False when nothing imported gmpy2.
- Each child also saves the heat result into OUT_DIR/save, as HCF's array saver does and at the same return (the r13
  issuer's advance() returning to the control's child()). It writes the arrays, arrays.json and cell_keys.json, and
  the cell key fields add the row's kind (exterior or collar) and physical_cell_id, the cross-composition key of
  collar cells (FOLD.md §13 item 6). The
  array digests use the untapped sha256, so the journal is unchanged. An incomplete save fails the child.
  Why not a wrapper: HCF's KEY_FIELDS is read only by HCF's child, and that child lists every module loaded from the
  workspace outside its frozen layout, so a wrapper would list itself. The harness is outside its own leak check by
  design, as HCF is in HCF's. v27/cells_keyed.py compares two saves by that key.

Revision 6 (23 Oct) = revision 5 with one change: prepare-a's wrapper for a later r13 is hcf_prepare_r14.py, whose
reviewed composition records are p20c-r1's and p20c-r2's (r5's hcf_prepare_r13.py takes p20c-r1's only).

Revision 3 = revision 2 plus booking TERMS (decision 5; the exact per-site rule proposed for R2): at the return
of the endpoint/interval inventory derive, the LOW ledger _admit and the decimal inventory _derive, a read-only
function of the frame records the terms each booking is summed from that a snapshot cannot hold (key item and
container getsizeof, a census of the LOW footprint walk, the decimal scan totals and the strings it charges).
v25/bookings.py recomputes every booking from its terms on each arm and ties each B term to A's. A term error
is an arm failure of its own.

Revision 5 = revision 4 plus the LOW ledger's _plan as a booking site: _admit only charges scan_bytes, and the
inventory it reserves (source_work, the stage components, work and result_bytes) is built in _plan. Its terms are
the DiagnosticInventory's three byte fields, CONTAINER_UNIT, the owner count and getsizeof(target).

Revision 4 = revision 3 with complete terms: the footprint walks mirror _footprint exactly (the outer values tuple
is not an object of its own) and record each type's count, getsizeof sum and largest object; every rational a
walk or owned_bytes charges is recorded as a multiset digest of (|numerator|, denominator) with its count and
getsizeof sum, because gmpy2 reports allocated limbs and reuses freed objects, so equal values can differ in
getsizeof by allocation history; the finish inventory footprint walk, the forward kernel's face-id text and
RESIDUE, the inventory maxima and an int return value (the orchestration bytes) are added. Everything below is
revision 2:

The arms are those of arms.py (r1): A is the unfolded composition prepared by the reviewed probe HCF, B is FOLD_OUT's
folded tree with the same r13 insertion and the control with only its helper imports rewritten, and child runs the
control's child() in this process from the layout's cwd (B: never the package parent, K5). A noise arm A' is a second
child run of A_DIR into a new OUT_DIR. Changes from r1:
- prepare-a records the original and patched r13 shas. prepare-b uses fold_r2, writes r13-insertion.diff (folded r13
  to B's r13: the one insertion) with all four r13 shas in arm.json (F6), and writes MANIFEST-h.json: FOLD_OUT's
  manifest with the r13 sha_map entry set to the two patched files and a field `a_layout` mapping each of A's helper
  copies (absolute path, as str() of the resolved path) to the composition path it copies (byte-equal checked; r13
  through its insertion). key_map stays injective; the records check applies a_layout first.
- child installs a hash tap before the control is imported. hashlib.sha256 is replaced, in this process only, by a
  wrapper around the real constructor that keeps the bytes fed to each object (up to STREAM_CAP) and, at each
  digest()/hexdigest(), writes the distinct (digest, preimage) pairs to OUT_DIR/journal.bin with the index
  journal.json (order of first finalisation, length, offset or null when over a cap, count, the finalising function
  as module:qualname). Every digest returned is the real object's. The records check (v25/parity.py) derives B's
  identifiers from A's preimages and re-hashes every stored preimage.
- Booking sites (F6 and decision 5): at the return of each function in BOOKING_SITES the frame's small locals (ints,
  strings, paths and tables of them) and the module's HERE and *SOURCES*/*PINS* tables go to OUT_DIR/bookings.json,
  so the checker can recompute each booking on A, map its inputs through the manifest and require B's exact value.
- An audit hook, live only during the control call, records process creation (decision 1: in B any spawn fails, since
  a worker would import the helpers itself) and every open, listdir or scandir of a relative path (in B any such read
  fails: it resolves against the cwd, K5).
- K4 counts closed_guard returns in closed_owned r4 and r5.
- B: no bare helper in sys.modules except the compiled-dot module under the certification kernel's seal (a by_path
  file that CK reads beside itself, checks against _H3_SHA256, execs and registers bare, as on A): its __file__ is
  folded/atlas_tectonics/_private/<name>.py, its bytes have the pinned sha, its _H3_SEAL equals (that path, the pin)
  and no qualified twin is loaded. Every other module loaded from the folded _private folder is named
  atlas_tectonics._private.<stem>.
- An exception from the control (for instance an identity-module IdentityError) is a refusal written to arm.json.
Exit 0 only when every check passes; OUT_DIR/arm.json lists the failures. Every root comes from the arguments.
"""
import difflib
from hashlib import sha256 as _real_sha256
import json
import os
from pathlib import Path, PurePath
import re
import shutil
import subprocess
import sys

ISSUER = 'private_heat_native_issuer_r13.py'
CLOSED = ('private_heat_closed_owned_r4.py', 'private_heat_closed_owned_r5.py')
CONTROL_NAME = 'step7_same_call_heat_control'
KEY_FIELDS = ('cell_id', 'logical_cell_id', 'voxel_index', 'partition_path', 'radial_band', 'chart',
              'source_chart_id', 'grid_id', 'kind', 'physical_cell_id')   # r7: HCF's, plus kind and physical_cell_id
ARRAY_NAME = re.compile(r'[A-Za-z0-9_]+')                           # r7: HCF's plain array names
CK_NAME = 'private_heat_certification_kernel_r1'
H3_NAME = 'private_heat_compiled_dot_r1'
PRIVATE = 'atlas_tectonics._private'
MARKER = '# Capture already imported dependencies ONCE, before a caller can request an\n'
TOOL_NAME = 'rm-fold-parity-observer-r5'
ABSOLUTE = re.compile(r'^([A-Za-z]:[\\/]|\\\\)')
USER_PATH = re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/]|^\\\\|[\\/]users[\\/]|/home/|^~[\\/]|%userprofile%|the-diadem'
                       r'|codex[\\/]', re.IGNORECASE)  # parity.USER_PATH, repeated so the child imports nothing
TABLE = re.compile(r'SOURCES|PINS', re.IGNORECASE)
STREAM_CAP = 64 << 20   # bytes kept per sha256 object; a longer stream is journalled by digest and length only
JOURNAL_CAP = 2 << 30   # preimage bytes written per arm
SNAPSHOTS_PER_SITE = 64
BOOKING_SITES = {       # (file stem, co_qualname): the functions holding the F6 bookings (FOLD.md §1 F6, H1)
    ('private_heat_finish_inventory_r1', '_issue'), ('private_heat_finish_inventory_r1', 'admit'),
    ('private_heat_finish_inventory_r2', 'admit'), ('private_heat_low_ledger_inventory_r1', '_admit'),
    ('private_heat_finish_kernel_r10', '_orchestration_bytes'), ('private_heat_finish_kernel_r11', '_orchestration_bytes'),
    ('private_heat_forward_kernel_r13', '_run'), ('private_heat_endpoint_inventory_r3', 'derive'),
    ('private_heat_interval_inventory_r1', 'derive'), ('private_heat_finish_issue_owned_r4', 'issue'),
    ('private_heat_decimal_inventory_r1', '_derive'), ('private_heat_low_ledger_inventory_r1', '_plan'),
}
SPAWN_EVENTS = {'subprocess.Popen', '_winapi.CreateProcess', 'os.posix_spawn', 'os.spawn', 'os.system',
                'os.startfile', 'os.exec', 'os.fork', 'os.forkpty'}
PATH_EVENTS = {'open', 'os.listdir', 'os.scandir'}
WORKER_SCRIPT = 'private_heat_functionals_parallel_r1.py'   # the heat workers run this file as `<file> worker`
OBS_ENV = 'RM_FOLD_WORKER_OBS'
OBS_DIR = Path(__file__).resolve().parent/'wobs2'           # sitecustomize.py: the worker observer r2
EXAMPLES = 20
TERM_STRING_CAP = 4 << 20   # a longer charged string is recorded by length and sha256


def _sha(raw):
    return _real_sha256(raw).hexdigest()


def _write_new(path, data):
    with open(path, 'xb') as handle:
        handle.write(data if isinstance(data, bytes) else data.encode('utf8'))


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


# ------------------------------------------------------------------ prepare
def prepare_a(a_dir, composed_root, hcf, control_py, composition=None):
    a_dir, composed_root = Path(a_dir), Path(composed_root).resolve()
    wrapper = None
    if composition is None:
        command = [sys.executable, '-B', str(hcf), 'prepare']
    else:  # a composition whose r13 is a later revision: HCF's prepare through hcf_prepare_r15.py (r7)
        wrapper = Path(__file__).resolve().parent/'hcf_prepare_r15.py'
        command = [sys.executable, '-B', str(wrapper), str(hcf), str(composition)]
    run = subprocess.run(command + [str(a_dir), str(composed_root/'src'), str(composed_root/'helpers')],
                         capture_output=True, text=True)
    if run.returncode:
        raise SystemExit('HCF prepare failed: %s' % (run.stderr or run.stdout)[-600:])
    info = _json(a_dir/'control.json')
    control_py = Path(control_py).resolve()
    original = Path(info['copied_helpers'][ISSUER]['source'])
    arm = dict(arm='A', control=str(control_py), control_sha256=_sha(control_py.read_bytes()),
               allowed=info['paths'], cwd=str(a_dir.resolve()), hcf=str(Path(hcf).resolve()),
               digest_roots=[str(a_dir.resolve()), str(composed_root/'src')],
               hcf_sha256=_sha(Path(hcf).read_bytes()), composed_root=str(composed_root),
               prepare_wrapper=None if wrapper is None else dict(path=str(wrapper), sha256=_sha(wrapper.read_bytes()),
                                                                 composition=str(Path(composition).resolve())),
               r13=dict(original=str(original), original_sha256=_sha(original.read_bytes()),
                        patched_sha256=_sha((a_dir/'helpers'/ISSUER).read_bytes())))
    _write_new(a_dir/'arm.json', json.dumps(arm, indent=1))
    print(json.dumps(dict(prepared='A', helpers=len(info['copied_helpers']),
                          r13=info['reference_r13_sha256'][:8])))


def _insertion(a_text, original):
    """The text HCF inserted into A's r13 copy before MARKER; refused unless A is exactly original + insertion."""
    if original.count(MARKER) != 1:
        raise SystemExit('original r13 marker count is not 1')
    at = original.index(MARKER)
    head, tail = original[:at], original[at:]
    if not (a_text.startswith(head) and a_text.endswith(tail)) or len(a_text) <= len(original):
        raise SystemExit("A's r13 is not the original with one insertion before the marker")
    return a_text[at:len(a_text) - len(tail)]


def _unqualify_imports(tree, private):
    """`from P import X as Y` -> `import X as Y`; `from P.X import n` -> `from X import n` (P the private package)."""
    import ast

    class Back(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level or not node.module:
                return node
            if node.module == private:
                return ast.copy_location(ast.Import([ast.alias(a.name, a.asname) for a in node.names]), node)
            if node.module.startswith(private + '.'):
                node.module = node.module[len(private) + 1:]
            return node
    return Back().visit(tree)


def _a_layout(a_dir, a_info, composed_root, manifest):
    """A's helper copies -> the composition path each one copies (str of resolved paths, as the helpers spell them)."""
    layout = {}
    for name, entry in sorted(a_info['copied_helpers'].items()):
        old = 'helpers/' + name
        if old not in manifest['modules']:
            continue
        source = Path(entry['source']).resolve()
        if source != (composed_root/'helpers'/name).resolve():
            raise SystemExit('HCF copied %s from outside the composition: %s' % (name, source))
        copy = (a_dir/'helpers'/name).resolve()
        if name != ISSUER and copy.read_bytes() != source.read_bytes():
            raise SystemExit("A's copy of %s differs from the composition" % name)
        layout[str(copy)] = str(source)
    if len(set(layout.values())) != len(layout):
        raise SystemExit('a_layout is not injective')
    return layout


def prepare_b(b_dir, fold_out, a_dir):
    import ast
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fold_r2 as FO
    b_dir, fold_out, a_dir = Path(b_dir), Path(fold_out), Path(a_dir)
    if b_dir.exists():
        raise SystemExit('B_DIR exists')
    a_arm, a_info = _json(a_dir/'arm.json'), _json(a_dir/'control.json')
    manifest = _json(fold_out/'MANIFEST.json')
    helper_names = {Path(old).stem for old in manifest['modules'] if old.startswith('helpers/')}
    h_tests = Path(a_info['paths'][2])
    clash = sorted(p.stem for p in h_tests.glob('*.py') if p.stem in helper_names)
    if clash:
        raise SystemExit('H tests hold files named like folded helpers (a bare import would load them): %s' % clash)
    layout = _a_layout(a_dir, a_info, Path(a_arm['composed_root']), manifest)
    # The folded tree, byte for byte, with the r13 insertion.
    folded = b_dir/'folded'
    shutil.copytree(fold_out/'folded', folded)
    for path in sorted(folded.rglob('*')):
        if path.is_file() and path.read_bytes() != (fold_out/'folded'/path.relative_to(folded)).read_bytes():
            raise SystemExit('copy differs: %s' % path)
    original_raw = Path(a_info['copied_helpers'][ISSUER]['source']).read_bytes()
    if _sha(original_raw) != a_arm['r13']['original_sha256']:
        raise SystemExit('the original r13 changed since prepare-a')
    original = original_raw.decode('utf8')
    a_r13 = (a_dir/'helpers'/ISSUER).read_bytes()
    if _sha(a_r13) != a_arm['r13']['patched_sha256']:
        raise SystemExit("A's r13 changed since prepare-a")
    inserted = _insertion(a_r13.decode('utf8'), original)
    r13_key = manifest['modules']['helpers/' + ISSUER]
    b_r13_path = folded/r13_key
    folded_r13_raw = b_r13_path.read_bytes()
    folded_r13 = folded_r13_raw.decode('utf8')
    if folded_r13.count(MARKER) != 1:
        raise SystemExit('folded r13 marker count is not 1')
    b_r13 = folded_r13.replace(MARKER, inserted + MARKER)
    b_r13_path.write_bytes(b_r13.encode('utf8'))
    diff = ''.join(difflib.unified_diff(folded_r13.splitlines(True), b_r13.splitlines(True),
                                        'folded/' + r13_key, 'B/' + r13_key))
    if sum(1 for line in diff.splitlines() if line.startswith('-') and not line.startswith('---')):
        raise SystemExit('the r13 diff removes lines')
    # The control with only its helper imports rewritten.
    control = Path(a_arm['control'])
    raw = control.read_bytes()
    if _sha(raw) != a_arm['control_sha256']:
        raise SystemExit('the control changed since prepare-a')
    src = FO.Source(CONTROL_NAME, raw)
    report = dict(bare_excluded=[], outside_scope=[])
    FO.rewrite_imports(src, CONTROL_NAME, helper_names, set(), helper_names, report)
    harness = src.result()
    back = _unqualify_imports(ast.parse(harness), FO.PRIVATE)
    if ast.dump(back) != ast.dump(ast.parse(raw)):
        raise SystemExit('the harness control differs from the original beyond its helper imports')
    (b_dir/'h').mkdir()
    _write_new(b_dir/'h'/(CONTROL_NAME + '.py'), harness)
    _write_new(b_dir/'r13-insertion.diff', diff)
    paths = [str(folded.resolve()), str(h_tests)]
    _write_new(b_dir/'control.json', json.dumps(dict(paths=paths, live_memory=a_info['live_memory'],
                                                     inventory_added_for_control=[], frozen=True), indent=1))
    b_manifest = json.loads(json.dumps(manifest))
    b_manifest['sha_map'][r13_key] = [_sha(a_r13), _sha(b_r13.encode('utf8'))]
    b_manifest['a_layout'] = layout
    _write_new(b_dir/'MANIFEST-h.json', json.dumps(b_manifest, indent=1, sort_keys=True))
    arm = dict(arm='B', control=str((b_dir/'h'/(CONTROL_NAME + '.py')).resolve()), control_sha256=_sha(harness),
               allowed=paths, cwd=str((b_dir/'h').resolve()), helper_names=sorted(helper_names),
               digest_roots=[str(b_dir.resolve())],
               package_parent=str(folded.resolve()), fold_out=str(fold_out.resolve()),
               manifest_sha256=_sha((fold_out/'MANIFEST.json').read_bytes()),
               manifest_h_sha256=_sha((b_dir/'MANIFEST-h.json').read_bytes()),
               inserted_sha256=_sha(inserted.encode('utf8')), harness_imports_rewritten=len(src.edits),
               outside_scope=report['outside_scope'],
               r13=dict(key=r13_key, original_sha256=a_arm['r13']['original_sha256'], a_sha256=_sha(a_r13),
                        folded_sha256=_sha(folded_r13_raw), b_sha256=_sha(b_r13.encode('utf8')),
                        diff_sha256=_sha(diff.encode('utf8')),
                        inserted_lines=inserted.count('\n')))
    _write_new(b_dir/'arm.json', json.dumps(arm, indent=1))
    print(json.dumps(dict(prepared='B', r13=arm['inserted_sha256'][:8], harness_edits=len(src.edits),
                          a_layout=len(layout), outside_scope=len(report['outside_scope']))))


# ------------------------------------------------------------------ child: hash tap
class _Journal:
    """Distinct (digest, preimage) pairs in order of first finalisation; preimages over a cap keep digest + length."""

    def __init__(self, out_dir):
        self.handle = open(out_dir/'journal.bin', 'xb')
        self.entries = {}
        self.written = 0
        self.over_stream = self.over_journal = 0

    def record(self, digest, parts, length, kept, frame):
        site = '%s:%s' % (frame.f_globals.get('__name__'), frame.f_code.co_qualname) if frame is not None else '?'
        entry = self.entries.get(digest)
        if entry is not None:
            entry['count'] += 1
            if len(entry['sites']) < 4 and site not in entry['sites']:
                entry['sites'].append(site)
            if entry['offset'] is not None or not kept:
                return
        else:
            entry = self.entries[digest] = dict(length=length, offset=None, count=1, sites=[site])
            if not kept:
                self.over_stream += 1
                return
        if self.written + length > JOURNAL_CAP:
            self.over_journal += 1
            return
        for part in parts:
            self.handle.write(part)
        entry['offset'] = self.written
        self.written += length

    def close(self, out_dir):
        self.handle.close()
        rows = [[digest, e['length'], e['offset'], e['count'], e['sites']] for digest, e in self.entries.items()]
        index = dict(schema='rm.fold.hash-journal.r1', entries=rows, stored_bytes=self.written,
                     over_stream_cap=self.over_stream, over_journal_cap=self.over_journal, stream_cap=STREAM_CAP,
                     journal_cap=JOURNAL_CAP, journal_sha256=_sha((out_dir/'journal.bin').read_bytes()))
        _write_new(out_dir/'journal.json', json.dumps(index, separators=(',', ':')))
        return dict(entries=len(rows), stored_bytes=self.written, over_stream_cap=self.over_stream,
                    over_journal_cap=self.over_journal)


def _tap(journal):
    """A sha256 constructor with the real one's results that hands each finalised stream to the journal."""
    real = _real_sha256

    class sha256:
        __slots__ = ('_h', '_parts', '_length', '_kept')
        name, digest_size, block_size = 'sha256', 32, 64

        def __init__(self, *args, **kwargs):
            self._h = real(*args, **kwargs)
            self._parts, self._length, self._kept = [], 0, True
            data = args[0] if args else kwargs.get('string', kwargs.get('data'))
            if data is not None:
                self._keep(data)

        def _keep(self, data):
            view = memoryview(data)
            self._length += view.nbytes
            if self._kept:
                if self._length > STREAM_CAP:
                    self._kept, self._parts = False, []
                else:
                    self._parts.append(view.tobytes())

        def update(self, data):
            self._h.update(data)
            self._keep(data)

        def digest(self):
            value = self._h.digest()
            journal.record(value.hex(), self._parts, self._length, self._kept, sys._getframe(1))
            return value

        def hexdigest(self):
            value = self._h.hexdigest()
            journal.record(value, self._parts, self._length, self._kept, sys._getframe(1))
            return value

        def copy(self):
            other = object.__new__(type(self))
            other._h, other._parts, other._length, other._kept = (self._h.copy(), list(self._parts), self._length,
                                                                  self._kept)
            return other
    return sha256


# ------------------------------------------------------------------ child: observers
def _small(value, depth=0):
    """A JSON form of booking inputs: ints, strings, paths and (nested) tables of them; anything else by type name."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        return value if len(value) <= 4096 else ['<str>', len(value)]
    if isinstance(value, PurePath):
        return ['<path>', str(value)]
    if depth < 3 and isinstance(value, dict) and len(value) <= 4096:
        return ['<dict>', [[_small(k, depth + 1), _small(v, depth + 1)] for k, v in value.items()]]
    if depth < 3 and isinstance(value, (list, tuple)) and len(value) <= 4096:
        return ['<seq>', [_small(v, depth + 1) for v in value]]
    return ['<%s>' % type(value).__name__]


def _snapshot(frame):
    names = {name: _small(value) for name, value in frame.f_locals.items()}
    glob = frame.f_globals
    tables = {name: _small(value) for name, value in list(glob.items())
              if name == 'HERE' or (TABLE.search(name) and isinstance(value, (dict, tuple, list, frozenset)))}
    return dict(locals=names, globals=tables, line=frame.f_lineno)


# ------------------------------------------------------------------ child: booking terms (revision 4)
def _term_str(value):
    if len(value) <= TERM_STRING_CAP:
        return value
    return ['<str>', len(value), _sha(value.encode('utf-8', 'surrogatepass'))]


def _rational_key(value):
    """[numerator, denominator] (signed, r7) of a Fraction or a gmpy2 mpq/mpz; None for anything else."""
    kind = type(value)
    if (kind.__module__, kind.__name__) == ('fractions', 'Fraction') or (
            kind.__module__.split('.')[0] == 'gmpy2' and kind.__name__ in ('mpq', 'mpz')):
        return [int(value.numerator), int(value.denominator)]
    return None


_LIMB_BITS = []


def _tight(value):
    """r7: the least getsizeof gmpy2 can report for an mpq or mpz: the type's __basicsize__ plus |numerator| and the
    denominator (an mpz: |value|) in whole limbs. gmpy2's __sizeof__ is the basic size plus the allocated limbs, and
    GMP allocates at least the limbs a value occupies; zero occupies none."""
    kind = type(value)
    if not _LIMB_BITS:
        _LIMB_BITS.append(int(sys.modules[kind.__module__.split('.')[0]].mp_limbsize()))
    bits = _LIMB_BITS[0]
    parts = (value.numerator, value.denominator) if kind.__name__ == 'mpq' else (value,)
    return kind.__basicsize__ + bits // 8 * sum((abs(int(part)).bit_length() + bits - 1) // bits for part in parts)


class _Rationals:
    """Per type name: count, getsizeof (or owned) bytes and the sorted (numerator, denominator) multiset; r7 adds the
    gmpy2 tight size sum and the count of values below their tight size (None for Fraction), and the distinct objects
    (by id; every caller walks objects the frame holds alive) with their size sum."""

    def __init__(self):
        self.rows = {}

    def add(self, value, size):
        key = _rational_key(value)
        if key is None:
            return False
        row = self.rows.setdefault(type(value).__name__, [0, 0, [], None, None, set(), 0])
        row[0] += 1
        row[1] += size
        row[2].append(key)
        if type(value).__module__.split('.')[0] == 'gmpy2':
            tight = _tight(value)
            row[3] = (row[3] or 0) + tight
            row[4] = (row[4] or 0) + int(sys.getsizeof(value) < tight)
        if id(value) not in row[5]:
            row[5].add(id(value))
            row[6] += size
        return True

    def table(self):
        return sorted([name, count, size, _sha(json.dumps(sorted(keys), separators=(',', ':')).encode('ascii')),
                       tight, below, len(ids), distinct_size]
                      for name, (count, size, keys, tight, below, ids, distinct_size) in self.rows.items())


def _walk(values):
    """A read-only mirror of the LOW ledger _footprint walk over each item of `values`: per type name objects,
    getsizeof bytes and largest getsizeof; the ndarray payload row (size, nbytes); the strings and the rationals."""
    census, strings, rationals = {}, [], _Rationals()

    def visit(value, depth=0):
        if depth > 16:
            raise ValueError('term walk deeper than _footprint allows')
        size = sys.getsizeof(value)
        row = census.setdefault(type(value).__name__, [0, 0, 0])
        row[0] += 1
        row[1] += size
        row[2] = max(row[2], size)
        rationals.add(value, size)
        if type(value) is str:
            strings.append(_term_str(value))
        elif type(value) is dict:
            for key, item in value.items():
                visit(key, depth + 1)
                visit(item, depth + 1)
        elif type(value) in (tuple, list):
            for item in value:
                visit(item, depth + 1)
        elif (type(value).__module__, type(value).__name__) == ('fractions', 'Fraction'):
            visit(value.numerator, depth + 1)
            visit(value.denominator, depth + 1)
        elif (type(value).__module__, type(value).__name__) == ('numpy', 'ndarray'):
            payload = census.setdefault('<ndarray payload>', [0, 0, 0])
            payload[0] += int(value.size)
            payload[1] += int(value.nbytes)
    for value in values:
        visit(value)
    return dict(census=sorted([name] + row for name, row in census.items()), strings=strings,
                rationals=rationals.table())


def _terms_inventory(frame):
    """endpoint_inventory_r3 / interval_inventory_r1 derive: the input_bytes sum term by term (their row, bounds and
    boundary loops), the key items' getsizeof census, the container sizes, the maxima behind `largest` and the
    rationals owned_bytes charges."""
    f = frame.f_locals
    rows, boundary, owned = f['rows'], f['boundary'], f['owned_bytes']
    keys = [key for row in rows for key in row['bounds']]
    census, rationals = {}, _Rationals()
    for key in keys:
        for item in key:
            name = '%s:%d' % (type(item).__name__, sys.getsizeof(item))
            census[name] = census.get(name, 0) + 1
    pairs = [owned(value) for row in rows for pair in row['bounds'].values() for value in pair]
    for row in rows:
        for pair in row['bounds'].values():
            for value in pair:
                rationals.add(value, owned(value))
    ends = [owned(entry[1]) for entry in boundary.values()]
    for entry in boundary.values():
        rationals.add(entry[1], owned(entry[1]))
    return dict(
        row_text=sum(2048+4*len(row['face_id'])+1024*len(row['ordered_keys']) for row in rows),
        key_items=sum(512+sum(sys.getsizeof(item) for item in key) for key in keys),
        key_census=sorted(census.items()),
        pairs=sum(pairs), pairs_max=max(pairs, default=0),
        boundary=sum(1024+4*len(key) for key in boundary)+sum(ends), boundary_max=max(ends, default=0),
        rationals=rationals.table(),
        rows_size=sys.getsizeof(rows), boundary_size=sys.getsizeof(boundary),
        witness_codec=f['witness_codec'], source_codec=f['source_codec'])


def _terms_low(frame):
    """low_ledger_inventory_r1._admit: the _footprint walk over the items of `values`."""
    return _walk(frame.f_locals['values'])


def _terms_low_plan(frame):
    """low_ledger_inventory_r1._plan: the inventory it returns, CONTAINER_UNIT, the owner count and getsizeof(target)."""
    f = frame.f_locals
    inventory = f['inventory']
    return dict(inventory=[inventory.input_bytes, inventory.work_bytes, inventory.result_bytes],
                unit=frame.f_globals['CONTAINER_UNIT'], owners=f['base']['owners'],
                target_size=sys.getsizeof(f['target']))


def _terms_finish_inventory(frame):
    """finish_inventory_r1.admit: the _footprint walk over (inspected, source_bindings, additional_bindings) and UNIT."""
    f = frame.f_locals
    return dict(_walk((f['inspected'], f['source_bindings'], f['additional_bindings'])),
                unit=frame.f_globals['UNIT'])


def _terms_forward(frame):
    """forward_kernel_r13._run: the geometry face-id terms of `amount` and RESIDUE."""
    face_ids = frame.f_locals['geometry']._face_ids
    return dict(face_count=len(face_ids), face_text=sum(len(fid) for fid in face_ids),
                residue=frame.f_globals['RESIDUE'])


def _terms_decimal(frame):
    """decimal_inventory_r1._derive: the scan totals and the strings its source-binding and witness scan charges."""
    f = frame.f_locals
    scan, system = f['scan'], f['system']
    return dict(scan_bytes=scan.bytes, metadata_bytes=scan.metadata_bytes,
                container_unit=frame.f_globals['CONTAINER_UNIT'],
                bindings=len(system.source_bindings),
                strings=[_term_str(value) for binding in system.source_bindings for value in binding],
                witness_json=_term_str(system.witness_json))


TERM_SITES = {
    ('private_heat_endpoint_inventory_r3', 'derive'): _terms_inventory,
    ('private_heat_interval_inventory_r1', 'derive'): _terms_inventory,
    ('private_heat_low_ledger_inventory_r1', '_admit'): _terms_low,
    ('private_heat_low_ledger_inventory_r1', '_plan'): _terms_low_plan,
    ('private_heat_finish_inventory_r1', 'admit'): _terms_finish_inventory,
    ('private_heat_forward_kernel_r13', '_run'): _terms_forward,
    ('private_heat_decimal_inventory_r1', '_derive'): _terms_decimal,
}


def _save_cell_keys(directory, caller):
    """r7: HCF's _save_cell_keys with physical_cell_id among the key fields: per cell of the heat result, in the
    result's own order, its mesh row's key fields, read from the control's child() frame (``old``, ``view``)."""
    local = caller.f_locals
    order = json.loads(local['old']._snapshot._metadata)['cell_ids']
    view, rows, mesh_order = local['view'], {}, []
    for index in range(view.cell_count):
        row = view.cell(index)
        value = row.value
        rows[value['cell_id']] = {key: value[key] for key in KEY_FIELDS if key in value}
        mesh_order.append(value['cell_id'])
        del row, value
    _write_new(directory/'cell_keys.json', json.dumps(dict(
        order='the heat result cell order (legacy metadata cell_ids)', mesh_row_order_equal=order == mesh_order,
        key_fields=list(KEY_FIELDS), cells=[rows[cell] for cell in order])))
    return len(order)


def _save_advance(directory, save, code, frame, value):
    """r7: HCF's array saver at the same return, the r13 issuer's module-level advance() returning to the control's
    child() (``frame`` is the returning frame). Arrays (exclusive creation), arrays.json and cell_keys.json go to
    DIRECTORY. An error is recorded and fails the child; it is never raised into the heat call."""
    if save['saved'] or save['error'] is not None:
        return sys.monitoring.DISABLE
    save['advance_returns'] += 1
    if value is None:
        return None
    try:
        import numpy as np
        if frame.f_code is not code:
            raise RuntimeError('the observed frame is not the returning advance()')
        caller = frame.f_back
        if caller is None or caller.f_code is not save['caller_code']:
            raise RuntimeError('advance() did not return to the control child()')
        names = list(value.array_names)
        if not names or len(set(names)) != len(names) or not all(ARRAY_NAME.fullmatch(name) for name in names):
            raise RuntimeError('array names missing, repeated or not plain: %r' % (names,))
        directory.mkdir()
        table = {}
        for name in names:
            array = np.array(value.array(name), copy=True)
            with open(directory/(name + '.npy'), 'xb') as handle:
                np.save(handle, array, allow_pickle=False)
            table[name] = dict(shape=list(array.shape), dtype=array.dtype.str,
                               sha256=_real_sha256(array.tobytes()).hexdigest())
        _write_new(directory/'arrays.json', json.dumps(table))
        save['cells'] = _save_cell_keys(directory, caller)
        save.update(saved=True, arrays=table)
    except Exception as error:
        save['error'] = '%s: %s' % (type(error).__name__, error)
    return sys.monitoring.DISABLE


def _save_problems(save, result):
    """r7: HCF's _save_check against the control's own array digests and cell count (empty: complete)."""
    problems = []
    if save['error'] is not None:
        problems.append('save: ' + save['error'])
    if not save['saved']:
        problems.append('save: the r13 advance() result was not saved (returns seen: %d)' % save['advance_returns'])
        return problems
    recorded = result.get('arrays')
    if type(recorded) is not dict or not recorded or set(recorded) != set(save['arrays']):
        problems.append('save: saved array names differ from the control result')
    else:
        problems += ['save: %s: saved SHA-256 differs from the control' % name for name in sorted(recorded)
                     if save['arrays'][name]['sha256'] != recorded[name]]
    if save['cells'] is None or save['cells'] != result.get('cell_count'):
        problems.append('save: cell keys for %r cells, the control has %r' % (save['cells'], result.get('cell_count')))
    return problems


def _observer(out_dir, state):
    monitoring = sys.monitoring
    tool = next((i for i in range(6) if i not in (3, 4) and monitoring.get_tool(i) is None), None)
    if tool is None:
        raise SystemExit('no free sys.monitoring tool id')

    def on_return(code, offset, value):
        state['events'] += 1
        name = Path(code.co_filename).name
        if name in CLOSED and code.co_qualname == 'closed_guard':
            state['closed_guard_returns'][name] = state['closed_guard_returns'].get(name, 0) + 1
            return None
        site = (name[:-3], code.co_qualname)
        if site in BOOKING_SITES:
            try:
                rows = state['bookings'].setdefault('%s:%s' % site, dict(calls=0, snapshots=[]))
                rows['calls'] += 1
                if len(rows['snapshots']) < SNAPSHOTS_PER_SITE:
                    frame = sys._getframe(1)
                    snap = _snapshot(frame)
                    if site in TERM_SITES:
                        snap['terms'] = TERM_SITES[site](frame)
                    if type(value) is int:
                        snap['returned'] = value
                    rows['snapshots'].append(snap)
            except Exception as error:
                state['booking_error'] = state['booking_error'] or 'booking %s: %s: %s' % (
                    site, type(error).__name__, error)
            return None
        if name == ISSUER and code.co_qualname == 'advance':
            return _save_advance(out_dir/'save', state['save'], code, sys._getframe(1), value)
        if name != ISSUER or code.co_qualname != 'advance_legacy_packaging':
            return monitoring.DISABLE
        if value is None:
            return None
        try:
            if state['saved']:
                raise RuntimeError('a second r12 packaging result')
            _write_new(out_dir/'metadata.json', bytes(value._snapshot._metadata))
            state['saved'] = True
        except Exception as error:
            state['error'] = '%s: %s' % (type(error).__name__, error)
        return None

    monitoring.use_tool_id(tool, TOOL_NAME)
    monitoring.register_callback(tool, monitoring.events.PY_RETURN, on_return)
    monitoring.set_events(tool, monitoring.events.PY_RETURN)
    monitoring.restart_events()

    def stop():
        monitoring.set_events(tool, 0)
        monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
        monitoring.free_tool_id(tool)
    return tool, stop


def _sites(frame):
    """The three innermost frames outside this file, as module:qualname:line."""
    sites = []
    while frame is not None and len(sites) < 3:
        if frame.f_code.co_filename != __file__:
            sites.append('%s:%s:%d' % (frame.f_globals.get('__name__'), frame.f_code.co_qualname, frame.f_lineno))
        frame = frame.f_back
    return sites


def _relative_kind(text, roots):
    """devnull; key (a package-relative key read against the cwd); inside (a relative spelling of an existing file in
    the layout or the environment, as numba and the certification kernel form one from an absolute path); outside."""
    if text == os.devnull:
        return 'devnull'
    if text.replace('\\', '/').split('/')[0] == 'atlas_tectonics':
        return 'key'
    real = Path(text).resolve()
    return 'inside' if real.exists() and any(real.is_relative_to(root) for root in roots) else 'outside'


def _audit(state):
    def hook(event, args):
        if not state['audit']:
            return
        if event in SPAWN_EVENTS:
            command = args[1] if event == 'subprocess.Popen' and len(args) > 1 else None
            worker = (isinstance(command, str) and command.endswith(' worker')
                      and WORKER_SCRIPT in command.rsplit(' ', 2)[-2])
            state['spawns'].append([event, repr(command if command is not None else args)[:400], worker])
        elif event in PATH_EVENTS and args:
            path = args[0]
            if isinstance(path, (str, bytes, os.PathLike)):
                try:
                    text = os.fsdecode(path)
                except Exception:
                    return
                if not os.path.isabs(text):
                    kind = _relative_kind(text, state['roots'])
                    rows = state['relative'].setdefault(kind, dict(count=0, examples=[]))
                    rows['count'] += 1
                    if len(rows['examples']) < EXAMPLES:
                        rows['examples'].append([event, text[:200], _sites(sys._getframe(1))])
    sys.addaudithook(hook)


def _digest_tree(roots):
    digest = _real_sha256()
    for root in roots:
        for path in sorted(item for item in Path(root).rglob('*') if item.is_file() and '__pycache__' not in item.parts):
            digest.update(('%s\0%s\0' % (path, _sha(path.read_bytes()))).encode('utf8'))
    return digest.hexdigest()


def _table_paths(module):
    """K6: absolute or user path strings inside a folded module's *SOURCES*/*PINS* globals (keys and values)."""
    hits = []

    def walk(value, where, depth):
        if isinstance(value, str):
            if ABSOLUTE.match(value) or USER_PATH.search(value):
                hits.append('%s.%s' % (module.__name__, where))
        elif depth < 4 and isinstance(value, dict):
            for key, item in value.items():
                walk(key, where + '{key}', depth + 1)
                walk(item, where + '[]', depth + 1)
        elif depth < 4 and isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                walk(item, where + '[]', depth + 1)
    for name, value in list(vars(module).items()):
        if TABLE.search(name) and not callable(value) and not isinstance(value, type(sys)):
            walk(value, name, 0)
    return hits


def _h3_sealed(module, private_dir):
    """The compiled-dot module CK loaded from the pinned bytes beside itself, with no qualified twin."""
    ck = sys.modules.get('%s.%s' % (PRIVATE, CK_NAME))
    path = private_dir/(H3_NAME + '.py')
    return (ck is not None and getattr(module, '__file__', None) == str(path) and path.is_file()
            and _sha(path.read_bytes()) == ck._H3_SHA256
            and getattr(module, '_H3_SEAL', None) == (str(path), ck._H3_SHA256)
            and '%s.%s' % (PRIVATE, H3_NAME) not in sys.modules)


def _b_checks(arm, problems):
    parent = Path(arm['package_parent'])
    private_dir = (parent/'atlas_tectonics'/'_private').resolve()
    k5 = dict(cwd=os.getcwd(), package_parent=str(parent), ok=Path(os.getcwd()).resolve() != parent.resolve())
    if not k5['ok']:
        problems.append('K5: cwd is the package parent')
    bare = set(arm['helper_names'])
    sealed = H3_NAME in sys.modules and _h3_sealed(sys.modules[H3_NAME], private_dir)
    top_level = sorted(name for name in list(sys.modules) if name.split('.')[0] in bare
                       and not (name == H3_NAME and sealed))
    if top_level:
        problems.append('helpers loaded at top level: %s' % top_level[:5])
    misnamed = []
    for name, module in list(sys.modules.items()):
        file = getattr(module, '__file__', None)
        if not file or Path(file).resolve().parent != private_dir:
            continue
        if (name != '%s.%s' % (PRIVATE, Path(file).stem) and not (name == H3_NAME and sealed)
                and not (name == PRIVATE and Path(file).name == '__init__.py')):
            misnamed.append(name)
    if misnamed:
        problems.append('modules from the private folder under other names: %s' % sorted(misnamed)[:5])
    k6 = sorted(hit for m in list(sys.modules.values()) if getattr(m, '__file__', None)
                and Path(m.__file__).resolve().is_relative_to(parent/'atlas_tectonics') for hit in _table_paths(m))
    if k6:
        problems.append('K6: absolute path strings in source tables: %s' % k6[:5])
    return dict(k5=k5, k6=k6, top_level_helpers=top_level, misnamed=misnamed,
                h3=dict(loaded=H3_NAME in sys.modules, sealed=sealed))


def _worker_h3_sealed(snapshot, private_dir):
    """_h3_sealed on a worker's exit snapshot."""
    facts, modules = snapshot.get('h3'), snapshot.get('modules', {})
    path = str(private_dir/(H3_NAME + '.py'))
    return (isinstance(facts, dict) and '%s.%s' % (PRIVATE, CK_NAME) in modules and facts.get('file') == path
            and facts.get('pin') is not None and facts.get('sha256') == facts['pin']
            and facts.get('seal') == [path, facts['pin']] and '%s.%s' % (PRIVATE, H3_NAME) not in modules)


def _workers(arm, obs, spawns, problems):
    """Decision 1 in every worker: each started worker left a load log (wobs/sitecustomize.py); in B no bare helper
    (but the sealed compiled-dot module) and no module from the private folder under another name (but the package
    and the worker script itself as __main__, or as __mp_main__, the alias multiprocessing gives it).

    The bare-name check covers every worker: the log names each module the import system looked for, written as it
    happens, so it holds for a worker the pool ends by force. A module put straight into sys.modules, and the file
    behind each name, are seen only in the exit snapshot, which a killed worker does not leave: there the
    private-folder name check is reported as not made (misnamed None), and the compiled-dot module counts as an
    unsealed bare helper, since its seal cannot be confirmed."""
    rows = []
    started = sum(1 for event, _, worker in spawns if event == 'subprocess.Popen' and worker)
    logs = sorted(obs.glob('w*.log'))
    if len(logs) != started:
        problems.append('worker observer: %d load logs for %d workers started' % (len(logs), started))
    private_dir = (Path(arm['package_parent'])/'atlas_tectonics'/'_private').resolve() if arm['arm'] == 'B' else None
    bare = set(arm.get('helper_names', ()))
    for log in logs:
        pid = log.stem[1:]
        snap_path = obs/('w%s.json' % pid)
        snapshot = _json(snap_path) if snap_path.is_file() else None
        lines = log.read_text(encoding='utf8').splitlines()
        if not lines or lines[0] != 's ' + pid:
            problems.append('worker observer: worker %s log does not start with the observer line' % pid)
        names = {line[2:] for line in lines if line[:2] in ('f ', 'i ')}
        row = dict(pid=int(pid), names=len(names), snapshot=snapshot is not None,
                   modules=None if snapshot is None else len(snapshot['modules']),
                   native=None if snapshot is None else snapshot.get('native'))   # r8
        if snapshot is not None and not snapshot.get('finder_first'):
            problems.append('worker observer: worker %s ended with the name finder no longer first' % pid)
        if private_dir is not None:
            modules = {} if snapshot is None else snapshot['modules']
            sealed = snapshot is not None and _worker_h3_sealed(snapshot, private_dir)
            top = sorted(name for name in names | set(modules) if name.split('.')[0] in bare
                         and not (name == H3_NAME and sealed))
            misnamed = None if snapshot is None else sorted(
                name for name, file in modules.items() if file and Path(file).resolve().parent == private_dir
                and name != '%s.%s' % (PRIVATE, Path(file).stem) and not (name == H3_NAME and sealed)
                and not (name == PRIVATE and Path(file).name == '__init__.py')
                and not (name in ('__main__', '__mp_main__') and Path(file).name == WORKER_SCRIPT))
            row.update(top_level_helpers=top, misnamed=misnamed, h3_sealed=sealed)
            if top:
                problems.append('decision 1: helpers loaded at top level in worker %s: %s' % (pid, top[:5]))
            if misnamed:
                problems.append('decision 1: private-folder modules under other names in worker %s: %s'
                                % (pid, misnamed[:5]))
        rows.append(row)
    return rows


def _gmp_record():
    """r7: the gmpy2 build this process loaded, read from sys.modules after the run; gmpy2 is never imported here."""
    gmpy2 = sys.modules.get('gmpy2')
    if gmpy2 is None:
        return dict(loaded=False)
    files = {name: _sha(Path(module.__file__).read_bytes()) for name, module in sorted(sys.modules.items())
             if (name == 'gmpy2' or name.startswith('gmpy2.')) and getattr(module, '__file__', None)}
    return dict(loaded=True, version=gmpy2.version(), mp_version=gmpy2.mp_version(), limb_bits=gmpy2.mp_limbsize(),
                basicsize=dict(mpq=gmpy2.mpq.__basicsize__, mpz=gmpy2.mpz.__basicsize__), module_sha256=files)


def _native_modules():
    """r8: {path: sha256} of each module this process has loaded whose file name starts libmpfr or libgmp."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)   # a private handle: no shared argtypes change
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32EnumProcessModules.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD))
    k32.K32EnumProcessModules.restype = wintypes.BOOL
    k32.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    k32.GetModuleFileNameW.restype = wintypes.DWORD
    process, size, needed = k32.GetCurrentProcess(), 1024, wintypes.DWORD()
    while True:
        handles = (wintypes.HMODULE * size)()
        if not k32.K32EnumProcessModules(process, handles, ctypes.sizeof(handles), ctypes.byref(needed)):
            raise OSError(ctypes.get_last_error(), 'K32EnumProcessModules')
        if needed.value <= ctypes.sizeof(handles):
            break
        size = needed.value // ctypes.sizeof(wintypes.HMODULE) + 64
    found, buffer = {}, ctypes.create_unicode_buffer(32768)
    for handle in handles[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        if not k32.GetModuleFileNameW(handle, buffer, len(buffer)):
            raise OSError(ctypes.get_last_error(), 'GetModuleFileNameW')
        if os.path.basename(buffer.value).lower().startswith(('libmpfr', 'libgmp')):
            found[buffer.value] = _sha(Path(buffer.value).read_bytes())
    return found


def _native_record():
    """r8 (RF2 condition c): the GMP and MPFR libraries this process loaded, and where RF2 expects MPFR."""
    record = dict(exec_prefix=sys.exec_prefix, expected_mpfr=os.path.join(
        sys.exec_prefix, 'Lib', 'site-packages', 'gmpy2.libs', 'libmpfr-6.dll'))
    try:
        record['modules'] = _native_modules()
    except Exception as error:   # recorded; v27/mpfr_same.py then fails this arm
        record['error'] = '%s: %s' % (type(error).__name__, str(error)[:300])
    return record


def child(layout, out_dir, reference=None):
    layout, out_dir = Path(layout).resolve(), Path(out_dir)
    arm = _json(layout/'arm.json')
    out_dir.mkdir(parents=True)
    os.chdir(arm['cwd'])
    allowed = [Path(p).resolve() for p in arm['allowed']]
    before = _digest_tree(arm['digest_roots'])
    control = Path(arm['control'])
    if _sha(control.read_bytes()) != arm['control_sha256']:
        raise SystemExit('the control changed')
    journal = _Journal(out_dir)
    import hashlib
    hashlib.sha256 = _tap(journal)   # before any helper or control import; this process only
    sys.path.append(str(control.parent))
    import importlib
    CONTROL = importlib.import_module(CONTROL_NAME)
    if Path(CONTROL.__file__).resolve() != control:
        raise SystemExit('the control loaded from %s' % CONTROL.__file__)
    env = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    state = dict(events=0, saved=False, error=None, booking_error=None, closed_guard_returns={}, bookings={},
                 audit=False, spawns=[],
                 relative={}, roots=allowed + env)
    state['save'] = dict(saved=False, error=None, arrays={}, cells=None, advance_returns=0,
                         caller_code=CONTROL.child.__code__)
    if 'PYTHONPATH' in os.environ or OBS_ENV in os.environ:
        raise SystemExit('PYTHONPATH or %s is already set; the worker observer would change it' % OBS_ENV)
    obs = out_dir/'workers'
    obs.mkdir()
    _audit(state)
    tool, stop = _observer(out_dir, state)
    problems, raised = [], None
    os.environ['PYTHONPATH'], os.environ[OBS_ENV] = str(OBS_DIR), str(obs.resolve())  # for workers only
    state['audit'] = True
    try:
        CONTROL.child(str(layout), str(out_dir/'control.json'))
    except BaseException as error:  # a refusal (IdentityError, a strict check) is reported, not swallowed
        if isinstance(error, KeyboardInterrupt):
            raise
        import traceback
        raised = dict(type=type(error).__name__, message=str(error)[:2000],
                      traceback=traceback.format_exc()[-4000:])
        problems.append('control raised %s: %s' % (raised['type'], raised['message'][:300]))
    finally:
        state['audit'] = False
        del os.environ['PYTHONPATH'], os.environ[OBS_ENV]
        stop()
        hashlib.sha256 = _real_sha256
    journal_info = journal.close(out_dir)
    _write_new(out_dir/'bookings.json', json.dumps(state['bookings'], indent=0, sort_keys=True))
    result = _json(out_dir/'control.json') if (out_dir/'control.json').is_file() else {}
    if raised is None and result.get('status') != 'PASS':
        problems.append('control status %s' % result.get('status'))
    if state['error'] or not state['saved']:
        problems.append('metadata not saved: %s' % state['error'])
    elif _sha((out_dir/'metadata.json').read_bytes()) != result.get('legacy', {}).get('metadata_sha256'):
        problems.append('saved metadata differs from the control digest')
    if state['booking_error']:
        problems.append('booking capture: %s' % state['booking_error'])
    problems += _save_problems(state['save'], result)
    if not sum(state['closed_guard_returns'].values()):
        problems.append('K4: closed_guard did not run')
    own = {Path(__file__).resolve(), control}
    leaks = sorted({str(Path(m.__file__).resolve()) for m in list(sys.modules.values())
                    if getattr(m, '__file__', None) and Path(m.__file__).resolve() not in own
                    and not any(Path(m.__file__).resolve().is_relative_to(root) for root in allowed + env)})
    if leaks:
        problems.append('loaded outside the layout: %s' % leaks[:5])
    after = _digest_tree(arm['digest_roots'])
    if before != after:
        problems.append('layout or inputs changed during the run')
    b = None
    workers = _workers(arm, obs, state['spawns'], problems)
    if arm['arm'] == 'B':
        b = _b_checks(arm, problems)
        other = [row for row in state['spawns'] if row[0] == 'subprocess.Popen' and not row[2]]
        if other:
            problems.append('decision 1: a process other than a heat worker was started in B: %s' % other[:2])
        for kind in ('key', 'outside'):
            if kind in state['relative']:
                problems.append('K5: relative path reads (%s) in B: %s' % (kind, state['relative'][kind]['examples'][:3]))
    if reference is not None:
        expected = _json(reference)
        if not expected.get('arrays') or result.get('arrays') != expected['arrays']:
            problems.append('arrays differ from the reference')
    if journal_info['over_journal_cap']:
        problems.append('hash journal over its cap: %d preimages not stored' % journal_info['over_journal_cap'])
    import psutil
    report = dict(arm=arm['arm'], layout=str(layout), status='FAIL' if problems else 'PASS', problems=problems,
                  raised=raised,
                  observer=dict(tool=tool, events=state['events'], saved=state['saved'],
                                closed_guard_returns=state['closed_guard_returns'],
                                booking_sites={k: v['calls'] for k, v in sorted(state['bookings'].items())}),
                  journal=journal_info, spawns=state['spawns'], relative_reads=state['relative'], workers=workers,
                  worker_observer_sha256=_sha((OBS_DIR/'sitecustomize.py').read_bytes()),
                  metadata_sha256=result.get('legacy', {}).get('metadata_sha256'),
                  result_id=result.get('legacy', {}).get('result_id'), arrays=result.get('arrays'),
                  leaks=leaks, inputs_sha256=before, b=b,
                  reference=None if reference is None else str(reference),
                  peak_working_set=getattr(psutil.Process().memory_info(), 'peak_wset', None),
                  control_seconds=result.get('elapsed_seconds'), gmp=_gmp_record(), native=_native_record(),
                  save={k: v for k, v in state['save'].items() if k != 'caller_code'})
    _write_new(out_dir/'arm.json', json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(dict(arm=arm['arm'], status=report['status'], problems=problems[:3],
                          metadata=str(report['metadata_sha256'])[:8], journal=journal_info['entries'],
                          closed_guard=state['closed_guard_returns'])), flush=True)
    return 0 if not problems else 1


def main(argv):
    if argv[:1] == ['prepare-a'] and len(argv) in (5, 6):
        prepare_a(*argv[1:])
    elif argv[:1] == ['prepare-b'] and len(argv) == 4:
        prepare_b(*argv[1:])
    elif argv[:1] == ['child'] and len(argv) in (3, 4):
        return child(*argv[1:])
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
