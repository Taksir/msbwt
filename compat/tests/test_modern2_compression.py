"""Read-only host-side regression tests for msbwt-modern2 compression
milestone 2 (first RLE/compression slice).

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 compression evidence, the byte identity of the
migrated compression-slice sources against the frozen originals, and the
route-specific golden contracts without requiring the WSL Python-2
environment.  The runtime build/slice validation lives in
packages/msbwt-modern2/validate/compression-milestone2.sh (WSL).
"""

import json
import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
MUSCYN = PACKAGE / "MUSCython"
GOLDENS = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
PROFILE = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
EVIDENCE = PACKAGE / "evidence" / "compression-milestone2.json"

DIRECT_SHA256 = "0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372"
POSTHOC_SHA256 = "53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3"
PAYLOAD_SHA256 = "6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb"
DECODED_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
DECODED_BWT = "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$"

COMPRESSION_SLICE_MODULES = [
    "MSBWTCompGenCython",
    "MSBWTGenCython",
    "RLE_BWTCython",
    "MultiStringBWTCython",
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ValidationDriverTests(unittest.TestCase):
    def test_driver_present_and_runs_each_route(self):
        driver = PACKAGE / "validate" / "compression-milestone2.sh"
        text = driver.read_text(encoding="utf-8")
        for route in ("run_direct_split", "run_direct_wrapper", "run_posthoc"):
            self.assertIn(route, text)
        self.assertIn("uniform-direct-split", text)
        self.assertIn("uniform-direct-wrapper", text)
        self.assertIn("uniform-compress-posthoc", text)
        self.assertIn("run_p2", text)
        self.assertIn("verify_reader", text)

    def test_driver_uses_host_side_safe_decoder_and_golden_manifests(self):
        driver = (PACKAGE / "validate" / "compression-milestone2.sh").read_text(
            encoding="utf-8")
        self.assertIn("artifact_manifest.py", driver)
        self.assertIn("decode_npy_rle_primary", driver)
        self.assertIn("compare_manifest", driver)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"], "modern2-milestone2-compression")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")
        self.assertEqual(evidence["build"]["modules"], 8)
        self.assertEqual(evidence["build"]["cython"], "3.0.12")
        self.assertEqual(evidence["build"]["language_level"], 2)
        self.assertEqual(evidence["py2_tests"]["status"], "ok")

    def test_evidence_route_hashes_match_committed_goldens(self):
        evidence = load_json(EVIDENCE)
        routes = evidence["routes"]
        self.assertEqual(routes["direct-split"]["run-a_whole_sha256"], DIRECT_SHA256)
        self.assertEqual(routes["direct-wrapper"]["run-a_whole_sha256"], DIRECT_SHA256)
        self.assertEqual(routes["posthoc"]["run-a_whole_sha256"], POSTHOC_SHA256)
        for route_key in ("direct-split", "direct-wrapper", "posthoc"):
            entry = routes[route_key]
            self.assertTrue(entry["golden_manifest_match"], route_key)
            self.assertTrue(entry["committed_decoded_rle_match"], route_key)
            self.assertTrue(entry["run_a_equals_run_b"], route_key)
            self.assertTrue(entry["run_a_equals_run_p2"], route_key)
            self.assertEqual(entry["shape_literal"],
                             "(22L,)" if route_key != "posthoc" else "(22,)",
                             route_key)
            self.assertEqual(entry["payload_sha256"], PAYLOAD_SHA256, route_key)
            self.assertEqual(entry["decoded_sha256"], DECODED_SHA256, route_key)
            self.assertEqual(entry["decoded_bwt"], DECODED_BWT, route_key)
            self.assertEqual(entry["decoded_length"], 48, route_key)
            self.assertEqual(entry["run_count"], 22, route_key)
        cross = routes["cross_route"]
        self.assertTrue(cross["payload_equal"])
        self.assertTrue(cross["direct_equals_wrapper_whole"])
        self.assertEqual(cross["payload_sha256"], PAYLOAD_SHA256)
        self.assertEqual(cross["direct_shape_literal"], "(22L,)")
        self.assertEqual(cross["posthoc_shape_literal"], "(22,)")
        self.assertTrue(routes["decoded_matches_committed_byte_primary"])

    def test_evidence_reader_matches_committed_legacy_reader_smoke(self):
        evidence = load_json(EVIDENCE)
        legacy = load_json(GOLDENS / "uniform-direct-split" / PROFILE / ROUTE /
                           "reader-smoke.json")
        for label, record in evidence["reader"].items():
            self.assertEqual(record["reader_class"],
                             "MUSCython.RLE_BWTCython.RLE_BWT", label)
            self.assertEqual(record["total_size"], 48, label)
            self.assertEqual(record["dollar_count"], 8, label)
            self.assertTrue(record["queries_match"], label)
            self.assertTrue(record["recovered_match"], label)
            added = {item["path"]: item["sha256"]
                     for item in record["side_effects"]["added"]}
            legacy_added = {item["path"]: item["sha256"]
                            for item in legacy["side_effects"]["added"]}
            self.assertEqual(added, legacy_added, label)
            self.assertEqual(record["side_effects"]["changed"], [], label)
            self.assertEqual(record["side_effects"]["removed"], [], label)


