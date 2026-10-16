"""I04b stage-finish controls: Case A frame invariance, Case B direction and length, the w and side disclosures, the
time oracle and the coupled time refinement, reopen parity on an I02 ledger, and the lune/zigzag fixtures with their
predeclared refusals. Criteria are tectonics/cases/i04_controls_v1.json part_b, fixed before running; numbers are
written to the JSON file named by ATLAS_I04_CONTROLS_REPORT when that variable is set (they are not acceptance).
Executed in the scratch candidate on Windows/CPython 3.12.14 (candidate controls, not acceptance). Heavy: several
minutes; not part of a quick profile.
SPDX-License-Identifier: AGPL-3.0-only
"""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np
from scipy.integrate import solve_ivp
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_feedback as B     # noqa: E402
from atlas_tectonics import integration_ledger as L       # noqa: E402
from atlas_tectonics import integration_ports as P        # noqa: E402
from atlas_tectonics import integration_strength as G     # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i02_workflow_fixtures as F2                          # noqa: E402
import i03_fixtures as F                                    # noqa: E402
import i04_strength_fixtures as Z                           # noqa: E402

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
CASE = Z.CASE
TOL = CASE['tolerances']
REPORT = {}
RIDGE, TRENCH = 'boundary-m00', 'boundary-m04'
ORACLE_T_MYR, COUPLED_T_MYR, LEVELS = .2, .4, (4, 8, 16)


def tearDownModule():
    path = os.environ.get('ATLAS_I04_CONTROLS_REPORT')
    if path:
        Path(path).write_bytes((json.dumps(B._plain(REPORT), indent=2, sort_keys=True)+'\n').encode('utf-8'))


def v_rel(omega):
    """Relative speed at the equator (north minus south, m/s) of an axisymmetric twin balance."""
    omega = np.asarray(omega, dtype=float)
    return float(omega[0][2]-omega[1][2])*Z.RADIUS_M


def summary(result):
    """What a disclosure or direction control reads from one coupled interval."""
    belt = result.balance.belt
    name = sorted(belt['boundaries'])[0]
    increments = [max(v) for _, v in result.advance.increments] or [0.]
    boundary = belt['boundaries'][name]
    return dict(v_rel_mm_yr=v_rel(result.motion_port.omega_rad_s)*Z.MYR*1e3/1e6,
                omega_rad_s=result.motion_port.omega_rad_s.tolist(),
                peak_resultant_n_m=boundary['peak_resultant_n_m'],
                plastic_share=boundary['plastic_share'], max_dkappa=max(increments),
                raw_kappa_width_2sigma_m=(boundary['raw_kappa_width_2sigma_over_thickness'] or 0.)*Z.THICKNESS_M,
                increment_width_2sigma_m=boundary['increment_width_2sigma_m'],
                iterations=result.report['iterations'], axis_tilt=result.report['axis_tilt'],
                pieces_per_face=result.report['pieces_per_face']['max'],
                increments=[h['increments'] for h in result.report['history']][-1])


def one(state, moving, inputs, years=Z.INTERVAL_MYR):
    return B.coupled_interval(state, moving, inputs, interval=Z.interval(state, years))


def relative_change(a, b):
    return abs(a-b)/max(abs(a), abs(b))


