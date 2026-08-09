"""Not-yet-migrated module stub for msbwt-modern2 bootstrap milestone 1.

This module exists so the legacy public import surface
(``MUSCython.GenericMerge``) is preserved.  The real Cython implementation
(``GenericMerge.pyx``) is part of the frozen legacy source and has NOT been
migrated to the Cython 3.0.x toolchain yet; calling any of its functions
raises NotImplementedError.

Merge was explicitly excluded from bootstrap milestone 1
(see docs/modernization/MODERN2_BOOTSTRAP_MILESTONE1.md).  The legacy
``merge -p 1`` UnboundLocalError and the historical committed generated-C
SIGSEGV are documented legacy defects that modern2 may fix in a later
milestone.
"""


def mergeTwoMSBWTs(*args, **kwargs):
    raise NotImplementedError(
        'MUSCython.GenericMerge.mergeTwoMSBWTs is not yet migrated in '
        'msbwt-modern2 bootstrap milestone 1')


def interleaveTwoBwts(*args, **kwargs):
    raise NotImplementedError(
        'MUSCython.GenericMerge.interleaveTwoBwts is not yet migrated in '
        'msbwt-modern2 bootstrap milestone 1')
