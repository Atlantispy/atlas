"""W02 coordinate geometry: nonuniform 1D columns, not plate/material identity.

Edges are positions in metres in an explicit fixed Cartesian reference frame.
Mesh motion is supplied separately from physical material velocity. All arrays
are immutable bytes-backed descriptors; changing a view cannot move this mesh.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import numpy as np
from ._validation import TectonicsError, input_shape, snapshot
from .resources import select_budget


@dataclass(frozen=True, slots=True, init=False)
class ColumnGrid1D:
    frame_id: str
    grid_id: str
    _edges: bytes = field(repr=False)

    def __init__(self, edges_m, *, frame_id: str, budget=None):
        if type(frame_id) is not str or not frame_id.strip() or len(frame_id)>256:
            raise TectonicsError('explicit nonblank coordinate frame required')
        shape=input_shape(edges_m, 'mesh edges')
        if len(shape)!=1 or shape[0]<2:
            raise TectonicsError('at least two one-dimensional mesh edges required')
        with select_budget(budget).reserve(48*shape[0]+4096, category='column-geometry'):
            edges=snapshot(edges_m, 'mesh edges')
            with np.errstate(over='ignore',invalid='ignore'):
                widths=np.diff(edges)
                centres=edges[:-1]+0.5*widths
            if (np.any(~np.isfinite(widths)) or np.any(widths<=0) or
                    np.any(~np.isfinite(centres)) or np.any(centres<=edges[:-1]) or
                    np.any(centres>=edges[1:])):
                raise TectonicsError('mesh must have finite positive, numerically resolvable cells; no crossings')
            owner=edges
            while type(owner) is np.ndarray:owner=owner.base
            if type(owner) is not bytes or len(owner)!=edges.nbytes:
                raise TectonicsError('mesh snapshot needs compact immutable backing')
            payload=owner
            h=hashlib.sha256(json.dumps({'schema':'atlas.column-grid.v1','frame':frame_id,
                         'cells':shape[0]-1,'dtype':np.dtype('float64').str},sort_keys=True).encode())
            h.update(payload)
            object.__setattr__(self,'frame_id',frame_id)
            object.__setattr__(self,'_edges',payload)
            object.__setattr__(self,'grid_id',h.hexdigest())

    @property
    def cells(self): return len(self._edges)//8-1
    @property
    def edges_m(self): return np.frombuffer(self._edges,dtype=np.float64)
    @property
    def widths_m(self): return np.diff(self.edges_m)
    @property
    def centres_m(self):
        e=self.edges_m
        return e[:-1]+0.5*np.diff(e)
    @property
    def nbytes(self): return len(self._edges)
    def descriptor(self):
        return {'kind':'column-grid-v1','frame_id':self.frame_id,'cells':self.cells,'grid_id':self.grid_id}
    def __reduce__(self): return (_restore_grid,(self.edges_m,self.frame_id,self.grid_id))
    def __deepcopy__(self,memo):
        memo[id(self)]=self
        return self


def _restore_grid(edges,frame,expected):
    result=ColumnGrid1D(edges,frame_id=frame)
    if result.grid_id!=expected: raise TectonicsError('mesh identity mismatch')
    return result
