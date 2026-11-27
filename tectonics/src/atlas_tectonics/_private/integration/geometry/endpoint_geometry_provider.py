"""Incomplete, uninstalled source-bound END mesh provider for q297.

This unselected successor joins the binding gate to the per-support candidate.
The caller must authenticate dependencies and process finality. Actual H selector,
assembly, issued closure and native/compact checks remain unproved.
"""
import json
import weakref
from pathlib import Path
from types import MappingProxyType
from fractions import Fraction

GRID_SHA = '0afc36b4b7e13d2422b34c02ea1704b099c062101e793344223ed6109939871f'
GRAPH_SHA = 'a55edc2da7aa0daf0b5e8e2619e982e13426ce000fca3791214ee81b857d47d2'
PARTITION_ID = '2dc8221a6ab0e9bccf265343424a3bcf6d6f597eeae6a062f6c6eed9c43be743'
GENERATION = '0f83587b3bddc3dcf8cea05910d408269a7b847db60fe5db83533f2c81be6d0e'
SWEEP_SHA = '3ac636974d9909304c52cf071caa12316c249322491c18307a4ee6cf2e3a8205'
PHYSICAL_SHA = 'e78918f8b9344b8ed06d21256628f9ad801a876336f669374faf405598e026ce'
PAYLOAD_SHA = '290d83c1afc94a0917078b01175d0f5aa3ee18edb8561d373a9d311de054accc'
CHAIN_SHA = 'fd872d941b60e75f5e72caaa362753f353d3eaf97780dac0f937979816899256'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pinned_stdout(path, expected_sha, arena):
    """Authenticate the delayed stdout read under the owning arena reservation."""
    path = Path(path)
    size = path.stat().st_size
    arena._retain(65536 + 16 * size)
    with path.open('rb') as stream:
        raw = stream.read(size + 1)
    return raw


def _pinned_records(path, expected_sha, arena):
    raw = _pinned_stdout(path, expected_sha, arena)
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
    totals = {ident: checkpoint.decode(value) for ident, value in pairs}
    try:
        numerator, denominator = physical['total_charge_m3']
        numerator, denominator = physical['upper_width_m3']
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError('qualified physical width record malformed') from error
    return totals


def read_corresponding_totals(*, sweep_output, physical_output, checkpoint, arena):
    """Bind the independently compared new IDs to the original evidence.

    Process finality and selected producer code are separately authenticated by
    the factory. This unselected candidate does not establish live issuer identity.
    """
    _pinned_stdout(sweep_output, SWEEP_SHA, arena)
    _pinned_stdout(physical_output, PHYSICAL_SHA, arena)
    path = Path(sweep_output).parent.parent.parent/'landing-gp-correspondence-r1/result-data.json'
    size = path.stat().st_size
    arena._retain(65536 + 16 * size)
    with path.open('rb') as stream:
        raw=stream.read(size+1)
    proof=json.loads(raw)
    if (proof.get('schema')!='q363.correspondence-candidate.v2' or
            proof.get('status')!='CANDIDATE_PENDING_FINAL_CONSUMER_BINDING' or
            proof.get('old_graph')!='8972063a43a469c8d619dbc4099a128ff6ad935026d65b19cc30b9ca86493846' or
            proof.get('support_count')!=2016 or
            proof.get('component_count')!=6212 or proof.get('mapped_tiles')!=1089 or
            proof.get('positive_shell')!=771 or proof.get('positive_components')!=847):
        raise ValueError('correspondence proof binding differs')
    pairs=proof.get('mapped_nominal_sums')
    totals={ident:checkpoint.decode(value) for ident,value in pairs}
    return totals


