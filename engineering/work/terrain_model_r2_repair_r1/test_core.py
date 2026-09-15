from dataclasses import replace
import math
import unittest

from core import Grid, State, CONTRACT, gradients, constraints_check, hillslope_step, raw_drainage, channel_step, advance


def state(rows=4,cols=4,spacing=10.,cover=1.):
    g=Grid(rows,cols,spacing,spacing)
    return State(g,tuple((rows-i//cols)*.1 for i in range(g.size)),
                 (cover*g.area_m2,)*g.size,(0.,)*g.size,2700.,2700.)


class CoreTests(unittest.TestCase):
    def test_planes_units_and_directions(self):
        s=state()
        for east,south in ((0,0),(.3,.4),(-.4,.3),(.3,-.4),(-.3,-.4)):
            z=[east*x+south*y+13 for x,y in map(s.grid.xy,range(s.grid.size))]
            d=gradients(s.grid,z)
            for got in d["grade_m_per_m"]:
                self.assertAlmostEqual(got,math.hypot(east,south),places=12)
            for got in d["slope_degrees"]:
                self.assertAlmostEqual(got,math.degrees(math.atan(math.hypot(east,south))),places=10)
        self.assertEqual(s.grid.xy(0),(5.,5.))

    def test_reject_invalid_shapes_units_numbers(self):
        for rows,cols in ((1,2),(129,129),(True,4),(-1,4)):
            with self.assertRaises(ValueError): Grid(rows,cols,1.,1.)
        for spacing in (0,-1,math.nan,math.inf,True,10**1000,1e-300):
            with self.assertRaises(ValueError): Grid(2,2,spacing,spacing)
        s=state()
        for changes in ({"porosity":(1.,)*16},{"mobile_solid_m3":(-1.,)*16},{"bedrock_m":(0.,)},
                        {"rock_density_kg_m3":0},{"sediment_density_kg_m3":math.nan}):
            with self.assertRaises(ValueError): replace(s,**changes)

    def test_cover_porosity_and_density_are_not_interchangeable(self):
        s=state(cover=1.)
        p=replace(s,porosity=(.5,)*16)
        self.assertEqual(p.cover_m,(2.,)*16)
        self.assertEqual(p.mobile_solid_m3,s.mobile_solid_m3)
        with self.assertRaises(ValueError): channel_step(p,[1.]*16,[.01]*16,[.005]*16,1.,5.,.1,[15])

    def test_flat_closed_soil_is_exactly_unchanged(self):
        s=replace(state(),bedrock_m=(0.,)*16)
        out,b=hillslope_step(s,[.003]*16,1.)
        self.assertEqual(s,out); self.assertEqual(b["solid_volume_residual_m3"],0)

    def test_bare_steep_rock_is_not_given_a_soil_slope_cap(self):
        s=replace(state(cover=0),bedrock_m=tuple(1000.*i for i in range(16)))
        out,b=hillslope_step(s,[.003]*16,1.,[1.2]*16)
        self.assertEqual(out,s)
        self.assertEqual(b["internal_transferred_solid_m3"],0)

    def test_soil_supply_and_conservation_with_spatial_porosity(self):
        s=state(cover=.000001)
        s=replace(s,porosity=tuple(.1 if i%2 else .4 for i in range(16)))
        out,b=hillslope_step(s,[.003]*16,1.)
        self.assertGreater(b["internal_transferred_solid_m3"],0)
        self.assertGreater(b["limited_source_cells"],0)
        self.assertGreaterEqual(min(out.mobile_solid_m3),0)
        self.assertAlmostEqual(math.fsum(out.mobile_solid_m3),math.fsum(s.mobile_solid_m3),places=12)
        self.assertEqual(out.bedrock_m,s.bedrock_m)

    def test_zero_K_material_contact_blocks_local_diffusion(self):
        s=state(); k=[.003]*16
        k[8:12]=[0.]*4
        out,_=hillslope_step(s,k,1.)
        self.assertEqual(out.mobile_solid_m3[8:12],s.mobile_solid_m3[8:12])

    def test_diffusion_stability_and_nonlinear_domain_rejections(self):
        s=state()
        with self.assertRaises(ValueError): hillslope_step(s,[1000.]*16,100.)
        with self.assertRaises(ValueError): hillslope_step(s,[.003]*16,1.,[.001]*16)
        with self.assertRaises(ValueError): hillslope_step(s,[.003]*16,1.,periodic_x=1)

    def test_porosity_contrast_cannot_hide_bulk_surface_instability(self):
        s=State(Grid(2,2,1.,1.),(0.,)*4,(1.,0.,1.,0.),(0.,.99,0.,.99),2700.,2700.)
        with self.assertRaisesRegex(ValueError,"stability"):
            hillslope_step(s,[1.]*4,.1)
        stable,_=hillslope_step(s,[1.]*4,.0001)
        self.assertLessEqual(max(stable.surface_m),1.)

    def test_small_gradient_nonlinear_limit(self):
        s=replace(state(),bedrock_m=tuple(i*1e-5 for i in range(16)))
        a,_=hillslope_step(s,[.003]*16,1.)
        b,_=hillslope_step(s,[.003]*16,1.,[1.2]*16)
        self.assertLess(max(abs(x-y) for x,y in zip(a.surface_m,b.surface_m)),1e-12)

    def test_analytical_sinusoid_and_grid_convergence(self):
        fixture=CONTRACT["linear_sinusoid_fixture"]
        errors=[]
        for cols,dt in zip(fixture["cells"],fixture["time_steps_years"],strict=True):
            dx=fixture["length_m"]/cols; g=Grid(2,cols,dx,dx)
            phase=[math.sin(2*math.pi*(i%cols+.5)/cols) for i in range(g.size)]
            s=State(g,(0.,)*g.size,tuple((2+fixture["amplitude_m"]*p)*g.area_m2 for p in phase),
                    (0.,)*g.size,2700.,2700.)
            for _ in range(round(fixture["duration_years"]/dt)):
                s,_=hillslope_step(s,[fixture["K_m2_per_year"]]*g.size,dt,periodic_x=True)
            expected=fixture["amplitude_m"]*math.exp(-fixture["K_m2_per_year"]*(2*math.pi/fixture["length_m"])**2*fixture["duration_years"])
            got=math.fsum((z-2)*p for z,p in zip(s.surface_m,phase))/math.fsum(p*p for p in phase)
            error=abs(got-expected)
            self.assertLess(error/expected,CONTRACT["linear_sinusoid_amplitude_relative_error_max"])
            errors.append(error)
        for a,b in zip(errors,errors[1:]):
            self.assertGreater(a/b,CONTRACT["linear_sinusoid_grid_refinement_error_ratio_min"])

    def test_raw_drainage_keeps_pits_and_does_not_condition_bed(self):
        s=state(); z=list(s.bedrock_m); z[5]=-4; s=replace(s,bedrock_m=tuple(z))
        before=s.as_dict(); graph=raw_drainage(s,[15])
        self.assertIn(5,graph["unresolved_terminals"])
        self.assertEqual(before,s.as_dict())
        self.assertEqual(graph["receivers"][15],-1)
        for i,j in enumerate(graph["receivers"]):
            if j>=0:self.assertLess(s.surface_m[j],s.surface_m[i])

    def test_channel_joins_budget_and_runoff_not_rainfall(self):
        s=state(cover=.3)
        out,b=channel_step(s,[1.]*16,[.01]*16,[.005]*16,1.,5.,.01,[12,13,14,15])
        self.assertGreater(b["rock_loss_solid_m3"],0)
        self.assertLessEqual(abs(b["solid_volume_residual_m3"]),b["solid_volume_tolerance_m3"])
        self.assertAlmostEqual(b["water_input_m3"],16.)
        self.assertAlmostEqual(b["water_residual_m3"],0)
        self.assertFalse(b["basin_stage_solved"])
        self.assertNotEqual(out,s)

    def test_channel_zero_runoff_is_no_erosion(self):
        s=state()
        out,b=channel_step(s,[0.]*16,[.01]*16,[.005]*16,1.,5.,1.,[15])
        self.assertEqual(out,s)
        self.assertEqual(b["rock_loss_solid_m3"],0)

    def test_channel_timestep_rejected_not_grade_clipped(self):
        s=state()
        with self.assertRaises(ValueError):channel_step(s,[1.]*16,[10.]*16,[10.]*16,1.,5.,100.,[15])

    def test_control_conflicts_name_id_without_changing_surface(self):
        s=state(); before=s.as_dict()
        c={"id":"summit-A","cell":0,"minimum_m":3.,"maximum_m":4.,"role":"hard", "reason":"fixture",
           "source_status":"SYNTHETIC","source_sha256":"0"*64,"owner":"Engineering"}
        with self.assertRaisesRegex(ValueError,"summit-A"):constraints_check(s,[c])
        self.assertEqual(before,s.as_dict())
        c["role"]="soft"; self.assertEqual(constraints_check(s,[c])[0]["id"],"summit-A")

    def test_coupled_steps_repeat_and_expose_evolving_topology(self):
        s=state()
        args=(s,3,.01,[.003]*16,[1.]*16,[.01]*16,[.005]*16,1.,5.,[12,13,14,15],[])
        a,records=advance(*args); b,repeated=advance(*args)
        self.assertEqual(a,b);self.assertEqual(records,repeated)
        self.assertEqual(len(records),3)
        self.assertIn("graph",records[-1]["channel"])
        self.assertNotIn("graph",records[0]["channel"])
        self.assertNotEqual(a.surface_m,s.surface_m)


if __name__=="__main__":unittest.main()
