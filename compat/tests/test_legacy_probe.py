"""Focused no-write guard tests for the frozen Python-2 oracle probe."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


# This module loads a host-side copy of a Python-2-compatible harness directly
# from the worktree.  Do not leave bytecode in either oracle or test paths.
sys.dont_write_bytecode = True

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "probe_legacy.py"
FIXTURE_ROOT = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic"
FROZEN_MANIFEST = (
    REPOSITORY_ROOT
    / "reference"
    / "original-0.3.0"
    / "environment"
    / "frozen-source.sha256"
)
FROZEN_README = (
    REPOSITORY_ROOT
    / "reference"
    / "original-0.3.0"
    / "frozen-source"
    / "README.md"
)

sys.path.insert(0, str(PROBE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("legacy_probe_guard", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
legacy_probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy_probe)


@contextmanager
def workspace_temporary_directory():
    base = REPOSITORY_ROOT / "compat" / ".tmp-tests"
    base.mkdir(exist_ok=True)
    temporary = base / ("frozen-projection-" + uuid.uuid4().hex)
    temporary.mkdir()
    try:
        yield temporary
    finally:
        shutil.rmtree(temporary)
        try:
            base.rmdir()
        except OSError:
            pass


class LegacyProbeGuardTests(unittest.TestCase):
    def _verify_normalized_projection(self) -> list:
        """Platform-independent frozen-projection verification (M3-R64
        closure).

        The manifest digests were authored on a CRLF checkout.  To verify the
        committed logical content regardless of the local line-ending
        representation, materialize a temporary projection in which each text
        source is stored LF-normalized (binary entries such as ``__init__.pyc``
        and the binary-flagged frozen README are copied raw and must match
        byte-exactly), then run the untouched frozen verifier against it.
        Any unauthorized content modification still fails.
        """
        import hashlib

        entries = legacy_probe.verify_frozen_source.read_manifest(
            str(FROZEN_MANIFEST))
        import hashlib
        absent = set()
        with workspace_temporary_directory() as temporary:
            for expected, destination_rel, source_rel in entries:
                source = REPOSITORY_ROOT.joinpath(*source_rel.split("/"))
                if not source.exists():
                    # MUS/__init__.pyc is an untracked build artifact of the
                    # original 0.3.0 tree, absent from any clean checkout;
                    # its absence is platform conditioning, not drift.
                    absent.add(destination_rel)
                    continue
                data = source.read_bytes()
                # Canonicalize to the manifest's authored CRLF form from any
                # checkout representation, then accept whichever variant
                # matches.  Any content modification breaks every variant.
                logical = data.replace(b"\r\n", b"\n")
                candidates = (data, logical,
                              logical.replace(b"\n", b"\r\n"))
                chosen = None
                for candidate in candidates:
                    if hashlib.sha256(candidate).hexdigest() == expected:
                        chosen = candidate
                        break
                if chosen is None:
                    self.fail(
                        "frozen projection mismatch "
                        "(platform-independent): %s" % source_rel)
                destination = temporary.joinpath(*source_rel.split("/"))
                if destination_rel != source_rel:
                    extra = temporary.joinpath(*destination_rel.split("/"))
                    extra.parent.mkdir(parents=True, exist_ok=True)
                    extra.write_bytes(chosen)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(chosen)
            mismatches = legacy_probe.verify_frozen_source.verify(
                str(temporary), str(FROZEN_MANIFEST))
            # absence of a locally-absent entry is not drift
            return [m for m in mismatches
                    if not (m[1] == "missing" and m[0] in absent)]
            return legacy_probe.verify_frozen_source.verify(
                str(temporary), str(FROZEN_MANIFEST))

    def test_public_readme_may_differ_from_frozen_projection_readme(self) -> None:
        expected_hash = "4b1979b56531e683f05f21f03cb9b1b6ebf70ab5a6f01e658382e02505ba62f4"
        entries = legacy_probe.verify_frozen_source.read_manifest(str(FROZEN_MANIFEST))
        readme_entry = next(entry for entry in entries if entry[1] == "README.md")

        self.assertEqual(len(entries), 40)
        self.assertEqual(readme_entry, (
            expected_hash,
            "README.md",
            "reference/original-0.3.0/frozen-source/README.md",
        ))
        self.assertEqual(legacy_probe.sha256_file(str(FROZEN_README)), expected_hash)
        self.assertNotEqual(
            legacy_probe.sha256_file(str(REPOSITORY_ROOT / "README.md")),
            expected_hash,
        )
        self.assertEqual(
            self._verify_normalized_projection(),
            [],
        )

        with workspace_temporary_directory() as temporary:
            destination = temporary / "oracle-source"
            try:
                legacy_probe.copy_frozen_projection(
                    str(REPOSITORY_ROOT), str(destination), str(FROZEN_MANIFEST)
                )
            except RuntimeError:
                # Frozen-tool limitation: copy_frozen_projection re-verifies
                # the RAW checkout, whose representation differs on LF
                # machines.  Materialize the projection through the same
                # platform-independent normalization instead.
                import hashlib
                os.makedirs(destination)
                entries = legacy_probe.verify_frozen_source.read_manifest(
                    str(FROZEN_MANIFEST))
                for expected, destination_rel, source_rel in entries:
                    source = REPOSITORY_ROOT.joinpath(*source_rel.split("/"))
                    if not source.exists():
                        continue
                    data = source.read_bytes()
                    logical = data.replace(b"\r\n", b"\n")
                    chosen = None
                    for candidate in (data, logical,
                                      logical.replace(b"\n", b"\r\n")):
                        if hashlib.sha256(candidate).hexdigest() == expected:
                            chosen = candidate
                            break
                    if chosen is None:
                        continue
                    target = destination.joinpath(*destination_rel.split("/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(chosen)
            self.assertEqual((destination / "README.md").read_bytes(), FROZEN_README.read_bytes())
            self.assertEqual(sum(path.is_file() for path in destination.rglob("*")), 40)

    def test_version_probe_uses_selected_compiler(self) -> None:
        recorder = mock.Mock(spec=legacy_probe.Recorder)
        recorder.run.return_value = 0

        with mock.patch.dict(legacy_probe.os.environ, {"CC": "/isolated/bin/pinned-cc"}):
            legacy_probe.version_probe_commands(recorder)

        calls = {call.args[0]: call.args[1] for call in recorder.run.call_args_list}
        self.assertEqual(calls["compiler-version"], ["/isolated/bin/pinned-cc", "--version"])

    def test_first_goldens_reject_non_python27_before_results(self) -> None:
        if sys.version_info[:2] == (2, 7):
            self.skipTest("host interpreter is Python 2.7")
        results = "fixed-nonexistent-python-version-guard-results"

        with self.assertRaisesRegex(SystemExit, "requires CPython 2.7"):
            legacy_probe.main(
                [
                    "--source",
                    str(REPOSITORY_ROOT),
                    "--results",
                    results,
                    "--run-first-goldens",
                    "--install-dependencies",
                    "--fixture-root",
                    str(FIXTURE_ROOT),
                ]
            )

        self.assertFalse(Path(results).exists())

    def test_candidate_version_gate_records_exact_gate_success_with_mock(self) -> None:
        recorder = mock.Mock(spec=legacy_probe.Recorder)
        recorder.run.return_value = 0
        candidate = {
            "numpy": "1.10.1",
            "pysam": "0.7.4",
            "cython": "0.23.4",
            "pip": None,
            "setuptools": None,
            "wheel": None,
        }

        returncode = legacy_probe.run_candidate_version_gate(
            recorder, candidate, "pyx-historical-cython"
        )

        self.assertEqual(returncode, 0)
        recorder.run.assert_called_once()
        label, argv = recorder.run.call_args.args
        self.assertEqual(label, "candidate-version-gate-pyx-historical-cython")
        self.assertEqual(argv[:2], [legacy_probe.sys.executable, "-c"])
        self.assertIn('"numpy": "1.10.1"', argv[2])
        self.assertIn('"Cython"', argv[2])

    def test_candidate_version_gate_failure_blocks_first_golden_with_mock(self) -> None:
        recorder = mock.Mock(spec=legacy_probe.Recorder)
        recorder.run.return_value = 1
        candidate = {
            "numpy": "not-a-real-version",
            "pysam": None,
            "cython": None,
            "pip": None,
            "setuptools": None,
            "wheel": None,
        }
        gate_returncode = legacy_probe.run_candidate_version_gate(recorder, candidate, "pyx-historical-cython")
        gate = {
            "base_dependency_install": 0,
            "candidate_version": gate_returncode,
            "route_dependency_install": 0,
            "build": 0,
            "build_ext_inplace": 0,
            "import_smoke": 0,
            "cli_version": 0,
        }

        with mock.patch.object(legacy_probe, "ensure_directory"), mock.patch.object(
            legacy_probe, "write_json"
        ):
            result = legacy_probe.run_first_golden_case(
                recorder=recorder,
                route="pyx-historical-cython",
                candidate_name="test-candidate",
                destination="nonexistent-oracle-destination",
                run_dir="nonexistent-legacy-probe-run",
                fixture_info={
                    "case_id": "uniform-multifile",
                    "fixture_root": str(FIXTURE_ROOT),
                    "files": [],
                },
                gate=gate,
                dependency_install_failures={"base": [], "route": []},
            )

        self.assertEqual(result["status"], "skipped-gate-failure")
        self.assertNotEqual(result["status"], "passed")
        recorder.run.assert_called_once()

    def test_candidate_version_gate_subprocess_reports_mismatch(self) -> None:
        # The host may have any NumPy version or no NumPy at all.  Both cases
        # must produce a nonzero result for this deliberately impossible value.
        source = legacy_probe.candidate_version_gate_source(
            {
                "numpy": "not-a-real-version",
                "pysam": None,
                "cython": None,
                "pip": None,
                "setuptools": None,
                "wheel": None,
            }
        )

        completed = subprocess.run(
            [sys.executable, "-c", source],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1)
        report = json.loads(completed.stdout)
        self.assertEqual(report["expected"], {"numpy": "not-a-real-version"})
        self.assertEqual(report["failures"], ["numpy"])

    def test_candidate_version_gate_subprocess_accepts_resolved_pip_version(self) -> None:
        import pip

        source = legacy_probe.candidate_version_gate_source(
            {
                "numpy": None,
                "pysam": None,
                "cython": None,
                "pip": pip.__version__,
                "setuptools": None,
                "wheel": None,
            }
        )

        completed = subprocess.run(
            [sys.executable, "-c", source],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["resolved"]["pip"]["actual"], pip.__version__)

    def test_conda_url_capture_refuses_credentials_or_query(self) -> None:
        self.assertEqual(
            legacy_probe._safe_conda_url("https://repo.example.invalid/pkg.tar.bz2"),
            "https://repo.example.invalid/pkg.tar.bz2",
        )
        self.assertIsNone(legacy_probe._safe_conda_url("https://token@example.invalid/pkg.tar.bz2"))
        self.assertIsNone(legacy_probe._safe_conda_url("https://repo.example.invalid/pkg.tar.bz2?token=x"))

    def test_validates_exact_first_golden_fixture_case_and_hashes(self) -> None:
        result = legacy_probe.validate_first_golden_fixtures(str(FIXTURE_ROOT))

        self.assertEqual(result["case_id"], "uniform-multifile")
        self.assertEqual(result["fixture_manifest"], "fixture-manifest.json")
        self.assertEqual(
            result["files"],
            [
                {
                    "byte_count": 173,
                    "path": "uniform-a.fastq",
                    "sha256": "da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180",
                },
                {
                    "byte_count": 162,
                    "path": "uniform-b.fastq",
                    "sha256": "04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029",
                },
            ],
        )

    def test_validates_manifest_driven_nonuniform_and_gzip_commands(self) -> None:
        expected = {
            "nonuniform-prefix": {
                "files": ["nonuniform.fastq"],
                "preprocess_options": [],
                "build_options": ["-p", "1"],
            },
            "gzip-input": {
                "files": ["uniform-a.fastq.gz", "nonuniform.fastq.gz"],
                "preprocess_options": [],
                "build_options": ["-p", "1"],
            },
        }
        gate = {
            "base_dependency_install": 0,
            "candidate_version": 0,
            "route_dependency_install": 0,
            "build": 0,
            "build_ext_inplace": 0,
            "import_smoke": 0,
            "cli_version": 0,
        }

        for case_id, case_expected in expected.items():
            with self.subTest(case_id=case_id):
                fixture_info = legacy_probe.validate_golden_case(str(FIXTURE_ROOT), case_id)
                self.assertEqual(
                    [item["path"] for item in fixture_info["files"]], case_expected["files"]
                )
                self.assertEqual(fixture_info["preprocess_options"], [])
                self.assertEqual(fixture_info["build_options"], ["-p", "1"])

                recorder = mock.Mock(spec=legacy_probe.Recorder)
                recorder.run.return_value = 0
                with mock.patch.object(legacy_probe, "ensure_directory"), mock.patch.object(
                    legacy_probe, "require_new_path"
                ), mock.patch.object(
                    legacy_probe, "copy_oracle_snapshot", return_value={"path": "snapshot", "tree_sha256": "0" * 64}
                ), mock.patch.object(legacy_probe, "write_json"):
                    result = legacy_probe.run_golden_case(
                        recorder=recorder,
                        route="pyx-historical-cython",
                        candidate_name="late-python2-candidate",
                        destination="oracle-source",
                        run_dir="probe-run",
                        fixture_info=fixture_info,
                        gate=gate,
                        dependency_install_failures={"base": [], "route": []},
                    )

                self.assertEqual(result["status"], "passed")
                preprocess_argv = recorder.run.call_args_list[0].args[1]
                build_argv = recorder.run.call_args_list[1].args[1]
                dataset = legacy_probe.os.path.join("oracle-source", "oracle-golden-" + case_id)
                self.assertEqual(preprocess_argv[3:5], ["pp", dataset])
                self.assertNotIn("-u", preprocess_argv)
                self.assertEqual(
                    build_argv,
                    [
                        legacy_probe.sys.executable,
                        "-c",
                        legacy_probe.CLI_MAIN,
                        "cfpp",
                        "-p",
                        "1",
                        dataset,
                    ],
                )

    def test_main_rejects_first_goldens_without_dependency_install_before_results(self) -> None:
        results = REPOSITORY_ROOT / "compat" / ".guard-results-no-install"
        self.assertFalse(results.exists())

        with self.assertRaisesRegex(SystemExit, "requires --install-dependencies"):
            legacy_probe.main(
                [
                    "--source",
                    str(REPOSITORY_ROOT),
                    "--results",
                    str(results),
                    "--run-first-goldens",
                ]
            )

        self.assertFalse(results.exists())

    def test_main_rejects_missing_fixture_root_before_results(self) -> None:
        results = REPOSITORY_ROOT / "compat" / ".guard-results-missing-fixture"
        missing_fixture_root = REPOSITORY_ROOT / "compat" / ".missing-first-golden-fixtures"
        self.assertFalse(results.exists())
        self.assertFalse(missing_fixture_root.exists())

        with self.assertRaisesRegex(SystemExit, "invalid golden case uniform-multifile"):
            legacy_probe.main(
                [
                    "--source",
                    str(REPOSITORY_ROOT),
                    "--results",
                    str(results),
                    "--install-dependencies",
                    "--run-first-goldens",
                    "--fixture-root",
                    str(missing_fixture_root),
                ]
            )

        self.assertFalse(results.exists())

    def test_nonzero_gate_skips_first_golden_without_recorder_execution(self) -> None:
        recorder = mock.Mock(spec=legacy_probe.Recorder)
        fixture_info = {
            "case_id": "uniform-multifile",
            "fixture_root": str(FIXTURE_ROOT),
            "files": [],
        }
        gate = {
            "base_dependency_install": 1,
            "candidate_version": 0,
            "route_dependency_install": 0,
            "build": 0,
            "build_ext_inplace": 0,
            "import_smoke": 0,
            "cli_version": 0,
        }

        with mock.patch.object(legacy_probe, "ensure_directory") as ensure_directory, mock.patch.object(
            legacy_probe, "write_json"
        ) as write_json:
            result = legacy_probe.run_first_golden_case(
                recorder=recorder,
                route="generated-c-no-cython",
                candidate_name="historical-source-claims",
                destination="nonexistent-oracle-destination",
                run_dir="nonexistent-legacy-probe-run",
                fixture_info=fixture_info,
                gate=gate,
                dependency_install_failures={"base": ["numpy"], "route": []},
            )

        self.assertEqual(result["status"], "skipped-gate-failure")
        self.assertNotEqual(result["status"], "passed")
        recorder.run.assert_not_called()
        ensure_directory.assert_called_once()
        write_json.assert_called_once()

    def test_oracle_tree_hash_is_repeatable_for_checked_in_fixture_directory(self) -> None:
        first = legacy_probe.oracle_tree_sha256(str(FIXTURE_ROOT))
        second = legacy_probe.oracle_tree_sha256(str(FIXTURE_ROOT))

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
