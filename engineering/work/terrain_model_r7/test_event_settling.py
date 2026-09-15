"""Independent frozen Decimal split-pool oracles; no terrain/file writes.

Expected event schedules come from the declared tiny geometries, not production
topology or returned events. The implicit root is checked against an independent
time-domain RK4 equation. This is numerical verification, not physical approval.
"""
from copy import deepcopy
from decimal import Decimal as D, localcontext
from functools import lru_cache
import json
import math
import unittest
from unittest.mock import patch

import event_settling as e
import r3_bindings as bindings


def column(w, s0, duration, wet_area=D(1)):
    if not s0 or not duration:
        return s0
    lo, hi = D(0), s0
    for _ in range(230):
        mid = (lo + hi) / 2
        residual = w * (mid / s0).ln() + mid - s0 + wet_area * duration
        if residual > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def decimal_rk4(w, s0, duration, steps):
    with localcontext() as ctx:
        ctx.prec = 65
        step = duration / steps
        s = s0
        def rhs(value):
            return -value / (w + value)
        for _ in range(steps):
            a = rhs(s)
            b = rhs(s + step * a / 2)
            c = rhs(s + step * b / 2)
            d = rhs(s + step * c)
            s += step * (a + 2*b + 2*c + d) / 6
        return s


@lru_cache(maxsize=2)
def oracle(which):
    with localcontext() as ctx:
        ctx.prec = 65
        if which == 1:
            w, s0, deposit = D('2.9991'), D('.001'), D('.0003')
            time = (w * (s0/(s0-deposit)).ln() + deposit) / 3
            concentration = (s0-deposit) / (w+s0-deposit)
            event_w = [D('1.9999')*(1-concentration), D(0), D('.9999')*(1-concentration)]
            event_s = [D('1.9999')*concentration, D(0), D('.9999')*concentration]
            final_s = [column(event_w[i], event_s[i], D('.8')-time) if i != 1 else D(0) for i in range(3)]
            final_b = [D('.0001')+a-b for a,b in zip(event_s, final_s)]
            return {'times': [time], 'event_w': event_w, 'event_s': event_s,
                    'W': event_w, 'S': final_s, 'B': final_b}
        if which != 2:
            raise AssertionError('unknown independent oracle')
        w, s0, dep1 = D('4.49865'), D('.0015'), D('.00025')
        s1 = s0-dep1
        time1 = (w*(s0/s1).ln()+dep1)/5
        c1 = s1/(w+s1)
        wl, sl = D('2.99995')*(1-c1), D('2.99995')*c1
        wr, sr = D('1.49995')*(1-c1), D('1.49995')*c1
        dep2 = D('.00015')
        time2 = time1+(wl*(sl/(sl-dep2)).ln()+dep2)/3
        c2 = (sl-dep2)/(wl+sl-dep2)
        event_w = [D('1.9999')*(1-c2), D(0), D('.9999')*(1-c2), D(0), wr]
        event_s = [D('1.9999')*c2, D(0), D('.9999')*c2, D(0), sr]
        final_s = [D(0)]*5
        final_b = [D('.0001'), D('.0001'), D('.0001'), D('.00005'), D('.00005')]
        for i in (0,2,4):
            start = time1 if i == 4 else time2
            final_s[i] = column(event_w[i],event_s[i],D('.8')-start)
            final_b[i] += event_s[i]-final_s[i]
        return {'times': [time1,time2], 'first_pool_W': [wl,wr], 'first_pool_S': [sl,sr],
                'W': event_w, 'S': final_s, 'B': final_b}


def initial(which=1, *, bed=None, shape=None, reverse=False):
    with localcontext() as ctx:
        ctx.prec = 65
        default = [D(0),D('1.9999'),D(1)] if which == 1 else [D(0),D('1.9999'),D(1),D('1.99995'),D('.5')]
        heights = default if bed is None else [D(str(v)) for v in bed]
        depths = [max(D(2)-z,D(0)) for z in heights]
        liquid, solid = (D('2.9991'),D('.001')) if which == 1 else (D('4.49865'),D('.0015'))
        if sum(depths) != liquid+solid:
            raise AssertionError('oracle geometry and source totals differ')
        c = solid/(liquid+solid)
        water = [float(d*(1-c)) for d in depths]
        sediment = [float(d*c) for d in depths]
        values = list(map(float,heights))
        if reverse:
            values.reverse();water.reverse();sediment.reverse()
        return bindings.capture.CaptureState(shape or [1,len(values)], [1.]*len(values), values,
                                             [0.]*len(values),water,sediment)


