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
FIXTURE_MANIFEST_SHA256 = "862187170b964062c4d31f45d2d88973dac793d46095ba8d7f742e74e6253358"
CASE_MANIFEST_SHA256 = "4757149711e322b56dd0cb8948066955e19c5724343d866e31c8df7a2eb15bd6"
GOLDEN_BASE = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
FIXTURE_ROOT = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic"
CASE_MANIFEST = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "oracle-cases.json"
CASES = {
    "nonuniform-prefix": {
        "fixture": "nonuniform.fastq",
        "fixture_sha256": "e19ef01c7683cd81534fada1f8142ddf35710a2e1bf9b70d92bb8de2acb1973e",
        "stage_counts": {"pre": 2, "build": 3},
        "pre_tree": "71f549690de7b78b8b2979692f0594966cb33618e1f7e48c098a17ecc3ea31a7",
        "build_tree": "ad4aa043feb549e0af861ffde0deca11f8ac0b030c5305183f61f04f5f4d8c0a",
        "msbwt_sha256": "da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2",
        "shape": [30],
        "total_size": 30,
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
            self.assertEqual(
                artifact_manifest.sha256_file(FIXTURE_ROOT / config["fixture"]),
                config["fixture_sha256"],
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
                self.assertEqual(reader["actual_queries"], reader["expected_queries"])
                self.assertEqual(reader["actual_recovered_strings"], reader["expected_recovered_strings"])
                self.assertEqual(reader["total_size"], config["total_size"])
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
