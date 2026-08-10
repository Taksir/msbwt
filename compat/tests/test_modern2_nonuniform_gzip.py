"""Host-side regression tests for msbwt-modern2 milestone 8: nonuniform
construction + gzip input end-to-end.

These tests are read-only and run on any CPython 3; they validate the
executed evidence record, the committed legacy golden contracts, the
migrated `MultimergeCython` source policy, and the exact modern2-vs-frozen
diff whitelist.
"""

import difflib
import hashlib
import json
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
EVIDENCE = PACKAGE / "evidence" / "nonuniform-gzip-milestone8.json"
DRIVER = PACKAGE / "validate" / "nonuniform-gzip-milestone8.sh"
GOLDENS = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
PROFILE = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"

# committed legacy contracts (from the golden manifests and reader smoke)
NONUNIFORM_PRE = {
    "offsets.npy": ("da7fcb73c1fa0bdc0c84ee2f137e566ce2ba506a15aad58c2358d8c446e6d08e", 64),
    "seqs.npy": ("f4239e43bfeffcfa48e4439b27faafa670dc6f16b117e8a92b3d3f7a4bbff303", 30),
}
NONUNIFORM_BUILD = {
    "msbwt.npy": ("da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2", 158),
    "offsets.npy": NONUNIFORM_PRE["offsets.npy"],
    "seqs.npy": NONUNIFORM_PRE["seqs.npy"],
}
NONUNIFORM_PAYLOAD = "7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03"
NONUNIFORM_SIDE_EFFECTS = {
    "fmIndex.npy": ("fc626114ba15fd9a1b242c1671aa5ea166492393d76b1ba840ce93859950cd0c", 176),
    "totalCounts.npy": ("2959abbf39535b8c8b4a080d8d3f3458ec0e4eadc9e2aa478156e84361af6f5c", 176),
}
GZIP_PRE = {
    "offsets.npy": ("9f96565f1486a66ea7726b0f8cb68da50871469c1e16f99b2a800573cc1f6194", 96),
    "seqs.npy": ("605c199e1023112d5e113dc1a4f9761b66d52937d2d56eeeaad4d51521ecf8c9", 54),
}
GZIP_BUILD = {
    "msbwt.npy": ("da40d02ef42d4cf61d7b4814a2bc2c44c48f3516a53d6111a19bf2fdba8ff33b", 182),
    "offsets.npy": GZIP_PRE["offsets.npy"],
    "seqs.npy": GZIP_PRE["seqs.npy"],
}
GZIP_PAYLOAD = "13c687364c3ca7ebae5379d4f8d9814d880616dd23968fdfa2c2697ced9f24ee"
GZIP_SIDE_EFFECTS = {
    "fmIndex.npy": ("9207663ec63508a3dd5dfc179f3963ac5aa2b5e046ed84dee6de5fd049cf82d4", 176),
    "totalCounts.npy": ("d5a953fe54e57854b58000639cbc29511f93736abf57819b7ee87f54ea54911f", 176),
}
COMPRESSED_GOLDEN = "9d19222eaa78c1d89304e79ff14a8a0a5f0c21c3ae979d179f570f1d8d5c1e66"
FROZEN_MULTIMERGE_PYX = "9c591c05697a662a0f0a7fb78b0afd609e7a567afb4ed182d926fca0726859cb"
FROZEN_MULTISTRINGBWT = "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unified_added_removed(frozen: Path, modern: Path):
    frozen_text = frozen.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    modern_text = modern.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    diff = list(difflib.unified_diff(
        frozen_text.splitlines(), modern_text.splitlines(), lineterm=""))
    added = [line[1:] for line in diff
             if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff
               if line.startswith("-") and not line.startswith("---")]
    return added, removed


def committed_manifest(case: str, stage: str) -> dict:
    path = GOLDENS / case / PROFILE / ROUTE / stage / "manifest.json"
    return load_json(path)


def committed_smoke(case: str) -> dict:
    path = GOLDENS / case / PROFILE / ROUTE / "reader-smoke.json"
    return load_json(path)


