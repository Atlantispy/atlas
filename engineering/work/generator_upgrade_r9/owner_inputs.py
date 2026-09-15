"""Exact R9 owner roster; statuses/references, never invented ecological values.

Standalone stdlib source provider for captured-byte provenance loading. Historical
scenario references are preserved but no numerical scenario is selected or run.
"""
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PureWindowsPath
import re
import stat

W = Path('C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace')
C = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02')
E = C/'the-diadem-local-tasks-10'
L = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted')
H = L/'work/species_habitat'
G = W/'06_Generator_System'
ECOLOGY = W/'02_Working_Files/Geography/Ecology/R9_Input_Contract'
POPULATION = W/'02_Working_Files/Geography/R9_Abundance_Inputs_2026-09-11'
DOSSIERS = W/'01_Current_Drive_Snapshot/Bannerhausen/10 Bannerhaus Dossiers by Primary Peak'
REGISTERS = Path('C:/Users/LOCAL_USER/.codex/.chatgpt-projects/g-p-LOCAL_PROJECT/work/v89x/LATEST_TREE_TOL_INTEGRATED_1_2/Registers')
MAX_BYTES = 8*1024*1024
ECOLOGY_PINS = {
    'INPUT_CONTRACT.md': 'abba2e6b724fc1245f4523d4feb32db08d316e351835f3ede4c14ef40912e7a0',
    'ROSTER_BIOLOGY_SOURCES.md': '04dc274cea52edd97b091b582a161f198aeb54da8c8b9c26cc8b2ccc2d12de99',
    'RETAINED_PRODUCER_COVERAGE.md': 'e290fc6e4889b593253ee587602ea42a987bca6ddd269cdf625a9ca10841a504'}
VALIDATION_SHA256 = 'af05aa985384c157f890b5854dac8fb4474b102a73e8a9a12122575b8ccbb655'
NODE_NAME = 'TOL_INTEGRATED_1_2_Node_Register.csv'
EDGE_NAME = 'TOL_INTEGRATED_1_2_Edge_Register.csv'
NODE_SHA256 = '3044815a97c2625eb057eeba044494c2e10be45f9cbbdc7ade90b01e87d181d4'
EDGE_SHA256 = '732328fb39185e9d7e02d8dcf0e420022e8fa8429d7cb8739d1e3d9659e9ccdf'
PRIMARY_HS4 = W/'01_Current_Drive_Snapshot/Primary Hausen/Venus Rafflesia/Sweet-Rot Maw ~1 Süßfäulschlund.docx'
PRIMARY_HS4_SHA256 = 'a763d0d04bdd8d4edf55a1b59dca94109a510fceab4c48dad6a669ec08e3e94f'

