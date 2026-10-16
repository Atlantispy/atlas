"""WP14 partition production: one incremental support DAG and compact body.

Applied after partition_native_patch, never to a loaded or frozen runtime.
The optional scope is the caller's existing retained scope. Scientific loops
and predicates remain native; only their record ownership/issuance changes.
"""
from copy import deepcopy
from hashlib import sha256
import sys

import mesh_tables as M
import partition_native_patch as PN
import partition_tables as P

INPUT_SHA256 = '29443f86c8dce100af71072426f9848a5cc7ed4f20cbbb323d98a6ec0c725924'
COMPOSED_INPUT_SHA256 = 'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253'


def resolve_scope(budget, scope=None, parent=None):
    from content_cache import RetainedScope
    view = None if parent is None else PN.compact_view(parent)
    inherited = view.scope if view is not None and PN._is_v2(view) else None
    if scope is None:
        scope = inherited
    if scope is not None and (type(scope) is not RetainedScope or scope.run_budget is not budget or
                              scope._closed or inherited is not None and inherited is not scope):
        raise PN._native().V.VolumeError('one existing open partition scope and exact run budget required')
    return scope


def _width(value, depth=0):
    if depth > 128:
        raise ValueError('record nesting exceeds bound')
    if type(value) in (list, tuple):
        return 2+sum(1+_width(v, depth+1) for v in value)
    if type(value) is dict:
        return 2+sum(2+M._width(k)+_width(v, depth+1) for k, v in value.items())
    return M._width(value)


def _normalise(value, memo, depth=0):
    """The native JSON container conversion, retaining unchanged subtrees."""
    if depth > 128:
        raise ValueError('record nesting exceeds bound')
    if type(value) not in (dict, list, tuple):
        return value
    found = memo.get(id(value))
    if found is not None:
        return found
    if type(value) is dict:
        changed = {k: _normalise(v, memo, depth+1) for k, v in value.items()}
        result = value if all(changed[k] is v for k, v in value.items()) else changed
    else:
        changed = [_normalise(v, memo, depth+1) for v in value]
        result = value if type(value) is list and all(a is b for a, b in zip(changed, value, strict=True)) else changed
    memo[id(value)] = result
    return result


def _object_storage(value, arena):
    """Distinct Python backing, including container capacity and scalar bodies."""
    seen, pending, total, nodes = set(), [value], 0, 0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        arena.hold(256)
        seen.add(id(item)); nodes += 1
        total += sys.getsizeof(item)
        if type(item) is dict:
            if len(item) > M.MAX_ITEMS or any(type(k) is not str for k in item):
                raise ValueError('bounded JSON object required')
            arena.hold(128*len(item))
            pending.extend(item.keys()); pending.extend(item.values())
        elif type(item) in (tuple, list):
            if len(item) > M.MAX_ITEMS:
                raise ValueError('bounded JSON sequence required')
            arena.hold(64*len(item))
            pending.extend(item)
        elif item is not None and type(item) not in (bool, int, float, str):
            raise ValueError('only native JSON values are admitted')
    return total, nodes


def owned_support(row, budget):
    """Transfer the scientific result before its arena leaves the producer."""
    # Charge traversal growth before each set/stack extension. Distinct backing,
    # rather than expanded DAG mentions, funds the retained result. Two backing
    # copies plus per-node memo/carrier space also cover tuple normalisation.
    scratch = P._Arena(budget)
    scratch.hold(65536)
    size, nodes = _object_storage(row, scratch)
    owner = M._Allocation(budget, 65536+2*size+512*nodes)
    result = M.OwnedRow(_normalise(row, {}), owner)
    del scratch
    return result


def native_projection(row, budget):
    """The contact/identity projection of a natively issued support row.

    Step 8: the native route keeps these few IDs instead of decoding every
    issued support twice more for contacts and identities; same values.
    """
    owner = M._Allocation(budget, 4096+512*len(row['components']))
    components = tuple({k: p[k] for k in ('logical_cell_id', 'parent_cell_id') if k in p}
                       for p in row['components'])
    return components, owner