class CaseA(unittest.TestCase):
    """Frame invariance (part_b case_a): a tilted copy of the twin world with the tilted torque gives the rotated
    omega and the same increments within cond(M+J) x 1e-10 + 2e-11."""

    def test_a_tilted_world_gives_the_rotated_motion_and_the_same_increments(self):
        state, moving = Z.twin_case()
        base = one(state, moving, Z.inputs())
        tilted_state, tilted_moving = Z.twin_case(tilt=F.TILT)
        tilted = one(tilted_state, tilted_moving,
                     Z.inputs(forcing=Z.forcing(axis=tuple(float(x) for x in F.axis(F.TILT)))))
        cond = max(base.balance.belt['condition'] or 1., tilted.balance.belt['condition'] or 1.)
        bound = cond*1e-10+2e-11
        expected = F.TILT.apply(base.motion_port.omega_rad_s)
        omega_error = float(np.max(np.abs(tilted.motion_port.omega_rad_s-expected)))/float(np.max(np.abs(expected)))
        a, b = dict(base.advance.increments), dict(tilted.advance.increments)
        faces = {face: v for (face, _), v in a.items()}, {face: v for (face, _), v in b.items()}
        self.assertEqual(set(faces[0]), set(faces[1]))
        scale = max(max(v) for v in faces[0].values())
        increment_error = max(float(np.max(np.abs(np.subtract(faces[0][f], faces[1][f])))) for f in faces[0])/scale
        REPORT['case_a_frame'] = dict(omega_relative=omega_error, increment_relative=increment_error, bound=bound,
                                      condition=cond)
        self.assertLessEqual(omega_error, bound)
        self.assertLessEqual(increment_error, bound)


