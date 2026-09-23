"""Source-bound Tosi S14-S23 reference selection; no simulation or PDF dependency.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re

CASE_DIR=Path(__file__).resolve().parents[1]/'cases'
FILENAME='tosi_case5b_reference.json'
SCHEMA='atlas.tosi-case5b-reference.v1'
SELECTION='finest-published-column-no-fallback.v1'
CODES=('YACC','Plaatjes','CHIC','GAIA','StreamV','StagYY','FEniCS','Fluidity','ASPECT','MC3D')


def load_reference(specification):
    target=specification['cases'].get('case5b_numerical_targets')
    if not isinstance(target,dict) or target.get('path')!=FILENAME or target.get('schema')!=SCHEMA or target.get('selection')!=SELECTION:
        raise ValueError('Case 5b source-bound numerical targets missing or unsupported')
    path=CASE_DIR/FILENAME
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Symbolic-link reference paths refused')
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=target.get('sha256'):raise ValueError('Case 5b reference bytes changed')
    data=json.loads(raw)
    if data.get('schema')!=SCHEMA or data.get('source',{}).get('sha256')!=target.get('source_pdf_sha256'):
        raise ValueError('Case 5b source identity differs')
    if [t['code'] for t in data.get('tables',[])]!=list(CODES):raise ValueError('Incomplete case 5b source tables')
    for index,table in enumerate(data['tables'],14):
        meshes=table['meshes'];rows=table['rows']
        if table['table']!=f'S{index}' or table['page']!=index+7 or not rows or not meshes or len(set(meshes))!=len(meshes):
            raise ValueError('Invalid reference table coordinates')
        for stress,cells in rows.items():
            if not re.fullmatch(r'[2-5]\.\d',stress) or len(cells)!=len(meshes):raise ValueError('Invalid reference yield/grid coordinates')
            for cell in cells:
                if cell is None:continue
                if len(cell)!=3 or cell[2] not in ('steady','periodic'):raise ValueError('Invalid source regime')
                if any(type(x) is not str or not re.fullmatch(r'\d+\.\d+',x) for x in cell[:2]):raise ValueError('Invalid printed numerical value')
                lo,hi=map(float,cell[:2])
                if not (math.isfinite(lo) and math.isfinite(hi) and 0<lo<=hi):raise ValueError('Invalid reference extrema')
    return data,sha


def compare(diagnostics,specification,*,yield_stress,regime,cells):
    """All finest-column source rows, partitioned before inspecting Atlas values.

    Source meshes differ between methods, as in Table 2. The envelope is a
    finest-published reference comparison, NOT an exact-grid error estimate.
    Independent Atlas grid adequacy remains mandatory. No fallback to a coarser
    published column when the selected column has a dash/absent yield.
    """
    data,sha=load_reference(specification)
    if (type(yield_stress) not in (float,int) or not math.isfinite(yield_stress) or
            not 3<=yield_stress<=5 or abs(yield_stress*10-round(yield_stress*10))>1e-10 or
            type(cells) is not int or cells<1):raise ValueError('Exact supported yield and run mesh required')
    stress=f'{yield_stress:.1f}';groups={'steady':[],'periodic':[]};absent=[]
    for table in data['tables']:
        if table['code']=='MC3D':continue
        source=dict(code=table['code'],table=table['table'],page=table['page'],mesh=table['meshes'][-1],yield_stress=stress)
        row=table['rows'].get(stress)
        cell=None if row is None else row[-1]
        if cell is None:
            absent.append(dict(**source,status='SOURCE_ABSENT',reason='yield not tabulated' if row is None else 'printed dash'))
        else:groups[cell[2]].append(dict(**source,printed_values=cell[:2]))
    result=dict(status='UNRESOLVED',comparisons={},all_available_metrics_within_envelope=False,
        reference_sha256=sha,selection=SELECTION,run_cells=cells,yield_stress=stress,
        regime=regime,published_regime_groups=groups,source_absent=absent,
        mixed_published_regimes=all(groups.values()),
        meaning='One necessary finest-published comparison gate; not exact-grid error, unanimous regime agreement or benchmark acceptance')
    if regime not in groups or not groups[regime]:
        result['reason']='No finest-column published support for the diagnosed regime at this exact yield';return result
    matched=groups[regime]
    values={'Nu_top':[float(x) for row in matched for x in row['printed_values']]} if regime=='steady' else {
        'mean_cycle_minimum':[float(row['printed_values'][0]) for row in matched],
        'mean_cycle_maximum':[float(row['printed_values'][1]) for row in matched]}
    if regime=='periodic' and (diagnostics.get('resolved') is not True or
            type(diagnostics.get('complete_cycles')) is not int or diagnostics['complete_cycles']!=10):
        result['reason']='Both extrema averaged over ten complete cycles are required';return result
    margin=specification['predeclared_acceptance']['table_relative_margin']
    for key,reference in values.items():
        if key not in diagnostics:result['comparisons'][key]={'status':'MISSING'};continue
        value=diagnostics[key]
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Nonfinite or nonnumeric diagnostic')
        lo=min(reference);hi=max(reference);delta=margin*max(abs(lo),abs(hi))
        result['comparisons'][key]=dict(value=value,published_min=lo,published_max=hi,
            comparison_low=lo-delta,comparison_high=hi+delta,
            status='WITHIN_ENVELOPE' if lo-delta<=value<=hi+delta else 'OUTSIDE_ENVELOPE')
    result['all_available_metrics_within_envelope']=all(v['status']=='WITHIN_ENVELOPE' for v in result['comparisons'].values())
    result['status']='ALL_WITHIN_ENVELOPE' if result['all_available_metrics_within_envelope'] else 'NOT_ALL_WITHIN_ENVELOPE'
    return result
