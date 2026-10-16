"""Stdlib-only exact source seams for compact partition workflow storage.

Importable without atlas_tectonics, so a composer can load it from authenticated
bytes. Each transform accepts exactly one pinned input digest, applies line-start
anchored seams that must each occur once, and refuses unless the output parses
and every statement outside the named functions is AST-identical to the input.
No file, loaded module or frozen source is edited here.
"""
import ast
from hashlib import sha256


# integration_regional_workflow after W.nonzero_cursor_source (ddb8d1b2 ->
# 61888439) and spatial_workflow_patch.transform (-> 26ebf01a).
WORKFLOW_INPUT_SHA256 = '26ebf01ad7c5ecbdb2170092b8899d6c174e9c0169641426ade69449ee48cdc7'
# integration_private_heat_cold after W.private_heat_cold_source (82d90e8f).
COLD_INPUT_SHA256 = 'd8a76d4d0287e8334dfe279b66ee91eb808dd1bf3bcc1ba13cae20ab935c50b4'
# Deterministic outputs, pinned so a composer can record exact stage digests.
# The cold output supersedes c1605caa, whose indexed branch handed the owning
# _RecordBytes metadata straight to resources r4 and so always refused.
WORKFLOW_OUTPUT_SHA256 = 'b81752611b3860b26666467227582c3decee1ef7a1e91e5977ea6b04133542f9'
COLD_OUTPUT_SHA256 = 'ed202b4b0834a0317cf644f7d5f9b68060bfe37408cfea7740bf3719cc569a7f'
MARKER = 'import partition_workflow_patch as _COMPACT_PARTITION\n'
WORKFLOW_FUNCTIONS = frozenset(('CollarWorkflow._partition_payload', 'CollarWorkflow._restore_partition',
    'CollarWorkflow._refresh', 'CollarWorkflow.advance_spatial', 'CollarWorkflow._publish', 'CollarWorkflow.open'))
COLD_FUNCTIONS = frozenset(('_restore_parent', 'restore_checkpoint'))


class PartitionWorkflowTransformRefused(ValueError):
    pass


def require(value, message):
    if not value:
        raise PartitionWorkflowTransformRefused(message)


_SPATIAL_IMPORT = 'import json\nimport spatial_workflow_patch as _COMPACT_SPATIAL\n'
_PUBLISH_CALL = ("                    header, partition_arrays = scratch.enter_context(self._partition_payload(\n"
                 "                        differential_partition, differential_interval, self._funding, self._collar, self._budget))\n")
WORKFLOW_SEAMS = (
    (_SPATIAL_IMPORT, _SPATIAL_IMPORT+MARKER),
    ('    def _partition_payload(cls, partition, geometry, funding, collar, budget):\n'
     '        """One immutable partition/support bundle; no per-cell certificate copies."""\n',
     '    def _partition_payload(cls, partition, geometry, funding, collar, budget, *, store=None,\n'
     '                           source_producer=None, cancel=None):\n'
     '        """One immutable partition/support bundle; no per-cell certificate copies."""\n'
     '        if store is not None:\n'
     '            with _COMPACT_PARTITION.payload(cls, partition, geometry, funding, collar, budget, store=store,\n'
     '                    source_producer=source_producer, cancel=cancel) as result:\n'
     '                yield result\n'
     '            return\n'),
    ('    def _restore_partition(cls, header, arrays, funding, collar, budget, *, interval=None):\n',
     '    def _restore_partition(cls, header, arrays, funding, collar, budget, *, interval=None, store=None):\n'
     "        if type(header) is dict and 'compact_partition' in header:\n"
     '            return _COMPACT_PARTITION.restore(cls, header, arrays, funding, collar, budget,\n'
     '                                              interval=interval, store=store)\n'),
    ("            partition, current_geometry = self._restore_partition(previous['differential_partition'], partition_arrays,\n"
     "                self._funding, self._collar, self._budget, interval=differential_interval)\n",
     "            partition, current_geometry = self._restore_partition(previous['differential_partition'], partition_arrays,\n"
     "                self._funding, self._collar, self._budget, interval=differential_interval, store=self._store)\n"),
    ("                p = partition.record()\n"
     "                if partition_binding != (partition.partition_id, p['parent_partition_id'],\n"
     "                                          _hash(p['support_ids']), partition.partition_id):\n",
     "                if partition_binding != _COMPACT_PARTITION.binding(partition, _hash):\n"),
    ("                    part['grid_id'] != self._differential_partition.record()['grid_id'] or\n",
     "                    part['grid_id'] != _COMPACT_PARTITION.field(self._differential_partition, 'grid_id').value or\n"),
    # Ordinary workflows keep their exact legacy call; only a migrated workflow's
    # successors publish one compact DAG root and alias its immutable chunks.
    (_PUBLISH_CALL,
     "                    if getattr(self, '_migration', None) is None:\n"
     + ''.join('    '+line for line in _PUBLISH_CALL.splitlines(keepends=True)) +
     "                    else:\n"
     "                        header, partition_arrays = scratch.enter_context(self._partition_payload(\n"
     "                            differential_partition, differential_interval, self._funding, self._collar, self._budget,\n"
     "                            store=self._store, source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))\n"),
    ("        arrays = _COMPACT_SPATIAL.workflow_arrays(self._store, previous['key'], budget=self._budget)\n"
     "        if arrays is None:\n"
     "            raise RegionalOwnerRefused('funded collar accepted payload is missing')\n",
     "        arrays = _COMPACT_PARTITION.workflow_arrays(self._store, previous['key'], budget=self._budget)\n"
     "        if arrays is None:\n"
     "            raise RegionalOwnerRefused('funded collar accepted payload is missing')\n"),
    ("                payload = _COMPACT_SPATIAL.workflow_arrays(store, root['key'], budget=budget)\n",
     "                payload = _COMPACT_PARTITION.workflow_arrays(store, root['key'], budget=budget)\n"),
)