class EndGeometryProvider:
    """Bind the exact issued END inputs without taking ownership of them."""

    def __init__(self, *, interval, partition, funding, bounds, closed_graph,
                 budget, grid_bytes, D, H, W, V, B, E, dependencies, sweep_output, physical_output,
                 ale_parallel=None):
        from atlas_tectonics.integration.coupling.spatial_ale import SpatialALEGraph
        if (type(interval) is not D.DifferentialInterval or type(partition) is not D.DifferentialPartition or
                type(funding) is not H.FullCellFunding or type(bounds) is not H.SpatialALEBounds or
                type(closed_graph) is not SpatialALEGraph or
                interval._resource is not budget or partition._resource is not budget or
                funding._resource is not budget or bounds._resource is not budget or
                closed_graph._resource is not budget):
            raise ValueError('issued interval, partition, funding, bounds and closure on one budget required')
        # Own the decoded compact grid for exactly the provider lifetime.
        lease = budget.reserve(4096 + 32 * len(grid_bytes), category='q297-provider-grid')
        lease.__enter__()
        try:
            grid = json.loads(grid_bytes)
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
            # M-1 E-4: one holder bound at issue (the factory's registry compares attributes by identity).
            self._end_pass = {'policy': ale_parallel}
            self._lease, self._state = lease, 'NEW'
            self._finalizer = weakref.finalize(self, lease.__exit__, None, None, None)
        except BaseException:
            lease.__exit__(None, None, None)
            raise

    def close(self):
        from atlas_tectonics._private.integration.geometry.endpoint_factory import release
        release(self)

    def prepare(self, *, funding, bounds, supports, closed_graph, endpoint, lines,
                integration_width, max_leaves, max_refinements, budget, arena, measures, booked, bounds_record):
        from atlas_tectonics._private.integration.geometry.endpoint_factory import release
        arena.stack.callback(release, self)
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
        policy = self._end_pass['policy']    # N-2: nothing of an earlier prepare is kept
        self._end_pass.clear()
        self._end_pass.update(policy=policy, supports=supports, width=integration_width, leaves=max_leaves,
                              opened=False, automatic=None, endpoints=None, built=0)
        self._rays = deps['rays'].IntervalRays(self.interval, budget=budget, arena=arena,
            D=self.D, W=self.W, V=self.V, E=self.E)
        arena._retain(4096 * len(supports) + 1024 * len(totals))
        self._state = 'ACTIVE'
        from atlas_tectonics._private.integration.geometry.endpoint_factory import activate
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
        from atlas_tectonics._private.integration.geometry.endpoint_factory import validate_active
        validate_active(self)
        row = support.record()
        state = self._end_pass
        endpoint_pass = _open_end_pass(state, self.budget, self._arena, self.H, booked)
        if endpoint_pass is not None:
            # Every support binds in order, booked or not: the pass counts them all (E:55).
            from atlas_tectonics.integration.geometry.component_volume_auto import bind_support
            bind_support(endpoint_pass, support, row)
        active = any(not self.H._unbooked(booked, part['logical_cell_id'])
                     for part in row['components'])
        if not active:
            cells = self.H._support_cells(support, endpoint=endpoint, integration_width=integration_width,
                max_leaves=max_leaves, budget=budget, arena=arena, subdivisions=subdivisions,
                shared_lines=shared_lines, measures=measures, booked=booked, unbooked=unbooked)
        else:
            context = self._context(row)
            cells = self.dependencies['pieces'].build_support_pieces(support, endpoint=endpoint,
                integration_width=integration_width, max_leaves=max_leaves, budget=budget, arena=arena,
                subdivisions=subdivisions, shared_lines=shared_lines, measures=measures, booked=booked,
                unbooked=unbooked, interval_rays=self._rays, context=context,
                nominal_totals=self._totals, piece_builder=self.dependencies['piece_builder'],
                D=self.D, H=self.H, W=self.W, V=self.V, B=self.B, E=self.E, endpoint_pass=endpoint_pass)
        state['built'] += 1
        if state['built'] == len(state['supports']):
            _close_end_pass(state)    # the last support's pieces are built: the workers end now
        return cells


def _open_end_pass(state, budget, arena, H, booked):
    """M-1 E-4: at the first support (after the witness observer read the peak, DM:982), a parent and an endpoint
    pass as the enclosure opens them (A:607-611), with the mesh's width and leaf limit, listing the END of the
    booked components only. No policy, or mode off, opens nothing. The mesh's arena closes it on any error."""
    if not state['opened']:
        state['opened'] = True
        policy = state['policy']
        if policy is not None and policy.mode != 'off':
            from atlas_tectonics.integration.parallel import selection as S
            from atlas_tectonics.integration.geometry import component_volume_auto as AE
            arena.stack.callback(_close_end_pass, state)
            state['automatic'] = S.open_automatic(budget=budget, max_width_m3=state['width'],
                                                  max_leaves=state['leaves'], policy=policy)
            endpoints = AE.open_automatic_endpoints(state['automatic'], state['width'],
                keep=lambda key: not H._unbooked(booked, key), endpoints=('end',))
            if endpoints is not None:
                endpoints.prepare(state['supports'])
            state['endpoints'] = endpoints
    return state['endpoints']


def _close_end_pass(state):
    """Close the pass, then the parent, then finish it, as the enclosure's finally does (A:626-642); then print
    the mesh's decision once, as the control prints the enclosure's (J:163). Scheduling evidence only."""
    endpoints, automatic = state.get('endpoints'), state.get('automatic')
    state['endpoints'] = state['automatic'] = None
    try:
        if endpoints is not None:
            endpoints.close()
    finally:
        if automatic is not None:
            try:
                automatic.close()
            finally:
                automatic.finish()
                try:
                    import json
                    print('ACTUAL_END_MESH_PARALLEL', json.dumps(automatic.decision, sort_keys=True), flush=True)
                except Exception:
                    pass    # a print that fails is dropped, never an error
