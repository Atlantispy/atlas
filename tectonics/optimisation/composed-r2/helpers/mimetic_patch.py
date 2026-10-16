"""Explicit native indexed metric entrypoint; no frozen runtime edits.

The exact validator is taken verbatim from the pinned native source. Only its
row access and retention are changed: one indexed row at a time, no canonical
whole-mesh copy. The native dictionary entrypoint remains byte-identical.
"""
from __future__ import annotations

import hashlib
import textwrap


MIMETIC_SHA256 = '4eb824b472c977d3c6b57693f966566f243f1a1d253472886a82b5b377bc1c94'
EXTREMUM_SHA256 = '9288970827dc90b37fa381f95fee01f1f5ef4aa98df0d6f641c26d26a7de2089'

_ROWS = '''class _CompactMetricRow:
    """One explicitly owned decoded row; never a whole-record substitute."""
    __slots__ = ('_owned',)

    def __init__(self, owned):
        self._owned = owned

    def __getitem__(self, key):
        return self._owned.value[key]

    def get(self, key, default=None):
        return self._owned.value.get(key, default)


class _CompactMetricRows:
    """A bounded row accessor, not an eagerly reconstructed metric record."""
    __slots__ = ('view', 'kind')

    def __init__(self, view, kind):
        self.view, self.kind = view, kind

    def __len__(self):
        return self.view.cell_count if self.kind == 'cell' else self.view.face_count

    def __getitem__(self, index):
        if type(index) is not int or not 0 <= index < len(self):
            raise IndexError(index)
        owned = self.view.cell(index) if self.kind == 'cell' else self.view.face(index)
        return _CompactMetricRow(owned)

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


'''

_ENTRY_PREFIX = '''    @classmethod
    def from_compact(cls, view, *, budget):
        """Validate indexed exact metrics without expanding source provenance.

        CompactMesh authenticates storage and canonical scientific identity;
        this entrypoint still performs every native metric/ownership check.
        Neither operation certifies physical coverage or a heat solution.
        """
        from mesh_tables import CompactMesh
        from .integration_spatial_transport import _workspace, _preserve_workspace
        if (cls is not MimeticGeometry or type(view) is not CompactMesh or
                not getattr(view, '_sealed', False) or type(budget) is not WorkBudget):
            raise TectonicsError('actual compact mesh and shared WorkBudget required')
        if view.budget is not budget:
            raise TectonicsError('compact thermal mesh belongs to a different budget')
        if not view.cell_count or not view.face_count:
            raise TectonicsError('empty thermal metric complex')
        face_rows = _CompactMetricRows(view, 'face')
        cell_rows = _CompactMetricRows(view, 'cell')
        # This bounded scan retains bit-width profiles, not a decoded copy of
        # geometry/support provenance. The original exact arithmetic capacity
        # calculation is reused with indexed sequences.
        metric_retained, metric_scratch = _metric_allocation_capacity(
            {'faces': face_rows, 'cells': cell_rows}, budget)
        self = object.__new__(cls)
        retained = ExitStack()
        committed = False
        try:
            if view.scope is not None:
                retained.callback(view._owner.retain().close)
            live = retained.enter_context(_ResizableLease(budget, category='mimetic-heat-retained'))
            live.resize(metric_retained+4096)
            with _workspace(budget, metric_scratch, 'mimetic-metric-validation'):
'''

_ENTRY_SUFFIX = '''                self._indexed = view
                self._encoded = None
                self._cells, self._incidence = tuple(decoded), tuple(map(tuple, incidence))
                self._face_ids, self._budget = tuple(faces), budget
                self.geometry_id = view.geometry_id
                del faces, centres, normals, incidence, keys, decoded
                del indexes, signs, offsets, vectors, distances
                del normal, centre, vector, offset, distance, volume
                weakref.finalize(self, retained.close)
                committed = True
                return self
        except BaseException as error:
            failure_owner = _preserve_workspace(error, retained)
            raise
        finally:
            if not committed:
                retained.close()

    def cell_id(self, index):
        """Failure diagnostics must not expand the entire indexed mesh."""
        indexed = getattr(self, '_indexed', None)
        if indexed is not None:
            owned = indexed.cell(index)
            return owned.value['cell_id']
        return self.record()['cells'][index]['cell_id']

    def legacy_record(self):
        """Explicit charged export; retain its owner while borrowing .value."""
        indexed = getattr(self, '_indexed', None)
        if indexed is None:
            raise TectonicsError('owned legacy export is specific to indexed geometry')
        return indexed.legacy_record()

'''


def _check(source, expected):
    if type(source) is not str or hashlib.sha256(source.encode()).hexdigest() != expected:
        raise ValueError('native metric source differs from the reviewed base')


def mimetic_source(source):
    _check(source, MIMETIC_SHA256)
    start = source.index('                faces, centres, normals = {}, [], []\n')
    end = source.index('                self._encoded, self._cells, self._incidence = ', start)
    validator = source[start:end]
    # All validation expressions, arithmetic order and refusal messages stay
    # verbatim. Only the explicit row source differs.
    validator = validator.replace("record['faces']", 'face_rows').replace("record['cells']", 'cell_rows')
    entry = _ENTRY_PREFIX+validator+_ENTRY_SUFFIX
    marker = '    def record(self):\n        return json.loads(self._encoded)\n'
    if source.count(marker) != 1:
        raise ValueError('native metric record seam is missing or ambiguous')
    source = source.replace('class MimeticGeometry:\n', _ROWS+'class MimeticGeometry:\n', 1)
    return source.replace(marker, entry+'''    def record(self):
        indexed = getattr(self, '_indexed', None)
        if indexed is not None:
            raise TectonicsError('indexed geometry requires direct rows or explicit owned legacy_record export')
        return json.loads(self._encoded)
''', 1)


def extremum_source(source):
    _check(source, EXTREMUM_SHA256)
    old = "geometry.record()['cells'][ci]['cell_id']"
    if source.count(old) != 1:
        raise ValueError('native extremum diagnostic seam differs')
    return source.replace(old, 'geometry.cell_id(ci)', 1)


def validator_ast(source, *, compact):
    """Expose the unchanged validation block for a focused AST parity check."""
    import ast
    tree = ast.parse(source)
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'MimeticGeometry')
    method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and
                  x.name == ('from_compact' if compact else '__init__'))
    attempt = next(x for x in method.body if isinstance(x, ast.Try))
    block = next(x for x in attempt.body if isinstance(x, ast.With))
    body = []
    for node in block.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == '_indexed' for t in node.targets):
            break
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Tuple) and any(
                isinstance(v, ast.Attribute) and v.attr == '_encoded' for v in t.elts) for t in node.targets):
            break
        body.append(node)
    text = ast.unparse(ast.Module(body=body, type_ignores=[]))
    if compact:
        text = text.replace('face_rows', "record['faces']").replace('cell_rows', "record['cells']")
    return ast.dump(ast.parse(textwrap.dedent(text)), include_attributes=False)
