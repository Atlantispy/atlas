"""Bounded authored R4.2 initial data and genuinely evolved illustration.
SPDX-License-Identifier: AGPL-3.0-only
This is not the R2-to-W02 world-initialisation workflow or a Tosi benchmark.
"""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))
from atlas_tectonics import (StokesBox2D,BoussinesqMaterial,DiffusiveScales,reference_rheology,
    ThermalBoundary2D,ThermochemicalProblem,ThermochemicalState,PreparedThermochemical2D,
    PreparedStokes2D,face_force_from_density)
from atlas_tectonics.thermochemical import _check_fields
from atlas_tectonics.resources import WorkBudget


def build_initial_state(n=None,budget=None):
    path=ROOT/'cases/thermochemical_r4_2.json'
    if path.is_symlink():raise ValueError('linked example case refused')
    raw=path.read_bytes();spec=json.loads(raw);a=spec['example'];digest=hashlib.sha256(raw).hexdigest()
    n=a['cells_per_axis'] if n is None else n
    if type(n) is not int or not 2<=n<=192:raise ValueError('bounded explicit example grid required')
    L=a['width_m'];H=a['height_m']
    b=StokesBox2D(n,n,L,H,'r4-2-authored-demo-Cartesian')
    source='Authored R4.2 demonstration, not Earth calibration; case SHA256 '+digest
    m=BoussinesqMaterial('illustrative-constant-Boussinesq',source,a['density_kg_m3'],a['heat_capacity_j_kg_k'],
        a['conductivity_w_m_k'],a['expansion_per_k'],a['reference_temperature_k'],a['composition_density_contrast_kg_m3'],
        a['heating_w_m3'],tuple(a['temperature_range_k']))
    kappa=m.conductivity_w_m_k/(m.density_kg_m3*m.heat_capacity_j_kg_k)
    p=ThermochemicalProblem(b,m,ThermalBoundary2D('fixed-top-bottom',a['bottom_temperature_k'],a['top_temperature_k']),
        reference_rheology('constant'),DiffusiveScales('illustrative-scales',L,kappa,a['viscosity_pa_s'],
        a['top_temperature_k'],a['bottom_temperature_k']-a['top_temperature_k'],H),tuple(a['gravity_m_s2']),
        'initial-state-epoch','slightly-denser-binary-constituent',source)
    budget=WorkBudget(256<<20) if budget is None else budget
    with budget.reserve(128*n*n+65536,category='thermochemical-example-input'):
        x,z=np.meshgrid(*b.axes());xx=x/L;zz=z/H
        T=a['bottom_temperature_k']+(a['top_temperature_k']-a['bottom_temperature_k'])*zz
        T+=a['temperature_perturbation_k']*np.sin(np.pi*zz)*np.cos(2*np.pi*(xx-.5))*np.sinc(.5/n)*np.sinc(1/n)
        nodes,weights=np.polynomial.legendre.leggauss(4);C=np.full_like(T,.2)
        for v,w in zip(nodes,weights):
            for vv,ww in zip(nodes,weights):
                C+=.6*w*ww/4*np.exp(-((xx+v/(2*n)-.5)/.15)**2-((zz+vv/(2*n)-.45)/.12)**2)
        state=ThermochemicalState(p,T,C,time_s=0.,source=source+'; authored cell-average initial fields',budget=budget)
    return state,spec,digest


def evolve_example(n=None,steps=None):
    budget=WorkBudget(256<<20)
    initial,spec,case_hash=build_initial_state(n,budget)
    steps=spec['example']['steps'] if steps is None else steps
    if type(steps) is not int or not 1<=steps<=spec['example']['steps']:raise ValueError('bounded explicit step count required')
    dt=spec['example']['dt_s'];state=initial;history=[]
    with PreparedThermochemical2D(state.problem,budget=budget) as plan:
        for i in range(steps):
            result=plan.advance(state,dt,source='R4.2 fixed illustrative interval; case '+case_hash)
            state=result.state
            history.append(dict(time_s=state.time_s,state_id=state.state_id,result_id=result.result_id,
                                **result.descriptor()['record']['balances']))
    # Recompute endpoint mechanics explicitly: the time step's retained velocities
    # belong to split RK stages and must not be drawn as a simultaneous endpoint.
    p=state.problem;rho,_=_check_fields(p,state.array('temperature_k'),state.array('composition'))
    forces=face_force_from_density(p.box,rho,p.gravity_m_s2,budget=budget)
    with PreparedStokes2D(p.box,p.rheology,p.scales,budget=budget) as solver:
        flow=solver.solve(*forces,frame_id=p.box.frame_id,epoch_id=p.epoch_id,time_s=state.time_s,
                          source='Recomputed accepted-endpoint mechanics for '+state.state_id)
    data={'initial_temperature_k':initial.array('temperature_k'),'final_temperature_k':state.array('temperature_k'),
          'initial_composition':initial.array('composition'),'final_composition':state.array('composition'),
          'temperature_change_k':state.array('temperature_k')-initial.array('temperature_k'),
          'final_u_m_s':flow.array('u_m_s'),'final_w_m_s':flow.array('w_m_s'),
          'final_pressure_pa':flow.array('pressure_pa'),'final_divergence_s_1':flow.array('divergence_s_1'),
          'time_s':np.array([h['time_s'] for h in history])}
    for k in ('heat_relative_residual','composition_relative_residual','composition_after_m3','heat_after_j',
              'bottom_outward_heat_j','top_outward_heat_j','source_heat_j','heat_change_j','courant_stage0','courant_stage1'):
        data[k]=np.array([h[k] for h in history])
    meta=dict(case_sha256=case_hash,problem=p.descriptor(),initial_id=initial.state_id,final_id=state.state_id,
        final_time_s=state.time_s,steps=steps,dt_s=dt,history=history,final_state=state.descriptor(),endpoint_flow=flow.descriptor(),
        initial_origin='AUTHORED cell averages',final_origin='EVOLVED constant-property heat/composition with two solved RK velocities per step',
        endpoint_flow_origin='SEPARATELY SOLVED from accepted final T/C, not an RK intermediate',
        R4_status='IN_PROGRESS',R4_complete=False,Tosi_benchmark=False,physical_validation=False,
        work_budget=budget.statistics())
    return data,meta
