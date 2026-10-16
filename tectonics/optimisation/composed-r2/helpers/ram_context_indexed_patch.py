"""Stdlib-only indexed route for the frozen cold heat binding context.

The frozen I/ram private_heat_restored_binding_ram_context_r1 (cd729dc2) is the
_context of every cold heat reopen (ram_recovery_r1 re-exports it). For an
indexed successor it refuses at six points: the two spatial snapshot type
checks, both spatial metadata decodes (resources r4 admits exact bytes, the
indexed metadata is an owning bytes subclass), the whole-mesh JSON decode, the
expanded current['thermal_mesh'] comparison/read, and the retained-metric
rehash of an absent legacy encoding. Each gets an explicit indexed branch whose
ordinary branch is the original statement, verbatim; nothing else changes. The
indexed thermal rows answer the required-boundary list from the sealed face
references, so the unchanged plan check never sees a silently empty default.

The private heat bundle applies this BEFORE source-pin reconciliation, so the
ram_recovery pin and the cold reader's _BINDING_SHA follow the composed bytes.
No file, loaded module or frozen source is edited here.
"""
import ast
from hashlib import sha256


BASE_SHA256 = 'cd729dc216ede88ef22f46e38327ca8d2547f96990ea6de60d11cf7db926f428'
OUTPUT_SHA256 = '85c9ed5fa7cc0f3b32101b99edf16f4e949d4b2e38e7becdd3e03fbc4fa196b7'
NAME = 'private_heat_restored_binding_ram_context_r1.py'
CHANGED_FUNCTIONS = frozenset(('_context',))
IMPORTS = ((('spatial_indexed_patch', '_INDEXED_SPATIAL'),), (('private_heat_indexed_runtime', '_INDEXED_HEAT'),))


class RamContextIndexedRefused(ValueError):
    pass


def require(value, message):
    if not value:
        raise RamContextIndexedRefused(message)


_ROUTE = '''

class _IndexedCharge:
    """One reservation released only when its holder is dropped (held errors keep it)."""
    __slots__ = ('_guard',)

    def __init__(self, budget, size, category):
        self._guard = None
        guard = budget.reserve(size, category=category)
        guard.__enter__()
        self._guard = guard

    def __del__(self):
        guard, self._guard = self._guard, None
        if guard is not None:
            guard.__exit__(None, None, None)


def _indexed_spatial(snapshot, states):
    """Only the two spatial endpoint snapshots may be indexed; all others stay native."""
    return (type(snapshot) is _INDEXED_SPATIAL.IndexedSpatialSnapshot
            and any(snapshot is state._snapshot for state in states))


def _indexed_snapshot(snapshot, budget, cancel):
    # The issuer's indexed identity: the complete logical record streamed from
    # the owned metadata bytes and every byte of the sealed compact mesh.
    R.check(cancel)
    if snapshot._budget is not budget:
        raise ValueError('indexed snapshot has a foreign resource owner')
    if _INDEXED_SPATIAL.snapshot_identity(snapshot) != snapshot.result_id:
        raise ValueError('Restored native snapshot identity differs')


def _indexed_metadata_view(snapshot, budget, cancel):
    """r4 JSON view of indexed small metadata, decoded from an exact charged copy.

    Resources r4 admits exact ``bytes`` only, while indexed metadata is an
    owning bytes subclass. The copy is charged before it exists; a held
    traceback keeps both. The r4 view retains only the decoded value.
    """
    R.check(cancel)
    metadata = snapshot._metadata
    if not isinstance(metadata, bytes):
        raise TypeError('Owned indexed snapshot metadata bytes required')
    charge = _IndexedCharge(budget, 65536+len(metadata), 'private-cold-indexed-metadata')
    raw = bytes(metadata)
    view = R.decoded(raw, budget=budget, cancel=cancel)
    del raw, charge
    return view


class _IndexedThermal:
    """Bounded endpoint-mesh rows for the original checks; never an expanded record.

    Header fields come from one owned header decode, cells one owned row at a
    time, required boundary faces from the sealed integer face references.
    Other whole tables are refused rather than reported absent.
    """
    __slots__ = ('_mesh', '_rows', '_required')
    _WHOLE = frozenset(('faces', 'support_tables', 'grid_lines', 'thermal_shared_lines'))

    def __init__(self, mesh, budget):
        if type(mesh) is not ExteriorMesh or not mesh.is_compact or mesh._resource is not budget:
            raise TypeError('Actual same-budget compact endpoint mesh required')
        self._mesh, self._rows, self._required = mesh, _INDEXED_HEAT.mesh_rows(mesh), None

    def _faces(self):
        if self._required is None:
            view = _INDEXED_HEAT.stored_mesh(self._mesh)
            if not view._required:
                self._required = (None, None)
            else:
                indexes = view._arrays['required.face']
                charge = _IndexedCharge(view.budget, 65536+128*len(indexes), 'private-cold-indexed-required-faces')
                self._required = ([view.face_id(int(index)) for index in indexes], charge)
        return self._required[0]

    def __getitem__(self, name):
        if name == 'required_thermal_boundary_faces':
            faces = self._faces()
            if faces is None:
                raise KeyError(name)
            return faces
        if name in self._WHOLE:
            raise TypeError('Indexed endpoint mesh exposes rows, never a whole table: '+name)
        return self._rows[name]

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    def __contains__(self, name):
        if name == 'cells':
            return True
        if name == 'required_thermal_boundary_faces':
            return self._faces() is not None
        if name in self._WHOLE:
            raise TypeError('Indexed endpoint mesh exposes rows, never a whole table: '+name)
        return name in self._rows.header.value


def _indexed_endpoint_differs(mesh, thermal, current, owner, graph, exchange):
    # The original endpoint gates, read from owned header rows. Indexed metadata
    # binds the sealed mesh by its streamed logical ID and must not also carry
    # an expanded copy; the whole mesh record is never rebuilt to compare it.
    return (mesh.geometry_id != current['thermal_mesh_id'] or 'thermal_mesh' in current
            or thermal['funding_id'] != owner._funding.funding_id or thermal['funding_id'] != graph['funding_id']
            or thermal['grid_id'] != owner._definition['grid_id'] or thermal['grid_id'] != graph['grid_id']
            or thermal['support_id'] != graph['end_support_id']
            or thermal['trajectory_id'] != graph['trajectory_id'] or thermal['time_s'] != graph['end_time_s']
            or ('source' in thermal) != ('source' in graph) or thermal.get('source') != graph.get('source')
            or 'booked_cell_rule' in thermal and thermal['booked_cell_rule'].get('closed_graph_id') != exchange['spatial_graph_id'])


def _indexed_geometry(mesh, geometry, budget, cancel):
    """Indexed metric of the sealed endpoint mesh; a retained one is rehashed by streaming."""
    if geometry is None:
        return MimeticGeometry.from_compact(_INDEXED_HEAT.stored_mesh(mesh), budget=budget)
    if (type(geometry) is not MimeticGeometry or geometry._budget is not budget
            or _INDEXED_HEAT.metric_identity(geometry, cancel=cancel) != mesh.geometry_id):
        raise ValueError('Retained restored metric differs from actual endpoint')
    return geometry

'''
ROUTE_NAMES = frozenset(('_IndexedCharge', '_indexed_spatial', '_indexed_snapshot', '_indexed_metadata_view',
                         '_IndexedThermal', '_indexed_endpoint_differs', '_indexed_geometry'))


