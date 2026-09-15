"""Small independent oracles and real-source invocation; never generate a map."""
from __future__ import annotations

import ast
import copy
import json
import math
import tempfile
import unittest
from decimal import Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from affine import Affine
from rasterio.windows import Window
from shapely.geometry import box

from . import core, provenance
from .bindings import bind, macro_source, macro_component_fixture, checked_source, verify_sources, _geology_zoom


class Numerics(unittest.TestCase):
    def test_seiche_residual_rejects_fake_mode(self):
        m=bind('marine');wet=np.ones((4,5),bool);depth=np.full((4,5),100.)
        operator,_=m.shallow_water_operator(depth,wet,1.)
        periods,modes,values,_=m.solve_seiche_modes(depth,wet,1.,mode_count=2)
        self.assertEqual(core.validate_seiche_eigenpairs(operator,wet,periods,modes,values)['status'],'PASS')
        bad=[np.zeros(wet.shape),modes[1]];bad[0][0,0]=1
        with self.assertRaises(ValueError):core.validate_seiche_eigenpairs(operator,wet,periods,bad,values)
        with self.assertRaises(ValueError):m.shallow_water_operator(depth,wet,1e308)
    def test_hg23_loads_joined_by_id(self):
        m=bind('hg23_envelope',{'base':SimpleNamespace(SEA='SEA')})
        roots={'ids':np.array([10,20]),'types':np.array([1,1]),'loads':np.array([[1.]*12,[7.]*12])}
        records=[{'root_cell_id':20,'terminal_type':1,'candidate_segment_ids':['b'],'status':'resolved'},{'root_cell_id':10,'terminal_type':1,'candidate_segment_ids':['a'],'status':'resolved'}]
        successor={'eligible':{'a','b'},'ordinary_successor':{},'ordinary_terminal':{'a':'TA','b':'TB'}}
        result=m.make_envelope(roots,records,successor)
        np.testing.assert_array_equal(result['lower'][0],1.);np.testing.assert_array_equal(result['lower'][1],7.)
        with self.assertRaises(ValueError):m.make_envelope(roots,[records[0],records[0]],successor)

    def test_biome_actual_hydro_branch_rejects_unknown(self):
        m=bind('biome_hydrology_reader')
        klass=next(n for n in ast.parse(m.source).body if isinstance(n,ast.ClassDef) and n.name=='InputSet')
        read=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='read')
        branch=next(n for n in read.body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.hydro is not None')
        obj=SimpleNamespace(hydro=object(),config={},_read_named=lambda *args:[np.array([[np.nan]])])
        scope=dict(m.namespace);scope.update({'self':obj,'context':{},'window':None,'eligible':np.ones((1,1),bool),'water_pending':np.zeros((1,1),bool),'h':1,'w':1})
        with self.assertRaises(ValueError):exec(compile(ast.Module(body=[branch],type_ignores=[]),'actual_hydro_reader_branch','exec'),scope)
    def test_cryo_classification_unknown_negative_and_impossible(self):
        m=bind('cryosphere_science');active=np.ones((1,1),bool)
        for snow,balances in ((np.nan,[0,0]),(-1,[0,0]),(1,[np.nan,0]),(0,[1,0])):
            with self.assertRaises(ValueError):m.classify_regime(np.array([[snow]]),np.array(balances,dtype=float).reshape(2,1,1),active)
        result=m.classify_regime(np.array([[10.]]),np.array([2.,-2.]).reshape(2,1,1),active)
        self.assertEqual(result.regime[0,0],3)
        self.assertTrue(result.possible_small_ice_support[0,0]);self.assertFalse(result.robust_small_ice_support[0,0])

    def test_cryo_real_store_mass_identity(self):
        m=bind('cryosphere_science');sf=np.full((12,1,1),10.);temp=np.full_like(sf,-3.)
        result=m.simulate_snow_year(sf,temp,np.ones((1,1),bool),3.,2.)
        mass=float(result.initial_swe_mm[0,0]+120-result.annual_melt_mm[0,0]-result.final_swe_mm[0,0])
        self.assertAlmostEqual(mass,0.,places=12)
        with self.assertRaises(ValueError):m.simulate_snow_year(np.full_like(sf,-1e-12),temp,np.ones((1,1),bool),3.,2.)
        with self.assertRaises(ValueError):m.simulate_snow_year(sf,np.full_like(sf,1e308),np.ones((1,1),bool),3.,2.)

    def test_weighted_bathymetry_ignores_only_zero_weight_unknown(self):
        m=bind('bathymetry_science')
        result=m.weighted_gaussian(np.array([[np.nan,7.,7.]]),np.array([[0.,1.,1.]]),1.)
        np.testing.assert_allclose(result,7.,rtol=1e-15)
        with self.assertRaises(ValueError):m.weighted_gaussian(np.array([[np.nan,7.]]),np.ones((1,2)),1.)
        result=m.weighted_gaussian(np.array([[2.,2.]]),np.array([[1e-200,1.]]),0.)
        np.testing.assert_array_equal(result,2.)

    def test_submerged_mean_preserves_land_unknown(self):
        m=bind('bathymetry_inputs',{'SCREEN_FACTOR':2})
        mask=np.array([[1,0],[0,0]],np.uint8);terrain=np.array([[-10.,np.nan],[np.nan,np.nan]])
        counts,fraction,mean,wet=m.aggregate_500m(mask,terrain)
        self.assertEqual(wet[0,0],-10.);self.assertEqual(counts[0,0],1);self.assertEqual(fraction[0,0],.25)
        self.assertTrue(np.isnan(mean[0,0]))
        mask[0,1]=1
        with self.assertRaises(ValueError):m.aggregate_500m(mask,terrain)
    def test_auxiliary_masks_and_affines(self):
        class Raster:
            def __init__(self,values,transform):
                self.values=values;self.height,self.width=values.shape;self.transform=transform;self.nodata=None
            def read(self,band,window=None,**kw):
                if window is None:return self.values.copy()
                return self.values[int(window.row_off):int(window.row_off+window.height),int(window.col_off):int(window.col_off+window.width)].copy()
        m=bind('climate_auxiliary',{'Window':Window,'TRANSFORM':Affine(1,0,0,0,1,0)})
        for values,transform in ((np.array([[np.nan]]),Affine.identity()),(np.array([[.5]]),Affine.identity()),(np.ones((1,1)),Affine(1,.25,0,0,1,0))):
            with self.assertRaises(ValueError):m.exact_auxiliary_fraction(Raster(values,transform),1,1)
        np.testing.assert_array_equal(m.exact_auxiliary_fraction(Raster(np.array([[1,0],[0,1]],np.uint8),Affine(.5,0,0,0,.5,0)),1,1),.5)

    def test_empty_regional_buffer_and_flat_seams(self):
        class FlatRaster:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,band,window):return np.zeros((int(window.height),int(window.width)))
        m=bind('climate_full_metrics',{'land':np.ones((4,4),bool),'Window':Window,'TILE':2,'W':6,'H':6,
            'band_map':lambda p:{'annual_mean_temperature_c':1,'annual_precipitation_mm':2},'rasterio':SimpleNamespace(open=lambda p:FlatRaster())})
        self.assertFalse(m.buffered(np.zeros((4,4),bool),20).any())
        self.assertTrue(m.global_output_seams({'r1_derived':None,'c4_derived':None})['pass'])

    def test_macro_geometry_unknown_not_zero(self):
        class Raster:
            nodata=-9999.
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,band):return np.array([[-9999.,1.]])
        m=bind('macro_geometry',{'rasterio':SimpleNamespace(open=lambda p:Raster()),'H':1,'W':2,'REQUIRED_DOMAIN':np.array([[False,True]])})
        result=m.read_tif(None);self.assertTrue(np.isnan(result[0,0]));self.assertEqual(result[0,1],1.)
        m.namespace['REQUIRED_DOMAIN']=np.ones((1,2),bool)
        with self.assertRaises(RuntimeError):m.read_tif(None)
    def test_all_sources_preserved(self):
        self.assertEqual(len(verify_sources()['sources']),80)

    def test_real_kernel_parent_means(self):
        for fine in (1,2,5,50):
            kernel=bind('climate_kernel',{'FINE':fine})
            for shape in ((1,1),(1,3),(2,2),(4,3)):
                values=np.arange(np.prod(shape),dtype=float).reshape(shape)*10
                coeff=kernel.conservative_coefficients(values)
                children=kernel.smooth_reconstruct(coeff,0,0,shape[0]*fine,shape[1]*fine)
                means=children.reshape(shape[0],fine,shape[1],fine).mean(axis=(1,3),dtype=np.float64)
                np.testing.assert_allclose(means,values,rtol=0,atol=2e-5)

    def test_fu_decimal_oracle_and_budget(self):
        kernel=bind('climate_kernel')
        for p,e,w in ((0.,10.,3.4),(10.,0.,3.4),(400.,600.,3.4),(1e-100,1e100,4.),(1e200,1e200,2.)):
            actual=float(kernel.fu_aet(p,e,w))
            self.assertTrue(0<=actual<=min(p,e))
            if p and e and max(p,e)/min(p,e)<1e10:
                with localcontext() as context:
                    context.prec=80
                    pp,ee,ww=map(lambda x:Decimal(str(x)),(p,e,w))
                    expected=float(pp+ee-(pp**ww+ee**ww)**(1/ww))
                self.assertAlmostEqual(actual/expected,1.,places=13)

    def test_fu_invalid(self):
        for p,e,w in ((-1,2,3.4),(np.nan,2,3.4),(1,np.inf,3.4),(1,2,1)):
            with self.assertRaises(ValueError): core.fu_aet(p,e,w)

    def test_lake_real_producer_assignment_conserves(self):
        external=np.full((12,2,3),2.); lake=np.ones_like(external)
        domain=np.ones((2,3),bool); domain[0,0]=False; lake[:,0,0]=0
        factor=np.broadcast_to(np.arange(1,7).reshape(1,2,3),(12,2,3)).copy()
        area=np.arange(1,7).reshape(2,3).astype(float)
        volumes=np.arange(1,13,dtype=float)*25
        x,l,receipt=macro_component_fixture(external,lake,factor,area,domain,volumes)
        np.testing.assert_array_equal(x,external*factor)
        np.testing.assert_allclose((l*area).sum(axis=(1,2)),volumes,rtol=2e-15)
        self.assertEqual(receipt['generation'].split(';')[0],'NOT_RUN')
        self.assertTrue(np.all(l[:,~domain]==0))

    def test_lake_zero_and_missing_support(self):
        z=np.zeros((12,1,1)); one=np.ones_like(z); mask=np.ones((1,1),bool)
        _,l,_=macro_component_fixture(one,z,one,1.,mask,np.zeros(12))
        self.assertFalse(l.any())
        with self.assertRaises(ValueError): macro_component_fixture(one,z,one,1.,mask,np.ones(12))
        with self.assertRaises(ValueError): macro_component_fixture(one,one,one*np.nan,1.,mask,np.ones(12))

    def test_macro_not_activated(self):
        with self.assertRaisesRegex(RuntimeError,'not activated'): bind('macro').main()

    def test_macro_original_budget_and_output_share_components(self):
        source,_=macro_source()
        self.assertNotIn('(precip_external_raw * scale + lake_precip) * R1T13_CORRECTION',source)
        self.assertIn('p = (precip_external_raw * scale + lake_precip).sum(axis=0)',source)
        self.assertIn('precip = precip_external_raw * scale + lake_precip',source)
        compile(source,'actual_corrected_macro','exec')

    def test_edaphic_no_fake_boundary(self):
        science=bind('biome_science')
        np.testing.assert_array_equal(science.edaphic_feather_weight(np.ones((4,4),bool),1.),1.)
        np.testing.assert_array_equal(science.edaphic_feather_weight(np.zeros((4,4),bool),1.),0.)
        mask=np.array([[False,True,True],[False,True,True]])
        expected=np.tile([0,1-math.exp(-1/30),1-math.exp(-2/30)],(2,1))
        np.testing.assert_allclose(science.edaphic_feather_weight(mask,1.),expected,atol=1e-8)

    def test_edaphic_invalid(self):
        for mask,cell,scale in ((np.array([[np.nan]]),1,30),(np.ones((1,1),bool),np.nan,30),(np.ones((1,1),bool),1,0)):
            with self.assertRaises(ValueError): core.edaphic_weight(mask,cell,scale)

    def test_surface_envelope_complete_scenarios_only(self):
        m=bind('surface_envelopes')
        values=np.full((2,12,1,1),10.); values[1]=100.; values[1,0]=np.nan
        lo,median,high,count,complete=m.strict_monthly_envelope(values,np.ones((1,1),np.uint16))
        self.assertTrue(complete[0,0]); self.assertEqual(count[0,0],1)
        np.testing.assert_array_equal(high,10.)
        np.testing.assert_array_equal(median,10.)
        _,_,high,_,complete=m.strict_monthly_envelope(values,np.full((1,1),2,np.uint16))
        self.assertFalse(complete[0,0]); self.assertTrue(np.isnan(high).all())

    def test_surface_expected_count_strict(self):
        for count in (np.ones((1,1)),np.array([[-1]]),np.array([[True]]),np.array([[3]])):
            with self.assertRaises(ValueError): bind('surface_envelopes').strict_monthly_envelope(np.ones((2,12,1,1)),count)

    def test_exact_protected_union(self):
        f=bind('surface_envelopes').protected_overlap_fraction
        a={'rows_100m_half_open':[0,5],'cols_100m_half_open':[0,5]}
        b={'rows_100m_half_open':[3,8],'cols_100m_half_open':[3,8]}
        self.assertEqual(f((1,1),0,0,[a,a])[0,0],.25)
        self.assertEqual(f((1,1),0,0,[a,b])[0,0],.46)
        self.assertEqual(f((1,1),0,0,[])[0,0],0.)

    def test_marine_all_cardinal_fetches(self):
        m=bind('marine'); polygon=box(0,0,10,20)
        for point,bearing,expected in (((5,20),0,20),((0,10),90,10),((5,0),180,20),((10,10),270,10)):
            self.assertAlmostEqual(m.directional_fetch_km(polygon,point,bearing),expected,places=10)
        self.assertEqual(m.directional_fetch_km(polygon,(5,20),180),0.)
        with self.assertRaises(ValueError): m.directional_fetch_km(polygon,(5,20),0,ray_length_km=1.)

    def test_narrow_gap_not_jumped(self):
        # A 20 m dry gap immediately north of the south shore: no 50 m jump.
        polygon=box(0,0,10,19.97).union(box(0,19.99,10,20))
        self.assertAlmostEqual(bind('marine').directional_fetch_km(polygon,(5,20),0),.01,places=9)

    def test_marine_unknown_area(self):
        m=bind('marine')
        with self.assertRaises(ValueError): m.aggregate_depth(np.array([[np.nan,10.]]),np.ones((1,2),np.uint8),2)
        c,d=m.aggregate_depth(np.array([[np.nan,10.]]),np.array([[0,1]],np.uint8),2)
        self.assertEqual(c[0,0],1); self.assertEqual(d[0,0],10.)

    def test_marine_analytic_spectrum(self):
        m=bind('marine'); a,_=m.shallow_water_operator(np.full((3,4),100.),np.ones((3,4),bool),1.)
        a=a.toarray()
        expected=np.sort([9.80665*100/1e6*(4-2*math.cos(math.pi*r/3)-2*math.cos(math.pi*c/4)) for r in range(3) for c in range(4)])
        np.testing.assert_allclose(np.linalg.eigvalsh(a),expected,atol=3e-18,rtol=1e-14)
        np.testing.assert_array_equal(a,a.T)
        np.testing.assert_allclose(a.sum(axis=1),0,atol=1e-18)

    def test_comparators_unknown_mismatch(self):
        for name,func in (('cryosphere_compare','max_difference'),('bathymetry_compare','max_abs')):
            f=getattr(bind(name),func)
            with self.assertRaises(ValueError): f(np.array([np.nan],np.float32),np.array([1.],np.float32))
            result=f(np.array([np.nan,2],np.float32),np.array([np.nan,2],np.float32))
            self.assertEqual(result,(0.,0,0,0,0) if func=='max_difference' else 0.)

    def test_hg2_slow_oracle(self):
        r=bind('hg2_seasonal').periodic_slow_release(np.ones((12,1,1)),1e20,np.ones((1,1),bool))
        self.assertAlmostEqual(float(r['monthly_release_mm'].sum()),12.,places=12)
        self.assertEqual(float(r['water_balance_residual_mm'][0,0]),0.)
        with localcontext() as ctx:
            ctx.prec=80
            tau=Decimal('1e20'); days=[31,28,31,30,31,30,31,31,30,31,30,31]
            end=Decimal(0)
            for d in days: end=(end+1)*(-Decimal(d)/tau).exp()
            storage=end/(1-(-Decimal(365)/tau).exp()); release=[]
            for d in days:
                pre=storage+1; closing=pre*(-Decimal(d)/tau).exp(); release.append(float(pre-closing)); storage=closing
        np.testing.assert_allclose(r['monthly_release_mm'][:,0,0],release,rtol=5e-15)

    def test_hg2_reject_unrepresentable(self):
        with self.assertRaises(ValueError): bind('hg2_seasonal').periodic_slow_release(np.full((12,1,1),1e308),1e20,np.ones((1,1),bool))

    def test_geology_cell_centres(self):
        a=np.array([[2.,6.],[2.,6.]])
        result=_geology_zoom(a,4,order=1)
        # At 1 km centres x=.5,1.5,...,7.5; source centre x=2,6.
        expected=np.tile(np.clip(np.arange(8)+.5,2,6),(8,1))
        np.testing.assert_array_equal(result,expected)

    def test_hazard_unknown_refuses_absence(self):
        fields={'domain':np.ones((1,1),bool),'precip':np.array([[np.nan]])}
        for name in ('hazard_mh','hazard_vh'):
            with self.assertRaises(ValueError): bind(name).classify(fields)
        fields['precip'][0,0]=-9999
        with self.assertRaises(ValueError): bind('hazard_mh').classify(fields)

    def test_vh_invalid_ice_and_direction(self):
        f={'domain':np.ones((1,1),bool),'small_ice':np.array([[255]])}
        with self.assertRaises(ValueError): bind('hazard_vh').classify(f)
        m=bind('hazard_vh'); source=np.zeros((9,9),bool);source[4,4]=True;domain=np.ones_like(source)
        southeast=m.direction_sector(source,domain,math.cos(math.radians(55)),math.sin(math.radians(55)),40)
        self.assertTrue(southeast[7,7]);self.assertFalse(southeast[7,1])


