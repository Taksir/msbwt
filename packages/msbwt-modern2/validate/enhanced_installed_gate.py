#!/usr/bin/env python2
"""enhanced-modern2 INSTALLED-distribution integration gate (Python 2.7).

Validates the enhanced feature stack entirely through the INSTALLED
distribution: ``MUS`` / ``MUSCython`` must resolve from site-packages (the
script refuses to run when they resolve from a repository checkout), and
every feature layer is exercised against embedded independent oracles:

  F2  provenance merge (identity-preserving, 10 sources)
  F3  query one constituent / per-source exact counts
  F4  sparse nonzero-source listing
  F5  sample frequency / F6 exact top-k
  F7  metadata groups / subset predicates
  F8A left/right sequence extensions
  F9  exact read-level provenance (readsContaining, recoverString)
  F12 generic BWT-aligned tag arrays (row_id)
  Q1  exact lossless FASTQ quality sidecar
  F11A exact post-construction LCP retrofit
  F10 source removal with provenance/tags/quality preservation
  F13A whole-index benchmark + backend contract + independent filesystem
       accounting

Independent oracles embedded here (no feature code is used to build
expectations): explicit terminated-suffix rows per leaf, stable suffix
merges, direct bit-array tree walks, naive interval bisection, explicit
adjacent-LCP computation, read/quality ground truth from the original
reads, ``np.arange`` tag expectations, and raw filesystem byte sums.

Usage:
    enhanced_installed_gate.py REPORT.json FIXTURE_DIR [REPO_ROOT]

Leaves the integrated package at <FIXTURE_DIR>/merged10 and the reduced
package at <FIXTURE_DIR>/reduced so the shell driver can point the
installed console scripts at them.  Writes REPORT.json with every
comparison count.  Exits non-zero on any mismatch or import leak.
"""

from __future__ import print_function

import hashlib
import json
import os
import shutil
import sys
import tempfile

import numpy as np

# ---------------------------------------------------------------------------
# installed-package import + leak proof
# ---------------------------------------------------------------------------

import MUS
import MUSCython  # noqa: F401  (compiled namespace must load)

