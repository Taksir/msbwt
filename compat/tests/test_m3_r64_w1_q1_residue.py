"""M3-R64-W1 regression: Windows Q1 temporary-directory lifecycle.

Pre-repair defect (M3-R64A audit / M3-12): ``_fill_quality_rows`` callers
opened ``quality_rows.npy`` through ``np.load(..., mmap_mode="r")`` and only
released the mapping *after* ``shutil.rmtree(temp_root, ...)`` had already run
in the ``finally`` block.  On Windows an open mapping prevents deletion, so a
``.q1-quality-build-*`` directory survived every successful quality build.

These tests pin the repaired lifecycle:

* no ``.q1-quality-build-*`` entries remain after a successful build;
* exact-quality semantics are unchanged (exact FASTQ ASCII recovery,
  terminal-255 sentinel exactly once per read, no quantization);
* the exception path still cleans up its temporary directory.
"""

import os
import shutil
import tempfile
import unittest

import numpy as np

from MUS.BWTTags import BWTTagStore
from MUS.QualitySidecar import (
    NO_QUALITY,
    QUALITY_TAG_NAME,  # noqa: F401  (name pin)
    QualitySidecar,
    QualitySidecarError,
    initialize_leaf_quality_from_records,
    validate_quality_sidecar,
)
import test_multisource_query as f3
from MUSCython import MultiStringBWTCython as MSB

loadBWT = MSB.loadBWT

READS = ["ACGTAC", "GGATC", "TTGCA"]
# NOTE: reads are chosen so that no two rotations coincide across reads;
# the naive leaf builder breaks ties arbitrarily, which corrupts raw
# dollar-ID walks for rotation-degenerate inputs (harness constraint,
# not a production defect).
SORTED_READS = [s.rstrip("$") for s in sorted(r + "$" for r in READS)]
N_ROWS = sum(len(r) + 1 for r in READS)
QUALITIES_BY_READ = {
    # Dollar IDs follow BWT construction order (sorted terminated reads);
    # key by the read itself so the mapping cannot silently drift.
    "ACGTAC": b"!I5~9A",   # extreme low Phred char, high char, digits
    "GGATC": b"~~~~~",
    "TTGCA": b"!!!!!",
}


def _qualities_by_dollar():
    # Established API contract: records are consumed positionally
    # (list(qualities_by_dollar_id)), i.e. ordered by leaf dollar ID.
    return [QUALITIES_BY_READ[read] for read in SORTED_READS]

def _build_package(work, name):
    """Leaf package with provenance, built by the established test builder."""
    return f3.make_read_derived_leaf(work, name, list(READS))


class Q1ResidueTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3r64w1-q1-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _residue_entries(self, bwt_dir):
        return [
            entry
            for entry in os.listdir(bwt_dir)
            if entry.startswith(".q1-quality-build-")
        ]

    def test_no_residue_after_successful_build_and_exact_semantics(self):
        bwt_dir = _build_package(self.work, "pkg")
        bwt = loadBWT(bwt_dir, False, None)

        sequences_by_dollar = []
        for dollar_id in range(len(READS)):
            recovered = bwt.recoverString(dollar_id)
            text = recovered.decode("ascii").replace("$", "")
            source = SORTED_READS[dollar_id]
            self.assertEqual(text, source, dollar_id)
            # Established contract: plain reads WITHOUT the '$' terminator.
            sequences_by_dollar.append(source.encode("ascii"))

        metadata = initialize_leaf_quality_from_records(
            bwt_dir,
            bwt,
            _qualities_by_dollar(),
            sequences_by_dollar_id=sequences_by_dollar,
            verify_sequences=True,
        )
        self.assertEqual(int(metadata["read_count"]), len(READS))

        # Lifecycle: nothing left behind inside the package directory.
        self.assertEqual(self._residue_entries(bwt_dir), [])

        # Persisted layer stays valid.
        validate_quality_sidecar(bwt_dir, full=True)

        # Exact-quality semantics unchanged: exact FASTQ ASCII per read.
        sidecar = QualitySidecar(bwt_dir)
        reloaded = loadBWT(bwt_dir, False, None)
        for dollar_id in range(len(READS)):
            sequence, quality = sidecar.recover_sequence_and_quality(
                reloaded,
                dollar_id,
            )
            self.assertEqual(quality, _qualities_by_dollar()[dollar_id], dollar_id)
            expected_sequence = SORTED_READS[dollar_id].encode()
            self.assertEqual(sequence, expected_sequence, dollar_id)

        # Terminal-255 sentinel: exactly one per read; no quantization among
        # base rows (values span the full supplied ASCII range).
        values = np.asarray(sidecar.values)
        self.assertEqual(values.shape[0], N_ROWS)
        self.assertEqual(int(np.count_nonzero(values == int(NO_QUALITY))),
                         len(READS))
        base_values = values[values != int(NO_QUALITY)]
        self.assertGreaterEqual(
            int(base_values.min()),
            min(min(q) for q in QUALITIES_BY_READ.values()))
        self.assertLessEqual(
            int(base_values.max()),
            max(max(q) for q in QUALITIES_BY_READ.values()))

    def test_failure_path_still_cleans_up(self):
        bwt_dir = _build_package(self.work, "pkg_fail")
        bwt = loadBWT(bwt_dir, False, None)
        broken = {0: b"short"}
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_records(
                bwt_dir,
                bwt,
                broken,
                verify_sequences=True,
            )
        self.assertEqual(self._residue_entries(bwt_dir), [])
        # No half-attached quality tag.
        store = BWTTagStore(bwt_dir)
        self.assertFalse(store.has_tag("quality"))


if __name__ == "__main__":
    unittest.main()
