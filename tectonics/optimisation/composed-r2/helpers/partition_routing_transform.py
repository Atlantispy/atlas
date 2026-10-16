"""Exact text transforms for compact-support routing; standard library only.

Every native input is the frozen runtime-integration-r1 text, bound by its
SHA-256 over the decoded LF text. There is no newline normalisation: an
appended, CR-converted or already transformed input is a different text and is
refused. Every anchor is a whole line that must START a line exactly once
(found by an overlapping scan, so an indented copy inside a deeper line is
not a hit). Raw call sites are counted. Ordinary (non-compact) statements stay
verbatim inside an explicit branch: a native object takes no new decode or
reservation. The runtime helpers are in partition_routing_patch; this module
imports neither numpy nor atlas_tectonics, so a composer can authenticate and
apply it before any runtime exists.

Per-file order: routing first, then the endpoint-scheduler and ALE-checkpoint
transforms (their anchors are disjoint; the pin below refuses the reverse).
"""
import ast
from hashlib import sha256


BASES = {
    'integration_routing_views': 'bd2f65ad8218bab51d90a9df765a7f0368a702ee4d4caf1a37cefe1268e6eb40',
    'integration_differential_ale': '8c5de47212a73548ecba1f759d884851b62b9b94c3f5b14e27268e5cda898529',
    'integration_parallel_dispatch': '2b17c8d95f254b66c44e75cf9fde1d7ee2c67b03c5d286c95997d401d06a4bab',
    'integration_parallel_selection': 'b7b153d90003670b4d47179353a2d1d0fe8fa5ff060bf553deb502aaaa84a007',
    'integration_component_volume_auto': '5ade97ccca1afd5c933fb5993d7e3500b3efd64d6e3bf76906b84f024f94205c',
    'integration_differential_trace': 'df20e7f1eb9059ccbd6c1637a5f7b0f0eb88fe616f88aef367692fe0a8b272e7',
}
# H/private_heat_original_continuation_r1.py and its derived control text,
# _replace_exact(i04_differential_continuation_control.py 9bae6ed3..., _EDITS).
HELPER_SHA256 = 'b6d5a5117c64a3ca26fdfd6c37469171189bc92bf7304aa0b66adaddf6bb552a'
DERIVED_CONTROL_SHA256 = '02437356348f8eef5e98deb95744f895192483b83f8caf9ba5b2a26493e560c7'
# Every partition field each consumer reads (checked against the frozen uses).
ALE_FIELDS = ('scope', 'interval_id', 'funding_id', 'collar_plan_id', 'source', 'component_keys',
    'start_time_s', 'end_time_s', 'finite_owner_id', 'finite_state_id', 'grid_lines',
    'grid_origin_m', 'grid_basis', 'native_contacts', 'parent_partition_id', 'start_support_id',
    'end_support_id', 'trajectory', 'trajectory_id', 'prior_trajectory_id', 'grid_id',
    'support_ids', 'identity_start_cells')
TRACE_FIELDS = ('scope', 'interval_id', 'end_support_id', 'trajectory_id', 'trajectory',
    'endpoint_network_id', 'end_time_s', 'current_geometry_id', 'network_id', 'start_time_s',
    'source', 'volume_map_id', 'native_cells', 'support_ids', 'native_contacts', 'funding_id', 'grid_id')
COMPACT_CHANGES = ('compact-partition-selected-fields-and-indexed-material-record',
                   'compact-trace-inputs-streamed-without-whole-support-decode',
                   'original-funding-transfer-forwarded-to-both-pressure-calls')


class CompactRoutingRefused(ValueError):
    pass


def require(test, message):
    if not test:
        raise CompactRoutingRefused(message)


def _pinned(source, expected, label):
    require(type(source) is str and sha256(source.encode('utf8')).hexdigest() == expected,
            'unreviewed compact routing source: '+label)


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


def _calls(source, old, new, expected):
    """Every raw call of one exact callee, counted; never a tail of another name."""
    require(type(source) is str and old.endswith('(') and new.endswith('('), 'exact callee required: '+old)
    count, at = 0, source.find(old)
    while at >= 0:
        require(at == 0 or not (source[at-1].isalnum() or source[at-1] in '_.'),
                'call site is part of another name: '+old)
        count += 1
        at = source.find(old, at+1)
    require(count == expected, 'compact routing call sites differ (%d, expected %d): %s' % (count, expected, old))
    return source.replace(old, new)