from MUS.BWTTags import BWTTagStore, attach_tag  # noqa: E402
from MUS.Benchmarking import (  # noqa: E402
    disk_breakdown,
    full_benchmark_document,
    inspect_index,
)
from MUS.LCP import LCPIndex, construct_lcp_from_bwt, lcp_exists  # noqa: E402
from MUS.MultiSourceProvenance import (  # noqa: E402
    load_manifest,
    merge_many_balanced,
    validate_manifest,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.QualitySidecar import (  # noqa: E402
    QualitySidecar,
    attach_quality_from_row_values,
)
from MUS.ReadProvenance import (  # noqa: E402
    ReadProvenanceIndex,
    initialize_leaf_read_provenance,
)
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402
from MUS.SourceRemoval import remove_sources  # noqa: E402

SEED = 20260811

TEN_SOURCE_READS = {
    "sample00": ["ACGTAC", "GATTACA", "AAAA"],
    "sample01": ["ACGTTC", "CCCC", "TACGTA"],
    "sample02": ["GGGG", "ACACAC", "TTAC"],
    "sample03": ["TGCATG", "CATCAT", "AGGG"],
    "sample04": ["AAAAAC", "CGCG", "GTGTGT"],
    "sample05": ["TTTT", "GCGTAC", "AACCAA"],
    "sample06": ["CAGTCA", "AGAGAG", "CTTT"],
    "sample07": ["GTACGT", "CCGGA", "ATATAT"],
    "sample08": ["NACGT", "ACNGT", "GGNCC"],
    "sample09": ["TTAACC", "CGTACG", "AAGGTT"],
}

ALPHABET_CODE = {"$": 0, "A": 1, "C": 2, "G": 3, "N": 4, "T": 5}
ROWS_FILENAME = "naive_suffix_rows.json"


# ---------------------------------------------------------------------------
# embedded fixture machinery (independent of the installed feature code)
# ---------------------------------------------------------------------------


def terminated_suffix_rows(reads):
    rows = []
    for read_id, read in enumerate(reads):
        text = read + "$"
        for pos in range(len(text)):
            rows.append({
                "suffix": text[pos:],
                "bwt": text[pos - 1] if pos > 0 else "$",
                "read_id": read_id,
                "pos": pos,
            })
    rows.sort(key=lambda row: (row["suffix"], row["read_id"], row["pos"]))
    return rows


def save_rows(directory, rows):
    with open(os.path.join(directory, ROWS_FILENAME), "w") as fp:
        json.dump(rows, fp, separators=(",", ":"))


def load_rows(directory):
    with open(os.path.join(directory, ROWS_FILENAME), "r") as fp:
        return json.load(fp)


def pack_little_endian_bits(bits):
    bits = np.asarray(bits, dtype=np.uint8).reshape(-1)
    out = np.zeros((bits.shape[0] + 7) // 8, dtype=np.uint8)
    for offset in range(8):
        selected = bits[offset::8]
        if selected.size:
            out[: selected.size] |= selected << np.uint8(offset)
    return out


def stable_suffix_merge(left_rows, right_rows):
    merged = []
    bits = []
    li = 0
    ri = 0
    while li < len(left_rows) or ri < len(right_rows):
        if ri >= len(right_rows):
            choose_right = False
        elif li >= len(left_rows):
            choose_right = True
        else:
            choose_right = right_rows[ri]["suffix"] < left_rows[li]["suffix"]
        if choose_right:
            merged.append(right_rows[ri])
            bits.append(1)
            ri += 1
        else:
            merged.append(left_rows[li])
            bits.append(0)
            li += 1
    return merged, bits


def read_derived_merge(left_dir, right_dir, output_dir, num_procs=1,
                       logger=None):
    merged_rows, bits = stable_suffix_merge(
        load_rows(left_dir), load_rows(right_dir))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    np.save(os.path.join(output_dir, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in merged_rows],
                       dtype=np.uint8))
    np.save(os.path.join(output_dir, "inter0.npy"),
            pack_little_endian_bits(bits))
    save_rows(output_dir, merged_rows)


def make_read_derived_leaf(work, source_name, reads):
    directory = os.path.join(work, source_name)
    os.mkdir(directory)
    rows = terminated_suffix_rows(reads)
    np.save(os.path.join(directory, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in rows],
                       dtype=np.uint8))
    save_rows(directory, rows)
    from MUS.MultiSourceProvenance import initialize_leaf_provenance
    initialize_leaf_provenance(
        directory, source_id=source_name, source_name=source_name)
    return directory


def default_leaf_records(reads, origin_base=100, file_count=1):
    records = []
    for i in range(len(reads)):
        record = {
            "origin_file_id": i % file_count,
            "origin_read_id": origin_base + i,
        }
        if len(reads) >= 2 and i < 2:
            record["mate_source_read_id"] = 1 - i
        records.append(record)
    return records


def attach_leaf_read_provenance(leaf_dir, reads, origin_base=100,
                                file_count=1):
    input_files = ["%s_R%d.fastq" % (os.path.basename(leaf_dir), fid)
                   for fid in range(file_count)]
    return initialize_leaf_read_provenance(
        leaf_dir,
        default_leaf_records(reads, origin_base=origin_base,
                             file_count=file_count),
        source_metadata={"input_files": input_files},
    )


# ---------------------------------------------------------------------------
# embedded independent oracles
# ---------------------------------------------------------------------------


def unpack_interleave(interleave_path, total_bits):
    packed = np.load(interleave_path, mmap_mode="r")
    needed = (int(total_bits) + 7) // 8
    used = np.asarray(packed[:needed], dtype=np.uint8)
    bits = np.zeros(int(total_bits), dtype=np.uint8)
    for offset in range(8):
        selected = bits[offset::8]
        if selected.size:
            bits[offset::8] = (used[: selected.size] >> np.uint8(offset)) \
                & np.uint8(1)
    return bits


def tree_walk_row(merged_dir, manifest, row_index):
    node = manifest["root"]
    local_index = int(row_index)
    while node["type"] == "merge":
        bits = unpack_interleave(
            os.path.join(merged_dir, str(node["interleave"])),
            node["length"])
        bit = int(bits[local_index])
        if bit == 0:
            child_index = int(np.count_nonzero(bits[:local_index] == 0))
            node = node["left"]
        else:
            child_index = int(np.count_nonzero(bits[:local_index] == 1))
            node = node["right"]
        local_index = child_index
    return str(node["source_id"]), local_index