class Integrity(unittest.TestCase):
    def test_marine_actual_release_stale_pass_cannot_package(self):
        for name in ('bathymetry_release','marine_release'):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'audit').mkdir();(root/'data').mkdir();(root/'data/values').write_bytes(b'first')
                digest=provenance.package_payload_identity(root)
                record={'status':'PASS','reviewer':'fixture','bound_payload':digest}
                for path in ('audit/INDEPENDENT_VALIDATION.json','audit/VISUAL_REVIEW_ATTESTATION.json'):(root/path).write_text(json.dumps(record))
                (root/'data/values').write_bytes(b'other')
                archive=root/'fixture.zip'
                m=bind(name,{'OUT':root,'ZIP':archive})
                with self.assertRaises(ValueError):m.main()
                self.assertFalse(archive.exists());self.assertFalse((root/'MANIFEST.json').exists())

    def test_climate_actual_package_requires_bound_attestation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir();(root/'data/values').write_bytes(b'fixture')
            for name in ('climate_package','climate_corrected_package'):
                m=bind(name,{'RUN':root,'PACKAGE_MACHINE_ATTESTATION':{'status':'PASS'},'PACKAGE_VISUAL_ATTESTATION':{'status':'PASS'}})
                with self.assertRaises(ValueError):
                    m.package({}, {}) if name=='climate_package' else m.main()
    def test_actual_r14_adjudication_assignment(self):
        m=bind('r14_release')
        function=next(n for n in ast.parse(m.source).body if isinstance(n,ast.FunctionDef) and n.name=='main')
        nodes=[]
        for n in function.body:
            if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Subscript) and isinstance(n.targets[0].value,ast.Name) and n.targets[0].value.id=='annual_audit' and isinstance(n.targets[0].slice,ast.Constant) and n.targets[0].slice.value in ('visual_adjudication','accepted_geometry_pass'):nodes.append(n)
        scope=dict(m.namespace);scope['annual_audit']={'machine_pass':False,'integrity':{},'gates':{'no_new_southwest_planar_front_numeric':False}}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual_release_assignments','exec'),scope)
        self.assertFalse(scope['annual_audit']['accepted_geometry_pass'])
        self.assertFalse(scope['annual_audit']['visual_adjudication']['pass'])

    def test_actual_pipeline_parent_hash_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'controls').mkdir();source=root/'source';source.write_bytes(b'first')
            config={'fixture':True};plan={'status':'PASS_READY_FOR_C1','input_config_sha256':__import__('hashlib').sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                'implementation_lineage':{},'parent_inputs':{'climate':{'path':str(source),'sha256':provenance.sha256(source)}}}
            (root/'controls/RESOLVED_PIPELINE_PLAN.json').write_text(json.dumps(plan))
            m=bind('pipeline_identity',{'read_json':lambda p:json.loads(p.read_text()),'resolve':Path,'sha256':provenance.sha256,'parent_inputs':lambda c,p:{'climate':source}})
            m.namespace['validate_config']=lambda c:{'run':root}
            m.require_prepared(config)
            source.write_bytes(b'other')
            with self.assertRaises(ValueError):m.require_prepared(config)

    def test_s2e_role_lock_matches_actual_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';source.write_bytes(b'fixture')
            lock={'sources':[{'role':'climate','path':'input','bytes':7,'sha256':provenance.sha256(source)}]}
            (root/'SOURCE_LOCK.json').write_text(json.dumps(lock))
            m=bind('s2e_common',{'RUN':root,'ROOT':root,'PATHS':{'climate':source},'load':lambda p:json.loads(p.read_text()),'sha256':provenance.sha256})
            self.assertEqual(m.verify_lock(),lock)
            (root/'SOURCE_LOCK.json').write_text(json.dumps({'sources':[]}))
            with self.assertRaises(ValueError):m.verify_lock()

    def test_s2e_unavailable_rss_cannot_pass(self):
        m=bind('s2e_common',{'peak_working_set_bytes':lambda:0,'path_bytes':lambda p:0,'RUN':Path('.'),'HARD_RSS_BYTES':1000,'HARD_SCRATCH_BYTES':1000,'HARD_RUNTIME_SECONDS':1})
        with self.assertRaises(RuntimeError):m.require_resource_gate()

    def test_s2e_actual_array_shape_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            np.save(root/'land_bundle_release_mm.npy',np.zeros((1,1,1)))
            m=bind('s2e_forcing',{'FORCING':root,'PARENT_COUNT':2})
            with self.assertRaises(ValueError):m.initialise_outputs(np.empty(0,np.uint32),[],[])

    def test_s2e_actual_resume_assignment_rejects_changed_payload(self):
        m=bind('s2e_forcing')
        function=next(n for n in ast.parse(m.source).body if isinstance(n,ast.FunctionDef) and n.name=='full')
        ifnode=next(n for n in ast.walk(function) if isinstance(n,ast.If) and ast.unparse(n.test)=='key in completed')
        # Remove continue only because this tiny fixture is not inside the full loop.
        statements=[n for n in ifnode.body if not isinstance(n,ast.Continue)]
        scope=dict(m.namespace);scope.update({'key':'r0000c0000','land_grid':np.ones((1,12,1,1)),'patch':np.ones((1,12,0)),'p_grid':np.ones((12,1,1)),
            'pet_grid':np.ones((12,1,1)),'target_index':np.array([],np.uint32),'row0':0,'row1':1,'col0':0,'col1':1,'tile_records':{'r0000c0000':{'payload_sha256':'0'*64}}})
        with self.assertRaises(ValueError):exec(compile(ast.Module(body=statements,type_ignores=[]),'actual_resume_body','exec'),scope)

    def test_s2e_checkpoint_without_payload_hash_is_rejected(self):
        with self.assertRaises(ValueError):provenance.forcing_completed_state({'completed_tile_keys':['r0000c0000'],'tiles':[{'key':'r0000c0000'}]},(1,1),1)
    def test_parent_same_size_mtime_change(self):
        row={'path':'parent','bytes':10,'mtime_ns':1,'actual_sha256':'a'*64,'expected_sha256':'a'*64,'hash_matches_expected':True}
        before={'status':'PASS','records':[row]}; after=copy.deepcopy(before)
        after['records'][0]['actual_sha256']='b'*64
        self.assertEqual(bind('soil_parent_identity').compare_parent_snapshot(before,after)['status'],'FAIL')
        after=copy.deepcopy(before);after['records'][0]['actual_sha256']=None
        with self.assertRaises(ValueError): bind('soil_parent_identity').compare_parent_snapshot(before,after)

    def test_path_sibling_prefix_rejected(self):
        with self.assertRaises(ValueError): provenance.within('/tmp/runs-evil/out','/tmp/runs')

    def test_conflicting_gate(self):
        for record in ({'status':'FAIL','pass':True},{'status':'PASS','pass':False},{'status':'PASS_PENDING_VISUAL'},{'status':'PASS','checks':{'a':1}}):
            with self.assertRaises(ValueError): provenance.require_pass(record)

    def test_bound_attestation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.bin';path.write_bytes(b'original')
            audit={'integrity':{'image.bin':provenance.sha256(path)},'gates':{'no_new_southwest_planar_front_numeric':False}}
            self.assertFalse(provenance.visual_adjudication(audit)['pass'])
            record={'status':'PASS','pass':True,'reviewer':'Fixture reviewer','reviewed_utc':'2026-09-10T00:00:00Z','finding':'fixture only','integrity':audit['integrity'],'adjudicated_gates':['no_new_southwest_planar_front_numeric']}
            self.assertTrue(provenance.visual_adjudication(audit,record,temp)['pass'])
            path.write_bytes(b'changed!')
            with self.assertRaises(ValueError): provenance.visual_adjudication(audit,record,temp)

    def test_r14_actual_release_no_manufactured_attestation(self):
        m=bind('r14_release')
        tree=ast.parse(checked_source('work/climate_ecology/c1r2_seam_repair/finalize_r1t14_climate_review.py'))
        # Verify the *compiled source function* resolves its adjudication to our
        # identity validator, never the historical unconditional PASS literal.
        self.assertIn('visual_adjudication',m.main.__code__.co_names)
        self.assertNotIn('PASS_WARNING_IS_GRADED_TERRAIN_FOLLOWING_FEATURE',m.main.__code__.co_consts)
        self.assertIs(m.main.__globals__['_identity'],provenance)

    def test_final_manifest_sees_added_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp); (p/'a').write_bytes(b'a')
            old=provenance.finish_manifest(p)
            provenance.require_fresh_manifest(p,old)
            (p/'b').write_bytes(b'b')
            with self.assertRaises(ValueError): provenance.require_fresh_manifest(p,old)
            new=provenance.finish_manifest(p)
            self.assertEqual([r['path'] for r in new['files']],['a','b'])

    def test_nested_manifest_is_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'nested').mkdir();(p/'nested/MANIFEST.json').write_text('{}')
            self.assertEqual(provenance.fresh_manifest(p)['files'][0]['path'],'nested/MANIFEST.json')

    def test_actual_biome_formation_rejects_wrapped_class(self):
        m=bind('biome_formation');support=np.ones((10,3,1,1));eligible=np.ones((1,1),bool)
        for bad in (np.array([[257]]),np.array([[1.5]]),np.array([[True]])):
            with self.assertRaises(ValueError):m.classify_formations(support,eligible,bad)
        result=m.classify_formations(support,eligible,np.array([[1]]))
        self.assertIn(int(result.composite_class[0,0]),[1,2,3])

    def test_actual_biome_uncertainty_bit256_rendered(self):
        m=bind('biome_uncertainty_render')
        function=next(n for n in ast.parse(m.source).body if isinstance(n,ast.FunctionDef) and n.name=='render_reviews')
        assignment=next(n for n in function.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='bit_count')
        scope={'np':np,'arrays':{'formation_uncertainty':np.array([[256,257,511]],np.uint16)}}
        exec(compile(ast.Module(body=[assignment],type_ignores=[]),'actual_uncertainty_assignment','exec'),scope)
        np.testing.assert_array_equal(scope['bit_count'],[[1,2,9]])

    def test_actual_hazard_validator_rejects_nonbinary_stack(self):
        class Dataset:
            def __init__(self,data,description=('mean_elevation_m',)):
                self.data=data;self.descriptions=description;self.height,self.width=data.shape[-2:];self.count=data.shape[0];self.nodata=255;self.transform=(1,0,0,0,1,0);self.crs=None
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return self.data if not args else self.data[args[0]-1]
        for name,count in (('hazard_mh_validation',8),('hazard_vh_validation',9)):
            bad=np.zeros((count*4,1,2),np.uint8);bad[0,0,0]=2
            diag=Dataset(np.ones((1,1,2)));diag.nodata=-9999.;sup=Dataset(bad)
            def opened(path):
                if 'support-alternatives' in str(path):return sup
                if 'domain_and_classification' in str(path):return Dataset(np.ones((2,1,2)))
                return diag
            m=bind(name,{'rasterio':SimpleNamespace(open=opened),'FULL':Path('/fixture'),'ROOT':Path('/fixture')})
            m.namespace['replay']=(lambda d:({},{})) if name.endswith('vh_validation') else (lambda d:{})
            with self.assertRaisesRegex(ValueError,'binary'):m.validate_full()
            sup.transform=(1,0,1,0,1,0)
            with self.assertRaisesRegex(ValueError,'spatial grid mismatch'):m.validate_full()
        good=np.array([[[1,255]],[[0,255]],[[1,255]],[[2,255]]],np.uint8)
        core.require_hazard_stack(good,np.array([[True,False]]),1)
        good[3,0,0]=3
        with self.assertRaises(ValueError):core.require_hazard_stack(good,np.array([[True,False]]),1)

    def test_actual_marine_validator_is_bound(self):
        m=bind('marine_validation')
        self.assertIn('validate_seiche_eigenpairs',m.main.__code__.co_names)

    def test_hg0_final_failure_stops_before_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'fixture'; (out/'audit/independent').mkdir(parents=True)
            reports={
                'audit/independent/HG0_R2_1_INDEPENDENT_VALIDATION.json':{'overall_r2_1_status':'FAIL'},
                'audit/HG0_R2_1_RENDERED_VISUAL_QA.json':{},
                'audit/HG0_R2_1_POSTBUILD_SCIENTIFIC_AUDIT.json':{},
                'audit/HG0_R2_1_PARENT_NO_MUTATION_AUDIT.json':{'status':'PASS'},
                'audit/HG0_R2_1_SERIALIZATION_AND_MASK_AUDIT.json':{'status':'PASS'}}
            for name,record in reports.items(): (out/name).write_text(json.dumps(record))
            archive=Path(temp)/'fixture.zip'
            m=bind('hg0_package',{'OUT':out,'ZIP_PATH':archive,'EXPECTED':{'r2_review_zip':'a','r2_review_manifest':'b'},'COMPOSITION_AUDIT':{'status':'PASS'},'utc_now':lambda:'fixture',
                'write_json':lambda p,o:p.write_text(json.dumps(o))})
            with self.assertRaises(ValueError): m.make_manifest_and_zip({'overall_preflight_status':'PASS'}, {})
            self.assertFalse(archive.exists());self.assertFalse((out/'MANIFEST.json').exists())
            self.assertEqual(json.loads((out/'audit/HG0_R2_1_PACKAGE_VALIDATION.json').read_text())['status'],'FAIL')

    def test_biome_real_build_finalises_after_all_additions(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'BM1R4_fixture'
            def write(p,o): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o))
            def original_build(config,target,replace):target.mkdir();(target/'initial').write_bytes(b'initial')
            def extra(config,target):p=target/'effective';p.write_bytes(b'effective');return p
            parent=SimpleNamespace(base=SimpleNamespace(build_full=original_build,rel=str,write_json=write),_adapt_config=lambda c:c,
                _materialize_legacy_context_bridge=lambda p:{},_create_presentation_aliases=lambda p:None,
                _refresh_bm1r3_metadata=lambda *args:{'status':'PASS'})
            m=bind('biome_builder',{'parent':parent,'preflight':lambda c:{'status':'PASS','authority':{}},'install_patch':lambda:None,
                '_write_effective_edaphic_data':extra,'_create_bm1r4_aliases':lambda p:[],'HERE':Path(temp)})
            m.build_full({'ecotone_margin_quantile':10.},out)
            manifest=json.loads((out/'MANIFEST.json').read_text())
            names={x['path'] for x in manifest['files']}
            self.assertTrue({'initial','effective','lineage/BM1R4_SUCCESSOR_LINEAGE.json','README_FIRST.md'}<=names)
            with self.assertRaises(ValueError):m.build_full({},out,replace=True)


if __name__=='__main__':
    unittest.main()
