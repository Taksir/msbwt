#!/usr/bin/env python
"""Run and record isolated Python-2 legacy-oracle dependency/build probes.

The program is deliberately compatible with Python 2.7.  It never changes the
provided source directory: it verifies and copies the audited source projection
to a new scratch directory before invoking frozen setup.py there.
"""
from __future__ import print_function

import argparse
import datetime
import glob
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import traceback

import verify_frozen_source


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MATRIX = os.path.join(SCRIPT_DIR, "probe-matrix.json")
DEFAULT_MANIFEST = os.path.join(SCRIPT_DIR, "frozen-source.sha256")
ROUTES = ("generated-c-no-cython", "pyx-historical-cython")
FIRST_GOLDEN_CASE_ID = "uniform-multifile"
FIRST_GOLDEN_FILES = ("uniform-a.fastq", "uniform-b.fastq")
FIRST_GOLDEN_MANIFEST = "fixture-manifest.json"
CLI_MAIN = "from MUS import CommandLineInterface; CommandLineInterface.mainRun()"
VERSIONED_CANDIDATE_PACKAGES = (
    ("numpy", "numpy", "numpy"),
    ("pysam", "pysam", "pysam"),
    ("cython", "Cython", "Cython"),
    ("pip", "pip", "pip"),
    ("setuptools", "setuptools", "setuptools"),
    ("wheel", "wheel", "wheel")
)
COMPILER_CONFIG_VARIABLES = (
    "CONFIG_ARGS", "CC", "CFLAGS", "CPPFLAGS", "LDFLAGS", "LDSHARED", "SOABI"
)
INHERITED_BUILD_VARIABLES = (
    "AR", "AS", "CC", "CXX", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LD", "LDFLAGS",
    "CONDA_BUILD_SYSROOT", "_CONDA_PYTHON_SYSCONFIGDATA_NAME", "PATH"
)

try:
    STRING_TYPES = (basestring,)
    TEXT_TYPE = unicode
    INTEGER_TYPES = (int, long)
except NameError:
    STRING_TYPES = (str,)
    TEXT_TYPE = str
    INTEGER_TYPES = (int,)