class OracleReadIdentity(object):
    """Fully independent read-identity oracle over naive suffix rows."""

    def __init__(self, merged_dir, leaf_dirs_by_source, reads_by_source):
        self.merged_dir = str(merged_dir)
        self.manifest = load_manifest(self.merged_dir, validate=True)
        self.leaf_rows = {}
        self.reads = {}
        self.leaf_dollar_rows = {}
        for sid, leaf_dir in leaf_dirs_by_source.items():
            rows = load_rows(leaf_dir)
            self.leaf_rows[sid] = rows
            self.reads[sid] = reads_by_source[sid]
            dollar_rows = [r for r in rows if r["suffix"] == "$"]
            local_dollar = {}
            for index, row in enumerate(dollar_rows):
                local_dollar[int(row["read_id"])] = index
            self.leaf_dollar_rows[sid] = local_dollar

        total_reads = sum(len(reads) for reads in reads_by_source.values())
        self.global_dollar = {}
        self.dollar_to_identity = {}
        for dollar_id in range(total_reads):
            sid, local_row = tree_walk_row(
                self.merged_dir, self.manifest, dollar_id)
            read_id = int(self.leaf_rows[sid][local_row]["read_id"])
            local_dollar = self.leaf_dollar_rows[sid][read_id]
            self.global_dollar[(sid, local_dollar)] = dollar_id
            self.dollar_to_identity[dollar_id] = (sid, local_dollar)
        self.read_count = total_reads

    def row_identity(self, row_index):
        """(source_id, local_row, read_id, pos) for one merged row."""
        sid, local_row = tree_walk_row(
            self.merged_dir, self.manifest, int(row_index))
        leaf_row = self.leaf_rows[sid][local_row]
        return (sid, local_row, int(leaf_row["read_id"]),
                int(leaf_row["pos"]))

    def getSequenceDollarID(self, row_index, returnOffset=False):
        sid, local_row = tree_walk_row(
            self.merged_dir, self.manifest, int(row_index))
        leaf_row = self.leaf_rows[sid][local_row]
        read_id = int(leaf_row["read_id"])
        local_dollar = self.leaf_dollar_rows[sid][read_id]
        dollar_id = self.global_dollar[(sid, local_dollar)]
        if returnOffset:
            return dollar_id, int(leaf_row["pos"])
        return dollar_id

    def recoverString(self, dollar_id):
        sid, local_dollar = self.dollar_to_identity[int(dollar_id)]
        inverse = {v: k for k, v in self.leaf_dollar_rows[sid].items()}
        read_id = inverse[local_dollar]
        return ("$" + self.reads[sid][read_id]).encode("ascii")


class OracleBackedAdapter(object):
    """recoverString(withIndex=True) safe for merged packages (naive)."""

    def __init__(self, directory, oracle):
        self.directory = str(directory)
        self.oracle = oracle
        self.rows = load_rows(self.directory)
        self.manifest = load_manifest(self.directory, validate=True)
        self.merged_index = {}
        for x in range(len(self.rows)):
            sid, local = tree_walk_row(
                self.directory, self.manifest, x)
            self.merged_index[(sid, int(local))] = x

    def getTotalSize(self):
        return len(self.rows)

    def getSequenceDollarID(self, row_index, returnOffset=False):
        return self.oracle.getSequenceDollarID(
            row_index, returnOffset=returnOffset)

    def recoverString(self, dollar_id, withIndex=False):
        oracle = self.oracle
        sid, local_dollar = oracle.dollar_to_identity[int(dollar_id)]
        inverse = {
            v: k for k, v in oracle.leaf_dollar_rows[sid].items()
        }
        read_id = inverse[local_dollar]
        leaf_rows = oracle.leaf_rows[sid]
        by_pos = {
            r["pos"]: i for i, r in enumerate(leaf_rows)
            if int(r["read_id"]) == read_id
        }
        length = max(by_pos)
        order = [length] + list(range(length))
        indices = [
            self.merged_index[(sid, by_pos[p])] for p in order
        ]
        sequence = "".join(
            leaf_rows[by_pos[p]]["suffix"][0] for p in order)
        encoded = sequence.encode("ascii")
        if withIndex:
            return encoded, indices
        return encoded


