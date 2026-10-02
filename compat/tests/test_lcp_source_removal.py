"""Host-side regression tests for Feature 11B: LCP-preserving Point-10
source removal (``MUS.LCP.filter_lcp_for_removal`` wired into
``MUS.SourceRemoval.retain_sources``).

Mandatory invariant (roadmap step 2):

    LCP(Point10(existing MSBWT, retained sources))
    ==
    LCP(independent rebuild from the retained sources)

element for element.  Two independent oracles are used for the right-hand
side: the explicit suffix-sort oracle from ``test_lcp`` and a fresh
Feature-11A construction on a ``drop_lcp`` copy of the same reduction.

Also covered: chunk-boundary carry of the range-minimum filter, chained
removals, randomized collections, stale-input rejection with no published
output, tag/quality coexistence, the CLI default, and old-reader/new-writer
plus new-reader/old-writer interoperability against msbwt-modern2.

Feature 11B is modern3-only; the module skips when the selected package
does not provide it.
"""

import hashlib
import json
import os
import random
import subprocess
import sys
import unittest

import numpy as np

import MUS.LCP as lcp_module
from MUS.LCP import (  # noqa: E402
    LCPError,
    LCPIndex,
    lcp_exists,
    validate_lcp,
)
from MUS.MultiSourceProvenance import validate_manifest  # noqa: E402
from MUS.SourceRemoval import remove_sources, retain_sources  # noqa: E402

import test_lcp as f11a  # noqa: E402
import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

HAS_11B = hasattr(lcp_module, "filter_lcp_for_removal")

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(TESTS_DIR, "..", ".."))
MODERN2 = os.path.join(REPO, "packages", "msbwt-modern2")
MODERN3 = os.path.join(REPO, "packages", "msbwt-modern3")

SEEDS = (20261002, 20261003, 20261004)

# Long shared prefixes across sources, so removing a source joins
# survivors whose LCP is a non-trivial minimum over the removed rows.
REPETITIVE_READS = {
    "R0": ["ACGTACGTAA", "ACGTACGTAC", "TTTTGGGG"],
    "R1": ["ACGTACGTAG", "ACGTACG", "TTTTGGGA"],
    "R2": ["ACGTACGTAT", "ACGTAC", "TTTTGG", "ACGTACGTAG"],
    "R3": ["ACGTACGTAA", "CCCCACGT", "TTTTGGGC"],
}


def naive_filter(lcps, keep_mask):
    """Definition-level reference: min over the gap between survivors."""
    survivors = np.flatnonzero(keep_mask)
    return np.asarray(
        [int(np.min(lcps[survivors[k]:survivors[k + 1]]))
         for k in range(len(survivors) - 1)],
        dtype=lcps.dtype,
    )


def file_sha256(path):
    with open(path, "rb") as fp:
        return hashlib.sha256(fp.read()).hexdigest()


@unittest.skipUnless(HAS_11B, "Feature 11B not in the selected package")
class RangeMinimumFilterTests(unittest.TestCase):
    def run_filter(self, lcps, mask, chunk_rows):
        out = np.zeros(max(0, int(mask.sum()) - 1), dtype=lcps.dtype)
        written, max_value = lcp_module._filter_lcp_values(
            lcps, mask, out, chunk_rows)
        self.assertEqual(written, out.shape[0])
        if out.size:
            self.assertEqual(max_value, int(out.max()))
        return out

    def test_matches_definition_for_every_chunk_size(self):
        rng = np.random.RandomState(20261002)
        for trial in range(200):
            n = int(rng.randint(2, 40))
            lcps = rng.randint(0, 9, size=n - 1).astype("<u4")
            density = rng.choice([0.05, 0.3, 0.7, 1.0])
            mask = rng.random_sample(n) < density
            if mask.sum() < 1:
                mask[int(rng.randint(0, n))] = True
            expected = naive_filter(lcps, mask)
            for chunk_rows in (1, 2, 3, 5, 7, n, n + 10):
                got = self.run_filter(lcps, mask, chunk_rows)
                self.assertTrue(
                    np.array_equal(got, expected),
                    (trial, chunk_rows, lcps, mask, got, expected))

    def test_edge_masks(self):
        lcps = np.asarray([3, 1, 4, 1, 5, 9, 2], dtype="<u8")
        cases = [
            [1, 0, 0, 0, 0, 0, 0, 1],   # first and last only
            [0, 0, 0, 1, 0, 0, 0, 0],   # single survivor
            [1, 1, 1, 1, 1, 1, 1, 1],   # identity
            [0, 0, 0, 0, 0, 0, 1, 1],   # survivors only at the end
        ]
        for case in cases:
            mask = np.asarray(case, dtype=np.bool_)
            for chunk_rows in (1, 2, 3, 8):
                got = self.run_filter(lcps, mask, chunk_rows)
                self.assertEqual(got.dtype, lcps.dtype)
                self.assertTrue(np.array_equal(
                    got, naive_filter(lcps, mask)), (case, chunk_rows))