def ensure_directory(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def utc_run_id():
    return datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + "-pid" + str(os.getpid())


def safe_component(value):
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    return "".join(character if character in allowed else "-" for character in value)


def write_json(path, value):
    with open(path, "wb") as handle:
        encoded = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
        if not isinstance(encoded, bytes):
            encoded = encoded.encode("utf-8")
        handle.write(encoded)
        handle.write(b"\n")


def read_json(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def require_new_path(path, description):
    if os.path.lexists(path):
        raise RuntimeError("refusing to overwrite existing {0}: {1}".format(description, path))


def validate_first_golden_fixtures(fixture_root):
    """Validate the exact two FASTQ inputs before creating a probe result.

    The fixture manifest is host-side compatibility input.  This Python-2
    reader only checks its declared byte count and SHA-256 values; it does not
    import the Python-3 fixture generator or any modern MSBWT code.
    """
    root = os.path.abspath(fixture_root)
    if not os.path.isdir(root):
        raise ValueError("fixture root is not a directory: {0}".format(root))
    manifest_path = os.path.join(root, FIRST_GOLDEN_MANIFEST)
    if not os.path.isfile(manifest_path):
        raise ValueError("fixture manifest is missing: {0}".format(manifest_path))
    try:
        manifest = read_json(manifest_path)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("fixture manifest is not valid UTF-8 JSON: {0}".format(exc))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported fixture manifest schema: {0!r}".format(manifest.get("schema_version")))

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("fixture manifest cases is not a list")
    matching_cases = [case for case in cases if isinstance(case, dict) and case.get("id") == FIRST_GOLDEN_CASE_ID]
    if len(matching_cases) != 1 or matching_cases[0].get("files") != list(FIRST_GOLDEN_FILES):
        raise ValueError("fixture manifest does not declare the exact {0} case".format(FIRST_GOLDEN_CASE_ID))

    file_entries = manifest.get("files")
    if not isinstance(file_entries, list):
        raise ValueError("fixture manifest files is not a list")
    declared = {}
    for entry in file_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), STRING_TYPES):
            raise ValueError("fixture manifest has an invalid file entry")
        path = entry["path"]
        if path in declared:
            raise ValueError("fixture manifest declares a file twice: {0}".format(path))
        declared[path] = entry

    verified_files = []
    for name in FIRST_GOLDEN_FILES:
        entry = declared.get(name)
        if entry is None:
            raise ValueError("fixture manifest lacks required file: {0}".format(name))
        if os.path.basename(name) != name:
            raise ValueError("first golden file is not a simple filename: {0}".format(name))
        expected_hash = entry.get("sha256")
        expected_size = entry.get("byte_count")
        if not isinstance(expected_hash, STRING_TYPES) or len(expected_hash) != 64:
            raise ValueError("fixture manifest has invalid SHA-256 for {0}".format(name))
        if not isinstance(expected_size, INTEGER_TYPES) or expected_size < 0:
            raise ValueError("fixture manifest has invalid byte count for {0}".format(name))
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            raise ValueError("fixture file is missing: {0}".format(path))
        actual_size = os.path.getsize(path)
        actual_hash = sha256_file(path)
        if actual_size != expected_size or actual_hash.lower() != expected_hash.lower():
            raise ValueError(
                "fixture bytes do not match manifest for {0}: size {1}/{2}, sha256 {3}/{4}".format(
                    name, actual_size, expected_size, actual_hash, expected_hash
                )
            )
        verified_files.append({
            "byte_count": actual_size,
            "path": name,
            "sha256": actual_hash
        })
    return {
        "case_id": FIRST_GOLDEN_CASE_ID,
        "fixture_manifest": FIRST_GOLDEN_MANIFEST,
        "fixture_manifest_sha256": sha256_file(manifest_path),
        "fixture_root": root,
        "files": verified_files
    }


def _path_bytes(path):
    if isinstance(path, TEXT_TYPE):
        return path.encode("utf-8")
    return path


def oracle_tree_sha256(root):
    """Hash an oracle-produced dataset tree without adding metadata to it."""
    if not os.path.isdir(root) or os.path.islink(root):
        raise RuntimeError("snapshot source is not an ordinary directory: {0}".format(root))
    digest = hashlib.sha256()
    for current_root, directories, filenames in os.walk(root):
        directories.sort()
        filenames.sort()
        for directory in directories:
            full_path = os.path.join(current_root, directory)
            if os.path.islink(full_path):
                raise RuntimeError("refusing symlink in oracle dataset: {0}".format(full_path))
        for filename in filenames:
            full_path = os.path.join(current_root, filename)
            if os.path.islink(full_path) or not os.path.isfile(full_path):
                raise RuntimeError("refusing non-regular oracle artifact: {0}".format(full_path))
            relative = os.path.relpath(full_path, root).replace(os.sep, "/")
            digest.update(b"file\x00")
            digest.update(_path_bytes(relative))
            digest.update(b"\x00")
            digest.update(str(os.path.getsize(full_path)).encode("ascii"))
            digest.update(b"\x00")
            with open(full_path, "rb") as handle:
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
    return digest.hexdigest()


def copy_oracle_snapshot(dataset_dir, case_dir, stage):
    digest = oracle_tree_sha256(dataset_dir)
    snapshot_name = "{0}-sha256-{1}".format(stage, digest)
    snapshot_path = os.path.join(case_dir, snapshot_name)
    require_new_path(snapshot_path, "oracle snapshot")
    shutil.copytree(dataset_dir, snapshot_path)
    if oracle_tree_sha256(snapshot_path) != digest:
        raise RuntimeError("oracle snapshot hash changed while copying: {0}".format(snapshot_path))
    return {"path": snapshot_name, "tree_sha256": digest}