class _Support:
    __slots__ = ('support_id', 'components', '_owner')

    def __init__(self, row, budget, identity):
        self._owner = M._Allocation(budget, 4096+512*len(row['components']))
        self.support_id = identity.sha256
        self.components = tuple({k: p[k] for k in ('logical_cell_id', 'parent_cell_id') if k in p}
                                for p in row['components'])


class SupportBatch:
    """One bounded incremental DAG; only contact projections stay native."""
    def __init__(self, scope, *, check=lambda: None):
        from partition_v2 import PartitionV2Builder
        self.scope, self.check = scope, check
        self._builder = PartitionV2Builder(scope=scope, check=check)
        self._rows, self._next = [], None
        self._inventory_chunks = []

    def issue(self, row):
        self.check()
        if self._next is not None:
            raise ValueError('previous issued support was not appended')
        identity = self._builder.add_support(row)
        self._next = _Support(row, self.scope.run_budget, identity)
        return self._next

    def append(self, support):
        if type(support) is not _Support or self._next is not support:
            raise ValueError('only the just-issued compact support may be appended')
        if len(self._rows) % 128 == 0:
            self._inventory_chunks.append(M._Allocation(self.scope.run_budget, 65536))
        self._rows.append(support)
        self._next = None

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def finish(self, body, identity):
        if self._next is not None:
            raise ValueError('issued support missing from contact inventory')
        # The contact projections are spent once the body exists; they and
        # their inventory bookings end before the whole-partition build.
        self._rows.clear()
        self._inventory_chunks.clear()
        return self._builder.finish(body, expected_partition_id=identity)

    def close(self):
        self._builder.close()
        self._rows.clear()
        self._next = None
        self._inventory_chunks.clear()


def finish(body_owner, supports, funding, collar, geometry, *, source=None):
    """One final body identity and domain admission, with no partition JSON.

    body_owner may be a one-slot list: this frame then takes the only
    reference, and the body ends once the sealed record holds it (Step 8),
    before whole-partition validation. source is the caller's decode of
    funding.descriptor()['source'] from the same call, if it has one.
    """
    if type(supports) is not SupportBatch:
        raise ValueError('actual compact support builder required')
    if type(body_owner) is list:
        body_owner = body_owner.pop()
    body = body_owner.value
    budget = supports.scope.run_budget
    identity = P._hash_json(body, budget)
    view = supports.finish(body, identity)
    del body, body_owner
    result = PN.admit_partition(PN._native().DifferentialPartition, view,
                                funding, collar, geometry, budget=budget, _source=source)
    supports.close()
    return result


# Step 8: carried charts are re-booked, not copied, on every parent route. A
# region aliases subtrees of the parent support export it was built from (as
# the native producer always has); each new region is walked once and its
# distinct reachable objects are booked before that export retires, so the
# alias stays paid and nothing else of the export is kept. Previously native
# and v1 parents kept every export's decode charge through assembly, and v2
# parents deep-copied each region at 4096+192 bytes per canonical byte.
# Test-only switch for the same-source before/after measurement (partition
# code is not a heat-issuer dependency).
REBOOK_CHARTS = True


class ChartLifetime:
    """Keep only the chart inputs regions use, paid as really held."""
    def __init__(self, partition, scope):
        self.budget, self.scope = partition._resource, scope
        self._legacy = (PN._RetainedRows(partition) if scope is None and not REBOOK_CHARTS
                        else None)
        self._owners = []
        self._cells = 0

    def keep(self, row):
        if self._legacy is not None:
            self._legacy.keep(row)

    def detach(self, region):
        if not REBOOK_CHARTS:
            if self.scope is None:
                return region
            # Reserve before cloning descendants; the old export remains paid too.
            owner = M._Allocation(self.budget, 4096+192*_width(region))
            result = deepcopy(region)
            self._owners.append(owner)
            return result
        # Book what this region keeps alive while its export is still paid.
        # The walk's own growth is charged to a scratch arena it releases.
        scratch = P._Arena(self.budget)
        scratch.hold(65536)
        size, nodes = _object_storage(region, scratch)
        self._owners.append(M._Allocation(self.budget, 4096+size+16*nodes))
        del scratch
        return region

    def cell(self):
        """Book carried parent_cells growth, one block per 128 entries."""
        if self._cells % 128 == 0:
            self._owners.append(M._Allocation(self.budget, 65536))
        self._cells += 1


