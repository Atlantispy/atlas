import unittest
from concurrent.futures import CancelledError
import threading
import weakref
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

from atlas_tectonics.subduction import (corner_flow, corner_streamfunction,
    benchmark_viscosity, PreparedSubduction, diagnostic_points_km, _flow_boundary, _Wedge)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.subduction_mesh import build_mesh


class SubductionTests(unittest.TestCase):
    def test_heat_factor_unpermutes_and_releases_phase_geometry(self):
        from scipy import sparse
        from atlas_tectonics import subduction as sub
        budget=WorkBudget(128*1024**2)
        matrix=sparse.csr_matrix([[4.,2.,0.,0.],[-1.,3.,1.,0.],[0.,-2.,5.,1.],[0.,0.,-.5,2.]])
        exact=np.array([1.,-3.,2.,.5])
        factor,guard=sub._factor(matrix,budget,'test-heat-factor')
        try:
            actual,error=sub._solve_checked(matrix,matrix@exact,factor)
            np.testing.assert_allclose(actual,exact,atol=1e-13,rtol=0.)
            self.assertLessEqual(error,1e-10)
            self.assertLessEqual(factor.statistics['realised_accounted_bytes'],factor.statistics['admitted_bytes'])
        finally:
            del factor
            guard.__exit__(None,None,None)
        self.assertEqual(budget.reserved_bytes,0)
        with build_mesh(24,budget=budget) as mesh:
            heat=sub._Heat(mesh,budget); real=sub._factor
            def factoring(matrix,owner,category):
                self.assertIsNone(heat.G)
                self.assertIsNone(heat.lap)
                self.assertIsNone(heat.geometry_guard)
                return real(matrix,owner,category)
            try:
                with patch.object(sub,'_factor',factoring):
                    temperature,_=heat.solve(np.zeros((len(mesh.cells),12,2)),stabilisation='supg',case='1a')
                self.assertTrue(np.isfinite(temperature).all())
            finally: heat.close()
        self.assertEqual(budget.reserved_bytes,0)

    def test_published_one_based_diagnostic_coordinates(self):
        p=diagnostic_points_km()
        self.assertEqual(p.shape,(115,2))
        np.testing.assert_array_equal(p[[0,1,36,37,-1]],[[60,60],[0,0],[210,210],[54,54],[120,120]])
        self.assertTrue(np.all(p[37:,1]<=p[37:,0]))

    def test_corner_traces_and_scale(self):
        np.testing.assert_allclose(corner_flow([[51,50],[100,50]]),0,atol=1e-14)
        np.testing.assert_allclose(corner_flow([[51,51],[100,100]]),np.full((2,2),2**-.5),atol=2e-14)
        np.testing.assert_allclose(corner_flow([[55,52],[100,70]]),np.repeat(corner_flow([[55,52]]),2,axis=0),atol=1e-14)

    def test_streamfunction_divergence_and_biharmonic(self):
        p=np.array([[80.,60.],[220.,150.]])
        h=1e-3
        dx=(corner_streamfunction(p+[h,0])-corner_streamfunction(p-[h,0]))/(2*h)
        dy=(corner_streamfunction(p+[0,h])-corner_streamfunction(p-[0,h]))/(2*h)
        np.testing.assert_allclose(corner_flow(p),np.stack((dy,-dx),axis=1),atol=1e-9)
        ux=(corner_flow(p+[h,0])-corner_flow(p-[h,0]))/(2*h)
        uy=(corner_flow(p+[0,h])-corner_flow(p-[0,h]))/(2*h)
        np.testing.assert_allclose(ux[:,0]+uy[:,1],0,atol=1e-10)

    def test_apex_and_invalid_points_refuse(self):
        for point in ([50,50],[49,50],[51,52],[np.nan,60]):
            with self.assertRaises(TectonicsError): corner_flow([point])

    def test_rheology_harmonic_cap_and_zero_strain(self):
        t=1000.; raw=1.32043e9*np.exp(335000/(8.3145*t))
        self.assertAlmostEqual(float(benchmark_viscosity('2a',t,0))/(1/(1/raw+1e-26)),1)
        self.assertEqual(float(benchmark_viscosity('2b',t,0)),1e26)
        raw=28968.6*np.exp(540000/(3.5*8.3145*t))*(1e-14)**(-2.5/3.5)
        self.assertAlmostEqual(float(benchmark_viscosity('2b',t,1e-14))/(1/(1/raw+1e-26)),1)
        for temp,rate in ((0,0),(1000,-1),(np.inf,0)):
            with self.assertRaises(TectonicsError): benchmark_viscosity('2a',temp,rate)

    def test_log_anderson_accelerates_slow_mode_and_rejects_worsening(self):
        from atlas_tectonics.subduction import _LogViscosityAnderson
        owner = WorkBudget(128*1024**2)
        mixing = _LogViscosityAnderson(owner); self.addCleanup(mixing.close); x = np.zeros(3)
        target = np.array([2., -1., .3]); rates = np.array([.82, .7, .2])
        for iteration in range(1, 201):
            residual = (1-rates)*(target-x)
            fallback = mixing.accept(residual)
            if fallback is not None:
                x = fallback; continue
            if np.max(np.abs(residual)) <= 1e-7:
                break
            x = mixing.propose(x, residual)
        self.assertLess(iteration, 30)
        np.testing.assert_allclose(x, target, rtol=0., atol=1e-6)
        self.assertGreater(mixing.accepted, 0)
        self.assertLessEqual(len(mixing.history), 4)
        self.assertLessEqual(owner.reserved_bytes, 9*x.nbytes)
        mixing.close(); self.assertEqual(owner.reserved_bytes, 0)
        mixing = _LogViscosityAnderson(owner); self.addCleanup(mixing.close)
        first = mixing.propose(np.array([0.]), np.array([1.]))
        mixing.propose(first, np.array([.9]))
        expected_fallback = first+.5*.9
        np.testing.assert_array_equal(mixing.accept(np.array([1.])), expected_fallback)
        self.assertEqual(mixing.rejected, 1)
        self.assertEqual(mixing.history, [])
        self.assertEqual(owner.reserved_bytes, 0)

    def test_adapter_and_budget_refuse(self):
        with self.assertRaises(TectonicsError): PreparedSubduction(12,source_id='test',outflow_operator='zero-curvature')
        with self.assertRaises(MemoryLimitError): PreparedSubduction(12,source_id='test',outflow_operator='natural-zero-diffusive-flux',budget=WorkBudget(10))

    def test_small_steady_and_exact_reuse(self):
        with PreparedSubduction(24,source_id='synthetic-focused-test',outflow_operator='natural-zero-diffusive-flux') as plan:
            self.assertIsNone(plan.heat.G)
            result=plan.solve('1a')
            self.assertIsNone(plan.heat.G)
            self.assertIsNone(plan.heat.geometry_guard)
            self.assertEqual(plan.budget.statistics()['categories']['subduction-heat-gradient'],0)
            self.assertIs(result,plan.solve('1a'))
            self.assertFalse(result.temperature_k.flags.writeable)
            self.assertTrue(np.all(result.points_xz_m[:,1]<=0))
            self.assertFalse(result.cells.flags.writeable)
            tri=result.points_xz_m[result.cells[:,:3]]
            a,b=tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]
            self.assertTrue(np.all(a[:,0]*b[:,1]-a[:,1]*b[:,0]>0))
            self.assertFalse(result.statistics['original2008_source_exact'])
            self.assertTrue(all(np.isfinite(result.diagnostics_c)))
            self.assertLess(result.statistics['thermal']['linear_residual'],1e-10)
            self.assertLess(result.statistics['thermal']['constant_temperature_residual'],1e-10)
            self.assertEqual(result.transport_wedge_velocity_m_s.shape,(len(result.wedge_global_elements),6,2))
            cancelled=threading.Event(); cancelled.set()
            with self.assertRaises(CancelledError): plan.solve('1a',cancel=cancelled)
        self.assertIsNone(plan.heat.G)
        self.assertEqual(plan.budget.statistics()['categories']['subduction-heat-gradient'],0)
        with self.assertRaises(TectonicsError): plan.solve('1a')

    def test_computed_wedge_nonzero_and_traction_pressure(self):
        with PreparedSubduction(24,source_id='synthetic-focused-test',outflow_operator='natural-zero-diffusive-flux') as plan:
            result=plan.solve('1c')
            self.assertGreater(np.max(np.abs(result.wedge_velocity_m_s)),0)
            self.assertGreater(np.max(np.abs(result.wedge_pressure_pa)),0)
            self.assertLess(result.statistics['mechanics']['linear_residual'],1e-10)
            self.assertLess(result.statistics['thermal']['constant_temperature_residual'],1e-10)
            self.assertLess(result.statistics['transport']['scaled_divergence_max'],1e-10)

    def test_different_case_evicts_unneeded_result_before_mechanics(self):
        with PreparedSubduction(24,source_id='synthetic-cache-lifetime',outflow_operator='natural-zero-diffusive-flux') as plan:
            previous=weakref.ref(plan.solve('1a'))
            self.assertIsNotNone(previous())  # owned by the one-entry cache
            solve_flow=plan.flow.solve
            def check_eviction(*args,**kwargs):
                self.assertIsNone(previous())
                self.assertEqual(plan.budget.statistics()['categories']['subduction-retained-result'],0)
                return solve_flow(*args,**kwargs)
            with patch.object(plan.flow,'solve',side_effect=check_eviction):
                current=plan.solve('1c')
        # Caller-owned results remain immutable and accounted after plan close.
        self.assertGreater(plan.budget.statistics()['categories']['subduction-retained-result'],0)
        self.assertFalse(current.temperature_k.flags.writeable)
        del current
        self.assertEqual(plan.budget.reserved_bytes,0)

    def test_case1b_prescribed_flux_compatible(self):
        with PreparedSubduction(24,source_id='synthetic-focused-test',outflow_operator='natural-zero-diffusive-flux') as plan:
            result=plan.solve('1b')
            self.assertTrue(np.isfinite(result.wedge_pressure_pa).all())

    def test_mesh_linear_first_edge_is_monotone_and_changes_only_its_midpoint(self):
        from atlas_tectonics.subduction import _slab_first_edge
        lengths = []
        for spacing in (24, 12):
            with build_mesh(spacing, grading='corner-r5') as mesh, mesh.wedge() as wedge:
                edge, length = _slab_first_edge(wedge); lengths.append(length)
                first, last, middle = edge; n = len(wedge.points)
                self.assertAlmostEqual(length, np.linalg.norm(wedge.points[last]-wedge.points[first])*1000.)
                s = np.linspace(0., 1., 101)
                polynomial = np.column_stack(((1-s)*(1-2*s), s*(2*s-1), 4*s*(1-s)))
                for case in ('1b', '1c', '2a', '2b'):
                    fixed, nodal = _flow_boundary(wedge, case)
                    explicit = _flow_boundary(wedge, case, 'nodal-p2-v1')
                    changed, linear = _flow_boundary(wedge, case, 'mesh-linear-first-edge-v1')
                    np.testing.assert_array_equal(fixed, explicit[0])
                    np.testing.assert_array_equal(nodal, explicit[1])
                    np.testing.assert_array_equal(fixed, changed)
                    np.testing.assert_array_equal(np.flatnonzero(nodal != linear), [middle, middle+n])
                    old = nodal.reshape(2, n).T[list(edge)]
                    new = linear.reshape(2, n).T[list(edge)]
                    np.testing.assert_array_equal(new[2], (new[0]+new[1])/2)
                    speed = (polynomial@new).sum(axis=1)/np.sqrt(2.)
                    np.testing.assert_allclose(speed, s, rtol=0., atol=3e-16)
                    self.assertTrue(np.all(np.diff(speed) >= 0.))
                    self.assertAlmostEqual(float(((polynomial@old).sum(axis=1)/np.sqrt(2.)).max()), 1.125)
                    np.testing.assert_allclose((polynomial@new)@np.array([1., -1.]), 0., atol=0.)
                np.testing.assert_array_equal(_flow_boundary(wedge, '1a')[1],
                    _flow_boundary(wedge, '1a', 'mesh-linear-first-edge-v1')[1])
                owner = np.flatnonzero(np.any(wedge.cells == middle, axis=1))
                broken = SimpleNamespace(points=wedge.points, vertex_count=wedge.vertex_count,
                    cells=np.concatenate((wedge.cells, wedge.cells[owner])))
                with self.assertRaisesRegex(TectonicsError, 'unique incident'):
                    _flow_boundary(broken, '1c', 'mesh-linear-first-edge-v1')
        self.assertLess(lengths[1], lengths[0])

    def test_coupling_trace_identity_cache_metadata_and_analytic_case_isolation(self):
        answers = []
        for trace in ('nodal-p2-v1', 'mesh-linear-first-edge-v1'):
            kwargs = {} if trace == 'nodal-p2-v1' else dict(coupling_trace=trace)
            with PreparedSubduction(24, source_id='synthetic-trace-test', mesh_grading='corner-r5',
                    outflow_operator='natural-zero-diffusive-flux', **kwargs) as plan:
                self.assertEqual(plan.flow.coupling_trace, trace)
                self.assertEqual(plan.slab_first_edge_length_m, plan.flow.slab_first_edge_length_m)
                def project(velocity, **kwargs):
                    return SimpleNamespace(element_node_velocity=velocity.copy(), diagnostics=lambda: {})
                def heat(velocity, **kwargs):
                    return np.full(len(plan.mesh.points), 1273.), dict(linear_residual=0.)
                # Exercise dispatch/result ownership without any coupled solve.
                with patch.object(plan.flow, 'solve', side_effect=AssertionError('analytic case must not solve mechanics')), \
                        patch.object(plan.transport, 'evaluate', side_effect=project), \
                        patch.object(plan.heat, 'solve', side_effect=heat):
                    result = plan.solve('1a')
                    self.assertIs(result, plan.solve('1a'))
                d = result.statistics
                self.assertEqual(d['coupling_trace'], trace)
                self.assertFalse(d['coupling_trace_applied'])
                self.assertEqual(d['slab_first_edge_length_m'], plan.slab_first_edge_length_m)
                answers.append((plan.plan_id, result.identity, plan.execution_id,
                    result.temperature_k.copy(), result.wedge_velocity_m_s.copy()))
            del result
            self.assertEqual(plan.budget.reserved_bytes, 0)
        self.assertNotEqual(answers[0][0], answers[1][0])
        self.assertNotEqual(answers[0][1], answers[1][1])
        self.assertEqual(answers[0][2], answers[1][2])
        for i in (3, 4): np.testing.assert_array_equal(answers[0][i], answers[1][i])
        with self.assertRaisesRegex(TectonicsError, 'coupling trace'):
            PreparedSubduction(24, source_id='test', outflow_operator='natural-zero-diffusive-flux', coupling_trace='physical-ramp')

    def test_affine_incompressible_mechanical_patch(self):
        budget=WorkBudget(128*1024**2)
        for grading in ('interface-r3','corner-r5'):
            with self.subTest(grading=grading), build_mesh(24,grading=grading,budget=budget) as mesh, mesh.wedge() as wedge:
                original=_flow_boundary
                def boundary(m,case):
                    fixed,_=original(m,'1b')
                    value=np.zeros(2*len(m.points))
                    exact=np.r_[m.points[:,0],-m.points[:,1]]
                    value[fixed]=exact[fixed]
                    return fixed,value
                numerical=_Wedge(wedge,budget)
                try:
                    with patch('atlas_tectonics.subduction._flow_boundary',boundary):
                        v,p,_,diagnostics=numerical.solve('1b',1.)
                    np.testing.assert_allclose(v,wedge.points*np.array([1.,-1.]),atol=1e-7,rtol=1e-10)
                    np.testing.assert_allclose(p,0,atol=1e-8)
                finally: numerical.close()


if __name__=='__main__': unittest.main()
