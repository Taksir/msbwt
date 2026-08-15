#!/usr/bin/env python2
"""msbwt-modern2 Q1 evidence generator: exact lossless FASTQ quality
sidecar (strict Point-12 specialization).

Runs inside the pinned Python-2.7 environment.  Exercises:

- suffix-start alignment oracle: expected quality arrays computed DIRECTLY
  from the naive suffix rows and the original reads; every row of the
  10-source fixture compared (191 rows, 0 mismatches);
- leaf initialization from records with independent sequence
  verification; sequence-mismatch and reserved-byte rejection;
- disk-backed FASTQ retrofit (plain + .gz, about.npy origin remapping
  where FASTQ order does not match dollar order, multiple origin files);
- two-way and balanced 10-source merges preserve every quality row;
  one-sided quality merge rejected BEFORE the BWT merge;
- merged retrofit from leaf arrays;
- Feature-10 removal: quality_reduced == quality_original[keep_mask]
  element-for-element; surviving reads recover exact original quality
  lines;
- query APIs: qualityValues (merged + source), readQuality /
  readSequenceAndQuality / readFastqData, readsContaining with
  include_quality=True, hasQuality, qualityForRow sentinel;
- deterministic randomized Level-3 differential (seed 20260811): 18
  random tagged merges and removals.

Any mismatch raises AssertionError; the driver records JSON only after
every gate passes.  Python 2.7 only.
"""

from __future__ import print_function

import json
import os
import random
import shutil
import sys
import tempfile

import numpy as np

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

PACKAGE = os.path.join(REPO, "packages", "msbwt-modern2")
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_read_provenance_py2 as f9  # noqa: E402
import test_quality_sidecar_py2 as q1  # noqa: E402

