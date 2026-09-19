#!/usr/bin/env python3
"""Bounded R4.1 publication review and same-work complete-call measurements.

SPDX-License-Identifier: AGPL-3.0-only
No reference acquisition, new model, installation or time evolution. Optional
--root explicitly selects an earlier source tree in a separate process; the
observer script's hash is recorded separately from that tree's source inventory.
"""
from pathlib import Path
from decimal import Decimal, localcontext
import argparse
import hashlib
import json
import platform
import sys
import time
import numpy as np


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--data-out',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.data_out is not None and args.data_out.exists():
        raise ValueError('refuse overwriting previous numerical evidence')
    sys.dont_write_bytecode=True
    sys.path[:0]=[str(root/'src'),str(root/'tests'),str(root)]
    from verify import source_inventory
    from atlas_tectonics import PreparedStokes2D,StokesSolvePolicy,DiffusiveScales,reference_rheology,face_force_from_density
    from atlas_tectonics.resources import WorkBudget
    from stokes_fixtures import unit_box,unit_scales,request
    before=source_inventory(root);probes=[];measurements=[];data={}
    def forces(a):return np.array([[a],[-a]]),np.array([[-a,a]])
    b=unit_box(2)
    for method in ('minres','direct'):
        for kappa,eta,a,label in [(1.,1.,20*np.nextafter(0.,1.),'rounded_subnormal'),
                                 (1.,1.,32*np.nextafter(0.,1.),'exact_subnormal'),
                                 (1.,1.,1e-310,'small_recorded_residual'),
                                 (1e22,1e100,1e-200,'extreme_reference_scale')]:
            s=DiffusiveScales('review-reference',1.,kappa,eta,1.,1.,1.)
            row={'case':label,'method':method,'force_n_m3':a,'eta_pa_s':eta,'reference_diffusivity_m2_s':kappa}
            with PreparedStokes2D(b,reference_rheology('constant'),s,policy=StokesSolvePolicy(method=method)) as p:
                try:r=p.solve(*forces(a),**request(b))
                except ValueError as e:row.update(accepted=False,error=str(e))
                else:
                    # In this exact 2x2 circulation, eta*A*u = 16 eta u.
                    # Normalise before multiplication to avoid repeating the
                    # very underflow being tested. eta=1e100 case is normal.
                    u=float(r.array('u_m_s')[0,1])
                    relative=abs(16*(u/(a/eta))-1.)
                    row.update(accepted=True,u_m_s=u,published_force_relative_residual=relative,
                               recorded_momentum=r.descriptor()['diagnostics']['momentum_linf'],
                               result_id=r.result_id)
            probes.append(row)
    tiny=np.nextafter(0.,1.);gravity=1e100
    face,_=face_force_from_density(b,np.tile([tiny,2*tiny],(2,1)),[gravity,0.])
    with localcontext() as ctx:
        ctx.prec=1100
        expected=float((Decimal.from_float(tiny)+Decimal.from_float(2*tiny))*Decimal.from_float(gravity)/2)
    probes.append({'case':'face_force_intermediate_rounding','actual_force_n_m3':float(face[0,0]),
                   'decimal_expected_n_m3':expected,'relative_error':abs(float(face[0,0])/expected-1)})
    for n in (64,256):
        box=unit_box(n);rng=np.random.default_rng(319+n)
        f=(rng.normal(size=(n,n-1)),rng.normal(size=(n-1,n)))
        budget=WorkBudget(256<<20);start=time.perf_counter()
        plan=PreparedStokes2D(box,reference_rheology('constant'),unit_scales(),budget=budget)
        setup=time.perf_counter()-start;times=[]
        try:
            for _ in range(6):
                start=time.perf_counter();r=plan.solve(*f,**request(box));times.append(time.perf_counter()-start)
            item={'n':n,'unknowns':box.unknowns,'setup_s':setup,'first_call_s':times[0],
                  'reused_calls_s':times[1:],'reused_median_s':float(np.median(times[1:])),
                  'iterations':r.descriptor()['iterations'],'diagnostics':r.descriptor()['diagnostics'],
                  'held_preparation_bytes':budget.reserved_bytes,'peak_admitted_bytes':budget.peak_reserved_bytes,
                  'result_id':r.result_id}
            if args.data_out is not None:
                for k in r.array_names:data[f'n{n}__{k}']=r.array(k)
        finally:plan.close()
        item['remaining_reserved_bytes']=budget.reserved_bytes;measurements.append(item)
    after=source_inventory(root)
    if after != before:raise ValueError('source changed during review measurement')
    if args.data_out is not None:
        with args.data_out.open('xb') as stream:np.savez_compressed(stream,**data)
    output={'schema':'atlas.r4-1-publication-review.v1',
            'status':'MEASURED_SCOPED_REVIEW_NOT_GEOLOGICAL_ACCEPTANCE',
            'observer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'runtime':{'python':platform.python_version(),'numpy':np.__version__,'platform':platform.system()},
            'source_sha256_before':before,'source_sha256_after':after,'source_unchanged':True,
            'probes':probes,'timings':measurements,
            'timing_scope':'fixed 64 and 256 square grids; setup, first call, five reused calls; complete calls include capture, solve, residuals and publication; not isolated process startup',
            'claims':{'physical_validation':False,'R4_complete':False,'RSS_cap':False,'universal_speedup':False}}
    print(json.dumps(output,indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