class CaseB(unittest.TestCase):
    """Direction (part_b case_b_direction), the w and side disclosures, mesh refinement and the ell sensitivity.

    Each predeclared criterion is its own test. The two that failed are kept, unchanged, as expected failures under
    the coordinator's round-1 rulings (b1, b2): the FAIL stays recorded and is not re-gated."""

    @classmethod
    def setUpClass(cls):
        cls.state, cls.moving = Z.twin_case()
        cls.base = summary(one(cls.state, cls.moving, Z.inputs()))
        cls.runs = dict(cohesion_x2=summary(one(cls.state, cls.moving,
                                                Z.inputs(declaration=Z.declaration(scale_cohesion=2.)))),
                        warmer_100k=summary(one(*Z.twin_case(warmer_k=100.), Z.inputs())),
                        kappa0_2_5=summary(one(*Z.twin_case(kappa=2.5), Z.inputs())),
                        torque_x2=summary(one(cls.state, cls.moving, Z.inputs(2*Z.TORQUE))))
        REPORT['case_b_direction'] = dict(base=cls.base, **cls.runs)
        cls.rows = {rows: summary(one(*Z.twin_case(rows=rows, kappa_profile=True), Z.inputs())) for rows in (2, 4, 8)}
        REPORT['case_b_refinement'] = cls.rows

    def test_each_declared_change_moves_the_speed_the_expected_way(self):
        # the expected-failure sibling's operands exist and are finite (a renamed key must not hide in it)
        self.assertTrue(math.isfinite(self.runs['torque_x2']['plastic_share']))
        self.assertTrue(math.isfinite(self.base['plastic_share']))
        speed = self.base['v_rel_mm_yr']
        self.assertLess(self.runs['cohesion_x2']['v_rel_mm_yr'], speed)
        self.assertGreater(self.runs['warmer_100k']['v_rel_mm_yr'], speed)
        self.assertGreater(self.runs['kappa0_2_5']['v_rel_mm_yr'], speed)
        self.assertGreater(self.runs['torque_x2']['v_rel_mm_yr'], speed)

    @unittest.expectedFailure
    def test_doubling_the_torque_raises_the_plastic_share(self):
        """Predeclared; FAILED (0.676 against 0.702). Expectation withdrawn as an authored error (ruling b1): at
        fixed history the creep layers' work grows as U^(1+1/n) while the plastic layers' stress rises less (a factor
        of 1.38 against 1.45 for the creep layers at 4.5 times the speed), and the localised weakening during the
        faster interval lowers the plastic work further."""
        self.assertGreater(self.runs['torque_x2']['plastic_share'], self.base['plastic_share'])

    def test_the_w_and_side_disclosures_are_reported(self):
        """Required, not gated: dependence on the authored width and on the declared placement."""
        wide = 2*Z.WIDTH_M
        state = Z.crust(Z.twin(width_m=wide))
        doubled = summary(one(state, Z.moving(state), Z.inputs(declaration=Z.declaration(width_m=wide))))
        network = Z.one_sided()
        state = Z.crust(network)
        moving = Z.moving(state)
        both = summary(one(state, moving, Z.inputs()))
        carrier = summary(one(state, moving, Z.inputs(declaration=Z.side_declaration('right'))))
        REPORT['w_disclosure'] = dict(w=self.base, w2=doubled)
        difference = {k: carrier[k]-both[k] for k in ('v_rel_mm_yr', 'peak_resultant_n_m', 'max_dkappa')}
        difference['omega_rad_s'] = (np.asarray(carrier['omega_rad_s'])-np.asarray(both['omega_rad_s'])).tolist()
        REPORT['side_disclosure'] = dict(both=both, carrier=carrier, difference=difference)
        for item in (doubled, both, carrier):
            self.assertTrue(all(math.isfinite(item[k]) for k in ('v_rel_mm_yr', 'peak_resultant_n_m', 'max_dkappa')))

    def test_refinement_of_the_force_speed_and_raw_history_width(self):
        """Rows 2, 4, 8 with the smooth inherited weakness: the change between 4 and 8 rows <= 0.03 on the peak
        resultant, the relative speed and width_2sigma, here the raw-history width (inherited profile plus one
        increment, so it mostly measures the authored input)."""
        for key in ('peak_resultant_n_m', 'v_rel_mm_yr', 'raw_kappa_width_2sigma_m'):
            self.assertLessEqual(relative_change(self.rows[4][key], self.rows[8][key]), TOL['mesh_refinement'], key)
        # the expected-failure sibling's operands exist and are finite
        self.assertTrue(math.isfinite(self.rows[4]['max_dkappa']) and math.isfinite(self.rows[8]['max_dkappa']))

    @unittest.expectedFailure
    def test_refinement_of_the_peak_increment(self):
        """Predeclared; FAILED (7.8% from 4 to 8 rows against 3%), a recorded pre-asymptotic outcome (ruling b2): the
        inherited kappa0 is sampled at row centres, and the cells are coarser than ell (h/ell = 1.25 at 8 rows; I01's
        0.03 was set for h/ell <= 0.25)."""
        self.assertLessEqual(relative_change(self.rows[4]['max_dkappa'], self.rows[8]['max_dkappa']),
                             TOL['mesh_refinement'])

    def test_a_longer_length_widens_the_increment_profile(self):
        """ell 2500 against 5000 m with belt cells < 2500 m (24 rows per side): the increment profile's
        width_2sigma differs by more than 50 m, wider for the larger ell."""
        state, moving = Z.twin_case(rows=24, kappa_profile=True)
        widths = {}
        for ell in (2500., 5000.):
            inputs = Z.inputs(declaration=Z.declaration(ell_m=ell))
            result, term, _, _ = B.solve_at(state, moving, inputs, interval=Z.interval(state),
                                            parent_state_id=state.state_id, evaluation='start')
            line, response = term.lines[0], term.last[1][0]
            self.assertTrue(all(c.cell.length_m < 2500. for c in line.cells))
            y = np.array([(c.cell.y0+c.cell.y1)/2 for c in line.cells])
            h = np.array([float(np.sum(c.prep.weight*p['plastic_rate'])/np.sum(c.prep.weight))*c.cell.length_m
                          for c, p in zip(line.cells, response['points'])])
            centre = float(np.sum(y*h)/np.sum(h))
            widths[ell] = 2*math.sqrt(float(np.sum((y-centre)**2*h)/np.sum(h)))
        REPORT['case_b_length'] = dict(width_2sigma_m=widths, difference_m=widths[5000.]-widths[2500.])
        self.assertGreater(widths[5000.]-widths[2500.], TOL['length_sensitivity_m'])