def _span(source, name, cls):
    """Character span of the one undecorated def (module level or in one class)."""
    tree = ast.parse(source)
    scope = tree.body
    if cls is not None:
        owners = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls]
        require(len(owners) == 1, 'compact routing class seam differs: '+cls)
        scope = owners[0].body
    found = [n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    require(len(found) == 1 and not found[0].decorator_list, 'compact routing function seam differs: '+name)
    # AST lines are '\n' lines here (pinned inputs contain no CR); str.splitlines would differ.
    starts = [0]
    for line in source.split('\n'):
        starts.append(starts[-1]+len(line)+1)
    return starts[found[0].lineno-1], starts[found[0].end_lineno]


def _function(source, name, original, replacement, *, cls=None):
    """Replace one exact definition located by the AST; no added blank line."""
    start, end = _span(source, name, cls)
    require(source[start:end] == original and replacement.endswith('\n'),
            'compact routing function text differs: '+name)
    return source[:start]+replacement+source[end:]


def _within(source, name, old, new, *, cls=None):
    """A line-anchored exactly-once edit confined to one definition."""
    start, end = _span(source, name, cls)
    return source[:start]+_once(source[start:end], old, new)+source[end:]


def _routing_views(source):
    source = _once(source, '        view = self._views.project(support.record())\n',
        "        if getattr(support, '_compact_ref', None) is not None:\n"
        '            # Issued from a compact partition: retain DAG references and a handle.\n'
        '            from partition_routing_patch import project_compact\n'
        '            return project_compact(self, support)\n'
        '        view = self._views.project(support.record())\n')
    # After a refusal: no import and no reservation. A compact handle can only
    # exist once partition_routing_patch is loaded.
    return _once(source, '    def __getitem__(self, key):\n        if key not in self._diagnostics:\n',
        '    def __getitem__(self, key):\n'
        "        compact = sys.modules.get('partition_routing_patch')\n"
        '        if compact is not None and type(self._handles.get(key)) is compact.CompactSupport:\n'
        '            return compact.diagnostic(self, key)\n'
        '        if key not in self._diagnostics:\n')


def _ale(source):
    for indent in (' '*8, ' '*12):
        source = _once(source, indent+"constraint = row['constraints'][name]\n",
            indent+"constraint_owner = owned_constraint(row['constraints'][name])\n"+
            indent+'constraint = constraint_owner.value\n')
    source = _once(source, '                components[key] = support, row, part\n',
        '                components[key] = support_rows._handles[support.support_id], row, part\n')
    source = _calls(source, 'D.enclose_component_wall(', '_compact_wall(', 2)
    source = _calls(source, 'D.enclose_component_interface(', '_compact_interface(', 1)
    source = _once(source, '    p, step, original = partition.record(), interval.record(), funding.descriptor()\n',
        "    if getattr(partition, '_compact', None) is None:\n"
        '        p, step, original = partition.record(), interval.record(), funding.descriptor()\n'
        '    else:\n'
        '        # Only the fields read below, owned while borrowed; original call order.\n'
        '        from partition_native_patch import partition_fields as _partition_fields\n'
        '        partition_owner = _partition_fields(partition, '+repr(ALE_FIELDS)+')\n'
        '        p, step, original = partition_owner.value, interval.record(), funding.descriptor()\n')
    return source+('\nfrom partition_routing_patch import owned_constraint, wall as _compact_wall, '
                   'interface as _compact_interface\n')


def _auto(source):
    return _once(source, "            parts = row['components']\n",
        "            if getattr(support, '_compact_ref', None) is not None:\n"
        '                # Offer the small retained handle, not the temporary native support.\n'
        '                from partition_routing_patch import retain_support\n'
        '                support = retain_support(support)\n'
        "            parts = row['components']\n")


_ROLLING_FACTS = (
    '    def _facts(self, support):\n'
    '        """[support, its id, its transport weight once asked for] per distinct support of the pass."""\n'
    '        found = self.identities.get(id(support))\n'
    '        if found is None or found[0] is not support:\n'
    '            if len(self.identities) >= self.cached:\n'
    '                self.identities.clear()\n'
    '            found = self.identities[id(support)] = [support, support.support_id, False]\n'
    '        return found\n')


def _selection(source):
    head, body = _ROLLING_FACTS.split('        found = self.identities.get(id(support))\n')
    return _function(source, '_facts', _ROLLING_FACTS, head+
        "        if getattr(support, '_compact_ref', None) is not None:\n"
        '            # A temporary native support of a compact partition: keep its handle.\n'
        '            from partition_routing_patch import rolling_facts\n'
        '            return rolling_facts(self, support)\n'
        '        found = self.identities.get(id(support))\n'+body, cls='_Rolling')


_BATCH_FACTS = (
    '    def _support_facts(self, support):\n'
    '        """(support id, interval id, start, end, shippable) of one issued support, decoded once."""\n'
    '        held = self._facts.get(id(support))\n'
    '        if held is None or held[0] is not support:\n'
    '            if len(self._facts) >= 512:\n'
    '                self._facts.clear()\n'
    '            record = support.record()\n'
    "            held = self._facts[id(support)] = (support, (support.support_id, record['interval_id'],\n"
    "                record['start_time_s'], record['end_time_s'], transport(support) is not None))\n"
    '        return held[1]\n')


def _dispatch(source):
    source = _once(source, '    raw = support._json\n',
        '    if type(support) is CompactSupport:\n'
        '        return compact_transport(support, MAX_INPUT, PARENT_STORAGE)\n'
        '    raw = support._json\n')
    for name in ('_request', '_wall_request'):
        # Both factories read three header fields only.
        source = _within(source, name, '    record = support.record()\n',
            '    header_owner = support_header(support)\n    record = header_owner.value\n')
    head, body = _BATCH_FACTS.split('        held = self._facts.get(id(support))\n')
    source = _function(source, '_support_facts', _BATCH_FACTS, head+
        "        if type(support) is CompactSupport or getattr(support, '_compact_ref', None) is not None:\n"
        '            return batch_facts(self, support, transport)\n'
        '        held = self._facts.get(id(support))\n'+body, cls='BatchParallelSession')
    # transport() is these same size filters (its frozen docstring says so).
    source = _once(source, '                    raw = support._json\n'
        "                    other = pair.get('other_support')\n"
        '                    if len(raw) > MAX_INPUT or other is not None and len(other._json) > MAX_INPUT:\n'
        '                        continue\n'
        '                    buffers = (raw,) if other is None else (raw, other._json)\n'
        '                    if any(_decoded_json_capacity(data)+65536+4*len(data) > PARENT_STORAGE//4\n'
        '                           for data in buffers):\n',
        "                    other = pair.get('other_support')\n"
        '                    if transport(support) is None or other is not None and transport(other) is None:\n')
    source = _once(source, '                buffers = (support._json,) if other is None else (support._json, other._json)\n'
        '                # The size filters of the predictor route, unchanged.\n'
        '                if any(len(data) > MAX_INPUT or\n'
        '                       _decoded_json_capacity(data)+65536+4*len(data) > PARENT_STORAGE//4 for data in buffers):\n',
        '                # The size filters of the predictor route, unchanged: transport() is that predicate.\n'
        '                if transport(support) is None or other is not None and transport(other) is None:\n')
    source = _once(source, '            local = _support(support._json, support.support_id, scratch)\n',
        '            support, other = as_native(support), as_native(other)\n'
        '            local = _support(support._json, support.support_id, scratch)\n')
    source = _once(source, "                inputs = {'support': support._json}\n"
        '                if other is not None:\n'
        "                    inputs['other'] = other._json\n",
        '                inputs = InputMap(MAX_INPUT, PARENT_STORAGE)\n'
        "                inputs.add('support', support)\n"
        '                if other is not None:\n'
        "                    inputs.add('other', other)\n")
    source = _once(source, '        requests, inputs, size = [], {}, 0\n',
        '        requests, inputs, size = [], InputMap(MAX_INPUT, PARENT_STORAGE), 0\n')
    source = _once(source, '                    inputs[self._support_facts(item)[0]] = item._json\n'
        '                    size += len(item._json)\n',
        '                    identity = self._support_facts(item)[0]\n'
        '                    if type(item) is CompactSupport and size+item.encoded_size > MAX_BATCH_INPUT:\n'
        '                        # Refused before its exact copy is made or charged.\n'
        "                        raise ValueError('batch exceeds the optional transport envelope')\n"
        '                    inputs.add(identity, item)\n'
        '                    size += len(inputs[identity])\n')
    return source+('\nfrom partition_routing_patch import (CompactSupport, compact_transport, support_header,\n'
                   '    as_native, batch_facts, InputMap)\n')


def _trace(source):
    source = _once(source, '            partition = component_partition.record()\n',
        "            if getattr(component_partition, '_compact', None) is None:\n"
        '                partition = component_partition.record()\n'
        '            else:\n'
        '                # Only the fields this trace reads, owned while borrowed.\n'
        '                from partition_native_patch import partition_fields as _partition_fields\n'
        '                partition_owner = _partition_fields(component_partition, '+repr(TRACE_FIELDS)+')\n'
        '                partition = partition_owner.value\n')
    # retain_support returns a plain native support unchanged.
    source = _once(source, '            supports = {support.support_id: support for support in component_partition.supports}\n',
        '            supports = {support.support_id: _retain_support(support) for support in component_partition.supports}\n')
    source = _once(source, '                            source = support.record()\n',
        '                            if type(support) is _CompactSupport:\n'
        '                                # One owned decode; a held failure payload keeps its charge.\n'
        '                                support, source_owner = _as_native_with_record(support)\n'
        '                                source = _OwnedPayload(source_owner.value, source_owner)\n'
        '                            else:\n'
        '                                source = support.record()\n')
    return source+('\nfrom partition_routing_patch import (retain_support as _retain_support,\n'
                   '    CompactSupport as _CompactSupport, as_native_with_record as _as_native_with_record)\n'
                   'from .integration_routing_views import _OwnedPayload\n')


_EDITS = {
    'integration_routing_views': _routing_views,
    'integration_differential_ale': _ale,
    'integration_parallel_dispatch': _dispatch,
    'integration_parallel_selection': _selection,
    'integration_component_volume_auto': _auto,
    'integration_differential_trace': _trace,
}


def transform(name, source):
    """One authenticated frozen native module -> its compact-routing text."""
    require(type(name) is str and type(source) is str, 'module name and decoded source text required')
    name = name.removesuffix('.py')
    require(name in BASES, 'unreviewed compact routing module: '+name)
    _pinned(source, BASES[name], name)
    source = _EDITS[name](source)
    compile(source, name+'.py[compact-routing]', 'exec', dont_inherit=True)
    return source


def continuation_control_source(source):
    """Edit the helper's derived control text, after its limit edits, before funding."""
    _pinned(source, DERIVED_CONTROL_SHA256, 'derived continuation control')
    source = _once(source,
        '    geo, part, accepted = current.record(), partition.record(), prior.record()\n'
        '    material_state = spatial_state.record()\n',
        '    from partition_routing_patch import compact_continuation_state, continuation_records\n'
        '    if compact_continuation_state(partition, spatial_state):\n'
        '        # Same order: geometry, selected partition fields, interval, material record.\n'
        '        geo, part, accepted, material_state, _compact_owner = continuation_records(\n'
        '            current, partition, prior, spatial_state)\n'
        '    else:\n'
        '        geo, part, accepted = current.record(), partition.record(), prior.record()\n'
        '        material_state = spatial_state.record()\n')
    # Before the size sum: len(partition._json) and every support would be
    # evaluated outside the diagnostic try. The streamed capture owns its own.
    source = _once(source, '    from i04_differential_joined_control import _retain_failure\n',
        "    if getattr(partition, '_compact', None) is not None:\n"
        '        from partition_routing_patch import retain_compact_trace\n'
        '        return retain_compact_trace(number, partition, volume_map, arguments, budget, name=name, scope=scope)\n'
        '    from i04_differential_joined_control import _retain_failure\n')
    compile(source, 'i04_differential_continuation_control.py[compact-routing]', 'exec', dont_inherit=True)
    return source


def original_continuation_source(source):
    """The additive historical helper -> its compact/funding successor text.

    Only three exact lines change: the derivation's change list and scope,
    and the derived text, which becomes funding(compact(_EDITS(control))).
    The _SOURCE relocation belongs to the heat bundle's reference paths.
    """
    _pinned(source, HELPER_SHA256, 'original continuation helper')
    source = _once(source, '                changes=[label for label, _, _ in _EDITS],\n',
        '                changes=[label for label, _, _ in _EDITS]+'+repr(list(COMPACT_CHANGES))+',\n')
    source = _once(source,
        "                scope='work ceilings of the endpoint pressure forcing and of the current-state trace only')\n",
        "                scope='work ceilings of the endpoint pressure forcing and of the current-state trace; '\n"
        "                      'compact partition/material readers, streamed trace-input capture and the '\n"
        "                      'original funding transfer of both pressure calls (no physical change)')\n")
    source = _once(source, '_DERIVED_TEXT = _replace_exact(_ORIGINAL_TEXT, _EDITS)\n',
        'from partition_routing_transform import continuation_control_source as _compact_continuation\n'
        'from funding_transfer import continuation_control_source_after_limits as _funding_continuation\n'
        '_DERIVED_TEXT = _funding_continuation(_compact_continuation(_replace_exact(_ORIGINAL_TEXT, _EDITS)))\n')
    compile(source, 'private_heat_original_continuation_r1.py[compact-routing]', 'exec', dont_inherit=True)
    return source
