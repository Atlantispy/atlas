"""R1 fold parity: the exact booking rule (review r1 decision 5), proposed for R2 in place of FOLD.md F6's B <= A.

  python -B bookings.py A_LAYOUT A_OUT B_LAYOUT B_OUT MANIFEST_H [REPORT_JSON]

Revision r3 (23 Oct; FOLD.md §13 items 1-4) reads arms_r7 output. It changes the rationals rule only:
- Build record: each arm's child arm.json must carry the gmpy2 build record, and the two records must be equal
  (version, mp_version, limb size, basic sizes, module shas). A gmpy row fails on an arm whose record says gmpy2
  was not loaded, or whose limbs are not 64 bits.
- Value digest: the multiset of signed (numerator, denominator).
- Tight limbs: on each arm, no gmpy value may have a getsizeof below its tight size (arms_r7 counts them), and a
  row's size may not be below its tight sum. The two arms' tight sums must be equal, because they are a function of
  the values. Each arm's size minus its tight sum is reported as over-allocation, in limbs.
- Cap: one-sided. B - A may not exceed one limb per eight values. B smaller passes: the tight floor bounds it from
  below, and it carries no memory risk.
- Distinct objects: each row's distinct-object count is reported, not checked.
A row from an earlier observer (four columns) fails closed.

The inputs are one arms_r5 smoke or run: each arm's layout folder (arm.json), its child output folder (bookings.json
with revision 5 terms) and B's MANIFEST-h. Every site in SITES must be reached on both arms, with at least one
snapshot each. For every booking site and snapshot:

1. Each declared booking is recomputed on each arm from that arm's recorded locals and terms, by its source line, and
   must equal the recorded value ('full'). Where an input is opaque to the observer, either the equation is solved for
   it on each arm and the two solutions must agree ('solved'), or the B - A delta must equal the delta of the visible
   terms while the opaque inputs are shown equal ('delta').
2. Each term is put in B's space on both arms and must then be equal ('tie'): A paths through the manifest, A pins
   re-pinned, HERE as each arm's own private folder (so the len(str(HERE)) delta is exact), file sizes measured on
   each tree, and every source table's digest checked against the file it names. Declared exceptions, each with
   its own check: rationals, where gmpy2 reports allocated limbs and reuses freed objects, so equal values can
   differ in getsizeof by allocation history (the signed (numerator, denominator) multiset must be equal and a size
   difference must be whole 8-byte limbs, B up to one limb per eight values larger); 64-hex text that the manifest does
   not map, which must follow one substitution sigma, consistent and one-to-one over the whole run (the records
   check owns grounding each digest); and the wall-clock '"seconds":<float>' spans inside witness_json (the text
   with those spans and its 64-hex runs cut out must be equal, so only the seconds digits can change its length;
   the size is computed on each arm). A path -> digest table is tied as a multiset: every booking that reads a
   table sums over its entries, so its order cannot change a booking (the records check hashes tables and owns
   their order). Each table's order class is reported: 'same' (equal lists), 'keys' (sorted by its own keys on both
   arms) or 'other'. Every name the observer records as a table (*SOURCES*, *PINS*, *bindings) must be a path ->
   digest dict or None. A stage's component list is tied name by name; a component that reads paths has its own
   equation instead. The LOW ledger _plan snapshot is linked to its _admit snapshot (the same call), whose inputs
   were checked against the files.
3. Every other int or bool a snapshot holds must be equal on both arms. Ties and this rule compare type as well as
   value (True is not 1, 1 is not 1.0).

Any failure exits 1 naming the site, the snapshot and the rule. An unknown site, an opaque value where a rule needs
the value, or an unmapped absolute path fails closed. getsizeof is version-specific, so this runs on CPython 3.12.
"""
from collections import Counter
from hashlib import sha256
import json
import ntpath
import re
import sys
from pathlib import Path

HEX64 = re.compile(r'^(sha256:)?([0-9a-f]{64})$')
HEX64_IN = re.compile(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])')
SECONDS = re.compile(r'"seconds":\s*-?(?:\d+\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)(?=[,}\]\s])')
ESCAPES = '"\\\b\f\n\r\t'
GMPY = ('mpq', 'mpz')


class BookingError(AssertionError):
    pass


def _is_abs(text):
    return isinstance(text, str) and (bool(ntpath.splitdrive(text)[0]) or text.startswith(('\\\\', '/')))


def _norm(text):
    return ntpath.normcase(ntpath.normpath(text))


# ------------------------------------------------------------------ tagged snapshot values (arms _small)
def _tag(value):
    if isinstance(value, list) and value and isinstance(value[0], str) and value[0].startswith('<'):
        return value[0]
    return None


def val(value, where):
    """Tagged form -> plain value: <dict> -> list of [key, value] pairs, <seq> -> list, <path> -> str. A tag without
    its payload (an opaque object or an over-long string) raises: no rule may read it."""
    tag = _tag(value)
    if tag is None:
        return value
    if tag == '<dict>' and len(value) == 2:
        return [[val(k, where), val(v, where)] for k, v in value[1]]
    if tag == '<seq>' and len(value) == 2:
        return [val(v, where) for v in value[1]]
    if tag == '<path>' and len(value) == 2:
        return value[1]
    raise BookingError('%s: opaque value %s' % (where, tag))


