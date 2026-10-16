"""Optional bounded per-query geometry progress hooks (proposed Step 11 runner option).

Source transform of atlas_tectonics/integration_differential_geometry.py. Adds a
module-level sink `_GEOMETRY_PROGRESS = None` and guarded calls:
  - endpoint volume query start, every subdivision step, and issue;
  - wall and interface query start and issue (an early return is closed by the
    next start).
With the sink unset (the default) each call is one global None test: no record,
work charge, reservation or result changes (parity: byte-identical records).
It uses no sys.monitoring/trace/profile hook, so automatic worker selection is
not disabled, and nothing is monkey-patched at run time, so the loaded-source
fences keep holding. The runner installs a recorder from G/geometry_progress.py.
The diagnosis asked for: support, component, endpoint, depth/leaves,
lower/upper/witness and the unmet stopping condition of a slow query.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253': 'RC1 composed-r1 runtime-src',
}

SINK = '''
# Optional bounded progress recorder (runner option; None = off, no effect).
_GEOMETRY_PROGRESS = None


'''
ANCHOR_SINK = 'def _component_volume_bounds_decoded(support, logical_cell_id, record, arena, *,\n'

ANCHOR_START = ('    width = W._q(max_width_m3)\n'
                '    if width < 0 or type(max_leaves) is not int or max_leaves < 1:\n'
                "        raise V.VolumeError('explicit nonnegative volume error and positive leaf limit required')\n")
HOOK_START = ('    if _GEOMETRY_PROGRESS is not None:\n'
              "        _GEOMETRY_PROGRESS.start('endpoint', support.support_id, logical_cell_id, endpoint,\n"
              "                                 literals=len(component['constraints']))\n")

ANCHOR_STEP = '            _, _, parent, depth, lo, hi, mask = storage.pop(queue)\n'
HOOK_STEP = ('            if _GEOMETRY_PROGRESS is not None:\n'
             '                _GEOMETRY_PROGRESS.step(leaves, len(queue), low, high, witness, width, positive_witness)\n')

ANCHOR_END = ("        if len(poses) > 1:\n"
              "            # Present only when used, so every other record keeps its bytes.\n"
              "            result['whole_voxel_pose_levels'] = poses\n"
              "    return _issue(DifferentialMeasure, result, budget)\n")
HOOK_END = ("        if len(poses) > 1:\n"
            "            # Present only when used, so every other record keeps its bytes.\n"
            "            result['whole_voxel_pose_levels'] = poses\n"
            "        if _GEOMETRY_PROGRESS is not None:\n"
            "            _GEOMETRY_PROGRESS.end(result)\n"
            "    return _issue(DifferentialMeasure, result, budget)\n")

# Surface measures: start and issue hooks inside each function (no rebinding, so a
# loaded-source fence over this module keeps holding). Early returns (adopted
# worker results, screen-only) are closed by the next start.
ANCHOR_WALL = ("    record, component, layer, cell = _support_component(support, logical_cell_id, budget)\n"
               "    static = 'current_geometry_id' in record\n")
HOOK_WALL = ("    if _GEOMETRY_PROGRESS is not None:\n"
             "        _GEOMETRY_PROGRESS.start('wall', support.support_id, logical_cell_id, (axis, end))\n")
# (the same two lines also end an earlier function; the following def makes it unique)
ANCHOR_WALL_END = ("            result['query'] = 'spatial moments only; no rate acceptance criterion requested'\n"
                   "    return _issue(DifferentialMeasure, result, budget)\n"
                   "\n\ndef _moving_interface_leaf(")
HOOK_WALL_END = ("            result['query'] = 'spatial moments only; no rate acceptance criterion requested'\n"
                 "    if _GEOMETRY_PROGRESS is not None:\n"
                 "        _GEOMETRY_PROGRESS.end(result)\n"
                 "    return _issue(DifferentialMeasure, result, budget)\n"
                 "\n\ndef _moving_interface_leaf(")
ANCHOR_IFACE = ("    record, component, layer, cell = _support_component(support, logical_cell_id, budget)\n"
                "    _, widths = _query_inputs(layer, cell, max_width_m3, max_leaves, (), ())\n"
                "    sign = next((s for name, s in component['constraints'] if name == constraint_name), None)\n")
HOOK_IFACE = ("    if _GEOMETRY_PROGRESS is not None:\n"
              "        _GEOMETRY_PROGRESS.start('interface', support.support_id, logical_cell_id, constraint_name,\n"
              "                                 other=other_logical_cell_id)\n")
ANCHOR_IFACE_END = ("            result['moving_interface_moments'] = interface_moments\n"
                    "    return _issue(DifferentialMeasure, result, budget)\n")
HOOK_IFACE_END = ("            result['moving_interface_moments'] = interface_moments\n"
                  "    if _GEOMETRY_PROGRESS is not None:\n"
                  "        _GEOMETRY_PROGRESS.end(result)\n"
                  "    return _issue(DifferentialMeasure, result, budget)\n")


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('progress-hook anchor must occur exactly once: ' + old[:60])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    if '_GEOMETRY_PROGRESS' in source:
        raise ValueError('progress hooks already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('progress-hook input is not the reviewed geometry; pass allow_unreviewed_input and re-run parity')
    source = _once(source, ANCHOR_SINK, SINK.lstrip('\n') + ANCHOR_SINK)
    source = _once(source, ANCHOR_START, ANCHOR_START + HOOK_START)
    source = _once(source, ANCHOR_STEP, HOOK_STEP + ANCHOR_STEP)
    source = _once(source, ANCHOR_END, HOOK_END)
    source = _once(source, ANCHOR_WALL, ANCHOR_WALL + HOOK_WALL)
    source = _once(source, ANCHOR_WALL_END, HOOK_WALL_END)
    source = _once(source, ANCHOR_IFACE, ANCHOR_IFACE + HOOK_IFACE)
    source = _once(source, ANCHOR_IFACE_END, HOOK_IFACE_END)
    return source
