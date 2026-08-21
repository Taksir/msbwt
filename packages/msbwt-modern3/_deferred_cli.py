"""Deferred CLI stubs for msbwt-modern3 (M3-1 packaging skeleton).

The underlying implementations belong to M3-2 (Python 3 source port) and
M3-3 (Cython extension migration). These stubs exist only to:

* prove the packaging / console-entry-point mapping works end-to-end, and
* fail clearly (non-zero exit, explanatory stderr) rather than silently
  producing a broken or misleading command.

They are intentionally NOT a port of any production behavior.
"""

import sys

MESSAGE = (
    "msbwt-modern3: this command is not yet implemented. "
    "The Python 3 port of the underlying logic is scheduled for M3-2/M3-3."
)


def _deferred(identity):
    sys.stderr.write("ERROR: %s: %s\n" % (identity, MESSAGE))
    raise SystemExit(1)


def ms_main():
    _deferred(
        "msbwt (legacy dispatcher: cffq, pp, cfpp, merge, query, "
        "massquery, compress, decompress, convert)"
    )


def bwt_tags():
    _deferred("msbwt-bwt-tags")


def lcp():
    _deferred("msbwt-lcp")


def quality_sidecar():
    _deferred("msbwt-quality-sidecar")


def remove_sources():
    _deferred("msbwt-remove-sources")


def retrofit_read_provenance():
    _deferred("msbwt-retrofit-read-provenance")


def benchmark_index():
    _deferred("msbwt-benchmark-index")