class Recorder(object):
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.commands_dir = os.path.join(output_dir, "commands")
        ensure_directory(self.commands_dir)
        self.records = []

    def run(self, label, argv, cwd=None):
        index = len(self.records) + 1
        stem = "{0:03d}-{1}".format(index, safe_component(label))
        stdout_name = stem + ".stdout"
        stderr_name = stem + ".stderr"
        stdout_path = os.path.join(self.commands_dir, stdout_name)
        stderr_path = os.path.join(self.commands_dir, stderr_name)
        started = datetime.datetime.utcnow().isoformat() + "Z"
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            returncode = process.returncode
        except OSError as exc:
            stdout = b""
            stderr = ("unable to start command: {0}\n".format(exc)).encode("utf-8")
            returncode = 127
        finished = datetime.datetime.utcnow().isoformat() + "Z"
        with open(stdout_path, "wb") as handle:
            handle.write(stdout)
        with open(stderr_path, "wb") as handle:
            handle.write(stderr)
        record = {
            "argv": argv,
            "cwd": cwd,
            "finished_utc": finished,
            "label": label,
            "returncode": returncode,
            "started_utc": started,
            "stderr": os.path.join("commands", stderr_name),
            "stdout": os.path.join("commands", stdout_name)
        }
        self.records.append(record)
        return returncode


def copy_frozen_projection(source, destination, manifest):
    mismatches = verify_frozen_source.verify(source, manifest)
    if mismatches:
        message = "frozen source verification failed: " + repr(mismatches)
        raise RuntimeError(message)
    if os.path.exists(destination):
        raise RuntimeError("scratch destination already exists: {0}".format(destination))
    entries = verify_frozen_source.read_manifest(manifest)
    for unused_digest, destination_relative, source_relative in entries:
        source_path = os.path.join(source, *source_relative.split("/"))
        destination_path = os.path.join(destination, *destination_relative.split("/"))
        parent = os.path.dirname(destination_path)
        ensure_directory(parent)
        shutil.copy2(source_path, destination_path)


def version_probe_commands(recorder):
    compiler = os.environ.get("CC") or "gcc"
    commands = [
        ("python-version", [sys.executable, "--version"]),
        ("pip-version", [sys.executable, "-m", "pip", "--version"]),
        ("pip-freeze-all", [sys.executable, "-m", "pip", "freeze", "--all"]),
        ("compiler-version", [compiler, "--version"]),
        ("python-package-versions", [sys.executable, "-c", "import json; import sys; names=['numpy','pysam','Cython','setuptools','wheel']; result={};\nfor name in names:\n try:\n  module=__import__(name); result[name]=getattr(module, '__version__', 'present-no-version')\n except Exception as exc:\n  result[name]='IMPORT_FAILED: %s: %s' % (exc.__class__.__name__, exc)\nprint(json.dumps(result, sort_keys=True))"])
    ]
    for label, argv in commands:
        recorder.run(label, argv)


def install_exact(recorder, package, version):
    return recorder.run(
        "install-{0}-{1}".format(package, version),
        [sys.executable, "-m", "pip", "install", "--upgrade", "{0}=={1}".format(package, version)]
    )


def install_base_candidate(recorder, candidate):
    failures = []
    for package in ("pip", "setuptools", "wheel", "numpy", "pysam"):
        version = candidate.get(package)
        if version:
            returncode = install_exact(recorder, package, version)
            if returncode:
                failures.append(package)
    return failures


def install_cython_candidate(recorder, candidate):
    version = candidate.get("cython")
    if not version:
        return ["cython-unspecified"]
    return [] if not install_exact(recorder, "Cython", version) else ["Cython"]


