"""WP14 partition production: one incremental support DAG and compact body.

Applied after partition_native_patch, never to a loaded or frozen runtime.
The optional scope is the caller's existing retained scope. Scientific loops
and predicates remain native; only their record ownership/issuance changes.
"""
from copy import deepcopy
import sys

from atlas_tectonics._private.codecs import mesh_tables as M
from atlas_tectonics._private.integration.geometry import partition_native_patch as PN
from atlas_tectonics._private.codecs import partition_tables as P


def resolve_scope(budget, scope=None, parent=None):
    view = None if parent is None else PN.compact_view(parent)
    inherited = view.scope if view is not None and PN._is_v2(view) else None
    if scope is None:
        scope = inherited
    return scope


def _width(value, depth=0):
    if type(value) in (list, tuple):
        return 2+sum(1+_width(v, depth+1) for v in value)
    if type(value) is dict:
        return 2+sum(2+M._width(k)+_width(v, depth+1) for k, v in value.items())
    return M._width(value)


def _normalise(value, memo, depth=0):
    """The native JSON container conversion, retaining unchanged subtrees."""
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
            arena.hold(128*len(item))
            pending.extend(item.keys()); pending.extend(item.values())
        elif type(item) in (tuple, list):
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
        from atlas_tectonics._private.integration.geometry.partition_adapter import PartitionV2Builder
        self.scope, self.check = scope, check
        self._builder = PartitionV2Builder(scope=scope, check=check)
        self._rows, self._next = [], None
        self._inventory_chunks = []

    def issue(self, row):
        self.check()
        identity = self._builder.add_support(row)
        self._next = _Support(row, self.scope.run_budget, identity)
        return self._next

    def append(self, support):
        if len(self._rows) % 128 == 0:
            self._inventory_chunks.append(M._Allocation(self.scope.run_budget, 65536))
        self._rows.append(support)
        self._next = None

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def finish(self, body, identity):
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