class ResolvedCaseB(unittest.TestCase):
    """Predeclared adequately resolved successor; historical CaseB assertions above remain unchanged.

    This separate class runs just two complete coupled intervals without CaseB's unrelated direction/disclosure
    setup. The 42/84 choice follows the actual great-circle cell-length bound before either run, not a measured
    favourable mesh. No physics, interval, solver or 3% acceptance setting changes.
    """

    def test_the_resolved_pair_meets_the_original_mesh_bound(self):
        declared = CASE['controls']['case_b_resolved_refinement']
        levels = declared['rows_per_side']
        criteria = declared['criteria']
        self.assertEqual(levels, [42, 84])
        self.assertEqual(criteria['relative_change_bound'], TOL['mesh_refinement'])
        runs = {}
        REPORT['case_b_resolved_refinement'] = dict(declaration=declared, runs=runs)
        with threadpool_limits(limits=1, user_api='blas'):
            for rows in levels:
                started = time.perf_counter()
                state, moving = Z.twin_case(rows=rows, kappa_profile=True)
                cell_sizes = {}

                def check_geometry(label, sphere):
                    support = P.trace_support(sphere.network)
                    lengths = [cell.length_m for edge in range(support.edges)
                               for cell in G.belt_cells(sphere.network, support, edge, Z.WIDTH_M)]
                    cell_sizes[label] = max(lengths)
                    self.assertLessEqual(max(lengths)/Z.ELL_M, criteria['max_cell_over_length'],
                                         (rows, label, max(lengths)/Z.ELL_M))

                check_geometry('start_max_cell_m', state)
                print('Resolved Case B: %d rows per side, max starting h/ell = %.9g; coupled interval starting'
                      % (rows, cell_sizes['start_max_cell_m']/Z.ELL_M), flush=True)
                result = one(state, moving, Z.inputs())
                check_geometry('endpoint_max_cell_m', result.step.state)
                runs[rows] = dict(summary(result), seconds=time.perf_counter()-started,
                                  nominal_cell_m=Z.WIDTH_M/(2*rows), **cell_sizes)
                print('Resolved Case B: %d rows complete in %.3f s, max_dkappa = %.12g'
                      % (rows, runs[rows]['seconds'], runs[rows]['max_dkappa']), flush=True)
        coarse, fine = levels
        changes = {key: relative_change(runs[coarse][key], runs[fine][key]) for key in criteria['quantities']}
        REPORT['case_b_resolved_refinement']['relative_changes'] = changes
        for key, value in changes.items():
            self.assertTrue(math.isfinite(value), key)
            self.assertLessEqual(value, TOL['mesh_refinement'], key)


def oracle_world():
    """The oracle twin: a uniform one-sided carrier belt of one row (one cell per line, the latitude row from -w/R to
    the equator) and the single-layer column, the row one cohort. A uniform belt cannot localise, so no point changes
    yield state over [0, T] (ruling C3(1)); the first, two-row form did (part_b time_oracle)."""
    latitudes = [-60., -30., 30., 60., -math.degrees(Z.WIDTH_M/Z.RADIUS_M)]
    network = Z.twin(latitudes_deg=latitudes, rows=0)
    equator = Z.twin_latitudes(0, Z.WIDTH_M, latitudes).index(0.)

    def cohort_of(face_id):
        if face_id.endswith('south') or face_id.endswith('north'):
            return 'cap-'+face_id[-5:]
        return 'row-1' if int(face_id[-2:]) == equator-1 else 'inherited-'+network.face_plate(face_id)
    state = Z.crust(network, single=True, cohort_of=cohort_of)
    return state, equator


def row_kappa(moving, state, equator):
    """The belt row's largest raw kappa over the pieces on its faces (sub-cohorts differ by ulps)."""
    values = [max(moving.cohort(piece.cohort_id).kappa) for piece in state.material.pieces()
              if not piece.face_id.endswith(('south', 'north')) and int(piece.face_id[-2:]) == equator-1]
    return max(values)