def advance(state, duration=.8, **kwargs):
    return e.settle_components(state,settling_m_year=1.,elapsed_years=duration,**kwargs)


class SplitPoolOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.predecessor = bindings.verify_predecessor()

    @classmethod
    def tearDownClass(cls):
        if bindings.verify_predecessor() != cls.predecessor:
            raise AssertionError('immutable R3 source closure changed during R4 tests')

    def near(self, got, expected, *, atol=1e-9, rtol=1e-12):
        expected = float(expected)
        self.assertTrue(math.isfinite(got))
        self.assertLessEqual(abs(got-expected),atol+rtol*max(abs(got),abs(expected)))

    def compare_oracle(self, state, expected):
        for field, key in (('liquid_m3','W'),('suspended_solid_m3','S'),('bed_solid_m3','B')):
            for i,(actual,wanted) in enumerate(zip(getattr(state,field),expected[key])):
                with self.subTest(field=field,cell=i):
                    self.near(actual,wanted)

    def conserved(self, initial_state, result, report):
        self.near(math.fsum(result.liquid_m3),math.fsum(initial_state.liquid_m3))
        self.near(math.fsum((*result.bed_solid_m3,*result.suspended_solid_m3)),
                  math.fsum((*initial_state.bed_solid_m3,*initial_state.suspended_solid_m3)))
        for key in ('liquid_ledger','solid_ledger'):
            self.assertLessEqual(abs(report[key]['residual']),report[key]['tolerance'])
        for key in ('physical_acceptance','production_authorised','shoreline_exchange_implemented'):
            self.assertIs(report[key],False)
        self.assertEqual(result.time_years,initial_state.time_years, 'outer capture owns time advancement')
        self.assertTrue(all(x>=0 for name in ('liquid_m3','suspended_solid_m3','bed_solid_m3') for x in getattr(result,name)))

    def test_decimal_integral_oracle_agrees_with_independent_time_ode(self):
        expected = oracle(1)
        with localcontext() as ctx:
            ctx.prec = 65
            duration = D('.8')-expected['times'][0]
            for i in (0,2):
                a=decimal_rk4(expected['event_w'][i],expected['event_s'][i],duration,256)
                b=decimal_rk4(expected['event_w'][i],expected['event_s'][i],duration,512)
                self.assertLess(abs(a-b),D('1e-14'))
                self.assertLess(abs(b-expected['S'][i]),D('1e-14'))

    def test_single_split_event_allocation_and_final_columns(self):
        state=initial();before=deepcopy(state.as_dict());expected=oracle(1)
        result,report=advance(state)
        self.assertEqual(state.as_dict(),before)
        self.compare_oracle(result,expected);self.conserved(state,result,report)
        self.assertEqual(report['initial_components'],[[0,1,2]])
        self.assertEqual(len(report['events']),1)
        event=report['events'][0]
        self.near(event['time_years'],expected['times'][0],rtol=1e-11)
        self.assertEqual(event['parent_cells'],[0,1,2]);self.assertEqual(event['dried_cells'],[1])
        self.assertIs(event['split'],True)
        self.assertEqual([r['cell_indices'] for r in event['daughters']],[[0],[2]])
        for row,i in zip(event['daughters'],(0,2)):
            self.near(row['liquid_m3'],expected['event_w'][i])
            self.near(row['suspended_solid_m3'],expected['event_s'][i])
        self.assertEqual(result.liquid_m3[1],0.);self.assertEqual(result.suspended_solid_m3[1],0.)
        concentrations=[result.suspended_solid_m3[i]/(result.liquid_m3[i]+result.suspended_solid_m3[i]) for i in (0,2)]
        self.assertGreater(concentrations[0]-concentrations[1],3e-5)
        for i in (0,2):
            self.near(result.bed_m[i]+result.liquid_m3[i]+result.suspended_solid_m3[i],2.,rtol=1e-11)

    def test_nested_two_event_tree_advances_all_daughters(self):
        state=initial(2);result,report=advance(state);expected=oracle(2)
        self.compare_oracle(result,expected);self.conserved(state,result,report)
        events=report['events'];self.assertEqual(len(events),2)
        for event,wanted in zip(events,expected['times']):
            self.near(event['time_years'],wanted,rtol=1e-11)
        self.assertEqual(events[0]['dried_cells'],[3]);self.assertEqual(events[1]['dried_cells'],[1])
        self.assertEqual([r['cell_indices'] for r in events[0]['daughters']],[[0,1,2],[4]])
        self.assertEqual([r['cell_indices'] for r in events[1]['daughters']],[[0],[2]])
        for row,wanted in zip(events[0]['daughters'],expected['first_pool_W']):self.near(row['liquid_m3'],wanted)
        for row,wanted in zip(events[0]['daughters'],expected['first_pool_S']):self.near(row['suspended_solid_m3'],wanted)
        self.assertEqual([i for i,w in enumerate(result.liquid_m3) if w>0],[0,2,4])
        terminals=[row for row in report['intervals'] if not any(other['parent_interval']==row['id'] for other in report['intervals'])]
        self.assertEqual(sorted(row['cell_indices'] for row in terminals),[[0],[2],[4]])
        for row in terminals:self.near(row['end_years'],.8,rtol=1e-11)

    def test_geometry_reflection_preserves_event_times_and_phases(self):
        for which in (1,2):
            a,ra=advance(initial(which));b,rb=advance(initial(which,reverse=True))
            for field in ('liquid_m3','suspended_solid_m3','bed_solid_m3'):
                for x,y in zip(getattr(a,field),reversed(getattr(b,field))):self.near(x,y)
            for x,y in zip(ra['events'],rb['events']):self.near(x['time_years'],y['time_years'],rtol=1e-11)

    def test_time_partitions_before_and_after_split_match_analytic_end(self):
        for which in (1,2):
            for prefix in (.2,.5):
                state=initial(which);first,_=advance(state,prefix);last,report=advance(first,.8-prefix)
                self.compare_oracle(last,oracle(which))
                self.conserved(first,last,report)

    def test_serialised_restart_same_prefix_is_exact(self):
        prefix,_=advance(initial(),.5)
        encoded=json.dumps(prefix.as_dict(),sort_keys=True,allow_nan=False)
        restored=bindings.capture.CaptureState(**json.loads(encoded))
        direct,a=advance(prefix,.3);restarted,b=advance(restored,.3)
        self.assertEqual(direct.as_dict(),restarted.as_dict())
        self.assertEqual(a,b)
        self.compare_oracle(restarted,oracle(1))

    def test_same_stage_disconnected_daughters_are_not_remixed(self):
        expected=oracle(1)
        state=bindings.capture.CaptureState([1,3],[1.]*3,[0.,1.9999,1.],
            list(map(float,expected['B'])),list(map(float,expected['W'])),list(map(float,expected['S'])))
        result,report=advance(state,.2)
        self.assertEqual(report['initial_components'],[[0],[2]])
        with localcontext() as ctx:
            ctx.prec=65
            for i in (0,2):
                wanted=column(expected['W'][i],expected['S'][i],D('.2'))
                self.near(result.suspended_solid_m3[i],wanted)
                self.near(result.liquid_m3[i],expected['W'][i])
        cs=[result.suspended_solid_m3[i]/(result.liquid_m3[i]+result.suspended_solid_m3[i]) for i in (0,2)]
        self.assertGreater(cs[0],cs[1])
        unchanged,_=advance(state,0.)
        self.assertEqual(unchanged.as_dict(),state.as_dict())

    def test_marginal_drying_retains_one_mixed_component(self):
        state=initial(bed=[0.,1.,1.9999]);result,report=advance(state)
        self.assertEqual(len(report['events']),1);event=report['events'][0]
        self.assertIs(event['split'],False);self.assertEqual(event['dried_cells'],[2])
        self.assertEqual([row['cell_indices'] for row in event['daughters']],[[0,1]])
        with localcontext() as ctx:
            ctx.prec=65
            total_s=column(D('2.9991'),D('.0007'),D('.8')-oracle(1)['times'][0],D(2))
            self.near(math.fsum(result.suspended_solid_m3),total_s)
        concentrations=[result.suspended_solid_m3[i]/(result.liquid_m3[i]+result.suspended_solid_m3[i]) for i in (0,1)]
        self.near(concentrations[0],concentrations[1],atol=1e-12)
        self.conserved(state,result,report)

    def test_four_eight_neighbour_topology_changes_split_not_mass(self):
        state=initial(bed=[0.,1.9999,3.,1.],shape=[2,2])
        for connectivity,split,daughters in ((4,True,[[0],[3]]),(8,False,[[0,3]])):
            result,report=advance(state,connectivity=connectivity)
            self.assertIs(report['events'][0]['split'],split)
            self.assertEqual([r['cell_indices'] for r in report['events'][0]['daughters']],daughters)
            self.conserved(state,result,report)

    def test_zero_forcing_keeps_connected_state_and_has_no_events(self):
        state=initial();result,report=e.settle_components(state,settling_m_year=0.,elapsed_years=.8)
        for field in ('liquid_m3','suspended_solid_m3','bed_solid_m3'):
            for a,b in zip(getattr(state,field),getattr(result,field)):self.near(a,b)
        self.assertEqual(report['events'],[]);self.conserved(state,result,report)

    def test_unrouted_stage_or_concentration_rejected_without_repair(self):
        original=initial()
        for mutation in ('stage','concentration'):
            data=original.as_dict()
            if mutation=='stage':data['liquid_m3'][0]+=.1
            else:
                data['liquid_m3'][0]-=.0001;data['suspended_solid_m3'][0]+=.0001
            state=bindings.capture.CaptureState(**data);before=deepcopy(state.as_dict())
            with self.assertRaises(ValueError):advance(state)
            self.assertEqual(state.as_dict(),before)

    def test_invalid_numeric_and_topology_controls_fail_closed(self):
        for key in ('settling_m_year','elapsed_years','wall_seconds'):
            for bad in (True,None,'1',math.inf,math.nan,-1.,10**1000):
                args={'settling_m_year':1.,'elapsed_years':.8,'wall_seconds':120};args[key]=bad
                with self.subTest(key=key,bad=str(bad)[:20]),self.assertRaises(ValueError):
                    e.settle_components(initial(),**args)
        for bad in (True,0,6):
            with self.assertRaises(ValueError):advance(initial(),connectivity=bad)
        with self.assertRaises(ValueError):advance(initial(),wall_seconds=121)
        with self.assertRaises(ValueError):advance(object())

    def test_cooperative_wall_limit_is_checked_after_solver_call(self):
        original=e.settling.settle_pool;clock=[0.]
        def delayed(*args,**kwargs):
            result=original(*args,**kwargs);clock[0]=121.;return result
        with patch.object(e.time,'monotonic',side_effect=lambda:clock[0]),patch.object(e.settling,'settle_pool',side_effect=delayed):
            with self.assertRaisesRegex(ValueError,'wall envelope'):advance(initial(),.1)

    def test_r3_rejection_and_immutable_dependency_binding_remain(self):
        state=bindings.capture.CaptureState([1,3],[1.]*3,[0.,1.9999,1.],[0.]*3,[2.9991,0.,0.],[.001,0.,0.])
        with self.assertRaisesRegex(ValueError,'split|disconnect|connectivity'):
            bindings.capture.step(state,outlets=[],connectivity=4,liquid_input_m3=[0.]*3,
                suspended_input_m3=[0.]*3,bed_input_solid_m3=[0.]*3,settling_m_year=1.,elapsed_years=.8,
                source_label='SYNTHETIC retained R3 unsupported split regression')
        self.assertEqual(bindings.verify_predecessor(),self.predecessor)


if __name__=='__main__':
    unittest.main()
