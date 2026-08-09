"""Not-yet-migrated module stub for msbwt-modern2 bootstrap milestone 1.

This module exists so the legacy public import surface (``MUSCython.LCPGen``)
is preserved.  The real Cython implementation (``LCPGen.pyx``) is part of the
frozen legacy source and has NOT been migrated to the Cython 3.0.x toolchain
yet; calling any of its functions raises NotImplementedError.

LCP generation is out of scope for bootstrap milestone 1
(see docs/modernization/MODERN2_BOOTSTRAP_MILESTONE1.md).
"""


def lcpGenerator(*args, **kwargs):
    raise NotImplementedError(
        'MUSCython.LCPGen.lcpGenerator is not yet migrated in '
        'msbwt-modern2 bootstrap milestone 1')


def linearLcpGenerator(*args, **kwargs):
    raise NotImplementedError(
        'MUSCython.LCPGen.linearLcpGenerator is not yet migrated in '
        'msbwt-modern2 bootstrap milestone 1')
