"""Read-only integrity checks for the first committed frozen-oracle golden."""

import importlib.util
import json
import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[2]
TOOL_PATH = REPOSITORY_ROOT / "compat" / "tools" / "artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("artifact_manifest", TOOL_PATH)
artifact_manifest = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(artifact_manifest)

SOURCE_COMMIT = "7503346ec072ddb89520db86fef85569a9ba093a"
PROFILE_ID = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
FIXTURE_MANIFEST_SHA256 = "862187170b964062c4d31f45d2d88973dac793d46095ba8d7f742e74e6253358"
EXPECTED_FIXTURES = {
    "compat/fixtures/synthetic/uniform-a.fastq": {
        "byte_count": 173,
        "sha256": "da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180",
    },
    "compat/fixtures/synthetic/uniform-b.fastq": {
        "byte_count": 162,
        "sha256": "04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029",
    },
}
STAGES = {"pre": 8, "build": 9}
MSBWT_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"

GOLDEN_ROOT = (
    REPOSITORY_ROOT
    / "compat"
    / "goldens"
    / "original-0.3.0"
    / "uniform-multifile"
    / PROFILE_ID
    / ROUTE
)
PROFILE_PATH = (
    REPOSITORY_ROOT
    / "compat"
    / "goldens"
    / "original-0.3.0"
    / "profiles"
    / (PROFILE_ID + ".json")
)
FIXTURE_MANIFEST_PATH = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic" / "fixture-manifest.json"
LOCK_ROOT = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "wsl" / "locks"
RECONSTRUCTION_SCRIPT = LOCK_ROOT.parent / "reconstruct-py27-late.sh"


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as source:
        return json.load(source)


