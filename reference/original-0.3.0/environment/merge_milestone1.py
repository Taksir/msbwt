#!/usr/bin/env python
"""Execute the canonical legacy merge/reader-indexing characterization.

This module is called only after ``probe_legacy`` has built and gated a frozen
source copy.  It runs under genuine CPython 2.7 and records raw Linux-ext4
evidence; host-side tooling performs safe NPY parsing, independent semantic
validation, and promotion after every relationship below passes.

Canonical case (``merge-uniform-a-uniform-b``):

  IN_A    ``pp -u`` + ``cfpp -p 1 -u`` from ``uniform-a.fastq``   (4 reads)
  IN_B    ``pp -u`` + ``cfpp -p 1 -u`` from ``uniform-b.fastq``   (4 reads)
  CLEAN   ``pp -u`` + ``cfpp -p 1 -u`` from both files            (8 reads)
  MERGE   ``merge -p 2 MERGED IN_A IN_B``

The frozen ``merge`` CLI requires ``-p N`` with ``N > 1`` because the default
``-p 1`` path raises ``NameError: name 'numProcs' is not defined``; the
canonical invocation ``merge -p 2`` clamps to a single process and is
deterministic.  The ``-p 1`` NameError is recorded as a legacy defect.

Expected merged output: ``inter0.npy`` (bit-packed interleave, ``|u1`` shape
``(7,)``) and ``msbwt.npy`` (``|u1``, 48 symbols) and nothing else.  The merge
mutates its inputs by lazily creating ``totalCounts.npy`` and ``fmIndex.npy``;
it never writes derived indexes into the output.  The merged primary is
expected to be byte-identical to the fresh clean build and to the committed
``uniform-multifile`` byte golden.
"""
from __future__ import print_function

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import traceback

import probe_legacy
import compression_milestone1