class ValidationDriverTests(unittest.TestCase):
    def test_driver_present_and_uses_independent_tooling(self):
        text = DRIVER.read_text(encoding="utf-8")
        self.assertIn("nonuniform-gzip-milestone8", text)
        self.assertIn("artifact_manifest.py", text)
        self.assertIn("bwt_oracle.py", text)
        self.assertIn("--evidence", text)
        self.assertIn("gate_compress_roundtrip", text)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "modern2-milestone8-nonuniform-gzip")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["py2_tests"]["status"], "ok")

    def test_evidence_tree_hashes_match_committed_manifests(self):
        evidence = load_json(EVIDENCE)
        for evidence_key, case, pre, build in (
                ("nonuniform", "nonuniform-prefix", NONUNIFORM_PRE, NONUNIFORM_BUILD),
                ("gzip", "gzip-input", GZIP_PRE, GZIP_BUILD)):
            pre_tree = dict(
                (line.split()[-1], (line.split()[0], int(line.split()[1])))
                for line in evidence[evidence_key]["pre_tree"])
            build_tree = dict(
                (line.split()[-1], (line.split()[0], int(line.split()[1])))
                for line in evidence[evidence_key]["build_tree"])
            self.assertEqual(pre_tree, pre, case)
            self.assertEqual(build_tree, build, case)

    def test_evidence_primary_headers_and_payloads(self):
        evidence = load_json(EVIDENCE)
        for evidence_key, case, payload, shape in (
                ("nonuniform_primary", "nonuniform-prefix", NONUNIFORM_PAYLOAD, "(30,)"),
                ("gzip_primary", "gzip-input", GZIP_PAYLOAD, "(54,)")):
            primary = evidence[evidence_key]
            self.assertEqual(primary["payload_sha256"], payload, case)
            self.assertIn(shape, primary["header_text"], case)
            self.assertIn("'descr': '|u1'", primary["header_text"], case)
            self.assertEqual(primary["header_len"], 118, case)

    def test_evidence_reader_matches_committed_smoke(self):
        evidence = load_json(EVIDENCE)
        for evidence_key, case, side_effects in (
                ("nonuniform_reader", "nonuniform-prefix", NONUNIFORM_SIDE_EFFECTS),
                ("gzip_reader", "gzip-input", GZIP_SIDE_EFFECTS)):
            reader = evidence[evidence_key]
            smoke = committed_smoke(case)
            self.assertEqual(reader["reader_class"],
                             "MUSCython.ByteBWTCython.ByteBWT", case)
            self.assertEqual(reader["total_size"], smoke["total_size"], case)
            self.assertEqual(reader["dollar_count"], smoke["dollar_count"],
                             case)
            self.assertTrue(reader["side_effects_match_committed"], case)
            self.assertTrue(reader["queries_match_committed"], case)
            self.assertTrue(reader["recovery_matches_committed"], case)
            self.assertTrue(reader["regeneration_bytes_identical"], case)
            self.assertEqual(reader["added_files"],
                             {name: {"sha256": digest, "size": size}
                              for name, (digest, size) in side_effects.items()},
                             case)

    def test_evidence_oracle_all_kmers_match(self):
        evidence = load_json(EVIDENCE)
        oracle = evidence["oracle"]
        for case in ("nonuniform-prefix", "gzip-input"):
            self.assertEqual(oracle[case]["mismatch_count"], 0, case)
            smoke = committed_smoke(case)
            self.assertEqual(oracle[case]["kmers_checked"],
                             len(smoke["expected_queries"]), case)

    def test_evidence_determinism_p2_and_compress_roundtrip(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(
            evidence["determinism"],
            {"nonuniform-prefix": "run-a == run-b byte-identical",
             "gzip-input": "run-a == run-b byte-identical"})
        self.assertEqual(
            evidence["p2"],
            {"nonuniform-prefix": "byte-identical to -p 1",
             "gzip-input": "byte-identical to -p 1"})
        self.assertIn("9d19222e", evidence["compress_roundtrip"]["status"])

    def test_evidence_source_policy(self):
        evidence = load_json(EVIDENCE)
        source = evidence["source"]
        self.assertEqual(source["frozen_MultimergeCython_pyx_sha256"],
                         FROZEN_MULTIMERGE_PYX)
        self.assertEqual(source["frozen_MultiStringBWT_py_sha256"],
                         FROZEN_MULTISTRINGBWT)
        self.assertEqual(source["pyx_diff_added"],
                         ["#cython: language_level=2"])
        self.assertEqual(source["pyx_diff_removed"], [])


class SourcePolicyTests(unittest.TestCase):
    def test_frozen_original_untouched(self):
        frozen_pyx = REPOSITORY_ROOT / "MUSCython" / "MultimergeCython.pyx"
        self.assertEqual(sha256_bytes(frozen_pyx.read_bytes()),
                         FROZEN_MULTIMERGE_PYX)
        frozen_msw = REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py"
        self.assertEqual(sha256_bytes(frozen_msw.read_bytes()),
                         FROZEN_MULTISTRINGBWT)

    def test_modern2_multimerge_pyx_diff_is_language_level_only(self):
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUSCython" / "MultimergeCython.pyx",
            PACKAGE / "MUSCython" / "MultimergeCython.pyx")
        self.assertEqual(added, ["#cython: language_level=2"])
        self.assertEqual(removed, [])

    def test_modern2_stub_removed(self):
        self.assertFalse((PACKAGE / "MUSCython" / "MultimergeCython.py").exists())
        self.assertTrue((PACKAGE / "MUSCython" / "MultimergeCython.pyx").exists())

    def test_setup_builds_multimerge(self):
        text = (PACKAGE / "setup.py").read_text(encoding="utf-8")
        self.assertIn("'MultimergeCython'", text)

    def test_existing_diff_whitelists_unchanged(self):
        # the MultiStringBWT.py whitelist (5 correction sites, 7/6) must not
        # have moved
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py",
            PACKAGE / "MUS" / "MultiStringBWT.py")
        self.assertEqual(len(added), 7)
        self.assertEqual(len(removed), 6)


