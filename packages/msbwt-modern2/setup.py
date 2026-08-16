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

import os

# Version comes from MUS.util (frozen behavior: the original setup.py does the
# same).  Safe because pip/setup.py run with the package source on sys.path.
from MUS import util

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


# enhanced-modern2 command-line tools are installed as conventional
# console-script entry points.  Each tool keeps its argparse `main()` and
# `MUS.*` imports; the entry points simply make the installed commands
# available on PATH with the environment's own interpreter.
ENHANCED_CONSOLE_SCRIPTS = [
    'msbwt-bwt-tags = tools.bwt_tags:main',
    'msbwt-lcp = tools.lcp:main',
    'msbwt-quality-sidecar = tools.quality_sidecar:main',
    'msbwt-remove-sources = tools.remove_sources:main',
    'msbwt-retrofit-read-provenance = tools.retrofit_read_provenance:main',
    'msbwt-benchmark-index = tools.benchmark_index:main',
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

    def build_extensions(self):
        # Native Windows (MinGW-w64) builds: link the extension DLLs against
        # msvcrt.dll instead of the MSVC9 CRT (msvcr90.dll).
        #
        # Background: distutils on Python 2.7 derives the CRT import library
        # from sys.version ("MSC v.1500" on the conda/CPython 2.7 Windows
        # build) and passes -lmsvcr90 to the mingw32 linker.  On Windows
        # 10/11 this is not loadable: the extension .pyd has no SxS manifest,
        # so the loader resolves msvcr90.dll outside the activation context
        # of the interpreter and the CRT's initialization aborts with runtime
        # error R6034 ("attempt to load the C runtime library incorrectly"),
        # failing every import.  The community-proven mingwpy approach links
        # Python 2.7 extensions against msvcrt.dll (always loadable, no
        # manifest) instead.  msbwt extensions perform no cross-CRT resource
        # passing: all Python-visible objects are allocated/freed through the
        # python27.dll exports, so this has no semantic effect on the build
        # or the artifacts.  Linux/GCC builds are unaffected (this branch
        # only triggers for the mingw32 compiler on Windows).
        compiler = getattr(self, 'compiler', None)
        if os.name == 'nt' and compiler is not None \
                and getattr(compiler, 'compiler_type', '') == 'mingw32':
            compiler.dll_libraries = ['msvcrt']
        _build_ext.build_extensions(self)


cmdClass['build_ext'] = build_ext

setup(name='msbwt-modern2',
      version=util.VERSION,
      description='Allows for merging and querying of multi-string BWTs for genomic strings (Python 2.7 modernization)',
      url='http://code.google.com/p/msbwt',
      author='James Holt',
      author_email='holtjma@cs.unc.edu',
      license='MIT',
      packages=['MUS', 'MUSCython', 'tools'],
      package_data={'MUSCython': ['BasicBWT.pxd']},
      # pysam is required on Linux/WSL for BAM preprocessing, but has no
      # CPython 2.7 Windows distribution (no cp27 win_amd64 wheel exists
      # on PyPI for any version).  The PEP 508 marker excludes it from
      # installation on Windows; FASTQ/MSBWT operations work without it.
      # BAM input is intentionally unavailable on native Windows.
      install_requires=['numpy', 'pysam; sys_platform != "win32"'],
      scripts=['bin/msbwt'],
<<<<<<< HEAD
      entry_points={'console_scripts': ENHANCED_CONSOLE_SCRIPTS},
=======
      entry_points={'console_scripts': ['msbwt = MUS.CommandLineInterface:mainRun']},
>>>>>>> af6bf28 (windows: make pysam optional so Windows installs without --no-deps)
      zip_safe=False,
      ext_modules=extModules,
      cmdclass=cmdClass)