_COLD_IMPORT = 'import private_heat_restored_binding_ram_recovery_r1 as B\n'
_COLD_MESH = ("        with R.decoded(spatial_state._snapshot._metadata, budget=budget, cancel=cancel) as endpoint:\n"
              "            mesh = B.ExteriorMesh.restore(endpoint.value['thermal_mesh'],\n"
              "                geometry_id=endpoint.value['thermal_mesh_id'], budget=budget)\n")
COLD_SEAMS = (
    (_COLD_IMPORT, _COLD_IMPORT+MARKER+'import spatial_indexed_patch as _COMPACT_INDEXED\n'),
    ("        payload = store.get(parent['key'], budget=budget)\n",
     "        payload = _COMPACT_PARTITION.workflow_arrays(store, parent['key'], budget=budget)\n"),
    ("                parent['exterior_state'], parent.get('exterior_advance'), records, budget) as (old, _unused):\n",
     "                parent['exterior_state'], parent.get('exterior_advance'), records, budget, store=store) as (old, _unused):\n"),
    (_COLD_MESH,
     "        if type(spatial_state._snapshot) is _COMPACT_INDEXED.IndexedSpatialSnapshot:\n"
     "            # The indexed endpoint keeps its sealed compact mesh beside small\n"
     "            # metadata; the expanded mesh record is never rebuilt to restore it.\n"
     "            # Resources r4 decodes exact bytes only, and indexed metadata is an\n"
     "            # owning bytes subclass: decode a plain copy charged before it\n"
     "            # exists. The reservation leaves with the copy; a held traceback\n"
     "            # keeps both (an entered, unexited reservation exits on collection).\n"
     "            endpoint_metadata = spatial_state._snapshot._metadata\n"
     "            endpoint_charge = budget.reserve(65536+len(endpoint_metadata),\n"
     "                                             category='private-cold-indexed-endpoint-metadata')\n"
     "            endpoint_charge.__enter__()\n"
     "            endpoint_metadata = bytes(endpoint_metadata)\n"
     "            with R.decoded(endpoint_metadata, budget=budget, cancel=cancel) as endpoint:\n"
     "                del endpoint_metadata\n"
     "                if 'thermal_mesh' in endpoint.value:\n"
     "                    raise ValueError('Indexed endpoint metadata must not carry an expanded thermal mesh')\n"
     "                view = spatial_state._snapshot._mesh\n"
     "                if not getattr(view, '_sealed', False) or view.budget is not budget:\n"
     "                    raise ValueError('Indexed endpoint mesh must be sealed on the workflow budget')\n"
     "                mesh = B.ExteriorMesh.from_compact(view, budget=budget)\n"
     "                if mesh.geometry_id != endpoint.value['thermal_mesh_id']:\n"
     "                    raise ValueError('Indexed endpoint mesh differs from its committed geometry ID')\n"
     "                del view\n"
     "            endpoint_charge.__exit__(None, None, None)\n"
     "            del endpoint_charge\n"
     "        else:\n"
     + ''.join('    '+line for line in _COLD_MESH.splitlines(keepends=True))),
)


