"""r7 -> r8 text of the original joined-control helper (16 Oct 2026, G-R3-1 (b')).

r8_source() adds three derived-text edits for a compact, unpublished end thermal mesh:
- JC 408: the mesh is built with publish_mesh_patch.mesh_options(workflow, partition), the
  compact context {'scope': the workflow store's retained scope} over the proposal's supports
  (shared when compact, copied in memory when native; none for a store without a retained
  scope, so a native store keeps today's call);
- JC 428: the build is noted for run.json (publish_mesh_patch.note_end_mesh), and the required
  thermal boundary faces are read through the mesh's indexed columns
  (publish_mesh_patch.required_boundary_faces), since a compact mesh refuses record();
- the joint-advance failure capture takes publish_mesh_patch.failure_mesh_operand(mesh), so a
  compact mesh's capture records its identity instead of failing (failure-only).
CollarWorkflow._publish publishes the mesh after its partition (the publish_mesh_patch stage
of the composed workflow). Every anchor must occur exactly once.
R/private_heat_original_joined_r8.py is r8_source() of R/private_heat_original_joined_r7.py,
byte for byte.
"""

R7_TAIL = "snapshot keeps r6's exact decode branch. Nothing else differs from r6.\n\"\"\"\n"
R8_TAIL = ("snapshot keeps r6's exact decode branch. Nothing else differs from r6.\n"
           "R8 (16 Oct 2026, G-R3-1 (b')) adds three derived edits for a compact, unpublished end\n"
           "thermal mesh: it is built in the workflow store's retained scope over the proposal's\n"
           "compact supports (publish_mesh_patch.mesh_options), its required boundary faces are\n"
           "read by index, and its failure capture records its identity. CollarWorkflow._publish\n"
           "publishes it after its partition. A native store keeps the native mesh.\n\"\"\"\n")
END_MESH = ("            mesh = H.build_differential_mesh(funding, bounds, partition.supports, endpoint='end',\n"
            "                max_geometry_volume_error_m3=32*radius**3, max_leaves=thermal_max_leaves,\n"
            "                max_witness_refinements=thermal_witness_refinements,\n"
            "                closed_graph=solution.graph, budget=budget)\n")
COMPACT_END_MESH = ("            # (b') D1 at JC 408: compact and unpublished in the store's scope; _publish publishes it.\n"
                    "            import publish_mesh_patch as _PUBLISH_MESH\n"
                    "            mesh = H.build_differential_mesh(funding, bounds, partition.supports, endpoint='end',\n"
                    "                max_geometry_volume_error_m3=32*radius**3, max_leaves=thermal_max_leaves,\n"
                    "                max_witness_refinements=thermal_witness_refinements,\n"
                    "                closed_graph=solution.graph, budget=budget,\n"
                    "                **_PUBLISH_MESH.mesh_options(workflow, partition))\n")
BOUNDARY = "        boundary = {name: ('power', 0.) for name in mesh.record()['required_thermal_boundary_faces']}\n"
INDEXED_BOUNDARY = ("        _PUBLISH_MESH.note_end_mesh(partition, mesh, budget)\n"
                    "        boundary = {name: ('power', 0.) for name in\n"
                    "                    _PUBLISH_MESH.required_boundary_faces(mesh)}\n")
FAILURE = ("                    parts = dict(error=str(error), closed_graph=solution.graph.record, thermal_mesh=mesh.record)\n"
           "                    size = len(solution.graph._json)+len(mesh._json)\n")
COMPACT_FAILURE = ("                    mesh_part, mesh_bytes = _PUBLISH_MESH.failure_mesh_operand(mesh)\n"
                   "                    parts = dict(error=str(error), closed_graph=solution.graph.record, thermal_mesh=mesh_part)\n"
                   "                    size = len(solution.graph._json)+mesh_bytes\n")
MESH_EDITS = (('compact-unpublished-end-mesh', END_MESH, COMPACT_END_MESH),
              ('indexed-required-boundary-faces', BOUNDARY, INDEXED_BOUNDARY),
              ('compact-mesh-failure-capture', FAILURE, COMPACT_FAILURE))
OLD_JOIN = '_EDITS = _EDITS + _PARTITION_EDITS + _RESTART_EDITS\n'
NEW_JOIN = (f'_MESH_EDITS = {MESH_EDITS!r}\n'
            '_EDITS = _EDITS + _PARTITION_EDITS + _RESTART_EDITS + _MESH_EDITS\n')
REPLACEMENTS = (
    ('r8-note', R7_TAIL, R8_TAIL),
    ('mesh-edit', OLD_JOIN, NEW_JOIN),
    ('derivation-schema', "    return dict(schema='atlas.private.original-joined-derivation.r7',",
     "    return dict(schema='atlas.private.original-joined-derivation.r8',"),
    ('exec-tag', "str(_SOURCE)+'[private_heat_original_joined_r7]'", "str(_SOURCE)+'[private_heat_original_joined_r8]'"),
)


def r8_source(r7_text):
    """The exact r8 text; refuses unless every r7 anchor occurs exactly once."""
    if type(r7_text) is not str:
        raise TypeError('r7 helper text required')
    text = r7_text
    for label, before, after in REPLACEMENTS:
        if text.count(before) != 1:
            raise ValueError('joined helper r7 anchor missing or ambiguous: '+label)
        text = text.replace(before, after, 1)
    return text