def candidate_version_gate_source(candidate):
    """Return Python-2-compatible code that proves exact candidate versions.

    Package imports are intentionally part of the check.  Metadata claiming a
    version is insufficient if importing the module itself fails, particularly
    for compiled NumPy and pysam extensions.
    """
    expected = {}
    modules = {}
    distributions = {}
    for matrix_key, module_name, distribution_name in VERSIONED_CANDIDATE_PACKAGES:
        version = candidate.get(matrix_key)
        if version is not None:
            expected[matrix_key] = version
            modules[matrix_key] = module_name
            distributions[matrix_key] = distribution_name
    encoded_expected = json.dumps(expected, sort_keys=True, ensure_ascii=True)
    encoded_modules = json.dumps(modules, sort_keys=True, ensure_ascii=True)
    encoded_distributions = json.dumps(distributions, sort_keys=True, ensure_ascii=True)
    return """
from __future__ import print_function
import json

expected = {expected}
module_names = {modules}
distribution_names = {distributions}
try:
    text_type = unicode
except NameError:
    text_type = str

def as_text(value):
    if isinstance(value, text_type):
        return value
    try:
        return str(value)
    except Exception:
        return None

def module_version(module, distribution_name):
    for attribute in ("__version__", "version"):
        value = getattr(module, attribute, None)
        if isinstance(value, (str, text_type)):
            return as_text(value), "module." + attribute
        nested = getattr(value, "__version__", None)
        if isinstance(nested, (str, text_type)):
            return as_text(nested), "module." + attribute + ".__version__"
    try:
        import pkg_resources
        return as_text(pkg_resources.get_distribution(distribution_name).version), "pkg_resources"
    except Exception as exc:
        return None, "version-unavailable: %s: %s" % (exc.__class__.__name__, exc)

resolved = {{}}
failures = []
for key in sorted(expected):
    module_name = module_names[key]
    try:
        module = __import__(module_name)
    except Exception as exc:
        resolved[key] = {{"actual": None, "error": "%s: %s" % (exc.__class__.__name__, exc), "expected": expected[key]}}
        failures.append(key)
        continue
    actual, source = module_version(module, distribution_names[key])
    resolved[key] = {{"actual": actual, "expected": expected[key], "source": source}}
    if actual != expected[key]:
        failures.append(key)
print(json.dumps({{"expected": expected, "resolved": resolved, "failures": failures}}, sort_keys=True))
raise SystemExit(1 if failures else 0)
""".format(
        expected=encoded_expected,
        modules=encoded_modules,
        distributions=encoded_distributions
    )


def run_candidate_version_gate(recorder, candidate, route):
    """Record the exact import/version gate that must pass before a golden."""
    return recorder.run(
        "candidate-version-gate-{0}".format(route),
        [sys.executable, "-c", candidate_version_gate_source(candidate)]
    )


def _read_text_file(path):
    try:
        with open(path, "rb") as handle:
            value = handle.read()
    except IOError as exc:
        return {"error": "{0}: {1}".format(exc.__class__.__name__, exc), "path": path}
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        text = value.decode("utf-8", "replace")
    return {"path": path, "text": text}


def _safe_conda_url(value):
    """Retain normal package URLs but never persist URL credentials or tokens."""
    if not isinstance(value, STRING_TYPES):
        return None
    try:
        try:
            from urllib.parse import urlsplit
        except ImportError:
            from urlparse import urlsplit
        parts = urlsplit(value)
        if parts.username or parts.password or parts.query or parts.fragment:
            return None
    except Exception:
        return None
    return value


def capture_conda_metadata(prefix):
    """Capture only reproducibility fields from conda package records, if any."""
    metadata_directory = os.path.join(prefix, "conda-meta")
    result = {"directory": metadata_directory, "packages": []}
    if not os.path.isdir(metadata_directory):
        return result
    for path in sorted(glob.glob(os.path.join(metadata_directory, "*.json"))):
        item = {"file": os.path.basename(path)}
        try:
            package = read_json(path)
        except (IOError, ValueError, UnicodeDecodeError) as exc:
            item["error"] = "{0}: {1}".format(exc.__class__.__name__, exc)
            result["packages"].append(item)
            continue
        for key in ("name", "version", "build", "channel", "md5", "sha256"):
            item[key] = package.get(key)
        url = package.get("url")
        safe_url = _safe_conda_url(url)
        item["url"] = safe_url
        if url is not None and safe_url is None:
            item["url_redacted"] = True
        result["packages"].append(item)
    return result


