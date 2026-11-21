"""Unit W g3 (issue 96), T-2: plan/result identifiers hash content, not code identity.
  python -B -I test_content_ids_w_g3_r1.py <package parent folder> [<repo tests folder for precursor_fixtures>]
Constructed (fake ExecutionContext with identity A or B): constitutive, Stokes, variable Stokes (+E-4 backend),
thermochemical (+E-2 evolution_id), free surface plan, precursor sampling, regional forcing, regional workflow,
regional geology re-make. Record-level: regional_thermomechanical (E-2 heat_source_sha256; advance too heavy)."""
import inspect
import os
import sys
import types
from dataclasses import asdict
import unittest
from dataclasses import replace

import numpy as np

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))
FIXTURES = sys.argv.pop(1) if __name__ == '__main__' and len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, 'tests')
from atlas_tectonics import (constitutive_execution, free_surface, precursor_sampling, regional_execution,  # noqa: E402
                             regional_forcing, regional_geology, regional_thermomechanical, regional_workflow,
                             stokes_execution, thermochemical_execution, variable_stokes_execution)
from atlas_tectonics import (StokesBox2D, DiffusiveScales, reference_rheology, BoussinesqMaterial,  # noqa: E402
                             ThermalBoundary2D, ThermochemicalProblem, ThermochemicalState, PrescribedMACVelocity,
                             NonlinearStokesPolicy, PlanarGeometry, BoundaryRegion, build_boundary_network,
                             RegionalGrid1D)
from atlas_tectonics.geological_records import GeologySource  # noqa: E402
from atlas_tectonics.regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot  # noqa: E402
from atlas_tectonics.regional_workflow_geometry import RegionalColumnSupport  # noqa: E402
from atlas_tectonics.reuse import TectonicsError, content_record  # noqa: E402

A, B, C = 'a'*64, 'b'*64, 'c'*64
MODULES = (constitutive_execution, free_surface, precursor_sampling, regional_forcing, regional_geology,
           regional_workflow, stokes_execution, thermochemical_execution, variable_stokes_execution)
SOURCE = GeologySource('g3-control', 'synthetic', 'unit W g3 identifier control')


class Code:
    """Stand-in ExecutionContext: one code identity, the backend it was asked for (or a forced one)."""
    def __init__(self, identity, backend=None):
        self.identity_value, self.backend_value = identity, backend

    def __enter__(self):
        outer = self
        class Ctx:
            def __init__(self, backend='reference'):
                self.backend = outer.backend_value or backend; self.identity = outer.identity_value; self._sources = {}
            def verify(self): pass
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *_): self.close()
        self.old = [(m, m.ExecutionContext) for m in MODULES]
        for m in MODULES:
            m.ExecutionContext = Ctx

    def __exit__(self, *_):
        for m, old in self.old:
            m.ExecutionContext = old


def box(n=4):
    return StokesBox2D(n, n, 1., 1., 'r4-cartesian-x-right-z-up')


def scales():
    return DiffusiveScales('analytical-SI-unit-scales', 1., 1., 1., 1., 1., 1.)


def request(b, source='g3 synthetic force'):
    return dict(frame_id=b.frame_id, epoch_id='g3-epoch', time_s=0., source=source)


def forces(b, amplitude=1.):
    x, z = np.meshgrid(*b.axes('force_x'))
    return amplitude*np.sin(np.pi*z), np.zeros((b.nz-1, b.nx))


class ConstitutiveTests(unittest.TestCase):
    def run_once(self, identity, profile):
        with Code(identity), constitutive_execution.PreparedRheology(profile) as p:
            r = p.evaluate(np.full(2, .5), np.full(2, .1), np.full(2, 1.), np.zeros(2))
            return p.identity, r.result_id

    def test_code_identity_leaves_plan_and_result_ids(self):
        law = reference_rheology('constant')
        self.assertEqual(self.run_once(A, law), self.run_once(B, law))
        other = self.run_once(A, replace(law, parameters=(('eta', 2.),)))
        self.assertNotEqual(other[0], self.run_once(A, law)[0]); self.assertNotEqual(other[1], self.run_once(A, law)[1])