FORMAT = "msbwt-legacy-merge-milestone1-raw-v1"
DERIVED_INPUT_FILES = compression_milestone1.DERIVED_INPUT_FILES
NAMEERROR_EXIT_CODE = 1
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def read_json(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def inventory(root):
    return compression_milestone1.inventory(root)


def parse_u1_npy(path):
    return compression_milestone1.parse_u1_npy(path)


def primary_record(path):
    """Safe-parse an NPY primary without retaining its payload bytes."""
    parsed = parse_u1_npy(path)
    parsed.pop("payload", None)
    return parsed


def require_new(path, label):
    if os.path.lexists(path):
        raise RuntimeError("{0} already exists: {1}".format(label, path))


def copy_tree(source, destination):
    require_new(destination, "copy destination")
    shutil.copytree(source, destination)
    if probe_legacy.oracle_tree_sha256(source) != probe_legacy.oracle_tree_sha256(destination):
        raise RuntimeError("tree changed while copying {0}".format(source))


def cli_argv(*arguments):
    return [sys.executable, "-c", probe_legacy.CLI_MAIN] + list(arguments)


def run_required(recorder, label, argv, cwd):
    returncode = recorder.run(label, argv, cwd=cwd)
    if returncode != 0:
        raise RuntimeError("required command failed at {0} with exit {1}".format(label, returncode))
    return returncode


def read_recorded_stream(recorder, record, field):
    path = os.path.join(recorder.output_dir, record[field])
    with open(path, "rb") as handle:
        return handle.read()


def sanitize_log_text(text, replacements):
    """Normalize timestamps and disposable absolute paths in captured log text."""
    value = text
    for source, replacement in replacements:
        value = value.replace(source, replacement)
    value = TIMESTAMP_PATTERN.sub("[TIMESTAMP]", value)
    return value


def stream_record(recorder, record, replacements):
    stdout = read_recorded_stream(recorder, record, "stdout")
    stderr = read_recorded_stream(recorder, record, "stderr")
    return {
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "sanitized_stdout": sanitize_log_text(stdout.decode("utf-8", "replace"), replacements),
        "sanitized_stderr": sanitize_log_text(stderr.decode("utf-8", "replace"), replacements),
    }


def validate_fixture_files(fixture_root, files):
    """Verify named fixture files against the committed fixture manifest."""
    root = os.path.abspath(fixture_root)
    manifest_path = os.path.join(root, probe_legacy.FIRST_GOLDEN_MANIFEST)
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise RuntimeError("unsupported fixture manifest schema")
    declared = {}
    for entry in manifest.get("files", []):
        declared[entry["path"]] = entry
    verified = []
    for name in files:
        entry = declared.get(name)
        if entry is None:
            raise RuntimeError("fixture manifest lacks required file: {0}".format(name))
        path = os.path.join(root, name)
        actual_size = os.path.getsize(path)
        actual_hash = sha256_file(path)
        if actual_size != entry["byte_count"] or actual_hash.lower() != entry["sha256"].lower():
            raise RuntimeError("fixture bytes do not match manifest for {0}".format(name))
        verified.append({"byte_count": actual_size, "path": name, "sha256": actual_hash})
    return {
        "fixture_manifest": probe_legacy.FIRST_GOLDEN_MANIFEST,
        "fixture_manifest_sha256": sha256_file(manifest_path),
        "fixture_root": root,
        "files": verified,
    }


def validate_config(path, golden_root, fixture_root):
    config = read_json(path)
    if config.get("format") != "msbwt-legacy-merge-milestone1-cases-v1":
        raise RuntimeError("unexpected merge case manifest format")
    if config.get("profile_id") != "py27-late-05a7d6d83862":
        raise RuntimeError("merge case manifest profile differs from verified profile")
    if config.get("route") != "pyx-historical-cython":
        raise RuntimeError("merge case manifest route differs from verified route")
    fixture_sets = {}
    for key, files in sorted(config["fixture_sets"].items()):
        fixture_sets[key] = validate_fixture_files(fixture_root, files)
    golden = config["clean_committed_golden"]
    golden_path = os.path.abspath(os.path.join(
        golden_root, *golden["path"]
        .replace("PROFILE", config["profile_id"])
        .replace("ROUTE", config["route"])
        .split("/")))
    build_inventory = inventory(golden_path)
    if build_inventory["tree_sha256"] != golden["tree_sha256"]:
        raise RuntimeError("committed uniform build tree differs from merge contract")
    primary_path = os.path.join(golden_path, golden["primary"])
    if sha256_file(primary_path) != golden["primary_sha256"]:
        raise RuntimeError("committed uniform msbwt.npy primary differs from merge contract")
    return config, fixture_sets, golden_path


def build_uniform(recorder, built_source, operation_root, label, fixture_paths, out_name):
    """Build one uniform byte BWT through the exact frozen CLI split path."""
    destination = os.path.join(operation_root, out_name)
    run_required(
        recorder, label + "-pp",
        cli_argv("pp", "-u", destination, *fixture_paths), built_source)
    preprocess = inventory(destination)
    run_required(
        recorder, label + "-cfpp",
        cli_argv("cfpp", "-p", "1", "-u", destination), built_source)
    output = inventory(destination)
    primary = primary_record(os.path.join(destination, "msbwt.npy"))
    return {
        "argv": [
            ["pp", "-u", "DESTINATION"] + [os.path.basename(path) for path in fixture_paths],
            ["cfpp", "-p", "1", "-u", "DESTINATION"],
        ],
        "path": destination,
        "preprocess": preprocess,
        "output": output,
        "primary": primary,
    }


def nameerror_probe(recorder, built_source, operation_root, label, input_a, input_b):
    """Record the frozen ``merge -p 1`` NameError on disposable copies."""
    probe_root = os.path.join(operation_root, "nameerror-p1")
    require_new(probe_root, "nameerror probe root")
    os.makedirs(probe_root)
    in_a = os.path.join(probe_root, "input-a")
    in_b = os.path.join(probe_root, "input-b")
    copy_tree(input_a, in_a)
    copy_tree(input_b, in_b)
    before_a = inventory(in_a)
    before_b = inventory(in_b)
    out = os.path.join(probe_root, "output")
    argv = cli_argv("merge", "-p", "1", out, in_a, in_b)
    returncode = recorder.run(label, argv, cwd=built_source)
    record = recorder.records[-1]
    streams = stream_record(recorder, record, [(built_source, "SOURCE")])
    after_a = inventory(in_a)
    after_b = inventory(in_b)
    if returncode != NAMEERROR_EXIT_CODE:
        raise RuntimeError("merge -p 1 exited {0}, expected NameError exit {1}".format(
            returncode, NAMEERROR_EXIT_CODE))
    # Frozen Python 2.7 raises UnboundLocalError (a NameError subclass) for the
    # unbound ``numProcs`` local; accept the exact subclass string.
    if "numProcs" not in streams["sanitized_stderr"] or \
            ("UnboundLocalError" not in streams["sanitized_stderr"] and
             "NameError" not in streams["sanitized_stderr"]):
        raise RuntimeError("merge -p 1 stderr lacks the numProcs NameError")
    if before_a != after_a or before_b != after_b:
        raise RuntimeError("merge -p 1 mutated its input copies")
    output_files = sorted(os.listdir(out)) if os.path.isdir(out) else None
    exception_type = "UnboundLocalError" if "UnboundLocalError" in streams["sanitized_stderr"] else (
        "NameError" if "NameError" in streams["sanitized_stderr"] else None)
    return {
        "argv": ["merge", "-p", "1", "DESTINATION", "INPUT_A", "INPUT_B"],
        "exit_code": returncode,
        "exception_type": exception_type,
        "streams": streams,
        "output_directory_created": os.path.isdir(out),
        "output_files": output_files,
        "input_a_unchanged": before_a == after_a,
        "input_b_unchanged": before_b == after_b,
    }


def merge_case(recorder, built_source, operation_root, label, input_a, input_b):
    """Run the canonical ``merge -p 2`` and inventory inputs before/after."""
    merge_root = os.path.join(operation_root, "merge")
    require_new(merge_root, "merge root")
    os.makedirs(merge_root)
    in_a = os.path.join(merge_root, "input-a")
    in_b = os.path.join(merge_root, "input-b")
    copy_tree(input_a, in_a)
    copy_tree(input_b, in_b)
    before_a = inventory(in_a)
    before_b = inventory(in_b)
    out = os.path.join(merge_root, "output")
    argv = cli_argv("merge", "-p", "2", out, in_a, in_b)
    run_required(recorder, label + "-merge", argv, built_source)
    record = recorder.records[-1]
    streams = stream_record(recorder, record, [(built_source, "SOURCE")])
    after_a = inventory(in_a)
    after_b = inventory(in_b)
    output = inventory(out)
    output_paths = sorted(item["path"] for item in output["files"])
    if output_paths != ["inter0.npy", "msbwt.npy"]:
        raise RuntimeError("merged output file set differs: {0}".format(output_paths))
    before_a_map = dict((item["path"], item) for item in before_a["files"])
    after_a_map = dict((item["path"], item) for item in after_a["files"])
    before_b_map = dict((item["path"], item) for item in before_b["files"])
    after_b_map = dict((item["path"], item) for item in after_b["files"])
    a_side_effects = sorted(set(after_a_map) - set(before_a_map))
    b_side_effects = sorted(set(after_b_map) - set(before_b_map))
    primary = primary_record(os.path.join(out, "msbwt.npy"))
    interleave = primary_record(os.path.join(out, "inter0.npy"))
    return {
        "argv": ["merge", "-p", "2", "DESTINATION", "INPUT_A", "INPUT_B"],
        "streams": streams,
        "input_a_before": before_a,
        "input_b_before": before_b,
        "input_a_after": after_a,
        "input_b_after": after_b,
        "input_a_side_effects": a_side_effects,
        "input_b_side_effects": b_side_effects,
        "output": output,
        "output_files": output_paths,
        "primary": primary,
        "interleave": interleave,
    }


def clean_case(recorder, built_source, operation_root, label, fixture_paths):
    """Build the clean-from-scratch combined control through the CLI."""
    destination = os.path.join(operation_root, "clean")
    run_required(
        recorder, label + "-clean-pp",
        cli_argv("pp", "-u", destination, *fixture_paths), built_source)
    preprocess = inventory(destination)
    run_required(
        recorder, label + "-clean-cfpp",
        cli_argv("cfpp", "-p", "1", "-u", destination), built_source)
    output = inventory(destination)
    primary = primary_record(os.path.join(destination, "msbwt.npy"))
    return {
        "argv": [
            ["pp", "-u", "DESTINATION", "uniform-a.fastq", "uniform-b.fastq"],
            ["cfpp", "-p", "1", "-u", "DESTINATION"],
        ],
        "path": destination,
        "preprocess": preprocess,
        "output": output,
        "primary": primary,
    }


def run_reader_smoke(recorder, environment_root, built_source, merged_dir, copy_path,
                     fixture_root, case_id, output, label, classification=False):
    argv = [
        sys.executable, os.path.join(environment_root, "reader_smoke.py"),
        "--source", built_source, "--dataset", merged_dir, "--copy", copy_path,
        "--fixture-root", fixture_root, "--case", case_id, "--output", output
    ]
    if classification:
        argv.append("--classification")
    run_required(recorder, label, argv, built_source)
    return read_json(output)


def run_cli_query(recorder, built_source, operation_root, label, merged_copy):
    """Probe the frozen ``query`` CLI on a disposable merged copy."""
    probe_root = os.path.join(operation_root, "query-cli")
    require_new(probe_root, "query CLI probe root")
    os.makedirs(probe_root)
    count_copy = os.path.join(probe_root, "count-copy")
    dump_copy = os.path.join(probe_root, "dump-copy")
    copy_tree(merged_copy, count_copy)
    copy_tree(merged_copy, dump_copy)
    count_argv = cli_argv("query", count_copy, "ACGTN")
    count_exit = run_required(recorder, label + "-query-count", count_argv, built_source)
    count_record = recorder.records[-1]
    count_stdout = read_recorded_stream(recorder, count_record, "stdout")
    dump_argv = cli_argv("query", "-d", dump_copy, "ACGTN")
    dump_exit = run_required(recorder, label + "-query-dump", dump_argv, built_source)
    dump_record = recorder.records[-1]
    dump_stdout = read_recorded_stream(recorder, dump_record, "stdout")
    count_text = count_stdout.decode("utf-8", "replace").strip()
    if count_text != "3":
        raise RuntimeError("query ACGTN count differs: {0!r}".format(count_text))
    dump_lines = [line.strip() for line in dump_stdout.decode("utf-8", "replace").splitlines()
                  if line.strip()]
    dumped = sorted(line.split(",")[0] for line in dump_lines)
    if dumped != ["ACGTN", "ACGTN", "ACGTN"]:
        raise RuntimeError("query -d dumped strings differ: {0}".format(dumped))
    return {
        "argv": [["query", "COPY", "ACGTN"], ["query", "-d", "COPY", "ACGTN"]],
        "count_exit_code": count_exit,
        "count_stdout_sha256": hashlib.sha256(count_stdout).hexdigest(),
        "count_text": count_text,
        "dump_exit_code": dump_exit,
        "dump_stdout_sha256": hashlib.sha256(dump_stdout).hexdigest(),
        "dumped_strings": dumped,
        "count_copy": inventory(count_copy),
        "dump_copy": inventory(dump_copy),
    }


def reader_evidence(recorder, environment_root, built_source, raw_root, run_id,
                    fixture_root, config, merged_path):
    root = os.path.join(raw_root, run_id, "reader")
    require_new(root, "merge reader evidence root")
    os.makedirs(root)
    smoke = run_reader_smoke(
        recorder, environment_root, built_source, merged_path,
        os.path.join(root, "merged-copy"), fixture_root,
        config["reader"]["case_id"], os.path.join(root, "reader-smoke.json"),
        run_id + "-reader-smoke", classification=True)
    query = run_cli_query(
        recorder, built_source, root, run_id + "-query", merged_path)
    return {
        "reader_smoke": smoke,
        "cli_query": query,
    }


def assert_determinism(result, config):
    run_a = result["cases"]["run-a"]
    run_b = result["cases"]["run-b"]
    comparisons = {}
    for key in ("input_a", "input_b", "clean"):
        left = run_a[key]
        right = run_b[key]
        comparisons[key] = {
            "preprocess_identical": left["preprocess"] == right["preprocess"],
            "output_identical": left["output"] == right["output"],
            "primary_identical": left["primary"] == right["primary"],
        }
    for key in ("merged",):
        left = run_a[key]
        right = run_b[key]
        comparisons[key] = {
            "input_a_before_identical": left["input_a_before"] == right["input_a_before"],
            "input_b_before_identical": left["input_b_before"] == right["input_b_before"],
            "input_a_after_identical": left["input_a_after"] == right["input_a_after"],
            "input_b_after_identical": left["input_b_after"] == right["input_b_after"],
            "output_identical": left["output"] == right["output"],
            "primary_identical": left["primary"] == right["primary"],
            "interleave_identical": left["interleave"] == right["interleave"],
            "input_a_side_effects_identical": left["input_a_side_effects"] == right["input_a_side_effects"],
            "input_b_side_effects_identical": left["input_b_side_effects"] == right["input_b_side_effects"],
        }
    for key in ("nameerror",):
        left = run_a[key]
        right = run_b[key]
        comparisons[key] = {
            "exit_code_identical": left["exit_code"] == right["exit_code"],
            "sanitized_stderr_identical": left["streams"]["sanitized_stderr"] == right["streams"]["sanitized_stderr"],
            "stderr_sha256_identical": left["streams"]["stderr_sha256"] == right["streams"]["stderr_sha256"],
            "output_directory_created": left["output_directory_created"] and right["output_directory_created"],
            "output_files_identical": left["output_files"] == right["output_files"],
        }
    for key in ("reader",):
        left = run_a[key]
        right = run_b[key]
        comparisons[key] = {
            "reader_smoke_queries_identical": (
                left["reader_smoke"]["actual_queries"] == right["reader_smoke"]["actual_queries"]),
            "reader_smoke_recovery_identical": (
                left["reader_smoke"]["actual_recovered_strings"] == right["reader_smoke"]["actual_recovered_strings"]),
            "reader_smoke_total_size_identical": (
                left["reader_smoke"]["total_size"] == right["reader_smoke"]["total_size"]),
            "reader_class_identical": (
                left["reader_smoke"]["reader_class"] == right["reader_smoke"]["reader_class"]),
            "cli_query_count_identical": (
                left["cli_query"]["count_text"] == right["cli_query"]["count_text"]),
            "cli_query_dumped_identical": (
                left["cli_query"]["dumped_strings"] == right["cli_query"]["dumped_strings"]),
        }
    failed = []
    for key, item in comparisons.items():
        for field, value in item.items():
            if not value:
                failed.append("{0}.{1}".format(key, field))
    if failed:
        raise RuntimeError("merge milestone determinism failed: {0}".format(failed))
    return comparisons


def execute(recorder, built_source, run_dir, fixture_root, golden_root, manifest_path):
    if sys.version_info[:2] != (2, 7) or platform.python_implementation() != "CPython":
        raise RuntimeError("merge milestone requires genuine CPython 2.7")
    config, fixture_sets, golden_path = validate_config(
        manifest_path, golden_root, fixture_root)
    milestone_root = os.path.join(run_dir, "merge-milestone1")
    require_new(milestone_root, "merge milestone result")
    os.makedirs(milestone_root)
    raw_root = os.path.join(milestone_root, "raw")
    os.makedirs(raw_root)
    environment_root = os.path.dirname(os.path.abspath(__file__))
    result = {
        "format": FORMAT,
        "manifest_sha256": sha256_file(manifest_path),
        "profile_id": config["profile_id"],
        "route": config["route"],
        "status": "not-run",
        "cases": {},
        "determinism": {},
        "canonical_runs": config["canonical_runs"],
        "clean_committed_golden": {
            "path": golden_path,
            "tree_sha256": config["clean_committed_golden"]["tree_sha256"],
            "primary_sha256": config["clean_committed_golden"]["primary_sha256"],
        },
        "fixture_sets": fixture_sets,
    }
    try:
        for run_id in config["canonical_runs"]:
            run_root = os.path.join(raw_root, run_id)
            require_new(run_root, "fresh merge run root")
            os.makedirs(run_root)
            input_a = build_uniform(
                recorder, built_source, run_root, run_id + "-input-a",
                [os.path.join(fixture_sets["input_a"]["fixture_root"], item["path"])
                 for item in fixture_sets["input_a"]["files"]], "input-a")
            input_b = build_uniform(
                recorder, built_source, run_root, run_id + "-input-b",
                [os.path.join(fixture_sets["input_b"]["fixture_root"], item["path"])
                 for item in fixture_sets["input_b"]["files"]], "input-b")
            clean = clean_case(
                recorder, built_source, run_root, run_id + "-clean",
                [os.path.join(fixture_sets["clean"]["fixture_root"], item["path"])
                 for item in fixture_sets["clean"]["files"]])
            if clean["primary"]["sha256"] != config["clean_committed_golden"]["primary_sha256"]:
                raise RuntimeError("clean control primary differs from committed uniform golden")
            nameerror = nameerror_probe(
                recorder, built_source, run_root, run_id + "-nameerror",
                input_a["path"], input_b["path"])
            merged = merge_case(
                recorder, built_source, run_root, run_id + "-merge",
                input_a["path"], input_b["path"])
            if merged["primary"]["shape"] != [config["expected"]["merged"]["symbols"]]:
                raise RuntimeError("merged primary shape differs from expected symbols")
            if merged["interleave"]["shape"] != config["expected"]["merged"]["interleave_shape"]:
                raise RuntimeError("merged interleave shape differs from expected")
            reader = reader_evidence(
                recorder, environment_root, built_source, raw_root, run_id,
                fixture_root, config, merged["path"] + "/output")
            result["cases"][run_id] = {
                "input_a": input_a,
                "input_b": input_b,
                "clean": clean,
                "nameerror": nameerror,
                "merged": merged,
                "reader": reader,
            }
        result["determinism"] = assert_determinism(result, config)
        result["status"] = "passed"
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = "{0}: {1}".format(exc.__class__.__name__, exc)
        result["traceback"] = traceback.format_exc()
        raise
    finally:
        probe_legacy.write_json(os.path.join(milestone_root, "raw-result.json"), result)