def _indent(text):
    return ''.join('    '+line if line.strip() else line for line in text.splitlines(keepends=True))


_IMPORT = 'from atlas_tectonics.reuse import ExecutionContext\n'
_SNAPSHOTS = ('    for snapshot in snapshots:\n'
              '        _snapshot(snapshot, budget, cancel)\n')
_PARENT = ('    parent_view = work.stack.enter_context(R.decoded(\n'
           '        parent_spatial_state._snapshot._metadata, budget=budget, cancel=cancel))\n')
_CURRENT = '    current = work.stack.enter_context(R.decoded(state._snapshot._metadata, budget=budget, cancel=cancel)).value\n'
_THERMAL = ('    thermal_view = work.stack.enter_context(R.decoded(mesh._json, budget=budget, cancel=cancel))\n'
            '    thermal = thermal_view.value\n')
_ENDPOINT = ("    if (mesh.geometry_id != current['thermal_mesh_id'] or thermal != current['thermal_mesh']\n"
             "            or thermal['funding_id'] != owner._funding.funding_id or thermal['funding_id'] != graph['funding_id']\n"
             "            or thermal['grid_id'] != owner._definition['grid_id'] or thermal['grid_id'] != graph['grid_id']\n"
             "            or thermal['support_id'] != graph['end_support_id']\n"
             "            or thermal['trajectory_id'] != graph['trajectory_id'] or thermal['time_s'] != graph['end_time_s']\n"
             "            or ('source' in thermal) != ('source' in graph) or thermal.get('source') != graph.get('source')\n"
             "            or 'booked_cell_rule' in thermal and thermal['booked_cell_rule'].get('closed_graph_id') != exchange['spatial_graph_id']):\n"
             "        raise ValueError('Restored physical mesh is not the actual transported endpoint')\n")
_ADOPT = ("    thermal = current['thermal_mesh']\n"
          '    thermal_view.close()\n')
_GEOMETRY = ('    if geometry is None:\n'
             '        geometry = MimeticGeometry(thermal, budget=budget)\n'
             '    elif (type(geometry) is not MimeticGeometry or geometry._budget is not budget\n'
             '          or sha256(geometry._encoded).hexdigest() != mesh.geometry_id):\n'
             "        raise ValueError('Retained restored metric differs from actual endpoint')\n")
