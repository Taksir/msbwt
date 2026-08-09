"""Strict integrity checks for post-uniform frozen-oracle goldens."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[2]
TOOL_PATH = REPOSITORY_ROOT / "compat" / "tools" / "artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("additional_artifact_manifest", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
artifact_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact_manifest)

PROFILE_ID = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
FIXTURE_MANIFEST_SHA256 = "7144c351057fe1acd8f8481a32fa560d9d85887e8f6d9d6a4140669f2d57eb97"
CASE_MANIFEST_SHA256 = "513f6957a06e4f1886d9499b4f1287f90a31d0d3e668971b4606bcb8536afc1a"
GOLDEN_BASE = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
FIXTURE_ROOT = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic"
CASE_MANIFEST = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "oracle-cases.json"
CASES = {
    "nonuniform-prefix": {
        "fixtures": {
            "nonuniform.fastq": "e19ef01c7683cd81534fada1f8142ddf35710a2e1bf9b70d92bb8de2acb1973e"
        },
        "stage_counts": {"pre": 2, "build": 3},
        "pre_tree": "71f549690de7b78b8b2979692f0594966cb33618e1f7e48c098a17ecc3ea31a7",
        "build_tree": "ad4aa043feb549e0af861ffde0deca11f8ac0b030c5305183f61f04f5f4d8c0a",
        "msbwt_sha256": "da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2",
        "shape": [30],
        "total_size": 30,
    },
    "gzip-input": {
        "fixtures": {
            "uniform-a.fastq.gz": "dc8bdc5aedc346f364e5e73a34734f61a55cb1b97f9788ac10ff774c16aaeadb",
            "nonuniform.fastq.gz": "93936b82d32a57dc8d1e7658fc8421ea61819db69414ac1464c5287e7148ccd8",
        },
        "stage_counts": {"pre": 2, "build": 3},
        "pre_tree": "e8e2d8d4c7f40019a3e20acdaba515514f00cdc06cba47056240628a678018c9",
        "build_tree": "188acea4cac12486c4c1a0d97ef618e807d3142e28cc266c56dda141d621bc8f",
        "msbwt_sha256": "da40d02ef42d4cf61d7b4814a2bc2c44c48f3516a53d6111a19bf2fdba8ff33b",
        "shape": [54],
        "total_size": 54,
    }
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class AdditionalCommittedGoldenTests(unittest.TestCase):
    def test_case_manifest_and_fixture_inputs_remain_exact(self) -> None:
        self.assertEqual(artifact_manifest.sha256_file(CASE_MANIFEST), CASE_MANIFEST_SHA256)
        fixture_manifest = FIXTURE_ROOT / "fixture-manifest.json"
        self.assertEqual(artifact_manifest.sha256_file(fixture_manifest), FIXTURE_MANIFEST_SHA256)
        for config in CASES.values():
            for fixture, fixture_sha256 in config["fixtures"].items():
                self.assertEqual(
                    artifact_manifest.sha256_file(FIXTURE_ROOT / fixture), fixture_sha256
                )

    def test_artifacts_provenance_determinism_and_reader_contract(self) -> None:
        for case_id, config in CASES.items():
            with self.subTest(case_id=case_id):
                root = GOLDEN_BASE / case_id / PROFILE_ID / ROUTE
                provenance = load_json(root / "provenance.json")
                determinism = load_json(root / "determinism-run-a-v-run-b.json")
                reader = load_json(root / "reader-smoke.json")

                self.assertEqual(provenance["case_id"], case_id)
                self.assertEqual(provenance["profile_id"], PROFILE_ID)
                self.assertEqual(provenance["route"], ROUTE)
                self.assertEqual(provenance["all_gate_returncodes"], 0)
                self.assertEqual(provenance["fixture_manifest_sha256"], FIXTURE_MANIFEST_SHA256)
                self.assertEqual(provenance["oracle_case_manifest_sha256"], CASE_MANIFEST_SHA256)
                self.assertNotIn(" -u ", " ".join(provenance["commands"]))
                self.assertEqual(
                    {
                        Path(item["path"]).name: item["sha256"]
                        for item in provenance["fixtures"]
                    },
                    config["fixtures"],
                )
                self.assertTrue(all(run["command_failures"] == 0 for run in provenance["runs"]))
                self.assertEqual(determinism["status"], "passed")
                self.assertEqual(determinism["runs"], ["run-a", "run-b"])

                for stage, tree_key in (("pre", "pre_tree"), ("build", "build_tree")):
                    expected = artifact_manifest.load_json(root / stage / "manifest.json")
                    actual = artifact_manifest.inventory_directory(root / stage / "artifacts")
                    comparison = artifact_manifest.compare_manifest(expected, actual)
                    self.assertTrue(comparison["matches"], comparison)
                    self.assertEqual(len(expected["artifacts"]), config["stage_counts"][stage])
                    stage_name = "preprocess" if stage == "pre" else "build"
                    self.assertTrue(determinism[stage_name]["matches"])
                    self.assertEqual(determinism[stage_name]["oracle_tree_sha256"], config[tree_key])
                    self.assertEqual(
                        determinism[stage_name]["manifest_content_sha256"],
                        expected["content_sha256"],
                    )

                build = artifact_manifest.load_json(root / "build" / "manifest.json")
                primary = next(item for item in build["artifacts"] if item["path"] == "msbwt.npy")
                self.assertEqual(primary["sha256"], config["msbwt_sha256"])
                self.assertEqual(primary["npy"]["dtype_descriptor"], "|u1")
                self.assertEqual(primary["npy"]["shape"], config["shape"])

                self.assertEqual(reader["status"], "passed")
                self.assertEqual(reader["format"], "msbwt-legacy-reader-smoke-v1")
                self.assertEqual(reader["actual_queries"], reader["expected_queries"])
                self.assertEqual(reader["actual_recovered_strings"], reader["expected_recovered_strings"])
                self.assertEqual(reader["total_size"], config["total_size"])
                self.assertEqual(
                    artifact_manifest.sha256_file(root / "reader-smoke.json"),
                    determinism["reader_smoke"]["result_sha256"],
                )
                self.assertTrue(determinism["reader_smoke"]["matches"])
                self.assertEqual(reader["side_effects"]["changed"], [])
                self.assertEqual(reader["side_effects"]["removed"], [])
                self.assertEqual(
                    {item["path"] for item in reader["side_effects"]["added"]},
                    {"fmIndex.npy", "totalCounts.npy"},
                )

                committed_text = (root / "provenance.json").read_text(encoding="utf-8") + (root / "reader-smoke.json").read_text(encoding="utf-8")
                self.assertNotIn("/home/", committed_text)
                self.assertNotIn("/mnt/", committed_text)


if __name__ == "__main__":
    unittest.main()
