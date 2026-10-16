"""Canonical producer-consumer caloric component reduction.

The heat producer has always summed one contiguous binary64 component vector
per cell. Summing a component-first tensor along axis zero can select a
different NumPy reduction algorithm. Preserve the producer's represented
capacity and component order, independent of cell count and array strides.

Caller owns the input and admits the output (8 bytes per cell), one temporary
component vector (8 bytes per component), and ordinary iterator headers. No
whole-array flattening/copy, numerical tolerance or rounding mode is added.
Physical validation of mass and Cp remains with the native owner.
"""
import numpy as np


def component_sum(values):
    if (type(values) is not np.ndarray or values.dtype != np.dtype(np.float64)
            or values.ndim < 2 or values.shape[0] == 0):
        raise TypeError('Component-first binary64 cell array required')
    result = np.empty(values.shape[1:], dtype=np.float64)
    for index in np.ndindex(result.shape):
        column = np.array(values[(slice(None), *index)], dtype=np.float64, copy=True)
        result[index] = np.sum(column)
    return result
