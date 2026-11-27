"""W02 prescribed 1D block/plate partitions and transactional topology events.

A partition owns the entire regional interval exactly once. Shared cuts are stored
once, not independently drawn by neighbours. Topology identity and material origin
are separate. These rules do not discover plates or solve driving forces. A line
partition has no 2D triple junctions; those belong to a future geometry backend.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, replace
import hashlib
import json
import math
from typing import Mapping
import numpy as np
from atlas_tectonics._validation import TectonicsError, scalar, input_shape, snapshot
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import _immutable_deepcopy
from atlas_tectonics.integration.resources import check_event
from atlas_tectonics.planet.mesh import ColumnGrid1D
from atlas_tectonics.materials.materials import (MaterialState, _name, _json, _account,
                        restore_material_state)
from atlas_tectonics.regional.regional import _METRICS
from atlas_tectonics.planet.remapping import (_mesh_state, _inventories, RemapPlan, remap_materials, advect_ale)


@dataclass(frozen=True,slots=True)
class PlateRecord:
    plate_id: str
    parent_plate_ids: tuple[str,...]=()
    def __post_init__(self):
        _name(self.plate_id,'plate ID')
        for p in self.parent_plate_ids:
            _name(p,'parent plate')


@dataclass(frozen=True,slots=True)
class BlockRecord:
    block_id: str
    plate_id: str
    parent_block_ids: tuple[str,...]=()
    def __post_init__(self):
        _name(self.block_id,'block ID');_name(self.plate_id,'plate ID')
        for p in self.parent_block_ids:
            _name(p,'parent block')


@dataclass(frozen=True,slots=True)
class BoundaryRecord:
    boundary_id: str
    kind: str='internal'
    active: bool=True
    subducting_side: str | None=None
    def __post_init__(self):
        _name(self.boundary_id,'boundary ID')
        if self.kind not in ('internal','rift','ridge','transform','collision','subduction','fracture'):
            raise TectonicsError('unsupported boundary regime')
        if type(self.active) is not bool:raise TectonicsError('boundary active must be bool')
        if self.kind=='subduction':
            if self.subducting_side not in ('left','right'):raise TectonicsError('subduction polarity must be explicit')
        elif self.subducting_side is not None:raise TectonicsError('only subduction declares a descending side')


@dataclass(frozen=True,slots=True)
class PlateTopology1D:
    """Cut intervals partition the region; list order defines unambiguous sides.

    Retired IDs remain reserved. Plate catalogue entries can remain with no active
    blocks so merging/retirement never erases their identity or permits rebinding.
    """
    cuts: ColumnGrid1D
    plates: tuple[PlateRecord,...]
    blocks: tuple[BlockRecord,...]
    boundaries: tuple[BoundaryRecord,...]
    retired_block_ids: tuple[str,...]=()
    retired_boundary_ids: tuple[str,...]=()
    topology_id: str=field(init=False)
    def __post_init__(self):
        bids=[b.block_id for b in self.blocks];fids=[f.boundary_id for f in self.boundaries]
        parents={p.plate_id:p.parent_plate_ids for p in self.plates}
        for b in self.blocks:
            if b.plate_id not in parents:raise TectonicsError('block references unknown plate')
        for retired,active in ((self.retired_block_ids,bids),(self.retired_boundary_ids,fids)):
            for k in retired:_name(k,'retired ID')
        object.__setattr__(self,'topology_id',hashlib.sha256(_json(self.descriptor())).hexdigest())

    def descriptor(self):
        return {'schema':'atlas.topology1d.v1','cuts':self.cuts.descriptor(),
                'plates':[asdict(p) for p in self.plates], 'blocks':[asdict(b) for b in self.blocks],
                'boundaries':[asdict(f) for f in self.boundaries],
                'retired_block_ids':list(self.retired_block_ids),'retired_boundary_ids':list(self.retired_boundary_ids)}

    def __reduce__(self):return (_restore_topology,(self.descriptor(),self.cuts.edges_m))
    __deepcopy__ = _immutable_deepcopy

    def owner_at(self,positions_m):
        """Half-open ownership [left,right); final endpoint belongs to final block."""
        from atlas_tectonics._validation import snapshot
        x=snapshot(positions_m,'query positions')
        edges=self.cuts.edges_m
        ids=np.minimum(np.searchsorted(edges,x,side='right')-1,len(self.blocks)-1)
        return tuple(self.blocks[int(i)].plate_id for i in ids.flat)


def _restore_topology(desc,edges):
    try:
        mesh=ColumnGrid1D(edges,frame_id=desc['cuts']['frame_id'])
        if mesh.descriptor()!=desc['cuts']:raise TectonicsError('topology cut identity mismatch')
        plates=tuple(PlateRecord(p['plate_id'],tuple(p['parent_plate_ids'])) for p in desc['plates'])
        blocks=tuple(BlockRecord(b['block_id'],b['plate_id'],tuple(b['parent_block_ids'])) for b in desc['blocks'])
        return PlateTopology1D(mesh,plates,blocks,tuple(BoundaryRecord(**f) for f in desc['boundaries']),
                               tuple(desc['retired_block_ids']),tuple(desc['retired_boundary_ids']))
    except (TypeError,KeyError) as exc:raise TectonicsError('invalid topology descriptor') from exc


@dataclass(frozen=True,slots=True,init=False)
class TectonicState1D:
    """Immutable material + current ownership, with one last accepted event receipt.

    A receipt is not an ever-growing per-cell history. Previously used event IDs
    are retained globally to reject replay; complete earlier receipts belong in
    the existing snapshot store. Parent hashes are lineage, not decoder parents.
    """
    material: MaterialState
    topology: PlateTopology1D
    model_id: str
    applied_event_ids: tuple[str,...]
    _receipt: bytes=field(repr=False)
    def __init__(self,material,topology,*,applied_event_ids=(),receipt=None,budget=None):
        _mesh_state(material)
        for e in applied_event_ids:_name(e,'event ID')
        payload=_json(receipt)
        with select_budget(budget).reserve(4*len(payload)+1024*(len(topology.blocks)+len(applied_event_ids))+8192,category='topology-state'):
            if receipt is not None:
                receipt.get('parent_model_id')
            object.__setattr__(self,'material',material);object.__setattr__(self,'topology',topology)
            object.__setattr__(self,'applied_event_ids',applied_event_ids);object.__setattr__(self,'_receipt',payload)
            object.__setattr__(self,'model_id',hashlib.sha256(_json(self.descriptor())).hexdigest())
    @property
    def receipt(self):return json.loads(self._receipt)
    def descriptor(self):
        return {'schema':'atlas.tectonic-state1d.v1','material_id':self.material.state_id,
                'topology_id':self.topology.topology_id,'event_ids':list(self.applied_event_ids),
                'receipt':self.receipt}
    def __reduce__(self):return (_restore_model,(self.material,self.topology,self.applied_event_ids,self.receipt,self.model_id))
    __deepcopy__ = _immutable_deepcopy


def _restore_model(material,topology,event_ids,receipt,expected):
    result=TectonicState1D(material,topology,applied_event_ids=event_ids,receipt=receipt)
    return result


def _begin(world,event_id,expected_parent_id,cancel):
    check_event(cancel, 'regional transport cancelled; no candidate published')
    _name(event_id,'event ID')


def _plates(old, additions):
    values={p.plate_id:p for p in old}
    for p in additions:
        values[p.plate_id]=p
    return tuple(values[k] for k in sorted(values))


def _new_topology(old,edges,blocks,boundaries,*,additions=(),retired_blocks=(),retired_boundaries=(),budget=None):
    return PlateTopology1D(ColumnGrid1D(edges,frame_id=old.cuts.frame_id,budget=budget),
        _plates(old.plates,additions),tuple(blocks),tuple(boundaries),
        tuple(sorted(set(old.retired_block_ids)|set(retired_blocks))),
        tuple(sorted(set(old.retired_boundary_ids)|set(retired_boundaries))))


def _ownership_transfers(material,before,after,*,budget=None):
    """Integrate exact interval ownership intersections, not IDs interpolated on cells.

    Numerical material reconstruction is the same accuracy-first conservative PLM
    used for remapping. A moved ownership cut does NOT itself move or create crust.
    The receipt records the reassignment of the material already at each location.
    """
    union=np.union1d(before.cuts.edges_m,after.cuts.edges_m)
    grid=ColumnGrid1D(union,frame_id=material.grid.frame_id,budget=budget)
    values=remap_materials(material,grid,budget=budget).thickness_m
    old_idx=np.searchsorted(before.cuts.edges_m,grid.centres_m,side='right')-1
    new_idx=np.searchsorted(after.cuts.edges_m,grid.centres_m,side='right')-1
    pieces={};widths=grid.widths_m
    for j in range(grid.cells):
        old=before.blocks[int(old_idx[j])].plate_id;new=after.blocks[int(new_idx[j])].plate_id
        key=(old,new)
        if key not in pieces:pieces[key]=[[] for _ in material.cohorts]
        for k in range(len(material.cohorts)):
            pieces[key][k].append(float(values[k,j])*float(widths[j]))
    transfers=[]
    for (old,new),cohorts in sorted(pieces.items()):
        transfers.append({'from_plate':old,'to_plate':new,
            'volume_m2':[math.fsum(v) for v in cohorts]})
    total=_inventories(material.thickness_m,material.grid)
    for k in range(len(total)):
        _account(float(total[k]),math.fsum(t['volume_m2'][k] for t in transfers),0.,0.,0.)
    return transfers


def _commit_change(world,target,event_id,kind,details,*,budget=None,cancel=None):
    c=len(world.material.cohorts);b=len(world.topology.blocks)+len(target.blocks)
    with select_budget(budget).reserve(512*c*b+128*b+16384,category='topology-event'):
        transfers=_ownership_transfers(world.material,world.topology,target,budget=budget)
        receipt={'operation':kind,'event_id':event_id,'parent_model_id':world.model_id,
            'time_s':world.material.time_s,'old_topology_id':world.topology.topology_id,
            'new_topology_id':target.topology_id,'material_state_id':world.material.state_id,
            'cohort_ids':[c.cohort_id for c in world.material.cohorts],
            'ownership_transfers':transfers,'details':details,
            'meaning':'prescribed ownership/structure event; material payload and formation history unchanged'}
        result=TectonicState1D(world.material,target,applied_event_ids=world.applied_event_ids+(event_id,),receipt=receipt,budget=budget)
        check_event(cancel, 'regional transport cancelled; no candidate published');return result


def split_block(world,block_id,split_m,left_block,right_block,boundary,*,event_id,
                  expected_parent_id,new_plates=(),budget=None,cancel=None):
    _begin(world,event_id,expected_parent_id,cancel);t=world.topology
    ids=[b.block_id for b in t.blocks]
    i=ids.index(block_id);x=scalar(split_m,'split coordinate')
    target=_new_topology(t,np.insert(t.cuts.edges_m,i+1,x),t.blocks[:i]+(left_block,right_block)+t.blocks[i+1:],
        t.boundaries[:i]+(boundary,)+t.boundaries[i:],additions=new_plates,retired_blocks=(block_id,),budget=budget)
    return _commit_change(world,target,event_id,'split-block-v1',{'source':block_id,'children':[left_block.block_id,right_block.block_id]},budget=budget,cancel=cancel)


def merge_blocks(world,block_ids,new_block,*,event_id,expected_parent_id,new_plates=(),budget=None,cancel=None):
    _begin(world,event_id,expected_parent_id,cancel);t=world.topology
    ids=[b.block_id for b in t.blocks]
    if type(block_ids) is not tuple or len(block_ids)<2 or len(set(block_ids))!=len(block_ids) or any(k not in ids for k in block_ids):
        raise TectonicsError('at least two distinct active adjacent blocks required')
    places=[ids.index(k) for k in block_ids];i,j=places[0],places[-1]
    target=_new_topology(t,np.delete(t.cuts.edges_m,np.arange(i+1,j+1)),t.blocks[:i]+(new_block,)+t.blocks[j+1:],
        t.boundaries[:i]+t.boundaries[j:],additions=new_plates,retired_blocks=block_ids,
        retired_boundaries=tuple(f.boundary_id for f in t.boundaries[i:j]),budget=budget)
    return _commit_change(world,target,event_id,'merge-blocks-v1',{'sources':list(block_ids),'child':new_block.block_id},budget=budget,cancel=cancel)


def reassign_blocks(world,assignments: Mapping[str,str],*,event_id,expected_parent_id,new_plates=(),budget=None,cancel=None):
    _begin(world,event_id,expected_parent_id,cancel);t=world.topology
    if not isinstance(assignments,Mapping) or not assignments or not set(assignments)<={b.block_id for b in t.blocks}:raise TectonicsError('explicit active-block membership map required')
    blocks=tuple(replace(b,plate_id=assignments.get(b.block_id,b.plate_id)) for b in t.blocks)
    target=_new_topology(t,t.cuts.edges_m,blocks,t.boundaries,additions=new_plates,budget=budget)
    return _commit_change(world,target,event_id,'plate-membership-v1',dict(assignments),budget=budget,cancel=cancel)


def change_boundary(world,boundary,*,event_id,expected_parent_id,budget=None,cancel=None):
    _begin(world,event_id,expected_parent_id,cancel);t=world.topology
    target=_new_topology(t,t.cuts.edges_m,t.blocks,tuple(boundary if f.boundary_id==boundary.boundary_id else f for f in t.boundaries),budget=budget)
    return _commit_change(world,target,event_id,'boundary-regime-v1',asdict(boundary),budget=budget,cancel=cancel)


def move_partition(world,new_edges_m,*,event_id,expected_parent_id,budget=None,cancel=None):
    """Instantaneous ownership reclassification, NOT displacement of geological mass.

    Physical moving boundaries over time use advance_plate_state and u-w fluxes.
    This event changes a supplied ownership interpretation at a single state time.
    """
    _begin(world,event_id,expected_parent_id,cancel);t=world.topology
    target=_new_topology(t,new_edges_m,t.blocks,t.boundaries,budget=budget)
    return _commit_change(world,target,event_id,'reclassify-ownership-v1',{'old_cuts':t.cuts.grid_id,'new_cuts':target.cuts.grid_id},budget=budget,cancel=cancel)


def _block_outflow_fractions(x,y,relative,dt,ids,scheme,backend,admitted):
    """Largest outgoing Courant fraction among each block's own cells.

    A cell's fraction is dt*leaving/width on its start width and, for MUSCL, on
    its end width too. Each backend's admission is repeated operation for
    operation, so the largest block value must be the admitted whole-domain
    maximum bit for bit, while a quiescent block reports zero, not its
    neighbour's value. A disagreement means this account and the transport
    kernel no longer describe the same admission; the event is refused.
    """
    leaving=np.maximum(relative[1:],0.)+np.maximum(-relative[:-1],0.)
    cells=None
    for edges in (x,y) if scheme=='muscl' else (x,):
        width=np.diff(edges)
        # advance_ale forms (dt/width)*leaving; _ale_reference forms dt*leaving/width.
        fraction=(dt/width)*leaving if backend=='numba' else (dt*leaving)/width
        cells=fraction if cells is None else np.maximum(cells,fraction)
    # Floor at +0, where advance_ale starts: an idle block is never labelled -0.
    fractions=[max(0.,float(v)) for v in np.maximum.reduceat(cells,ids[:-1])]
    return fractions


def advance_plate_state(world,u,w,dt,*,left,right,event_id,expected_parent_id,
                          event_times_s=(),scheme='muscl',backend='numba',budget=None,cancel=None):
    """Advance aligned control volumes and their shared ownership faces together.

    A plate cut must coincide exactly with a mesh face before the interval. Regrid
    explicitly to insert missing cuts. Its flux is then the SAME ALE face flux used
    by adjacent blocks, so block/cohort budgets cannot double-count a transfer.
    Each block account carries that block's own largest outgoing fraction (v2);
    v1 receipts repeated the whole-domain maximum in every block.
    No generated ridge production or slab force is inferred from a boundary label.
    """
    _begin(world,event_id,expected_parent_id,cancel)
    old=world.material;t=world.topology;x=old.grid.edges_m;cuts=t.cuts.edges_m
    ids=np.searchsorted(x,cuts)
    if np.any(ids>=len(x)) or not np.array_equal(x[ids],cuts):raise TectonicsError('plate cuts must align with material faces; remap first')
    c=len(old.cohorts);n=old.grid.cells
    if input_shape(u)!=(n+1,) or input_shape(w)!=(n+1,):raise TectonicsError('N+1 physical and mesh face velocities required')
    # 96 bytes per face: the captured velocities and the outflow-fraction scratch.
    with select_budget(budget).reserve(48*c*n+96*(n+1)+4096*c*len(t.blocks)+16384,category='plate-evolution'):
        # One capture serves the transport kernel and the block accounts alike.
        u=snapshot(u,'physical face velocity');w=snapshot(w,'mesh velocity')
        motion=advect_ale(old,u,w,dt,left=left,right=right,scheme=scheme,backend=backend,
                           event_times_s=event_times_s,budget=budget,cancel=cancel)
        new=motion.state;y=new.grid.edges_m
        target=_new_topology(t,y[ids],t.blocks,t.boundaries,budget=budget)
        from atlas_tectonics.planet._mesh_native import block_inventories
        before_all=block_inventories(old.thickness_m,x,ids)
        after_all=block_inventories(new.thickness_m,y,ids)
        fractions=_block_outflow_fractions(x,y,u-w,float(dt),ids,scheme,backend,float(motion.accounts[0,5]))
        accounts=[]
        for b in range(len(t.blocks)):
            start,end=int(ids[b]),int(ids[b+1]);rows=[]
            for k in range(c):
                before=float(before_all[b,k]);after=float(after_all[b,k])
                rows.append(dict(zip(_METRICS,_account(before,after,float(dt)*motion.face_flux_m2_s[k,start],
                    -float(dt)*motion.face_flux_m2_s[k,end],fractions[b]))))
            accounts.append({'block_id':t.blocks[b].block_id,'plate_id':t.blocks[b].plate_id,'cohorts':rows})
        receipt={'operation':'advance-plate-control-volumes-v2','event_id':event_id,'parent_model_id':world.model_id,
            'time_s':new.time_s,'duration_s':float(dt),'old_topology_id':t.topology_id,'new_topology_id':target.topology_id,
            'material_transition_id':new.transition_id,'block_accounts':accounts,'scheme':scheme,'backend':backend}
        result=TectonicState1D(new,target,applied_event_ids=world.applied_event_ids+(event_id,),receipt=receipt,budget=budget)
        check_event(cancel, 'regional transport cancelled; no candidate published');return result


def regrid_plate_state(world,target_mesh,*,event_id,expected_parent_id,plan=None,budget=None,cancel=None):
    """Change the computational mesh without moving a single ownership boundary."""
    _begin(world,event_id,expected_parent_id,cancel)
    material=remap_materials(world.material,target_mesh,plan=plan,budget=budget,cancel=cancel)
    receipt={'operation':'regrid-plate-state-v1','event_id':event_id,'parent_model_id':world.model_id,
             'time_s':material.time_s,'material_transition':material.transition_id,
             'topology_id':world.topology.topology_id}
    return TectonicState1D(material,world.topology,applied_event_ids=world.applied_event_ids+(event_id,),receipt=receipt,budget=budget)


def save_tectonic_state(world,store,*,budget=None,cancel=None):
    """Existing chunk store; edges and fields are arrays, never duplicated JSON grids."""
    meta={'model':world.descriptor(),'material':world.material.descriptor(),'topology':world.topology.descriptor()}
    return store.put(world.model_id,{'partial_thickness_m':world.material.thickness_m,
        'material_edges_m':world.material.grid.edges_m,'topology_edges_m':world.topology.cuts.edges_m},
        meta,budget=budget,cancel=cancel)


def load_tectonic_state(store,model_id,*,budget=None):
    data=store.get(model_id,budget=budget)
    if data is None:return None
    meta=store.metadata(model_id)
    if (set(data)!={'partial_thickness_m','material_edges_m','topology_edges_m'} or
            type(meta) is not dict or set(meta)!={'model','material','topology'}):raise TectonicsError('invalid model snapshot inventory')
    try:
        desc=meta['model']
        if set(desc)!={'schema','material_id','topology_id','event_ids','receipt'} or desc['schema']!='atlas.tectonic-state1d.v1':raise TectonicsError('invalid model schema')
        material=restore_material_state(meta['material'],data['partial_thickness_m'],desc['material_id'],
                                        edges_m=data['material_edges_m'],budget=budget)
        topology=_restore_topology(meta['topology'],data['topology_edges_m'])
        if topology.topology_id!=desc['topology_id']:raise TectonicsError('restored topology mismatch')
        result=TectonicState1D(material,topology,applied_event_ids=tuple(desc['event_ids']),receipt=desc['receipt'],budget=budget)
        if result.model_id!=model_id:raise TectonicsError('model snapshot identity mismatch')
        return result
    except (KeyError,TypeError) as exc:raise TectonicsError('malformed model snapshot') from exc


def apply_plate_material_event(world,event,amount,*,expected_parent_id,budget=None,cancel=None):
    """Prescribed birth/add/remove affects material, never silently alters ownership.

    The existing event validation ties transfer to the exact material parent and
    named reservoir. This wrapper also binds the containing topology/model parent.
    """
    from atlas_tectonics.materials.materials import apply_material_event
    _begin(world,event.event_id,expected_parent_id,cancel)
    transferred=apply_material_event(world.material,event,amount,budget=budget,cancel=cancel)
    receipt={'operation':'plate-material-transfer-v1','event_id':event.event_id,
             'parent_model_id':world.model_id,'time_s':world.material.time_s,
             'material_transition_id':transferred.state.transition_id,
             'transfer':transferred.state.transition_record,'topology_id':world.topology.topology_id}
    return TectonicState1D(transferred.state,world.topology,
            applied_event_ids=world.applied_event_ids+(event.event_id,),receipt=receipt,budget=budget)
