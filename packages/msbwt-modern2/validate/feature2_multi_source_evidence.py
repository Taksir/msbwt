"""Feature-2 multi-source provenance evidence generator (runs inside the
pinned Python-2.7 environment; invoked by
validate/feature2-multi-source-provenance.sh).

Executes, against REAL modern2 construction (``pp`` + ``cfpp``) and REAL
``GenericMerge.mergeTwoMSBWTs`` through the Feature-2 adapter:

- canonical two-source fixture merge, including the Feature-1 compatibility
  contract (row-level provenance agreement with ``MUS.SourceIndex`` and
  per-query source-count agreement);
- multi-stage merge provenance: 3-source chain, 4-source balanced,
  4-source unbalanced ``((A+B)+C)+D``, 5-source balanced, 10-source balanced;
  every original source identity is proven to survive each merge stage by
  exact constituent recovery (``extract_constituent_bwt`` == standalone
  ``msbwt.npy`` bit-for-bit) plus an independent rotation-sort block oracle
  (every unambiguous row exact; tied rows by per-source multiplicity) and
  order-independent per-symbol joint provenance + LF-recovered multiset
  checks;
- the deterministic 3-source edge corpus (12 classes: unequal sizes,
  duplicates, identical reads across sources, all-identical, prefix/suffix
  sharing, N-heavy, single-base, mixed lengths, repeated motifs,
  lexicographically similar);
- a 40-dataset randomized suite (seed 20260811, 3-8 sources) plus 4 explicit
  10-source datasets: extraction exactness, per-source totals, BWT-length
  invariant, persistence/reload;
- persistence/corruption probes: same-length replaced BWT, manifest copied
  from another index, same-length same-count replaced interleave, truncated
  manifest, wrong version, wrong-dtype interleave, missing interleave, BWT
  length mismatch -- every one must raise ``ProvenanceError``;
- atomic-write probe (no ``.tmp`` left behind, deterministic manifest bytes);
- performance/storage sanity (bytes per row, load/validate/extract times).

Any mismatch is dumped in full and fails the run.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

PACKAGE = os.path.join(REPO, "packages", "msbwt-modern2")
# the in-tree package must win over any installed msbwt-modern2
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_source_index_py2 as f1  # noqa: E402

import numpy as np  # noqa: E402

from MUS.MultiSourceProvenance import (  # noqa: E402
    MANIFEST_FILENAME,
    ProvenanceError,
    extract_constituent_bwt,
    initialize_leaf_provenance,
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
    save_manifest,
    source_ids,
    unpack_interleave,
    validate_manifest,
)
from MUS.MultiSourceProvenance import holt_merge_two  # noqa: E402
from MUS.SourceIndex import TwoSourceBWT  # noqa: E402

SEED = f1.SEED
RANDOMIZED_DATASETS = 40
TEN_SOURCE_DATASETS = 4

SYMBOLS = "$ACGNT"


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total


def _tree_depth(node):
    if node["type"] == "leaf":
        return 0
    return 1 + max(_tree_depth(node["left"]), _tree_depth(node["right"]))


# ---------------------------------------------------------------------------
# independent oracles (do not call Feature-2 implementation logic)
# ---------------------------------------------------------------------------


def _cyclic_cmp(left, right):
    """Compare two rotation strings as cyclic (circular) sequences.

    The merged BWT orders rotations of terminated reads as CIRCULAR strings:
    after the end of one rotation the comparison wraps around to its start.
    A plain string sort disagrees with the circular order exactly when
    rotations of different-length reads share a prefix (the shorter one
    wraps to a later character).  Two strings are compared character by
    character with wrap-around; the combined period is bounded by
    len(left) * len(right), which covers the lcm.
    """
    llen = len(left)
    rlen = len(right)
    limit = llen * rlen
    for index in range(limit):
        a = left[index % llen]
        b = right[index % rlen]
        if a != b:
            return -1 if a < b else 1
    return 0


def rotation_block_oracle(reads_by_source, source_ids_order, labels,
                          total_bits):
    """Compare Feature-2 row labels against the independent rotation-sort
    prediction for uniform-route inputs.

    ``reads_by_source`` is the source-tagged input record list, so the oracle
    is fully independent of Feature-2 code.  Every rotation of every read
    (with the ``$`` terminator) is sorted in the CIRCULAR order used by the
    merged BWT; the rotation occupying final row ``x`` predicts the source of
    row ``x``.  Blocks are cyclic-equivalence classes (rotations of the same
    circular string): a class belonging to exactly one source must label
    every row in its block with that source; classes shared by several
    sources are order-ambiguous by design and are verified by per-source
    multiplicity inside the block.
    """
    from collections import Counter
    counters = []
    for reads in reads_by_source:
        rotations = []
        for read in reads:
            terminated = read + "$"
            for start in range(len(terminated)):
                rotations.append(terminated[start:] + terminated[:start])
        counters.append(Counter(rotations))

    all_rotations = set()
    for counter in counters:
        all_rotations |= set(counter)
    ordered = sorted(all_rotations, cmp=_cyclic_cmp)

    # group consecutive cyclic-equal rotations into blocks
    blocks = []
    for rotation in ordered:
        if blocks and _cyclic_cmp(blocks[-1][0], rotation) == 0:
            blocks[-1].append(rotation)
        else:
            blocks.append([rotation])

    exact_checked = 0
    tied_rows = 0
    mismatches = []
    position = 0
    for block_rotations in blocks:
        block_counts = [
            sum(counter[rotation] for rotation in block_rotations)
            for counter in counters]
        block_len = sum(block_counts)
        block = labels[position:position + block_len]
        present = [i for i, count in enumerate(block_counts) if count > 0]
        if len(present) > 1:
            for i in present:
                got = block.count(source_ids_order[i])
                if got != block_counts[i]:
                    mismatches.append(
                        "tied block %r: source %s got %d expected %d"
                        % (block_rotations[0], source_ids_order[i], got,
                           block_counts[i]))
            tied_rows += block_len
        else:
            src_id = source_ids_order[present[0]]
            if any(label != src_id for label in block):
                mismatches.append(
                    "unique block %r expected all %s, got %r"
                    % (block_rotations[0], src_id, block[:8]))
            else:
                exact_checked += block_len
        position += block_len

    if position != total_bits:
        mismatches.append("oracle covered %d rows, expected %d"
                          % (position, total_bits))
    return {
        "exact_rows_checked": exact_checked,
        "tied_rows_multiplicity_checked": tied_rows,
        "mismatches": mismatches,
    }


def lf_recover_reads(merged, total_bits):
    """Recover the read multiset from a merged BWT via LF mapping."""
    counts = [int(merged.getSymbolCount(symbol))
              for symbol in range(6)]
    c_table = [0] * 6
    running = 0
    for symbol in range(6):
        c_table[symbol] = running
        running += counts[symbol]
    occ = []
    tally = [0] * 6
    for position in range(total_bits):
        tally[int(merged.getCharAtIndex(position))] += 1
        occ.append(list(tally))

    def lf(index):
        symbol = int(merged.getCharAtIndex(index))
        return c_table[symbol] + occ[index][symbol] - 1

    reads = []
    for start in range(total_bits):
        if int(merged.getCharAtIndex(start)) != 0:
            continue
        reversed_chars = []
        index = start
        while True:
            index = lf(index)
            if int(merged.getCharAtIndex(index)) == 0:
                break
            reversed_chars.append(
                SYMBOLS[int(merged.getCharAtIndex(index))])
        reads.append("".join(reversed(reversed_chars)))
    return sorted(reads)


def row_source_labels(bwt_dir, manifest, total_bits):
    """Feature-2-side row labels: walk the saved interleave tree.

    This consumes only the persisted interleave files + tree structure; the
    oracle above is the source-tagged rotation prediction it is compared
    against.
    """
    labels = [None] * total_bits

    def walk(node, rows):
        if node["type"] == "leaf":
            for row in rows:
                labels[row] = node["source_id"]
            return
        bits = unpack_interleave(
            os.path.join(bwt_dir, str(node["interleave"])), node["length"])
        left_rows = [row for row, bit in zip(rows, bits) if bit == 0]
        right_rows = [row for row, bit in zip(rows, bits) if bit == 1]
        walk(node["left"], left_rows)
        walk(node["right"], right_rows)

    walk(manifest["root"], range(total_bits))
    return labels


# ---------------------------------------------------------------------------
# case machinery
# ---------------------------------------------------------------------------


def np_load(leaf_dir):
    return np.load(os.path.join(leaf_dir, "msbwt.npy")).copy()


def build_and_merge(harness, work, label, groups, tree):
    """Build standalone real BWTs and merge them with the REAL two-way
    GenericMerge adapter.  ``tree`` is 'balanced' (merge_many_balanced) or
    'chain' (repeated left-to-right two-way merges)."""
    ids = ["s%d" % i for i in range(len(groups))]
    leaves = []
    loaded = []
    originals = []
    for i, reads in enumerate(groups):
        leaf = harness.build_fastq_source("%s-%d" % (label, i), reads)
        # attach the stable identity before any merge so both balanced and
        # chain trees carry the requested source IDs
        initialize_leaf_provenance(leaf, source_id=ids[i], source_name=ids[i])
        leaves.append(leaf)
        loaded.append(f1.load_standalone(leaf))
        originals.append(np_load(leaf))

    if tree == "balanced":
        output = os.path.join(work, label)
        merge_many_balanced(
            leaves, output, merge_two_func=holt_merge_two,
            source_ids=ids, source_names=ids, num_procs=1)
    else:
        current = leaves[0]
        for i in range(1, len(leaves)):
            parent = os.path.join(work, "%s-st%d" % (label, i))
            merge_two_with_provenance(
                current, leaves[i], parent,
                merge_two_func=holt_merge_two, num_procs=1)
            current = parent
        output = current

    # the plain ByteBWT reader is source-count agnostic (TwoSourceBWT is a
    # two-source Feature-1 wrapper and cannot wrap 3+ source packages)
    merged_reader = f1.load_standalone(output)
    return output, ids, merged_reader, loaded, originals


def verify_package(bwt_dir, ids, reads_by_source, merged_bwt, label,
                   loaded, originals):
    """Run every Feature-2 invariant on a real merged package.

    Returns a report dict; any violation appends to ``mismatches`` (the run
    fails if any case has mismatches).
    """
    report = {"case": label}
    mismatches = []
    manifest = load_manifest(bwt_dir, validate=True)
    total_bits = int(manifest["bwt_length"])

    # --- extraction exactness + per-source totals -------------------------
    observed = []
    for i, sid in enumerate(ids):
        extracted = extract_constituent_bwt(bwt_dir, sid)
        if not np.array_equal(extracted, originals[i]):
            mismatches.append(
                "extraction mismatch for %s (len %d)" % (sid, len(extracted)))
        observed.append(int(extracted.shape[0]))
    expected_totals = [sum(len(read) + 1 for read in reads)
                       for reads in reads_by_source]
    report["per_source_totals"] = list(zip(ids, observed))
    report["expected_totals"] = list(zip(ids, expected_totals))
    if observed != expected_totals:
        mismatches.append("totals %r != expected %r"
                          % (observed, expected_totals))
    if sum(observed) != total_bits:
        mismatches.append("sum(source totals) %d != bwt_length %d"
                          % (sum(observed), total_bits))

    # --- row labels + order-independent per-symbol joint counts ------------
    labels = row_source_labels(bwt_dir, manifest, total_bits)
    id_to_index = {sid: i for i, sid in enumerate(ids)}
    joint = [[0] * len(ids) for _ in range(6)]
    for position in range(total_bits):
        symbol = int(merged_bwt.getCharAtIndex(position))
        joint[symbol][id_to_index[labels[position]]] += 1
    joint_ok = True
    for i, standalone in enumerate(loaded):
        for symbol_index in range(6):
            expected_count = int(standalone.getSymbolCount(symbol_index))
            if joint[symbol_index][i] != expected_count:
                joint_ok = False
                mismatches.append(
                    "joint provenance symbol %d source %s: got %d expected %d"
                    % (symbol_index, ids[i], joint[symbol_index][i],
                       expected_count))
    report["joint_provenance_consistent"] = joint_ok

    recovered = lf_recover_reads(merged_bwt, total_bits)
    union = sorted([read for reads in reads_by_source for read in reads])
    report["lf_recovered_multiset_matches"] = recovered == union
    if recovered != union:
        mismatches.append("LF-recovered multiset != union")

    # --- rotation-sort block oracle (uniform-route inputs) -----------------
    uniform = bool(reads_by_source) and all(
        bool(reads) and all(len(read) == len(reads[0]) for read in reads)
        for reads in reads_by_source)
    report["rotation_oracle_applicable"] = uniform
    if uniform:
        oracle = rotation_block_oracle(reads_by_source, ids, labels,
                                       total_bits)
        report["exact_rows_checked"] = oracle["exact_rows_checked"]
        report["tied_rows_multiplicity_checked"] = (
            oracle["tied_rows_multiplicity_checked"])
        mismatches.extend(oracle["mismatches"])
    else:
        report["exact_rows_checked"] = 0
        report["tied_rows_multiplicity_checked"] = 0

    report["extraction_mismatches"] = sum(
        1 for m in mismatches if m.startswith("extraction mismatch"))
    report["mismatch_count"] = len(mismatches)
    report["mismatches"] = mismatches
    return report


# ---------------------------------------------------------------------------
# corruption / staleness probes
# ---------------------------------------------------------------------------


def run_corruption_probes(work):
    """Execute every persistence-safety probe; each must raise
    ProvenanceError.  Returns {probe: bool}."""

    def fake_merge(left_dir, right_dir, output_dir, num_procs=1, logger=None):
        left = np.load(os.path.join(left_dir, "msbwt.npy"))
        right = np.load(os.path.join(right_dir, "msbwt.npy"))
        bits = []
        li = ri = 0
        while li < len(left) or ri < len(right):
            if li < len(left) and (ri >= len(right) or li <= ri):
                bits.append(0)
                li += 1
            else:
                bits.append(1)
                ri += 1
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        merged = np.empty(len(bits), dtype=np.uint8)
        li = ri = 0
        for i, bit in enumerate(bits):
            if bit:
                merged[i] = right[ri]
                ri += 1
            else:
                merged[i] = left[li]
                li += 1
        np.save(os.path.join(output_dir, "msbwt.npy"), merged)
        np.save(os.path.join(output_dir, "inter0.npy"),
                f1.pack_little_endian_bits(bits))

    root = os.path.join(work, "corrupt-probes")
    os.mkdir(root)

    def make_package(name, a_values, b_values):
        left = os.path.join(root, name + "-a")
        right = os.path.join(root, name + "-b")
        os.mkdir(left)
        os.mkdir(right)
        np.save(os.path.join(left, "msbwt.npy"),
                np.asarray(a_values, dtype=np.uint8))
        np.save(os.path.join(right, "msbwt.npy"),
                np.asarray(b_values, dtype=np.uint8))
        initialize_leaf_provenance(left, source_id="A", source_name="A")
        initialize_leaf_provenance(right, source_id="B", source_name="B")
        merged = os.path.join(root, name)
        merge_two_with_provenance(
            left, right, merged, merge_two_func=fake_merge)
        return merged

    def raises(function):
        try:
            function()
            return False
        except ProvenanceError:
            return True

    probes = {}

    package = make_package("slrb", [1, 2, 3], [4, 5])
    bwt_path = os.path.join(package, "msbwt.npy")
    original = np.load(bwt_path)
    changed = original.copy()
    changed[0] = changed[0] ^ np.uint8(1)
    np.save(bwt_path, changed)
    probes["same_length_replaced_bwt_detected"] = raises(
        lambda: validate_manifest(package))

    other = make_package("copy", [9, 8, 7], [6, 5])
    shutil.copyfile(os.path.join(package, MANIFEST_FILENAME),
                    os.path.join(other, MANIFEST_FILENAME))
    probes["copied_manifest_detected"] = raises(
        lambda: validate_manifest(other))

    package2 = make_package("slic", [1, 2], [3, 4])
    manifest2 = load_manifest(package2)
    node = manifest2["root"]
    inter_path = os.path.join(package2, node["interleave"])
    bits = unpack_interleave(inter_path, node["length"])
    assert bits.tolist() != list(reversed(bits))
    np.save(inter_path, f1.pack_little_endian_bits(list(reversed(bits))))
    probes["same_length_same_count_replaced_interleave_detected"] = raises(
        lambda: validate_manifest(package2))

    package3 = make_package("trunc", [1, 2], [3])
    with open(os.path.join(package3, MANIFEST_FILENAME), "ab") as handle:
        handle.write(b'{"truncated":')
    probes["truncated_manifest_detected"] = raises(
        lambda: load_manifest(package3))

    package4 = make_package("ver", [1, 2], [3])
    bad = json.loads(json.dumps(load_manifest(package4)))
    bad["version"] = 99
    save_manifest(package4, bad)
    probes["wrong_version_detected"] = raises(
        lambda: validate_manifest(package4))

    package5 = make_package("dtype", [1, 2], [3])
    node5 = load_manifest(package5)["root"]
    inter5 = os.path.join(package5, node5["interleave"])
    np.save(inter5, np.load(inter5).astype(np.uint16))
    probes["wrong_dtype_interleave_detected"] = raises(
        lambda: validate_manifest(package5))

    package6 = make_package("miss", [1, 2], [3])
    node6 = load_manifest(package6)["root"]
    os.remove(os.path.join(package6, node6["interleave"]))
    probes["missing_interleave_detected"] = raises(
        lambda: validate_manifest(package6))

    package7 = make_package("len", [1, 2], [3])
    bad7 = json.loads(json.dumps(load_manifest(package7)))
    bad7["bwt_length"] = bad7["bwt_length"] + 1
    save_manifest(package7, bad7)
    probes["bwt_length_mismatch_detected"] = raises(
        lambda: validate_manifest(package7))

    return probes


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    work = tempfile.mkdtemp(prefix="f2-evidence-")
    report = {
        "seed": SEED,
        "randomized_datasets": RANDOMIZED_DATASETS,
        "explicit_ten_source_datasets": TEN_SOURCE_DATASETS,
        "datasets": [],
        "deterministic_cases": [],
        "edge_corpus": [],
        "corruption_probes": {},
        "atomic_write_probe": {},
        "feature1_compatibility": {},
        "performance": {},
        "mismatch_count": 0,
    }
    all_mismatches = []
    harness = f1.SourceHarness(work)
    try:
        # =================================================================
        # canonical two-source fixture merge (Feature-1 compatibility)
        # =================================================================
        a_dir = harness.build_fixture_source("canon-a", "uniform-a.fastq")
        b_dir = harness.build_fixture_source("canon-b", "uniform-b.fastq")
        m_dir = os.path.join(work, "canon-m")
        manifest = merge_two_with_provenance(
            a_dir, b_dir, m_dir,
            merge_two_func=holt_merge_two,
            left_source_id="A", left_source_name="A",
            right_source_id="B", right_source_name="B",
            num_procs=1)
        canon_merged = TwoSourceBWT.load(m_dir, source_names=("A", "B"))
        total_bits = int(canon_merged.bwt.getTotalSize())

        canon_report = verify_package(
            m_dir, ["A", "B"],
            [f1.CANONICAL_READS_A, f1.CANONICAL_READS_B],
            canon_merged.bwt, "canonical-two-source",
            [f1.load_standalone(a_dir), f1.load_standalone(b_dir)],
            [np_load(a_dir), np_load(b_dir)])
        canon_report["merge_tree"] = "balanced"
        canon_report["source_count"] = 2
        canon_report["depth"] = 1
        canon_report["reload_ok"] = bool(validate_manifest(m_dir))
        canon_report["queries_checked"] = 0
        canon_report["query_mismatches"] = 0
        report["deterministic_cases"].append(canon_report)

        # Feature-1 compatibility: row-level and query-level agreement
        labels = row_source_labels(m_dir, manifest, total_bits)
        bits = unpack_interleave(
            os.path.join(m_dir, manifest["root"]["interleave"]), total_bits)
        row_mismatches = 0
        for row in range(total_bits):
            feature1 = canon_merged.source_index.source_at(row)
            if int(bits[row]) != feature1:
                row_mismatches += 1
        queries = (list(f1.COMMITTED_QUERIES.keys())
                   + [str(q) for q in f1.CANONICAL_EXTRA_QUERIES])
        query_mismatches = 0
        for query in queries:
            result = canon_merged.countOccurrencesBySource(query)
            low, high = result["interval"]
            interval_bits = bits[low:high]
            tree_a = int(interval_bits.size - interval_bits.sum())
            tree_b = int(interval_bits.sum())
            if (tree_a != result["A"] or tree_b != result["B"]
                    or tree_a + tree_b != result["total"]):
                query_mismatches += 1
        report["feature1_compatibility"] = {
            "two_source_merged": True,
            "rows_compared": total_bits,
            "row_mismatches": row_mismatches,
            "queries_compared": len(queries),
            "query_mismatches": query_mismatches,
            "source_ids": source_ids(m_dir),
        }
        all_mismatches.extend(
            ["f1-rows"] * row_mismatches + ["f1-queries"] * query_mismatches)

        # =================================================================
        # multi-stage merge provenance cases
        # =================================================================
        # uniform synthetic sets (all reads same length per source) so the
        # independent rotation-sort block oracle applies to the multi-source
        # deterministic cases; the mixed-lengths edge class and the random
        # datasets keep nonuniform coverage
        syn_c = ["ACGTACGT", "GGGAGGGG", "NNNANNNN"]
        syn_d = ["TTTTTTTT", "ACGTACGT", "NNNNNNNN"]
        syn_e = ["GATTACAA", "ACGTACGT", "NNTGNNTG"]
        syn_f = ["AAAA", "CCCC", "GGGG", "TTTT"]
        syn_g = ["AGCTAGCT", "AGTAGTAG", "CCCCCCCC"]
        syn_h = ["TAGGTAGG", "GATGATGA", "ATCATCAT", "CTACTACT"]
        syn_i = ["ACNACN", "TGNTGN", "NGTNGT"]
        syn_j = ["AAAAAA", "CCCCCC", "GGGGGG", "TTTTTT", "NNNNNN",
                 "AACCGG"]

        def add_case(label, groups, tree, source_count=None):
            out, ids, merged_bwt, loaded, originals = build_and_merge(
                harness, work, label, groups, tree)
            case_report = verify_package(
                out, ids, groups, merged_bwt, label, loaded, originals)
            case_report["merge_tree"] = tree
            case_report["source_count"] = source_count or len(ids)
            case_report["depth"] = _tree_depth(load_manifest(out)["root"])
            case_report["reload_ok"] = bool(validate_manifest(out))
            case_report["final_bwt_length"] = int(
                load_manifest(out)["bwt_length"])
            report["deterministic_cases"].append(case_report)
            if case_report["mismatch_count"]:
                all_mismatches.extend(case_report["mismatches"])
            return case_report

        add_case("three-source-chain",
                 [f1.CANONICAL_READS_A, f1.CANONICAL_READS_B, syn_c],
                 "chain")
        add_case("four-source-balanced",
                 [f1.CANONICAL_READS_A, f1.CANONICAL_READS_B, syn_c, syn_d],
                 "balanced")
        add_case("four-source-unbalanced",
                 [syn_e, syn_f, syn_g, syn_h], "chain")
        add_case("five-source-balanced",
                 [f1.CANONICAL_READS_A, syn_c, syn_e, syn_g, syn_i],
                 "balanced")
        ten_report = add_case(
            "ten-source-balanced",
            [f1.CANONICAL_READS_A, f1.CANONICAL_READS_B, syn_c, syn_d,
             syn_e, syn_f, syn_g, syn_h, syn_i, syn_j],
            "balanced")
        report["ten_source_fixture"] = {
            "source_count": 10,
            "depth": ten_report["depth"],
            "extraction_mismatches": ten_report["extraction_mismatches"],
            "reload_ok": ten_report["reload_ok"],
            "final_bwt_length": ten_report["final_bwt_length"],
            "per_source_totals": ten_report["per_source_totals"],
            "exact_rows_checked": ten_report["exact_rows_checked"],
            "tied_rows_multiplicity_checked": (
                ten_report["tied_rows_multiplicity_checked"]),
        }

        # =================================================================
        # deterministic 3-source edge corpus (12 classes)
        # =================================================================
        for pair_index, (label, reads_a, reads_b) in enumerate(f1.EDGE_CORPUS):
            reads_c = ["T" * (len(reads_a[0]) + 1)] if reads_a else ["TT"]
            if len(reads_c[0]) > 12:
                reads_c = ["T" * 12]
            groups = [reads_a, reads_b, reads_c]
            out, ids, merged_bwt, loaded, originals = build_and_merge(
                harness, work, "edge-%02d-%s" % (pair_index, label),
                groups, "balanced")
            case_report = verify_package(
                out, ids, groups, merged_bwt, "edge-%s" % label,
                loaded, originals)
            case_report["merge_tree"] = "balanced"
            case_report["source_count"] = 3
            case_report["depth"] = _tree_depth(load_manifest(out)["root"])
            case_report["reload_ok"] = bool(validate_manifest(out))
            report["edge_corpus"].append(case_report)
            if case_report["mismatch_count"]:
                all_mismatches.extend(case_report["mismatches"])

        # =================================================================
        # randomized multi-source suite (seed 20260811)
        # =================================================================
        rng = random.Random(SEED)
        for case_index in range(RANDOMIZED_DATASETS):
            source_count = rng.randint(3, 8)
            groups = [f1.make_random_case(rng)[0]
                      for _ in range(source_count)]
            label = "random-%02d" % case_index
            tree = "chain" if case_index % 4 == 0 else "balanced"
            out, ids, merged_bwt, loaded, originals = build_and_merge(
                harness, work, label, groups, tree)
            case_report = verify_package(
                out, ids, groups, merged_bwt, label, loaded, originals)
            case_report["seed"] = SEED
            case_report["merge_tree"] = tree
            case_report["source_count"] = source_count
            case_report["reads_per_source"] = [list(g) for g in groups]
            case_report["final_bwt_length"] = int(
                load_manifest(out)["bwt_length"])
            case_report["reload_ok"] = bool(validate_manifest(out))
            report["datasets"].append(case_report)
            if case_report["mismatch_count"]:
                all_mismatches.extend(case_report["mismatches"])

        # explicit 10-source random datasets
        rng10 = random.Random(SEED + 1000)
        for case_index in range(TEN_SOURCE_DATASETS):
            groups = [f1.make_random_case(rng10)[0] for _ in range(10)]
            label = "random-ten-%02d" % case_index
            out, ids, merged_bwt, loaded, originals = build_and_merge(
                harness, work, label, groups, "balanced")
            case_report = verify_package(
                out, ids, groups, merged_bwt, label, loaded, originals)
            case_report["seed"] = SEED + 1000
            case_report["merge_tree"] = "balanced"
            case_report["source_count"] = 10
            case_report["reads_per_source"] = [list(g) for g in groups]
            case_report["final_bwt_length"] = int(
                load_manifest(out)["bwt_length"])
            case_report["reload_ok"] = bool(validate_manifest(out))
            report["datasets"].append(case_report)
            if case_report["mismatch_count"]:
                all_mismatches.extend(case_report["mismatches"])

        # =================================================================
        # corruption / staleness probes (fake merges, executed)
        # =================================================================
        probes = run_corruption_probes(work)
        report["corruption_probes"] = probes
        if not all(probes.values()):
            all_mismatches.append("a corruption probe was not detected")

        # =================================================================
        # atomic-write probe
        # =================================================================
        probe_dir = os.path.join(work, "atomic-probe")
        os.mkdir(probe_dir)
        np.save(os.path.join(probe_dir, "msbwt.npy"),
                np.asarray([1, 2, 3], dtype=np.uint8))
        initialize_leaf_provenance(probe_dir, source_id="at", source_name="at")
        manifest_obj = load_manifest(probe_dir)
        save_manifest(probe_dir, manifest_obj)
        save_manifest(probe_dir, manifest_obj)
        with open(os.path.join(probe_dir, MANIFEST_FILENAME), "rb") as handle:
            first = handle.read()
        save_manifest(probe_dir, manifest_obj)
        with open(os.path.join(probe_dir, MANIFEST_FILENAME), "rb") as handle:
            second = handle.read()
        leftovers = [name for name in os.listdir(probe_dir)
                     if name.endswith(".tmp")]
        report["atomic_write_probe"] = {
            "deterministic_bytes": first == second,
            "no_tmp_leftovers": not leftovers,
        }

        # =================================================================
        # performance / storage sanity
        # =================================================================
        perf = {}
        json_bytes = os.path.getsize(os.path.join(m_dir, MANIFEST_FILENAME))
        interleaves_bytes = _dir_size(
            os.path.join(m_dir, "provenance", "interleaves"))
        perf["canonical_provenance_json_bytes"] = json_bytes
        perf["canonical_interleaves_bytes"] = interleaves_bytes
        perf["canonical_bytes_per_row"] = round(
            float(json_bytes + interleaves_bytes) / total_bits, 2)
        perf["canonical_merged_package_bytes"] = _dir_size(m_dir)
        start = time.time()
        load_manifest(m_dir)
        perf["canonical_load_manifest_s"] = round(time.time() - start, 4)
        start = time.time()
        validate_manifest(m_dir)
        perf["canonical_validate_s"] = round(time.time() - start, 4)
        start = time.time()
        extract_constituent_bwt(m_dir, "A")
        perf["canonical_extract_one_constituent_s"] = round(
            time.time() - start, 4)
        ten_package = os.path.join(work, "ten-source-balanced")
        perf["ten_source_package_bytes"] = _dir_size(ten_package)
        perf["ten_source_provenance_json_bytes"] = os.path.getsize(
            os.path.join(ten_package, MANIFEST_FILENAME))
        perf["ten_source_interleaves_bytes"] = _dir_size(
            os.path.join(ten_package, "provenance", "interleaves"))
        perf["ten_source_bwt_length"] = int(
            load_manifest(ten_package)["bwt_length"])
        perf["ten_source_bytes_per_row"] = round(
            float(perf["ten_source_package_bytes"])
            / perf["ten_source_bwt_length"], 2)
        report["performance"] = perf
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # ---- totals ----
    report["mismatch_count"] = len(all_mismatches)
    report["dataset_mismatches"] = sum(
        dataset["mismatch_count"] for dataset in report["datasets"])
    report["case_mismatches"] = sum(
        case["mismatch_count"] for case in report["deterministic_cases"])
    report["edge_mismatches"] = sum(
        case["mismatch_count"] for case in report["edge_corpus"])
    report["source_counts_tested"] = sorted(set(
        [case["source_count"] for case in report["datasets"]]
        + [case["source_count"] for case in report["deterministic_cases"]]
        + [case["source_count"] for case in report["edge_corpus"]]))
    report["total_merges_real"] = (
        sum(case["source_count"] - 1 for case in report["datasets"])
        + sum(case["source_count"] - 1
              for case in report["deterministic_cases"])
        + sum(case["source_count"] - 1 for case in report["edge_corpus"]))

    if all_mismatches:
        with open("/tmp/feature2-mismatches.json", "w") as handle:
            json.dump(all_mismatches[:50], handle, indent=2, sort_keys=True)
        raise SystemExit(
            "FEATURE-2 MISMATCHES: %d (first 50 dumped to "
            "/tmp/feature2-mismatches.json)" % len(all_mismatches))

    payload = json.dumps(report, indent=2, sort_keys=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as handle:
            handle.write(payload + "\n")
    else:
        print(payload)
    print("FEATURE-2 EVIDENCE OK: %d randomized datasets (%d explicit "
          "10-source), %d deterministic cases, %d edge classes, 0 mismatches"
          % (len(report["datasets"]), TEN_SOURCE_DATASETS,
             len(report["deterministic_cases"]), len(report["edge_corpus"])))


if __name__ == "__main__":
    main()