class CompressionSourceIdentityTests(unittest.TestCase):
    """The compression slice was migrated without semantic source changes.

    Every migrated ``.pyx`` must stay byte-identical to the frozen original
    (after LF normalization) apart from the explicit ``language_level=2``
    header line.  This is the strongest protection for the Cython-3 typed
    division/modulo/power audit conclusion: no integer-semantics fix was
    required for the compression slice because no typed division is on the
    exercised paths and every modulo/power site has positive small operands.
    """

    def test_compression_pyx_identical_to_frozen_plus_language_level(self):
        frozen_manifest = (REPOSITORY_ROOT / "reference" / "original-0.3.0" /
                           "environment" / "frozen-source.sha256")
        expected = {}
        for line in frozen_manifest.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            digest, declaration = line.split(None, 1)
            source = declaration.split(" <- ", 1)[-1]
            expected[source] = digest
        for name in COMPRESSION_SLICE_MODULES:
            relative = "MUSCython/{}.pyx".format(name)
            frozen_bytes = (REPOSITORY_ROOT / relative).read_bytes().replace(
                b"\r\n", b"\n")
            migrated = (MUSCYN / (name + ".pyx")).read_bytes().replace(
                b"\r\n", b"\n")
            self.assertEqual(frozen_bytes.splitlines()[0],
                             migrated.splitlines()[0], relative)
            frozen_lines = frozen_bytes.splitlines()
            expected_lines = frozen_lines[:1] + \
                [b"#cython: language_level=2"] + frozen_lines[1:]
            self.assertEqual(migrated.splitlines(), expected_lines, relative)

    def test_no_typed_division_on_direct_compression_path(self):
        text = (MUSCYN / "MSBWTCompGenCython.pyx").read_text(
            encoding="utf-8").splitlines()
        # every division/modulo/power operator line in the direct compressed
        # builder must be one of the audited positive-operand sites
        audited = re.compile(
            r"\(columnID\+2\) % seqLen|32\*\*finalSymbolPos|32\*\*startPoint")
        for number, line in enumerate(text, 1):
            if re.search(r" / |//| % |\*\*", line):
                self.assertIsNotNone(audited.search(line),
                                     "unexpected operator at line {}: {}".format(
                                         number, line))

    def test_compression_evidence_reader_side_effect_hashes_match_legacy(self):
        evidence = load_json(EVIDENCE)
        legacy = load_json(GOLDENS / "uniform-compress-posthoc" / PROFILE / ROUTE /
                           "reader-smoke.json")
        for label, record in evidence["reader"].items():
            for item in record["side_effects"]["added"]:
                expected = next(
                    e for e in legacy["side_effects"]["added"]
                    if e["path"] == item["path"])
                self.assertEqual(item["sha256"], expected["sha256"], label)
                self.assertEqual(item["size"], expected["size"], label)


if __name__ == "__main__":
    unittest.main()