class Env:
    """A snapshot's globals and locals, decoded on first use, so an opaque value fails only where a rule reads it."""

    def __init__(self, snap, where):
        self.raw = dict(snap['globals'])
        self.raw.update(snap['locals'])
        self.where = where

    def __getitem__(self, name):
        if name not in self.raw:
            raise BookingError('%s: %s not in the snapshot' % (self.where, name))
        return val(self.raw[name], '%s %s' % (self.where, name))

    def length(self, name):
        """len() of a recorded container without decoding its items (they may be opaque)."""
        raw = self.raw.get(name)
        tag = _tag(raw)
        if tag in ('<dict>', '<seq>') and len(raw) == 2:
            return len(raw[1])
        if tag is None and isinstance(raw, (list, str)):
            return len(raw)
        raise BookingError('%s: no length for %s (%s)' % (self.where, name, tag))

    def ints(self):
        return {k: v for k, v in self.raw.items() if type(v) in (int, bool)}


def json_capacity(node, where):
    """integration_spatial_transport._json_encoding_capacity over a tagged value: (encoded, temporary)."""
    length = atoms = containers = entries = 0

    def string_size(text):
        size = 2
        for char in text:
            n = ord(char)
            size += 2 if char in ESCAPES else 6 if n < 32 or 126 < n <= 65535 else 12 if n > 65535 else 1
        return size

    def atom_size(atom, key=False):
        if isinstance(atom, str):
            return string_size(atom)
        if atom is None:
            size = 4
        elif isinstance(atom, bool):
            size = 4 if atom else 5
        elif isinstance(atom, int):
            size = max(1, (abs(atom).bit_length()*30103)//100000+1)+(atom < 0)
        else:
            raise BookingError('%s: JSON atom %r' % (where, atom))
        return size + (2 if key else 0)

    def visit(value):
        nonlocal length, atoms, containers, entries
        tag = _tag(value)
        if tag in ('<dict>', '<seq>') and len(value) == 2:
            items = value[1]
            containers += 1
            length += 2 + max(0, len(items)-1)
            if tag == '<dict>':
                entries += len(items)
                length += len(items)
                for key, child in items:
                    length += atom_size(val(key, where), key=True)
                    atoms += 1
                    visit(child)
            else:
                for child in items:
                    visit(child)
        elif tag == '<float>' and len(value) == 1:
            length += 32
            atoms += 1
        elif tag is not None:
            raise BookingError('%s: opaque JSON value %s' % (where, tag))
        else:
            length += atom_size(value)
            atoms += 1
    visit(node)
    return 64+length, 65536+3*length+96*atoms+192*containers+96*entries


def str_size(text, where):
    if not isinstance(text, str):
        raise BookingError('%s: string term not recorded in full (%r)' % (where, text[:2]))
    return sys.getsizeof(text)


# ------------------------------------------------------------------ the manifest's translation of A into B's space
class Translation:
    def __init__(self, manifest):
        key_map = manifest['key_map']
        self.paths, self.shas = {}, {}

        def put(table, old, new, what):
            if table.setdefault(old, new) != new:
                raise BookingError('manifest maps %s %s two ways' % (what, old))
        for a_copy, composed in manifest['a_layout'].items():
            put(self.paths, _norm(a_copy), key_map.get(composed, composed), 'path')
        for old, new in key_map.items():
            self.paths.setdefault(_norm(old), new)
        for key, row in manifest.get('f5_repins', {}).items():
            for spelling, digest in row['spellings'].items():
                put(self.paths, _norm(spelling), key, 'path')
                put(self.shas, digest, row['new'], 'sha')
        for key, (old, new) in manifest['sha_map'].items():
            put(self.shas, old, new, 'sha')

    def path(self, text, where):
        if not _is_abs(text):
            return text
        new = self.paths.get(_norm(text))
        if new is None or _is_abs(new):
            raise BookingError('%s: unmapped absolute path %s' % (where, text))
        return new

    def sha(self, text):
        match = HEX64.match(text) if isinstance(text, str) else None
        return text if not match else (match.group(1) or '') + self.shas.get(match.group(2), match.group(2))

    def string(self, text, where):
        return self.path(text, where) if _is_abs(text) else self.sha(text)


class Arm:
    """One arm's files: its private folder (HERE), how its table keys resolve, file sizes and digests."""

    def __init__(self, name, layout, out, translation):
        self.name = name
        self.layout = json.loads((layout/'arm.json').read_text(encoding='utf-8'))
        self.bookings = json.loads((out/'bookings.json').read_text(encoding='utf-8'))
        report = out/'arm.json'
        self.gmp = json.loads(report.read_text(encoding='utf-8')).get('gmp') if report.is_file() else None
        self.tr = translation
        if name == 'A':
            self.root, self.here = None, layout/'helpers'
        else:
            self.root = Path(self.layout['package_parent'])
            self.here = self.root/'atlas_tectonics'/'_private'
        self._sizes, self._digests = {}, {}

    def file(self, key, where, pinned=False):
        if pinned:
            if _is_abs(key) or '/' in key or '\\' in key:
                raise BookingError('%s: pin name %s is not a bare file name' % (where, key))
            return self.here/key
        if self.name == 'A':
            if not _is_abs(key):
                raise BookingError('%s: A source key %s is not absolute' % (where, key))
            return Path(key)
        if _is_abs(key):
            raise BookingError('%s: absolute path in B: %s' % (where, key))
        return self.root/key

    def size(self, key, where, pinned=False):
        path = self.file(key, where, pinned)
        if path not in self._sizes:
            self._sizes[path] = path.stat().st_size
        return self._sizes[path]

    def digest(self, path):
        if path not in self._digests:
            self._digests[path] = sha256(path.read_bytes()).hexdigest()
        return self._digests[path]

    def table(self, pairs, where, pinned=False):
        """A source table in B's space, after checking that every digest is its file's sha256."""
        out = []
        for key, digest in pairs:
            match = HEX64.match(digest) if isinstance(digest, str) else None
            if not (isinstance(key, str) and match):
                raise BookingError('%s: table entry %r is not path -> sha256' % (where, (key, digest)))
            path = self.file(key, where, pinned)
            if self.digest(path) != match.group(2):
                raise BookingError('%s: %s digest is not its file sha256 on %s' % (where, key, self.name))
            out.append([key if self.name == 'B' or pinned else self.tr.path(key, where),
                        digest if self.name == 'B' else self.tr.sha(digest)])
        return out

    def check_here(self, here, where):
        if _norm(here) != _norm(str(self.here)):
            raise BookingError('%s: HERE on %s is %s, not its private folder %s' % (where, self.name, here, self.here))
        return len(here)

    def strings(self, values, where):
        """A walk's strings in B's space: A paths and pins translated; B as recorded."""
        for value in values:
            str_size(value, where)
        return list(values) if self.name == 'B' else [self.tr.string(v, where) for v in values]


# ------------------------------------------------------------------ equations
class Eqs:
    """One arm's evaluation of one snapshot: equation results, tie values, solved unknowns and allocation rows."""

    def __init__(self, arm, where):
        self.arm, self.where = arm, where
        self.full, self.delta, self.solved, self.tie, self.alloc, self.strings = {}, {}, {}, {}, {}, {}
        self.covered = set()
        self.tables = {}
        self.hexes = []
        self.arm_raw = None   # set by evaluate: the snapshot's tagged value by name
        self.link = None      # set by evaluate: the linked site's snapshot (LINKS) on this arm, as an Env

    def table(self, name, pairs, pinned=False):
        """Tie a path -> digest table (or a list of them) in B's space as a multiset; keep its order for the report."""
        first = pairs[0] if pairs else None
        nested = isinstance(first, list) and not (len(first) == 2 and isinstance(first[0], str))
        sets = pairs if nested else [pairs]
        for j, table in enumerate(sets):
            label = '%s[%d]' % (name, j) if nested else name
            translated = self.arm.table(table, self.where, pinned)
            keys = [key for key, _ in table]
            self.tables[label] = (translated, keys == sorted(keys))
            self.tied(label, sorted(map(tuple, translated)))
        return sets

    def eq(self, name, recorded, computed):
        self.full[name] = (recorded, computed)
        self.covered.add(name)

    def by_delta(self, name, recorded, visible):
        self.delta[name] = (recorded, visible)
        self.covered.add(name)

    def solve(self, name, value):
        self.solved[name] = value

    def tied(self, name, value):
        self.tie[name] = value

    def walk(self, terms, name):
        """The _footprint mirror: (footprint, objects, largest) on this arm, with the census tied (str and gmpy2 rows
        by their own rules) and the strings put in B's space."""
        rows = {row[0]: row[1:] for row in terms['census']}
        footprint = sum(row[1] for row in rows.values())
        objects = sum(row[0] for row in rows.values())
        largest = max([row[2] for kind, row in rows.items() if kind != '<ndarray payload>'], default=0)
        strings = terms['strings']
        count, size, _ = rows.get('str', [0, 0, 0])
        if count != len(strings) or size != sum(str_size(s, self.where) for s in strings):
            raise BookingError('%s: %s str census is not its strings' % (self.where, name))
        self.strings[name] = self.arm.strings(strings, self.where)
        self.tied(name + ' str count', count)
        self.rationals(terms['rationals'], name, {k: rows[k] for k in rows if k in GMPY})
        self.tied(name + ' census', sorted([k] + r for k, r in rows.items() if k != 'str' and k not in GMPY))
        return footprint, objects, largest

    def rationals(self, table, name, census=None):
        for row in table:
            if len(row) != 8:
                raise BookingError('%s: %s rationals row has %d columns, not the 8 of arms_r7' % (self.where, name,
                                                                                                  len(row)))
            kind, count, size, digest, tight, below, distinct, distinct_size = row
            gmpy = kind in GMPY
            if census is not None and gmpy and census.get(kind, [None, None])[:2] != [count, size]:
                raise BookingError('%s: %s %s census is not its rationals' % (self.where, name, kind))
            if gmpy:
                gmp = self.arm.gmp or {}
                if gmp.get('loaded') is not True or gmp.get('limb_bits') != 64:
                    raise BookingError('%s: %s %s needs a loaded 64-bit-limb gmpy2 record, not %r' % (
                        self.where, name, kind, gmp))
                if type(tight) is not int or type(below) is not int:
                    raise BookingError('%s: %s %s has no tight record' % (self.where, name, kind))
                if below or size < tight:
                    raise BookingError('%s: %s %s: %d values below their tight size (size %d, tight %d)' % (
                        self.where, name, kind, below, size, tight))
            elif tight is not None or below is not None:
                raise BookingError('%s: %s %s is not gmpy2 but records a tight size' % (self.where, name, kind))
            self.alloc['%s %s' % (name, kind)] = (count, size, digest, gmpy, tight, distinct, distinct_size)
        for kind in (census or {}):
            if '%s %s' % (name, kind) not in self.alloc:
                raise BookingError('%s: %s census has %s values the rationals did not record' % (self.where, name, kind))


def _components(x, e, *own):
    """A stage's (name, value) components as a dict; tied A to B name by name, except the `own` components, which
    read paths and have their own equation (their place in the list is still tied)."""
    pairs = e['components']
    if any(not (isinstance(p, list) and len(p) == 2 and isinstance(p[0], str) and type(p[1]) is int) for p in pairs):
        raise BookingError('%s: components are not (name, int) pairs' % x.where)
    components = dict(pairs)
    if len(components) != len(pairs) or not set(own) <= set(components):
        raise BookingError('%s: repeated or missing component name' % x.where)
    x.tied('components', [[name, '<own equation>' if name in own else value] for name, value in pairs])
    return components


def site_issue(x, e, t, returned):
    maps = x.table('maps', e['maps'])
    face_ids = e['face_ids']
    x.tied('face ids', [len(face_ids), sum(len(f) for f in face_ids)])
    here = x.arm.check_here(e['HERE'], x.where)
    entries = [pair for m in maps for pair in m]
    paths = len(entries)
    text = sum(len(f) for f in face_ids) + sum(len(p)+len(d)+here for p, d in entries)
    largest = max(x.arm.size(p, x.where) for p, _ in entries)
    x.eq('paths', e['paths'], paths)
    x.eq('text', e['text'], text)
    x.eq('source_size', e['source_size'], largest)
    x.eq('fixed_bytes', e['fixed_bytes'], 1024*(192+48*e['n']+24*e['nf']+8*paths)+32*text+2*largest)


def site_orchestration(x, e, t, returned):
    maps = x.table('maps', e['maps'])
    paths = sum(len(m) for m in maps)
    text = sum(len(p)+len(d) for m in maps for p, d in m if isinstance(p, str) and isinstance(d, str))
    x.eq('paths', e['paths'], paths)
    x.eq('text', e['text'], text)
    x.eq('<returned>', returned, 262144+1024*(128+e['face_count']+8*paths)+8*text)


def site_forward(x, e, t, returned):
    sources = e['_SOURCES']
    x.table('_SOURCES', sources)
    capacity, boundary = e.length('capacity'), e.length('boundary')
    faces, face_text, residue = t['face_count'], t['face_text'], t['residue']
    x.tied('face terms', [capacity, boundary, faces, face_text, residue])
    x.eq('amount', e['amount'], 262144+1024*(16*capacity+8*faces+16*boundary+256)
         + 8*sum(len(p)+len(d) for p, d in sources)+8*face_text+8192+128*faces+residue)


def site_finish_inventory(x, e, t, returned):
    sets = x.table('binding_sets', e['binding_sets'])
    pins = e['PINS']
    x.table('PINS', pins, pinned=True)
    x.arm.check_here(e['HERE'], x.where)
    path_count = sum(len(s) for s in sets)+len(pins)
    largest_source = max(max((x.arm.size(p, x.where) for s in sets for p, _ in s), default=0),
                         max(x.arm.size(n, x.where, pinned=True) for n, _ in pins))
    x.eq('path_count', e['path_count'], path_count)
    x.eq('source_size', e['source_size'], largest_source)
    footprint, objects, largest = x.walk(t, 'footprint walk')
    x.eq('footprint', e['footprint'], footprint)
    x.eq('objects', e['objects'], objects)
    x.eq('_', e['_'], largest)
    unit = t['unit']
    x.tied('UNIT', unit)
    components = _components(x, e, 'source_read_and_binding_work')
    x.eq('component source_read_and_binding_work', components['source_read_and_binding_work'],
         2*largest_source+unit*(4*path_count+16))
    x.eq('work', e['work'], sum(components.values()))
    x.eq('retained', e['retained'], e['work']+e['chars']+unit*(objects+32))
    # R.native_workspace_allowance(8*max(1, scalar_storage), 4) is not recorded: scalar_storage stays an int that
    # must be equal on both arms, so the allowance cancels in the delta.
    x.by_delta('scan_bytes', e['scan_bytes'], unit*(objects+1)+2*largest_source)


def site_low(x, e, t, returned):
    sets = x.table('binding_sets', e['binding_sets'])
    x.table('_PINS', e['_PINS'], pinned=True)
    x.arm.check_here(e['HERE'], x.where)
    largest_source = max((x.arm.size(p, x.where) for s in sets for p, _ in s), default=0)
    x.eq('largest_source', e['largest_source'], largest_source)
    x.eq('binding_count', e['binding_count'], sum(len(s) for s in sets))
    footprint, objects, largest = x.walk(t, 'footprint walk')
    x.eq('footprint', e['footprint'], footprint)
    x.eq('objects', e['objects'], objects)
    x.eq('largest', e['largest'], largest)
    # native_workspace_allowance(8*max(1, largest), objects) and CONTAINER_UNIT*(objects+1) are not recorded: both
    # inputs must be equal on both arms, and the delta is then 2 x the largest-source delta.
    x.tied('allowance inputs', [objects, largest])
    x.by_delta('scan_bytes', e['scan_bytes'], 2*largest_source)


def site_low_plan(x, e, t, returned):
    """LOW ledger _plan: the inventory _admit reserves. Its path inputs come from the same call's _admit snapshot."""
    admit = x.link
    for name, admitted in (('largest_source', 'largest_source'), ('binding_count', 'binding_count'),
                           ('footprint', 'footprint'), ('object_count', 'objects')):
        x.eq(name, e[name], admit[admitted])
    stage, unit, n, count, owners = e['stage'], t['unit'], e['n'], e['count'], t['owners']
    for name, value in (('stage', stage), ('CONTAINER_UNIT', unit), ('owners', owners),
                        ('getsizeof(target)', t['target_size'])):
        x.tied(name, value)
    x.eq('source_work', e['source_work'], 2*e['largest_source']+unit*(3*e['binding_count']+4))
    components = _components(x, e, 'source_verification')
    x.eq('component source_verification', components['source_verification'], e['source_work'])
    if stage == 'initial':
        units = 32+18*n+8*count+5*owners+e['object_count']
        containers, result = 'containers_and_binary_snapshots', unit*(24+len(components))
    elif stage == 'ledger':
        units = 64+30*n+9*count+6*owners+4*e['binding_count']
        containers = 'containers_and_result_views'
        result = e['exact_slots']+e['public_slots']+unit*(64+20*n+8*count+6*owners)+4*t['target_size']
    else:
        raise BookingError('%s: unknown LOW stage %r' % (x.where, stage))
    x.eq('units', e['units'], units)
    x.eq('component ' + containers, components[containers], unit*units)
    x.eq('work', e['work'], sum(components.values()))
    x.eq('result_bytes', e['result_bytes'], result)
    input_bytes, work_bytes, result_bytes = t['inventory']
    x.eq('inventory input_bytes', input_bytes, max(1, e['footprint']))
    x.eq('inventory work_bytes', work_bytes, e['work'])
    x.eq('inventory result_bytes', result_bytes, e['result_bytes'])


def site_inventory(x, e, t, returned):
    sources = e['source_bindings']
    x.table('source_bindings', sources)
    source_bytes, source_codec = json_capacity(x.arm_raw('source_bindings'), x.where)
    x.eq('source_bytes', e['source_bytes'], source_bytes)
    x.eq('source_codec', e['source_codec'], source_codec)
    if t['source_codec'] != e['source_codec'] or t['witness_codec'] != e['witness_codec']:
        raise BookingError('%s: terms and locals disagree on the codec sizes' % x.where)
    for name in ('row_text', 'key_items', 'key_census', 'rows_size', 'boundary_size'):
        x.tied(name, t[name])
    x.rationals(t['rationals'], 'owned values')
    owned = sum(row[2] for row in t['rationals'])
    x.tied('owned bytes beyond the rationals', t['pairs']+t['boundary']-owned)
    rows, boundary, cells = e.length('rows'), e.length('boundary'), e['cells']
    x.eq('input_bytes', e['input_bytes'], t['row_text']+t['key_items']+t['pairs']+t['boundary']+t['witness_codec']
         + source_codec+t['rows_size']+t['boundary_size'])
    largest = max(2048, t['pairs_max'], t['boundary_max'])
    x.eq('largest', e['largest'], largest)
    x.eq('scan_bytes', e['scan_bytes'], (1 << 20)+2048*(e['owners']+cells+boundary)+16*largest)
    x.eq('codec', e['codec'], 2*(e['witness_codec']+source_codec)+4*(e['witness_bytes']+source_bytes))
    x.eq('containers', e['containers'], 2048*(e['weights']+e['owners']+cells+rows+boundary+1))
    x.eq('work', e['work'], e['scalar']+e['decimal']+e['containers']+e['retained_endpoint_bytes']+e['codec']
         + e['scan_bytes'])
    rest = (4096+2048*(2*rows+cells+boundary+len(sources))+1024*(e['weights']+cells)
            + 2*(e['witness_bytes']+source_bytes))
    if _tag(x.arm_raw('op')) in ('<dict>', '<seq>') and len(x.arm_raw('op')) == 2:
        x.eq('result', e['result'], rest+1024*e.length('op'))
        x.tied('len(op)', e.length('op'))
    else:
        # op is too large for the snapshot: solve result's equation for len(op) on each arm; the two must agree.
        ops, remainder = divmod(e['result']-rest, 1024)
        if remainder or ops < 0:
            raise BookingError('%s: result leaves no whole len(op) (%d)' % (x.where, e['result']-rest))
        x.solve('len(op)', ops)
        x.covered.add('result')


def _mask_witness(text, hexes):
    """witness_json's text with each '"seconds":<float>' span masked and its 64-hex runs cut out into `hexes`, in
    order. Everything else (spacing, key order, escapes, number spelling) stays and must be equal."""
    json.loads(text)
    masked = SECONDS.sub('"seconds":<seconds>', text)
    hexes.extend(HEX64_IN.findall(masked))
    return HEX64_IN.sub('#', masked)


def site_decimal(x, e, t, returned):
    strings = t['strings']
    if len(strings) != 2*t['bindings']:
        raise BookingError('%s: source binding strings are not pairs' % x.where)
    x.table('source_bindings', [list(pair) for pair in zip(strings[0::2], strings[1::2], strict=True)])
    witness = t['witness_json']
    str_size(witness, x.where)
    x.tied('witness_json masked', _mask_witness(witness, x.hexes))
    unit = t['container_unit']
    x.tied('CONTAINER_UNIT', unit)
    metadata, scan = t['metadata_bytes'], t['scan_bytes']
    x.tied('metadata beyond the binding and witness strings',
           metadata-sum(str_size(s, x.where) for s in strings)-str_size(witness, x.where))
    x.tied('scan beyond metadata', scan-metadata)
    components = _components(x, e)
    x.eq('input_bytes', e['input_bytes'], scan+unit*(6+len(components)+e.length('counts')))
    x.eq('work_bytes', e['work_bytes'], sum(components.values()))
    slot, n = e['generated_slot'], e['n']
    ledger = unit*(1+e['faces'])+e['owners']*(slot+sys.getsizeof('')+e['chars'])
    x.eq('ledger', e['ledger'], ledger)
    x.eq('result_bytes', e['result_bytes'], slot*n+8*n+2*ledger+unit*12+slot*(64+t['bindings'])+2*metadata
         + str_size(e['target'], x.where)+unit)


def site_tables_only(x, e, t, returned):
    return None


SITES = {
    'private_heat_finish_issue_owned_r4:issue': site_issue,
    'private_heat_finish_kernel_r11:_orchestration_bytes': site_orchestration,
    'private_heat_forward_kernel_r13:_run': site_forward,
    'private_heat_finish_inventory_r1:admit': site_finish_inventory,
    'private_heat_finish_inventory_r2:admit': site_tables_only,
    'private_heat_low_ledger_inventory_r1:_admit': site_low,
    'private_heat_low_ledger_inventory_r1:_plan': site_low_plan,
    'private_heat_endpoint_inventory_r3:derive': site_inventory,
    'private_heat_interval_inventory_r1:derive': site_inventory,
    'private_heat_decimal_inventory_r1:_derive': site_decimal,
}
# Every site must be reached: the control's call goes through all of them. (The observer also watches
# finish_inventory_r1._issue and finish_kernel_r10._orchestration_bytes, which this call does not reach; if one is
# ever reached it fails closed as a site without equations.)
REQUIRED = frozenset(SITES)
LINKS = {'private_heat_low_ledger_inventory_r1:_plan': 'private_heat_low_ledger_inventory_r1:_admit'}
TABLE_NAME = re.compile(r'SOURCES|PINS', re.IGNORECASE)   # arms_r5 TABLE, plus names ending in 'bindings'


def _strict(value):
    """A comparison key that tells True from 1 and 1 from 1.0."""
    return repr(value)


def evaluate(arm, site, snap, where, link=None):
    x = Eqs(arm, where)
    e = Env(snap, where)
    x.arm_raw = lambda name: e.raw[name]
    x.link = link
    SITES[site](x, e, snap.get('terms', {}), snap.get('returned'))
    # Every top-level path -> digest table is tied in B's space, whether or not an equation reads it; a recorded
    # table that is not a path -> digest dict (or None) fails closed.
    for name, raw in e.raw.items():
        if not (TABLE_NAME.search(name) or name.endswith('bindings')) or name in x.tables:
            continue
        if raw is None:
            x.tied(name, None)
        elif _tag(raw) == '<dict>' and len(raw) == 2:
            x.table(name, val(raw, where), pinned='PINS' in name.upper())
        else:
            raise BookingError('%s: table %s is not a path -> digest dict (%s)' % (where, name, _tag(raw) or raw))
    return x, e


class Sigma:
    """The run's one substitution of unmapped 64-hex text, A -> B. Pairs come from aligned text (witness_json, and
    residual strings whose text is equal once their 64-hex runs are cut out); it must be one-to-one; then every
    residual string must be the sigma image of its partner."""

    def __init__(self):
        self.pairs, self.residuals, self.map = [], [], {}

    def _put(self, where, old, new, problems):
        if self.map.setdefault(old, new) != new:
            problems.append('%s: digest %s maps to two digests (sigma not a function)' % (where, old[:12]))

    def close(self):
        problems = []
        for where, old, new in self.pairs:
            self._put(where, old, new, problems)
        for where, extra_a, extra_b in self.residuals:
            by_mask_a, by_mask_b = {}, {}
            for extra, by_mask in ((extra_a, by_mask_a), (extra_b, by_mask_b)):
                for text, count in extra.items():
                    by_mask.setdefault(HEX64_IN.sub('#', text), []).extend([text]*count)
            for mask in set(by_mask_a) | set(by_mask_b):
                group_a, group_b = by_mask_a.get(mask, []), by_mask_b.get(mask, [])
                if len(group_a) != len(group_b) or mask.count('#') == 0:
                    problems.append('%s strings differ beyond digests: A %s / B %s' % (
                        where, [t[:80] for t in group_a[:2]], [t[:80] for t in group_b[:2]]))
                elif len(group_a) == 1 and mask != '#':
                    for old, new in zip(HEX64_IN.findall(group_a[0]), HEX64_IN.findall(group_b[0]), strict=True):
                        self._put(where, old, new, problems)
        inverse = {}
        for old, new in self.map.items():
            if inverse.setdefault(new, old) != old:
                problems.append('sigma is not one-to-one: %s and %s both map to %s' % (inverse[new][:12], old[:12],
                                                                                       new[:12]))
        for where, extra_a, extra_b in self.residuals:
            image = Counter()
            for text, count in extra_a.items():
                image[HEX64_IN.sub(lambda m: self.map.get(m.group(0), '?' * 64), text)] += count
            if image != extra_b:
                problems.append('%s strings are not the sigma image of A: %d unexplained' % (
                    where, sum((extra_b - image).values())))
        return problems


def compare(site, i, xa, ea, xb, eb, report, sigma):
    where = '%s #%d' % (site, i)
    problems = []
    for x in (xa, xb):
        for name, (recorded, computed) in x.full.items():
            if recorded != computed or type(recorded) is not type(computed):
                problems.append('%s %s: recorded %r, equation %r on %s' % (where, name, recorded, computed, x.arm.name))
    for name in sorted(set(xa.delta) | set(xb.delta)):
        (ra, va), (rb, vb) = xa.delta[name], xb.delta[name]
        if rb-ra != vb-va:
            problems.append('%s %s: delta %d, terms delta %d' % (where, name, rb-ra, vb-va))
    for kind in ('solved', 'tie'):
        a, b = getattr(xa, kind), getattr(xb, kind)
        for name in sorted(set(a) | set(b)):
            if name not in a or name not in b or _strict(a[name]) != _strict(b[name]):
                problems.append('%s %s %s differs: A %s / B %s' % (where, kind, name, str(a.get(name))[:160],
                                                                  str(b.get(name))[:160]))
    allocation, over = 0, []
    for name in sorted(set(xa.alloc) | set(xb.alloc)):
        if name not in xa.alloc or name not in xb.alloc:
            problems.append('%s rationals %s on one arm only' % (where, name))
            continue
        (ca, sa, da, gmpy, ta, na, _), (cb, sb, db, _, tb, nb, _) = xa.alloc[name], xb.alloc[name]
        if (ca, da) != (cb, db):
            problems.append('%s rationals %s: values differ (%d %s / %d %s)' % (where, name, ca, da[:8], cb, db[:8]))
        elif ta != tb:
            problems.append('%s rationals %s: tight sizes %s / %s differ for equal values' % (where, name, ta, tb))
        elif sa != sb and not (gmpy and (sb-sa) % 8 == 0):
            problems.append('%s rationals %s: size %d -> %d is not allocation in whole limbs' % (where, name, sa, sb))
        elif sb-sa > 8*-(-ca//8):
            # Allocation history moves a few limbs over many values (ar6: at most 0.07 limbs per value); more than
            # one limb per eight values is not history. One-sided (r3): B smaller is bounded by the tight floor.
            problems.append('%s rationals %s: size %d -> %d is more than one limb per eight of its %d values' % (
                where, name, sa, sb, ca))
        allocation += sb-sa
        if gmpy:
            over.append([name, ca, (sa-ta)//8, (sb-tb)//8, na, nb])
    residual = 0
    for name in sorted(set(xa.strings) | set(xb.strings)):
        extra_a = Counter(xa.strings.get(name, ())) - Counter(xb.strings.get(name, ()))
        extra_b = Counter(xb.strings.get(name, ())) - Counter(xa.strings.get(name, ()))
        sigma.residuals.append(('%s %s' % (where, name), extra_a, extra_b))
        residual += sum(extra_a.values())
    if len(xa.hexes) != len(xb.hexes):
        problems.append('%s witness_json digests %d / %d' % (where, len(xa.hexes), len(xb.hexes)))
    else:
        sigma.pairs.extend(('%s witness_json' % where, ha, hb) for ha, hb in zip(xa.hexes, xb.hexes, strict=True))
    orders = Counter()
    for name in sorted(set(xa.tables) & set(xb.tables)):
        (ta, sorted_a), (tb, sorted_b) = xa.tables[name], xb.tables[name]
        orders['same' if ta == tb else 'keys' if sorted_a and sorted_b else 'other'] += 1
    ia, ib = ea.ints(), eb.ints()
    for name in sorted((set(ia) | set(ib)) - xa.covered - xb.covered):
        if _strict(ia.get(name, '<absent>')) != _strict(ib.get(name, '<absent>')):
            problems.append('%s int %s differs with no equation: %r -> %r' % (where, name, ia.get(name),
                                                                              ib.get(name)))
    report.append(dict(site=site, snapshot=i, full=len(xa.full)+len(xb.full), delta=len(xa.delta), over_limbs=over,
                       solved=len(xa.solved), ties=len(xa.tie), rationals=len(xa.alloc), allocation_bytes=allocation,
                       digest_strings=residual, ints=len(ia), table_order=dict(orders), problems=problems))
    return problems


def check(a_layout, a_out, b_layout, b_out, manifest):
    if sys.version_info[:2] != (3, 12):
        raise BookingError('getsizeof rules are for CPython 3.12, not %s' % sys.version.split()[0])
    translation = Translation(manifest)
    a = Arm('A', a_layout, a_out, translation)
    b = Arm('B', b_layout, b_out, translation)
    if a.gmp is None or b.gmp is None:
        raise BookingError('an arm has no gmpy2 build record (arms_r7 writes it to the child arm.json)')
    if a.gmp != b.gmp:
        raise BookingError('the arms loaded different gmpy2 builds: %s / %s' % (a.gmp, b.gmp))
    if set(a.bookings) != set(b.bookings):
        raise BookingError('booking sites differ: %s' % sorted(set(a.bookings) ^ set(b.bookings)))
    unknown = sorted(set(a.bookings) - set(SITES))
    if unknown:
        raise BookingError('no booking equations for %s' % unknown)
    missing = sorted(REQUIRED - set(a.bookings))
    if missing:
        raise BookingError('required booking sites not reached: %s' % missing)
    report, problems, sigma = [], [], Sigma()
    for site in sorted(a.bookings):
        ra, rb = a.bookings[site], b.bookings[site]
        if ra['calls'] != rb['calls'] or len(ra['snapshots']) != len(rb['snapshots']) or not ra['snapshots']:
            raise BookingError('%s: calls %d / %d, snapshots %d / %d' % (
                site, ra['calls'], rb['calls'], len(ra['snapshots']), len(rb['snapshots'])))
        if len(ra['snapshots']) < ra['calls']:
            problems.append('%s: %d calls but only %d snapshots' % (site, ra['calls'], len(ra['snapshots'])))
        links = (None, None)
        if site in LINKS:
            la, lb = a.bookings[LINKS[site]], b.bookings[LINKS[site]]
            if not (la['calls'] == ra['calls'] == lb['calls'] and len(la['snapshots']) == len(ra['snapshots'])
                    == len(lb['snapshots'])):
                raise BookingError('%s: calls or snapshots differ from its linked %s' % (site, LINKS[site]))
            links = (la['snapshots'], lb['snapshots'])
        for i, (sa, sb) in enumerate(zip(ra['snapshots'], rb['snapshots'], strict=True)):
            where = '%s #%d' % (site, i)
            if sa['line'] != sb['line']:
                raise BookingError('%s: returned at line %s / %s' % (where, sa['line'], sb['line']))
            link_a, link_b = ((None, None) if links[0] is None else
                              (Env(links[0][i], where + ' A link'), Env(links[1][i], where + ' B link')))
            try:
                xa, ea = evaluate(a, site, sa, where + ' A', link_a)
                xb, eb = evaluate(b, site, sb, where + ' B', link_b)
            except (BookingError, KeyError, TypeError, ValueError, OSError) as error:
                problems.append('%s: %s: %s' % (where, type(error).__name__, error))
                continue
            problems += compare(site, i, xa, ea, xb, eb, report, sigma)
    problems += sigma.close()
    report.append(dict(sigma=sorted([old, new] for old, new in sigma.map.items()), gmp=a.gmp))
    return problems, report


def main(argv):
    if len(argv) not in (5, 6):
        print(__doc__)
        return 2
    a_layout, a_out, b_layout, b_out = map(Path, argv[:4])
    manifest = json.loads(Path(argv[4]).read_text(encoding='utf-8'))
    try:
        problems, report = check(a_layout, a_out, b_layout, b_out, manifest)
    except BookingError as error:
        problems, report = ['%s' % error], []
    for row in report:
        if 'sigma' in row:
            print('sigma: %d unmapped digests, one-to-one' % len(row['sigma']))
            print('gmpy2: %s' % json.dumps({k: v for k, v in (row['gmp'] or {}).items() if k != 'module_sha256'}))
            continue
        print('%-55s #%d full %2d delta %d solved %d ties %2d rationals %d alloc %+d digests %d %s' % (
            row['site'], row['snapshot'], row['full'], row['delta'], row['solved'], row['ties'], row['rationals'],
            row['allocation_bytes'], row['digest_strings'], 'ok' if not row['problems'] else 'FAIL')
            + ' over A/B %d/%d' % (sum(r[2] for r in row['over_limbs']), sum(r[3] for r in row['over_limbs']))
            + ' order %s' % ','.join('%s=%d' % kv for kv in sorted(row['table_order'].items())))
    for problem in problems:
        print('FAIL', problem)
    status = 'PASS' if not problems else 'FAIL'
    print(json.dumps(dict(status=status, snapshots=len(report)-1 if report else 0, problems=len(problems))))
    if len(argv) == 6:
        Path(argv[5]).write_text(json.dumps(dict(status=status, problems=problems, report=report), indent=1),
                                 encoding='utf-8')
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
