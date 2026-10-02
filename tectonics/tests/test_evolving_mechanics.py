"""Coincident producer inputs, analytic mechanics and bounded prepared reuse.

These small controls test the evolving-input bridge, not geological evolution.
"""
from concurrent.futures import CancelledError
from dataclasses import replace
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import evolving_mechanics, reuse
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.evolving_mechanics import (
    PreparedEvolvingRegionalMechanics, RegionalInputBlock,
    RegionalInputContext, RegionalMechanicalRequest, regional_thermal_gravity,
)
from atlas_tectonics.regional_execution import (
    RegionalMechanicsScales, RegionalReferencePressure,
)
from atlas_tectonics.regional_stokes import boundary_coordinates
from atlas_tectonics.regional_thermomechanical import RegionalThermalBodyForce
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


SIDES = ('left', 'right', 'bottom', 'top')


def context(**changes):
    values = dict(nx=4, nz=4, width_m=1., height_m=1.,
                  frame_id='synthetic-x-right-z-up', vertical_datum='bottom-z-zero',
                  epoch_id='synthetic-epoch', time_s=0., origin_x_m=12., origin_z_m=-3.)
    values.update(changes)
    return RegionalInputContext(**values)


def pattern(top_traction=False):
    values = {side: {'u': 'velocity', 'w': 'velocity'} for side in SIDES}
    if top_traction:
        values['top'] = {'u': 'traction', 'w': 'traction'}
    return values


def block(c, kind, fields, *, source='synthetic-producer', state='state-0',
          sampling='exact analytic values on declared supports', effects=(), **kwargs):
    return RegionalInputBlock(c, kind, fields, source_id=source,
                              producer_state_id=state, sampling=sampling,
                              effect_ids=effects, **kwargs)


def material(c, eta=1., **kwargs):
    return block(c, 'material', {'centre': np.full((c.nz, c.nx), eta),
                                 'vertex': np.full((c.nz+1, c.nx+1), eta)}, **kwargs)


def force(c, gravity=0., *, effects=('body-gravity',), **kwargs):
    return block(c, 'body-force', {'u': np.zeros((c.nz, c.nx+1)),
                                   'w': np.full((c.nz+1, c.nx), -gravity)},
                 effects=effects, **kwargs)


def boundary(c, shear=1., *, types=None, top_normal=0., effects=('boundary-motion',),
             **kwargs):
    types = pattern() if types is None else types
    values = {}
    for side, parts in types.items():
        for component, mode in parts.items():
            _, z = boundary_coordinates(c.nx, c.nz, c.width_m, c.height_m,
                                        side, component)
            values[side+'_'+component] = (
                shear*z if component == 'u' and mode == 'velocity' else np.zeros(z.shape))
    values['top_w'] = top_normal
    return block(c, 'boundary', values, effects=effects, boundary_types=types, **kwargs)


def pressure(c, value=2., **kwargs):
    return block(c, 'surface-pressure', {'downward': value},
                 effects=('surface-pressure',), **kwargs)


def request(c=None, *, eta=1., shear=1., gravity=0., state='state-0',
            top_traction=False, surface=None):
    c = context() if c is None else c
    return RegionalMechanicalRequest(
        material(c, eta, state=state),
        (force(c, gravity, state=state, includes_total_gravity=True),),
        boundary(c, shear, types=pattern(top_traction), state=state),
        surface_pressure=surface)


def prepare(c=None, *, types=None, budget=None, reference=None, cancel=None):
    c = context() if c is None else c
    types = pattern() if types is None else types
    datum = None if types['top']['w'] == 'traction' else 0.
    return PreparedEvolvingRegionalMechanics(
        c, types, scales=RegionalMechanicsScales(1., 1.), viscosity_scale_pa_s=1.,
        physical_mean_pressure_pa=datum, reference_pressure=reference,
        budget=budget, cancel=cancel)


def expected_u(c, shear=1.):
    z = (np.arange(c.nz)+.5)*c.height_m/c.nz
    return np.broadcast_to((shear*z)[:, None], (c.nz, c.nx+1))


