"""Intentionally non-migrated module stub for msbwt-modern2 (milestone 10).

Classification: DEAD/PRIVATE - intentionally not migrated.

``MUSCython.LCPGen`` is not reachable from any public modern2 path:

- no CLI subcommand dispatches to it (see ``MUS/CommandLineInterface.py``);
- no Python or Cython module imports it (verified by repository-wide call
  graph search at milestone 10); the frozen ``setup.py`` builds it only
  because the historical package built every ``.pyx`` module;
- the readers only *consume* an ``lcps.npy`` if one is present; nothing in
  the supported public paths ever creates one.

It therefore has no release-blocking role in modern2 and stays an explicit
stub so the legacy import surface (``import MUSCython.LCPGen``) keeps
working.  Calling either function raises NotImplementedError; this is the
documented intentional compatibility decision for this dead/private module.
"""


def lcpGenerator(*args, **kwargs):
    raise NotImplementedError(
        'MUSCython.LCPGen.lcpGenerator is not migrated in msbwt-modern2: '
        'classified DEAD/PRIVATE (no public CLI/API path reaches it; see '
        'docs/modernization/MODERN2_MILESTONE10_PUBLIC_SURFACE.md)')


def linearLcpGenerator(*args, **kwargs):
    raise NotImplementedError(
        'MUSCython.LCPGen.linearLcpGenerator is not migrated in '
        'msbwt-modern2: classified DEAD/PRIVATE (no public CLI/API path '
        'reaches it; see '
        'docs/modernization/MODERN2_MILESTONE10_PUBLIC_SURFACE.md)')
