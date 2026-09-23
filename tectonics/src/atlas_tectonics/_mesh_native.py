"""Strict compiled overlap integration and moving-control-volume transport.

No fast math, unreviewed reduction order, parallel shared writes, or JIT disk
cache. A remap changes representation at one time. ALE evolves the conservative
quantity Q=H*cell_width with flux (u-w)*H, and the same moving face geometry.
"""
import math
import numpy as np
from numba import njit
from ._transport_native import positive_sum, _add_bits, _rounded_sum


@njit(inline='always',fastmath=False,cache=False)
def slope_at(h,x,i):
    n=h.size
    if n==1:return 0.0
    wi=x[i+1]-x[i]
    # Form local widths before adding: mixing a width with an absolute edge
    # loses low bits at large origins (notably across binary exponent changes).
    if i==0:
        s=(h[1]-h[0])/(0.5*wi+0.5*(x[2]-x[1]))
    elif i==n-1:
        s=(h[i]-h[i-1])/(0.5*wi+0.5*(x[i]-x[i-1]))
    else:
        dl=0.5*wi+0.5*(x[i]-x[i-1]);dr=0.5*wi+0.5*(x[i+2]-x[i+1])
        a=(h[i]-h[i-1])/dl;b=(h[i+1]-h[i])/dr
        if not ((a>0 and b>0) or (a<0 and b<0)):return 0.0
        # Weighted centred derivative on unequal cells, then MC limiting.
        c=(a*dr+b*dl)/(dl+dr)
        s=math.copysign(min(abs(c),2*abs(a),2*abs(b)),a)
        span=min(abs(h[i]-h[i-1]),abs(h[i+1]-h[i]))
        s=math.copysign(min(abs(s),2*(span/wi)),s)
    # Preserve the cell mean while limiting reconstructed endpoint heights.
    # nextafter protects the nonnegative reconstruction from a rounded overshoot.
    cap=2*(h[i]/wi)
    if abs(s)>=cap and cap>0:cap=np.nextafter(cap,0.0)
    s=math.copysign(min(abs(s),cap),s)
    if not math.isfinite(s):raise ValueError('reconstruction slope outside numerical range')
    return s


@njit(nogil=True,fastmath=False,cache=False)
def overlap_geometry(source,target):
    """Sorted-mesh sweep: at most Ns+Nt-1 overlaps, never a dense remap matrix."""
    ns=source.size-1;nt=target.size-1
    starts=np.empty(nt+1,np.int64);donors=np.empty(ns+nt,np.int64)
    lengths=np.empty(ns+nt);offsets=np.empty(ns+nt)
    k=0;i=0
    for j in range(nt):
        starts[j]=k
        while i+1<ns and source[i+1]<=target[j]:i+=1
        q=i
        while q<ns and source[q]<target[j+1]:
            a=max(source[q],target[j]);b=min(source[q+1],target[j+1])
            if b>a:
                donors[k]=q;lengths[k]=b-a
                # Use local offsets to avoid subtracting huge absolute centroids.
                offsets[k]=(a-source[q])+0.5*(b-a)-0.5*(source[q+1]-source[q])
                k+=1
            if source[q+1]>=target[j+1]:break
            q+=1
        i=q
    starts[nt]=k
    return starts,donors[:k],lengths[:k],offsets[:k]


@njit(nogil=True,fastmath=False,cache=False)
def remap_rows(h,x,y,ptr,donors,lengths,offsets,linear):
    c,ns=h.shape;nt=y.size-1
    result=np.empty((c,nt));s=np.empty(ns);bits=np.empty(1,dtype=np.float64)
    limbs=np.zeros(34,np.uint64)
    for k in range(c):
        for i in range(ns):s[i]=slope_at(h[k],x,i) if linear else 0.0
        for j in range(nt):
            limbs[:]=0
            for q in range(ptr[j],ptr[j+1]):
                i=donors[q]
                part=lengths[q]*(h[k,i]+s[i]*offsets[q])
                if not math.isfinite(part) or part<0:raise ValueError('invalid reconstructed overlap inventory')
                bits[0]=part;_add_bits(limbs,bits.view(np.uint64)[0])
            value=_rounded_sum(limbs)/(y[j+1]-y[j])
            if not math.isfinite(value) or value<0:raise ValueError('remapped thickness outside range')
            result[k,j]=value
    return result


@njit(nogil=True,fastmath=False,cache=False)
def inventories(h,x):
    c,n=h.shape;out=np.empty(c);terms=np.empty(n)
    for k in range(c):
        for i in range(n):
            terms[i]=h[k,i]*(x[i+1]-x[i])
            if not math.isfinite(terms[i]) or terms[i]<0:raise ValueError('inventory outside range')
        out[k]=positive_sum(terms)
    return out