# Explicit directly named owner dependencies. These are identity checks, not a
# second biological approval, a transitive corpus traversal or code execution.
DIRECT = (
 (REGISTERS/NODE_NAME, NODE_SHA256, 'extracted TOL identity register; EST is not whole-dossier approval'),
 (REGISTERS/EDGE_NAME, EDGE_SHA256, 'extracted active TOL relationship register; provisional descent retained'),
 (PRIMARY_HS4, PRIMARY_HS4_SHA256, 'HS4 primary paragraph evidence; PRIMARY_DOMAIN_SOURCE_STATUS_UNVERIFIED retained'),
 (C/'the-diadem-local-tasks-8/outputs/GEO_ENGINEERING_SCIENTIFIC_UPGRADE_DECISIONS_2026-09-10_R1_ECOLOGY.md', 'e43b6edabced8f9c652da23e8f1dfa49fa2d7ff30488eaf79eac49edce08965b', 'Ecology ECO-02-04 owner-bound working contract, not canon or installation'),
 (C/'the-diadem-local-tasks/outputs/Scientific_Upgrade_Ecology_Integration_2026-09-10_B2.md', '7989cd757944503143dc1256dbcd1f1022a3207a8392ecb9511585f847545b97', 'GEO B2 common-snapshot/candidate qualification'),
 (C/'diadem-species-coordinator/outputs/HS11_Larval_Host_Guild_Decision_2026-09-10_R1.md', 'd836e68c227dbf8d75be32cbfc9f42760377db301e00a738cc3037d2f81cb676', 'HS11 functional recruitment hypothesis permission; numeric host inputs unknown; primary source status unverified'),
 (C/'the-diadem-local-tasks/outputs/Scientific_Upgrade_HS11_Integration_2026-09-10_B3.md', '2b475af90a7b1e7aa29ae9a634897418528c182f008c9e0596a30fecda5a8954', 'GEO B3 bounded HS11 decision integration'),
 (W/'01_Current_Drive_Snapshot/Geography/00 Canon-Controlled Geography Docs & Reading Guide/Diadem Geography — Master Living Canon.docx', '5f269d7ba3be0aee680edec180376ea471403f606f9fb7b9e5f77f69be4f6e38', 'owner-named master constraint reference; changed R9 parents qualified separately'),
 (H/'h0_requirements/die_aufgehobenen_habitat_range_requirements.review-only.json', 'c784da4e1d70ad4c181462a60bd6afadf9b873ec53f5375fcbd6490964be6420', 'HS14 review-only exceptional event/person requirements'),
 (H/'h0_requirements/schwarzflut_habitat_range_requirements.review-only.json', '2be7a01bf06af09133115d8a21828b03a49a6a77f8ad31dbe0e6e7f325585791', 'HS19 review-only single organism / absent wild population separation'),
 (E/'work/scientific_foundation_r1/connectivity.py', '5b6e6090f824d9c62b89556dfe9144f5705832e808038854256c0f73bfaf27dd', 'curated retained branch: real bounded barrier graph; not executed by owner provider'),
 (G/'engine/stage6d_species_census.py', 'f26a72543989ad2927e48ac2616d70a40d425c8cbfbb62c1ad9e19be08a68636', 'curated retained branch: nonspatial prescribed census sidecar, not density inference'),
 (G/'engine/build_stage6d_species_census.py', 'a4e6de33888b615eced58335c4f25124a8167d07a576034fcb7dd61780e35926', 'curated retained census launcher; not executed'),
 (G/'engine/stage6d_species_rules.py', 'ab7eac41306ebe498d00be214631135e6e6d5d6a86e6fbf1d3454c5e99aa4755', 'curated retained counting/residence/deduplication controls; not density authority'),
 (G/'generated_outputs/S6D_PRIMARY_SPECIES_DENSITY_AUDIT_WORKING_V1_2026-08-31/README_FIRST.md', '0debafd804ec62d3532440fbb2d43977cce7745b0cf87ce8b1e259aa90c523bc', 'curated density audit interpretation; not population validation'),
 (G/'generated_outputs/S6D_PRIMARY_SPECIES_DENSITY_AUDIT_WORKING_V1_2026-08-31/Diadem_Primary_Species_Density_Sensitivity_Summary_WORKING.json', '39b9b06ab88f2d5de091e6bacc87d211826ccc733ab022c0f800f029542f2ef5', 'curated audit-only implied political-area density; no calibrated occupied density'),
 (G/'generated_outputs/S6D_PRIMARY_SPECIES_ECOLOGY_RECONCILED_WORKING_V2_2026-08-31/BIAS_REVIEW_NOTICE.md', 'ca4a6ef27665506be977da41fedfc18bd8620ca994eec3d8852df071e7cd4c65', 'V2 retained AUDIT ONLY; forbidden as current population prior'),
 (G/'engine/stage6d_rootreach_footprint.py', 'c3094704f5707f358210025598101ee57f2c8212c522fab6982b58ef893fcd1f', 'curated human enclave footprint; not plant abundance/occupied fraction'))

