"""3C-R1 reference protocol: measurable checks, held-out regions, no realism score.

The numerical implementation and evidence integrity may pass while scientific
model acceptance remains open. No function in this module changes a generator,
selects a seed, raises a tolerance or changes a classification to obtain a pass.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np

from .plate_reference_dataset import (
    ReferenceDataError, PB2002Dataset, PB2002_COUNTS, PB2002_FILES,
    EARTH_REFERENCE_RADIUS_M, SOURCE_POSITION_BOUND_M, BOUNDARY_CLASSES,
    load_pb2002, lonlat_vectors, spherical_ring_measures,
    multiscale_ring_measures, step_motion, _json, _angles,
)
from .plate_reference import AREA_ROWS
from .geometry import _check_cancel
from .resources import select_budget


# Fixed BEFORE testing/tuning a replacement generation method. All PB2002 areas
# have already calibrated Atlas, so no individual area is falsely called held out.
WITHHELD_MORPHOLOGY_PLATES = ('KE','MA','MN','NB','NI','PS','SB','SS','TO','WL')
EXPOSED_OUTLINE_PLATES = ('CO',)
EXPOSED_STEP_NUMBERS = tuple(range(1,13))
OBSERVATION_SCALES_M = (100_000.,250_000.,500_000.)
_SOURCE_FAMILY = 'PB2002-Bird-2003'


def reference_protocol() -> dict:
    """Detached preregistration, not a claim that held-out observations are secret.

    Reading data to verify units/source integrity is separate from using it to
    tune the candidate. Within-model holdout remains correlated and must be
    supplemented by independent model/history challenges before R9 sign-off.
    """
    record = dict(
        schema='atlas.plate-reference-protocol.r1.v1',registered_date='2026-09-18',
        evidence_family=_SOURCE_FAMILY,
        source_epoch='PB2002 present-day representation published in 2003; not 2026 observations',
        source_coordinates='published longitude east/latitude north degrees on a sphere',
        radius_m=EARTH_REFERENCE_RADIUS_M,
        scales_m=list(OBSERVATION_SCALES_M),sampling_phases=[0.,.5],
        splits=dict(
            all_52_areas='previously exposed calibration; never validation',
            outline_development='all except reserved plates; Cocos explicitly previously exposed',
            outline_withheld=list(WITHHELD_MORPHOLOGY_PLATES),
            motion_withheld='entire boundary segments touching any reserved plate, not random steps',
            motion_previously_exposed=list(EXPOSED_STEP_NUMBERS),
            orogen_shapes='all reserved from generation tuning; used for source/numerical verification',
            independence='within-PB2002 spatial/observable holdout, NOT a second independent dataset'),
        numerical_checks=dict(
            area='Gauss-Bonnet versus independent solid-angle fan: max(2e-12,64*N*eps) sr',
            source_area='Table 1 half-unit 5e-6 sr + 2*perimeter*epsilon + N*pi*epsilon^2; epsilon=60m/R',
            source_position='DIG six significant digits: <=60m numerical rounding, not geological accuracy',
            motion='per-step component bound from 0.001-degree endpoints, 0.001-degree poles, 0.0001 deg/Ma rates and 0.1 mm/a outputs',
            length='0.05km + two endpoint coordinate-rounding bounds',
            topology='exact canonical decimal-coordinate edge incidence; report discrepancies, never snap',
            resolution='uniform arc-length sampling at named physical scales, both phases; short outlines marked unresolved'),
        scientific_checks=dict(
            shape_population='joint area, compactness, reflex turning, boundary-moment measures and adjacency; no acceptance threshold invented',
            boundary_structure='class-specific lengths and transitions, small-plate margin associations; source classifications retained',
            kinematics='relative Euler motion and signs; this is not independent validation of a dynamic velocity field',
            deformation='orogens are overlays and not added to rigid-plate area',
            history='not supplied by this static model; cannot pass persistence/formation/reorganisation tests',
            independent_model='not supplied by a PB2002 reformat; required at R9',
            actual_geological_uncertainty='not globally quantified by source; do not turn rounding bounds into confidence intervals'),
        policy=dict(
            calibration_before_withheld=True,
            holdout_requires_run_id_and_explicit_selection=True,
            altering_split_requires_new_protocol=True,
            runtime_cannot_promote_geological_acceptance=True,
            source_and_numerical_verification_is_not_calibration=True,
            no_universal_realism_score=True,
            no_generator_changes=True),
        outstanding_reference_challenges=[
            dict(name='multi-epoch plate reconstruction',status='NOT_ACQUIRED',reason='required for history; present-day poles cannot invent past topology'),
            dict(name='external plate/deformation model with explicit ancestry',status='NOT_ACQUIRED',reason='cross-model challenge; shared observations must be disclosed')])
    record['protocol_id']=hashlib.sha256(_json(record)).hexdigest()
    return record


def record_role(*, observable, plate_id=None, boundary=None, step_number=None) -> str:
    """Explicit field-level split: an area can be calibration while its shape is held out."""
    known = {name for name,_ in AREA_ROWS}
    if plate_id is not None and plate_id not in known:raise ReferenceDataError('unknown reference plate')
    if observable == 'area':return 'CALIBRATION_PREVIOUSLY_EXPOSED'
    if observable == 'orogen':return 'WITHHELD_WITHIN_MODEL'
    if observable == 'outline':
        if plate_id is None:raise ReferenceDataError('outline split needs plate ID')
        if plate_id in WITHHELD_MORPHOLOGY_PLATES:return 'WITHHELD_WITHIN_MODEL'
        return 'DEVELOPMENT_PREVIOUSLY_EXPOSED' if plate_id in EXPOSED_OUTLINE_PLATES else 'DEVELOPMENT'
    if observable == 'motion':
        if not isinstance(boundary,str) or len(boundary)!=5 or not {boundary[:2],boundary[3:]}<=known:
            raise ReferenceDataError('motion split needs known boundary owners')
        if step_number in EXPOSED_STEP_NUMBERS:return 'DEVELOPMENT_PREVIOUSLY_EXPOSED'
        return 'WITHHELD_WITHIN_MODEL' if {boundary[:2],boundary[3:]} & set(WITHHELD_MORPHOLOGY_PLATES) else 'DEVELOPMENT'
    raise ReferenceDataError('unregistered observable')


def evaluation_record(dataset_id, candidate_id, *, split, run_id, purpose):
    """Identify an evaluation without leaking it into calibration automatically.

    This is an audit record, not access control against someone editing Python.
    'withheld' must be deliberate; no default silently evaluates it during tuning.
    """
    if split not in ('development','withheld','source-verification'):
        raise ReferenceDataError('explicit supported split required')
    if purpose not in ('calibration','validation','source-verification'):
        raise ReferenceDataError('explicit evidence purpose required')
    if (split=='withheld' and purpose!='validation') or (split=='source-verification')!=(purpose=='source-verification'):
        raise ReferenceDataError('evidence split and intended use disagree')
    for value in (dataset_id,candidate_id):
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ReferenceDataError('dataset and candidate SHA256 identities required')
    if not isinstance(run_id,str) or not run_id.strip() or len(run_id)>256:
        raise ReferenceDataError('named bounded evaluation run required')
    record=dict(schema='atlas.plate-reference-use.v1',dataset_id=dataset_id,candidate_id=candidate_id,
                protocol_id=reference_protocol()['protocol_id'],split=split,run_id=run_id,purpose=purpose,
                independent_evidence_families=1,geological_model_accepted=False)
    record['evaluation_id']=hashlib.sha256(_json(record)).hexdigest()
    return record


def _vertex_key(xy):
    """Exact source-decimal seam equivalence, NOT coordinate snapping."""
    lon,lat=(Decimal(str(float(v))) for v in xy)
    lon=((lon%360)+360)%360
    if lon>=180:lon-=360
    if abs(lat)==90:lon=Decimal(0)
    if lon==0:lon=Decimal(0)
    if lat==0:lat=Decimal(0)
    return str(lon.normalize()),str(lat.normalize())


def _edge_key(a,b):
    aa,bb=_vertex_key(a),_vertex_key(b)
    return (aa,bb) if aa<bb else (bb,aa)


def boundary_inventory(dataset: PB2002Dataset, *, cancel=None):
    """Reconcile the source's duplicated polygon edges against single boundaries.

    The source files are not rounded/snapped into Atlas topology. Unmatched edges
    stay in the report, because a published reconstruction can have discrepancies.
    """
    plates=defaultdict(list);boundaries=defaultdict(list);neighbours=defaultdict(set)
    endpoints=defaultdict(set)
    repeated_source_spans=0
    for curve in dataset.plates:
        _check_cancel(cancel)
        for a,b in zip(curve.coordinates[:-1],curve.coordinates[1:]):
            if np.array_equal(a,b):
                repeated_source_spans += 1
                continue  # Exact source repetition, not a physical boundary edge.
            plates[_edge_key(a,b)].append((curve.name,_vertex_key(a),_vertex_key(b)))
    for curve in dataset.boundaries:
        _check_cancel(cancel);left,right=curve.owners
        neighbours[left].add(right);neighbours[right].add(left)
        for endpoint in curve.coordinates[[0,-1]]:endpoints[_vertex_key(endpoint)].update((left,right))
        for a,b in zip(curve.coordinates[:-1],curve.coordinates[1:]):
            boundaries[_edge_key(a,b)].append((left,right,_vertex_key(a),_vertex_key(b)))
    keys=set(plates)|set(boundaries);issues=[]
    for key in sorted(keys):
        a,b=plates.get(key,[]),boundaries.get(key,[])
        valid=(len(a)==2 and len(b)==1 and a[0][0]!=a[1][0] and a[0][1:]==tuple(reversed(a[1][1:])))
        if valid:
            left,right,begin,end=b[0]
            valid={(owner,x,y) for owner,x,y in a}=={(left,begin,end),(right,end,begin)}
        if not valid:
            issues.append(dict(edge=[list(vertex) for vertex in key],polygon_uses=len(a),boundary_uses=len(b),
                polygon_owner_directions=[[owner,list(begin),list(end)] for owner,begin,end in a],
                boundary_owner_directions=[[left,right,list(begin),list(end)] for left,right,begin,end in b]))
    return dict(unique_boundary_edges=len(boundaries),unique_polygon_edges=len(plates),
                exact_repeated_polygon_spans_excluded=repeated_source_spans,
                incidence_discrepancies=issues,neighbours={k:sorted(v) for k,v in sorted(neighbours.items())},
                junction_owner_sets=[dict(location=list(key),owners=sorted(owners)) for key,owners in sorted(endpoints.items()) if len(owners)>=3],
                interpretation='static source connectivity; no inference of dynamic triple-junction stability')


def _source_step_alignment(dataset):
    """Align each printed step to its original high-resolution segment, in source order."""
    issues=[];i=0
    for curve in dataset.boundaries:
        for a,b in zip(curve.coordinates[:-1],curve.coordinates[1:]):
            step=dataset.steps[i];i+=1
            errors=[]
            for full,rounded in ((a,step.start),(b,step.end)):
                errors += [abs((float(full[0])-rounded[0]+180)%360-180),abs(float(full[1])-rounded[1])]
            if step.boundary!=curve.name or max(errors)>.0005+1e-10:
                issues.append(dict(number=step.number,boundary=step.boundary,source_curve=curve.name,max_endpoint_difference_deg=max(errors)))
    return issues


def reference_dataset_report(dataset, *, budget=None, cancel=None, include_scales=True):
    """Evaluate ALL records from a complete pinned dataset; never approve a generator.

    Data availability and scientific validity remain separate. No full-data pass
    is issued from synthetic fixtures or from Cocos plus twelve known steps.
    """
    if type(dataset) is not PB2002Dataset:
        raise ReferenceDataError('complete typed reference dataset required')
    counts=tuple(map(len,(dataset.plates,dataset.boundaries,dataset.orogens,dataset.poles,dataset.steps)))
    if counts!=PB2002_COUNTS or {p for p,_ in dataset.raw_sha256}!={p for p,_,_ in PB2002_FILES}:
        raise ReferenceDataError('a partial reference dataset cannot pass the complete-data gate')
    _check_cancel(cancel)
    with select_budget(budget).reserve(96*1024**2,category='plate-reference-report'):
        report=dict(schema='atlas.plate-reference-report.r1.v1',dataset=dataset.provenance(),
                    protocol=reference_protocol(),purpose='SOURCE_AND_NUMERICAL_VERIFICATION_ONLY',
                    generated_planet_assessed=False,geological_model_accepted=False)
        table=dict(AREA_ROWS);epsilon=SOURCE_POSITION_BOUND_M/EARTH_REFERENCE_RADIUS_M
        plates=[];numeric_issues=[];geometry_observations=[];unresolved=[]
        for curve in dataset.plates + dataset.orogens:
            _check_cancel(cancel)
            coordinates=curve.coordinates
            observation=dict(source_id=curve.source_id,kind=curve.kind,
                source_record=curve.record_number,source_title=curve.source_title,
                raw_coordinate_count=curve.count,explicitly_closed=curve.explicitly_closed,
                repeated_coordinate_numbers=[i+1 for i in curve.repeated_vertex_indices],
                exact_repeated_coordinate_count=len(curve.repeated_vertex_indices),
                raw_coordinates_preserved=True)
            if not curve.explicitly_closed:
                endpoints=lonlat_vectors(coordinates[[0,-1]])
                observation['endpoint_gap_m']=float(_angles(endpoints[:1],endpoints[1:])[0])*EARTH_REFERENCE_RADIUS_M
            geometry_observations.append(observation)
        for curve in dataset.plates:
            _check_cancel(cancel)
            row=dict(plate_id=curve.name,source_title=curve.source_title,source_record=curve.record_number,
                     area_role=record_role(observable='area',plate_id=curve.name),
                     shape_role=record_role(observable='outline',plate_id=curve.name))
            try:
                vectors=lonlat_vectors(curve.measurement_coordinates())
                m=spherical_ring_measures(vectors,budget=budget,cancel=cancel)
                numerical_bound=max(2e-12,64*m['segments']*np.finfo(float).eps)
                position_band=2*m['perimeter_radians']*epsilon+m['segments']*math.pi*epsilon**2
                area_bound=.000005+position_band
                row.update(status='MEASURED',metrics=m,table_area_sr=table[curve.name],
                     area_difference_sr=m['area_steradians']-table[curve.name],
                     source_area_rounding_bound_sr=area_bound,area_formula_bound_sr=numerical_bound)
                if include_scales:
                    row['multiscale']=multiscale_ring_measures(vectors,EARTH_REFERENCE_RADIUS_M,
                        OBSERVATION_SCALES_M,budget=budget,cancel=cancel)
                if abs(row['area_difference_sr'])>area_bound or m['area_formula_disagreement_sr']>numerical_bound:
                    numeric_issues.append(dict(kind='area',plate=curve.name,
                        source_table_difference_sr=row['area_difference_sr'],source_table_bound_sr=area_bound,
                        formula_disagreement_sr=m['area_formula_disagreement_sr'],formula_bound_sr=numerical_bound))
            except ReferenceDataError as exc:
                row.update(status='UNRESOLVED_SOURCE_GEOMETRY',metrics=None,error=str(exc))
                unresolved.append(dict(source_id=curve.source_id,error=str(exc)))
            plates.append(row)
        report['plates']=plates
        orogens=[]
        for curve in dataset.orogens:
            _check_cancel(cancel)
            row=dict(name=curve.name,source_record=curve.record_number,role=record_role(observable='orogen'),
                interpretation='overlapping diffuse-deformation overlay, not an additional rigid plate')
            try:
                row.update(status='MEASURED',metrics=spherical_ring_measures(
                    lonlat_vectors(curve.measurement_coordinates()),budget=budget,cancel=cancel))
            except ReferenceDataError as exc:
                row.update(status='UNRESOLVED_SOURCE_GEOMETRY',metrics=None,error=str(exc))
                unresolved.append(dict(source_id=curve.source_id,error=str(exc)))
            orogens.append(row)
        report['orogens']=orogens
        report['source_geometry']=dict(observations=geometry_observations,unresolved=unresolved,
            exact_repeated_coordinate_count=sum(o['exact_repeated_coordinate_count'] for o in geometry_observations),
            interpretation='raw evidence preserved; exact repeats omitted only from numerical views; open rings never closed implicitly')
        topology=boundary_inventory(dataset,cancel=cancel)
        report['connectivity']=topology
        report['source_step_alignment_issues']=_source_step_alignment(dataset)
        poles={p.plate_id:p for p in dataset.poles};motion_issues=[];max_errors=[0.,0.]
        class_lengths=defaultdict(list);orogen_lengths=defaultdict(list);roles=Counter();plate_classes=defaultdict(lambda:defaultdict(list))
        segments=defaultdict(list)
        for step in dataset.steps:
            _check_cancel(cancel);m=step_motion(step,poles)
            errors=[abs(m['opening_error_mm_a']),abs(m['right_lateral_error_mm_a'])]
            max_errors=[max(a,b) for a,b in zip(max_errors,errors)]
            if (not m['direction_resolved'] or max(errors)>m['component_rounding_bound_mm_a']
                    or abs(m['length_km']-m['source_length_km'])>m['length_rounding_bound_km']
                    or abs(m['speed_error_mm_a'])>m['speed_rounding_bound_mm_a']):
                motion_issues.append(m)
            roles[record_role(observable='motion',boundary=step.boundary,step_number=step.number)]+=1
            class_lengths[step.kind].append(m['length_km'])
            orogen_lengths[step.in_orogen].append(m['length_km'])
            for owner in (step.boundary[:2],step.boundary[3:]):plate_classes[owner][step.kind].append(m['length_km'])
            # A new source segment is not necessarily a physical change of type.
            if not step.continuous:segment_key=step.number
            segments[segment_key].append(step.kind)
        report['motion']=dict(steps_checked=len(dataset.steps),role_counts=dict(roles),
                              max_component_errors_mm_a=max_errors,issues=motion_issues,
                              interpretation='Euler reconstruction and rounded-table consistency, not independent dynamic validation')
        report['boundary_context']=dict(
            length_km_by_class={k:math.fsum(class_lengths[k]) for k in BOUNDARY_CLASSES},
            length_km_inside_orogens=math.fsum(orogen_lengths[True]),
            length_km_outside_orogens=math.fsum(orogen_lengths[False]),
            length_km_by_plate_and_class={p:{k:math.fsum(v) for k,v in sorted(classes.items())} for p,classes in sorted(plate_classes.items())},
            class_transitions_by_source_segment={str(k):sum(a!=b for a,b in zip(v,v[1:])) for k,v in segments.items()},
            note='source step classes and deformation flags preserved; no SUB label inferred only from convergence')
        report['numerical_issues']=numeric_issues
        measured=[r for r in plates if r['status']=='MEASURED']
        report['measurement_coverage']=dict(plates_attempted=len(plates),plates_measured=len(measured),
            orogens_attempted=len(orogens),orogens_measured=sum(r['status']=='MEASURED' for r in orogens),
            boundary_segments_checked=len(dataset.boundaries),motion_steps_checked=len(dataset.steps))
        # A partial sum is not a planetary closure result.
        report['area_sum_steradians']=math.fsum(r['metrics']['area_steradians'] for r in measured) if len(measured)==len(plates) else None
        report['area_closure_error_sr']=report['area_sum_steradians']-4*math.pi if report['area_sum_steradians'] is not None else None
        report['source_rounding_area_envelope_sr']=math.fsum(r['source_area_rounding_bound_sr'] for r in measured)
        okay=(not unresolved and not numeric_issues and not motion_issues and not topology['incidence_discrepancies']
              and not report['source_step_alignment_issues']
              and report['area_closure_error_sr'] is not None
              and abs(report['area_closure_error_sr'])<=report['source_rounding_area_envelope_sr'])
        report['status']='PASS_COMPLETE_REFERENCE_CHECKS' if okay else 'REFERENCE_DISCREPANCIES_REQUIRE_REVIEW'
        report['full_dataset_tested']=True
        report['reference_processing_completed']=True
        report['unavailable_gates']=['independent reconstruction/model','historical evolution','field-derived rigidity','geological generation acceptance']
        _check_cancel(cancel)
        return report


def write_report_snapshot(report, store, *, budget=None, cancel=None):
    """Use the existing exact snapshot store, not another reference-cache format."""
    from .storage import ArrayStore
    if (not isinstance(store,ArrayStore) or report.get('schema')!='atlas.plate-reference-report.r1.v1'
            or report.get('geological_model_accepted') is not False):
        raise ReferenceDataError('typed store and R1 report required')
    raw=_json(report);key=hashlib.sha256(raw).hexdigest()
    store.put(key,{'reference_report_utf8':np.frombuffer(raw,dtype='u1')},
              {'schema':'atlas.reference-report-snapshot.v1','report_sha256':key},budget=budget,cancel=cancel)
    return key


def read_report_snapshot(store, key, *, budget=None):
    """Restore the actual recorded source/version/results, never recompute a new reference."""
    data=store.get(key,budget=budget)
    if data is None:return None
    if (set(data)!={'reference_report_utf8'} or data['reference_report_utf8'].dtype!=np.dtype('u1')
            or data['reference_report_utf8'].ndim!=1
            or store.metadata(key)!={'schema':'atlas.reference-report-snapshot.v1','report_sha256':key}):
        raise ReferenceDataError('reference report snapshot inventory mismatch')
    raw=data['reference_report_utf8'].tobytes()
    if hashlib.sha256(raw).hexdigest()!=key:raise ReferenceDataError('reference report identity mismatch')
    record=json.loads(raw)
    if record.get('schema')!='atlas.plate-reference-report.r1.v1' or record.get('geological_model_accepted') is not False:
        raise ReferenceDataError('invalid reference report or unsupported acceptance claim')
    return record


def _compare_distributions(reference_values, candidate_values, *, metric, dataset_id,
                          candidate_id, split, run_id, reference_scale_m=None,
                          candidate_scale_m=None, unresolved_reference=0, unresolved_candidate=0):
    """Separate empirical-distribution discrepancies, never a composite realism pass.

    Area was used for calibration already. Shape comparisons must identify one
    common physical observation scale. Unresolved objects are disclosed, not
    silently discarded to improve agreement. Empirical CDF distance is descriptive;
    correlated plates are not independent samples and no p-value is invented.
    """
    from ._validation import read_array, scalar
    metrics=('area_fraction','compactness','reflex_turning_radians','neighbour_count',
             'boundary_length_radians','boundary_moment_ratio')
    if metric not in metrics:raise ReferenceDataError('unregistered population metric')
    if metric=='area_fraction' and split=='withheld':
        raise ReferenceDataError('PB2002 areas are exposed calibration, not withheld evidence')
    if metric not in ('area_fraction','neighbour_count'):
        a=scalar(reference_scale_m,'reference observation scale',positive=True)
        b=scalar(candidate_scale_m,'candidate observation scale',positive=True)
        if a!=b:raise ReferenceDataError('comparison requires identical physical observation scales')
    if any(type(n) is not int or n<0 for n in (unresolved_reference,unresolved_candidate)):
        raise ReferenceDataError('unresolved population counts must be nonnegative integers')
    a=read_array(reference_values,'reference observations',ndim=1,nonnegative=True)
    b=read_array(candidate_values,'candidate observations',ndim=1,nonnegative=True)
    if metric=='area_fraction' and (np.any(a>1) or np.any(b>1)):
        raise ReferenceDataError('area fractions must be in [0,1]')
    a=np.sort(a);b=np.sort(b);grid=np.union1d(a,b)
    gap=np.abs(np.searchsorted(a,grid,side='right')/len(a)-np.searchsorted(b,grid,side='right')/len(b))
    quantiles=(0.,.1,.25,.5,.75,.9,1.)
    record=evaluation_record(dataset_id,candidate_id,split=split,run_id=run_id,
                             purpose='validation' if split=='withheld' else 'calibration')
    record.update(metric=metric,observation_scale_m=reference_scale_m,
                  reference_count=len(a),candidate_count=len(b),
                  unresolved_reference=unresolved_reference,unresolved_candidate=unresolved_candidate,
                  quantile_probabilities=list(quantiles),
                  reference_quantiles=np.quantile(a,quantiles).tolist(),
                  candidate_quantiles=np.quantile(b,quantiles).tolist(),
                  empirical_cdf_maximum_gap=float(gap.max()),
                  scientific_threshold=None,status='DESCRIPTIVE_COMPARISON_NOT_ACCEPTANCE')
    return record


def compare_distributions(reference_values, candidate_values, *, metric, dataset_id,
                          candidate_id, split, run_id, reference_scale_m=None,
                          candidate_scale_m=None, unresolved_reference=0, unresolved_candidate=0,
                          budget=None, cancel=None):
    """Budgeted, cancellation-aware distribution comparison; see private method."""
    from ._validation import input_shape
    _check_cancel(cancel)
    a=input_shape(reference_values,'reference observations')
    b=input_shape(candidate_values,'candidate observations')
    if len(a)!=1 or len(b)!=1 or not a[0] or not b[0]:
        raise ReferenceDataError('nonempty one-dimensional observed populations required')
    with select_budget(budget).reserve(128*(a[0]+b[0])+16384,category='plate-reference-comparison'):
        result=_compare_distributions(reference_values,candidate_values,metric=metric,dataset_id=dataset_id,
             candidate_id=candidate_id,split=split,run_id=run_id,reference_scale_m=reference_scale_m,
             candidate_scale_m=candidate_scale_m,unresolved_reference=unresolved_reference,
             unresolved_candidate=unresolved_candidate)
        _check_cancel(cancel)
        return result
