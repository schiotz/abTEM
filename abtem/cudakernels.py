import cupy as cp
from numba import cuda
import math
from abtem.utils import coordinates_in_disc
from numba import cuda, prange, jit
import numpy as np


@cuda.jit
def put_squares(array, positions, indices):
    i = cuda.threadIdx.x + cuda.blockIdx.x * cuda.blockDim.x

    if i < indices.shape[0]:
        row, col = indices[i]
        cuda.atomic.add(array, (row, col), (positions[i, 0] - row) * (positions[i, 1] - col))
        cuda.atomic.add(array, (row + 1, col), (row + 1 - positions[i, 0]) * (positions[i, 1] - col))
        cuda.atomic.add(array, (row, col + 1), (positions[i, 0] - row) * (col + 1 - positions[i, 1]))
        cuda.atomic.add(array, (row + 1, col + 1), (row + 1 - positions[i, 0]) * (col + 1 - positions[i, 1]))


@cuda.jit
def interpolate_radial_functions_cuda_kernel(array, indices, positions, rows, cols, r, values, derivatives):
    i = cuda.threadIdx.x + cuda.blockIdx.x * cuda.blockDim.x
    n = indices.shape[0] // positions.shape[0]
    dr = (r[1] - r[0]).item()

    if i < indices.shape[0]:
        r_interp = math.sqrt((rows[indices[i]] - positions[i // n, 0]) ** 2 +
                             (cols[indices[i]] - positions[i // n, 1]) ** 2)
        # idx = int(math.floor(math.log(r_interp / r[0]) / log_dr))

        idx = int(math.floor((r_interp - r[0]) / dr))

        if idx < 0:
            val = values[0]

        elif idx > len(r) - 2:
            if idx > len(r) - 1:
                val = values[-1]
            else:
                val = values[-2]

        else:
            val = values[idx] + (r_interp - r[idx]) * derivatives[idx]

        cuda.atomic.add(array, indices[i], val)


@jit(nopython=True, nogil=True, parallel=True)
def interpolate_radial_functions_kernel(array, indices, positions, rows, cols, r, values, derivatives):
    dr = r[1] - r[0]

    for i in range(indices.shape[0]):
        for j in prange(indices.shape[1]):
            r_interp = math.sqrt((rows[indices[i, j]] - positions[i, 0]) ** 2 +
                                 (cols[indices[i, j]] - positions[i, 1]) ** 2)
            # idx = int(math.floor(math.log(r_interp / r[0]) / log_dr))

            idx = int(math.floor((r_interp - r[0]) / dr))

            if idx < 0:
                val = values[0]

            elif idx > len(r) - 1:
                val = values[-1]

            else:
                val = values[idx] + (r_interp - r[idx]) * derivatives[idx]

            array[indices[i, j]] += val


def interpolate_radial_functions(func, positions, shape, cutoff, inner_cutoff=0.):
    xp = cp.get_array_module(positions)

    n = xp.int(xp.ceil(cutoff - inner_cutoff))
    r = xp.linspace(inner_cutoff, cutoff, 2 * n)
    values = func(r)

    margin = xp.int(xp.ceil(r[-1]))
    padded_shape = (shape[0] + 2 * margin, shape[1] + 2 * margin)
    array = xp.zeros(padded_shape[0] * padded_shape[1], dtype=cp.float32)

    derivatives = xp.diff(values) / xp.diff(r)

    positions = positions + margin
    indices = xp.rint(positions).astype(xp.int)[:, 0] * padded_shape[0] + xp.rint(positions).astype(xp.int)[:, 1]
    indices = (indices[:, None] + xp.asarray(coordinates_in_disc(margin - 1, padded_shape))[None]).ravel()

    rows, cols = xp.indices(padded_shape)
    rows = rows.ravel()
    cols = cols.ravel()

    if xp is cp:
        indices = indices.ravel()
        threadsperblock = 32
        blockspergrid = (indices.size + (threadsperblock - 1)) // threadsperblock
        interpolate_radial_functions_cuda_kernel[blockspergrid, threadsperblock](array, indices, positions, rows, cols,
                                                                                 r, values, derivatives)
    else:
        interpolate_radial_functions_kernel(array, indices, positions, rows, cols, r, values, derivatives)

    array = array.reshape(padded_shape)
    array = array[margin:-margin, margin:-margin]

    return array