def chain(state, moving, inputs, intervals, years):
    """N coupled intervals over T: (peak kappa gain, cumulative relative rotation, final relative speed, max
    iteration error, the per-interval coupling summaries)."""
    record, rotation, results = None, 0., []
    for _ in range(intervals):
        interval = Z.interval(state, years)
        result = B.coupled_interval(state, moving, inputs, interval=interval, parent=record)
        rotation += v_rel(result.motion_port.omega_rad_s)/Z.RADIUS_M*(interval[3]-interval[2])
        results.append(dict(iterations=result.report['iterations'], residual=result.report['residual'],
                            iteration_error=result.report['iteration_error'], axis_tilt=result.report['axis_tilt'],
                            pieces_per_face=result.report['pieces_per_face']['max'],
                            increments=result.report['history'][-1]['increments']))
        state, moving, record = result.step.state, result.moving, result
    return state, moving, rotation, v_rel(result.motion_port.omega_rad_s), results


def orders(errors):
    return [math.log2(errors[i]/errors[i+1]) for i in range(len(errors)-1)]


class TimeRefinement(unittest.TestCase):
    """The rulings' replacement time criterion (C3), with the one-sided carrier belt (mid-build ruling)."""

    def test_the_oracle_control_is_first_order(self):
        state, equator = oracle_world()
        inputs = Z.inputs(declaration=Z.side_declaration('right'))
        moving0 = Z.moving(state, single=True)
        interval = Z.interval(state)

        yielding = []

        def rhs(_, y):
            moving = Z.moving(state, single=True, kappa_of=lambda c: y[0] if c == 'row-1' else Z.KAPPA0)
            result, term, strength, _ = B.solve_at(state, moving, inputs, interval=interval,
                                                   parent_state_id=state.state_id, evaluation='start')
            rates, _, _ = term.products(1.)
            rate = max(float(np.max(rates[i])) for i, (_, c) in enumerate(strength.pieces)
                       if c == 'row-1' and i in rates)
            yielding.append(all(np.all(p['plastic_rate'] > 0) for r in term.last[1] for p in r['points']))
            return [rate, v_rel(result.omega_rad_s)/Z.RADIUS_M]
        span = ORACLE_T_MYR*Z.MYR
        started = time.perf_counter()
        exact = solve_ivp(rhs, (0., span), [Z.KAPPA0, 0.], method='DOP853', rtol=1e-10, atol=1e-14)
        self.assertTrue(exact.success, exact.message)
        self.assertTrue(all(yielding))                                 # no point leaves yield over [0, T]
        oracle_gain = float(exact.y[0][-1])-Z.KAPPA0
        oracle_rotation = float(exact.y[1][-1])
        self.assertLess(Z.KAPPA0+oracle_gain, 3.)                      # inside the weakening interval over [0, T]
        errors, runs = dict(gain=[], rotation=[]), {}
        for n in LEVELS:
            end, moving, rotation, _, results = chain(state, moving0, inputs, n, ORACLE_T_MYR/n)
            gain = row_kappa(moving, end, equator)-Z.KAPPA0
            errors['gain'].append(abs(gain-oracle_gain))
            errors['rotation'].append(abs(rotation-oracle_rotation))
            runs[n] = dict(gain=gain, rotation_rad=rotation, intervals=results)
        observed = {k: orders(v) for k, v in errors.items()}
        REPORT['time_oracle'] = dict(oracle=dict(gain=oracle_gain, rotation_rad=oracle_rotation,
                                                 evaluations=int(exact.nfev),
                                                 seconds=time.perf_counter()-started),
                                     errors=errors, orders=observed, runs=runs)
        window = TOL['oracle_order_window']
        for key, values in observed.items():
            for value in values:
                self.assertTrue(window[0] <= value <= window[1], (key, observed))

    def test_the_coupled_layered_feedback_resolves_under_step_halving(self):
        network = Z.one_sided()
        state = Z.crust(network)
        moving0 = Z.moving(state)
        inputs = Z.inputs(declaration=Z.side_declaration('right'))
        start, _, _, _ = B.solve_at(state, moving0, inputs, interval=Z.interval(state), parent_state_id=state.state_id,
                                    evaluation='start')
        speed0 = v_rel(start.omega_rad_s)
        runs = {}
        for n in LEVELS:
            end, moving, rotation, speed, results = chain(state, moving0, inputs, n, COUPLED_T_MYR/n)
            gain = max(max(c.kappa) for c in moving.cohorts)-Z.KAPPA0
            runs[n] = dict(gain=gain, rotation_rad=rotation, final_speed_m_s=speed, feedback_m_s=speed-speed0,
                           intervals=results)
        changes = {key: relative_change(runs[8][key], runs[16][key]) for key in ('gain', 'rotation_rad',
                                                                                 'final_speed_m_s')}
        three = {key: (math.log2(abs(runs[4][key]-runs[8][key])/abs(runs[8][key]-runs[16][key]))
                       if runs[8][key] != runs[16][key] else None) for key in ('gain', 'rotation_rad')}
        halving = abs(runs[8]['feedback_m_s']-runs[16]['feedback_m_s'])
        iteration = max(r['iteration_error'] or 0. for n in (8, 16) for r in runs[n]['intervals'])
        smallest = min(changes.values())
        REPORT['time_coupled'] = dict(speed0_m_s=speed0, runs=runs, step_halving=changes, orders_reported=three,
                                      feedback_over_halving=abs(runs[16]['feedback_m_s'])/halving if halving else None,
                                      iteration_over_time=iteration/smallest if smallest else None)
        for key, value in changes.items():
            self.assertLessEqual(value, TOL['time_step_halving'], key)
        self.assertGreaterEqual(abs(runs[16]['feedback_m_s']), TOL['coupling_resolution_factor']*halving)
        self.assertLessEqual(iteration, 1e-3*smallest)
        for n in LEVELS:
            for item in runs[n]['intervals']:
                self.assertLessEqual(item['axis_tilt'], 64*G.EPS)
                self.assertEqual(item['pieces_per_face'], 1)


