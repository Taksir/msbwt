"""Host-side regression tests for Feature 11C: LCP-interval applications
(``MUS.LCPIntervals`` plus the ``MultiSourceBWT`` 11C methods).

Every expectation comes from the read strings alone, with no BWT or LCP code:

- lcp-intervals: brute force over all row ranges of the explicit suffix
  sort (definition-level);
- maximal / supermaximal repeats: every substring of every read, with left
  and right contexts where each read start/end is its own distinct
  terminator;
- source support, group/subset counts, and read support: direct
  overlapping substring counts per source and per read.

Also covered: child intervals, chunk-size invariance, the compiled Holt
BWT spelling path, repeats after Feature-11B removal, and argument errors.
"""

import os
import random
import shutil
import tempfile
import unittest

import numpy as np

import MUS.LCP as lcp_module
from MUS.LCP import LCPIndex
from MUS.MultiSourceQuery import MultiSourceBWT, MultiSourceQueryError
from MUS.ReadProvenance import ReadProvenanceIndex
from MUS.SourceMetadata import SourceMetadataCatalog

import test_lcp as f11a  # noqa: E402
import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

try:
    import MUS.LCPIntervals as intervals_module
except ImportError:  # selected package predates Feature 11C
    intervals_module = None

HAS_11C = intervals_module is not None
SEEDS = (20261005, 20261006, 20261007)

REPEAT_READS = {
    "S0": ["ACGTACGTTA", "GGACGTAC", "TTTT"],
    "S1": ["CACGTACGA", "ACGTNACG", "TTTTA"],
    "S2": ["ACGTACGTTA", "GTACGTAC", "AAAA"],
    "S3": ["NNACGT", "ACGT", "TTTTT"],
}


# ---------------------------------------------------------------- oracles

def oracle_intervals(lcps, min_lcp=1, max_lcp=None, min_size=2):
    """All lcp-intervals by definition over the stored adjacent array."""
    n_rows = len(lcps) + 1
    found = set()
    for start in range(n_rows):
        for end in range(start + 2, n_rows + 1):
            value = int(min(lcps[start:end - 1]))
            if value < 1:
                break
            if start > 0 and lcps[start - 1] >= value:
                continue
            if end < n_rows and lcps[end - 1] >= value:
                continue
            if value < min_lcp or end - start < min_size:
                continue
            if max_lcp is not None and value > max_lcp:
                continue
            found.add((value, start, end))
    return found


def oracle_repeats(reads_by_source, min_length=1, max_length=None,
                   min_occurrences=2, supermaximal=False):
    """Maximal repeats from read strings, keyed by sequence."""
    occurrences = {}
    for sid, reads in reads_by_source.items():
        for read_index, read in enumerate(reads):
            uid = (sid, read_index)
            for i in range(len(read)):
                for j in range(i + 1, len(read) + 1):
                    word = read[i:j]
                    left = read[i - 1] if i > 0 else ("^",) + uid
                    right = read[j] if j < len(read) else ("$",) + uid
                    occurrences.setdefault(word, []).append(
                        (uid, left, right))
    maximal = {}
    for word, occ in occurrences.items():
        if len(occ) < 2:
            continue
        if len(set(o[2] for o in occ)) < 2:
            continue
        if len(set(o[1] for o in occ)) < 2:
            continue
        maximal[word] = occ
    if supermaximal:
        maximal = {
            w: occ for w, occ in maximal.items()
            if not any(w != other and w in other for other in maximal)
        }
    return {
        w: occ for w, occ in maximal.items()
        if len(w) >= min_length
        and (max_length is None or len(w) <= max_length)
        and len(occ) >= min_occurrences
    }


def per_source_counts(reads_by_source, word):
    counts = {}
    for sid, reads in reads_by_source.items():
        total = sum(f9.overlapping_count(r, word) for r in reads)
        if total:
            counts[sid] = total
    return counts


def reads_containing(reads_by_source, word):
    return sum(1 for reads in reads_by_source.values()
               for r in reads if word in r)