def _once(source, old, new):
    # Line-start anchoring: an indented anchor must not match as the tail of a
    # more deeply indented line, and the complete anchor must be unique.
    require(source.count(old) == 1 and source.count('\n'+old) == 1,
            'compact partition workflow seam missing or ambiguous: '+old.strip()[:80])
    return source.replace(old, new, 1)


def _parse(source):
    try:
        return ast.parse(source)
    except SyntaxError as error:
        raise PartitionWorkflowTransformRefused('transformed source does not parse') from error


def functions(tree):
    """Qualified function name -> AST dump; duplicate qualified names refused."""
    result = {}
    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix+child.name
                if not isinstance(child, ast.ClassDef):
                    require(name not in result, 'ambiguous qualified function name: '+name)
                    result[name] = ast.dump(child, include_attributes=False)
                visit(child, name+'.')
            else:
                visit(child, prefix)
    visit(tree, '')
    return result


def skeleton(tree, names, imports=()):
    """Dump with named function bodies/signatures stubbed and named imports dropped."""
    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix+child.name
                if not isinstance(child, ast.ClassDef) and name in names:
                    child.args = ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
                                               kw_defaults=[], kwarg=None, defaults=[])
                    child.body = [ast.Pass()]
                    continue
                visit(child, name+'.')
            else:
                visit(child, prefix)
    visit(tree, '')
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Import) and
                 tuple((a.name, a.asname) for a in n.names) in imports)]
    return ast.dump(tree, include_attributes=False)


def _apply(source, expected, produced, seams, names, imports):
    require(type(source) is str and sha256(source.encode()).hexdigest() == expected and MARKER not in source,
            'exact reviewed input source required once')
    before = _parse(source)
    for old, new in seams:
        source = _once(source, old, new)
    after = _parse(source)
    a, b = functions(before), functions(after)
    require(set(a) == set(b) and {n for n in a if a[n] != b[n]} == names,
            'compact partition seams changed functions outside the reviewed set')
    require(skeleton(before, names) == skeleton(after, names, imports),
            'compact partition seams changed statements outside the reviewed functions')
    require(sha256(source.encode()).hexdigest() == produced, 'compact partition seams produced unreviewed output')
    return source


def transform(source):
    """Workflow seams after spatial_workflow_patch; ordinary publication unchanged."""
    return _apply(source, WORKFLOW_INPUT_SHA256, WORKFLOW_OUTPUT_SHA256, WORKFLOW_SEAMS, WORKFLOW_FUNCTIONS,
                  ((('partition_workflow_patch', '_COMPACT_PARTITION'),),))


def cold_source(source):
    """Cold reader seams after W.private_heat_cold_source; legacy mesh branch unchanged."""
    return _apply(source, COLD_INPUT_SHA256, COLD_OUTPUT_SHA256, COLD_SEAMS, COLD_FUNCTIONS,
                  ((('partition_workflow_patch', '_COMPACT_PARTITION'),),
                   (('spatial_indexed_patch', '_COMPACT_INDEXED'),)))


def transform_v2(source):
    """Both fresh and migrated branches use the explicit compact store seam.

    Applied only by a successor composer after transform(); frozen source and
    the old transform's pinned output are unchanged. WP5/WP8 supply the interval
    candidate/resolver at the surrounding workflow boundary.
    """
    require(type(source) is str and sha256(source.encode()).hexdigest() == WORKFLOW_OUTPUT_SHA256,
            'exact partition workflow v1 output required before v2 seam')
    before = _parse(source)
    old = next(new for anchor, new in WORKFLOW_SEAMS if anchor == _PUBLISH_CALL)
    new = ("                    header, partition_arrays = scratch.enter_context(self._partition_payload(\n"
           "                        differential_partition, differential_interval, self._funding, self._collar, self._budget,\n"
           "                        store=self._store, source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))\n")
    result = _once(source, old, new)
    after = _parse(result)
    allowed = frozenset(('CollarWorkflow._publish',))
    a, b = functions(before), functions(after)
    require(set(a) == set(b) and {name for name in a if a[name] != b[name]} == allowed and
            skeleton(before, allowed) == skeleton(after, allowed),
            'partition v2 seam changed outside publication')
    return result
