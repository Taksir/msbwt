# -*- coding: utf-8 -*-
"""Platform-consistent .npy writer for the modern2 py2 test suite.

np.save() on CPython 2.7/Windows writes the array's shape tuple elements
(py2 longs on Windows) into the .npy header as 'L'-suffixed literals (e.g.
'(1056000L,)'), while Linux writes plain ints.  The committed test constants
were recorded from Linux, so test-created fixtures must be written with a
normalized int shape.  open_memmap() with ``tuple(int(x) for x in shape)``
produces byte-identical headers on Linux and Windows.
"""
import numpy as np


def save_npy(path, arr):
    mm = np.lib.format.open_memmap(path, 'w+', arr.dtype,
                                   tuple(int(x) for x in arr.shape))
    mm[:] = arr
    del mm