def parent_rows(partition, scope):
    fields = ('plate_id', 'source_chart_id', 'source_key', 'radial_layer',
              'radial_band', 'voxel_index', 'components', 'constraints')
    if scope is None:
        for support in partition.supports:
            yield PN.owned_support_record(support)
    else:
        yield from PN.support_records(partition, fields=fields)


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('live partition seam differs: '+old[:100])
    return source.replace(old, new, 1)


def transform(source):
    """Exact current producer; selection requires its measured benefit gate."""
    input_hash = sha256(source.encode()).hexdigest()
    if input_hash not in (INPUT_SHA256, COMPOSED_INPUT_SHA256):
        raise ValueError('exact reviewed partition-native output required')
    source = _once(source, '                               _angular_cache=None, _interval_record=None):\n',
        '                               _angular_cache=None, _interval_record=None, _owned_result=False):\n')
    source = _once(source, '    return _issue(DifferentialSupport, result, budget)\n\n\ndef _cached_constraint_pose',
        '        if _owned_result:\n'
        '            from live_partition_patch import owned_support\n'
        '            return owned_support(result, budget)\n'
        '    return _issue(DifferentialSupport, result, budget)\n\n\ndef _cached_constraint_pose')
    source = _once(source, '                                   grid_lines, max_components, budget):\n',
        '                                   grid_lines, max_components, budget, compact_scope=None):\n')
    source = _once(source, '        grid_lines=grid_lines, max_components=max_components, budget=budget)\n',
        '        grid_lines=grid_lines, max_components=max_components, budget=budget, compact_scope=compact_scope)\n')
    source = _once(source, '                        grid_lines, max_components, budget, parent_partition=None):\n',
        '                        grid_lines, max_components, budget, parent_partition=None,\n'
        '                        compact_scope=None, _final_fields=None):\n'
        '    from live_partition_patch import resolve_scope, SupportBatch, finish\n'
        '    compact_scope = resolve_scope(budget, compact_scope, parent_partition)\n')
    # Both routes take the scientific row once, as an owned value (no first
    # native issue and whole decode); the native route then issues it once
    # and keeps the few contact/identity IDs instead of decoding it twice more.
    source = _once(source, '    supports, cells, by_voxel, native_voxels, excluded_voxels = [], {}, {}, {}, set()\n',
        '    supports = [] if compact_scope is None else SupportBatch(compact_scope)\n'
        '    from live_partition_patch import native_projection\n'
        '    native_components = {}\n'
        '    cells, by_voxel, native_voxels, excluded_voxels = {}, {}, {}, set()\n')
    source = _once(source, '                    _owner_face_ids=(region[\'source_face_id\'],) if static else None)\n'
                           '                row = support.record()\n',
        '                    _owner_face_ids=(region[\'source_face_id\'],) if static else None,\n'
        '                    _owned_result=True)\n'
        '                row_owner = support\n'
        '                row = support.value\n')
    source = _once(source, '                support = _issue(DifferentialSupport, row, budget)\n',
        '                support = (_issue(DifferentialSupport, row, budget) if compact_scope is None\n'
        '                           else supports.issue(row))\n'
        '                if compact_scope is None:\n'
        '                    native_components[support.support_id] = native_projection(row, budget)\n')
    source = _once(source, "                if not row['components']:\n                    continue\n",
        "                if not row['components']:\n"
        "                    row = support = row_owner = None\n"
        "                    continue\n")
    source = _once(source, "                    raise V.VolumeError('complete source partition exceeds explicit component count; nothing omitted')\n",
        "                    raise V.VolumeError('complete source partition exceeds explicit component count; nothing omitted')\n"
        "                row = part = row_owner = None\n")
    source = _once(source, '                        for part in support.record()[\'components\']:\n',
        '                        for part in (native_components[support.support_id][0] if compact_scope is None\n'
        '                                     else support.components):\n')
    source = _once(source, '                for support in supports for p in support.record()[\'components\'] if p[\'parent_cell_id\'] is not None]\n',
        '                for support in supports\n'
        '                for p in (native_components[support.support_id][0] if compact_scope is None else support.components)\n'
        '                if p[\'parent_cell_id\'] is not None]\n')
    source = _once(source, '        issued = _issue(DifferentialPartition, result, budget)\n'
                           '        object.__setattr__(issued, \'_supports\', tuple(supports))\n    return issued\n',
        '        # The scientific work ends with the result dict on both branches.\n'
        '        # Its candidate and arena charges stay booked until the block exits.\n'
        '        del by_voxel, cells, native_voxels, excluded_voxels, prepared_regions\n'
        '        del pose_cache, angular_cache, owner_planes, carried_planes, start_fans\n'
        '        del current, native, excluded, contacts, native_components\n'
        '        if _final_fields is not None:\n'
        '            result.update(_final_fields)\n'
        '        if compact_scope is None:\n'
        '            issued = _issue(DifferentialPartition, result, budget)\n'
        '            object.__setattr__(issued, \'_supports\', tuple(supports))\n'
        '            return issued\n'
        '        from live_partition_patch import owned_support\n'
        '        holder = [owned_support(result, budget)]\n'
        '        del result\n'
        "    return finish(holder, supports, funding, collar, geometry, source=original['source'])\n")
    # The gates above are the only readers; assembly decodes its own copy.
    source = _once(source, '    return _assemble_partition(funding, sphere, geometry, collar, original, regions,\n',
        '    del current\n'
        '    return _assemble_partition(funding, sphere, geometry, collar, original, regions,\n')
    signature = ('                               finite_stock_state, max_components, budget'+
                 (', _runtime_transfer=None' if input_hash == COMPOSED_INPUT_SHA256 else '')+'):\n')
    source = _once(source, signature, signature.replace('):\n', ', compact_scope=None):\n'))
    source = _once(source, '    retained_rows = _RetainedRows(parent_partition)\n',
        '    from live_partition_patch import resolve_scope, ChartLifetime, parent_rows\n'
        '    compact_scope = resolve_scope(budget, compact_scope, parent_partition)\n'
        '    retained_rows = ChartLifetime(parent_partition, compact_scope)\n')
    source = _once(source, '    for support in parent_partition.supports:\n'
                           '        support_owner = owned_support_record(support)\n',
        '    for support_owner in parent_rows(parent_partition, compact_scope):\n')
    source = _once(source, '                    parent_owner_ray_ids=component[\'owner_ray_ids\'], parent_cells={}, parent_chart=identity)\n',
        '                    parent_owner_ray_ids=component[\'owner_ray_ids\'], parent_cells={}, parent_chart=identity)\n'
        '                regions[key] = retained_rows.detach(regions[key])\n')
    # One issue on both routes: the finite fields join the result before its
    # only encoding (canonical sorted keys; tuples encode as lists), instead of
    # a native issue, a whole decode and a re-issue. The decoded interval,
    # finite stock list and parent header end before assembly.
    source = _once(source, "    stocks = finite_stock_state.record()['stocks']\n",
        '    finite_record = finite_stock_state.record()\n'
        "    stocks = finite_record['stocks']\n")
    source = _once(source, '    result = _assemble_partition(funding, sphere, interval, collar, original,\n'
                           '        [regions[k] for k in sorted(regions)], grid_lines=tuple(tuple(map(W._decode, axis)) for axis in old[\'grid_lines\']),\n'
                           '        max_components=max_components, budget=budget, parent_partition=parent_partition)\n',
        '    grid_lines = tuple(tuple(map(W._decode, axis)) for axis in old[\'grid_lines\'])\n'
        '    final_fields = dict(finite_state_id=finite_stock_state.state_id, finite_owner_id=finite_stock_state._owner.owner_id,\n'
        '        component_registry_id=finite_record[\'registry_id\']\n'
        '            if \'registry_id\' in finite_record else finite_stock_state._owner.definition()[\'registry_id\'])\n'
        '    del step, stocks, finite_record, old, old_owner\n'
        '    result = _assemble_partition(funding, sphere, interval, collar, original,\n'
        '        [regions[k] for k in sorted(regions)], grid_lines=grid_lines,\n'
        '        max_components=max_components, budget=budget, parent_partition=parent_partition,\n'
        '        compact_scope=compact_scope, _final_fields=final_fields)\n'
        '    return result\n')
    source = _once(source, '    r = result.record()\n'
        '    r.update(finite_state_id=finite_stock_state.state_id, finite_owner_id=finite_stock_state._owner.owner_id,\n'
        "        component_registry_id=finite_stock_state.record()['registry_id'] if 'registry_id' in finite_stock_state.record()\n"
        "            else finite_stock_state._owner.definition()['registry_id'])\n"
        '    issued = _issue(DifferentialPartition, r, budget)\n'
        "    object.__setattr__(issued, '_supports', result.supports)\n"
        '    return issued\n', '')
    source = _once(source, "            cells[at] = component['logical_cell_id']\n",
        "            cells[at] = component['logical_cell_id']\n"
        '            retained_rows.cell()\n')
    start = source.index('    regions = {}\n    for support_owner in parent_rows(parent_partition, compact_scope):\n')
    end = source.index('    # Actual finite birth declarations', start)
    loop = source[start:end]
    helper = ('\n\ndef _carried_partition_regions(parent_partition, step, old_time, retained_rows, compact_scope):\n'
              '    from live_partition_patch import parent_rows\n'+loop+'    return regions\n')
    source = source[:start]+('    regions = _carried_partition_regions(parent_partition, step, old_time,\n'
                             '                                          retained_rows, compact_scope)\n')+source[end:]
    source += helper
    return source