class StokesTests(unittest.TestCase):
    def run_once(self, identity, amplitude=1.):
        b = box()
        with Code(identity), stokes_execution.PreparedStokes2D(b, reference_rheology('constant'), scales()) as p:
            return p.identity, p.solve(*forces(b, amplitude), **request(b)).result_id

    def test_code_identity_leaves_plan_and_result_ids(self):
        a = self.run_once(A)
        self.assertEqual(a, self.run_once(B))
        self.assertNotEqual(a[1], self.run_once(A, 2.)[1])


class VariableStokesTests(unittest.TestCase):
    def run_once(self, identity, eta=1., backend=None):
        b = box()
        with Code(identity, backend), variable_stokes_execution.PreparedVariableStokes2D(
                b, scales(), policy=NonlinearStokesPolicy(method='direct')) as p:
            r = p.solve(*forces(b), np.full((b.nz, b.nx), eta), np.full((b.nz-1, b.nx-1), eta), **request(b))
            return p.identity, r.result_id, r.descriptor()['backend']

    def test_code_identity_leaves_ids_and_backend_enters_them(self):
        a = self.run_once(A)
        self.assertEqual(a, self.run_once(B)); self.assertEqual(a[2], 'scipy')
        self.assertNotEqual(a[1], self.run_once(A, eta=2.)[1])
        numba = self.run_once(A, backend='numba')  # E-4: same code identity, other backend -> other ids
        self.assertNotEqual(a[0], numba[0]); self.assertNotEqual(a[1], numba[1])


    def test_guess_binds_the_code_it_was_solved_under(self):  # W-1b case d (T-3): plan_id no longer carries the code
        b = box(); n = (b.nz, b.nx)
        def guess(code):
            meta = dict(schema='atlas.nonlinear-stokes-guess.v1', box=asdict(b), scales=asdict(scales()),
                        rheology=reference_rheology('constant').descriptor(), plan_id=C, context_id=code,
                        epoch_id='e', time_s=0., source_result_id=C)
            arrays = dict(u_m_s=np.zeros((b.nz, b.nx+1)), w_m_s=np.zeros((b.nz+1, b.nx)), pressure_pa=np.zeros(n))
            g = object.__new__(variable_stokes_execution.NonlinearStokesGuess); g._capture(meta, arrays, None)
            return g
        self.assertEqual(guess(A).guess_id, guess(B).guess_id)  # code is not content
        bind = lambda code: variable_stokes_execution._check_guess_binding(
            guess(A), C, code, reference_rheology('constant'), 'e', 0., box=b, scales=scales())
        bind(A)
        with self.assertRaisesRegex(TectonicsError, 'initial-guess source/plan'):
            bind(B)