class CommittedGoldenTests(unittest.TestCase):
    def test_committed_manifests_match_expected_contracts(self):
        # the committed golden manifests are the byte contract; these tests
        # pin the exact expected values the modern2 route must reproduce
        for case, pre, build in (
                ("nonuniform-prefix", NONUNIFORM_PRE, NONUNIFORM_BUILD),
                ("gzip-input", GZIP_PRE, GZIP_BUILD)):
            manifest = committed_manifest(case, "pre")
            actual = dict(
                (entry["path"], (entry["sha256"], entry["size"]))
                for entry in manifest["artifacts"])
            self.assertEqual(actual, pre, case)
            manifest = committed_manifest(case, "build")
            actual = dict(
                (entry["path"], (entry["sha256"], entry["size"]))
                for entry in manifest["artifacts"])
            self.assertEqual(actual, build, case)

    def test_committed_msbwt_payloads(self):
        for case, payload in (
                ("nonuniform-prefix", NONUNIFORM_PAYLOAD),
                ("gzip-input", GZIP_PAYLOAD)):
            manifest = committed_manifest(case, "build")
            entry = next(e for e in manifest["artifacts"]
                         if e["path"] == "msbwt.npy")
            self.assertEqual(entry["npy"]["payload_sha256"], payload, case)
            self.assertEqual(entry["npy"]["dtype_descriptor"], "|u1", case)

    def test_committed_smoke_side_effects(self):
        for case, side_effects in (
                ("nonuniform-prefix", NONUNIFORM_SIDE_EFFECTS),
                ("gzip-input", GZIP_SIDE_EFFECTS)):
            smoke = committed_smoke(case)
            actual = dict(
                (entry["path"], (entry["sha256"], entry["size"]))
                for entry in smoke["side_effects"]["added"])
            self.assertEqual(actual, side_effects, case)
            self.assertEqual(smoke["reader_class"], "ByteBWT", case)
            self.assertEqual(smoke["status"], "passed", case)

    def test_nonuniform_compress_posthoc_golden(self):
        manifest = load_json(GOLDENS / "nonuniform-compress-posthoc" /
                             PROFILE / ROUTE / "manifest.json")
        entry = next(e for e in manifest["artifacts"]
                     if e["path"] == "comp_msbwt.npy")
        self.assertEqual(entry["sha256"], COMPRESSED_GOLDEN)


if __name__ == "__main__":
    unittest.main()
