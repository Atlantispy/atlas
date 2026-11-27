"""W01 4B: sourced Earth reference properties and explicit mixture bookkeeping.

A reference datum is not an equation of state. The catalogue retains original
units, source locations, population ranges, temperature provenance and basis.
No density, heat-capacity or conductivity value is extrapolated into a hot mantle.
No unknown heat source is set to zero. The old geological description schema is
not changed: adapters export selected constant REFERENCE values and source IDs.
Consumers needing condition-dependent laws must use their own named W03/W07 law.

Conductivity defaults to bounds, not an unjustified point estimate. Series and
parallel are exact ideal arrangements for scalar conductivities; geometric mixing
is an explicit random-mixture approximation, not automatic physical validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from functools import lru_cache
from decimal import Context, Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import json
import math
from types import MappingProxyType
from typing import TYPE_CHECKING, cast
if TYPE_CHECKING:
    from atlas_tectonics.history.geological_records import GeologicalLayer

import numpy as np

from atlas_tectonics._validation import TectonicsError, scalar
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import _immutable_deepcopy
from atlas_tectonics.integration.resources import check_event
from atlas_tectonics.history.geological_records import MaterialDefinition, GeologySource, GeologyError
from atlas_tectonics.materials.earth_material_data import LIBRARY_VERSION, SOURCES, ROWS, SEDIMENT_RECIPES

# Exact SI scale conversions. Linear expansion is converted only through its
# explicitly named isotropic approximation; a bare '1/K' cannot hide that choice.
UNIT_DEFINITIONS = (
    ('kg/m3', 'density', 1.), ('g/cm3', 'density', 1000.),
    ('W/m/K', 'conductivity', 1.), ('J/kg/K', 'heat_capacity', 1.),
    ('J/g/K', 'heat_capacity', 1000.), ('kJ/kg/K', 'heat_capacity', 1000.),
    ('W/m3', 'heat_production', 1.), ('microW/m3', 'heat_production', 1e-6),
    ('1/K', 'thermal_expansion', 1.), ('1e-5/K', 'thermal_expansion', 1e-5),
    ('linear_micro/K_isotropic', 'thermal_expansion', 3e-6),
)


def _unit_info(unit):
    # Tiny immutable lookup, performed during reference preparation, not per cell.
    # The tuple also participates in the existing loaded-constant identity guard.
    for name, physical, scale in UNIT_DEFINITIONS:
        if unit==name:return physical,scale
    raise MaterialLibraryError('unsupported property unit')

PROPERTIES = ('density', 'heat_capacity', 'conductivity', 'heat_production', 'thermal_expansion')
SI_UNITS = ('kg/m3', 'J/kg/K', 'W/m/K', 'W/m3', '1/K')
_CAPABILITIES = MappingProxyType({
    'inventory': ('density',), 'sensible_heat_reference': ('density','heat_capacity'),
    'conduction_reference': ('density','heat_capacity','conductivity'),
    'radiogenic_reference': ('heat_production',),
    'instantaneous_buoyancy': ('density','thermal_expansion'),
    'expansion_secant': ('thermal_expansion',),
})
MAX_PROFILES, MAX_SOURCES, MAX_RECIPE_COMPONENTS = 512, 128, 128
MAX_CATALOGUE_BYTES = 2 * 1024 * 1024


class MaterialLibraryError(GeologyError):
    """Missing, inconsistent or unsupported material knowledge; never zero data."""


def _text(value, label, limit=4096):
    return value


def _number(value, label, *, positive=False, nonnegative=False):
    try:return scalar(value,label,positive=positive,nonnegative=nonnegative)
    except TectonicsError as exc:raise MaterialLibraryError(str(exc)) from exc


def _json(value):
    try:
        return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,
                          allow_nan=False).encode('ascii')
    except (TypeError,ValueError,RecursionError,OverflowError) as exc:
        raise MaterialLibraryError('invalid material manifest') from exc


def _digest(value): return hashlib.sha256(_json(value)).hexdigest()


def _cancel(cancel):
    if cancel is not None:
        check_event(cancel, 'regional transport cancelled; no candidate published')


@dataclass(frozen=True, slots=True)
class MaterialReferenceSource:
    source_id: str
    citation: str
    url: str
    scope: str
    def __post_init__(self):
        for name in ('source_id','citation','url','scope'):
            getattr(self,name)


@dataclass(frozen=True, slots=True)
class PropertyDatum:
    """One factual scalar/range plus its actual meaning, not a fitted material law.

    reference_temperature_k is a labelled reference coordinate; 'nominal' notes
    identify missing exact measurement conditions. temperature_span_k is the
    interval of a SECANT, not permission to use it as an instantaneous derivative.
    No pressure dependence is supplied. Natural ranges are not probability bounds.
    """
    property: str
    reported_value: float
    reported_unit: str
    source_id: str
    locator: str
    reported_bounds: tuple[float,float] | None = None
    selection: str = 'reported'
    reference_temperature_k: float = 293.15
    temperature_span_k: tuple[float,float] | None = None
    condition_note: str = ''

    def __post_init__(self):
        object.__setattr__(self,'reported_value',_number(self.reported_value,'reported value',
            positive=self.property in ('density','conductivity','heat_capacity'),
            nonnegative=self.property=='heat_production'))
        object.__setattr__(self,'reference_temperature_k',_number(self.reference_temperature_k,'reference temperature',nonnegative=True))
        if self.reported_bounds is not None:
            lo,hi=(_number(x,'range endpoint') for x in self.reported_bounds)
            object.__setattr__(self,'reported_bounds',(lo,hi))
        secant=self.selection in ('interval_secant','isotropic_interval_secant')
        if secant:
            a,b=(_number(x,'secant temperature',nonnegative=True) for x in cast('tuple[float,float]', self.temperature_span_k))
            object.__setattr__(self,'temperature_span_k',(a,b))

    @property
    def value_si(self):
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
            return float(Decimal(str(self.reported_value))*Decimal(str(_unit_info(self.reported_unit)[1])))
    @property
    def bounds_si(self):
        if self.reported_bounds is None:
            value=self.value_si
            return value,value
        a,b=self.reported_bounds
        scale=_unit_info(self.reported_unit)[1]
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
            decimal_scale=Decimal(str(scale))
            return tuple(float(Decimal(str(v))*decimal_scale) for v in (a,b))
    @property
    def is_secant(self): return self.temperature_span_k is not None


@dataclass(frozen=True, slots=True)
class EarthMaterialProfile:
    material_id: str
    name: str
    family: str
    basis: str
    aliases: tuple[str,...]
    properties: tuple[PropertyDatum,...]
    note: str = ''
    profile_id: str = field(init=False)

    def __post_init__(self):
        for n in ('material_id','name','family'): getattr(self,n)
        object.__setattr__(self,'properties',tuple(sorted(self.properties,key=lambda p:PROPERTIES.index(p.property))))
        object.__setattr__(self,'profile_id',_digest(self.descriptor()))

    def descriptor(self):
        return {k:getattr(self,k) for k in ('material_id','name','family','basis','aliases','note')} | {
            'properties':[asdict(p) for p in self.properties]}

    def datum(self, name):
        return next((p for p in self.properties if p.property==name),None)

    def missing(self, capability='conduction_reference', *, temperature_k=None, pressure_pa=None):
        """Return every unsupported requirement instead of failing halfway through a run.

        No high-pressure or arbitrary-temperature law is hidden behind lookup.
        Reference numbers can be inspected without a temperature request; asking
        for an actual state enforces each datum's coordinate and secant meaning.
        """
        if temperature_k is not None: temperature_k=_number(temperature_k,'temperature',nonnegative=True)
        if pressure_pa is not None: pressure_pa=_number(pressure_pa,'pressure',nonnegative=True)
        problems=[]
        if pressure_pa is not None: problems.append('pressure: no pressure-qualified law or measurement range supplied')
        for key in _CAPABILITIES[capability]:
            d=self.datum(key)
            if d is None:problems.append(key+': not supplied for this profile');continue
            if d.is_secant and capability!='expansion_secant':
                problems.append(key+': interval secant is not an instantaneous material law')
            elif capability=='expansion_secant' and not d.is_secant:
                problems.append(key+': requested secant interval unavailable')
            elif temperature_k is not None and temperature_k!=d.reference_temperature_k:
                problems.append(key+': requested temperature differs from supplied reference; no extrapolation')
        if temperature_k is None and capability!='expansion_secant':
            temperatures={d.reference_temperature_k for key in _CAPABILITIES[capability]
                          if (d:=self.datum(key)) is not None and not d.is_secant}
            if len(temperatures)>1:problems.append('reference conditions differ between required properties')
        return tuple(problems)

    def require(self, capability='conduction_reference', **conditions):
        self.missing(capability,**conditions)
        return self


@dataclass(frozen=True, slots=True)
class SedimentMatrixRecipe:
    recipe_id: str
    components: tuple[tuple[str,float],...]
    statement: str
    def __post_init__(self):
        _fractions(self.components)


def _fractions(components):
    names=[];weights=[]
    for item in components:
        names.append(item[0]);weights.append(_number(item[1],'fraction',nonnegative=True))
    return tuple(names),tuple(weights)


@dataclass(frozen=True, slots=True, init=False)
class EarthMaterialLibrary:
    version: str
    profiles: tuple[EarthMaterialProfile,...]
    sources: tuple[MaterialReferenceSource,...]
    recipes: tuple[SedimentMatrixRecipe,...]
    library_id: str
    _index: object=field(repr=False,compare=False)
    _source_index: object=field(repr=False,compare=False)
    _aliases: object=field(repr=False,compare=False)
    _payload: bytes=field(repr=False,compare=False)

    def __init__(self, version, profiles: tuple[EarthMaterialProfile,...], sources: tuple[MaterialReferenceSource,...], recipes=()):
        profiles=tuple(sorted(profiles,key=lambda p:p.material_id));sources=tuple(sorted(sources,key=lambda s:s.source_id))
        index={p.material_id:p for p in profiles};source_index={s.source_id:s for s in sources}
        for p in profiles:
            if any(d.source_id not in source_index for d in p.properties):raise MaterialLibraryError('unknown property source')
        for r in recipes:
            if any(id not in index or index[id].basis!='grain' for id,_ in r.components):
                raise MaterialLibraryError('sediment recipes must refer to grain constituents')
        aliases={}
        for p in profiles:
            for name in (p.material_id,p.name,*p.aliases):aliases.setdefault(name.casefold(),set()).add(p.material_id)
        payload=_json({'schema':'atlas.earth-material-library.v1','version':version,
            'profiles':[p.descriptor() for p in profiles], 'sources':[asdict(s) for s in sources],
            'recipes':[asdict(r) for r in recipes]})
        for k,v in dict(version=version,profiles=profiles,sources=sources,recipes=recipes,
            library_id=hashlib.sha256(payload).hexdigest(),_index=MappingProxyType(index),
            _source_index=MappingProxyType(source_index),
            _aliases=MappingProxyType({k:tuple(sorted(v)) for k,v in aliases.items()}),_payload=payload).items():
            object.__setattr__(self,k,v)

    def __getitem__(self, material_id):
        # Scientific code uses canonical IDs, never ambiguous display-name guesses.
        try:return self._index[material_id]
        except (KeyError,TypeError) as exc:raise MaterialLibraryError('unknown canonical material ID: '+str(material_id)) from exc
    def find(self,name):
        return tuple(self._index[i] for i in self._aliases.get(name.casefold(),()))
    def descriptor(self):return json.loads(self._payload)
    @property
    def nbytes(self):return len(self._payload)
    def __reduce__(self):return (EarthMaterialLibrary,(self.version,self.profiles,self.sources,self.recipes))
    __deepcopy__ = _immutable_deepcopy

    def coverage(self, *, reference_temperature_k=293.15):
        """Reference-compatible coverage, not hot/high-pressure validation.

        A mineral's 0 C heat capacity does not complete its 20 C thermal profile.
        Secants are counted by their own source interval, not as state derivatives.
        """
        t=_number(reference_temperature_k,'reference temperature',nonnegative=True)
        return {c:tuple(p.material_id for p in self.profiles
            if not p.missing(c,temperature_k=None if c=='expansion_secant' else t))
                for c in _CAPABILITIES}

    def unresolved(self, ids, capability='conduction_reference', *,
                   reference_temperature_k=293.15, pressure_pa=None):
        """Return all preflight gaps for selected profiles, with no guessed values."""
        return tuple((id, self[id].missing(capability,temperature_k=reference_temperature_k,
                                          pressure_pa=pressure_pa)) for id in ids)


    def definitions(self, ids: tuple[str,...], *, reference_temperature_k=293.15):
        """Stage-4-compatible reference records + immutable provenance records.

        Per-property temperatures are not collapsed: mismatched cp and secant alpha
        are omitted with an explicit reason, never silently treated as 20 C data.
        The full source manifest remains retrievable by library/profile identity.
        No valid_temperature interval is invented from one reference measurement.
        """
        t=_number(reference_temperature_k,'reference temperature',nonnegative=True)
        definitions=[];sources=[]
        for id in sorted(ids):
            p=self[id];values={};missing=[]
            for key in PROPERTIES:
                d=p.datum(key)
                if d is None or d.is_secant or d.reference_temperature_k!=t:
                    values[key]=None
                    missing.append(key+(': secant/mismatched condition' if d is not None else ': source not supplied'))
                else:values[key]=d.value_si
            sid='earth-ref-'+_digest((self.library_id,p.profile_id,t))
            # A concise original statement preserves basis/selection/conditions in
            # existing GeologicalCase snapshots without copying articles.
            statement=_json({'library':self.library_id,'profile':p.profile_id,'version':self.version,
                'basis':p.basis,'reference_only':True,'note':p.note,
                'property_evidence':[asdict(d) for d in p.properties]}).decode('ascii')
            refs=tuple(sorted({self._source_index[d.source_id].url for d in p.properties}))
            sources.append(GeologySource(sid,'literature',statement,refs,p.profile_id))
            definitions.append(MaterialDefinition(id,'fluid' if p.basis=='fluid' else 'solid',sid,
                values['density'],values['conductivity'],values['heat_capacity'],values['heat_production'],
                values['thermal_expansion'],t,None,'; '.join(missing) if missing else None))
        return tuple(definitions),tuple(sources)

    def prepare(self, ids: tuple[str,...], properties=('density','heat_capacity','conductivity'), *,
                reference_temperature_k=293.15, budget=None):
        return PreparedMaterialTable(self,ids,properties,reference_temperature_k=reference_temperature_k,budget=budget)


@lru_cache(maxsize=1)
def earth_material_library() -> EarthMaterialLibrary:
    """One immutable, offline catalogue per process; no network or installation."""
    sources=tuple(MaterialReferenceSource(*x) for x in SOURCES)
    profiles=tuple(EarthMaterialProfile(*r[:5],tuple(PropertyDatum(*d) for d in r[5]),r[6]) for r in ROWS)
    recipes=tuple(SedimentMatrixRecipe(*x) for x in SEDIMENT_RECIPES)
    return EarthMaterialLibrary(LIBRARY_VERSION,profiles,sources,recipes)


@dataclass(frozen=True, slots=True)
class MaterialBlend:
    """Resolved reference mixture, with explicit approximation and missing fields."""
    component_volume_fractions: tuple[tuple[str,float],...]
    library_id: str
    density_kg_m3: float
    specific_heat_j_kg_k: float | None
    volumetric_heat_capacity_j_m3_k: float | None
    conductivity_w_m_k: float | None
    conductivity_bounds_w_m_k: tuple[float,float] | None
    heat_production_w_m3: float | None
    porosity: float
    conductivity_model: str
    reference_temperature_k: float
    notes: tuple[str,...]
    blend_id: str = field(init=False)
    def __post_init__(self):
        _fractions(self.component_volume_fractions)
        for name in ('density_kg_m3','specific_heat_j_kg_k','volumetric_heat_capacity_j_m3_k','conductivity_w_m_k'):
            value=getattr(self,name)
            if value is not None:object.__setattr__(self,name,_number(value,name,positive=True))
        if self.specific_heat_j_kg_k is not None:
            pass
        if self.heat_production_w_m3 is not None:
            object.__setattr__(self,'heat_production_w_m3',_number(self.heat_production_w_m3,'heat production',nonnegative=True))
        phi=_number(self.porosity,'porosity',nonnegative=True)
        object.__setattr__(self,'porosity',phi)
        object.__setattr__(self,'reference_temperature_k',_number(self.reference_temperature_k,'temperature',nonnegative=True))
        if self.conductivity_bounds_w_m_k is not None:
            pair=self.conductivity_bounds_w_m_k
            lo,hi=(_number(x,'conductivity bound',positive=True) for x in pair)
            object.__setattr__(self,'conductivity_bounds_w_m_k',(lo,hi))
        descriptor={f.name:getattr(self,f.name) for f in fields(self) if f.name!='blend_id'}
        object.__setattr__(self,'blend_id',_digest(descriptor))



def mix_materials(library: EarthMaterialLibrary, components: tuple[tuple[str,float],...], *,
                  fraction_basis: str, porosity: float=0., pore_fluid: str | None=None,
                  conductivity: str='bounds', reference_temperature_k: float=293.15,
                  budget=None) -> MaterialBlend:
    """Mix using additive volumes and heat inventories, not average cp by volume.

    Components describe the solid matrix; porosity is added ONLY to grain data.
    For mass fractions, v_i=(w_i/rho_i)/sum(w/rho). Heat capacity is mass-weighted:
    Cv=sum(v_i*rho_i*cp_i), cp=Cv/rho. No alpha blend is inferred without elastic
    constraints. No phase changes, reactions, excess volumes or radiogenic decay.
    """
    names,weights=_fractions(components)
    phi=_number(porosity,'porosity',nonnegative=True)
    t=_number(reference_temperature_k,'reference temperature',nonnegative=True)
    with select_budget(budget).reserve(4096+1024*(len(names)+1),category='material-mixture'):
        selected=[(library[n],w) for n,w in zip(names,weights) if w>0]
        values={}
        def value(p,key):
            cache_key=(p.material_id,key)
            if cache_key not in values:
                d=p.datum(key)
                values[cache_key]=None if d is None or d.is_secant or d.reference_temperature_k!=t else d.value_si
            return values[cache_key]
        if any(value(p,'density') is None for p,w in selected):raise MaterialLibraryError('mixture densities unavailable at the stated reference')
        if fraction_basis=='mass':
            reciprocal=[w/value(p,'density') for p,w in selected]; total=math.fsum(reciprocal)
            selected=[(p,x/total) for (p,_),x in zip(selected,reciprocal)]
        volumes=[(p,v*(1-phi)) for p,v in selected]
        if phi:
            fluid=library[pore_fluid]
            if fluid.basis!='fluid' or value(fluid,'density') is None:raise MaterialLibraryError('appropriate fluid reference required')
            volumes.append((fluid,phi))
        try:
            rho=math.fsum(v*value(p,'density') for p,v in volumes)
            all_cp=all(value(p,'heat_capacity') is not None for p,v in volumes)
            cv=math.fsum(v*value(p,'density')*value(p,'heat_capacity') for p,v in volumes) if all_cp else None
            cp=cv/rho if cv is not None else None
            all_k=all(value(p,'conductivity') is not None for p,v in volumes)
            bounds=None;k=None
            if all_k:
                series=1/math.fsum(v/value(p,'conductivity') for p,v in volumes)
                parallel=math.fsum(v*value(p,'conductivity') for p,v in volumes)
                bounds=(series,parallel)
                if conductivity=='series':k=series
                elif conductivity=='parallel':k=parallel
                elif conductivity=='geometric':k=math.exp(math.fsum(v*math.log(value(p,'conductivity')) for p,v in volumes))
            q=math.fsum(v*value(p,'heat_production') for p,v in volumes) if all(value(p,'heat_production') is not None for p,v in volumes) else None
            for val in (rho,cv,cp,k,q,*(bounds or ())):
                if val is not None and not math.isfinite(val):raise OverflowError('nonfinite mixture')
        except (OverflowError,ZeroDivisionError) as exc:raise MaterialLibraryError('mixture exceeds numerical range') from exc
        notes=['Additive volumes and local thermal equilibrium; source/profile uncertainty is not eliminated by mixing.']
        if not all_cp:notes.append('Heat capacity missing or at an incompatible reference condition; not zero.')
        if not all_k:notes.append('Conductivity missing at reference; no proxy or zero substituted.')
        elif conductivity=='bounds':notes.append('Conductivity structure unresolved; harmonic/arithmetic scalar bounds returned, no invented central value.')
        elif conductivity=='geometric':notes.append('Explicit geometric-mean approximation; not a universal porous-rock law or an accuracy upgrade.')
        if q is None:notes.append('Radiogenic heat requires source data for every nonzero constituent; no zero assumption.')
        return MaterialBlend(tuple((p.material_id,v) for p,v in volumes),library.library_id,rho,cp,cv,k,bounds,q,phi,conductivity,t,tuple(notes))


def sediment_matrix(recipe_id, *, porosity, pore_fluid=None, conductivity='bounds', library=None, budget=None):
    """Named grain recipes; pore volume must be supplied, never a hidden soil default."""
    lib=earth_material_library() if library is None else library
    recipe=cast(SedimentMatrixRecipe, next((r for r in lib.recipes if r.recipe_id==recipe_id),None))
    return mix_materials(lib,recipe.components,fraction_basis='volume',porosity=porosity,
                         pore_fluid=pore_fluid,conductivity=conductivity,budget=budget)


@dataclass(frozen=True, slots=True, init=False)
class PreparedMaterialTable:
    """One compact property table; gather integer material codes in native batches.

    Missing entries carry an independent boolean mask. Ordinary gather refuses
    them. No object, dictionary or source citation is duplicated per map cell.
    The caller accounts retained table/output memory; per-call admission is not RSS.
    """
    library_id: str
    material_ids: tuple[str,...]
    properties: tuple[str,...]
    reference_temperature_k: float
    table_id: str
    _values: bytes=field(repr=False)
    _known: bytes=field(repr=False)
    def __init__(self,library,ids,properties=('density','heat_capacity','conductivity'),*,reference_temperature_k=293.15,budget=None):
        t=_number(reference_temperature_k,'reference temperature',nonnegative=True)
        with select_budget(budget).reserve(8192+32*len(ids)*len(properties),category='material-table'):
            values=np.zeros((len(ids),len(properties)),dtype=np.float64);known=np.zeros_like(values,dtype=bool)
            for i,id in enumerate(ids):
                p=library[id]
                for j,key in enumerate(properties):
                    d=p.datum(key)
                    if d is not None and not d.is_secant and d.reference_temperature_k==t:values[i,j]=d.value_si;known[i,j]=True
            raw=values.tobytes();mask=known.tobytes()
            descriptor={'library':library.library_id,'ids':ids,'properties':properties,'temperature':t,'schema':'atlas.material-table.v1'}
            identity=hashlib.sha256(_json(descriptor)+b'\0'+raw+mask).hexdigest()
            for key,val in dict(library_id=library.library_id,material_ids=ids,properties=properties,reference_temperature_k=t,table_id=identity,_values=raw,_known=mask).items():object.__setattr__(self,key,val)
    @property
    def nbytes(self):return len(self._values)+len(self._known)
    def inspect(self):
        shape=(len(self.material_ids),len(self.properties))
        return np.frombuffer(self._values,dtype=np.float64).reshape(shape),np.frombuffer(self._known,dtype=bool).reshape(shape)
    def gather(self,codes: np.ndarray,*,budget=None,cancel=None):
        """Dense integer codes -> immutable (...,properties) reference data, or refuse.

        Call inspect() for an explicitly masked catalogue view. A missing physical
        property is never emitted as the internal zero placeholder from this path.
        """
        _cancel(cancel)
        required=8192+codes.size*(codes.itemsize+24*len(self.properties)+8)
        with select_budget(budget).reserve(required,category='material-gather'):
            captured=np.array(codes,copy=True,order='C');values,known=self.inspect()
            unique=np.unique(captured)
            if unique.size and not known[unique].all():
                missing=[self.material_ids[int(i)]+':'+self.properties[j] for i in unique for j in range(len(self.properties)) if not known[int(i),j]]
                raise MaterialLibraryError('missing or incompatible reference data: '+', '.join(missing))
            result=np.empty(captured.shape+(len(self.properties),),dtype=np.float64)
            flat=result.reshape(-1,len(self.properties));source=captured.reshape(-1)
            for start in range(0,source.size,65536):
                _cancel(cancel);flat[start:start+65536]=values[source[start:start+65536]]
            _cancel(cancel)
            return np.frombuffer(result.tobytes(),dtype=np.float64).reshape(result.shape)
    def __reduce__(self):
        return (_restore_table, (self.library_id,self.material_ids,self.properties,
            self.reference_temperature_k,self._values,self._known,self.table_id))
    __deepcopy__ = _immutable_deepcopy


def _restore_table(library_id,ids,properties,t,raw,mask,expected):
    """Restore typed compact buffers and verify their descriptor, not pickle flags."""
    t=_number(t,'table reference temperature',nonnegative=True)
    v=np.frombuffer(raw,dtype=np.float64);m=np.frombuffer(mask,dtype=bool)
    shaped=v.reshape(len(ids),len(properties));m.reshape(shaped.shape)
    for j,key in enumerate(properties):
        pass
    descriptor={'library':library_id,'ids':ids,'properties':properties,'temperature':t,'schema':'atlas.material-table.v1'}
    actual=hashlib.sha256(_json(descriptor)+b'\0'+raw+mask).hexdigest()
    table=object.__new__(PreparedMaterialTable)
    for key,value in dict(library_id=library_id,material_ids=ids,properties=properties,
        reference_temperature_k=t,table_id=actual,_values=raw,_known=mask).items():object.__setattr__(table,key,value)
    return table


@dataclass(frozen=True, slots=True)
class RadiogenicAssay:
    """Elemental mass fractions, NOT oxide percentages; present-day natural mixture."""
    uranium_ppm: float
    thorium_ppm: float
    potassium_weight_percent: float
    source_id: str
    def __post_init__(self):
        for key in ('uranium_ppm','thorium_ppm','potassium_weight_percent'):
            object.__setattr__(self,key,_number(getattr(self,key),key,nonnegative=True))
    def heat_production(self,density_kg_m3):
        """Rybach reference equation in SI W/m3; not radioactive-history evolution.

        Original equation returns microW/m3: multiply by 1e-6 exactly once.
        Do not accept K2O here: its elemental conversion belongs to the assay source.
        """
        rho=_number(density_kg_m3,'density',positive=True)
        q=rho*1e-11*math.fsum((9.52*self.uranium_ppm,2.56*self.thorium_ppm,3.48*self.potassium_weight_percent))
        return q


def save_material_library(library,store,*,budget=None,cancel=None):
    """Persist actual reference records, not just a dependency on an installed version."""
    _cancel(cancel)
    return store.put(library.library_id,{'catalogue_json':np.frombuffer(library._payload,dtype='u1')},
        {'schema':'atlas.earth-material-snapshot.v1','library_id':library.library_id,'version':library.version},
        budget=budget,cancel=cancel)


def restore_material_library(payload: bytes, expected_id: str):
    """Strict bounded canonical format. No pickle or executable external contents."""
    def pairs(items):
        result={}
        for k,v in items:
            result[k]=v
        return result
    try:
        data=json.loads(payload,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(MaterialLibraryError('nonfinite catalogue')))
        if type(data) is not dict or set(data)!={'schema','version','profiles','sources','recipes'} or data['schema']!='atlas.earth-material-library.v1':raise MaterialLibraryError('invalid catalogue schema')
        if type(data['profiles']) is not list or len(data['profiles'])>MAX_PROFILES or type(data['sources']) is not list or len(data['sources'])>MAX_SOURCES or type(data['recipes']) is not list or len(data['recipes'])>128:raise MaterialLibraryError('catalogue inventory exceeds limit')
        profiles=[]
        for p in data['profiles']:
            if set(p)!={'material_id','name','family','basis','aliases','properties','note'}:raise MaterialLibraryError('invalid profile schema')
            if type(p['properties']) is not list or not 1<=len(p['properties'])<=len(PROPERTIES):
                raise MaterialLibraryError('invalid property inventory')
            ds=[]
            for d in p['properties']:
                if d['reported_bounds'] is not None:d['reported_bounds']=tuple(d['reported_bounds'])
                if d['temperature_span_k'] is not None:d['temperature_span_k']=tuple(d['temperature_span_k'])
                ds.append(PropertyDatum(**d))
            profiles.append(EarthMaterialProfile(p['material_id'],p['name'],p['family'],p['basis'],tuple(p['aliases']),tuple(ds),p['note']))
        result=EarthMaterialLibrary(data['version'],tuple(profiles),tuple(MaterialReferenceSource(**s) for s in data['sources']),tuple(SedimentMatrixRecipe(r['recipe_id'],tuple(tuple(c) for c in r['components']),r['statement']) for r in data['recipes']))
        if result._payload!=payload:raise MaterialLibraryError('noncanonical or altered catalogue representation')
        return result
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError) as exc:
        if isinstance(exc,MaterialLibraryError):raise
        raise MaterialLibraryError('malformed material catalogue') from exc


def load_material_library(store,library_id,*,budget=None,cancel=None):
    _cancel(cancel)
    data=store.get(library_id,budget=budget)
    if data is None:return None
    store.metadata(library_id)
    a=data['catalogue_json']
    with store._workspace(48*a.nbytes+8192,budget,category='material-restore'):
        result=restore_material_library(a.tobytes(),library_id)
        _cancel(cancel);return result


def resolve_geological_layer(case, column_id, layer_id, *, library=None,
                              conductivity='bounds', reference_temperature_k=293.15,
                              budget=None):
    """Resolve an existing stage-4 layer against the exact library it was bound to.

    This is property resolution, not spatial sampling, compaction or heat evolution.
    Cohorts with the same material share properties without losing cohort histories.
    A bulk-rock reference cannot be used as a mineral matrix and given pores again.
    A changed material or evidence record requires explicit rebinding, not overwrite.
    """
    lib=earth_material_library() if library is None else library
    column=case.column(column_id)
    layer=cast('GeologicalLayer', next((l for l in column.layers if l.layer_id==layer_id),None))
    if layer.porosity is None:raise MaterialLibraryError('porosity is unknown, not zero')
    with select_budget(budget).reserve(8192+2048*(len(layer.components)+1),category='layer-materials'):
        cohorts={c.cohort.cohort_id:c.cohort for c in case.cohorts}
        groups={}
        for part in layer.components:
            id=cohorts[part.cohort_id].material_id
            groups.setdefault(id,[]).append(part.solid_volume_fraction)
        fluid=column.fluid_material_id if layer.porosity>0 else None
        selected=tuple(sorted(set(groups)|({fluid} if fluid is not None else set())))
        expected,sources=lib.definitions(selected,reference_temperature_k=reference_temperature_k)
        components=tuple((id,math.fsum(v)) for id,v in sorted(groups.items()))
        return mix_materials(lib,components,fraction_basis='volume',porosity=layer.porosity,
            pore_fluid=fluid,conductivity=conductivity,reference_temperature_k=reference_temperature_k,
            budget=budget)