PLANT_IDS = (
 'aurblatt', 'cloud_kelp', 'codex_blooms', 'dandeblooms',
 'mistchimes_nebelglockchen', 'mistleholly_berries', 'periwinkle_vine',
 'red_wheat_grass', 'roseblooms_rosenkronen', 'seedshot_lamp_reeds',
 'skyreach_vine', 'sleep_s_voice_schlafstimme', 'slope_pines',
 'thornwillows', 'twilight_blossoms', 'wandering_mangroves')

# Compact readbacks of the pinned owner's qualitative paragraph, not parameters.
PLANT_NOTES = {
 'aurblatt':'Ventilated metal-bearing terraces, mostly managed groves, seasonal leaf fall.',
 'cloud_kelp':'Rooted vascular spore plant; storm-spore dispersal and sheltered moist gametophyte; no free adult drift. Later DEC-038/039 addendum retained.',
 'codex_blooms':'Drained moist loam, managed groves.',
 'dandeblooms':'Sexually functional clonal plantlets root after landing; seasonal mature-clock release; no instant recursive clocks. Later DEC-078 addendum retained.',
 'mistchimes_nebelglockchen':'Mist dependence and fog-cycle bloom.',
 'mistleholly_berries':'Graft retains separate host/crown genomes; year-round cultivated fruit supersedes winter-only reading. Later DEC-081 addendum retained.',
 'periwinkle_vine':'Node-rooting spread and local ant/seed dispersal; larger gaps difficult; evergreen, no obligatory winter dormancy, spring flowers; wild moist shade beyond jurisdiction, no mandatory graves/seedwind; bond identity survives ramet separation.',
 'red_wheat_grass':'Perennial grassland/wind seeds; soil/water/seasonality TBD.',
 'roseblooms_rosenkronen':'Rooted adults, burst seeds, temperate drained crevices; clumped wild versus civic planting.',
 'seedshot_lamp_reeds':'NON-CANON seed firing into stone/metal; natural requirements and seasonality UNKNOWN.',
 'skyreach_vine':'DRAFT/core relationship CANON; proposed mature host-access necessity conflicts with using primary HS4 maintenance as a universal host gate; reconciliation UNKNOWN.',
 'sleep_s_voice_schlafstimme':'Cultivated context; natural habitat/reproduction OPEN/TBD.',
 'slope_pines':'Cold thin-soil slopes, snowmelt and root fusion.',
 'thornwillows':'Bog/fen hummocks, photosynthetic maintenance and supplementary blood.',
 'twilight_blossoms':'Cultivated context; natural habitat/reproduction OPEN/TBD.',
 'wandering_mangroves':'Brackish wetland/surge; rare costly anchored stepping; deep crown drowning, extreme salt and hard freeze constrain; movement budget UNKNOWN, routine seasonal migration unestablished.'}


def _checked(path, expected):
    path = Path(path)
    if not path.is_absolute() or type(expected) is not str or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('absolute source and exact SHA256 required')
    for part in (path, *path.parents):
        st = part.lstat()
        if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0)&0x400:
            raise ValueError('linked/reparse owner source prohibited')
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_BYTES:
        raise ValueError('bounded singly-linked source required')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('owner source pin mismatch: '+str(path))
    return raw


def _json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result: raise ValueError('duplicate JSON key')
            result[k] = v
        return result
    def bad(_): raise ValueError('nonfinite JSON')
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    def visit(v):
        if isinstance(v, float) and not math.isfinite(v): bad(v)
        if isinstance(v, dict):
            for x in v.values(): visit(x)
        elif isinstance(v, list):
            for x in v: visit(x)
    visit(result)
    return result


def _plant_table(text):
    rows = re.findall(r'^\| `([^`]+)`; `([^`]+)` \| `([0-9a-f]{64})` \| (.*?) \|$', text, re.M)
    if len(rows) != 16 or tuple(r[0] for r in rows) != PLANT_IDS:
        raise ValueError('exact owner sixteen-plant table required')
    result = {}
    for suffix, relative, sha, raw_status in rows:
        p = PureWindowsPath(relative)
        if p.is_absolute() or p.drive or p.root or '..' in p.parts or not p.parts:
            raise ValueError('unsafe owner dossier member')
        result['bannerhaus_'+suffix] = {'path': str(DOSSIERS.joinpath(*p.parts)),
            'sha256': sha, 'raw_status': raw_status, 'section': raw_status.split('; ', 1)[-1]}
    return result