# ---------------------------------------------------------------- fixtures

class IntervalFixture(object):
    def __init__(self, work, reads_by_source, name="merged"):
        self.reads = reads_by_source
        self.leaves, self.output, self.manifest, self.oracle = (
            f9.build_fixture_with_reads(work, reads_by_source, name=name))
        lcp_module.construct_lcp_from_bwt(
            self.output,
            bwt=f11a.OracleBackedAdapter(self.output, self.oracle))
        read_index = ReadProvenanceIndex(self.output, mmap=False)
        self.wrapped = MultiSourceBWT(
            None, read_index.source_index,
            read_provenance=read_index,
            lcp_index=LCPIndex(self.output))
        self.wrapped.bwt = f9.OracleBWTAdapter(
            self.oracle, self.output, self.manifest)
        self.lcps = np.asarray(LCPIndex(self.output).values)


@unittest.skipUnless(HAS_11C, "Feature 11C not in the selected package")
class IntervalEnumerationTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="lcp11c-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_matches_definition_on_synthetic_arrays(self):
        rng = np.random.RandomState(20261005)
        for trial in range(150):
            n = int(rng.randint(1, 30))
            lcps = rng.randint(0, 6, size=n).astype("<u4")
            for min_lcp, max_lcp, min_size in (
                    (1, None, 2), (2, None, 2), (1, 3, 2), (2, 4, 3)):
                expected = oracle_intervals(lcps, min_lcp, max_lcp, min_size)
                for chunk_rows in (1, 2, 5, n + 3):
                    got = list(intervals_module.iter_lcp_intervals(
                        lcps, min_lcp=min_lcp, max_lcp=max_lcp,
                        min_size=min_size, chunk_rows=chunk_rows))
                    self.assertEqual(len(got), len(set(got)))
                    self.assertEqual(
                        set((i.lcp, i.start, i.end) for i in got),
                        expected, (trial, lcps, min_lcp, chunk_rows))

    def test_bottom_up_order_and_children(self):
        fixture = IntervalFixture(self.work, REPEAT_READS)
        got = list(fixture.wrapped.lcpIntervals())
        seen = set()
        for interval in got:
            children = fixture.wrapped.lcpChildren(interval)
            self.assertGreaterEqual(len(children), 2)
            self.assertEqual(children[0][0], interval.start)
            self.assertEqual(children[-1][1], interval.end)
            for (a, b, child_lcp), (c, _, _) in zip(children, children[1:]):
                self.assertEqual(b, c)
            for start, end, child_lcp in children:
                if child_lcp is None:
                    self.assertEqual(end - start, 1)
                else:
                    self.assertGreater(child_lcp, interval.lcp)
                    # bottom-up: every child was produced before its parent
                    self.assertIn((child_lcp, start, end), seen)
            seen.add((interval.lcp, interval.start, interval.end))

    def test_interval_sequences_match_suffix_rows(self):
        fixture = IntervalFixture(self.work, REPEAT_READS)
        suffixes = [r["suffix"] for r in f3.load_rows(fixture.output)]
        for interval in fixture.wrapped.lcpIntervals():
            sequence = fixture.wrapped.lcpIntervalSequence(interval)
            for row in range(interval.start, interval.end):
                self.assertEqual(
                    suffixes[row][:interval.lcp].encode("ascii"), sequence)

    def test_invalid_arguments(self):
        lcps = np.zeros(3, dtype="<u4")
        for kwargs in ({"min_lcp": 0}, {"min_lcp": 3, "max_lcp": 2},
                       {"min_size": 1}):
            with self.assertRaises(intervals_module.LCPIntervalError):
                list(intervals_module.iter_lcp_intervals(lcps, **kwargs))
        with self.assertRaises(intervals_module.LCPIntervalError):
            intervals_module.child_intervals(
                np.asarray([2, 1], dtype="<u4"), (2, 0, 3))