@unittest.skipUnless(HAS_11B, "Feature 11B not in the selected package")
class LCPPreservingRemovalTests(f11a.LCPHostTestBase):
    def reduce_both_ways(self, output, leaves, rbs, remove, name,
                         chunk_rows=None):
        """Point-10 removal with LCP carried, plus the rebuild oracle."""
        kwargs = {}
        if chunk_rows is not None:
            kwargs["chunk_rows"] = chunk_rows
        preserved = os.path.join(self.work, name)
        stats = remove_sources(output, preserved, sources=remove, **kwargs)
        self.assertTrue(stats["lcp_preserved"])

        rebuilt = os.path.join(self.work, name + "_rebuilt")
        dropped_stats = remove_sources(
            output, rebuilt, sources=remove, drop_lcp=True, **kwargs)
        self.assertFalse(dropped_stats["lcp_preserved"])
        self.assertFalse(lcp_exists(rebuilt))

        keep = {sid: rbs[sid] for sid in rbs if sid not in remove}
        f11a.save_expected_rows(preserved, leaves, keep)
        f11a.save_expected_rows(rebuilt, leaves, keep)
        self.construct(
            rebuilt,
            f9.OracleReadIdentity(
                rebuilt, {sid: leaves[sid] for sid in keep}, keep))
        return preserved, rebuilt

    def assert_matches_rebuild(self, preserved, rebuilt):
        # Oracle 1: explicit suffix sort over the retained reads.
        index, _ = self.assert_lcp_exact(preserved)
        # Oracle 2: independent Feature-11A construction, same bytes.
        carried = np.load(os.path.join(preserved, "lcps.npy"))
        fresh = np.load(os.path.join(rebuilt, "lcps.npy"))
        self.assertEqual(carried.dtype, fresh.dtype)
        self.assertTrue(np.array_equal(carried, fresh))
        # The LCP layer changes nothing else in the reduced package.
        self.assertEqual(
            file_sha256(os.path.join(preserved, "msbwt.npy")),
            file_sha256(os.path.join(rebuilt, "msbwt.npy")))
        meta = validate_lcp(preserved, full=True)
        fresh_meta = validate_lcp(rebuilt, full=True)
        for key in ("bwt_rows", "read_count", "max_lcp", "bwt_sha256",
                    "array_length", "array_dtype", "terminator_semantics"):
            self.assertEqual(meta[key], fresh_meta[key], key)
        self.assertEqual(meta["algorithm"], "point10-survivor-range-minimum")
        self.assertFalse(meta["max_read_length_exact"])
        self.assertGreaterEqual(
            meta["max_read_length"], fresh_meta["max_read_length"])
        self.assertTrue(validate_manifest(preserved))
        return index

    def test_ten_source_selections_match_rebuild(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        input_meta = validate_lcp(output)
        selections = [
            ["sample09"],
            ["sample00"],
            ["sample00", "sample02", "sample09"],
            ["sample01", "sample03", "sample05", "sample07"],
            ["sample%02d" % i for i in range(9)],      # keep one source
        ]
        for i, remove in enumerate(selections):
            preserved, rebuilt = self.reduce_both_ways(
                output, leaves, rbs, remove, "sel%d" % i)
            self.assert_matches_rebuild(preserved, rebuilt)
            meta = validate_lcp(preserved)
            self.assertEqual(
                meta["derived_from"]["bwt_sha256"], input_meta["bwt_sha256"])
            self.assertEqual(meta["derived_from"]["bwt_rows"], 191)

    def test_repetitive_sources_small_chunks(self):
        leaves, output, oracle, rbs = self.build_merged(
            REPETITIVE_READS, name="rep")
        self.construct(output, oracle)
        for i, remove in enumerate((["R1"], ["R0", "R2"], ["R3"])):
            for chunk_rows in (1, 3, 1 << 20):
                preserved, rebuilt = self.reduce_both_ways(
                    output, leaves, rbs, remove,
                    "rep%d_c%d" % (i, chunk_rows), chunk_rows=chunk_rows)
                index = self.assert_matches_rebuild(preserved, rebuilt)
                # Non-trivial joins really occur in this fixture.
                self.assertGreaterEqual(index.max_lcp, 6)

    def test_chained_removal_equals_one_shot(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        step1 = os.path.join(self.work, "step1")
        remove_sources(output, step1, sources=["sample00", "sample04"])
        step2 = os.path.join(self.work, "step2")
        remove_sources(step1, step2, sources=["sample06", "sample08"])
        one_shot = os.path.join(self.work, "one_shot")
        remove_sources(
            output, one_shot,
            sources=["sample00", "sample04", "sample06", "sample08"])
        self.assertTrue(np.array_equal(
            np.load(os.path.join(step2, "lcps.npy")),
            np.load(os.path.join(one_shot, "lcps.npy"))))
        keep = {sid: rbs[sid] for sid in rbs
                if sid not in ("sample00", "sample04",
                               "sample06", "sample08")}
        f11a.save_expected_rows(step2, leaves, keep)
        self.assert_lcp_exact(step2)
        self.assertEqual(
            validate_lcp(step2)["derived_from"]["bwt_sha256"],
            validate_lcp(step1)["bwt_sha256"])

    def test_retain_sources_preserves_lcp(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        reduced = os.path.join(self.work, "kept")
        stats = retain_sources(output, reduced, ["sample03", "sample07"])
        self.assertTrue(stats["lcp_preserved"])
        keep = {sid: rbs[sid] for sid in ("sample03", "sample07")}
        f11a.save_expected_rows(reduced, leaves, keep)
        self.assert_lcp_exact(reduced)

    def test_randomized_collections(self):
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(4):
                reads_by_source = {}
                for i in range(rng.randint(2, 5)):
                    sid = "Q%d_%d_%d" % (seed_index, case, i)
                    reads = []
                    for _ in range(rng.randint(1, 4)):
                        if reads and rng.random() < 0.3:
                            reads.append(rng.choice(reads))
                            continue
                        reads.append("".join(
                            rng.choice("ACGTN")
                            for _ in range(rng.randint(1, 9))))
                    reads_by_source[sid] = reads
                tag = "rnd_%d_%d" % (seed_index, case)
                leaves, output, oracle, rbs = self.build_merged(
                    reads_by_source, name=tag)
                self.construct(output, oracle)
                ids = sorted(reads_by_source)
                remove = rng.sample(ids, rng.randint(1, len(ids) - 1))
                preserved, rebuilt = self.reduce_both_ways(
                    output, leaves, rbs, remove, tag + "_r",
                    chunk_rows=rng.choice([1, 2, 5, 1 << 20]))
                self.assert_matches_rebuild(preserved, rebuilt)

    def test_stale_input_layer_rejected_without_output(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        meta_path = os.path.join(output, "lcp.json")
        with open(meta_path) as fp:
            doc = json.load(fp)
        doc["bwt_sha256"] = "0" * 64
        with open(meta_path, "w") as fp:
            json.dump(doc, fp)
        target = os.path.join(self.work, "never")
        with self.assertRaises(LCPError):
            remove_sources(output, target, sources=["sample09"])
        self.assertFalse(os.path.exists(target))
        leftovers = [n for n in os.listdir(self.work)
                     if n.startswith(".never")]
        self.assertEqual(leftovers, [])

    def test_tags_and_quality_survive_with_lcp(self):
        from MUS.BWTTags import BWTTagStore, attach_tag
        from MUS.QualitySidecar import (
            QualitySidecar, attach_quality_from_row_values)
        from MUS.MultiSourceProvenance import merge_many_balanced

        reads_by_source = {"A": ["ACGTAC", "AAAA"],
                           "B": ["ACGTTT", "CCCC"],
                           "C": ["ACGTAA", "GGTT"]}
        leaves = {}
        for sid, reads in reads_by_source.items():
            leaf = f3.make_read_derived_leaf(self.work, sid, reads)
            rows = f3.load_rows(leaf)
            attach_tag(leaf, "row_id",
                       np.arange(len(rows), dtype=np.uint32))
            q = np.asarray(
                [255 if r["pos"] >= len(reads[r["read_id"]])
                 else 33 + (i % 40) for i, r in enumerate(rows)],
                dtype=np.uint8)
            attach_quality_from_row_values(leaf, q)
            leaves[sid] = leaf
        output = os.path.join(self.work, "merged")
        merge_many_balanced(list(leaves.values()), output,
                            merge_two_func=f3.read_derived_merge)
        self.construct(output, f9.OracleReadIdentity(
            output, leaves, reads_by_source))
        tags_before = BWTTagStore(output).array("row_id").copy()

        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(output, reduced, sources=["B"])
        self.assertTrue(stats["lcp_preserved"])
        self.assertTrue(stats["bwt_tags_preserved"])
        self.assertTrue(stats["quality_sidecar_preserved"])
        keep = {sid: reads_by_source[sid] for sid in ("A", "C")}
        f11a.save_expected_rows(reduced, leaves, keep)
        self.assert_lcp_exact(reduced)
        self.assertEqual(
            BWTTagStore(reduced).array("row_id").shape[0],
            len(f3.load_rows(reduced)))
        self.assertEqual(
            QualitySidecar(reduced).values.shape[0],
            len(f3.load_rows(reduced)))
        self.assertTrue(np.array_equal(
            BWTTagStore(output).array("row_id"), tags_before))


def run_with_package(package_dir, code, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([package_dir, TESTS_DIR])
    return subprocess.run(
        [sys.executable, "-c", code] + list(args),
        cwd=TESTS_DIR, env=env, capture_output=True, text=True,
        check=False)


OLD_READER = r"""
import sys, json
import numpy as np
import MUS.LCP as m
assert not hasattr(m, "filter_lcp_for_removal"), "not the modern2 module"
meta = m.validate_lcp(sys.argv[1], full=True)
index = m.LCPIndex(sys.argv[1])
print(json.dumps({"values": [int(v) for v in index.values],
                  "max_lcp": index.max_lcp}))
"""

OLD_WRITER = r"""
import sys, os
import test_lcp as f11a
import test_multisource_query as f3
import test_read_provenance as f9
import MUS.LCP as m
from MUS.MultiSourceProvenance import merge_many_balanced
assert not hasattr(m, "filter_lcp_for_removal"), "not the modern2 module"
work = sys.argv[1]
leaves = {sid: f3.make_read_derived_leaf(work, sid, reads)
          for sid, reads in f3.TEN_SOURCE_READS.items()}
output = os.path.join(work, "old_merged10")
merge_many_balanced(list(leaves.values()), output,
                    merge_two_func=f3.read_derived_merge)
oracle = f9.OracleReadIdentity(output, leaves, f3.TEN_SOURCE_READS)
m.construct_lcp_from_bwt(output,
                         bwt=f11a.OracleBackedAdapter(output, oracle))
print(output)
"""


@unittest.skipUnless(HAS_11B, "Feature 11B not in the selected package")
@unittest.skipUnless(os.path.isdir(MODERN2), "msbwt-modern2 not present")
class Modern2InteroperabilityTests(f11a.LCPHostTestBase):
    def test_old_reader_accepts_new_writer_layer(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        reduced = os.path.join(self.work, "reduced")
        remove_sources(output, reduced, sources=["sample02", "sample05"])
        result = run_with_package(MODERN2, OLD_READER, reduced)
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        index = LCPIndex(reduced)
        self.assertEqual(doc["values"], [int(v) for v in index.values])
        self.assertEqual(doc["max_lcp"], index.max_lcp)

    def test_new_writer_consumes_old_writer_layer(self):
        result = run_with_package(MODERN2, OLD_WRITER, self.work)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout.strip().splitlines()[-1]
        leaves = {sid: os.path.join(self.work, sid)
                  for sid in f3.TEN_SOURCE_READS}
        reduced = os.path.join(self.work, "reduced_from_old")
        stats = remove_sources(output, reduced, sources=["sample09"])
        self.assertTrue(stats["lcp_preserved"])
        keep = {sid: reads for sid, reads in f3.TEN_SOURCE_READS.items()
                if sid != "sample09"}
        f11a.save_expected_rows(reduced, leaves, keep)
        self.assert_lcp_exact(reduced)


@unittest.skipUnless(HAS_11B, "Feature 11B not in the selected package")
class RemovalCLITests(f11a.LCPHostTestBase):
    def test_cli_carries_lcp_by_default_and_drops_on_request(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        script = os.path.join(MODERN3, "tools", "remove_sources.py")
        env = dict(os.environ)
        env["PYTHONPATH"] = MODERN3
        for flag, expected in (([], True), (["--drop-lcp"], False)):
            target = os.path.join(self.work, "cli_%s" % expected)
            result = subprocess.run(
                [sys.executable, script, "--input", output,
                 "--output", target, "--remove", "sample09"] + flag,
                env=env, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["lcp_preserved"], expected)
            self.assertEqual(lcp_exists(target), expected)


if __name__ == "__main__":
    unittest.main()