def capture_python_build_metadata():
    try:
        import sysconfig
    except ImportError:
        from distutils import sysconfig
    try:
        import ssl
        openssl_version = getattr(ssl, "OPENSSL_VERSION", None)
        openssl_version_info = getattr(ssl, "OPENSSL_VERSION_INFO", None)
    except ImportError as exc:
        openssl_version = None
        openssl_version_info = "IMPORT_FAILED: {0}: {1}".format(exc.__class__.__name__, exc)
    config_variables = {}
    for name in COMPILER_CONFIG_VARIABLES:
        config_variables[name] = sysconfig.get_config_var(name)
    inherited = {}
    for name in INHERITED_BUILD_VARIABLES:
        inherited[name] = {
            "host_specific": name == "PATH",
            "value": os.environ.get(name)
        }
    return {
        "compiler_config_variables": config_variables,
        "inherited_build_environment": inherited,
        "openssl_from_python": {
            "version": openssl_version,
            "version_info": openssl_version_info
        },
        "python_prefix": sys.prefix,
        "python_sys_version": sys.version,
        "python_maxunicode": getattr(sys, "maxunicode", None)
    }


def capture_host_metadata(recorder, run_dir):
    metadata = {
        "architecture": platform.machine(),
        "machine": platform.machine(),
        "base_image_reference": os.environ.get("ORACLE_BASE_IMAGE_REFERENCE"),
        "base_image_status": os.environ.get("ORACLE_BASE_IMAGE_STATUS"),
        "conda_metadata": capture_conda_metadata(sys.prefix),
        "glibc_from_python": platform.libc_ver(),
        "os_release": _read_text_file("/etc/os-release"),
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_implementation": platform.python_implementation(),
        "python_version": sys.version,
        "timezone_name": os.environ.get("TZ"),
        "uname_from_python": platform.uname(),
        "utc_started": datetime.datetime.utcnow().isoformat() + "Z"
    }
    metadata.update(capture_python_build_metadata())
    write_json(os.path.join(run_dir, "environment.json"), metadata)
    for label, argv in (
        ("uname", ["uname", "-a"]),
        ("os-release", ["sh", "-c", "cat /etc/os-release"]),
        ("locale", ["locale"]),
        ("ldd-version", ["ldd", "--version"]),
        ("openssl-version", ["openssl", "version", "-a"]),
    ):
        recorder.run(label, argv)


def resolve_routes(value):
    if value == "all":
        return ROUTES
    return (value,)


