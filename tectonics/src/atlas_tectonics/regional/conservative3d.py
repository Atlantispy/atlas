"""Locally conservative Q2/(Q1+P0) hexahedral pressure enrichment.

The velocity space and full symmetric-gradient stress are unchanged. The last
cell indicator is omitted: the Q1 partition of unity already supplies its
constant together with the other indicators. This is a basis of the enriched
space, not a pressure pin or a relaxed continuity equation.

Pestana and Silvester (2024), Numerische Mathematik, section 2.1,
doi:10.1007/s00211-024-01420-z (tensor-product extended Taylor--Hood space).
SPDX-License-Identifier: AGPL-3.0-only
"""
import hashlib
from pathlib import Path

import numpy as np
from scipy import sparse

_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def assembly_bytes(ncells):
    # COO/CSR intermediates, stacked B, pressure coefficients and result fields;
    # four copies of 81-entry rows plus 27 quadrature pressure/stress values.
    return 65536+16384*ncells


def enrich(mesh, B, weights, diagonal, viscosity):
    """Append all but one exact-Gauss cell continuity equation."""
    local = -np.einsum('q,qai->ai', mesh.quadrature_weights, mesh._grad_v).reshape(81)
    dofs = (mesh.velocity_cells[:, :, None]*3+np.arange(3)).reshape(mesh.nc, 81)
    C = sparse.coo_matrix((np.tile(local, mesh.nc),
        (np.repeat(np.arange(mesh.nc), 81), dofs.ravel())),
        shape=(mesh.nc, 3*mesh.nv)).tocsr()
    volume = float(np.sum(mesh.quadrature_weights))
    extended_weights = np.r_[weights, np.full(mesh.nc-1, volume)]
    extended_diagonal = np.r_[diagonal,
        np.sum(mesh.quadrature_weights/viscosity, axis=1)[:-1]]
    constant = np.r_[np.ones(mesh.np), np.zeros(mesh.nc-1)]
    return sparse.vstack((B, C[:-1]), format='csr'), extended_weights, extended_diagonal, constant


def cell_coefficients(mesh, pressure):
    return np.r_[pressure[mesh.np:], 0.]


def evaluate(mesh, velocity, pressure):
    values = mesh.evaluate(velocity, pressure[:mesh.np])
    values['pressure_q'] += cell_coefficients(mesh, pressure)[:, None]
    return values
