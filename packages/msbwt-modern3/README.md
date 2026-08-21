# msbwt-modern3: Python 3 packaging skeleton (M3-1)

This directory is the **independent Python 3 distribution** for the MSBWT
modernization effort. It is intentionally separate from:

* the frozen legacy root (`MUS/`, `MUSCython/` at the repository root), and
* `packages/msbwt-modern2/` (the frozen Python 2.7 / Cython 3.0.x oracle).

## M3-1 scope

M3-1 establishes only the packaging/build skeleton and importability:

* distribution identity (`msbwt-modern3`),
* build-system configuration (PEP 517 / setuptools + Cython),
* dependency declarations (NumPy; pysam conditional on platform),
* Cython extension-build scaffolding (populated in M3-3),
* console-entry-point mapping for all established CLI identities,
* sdist/wheel buildability and fresh-install importability.

It does **not** port Python 2 production modules (that is M3-2) and does
**not** perform the Cython migration (that is M3-3). The `MUS` and
`MUSCython` packages here are currently minimal namespace stubs so the
package is installable and importable; production modules are added in
M3-2 and the compiled extensions in M3-3.

## Public namespace strategy

The eventual public namespaces `MUS`, `MUSCython`, and the `msbwt` CLI are
preserved unchanged (no renaming for aesthetics). Because `msbwt-modern2`
exposes the same import packages, the two distributions must be installed
in **separate environments**; they are never co-installed. Differential
testing is performed across environments, not by co-installation.
