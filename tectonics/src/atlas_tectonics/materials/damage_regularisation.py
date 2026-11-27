"""R3 fixed-length, no-flux nonlocal damage operator on a 1D uniform support.

SPDX-License-Identifier: AGPL-3.0-only

Atlas-selected extension, NOT an equation from Becker & Fuchs (2023):
    d_bar - ell^2 * d_bar_xx = d,  d_bar_x = 0 at both ends.
Cell-centred finite volumes give an SPD M-matrix. A positive physical ell is
independent of grid spacing. A reusable banded Cholesky factor gives O(n) solves,
not a dense inverse or a newly invented scheduler. Positivity holds. Constants
and the integral are preserved only to a relative error that grows roughly as
eps*(ell/dx)^2: about 4e-16 at ell/dx = 1 and up to about 5e-6 at the admitted
limit ell/dx = 1e5 (2e-10 to 5e-6 measured there, from 3 to 1,000,000 cells).
The residual check scales its tolerance by the same factor, so that error is
accepted; it is not renormalised away. Modal/refinement verification does NOT
establish mesh-independent shear-band localisation in an as-yet absent R4
coupled solver. Raw history is retained separately; filtering must not
overwrite or repeatedly diffuse it. The caller explicitly chooses the value
used by the strength law, so the published local-law control remains available
unchanged.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import threading

import numpy as np
# Preserve the package's explicit NumPy-only reference route. The selected
# banded operator still requires SciPy and never switches algorithms silently.
try:
    from scipy.linalg import cholesky_banded, cho_solve_banded
except ImportError:
    cholesky_banded = cho_solve_banded = None

from atlas_tectonics._validation import TectonicsError, scalar, read_array, frozen
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import check_event_or_callable
from atlas_tectonics.integration.reuse import ExecutionContext
from atlas_tectonics.materials.constitutive import _json
from atlas_tectonics.materials.constitutive_execution import PreparedRheology


@dataclass(frozen=True, slots=True)
class DamageLengthScale:
    name: str
    domain_length_m: float
    length_scale_m: float
    cells: int
    source: str

    def __post_init__(self):
        for key in ('domain_length_m','length_scale_m'):
            object.__setattr__(self,key,scalar(getattr(self,key),key,positive=True))
        if type(self.cells) is not int or not 3<=self.cells<=1_000_000:
            raise TectonicsError('regularisation requires 3..1000000 cells')


class PreparedDamageRegularisation:
    """A source-bound operator with bounded retained factorisation, not a history."""
    def __init__(self,parameters,*,budget=None):
        if cholesky_banded is None or cho_solve_banded is None:
            raise TectonicsError('SciPy banded solver unavailable; no regularisation backend fallback')
        self.parameters=parameters; self.budget=select_budget(budget)
        self._closed=False; self._active=False; self._lock=threading.Lock(); self._context=None
        self._guard=self.budget.reserve(64*parameters.cells+5*1024**2,category='damage-length-factor')
        self._guard.__enter__()
        try:
            self._context=ExecutionContext('scipy')
            n=parameters.cells; self._s=(parameters.length_scale_m/(parameters.domain_length_m/n))**2
            a=np.zeros((2,n)); a[0]=1+2*self._s; a[0,0]=a[0,-1]=1+self._s
            a[1,:-1]=-self._s
            self._factor=frozen(cholesky_banded(a,lower=True,check_finite=False))
            self.identity=hashlib.sha256(_json({'method':'atlas.damage-helmholtz-1d.v1',
                'parameters':asdict(parameters),'context':self._context.identity})).hexdigest()
        except BaseException:
            self._guard.__exit__(None,None,None)
            raise

    def __setattr__(self,name,value):
        object.__setattr__(self,name,value)

    def __enter__(self):
        return self

    def __exit__(self,*_): self.close()

    _close_refusal = 'join regularisation before close'
    close = PreparedRheology.close

    def apply(self,damage,*,cancel=None):
        with self._lock:
            self._active=True
        try:
            check_event_or_callable(cancel, 'constitutive work cancelled')
            with self.budget.reserve(96*self.parameters.cells+65536,category='damage-length-solve'):
                raw=read_array(damage,'raw damage',nonnegative=True)
                value=cho_solve_banded((self._factor,True),raw,check_finite=False)
                # Independent residual from flux differences, not the solver's factors.
                flux=self._s*np.diff(value)
                residual=value-raw
                residual[:-1]-=flux; residual[1:]+=flux
                result=frozen(value)
            check_event_or_callable(cancel, 'constitutive work cancelled')
            return result
        finally:
            with self._lock:self._active=False
