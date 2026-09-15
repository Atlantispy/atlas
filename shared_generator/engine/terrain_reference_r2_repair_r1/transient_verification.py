"""Independent steady-rate and base-level-step convergence checks."""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path

from core import Grid, State, channel_step

PATH=Path(__file__).with_name("TRANSIENT_CONTRACT.json")
CONTRACT_SHA256="2e18b8ab77e1a371b404c2961089eb7264f3bc31d584ceb46dbfee77b94a369c"


def profile(contract):
    g=Grid(contract["rows"],contract["cols"],contract["spacing_m"],contract["spacing_m"])
    heights=[0.]*g.size
    for row in range(g.rows-2,-1,-1):
        contributing=(row+1)*g.area_m2
        drop=.07/math.sqrt(contributing)*g.dy_m
        for col in range(g.cols):heights[row*g.cols+col]=heights[(row+1)*g.cols+col]+drop
    cover=contract["cover_m"]
    return State(g,tuple(z-cover for z in heights),(cover*g.area_m2,)*g.size,(0.,)*g.size,2700.,2700.)


def evolve(s,contract,dt):
    n=s.grid.size; count=round(contract["total_duration_years"]/dt)
    max_residual=0.
    for _ in range(count):
        s,r=channel_step(s,[contract["runoff_m_per_year"]]*n,[contract["K_s_per_year"]]*n,
                         [contract["K_r_per_year"]]*n,contract["cover_scale_m"],contract["settling_m_per_year"],dt,[n-2,n-1])
        max_residual=max(max_residual,abs(r["solid_volume_residual_m3"]))
    return s,max_residual


def run_verification():
    raw=PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=CONTRACT_SHA256:raise ValueError("frozen transient contract changed")
    c=json.loads(raw)
    s=profile(c); n=s.grid.size; dt=.01
    unchanged,r=channel_step(s,[1.]*n,[c["K_s_per_year"]]*n,[c["K_r_per_year"]]*n,1.,5.,dt,[n-2,n-1])
    rates=[(s.bedrock_m[i]-unchanged.bedrock_m[i])/dt for i in range(n-2)]
    rate_error=max(abs(v-c["expected_unperturbed_erosion_m_per_year"]) for v in rates)
    perturbed=list(s.bedrock_m)
    for i in (n-2,n-1):perturbed[i]+=c["base_level_step_m"]
    s=replace(s,bedrock_m=tuple(perturbed))
    fine,fine_residual=evolve(s,c,c["fine_dt_years"])
    observations=[]
    for step in c["coarse_dt_years"]:
        final,residual=evolve(s,c,step)
        observations.append({"dt_years":step,"max_height_difference_from_fine_m":max(abs(a-b) for a,b in zip(final.surface_m,fine.surface_m)),
                             "max_solid_residual_m3":residual})
    ratios=[a["max_height_difference_from_fine_m"]/b["max_height_difference_from_fine_m"] for a,b in zip(observations,observations[1:])]
    checks={"steady_rate":rate_error<=c["rate_absolute_tolerance_m_per_year"],
            "convergence":all(v>=c["expected_error_refinement_ratio_minimum"] for v in ratios),
            "finite_cover":min(fine.mobile_solid_m3)>=0,"contract_unchanged":PATH.read_bytes()==raw}
    return {"status":"PASS_NUMERICAL_TRANSIENT_ONLY" if all(checks.values()) else "FAIL",
            "contract_sha256":hashlib.sha256(raw).hexdigest(),"checks":checks,"steady_rate_error_m_year":rate_error,
            "observations":observations,"error_ratios":ratios,"fine_max_solid_residual_m3":fine_residual,
            "physical_acceptance":False}


if __name__=="__main__":print(json.dumps(run_verification(),indent=2))
