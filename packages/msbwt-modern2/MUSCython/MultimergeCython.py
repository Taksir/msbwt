"""Not-yet-migrated module stub for msbwt-modern2 bootstrap milestone 1.

This module exists so the legacy public import surface
(``MUSCython.MultimergeCython``) is preserved.  The real Cython implementation
(``MultimergeCython.pyx``) is part of the frozen legacy source and has NOT
been migrated to the Cython 3.0.x toolchain yet; calling any of its functions
raises NotImplementedError.

Non-uniform (variable-length) construction and the non-uniform preprocessing
route are out of scope for bootstrap milestone 1
(see docs/modernization/MODERN2_BOOTSTRAP_MILESTONE1.md).
"""

_PUBLIC_NAMES = [
    'createMSBWTFromSeqs', 'preprocessSeqs', 'createMSBWTFromFasta',
    'preprocessFasta', 'createMSBWTFromFastq', 'preprocessFastqs',
    'mergeTwoMSBWTs', 'mergeUsingInterleave', 'fastaIterator', 'fastqIterator',
    'formatSeqsForMerge', 'memoryBWT', 'interleaveLevelMerge', 'levelIterator',
    'buildViaMerge256', 'rangeIterator', 'rangeSolve_thread',
]


def _not_implemented(name):
    def stub(*args, **kwargs):
        raise NotImplementedError(
            'MUSCython.MultimergeCython.%s is not yet migrated in '
            'msbwt-modern2 bootstrap milestone 1' % name)
    stub.__name__ = name
    return stub


for _name in _PUBLIC_NAMES:
    globals()[_name] = _not_implemented(_name)

del _name
