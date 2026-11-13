"""Incomplete, uninstalled source-bound END mesh provider for q297.

This unselected successor joins the binding gate to the per-support candidate.
The caller must authenticate dependencies and process finality. Actual H selector,
assembly, issued closure and native/compact checks remain unproved.
"""
import hashlib
import json
import weakref
from pathlib import Path
from types import MappingProxyType
from fractions import Fraction

GRID_SHA = '9b9abbf95f17fdd771fff0ca565599707def2c1c3d929f668d7d13d83f133d67'
GRAPH_SHA = 'b28193a53cce443ac6756b8358fe2411d198f3b61087d7335b8bcfc3b81a7f40'
PARTITION_ID = '9638746f2de6c76b5788cedfd5240200276a4231fa0487ff8353eec1a8049654'
CARRY_SHA = '44b889737d1f9a08def913ec9209d1203b996d6ef69f35803f36c6a2fc9334f5'
GENERATION = '0f83587b3bddc3dcf8cea05910d408269a7b847db60fe5db83533f2c81be6d0e'
SWEEP_SHA = '3ac636974d9909304c52cf071caa12316c249322491c18307a4ee6cf2e3a8205'
PHYSICAL_SHA = 'e78918f8b9344b8ed06d21256628f9ad801a876336f669374faf405598e026ce'
PAYLOAD_SHA = '290d83c1afc94a0917078b01175d0f5aa3ee18edb8561d373a9d311de054accc'
CHAIN_SHA = 'fd872d941b60e75f5e72caaa362753f353d3eaf97780dac0f937979816899256'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pinned_records(path, expected_sha, arena):
    """Read one admitted bounded record under the owning arena reservation."""
    path = Path(path)
    size = path.stat().st_size
    if not 0 < size <= 32 << 20:
        raise ValueError('qualification proof exceeds its source bound')
    arena._retain(65536 + 16 * size)
    with path.open('rb') as stream:
        raw = stream.read(size + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('qualification proof identity differs')
    records = []
    for line in raw.splitlines():
        if line.lstrip().startswith(b'{'):
            record = json.loads(line)
            if type(record) is dict:
                records.append(record)
    return records


def read_verified_totals(*, sweep_output, physical_output, checkpoint, arena):
    """Load only the bound q347/q348 nominal totals and physical receipt.

    The caller must separately authenticate the tracked attempts and selected
    inputs; these source pins cannot by themselves establish process finality.
    """
    sweep = [r for r in _pinned_records(sweep_output, SWEEP_SHA, arena)
             if r.get('stage') == 'STREAMED_SOURCE_GRID_SWEEP']
    physical = [r for r in _pinned_records(physical_output, PHYSICAL_SHA, arena)
                if r.get('stage') == 'EMITTED_COMPONENT_SOURCE_COMPARISON']
    if len(sweep) != 1 or len(physical) != 1:
        raise ValueError('qualified source records are missing or ambiguous')
    sweep, physical = sweep[0], physical[0]
    if (sweep.get('generation') != GENERATION or sweep.get('tile_count') != 1089 or
            sweep.get('positive_shell') != 771 or sweep.get('total_work') != 357120461 or
            sweep.get('payload_digest') != PAYLOAD_SHA or
            physical.get('compared_sweep_run') != '06b9cb35-ee24-4796-bf15-1b8395390514' or
            physical.get('compared_generation') != GENERATION or physical.get('compared_chain_sha256') != CHAIN_SHA or
            physical.get('consumed_stdout_sha256') != SWEEP_SHA or physical.get('consumed_payload_digest') != PAYLOAD_SHA or
            physical.get('logical_components') != 6212 or physical.get('positive_charges') != 847 or
            physical.get('counts') != {'inherited': 4129, 'birth': 2083, 'zero': 5365}):
        raise ValueError('qualified sweep or physical receipt differs')
    pairs = sweep.get('positive_component_sums')
    if (type(pairs) is not list or len(pairs) != 847 or
            any(type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str for pair in pairs)):
        raise ValueError('qualified positive component inventory differs')
    ids = [pair[0] for pair in pairs]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError('qualified positive component IDs differ')
    folded = dict(generation=GENERATION, tiles=1089, positive_shell=771,
                  total_work=357120461, positive_component_sums=pairs)
    if checkpoint.digest(folded) != PAYLOAD_SHA:
        raise ValueError('qualified nominal fold digest differs')
    totals = {ident: checkpoint.decode(value) for ident, value in pairs}
    if any(value <= 0 for value in totals.values()):
        raise ValueError('qualified nominal total is not positive')
    try:
        numerator, denominator = physical['total_charge_m3']
        charge = Fraction(int(numerator, 16), int(denominator, 16))
        numerator, denominator = physical['upper_width_m3']
        width = Fraction(int(numerator, 16), int(denominator, 16))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError('qualified physical width record malformed') from error
    if not 0 <= charge <= width == 32000:
        raise ValueError('qualified physical width exceeded')
    return totals


def read_corresponding_totals(*, sweep_output, physical_output, checkpoint, arena):
    """Bind the independently compared new IDs to the original evidence.

    Process finality and selected producer code are separately authenticated by
    the factory. This unselected candidate does not establish live issuer identity.
    """
    old_count = len(read_verified_totals(sweep_output=sweep_output, physical_output=physical_output,
                                         checkpoint=checkpoint, arena=arena))
    path = Path(sweep_output).parent.parent.parent/'q363-correspondence-r2/result-data.json'
    size = path.stat().st_size
    if not 0 < size <= 4 << 20:
        raise ValueError('correspondence proof exceeds source bound')
    arena._retain(65536 + 16 * size)
    with path.open('rb') as stream:
        raw=stream.read(size+1)
    if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=CARRY_SHA:
        raise ValueError('correspondence proof identity differs')
    proof=json.loads(raw)
    if (proof.get('schema')!='q363.correspondence-candidate.v2' or
            proof.get('status')!='CANDIDATE_PENDING_FINAL_CONSUMER_BINDING' or
            proof.get('old_graph')!='8972063a43a469c8d619dbc4099a128ff6ad935026d65b19cc30b9ca86493846' or
            proof.get('new_graph')!=GRAPH_SHA or proof.get('support_count')!=2016 or
            proof.get('component_count')!=6212 or proof.get('mapped_tiles')!=1089 or
            proof.get('positive_shell')!=771 or proof.get('positive_components')!=847 or old_count!=847):
        raise ValueError('correspondence proof binding differs')
    pairs=proof.get('mapped_nominal_sums')
    if (type(pairs) is not list or len(pairs)!=847 or
            any(type(p) is not list or len(p)!=2 or type(p[0]) is not str for p in pairs)):
        raise ValueError('corresponding nominal pairs malformed')
    ids=[p[0] for p in pairs]
    if ids!=sorted(ids) or len(ids)!=len(set(ids)):
        raise ValueError('corresponding nominal identities differ')
    totals={ident:checkpoint.decode(value) for ident,value in pairs}
    if any(value<=0 for value in totals.values()):
        raise ValueError('corresponding nominal total is not positive')
    return totals


class EndGeometryProvider:
    """Bind the exact issued END inputs without taking ownership of them."""

    def __init__(self, *, interval, partition, funding, bounds, closed_graph,
                 budget, grid_bytes, D, H, W, V, B, E, dependencies, sweep_output, physical_output):
        from atlas_tectonics.integration_spatial_ale import SpatialALEGraph
        if (type(interval) is not D.DifferentialInterval or type(partition) is not D.DifferentialPartition or
                type(funding) is not H.FullCellFunding or type(bounds) is not H.SpatialALEBounds or
                type(closed_graph) is not SpatialALEGraph or
                interval._resource is not budget or partition._resource is not budget or
                funding._resource is not budget or bounds._resource is not budget or
                closed_graph._resource is not budget):
            raise ValueError('issued interval, partition, funding, bounds and closure on one budget required')
        if type(grid_bytes) is not bytes or hashlib.sha256(grid_bytes).hexdigest() != GRID_SHA:
            raise ValueError('selected successor grid identity differs')
        if closed_graph.geometry_id != GRAPH_SHA or partition.partition_id != PARTITION_ID:
            raise ValueError('issued closure or partition identity differs')
        # Own the decoded compact grid for exactly the provider lifetime.
        lease = budget.reserve(4096 + 32 * len(grid_bytes), category='q297-provider-grid')
        lease.__enter__()
        try:
            grid = json.loads(grid_bytes)
            if (grid.get('schema') != 'atlas.diagnostic.q336-successor-grid.v1' or
                    grid.get('graph_id') != GRAPH_SHA or grid.get('partition_id') != PARTITION_ID or
                    grid.get('booked_exterior') != 847 or grid.get('refinements') != 2):
                raise ValueError('selected successor grid provenance differs')
            ids = [support.support_id for support in partition.supports]
            if ids != grid.get('support_ids') or len(ids) != len(set(ids)):
                raise ValueError('issued ordered support inventory differs')
            def freeze(value):
                if type(value) is dict:
                    return MappingProxyType({key: freeze(item) for key, item in value.items()})
                if type(value) is list:
                    return tuple(freeze(item) for item in value)
                return value
            grid = freeze(grid)
            self.interval, self.partition, self.funding, self.bounds = interval, partition, funding, bounds
            self.closed_graph, self.budget, self.grid = closed_graph, budget, grid
            self.D, self.H, self.W, self.V, self.B, self.E = D, H, W, V, B, E
            self.dependencies = dependencies
            self.sweep_output, self.physical_output = sweep_output, physical_output
            self._lease, self._state = lease, 'NEW'
            self._finalizer = weakref.finalize(self, lease.__exit__, None, None, None)
        except BaseException:
            lease.__exit__(None, None, None)
            raise

    def close(self):
        from atlas_tectonics._private.q297_end_factory_v2 import release
        release(self)

    def prepare(self, *, funding, bounds, supports, closed_graph, endpoint, lines,
                integration_width, max_leaves, max_refinements, budget, arena, measures, booked, bounds_record):
        if (getattr(self, '_state', None) != 'CLAIMED' or endpoint != 'end' or funding is not self.funding or bounds is not self.bounds or
                supports is not self.partition.supports or closed_graph is not self.closed_graph or
                budget is not self.budget or arena.resource is not budget):
            raise ValueError('END provider context or lifetime differs')
        from atlas_tectonics._private.q297_end_factory_v2 import release
        arena.stack.callback(release, self)
        if (bounds_record.get('interval_id') != self.interval.interval_id or
                bounds_record.get('partition_id') != self.partition.partition_id or
                bounds_record.get('funding_id') != self.funding.funding_id or
                tuple(bounds_record.get('support_ids', ())) != self.grid['support_ids']):
            raise ValueError('issued bounds and provider source identities differ')
        if (integration_width != self.W._decode(self.grid['local_width']) or max_leaves != 2**19 or
                type(max_refinements) is not int or max_refinements < 2 or type(booked) is not dict):
            raise ValueError('selected physical width, refinement or booking differs')
        expected_lines = tuple(tuple(map(self.W._decode, axis)) for axis in bounds_record['grid_lines'])
        grid = tuple(tuple(map(self.W._decode, axis)) for axis in self.grid['grid'])
        if (lines != expected_lines or len(grid) != 3 or
                any(any(a >= b for a, b in zip(axis, axis[1:], strict=False)) for axis in grid) or
                any(not set(lines[i]) <= set(grid[i]) or lines[i][0] != grid[i][0] or
                    lines[i][-1] != grid[i][-1] for i in range(3)) or
                Fraction(-33, 8) not in grid[2]):
            raise ValueError('selected grid does not refine the actual bounds')
        # This isolated candidate requires a separately authenticated dependency
        # set and tracked process finality. It is not selected by a runtime.
        deps = self.dependencies
        required = {'checkpoint', 'pieces', 'piece_builder', 'rays', 'family', 'start'}
        if type(deps) is not MappingProxyType or set(deps) != required:
            raise ValueError('exact candidate dependency set required')
        totals = read_corresponding_totals(sweep_output=self.sweep_output,
            physical_output=self.physical_output, checkpoint=deps['checkpoint'], arena=arena)
        component_ids = [part['logical_cell_id'] for support in supports
                         for part in support.record()['components']]
        if (len(component_ids) != len(set(component_ids)) or
                any(key not in booked for key in component_ids) or
                {key for key in component_ids if booked[key] > 0} != set(totals)):
            raise ValueError('qualified nominal IDs differ from actual positive bookings')
        self._arena, self._measures, self._booked = arena, measures, booked
        self._shared, self._totals = grid, MappingProxyType(totals)
        self._contexts = {}
        self._rays = deps['rays'].IntervalRays(self.interval, budget=budget, arena=arena,
            D=self.D, W=self.W, V=self.V, E=self.E)
        arena._retain(4096 * len(supports) + 1024 * len(totals))
        self._state = 'ACTIVE'
        from atlas_tectonics._private.q297_end_factory_v2 import activate
        activate(self)
        # The original witness refinement is one; the extra q336 split is
        # qualification geometry, not a second witness-driven refinement.
        return grid, measures, 1

    def _context(self, row):
        key = json.dumps((row['plate_id'], row['start_time_s'], row['end_time_s'], row['grid_id']),
                         sort_keys=True, separators=(',', ':'))
        if key not in self._contexts:
            c = self.dependencies['family'].FamilyPose(row, self.budget, self._arena,
                self.D, self.W, self.V, self.E, self.dependencies['start'].exact_material_start)
            if c.omega[0] == 0 and c.omega[1] == 0 and c.omega[2] != 0:
                mat = c.matrix
                C, S = mat[0][0], mat[1][0]
                if mat != ((C, -S, Fraction(0)), (S, C, Fraction(0)),
                           (Fraction(0), Fraction(0), Fraction(1))):
                    raise ValueError('unexpected pure-z material matrix')
                theta = c.omega[2] * c.duration
                c.error = min(c.error, abs(C-(1-theta**2/2))+abs(theta)**4/24+
                              abs(S-(theta-theta**3/6))+abs(theta)**5/120)
            self._arena._retain(2048 + len(key))
            self._contexts[key] = c
        c = self._contexts[key]
        if (tuple(map(self.W._decode, row['material_angular_velocity_rad_s'])) != c.omega or
                self.W._decode(row['duration_s']) != c.duration or row['grid_id'] != c.frame):
            raise ValueError('material context mismatch')
        return c

    def support_cells(self, support, *, endpoint, integration_width, max_leaves, budget,
                      arena, subdivisions, shared_lines, measures, booked, unbooked):
        if (getattr(self, '_state', None) != 'ACTIVE' or arena is not self._arena or budget is not self.budget or
                shared_lines is not self._shared or measures is not self._measures or booked is not self._booked):
            raise ValueError('prepared END provider context differs')
        from atlas_tectonics._private.q297_end_factory_v2 import validate_active
        validate_active(self)
        row = support.record()
        active = any(not self.H._unbooked(booked, part['logical_cell_id'])
                     for part in row['components'])
        if not active:
            return self.H._support_cells(support, endpoint=endpoint, integration_width=integration_width,
                max_leaves=max_leaves, budget=budget, arena=arena, subdivisions=subdivisions,
                shared_lines=shared_lines, measures=measures, booked=booked, unbooked=unbooked)
        context = self._context(row)
        return self.dependencies['pieces'].build_support_pieces(support, endpoint=endpoint,
            integration_width=integration_width, max_leaves=max_leaves, budget=budget, arena=arena,
            subdivisions=subdivisions, shared_lines=shared_lines, measures=measures, booked=booked,
            unbooked=unbooked, interval_rays=self._rays, context=context,
            nominal_totals=self._totals, piece_builder=self.dependencies['piece_builder'],
            D=self.D, H=self.H, W=self.W, V=self.V, B=self.B, E=self.E)