SEAMS = (
    (_IMPORT, _IMPORT+'import spatial_indexed_patch as _INDEXED_SPATIAL\n'
              'import private_heat_indexed_runtime as _INDEXED_HEAT\n'),
    ('\n\ndef _context(owner, parent_spatial_state, parent_collar_state, state, collar_state,\n',
     _ROUTE+'\ndef _context(owner, parent_spatial_state, parent_collar_state, state, collar_state,\n'),
    (_SNAPSHOTS,
     '    for snapshot in snapshots:\n'
     '        if _indexed_spatial(snapshot, (parent_spatial_state, state)):\n'
     '            _indexed_snapshot(snapshot, budget, cancel)\n'
     '        else:\n'
     '            _snapshot(snapshot, budget, cancel)\n'),
    (_PARENT,
     '    if _indexed_spatial(parent_spatial_state._snapshot, (parent_spatial_state, state)):\n'
     '        parent_view = work.stack.enter_context(_indexed_metadata_view(\n'
     '            parent_spatial_state._snapshot, budget, cancel))\n'
     '    else:\n'+_indent(_PARENT)),
    (_CURRENT,
     '    if _indexed_spatial(state._snapshot, (parent_spatial_state, state)):\n'
     '        current = work.stack.enter_context(_indexed_metadata_view(state._snapshot, budget, cancel)).value\n'
     '    else:\n'+_indent(_CURRENT)),
    (_THERMAL,
     '    if mesh.is_compact:\n'
     '        thermal_view, thermal = None, _IndexedThermal(mesh, budget)\n'
     '    else:\n'+_indent(_THERMAL)),
    (_ENDPOINT,
     '    if mesh.is_compact:\n'
     '        if _indexed_endpoint_differs(mesh, thermal, current, owner, graph, exchange):\n'
     "            raise ValueError('Restored physical mesh is not the actual transported endpoint')\n"
     '    else:\n'+_indent(_ENDPOINT)),
    (_ADOPT,
     '    if not mesh.is_compact:\n'+_indent(_ADOPT)),
    (_GEOMETRY,
     '    if mesh.is_compact:\n'
     '        geometry = _indexed_geometry(mesh, geometry, budget, cancel)\n'
     '    else:\n'+_indent(_GEOMETRY)),
)


def _once(source, old, new):
    # Line-start anchored, counting overlapping occurrences: an indented anchor
    # must not match as the tail of a more deeply indented line.
    starts, at = 0, source.find(old)
    while at >= 0:
        starts += at == 0 or source[at-1] == '\n' or old.startswith('\n')
        at = source.find(old, at+1)
    require(source.count(old) == 1 and starts == 1,
            'cold binding context seam missing or ambiguous: '+old.strip()[:80])
    return source.replace(old, new, 1)


def _parse(source):
    try:
        return ast.parse(source)
    except SyntaxError as error:
        raise RamContextIndexedRefused('transformed cold binding context does not parse') from error


def _indexed_test(test):
    """'mesh.is_compact' or an _indexed_spatial(...) call; their branches are the additions."""
    return (isinstance(test, ast.Attribute) and test.attr == 'is_compact'
            and isinstance(test.value, ast.Name) and test.value.id == 'mesh'
            or isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and test.func.id == '_indexed_spatial')


class _Ordinary(ast.NodeTransformer):
    """Keep only the ordinary branch of every indexed selection."""
    def _keep(self, nodes):
        kept = []
        for child in nodes:
            value = self.visit(child)
            kept.extend(value if isinstance(value, list) else [value])
        return kept

    def visit_If(self, node):
        if _indexed_test(node.test):
            require(node.orelse, 'indexed selection without its ordinary branch')
            return self._keep(node.orelse)
        if (isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
                and _indexed_test(node.test.operand)):
            require(not node.orelse, 'indexed-only else branch is not reviewed')
            return self._keep(node.body)
        return self.generic_visit(node)


def ordinary(tree):
    """Module AST with the indexed route removed: imports, helpers and branches."""
    body = []
    for node in tree.body:
        if isinstance(node, ast.Import) and tuple((a.name, a.asname) for a in node.names) in IMPORTS:
            continue
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in ROUTE_NAMES:
            continue
        body.append(_Ordinary().visit(node) if isinstance(node, ast.FunctionDef) and node.name == '_context' else node)
    tree.body = body
    return ast.fix_missing_locations(tree)


def _functions(tree):
    return {node.name: ast.dump(node, include_attributes=False) for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


def transform(source):
    """Exact reviewed input once; ordinary statements stay AST-identical."""
    require(type(source) is str and sha256(source.encode()).hexdigest() == BASE_SHA256
            and '_INDEXED_SPATIAL' not in source, 'exact reviewed cold binding context required once')
    before = _parse(source)
    for old, new in SEAMS:
        source = _once(source, old, new)
    after = _parse(source)
    a, b = _functions(before), _functions(after)
    require(set(b)-set(a) == ROUTE_NAMES and set(a) <= set(b) and
            {n for n in a if a[n] != b[n]} == CHANGED_FUNCTIONS,
            'cold binding seams changed definitions outside the reviewed route')
    require(ast.dump(ordinary(after), include_attributes=False) == ast.dump(before, include_attributes=False),
            'cold binding seams changed ordinary statements')
    compile(source, NAME+'[indexed-route]', 'exec', dont_inherit=True)
    require(sha256(source.encode()).hexdigest() == OUTPUT_SHA256, 'cold binding seams produced unreviewed output')
    return source