class ThermochemicalTests(unittest.TestCase):
    def problem(self, k=.01):
        b = StokesBox2D(4, 4, 1., 1., 'r4-2-synthetic-cartesian')
        m = BoussinesqMaterial('synthetic-constant-properties', 'Authored numerical control, not Earth calibration',
                               1., 1., k, .001, 300., .01, 0., (1., 1000.))
        return ThermochemicalProblem(b, m, ThermalBoundary2D('fixed-top-bottom', 310., 300.), reference_rheology('constant'),
            DiffusiveScales('test-scales', 1., k, 1., 300., 10., 1.), (0., -1.), 'test-epoch', 'synthetic-heavy-constituent',
            'test specification')

    def run_once(self, identity, k=.01):
        p = self.problem(k); b = p.box
        x, z = np.meshgrid(*b.axes())
        s0 = ThermochemicalState(p, 310.-10*z, np.full(x.shape, .4), time_s=0., source='g3 initial')
        with Code(identity), thermochemical_execution.PreparedThermochemical2D(p, backend='reference') as plan:
            return plan.identity, plan.advance(s0, .001, source='g3 step', velocity=self.rest(b)).state

    def rest(self, b):
        return PrescribedMACVelocity(b, np.zeros((b.nz, b.nx+1)), np.zeros((b.nz+1, b.nx)), source='explicit zero velocity')

    def test_continued_state_under_other_code_is_refused(self):  # W-1 case d (T-3)
        _, s1 = self.run_once(A)
        self.assertEqual(s1.descriptor()['execution'], A)
        meta = s1.descriptor(); meta['execution'] = B  # code is not content: same state_id
        self.assertEqual(ThermochemicalState.restore(meta, {k: s1.array(k) for k in s1.array_names}).state_id, s1.state_id)
        for code in (A, B):
            with Code(code), thermochemical_execution.PreparedThermochemical2D(self.problem(), backend='reference') as plan:
                go = lambda: plan.advance(s1, .001, source='g3 step 2', velocity=self.rest(s1.problem.box))
                if code == A:
                    self.assertEqual(go().state.step_index, 2)
                else:
                    with self.assertRaisesRegex(TectonicsError, 'source/policy changed'):
                        go()

    def test_code_identity_leaves_ids_and_evolution_id_enters_state_id(self):
        (pa, sa), (pb, sb) = self.run_once(A), self.run_once(B)
        self.assertEqual((pa, sa.state_id), (pb, sb.state_id))
        self.assertEqual(sa.descriptor()['evolution_id'], pa); self.assertNotIn('execution_id', sa.descriptor())
        self.assertNotEqual(pa, self.run_once(A, k=.02)[0])
        meta = sa.descriptor(); meta['evolution_id'] = C  # E-2: another plan -> another state identifier
        moved = ThermochemicalState.restore(meta, {k: sa.array(k) for k in ('temperature_k', 'composition')})
        self.assertNotEqual(moved.state_id, sa.state_id)


class FreeSurfaceTests(unittest.TestCase):
    def plan_id(self, identity, viscosity=1.):
        with Code(identity), free_surface.PreparedFreeSurface2D(4, 2, width_m=2., bottom_m=0., reference_height_m=1.,
                viscosity_pa_s=viscosity, density_kg_m3=1., gravity_m_s2=1., external_pressure_pa=0., strike_width_m=1.,
                scales=RegionalMechanicsScales(1., 1.), frame_id='synthetic surface', vertical_datum='flat bottom zero',
                material_source='homogeneous isothermal control', load_source='explicit self gravity', method='direct') as p:
            return p._plan_id

    def test_code_identity_leaves_plan_id(self):
        self.assertEqual(self.plan_id(A), self.plan_id(B))
        self.assertNotEqual(self.plan_id(A), self.plan_id(A, 2.))


class PrecursorTests(unittest.TestCase):
    def test_code_identity_leaves_plan_and_sample_ids(self):
        sys.path.append(FIXTURES)
        try:
            import precursor_fixtures as pf
        except ImportError:
            self.skipTest('precursor_fixtures not found: pass the repo tests folder')
        def once(identity, state):
            with Code(identity), precursor_sampling.PreparedPrecursor(state) as p:
                return p.identity, p.sample_cells((pf.cell(),), **pf.REQUEST).sample_id
        s = pf.state()
        self.assertEqual(once(A, s), once(B, s))
        other = once(A, pf.state(pf.mixed_case()))
        self.assertNotEqual(other[0], once(A, s)[0])


