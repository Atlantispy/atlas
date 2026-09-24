"""Bounded exact-ID coalescing of support seams before native boundary fairing.

WORKING NON-CANON. This changes working patches only: surviving directions and
physical boundary edge IDs are never approximated or reconstructed by overlay.
The caller owns the returned buffers, their retained budget and the final native
atlas build/source admission. Failed local merges retain the preceding patches.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import math

import numpy as np

from atlas_tectonics.geometry import GeometryError, _check_cancel
from atlas_tectonics.resources import select_budget
from atlas_tectonics.spherical_atlas import SphericalAtlas, SphericalPatch
from atlas_tectonics.spherical_geometry import SphericalChart


_CAP_COSINE = math.cos(math.radians(75.0))
_METHOD = 'exact-id-single-ring-75deg-coalescing-v1'


def _single_cycle(edges):
    """Return one oriented ID cycle; refuse holes, pinches and separate outers."""
    successor = {}
    incoming = set()
    for a, b in edges:
        if a in successor or b in incoming:
            return None
        successor[a] = b
        incoming.add(b)
    if len(successor) < 3 or set(successor) != incoming:
        return None
    start = min(successor)
    ring = []
    seen = set()
    node = start
    while node not in seen:
        seen.add(node)
        ring.append(node)
        node = successor[node]
    if node != start or len(ring) != len(successor):
        return None
    return tuple(ring)


def coalesce(support, labels, *, budget, cancel):
    """Merge at most once per original edge, preserving exact shared boundaries.

    Only identical final ownership merges. Every original vertex of an admitted
    group lies within 75 degrees of its area-weighted original chart centres.
    Groups producing holes or pinched rings retain seams. Failed geometric
    proposals are local refusals, never automatic repair or tolerance changes.
    """
    _check_cancel(cancel)
    if type(support) is not SphericalAtlas:
        raise GeometryError('coalescing requires a validated SphericalAtlas')
    policy = select_budget(budget)
    count = len(support.patches)
    # Account existing-support references, dictionaries/sets, one tentative union,
    # ID strings and returned buffers before constructing them. Native polygon
    # validation makes its own nested reservations in the same budget.
    halfedges = sum(len(ring) for p in support.patches for ring in p.rings)
    label_bytes = sum(len(p.patch_id.encode('utf-8')) for p in support.patches)
    label_bytes += sum(len(v.encode('utf-8')) for v in support.vertex_ids)
    work_bound = (support.retained_bytes_estimate + 3072 * halfedges
                  + 4096 * count + 1024 * support.vertex_count
                  + 8 * label_bytes + 262144)
    with policy.reserve(work_bound, category='new-boundary-coalesce'):
        assigned = np.asarray(labels)
        if (assigned.shape != (count,) or assigned.dtype.kind not in 'iu'
                or np.any(assigned < 0) or np.any(assigned >= 52)):
            raise GeometryError('one nonnegative integer ownership label per support patch required')
        # Existing registry rows remain byte-identical. Integer indices are only
        # internal keys; no geometric matching or coordinate welding occurs.
        points = support.vertex_directions
        ids = support.vertex_ids
        lookup = {name: i for i, name in enumerate(ids)}
        weighted = np.array([float(area) * np.asarray(p.chart.centre)
                             for p, area in zip(support.patches, support.patch_areas_sr)])
        groups = {}
        parent = list(range(count))
        for i, patch in enumerate(support.patches):
            rings = [tuple(lookup[v] for v in ring) for ring in patch.rings]
            edges = {(a, b) for ring in rings
                     for a, b in zip(ring, ring[1:] + ring[:1])}
            groups[i] = dict(members=(i,), vertices=set(v for ring in rings for v in ring),
                             edges=edges, patch=patch)

        def root(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        attempts = 0
        accepted = 0
        refusals = dict(cap=0, non_simple_cycle=0)
        # Native edge order is canonical global-ID order. Each original edge is
        # visited once, and rejected pairs are not placed in a retry queue.
        for left, right in support.side_patches:
            _check_cancel(cancel)
            a, b = root(int(left)), root(int(right))
            if a == b or assigned[a] != assigned[b]:
                continue
            attempts += 1
            if b < a:
                a, b = b, a
            first, second = groups[a], groups[b]
            members = tuple(sorted(first['members'] + second['members']))
            centre = np.array([math.fsum(float(weighted[i, axis]) for i in members)
                               for axis in range(3)])
            norm = float(np.linalg.norm(centre))
            original_vertices = first['vertices'] | second['vertices']
            if not math.isfinite(norm) or norm == 0:
                refusals['cap'] += 1
                continue
            centre /= norm
            if np.any(points[sorted(original_vertices)] @ centre < _CAP_COSINE):
                refusals['cap'] += 1
                continue
            edges = first['edges'].copy()
            for u, v in second['edges']:
                if (v, u) in edges:
                    edges.remove((v, u))
                elif (u, v) in edges:
                    raise GeometryError('same-side edge encountered in validated support merge')
                else:
                    edges.add((u, v))
            ring = _single_cycle(edges)
            if ring is None:
                refusals['non_simple_cycle'] += 1
                continue
            owner = f'plate-{int(assigned[a]):06d}'
            # Membership, not mutable coordinates, identifies a working patch.
            membership = '\0'.join(support.patches[i].patch_id for i in members).encode('utf-8')
            patch_id = 'coalesced-' + hashlib.sha256(membership).hexdigest()
            candidate = SphericalPatch(patch_id, owner, owner,
                tuple(ids[i] for i in ring),
                SphericalChart(support.sphere, tuple(centre), _CAP_COSINE))
            # Exact cancellation is the union of already validated same-side
            # faces. With one simple ID cycle and a common hemisphere, its
            # existing edges cannot acquire a crossing or reverse orientation.
            # Do not rebuild a native spatial index for every growing union;
            # fairing checks all final local polygons, and the caller must run
            # the complete native atlas builder before publishing anything.
            parent[b] = a
            groups[a] = dict(members=members, vertices=original_vertices,
                             edges=edges, patch=candidate)
            del groups[b]
            accepted += 1

        patches = []
        for index in sorted(groups):
            _check_cancel(cancel)
            group = groups[index]
            owner = f'plate-{int(assigned[index]):06d}'
            patch = group['patch']
            if len(group['members']) == 1:
                patch = replace(patch, region_id=owner, plate_id=owner)
            patches.append(patch)
        patches = tuple(sorted(patches, key=lambda patch: patch.patch_id))
        used = {v for patch in patches for ring in patch.rings for v in ring}
        vertices = {name: points[lookup[name]] for name in sorted(used)}
        record = dict(method=_METHOD, cap_degrees=75.0,
            original_patches=count, coalesced_patches=len(patches),
            original_vertices=support.vertex_count, retained_vertices=len(vertices),
            merge_attempts=attempts, maximum_merge_attempts=support.edge_count,
            accepted_merges=accepted, refused_merges=refusals,
            work_reservation_bytes=work_bound,
            physical_boundary='exact original shared IDs and directions',
            holes_and_pinches='retain working seams')
        return vertices, patches, record


import math
import numpy as np
import shapely
from shapely.geometry import Polygon
from atlas_tectonics.geometry import GeometryError, _check_cancel


def fair(vertices, patches, *, budget, cancel=None):
    """Regularise native boundaries, jointly restore all plate areas, never evolve."""
    passes=16
    names=tuple(sorted(vertices)); lookup={name:i for i,name in enumerate(names)}
    n=len(names); owners=tuple(sorted({p.plate_id for p in patches})); m=len(owners)
    halfedges=sum(len(p.vertex_ids) for p in patches)
    work=8*(24*m*n+64*n+64*halfedges+16*m*m)+262144
    with budget.reserve(work,category='new-boundary-fair'):
        x=np.array([vertices[k] for k in names]); original=x.copy()
        rings=[]; incidence={}; first=[];second=[];centre=[];owner=[]
        for p in patches:
            if p.holes:raise GeometryError('boundary fairing requires explicit unholed working patches')
            ring=np.array([lookup[k] for k in p.vertex_ids]);rings.append(ring)
            for i,j in zip(ring,np.roll(ring,-1)):
                incidence.setdefault(tuple(sorted((int(i),int(j)))),[]).append(p.plate_id)
                first.append(i);second.append(j);centre.append(p.chart.centre);owner.append(owners.index(p.plate_id))
        ii,jj,cc,oo=np.array(first),np.array(second),np.array(centre),np.array(owner)
        neighbors=[[] for _ in names];boundary=[[] for _ in names]
        for (i,j),pair in incidence.items():
            if len(pair)!=2:raise GeometryError('unpaired shared edge before fairing')
            neighbors[i].append(j);neighbors[j].append(i)
            if pair[0]!=pair[1]:boundary[i].append(j);boundary[j].append(i)
        # Fixed true tectonic junctions and remaining working-patch junctions.
        movable=np.array([i for i in range(n) if len(boundary[i])==2 and len(neighbors[i])==2],dtype=int)
        fixed=np.ones(n,dtype=bool);fixed[movable]=False
        pinned=original.copy()
        bn=np.array([boundary[i] for i in movable],dtype=int).reshape(-1,2)
        def areas_gradient(z,gradient=True):
            u,v=z[ii],z[jj]
            num=np.einsum('ij,ij->i',cc,np.cross(u,v))
            den=1+np.einsum('ij,ij->i',cc,u+v)+np.einsum('ij,ij->i',u,v)
            ar=np.bincount(oo,weights=2*np.arctan2(num,den),minlength=m)
            if not gradient:return ar
            sq=(den*den+num*num)[:,None]
            gu=2*(den[:,None]*np.cross(v,cc)-num[:,None]*(cc+v))/sq
            gv=2*(den[:,None]*np.cross(cc,u)-num[:,None]*(cc+u))/sq
            G=np.zeros((m,n,3));np.add.at(G,(oo,ii),gu);np.add.at(G,(oo,jj),gv)
            G-=np.einsum('pij,ij->pi',G,z)[:,:,None]*z[None,:,:];G[:,fixed]=0
            return ar,G.reshape(m,-1)
        targets=areas_gradient(x,False)
        edges=np.array(tuple(incidence),dtype=int)
        if len(movable):
            lengths=np.arccos(np.clip(np.einsum('ik,ijk->ij',original[movable],original[bn]),-1,1))
            max_shift=lengths.mean(axis=1)
        else:max_shift=np.empty(0)
        def valid(z):
            if not np.isfinite(z).all():return False
            angles=2*np.arctan2(np.linalg.norm(z[edges[:,0]]-z[edges[:,1]],axis=1),np.linalg.norm(z[edges[:,0]]+z[edges[:,1]],axis=1))
            if np.any(angles<=1e-8) or np.any(angles>=math.pi-1e-8):return False
            if len(movable):
                moved=2*np.arctan2(np.linalg.norm(z[movable]-original[movable],axis=1),np.linalg.norm(z[movable]+original[movable],axis=1))
                if np.any(moved>max_shift):return False
            for p,ring in zip(patches,rings):
                local=z[ring]@p.chart.basis.T
                if np.any(local[:,2]<p.chart.min_cosine):return False
                polygon=Polygon(local[:,:2]/local[:,2,None])
                if not polygon.is_valid or polygon.area<=0 or not shapely.is_ccw(polygon.exterior):return False
            return True
        if not valid(x):raise GeometryError('invalid initial working faces for fairing')
        def project(z,d):
            ar,G=areas_gradient(z)
            rhs=G@d.reshape(-1)+(ar-targets)
            multiplier=np.linalg.lstsq(G@G.T,rhs,rcond=1e-12)[0]
            out=d-(G.T@multiplier).reshape(n,3);out[fixed]=0
            return out
        backtracks=[]
        for step in range(passes):
            _check_cancel(cancel)
            moved=2*np.arctan2(np.linalg.norm(x[movable]-original[movable],axis=1),np.linalg.norm(x[movable]+original[movable],axis=1))
            reached=movable[moved>=.99*max_shift]
            fixed[reached]=True;pinned[reached]=x[reached]
            d=np.zeros_like(x)
            d[movable]=.35*(x[bn].mean(axis=1)-x[movable])
            d-=np.einsum('ij,ij->i',x,d)[:,None]*x
            d=project(x,d)
            for back in range(16):
                _check_cancel(cancel)
                z=x+2.**-back*d;z/=np.linalg.norm(z,axis=1)[:,None];z[fixed]=pinned[fixed]
                if valid(z) and np.max(abs(areas_gradient(z,False)-targets)/targets)<.01:break
            else:raise GeometryError('No safe bounded boundary-fairing step.')
            x=z;backtracks.append(back)
        for correction in range(12):
            _check_cancel(cancel)
            residual=max(abs(areas_gradient(x,False)-targets))
            if residual<1e-12:break
            d=project(x,np.zeros_like(x))
            for back in range(16):
                z=x+2.**-back*d;z/=np.linalg.norm(z,axis=1)[:,None];z[fixed]=pinned[fixed]
                if valid(z) and max(abs(areas_gradient(z,False)-targets))<residual:break
            else:raise GeometryError('no safe area restoration after fairing')
            x=z
        residual=float(max(abs(areas_gradient(x,False)-targets)))
        if residual>=1e-12:raise GeometryError('boundary fairing failed to restore original plate areas')
        def turning(z):
            if not len(movable):return dict(mean_degrees=0.,rms_degrees=0.)
            u=z[bn[:,0]]-np.einsum('ij,ij->i',z[bn[:,0]],z[movable])[:,None]*z[movable]
            v=z[bn[:,1]]-np.einsum('ij,ij->i',z[bn[:,1]],z[movable])[:,None]*z[movable]
            u/=np.linalg.norm(u,axis=1)[:,None];v/=np.linalg.norm(v,axis=1)[:,None]
            angles=np.arccos(np.clip(-np.einsum('ij,ij->i',u,v),-1,1))
            return dict(mean_degrees=float(np.degrees(angles.mean())),rms_degrees=float(np.degrees(np.sqrt(np.mean(angles*angles)))))
        displacement=2*np.arctan2(np.linalg.norm(x-original,axis=1),np.linalg.norm(x+original,axis=1))
        return dict(zip(names,x)),dict(method='coupled-area-constrained-spherical-fairing-v1',passes=passes,
            damping=.35,maximum_shift='one original mean incident boundary edge length',
            area_restoration_tolerance_sr=1e-12,maximum_plate_area_drift_sr=residual,
            maximum_displacement_rad=float(displacement.max()),movable_vertices=len(movable),
            fixed_vertices=int(fixed.sum()),backtracking_halvings=backtracks,
            before=turning(original),after=turning(x),work_reservation_bytes=work)

# Source-only successor: no native package or historical checkpoint is changed.
from pathlib import Path
_SOURCE = Path(__file__).resolve()
_LOADED_HASH = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()


def source_hash():
    from new_world_contract import ContractError
    value = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()
    if value != _LOADED_HASH:
        raise ContractError('SOURCE_MISMATCH', 'Boundary adapter changed while loaded.')
    return value

