"""Regression tests for M3-7: F1-F8A source/provenance/query parity.

These tests execute the real modern3 implementation end-to-end (build a tiny
multi-source provenance package through GenericMerge + MultiSourceProvenance,
then exercise the Feature query layer) and pin the repaired contract:

- ``MultiSourceBWT.countSubset(..., include_stats=True)`` must return
  ``stats`` containing exactly the traversal diagnostics produced by
  ``TwoSourceInterleaveIndex.subset_count_interval`` (the modern2 oracle
  shape).  An earlier Python-3 edit injected merged-interval/selection keys
  into that dict, silently diverging from the oracle return contract.
"""

import json
import os
import shutil
import random
import sys
import tempfile
import unittest

import numpy as np

REPO_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))
MODERN3_DIR = os.path.join(REPO_ROOT, 'packages', 'msbwt-modern3')
if MODERN3_DIR not in sys.path:
    sys.path.insert(0, MODERN3_DIR)

from MUS import MultiSourceProvenance as MSP            # noqa: E402
from MUS.MultiSourceQuery import MultiSourceBWT         # noqa: E402
from MUS.SourceMetadata import SourceMetadataCatalog    # noqa: E402


def _write_fastq(path, reads):
    with open(path, 'w', newline='\n') as fp:
        for i, r in enumerate(reads):
            fp.write('@r%d\n%s\n+\n%s\n' % (i, r, 'I' * len(r)))


class M37SourceParityBase(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='m37_parity_')
        rng = random.Random(4017)
        self.reads_a = [''.join(rng.choice('ACGT') for _ in range(10))
                        for _ in range(5)]
        self.reads_b = [''.join(rng.choice('ACGT') for _ in range(8))
                        for _ in range(4)]
        fa = os.path.join(self.work, 'a.fastq')
        fb = os.path.join(self.work, 'b.fastq')
        _write_fastq(fa, self.reads_a)
        _write_fastq(fb, self.reads_b)

        from MUSCython import MultiStringBWTCython as MSBWT
        import logging
        logger = logging.getLogger('m37_test')
        logger.addHandler(logging.NullHandler())
        ca = os.path.join(self.work, 'const_a')
        cb = os.path.join(self.work, 'const_b')
        for d, fq, sid, sname in ((ca, fa, 'srcA', 'sampleA'),
                                  (cb, fb, 'srcB', 'sampleB')):
            os.makedirs(d)
            MSBWT.createMSBWTFromFastq([fq], d, 1, True, logger)
            MSP.initialize_leaf_provenance(d, source_id=sid,
                                           source_name=sname)
        merged = os.path.join(self.work, 'merged')
        os.makedirs(merged)
        MSP.merge_two_with_provenance(ca, cb, merged, MSP.holt_merge_two,
                                      num_procs=1)
        self.merged = merged

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)


class TestCountSubsetStatsContract(M37SourceParityBase):
    """Reproduction + fix pinning for the M3-7 countSubset stats defect."""

    def test_stats_contains_only_traversal_diagnostics(self):
        ms = MultiSourceBWT.load(self.merged)
        result = ms.countSubset(b'AC', sources=['srcA', 'srcB'],
                                include_stats=True)
        expected = {
            "root_interval_size",
            "selected_sources",
            "internal_nodes_visited",
            "branches_pruned_empty_interval",
            "branches_pruned_unselected",
            "subtree_shortcuts",
            "rank_nodes_loaded_before",
            "rank_nodes_loaded_after",
            "rank_nodes_loaded_for_query",
        }
        self.assertEqual(set(result["stats"].keys()), expected)

    def test_top_level_result_shape_unchanged(self):
        ms = MultiSourceBWT.load(self.merged)
        result = ms.countSubset(b'AC', sources=['srcA'], include_stats=True)
        self.assertEqual(
            sorted(result.keys()),
            ["count", "merged_count", "merged_interval", "selected_source_count",
             "selected_source_ids", "sequence", "stats"])
        self.assertIsInstance(result["count"], int)


class TestSourceIdentityNotLabels(M37SourceParityBase):
    """F2/F7 core contract: identity is the stable source ID, not labels."""

    def test_duplicate_labels_keep_distinct_ids(self):
        ids = MSP.source_ids(self.merged)
        self.assertEqual(ids, ["srcA", "srcB"])
        names = [s.get("source_name") for s in MSP.list_sources(self.merged)]
        # distinct ids even if labels were equal
        self.assertEqual(len(set(ids)), len(ids))

    def test_metadata_mutation_preserves_identity(self):
        cat = SourceMetadataCatalog.load(
            self.merged, MSP.list_sources(self.merged), required=False)
        cat.define_group("g1", ["srcA"])
        cat.set_source_metadata("srcA", tissue="lung")
        cat.save(self.merged)
        before = MSP.source_ids(self.merged)
        man_before = json.load(open(os.path.join(
            self.merged, "provenance.json")), )
        # reload and mutate again
        cat2 = SourceMetadataCatalog.load(
            self.merged, MSP.list_sources(self.merged), required=False)
        cat2.set_source_metadata("srcA", tissue="heart")
        cat2.save(self.merged)
        self.assertEqual(MSP.source_ids(self.merged), before)
        man_after = json.load(open(os.path.join(
            self.merged, "provenance.json")))
        self.assertEqual(man_before["msbwt_sha256"],
                         man_after["msbwt_sha256"])

    def test_constituent_extraction_matches_original(self):
        import hashlib
        extracted = MSP.extract_all_constituent_bwts(self.merged)
        orig = {
            'srcA': np.load(os.path.join(self.work, 'const_a',
                                         'msbwt.npy')),
            'srcB': np.load(os.path.join(self.work, 'const_b',
                                         'msbwt.npy')),
        }
        for sid, arr in extracted.items():
            self.assertEqual(hashlib.sha256(arr.tobytes()).hexdigest(),
                             hashlib.sha256(orig[sid].tobytes()).hexdigest(),
                             sid)

    def test_f4_f5_invariant_and_oracle(self):
        ms = MultiSourceBWT.load(self.merged)
        for p in (b'AC', b'GGGGGGGGGGG', self.reads_a[0].encode()[:4]):
            nz = ms.nonzeroSources(p)
            freq = ms.sourceFrequency(p)
            self.assertEqual(freq, len(nz))
            # independent oracle from original reads (cyclic rotations)
            expected = {}
            for sid, reads in (('srcA', self.reads_a),
                               ('srcB', self.reads_b)):
                cnt = 0
                for r in reads:
                    s = r + '$'
                    for i in range(len(s)):
                        if (s[i:] + s[:i]).startswith(p.decode()):
                            cnt += 1
                if cnt:
                    expected[sid] = cnt
            got = dict((rec['source_id'], rec['count']) for rec in nz)
            self.assertEqual(got, expected)


if __name__ == '__main__':
    unittest.main()