from MUS.QualitySidecar import (  # noqa: E402
    QualitySidecar,
    QualitySidecarError,
    initialize_leaf_quality_from_fastqs,
    initialize_leaf_quality_from_records,
    quality_sidecar_exists,
    retrofit_merged_quality_from_leaf_arrays,
)
from MUS.MultiSourceProvenance import (  # noqa: E402
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.ReadProvenance import ReadProvenanceIndex  # noqa: E402
from MUS.SourceRemoval import remove_sources  # noqa: E402

SEED = 20260811


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "naive_suffix_rows_plus_original_reads",
            "original_fastq_lines",
            "independent_suffix_sort_replay",
        ],
        "alignment": {},
        "leaf_records": {},
        "fastq_retrofit": {},
        "merge_lifecycle": {},
        "retrofit": {},
        "removal": {},
        "queries": {},
        "randomized": {},
        "notes": [
            "Q1 is a strict Point-12 specialization: reserved uint8 tag "
            "fastq_quality_ascii, suffix-first-base alignment, terminal-$ "
            "sentinel 255, no Phred conversion, no quantization.",
            "quality_sidecar.json records the semantic contract; the "
            "quality tag is ordinary Point-12 storage (never double "
            "counted by Feature 13A).",
        ],
    }

    work = tempfile.mkdtemp(prefix="q1-evidence-")
    try:
        # ---------------- 10-source quality fixture -----------------------
        leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(work, sid, reads)
            f9.attach_leaf_read_provenance(leaf, reads)
            qualities = [
                q1.quality_for_read(reads[i], i, 0)
                for i in range(len(reads))
            ]
            initialize_leaf_quality_from_records(
                leaf, q1.NaiveQualityBWT(leaf), qualities,
                sequences_by_dollar_id=reads)
            leaves[sid] = leaf
        output = os.path.join(work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)

        alignment = report["alignment"]
        sidecar = QualitySidecar(output)
        expected = q1.expected_merged_quality(
            output, leaves, f9.TEN_SOURCE_READS)
        mismatches = []
        comparisons = 0
        for x in range(expected.shape[0]):
            comparisons += 1
            if int(sidecar.values[x]) != int(expected[x]):
                mismatches.append((x, int(sidecar.values[x]),
                                   int(expected[x])))
        alignment["rows"] = expected.shape[0]
        alignment["comparisons"] = comparisons
        alignment["mismatches"] = len(mismatches)
        assert expected.shape[0] == 191
        assert mismatches == []

        # every read's recovered quality equals its deterministic line
        leaf_checks = 0
        for sid, leaf in leaves.items():
            lsidecar = QualitySidecar(leaf)
            reads = f9.TEN_SOURCE_READS[sid]
            for d in range(len(reads)):
                leaf_checks += 1
                if lsidecar.recover_quality(
                        q1.NaiveQualityBWT(leaf), d) != \
                        q1.quality_for_read(reads[d], d, 0):
                    mismatches.append(("leaf_recovery", sid, d, "x"))
        report["leaf_records"] = {
            "reads": leaf_checks,
            "mismatches": 0,
        }
        assert mismatches == []

        # ---------------- FASTQ retrofit (unsorted about) -----------------
        fastq = report["fastq_retrofit"]
        reads = ["ACGT", "AAAA", "TTTT"]
        fastq_path = os.path.join(work, "src.fastq")
        q1.write_fastq(fastq_path, [
            ("read0", "TTTT", "IIII"),
            ("read1", "ACGT", "####"),
            ("read2", "AAAA", "!!!!"),
        ])
        leaf = f9.make_read_derived_leaf(work, "fastqleaf", reads)
        about = np.empty(
            3, dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        about[0] = (0, 1)
        about[1] = (0, 2)
        about[2] = (0, 0)
        np.save(os.path.join(leaf, "about.npy"), about)
        bwt = q1.NaiveQualityBWT(leaf)
        initialize_leaf_quality_from_fastqs(leaf, bwt, [fastq_path])
        lsidecar = QualitySidecar(leaf)
        assert lsidecar.recover_quality(bwt, 0) == b"####"
        assert lsidecar.recover_quality(bwt, 1) == b"!!!!"
        assert lsidecar.recover_quality(bwt, 2) == b"IIII"
        fastq["unsorted_origin"] = True
        # gz + multiple files
        gz1 = os.path.join(work, "lane1.fastq.gz")
        gz2 = os.path.join(work, "lane2.fastq")
        q1.write_fastq(gz1, [("r0", "ACGT", "####")])
        q1.write_fastq(gz2, [("r1", "AAAA", "!!!!")])
        leaf2 = f9.make_read_derived_leaf(work, "gzleaf", ["ACGT", "AAAA"])
        about2 = np.empty(
            2, dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        about2[0] = (0, 0)
        about2[1] = (1, 0)
        np.save(os.path.join(leaf2, "about.npy"), about2)
        initialize_leaf_quality_from_fastqs(
            leaf2, q1.NaiveQualityBWT(leaf2), [gz1, gz2])
        l2 = QualitySidecar(leaf2)
        assert l2.recover_quality(q1.NaiveQualityBWT(leaf2), 0) == b"####"
        assert l2.recover_quality(q1.NaiveQualityBWT(leaf2), 1) == b"!!!!"
        fastq["gz_and_multiple_files"] = True
        # sequence mismatch rejected by default, opt-out available
        bad = os.path.join(work, "bad.fastq")
        q1.write_fastq(bad, [("r0", "ACGT", "####"), ("r1", "CCCC", "!!!!")])
        leaf3 = f9.make_read_derived_leaf(work, "badleaf", ["ACGT", "AAAA"])
        about3 = np.empty(
            2, dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        about3[0] = (0, 0)
        about3[1] = (0, 1)
        np.save(os.path.join(leaf3, "about.npy"), about3)
        try:
            initialize_leaf_quality_from_fastqs(
                leaf3, q1.NaiveQualityBWT(leaf3), [bad])
            raise AssertionError("sequence mismatch not rejected")
        except QualitySidecarError:
            pass
        initialize_leaf_quality_from_fastqs(
            leaf3, q1.NaiveQualityBWT(leaf3), [bad],
            verify_sequences=False)
        fastq["mismatch_rejected"] = True

        # ---------------- merge lifecycle --------------------------------
        merged = report["merge_lifecycle"]
        assert quality_sidecar_exists(output)
        meta = sidecar.metadata
        assert meta["builder"] == "automatic-merge"
        assert "child_builders" in meta
        merged["one_sided_rejected"] = False
        la = f9.make_read_derived_leaf(work, "OA", ["ACGTAC", "AAAA"])
        lb = f9.make_read_derived_leaf(work, "OB", ["TTTT", "CCCC"])
        initialize_leaf_quality_from_records(
            la, q1.NaiveQualityBWT(la), [b"######", b"####"],
            sequences_by_dollar_id=["ACGTAC", "AAAA"])
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        try:
            merge_two_with_provenance(
                la, lb, os.path.join(work, "bad"),
                merge_two_func=should_not_run)
            raise AssertionError("one-sided quality merge not rejected")
        except QualitySidecarError:
            pass
        assert not called[0]
        assert not os.path.exists(os.path.join(work, "bad", "msbwt.npy"))
        merged["one_sided_rejected"] = True
        merged["rows"] = 191
        merged["mismatches"] = 0

        # ---------------- merged retrofit --------------------------------
        retrofit = report["retrofit"]
        retrofit_out = os.path.join(work, "retrofit_copy")
        shutil.copytree(output, retrofit_out)
        from MUS.BWTTags import remove_tag
        remove_tag(retrofit_out, "fastq_quality_ascii")
        os.remove(os.path.join(retrofit_out, "quality_sidecar.json"))
        arrays_by_source = {
            sid: QualitySidecar(leaf).values
            for sid, leaf in leaves.items()
        }
        retrofit_merged_quality_from_leaf_arrays(
            retrofit_out, arrays_by_source)
        rsidecar = QualitySidecar(retrofit_out)
        assert np.array_equal(rsidecar.values, expected)
        retrofit["mismatches"] = 0
        retrofit["rows"] = 191

        # ---------------- Feature-10 removal -----------------------------
        removal = report["removal"]
        keep_set = set(s for s in f9.TEN_SOURCE_READS
                       if s not in ("sample00", "sample02", "sample09"))
        manifest = load_manifest(output)
        mask = np.asarray(
            [q1.f9_row_source(output, manifest, x) in keep_set
             for x in range(sidecar.bwt_rows)],
            dtype=np.bool_)
        reduced = os.path.join(work, "reduced")
        stats = remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"])
        assert stats["quality_sidecar_preserved"]
        red_sidecar = QualitySidecar(reduced)
        removal["mismatches"] = 0
        for x in range(red_sidecar.bwt_rows):
            if int(red_sidecar.values[x]) != int(sidecar.values[mask][x]):
                mismatches.append(("removal_row", x, "x", "y"))
        # surviving reads recover exact original quality lines
        q1.save_expected_rows(reduced, leaves, keep_set)
        reduced_oracle = f9.OracleReadIdentity(
            reduced,
            {sid: leaves[sid] for sid in keep_set},
            {sid: f9.TEN_SOURCE_READS[sid] for sid in keep_set})
        rbwt = q1.NaiveQualityBWT(reduced, oracle=reduced_oracle)
        recovered_reads = 0
        for sid in keep_set:
            reads = f9.TEN_SOURCE_READS[sid]
            for local_id in range(len(reads)):
                dollar_id = reduced_oracle.global_dollar[(sid, local_id)]
                quality = red_sidecar.recover_quality(rbwt, dollar_id)
                recovered_reads += 1
                if quality != q1.quality_for_read(reads[local_id],
                                                  local_id, 0):
                    mismatches.append(("removal_quality", sid, local_id,
                                       "x"))
        removal["read_quality_recovered"] = recovered_reads == 21
        assert recovered_reads == 21
        removal["rows"] = red_sidecar.bwt_rows
        assert mismatches == []

        # ---------------- query lifecycle --------------------------------
        queries = report["queries"]
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        wrapped = MultiSourceBWT(
            None, index, quality_sidecar=sidecar,
            bwt_tags=sidecar.store,
            read_provenance=ReadProvenanceIndex(
                output, mmap=False, source_index=index))
        oracle = f9.OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in leaves},
            f9.TEN_SOURCE_READS)
        wrapped.bwt = q1.NaiveQualityBWT(output, oracle=oracle)
        qcomparisons = 0
        qmismatches = []
        assert wrapped.hasQuality()
        assert wrapped.qualityForRow(0) is None
        for pattern in ("A", "AC", "CGT", "AAAA", "N", "AAGGTT"):
            low, high = q1.naive_interval_q(output, pattern)
            result = wrapped.qualityValues(pattern)
            qcomparisons += 1
            if result["value_count"] != high - low:
                qmismatches.append(("interval_count", pattern))
            qcomparisons += 1
            if not np.array_equal(
                    result["values"], sidecar.values[low:high]):
                qmismatches.append(("interval_values", pattern))
            for sid in f9.TEN_SOURCE_READS:
                sresult = wrapped.qualityValues(pattern, source=sid)
                expected_rows = [
                    x for x in range(low, high)
                    if q1.f9_row_source(output, manifest, x) == sid
                ]
                qcomparisons += 1
                if sresult["value_count"] != len(expected_rows):
                    qmismatches.append(("source_count", pattern, sid))
        for sid in ("sample00", "sample03", "sample09"):
            reads = f9.TEN_SOURCE_READS[sid]
            for local_id in range(len(reads)):
                dollar_id = oracle.global_dollar[(sid, local_id)]
                quality = wrapped.readQuality(dollar_id)
                qcomparisons += 1
                if quality != q1.quality_for_read(reads[local_id],
                                                  local_id, 0):
                    qmismatches.append(("read_quality", sid, local_id,
                                        "x"))
                sequence, q2 = wrapped.readSequenceAndQuality(dollar_id)
                qcomparisons += 1
                if sequence != reads[local_id].encode("ascii") or q2 != \
                        quality:
                    qmismatches.append(("seq_qual", sid, local_id, "x"))
        rc = wrapped.readsContaining("AAGGTT", include_quality=True)
        qcomparisons += 1
        if rc["reads"][0]["quality"] != q1.quality_for_read("AAGGTT", 2, 0):
            qmismatches.append(("reads_containing_quality", "x", "y", "z"))
        # group/where quality selection equals independently projected rows
        from MUS.SourceMetadata import SourceMetadataCatalog
        metadata = SourceMetadataCatalog(index.list_sources())
        metadata.define_group(
            "case", ["sample00", "sample01", "sample02"])
        for sid in ("sample00", "sample01", "sample02"):
            metadata.set_source_metadata(sid, cohort="case")
        wrapped2 = MultiSourceBWT(
            None, index, source_metadata=metadata,
            quality_sidecar=sidecar, bwt_tags=sidecar.store,
            read_provenance=wrapped.read_provenance)
        wrapped2.bwt = wrapped.bwt
        for pattern in ("A", "AC", "CGT"):
            low, high = q1.naive_interval_q(output, pattern)
            for kind, selector in (
                ("subset", {"sources": ["sample00", "sample02"]}),
                ("group", {"group": "case"}),
                ("where", {"where": {"cohort": "case"}}),
            ):
                sresult = wrapped2.qualityValues(
                    pattern, **selector)
                if kind == "subset":
                    selected = set(selector["sources"])
                else:
                    selected = set(["sample00", "sample01", "sample02"])
                expected_rows = [
                    x for x in range(low, high)
                    if q1.f9_row_source(output, manifest, x) in selected
                ]
                qcomparisons += 1
                if sresult["value_count"] != len(expected_rows):
                    qmismatches.append(("selection_count",
                                        pattern, kind))
                qcomparisons += 1
                if not np.array_equal(
                        sresult["values"],
                        sidecar.values[expected_rows]):
                    qmismatches.append(("selection_values",
                                        pattern, kind))
        queries["comparisons"] = qcomparisons
        queries["mismatches"] = len(qmismatches)
        assert qmismatches == []
        assert qcomparisons > 100

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        cases = 0
        for case in range(18):
            rleaves = {}
            reads_by_source = {}
            n_sources = rng.randint(2, 5)
            for i in range(n_sources):
                sid = "R%02d_S%d" % (case, i)
                n_reads = rng.randint(1, 4)
                reads = []
                alphabet = "ACGTN"
                for _ in range(n_reads):
                    length = rng.randint(1, 8)
                    if rng.random() < 0.3 and reads:
                        reads.append(reads[rng.randrange(len(reads))])
                        continue
                    reads.append("".join(
                        rng.choice(alphabet) for _ in range(length)))
                reads_by_source[sid] = reads
                leaf = f9.make_read_derived_leaf(work, sid, reads)
                initialize_leaf_quality_from_records(
                    leaf, q1.NaiveQualityBWT(leaf),
                    [q1.quality_for_read(reads[j], j, 0)
                     for j in range(len(reads))],
                    sequences_by_dollar_id=reads)
                rleaves[sid] = leaf
            rout = os.path.join(work, "rand_%02d" % case)
            merge_many_balanced(
                list(rleaves.values()), rout,
                merge_two_func=f9.read_derived_merge)
            rsidecar = QualitySidecar(rout)
            rexpected = q1.expected_merged_quality(
                rout, rleaves, reads_by_source)
            cases += 1
            if not np.array_equal(rsidecar.values, rexpected):
                random_mismatches.append(("merge", case))
            remove_ids = [
                sid for sid in rleaves if rng.random() < 0.4
            ]
            if not remove_ids or len(remove_ids) == len(rleaves):
                remove_ids = [list(rleaves)[0]]
            rred = os.path.join(work, "randred_%02d" % case)
            rstats = remove_sources(rout, rred, sources=remove_ids)
            if not rstats["quality_sidecar_preserved"]:
                random_mismatches.append(("remove_stats", case))
            rrsidecar = QualitySidecar(rred)
            keep = set(reads_by_source) - set(remove_ids)
            rmanifest = load_manifest(rout)
            rmask = np.asarray(
                [q1.f9_row_source(rout, rmanifest, x) in keep
                 for x in range(rsidecar.bwt_rows)],
                dtype=np.bool_)
            if not np.array_equal(
                    rrsidecar.values, rsidecar.values[rmask]):
                random_mismatches.append(("remove", case))
        report["randomized"] = {
            "seed": SEED,
            "cases": cases,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert cases == 18

        report["mismatch_count"] = (
            len(mismatches) + len(qmismatches) + len(random_mismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: q1_quality_sidecar_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
