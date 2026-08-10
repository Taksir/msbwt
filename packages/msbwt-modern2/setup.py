# msbwt-modern2: independently built Python 2.7 distribution of the MSBWT
# package, preserving the legacy public `MUS`, `MUSCython`, and `msbwt` CLI
# surfaces.  This build system is intentionally independent from the legacy
# root setup.py and from msbwt-modern3.
#
# Pinned toolchain policy (see environment/ for the exact records):
#   - CPython 2.7.18 (cp27mu/UCS4)
#   - Cython exactly 3.0.12 (the last Cython 3.0.x; Cython 3.1+ is prohibited)
#   - NumPy 1.16.6, pysam 0.15.4, pip 20.3.4, setuptools 44.1.1, wheel 0.37.1
#   - GCC 7.3.0 x86_64-conda_cos6-linux-gnu (conda toolchain)
#
# language_level=2 is applied explicitly by cythonize so every module keeps
# Python 2 semantics under Cython 3.0.x.

from setuptools import setup
from setuptools import Extension

# Version comes from MUS.util (frozen behavior: the original setup.py does the
# same).  Safe because pip/setup.py run with the package source on sys.path.
from MUS import util

EXTENSION_NAMES = [
    'AlignmentUtil',
    'BasicBWT',
    'ByteBWTCython',
    'GenericMerge',
    'MSBWTCompGenCython',
    'MSBWTGenCython',
    'MultiStringBWTCython',
    'MultimergeCython',
    'RLE_BWTCython',
    'LZW_BWTCython',
]

# modern2 modules NOT yet migrated in bootstrap milestone 1 are provided as
# explicit Python stubs (see MUSCython/*_stub.py); they are not built here.

try:
    from Cython.Build import cythonize
    from Cython.Distutils import build_ext as _build_ext
except ImportError:
    useCython = False
    from setuptools.command.build_ext import build_ext as _build_ext
else:
    useCython = True
    try:
        from Cython import __version__ as _cython_version
    except ImportError:
        _cython_version = ''
    if not _cython_version.startswith('3.0.'):
        raise SystemExit(
            'msbwt-modern2 requires Cython 3.0.x (pinned exactly 3.0.12); '
            'found %r.  Cython 3.1+ and 0.29.x are not supported.' % _cython_version)

cmdClass = {}
extModules = []
if useCython:
    extModules += [
        Extension('MUSCython.' + name, ['MUSCython/' + name + '.pyx'], include_dirs=['.'])
        for name in EXTENSION_NAMES
    ]
    extModules = cythonize(extModules, language_level=2, include_path=['.'])
    cmdClass.update({'build_ext': _build_ext})
else:
    extModules += [
        Extension('MUSCython.' + name, ['MUSCython/' + name + '.c'], include_dirs=['.'])
        for name in EXTENSION_NAMES
    ]


class build_ext(_build_ext):
    def finalize_options(self):
        _build_ext.finalize_options(self)
        try:
            __builtins__.__NUMPY_SETUP__ = False
        except AttributeError:
            pass
        import numpy as np
        self.include_dirs.append(np.get_include())


cmdClass['build_ext'] = build_ext

setup(name='msbwt-modern2',
      version=util.VERSION,
      description='Allows for merging and querying of multi-string BWTs for genomic strings (Python 2.7 modernization)',
      url='http://code.google.com/p/msbwt',
      author='James Holt',
      author_email='holtjma@cs.unc.edu',
      license='MIT',
      packages=['MUS', 'MUSCython'],
      package_data={'MUSCython': ['BasicBWT.pxd']},
      install_requires=['pysam', 'numpy'],
      scripts=['bin/msbwt'],
      zip_safe=False,
      ext_modules=extModules,
      cmdclass=cmdClass)