def _context():
    ecology = {name: _checked(ECOLOGY/name, sha).decode('utf-8-sig') for name, sha in ECOLOGY_PINS.items()}
    plants = _plant_table(ecology['ROSTER_BIOLOGY_SOURCES.md'])
    validation = _json(_checked(POPULATION/'VALIDATION.json', VALIDATION_SHA256))
    if validation.get('schema') != 'diadem.r9.population-abundance-validation.v1' or validation.get('status') != 'PASS':
        raise ValueError('exact Population owner validation contract required')
    required = {'DECISION.md', 'ROSTER.json', 'SOURCES.json', 'PARAMETER_SCENARIOS.json',
                'habitat_bindings_01_10.json', 'habitat_bindings_11_20.json'}
    records = validation['files']
    if len(records) != 6 or {r['name'] for r in records} != required:
        raise ValueError('complete bounded Population file closure required')
    files = {}
    for r in records:
        raw = _checked(POPULATION/r['name'], r['sha256'])
        if len(raw) != r['bytes']: raise ValueError('Population source byte count mismatch')
        files[r['name']] = _json(raw) if r['name'].endswith('.json') else raw.decode('utf-8-sig')
    roster = files['ROSTER.json']
    if roster.get('schema') != 'diadem.r9.population-abundance-inputs.v1' or len(roster['rows']) != 20 or {r['hs'] for r in roster['rows']} != set(range(1,21)):
        raise ValueError('exact twenty-row Population roster required')
    if files['SOURCES.json'].get('schema') != 'diadem.r9.population-source-bindings.v1':
        raise ValueError('Population source schema mismatch')
    return ecology, plants, validation, files


