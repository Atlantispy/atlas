"""Spherical metric kernels: exact minor-arc geometry in binary64, no fast-math.

A projected polygon supplies topology only. These routines measure angular
separation on the sphere; projected straight-line distance is never substituted.
Each query keeps scalar scratch, not a points-by-edges distance matrix.
"""
import math
import numpy as np
from numba import njit


@njit(inline='always', fastmath=False, cache=False)
def _angle(ax, ay, az, bx, by, bz):
    # The half-angle form preserves both tiny and almost antipodal separations.
    minus = math.sqrt((ax-bx)**2+(ay-by)**2+(az-bz)**2)
    plus = math.sqrt((ax+bx)**2+(ay+by)**2+(az+bz)**2)
    return 2*math.atan2(minus, plus)


@njit(nogil=True, fastmath=False, cache=False)
def arc_distances(points, starts, ends):
    """Minimum distance to a nonempty collection of points/minor arcs, in radians.

    A degenerate start==end explicitly represents a point from an intersection.
    Closest projection is accepted only when it lies on the finite minor arc;
    otherwise an endpoint is nearest. No infinite-great-circle shortcut is used.
    """
    out=np.empty(len(points),dtype=np.float64)
    for i in range(len(points)):
        px,py,pz=points[i,0],points[i,1],points[i,2]
        best=math.pi
        for j in range(len(starts)):
            ax,ay,az=starts[j,0],starts[j,1],starts[j,2]
            bx,by,bz=ends[j,0],ends[j,1],ends[j,2]
            d=min(_angle(px,py,pz,ax,ay,az),_angle(px,py,pz,bx,by,bz))
            # (a+b) x (b-a) == 2*(a x b), but unlike subtracting nearly
            # equal products it retains the short-edge direction. This is the
            # stable-cross construction used by S2; no tolerance widens the arc.
            sx,sy,sz=ax+bx,ay+by,az+bz
            dx,dy,dz=bx-ax,by-ay,bz-az
            nx,ny,nz=sy*dz-sz*dy,sz*dx-sx*dz,sx*dy-sy*dx
            scale=max(abs(nx),abs(ny),abs(nz))
            if scale>0:
                # Scale before taking a norm so squaring a short normal does
                # not underflow. start==end still uses the point/endpoint path.
                nx,ny,nz=nx/scale,ny/scale,nz/scale
                norm=math.sqrt(nx*nx+ny*ny+nz*nz)
                nx,ny,nz=nx/norm,ny/norm,nz/norm
                h=px*nx+py*ny+pz*nz
                qx,qy,qz=px-h*nx,py-h*ny,pz-h*nz
                qnorm=math.sqrt(qx*qx+qy*qy+qz*qz)
                if qnorm>0:
                    qx,qy,qz=qx/qnorm,qy/qnorm,qz/qnorm
                    tx,ty,tz=ny*az-nz*ay,nz*ax-nx*az,nx*ay-ny*ax
                    along=math.atan2(qx*tx+qy*ty+qz*tz,qx*ax+qy*ay+qz*az)
                    extent=_angle(ax,ay,az,bx,by,bz)
                    # No tolerance extends the physical arc. An endpoint near an
                    # equality already provides a continuous fallback distance.
                    if 0<=along<=extent:
                        d=min(d,math.atan2(abs(h),qnorm))
            if d<best:best=d
        out[i]=best
    return out
