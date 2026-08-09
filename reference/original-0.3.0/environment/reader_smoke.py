#!/usr/bin/env python
"""Validate a frozen build on a disposable copy using fixture-derived facts."""
from __future__ import print_function

import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import sys
import traceback

import probe_legacy


def write_json(path, value):
    with open(path, "wb") as handle:
        encoded = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
        if not isinstance(encoded, bytes):
            encoded = encoded.encode("utf-8")
        handle.write(encoded)
        handle.write(b"\n")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def inventory_files(root):
    result = {}
    for current_root, directories, filenames in os.walk(root):
        directories.sort()
        filenames.sort()
        for directory in directories:
            if os.path.islink(os.path.join(current_root, directory)):
                raise RuntimeError("reader copy contains a symlink directory")
        for filename in filenames:
            path = os.path.join(current_root, filename)
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeError("reader copy contains a non-regular file")
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            result[relative] = {
                "sha256": sha256_file(path),
                "size": os.path.getsize(path)
            }
    return result


def read_fastq_sequences(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as handle:
        lines = handle.read().splitlines()
    if not lines or len(lines) % 4:
        raise ValueError("fixture is not a complete four-line FASTQ")
    sequences = []
    for index in range(0, len(lines), 4):
        header, sequence, separator, quality = lines[index:index + 4]
        if not header.startswith(b"@") or not separator.startswith(b"+"):
            raise ValueError("fixture has an invalid FASTQ record")
        if len(sequence) != len(quality):
            raise ValueError("fixture sequence and quality lengths differ")
        sequences.append(sequence)
    return sequences


def all_fixture_substrings(sequences):
    queries = set()
    for sequence in sequences:
        for start in range(len(sequence)):
            for end in range(start + 1, len(sequence) + 1):
                queries.add(sequence[start:end])
    longest = max(len(sequence) for sequence in sequences)
    queries.add(b"A" * (longest + 1))
    return sorted(queries)


def overlapping_count(sequences, query):
    return sum(
        1
        for sequence in sequences
        for offset in range(0, len(sequence) - len(query) + 1)
        if sequence[offset:offset + len(query)] == query
    )


def expected_recovered_strings(sequences):
    """Return the legacy recoverString representation for fixture reads."""
    # recoverString returns the sentinel first; the legacy CLI deliberately
    # strips byte zero before displaying recovered sequences.
    return sorted(b"$" + sequence for sequence in sequences)


def compare_inventories(before, after):
    before_paths = set(before)
    after_paths = set(after)
    return {
        "added": [dict({"path": path}, **after[path]) for path in sorted(after_paths - before_paths)],
        "changed": [
            {"path": path, "before": before[path], "after": after[path]}
            for path in sorted(before_paths.intersection(after_paths))
            if before[path] != after[path]
        ],
        "removed": sorted(before_paths - after_paths)
    }


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="built frozen source used for imports")
    parser.add_argument("--dataset", required=True, help="successful build snapshot to copy")
    parser.add_argument("--copy", required=True, help="new disposable dataset-copy path")
    parser.add_argument("--fixture-root", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--case-manifest", default=probe_legacy.DEFAULT_ORACLE_CASES)
    parser.add_argument("--output", required=True, help="JSON result path outside the copied dataset")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if sys.version_info[:2] != (2, 7) or platform.python_implementation() != "CPython":
        raise SystemExit("reader smoke requires genuine CPython 2.7")
    if os.path.lexists(args.copy):
        raise SystemExit("reader smoke refuses an existing copy path")
    fixture_info = probe_legacy.validate_golden_case(
        args.fixture_root, args.case, args.case_manifest
    )
    fixture_paths = [
        os.path.join(fixture_info["fixture_root"], item["path"])
        for item in fixture_info["files"]
    ]
    sequences = []
    for fixture_path in fixture_paths:
        sequences.extend(read_fastq_sequences(fixture_path))

    shutil.copytree(args.dataset, args.copy)
    before = inventory_files(args.copy)
    expected_recovered = expected_recovered_strings(sequences)
    queries = all_fixture_substrings(sequences)
    expected_queries = {
        query.decode("ascii"): overlapping_count(sequences, query)
        for query in queries
    }
    result = {
        "case_id": args.case,
        "expected_queries": expected_queries,
        "expected_recovered_strings": [value.decode("ascii") for value in expected_recovered],
        "fixture_files": [
            {"path": item["path"], "sha256": item["sha256"], "byte_count": item["byte_count"]}
            for item in fixture_info["files"]
        ],
        "format": "msbwt-legacy-reader-smoke-v1",
        "status": "not-run"
    }
    try:
        source = os.path.abspath(args.source)
        sys.path.insert(0, source)
        os.chdir(source)
        from MUSCython import MultiStringBWTCython

        reader = MultiStringBWTCython.loadBWT(os.path.abspath(args.copy), useMemmap=False)
        actual_queries = {
            query.decode("ascii"): int(reader.countOccurrencesOfSeq(query))
            for query in queries
        }
        dollar_count = int(reader.getSymbolCount(0))
        recovered = sorted(reader.recoverString(index) for index in range(dollar_count))
        result.update({
            "actual_queries": actual_queries,
            "actual_recovered_strings": [value.decode("ascii") for value in recovered],
            "dollar_count": dollar_count,
            "reader_class": reader.__class__.__name__,
            "total_size": int(reader.getTotalSize())
        })
        if actual_queries != expected_queries:
            raise AssertionError("frozen reader query results differ from fixture-derived counts")
        if recovered != expected_recovered:
            raise AssertionError("frozen reader recovery differs from fixture sequences")
        if result["total_size"] != sum(len(sequence) + 1 for sequence in sequences):
            raise AssertionError("frozen reader total size differs from fixture-derived length")
        result["status"] = "passed"
    except Exception as exc:
        result["error"] = "{0}: {1}".format(exc.__class__.__name__, exc)
        result["traceback"] = traceback.format_exc()
        result["status"] = "failed"
    finally:
        after = inventory_files(args.copy)
        result["side_effects"] = compare_inventories(before, after)
        write_json(args.output, result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
