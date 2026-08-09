"""Not-yet-migrated module stub for msbwt-modern2 bootstrap milestone 1.

This module exists so the legacy public import surface (``MUSCython.CompressToRLE``)
is preserved.  The real Cython implementation (``CompressToRLE.pyx``) is part of
the frozen legacy source and has NOT been migrated to the Cython 3.0.x toolchain
yet; calling any of its functions raises NotImplementedError.

See docs/modernization/MODERN2_BOOTSTRAP_MILESTONE1.md for the migration
status table.  Do not treat this stub as an implementation.
"""


def compressInput(*args, **kwargs):
    raise NotImplementedError(
        'MUSCython.CompressToRLE.compressInput is not yet migrated in '
        'msbwt-modern2 bootstrap milestone 1')
