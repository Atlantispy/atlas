"""The explicit n=1, V=m=0 subset of the existing I01 SI creep law.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import math

import numpy as np

from atlas_tectonics.integration import _column as I01
from atlas_tectonics._validation import input_shape, snapshot
from atlas_tectonics.integration.resources import select_budget

METHOD = 'atlas.i01-newtonian-creep.v1'
FAMILY = 'i01-newtonian-creep'


def descriptor(law):
    """Validate the entire typed law; no unsupported term may be discarded."""
    tuple(I01.Creep(**item) for item in law.dicts())
    return dict(method=METHOD, family=FAMILY, law=law.record(), gas_constant_j_mol_k=I01.R,
                convention='already-SI invariant e=sum(A exp(-E/RT))*s; s=2eta e',
                scope='n=1; activation volume=0; grain exponent=0; no plasticity/memory/viscosity bounds')


def viscosity_pa_s(law, temperature_k, *, budget=None, cancel=None):
    """Positive finite SI viscosity; stable log-sum, with no floor or ceiling.

    The input is actual absolute temperature, not a nondimensional roundtrip.
    Mechanisms act in parallel at common stress, so their fluidities add.
    """
    descriptor(law)
    shape = input_shape(temperature_k, 'absolute temperature')
    count = math.prod(shape)
    with select_budget(budget).reserve(16384+256*count, category='regional-I01-creep'):
        if cancel is not None and cancel.is_set():
            raise CancelledError('regional I01 creep cancelled')
        temperature = snapshot(temperature_k, 'absolute temperature')
        with np.errstate(over='ignore', under='ignore', invalid='ignore', divide='ignore'):
            denominator = I01.R*temperature
            coefficient = None
            for item in law.dicts():
                local = math.log(item['a'])-item['energy_j_mol']/denominator
                coefficient = local if coefficient is None else np.logaddexp(coefficient, local)
            eta = np.exp(-math.log(2.)-coefficient)
        if cancel is not None and cancel.is_set():
            raise CancelledError('regional I01 creep cancelled')
        return eta
