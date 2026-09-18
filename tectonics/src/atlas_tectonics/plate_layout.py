"""Reference-conditioned connected initial layouts; no inferred plate dynamics.

The old one-site/one-plate Voronoi generator remains a named geometry fixture.
Here a fine shared spherical subdivision is partitioned by connected recursive
geodesic cuts, using a published rank/area spectrum. Three native sparse shortest-
path solves per split avoid an all-pairs matrix. Subdivision cells are NOT plates.

The generated geometry is a statistical hypothesis. Area fitting is calibration.
This module deliberately DOES NOT issue geological acceptance: full outline,
deformation-zone and motion/history evidence is still required. It records that
missing evidence in every generated atlas, rather than treating a closed sphere
as proof of Earth-like plate tectonics.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
import hashlib
import math
import numpy as np
from .coordinates import SphericalFrame
from .geometry import GeometryError, _check_cancel, _json, _limits
from .resources import select_budget
from .planetary_generation import PlanetPartitionSettings, generate_planetary_partition, _runtime
from .spherical_atlas import SphericalAtlas, build_spherical_atlas, _angle
from .plate_reference import reference_area_fractions, plate_reference_record

_METHOD='pb2002-ranked-connected-geodesic-cuts-v1'


@dataclass(frozen=True, slots=True)
class PlateLayoutSettings:
    """Explicit initialisation prior and finite geometric resolution.

    ``support_cells`` controls the generating subdivision, NOT screen pixels and
    not solver cells. Increasing it changes the statistical model's resolved
    boundary scale and receives a different identity. Working-patch subdivision
    of an already generated layout does not change the physical plate geometry.
    A caller cannot lower accuracy automatically in response to memory pressure.
    """
    plate_count: int
    seed: int
    support_cells: int = 1024
    max_area_l1_error: float = .04
    max_relative_area_error: float = .25

    def __post_init__(self):
        if type(self.plate_count) is not int or not 2 <= self.plate_count <= 52:
            raise GeometryError('reference-conditioned plate_count must be in 2..52')
        if type(self.seed) is not int or not 0 <= self.seed < 2**128:
            raise GeometryError('seed must be unsigned 128-bit')
        if type(self.support_cells) is not int or self.support_cells < 4*self.plate_count:
            raise GeometryError('at least four support cells per requested plate are required')
        from ._validation import scalar
        absolute=scalar(self.max_area_l1_error,'max_area_l1_error',positive=True)
        relative=scalar(self.max_relative_area_error,'max_relative_area_error',positive=True)
        if absolute>.1 or relative>1:raise GeometryError('invalid area approximation tolerance')
        object.__setattr__(self,'max_area_l1_error',absolute)
        object.__setattr__(self,'max_relative_area_error',relative)


def _graph(atlas):
    """Dual adjacency from authoritative shared edges; strictly positive costs."""
    from scipy.sparse import csr_matrix
    centres=[]
    for p in atlas.patches: centres.append(np.array(p.chart.centre))
    centres=np.asarray(centres)
    sides=atlas.side_patches
    dist=_angle(centres[sides[:,0]],centres[sides[:,1]])
    rows=np.r_[sides[:,0],sides[:,1]];cols=np.r_[sides[:,1],sides[:,0]]
    return csr_matrix((np.r_[dist,dist],(rows,cols)),shape=(len(centres),len(centres)))


def _connected_cut(graph, nodes, areas, wanted, reserve_left, reserve_right, salt, cancel):
    """Connected weighted geodesic Voronoi cut with an area-selected threshold.

    Difference of two shortest-path distances is monotone towards its associated
    source. Strict sub/superlevel sets are therefore connected, barring numerical
    ties. Ties are NOT perturbed or broken into disconnected islands: candidate
    cuts are independently checked. A failed cut causes an explicit refusal.
    """
    from scipy.sparse.csgraph import dijkstra, connected_components
    g=graph[nodes][:,nodes]
    if connected_components(g,directed=False,return_labels=False)!=1:
        raise GeometryError('partition recursion received disconnected support')
    first=int.from_bytes(hashlib.sha256(salt).digest()[:8],'little')%len(nodes)
    d0=dijkstra(g,directed=False,indices=first)
    a=int(np.argmax(d0));da=dijkstra(g,directed=False,indices=a)
    b=int(np.argmax(da));db=dijkstra(g,directed=False,indices=b)
    score=da-db
    order=np.argsort(score,kind='stable')
    cumulative=np.cumsum(areas[nodes[order]],dtype='f8')
    positions=np.arange(reserve_left,len(nodes)-reserve_right+1)
    if len(positions)==0:raise GeometryError('unresolved plate population; increase support_cells')
    ranked=positions[np.argsort(np.abs(cumulative[positions-1]-wanted),kind='stable')]
    # Only a bounded set of neighbouring thresholds is tried, not indefinite
    # post-hoc editing of the requested statistical spectrum.
    for cut in ranked[:64]:
        _check_cancel(cancel)
        if score[order[cut-1]] == score[order[cut]]:continue
        left,right=np.sort(nodes[order[:cut]]),np.sort(nodes[order[cut:]])
        if (connected_components(graph[left][:,left],directed=False,return_labels=False)==1
            and connected_components(graph[right][:,right],directed=False,return_labels=False)==1):
            return left,right
    raise GeometryError('no connected nonambiguous cut within the finite search; increase support resolution or change seed')


def _assign(graph, areas, targets, seed, cancel):
    labels=np.full(len(areas),-1,dtype='i8')
    pending=[(np.arange(len(areas)),tuple(range(len(targets))),b'root')]
    while pending:
        nodes,owners,path=pending.pop();_check_cancel(cancel)
        if len(owners)==1:
            labels[nodes]=owners[0];continue
        weights=targets[list(owners)];prefix=np.cumsum(weights)
        split=int(np.argmin(abs(prefix[:-1]-prefix[-1]*.5)))+1
        lhs,rhs=owners[:split],owners[split:]
        fraction=math.fsum(targets[i] for i in lhs)/math.fsum(weights)
        wanted=math.fsum(areas[nodes])*fraction
        left,right=_connected_cut(graph,nodes,areas,wanted,len(lhs),len(rhs),
                      seed.to_bytes(16,'little')+path,cancel)
        pending.append((right,rhs,path+b'R'));pending.append((left,lhs,path+b'L'))
    if np.any(labels<0):raise GeometryError('unassigned support remains')
    return labels


def layout_metrics(atlas, *, budget=None, cancel=None):
    """Scale-explicit morphology diagnostics, never a geological pass certificate.

    Compactness is the spherical isoperimetric quotient A(4*pi-A)/P^2.
    It is invariant under radius and global rotation, unlike planar 4*pi*A/P^2.
    Use plate_outline_cycles + spherical_ring_metrics for supported simple
    outlines. These diagnostics do not compare unequal resolutions as equivalent.
    """
    _check_cancel(cancel)
    if type(atlas) is not SphericalAtlas:raise GeometryError('SphericalAtlas required')
    from scipy.sparse.csgraph import connected_components
    ids=atlas.plate_ids;lookup={n:i for i,n in enumerate(ids)}
    with select_budget(budget).reserve(256*(len(atlas.patches)+atlas.edge_count)+16384,category='plate-layout-metrics'):
        areas=np.zeros(len(ids));perimeters=np.zeros(len(ids));degree=np.zeros(len(ids),dtype='i8')
        for p,a in zip(atlas.patches,atlas.patch_areas_sr):areas[lookup[p.plate_id]]+=a
        points=atlas.vertex_directions;lengths=_angle(points[atlas.edge_vertices[:,0]],points[atlas.edge_vertices[:,1]])
        graph=_graph(atlas);owners=np.array([lookup[p.plate_id] for p in atlas.patches]);components=[]
        for i in range(len(ids)):
            _check_cancel(cancel);nodes=np.flatnonzero(owners==i)
            components.append(int(connected_components(graph[nodes][:,nodes],directed=False,return_labels=False)))
        for j,(a,b) in enumerate(atlas.side_patches):
            left,right=owners[a],owners[b]
            if left!=right:perimeters[left]+=lengths[j];perimeters[right]+=lengths[j]
        for a,b in atlas.adjacency():degree[lookup[a]]+=1;degree[lookup[b]]+=1
        positive=perimeters>0
        compact=np.ones(len(ids));compact[positive]=areas[positive]*(4*math.pi-areas[positive])/perimeters[positive]**2
        fr=areas/(4*math.pi);order=np.argsort(-fr,kind='stable')
        return {'schema':'atlas.plate-layout-metrics.v1','plate_ids':list(ids),
            'area_fractions':fr.tolist(),'ranked_area_fractions':fr[order].tolist(),
            'area_steradians':areas.tolist(),'perimeter_radians':perimeters.tolist(),
            'compactness':compact.tolist(),'neighbour_count':degree.tolist(),
            'connected_components':components,'largest_fraction':float(fr.max()),
            'smallest_fraction':float(fr.min()),'area_ratio':float(fr.max()/fr.min()),
            'boundary_length_radians':float(perimeters.sum()/2),
            'maximum_support_area_sr':float(atlas.patch_areas_sr.max()),
            'morphology_validated':False,'dynamics_validated':False}


def _generate_plate_layout(sphere, settings, *, limits=None, budget=None, cancel=None, execution_id):
    """Construct a reference-conditioned hypothesis and return it with honest status.

    This is a reference-conditioned candidate, NOT a certified Earth-like default.
    The legacy
    PlanetPartitionSettings route is explicitly a Voronoi geometry fixture.
    Normal generation does not infer velocity vectors, subduction polarity, crust
    type or weakening from areas. Those require a supported scenario/history.
    """
    if type(sphere) is not SphericalFrame or type(settings) is not PlateLayoutSettings:
        raise GeometryError('explicit sphere and PlateLayoutSettings required')
    _check_cancel(cancel);lim=_limits(limits);policy=select_budget(budget)
    # Reuse the audited subdivision builder. The intermediate owners are temporary
    # support labels, never exported as independent tectonic plates.
    support=generate_planetary_partition(sphere,PlanetPartitionSettings(settings.support_cells,settings.seed),
                                         limits=lim,budget=policy,cancel=cancel)
    n=len(support.patches)
    with policy.reserve(support.retained_bytes_estimate+4096*n+65536,category='plate-layout'):
        graph=_graph(support);targets=reference_area_fractions(settings.plate_count)
        labels=_assign(graph,support.patch_areas_sr,targets,settings.seed,cancel)
        fractions=np.bincount(labels,weights=support.patch_areas_sr,minlength=settings.plate_count)/(4*math.pi)
        error=float(np.abs(fractions-targets).sum())
        relative_error=np.abs(fractions-targets)/targets
        if float(relative_error.max())>settings.max_relative_area_error:
            raise GeometryError('a small plate is unresolved: relative area error exceeds requested limit; increase support resolution')
        if error>settings.max_area_l1_error:
            raise GeometryError(f'area spectrum unresolved: L1 error {error:.6g} exceeds {settings.max_area_l1_error}; increase support_cells, never relax silently')
        patches=tuple(replace(p,region_id=f'plate-{labels[i]:06d}',plate_id=f'plate-{labels[i]:06d}') for i,p in enumerate(support.patches))
        unresolved=[int(i) for i,t in enumerate(targets) if 4*math.pi*t<4*support.patch_areas_sr.max()]
        reference=plate_reference_record()
        record={'schema':'atlas.plate-layout-generation.v1','method':_METHOD,
            'settings':asdict(settings),'reference':reference,'support_geometry_id':support.geometry_id,
            'target_area_fractions':targets.tolist(),'realised_area_fractions':fractions.tolist(),
            'area_l1_error':error,'relative_area_errors':relative_error.tolist(),'poorly_resolved_ranks':unresolved,
            'prior':'largest-N PB2002 areas, proportionally renormalised; connected native geodesic cuts',
            'acceptance':{'geometry':'checked','area_spectrum':'calibrated-not-independent-validation',
                'outline_morphology':'NOT_ACCEPTED','motion_history':'NOT_ACCEPTED',
                'geological_validation':False},'runtime':_runtime(),
            'execution_id':execution_id}
        atlas=build_spherical_atlas(sphere,dict(zip(support.vertex_ids,support.vertex_directions)),patches,
            limits=lim,budget=policy,cancel=cancel,source_bindings={'plate_layout':record})
        _check_cancel(cancel);return atlas


def require_geological_layout_acceptance(atlas):
    """A closed partition/area fit must never be silently certified as realistic.

    No generated route currently supplies the independent full-outline and history
    evidence needed by this gate. Kept as an explicit refusal, not a mutable bool
    that user metadata can set to bypass missing scientific validation.
    """
    if type(atlas) is not SphericalAtlas:raise GeometryError('SphericalAtlas required')
    raise GeometryError('geological layout acceptance remains open: area fit and closed coverage do not validate boundary morphology or tectonic history')


def plate_outline_cycles(atlas, plate_id, *, budget=None, cancel=None):
    """Return oriented physical boundary rings, excluding working-patch seams.

    A point where one owner has several separate boundary sectors is explicitly
    refused by this ring helper; the full atlas network still represents it.
    This avoids inventing a choice of outgoing edge at a pinched junction.
    """
    _check_cancel(cancel)
    if type(atlas) is not SphericalAtlas or plate_id not in atlas.plate_ids:
        raise GeometryError('known atlas plate required')
    with select_budget(budget).reserve(512*atlas.edge_count+8192,category='plate-outlines'):
        successor={};edges=atlas.edge_vertices;patches=atlas.patches
        for j,(a,b) in enumerate(atlas.side_patches):
            left,right=patches[a].plate_id,patches[b].plate_id
            if left==right or plate_id not in (left,right):continue
            v,w=map(int,edges[j])
            if right==plate_id:v,w=w,v
            if v in successor:raise GeometryError('pinched owner requires network, not a simple boundary ring')
            successor[v]=w
        if len(set(successor.values()))!=len(successor) or set(successor)!=set(successor.values()):
            raise GeometryError('owner outline is not a closed directed cycle set')
        rings=[];remaining=set(successor)
        while remaining:
            _check_cancel(cancel);start=min(remaining);ring=[];node=start
            while node in remaining:
                ring.append(node);remaining.remove(node);node=successor[node]
            if node!=start:raise GeometryError('owner cycle did not close')
            if len(ring)<3:raise GeometryError('degenerate owner ring')
            values=atlas.vertex_directions[ring]
            rings.append(np.frombuffer(values.tobytes(),dtype='f8').reshape(-1,3))
        return tuple(rings)


def evaluate_plate_kinematics(atlas, angular_velocities_rad_s, *, budget=None, cancel=None):
    """Apply SUPPLIED Euler vectors to verified boundaries, never infer forces.

    Velocities are planet-centred forward-time rad/s. Returned opening is
    (right-left).right_normal, tangential is (right-left).tangent. No boundary is
    labelled subduction or assigned polarity from these signs. For each rigid
    plate, the exact great-circle line integral of its own normal velocity over
    its closed outline should be zero: rigid motion cannot change its area.

    A midpoint velocity times segment length is not exact on a curved sphere.
    The sinc(theta/2) correction below analytically integrates a rigid rotation
    over the entire arc and makes this account invariant to arc subdivision.
    """
    from collections.abc import Mapping
    from ._validation import snapshot
    if type(atlas) is not SphericalAtlas or not isinstance(angular_velocities_rad_s,Mapping):
        raise GeometryError('atlas and explicit Euler-vector mapping required')
    _check_cancel(cancel)
    if set(angular_velocities_rad_s)!=set(atlas.plate_ids):
        raise GeometryError('one explicit angular velocity per plate; no missing/extra motion')
    policy=select_budget(budget);_check_cancel(cancel)
    with policy.reserve(2048*atlas.edge_count+8192*len(atlas.plate_ids)+16384,category='plate-kinematics'):
        vectors={}
        for plate,value in sorted(angular_velocities_rad_s.items()):
            if np.shape(value)!=(3,):raise GeometryError('Euler vector must have three components')
            vectors[plate]=snapshot(value,'Euler vector')
        ids=np.array(atlas.interplate_edges,dtype='i8')
        if not len(ids):
            return {'schema':'atlas.prescribed-plate-kinematics.v1','edge_ids':[],
                'values':np.frombuffer(b'',dtype='f8').reshape(0,3),
                'own_area_rate_sr_s':{p:0. for p in atlas.plate_ids},
                'interpretation':'prescribed rigid motion; no geological acceptance'}
        frames=atlas.frames(ids,budget=policy,cancel=cancel)
        left=np.empty((len(ids),3));right=np.empty_like(left)
        sides=atlas.side_patches[ids]
        for i,(a,b) in enumerate(sides):
            left[i]=vectors[atlas.patches[a].plate_id];right[i]=vectors[atlas.patches[b].plate_id]
        with np.errstate(over='ignore',invalid='ignore'):
            lv=np.cross(left,frames.position_m);rv=np.cross(right,frames.position_m)
            relative=rv-lv
            values=np.column_stack((np.sum(relative*frames.right_normal,axis=1),
                                    np.sum(relative*frames.tangent,axis=1),
                                    np.sum(relative*(frames.position_m/atlas.sphere.radius_m),axis=1)))
            theta=frames.length_m/atlas.sphere.radius_m
            # Work in solid-angle/time first, avoiding R**2 overflow.
            mid=frames.position_m/atlas.sphere.radius_m
            factor=2*np.sin(theta/2)
            rates_l=np.sum(np.cross(left,mid)*frames.right_normal,axis=1)*factor
            rates_r=-np.sum(np.cross(right,mid)*frames.right_normal,axis=1)*factor
        if not all(np.isfinite(a).all() for a in (values,rates_l,rates_r)):
            raise GeometryError('kinematic diagnostic exceeds binary64 range')
        accounts={p:[] for p in atlas.plate_ids}
        for i,(a,b) in enumerate(sides):
            accounts[atlas.patches[a].plate_id].append(float(rates_l[i]))
            accounts[atlas.patches[b].plate_id].append(float(rates_r[i]))
        _check_cancel(cancel)
        return {'schema':'atlas.prescribed-plate-kinematics.v1','edge_ids':[atlas.edge_ids[i] for i in ids],
            'columns':['opening_m_s','tangential_m_s','radial_relative_m_s'],
            'values':np.frombuffer(values.tobytes(),dtype='f8').reshape(-1,3),
            'own_area_rate_sr_s':{p:math.fsum(v) for p,v in accounts.items()},
            'angular_velocities_rad_s':{p:v.tolist() for p,v in vectors.items()},
            'interpretation':'prescribed rigid motion; no polarity, force balance or geological acceptance'}


def generate_plate_layout(sphere, settings, *, limits=None, budget=None, cancel=None):
    """Generate a calibrated statistical candidate, not an accepted plate history.

    Uses the existing byte-verified execution context. An implementation change
    during construction prevents publication. The context is temporary and its
    reference/binary limitations are unchanged; no duplicate cache is introduced.
    """
    from .reuse import ExecutionContext
    from pathlib import Path
    _check_cancel(cancel)
    if type(sphere) is not SphericalFrame or type(settings) is not PlateLayoutSettings:
        raise GeometryError('explicit sphere and PlateLayoutSettings required')
    policy=select_budget(budget)
    source_bytes=sum(p.stat().st_size for p in Path(__file__).parent.glob('*.py'))
    with policy.reserve(8*source_bytes+262144,category='plate-layout-identity'):
        with ExecutionContext() as context:
            result=_generate_plate_layout(sphere,settings,limits=limits,budget=policy,
                                         cancel=cancel,execution_id=context.identity)
            _check_cancel(cancel)
            context.verify()
            return result
