"""W02 coordinate geometry: nonuniform 1D columns, not plate/material identity.

Edges are positions in metres in an explicit fixed Cartesian reference frame.
Mesh motion is supplied separately from physical material velocity. All arrays
are immutable bytes-backed descriptors; changing a view cannot move this mesh.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
from typing import cast
import numpy as np
from atlas_tectonics._validation import input_shape, snapshot
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import _immutable_deepcopy


@dataclass(frozen=True, slots=True, init=False)
class ColumnGrid1D:
    frame_id: str
    grid_id: str
    _edges: bytes = field(repr=False)

    def __init__(self, edges_m, *, frame_id: str, budget=None):
        shape=input_shape(edges_m, 'mesh edges')
        with select_budget(budget).reserve(48*shape[0]+4096, category='column-geometry'):
            edges=snapshot(edges_m, 'mesh edges')
            with np.errstate(over='ignore',invalid='ignore'):
                pass
            owner=edges
            while type(owner) is np.ndarray:owner=owner.base
            payload=cast(bytes, owner)
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
    __deepcopy__ = _immutable_deepcopy


def _restore_grid(edges,frame,expected):
    result=ColumnGrid1D(edges,frame_id=frame)
    return result
