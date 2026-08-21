"""Shared test configuration for msbwt compat tests.

Provides a --msbwt-package option to select which distribution the tests
exercise.  Default is msbwt-modern3 (the Python 3 port under test).

Usage:
    # Run tests against modern3 (default):
    pytest compat/tests/

    # Run tests against modern2 (oracle):
    pytest compat/tests/ --msbwt-package=msbwt-modern2
"""

import os
import sys


def pytest_addoption(parser):
    parser.addoption(
        "--msbwt-package",
        default="msbwt-modern3",
        choices=["msbwt-modern2", "msbwt-modern3"],
        help=(
            "Which package to import: msbwt-modern2 (frozen oracle) or "
            "msbwt-modern3 (Python 3 port). Default: msbwt-modern3."
        ),
    )


def pytest_configure(config):
    """Inject the selected package directory into sys.path[0].

    This runs before test collection, so module-level imports in test
    files will resolve against the correct package.
    """
    package_name = config.getoption("--msbwt-package", default="msbwt-modern3")
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    package_dir = os.path.normpath(
        os.path.join(tests_dir, "..", "..", "packages", package_name)
    )
    if not os.path.isdir(package_dir):
        raise SystemExit(
            "Selected package directory does not exist: %s" % package_dir
        )
    # Insert at position 0 and ensure no stale entry
    while package_dir in sys.path:
        sys.path.remove(package_dir)
    sys.path.insert(0, package_dir)
    # Store for verification in test output
    config._msbwt_package_dir = package_dir
    config._msbwt_package_name = package_name