class CommittedGoldenTests(unittest.TestCase):
    def test_reconstruction_bootstraps_locked_pip_before_full_wheel_lock(self):
        script = RECONSTRUCTION_SCRIPT.read_text(encoding="utf-8")
        bootstrap = script.index('expected_filename = \'pip-20.3.4-py2.py3-none-any.whl\'')
        version_gate = script.index('PIP_VERSION_OUTPUT=$("$PREFIX/bin/python" -m pip --version)')
        full_lock = script.index('--require-hashes --upgrade -r "$WHEEL_LOCK"')

        self.assertLess(bootstrap, version_gate)
        self.assertLess(version_gate, full_lock)
        self.assertIn('cd "$WORK_DIR"', script)
        self.assertIn("unset PYTHONHOME PYTHONPATH PYTHONUSERBASE", script)
        self.assertIn("export PYTHONNOUSERSITE=1", script)
        self.assertIn("export PIP_CONFIG_FILE=/dev/null", script)
        self.assertIn("curl --disable --fail", script)
        self.assertIn("--no-deps --only-binary=:all: --no-index --upgrade", script)
        self.assertNotIn("217ae5161a0e08c0fb873858806e3478c9775caffce5168b50ec885e358c199d", script)

    def test_environment_locks_match_verified_profile(self):
        profile = load_json(PROFILE_PATH)
        conda_lock = load_json(LOCK_ROOT / (PROFILE_ID + "-conda-sha256.json"))
        explicit_lines = [
            line
            for line in (LOCK_ROOT / (PROFILE_ID + "-conda-explicit.txt")).read_text(
                encoding="utf-8"
            ).splitlines()
            if line and not line.startswith("#") and line != "@EXPLICIT"
        ]

        self.assertEqual(conda_lock["profile_id"], PROFILE_ID)
        self.assertEqual(len(conda_lock["packages"]), 32)
        self.assertEqual(
            conda_lock["excluded_superseded_records"],
            {"pip": "20.0.2", "setuptools": "44.0.0", "wheel": "0.34.2"},
        )
        expected_explicit = {
            package["url"] + "#" + package["md5"] for package in conda_lock["packages"]
        }
        self.assertEqual(set(explicit_lines), expected_explicit)
        self.assertTrue(
            all(
                package["url"].startswith("https://")
                and re.fullmatch(r"[0-9a-f]{32}", package["md5"])
                and re.fullmatch(r"[0-9a-f]{64}", package["sha256"])
                for package in conda_lock["packages"]
            )
        )

        wheel_records = {}
        for line in (LOCK_ROOT / (PROFILE_ID + "-wheels.txt")).read_text(
            encoding="utf-8"
        ).splitlines():
            if not line or line.startswith("#"):
                continue
            name, remainder = line.split(" @ ", 1)
            url, digest = remainder.split(" --hash=sha256:", 1)
            wheel_records[name.lower()] = (url, digest)
        expected_wheels = {
            package["name"].lower(): (package["artifact_url"], package["artifact_sha256"])
            for package in profile["python_packages"]
        }
        self.assertEqual(wheel_records, expected_wheels)

    def test_stage_artifacts_match_committed_manifests(self):
        for stage, expected_count in STAGES.items():
            stage_root = GOLDEN_ROOT / stage
            expected = artifact_manifest.load_json(stage_root / "manifest.json")
            actual = artifact_manifest.inventory_directory(stage_root / "artifacts")
            comparison = artifact_manifest.compare_manifest(expected, actual)

            self.assertTrue(comparison["matches"], comparison)
            self.assertIsNone(comparison["expected_integrity_error"])
            self.assertIsNone(comparison["actual_integrity_error"])
            self.assertEqual(len(expected["artifacts"]), expected_count)
            self.assertEqual(len(actual["artifacts"]), expected_count)
            self.assertTrue(all(entry["type"] == "file" for entry in expected["artifacts"]))
            self.assertTrue(all(entry["type"] == "file" for entry in actual["artifacts"]))
            self.assertFalse(any("npy_error" in entry for entry in expected["artifacts"]))
            self.assertFalse(any("npy_error" in entry for entry in actual["artifacts"]))

    def test_profile_provenance_and_fixture_contract_are_exact(self):
        profile = load_json(PROFILE_PATH)
        provenance = load_json(GOLDEN_ROOT / "provenance.json")
        fixture_manifest = load_json(FIXTURE_MANIFEST_PATH)

        self.assertEqual(profile["format"], "msbwt-legacy-oracle-profile-v1")
        self.assertEqual(profile["profile_id"], PROFILE_ID)
        self.assertEqual(profile["profile_id_derivation"]["full_sha256"][:12], "05a7d6d83862")
        self.assertEqual(profile["python"]["implementation"], "CPython")
        self.assertTrue(profile["python"]["version"].startswith("2.7."))
        self.assertEqual(profile["source"]["commit"], SOURCE_COMMIT)
        self.assertFalse(profile["source"]["modified"])

        self.assertEqual(provenance["format"], "msbwt-legacy-golden-provenance-v1")
        self.assertEqual(provenance["case_id"], "uniform-multifile")
        self.assertEqual(provenance["profile_id"], profile["profile_id"])
        self.assertEqual(provenance["route"], ROUTE)
        self.assertEqual(provenance["source_commit"], profile["source"]["commit"])
        self.assertEqual(provenance["interpreter_gate"], "CPython 2.7")
        self.assertEqual(provenance["fixture_manifest_sha256"], FIXTURE_MANIFEST_SHA256)
        self.assertEqual(artifact_manifest.sha256_file(FIXTURE_MANIFEST_PATH), FIXTURE_MANIFEST_SHA256)
        self.assertEqual(provenance["all_gate_returncodes"], 0)

        manifest_fixtures = {
            "compat/fixtures/synthetic/" + entry["path"]: entry
            for entry in fixture_manifest["files"]
        }
        self.assertEqual({entry["path"] for entry in provenance["fixtures"]}, set(EXPECTED_FIXTURES))
        for fixture in provenance["fixtures"]:
            expected = EXPECTED_FIXTURES[fixture["path"]]
            manifest_entry = manifest_fixtures[fixture["path"]]
            fixture_path = REPOSITORY_ROOT / fixture["path"]
            self.assertEqual(fixture["byte_count"], expected["byte_count"])
            self.assertEqual(fixture["sha256"], expected["sha256"])
            self.assertEqual(manifest_entry["byte_count"], expected["byte_count"])
            self.assertEqual(manifest_entry["sha256"], expected["sha256"])
            self.assertEqual(fixture_path.stat().st_size, expected["byte_count"])
            self.assertEqual(artifact_manifest.sha256_file(fixture_path), expected["sha256"])

    def test_determinism_and_primary_bwt_contract(self):
        provenance = load_json(GOLDEN_ROOT / "provenance.json")
        determinism = load_json(GOLDEN_ROOT / "determinism-run-b-v-run-c.json")
        build_manifest = artifact_manifest.load_json(GOLDEN_ROOT / "build" / "manifest.json")

        self.assertEqual(determinism["format"], "msbwt-legacy-determinism-comparison-v1")
        self.assertEqual(determinism["runs"], ["run-b", "run-c"])
        self.assertEqual(determinism["status"], "passed")
        for stage, provenance_key in (
            ("preprocess", "preprocess_oracle_tree_sha256"),
            ("build", "build_oracle_tree_sha256"),
        ):
            stage_result = determinism[stage]
            self.assertTrue(stage_result["matches"])
            self.assertEqual(stage_result["added"], [])
            self.assertEqual(stage_result["changed"], [])
            self.assertEqual(stage_result["removed"], [])
            self.assertEqual(stage_result["oracle_tree_sha256"], provenance[provenance_key])

        self.assertEqual(
            determinism["preprocess"]["manifest_content_sha256"],
            artifact_manifest.load_json(GOLDEN_ROOT / "pre" / "manifest.json")["content_sha256"],
        )
        self.assertEqual(
            determinism["build"]["manifest_content_sha256"],
            build_manifest["content_sha256"],
        )
        primary = next(entry for entry in build_manifest["artifacts"] if entry["path"] == "msbwt.npy")
        self.assertEqual(primary["type"], "file")
        self.assertEqual(primary["sha256"], MSBWT_SHA256)
        self.assertEqual(primary["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(primary["npy"]["shape"], [48])


if __name__ == "__main__":
    unittest.main()
