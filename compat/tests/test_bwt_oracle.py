"""Host-side guards for the independent MSBWT oracle used by merge validation.

The rotation-sort oracle must reproduce the committed ``uniform-multifile``
byte primary exactly, and the committed ``nonuniform-prefix`` primary must be
independently valid (backward-search counts and LF recovery) while using a
different byte ordering than rotation-sort.  These facts determine why the
canonical merge baseline uses uniform inputs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import struct
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPOSITORY_ROOT / "compat" / "tools" / "bwt_oracle.py"
SPEC = importlib.util.spec_from_file_location("bwt_oracle", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
bwt_oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bwt_oracle)

GOLDEN_ROOT = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
UNIFORM_BUILD = (GOLDEN_ROOT
                 / "uniform-multifile" / "py27-late-05a7d6d83862" / "pyx-historical-cython"
                 / "build" / "artifacts" / "msbwt.npy")
NONUNIFORM_BUILD = (GOLDEN_ROOT
                    / "nonuniform-prefix" / "py27-late-05a7d6d83862" / "pyx-historical-cython"
                    / "build" / "artifacts" / "msbwt.npy")

UNIFORM_READS = ["ACGTN", "AAAAA", "ACGTN", "NACGT", "ACGTN", "CCCCC", "GGGGG", "TTTTT"]
NONUNIFORM_READS = ["A", "AC", "ACG", "ACGT", "ACGTN", "TTTTTTT", "N"]
UNIFORM_PAYLOAD_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
UNIFORM_BWT = "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$"


def read_u1_payload(path: Path) -> bytes:
    data = path.read_bytes()
    header_length = struct.unpack("<H", data[8:10])[0]
    return data[10 + header_length:]


def u1_shape(path: Path):
    data = path.read_bytes()
    header_length = struct.unpack("<H", data[8:10])[0]
    header = data[10:10 + header_length].decode("latin-1")
    match = re.search(r"'shape':\s*(\([^)]*\))[,}]", header)
    shape = match.group(1).replace("L", "")
    return int(shape.strip("(),"))


class BwtOracleTests(unittest.TestCase):
    def test_rotation_sort_reproduces_the_committed_uniform_primary(self) -> None:
        payload = bwt_oracle.rotation_sort_bwt(UNIFORM_READS)
        committed = read_u1_payload(UNIFORM_BUILD)

        self.assertEqual(len(payload), 48)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), UNIFORM_PAYLOAD_SHA256)
        self.assertEqual(payload, committed)
        self.assertEqual(bwt_oracle.decode_payload(payload), UNIFORM_BWT)
        self.assertEqual(u1_shape(UNIFORM_BUILD), 48)

    def test_uniform_oracle_semantic_invariants(self) -> None:
        payload = bwt_oracle.rotation_sort_bwt(UNIFORM_READS)

        self.assertEqual(bwt_oracle.symbol_counts(payload),
                         {"A": 9, "C": 9, "G": 9, "N": 4, "T": 9, "$": 8})
        self.assertEqual(bwt_oracle.symbol_counts(payload),
                         bwt_oracle.expected_symbol_counts(UNIFORM_READS))
        bwt_oracle.verify_backward_counts(payload, UNIFORM_READS)
        self.assertEqual(bwt_oracle.lf_recover_reads(payload), sorted(UNIFORM_READS))

    def test_nonuniform_golden_is_valid_but_not_rotation_sort(self) -> None:
        committed = read_u1_payload(NONUNIFORM_BUILD)
        rotation_sort = bwt_oracle.rotation_sort_bwt(NONUNIFORM_READS)

        # Both orderings must be valid MSBWTs of the same multiset ...
        bwt_oracle.verify_backward_counts(committed, NONUNIFORM_READS)
        bwt_oracle.verify_backward_counts(rotation_sort, NONUNIFORM_READS)
        self.assertEqual(bwt_oracle.lf_recover_reads(committed), sorted(NONUNIFORM_READS))
        self.assertEqual(bwt_oracle.lf_recover_reads(rotation_sort), sorted(NONUNIFORM_READS))
        # ... but the frozen multimerge builder uses a different byte ordering.
        self.assertNotEqual(committed, rotation_sort)
        self.assertEqual(bwt_oracle.symbol_counts(committed),
                         bwt_oracle.expected_symbol_counts(NONUNIFORM_READS))

    def test_interleave_prediction_for_uniform_inputs(self) -> None:
        input_a = UNIFORM_READS[:4]
        input_b = UNIFORM_READS[4:]
        prediction = bwt_oracle.interleave_prediction(input_a, input_b)

        self.assertEqual(prediction["total_positions"], 48)
        self.assertEqual(prediction["unique_to_a"], 12)
        self.assertEqual(prediction["unique_to_b"], 18)
        self.assertEqual(prediction["tied"], 18)
        self.assertEqual(len(prediction["expected_bits"]), 48)
        # The only tied rotations are the six rotations of ACGTN, present 2x
        # in input A and 1x in input B.
        tied_blocks = [b for b in prediction["blocks"]
                       if b["expected_bit"] is None]
        self.assertEqual(len(tied_blocks), 6)
        for block in tied_blocks:
            self.assertEqual(block["count_a"], 2)
            self.assertEqual(block["count_b"], 1)

    def test_bits_from_interleave_payload_expands_little_endian_bits(self) -> None:
        bits = bwt_oracle.bits_from_interleave_payload(bytes([0b00000001, 0b10000000]), 16)
        self.assertEqual(bits[0], 1)
        self.assertEqual(bits[7], 0)
        self.assertEqual(bits[8], 0)
        self.assertEqual(bits[15], 1)

    def test_backward_count_matches_expected_substring_counts(self) -> None:
        payload = bwt_oracle.rotation_sort_bwt(UNIFORM_READS)
        expected = bwt_oracle.expected_substring_counts(UNIFORM_READS)

        for query, count in expected.items():
            self.assertEqual(bwt_oracle.backward_count(payload, query), count)
        self.assertEqual(bwt_oracle.backward_count(payload, "TTTTTT"), 0)
        self.assertEqual(bwt_oracle.backward_count(payload, "ACGTN"), 3)
        self.assertEqual(bwt_oracle.backward_count(payload, "ACGT"), 4)


if __name__ == "__main__":
    unittest.main()
