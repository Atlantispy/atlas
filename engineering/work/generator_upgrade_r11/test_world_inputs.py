"""Pinned real owner returns; synthetic small indices/lineage, never new maps."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import unittest

from . import world_inputs as w

INDEX = Path(r'C:\Users\LOCAL_USER\Documents\Codex\2026-09-02\the-diadem-local-tasks\work\r11_geo_closure\OWNER_DELTAS_P1_P2.json')


def actual_package():
    raw = INDEX.read_bytes()
    if hashlib.sha256(raw).hexdigest() != w.INDEX_SHA:
        raise ValueError('owner delta index changed')
    delta = json.loads(raw)
    bindings = {str(INDEX): w.INDEX_SHA}
    for r in delta['artifacts'] + delta['source_returns']:
        p = Path(r['path'])
        if hashlib.sha256(p.read_bytes()).hexdigest() != r['sha256']:
            raise ValueError('actual owner delta source changed')
        bindings[str(p)] = r['sha256']
        if 'evidence_path' in r:
            p = Path(r['evidence_path'])
            if hashlib.sha256(p.read_bytes()).hexdigest() != r['evidence_sha256']:
                raise ValueError('actual owner evidence changed')
            bindings[str(p)] = r['evidence_sha256']
    # Same explicitly supplied interpretation as the root's package, not a new
    # scientific choice. Large data payloads are not loaded by these unit tests.
    return {'owner_deltas': delta, 'source_bindings': bindings,
        'effective_interpretation': {'physical': {'selected_branch': w.COMPOSITE,
            'original_reference_columns_automatically_rebound': False},
            'political': {'new_world_legacy_source_policy': 'REJECTED_CONTROL_DO_NOT_SEED'}}}


class WorldInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = actual_package()

    def node(self, name, *, sha=None, role='OWNER_NEUTRAL_PHYSICAL', parents=None):
        if sha is None:
            sha = sorted(w.PHYSICAL_HASHES)[0]
        return {'node_id': name, 'kind': 'SOURCE' if parents is None else 'DERIVED',
            'sha256': sha, 'source_path': 'ISOLATED_TEST/' + name if parents is None else None,
            'role': role, 'parents': [] if parents is None else list(parents), 'lineage_complete': True,
            'evidence': 'ISOLATED TEST lineage; source hash is an owner-listed identity, not a new large-payload verification.'}

    def lineage_package(self, nodes):
        p = deepcopy(self.p)
        for n in nodes:
            if n['kind'] == 'SOURCE':
                p['source_bindings'][n['source_path']] = n['sha256']
        return p

    def legacy(self):
        a = self.node('v11', sha=sorted(w.LEGACY_HASHES)[0], role='LEGACY_STAGE6C_V11')
        z = self.node('stage3', sha='3'*64, role='INHERITED_STAGE3_POLITICAL_MASK', parents=['v11'])
        b = self.node('stage4', sha='4'*64, role='INHERITED_STAGE4_HOST_JURISDICTION', parents=['stage3'])
        c = self.node('stage5b', sha='5'*64, role='INHERITED_STAGE5B_POLITICAL_FILTER', parents=['stage4'])
        d = self.node('renamed-opportunity', sha='6'*64, role='OWNER_NEUTRAL_DERIVED', parents=['stage5b'])
        return [a, z, b, c, d]

    def terrain(self, value, coverage='PRESENT_VERIFIED', **extra):
        args = dict(coverage=coverage, authority_id=w.AUTHORITY_ID, generation=0, merkle_root=w.TERRAIN_ROOT)
        args.update(extra)
        return w.elevation(self.p, value, **args)

    def test_real_owner_decisions_and_unknowns_retained(self):
        result = w.declared_frames(self.p)
        self.assertEqual(result['frames'][w.COMPOSITE]['shape'], [18600,22000])
        self.assertIsNone(result['world_date'])
        self.assertIsNone(result['vertical']['water_family_offsets'])
        self.assertIsNone(result['vertical']['precise_datum_realisation'])
        self.assertIsNone(result['accepted_cross_frame_join'])
        self.assertIsNone(result['boundary_conditions'])
        self.assertEqual(result['raw_metadata'], {'crs':None,'band_units':None,'nodata':None,'zarr_fill_value':0})

    def test_composite_first_last_exact_centres_and_metres(self):
        first = w.coordinates(self.p, w.COMPOSITE, 0, 0)
        last = w.coordinates(self.p, w.COMPOSITE, 18599, 21999)
        self.assertEqual((first['x'],first['y']), ('50','50'))
        self.assertEqual((last['x'],last['y']), ('2199950','1859950'))
        km = w.coordinates(self.p, w.COMPOSITE, 0, 0, unit='km')
        self.assertEqual((km['x'],km['y']), ('1/20','1/20'))

    def test_native_c1c_axes_and_history_node_not_cell(self):
        c = w.coordinates(self.p, w.C1C, 0, 0, unit='km')
        a = w.coordinates(self.p, w.HISTORY_A, 0, 0, unit='km')
        self.assertEqual((c['x'],c['y']), ('1/2','3299/2'))
        self.assertEqual((a['x'],a['y']), ('0','0'))
        self.assertEqual(a['sampling'], 'NODE')
        last = w.coordinates(self.p, w.C1C, 1649, 1949, unit='km')
        self.assertEqual((last['x'],last['y']), ('3899/2','1/2'))

    def test_index_edges_boolean_and_unknown_frames_rejected(self):
        for row,col in ((-1,0),(18600,0),(0,22000),(False,0),(0,.5)):
            with self.assertRaises(ValueError):
                w.coordinates(self.p, w.COMPOSITE, row, col)
        for frame in ('C1R7','D3.1_ONLY','10M_REFINEMENT'):
            with self.assertRaises(ValueError):
                w.coordinates(self.p, frame, 0, 0)

    def test_stillklinge_exact_half_open_composition(self):
        c = w.declared_frames(self.p)['composition']
        self.assertEqual(c['rows_half_open'], [2200,6100])
        self.assertEqual(c['columns_half_open'], [9100,10650])
        self.assertFalse(c['resampling'])

    def test_c1r_requires_actual_bound_field_sampling(self):
        self.assertEqual(w.coordinates(self.p, w.C1R_AUTHORITY, 120, 80)['status'], 'UNKNOWN')
        sampling = {'field_id':'isolated-test-field','sampling':'CELL_CENTRE','shape':[665,710],
            'source_path': 'ISOLATED_TEST/field_metadata', 'source_sha256':'a'*64,
            'evidence':'ISOLATED TEST exact per-field metadata, not actual atlas payload.'}
        p = deepcopy(self.p)
        p['source_bindings'][sampling['source_path']] = sampling['source_sha256']
        with self.assertRaisesRegex(ValueError, 'exact verified package'):
            w.coordinates(p, w.C1R_AUTHORITY, 120, 80, field_sampling=sampling)
        p['field_sampling_records'] = [deepcopy(sampling)]
        r = w.coordinates(p, w.C1R_AUTHORITY, 120, 80, field_sampling=sampling, unit='km')
        self.assertEqual((r['x'],r['y']), ('2','2'))
        self.assertFalse(r['accepted_world_join'])
        sampling['sampling'] = 'NODE'
        with self.assertRaises(ValueError):
            w.coordinates(p, w.C1R_AUTHORITY, 120, 80, field_sampling=sampling)

    def test_c1r_public_crop_is_not_c1c_or_same_sampling(self):
        s = w.declared_frames(self.p)['c1r_scenario']
        self.assertEqual(s['public_crop_in_authority'], {'row':120,'column':80,'height':465,'width':550})
        self.assertEqual(s['public_extent_km'], ['0','2200','0','1860'])
        self.assertFalse(s['scale_only_control'])

    def test_owner_reflection_point_not_sampling_equivalence(self):
        r = w.transform_point(self.p, w.HISTORY_A, w.C1C, '1/2','1/2')
        self.assertEqual((r['x_km'],r['y_km']), ('1/2','3299/2'))
        self.assertFalse(r['sampling_equivalent'])
        self.assertFalse(r['accepted_world_join'])
        back = w.transform_point(self.p, w.C1C, w.HISTORY_A, r['x_km'],r['y_km'])
        self.assertEqual((back['x_km'],back['y_km']), ('1/2','1/2'))

    def test_cross_frame_origin_similarity_never_implicit_transform(self):
        for source,target in ((w.C1C,w.COMPOSITE),(w.C1R_AUTHORITY,w.COMPOSITE),(w.COMPOSITE,w.C1C)):
            r = w.transform_point(self.p, source,target,'1','1')
            self.assertEqual(r['status'], 'UNKNOWN')
            self.assertIsNone(r['x_km'])

    def test_declared_transform_requires_exact_verified_record(self):
        p = deepcopy(self.p)
        path = next(path for path,sha in p['source_bindings'].items() if sha == w.PHYSICAL_SHA)
        t = {'source_frame':w.C1C,'target_frame':w.COMPOSITE,'matrix_km':[['1','0','0'],['0','-1','1650']],
            'source_path':path,'source_sha256':w.PHYSICAL_SHA,'evidence':'ISOLATED TEST future declared transform, not actual owner selection.',
            'status':'WORKING NON-CANON'}
        with self.assertRaisesRegex(ValueError, 'exact verified package'):
            w.transform_point(p,w.C1C,w.COMPOSITE,'1','1',transform=t)
        p['coordinate_transforms'] = [deepcopy(t)]
        r = w.transform_point(p,w.C1C,w.COMPOSITE,'1','1',transform=t)
        self.assertEqual((r['x_km'],r['y_km']), ('1','1649'))
        self.assertFalse(r['accepted_world_join'])
        t['matrix_km'][0][0] = '0'
        p['coordinate_transforms'] = [deepcopy(t)]
        with self.assertRaisesRegex(ValueError,'degenerate'):
            w.transform_point(p,w.C1C,w.COMPOSITE,'1','1',transform=t)

    def test_no_transform_extrapolation(self):
        for x,y in ((-1,0),(1951,0),(0,1651),(float('nan'),1),(True,1)):
            with self.assertRaises(ValueError):
                w.transform_point(self.p,w.C1C,w.HISTORY_A,x,y)

    def test_zero_height_requires_known_coverage_and_z_is_not_km(self):
        self.assertEqual(self.terrain(1930)['z_m'], '1930')
        self.assertEqual(self.terrain(0)['z_m'], '0')
        for coverage in ('MISSING_SHARD','OUTSIDE_SUPPORT','UNKNOWN'):
            r = self.terrain(0,coverage)
            self.assertIsNone(r['z_m'])
            self.assertEqual(r['raw_storage_value'],'0')
            self.assertEqual(r['status'],'UNKNOWN')
        self.assertIsNone(self.terrain(None)['z_m'])

    def test_changed_authority_generation_requires_rebind(self):
        for kwargs in ({'generation':1},{'generation':False},{'merkle_root':'0'*64},{'authority_id':'other'}):
            with self.assertRaises(ValueError):
                self.terrain(0,**kwargs)

    def test_same_parent_relative_height_only(self):
        self.assertEqual(w.relative_height(self.terrain(1960),self.terrain(1930))['difference_m'],'30')
        self.assertIsNone(w.relative_height(self.terrain(0,'MISSING_SHARD'),self.terrain(1930))['difference_m'])
        a,z = self.terrain(1960),self.terrain(1930)
        z['reference_token']='WATER_FAMILY_WITH_UNKNOWN_OFFSET'
        with self.assertRaises(ValueError): w.relative_height(a,z)
        a,z = self.terrain(1960),self.terrain(1930)
        a['authority_id']=z['authority_id']='unbound'
        with self.assertRaises(ValueError): w.relative_height(a,z)

    def test_every_new_world_purpose_rejects_every_legacy_hash(self):
        for sha in w.LEGACY_HASHES:
            n = self.node('renamed-physical',sha=sha,role='OWNER_NEUTRAL_PHYSICAL')
            p = self.lineage_package([n])
            for purpose in w.NEW_WORLD_USES:
                with self.assertRaises(w.SourceUseError) as got:
                    w.validate_source_use(p,[n],[n['node_id']],purpose=purpose)
                self.assertEqual(got.exception.status,'REJECTED_CONTROL_DO_NOT_SEED')

    def test_inherited_stage3_4_5b_and_laundered_derived_hash_rejected(self):
        nodes = self.legacy()
        p = self.lineage_package(nodes)
        for target in ('stage3','stage4','stage5b','renamed-opportunity'):
            with self.assertRaises(w.SourceUseError) as got:
                w.validate_source_use(p,nodes,[target],purpose='NEW_WORLD_SEED')
            self.assertIn('v11',got.exception.lineage)
            self.assertEqual(got.exception.status,'REJECTED_CONTROL_DO_NOT_SEED')

    def test_all_explicit_political_roles_rejected_even_unknown_payload_hash(self):
        for role in w.LEGACY_ROLES:
            n = self.node('legacy',sha='b'*64,role=role)
            p = self.lineage_package([n])
            with self.assertRaises(w.SourceUseError) as got:
                w.validate_source_use(p,[n],['legacy'],purpose='NEW_WORLD_PARENT')
            self.assertEqual(got.exception.status,'REJECTED_CONTROL_DO_NOT_SEED')

    def test_legacy_regression_allowed_only_explicit_label(self):
        nodes = self.legacy()
        p = self.lineage_package(nodes)
        for purpose in w.LEGACY_USES:
            r = w.validate_source_use(p,nodes,['renamed-opportunity'],purpose=purpose,
                legacy_label='Exact Stage6C2026-08-30/V11 legacy source-qualified regression only')
            self.assertEqual(r['status'],'ALLOWED_LABELLED_LEGACY_USE')
            self.assertFalse(r['political_generation_accepted'])
            with self.assertRaises(ValueError):
                w.validate_source_use(p,nodes,['renamed-opportunity'],purpose=purpose)

    def test_neutral_opportunity_survives_only_independent_dependency_graph(self):
        neutral = self.node('retained-physical')
        opportunity = self.node('opportunity',sha='c'*64,role='OWNER_NEUTRAL_DERIVED',parents=['retained-physical'])
        nodes = self.legacy()+[neutral,opportunity]
        p = self.lineage_package(nodes)
        r = w.validate_source_use(p,nodes,['opportunity'],purpose='DISTRICT_FORMATION')
        self.assertEqual(r['lineage_node_ids'],['opportunity','retained-physical'])
        self.assertEqual(r['rejected_control_ancestry'],[])
        opportunity['parents'].append('stage4')
        with self.assertRaises(w.SourceUseError):
            w.validate_source_use(p,nodes,['opportunity'],purpose='DISTRICT_FORMATION')

    def test_species_ownership_and_target_counts_cannot_force_districts(self):
        for role in ('SPECIES_IDENTITY','RESOURCE_OWNERSHIP','POLITICAL_TARGET_COUNT_AREA'):
            n = self.node('constraint',role=role)
            p = self.lineage_package([n])
            with self.assertRaises(w.SourceUseError) as got:
                w.validate_source_use(p,[n],['constraint'],purpose='DISTRICT_FORMATION')
            self.assertEqual(got.exception.status,'REJECTED_CONTROL_DO_NOT_SEED')

    def test_unknown_leaf_cannot_self_declare_neutral(self):
        n = self.node('unknown-new-data',sha='d'*64)
        p = self.lineage_package([n])
        with self.assertRaises(w.SourceUseError) as got:
            w.validate_source_use(p,[n],[n['node_id']],purpose='DISTRICT_FORMATION')
        self.assertEqual(got.exception.status,'UNKNOWN')

    def test_unbound_leaf_missing_parent_and_incomplete_lineage_rejected(self):
        nodes = self.legacy()
        for change in ('binding','parent','complete','fake-derived'):
            p = self.lineage_package(nodes)
            bad = deepcopy(nodes)
            if change=='binding': p['source_bindings'].pop(bad[0]['source_path'])
            elif change=='parent': bad[-1]['parents']=['missing']
            elif change=='complete': bad[0]['lineage_complete']=False
            else: bad[-1]['parents']=[]
            with self.assertRaises(ValueError):
                w.validate_source_use(p,bad,['renamed-opportunity'],purpose='NEW_WORLD_PARENT')

    def test_cycles_duplicate_ids_and_relabelled_purpose_rejected(self):
        nodes=self.legacy()
        p=self.lineage_package(nodes)
        for change in ('cycle','duplicate','purpose','legacy-label'):
            bad=deepcopy(nodes)
            kwargs={'purpose':'NEW_WORLD_SEED'}
            if change=='cycle': bad[1]['parents']=['renamed-opportunity']
            elif change=='duplicate': bad.append(deepcopy(bad[0]))
            elif change=='purpose': kwargs['purpose']='JUST_A_TEST_SEED'
            else:
                bad=[self.node('neutral')];p=self.lineage_package(bad)
                kwargs['legacy_label']='claim regression but actually new seed'
            with self.assertRaises(ValueError):
                w.validate_source_use(p,bad,[bad[-1]['node_id']],**kwargs)

    def test_owner_interpretation_cannot_change_or_rebind_old_columns(self):
        for change in ('policy','rebind','branch','world','decision'):
            p=deepcopy(self.p)
            if change=='policy': p['effective_interpretation']['political']['new_world_legacy_source_policy']='ALLOW_SEED'
            elif change=='rebind': p['effective_interpretation']['physical']['original_reference_columns_automatically_rebound']=True
            elif change=='branch': p['effective_interpretation']['physical']['selected_branch']='D3.1_ONLY'
            elif change=='world': p['owner_deltas']['accepted_compatible_world_snapshot']='NEW_ACCEPTED_WORLD'
            else:
                key=next(k for k,h in p['source_bindings'].items() if h==w.PHYSICAL_SHA)
                p['source_bindings'][key]='0'*64
            with self.assertRaises(ValueError): w.declared_frames(p)

    def test_all_outputs_strict_json_and_input_unchanged(self):
        p=deepcopy(self.p)
        first=w.declared_frames(p)
        self.assertEqual(first,w.declared_frames(p))
        self.assertEqual(p,self.p)
        json.dumps(first,allow_nan=False)
        nodes=self.legacy()
        p=self.lineage_package(nodes)
        before=deepcopy(nodes)
        a=w.validate_source_use(p,nodes,['v11'],purpose='LEGACY_JOIN',legacy_label='source-qualified legacy')
        z=w.validate_source_use(p,nodes,['v11'],purpose='LEGACY_JOIN',legacy_label='source-qualified legacy')
        self.assertEqual(a,z)
        self.assertEqual(before,nodes)
        json.dumps(a,allow_nan=False)


if __name__=='__main__':
    unittest.main()