class EvolvingMechanicsTests(unittest.TestCase):
    def test_all_parts_require_coincident_time_and_support(self):
        c = context()
        original = request(c, top_traction=True, shear=0., surface=pressure(c))
        changes = dict(time_s=1., epoch_id='other-epoch', frame_id='other-frame',
                       vertical_datum='other-datum', origin_x_m=13., origin_z_m=-2.,
                       nx=5, nz=5, width_m=2., height_m=2.)
        for field, value in changes.items():
            other = replace(c, **{field: value})
            candidates = {
                'material': material(other),
                'body_forces': (force(other),),
                'boundary': boundary(other, 0., types=pattern(True)),
                'surface_pressure': pressure(other),
            }
            for part, candidate in candidates.items():
                args = dict(material=original.material, body_forces=original.body_forces,
                            boundary=original.boundary, surface_pressure=original.surface_pressure)
                args[part] = candidate
                with self.subTest(field=field, part=part), self.assertRaises(TectonicsError):
                    RegionalMechanicalRequest(**args)

    def test_prepared_support_is_fixed_but_coincident_time_can_change(self):
        c = context()
        with prepare(c) as plan:
            first = plan.evaluate(request(c))
            later = plan.evaluate(request(replace(c, time_s=5.)))
            self.assertNotEqual(first.result_id, later.result_id)
            for name in first.array_names:
                assert_array_equal(first.array(name), later.array(name))
            for field, value in (('epoch_id', 'new'), ('origin_x_m', 13.),
                                 ('origin_z_m', -2.), ('nx', 5), ('width_m', 2.)):
                with self.subTest(field=field), self.assertRaises(TectonicsError):
                    plan.evaluate(request(replace(c, **{field: value})))
            with self.assertRaises(TectonicsError):
                plan.evaluate(request(c, top_traction=True))

    def test_exact_field_support_and_source_labels_are_required(self):
        c = context()
        valid = {'centre': np.ones((4, 4)), 'vertex': np.ones((5, 5))}
        for fields in ({'centre': valid['centre']},
                       dict(valid, vertex=np.ones((4, 4))),
                       dict(valid, centre=1.), dict(valid, centre=np.zeros((4, 4)))):
            with self.subTest(fields=tuple(fields)), self.assertRaises(TectonicsError):
                block(c, 'material', fields)
        for name in ('source', 'state', 'sampling'):
            with self.subTest(label=name), self.assertRaises(TectonicsError):
                material(c, **{name: ''})
        with self.assertRaises(TectonicsError):
            block(c, 'body-force', {'u': np.zeros((4, 4)), 'w': np.zeros((5, 4))},
                  effects=('force',))
        with self.assertRaises(TectonicsError):
            pressure(c, np.zeros(c.nx))  # Normal boundary includes both corner traces.

    def test_duplicate_effect_ids_refuse_within_and_between_inputs(self):
        c = context()
        with self.assertRaises(TectonicsError):
            force(c, effects=('same', 'same'))
        with self.assertRaises(TectonicsError):
            RegionalMechanicalRequest(material(c),
                                      (force(c), force(c, state='other-state')),
                                      boundary(c))
        with self.assertRaises(TectonicsError):
            RegionalMechanicalRequest(material(c), (force(c, effects=('boundary-motion',)),),
                                      boundary(c))
        with self.assertRaises(TectonicsError):
            RegionalMechanicalRequest(material(c), (force(c),),
                                      boundary(c, types=pattern(True), effects=('surface-pressure',)),
                                      surface_pressure=pressure(c))

    def test_total_gravity_has_one_owner_even_with_distinct_effect_ids(self):
        c = context()
        forces = (force(c, effects=('gravity-a',), includes_total_gravity=True),
                  force(c, effects=('gravity-b',), includes_total_gravity=True))
        with self.assertRaises(TectonicsError):
            RegionalMechanicalRequest(material(c), forces, boundary(c))
        with self.assertRaises(TectonicsError):
            material(c, includes_total_gravity=True)

    def test_w04_or_other_added_displacement_is_refused(self):
        r = request()
        for added in (('W04-support-result',), ('other-displacement',), []):
            with self.subTest(added=added), self.assertRaises(TectonicsError):
                RegionalMechanicalRequest(r.material, r.body_forces, r.boundary,
                                          additional_displacement_ids=added)

    def test_surface_pressure_needs_unoccupied_top_normal_traction(self):
        c = context()
        for bc in (boundary(c), boundary(c, types=pattern(True), top_normal=-1.)):
            with self.assertRaises(TectonicsError):
                RegionalMechanicalRequest(material(c), (force(c),), bc,
                                          surface_pressure=pressure(c))
        r = request(c, top_traction=True, shear=0., surface=pressure(c))
        self.assertEqual(r.surface_pressure.array('downward').shape, (c.nx+2,))

    def test_surface_pressure_sign_and_reference_gravity_give_hydrostatics(self):
        c = context(width_m=2., height_m=3.)
        r = request(c, shear=0., gravity=7., top_traction=True, surface=pressure(c, 2.))
        reference = RegionalReferencePressure(2., 7., 'analytic constant-density reference')
        with prepare(c, types=pattern(True), reference=reference) as plan:
            result = plan.evaluate(r)
        z = (np.arange(c.nz)+.5)*c.height_m/c.nz
        expected = np.broadcast_to((2.+7.*(c.height_m-z))[:, None], (c.nz, c.nx))
        assert_allclose(result.array('u_m_s'), 0., atol=1e-9)
        assert_allclose(result.array('w_m_s'), 0., atol=1e-9)
        assert_allclose(result.array('dynamic_pressure_pa'), 0., atol=1e-9)
        assert_allclose(result.array('physical_pressure_pa'), expected, atol=1e-9)
        assert_array_equal(result.array('boundary_input_top_w'), np.full(c.nx+2, -2.))
        assert_allclose(result.array('stress_zz_pa'), -expected, atol=1e-9)

    def test_changed_viscosity_and_boundary_match_exact_affine_shear(self):
        c = context()
        with prepare(c) as plan:
            first = plan.evaluate(request(c))
            viscous = plan.evaluate(request(c, eta=2., state='eta-two'))
            sheared = plan.evaluate(request(c, eta=2., shear=3., state='shear-three'))
            for result, eta, shear in ((first, 1., 1.), (viscous, 2., 1.), (sheared, 2., 3.)):
                assert_allclose(result.array('u_m_s'), expected_u(c, shear), atol=1e-9)
                assert_allclose(result.array('w_m_s'), 0., atol=1e-9)
                assert_allclose(result.array('physical_pressure_pa'), 0., atol=1e-9)
                assert_allclose(result.array('deviatoric_stress_xz_pa'), eta*shear, atol=1e-9)
            self.assertEqual(len({x.result_id for x in (first, viscous, sheared)}), 3)
            self.assertEqual(plan.statistics()['mechanics']['coefficient_refills'], 1)

    def test_changed_body_force_changes_pressure_with_same_affine_motion(self):
        c = context()
        with prepare(c) as plan:
            first = plan.evaluate(request(c))
            loaded = plan.evaluate(request(c, gravity=4., state='changed-force'))
        z = (np.arange(c.nz)+.5)*c.height_m/c.nz
        expected = np.broadcast_to((4.*(c.height_m/2.-z))[:, None], (c.nz, c.nx))
        assert_allclose(first.array('physical_pressure_pa'), 0., atol=1e-9)
        assert_allclose(loaded.array('physical_pressure_pa'), expected, atol=1e-9)
        assert_allclose(loaded.array('u_m_s'), expected_u(c), atol=1e-9)
        self.assertNotEqual(first.result_id, loaded.result_id)

    def test_same_coefficients_retain_factor_but_provenance_changes_result(self):
        c = context()
        with prepare(c) as plan:
            r = request(c)
            first = plan.evaluate(r)
            factor = plan._plan._core._factor
            self.assertIs(first, plan.evaluate(r))
            changed = plan.evaluate(request(c, state='new-source-state'))
            self.assertIs(factor, plan._plan._core._factor)
            self.assertNotEqual(first.result_id, changed.result_id)
            for name in first.array_names:
                assert_array_equal(first.array(name), changed.array(name))
            stats = plan.statistics()
            self.assertEqual(stats['preparations'], 1)
            self.assertEqual(stats['latest_hits'], 1)
            self.assertEqual(stats['mechanics']['coefficient_reuse_hits'], 1)
            self.assertEqual(stats['mechanics'].get('coefficient_refills', 0), 0)

    def test_changed_prepared_and_cold_have_full_output_parity(self):
        c = context()
        changed = request(c, eta=3., shear=2., gravity=4., state='changed-all')
        with prepare(c) as plan:
            plan.evaluate(request(c))
            warm = plan.evaluate(changed)
        with prepare(c) as plan:
            cold = plan.evaluate(changed)
        self.assertEqual(warm.array_names, cold.array_names)
        for name in cold.array_names:
            with self.subTest(field=name):
                assert_allclose(warm.array(name), cold.array(name), rtol=1e-9, atol=1e-9)
        self.assertEqual(warm.descriptor()['request'], cold.descriptor()['request'])
        for result in (warm, cold):
            self.assertTrue(result.mechanics.descriptor()['diagnostics']['gates_passed'])
            self.assertTrue(result.descriptor()['steady_snapshot'])
            self.assertFalse(result.descriptor()['time_advanced'])
            self.assertFalse(result.descriptor()['displacement_added'])

    def test_supplied_thermal_gravity_matches_cold_and_replaces_original_gravity(self):
        c = context()
        law = RegionalThermalBodyForce(2., 3., .001, 300., 'synthetic linear buoyancy')
        def thermal_request(temperature, state):
            gravity = regional_thermal_gravity(
                c, np.full((c.nz, c.nx), temperature), law,
                producer_state_id=state, thermal_source_id='supplied cell-mean temperature')
            return RegionalMechanicalRequest(material(c), (gravity,), boundary(c))
        initial = thermal_request(300., 'cold-temperature')
        changed = thermal_request(400., 'warm-temperature')
        self.assertTrue(changed.body_forces[0].descriptor()['includes_total_gravity'])
        assert_allclose(changed.body_forces[0].array('w'), -5.4, atol=1e-14)
        with self.assertRaises(TectonicsError):
            RegionalMechanicalRequest(changed.material,
                (*changed.body_forces, force(c, 6., effects=('old-gravity',),
                                            includes_total_gravity=True)), changed.boundary)
        reference = RegionalReferencePressure(0., 6., 'reference density times gravity')
        with prepare(c, reference=reference) as plan:
            first = plan.evaluate(initial)
            warm = plan.evaluate(changed)
        with prepare(c, reference=reference) as plan:
            cold = plan.evaluate(changed)
        z = (np.arange(c.nz)+.5)*c.height_m/c.nz
        for result, density_gravity in ((first, 6.), (warm, 5.4)):
            expected = np.broadcast_to((density_gravity*(.5-z))[:, None], (c.nz, c.nx))
            assert_allclose(result.array('physical_pressure_pa'), expected, atol=1e-9)
            assert_allclose(result.array('u_m_s'), expected_u(c), atol=1e-9)
            assert_allclose(result.array('w_m_s'), 0., atol=1e-9)
        self.assertNotEqual(first.result_id, warm.result_id)
        self.assertEqual(warm.array_names, cold.array_names)
        for name in cold.array_names:
            with self.subTest(field=name):
                assert_allclose(warm.array(name), cold.array(name), rtol=1e-9, atol=1e-9)

    def test_source_drift_refuses_even_an_identical_latest_request(self):
        r = request()
        with prepare() as plan:
            plan.evaluate(r)
            original = reuse._source_bytes
            def changed():
                sources = original()
                sources['synthetic-source-drift.py'] = b'not the accepted implementation'
                return sources
            with mock.patch.object(reuse, '_source_bytes', changed):
                with self.assertRaises(TectonicsError):
                    plan.evaluate(r)
            self.assertEqual(plan.statistics()['latest_hits'], 0)

    def test_inputs_outputs_and_descriptors_are_detached_immutable_snapshots(self):
        c = context()
        values = {'centre': np.ones((4, 4)), 'vertex': np.ones((5, 5))}
        m = block(c, 'material', values)
        identifier = m.result_id
        values['centre'][:] = 99.
        values['vertex'][:] = 99.
        m.descriptor()['context']['time_s'] = 99.
        self.assertEqual(m.result_id, identifier)
        self.assertEqual(m.context.time_s, 0.)
        assert_array_equal(m.array('centre'), np.ones((4, 4)))
        with self.assertRaises(ValueError):
            m.array('centre').setflags(write=True)
        with self.assertRaises(TectonicsError):
            m.result_id = 'changed'
        r = RegionalMechanicalRequest(m, (force(c),), boundary(c))
        with prepare(c) as plan:
            result = plan.evaluate(r)
            with self.assertRaises(AttributeError):
                plan._geometry = b'changed'
        view = result.array('u_m_s')
        original_shape = view.shape
        with self.assertRaises(ValueError):
            view.setflags(write=True)
        view.shape = (view.size,)
        self.assertEqual(result.array('u_m_s').shape, original_shape)
        result.descriptor()['request']['context']['time_s'] = 99.
        self.assertEqual(result.descriptor()['request']['context']['time_s'], 0.)
        assert_allclose(result.array('deviatoric_stress_xz_pa'), 1., atol=1e-9)

    def test_cancellation_before_and_during_evaluation_releases_transient_work(self):
        c = context()
        event = threading.Event()
        event.set()
        owner = WorkBudget(128*1024**2)
        with self.assertRaises(CancelledError):
            material(c, cancel=event, budget=owner)
        with self.assertRaises(CancelledError):
            prepare(c, cancel=event, budget=owner)
        self.assertEqual(owner.reserved_bytes, 0)
        event.clear()
        with prepare(c, budget=owner) as plan:
            r = request(c)
            first = plan.evaluate(r)
            retained = owner.reserved_bytes
            event.set()
            with self.assertRaises(CancelledError):
                plan.evaluate(r, cancel=event)
            self.assertEqual(owner.reserved_bytes, retained)
            event.clear()
            original = evolving_mechanics._sum_forces
            def cancel_after_force_capture(blocks, name):
                answer = original(blocks, name)
                event.set()
                return answer
            with mock.patch.object(evolving_mechanics, '_sum_forces', cancel_after_force_capture):
                with self.assertRaises(CancelledError):
                    plan.evaluate(r, cancel=event)
            # Failure may release the latest response; it must not retain transient inputs.
            self.assertLessEqual(owner.reserved_bytes, retained)
            self.assertEqual(owner.statistics()['categories']['evolving-mechanical-inputs'], 0)
            event.clear()
            restored = plan.evaluate(r)
            self.assertEqual(first.result_id, restored.result_id)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_shared_budget_refusal_preserves_sibling_reservations_and_releases_owner(self):
        c = context()
        tiny = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):
            material(c, budget=tiny)
        with self.assertRaises(MemoryLimitError):
            prepare(c, budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        owner = WorkBudget(128*1024**2)
        with owner.reserve(4096, category='independent-sibling'):
            with prepare(c, budget=owner) as plan:
                r = request(c)
                accepted = plan.evaluate(r)
                retained = owner.reserved_bytes
                with owner.reserve(owner.available_bytes-32768, category='other-live-work'):
                    occupied = owner.reserved_bytes
                    other_work = owner.statistics()['categories']['other-live-work']
                    with self.assertRaises(MemoryLimitError):
                        plan.evaluate(r)
                    self.assertLessEqual(owner.reserved_bytes, occupied)
                    self.assertEqual(owner.statistics()['categories']['other-live-work'], other_work)
                    self.assertEqual(owner.statistics()['categories']['independent-sibling'], 4096)
                self.assertLessEqual(owner.reserved_bytes, retained)
                self.assertEqual(plan.evaluate(r).result_id, accepted.result_id)
            self.assertEqual(owner.reserved_bytes, 4096)
        self.assertEqual(owner.reserved_bytes, 0)


class AcceptedThenCancel:
    """Cancel token that fires once, at the first check after the operator names ``material_id``.

    The operator's definition changes only when the coefficient change is accepted,
    so that check is the closing one of the regional operation. It stands for a
    cancellation that arrives from another thread just after acceptance.
    """
    def __init__(self, plan, material_id):
        self.plan, self.material_id, self.fired = plan, material_id, False

    def is_set(self):
        operator = self.plan._plan
        if (not self.fired and operator is not None
                and operator.descriptor()['material_source'] == self.material_id):
            self.fired = True
            return True
        return False


def cancel_in_factorisation(core, event):
    original = core._numeric
    def numeric(coefficients, cancel):
        event.set()
        return original(coefficients, cancel)
    core._numeric = numeric


def cancel_after_core_refill(core, event):
    original = core.refill_viscosity
    def refill(**kwargs):
        answer = original(**kwargs)
        event.set()
        return answer
    core.refill_viscosity = refill


def fail_in_factorisation(core, event):
    def numeric(coefficients, cancel):
        raise ValueError('synthetic factorisation failure')
    core._numeric = numeric


class Abort(BaseException):
    """An interruption that is not an Exception, as a keyboard interrupt or an interpreter exit is."""


def abort_in_factorisation(core, event):
    def numeric(coefficients, cancel):
        raise Abort('synthetic interruption')
    core._numeric = numeric


class InterruptedViscosityChangeTests(unittest.TestCase):
    """R7 (s12-2): a cancelled or failed viscosity change must not break the plan.

    Cancellations and failures are injected through instance attributes of the
    one core object or through cancel tokens. Replacing a function of the bound
    package would itself be refused as a changed implementation; only the
    source-change method does so, as the existing source-drift method does,
    because a changed source is what it emulates.
    """
    def exact(self, result, eta, shear=1.):
        assert_allclose(result.array('deviatoric_stress_xz_pa'), eta*shear, atol=1e-9)
        assert_array_equal(result.array('viscosity_center_pa_s'), eta)

    def test_cancellation_at_every_check_of_a_viscosity_change_leaves_a_correct_plan(self):
        class OnCheck:
            def __init__(self, n):
                self.n, self.calls = n, 0
            def is_set(self):
                self.calls += 1
                return self.calls == self.n
        c = context()
        old, new = request(c), request(c, eta=2., state='eta-two')
        with prepare(c) as plan:
            expected = ((old, 1., plan.evaluate(old).result_id), (new, 2., plan.evaluate(new).result_id))
        accepted = False
        left = set()
        for n in range(1, 33):
            owner = WorkBudget(128*1024**2)
            with self.subTest(check=n), prepare(c, budget=owner) as plan:
                plan.evaluate(old)
                with self.assertRaises(CancelledError):
                    plan.evaluate(new, cancel=OnCheck(n))
                # Once the label names the new material the change was accepted;
                # later checks belong to the solve, not to the coefficient change.
                accepted = plan._material_id == new.material.result_id
                operator = plan._plan
                if operator is None:
                    left.add('operator released')
                elif plan._material_id is not None:
                    left.add('label kept')
                else:
                    holds_new = operator.descriptor()['material_source'] == new.material.result_id
                    left.add('label unknown, holds '+('new' if holds_new else 'old'))
                for r, eta, identifier in expected:
                    result = plan.evaluate(r)
                    self.exact(result, eta)
                    self.assertEqual(result.result_id, identifier)
            self.assertEqual(owner.reserved_bytes, 0)
            if accepted:
                break
        self.assertTrue(accepted)
        # The scan met a cancellation before, during and after the numeric refill.
        self.assertEqual(left, {'label kept', 'label unknown, holds old', 'operator released',
                                'label unknown, holds new'})

    def test_change_interrupted_after_the_numeric_refill_started_rebuilds_the_operator(self):
        for inject, failure in ((cancel_in_factorisation, CancelledError),
                                (cancel_after_core_refill, CancelledError),
                                (fail_in_factorisation, ValueError),
                                (abort_in_factorisation, Abort)):
            c = context()
            event = threading.Event()
            owner = WorkBudget(128*1024**2)
            with self.subTest(inject=inject.__name__), prepare(c, budget=owner) as plan:
                idle = owner.reserved_bytes
                first = plan.evaluate(request(c))
                operator = plan._plan
                inject(operator._core, event)
                with self.assertRaises(failure):
                    plan.evaluate(request(c, eta=2., state='eta-two'), cancel=event)
                event.clear()
                # The invalidated operator is closed and released, not kept.
                self.assertIsNone(plan.statistics()['mechanics'])
                self.assertEqual(owner.reserved_bytes, idle)
                self.assertFalse(operator.usable)
                again = plan.evaluate(request(c))
                self.assertEqual(again.result_id, first.result_id)
                self.exact(again, 1.)
                self.exact(plan.evaluate(request(c, eta=2., state='eta-two')), 2.)
                self.exact(plan.evaluate(request(c, eta=3., state='eta-three')), 3.)
                stats = plan.statistics()
                self.assertEqual(stats['preparations'], 2)
                self.assertEqual(stats['mechanics']['coefficient_refills'], 2)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_rebuilt_operator_publishes_the_same_bytes_as_an_uninterrupted_change(self):
        c = context()
        changed = request(c, eta=2., shear=3., gravity=4., state='changed-all')
        with prepare(c) as plan:
            plan.evaluate(request(c))
            expected = plan.evaluate(changed)
        event = threading.Event()
        with prepare(c) as plan:
            plan.evaluate(request(c))
            cancel_in_factorisation(plan._plan._core, event)
            with self.assertRaises(CancelledError):
                plan.evaluate(changed, cancel=event)
            event.clear()
            rebuilt = plan.evaluate(changed)
        self.assertEqual(rebuilt.result_id, expected.result_id)
        self.assertEqual(rebuilt.mechanics.result_id, expected.mechanics.result_id)
        self.assertEqual(rebuilt.array_names, expected.array_names)
        for name in expected.array_names:
            self.assertEqual(rebuilt.array(name).tobytes(), expected.array(name).tobytes(), name)

    def test_cancellation_after_an_accepted_change_never_serves_the_old_label(self):
        c = context()
        with prepare(c) as plan:
            first = plan.evaluate(request(c))
            second = request(c, eta=2., state='eta-two')
            with self.assertRaises(CancelledError):
                plan.evaluate(second, cancel=AcceptedThenCancel(plan, second.material.result_id))
            # The operator holds the new material although the call raised. A request
            # carrying the previous material must be solved with that material.
            again = plan.evaluate(request(c))
            self.exact(again, 1.)
            self.assertEqual(again.result_id, first.result_id)
            self.exact(plan.evaluate(second), 2.)
            self.assertEqual(plan.statistics()['preparations'], 1)

    def test_cancellation_before_the_numeric_refill_keeps_the_operator(self):
        class AtOperationEntry:
            # Fires once, at the regional operation's entry check: the operator is
            # active but no coefficient has been touched.
            def __init__(self, operator):
                self.operator, self.fired = operator, False
            def is_set(self):
                if not self.fired and self.operator._active:
                    self.fired = True
                    return True
                return False
        c = context()
        with prepare(c) as plan:
            first = plan.evaluate(request(c))
            operator = plan._plan
            token = AtOperationEntry(operator)
            with self.assertRaises(CancelledError):
                plan.evaluate(request(c, eta=2., state='eta-two'), cancel=token)
            self.assertTrue(token.fired)
            self.assertIs(plan._plan, operator)
            self.assertTrue(operator.usable)
            again = plan.evaluate(request(c))
            self.assertEqual(again.result_id, first.result_id)
            self.exact(again, 1.)
            self.exact(plan.evaluate(request(c, eta=2., state='eta-two')), 2.)
            stats = plan.statistics()
            self.assertEqual(stats['preparations'], 1)
            self.assertEqual(stats['mechanics']['coefficient_refills'], 1)

    def test_budget_refused_change_still_serves_the_unchanged_material(self):
        # A coefficient change reserves the operator's retained allowance a second
        # time, so the smallest budget that admits preparation and solves refuses
        # it before anything is touched. Every reservation is deterministic.
        c = context()
        roomy = WorkBudget(128*1024**2)
        with prepare(c, budget=roomy) as plan:
            plan.evaluate(request(c))
        owner = WorkBudget(roomy.peak_reserved_bytes)
        with prepare(c, budget=owner) as plan:
            first = plan.evaluate(request(c))
            operator = plan._plan
            with self.assertRaises(MemoryLimitError):
                plan.evaluate(request(c, eta=2., state='eta-two'))
            self.assertIs(plan._plan, operator)
            # The unchanged material needs no coefficient change and no refill
            # allowance: it is served as it was before the refused change.
            again = plan.evaluate(request(c))
            self.assertEqual(again.result_id, first.result_id)
            self.exact(again, 1.)
            self.assertEqual(plan.statistics()['mechanics'].get('coefficient_reuse_hits', 0), 0)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_source_change_during_a_change_is_reported_and_never_adopted(self):
        c = context()
        owner = WorkBudget(128*1024**2)
        original = reuse._source_bytes
        def changed():
            sources = original()
            sources['synthetic-source-drift.py'] = b'not the accepted implementation'
            return sources
        drift = mock.patch.object(reuse, '_source_bytes', changed)
        with prepare(c, budget=owner) as plan:
            idle = owner.reserved_bytes
            first = plan.evaluate(request(c))
            operator = plan._plan
            core_refill = operator._core.refill_viscosity
            def refill(**kwargs):
                answer = core_refill(**kwargs)
                drift.start()  # the source changes while the coefficients are being replaced
                return answer
            operator._core.refill_viscosity = refill
            try:
                # The post-refill source check refuses. Closing the invalidated
                # operator refuses as well: that second error must not replace the
                # first (it would carry the first as its context), and the
                # operator's storage is released all the same.
                with self.assertRaises(TectonicsError) as caught:
                    plan.evaluate(request(c, eta=2., state='eta-two'))
                self.assertIsNone(caught.exception.__context__)
                self.assertTrue(operator._closed)
                self.assertIsNone(plan._plan)
                self.assertEqual(owner.reserved_bytes, idle)
                # A replacement prepared from the changed source is refused, not adopted.
                for _ in range(2):
                    with self.assertRaises(TectonicsError):
                        plan.evaluate(request(c))
                    self.assertIsNone(plan._plan)
                    self.assertEqual(owner.reserved_bytes, idle)
                self.assertEqual(plan.statistics()['preparations'], 1)
            finally:
                drift.stop()
            again = plan.evaluate(request(c))
            self.assertEqual(again.result_id, first.result_id)
            self.assertEqual(again.mechanics.descriptor()['context_id'],
                             first.mechanics.descriptor()['context_id'])
            self.assertEqual(plan.statistics()['preparations'], 2)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_replacement_operator_cannot_adopt_another_execution_identity(self):
        c = context()
        event = threading.Event()
        owner = WorkBudget(128*1024**2)
        with prepare(c, budget=owner) as plan:
            idle = owner.reserved_bytes
            first = plan.evaluate(request(c))
            cancel_in_factorisation(plan._plan._core, event)
            with self.assertRaises(CancelledError):
                plan.evaluate(request(c, eta=2., state='eta-two'), cancel=event)
            event.clear()
            recorded = plan._execution_id
            self.assertEqual(recorded, first.mechanics.descriptor()['context_id'])
            # Stand in for a plan first prepared under other source bytes.
            object.__setattr__(plan, '_execution_id', 'identity-of-an-earlier-source')
            with self.assertRaises(TectonicsError):
                plan.evaluate(request(c))
            self.assertIsNone(plan._plan)
            self.assertEqual(owner.reserved_bytes, idle)
            object.__setattr__(plan, '_execution_id', recorded)
            self.assertEqual(plan.evaluate(request(c)).result_id, first.result_id)
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