@unittest.skipUnless(HAS_11C, "Feature 11C not in the selected package")
class MaximalRepeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="lcp11c-rep-")
        cls.fixture = IntervalFixture(cls.work, REPEAT_READS)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def collect(self, **kwargs):
        records = list(self.fixture.wrapped.maximalRepeats(**kwargs))
        by_sequence = {}
        for record in records:
            sequence = record["sequence"].decode("ascii")
            self.assertNotIn(sequence, by_sequence)
            by_sequence[sequence] = record
        return by_sequence

    def test_maximal_repeats_match_string_oracle(self):
        for kwargs in ({}, {"min_length": 3}, {"min_length": 2,
                       "max_length": 4}, {"min_occurrences": 3}):
            got = self.collect(**kwargs)
            expected = oracle_repeats(self.fixture.reads, **kwargs)
            self.assertEqual(set(got), set(expected), kwargs)
            for word, record in got.items():
                self.assertEqual(record["occurrences"], len(expected[word]))
                self.assertEqual(record["length"], len(word))
                self.assertEqual(record["end"] - record["start"],
                                 record["occurrences"])

    def test_supermaximal_repeats_match_string_oracle(self):
        got = self.collect(supermaximal=True)
        expected = oracle_repeats(self.fixture.reads, supermaximal=True)
        self.assertEqual(set(got), set(expected))

    def test_source_support(self):
        got = self.collect(include_sources=True)
        for word, record in got.items():
            counts = per_source_counts(self.fixture.reads, word)
            self.assertEqual(record["source_frequency"], len(counts), word)
            self.assertEqual(
                {s["source_id"]: s["count"] for s in record["sources"]},
                counts, word)

    def test_source_frequency_filters(self):
        everything = self.collect()
        got = self.collect(min_sources=2, max_sources=3)
        expected = {
            w for w in everything
            if 2 <= len(per_source_counts(self.fixture.reads, w)) <= 3}
        self.assertEqual(set(got), expected)
        self.assertTrue(expected)

    def test_subset_and_group_counts(self):
        selection = ["S1", "S3"]
        subset = {s: self.fixture.reads[s] for s in selection}
        by_sources = self.collect(sources=selection, min_selected=1)
        catalog = SourceMetadataCatalog(
            self.fixture.wrapped.source_index.list_sources())
        catalog.define_group("pair", selection)
        self.fixture.wrapped.source_metadata = catalog
        by_group = self.collect(group="pair", min_selected=1)
        expected = {
            w: sum(per_source_counts(subset, w).values())
            for w in oracle_repeats(self.fixture.reads)
        }
        expected = {w: c for w, c in expected.items() if c >= 1}
        for got in (by_sources, by_group):
            self.assertEqual(
                {w: r["selected_count"] for w, r in got.items()}, expected)

    def test_read_support(self):
        got = self.collect(include_read_count=True, min_length=2)
        for word, record in got.items():
            self.assertEqual(
                record["read_count"],
                reads_containing(self.fixture.reads, word), word)

    def test_limit_and_errors(self):
        wrapped = self.fixture.wrapped
        self.assertEqual(len(list(wrapped.maximalRepeats(limit=3))), 3)
        self.assertEqual(list(wrapped.maximalRepeats(limit=0)), [])
        with self.assertRaises(ValueError):
            list(wrapped.maximalRepeats(sources=["S0"], group="pair"))
        with self.assertRaises(ValueError):
            list(wrapped.maximalRepeats(min_selected=1))
        bare = MultiSourceBWT(None, wrapped.source_index)
        with self.assertRaises(MultiSourceQueryError):
            list(bare.maximalRepeats())