@njit(fastmath=False,cache=False)
def _flux(h,x,relative,external_l,external_r,linear,flux):
    n=h.size
    for j in range(n+1):
        a=relative[j]
        if j==0:
            donor=external_l if a>0 else h[0]-0.5*(x[1]-x[0])*(slope_at(h,x,0) if linear else 0.)
        elif j==n:
            donor=h[n-1]+0.5*(x[n]-x[n-1])*(slope_at(h,x,n-1) if linear else 0.) if a>=0 else external_r
        else:
            i=j-1 if a>=0 else j
            offset=0.5*(x[i+1]-x[i])*(1 if a>=0 else -1)
            donor=h[i]+(slope_at(h,x,i) if linear else 0.)*offset
        value=a*donor
        if not math.isfinite(value) or donor<0:raise ValueError('invalid ALE reconstructed flux')
        flux[j]=value


@njit(nogil=True,fastmath=False,cache=False)
def advance_ale(h,x,y,relative,dt,el,er,linear):
    """SSP-RK2 in cell inventories, with geometric widths advanced consistently.

    x and y are start/end edges of a linearly moving mesh. Q1 lives on y, and
    the second Euler stage uses H1=Q1/width(y). Averaging Q, not H, enforces GCL.
    """
    c,n=h.shape;maximum=0.0;cap=0.5 if linear else 1.0
    for i in range(n):
        w0=x[i+1]-x[i];w1=y[i+1]-y[i]
        if w0<=0 or w1<=0:raise ValueError('crossed mesh faces')
        leaving=max(relative[i+1],0.)+max(-relative[i],0.)
        for width in (w0,w1 if linear else w0):
            f=(dt/width)*leaving
            if not math.isfinite(f) or f>cap:raise ValueError('moving-grid outgoing Courant limit exceeded')
            maximum=max(maximum,f)
    out=np.empty((c,n));mean=np.empty((c,n+1));stage=np.empty(n)
    f1=np.empty(n+1)
    for k in range(c):
        _flux(h[k],x,relative,el[k],er[k],linear,mean[k])
        for i in range(n):
            q=h[k,i]*(x[i+1]-x[i])+dt*(mean[k,i]-mean[k,i+1])
            stage[i]=q/(y[i+1]-y[i])
            if not math.isfinite(stage[i]) or stage[i]<0:raise ValueError('negative/out-of-range ALE stage; no clipping')
        if linear and dt!=0:
            _flux(stage,y,relative,el[k],er[k],linear,f1)
            for i in range(n):
                q0=h[k,i]*(x[i+1]-x[i]);q1=stage[i]*(y[i+1]-y[i])
                q2=q1+dt*(f1[i]-f1[i+1])
                if not math.isfinite(q2) or q2<0:raise ValueError('negative/out-of-range ALE Euler stage')
                # Convex combination of extensive states, not densities on different cells.
                out[k,i]=(0.5*q0+0.5*q2)/(y[i+1]-y[i])
            for j in range(n+1):mean[k,j]=0.5*mean[k,j]+0.5*f1[j]
        else:
            out[k,:]=stage
        for i in range(n):
            if not math.isfinite(out[k,i]) or out[k,i]<0:raise ValueError('invalid ALE candidate')
    return out,mean,maximum


@njit(nogil=True,fastmath=False,cache=False)
def block_inventories(h,x,cut_indices):
    """Batched accurate inventory reductions; no Python loop over all material cells."""
    c,n=h.shape;b=cut_indices.size-1
    out=np.empty((b,c));terms=np.empty(n)
    for block in range(b):
        start=cut_indices[block];end=cut_indices[block+1]
        for k in range(c):
            for i in range(start,end):terms[i-start]=h[k,i]*(x[i+1]-x[i])
            out[block,k]=positive_sum(terms[:end-start])
    return out


@njit(nogil=True,fastmath=False,cache=False)
def mapped_points(positions,source,target):
    """Piecewise-affine material motion, O(P log N), not arbitrary ALE tracer advection."""
    out=np.empty(positions.size);stretch=np.empty(positions.size)
    n=source.size-1
    for k in range(positions.size):
        p=positions[k]
        i=min(np.searchsorted(source,p,side='right')-1,n-1)
        if i<0 or p>source[-1]:raise ValueError('material marker outside mapping')
        dx=source[i+1]-source[i];dy=target[i+1]-target[i]
        if p==source[i]:out[k]=target[i]
        elif p==source[i+1]:out[k]=target[i+1]
        else:out[k]=target[i]+((p-source[i])/dx)*dy
        stretch[k]=dy/dx
        if not math.isfinite(out[k]) or not math.isfinite(stretch[k]) or stretch[k]<=0:raise ValueError('marker map outside numerical range')
    return out,stretch
