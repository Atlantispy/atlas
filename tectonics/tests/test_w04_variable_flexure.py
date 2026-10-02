"""Independent variable-D controls: synthetic SI values, not field calibration."""
from dataclasses import FrozenInstanceError, replace
from concurrent.futures import CancelledError
import math
import re
from threading import Event
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.finite_flexure import FlexureBoundary1D, FiniteRegionFlexure
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.regional import RegionalGrid1D
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.variable_flexure import (
    RigidityProfile1D, VariableFlexureAccuracy, VariableRigidityFlexure, _one_norm_estimate,
)


SOURCE = 'independent synthetic variable-plate control; arbitrary SI values'
PARAMETERS = FlexureParameters('variable-fixture', SOURCE, 12., 1., 0., 4., 1.)
CONTINUOUS = FlexureBoundary1D('continuous', 'continuous', SOURCE)
CLAMPED = FlexureBoundary1D('clamped', 'clamped', SOURCE)
FREE = FlexureBoundary1D('free', 'free', SOURCE)
ACCURACY = VariableFlexureAccuracy(SOURCE, 1e-3, 1e-9, 1e-9, 1e-9,
    max_refinements=6, max_elements=4096, max_element_over_alpha=.5)


def profile(rigidity, *, length=4., origin=0., thickness=1., far=None,
            source_id=SOURCE, budget=None):
    d = np.asarray(rigidity, dtype=float)
    te = np.broadcast_to(thickness, d.shape).copy()
    outside = (None, None) if far is None else tuple((12.*v, 1., 0.) for v in far)
    return RigidityProfile1D(RegionalGrid1D(len(d), length, origin),
        12.*d/te**3, te, np.zeros(len(d)), source_id=source_id,
        frame_id='synthetic-planar-frame', datum_id='synthetic-datum',
        epoch_id='fixed-reference-epoch', far_left=outside[0], far_right=outside[1],
        budget=budget)


def solve(p, load, boundary=CLAMPED, accuracy=ACCURACY):
    with VariableRigidityFlexure(p, PARAMETERS, boundary, accuracy) as plan:
        return plan.solve(load)


def two_piece_oracle(cells=8, length=4., rigidities=(1., 16.), pressures=(2., -1.)):
    """Independent 8-coefficient continuum solution, with a true central D jump.

    Each half has q/K plus growing/decaying complex modes, centred on that
    half to keep this small oracle well conditioned. Match w,w',D*w'',D*w'''
    at the interface and impose clamped outer ends. No FEM/kernel functions.
    """
    k = 4.
    centres = (length/4., 3.*length/4.)

    def basis(piece, x, derivative):
        beta = (k/(4.*rigidities[piece]))**.25
        modes = []
        for real_sign in (-1., 1.):
            z = complex(real_sign, 1.)*beta
            value = z**derivative*np.exp(z*(x-centres[piece]))
            modes.extend((value.real, value.imag))
        return np.asarray(modes)

    matrix = np.zeros((8, 8)); rhs = np.zeros(8)
    for row, (piece, x, derivative) in enumerate(
            ((0, 0., 0), (0, 0., 1), (1, length, 0), (1, length, 1))):
        matrix[row, 4*piece:4*piece+4] = basis(piece, x, derivative)
        if derivative == 0:
            rhs[row] = -pressures[piece]/k
    for derivative in range(4):
        weights = rigidities if derivative >= 2 else (1., 1.)
        matrix[4+derivative, :4] = weights[0]*basis(0, length/2., derivative)
        matrix[4+derivative, 4:] = -weights[1]*basis(1, length/2., derivative)
    rhs[4] = (pressures[1]-pressures[0])/k
    coefficients = np.linalg.solve(matrix, rhs)
    result = np.empty((cells, 3, 4)); h = length/cells
    for cell in range(cells):
        piece = 0 if cell < cells//2 else 1
        for location, fraction in enumerate((0., .5, 1.)):
            for derivative in range(4):
                value = basis(piece, (cell+fraction)*h, derivative)@coefficients[4*piece:4*piece+4]
                result[cell, location, derivative] = value + (pressures[piece]/k if derivative == 0 else 0.)
    return result


