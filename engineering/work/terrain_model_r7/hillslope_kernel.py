"""R7 successor of the pinned repaired-R2 hillslope kernel; not canon authority.

Finite-volume soil transport responds to the SAME physical surface used by
channel incision/deposition. Channel rates use the zero-porosity, equal-solid-
density, m=.5/n=1 SPACE subset, not a complete SPACE integrator. Every splitting
step is guarded; invalid timesteps fail rather than clipping terrain to a grade.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

MAX_CELLS = 16384
CONTRACT_PATH = Path(__file__).with_name("NUMERICAL_CONTRACT.json")
CONTRACT_SHA256 = "131b131067b9d0c4327a4130ec1e2d15e88fe56ee4e19c7b5219b2cb1ae708e5"
if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()!=CONTRACT_SHA256:
    raise ValueError("frozen R2 numerical contract changed")
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def number(value, name, low=None, strict=False):
    if type(value) not in (int, float):
        raise ValueError(name + " requires a real number")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(name + " is not binary64 representable") from exc
    if not math.isfinite(value) or (low is not None and (value <= low if strict else value < low)):
        raise ValueError(name + " outside finite supported range")
    return value


def _positive_product(values, name):
    """Preserve ordinary arithmetic; scale only an exceptional intermediate.

    All factors are nonnegative. A nonzero physical flux which is outside
    binary64 range is refused rather than silently reported as zero.
    """
    factors=tuple(number(v,name,0) for v in values)
    if any(v==0 for v in factors):return 0.
    ordinary=1.
    for value in factors:ordinary*=value
    if math.isfinite(ordinary) and ordinary>0:return ordinary
    mantissa=1.;exponent=0
    for value in factors:
        m,e=math.frexp(value);mantissa*=m;exponent+=e
        mantissa,shift=math.frexp(mantissa);exponent+=shift
    try:result=math.ldexp(mantissa,exponent)
    except OverflowError as exc:raise ValueError(name+' overflows representable range') from exc
    if not math.isfinite(result) or result<=0:
        raise ValueError(name+' positive value is outside representable range')
    return result


def _harmonic_mean(a,b):
    a=number(a,'face diffusivity',0,True);b=number(b,'face diffusivity',0,True)
    reciprocal=1/a+1/b
    if math.isfinite(reciprocal) and reciprocal>0:
        result=2/reciprocal
        if math.isfinite(result) and result>0:return result
    low,high=sorted((a,b))
    return number(low/(.5+.5*(low/high)),'harmonic face diffusivity',0,True)


def field(values, n, name, low=None):
    if type(values) not in (list, tuple) or len(values) != n:
        raise ValueError(name + " must match the full grid")
    return tuple(number(v, name, low) for v in values)


@dataclass(frozen=True)
class Grid:
    rows: int
    cols: int
    dx_m: float
    dy_m: float
    origin_x_m: float = 0.0
    origin_y_m: float = 0.0
    frame: str = "synthetic_local_m_x_east_y_south"
    vertical_datum: str = "synthetic_relative_m"

    def __post_init__(self):
        if any(type(v) is not int or v < 2 for v in (self.rows, self.cols)) or self.size > MAX_CELLS:
            raise ValueError("grid requires2..16384 cells with at least2 per axis")
        for name in ("dx_m", "dy_m"):
            object.__setattr__(self, name, number(getattr(self, name), name, 0, True))
        for name in ("origin_x_m", "origin_y_m"):
            object.__setattr__(self, name, number(getattr(self, name), name))
        if not math.isfinite(self.area_m2) or self.area_m2 <= 0:
            raise ValueError("grid area overflow/underflow")
        if not self.frame or not self.vertical_datum:
            raise ValueError("explicit frame and datum required")

    @property
    def size(self):
        return self.rows * self.cols

    @property
    def area_m2(self):
        return self.dx_m * self.dy_m

    def xy(self, index):
        if type(index) is not int or not 0 <= index < self.size:
            raise ValueError("invalid grid index")
        row, col = divmod(index, self.cols)
        return self.origin_x_m + (col + .5) * self.dx_m, self.origin_y_m + (row + .5) * self.dy_m

    def neighbours(self, index, diagonal=False):
        row, col = divmod(index, self.cols)
        for dr, dc in ((-1,0), (0,-1), (0,1), (1,0)) + (((-1,-1),(-1,1),(1,-1),(1,1)) if diagonal else ()):
            rr, cc = row + dr, col + dc
            if 0 <= rr < self.rows and 0 <= cc < self.cols:
                yield rr * self.cols + cc, math.hypot(dc * self.dx_m, dr * self.dy_m)


@dataclass(frozen=True)
class State:
    grid: Grid
    bedrock_m: tuple
    mobile_solid_m3: tuple
    porosity: tuple
    rock_density_kg_m3: float
    sediment_density_kg_m3: float
    source_status: str = "WORKING NON-CANON SYNTHETIC ENGINEERING SCENARIO"

    def __post_init__(self):
        if not isinstance(self.grid, Grid):
            raise ValueError("validated Grid required")
        n = self.grid.size
        object.__setattr__(self, "bedrock_m", field(self.bedrock_m,n,"bedrock_m"))
        object.__setattr__(self, "mobile_solid_m3", field(self.mobile_solid_m3,n,"mobile_solid_m3",0))
        object.__setattr__(self, "porosity", field(self.porosity,n,"porosity",0))
        if max(self.porosity) >= 1:
            raise ValueError("porosity must be less than1")
        for name in ("rock_density_kg_m3", "sediment_density_kg_m3"):
            object.__setattr__(self,name,number(getattr(self,name),name,0,True))
        if not self.source_status:
            raise ValueError("source status required")
        field(self.surface_m,n,"derived surface")

    @property
    def cover_m(self):
        a = self.grid.area_m2
        return tuple(v / (a * (1-p)) for v,p in zip(self.mobile_solid_m3,self.porosity,strict=True))

    @property
    def surface_m(self):
        return tuple(z+h for z,h in zip(self.bedrock_m,self.cover_m,strict=True))

    def as_dict(self):
        return {"bedrock_m":list(self.bedrock_m),"mobile_solid_m3":list(self.mobile_solid_m3),
                "mobile_cover_m":list(self.cover_m),"surface_m":list(self.surface_m),
                "porosity":list(self.porosity),"rock_density_kg_m3":self.rock_density_kg_m3,
                "sediment_density_kg_m3":self.sediment_density_kg_m3,"source_status":self.source_status}


def gradients(grid, heights, *, periodic_x=False):
    if type(periodic_x) is not bool:
        raise ValueError("periodic_x must be Boolean")
    z=field(heights,grid.size,"heights")
    gx=[]; gy=[]
    for i in range(grid.size):
        row,col=divmod(i,grid.cols)
        if periodic_x:
            left=row*grid.cols+(col-1)%grid.cols
            right=row*grid.cols+(col+1)%grid.cols
            x_distance=2*grid.dx_m
        else:
            left=i-1 if col else i; right=i+1 if col+1<grid.cols else i
            x_distance=(right-left)*grid.dx_m
        up=i-grid.cols if row else i; down=i+grid.cols if row+1<grid.rows else i
        gx.append((z[right]-z[left])/x_distance)
        gy.append((z[down]-z[up])/(((down-up)/grid.cols)*grid.dy_m))
    norm=[math.hypot(x,y) for x,y in zip(gx,gy,strict=True)]
    return {"dz_dx":gx,"dz_dy":gy,"grade_m_per_m":norm,
            "slope_degrees":[math.degrees(math.atan(s)) for s in norm],
            "grade_percent":[100*s for s in norm],"edge_method":
                "periodic centred x; one-sided y exterior" if periodic_x else "one-sided exterior; centred interior"}


def constraints_check(state, constraints):
    z=state.surface_m; seen=set()
    if not isinstance(constraints,list):
        raise ValueError("explicit constraints list required")
    issues=[]
    for c in constraints:
        if set(c)!={"id","cell","minimum_m","maximum_m","role","reason","source_status","source_sha256","owner"}:
            raise ValueError("incomplete constraint identity/provenance")
        if not isinstance(c["id"],str) or not c["id"] or c["id"] in seen:
            raise ValueError("unique constraint IDs required")
        seen.add(c["id"])
        cell=c["cell"]
        if type(cell) is not int or not 0<=cell<len(z):
            raise ValueError("constraint cell out of bounds")
        lo=number(c["minimum_m"],"constraint minimum"); hi=number(c["maximum_m"],"constraint maximum")
        if lo>hi:
            raise ValueError("CONFLICT incompatible interval:"+c["id"])
        if c["role"] not in {"hard","soft","reference"}:
            raise ValueError("invalid constraint role")
        if any(not isinstance(c[k],str) or not c[k] for k in ("reason","source_status","owner")):
            raise ValueError("constraint ownership/reason/status required")
        if not isinstance(c["source_sha256"],str) or len(c["source_sha256"])!=64 or any(x not in "0123456789abcdef" for x in c["source_sha256"]):
            raise ValueError("source sha256 required")
        if not lo<=z[cell]<=hi:
            issues.append({"id":c["id"],"role":c["role"],"actual_m":z[cell],"interval_m":[lo,hi]})
    if any(x["role"]=="hard" for x in issues):
        raise ValueError("CONFLICT hard controls:"+json.dumps(issues,sort_keys=True))
    return issues


def hillslope_step(state, diffusivity_m2_year, dt_years, critical_gradient=None, *, periodic_x=False):
    """Synchronous 4-face soil flux; material-limited, no bedrock clipping.

    K describes bulk mobile transport; the upslope porosity converts to solid
    volume. A timestep violating the conservative explicit bound is rejected.
    Roering's law is evaluated with a two-component face gradient.
    """
    if type(periodic_x) is not bool:
        raise ValueError("periodic_x must be Boolean")
    g=state.grid; n=g.size; z=state.surface_m
    k=field(diffusivity_m2_year,n,"diffusivity",0)
    dt=number(dt_years,"dt_years",0,True)
    critical=None if critical_gradient is None else field(critical_gradient,n,"critical gradient",0)
    gradient=gradients(g,z,periodic_x=periodic_x)
    faces=[]; maximum_d=0.
    for i in range(n):
        row,col=divmod(i,g.cols)
        right=i+1 if col+1<g.cols else (row*g.cols if periodic_x else n)
        for j,distance,width,tangent in ((right,g.dx_m,g.dy_m,"dz_dy"),(i+g.cols,g.dy_m,g.dx_m,"dz_dx")):
            if j>=n:
                continue
            if k[i]==0 or k[j]==0:
                continue
            normal=(z[i]-z[j])/distance
            if normal==0:
                continue
            source,target=(i,j) if normal>0 else (j,i)
            if state.mobile_solid_m3[source]==0:
                continue  # Bare cliffs are not capped or diffused as soil.
            coefficient=_harmonic_mean(k[i],k[j])
            norm2=normal*normal+((gradient[tangent][i]+gradient[tangent][j])*.5)**2
            ratio=0.
            if critical is not None:
                sc=min(critical[i],critical[j])
                if sc<=0 or norm2>=sc*sc:
                    raise ValueError("soil transport outside declared critical-gradient regime")
                ratio=norm2/(sc*sc)
            # Surface response uses receiving bulk volume, not just conserved
            # solid volume. This symmetric bound also covers a flux reversal.
            eps_i=1-state.porosity[i];eps_j=1-state.porosity[j]
            effective=coefficient*(1+ratio)/(1-ratio)**2*max(eps_i/eps_j,eps_j/eps_i)
            maximum_d=max(maximum_d,effective)
            amount=_positive_product((coefficient,abs(normal),1/(1-ratio),width,dt,1-state.porosity[source]),'face solid volume')
            number(amount,"face solid volume",0)
            faces.append((source,target,amount))
    cfl=maximum_d*dt*(1/g.dx_m**2+1/g.dy_m**2)
    if cfl>CONTRACT["explicit_diffusion_cfl"]:
        raise ValueError("timestep violates explicit diffusion stability bound")
    requested=[0.]*n
    for source,_,amount in faces:
        requested[source]+=amount
    scales=[min(1.,available/demand) if demand else 1. for available,demand in zip(state.mobile_solid_m3,requested,strict=True)]
    incoming=[[] for _ in range(n)]; outgoing=[[] for _ in range(n)]
    for source,target,amount in faces:
        actual=amount*scales[source]
        outgoing[source].append(actual); incoming[target].append(actual)
    updated=[math.fsum([state.mobile_solid_m3[i],math.fsum(incoming[i]),-math.fsum(outgoing[i])]) for i in range(n)]
    # Reject a negative inventory beyond representational roundoff; the only
    # zero repair is separately measured and included in conservation residual.
    roundoff=0.
    for i,v in enumerate(updated):
        if v<0:
            if v < -1e-12*max(1.,state.mobile_solid_m3[i]):
                raise ValueError("negative mobile inventory")
            roundoff-=v; updated[i]=0.
    result=replace(state,mobile_solid_m3=tuple(updated))
    residual=math.fsum(result.mobile_solid_m3)-math.fsum(state.mobile_solid_m3)
    return result,{"process":"hillslope_transport","internal_transferred_solid_m3":math.fsum(math.fsum(v) for v in outgoing),
                   "solid_volume_residual_m3":residual,"mass_residual_kg":residual*state.sediment_density_kg_m3,
                   "limited_source_cells":sum(v<1 for v in scales),"roundoff_zero_adjustment_m3":roundoff,
                   "explicit_cfl":cfl,"boundary":"periodic x / closed y" if periodic_x else "closed material flux"}


def raw_drainage(state, external_outlets):
    """Strict-descent D8 potential graph. Pits/flats remain unresolved terminals."""
    n=state.grid.size; z=state.surface_m
    if type(external_outlets) not in (list,tuple) or any(type(i) is not int or not 0<=i<n for i in external_outlets) or len(set(external_outlets))!=len(external_outlets):
        raise ValueError("explicit unique external outlet cells required")
    outlets=set(external_outlets); receivers=[]; lengths=[]
    for i in range(n):
        candidates=[((z[i]-z[j])/distance,-j,j,distance) for j,distance in state.grid.neighbours(i,True) if z[j]<z[i]]
        if i in outlets or not candidates:
            receivers.append(-1); lengths.append(0.)
        else:
            _,_,j,distance=max(candidates)
            receivers.append(j); lengths.append(distance)
    return {"receivers":receivers,"distance_m":lengths,
            "order":sorted(range(n),key=lambda i:(-z[i],i)),
            "external_outlets":sorted(outlets),
            "unresolved_terminals":[i for i,r in enumerate(receivers) if r==-1 and i not in outlets],
            "kind":"raw strict-descent potential graph, not hydraulics"}


def channel_step(state, runoff_m_year, sediment_k_per_year, rock_k_per_year, cover_scale_m,
                 settling_m_year, dt_years, external_outlets):
    """Guarded explicit mixed-bed step with conservative downstream exchange.

    Detachment/entrainment uses A^.5*S, so K has1/year units. Water runoff is
    explicit and need not equal rainfall. Supply-limited/no-runoff terminal
    deposition is retained as mobile sediment; water storage is a separate
    interface. This step does NOT solve a basin's water stage or backwater.
    """
    if any(state.porosity) or state.rock_density_kg_m3!=state.sediment_density_kg_m3:
        raise ValueError("channel reference requires zero porosity and equal solid densities")
    n=state.grid.size; a=state.grid.area_m2; z=state.surface_m; h=state.cover_m
    runoff=field(runoff_m_year,n,"runoff",0)
    ks=field(sediment_k_per_year,n,"sediment K",0); kr=field(rock_k_per_year,n,"rock K",0)
    hstar=number(cover_scale_m,"cover scale",0,True)
    velocity=number(settling_m_year,"settling",0)
    dt=number(dt_years,"dt",0,True)
    graph=raw_drainage(state,external_outlets)
    area=[a]*n; water=[q*a for q in runoff]; incoming=[0.]*n
    cover=list(state.mobile_solid_m3); rock=list(state.bedrock_m)
    erosion=[0.]*n; export=0.; stored_water=0.; exported_water=0.; outflux=[0.]*n
    outlets=set(external_outlets)
    for i in graph["order"]:
        j=graph["receivers"][i]
        if j<0 or water[i]==0:
            if i in outlets:
                export+=incoming[i]*dt; exported_water+=water[i]*dt
                outflux[i]=incoming[i]
            else:
                cover[i]+=incoming[i]*dt; stored_water+=water[i]*dt
            # A dry-cell incoming water flux cannot occur: water is aggregated
            # before processing. Zero water with sediment is stored, not erased.
        else:
            slope=(z[i]-z[j])/graph["distance_m"][i]
            intensity=math.sqrt(area[i])*slope
            exposed=math.exp(-h[i]/hstar)
            er=kr[i]*intensity*exposed
            es=ks[i]*intensity*(-math.expm1(-h[i]/hstar))
            q=(incoming[i]+a*(er+es))/(1+velocity*a/water[i])
            deposition=velocity*q/water[i]
            change=(deposition-es)*a*dt
            if state.mobile_solid_m3[i]+change<0:
                raise ValueError("channel timestep exhausts cover; reduce dt")
            rock[i]-=er*dt; cover[i]+=change; erosion[i]=er*a*dt
            incoming[j]+=q; outflux[i]=q
        if j>=0:
            area[j]+=area[i]; water[j]+=water[i]
    result=replace(state,bedrock_m=tuple(rock),mobile_solid_m3=tuple(cover))
    updated_surface=result.surface_m
    maximum_drop_consumption=0.
    for i,j in enumerate(graph["receivers"]):
        if j<0:continue
        old_drop=z[i]-z[j];new_drop=updated_surface[i]-updated_surface[j]
        fraction=max(0.,(old_drop-new_drop)/old_drop)
        maximum_drop_consumption=max(maximum_drop_consumption,fraction)
        if fraction>CONTRACT["channel_step_fraction_of_link_relief"]:
            raise ValueError("channel timestep consumes relative link relief excessively; reduce dt")
    # Use independently evaluated geometric bedrock difference, not only the
    # rate oracle; unavoidable subtraction error belongs in the residual.
    geometric_rock_loss=math.fsum((before-after)*a for before,after in zip(state.bedrock_m,result.bedrock_m,strict=True))
    mobile_change=math.fsum(result.mobile_solid_m3)-math.fsum(state.mobile_solid_m3)
    residual=mobile_change+export-geometric_rock_loss
    runoff_volume=math.fsum(q*a*dt for q in runoff)
    height_roundoff_bound=math.fsum(2*math.ulp(before)*a+2*math.ulp(after)*a for before,after in zip(state.bedrock_m,result.bedrock_m,strict=True))
    allowed=CONTRACT["solid_volume_m3"]["atol"]+CONTRACT["solid_volume_m3"]["rtol"]*max(abs(mobile_change),export,geometric_rock_loss)+height_roundoff_bound
    if abs(residual)>allowed:
        raise ValueError("channel geometric/material budget does not close")
    return result,{"process":"channel_mixed_bed","graph":graph,"area_m2":area,
                   "water_discharge_m3_year":water,"sediment_outflux_m3_year":outflux,
                   "rock_loss_solid_m3":geometric_rock_loss,"rate_rock_loss_solid_m3":math.fsum(erosion),
                   "mobile_change_m3":mobile_change,"external_solid_export_m3":export,
                   "solid_volume_residual_m3":residual,"mass_residual_kg":residual*state.sediment_density_kg_m3,
                   "solid_volume_tolerance_m3":allowed,"height_subtraction_roundoff_bound_m3":height_roundoff_bound,
                   "maximum_link_drop_consumption_fraction":maximum_drop_consumption,
                   "water_input_m3":runoff_volume,"external_water_export_m3":exported_water,
                   "unresolved_terminal_water_storage_m3":stored_water,
                   "water_residual_m3":stored_water+exported_water-runoff_volume,
                   "basin_stage_solved":False}


def advance(state, steps, dt_years, diffusivity_m2_year, runoff_m_year, sediment_k_per_year,
            rock_k_per_year, cover_scale_m, settling_m_year, external_outlets, constraints,
            critical_gradient=None, _deadline=None):
    if type(steps) is not int or not 1<=steps<=CONTRACT["max_steps"]:
        raise ValueError("bounded positive step count required")
    constraints_check(state,constraints)
    records=[]
    for step in range(steps):
        if _deadline is not None and time.monotonic()>_deadline:
            raise ValueError("bounded numerical wall-time envelope exceeded")
        state,hills=hillslope_step(state,diffusivity_m2_year,dt_years,critical_gradient)
        state,channel=channel_step(state,runoff_m_year,sediment_k_per_year,rock_k_per_year,
                                   cover_scale_m,settling_m_year,dt_years,external_outlets)
        controls=constraints_check(state,constraints)
        topology_sha=hashlib.sha256(json.dumps(channel["graph"]["receivers"],separators=(",",":")).encode()).hexdigest()
        records.append({"step":step,"hillslope":hills,
                        "channel":channel if step==steps-1 else {k:v for k,v in channel.items() if not isinstance(v,(list,dict))},
                        "raw_topology_sha256":topology_sha,"control_residuals":controls})
    return state,records