def source_bindings():
    """Exact owner-file, roster-dossier and bounded direct-source identity ledger.

    This does not revalidate the owner's scientific findings, old raster bytes,
    package approvals, or the unread whole historical biology corpus.
    """
    _, plants, validation, files = _context()
    result = {}
    def add(path, sha, role):
        path = str(Path(path))
        if path in result:
            if result[path]['sha256'] != sha: raise ValueError('conflicting owner source hashes')
            return
        _checked(path, sha)
        result[path] = {'path': path, 'sha256': sha, 'role': role}
    for name, sha in ECOLOGY_PINS.items(): add(ECOLOGY/name, sha, 'current Ecology owner contract '+name+'; exact raw source statuses retained')
    add(POPULATION/'VALIDATION.json', VALIDATION_SHA256, 'Population owner validation receipt; bounded readback, not a new census')
    for r in validation['files']: add(POPULATION/r['name'], r['sha256'], 'current Population owner '+r['name']+'; menu scenarios not automatically selected')
    for key, r in files['SOURCES.json']['sources'].items():
        add(r['path'], r['sha256'], 'Population declared source '+key+'; raw status: '+r['status']+'; sections: '+r['sections'])
    def collect(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                add(value['path'], value['sha256'], 'Population-bound retained habitat producer/control/semantics; not executed or reapproved')
            else:
                for child in value.values(): collect(child)
        elif isinstance(value, list):
            for child in value: collect(child)
    for name in ('habitat_bindings_01_10.json', 'habitat_bindings_11_20.json'): collect(files[name])
    for ident, row in plants.items(): add(row['path'], row['sha256'], ident+' dossier identity; raw source status/loci: '+row['raw_status'])
    for path, sha, role in DIRECT: add(path, sha, role)
    if len(result) > 256: raise ValueError('bounded owner ledger exceeded')
    return sorted(result.values(), key=lambda row: row['path'])


def _registers():
    nodes = list(csv.DictReader(io.StringIO(_checked(REGISTERS/NODE_NAME, NODE_SHA256).decode('utf-8-sig'))))
    edges = list(csv.DictReader(io.StringIO(_checked(REGISTERS/EDGE_NAME, EDGE_SHA256).decode('utf-8-sig'))))
    nm = {r['node_id']: r for r in nodes}
    if len(nm) != len(nodes): raise ValueError('duplicate TOL identity')
    return nm, edges


def biological_roster():
    """36 owner-required identity records; no new ecological parameter values.

    source_status is the *integration* status. Source binding raw_status,
    Population reference row statuses, and TOL node/edge states remain distinct.
    """
    source_bindings()
    ecology, plants, validation, files = _context()
    records = {r['name']: r for r in validation['files']}
    population = files['ROSTER.json']; source_refs = files['SOURCES.json']['sources']
    nm, edges = _registers()
    owner_status = re.search(r'^Status: (.+)$', ecology['INPUT_CONTRACT.md'], re.M)
    if owner_status is None: raise ValueError('exact owner status line required')
    contract = {'path': str(ECOLOGY/'INPUT_CONTRACT.md'), 'sha256': ECOLOGY_PINS['INPUT_CONTRACT.md'],
                'raw_status': owner_status.group(1),
                'section': 'Roster and retained coverage; Seasons, barriers and stock'}
    result = {}
    for row in sorted(population['rows'], key=lambda r: r['hs']):
        hs = row['hs']; ident = 'HS'+str(hs)
        special = {'population_roster_binding': {'path': str(POPULATION/'ROSTER.json'), 'sha256': records['ROSTER.json']['sha256'], 'section': 'rows[hs='+str(hs)+']'},
            'population_source_references': {k: copy.deepcopy(source_refs[k]) for k in row['source_refs']},
            'occupied_habitat_fraction': None, 'measured_occupied_density_bounds': None,
            'quantitative_spatial_rules_status': 'UNKNOWN; no parameter menu scenario selected'}
        if hs == 3: special['identity_note'] = 'Snake with three morphs; canopy support is not plant population.'
        if hs == 4:
            special.update(adult_movement='NOT_APPLICABLE_ROOTED_SESSILE_ADULT',
                count_unit='independent continuous self-sufficient Rootreach; attached crowns/unsevered daughters non-additive',
                universal_skyreach_host_gate='UNKNOWN pending Species reconciliation',
                primary_reference={'path': str(PRIMARY_HS4), 'sha256': PRIMARY_HS4_SHA256,
                    'raw_status': 'PRIMARY_DOMAIN_SOURCE_STATUS_UNVERIFIED', 'section': 'P39-48,P53-57'},
                reproduction='Primary P54-57 supersedes blanket TBD: safe-open pollination, self-incompatible hermaphroditism, possible rhizome daughters; numeric rates UNKNOWN')
        if hs == 9: special['mobile_cohort'] = 'UNKNOWN; annual-mean all-stage stock cannot be placed on adult movement corridors.'
        if hs == 10: special['seasonal_role'] = 'Local cave-to-river-valley redistribution allowed; fine timing/intensity/maternity fields UNKNOWN; separate flight and cave-water graphs.'
        if hs == 11:
            special['recruitment_contract'] = 'Functional host-guild WORKING NON-CANON hypothesis permitted; gates local recruitment, not every adult-use cell; adult persistence needs accessible recruitment or declared immigration plus resources/refuge; taxa/supply/rates/timescales UNKNOWN.'
        if hs == 13: special['spatial_presence'] = 'UNKNOWN; approximate500 affiliation/service stock includes foreign-hospital service and cannot all be assumed present.'
        if hs == 14: special.update(product_applicability='NONSPATIAL_EVENT', occurrence='UNKNOWN; dated event/identity register required', habitat_generated_density='NOT_APPLICABLE')
        if hs == 15: special['mobile_cohort'] = 'UNKNOWN;120000 all-stage reference includes89000 mature plus31000 pre-adult; not an adult total.'
        if hs == 17: special.update(whole_diadem_total=None, total_scope='7600 core reference only', seasonal_role='Mostly local elevational movers plus valley residents; weights/timing/budgets UNKNOWN.')
        if hs == 19: special.update(product_applicability='ABSENT_WILD', wild_population_count=0,
            multiple_organism_density='NOT_APPLICABLE', wild_migration='NOT_APPLICABLE', footprint_and_mass='UNKNOWN; one organism, incorporated human identities separate')
        if hs == 20: special['regular_migration'] = 'UNESTABLISHED; explicit local flight/use hypotheses remain possible.'
        result[ident] = {'organism_id': ident, 'name': row['species'],
            'kind': 'PLANT' if hs == 4 else 'OTHER' if hs in (14,19) else 'ANIMAL',
            'retained_hs': hs, 'source_status': 'WORKING NON-CANON', 'source_binding': copy.deepcopy(contract),
            'evidence': 'Owner-bound R9 Ecology INPUT_CONTRACT.md; Population ROSTER.json exact HS'+str(hs)+' row, statuses and scope retained.',
            'population_reference': copy.deepcopy(row), 'special_details': special}
    for ident, dossier in plants.items():
        node = nm.get(ident)
        if node is None or (node['node_class'],node['entity_domain'],node['genealogical_eligibility'],node['project_role'],node['canon_state'],node['active_in_phase_11_2']) != ('SPC','ORG','YES','BHS','EST','YES'):
            raise ValueError('owner plant identity register mismatch')
        cursor = ident; ancestry = []
        while cursor != 'clade_plantae':
            if cursor in ancestry or cursor not in nm: raise ValueError('plant ancestry unresolved/cyclic')
            ancestry.append(cursor); cursor = nm[cursor]['parent_node_id']
        terminal = [r for r in edges if r['target_node_id']==ident and r['active_in_phase_11_2']=='YES']
        if len(terminal)!=1 or terminal[0]['source_node_id']!=node['parent_node_id'] or terminal[0]['edge_type']!='PD' or terminal[0]['edge_confidence']!='STW':
            raise ValueError('owner provisional plant lineage mismatch')
        result[ident] = {'organism_id':ident, 'name':node['display_name'], 'kind':'PLANT',
            'retained_hs':None, 'source_status':'WORKING NON-CANON', 'source_binding':copy.deepcopy(dossier),
            'evidence':'Owner-selected additional plant identity; Ecology ROSTER_BIOLOGY_SOURCES.md exact dossier row/loci. Register EST does not approve the whole dossier.',
            'population_reference':None, 'special_details':{
                'owner_contract_binding':copy.deepcopy(contract),
                'node_reference':{'path':str(REGISTERS/NODE_NAME),'sha256':NODE_SHA256,
                    'fields':{k:node[k] for k in ('node_id','display_name','node_class','entity_domain','canon_state','evidence_basis','parent_node_id','active_in_phase_11_2')}},
                'terminal_edge_reference':{'path':str(REGISTERS/EDGE_NAME),'sha256':EDGE_SHA256,
                    'fields':{k:terminal[0][k] for k in ('edge_id','source_node_id','target_node_id','edge_type','edge_type_label','edge_confidence','edge_confidence_label','evidence_basis','active_in_phase_11_2')}},
                'qualitative_contract_binding':{'path':str(ECOLOGY/'ROSTER_BIOLOGY_SOURCES.md'),'sha256':ECOLOGY_PINS['ROSTER_BIOLOGY_SOURCES.md'],'section':'Qualitative constraints; numeric fields UNKNOWN'},
                'qualitative_constraint_readback':PLANT_NOTES[ident.removeprefix('bannerhaus_')],
                'occupied_habitat_fraction':None,'density':None,'movement_budget':None,
                'quantitative_spatial_rules_status':'UNKNOWN; no biological defaults',
                'count_unit':'UNKNOWN; require species-specific ramet/genet/colony distinction'}}
    if len(result)!=36 or sum(r['kind']=='PLANT' for r in result.values())!=17:
        raise ValueError('exact36 identity/17plant owner roster required')
    return result