def ceiling_outcome(p, parameters, load, tolerances, refinements, **policy):
    """A periodic solve's outcome (the result, or the refusal's text), the
    subdivisions built, and each successive pair's domain-maximum changes
    recomputed from the retained factors."""
    accuracy = VariableFlexureAccuracy(SOURCE, *tolerances, max_refinements=refinements,
                                       max_elements=1 << 20, **policy)
    with VariableRigidityFlexure(p, parameters, 'periodic', accuracy) as plan:
        try:
            outcome = plan.solve(load)
        except TectonicsError as error:
            outcome = str(error)
        levels = sorted(plan._levels)
        responses = [plan._response(plan._factor(s), load) for s in levels]
    changes = np.array([np.max(np.maximum(np.max(np.abs(new[:, :3, :3]-old[:, :3, :3]), axis=1),
                                          np.abs(new[:, 3, :3]-old[:, 3, :3])), axis=0)
                        for old, new in zip(responses, responses[1:])])
    return outcome, levels, changes


def quoted_changes(message):
    """Every (change, subdivisions) pair a ceiling refusal quotes, in order."""
    return [(float(value), int(count)) for value, count in
            re.findall(r'(\d\.\d+e[-+]\d+)[^;()]*? at (\d+)', message)]


class VariableRigidityFlexureTests(unittest.TestCase):
    def test_error_estimator_does_not_stop_at_a_constant_mode_nullspace(self):
        # Derivative maps annihilate constants. An initial zero product must
        # still reach coordinate probes, not falsely report zero sensitivity.
        matrix=np.array([[1.,1.,-1.,-1.],[-1.,-1.,1.,1.]])
        estimate=_one_norm_estimate(lambda x: matrix@x,lambda x: matrix.T@x,4)
        self.assertEqual(estimate,np.linalg.norm(matrix,1))

    def assert_quotes(self, message, levels, changes, fields):
        # A ceiling refusal must quote, for exactly these fields and in this order,
        # the smallest change with its subdivisions and then the change at the
        # ceiling. The wording around those numbers is not pinned.
        best = np.argmin(changes, axis=0)
        expected = [pair for field in fields for pair in
                    ((changes[best[field], field], levels[best[field]+1]), (changes[-1, field], levels[-1]))]
        quoted = quoted_changes(message)
        self.assertEqual([count for _, count in quoted], [count for _, count in expected], message)
        assert_allclose([value for value, _ in quoted], [value for value, _ in expected], rtol=1e-3, atol=0.)

    def test_uniform_load_is_exact_equilibrium_for_arbitrary_positive_rigidity(self):
        d = [1., 16., 2., 4., 8., 1., 3., 5.]
        for boundary in (FREE, CONTINUOUS, 'periodic'):
            with self.subTest(boundary=boundary):
                p = profile(d, far=(2., 7.) if boundary == CONTINUOUS else None)
                load = np.r_[np.full(8, 3.), [3., 3.] if boundary == CONTINUOUS else [0., 0.]]
                result = solve(p, load, boundary)
                self.assertEqual(result.shape, (8, 5, 4))
                assert_allclose(result[:, :3, 0], .75, rtol=0., atol=2e-13)
                assert_allclose(result[:, :3, 1:], 0., rtol=0., atol=2e-12)
                assert_allclose(result[:, 3, 0], .75, rtol=0., atol=2e-13)
                assert_allclose(result[:, 3, 1:], 0., rtol=0., atol=2e-12)
                self.assertTrue(np.all(result[:, 4, :3] >= 0.))
                self.assertTrue(np.all(result[:, 4, 3] >= 2.))

    def test_two_piece_clamped_plate_matches_independent_exponential_oracle(self):
        d = np.r_[np.ones(4), np.full(4, 16.)]
        load = np.r_[np.full(4, 2.), np.full(4, -1.), 0., 0.]
        # The public gate estimates only w, slope and curvature. This extra
        # third-derivative oracle needs a stronger declared solve policy; its
        # fixed comparison tolerance below is not a claim that shear is gated.
        result = solve(profile(d), load, accuracy=replace(ACCURACY, relative_tolerance=3e-4))
        exact = two_piece_oracle()
        # Fixed continuum tolerances, independent of the solver's mesh gate.
        for derivative, tolerance in enumerate((3e-5, 1e-4, 4e-4, 2e-2)):
            with self.subTest(derivative=derivative):
                assert_allclose(result[:, :3, derivative], exact[:, :, derivative],
                    rtol=0., atol=tolerance)
        assert_allclose(result[0, 0, :2], 0., rtol=0., atol=2e-13)
        assert_allclose(result[-1, 2, :2], 0., rtol=0., atol=2e-13)
        assert_allclose(result[3, 2, :2], result[4, 0, :2], rtol=0., atol=2e-12)
        exact_jump = exact[3, 2, 2]-exact[4, 0, 2]
        self.assertGreater(abs(result[3, 2, 2]-result[4, 0, 2]), .5*abs(exact_jump))
        # The exact interface transmits moment, not curvature continuity.
        assert_allclose(exact[3, 2, 2], 16.*exact[4, 0, 2], rtol=0., atol=2e-13)
        allowance = np.array([1e-9]*3)+3e-4*np.max(result[:, 3, :3], axis=0)
        self.assertTrue(np.all(result[:, 4, :3] <= allowance))

    def test_uniform_rigidity_refines_towards_exact_cell_integrated_green_response(self):
        p = profile(np.ones(8), far=(1., 1.))
        load = np.r_[[0., 1., -.5, 0., 2., 0., 0., 1.], .5, -.25]
        analytic = FiniteRegionFlexure(p.grid, PARAMETERS, CONTINUOUS).solve(load)
        exact = analytic[2*np.arange(8)[:, None]+np.arange(3)]
        loose = solve(p, load, CONTINUOUS, replace(ACCURACY, relative_tolerance=5e-3))
        tight = solve(p, load, CONTINUOUS, replace(ACCURACY,
            relative_tolerance=1e-4, max_refinements=7))
        coarse_error = float(np.max(np.abs(loose[:, :3, :3]-exact[:, :, :3])))
        fine_error = float(np.max(np.abs(tight[:, :3, :3]-exact[:, :, :3])))
        self.assertLess(fine_error, coarse_error)
        self.assertGreaterEqual(tight[0, 4, 3], loose[0, 4, 3])
        for derivative, tolerance in enumerate((3e-5, 3e-5, 2e-4)):
            assert_allclose(tight[:, :3, derivative], exact[:, :, derivative],
                rtol=0., atol=tolerance)

    def test_periodic_rigidity_and_load_translate_across_the_seam(self):
        d = np.array([1., 2., 8., 4., 3., 1., 5., 16.])
        q = np.array([4., 1., 2., -.5, 3., 2., 1., 3.5])
        self.assertNotEqual(d[0], d[-1])  # A legitimate jump in the repeating profile.
        original = solve(profile(d), np.r_[q, 0., 0.], 'periodic')
        shifted = solve(profile(np.roll(d, 3)), np.r_[np.roll(q, 3), 0., 0.], 'periodic')
        assert_allclose(shifted[:, :4], np.roll(original[:, :4], 3, axis=0),
            rtol=2e-7, atol=2e-8)
        assert_allclose(original[-1, 2, :2], original[0, 0, :2], rtol=0., atol=2e-12)
        self.assertGreater(float(np.mean(original[:, 1, 0])), .1)

    def test_reflection_and_explicit_uniform_exterior_extension_preserve_response(self):
        d = np.r_[np.ones(4), np.full(4, 4.)]
        q = np.array([0., 1., -.5, 0., 2., 0., .5, 1.])
        original = solve(profile(d, far=(1., 4.)), np.r_[q, .5, -.25], CONTINUOUS)
        reflected = solve(profile(d[::-1], far=(4., 1.)), np.r_[q[::-1], -.25, .5], CONTINUOUS)
        expected = original[::-1, 2::-1, :]*np.array([1., -1., 1., -1.])
        assert_allclose(reflected[:, :3], expected, rtol=2e-7, atol=2e-8)
        assert_allclose(reflected[:, 3], original[::-1, 3], rtol=2e-7, atol=2e-8)
        extended_d = np.r_[np.ones(2), d, np.full(2, 4.)]
        extended_q = np.r_[np.full(2, .5), q, np.full(2, -.25), .5, -.25]
        extended = solve(profile(extended_d, length=6., origin=-1., far=(1., 4.)),
            extended_q, CONTINUOUS)
        # Extension replaces exact half-lines by FE cells: convergence, not
        # bitwise subdivision invariance, is the honest numerical contract.
        assert_allclose(extended[2:10, :3, :3], original[:, :3, :3], rtol=0., atol=3e-4)

    def test_equivalent_rigidity_preserves_response_but_not_thickness_strain(self):
        d = np.array([1., 2., 4., 8., 8., 4., 2., 1.])
        thin, thick = profile(d), profile(d, thickness=2.)
        self.assertNotEqual(thin.profile_id, thick.profile_id)
        assert_allclose(thin.rigidity_n_m, thick.rigidity_n_m, rtol=2e-15, atol=0.)
        load = np.r_[[0., 1., 2., 3., 2., 1., -.5, 0.], 0., 0.]
        a, b = solve(thin, load), solve(thick, load)
        assert_allclose(a[:, :3], b[:, :3], rtol=2e-7, atol=2e-8)
        assert_allclose(a[:, 3, :3], b[:, 3, :3], rtol=2e-7, atol=2e-8)
        assert_allclose(b[:, 3, 3], 2.*a[:, 3, 3], rtol=2e-7, atol=2e-8)
        assert_allclose(a[:, 3, 3], .5*a[:, 3, 2], rtol=0., atol=0.)
        self.assertTrue(np.all(a[:, 3, :3] >= np.max(np.abs(a[:, :3, :3]), axis=1)-1e-12))

    def test_invalid_material_boundary_load_and_accuracy_or_unresolved_mesh_refuse(self):
        grid = RegionalGrid1D(8, 4.)
        metadata = dict(source_id=SOURCE, frame_id='frame', datum_id='datum', epoch_id='epoch')
        for e, te, nu in ((0., 1., 0.), (12., 0., 0.), (12., 1., .5),
                          (12., 1., -1.), (math.nan, 1., 0.), (1e-300, 1e-100, 0.)):
            with self.subTest(material=(e, te, nu)), self.assertRaises(TectonicsError):
                RigidityProfile1D(grid, np.full(8, e), np.full(8, te), np.full(8, nu), **metadata)
        with self.assertRaises(TectonicsError):
            RigidityProfile1D(grid, np.ones(7), np.ones(8), np.zeros(8), **metadata)
        with self.assertRaises(TectonicsError):
            RigidityProfile1D(grid, np.ones(8), np.ones(8), np.zeros(8),
                far_left=[12., 1., 0.], **metadata)
        p = profile(np.ones(8))
        for boundary, material in ((CONTINUOUS, p), (FREE, profile(np.ones(8), far=(1., 1.))),
                                   ('invented', p)):
            with self.subTest(boundary=boundary), self.assertRaises(TectonicsError):
                VariableRigidityFlexure(material, PARAMETERS, boundary, ACCURACY)
        for kwargs in ({'relative_tolerance': 0.}, {'relative_tolerance': 1.},
                       {'absolute_slope': 0.}, {'max_refinements': 0},
                       {'max_elements': 0}, {'max_element_over_alpha': 2.}):
            with self.subTest(policy=kwargs), self.assertRaises(TectonicsError):
                replace(ACCURACY, **kwargs)
        with VariableRigidityFlexure(p, PARAMETERS, CLAMPED, ACCURACY) as plan:
            for load in (np.zeros(8), np.zeros((1, 10)), np.full(10, math.nan),
                         np.ma.array(np.zeros(10)), np.r_[np.zeros(8), 1., 0.]):
                with self.subTest(shape=load.shape), self.assertRaises(TectonicsError):
                    plan.solve(load)
        with self.assertRaises(TectonicsError):
            VariableRigidityFlexure(p, PARAMETERS, CLAMPED, replace(ACCURACY, max_elements=8))
        demanding = replace(ACCURACY, relative_tolerance=1e-12,
            absolute_displacement_m=1e-14, absolute_slope=1e-14,
            absolute_curvature_per_m=1e-14, max_refinements=1)
        with VariableRigidityFlexure(p, PARAMETERS, CLAMPED, demanding) as plan:
            with self.assertRaisesRegex(TectonicsError, 'tolerance|refinement'):
                plan.solve(np.r_[np.ones(8), 0., 0.])
        with VariableRigidityFlexure(profile(np.ones(8), far=(1., 1.)),
                PARAMETERS, CONTINUOUS, ACCURACY) as plan:
            with self.assertRaisesRegex(TectonicsError, 'scaled pressure'):
                plan.solve(np.r_[np.zeros(8), np.nextafter(0., 1.), 0.])

    def test_ceiling_refusal_quotes_the_smallest_estimate_where_refinement_stalled(self):
        # Sixteen periodic cells with elastic thicknesses of 45, 30 and 8 km over six
        # of the smallest flexural lengths. Past 32-64 subdivisions the mesh-change
        # estimates grow again (round-off in the banded solve), so a tolerance below
        # that floor is met at none of the eight levels. The refusal used to say only
        # that the tolerance was not reached within the ceiling.
        parameters = FlexureParameters('round-off-floor', SOURCE, 7e10, 20e3, .25, 3300., 9.81)
        thickness = np.where(np.arange(16) < 8, 30e3, 8e3); thickness[0] = 45e3
        rigidity = 7e10*thickness**3/(12*(1-.25**2))
        length = 6*float(np.min((4*rigidity/parameters.restoring_pa_per_m)**.25))
        p = RigidityProfile1D(RegionalGrid1D(16, length, 0.), np.full(16, 7e10), thickness, np.full(16, .25),
            source_id=SOURCE, frame_id='synthetic-planar-frame', datum_id='synthetic-datum',
            epoch_id='fixed-reference-epoch')
        load = np.r_[1e7*np.cos(1.7*np.arange(16)+.3), 0., 0.]

        def run(tolerances, refinements):
            return ceiling_outcome(p, parameters, load, tolerances, refinements)

        below_floor = (1e-9, 1e-9, 1e-14, 1e-18)
        message, levels, changes = run(below_floor, 8)
        self.assertIsInstance(message, str)                                 # refused
        self.assertEqual(levels, [2**k for k in range(9)])                  # every level was still tried
        best = np.argmin(changes, axis=0)
        self.assertTrue(np.all(changes[-1] > changes[best, range(3)]))      # every field rose again
        named = quoted_changes(message)
        for field in range(3):
            smallest, subdivisions = changes[best[field], field], levels[best[field]+1]
            self.assertTrue(any(count == subdivisions and abs(value-smallest) <= 1e-3*smallest
                                for value, count in named), (field, smallest, subdivisions, message))
        self.assert_quotes(message, levels, changes, (0, 1, 2))
        # A field whose estimate rose is not named while it meets its tolerance: with
        # a 10 m displacement allowance only slope and curvature fail at 256.
        mixed, levels, changes = run((1e-9, 10., 1e-14, 1e-18), 8)
        self.assertIsInstance(mixed, str)
        self.assertEqual(levels, [2**k for k in range(9)])
        self.assertGreater(changes[-1, 0], changes[-2, 0])                  # the displacement rose too
        self.assertLess(changes[-1, 0], 10.)                                # but within its allowance
        self.assert_quotes(mixed, levels, changes, (1, 2))
        # Estimates that only fell (a ceiling too low for the tolerance) keep the plain refusal.
        plain, levels, changes = run(below_floor, 2)
        self.assertIsInstance(plain, str)
        self.assertEqual(levels, [1, 2, 4])
        self.assertTrue(np.all(np.argmin(changes, axis=0) == len(changes)-1))
        self.assertNotEqual(plain, message)
        self.assertFalse(re.search(r'\d\.\d+e[-+]\d+', plain))
        # This pair formerly passed at 64 subdivisions despite a displacement
        # change already rising from its minimum. The independent precision
        # allowance now refuses that unsupported pass, without stopping early.
        refused, levels, changes = run((1e-4, 1e-6, 1e-9, 1e-13), 8)
        self.assertEqual(levels, [2**k for k in range(9)])
        self.assertGreater(changes[5, 0], changes[4, 0])
        self.assertIsInstance(refused,str)
        self.assertIn('numerical precision',refused)

    def test_accidentally_agreeing_meshes_do_not_pass_below_numerical_precision(self):
        # Captured continuous-profile regression: at 384 subdivisions the old
        # displacement change was 4.9e-8 m against a 7.1e-8 m allowance, yet a
        # 64-ulp material perturbation moved it by 5.5e-6 m. The perturbation is
        # evidence for this fixture, never the solver's error-estimation method.
        parameters=FlexureParameters('precision-control',SOURCE,7e10,20e3,.25,3300.,9.81)
        thickness=np.full(13,71344.75169996313)
        material=(7e10,float(thickness[0]),.25)
        p=RigidityProfile1D(RegionalGrid1D(13,1084244.4854291864,0.),
            np.full(13,7e10),thickness,np.full(13,.25),source_id=SOURCE,
            frame_id='synthetic-planar-frame',datum_id='synthetic-datum',
            epoch_id='fixed-reference-epoch',far_left=material,far_right=material)
        load=np.array([3278.6980138314125,1061.7840278089784,-1693.8767316038447,
            -672.455277689334,-3898.585612172092,-2900.7305771289743,-430.7953436446985,
            -2914.570884041081,-1033.551672021682,-227.6991654316522,470.91614345353537,
            3949.6663951871315,-544.2218342500279,1657973.0630892566,-317591.7304542913])
        accuracy=VariableFlexureAccuracy(SOURCE,2.7592818405398763e-9,
            2.0065868640322665e-10,1.648344846558318e-16,1.92250304598375e-13,
            max_refinements=7,max_elements=65536,max_element_over_alpha=.25)
        with VariableRigidityFlexure(p,parameters,CONTINUOUS,accuracy) as plan:
            with self.assertRaisesRegex(TectonicsError,'precision|tolerance'):
                plan.solve(load)
            # Independent acceptance requirement: even when the platform's
            # successive-mesh differences happen to agree, its arithmetic
            # sensitivity cannot be smaller than the requested displacement.
            result,uncertainty=plan._response(plan._factor(384),load,precision=True)
            limit=accuracy.absolute_displacement_m+accuracy.relative_tolerance*np.max(result[:,3,0])
            self.assertGreater(uncertainty[0],limit)

    def test_ceiling_refusal_stays_plain_while_a_failing_field_is_still_falling(self):
        # Five periodic cells whose first slope estimate is small by accident: 1.3e-9
        # at 2 subdivisions, then 1.4e-8 at 4, and from there it falls at every level
        # until the tolerance is met at 32. At ceilings 3 and 4 the slope fails and
        # lies above that early minimum while refinement is still reducing it. A
        # refusal that named a floor there said the opposite of what a higher ceiling
        # then does.
        parameters = FlexureParameters('early-dip', SOURCE, 7e10, 20e3, .25, 3300., 9.81)
        p = RigidityProfile1D(RegionalGrid1D(5, 12e3, 0.), np.full(5, 7e10),
            np.array([15e3, 10e3, 7.3e3, 24e3, 17e3]), np.full(5, .25), source_id=SOURCE,
            frame_id='synthetic-planar-frame', datum_id='synthetic-datum',
            epoch_id='fixed-reference-epoch')
        load = np.array([-1.0e7, -1.8e7, 1.7e7, -7.4e6, -4.3e6, 0., 0.])

        def run(refinements):
            return ceiling_outcome(p, parameters, load, (1e-12, 1e-2, 5e-10, 1e-10), refinements,
                                   max_element_over_alpha=1.)

        plain, levels, changes = run(1)                 # one estimate cannot have stopped falling
        self.assertIsInstance(plain, str)
        self.assert_quotes(plain, levels, changes, ())
        for refinements in (3, 4):
            with self.subTest(refinements=refinements):
                message, levels, changes = run(refinements)
                self.assertEqual(levels, [2**k for k in range(refinements+1)])
                self.assertGreater(changes[-1, 1], np.min(changes[:, 1]))   # above its earlier minimum
                self.assertLess(changes[-1, 1], changes[-2, 1])             # and still falling
                self.assertEqual(message, plain)
        accepted, levels, changes = run(8)
        self.assertEqual(levels, [1, 2, 4, 8, 16, 32])
        self.assertTrue(np.all(accepted[:, 4, 3] == 32.))
        # One refinement after the early minimum nothing yet shows the slope falling,
        # so that refusal quotes the minimum, for the slope alone (the curvature fails
        # too but is falling). It is the same solve that ceiling 5 accepts, which is
        # why the refusal may offer round-off as a cause but must not assert it.
        message, levels, changes = run(2)
        self.assertEqual(levels, [1, 2, 4])
        self.assertGreater(changes[-1, 1], changes[-2, 1])
        self.assertLess(changes[-1, 2], changes[-2, 2])
        self.assert_quotes(message, levels, changes, (1,))

    def test_immutable_snapshots_lazy_factor_reuse_close_and_per_call_budget(self):
        budget = WorkBudget(32<<20)
        e = np.full(8, 12.); te = np.ones(8); nu = np.zeros(8)
        metadata = dict(source_id=SOURCE, frame_id='frame', datum_id='datum', epoch_id='epoch')
        p = RigidityProfile1D(RegionalGrid1D(8, 4.), e, te, nu, budget=budget, **metadata)
        original_id = p.profile_id
        e[:] = 120.; te[:] = 2.; nu[:] = .2
        assert_allclose(p.rigidity_n_m, 1., rtol=2e-15, atol=0.)
        assert_array_equal(p.elastic_thickness_m, np.ones(8))
        self.assertEqual(p.profile_id, original_id)
        with self.assertRaises(ValueError): p.rigidity_n_m.setflags(write=True)
        with self.assertRaises(FrozenInstanceError): p.source_id = 'edited'
        with self.assertRaises(FrozenInstanceError): ACCURACY.relative_tolerance = .1
        plan = VariableRigidityFlexure(p, PARAMETERS, FREE, ACCURACY, budget=budget)
        self.assertEqual(plan.setup_bytes, 0)
        try:
            load = np.r_[np.ones(8), 0., 0.]
            result = plan.solve(load)
            before = result.copy(); load[:] = 0.
            assert_array_equal(result, before)
            self.assertGreater(plan.setup_bytes, 0)
            retained = plan.setup_bytes
            self.assertEqual(budget.reserved_bytes, retained)
            assert_array_equal(plan.solve(np.r_[np.ones(8), 0., 0.]), result)
            self.assertEqual(plan.setup_bytes, retained)
            with self.assertRaises(ValueError): result.setflags(write=True)
            with self.assertRaises(ValueError): result[0, 0, 0] = 0.
            with self.assertRaises(AttributeError): plan.profile = profile(np.full(8, 2.))
        finally:
            plan.close()
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(plan.setup_bytes, 0)
        plan.close()
        with self.assertRaises(TectonicsError): plan.solve(np.zeros(10))
        tiny = WorkBudget(1)
        with self.assertRaises(MemoryLimitError): profile(np.ones(8), budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        # This fits the small outer load/output reservation but not factor or
        # response work; an explicit per-call budget must cover those too.
        call_budget = WorkBudget(20000)
        with VariableRigidityFlexure(p, PARAMETERS, FREE, ACCURACY, budget=budget) as fresh:
            cancelled = Event(); cancelled.set()
            with self.assertRaises(CancelledError):
                fresh.solve(np.zeros(10), budget=call_budget, cancel=cancelled)
            self.assertEqual(budget.reserved_bytes, 0)
            self.assertEqual(call_budget.reserved_bytes, 0)
            with self.assertRaises((MemoryLimitError, TectonicsError)):
                fresh.solve(np.r_[np.ones(8), 0., 0.], budget=call_budget)
        self.assertEqual(call_budget.reserved_bytes, 0)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