def transform_lifetimes(source):
    """Selected candidate: parent chart ownership only; original output route.

    Compose last, after the existing endpoint/geometry-transfer checks. This
    does not activate experimental support batching or change record issuance.
    """
    if sha256(source.encode()).hexdigest() not in (INPUT_SHA256, COMPOSED_INPUT_SHA256):
        raise ValueError('exact reviewed partition-native or complete geometry output required')
    source = _once(source, '    retained_rows = _RetainedRows(parent_partition)\n',
        '    from live_partition_patch import resolve_scope, ChartLifetime\n'
        '    _chart_scope = resolve_scope(budget, parent=parent_partition)\n'
        '    retained_rows = ChartLifetime(parent_partition, _chart_scope)\n')
    source = _once(source, '    for support in parent_partition.supports:\n'
                           '        support_owner = owned_support_record(support)\n',
        '    for support_owner in parent_rows(parent_partition, _chart_scope):\n')
    source = _once(source, '                    parent_owner_ray_ids=component[\'owner_ray_ids\'], parent_cells={}, parent_chart=identity)\n',
        '                    parent_owner_ray_ids=component[\'owner_ray_ids\'], parent_cells={}, parent_chart=identity)\n'
        '                regions[key] = retained_rows.detach(regions[key])\n')
    source = _once(source, "            cells[at] = component['logical_cell_id']\n",
        "            cells[at] = component['logical_cell_id']\n"
        '            retained_rows.cell()\n')
    start = source.index('    regions = {}\n    for support_owner in parent_rows(parent_partition, _chart_scope):\n')
    end = source.index('    # Actual finite birth declarations', start)
    loop = source[start:end]
    helper = ('\n\ndef _carried_partition_regions(parent_partition, step, old_time, retained_rows, _chart_scope):\n'
              '    from live_partition_patch import parent_rows\n'+loop+'    return regions\n')
    source = source[:start]+('    regions = _carried_partition_regions(parent_partition, step, old_time,\n'
                             '                                          retained_rows, _chart_scope)\n')+source[end:]
    return source+helper