def run_first_golden_case(
        recorder, route, candidate_name, destination, run_dir, fixture_info, gate,
        dependency_install_failures):
    """Capture the one permitted initial CLI scenario after every gate passes."""
    case_dir = os.path.join(
        run_dir,
        "first-goldens",
        "{0}-{1}".format(FIRST_GOLDEN_CASE_ID, safe_component(route))
    )
    require_new_path(case_dir, "first-golden case directory")
    ensure_directory(case_dir)
    dataset_dir = os.path.join(destination, "oracle-first-golden-" + FIRST_GOLDEN_CASE_ID)
    result = {
        "build_route": route,
        "candidate": candidate_name,
        "case_id": FIRST_GOLDEN_CASE_ID,
        "command_labels": {
            "setup_build": "build-{0}".format(route),
            "build_ext_inplace": "build-ext-inplace-{0}".format(route),
            "import_smoke": "import-smoke-{0}".format(route),
            "cli_version": "cli-version-{0}".format(route),
            "preprocess": "first-golden-pp-{0}".format(FIRST_GOLDEN_CASE_ID),
            "cfpp": "first-golden-cfpp-{0}".format(FIRST_GOLDEN_CASE_ID)
        },
        "fixture": fixture_info,
        "gate_returncodes": gate,
        "dependency_install_failures": dependency_install_failures,
        "snapshots": {},
        "status": "not-run"
    }
    # A golden can be marked passed only below, after the four build/import/CLI
    # gate commands, both frozen CLI calls, and both immutable copies succeed.
    if any(returncode != 0 for returncode in gate.values()):
        result["status"] = "skipped-gate-failure"
        write_json(os.path.join(case_dir, "case-result.json"), result)
        return result

    try:
        require_new_path(dataset_dir, "first-golden working dataset")
        fixture_paths = [os.path.join(fixture_info["fixture_root"], name) for name in FIRST_GOLDEN_FILES]
        preprocess_returncode = recorder.run(
            result["command_labels"]["preprocess"],
            [sys.executable, "-c", CLI_MAIN, "pp", "-u", dataset_dir] + fixture_paths,
            cwd=destination
        )
        result["preprocess_returncode"] = preprocess_returncode
        if preprocess_returncode != 0:
            result["status"] = "failed-preprocess"
            return result
        result["snapshots"]["preprocess"] = copy_oracle_snapshot(dataset_dir, case_dir, "preprocess")

        build_returncode = recorder.run(
            result["command_labels"]["cfpp"],
            [sys.executable, "-c", CLI_MAIN, "cfpp", "-p", "1", "-u", dataset_dir],
            cwd=destination
        )
        result["build_returncode"] = build_returncode
        if build_returncode != 0:
            result["status"] = "failed-build"
            return result
        result["snapshots"]["build"] = copy_oracle_snapshot(dataset_dir, case_dir, "build")
        result["status"] = "passed"
        return result
    except Exception as exc:
        result["error"] = "{0}: {1}".format(exc.__class__.__name__, exc)
        result["status"] = "harness-error"
        raise
    finally:
        write_json(os.path.join(case_dir, "case-result.json"), result)


