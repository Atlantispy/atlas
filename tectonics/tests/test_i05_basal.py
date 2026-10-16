"""I05.3 basal exchange: the package reproduction equals the I01 basal-closure tool (R-5, no tool moved).

The tool is imported here only, as the I01 tests import it; production code never imports it. Equal inputs must give
bitwise-equal proposals and the same refusal codes, and a refused input is never modified. The accounts are the tool's
own manufactured control accounts (declared states, not flow solutions). The I05-9 units rule converts a proposal into
whole-stock I02 Transfers with an authored test length and commits one through a real I02 ledger.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
from fractions import Fraction
import math
from pathlib import Path
import sys
import tempfile
import unittest

from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_i01_basal_closure as tool                       # noqa: E402
import i02_workflow_fixtures as F                            # noqa: E402

from atlas_tectonics import integration_basal as B          # noqa: E402
from atlas_tectonics import integration_ledger as L, integration_state as I   # noqa: E402

SPEC = tool.load_case()
RET = tool.retained_inputs()
PAR, CFG, SIDE, DT = tool.reference_numbers(SPEC)
W, ZB, HL = CFG['width_m'], CFG['base_depth_m'], CFG['lithosphere_thickness_m']


def outcome(function, *args, **kwargs):
    """('ok', result) or ('refused', code), for either implementation."""
    try:
        return 'ok', function(*args, **kwargs)
    except (tool.Refusal, B.BasalRefused) as exc:
        return 'refused', exc.code


def box(**changes):
    return tool.box_account(SPEC, RET, width=W, depth=ZB, dt=DT, parent='i05-parity', **changes)


def strip(lam1, *, depth=ZB, outgoing=None):
    face = tool.strip_open_base(route='open_base', reference_width_m=1e5, base_depth_m=depth,
                                lithosphere_thickness_m=HL, stretch_start=1.0, stretch_end=lam1)
    state = None if outgoing is None else (1600.0, [1590.0, 1610.0])
    return tool.strip_account(SPEC, RET, face, depth=depth, dt=DT, parent='i05-strip', outgoing=outgoing,
                              asthenosphere_state=state)


class StripParity(unittest.TestCase):
    def test_strip_open_base_outputs_and_codes(self):
        pairs = [(1.0, 1.2), (1.0, 1.25), (1.0, 0.9), (1.0, 0.875), (0.625, 1.0), (1.0, 0.625), (0.6, 1.0),
                 (1.0, 0.6), (1.0, 1.0), (1.0, 1.5), (0.5, 1.0), (1.0, math.nan), (True, 1.0), ('1', 1.0)]
        depths = [HL, ZB, 160000.0, math.nextafter(160000.0, 0.0), 0.5*HL, -1.0]
        cases = [dict(route='open_base', reference_width_m=1e5, base_depth_m=z, lithosphere_thickness_m=HL,
                      stretch_start=a, stretch_end=b) for z in depths for a, b in pairs]
        cases += [dict(route='closed', reference_width_m=1e5, base_depth_m=ZB, lithosphere_thickness_m=HL,
                       stretch_start=1.0, stretch_end=1.2),
                  dict(route='open_base', reference_width_m=0.0, base_depth_m=ZB, lithosphere_thickness_m=HL,
                       stretch_start=1.0, stretch_end=1.2)]
        codes = set()
        for kwargs in cases:
            expected, got = outcome(tool.strip_open_base, **kwargs), outcome(B.strip_open_base, **kwargs)
            self.assertEqual(got, expected, kwargs)
            if got[0] == 'refused':
                codes.add(got[1])
        self.assertEqual(codes, {B.NO_LAYER, B.WINDOW, B.INVALID, B.CLOSED})

    def test_thermal_condition_table(self):
        for kind in ('base', 'side', 'surface'):
            for mesh in B.MESHES:
                for flow in ('inflow', 'outflow', 'impermeable'):
                    self.assertEqual(B.thermal_condition(kind, mesh, flow), tool.thermal_condition(kind, mesh, flow))
        self.assertEqual(B.NO_CONDUCTION, tool.NO_CONDUCTION)

    def test_volume_account(self):
        cases = [(1e10, 1.2e10, [1e9, 1e9], [2e9], []), (1e10, 1e10, [0.0], [1e9], [1e9]),
                 (1e10, 0.9e10, [-0.5e9, -0.5e9], [], [1e9]), (1e10, 1.2e10, [1e9], [2e9], []),
                 (1e10, 1.2e10, [2e9], [2e9], [1e3]), (-1.0, 1.0, [], [], []), (1e10, 1e10, [math.inf], [], [])]
        for args in cases:
            self.assertEqual(outcome(B.volume_account, *args), outcome(tool.volume_account, *args), args)


class ProposalParity(unittest.TestCase):
    def accounts(self):
        layer = W*(ZB-HL)
        reversed_volume = tool.per_aspect_year(PAR['reversed']['base_outward_velocity_m_per_aspect_year'],
                                               CFG['aspect_year_s'])*W*DT
        yield 'constant volume', box(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT)
        yield 'moving surface', box(inflow_volume=reversed_volume, surface_swept=reversed_volume)
        yield 'base outflow', box(base_outflow=(reversed_volume, 1605.0), surface_swept=-reversed_volume,
                                  asthenosphere_state=(1600.0, [1590.0, 1610.0]))
        yield 'cohort overdraft', box(surface_swept=-1.01*layer, base_outflow=(1.01*layer, CFG['base_temperature_k']))
        yield 'strip extension', strip(1.2)
        yield 'strip compression', strip(0.9, outgoing=1605.0)
        yield 'strip at the lithosphere base', strip(1.2, depth=HL)
        yield 'datum shifted', tool.shift_datum(box(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT), 1273.0)

    def test_proposals_are_bitwise_equal(self):
        refused = 0
        for name, account in self.accounts():
            before = copy.deepcopy(account)
            expected, got = outcome(tool.propose_interval, account), outcome(B.propose_interval, account)
            self.assertEqual(got, expected, name)
            self.assertEqual(account, before, name)
            refused += got[0] == 'refused'
        self.assertEqual(refused, 1)                          # the cohort overdraft only

    def test_every_account_refusal_has_the_tool_code(self):
        account = box(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT)
        gravity = account['interior']['gravity_work_j']
        stored = account['sources']['exterior-asthenosphere']['energy_j']
        start = account['domain']['volume_start_m2']
        doubled = [(('domain', 'cohorts', name, key), 2*item[key]) for name, item in account['domain']['cohorts'].items()
                   for key in ('mass_kg', 'energy_j')]
        cases = [
            [(('streams', 0, 'volume_m2'), math.nan)], [(('streams', 0, 'volume_m2'), -1.0)],
            [(('interval_s',), [DT, 0.0])], [(('extra',), 1)], [(('streams', 1, 'temperature_k'), 1700.0)],
            [(('segments', 'left', 'mesh'), 'material')],
            [(('streams', 1), {'segment': 'left', 'direction': 'in', 'volume_m2': 1.0,
                               'source': 'exterior-asthenosphere'})],
            [(('conduction_in_j', 'top'), tool.DELETE)], [(('interior', 'latent_j'), 1.0)],
            [(('interior', 'heat_fraction'), 1.5)], [(('interior', 'gravity_work_j'), gravity*(1+1e-6))],
            [(('boundary_work_in_j', 'top'), 1.0)], [(('segments', 'base', 'swept_volume_m2'), 1.0)],
            [(('domain', 'volume_end_m2'), start+1e3)],
            [(('sources', 'exterior-asthenosphere', 'temperature_kind'), 'potential')],
            [(('sources', 'exterior-asthenosphere', 'energy_j'), stored*1.001)],
            [(('sources', 'exterior-asthenosphere', 'datum_k'), 0.0)],
            [(('domain', 'cohorts', 'asthenosphere-initial', 'datum_k'), 0.0)],
            [(('materials', 'asthenosphere', 'role'), 'oceanic_crust')],
            [(('materials', 'asthenosphere', 'density_kg_m3'), '3300')],
            [(('streams', 0), {'segment': 'base', 'direction': 'in', 'volume_m2': 1.0,
                               'source': 'exterior-asthenosphere'}), (('streams', 1, 'segment'), 'base')],
            doubled, [(('conduction_in_j', 'left'), 1e12)], [(('law',), 'atlas.other')],
            [(('receivers',), ['exterior-asthenosphere'])],
            [(('sources', 'exterior-asthenosphere', 'phase'), 'partially_molten')],
            [(('streams', 1, 'receiver'), 'nowhere')],
            [(('interior', 'gravity_work_j'), tool.DELETE)],
        ]
        codes = set()
        for changes in cases:
            item = tool.mutated(account, *changes)
            before = copy.deepcopy(item)
            expected, got = outcome(tool.propose_interval, item), outcome(B.propose_interval, item)
            self.assertEqual(got, expected, changes)
            self.assertEqual(got[0], 'refused', changes)
            self.assertEqual(item, before, changes)
            codes.add(got[1])
        self.assertEqual(len(codes), 15)

    def test_exhaustion_is_exact_and_joint(self):
        volume = tool.per_aspect_year(PAR['reversed']['base_outward_velocity_m_per_aspect_year'],
                                      CFG['aspect_year_s'])*W*DT
        account = box(inflow_volume=volume, surface_swept=volume)
        del account['boundary_work_in_j'], account['interior']['gravity_work_j']
        ast = B.materials_of(account['materials'])['asthenosphere']
        per_kg = ast.specific_energy(CFG['base_temperature_k'], CFG['datum_k'])
        demand = ast.density_kg_m3*volume

        def stocked(mass):
            return tool.mutated(account, (('sources', 'exterior-asthenosphere', 'mass_kg'), mass),
                                (('sources', 'exterior-asthenosphere', 'energy_j'), mass*per_kg))
        exact = B.propose_interval(stocked(demand))
        self.assertEqual(exact, tool.propose_interval(stocked(demand)))
        row = exact['sources']['exterior-asthenosphere']
        self.assertEqual((row['remaining_mass_kg'], row['remaining_energy_j']), (0.0, 0.0))
        short = stocked(math.nextafter(demand, 0.0))
        self.assertEqual(outcome(B.propose_interval, short), ('refused', B.EXHAUSTED))
        split = stocked(0.75*demand)
        split['segments'] = {'base-west': {'kind': 'base', 'mesh': 'fixed', 'swept_volume_m2': 0.0},
                             'base-east': {'kind': 'base', 'mesh': 'fixed', 'swept_volume_m2': 0.0},
                             **{k: v for k, v in split['segments'].items() if k != 'base'}}
        split['conduction_in_j'] = {'base-west': 0.0, 'base-east': 0.0,
                                    **{k: v for k, v in split['conduction_in_j'].items() if k != 'base'}}
        split['streams'] = [{'segment': name, 'direction': 'in', 'volume_m2': volume/2,
                             'source': 'exterior-asthenosphere'} for name in ('base-west', 'base-east')]
        self.assertEqual(outcome(B.propose_interval, split), ('refused', B.EXHAUSTED))
        self.assertEqual(outcome(tool.propose_interval, split), ('refused', tool.EXHAUSTED))


class EndpointParity(unittest.TestCase):
    def test_supplied_endpoint_and_foreign_proposals(self):
        for account in (box(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT), strip(1.2), strip(0.9, outgoing=1605.0)):
            proposal = B.propose_interval(account)
            mass, energy = tool.end_state_of(account, proposal)
            volume = proposal['volume']['end_m2']
            self.assertEqual(B.diagnose_endpoint(account, proposal, mass, energy, volume),
                             tool.diagnose_endpoint(account, proposal, mass, energy, volume))
            other = tool.mutated(account, (('parent',), 'someone-else'))
            self.assertEqual(outcome(B.diagnose_endpoint, other, proposal, mass, energy, volume),
                             ('refused', B.FOREIGN))
            edited = copy.deepcopy(proposal)
            edited['domain']['energy_j'] *= 1+1e-9
            self.assertEqual(outcome(B.diagnose_endpoint, account, edited, mass, energy, volume),
                             ('refused', B.FOREIGN))
            for args in ((dict(mass, **{next(iter(mass)): next(iter(mass.values()))*(1+1e-9)}), energy, volume),
                         (mass, energy, volume*(1+1e-9)), (mass, energy*(1+1e-6)+1e6, volume)):
                self.assertEqual(outcome(B.diagnose_endpoint, account, proposal, *args),
                                 outcome(tool.diagnose_endpoint, account, proposal, *args))
                self.assertEqual(outcome(B.diagnose_endpoint, account, proposal, *args)[1], B.ENDPOINT)


# Authored test inputs, not IN-06 values: the attached-window length and the caloric basis the stocks declare.
LS = 1000.0
LS_SOURCE = 'test: authored attached-window length for the I05-9 units check, not an IN-06 value'
CALORIC = 'test: caloric Cp (T - T_ref) at the I01 datum T_ref = 273 K (atlas.basal-inflow-closure.v1)'
EXTERIORS = (('inflow', 'source'), ('outflow', 'sink'))


def strip_stocks(account):
    """The I02 fixture's two stocks with one component, the strip's own 'asthenosphere' (the fixture catalogue holds
    it), in the caloric basis: store-a holds L_s times the initial asthenosphere cohort (kg, J); store-b stays apart."""
    cohort = account['domain']['cohorts']['asthenosphere-initial']
    return F.reservoirs(component_ids=('asthenosphere',), component_mass_kg=[[LS*cohort['mass_kg']], [1.]],
                        enthalpy_j=[LS*cohort['energy_j'], 4.], enthalpy_source=CALORIC)


class StripTransfers(unittest.TestCase):
    """I05-9: a per-metre proposal becomes whole-stock I02 Transfers only through a declared, labelled L_s, for the
    I02 interval it is committed over (start and duration bound), once per strip and interval."""

    @classmethod
    def setUpClass(cls):
        with threadpool_limits(limits=1, user_api='blas'):
            cls.prepared = F.preparation()

    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.state = F.root(stocks=strip_stocks(strip(1.2)), basis=CALORIC, prepared=self.prepared)
        self.store = F.store(self.folder/'ledger'/'ledger.sqlite')
        self.addCleanup(self.store.close)
        self.ledger, self.root = L.Ledger.create(self.store, self.state, exteriors=EXTERIORS)
        self.exchange = self.ledger.exchange(self.root)

    def times(self, ledger=None, start=0, end=1):
        ledger = self.ledger if ledger is None else ledger
        steps, step_s, origin = ledger._schedule()
        times = L._step_times(origin, step_s, steps)
        return [times[start], times[end]]

    def timed(self, account, start=0, end=1, ledger=None):
        """The account over the I02 interval (start, end] of the ledger's own clock."""
        return tool.mutated(account, (('interval_s',), self.times(ledger, start, end)))

    def convert(self, proposal, account, **changes):
        """strip_transfers with the strip's exterior mappings for exactly the rows the proposal holds."""
        held = proposal if type(proposal) is dict else {}
        values = dict(account=account, ledger=self.ledger, parent=self.root, end_step=1, attached_window_length_m=LS,
                      length_source=LS_SOURCE, producer='tests/test_i05_basal.py', basis=CALORIC,
                      sources={k: v for k, v in {'exterior-asthenosphere': 'inflow'}.items()
                               if k in held.get('sources', {})},
                      receivers={k: v for k, v in {'exterior-asthenosphere-sink': 'outflow'}.items()
                                 if k in held.get('receivers', {})}, domain_node='store-a')
        values.update(changes)
        return B.strip_transfers(proposal, **values)

    def refused(self, code, pattern, proposal, account, **changes):
        before = copy.deepcopy(proposal)
        with self.assertRaisesRegex(B.BasalRefused, pattern) as caught:
            self.convert(proposal, account, **changes)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(proposal, before)

    def test_whole_stock_quantities_are_ls_times_the_per_metre_proposal(self):
        account = self.timed(strip(1.2))
        extension = B.propose_interval(account)
        before = copy.deepcopy(extension)
        (inflow,) = self.convert(extension, account)
        row = extension['sources']['exterior-asthenosphere']
        self.assertEqual(inflow.component_mass_kg, (('asthenosphere', LS*-row['components_kg']['asthenosphere']),))
        self.assertEqual(inflow.enthalpy_j, LS*-row['energy_j'])
        cohort = next(iter(extension['domain']['new_cohorts'].values()))
        self.assertEqual((inflow.component_mass_kg[0][1], inflow.enthalpy_j),
                         (LS*cohort['mass_kg'], LS*cohort['energy_j']))           # one component, fraction 1
        self.assertEqual((inflow.label, inflow.donor, inflow.receiver, inflow.basis, inflow.units),
                         ('basal/%s/0-1/in/exterior-asthenosphere' % B.strip_identity(account), 'inflow', 'store-a',
                          CALORIC,
                          (('enthalpy', 'J'), ('mass', 'kg'))))
        self.assertEqual(inflow.producer, f'tests/test_i05_basal.py (L_s {LS!r} m: {LS_SOURCE})')
        self.assertEqual(extension, before)
        self.assertEqual(self.convert(extension, account), (inflow,))             # deterministic
        shortening_account = self.timed(strip(0.9, outgoing=1605.0))
        shortening = B.propose_interval(shortening_account)
        (outflow,) = self.convert(shortening, shortening_account)
        part = shortening['receivers']['exterior-asthenosphere-sink']
        self.assertEqual((outflow.label, outflow.donor, outflow.receiver),
                         ('basal/%s/0-1/out/exterior-asthenosphere-sink' % B.strip_identity(shortening_account),
                          'store-a', 'outflow'))
        self.assertEqual(outflow.component_mass_kg, (('asthenosphere', LS*part['components_kg']['asthenosphere']),))
        self.assertEqual(outflow.enthalpy_j, LS*part['energy_j'])
        for length in (None, 0.0, -LS, math.nan, math.inf, True, '1000'):
            with self.subTest(length=length):
                self.refused(B.INVALID, 'attached-window length L_s', extension, account,
                             attached_window_length_m=length)
        for source in ('', '  ', None):
            with self.subTest(source=source):
                self.refused(B.INVALID, 'attached-window length source', extension, account, length_source=source)
        for missing in ('attached_window_length_m', 'account', 'ledger', 'parent'):
            values = dict(account=account, ledger=self.ledger, parent=self.root, end_step=1,
                          attached_window_length_m=LS, length_source=LS_SOURCE, producer='p', basis=CALORIC,
                          sources={}, receivers={}, domain_node='store-a')
            del values[missing]
            with self.assertRaises(TypeError):                                    # never defaulted
                B.strip_transfers(extension, **values)

    def test_the_converted_inflow_commits_once_through_the_i02_ledger(self):
        account = self.timed(strip(1.2))
        (inflow,) = self.convert(B.propose_interval(account), account)
        s1 = I.Continuation(self.state).advance(self.state, 1).state
        start = self.exchange.inventory
        old_kg, old_j = float(start.component_mass_kg[0, 0]), float(start.enthalpy_j[0])
        commit = self.ledger.commit(self.root, (s1,), (inflow,))
        after = self.ledger.exchange(commit)
        mass, energy = after.inventory.component_mass_kg, after.inventory.enthalpy_j
        moved, heat = inflow.component_mass_kg[0][1], inflow.enthalpy_j
        self.assertEqual((float(mass[0, 0]), float(energy[0])), (old_kg+moved, old_j+heat))   # one correct rounding
        exact = after.descriptor()['exact']
        self.assertEqual(Fraction(float(mass[0, 0]))-Fraction(old_kg),
                         Fraction(moved)+Fraction(exact['rounding_kg'][0]))
        self.assertEqual(Fraction(float(energy[0]))-Fraction(old_j), Fraction(heat)+Fraction(exact['rounding_j']))
        self.assertEqual((float(mass[1, 0]), float(energy[1])), (1., 4.))         # store-b untouched
        self.assertEqual((Fraction(exact['supplied_kg'][0][0]), Fraction(exact['supplied_j'][0])),
                         (Fraction(moved), Fraction(heat)))                       # the named source, exactly
        self.assertEqual((exact['supplied_kg'][1], exact['supplied_j'][1]), (['0/1'], '0/1'))
        closure = after.closure()
        self.assertTrue(closure['identity_exact'])
        self.assertEqual((closure['component_residual_kg'], closure['enthalpy_residual_j']),
                         (list(after.rounding_kg), after.rounding_j))
        record = commit.metadata()['transfers'][0]
        self.assertEqual((record['label'], record['producer'], record['units'], record['basis']),
                         (inflow.label, inflow.producer, L.UNITS, CALORIC))
        self.assertEqual(self.ledger.head().key, commit.key)

    def test_a_proposal_is_bound_to_its_i02_interval_and_booked_once_per_strip(self):
        """basal-01: the proposal's interval must be the I02 interval (start and duration) it is committed over, and
        a second proposal for the same strip in one interval is refused (its transfers carry the strip's labels)."""
        bare = strip(1.2)
        proposal = B.propose_interval(bare)
        self.assertNotEqual(proposal['interval_s'], self.times())
        self.refused(B.FOREIGN, 'not the I02 interval', proposal, bare)            # the I01 account's own clock
        two = self.timed(strip(1.2), 0, 2)                                          # twice the step's duration
        self.refused(B.FOREIGN, 'not the I02 interval', B.propose_interval(two), two)
        later = tool.mutated(strip(1.2), (('interval_s',), [self.times()[1], self.times(start=1, end=2)[1]]))
        self.refused(B.FOREIGN, 'not the I02 interval', B.propose_interval(later), later)
        account = self.timed(strip(1.2))
        once = self.convert(B.propose_interval(account), account)
        again = self.convert(B.propose_interval(account), account)
        s1 = I.Continuation(self.state).advance(self.state, 1).state
        with self.assertRaisesRegex(L.ExchangeRefused, 'already applied'):
            self.ledger.commit(self.root, (s1,), once+again)
        self.assertEqual(self.ledger.head().key, self.root.key)
        commit = self.ledger.commit(self.root, (s1,), once)
        with self.assertRaisesRegex(B.BasalRefused, 'parent'):                      # start: the parent commit's step
            self.convert(B.propose_interval(account), account, parent=commit, end_step=1)
        # The next interval converts the same strip again under its own labels.
        following = self.timed(strip(1.2), 1, 2)
        (next_inflow,) = self.convert(B.propose_interval(following), following, parent=commit, end_step=2)
        self.assertEqual(next_inflow.label, 'basal/%s/1-2/in/exterior-asthenosphere' % B.strip_identity(following))
        self.assertEqual(B.strip_identity(following), B.strip_identity(account))     # the interval is not in it
        # RB-1: the labels are the proposal's own row names and the account's strip identity, never the caller's
        # names, so the same proposal converted again under another stock node or another exterior collides too.
        ledger, root = self.two_sources()
        node = self.convert(B.propose_interval(account), account, ledger=ledger, parent=root, domain_node='store-b')
        exterior = self.convert(B.propose_interval(account), account, ledger=ledger, parent=root,
                                sources={'exterior-asthenosphere': 'inflow2'})
        plain = self.convert(B.propose_interval(account), account, ledger=ledger, parent=root)
        s1 = I.Continuation(self.state).advance(self.state, 1).state
        for second in (node, exterior):
            with self.assertRaisesRegex(L.ExchangeRefused, 'already applied'):
                ledger.commit(root, (s1,), plain+second)
        self.assertEqual(ledger.head().key, root.key)

    def two_sources(self):
        """A ledger of the same stocks with two declared source exteriors."""
        store = F.store(self.folder/'two-sources'/'ledger.sqlite')
        self.addCleanup(store.close)
        return L.Ledger.create(store, self.state, exteriors=(('inflow', 'source'), ('inflow2', 'source'),
                                                              ('outflow', 'sink')))

    def test_structurally_absent_components_are_filled_with_an_explicit_zero(self):
        """Ruling (a): under stocks of the strip's components plus one that no feeding material declares, each row is
        filled with an explicit 0.0 kg of it (bound into the transfer record); a component a feeding material
        declares is never filled."""
        stocks = F.reservoirs(component_ids=('asthenosphere', 'upper-crust'),
                              component_mass_kg=[[LS*strip(1.2)['domain']['cohorts']['asthenosphere-initial']
                                                  ['mass_kg'], 0.], [1., 1.]],
                              enthalpy_j=[LS*strip(1.2)['domain']['cohorts']['asthenosphere-initial']['energy_j'], 4.],
                              enthalpy_source=CALORIC)
        state = F.root(stocks=stocks, basis=CALORIC, prepared=self.prepared)
        store = F.store(self.folder/'two'/'ledger.sqlite')
        self.addCleanup(store.close)
        ledger, root = L.Ledger.create(store, state, exteriors=EXTERIORS)
        account = self.timed(strip(1.2), ledger=ledger)
        (inflow,) = self.convert(B.propose_interval(account), account, ledger=ledger, parent=root)
        row = B.propose_interval(account)['sources']['exterior-asthenosphere']
        self.assertEqual(inflow.component_mass_kg, (('asthenosphere', LS*-row['components_kg']['asthenosphere']),
                                                    ('upper-crust', 0.0)))
        self.assertIn('zero-filled: upper-crust', inflow.producer)
        commit = ledger.commit(root, (I.Continuation(state).advance(state, 1).state,), (inflow,))
        self.assertEqual(commit.metadata()['transfers'][0]['component_mass_kg']['upper-crust'], 0.0)
        self.assertTrue(ledger.exchange(commit).closure()['identity_exact'])
        declared = tool.mutated(account, (('materials', 'asthenosphere', 'components'),
                                          {'asthenosphere': 0.5, 'upper-crust': 0.5}))
        self.assertEqual(sorted(B.propose_interval(declared)['sources']['exterior-asthenosphere']['components_kg']),
                         ['asthenosphere', 'upper-crust'])
        self.convert(B.propose_interval(declared), declared, ledger=ledger, parent=root)     # nothing to fill

    def test_a_declared_component_is_never_filled(self):
        """RB-4: a row lacking a component that a material feeding it declares is refused, not zero-filled (the
        guard behind ruling (a); a recomputed proposal cannot reach it, so _scaled is called directly)."""
        row = {'components_kg': {'asthenosphere': -1.0}, 'energy_j': -1.0}
        with self.assertRaisesRegex(B.BasalRefused, 'feeding it declares') as caught:
            B._scaled('source s', row, ('asthenosphere', 'upper-crust'), LS, True, {'asthenosphere', 'upper-crust'})
        self.assertEqual(caught.exception.code, B.INVALID)
        masses, _, filled = B._scaled('source s', row, ('asthenosphere', 'upper-crust'), LS, True, {'asthenosphere'})
        self.assertEqual((masses, filled), ((('asthenosphere', LS), ('upper-crust', 0.0)), ['upper-crust']))

    def test_exhaustion_and_mismatches_refuse_before_any_transfer(self):
        account = self.timed(strip(1.2))
        demand = -B.propose_interval(account)['sources']['exterior-asthenosphere']['mass_kg']
        ast = B.materials_of(account['materials'])['asthenosphere']
        per_kg = ast.specific_energy(CFG['base_temperature_k'], CFG['datum_k'])

        def stocked(mass):
            return tool.mutated(account, (('sources', 'exterior-asthenosphere', 'mass_kg'), mass),
                                (('sources', 'exterior-asthenosphere', 'energy_j'), mass*per_kg))
        exact = B.propose_interval(stocked(demand))
        self.assertEqual(exact['sources']['exterior-asthenosphere']['remaining_mass_kg'], 0.0)
        self.assertEqual(len(self.convert(exact, stocked(demand))), 1)            # exactly exhausted still converts
        # One ulp short: the I01 proposal refuses, so no proposal and no Transfer can exist.
        short = stocked(math.nextafter(demand, 0.0))
        self.assertEqual(outcome(B.propose_interval, short), ('refused', B.EXHAUSTED))
        self.refused(B.EXHAUSTED, 'holds', exact, short)
        # A proposal is converted only as the declared account gives it: an edited row (the moved components, the
        # energy, the mass or the checked remainder) refuses, so what is checked is what moves.
        source = ('sources', 'exterior-asthenosphere')
        for path, value in ((source+('components_kg', 'asthenosphere'),
                             2*exact['sources']['exterior-asthenosphere']['components_kg']['asthenosphere']),
                            (source+('energy_j',), 3*exact['sources']['exterior-asthenosphere']['energy_j']),
                            (source+('mass_kg',), -1.0), (source+('remaining_mass_kg',), -1.0)):
            edited = copy.deepcopy(exact)
            row = edited
            for key in path[:-1]:
                row = row[key]
            row[path[-1]] = value
            with self.subTest(path=path):
                self.refused(B.FOREIGN, 'declared account', edited, stocked(demand))

        def with_components(parts):
            changed = tool.mutated(account, (('materials', 'asthenosphere', 'components'), parts))
            return B.propose_interval(changed), changed
        proposal = B.propose_interval(account)
        shortening_account = self.timed(strip(0.9, outgoing=1605.0))
        shortening = (B.propose_interval(shortening_account), shortening_account)
        plain = (proposal, account)
        cases = [
            ('caloric basis other than the stocks', B.DATUM, 'caloric basis', plain, dict(basis=F.BASIS)),
            ('relabelled component', B.INVALID, 'components', with_components({'Asthenosphere': 1.0}), {}),
            ('component set other than the stocks', B.INVALID, 'components',
             with_components({'asthenosphere': 0.5, 'olivine': 0.5}), {}),
            ('committed status', B.FOREIGN, 'uncommitted', (dict(proposal, status='COMMITTED'), account), {}),
            ('another law', B.FOREIGN, 'uncommitted', (dict(proposal, law='atlas.other'), account), {}),
            ('another account', B.FOREIGN, 'declared account', (proposal, shortening_account), {}),
            ('unmapped source', B.INVALID, 'map to no declared exterior', plain, dict(sources={})),
            ('a mapping for a row the proposal does not hold', B.INVALID, 'holds no such row', plain,
             dict(receivers={'exterior-asthenosphere-sink': 'outflow'})),         # an inflow-only proposal
            ('undeclared exterior', B.INVALID, 'undeclared exterior', plain,
             dict(sources={'exterior-asthenosphere': 'nowhere'})),
            ('a sink supplying', B.INVALID, 'never supplies', plain,
             dict(sources={'exterior-asthenosphere': 'outflow'})),
            ('outflow into a source', B.OUTFLOW, 'never returns to a source', shortening,
             dict(receivers={'exterior-asthenosphere-sink': 'inflow'})),
            ('domain node not a stock', B.INVALID, 'not an attached stock', plain, dict(domain_node='inflow')),
            ('not an I02 ledger', B.INVALID, 'Ledger', plain, dict(ledger=self.exchange)),
            ('an end step before the start', B.INVALID, 'whole global steps', plain, dict(end_step=0)),
        ]
        for name, code, pattern, (item, given), changes in cases:
            with self.subTest(name):
                self.refused(code, pattern, item, given, **changes)
        self.assertEqual(self.ledger.head().key, self.root.key)                  # nothing reached the ledger


if __name__ == '__main__':
    unittest.main()
