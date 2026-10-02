# Releasing pymsbwt

`pymsbwt` is built from `packages/msbwt-modern3` by `.github/workflows/release.yml`.
The workflow uses PyPI Trusted Publishing, so no API token is stored anywhere.

## One-time setup (done by the project owner)

1. **Register the project names.**  On https://pypi.org and https://test.pypi.org create
   a *pending publisher* (Account settings > Publishing > "Add a new pending publisher"):
   - PyPI project name: `pymsbwt`
   - Owner: `Taksir`, repository: `msbwt`
   - Workflow file: `release.yml`
   - Environment: `pypi` on PyPI, `testpypi` on TestPyPI
2. **Create the GitHub environments.**  Repository Settings > Environments: create
   `testpypi` and `pypi`.  On `pypi`, enable *Required reviewers* and add yourself;
   this is the manual approval before anything reaches the real index.

## Cutting a release

1. Set the new version in `packages/msbwt-modern3/MUS/util.py` (`VERSION`; it is the
   single source for the package version and for `msbwt -V`).
2. Open a pull request.  The workflow builds the wheels and runs the compat suite and
   the installed-wheel smoke test on every platform; nothing is published from a PR.
3. Merge, then tag and push: `git tag v0.4.0 && git push origin v0.4.0`.
4. The tag build publishes to TestPyPI.  Check it with
   `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pymsbwt==0.4.0`.
5. Approve the `pypi` environment run in the Actions tab to publish to PyPI.

A published version can never be replaced; if something is wrong, yank it on PyPI and
release the next version.

## What gets published

An sdist (needs a C compiler to install) and `cp314` wheels for Linux x86-64 and ARM64
(manylinux), Windows AMD64, and macOS ARM64.  Only platforms whose wheel passes
`packages/msbwt-modern3/ci/smoke_test.py` in CI are published.  Python 3.14 is the only
supported version.