@unittest.skipUnless(HAS_11C, "Feature 11C not in the selected package")
class RandomizedAndLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="lcp11c-rnd-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_randomized_collections(self):
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(3):
                reads_by_source = {}
                motif = "".join(rng.choice("ACGT") for _ in range(5))
                for i in range(rng.randint(2, 4)):
                    reads = []
                    for _ in range(rng.randint(1, 4)):
                        if reads and rng.random() < 0.2:
                            reads.append(rng.choice(reads))
                            continue
                        left = "".join(rng.choice("ACGTN")
                                       for _ in range(rng.randint(0, 4)))
                        right = "".join(rng.choice("ACGT")
                                        for _ in range(rng.randint(0, 4)))
                        middle = motif if rng.random() < 0.6 else ""
                        reads.append(left + middle + right or "A")
                    reads_by_source["R%d" % i] = reads
                case_dir = os.path.join(
                    self.work, "case_%d_%d" % (seed_index, case))
                os.mkdir(case_dir)
                fixture = IntervalFixture(case_dir, reads_by_source)
                for supermaximal in (False, True):
                    got = {
                        r["sequence"].decode("ascii"): r["occurrences"]
                        for r in fixture.wrapped.maximalRepeats(
                            supermaximal=supermaximal)}
                    expected = {
                        w: len(occ) for w, occ in oracle_repeats(
                            reads_by_source,
                            supermaximal=supermaximal).items()}
                    self.assertEqual(got, expected,
                                     (seed, case, supermaximal))

    def test_repeats_after_lcp_preserving_removal(self):
        from MUS.SourceRemoval import remove_sources
        fixture = IntervalFixture(self.work, REPEAT_READS)
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(fixture.output, reduced, sources=["S2"])
        self.assertTrue(stats["lcp_preserved"])
        keep = {s: r for s, r in REPEAT_READS.items() if s != "S2"}
        f11a.save_expected_rows(reduced, fixture.leaves, keep)
        oracle = f9.OracleReadIdentity(
            reduced, {s: fixture.leaves[s] for s in keep}, keep)
        read_index = ReadProvenanceIndex(reduced, mmap=False)
        wrapped = MultiSourceBWT(
            None, read_index.source_index, read_provenance=read_index,
            lcp_index=LCPIndex(reduced))
        wrapped.bwt = f9.OracleBWTAdapter(
            oracle, reduced, f9.load_manifest(reduced, validate=True))
        got = {r["sequence"].decode("ascii"): r["occurrences"]
               for r in wrapped.maximalRepeats()}
        expected = {w: len(o) for w, o in oracle_repeats(keep).items()}
        self.assertEqual(got, expected)


@unittest.skipUnless(HAS_11C, "Feature 11C not in the selected package")
class CompiledSpellingTests(unittest.TestCase):
    """The repeat spelling path against the real compiled Holt BWT."""

    def setUp(self):
        try:
            from MUSCython import MultiStringBWTCython
        except ImportError:
            self.skipTest("compiled MUSCython extensions not built")
        self.loader = MultiStringBWTCython
        self.work = tempfile.mkdtemp(prefix="lcp11c-compiled-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_compiled_sequences_match_oracle(self):
        fixture = IntervalFixture(self.work, REPEAT_READS)
        compiled = self.loader.loadBWT(fixture.output, useMemmap=False)
        expected = oracle_repeats(REPEAT_READS)
        fixture.wrapped.bwt = compiled
        got = {r["sequence"].decode("ascii"): r["occurrences"]
               for r in fixture.wrapped.maximalRepeats()}
        self.assertEqual(got, {w: len(o) for w, o in expected.items()})

    def test_cli_repeats(self):
        import json
        import subprocess
        import sys
        fixture = IntervalFixture(self.work, REPEAT_READS)
        package = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "packages", "msbwt-modern3"))
        env = dict(os.environ)
        env["PYTHONPATH"] = package
        result = subprocess.run(
            [sys.executable, os.path.join(package, "tools", "lcp.py"),
             "repeats", "--input", fixture.output, "--min-length", "3",
             "--include-sources", "--include-read-count"],
            env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        expected = oracle_repeats(REPEAT_READS, min_length=3)
        self.assertEqual(
            {r["sequence"]: r["occurrences"] for r in records},
            {w: len(o) for w, o in expected.items()})
        for record in records:
            self.assertEqual(
                record["read_count"],
                reads_containing(REPEAT_READS, record["sequence"]))


if __name__ == "__main__":
    unittest.main()