def _forcing(identity, translation=(1., 0., 0.)):
    units = dict(length_unit='m', velocity_unit='m/s', angular_velocity_unit='rad/s')
    domain = PlanarGeometry.polygon(((0., 0.), (10., 0.), (10., 10.), (0., 10.)), frame_id='plane')
    net = build_boundary_network(domain, (BoundaryRegion('whole', 'A', domain),))
    motion = regional_forcing.PrescribedPlateMotion('A', 'plane', 'epoch', 0., 'planar-rigid', translation, (0., 0., 0.),
                                                    (0., 0., 0.), SOURCE, **units)
    definition = regional_forcing.RegionalMotionDefinition(topology=net, motions=(motion,), epoch_id='epoch', start_time_s=0.,
                                                           duration_s=.25, time_unit='s', source=SOURCE)
    section = regional_forcing.PlanarRegionalSection(section_id='section', frame_id='plane', epoch_id='epoch', time_s=0.,
        origin_m=(0., 5., 0.), direction_xy=(1., 0.), length_m=10., frame_velocity_m_s=(0., 0., 0.),
        frame_angular_velocity_rad_s=(0., 0., 0.), source=SOURCE, **units)
    reduction = regional_forcing.RegionalReduction('planar-columns', 'frozen-at-start', SOURCE, 1.)
    with Code(identity), regional_forcing.PreparedRegionalForcing(definition, section, reduction) as p:
        f = p.faces(RegionalGrid1D(10, 10.), frame_id='plane', epoch_id='epoch', start_time_s=0., duration_s=.25)
        return p.identity, f.samples.identity, f.forcing_id


class ForcingTests(unittest.TestCase):
    def test_code_identity_leaves_plan_samples_and_forcing_ids(self):
        a = _forcing(A)
        self.assertEqual(a, _forcing(B))
        other = _forcing(A, (2., 0., 0.))
        self.assertNotEqual(other[0], a[0]); self.assertNotEqual(other[2], a[2])


def _workflow(identity, max_steps=4):
    ns = types.SimpleNamespace
    return regional_workflow._state(ns(sample_id='1'*64), ns(forcing_id='2'*64),
        RegionalColumnSupport('planar-strip', 0., 10., SOURCE), (), ns(state_id='3'*64), None, max_steps, 'muscl',
        'reference', identity)


class WorkflowAndGeologyTests(unittest.TestCase):
    def test_workflow_id_and_the_geology_remake(self):
        a = _workflow(A)
        self.assertEqual(a.workflow_id, _workflow(B).workflow_id)
        self.assertNotEqual(a.workflow_id, _workflow(A, 5).workflow_id)
        # regional_geology.py:264 re-makes it with regional_execution._hash: same bytes.
        self.assertEqual(regional_execution._hash(content_record(a.descriptor())), a.workflow_id)

    def geology(self, identity, nx=1):
        out = object.__new__(regional_geology.RegionalGeologicalInputs)
        RegionalMechanicalSnapshot.__init__(out, dict(schema='atlas.regional-geological-inputs.v1', nx=nx,
            execution_id=identity, execution_backend='reference', source_execution_id=identity), {'f': np.zeros(2)})
        return out

    def test_geology_verify_remakes_the_binding_id(self):
        a, b = self.geology(A), self.geology(B)
        self.assertEqual(a.binding_id, b.binding_id)
        for identity, g in ((A, a), (B, b)):
            with Code(identity):
                g.verify(context=regional_geology.ExecutionContext('reference'))
        self.assertNotEqual(a.binding_id, self.geology(A, 2).binding_id)


class ThermomechanicalRecordTests(unittest.TestCase):
    def test_heat_source_digest_is_renamed_and_kept(self):
        source = inspect.getsource(regional_thermomechanical.advance_regional_thermomechanics)
        self.assertIn("'heat_source_sha256':_value_hash(source)", source); self.assertNotIn("'source_sha256'", source)
        binding = lambda data: {'heat_source_sha256': regional_thermomechanical._value_hash(np.full(2, data))}
        self.assertNotEqual(regional_execution._hash(content_record(binding(1.))),
                            regional_execution._hash(content_record(binding(2.))))


if __name__ == '__main__':
    unittest.main()
