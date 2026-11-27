"""Exact text transform for compact-support routing of the derived continuation control.

Every anchor is a whole line that must START a line exactly once (found by an
overlapping scan, so an indented copy inside a deeper line is not a hit).
Ordinary (non-compact) statements stay verbatim inside an explicit branch. The
runtime helpers are in partition_routing_patch.
"""
from atlas_shared.errors import AtlasError


class CompactRoutingRefused(ValueError, AtlasError):
    pass


def require(test, message):
    if not test:
        raise CompactRoutingRefused(message)


def _once(source, old, new):
    """Replace the one whole-line anchor that starts a line; refuse 0 or 2+ hits."""
    require(type(source) is str and type(old) is str and type(new) is str and old.endswith('\n')
            and not old.startswith('\n') and new.endswith('\n'), 'whole-line anchor required: '+old[:80])
    hits, at = [], source.find(old)
    while at >= 0:
        # Overlapping scan: two adjacent identical lines are two hits.
        if at == 0 or source[at-1] == '\n':
            hits.append(at)
        at = source.find(old, at+1)
    require(len(hits) == 1, 'compact routing seam differs (%d line-start hits): %s' % (len(hits), old[:100]))
    return source[:hits[0]]+new+source[hits[0]+len(old):]


def continuation_control_source(source):
    """Edit the helper's derived control text, after its limit edits, before funding."""
    source = _once(source,
        '    geo, part, accepted = current.record(), partition.record(), prior.record()\n'
        '    material_state = spatial_state.record()\n',
        '    from atlas_tectonics._private.integration.geometry.partition_routing_patch import compact_continuation_state, continuation_records\n'
        '    if compact_continuation_state(partition, spatial_state):\n'
        '        # Same order: geometry, selected partition fields, interval, material record.\n'
        '        geo, part, accepted, material_state, _compact_owner = continuation_records(\n'
        '            current, partition, prior, spatial_state)\n'
        '    else:\n'
        '        geo, part, accepted = current.record(), partition.record(), prior.record()\n'
        '        material_state = spatial_state.record()\n')
    # Before the size sum: len(partition._json) and every support would be
    # evaluated outside the diagnostic try. The streamed capture owns its own.
    source = _once(source, '    from atlas_tectonics._private.integration.runtime_joined_control import _retain_failure\n',
        "    if getattr(partition, '_compact', None) is not None:\n"
        '        from atlas_tectonics._private.integration.geometry.partition_routing_patch import retain_compact_trace\n'
        '        return retain_compact_trace(number, partition, volume_map, arguments, budget, name=name, scope=scope)\n'
        '    from atlas_tectonics._private.integration.runtime_joined_control import _retain_failure\n')
    compile(source, 'i04_differential_continuation_control.py[compact-routing]', 'exec', dont_inherit=True)
    return source