CONTINUE = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from threadpoolctl import threadpool_limits
import test_i04_controls as T
import i02_workflow_fixtures as F2
from atlas_tectonics import integration_ledger as L
with threadpool_limits(limits=1, user_api='blas'):
    store = F2.store(sys.argv[2])
    ledger = L.Ledger.open(store, sys.argv[3], source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
    ledger.verify_chain()
    verified = None                                  # the head's record is replayed by the first step
    for _ in range(int(sys.argv[4])):
        verified = T.ledger_interval(ledger, verified)
    print(' '.join(T.ledger_summary(ledger)))
    store.close()
'''


def ledger_inputs():
    return Z.inputs(declaration=Z.side_declaration('right'))


def ledger_interval(ledger, verified=None):
    """One coupled interval on the ledger through the ledger route: step reads the head's own record (replaying it
    unless ``verified`` is the value commit returned for that head) and commit binds the interval and the
    inheritance before writing. Returns the new head's Verified value."""
    coupled = B.step(ledger, ledger_inputs(), verified=verified)
    return B.commit(ledger, coupled, deadline=time.perf_counter()+600.)


def ledger_summary(ledger):
    head = ledger.head()
    driving = B.find_driving(ledger, head)['record']
    return [str(head.accepted_steps), hashlib.sha256(head._metadata).hexdigest(), head.state_id,
            ledger.sphere(head).state_id, ledger.moving(head).moving_id,
            hashlib.sha256(json.dumps(driving, sort_keys=True).encode()).hexdigest()]


class ReopenParity(unittest.TestCase):
    """Two intervals, save, a fresh process reopens and continues two more: equal to the uninterrupted four field by
    field and on the head record's sha256; every driving record replays."""

    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.prepared = F2.preparation()

    def ledger(self, name):
        network = Z.one_sided(side='right', epoch=F2.EPOCH, time_s=F2.START)
        sphere = Z.crust(network)
        store = F2.store(self.folder/name/'ledger.sqlite')
        ledger, _ = L.Ledger.create(store, F2.root(8, prepared=self.prepared), sphere=sphere, moving=Z.moving(sphere))
        return store, ledger

    def test_a_reopened_history_continues_to_the_same_head(self):
        store, whole = self.ledger('whole')
        self.addCleanup(store.close)
        verified = None
        for _ in range(4):
            verified = ledger_interval(whole, verified)
        cache = {}
        for commit in whole.chain()[1:]:
            self.assertEqual(B.verify_driving(whole, commit, cache=cache).status, B.REPLAYED)
        expected = ledger_summary(whole)
        saved, part = self.ledger('saved')
        verified = None
        for _ in range(2):
            verified = ledger_interval(part, verified)
        ledger_id = part.ledger_id
        saved.close()
        path = str(self.folder/'saved'/'ledger.sqlite')
        output = subprocess.run([sys.executable, '-B', '-c', CONTINUE, str(HERE), path, ledger_id, '2'],
                                capture_output=True, text=True, timeout=1800, env=dict(os.environ, PYTHONPATH=SRC))
        self.assertEqual(output.returncode, 0, output.stderr[-3000:])
        continued = output.stdout.split()
        REPORT['reopen_parity'] = dict(uninterrupted=expected, continued=continued)
        self.assertEqual(continued, expected)


class LuneFixtures(unittest.TestCase):
    """Ruling P5 (replacement fixtures): the lune ridge and the zigzag ridge take a D1/D2 balance at the interval
    start (labelled COARSE: 45 degree sectors), and their coupled intervals refuse by name (beta aliasing on the
    birth strip); the trench refuses at the inherited bracket check. Nothing is worked around."""

    def case(self, network, belts):
        state = Z.crust(network)
        inputs = Z.inputs(declaration=Z.declaration(boundaries=belts),
                          forcing=Z.forcing(plate='east', belts=belts, plates=('east', 'west')),
                          template=(('supplies', Z.supplies(RIDGE)), ('sinks', (F.sink(TRENCH),))),
                          births=Z.births())
        return state, Z.moving(state), inputs

    def test_ridge_belts_balance_at_the_start_and_refuse_coupled(self):
        found = {}
        for label, network in (('lune', F.lune_world()), ('zigzag', F.lune_world(zigzag_deg=4.))):
            state, moving, inputs = self.case(network, (RIDGE,))
            result, _, _, _ = B.solve_at(state, moving, inputs, interval=Z.interval(state),
                                         parent_state_id=state.state_id, evaluation='start')
            belt = result.belt['boundaries'][RIDGE]
            self.assertIn(G.COARSE, result.belt['labels'])
            self.assertGreater(belt['c_min'], 0.)                     # opening
            omega = result.omega_rad_s
            tilt = float(np.linalg.norm(omega[:, :2]))/float(np.linalg.norm(omega))
            with self.assertRaises(G.StrengthRefused) as caught:
                B.coupled_interval(state, moving, inputs, interval=Z.interval(state))
            self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNRESOLVED_BELT, 'beta'))
            found[label] = dict(c_min=belt['c_min'], c_max=belt['c_max'], beta_max=belt['beta_max'], axis_tilt=tilt,
                                coupled_refusal=str(caught.exception))
        self.assertLess(found['zigzag']['c_min'], 1.)                    # oblique segments
        REPORT['lune'] = found

    def test_the_trench_belt_refuses_at_the_inherited_bracket_check(self):
        state, moving, inputs = self.case(F.lune_world(), (TRENCH,))
        with self.assertRaises(G.StrengthRefused) as caught:
            B.solve_at(state, moving, inputs, interval=Z.interval(state), parent_state_id=state.state_id,
                       evaluation='start')
        self.assertEqual(caught.exception.code, G.UNSUPPORTED)
        self.assertIn('not monotone', str(caught.exception))         # the bracket search's monotonicity check
        REPORT['lune_trench'] = str(caught.exception)


if __name__ == '__main__':
    unittest.main()