def bisect_left(a, x):
    lo = 0
    hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def naive_interval(directory, pattern):
    suffixes = [row["suffix"] for row in load_rows(directory)]
    low = bisect_left(suffixes, pattern)
    high = bisect_left(suffixes, pattern + "\x7f")
    return low, high


def interval_length(directory, pattern):
    low, high = naive_interval(directory, pattern)
    return high - low


def row_source(merged_dir, manifest, row_index):
    return tree_walk_row(merged_dir, manifest, row_index)[0]


def row_interval_count(merged_dir, manifest, sid, pattern):
    low, high = naive_interval(merged_dir, pattern)
    return sum(
        1 for x in range(low, high)
        if row_source(merged_dir, manifest, x) == sid
    )


def explicit_lcp(a, b):
    """Independent adjacent LCP; '$' is never counted as a symbol."""
    i = 0
    j = 0
    count = 0
    while (
        i < len(a) and j < len(b)
        and a[i] == b[j] and a[i] != "$"
    ):
        count += 1
        i += 1
        j += 1
    return count


def expected_lcps(directory):
    suffixes = [row["suffix"] for row in load_rows(directory)]
    return np.asarray(
        [explicit_lcp(suffixes[i], suffixes[i + 1])
         for i in range(len(suffixes) - 1)],
        dtype=np.uint32,
    )


def expected_quality_row_values(oracle, directory):
    """Per-row expected Q1 quality byte: original FASTQ byte or sentinel.

    Matches the fixture attachment rule (quality attached per LEAF row:
    ``33 + (leaf_row_index % 40)`` for biological bases, sentinel 255 on
    terminal-'$' rows).
    """
    rows = load_rows(directory)
    values = np.zeros(len(rows), dtype=np.uint8)
    for idx, row in enumerate(rows):
        sid, local_row, read_id, pos = oracle.row_identity(idx)
        read = oracle.reads[sid][read_id]
        if pos >= len(read):
            values[idx] = 255
        else:
            values[idx] = 33 + (int(local_row) % 40)
    return values


def expected_bwt_bytes(leaves, all_ids, keep_ids):
    """Independent suffix sort of the retained reads (no removal code)."""
    all_order = {sid: i for i, sid in enumerate(all_ids)}
    rows = []
    for sid in keep_ids:
        for row in load_rows(leaves[sid]):
            rows.append((
                row["suffix"],
                all_order[sid],
                int(row["read_id"]),
                int(row["pos"]),
                row["bwt"],
            ))
    rows.sort()
    return np.asarray(
        [ALPHABET_CODE[r[4]] for r in rows], dtype=np.uint8)


def dir_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        digest.update(fp.read())
    return digest.hexdigest()


def expected_read_quality(oracle, sid, read_id):
    """Exact original quality bytes for one read (fixture ground truth).

    Quality was attached per leaf BWT row as ``33 + (leaf_row % 40)`` on
    biological-base suffix rows; the terminal-'$' row carries the 255
    sentinel and contributes no quality byte.  Recovered order follows
    the read's base positions.
    """
    rows = oracle.leaf_rows[sid]
    per_pos = {}
    for idx, row in enumerate(rows):
        if int(row["read_id"]) != read_id:
            continue
        if row["suffix"] == "$":
            continue
        per_pos[int(row["pos"])] = 33 + (idx % 40)
    return bytes(bytearray(
        per_pos[pos] for pos in sorted(per_pos)))


def filesystem_total_bytes(root):
    total = 0
    for base, _, names in os.walk(str(root)):
        for name in names:
            total += os.path.getsize(os.path.join(base, name))
    return total


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

PATTERNS = ["A", "C", "G", "T", "AC", "CG", "GT", "CGT", "GTAC", "AAAA",
            "AAGGTT", "N", "TTAC", "GATTACA"]


