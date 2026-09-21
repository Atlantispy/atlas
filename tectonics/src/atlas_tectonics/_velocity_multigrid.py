"""Fixed linear geometric V-cycle for the closed free-slip MAC velocity block.

SPDX-License-Identifier: AGPL-3.0-only
Full coupled symmetric stress, Galerkin coarsening and degree-four Chebyshev
smoothing. This is assembled GMG, not a matrix-free ASPECT implementation.
Only square power-of-two grids with isotropic physical spacing are admitted.
The caller owns resource admission, cancellation, source identity and reuse.
"""
import numpy as np
try:
    from scipy.sparse import coo_matrix, block_diag, kron
    from scipy.sparse.linalg import splu
except ImportError:
    # Reference-only execution contexts enumerate this module too. Preparation
    # already refuses missing SciPy for actual variable-mechanics execution.
    coo_matrix = block_diag = kron = splu = None
from ._validation import TectonicsError


def supported(box):
    n = box.nx
    return (n >= 8 and n == box.nz and n & (n - 1) == 0 and
            box.width_m == box.height_m)


def prolongation_1d(n, centred):
    """Cell centres reflect tangentially; eliminated normal walls stay zero."""
    coarse = n // 2
    points = (np.arange(n) + .5) / 2 - .5 if centred else np.arange(1, n) / 2
    rows, cols, values = [], [], []
    for row, x in enumerate(points):
        left = int(np.floor(x)); fraction = x - left
        for col, weight in ((left, 1 - fraction), (left + 1, fraction)):
            if centred:
                col = min(coarse - 1, max(0, col))
            elif col in (0, coarse):
                continue
            if not centred:
                col -= 1
            if weight:
                rows.append(row); cols.append(col); values.append(weight)
    shape = (n, coarse) if centred else (n - 1, coarse - 1)
    result = coo_matrix((values, (rows, cols)), shape=shape).tocsr()
    result.sum_duplicates()
    return result


def hierarchy_transfers(n, cancel):
    transfers = []
    while n > 4:
        cancel()
        cell = prolongation_1d(n, True); face = prolongation_1d(n, False)
        transfers.append(block_diag((kron(cell, face), kron(face, cell)), format='csr'))
        n //= 2
    return transfers


def sparse_bytes(matrix):
    return matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes


class GeometricVcycle:
    """One fixed linear pre/post V-cycle; no inner stopping-tolerance changes."""
    def __init__(self, matrix, transfers, cancel):
        self.levels = []; self.transfers = transfers
        for transfer in transfers:
            cancel()
            matrix = matrix.tocsr(); diagonal = matrix.diagonal()
            if not np.isfinite(matrix.data).all() or np.any(diagonal <= 0):
                raise TectonicsError('multigrid requires finite positive velocity diagonal')
            # Gershgorin upper bound for the similar SPD-scaled operator.
            upper = float(np.max(np.asarray(abs(matrix).sum(axis=1)).ravel() / diagonal))
            if not np.isfinite(upper) or upper <= 0:
                raise TectonicsError('invalid multigrid smoothing bound')
            self.levels.append((matrix, 1 / diagonal, upper))
            matrix = (transfer.T @ matrix @ transfer).tocsc()
        cancel()
        self.coarse = splu(matrix.tocsc(), permc_spec='COLAMD')
        self.nbytes = sum(sparse_bytes(x[0]) + x[1].nbytes for x in self.levels)
        self.nbytes += sum(sparse_bytes(p) for p in transfers)
        self.nbytes += sparse_bytes(self.coarse.L) + sparse_bytes(self.coarse.U)

    @staticmethod
    def smooth(matrix, inverse_diagonal, upper, rhs, x):
        lower = upper / 20
        theta = (upper + lower) / 2; delta = (upper - lower) / 2
        sigma = theta / delta; rho = 1 / sigma
        direction = inverse_diagonal * (rhs - matrix @ x) / theta
        x = x + direction
        for _ in range(3):
            next_rho = 1 / (2 * sigma - rho)
            direction = (next_rho * rho) * direction + (2 * next_rho / delta) * inverse_diagonal * (rhs - matrix @ x)
            x = x + direction; rho = next_rho
        return x

    def _cycle(self, level, rhs):
        if level == len(self.levels):
            return self.coarse.solve(rhs)
        matrix, inverse_diagonal, upper = self.levels[level]
        transfer = self.transfers[level]
        x = self.smooth(matrix, inverse_diagonal, upper, rhs, np.zeros_like(rhs))
        x += transfer @ self._cycle(level + 1, transfer.T @ (rhs - matrix @ x))
        return self.smooth(matrix, inverse_diagonal, upper, rhs, x)

    def solve(self, rhs):
        return self._cycle(0, rhs)
