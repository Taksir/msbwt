# msbwt-modern3 build configuration (M3-1 skeleton).
#
# M3-1 establishes only the packaging skeleton. The Cython extensions are
# NOT built here because the .pyx sources belong to the M3-3 migration and
# are not yet present. The extension list below is auto-populated from any
# MUSCython/*.pyx files that exist, so M3-3 can simply add the ported
# sources without restructuring this file.
#
# Cython language level is pinned to '3str' per MODERN3_REFERENCE_ENVIRONMENT.md.
# NumPy headers are injected into the extension build (M3-3) only when
# extensions are actually compiled, so the M3-1 pure-Python build does not
# require NumPy at build time beyond the build-system requirement.

import os

from setuptools import setup, Extension

# Mirror of MUSCython modules (excluding the dead/private LCPGen stub).
EXTENSION_NAMES = [
    'AlignmentUtil',
    'BasicBWT',
    'ByteBWTCython',
    'CompressToRLE',
    'GenericMerge',
    'MSBWTCompGenCython',
    'MSBWTGenCython',
    'MultiStringBWTCython',
    'MultimergeCython',
    'RLE_BWTCython',
    'LZW_BWTCython',
]

extModules = []
for name in EXTENSION_NAMES:
    src = os.path.join('MUSCython', name + '.pyx')
    if os.path.exists(src):
        extModules.append(Extension('MUSCython.' + name, [src], include_dirs=['.']))

if extModules:
    from Cython.Build import cythonize
    from setuptools.command.build_ext import build_ext as _build_ext

    extModules = cythonize(extModules, language_level='3str', include_path=['.'])

    class build_ext(_build_ext):
        def finalize_options(self):
            _build_ext.finalize_options(self)
            try:
                __builtins__.__NUMPY_SETUP__ = False
            except AttributeError:
                pass
            import numpy as np
            self.include_dirs.append(np.get_include())

    setup(cmdclass={'build_ext': build_ext}, ext_modules=extModules)
else:
    # No ported extension sources yet (M3-1). Build a pure-Python skeleton so
    # sdist/wheel/install remain exercisable and the namespace imports cleanly.
    setup()