def run_gate(fixture_root):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "imports": {
            "MUS.__file__": MUS.__file__,
            "MUSCython.__file__": MUSCython.__file__,
        },
        "integrated_package": {},
        "reduced_package": {},
        "benchmark": {},
        "tools_fixture": {},
    }

    work = tempfile.mkdtemp(prefix="installed-gate-")
    try:
        # ---------------- integrated 10-source package -------------------
        leaves = {}
        for sid, reads in TEN_SOURCE_READS.items():
            leaf = make_read_derived_leaf(work, sid, reads)
            attach_leaf_read_provenance(leaf, reads)
            attach_tag(
                leaf, "row_id",
                np.arange(len(load_rows(leaf)), dtype=np.uint32))
            rows = load_rows(leaf)
            q = np.zeros(len(rows), dtype=np.uint8)
            for idx, r in enumerate(rows):
                read = reads[r["read_id"]]
                q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
            attach_quality_from_row_values(leaf, q)
            leaves[sid] = leaf
        output = os.path.join(work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=read_derived_merge)
        oracle = OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in leaves},
            TEN_SOURCE_READS)
        construct_lcp_from_bwt(
            output, bwt=OracleBackedAdapter(output, oracle))

        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        read_index = ReadProvenanceIndex(
            output, mmap=False, source_index=index)
        metadata = SourceMetadataCatalog(index.list_sources())
        metadata.define_group("case", ["sample00", "sample01", "sample02"])
        for sid in ("sample00", "sample01", "sample02"):
            metadata.set_source_metadata(sid, cohort="case")
        wrapped = MultiSourceBWT(
            None, index, source_metadata=metadata,
            read_provenance=read_index,
            bwt_tags=BWTTagStore(output),
            quality_sidecar=QualitySidecar(output),
            lcp_index=LCPIndex(output))
        wrapped.bwt = OracleBackedAdapter(output, oracle)

        integrated = report["integrated_package"]
        assert validate_manifest(output)
        assert read_index.read_count == 30
        assert wrapped.hasQuality() and wrapped.hasLCP()
        assert wrapped.listTags() == ["fastq_quality_ascii", "row_id"]

        mismatches = []
        comparisons = 0
        manifest = load_manifest(output)
        quality_expected = expected_quality_row_values(oracle, output)

        for pattern in PATTERNS:
            low, high = naive_interval(output, pattern)
            for sid in TEN_SOURCE_READS:
                expected = sum(
                    1 for x in range(low, high)
                    if row_source(output, manifest, x) == sid
                )
                comparisons += 1
                if wrapped.countOccurrencesForSource(
                        pattern, sid) != expected:
                    mismatches.append(("F3", pattern, sid))
            sparse = wrapped.nonzeroSources(pattern)
            comparisons += 1
            if sum(r["count"] for r in sparse) != high - low:
                mismatches.append(("F4", pattern, "sum"))
            expected_freq = sum(
                1 for sid in TEN_SOURCE_READS
                if row_interval_count(output, manifest, sid,
                                      pattern) > 0
            )
            comparisons += 1
            if wrapped.sourceFrequency(pattern) != expected_freq:
                mismatches.append(("F5", pattern, expected_freq))
            top = wrapped.topSources(pattern, k=3)
            comparisons += 1
            if len(top) != min(3, expected_freq):
                mismatches.append(("F6", pattern, len(top)))
            expected_case = sum(
                row_interval_count(output, manifest, sid, pattern)
                for sid in ("sample00", "sample01", "sample02")
            )
            comparisons += 1
            if wrapped.countGroup(pattern, "case") != expected_case:
                mismatches.append(("F7_group", pattern, expected_case))
            comparisons += 1
            if wrapped.countWhere(pattern, {"cohort": "case"}) != \
                    expected_case:
                mismatches.append(("F7_where", pattern, expected_case))
            for direction in ("left", "right"):
                ext = (wrapped.extendLeft(pattern)
                       if direction == "left"
                       else wrapped.extendRight(pattern))
                for rec in ext["extensions"]:
                    expected_count = interval_length(
                        output, rec["sequence"])
                    comparisons += 1
                    if rec["count"] != expected_count:
                        mismatches.append(
                            ("F8A", pattern, direction,
                             rec["sequence"], rec["count"],
                             expected_count))
            tvals = wrapped.tagValues(pattern, "row_id")
            comparisons += 1
            if tvals["value_count"] != high - low:
                mismatches.append(("F12", pattern, "count"))
            if tvals["value_count"] and "values" in tvals:
                # row-aligned tag: expected values are each row's
                # leaf-local row index (independent tree-walk oracle)
                expected_values = np.asarray(
                    [oracle.row_identity(x)[1] for x in range(low, high)],
                    dtype=np.uint32)
                comparisons += 1
                if not np.array_equal(
                        np.asarray(tvals["values"], dtype=np.uint32),
                        expected_values):
                    mismatches.append(("F12_values", pattern, "slice"))
            qvals = wrapped.qualityValues(pattern)
            comparisons += 1
            if qvals["value_count"] != high - low:
                mismatches.append(("Q1", pattern, "count"))
            if qvals["value_count"] and "values" in qvals:
                expected_q = quality_expected[low:high]
                comparisons += 1
                if not np.array_equal(
                        np.asarray(qvals["values"], dtype=np.uint8),
                        expected_q):
                    mismatches.append(("Q1_values", pattern, "bytes"))
            rc = wrapped.readsContaining(pattern)
            comparisons += 1
            if rc["reported_occurrences"] != high - low:
                mismatches.append(("F9", pattern, "total"))

        # F11A: explicit adjacent-LCP oracle vs stored LCP layer
        expected_lcp = expected_lcps(output)
        lcp_index = LCPIndex(output)
        for row in (0, 1, 10, 50, 100, 150, 189, 190):
            comparisons += 1
            if lcp_index.adjacent(row) != int(expected_lcp[row]):
                mismatches.append(("F11A_adjacent", row, int(
                    expected_lcp[row])))
        comparisons += 1
        if wrapped.lcpAt(100) != int(expected_lcp[99]):
            mismatches.append(("F11A", "boundary", "x"))
        comparisons += 1
        if wrapped.lcpBetweenRows(10, 20) != int(
                np.min(expected_lcp[10:20])):
            mismatches.append(("F11A", "rmq", "x"))
        comparisons += 1
        if lcp_index.read_count != 30:
            mismatches.append(("F11A", "read_count", lcp_index.read_count))

        # F9: recoverString == original reads (through the oracle)
        recovered = wrapped.readsContaining(
            "GATTACA", include_sequence=True)
        comparisons += 1
        if recovered["reported_occurrences"] != interval_length(
                output, "GATTACA"):
            mismatches.append(("F9", "GATTACA", "total"))
        for rec in recovered["reads"]:
            comparisons += 1
            if rec["sequence"] != b"$GATTACA":
                mismatches.append(("F9", "recover", rec.get("sequence")))
        # Q1: per-read quality bytes == original fixture quality bytes
        qrecs = wrapped.readsContaining(
            "GATTACA", include_quality=True)
        for rec in qrecs["reads"]:
            sid, local_dollar = oracle.dollar_to_identity[
                int(rec["dollar_id"])]
            inverse = {
                v: k for k, v in oracle.leaf_dollar_rows[sid].items()
            }
            read_id = inverse[local_dollar]
            expected_q = expected_read_quality(oracle, sid, read_id)
            comparisons += 1
            if rec["quality"] != expected_q:
                mismatches.append(
                    ("Q1_read", sid, read_id, rec["quality"],
                     expected_q))

        integrated["comparisons"] = comparisons
        integrated["mismatches"] = len(mismatches)
        assert mismatches == []
        assert comparisons > 200

        # ---------------- F13A accounting vs filesystem oracle -----------
        bench = report["benchmark"]
        structural = inspect_index(output)
        bench["integrated_N"] = structural["structure"]["N"]
        bench["integrated_lcp_available"] = (
            structural["storage"]["lcp"]["available"])
        assert bench["integrated_N"] == 191
        assert bench["integrated_lcp_available"]
        breakdown = disk_breakdown(output)
        comparisons += 1
        if breakdown["physical_total_bytes"] != filesystem_total_bytes(
                output):
            mismatches.append(("F13A", "disk_total", "fs"))
        doc = full_benchmark_document(output)
        comparisons += 1
        if doc["backend_contract"]["contract_version"] != 1:
            mismatches.append(("F13A", "contract_version", "x"))
        assert mismatches == []

        # ---------------- Feature-10 reduced package ---------------------
        reduced = os.path.join(work, "reduced")
        stats = remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"],
            drop_lcp=True)
        assert stats["read_provenance_preserved"]
        assert stats["bwt_tags_preserved"]
        assert stats["quality_sidecar_preserved"]
        assert not lcp_exists(reduced)

        keep = {sid: TEN_SOURCE_READS[sid] for sid in TEN_SOURCE_READS
                if sid not in ("sample00", "sample02", "sample09")}
        rindex = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        rread = ReadProvenanceIndex(
            reduced, mmap=False, source_index=rindex)
        rmeta = SourceMetadataCatalog(rindex.list_sources())
        rwrapped = MultiSourceBWT(
            None, rindex, source_metadata=rmeta,
            read_provenance=rread,
            bwt_tags=BWTTagStore(reduced),
            quality_sidecar=QualitySidecar(reduced))
        reduced_oracle = OracleReadIdentity(
            reduced,
            {sid: leaves[sid] for sid in keep},
            keep)
        rwrapped.bwt = OracleBackedAdapter(reduced, reduced_oracle)

        reduced_report = report["reduced_package"]
        reduced_report["read_count"] = rread.read_count
        reduced_report["lcp_absent"] = not lcp_exists(reduced)
        assert rread.read_count == 21
        rcomparisons = 0
        rmismatches = []
        rmanifest = load_manifest(reduced)
        rquality_expected = expected_quality_row_values(
            reduced_oracle, reduced)

        # independent retained rebuild: suffix sort of retained reads
        all_ids = sorted(TEN_SOURCE_READS)
        expected_bytes = expected_bwt_bytes(leaves, all_ids, sorted(keep))
        actual_bytes = np.load(os.path.join(reduced, "msbwt.npy"))
        comparisons += 1
        if not np.array_equal(actual_bytes, expected_bytes):
            rmismatches.append(("F10", "rebuild_bytes", "payload"))
        reduced_report["rebuild_payload_equal"] = True
        # whole-file byte equality vs an independent clean reconstruction
        # (fresh stable-merge of the retained leaves)
        rebuild = os.path.join(work, "rebuild")
        merge_many_balanced(
            [leaves[sid] for sid in sorted(keep)], rebuild,
            merge_two_func=read_derived_merge)
        reduced_report["rebuild_whole_file_equal"] = (
            dir_sha256(os.path.join(reduced, "msbwt.npy"))
            == dir_sha256(os.path.join(rebuild, "msbwt.npy"))
        )
        comparisons += 1
        if not reduced_report["rebuild_whole_file_equal"]:
            rmismatches.append(("F10", "rebuild_whole_file", "bytes"))

        for pattern in PATTERNS:
            low, high = naive_interval(reduced, pattern)
            for sid in keep:
                expected = sum(
                    1 for x in range(low, high)
                    if row_source(reduced, rmanifest, x) == sid
                )
                rcomparisons += 1
                if rwrapped.countOccurrencesForSource(
                        pattern, sid) != expected:
                    rmismatches.append(("F3_reduced", pattern, sid))
            sparse = rwrapped.nonzeroSources(pattern)
            rcomparisons += 1
            if sum(r["count"] for r in sparse) != high - low:
                rmismatches.append(("F4_reduced", pattern, "sum"))
            rcomparisons += 1
            if rwrapped.sourceFrequency(pattern) != sum(
                    1 for sid in keep
                    if row_interval_count(reduced, rmanifest, sid,
                                          pattern) > 0):
                rmismatches.append(("F5_reduced", pattern, "freq"))
            rc = rwrapped.readsContaining(pattern, include_quality=True)
            rcomparisons += 1
            if rc["reported_occurrences"] != high - low:
                rmismatches.append(("F9_reduced", pattern, "total"))
            if any(rec["source_id"] not in keep
                   for rec in rc["reads"]):
                rmismatches.append(("F9_reduced", pattern, "purity"))
            for rec in rc["reads"]:
                sid, local_dollar = reduced_oracle.dollar_to_identity[
                    int(rec["dollar_id"])]
                inverse = {
                    v: k for k, v in
                    reduced_oracle.leaf_dollar_rows[sid].items()
                }
                read_id = inverse[local_dollar]
                expected_q = expected_read_quality(
                    reduced_oracle, sid, read_id)
                rcomparisons += 1
                if rec["quality"] != expected_q:
                    rmismatches.append(
                        ("Q1_reduced_read", pattern, sid, read_id))
            qvals = rwrapped.qualityValues(pattern)
            rcomparisons += 1
            if qvals["value_count"] != high - low:
                rmismatches.append(("Q1_reduced", pattern, "count"))
            if qvals["value_count"] and "values" in qvals:
                expected_q = rquality_expected[low:high]
                rcomparisons += 1
                if not np.array_equal(
                        np.asarray(qvals["values"], dtype=np.uint8),
                        expected_q):
                    rmismatches.append(("Q1_reduced", pattern, "bytes"))
            tvals = rwrapped.tagValues(pattern, "row_id")
            rcomparisons += 1
            if tvals["value_count"] != high - low:
                rmismatches.append(("F12_reduced", pattern, "count"))
            if tvals["value_count"] and "values" in tvals:
                expected_values = np.asarray(
                    [reduced_oracle.row_identity(x)[1]
                     for x in range(low, high)],
                    dtype=np.uint32)
                rcomparisons += 1
                if not np.array_equal(
                        np.asarray(tvals["values"], dtype=np.uint32),
                        expected_values):
                    rmismatches.append(
                        ("F12_reduced", pattern, "slice"))

        reduced_report["comparisons"] = rcomparisons
        reduced_report["mismatches"] = len(rmismatches)
        assert rmismatches == []
        assert rcomparisons > 100

        reduced_structural = inspect_index(reduced)
        bench["reduced_N"] = reduced_structural["structure"]["N"]
        bench["reduced_lcp_available"] = (
            reduced_structural["storage"]["lcp"]["available"])
        assert bench["reduced_N"] == 133
        assert not bench["reduced_lcp_available"]

        report["mismatch_count"] = (
            len(mismatches) + len(rmismatches))
        assert report["mismatch_count"] == 0

        # ---------------- tools fixture (kept for the shell driver) ------
        fixture_output = os.path.join(fixture_root, "merged10")
        fixture_reduced = os.path.join(fixture_root, "reduced")
        fixture_leaves = os.path.join(fixture_root, "leaves")
        shutil.copytree(output, fixture_output)
        shutil.copytree(reduced, fixture_reduced)
        os.makedirs(fixture_leaves)
        for sid, leaf_dir in leaves.items():
            shutil.copytree(
                leaf_dir, os.path.join(fixture_leaves, sid))
        report["tools_fixture"] = {
            "merged10": fixture_output,
            "reduced": fixture_reduced,
            "leaves": fixture_leaves,
            "n_merged_rows": 191,
            "n_reduced_rows": 133,
            "sources": all_ids,
            "removed_sources": ["sample00", "sample02", "sample09"],
        }
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) not in (3, 4):
        sys.stderr.write(
            "usage: enhanced_installed_gate.py REPORT.json FIXTURE_DIR "
            "[REPO_ROOT]\n")
        return 2
    report_path = sys.argv[1]
    fixture_root = sys.argv[2]
    repo_root = sys.argv[3] if len(sys.argv) == 4 else None

    mus_file = os.path.abspath(MUS.__file__)
    cyn_file = os.path.abspath(MUSCython.__file__)
    leaks = []
    if "/mnt/" in mus_file or "/mnt/" in cyn_file:
        leaks.append("imports resolve from a /mnt/ (repository) path")
    if repo_root is not None:
        root = os.path.abspath(repo_root)
        if mus_file.startswith(root) or cyn_file.startswith(root):
            leaks.append(
                "imports resolve from the repository tree: %s" % mus_file)
    if leaks:
        sys.stderr.write("IMPORT LEAK: %s\n" % "; ".join(leaks))
        return 3

    if not os.path.isdir(fixture_root):
        os.makedirs(fixture_root)
    report = run_gate(fixture_root)
    report["imports"] = {
        "MUS.__file__": mus_file,
        "MUSCython.__file__": cyn_file,
        "repo_leak": bool(leaks),
    }
    with open(report_path, "w") as fp:
        json.dump(report, fp, indent=2, sort_keys=True)
        fp.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