def run_route(
        recorder, route, source, scratch_root, manifest, candidate, candidate_name,
        install_dependencies, base_install_failures, run_first_goldens, fixture_info, run_dir):
    destination = os.path.join(scratch_root, route)
    copy_frozen_projection(source, destination, manifest)
    route_install_failures = []
    if route == "generated-c-no-cython":
        remove_returncode = recorder.run(
            "remove-cython-for-generated-c", [sys.executable, "-m", "pip", "uninstall", "-y", "Cython"]
        )
        if remove_returncode != 0:
            route_install_failures.append("Cython")
    elif route == "pyx-historical-cython":
        if install_dependencies:
            route_install_failures.extend(install_cython_candidate(recorder, candidate))
    else:
        raise ValueError("unknown route: {0}".format(route))
    version_probe_commands(recorder)
    candidate_version_returncode = run_candidate_version_gate(recorder, candidate, route)
    build_returncode = recorder.run("build-{0}".format(route), [sys.executable, "setup.py", "build"], cwd=destination)
    build_ext_returncode = recorder.run(
        "build-ext-inplace-{0}".format(route),
        [sys.executable, "setup.py", "build_ext", "--inplace"],
        cwd=destination
    )
    import_returncode = recorder.run(
        "import-smoke-{0}".format(route),
        [sys.executable, "-c", "import MUS; import MUSCython; import MUSCython.MultiStringBWTCython; print('IMPORT_SMOKE_OK')"],
        cwd=destination
    )
    cli_returncode = recorder.run(
        "cli-version-{0}".format(route),
        [sys.executable, "-c", CLI_MAIN, "--version"],
        cwd=destination
    )
    gate = {
        "build": build_returncode,
        "build_ext_inplace": build_ext_returncode,
        "cli_version": cli_returncode,
        "base_dependency_install": 0 if not base_install_failures else 1,
        "candidate_version": candidate_version_returncode,
        "route_dependency_install": 0 if not route_install_failures else 1,
        "import_smoke": import_returncode
    }
    dependency_install_failures = {
        "base": list(base_install_failures),
        "route": route_install_failures
    }
    route_result = {
        "dependency_install_failures": dependency_install_failures,
        "gate_returncodes": gate,
        "route": route
    }
    if run_first_goldens:
        route_result["first_golden"] = run_first_golden_case(
            recorder, route, candidate_name, destination, run_dir, fixture_info, gate,
            dependency_install_failures
        )
    return route_result


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="read-only repository root containing the frozen source projection")
    parser.add_argument("--results", required=True, help="parent directory for a newly created run record")
    parser.add_argument("--candidate", default="historical-source-claims", help="candidate key from --matrix")
    parser.add_argument("--matrix", default=DEFAULT_MATRIX, help="candidate matrix JSON")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="frozen source SHA-256 manifest")
    parser.add_argument("--route", choices=("all",) + ROUTES, default="all", help="build route to run")
    parser.add_argument("--install-dependencies", action="store_true", help="install the candidate packages before build probes")
    parser.add_argument(
        "--run-first-goldens",
        action="store_true",
        help="after successful build/import/CLI gates, run only the uniform-multifile pp/cfpp scenario"
    )
    parser.add_argument(
        "--fixture-root",
        help="synthetic fixture directory; required with --run-first-goldens and verified before any result directory is created"
    )
    parser.add_argument("--allow-failures", action="store_true", help="return zero after recording failed commands")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    matrix = read_json(args.matrix)
    candidate = matrix.get("candidates", {}).get(args.candidate)
    if candidate is None:
        raise SystemExit("unknown candidate: {0}".format(args.candidate))
    if candidate.get("status") != "candidate-only":
        raise SystemExit("refusing candidate without explicit candidate-only status")
    fixture_info = None
    if args.run_first_goldens:
        if not args.install_dependencies:
            raise SystemExit("--run-first-goldens requires --install-dependencies")
        if not args.fixture_root:
            raise SystemExit("--run-first-goldens requires --fixture-root")
        try:
            fixture_info = validate_first_golden_fixtures(args.fixture_root)
        except ValueError as exc:
            raise SystemExit("invalid first-golden fixtures: {0}".format(exc))
        if sys.version_info[:2] != (2, 7) or platform.python_implementation() != "CPython":
            raise SystemExit("--run-first-goldens requires CPython 2.7")

    run_dir = os.path.join(os.path.abspath(args.results), utc_run_id())
    ensure_directory(run_dir)
    write_json(os.path.join(run_dir, "candidate.json"), candidate)
    recorder = Recorder(run_dir)
    capture_host_metadata(recorder, run_dir)
    source = os.path.abspath(args.source)
    scratch_root = os.path.join(run_dir, "scratch")
    route_errors = []
    route_results = []
    base_install_failures = []
    try:
        source_mismatches = verify_frozen_source.verify(source, args.manifest)
        write_json(os.path.join(run_dir, "source-verification.json"), {
            "manifest": os.path.abspath(args.manifest),
            "mismatches": source_mismatches,
            "source": source,
            "valid": not source_mismatches
        })
        if source_mismatches:
            route_errors.append("source-verification-failed")
        else:
            if args.install_dependencies:
                base_install_failures = install_base_candidate(recorder, candidate)
            for route in resolve_routes(args.route):
                try:
                    route_results.append(run_route(
                        recorder, route, source, scratch_root, args.manifest,
                        candidate, args.candidate, args.install_dependencies,
                        base_install_failures, args.run_first_goldens, fixture_info, run_dir
                    ))
                except Exception as exc:
                    route_errors.append("{0}: {1}".format(route, exc))
                    with open(os.path.join(run_dir, "{0}.exception.txt".format(safe_component(route))), "wb") as handle:
                        handle.write(traceback.format_exc().encode("utf-8"))
    finally:
        failures = [record for record in recorder.records if record["returncode"] != 0]
        report = {
            "candidate": args.candidate,
            "candidate_status": candidate.get("status"),
            "base_dependency_install_failures": base_install_failures,
            "command_failures": len(failures),
            "commands": recorder.records,
            "routes": list(resolve_routes(args.route)),
            "route_errors": route_errors,
            "route_results": route_results,
            "source_commit": matrix.get("source_commit"),
            "status": "passed" if not failures and not route_errors else "failed"
        }
        write_json(os.path.join(run_dir, "report.json"), report)
    if report["status"] == "failed" and not args.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
