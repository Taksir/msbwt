#!/usr/bin/env python
"""Execute the non-resumable interruption characterization under Python 2.7.

This module is called only after ``probe_legacy`` has built and gated a frozen
source copy.  Milestone 3 is failure characterization only: it determines what
the frozen implementation actually does when interrupted in states that are
not valid resumable checkpoints.  No recovery or successful-golden claim is
made for any partial artifact.

Cases (external failpoint adapter, frozen source never patched):

  m3c1  post-hoc compression: the frozen ``MUS.MSBWTGen.compressBWTPoolProcess``
        is called once for the first bin, then the adapter exits 86 before the
        parent join step.  The destination retains the complete
        ``comp_msbwt.npy.temp.<bin>.npy`` chunk and no final primary.
  m3c2  post-hoc decompression: the frozen ``decompressBWT`` preallocation and
        tuple dispatch are replicated, then ``decompressBWTPoolProcess`` is
        called for the first tuple.  If it completes, the adapter exits 86
        before the second tuple; if the frozen worker itself raises (the
        committed profile-specific decompression failure contract), the natural
        failure is recorded and the adapter exits ``NATURAL_FAILURE_EXIT_CODE``.
  m3c3  parser refusal: the unchanged CLI is invoked against copies of each
        nonempty interrupted destination; the ``util.newDirectory`` type
        refuses the destination during argument parsing.
  m3c4  uniform byte builder: ``MSBWTGenCython.createMsbwtFromSeqs`` is
        interrupted at "Finished iteration 2 in"; a subsequent ``cfpp -p 1 -u``
        restarts construction from scratch because the byte builder has no
        checkpoint scan.  Whether the restarted output matches a clean build is
        recorded, but it is labelled restart-from-scratch, never resume.

Host-side tooling performs safe NPY parsing and promotion after every
relationship below passes.
"""
from __future__ import print_function

import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import traceback

import probe_legacy
import compression_milestone1
import compression_milestone2


FORMAT = "msbwt-legacy-compression-milestone3-raw-v1"
FAILPOINT_EXIT_CODE = 86
NATURAL_FAILURE_EXIT_CODE = 87
FAILPOINT_TIMEOUT_SECONDS = 1200

RESUME_MARKERS = ("Resuming previous run", "Backup located", "resuming...")
FROM_SCRATCH_MARKERS = ("Generating level 1 insertions", "Beginning iterations")
PARSER_REFUSAL_EXIT_CODE = 2


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


def validate_config(path, golden_root, fixture_root):
    config = read_json(path)
    if config.get("format") != "msbwt-legacy-compression-milestone3-cases-v1":
        raise RuntimeError("unexpected milestone-3 case manifest format")
    if config.get("profile_id") != "py27-late-05a7d6d83862":
        raise RuntimeError("milestone-3 case manifest profile differs from verified profile")
    if config.get("route") != "pyx-historical-cython":
        raise RuntimeError("milestone-3 case manifest route differs from verified route")
    if config.get("failpoint_exit_code") != FAILPOINT_EXIT_CODE:
        raise RuntimeError("milestone-3 failpoint exit code differs")
    if config.get("natural_failure_exit_code") != NATURAL_FAILURE_EXIT_CODE:
        raise RuntimeError("milestone-3 natural failure exit code differs")
    fixtures = {
        "uniform": probe_legacy.validate_golden_case(
            fixture_root, config["fixture_cases"]["uniform"])
    }
    golden = config["uniform_byte_golden"]
    golden_path = os.path.abspath(os.path.join(
        golden_root, *golden["path"]
        .replace("PROFILE", config["profile_id"])
        .replace("ROUTE", config["route"])
        .split("/")))
    build_inventory = inventory(golden_path)
    if build_inventory["tree_sha256"] != golden["tree_sha256"]:
        raise RuntimeError("committed uniform build tree differs from milestone-3 contract")
    primary_path = os.path.join(golden_path, golden["primary"])
    if sha256_file(primary_path) != golden["primary_sha256"]:
        raise RuntimeError("committed uniform msbwt.npy primary differs from milestone-3 contract")
    return config, fixtures, golden_path


def run_failpoint(recorder, adapter_path, built_source, operation_root, label,
                  case_id, case_config, dataset, destination=None):
    """Invoke the frozen worker through the external failpoint adapter.

    The adapter runs in a new process session so the harness can terminate any
    remaining multiprocessing pool children after the adapter exits.  For
    m3c1/m3c4 the adapter exits ``FAILPOINT_EXIT_CODE``; for m3c2 it exits
    ``FAILPOINT_EXIT_CODE`` if the first tuple completes or
    ``NATURAL_FAILURE_EXIT_CODE`` if the frozen worker itself fails.
    """
    record_path = os.path.join(operation_root, "failpoint-record.json")
    log_path = os.path.join(operation_root, "failpoint-log.txt")
    argv = [
        sys.executable, adapter_path,
        "--dataset", dataset,
        "--case", case_id,
        "--failpoint-prefix", case_config["failpoint_prefix"],
        "--record", record_path,
        "--log", log_path,
        "--processes", str(case_config["adapter_processes"])
    ]
    if destination is not None:
        argv.extend(["--destination", destination])
    index = len(recorder.records) + 1
    stem = "{0:03d}-{1}".format(index, probe_legacy.safe_component(label))
    stdout_name = stem + ".stdout"
    stderr_name = stem + ".stderr"
    stdout_path = os.path.join(recorder.commands_dir, stdout_name)
    stderr_path = os.path.join(recorder.commands_dir, stderr_name)
    with open(stdout_path, "wb") as stdout_handle:
        with open(stderr_path, "wb") as stderr_handle:
            process = subprocess.Popen(
                argv, cwd=built_source, stdout=stdout_handle, stderr=stderr_handle,
                preexec_fn=os.setsid)
            returncode = compression_milestone2.poll_with_timeout(process, label)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    with open(stdout_path, "rb") as handle:
        stdout = handle.read()
    with open(stderr_path, "rb") as handle:
        stderr = handle.read()
    record = {
        "argv": argv,
        "cwd": built_source,
        "label": label,
        "returncode": returncode,
        "stderr": os.path.join("commands", stderr_name),
        "stdout": os.path.join("commands", stdout_name)
    }
    recorder.records.append(record)
    expected_exits = case_config["expected_exit_codes"]
    if returncode not in expected_exits:
        raise RuntimeError("failpoint adapter exited {0}; expected one of {1} at {2}".format(
            returncode, expected_exits, label))
    if not os.path.isfile(record_path):
        raise RuntimeError("failpoint adapter did not flush a record at {0}".format(label))
    failpoint_record = read_json(record_path)
    return {
        "exit_code": returncode,
        "record": failpoint_record,
        "record_sha256": sha256_file(record_path),
        "log_sha256": sha256_file(log_path),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }


def tree_compare(left, right):
    return compression_milestone2.tree_compare(left, right)


def nonzero_region_fingerprint(payload, boundary):
    """Return which regions of a decompressed evidence primary are non-zero.

    Iteration of a Python 2 ``str`` yields 1-char strings while Python 3
    iteration yields ints, so byte values are normalized with the shared
    ``compression_milestone1._byte_value`` helper; ``'\x00' != 0`` would
    otherwise be True for an all-zero payload under Python 2.
    """
    prefix = payload[:boundary]
    tail = payload[boundary:]
    return {
        "boundary": boundary,
        "prefix_region_any_nonzero": any(
            compression_milestone1._byte_value(byte) != 0 for byte in prefix),
        "tail_region_any_nonzero": any(
            compression_milestone1._byte_value(byte) != 0 for byte in tail),
    }


def m3c1_case(recorder, built_source, environment_root, operation_root, label,
              uniform_build, config):
    """Interrupt post-hoc compression after the first worker bin."""
    case_config = config["cases"]["m3c1"]
    case_root = os.path.join(operation_root, "m3c1")
    require_new(case_root, "m3c1 case root")
    os.makedirs(case_root)
    src = os.path.join(case_root, "m3c1-source")
    dst = os.path.join(case_root, "m3c1-destination")
    copy_tree(uniform_build, src)
    require_new(dst, "m3c1 destination")
    os.makedirs(dst)
    source_before = inventory(src)
    failpoint = run_failpoint(
        recorder, os.path.join(environment_root, "failpoint_adapter.py"),
        built_source, case_root, label + "-m3c1-failpoint",
        "m3c1", case_config, src, destination=dst)
    source_after = inventory(src)
    destination = inventory(dst)
    temp_files = sorted(
        item for item in destination["files"]
        if item["path"].startswith(case_config["temp_prefix"]))
    if len(temp_files) != 1:
        raise RuntimeError("m3c1 interrupted destination has {0} temp files, expected 1".format(
            len(temp_files)))
    final_paths = [item["path"] for item in destination["files"]]
    if case_config["final_primary"] in final_paths:
        raise RuntimeError("m3c1 interrupted destination already contains the final primary")
    if source_before != source_after:
        raise RuntimeError("m3c1 source changed during the compression worker")
    temp_record = primary_record(os.path.join(dst, temp_files[0]["path"]))
    temp_payload_matches_rle_contract = (
        temp_record["payload_sha256"] == config["uniform_rle_payload_sha256"])
    if not temp_payload_matches_rle_contract:
        raise RuntimeError("m3c1 interrupted temp payload differs from the committed RLE contract")
    return {
        "argv": ["compressBWTPoolProcess first tuple -> comp_msbwt.npy.temp.0.npy"],
        "source_before": source_before,
        "source_after": source_after,
        "source_unchanged": source_before == source_after,
        "failpoint": failpoint,
        "destination_path": dst,
        "destination": destination,
        "temp_files": [item["path"] for item in temp_files],
        "temp_primary": temp_record,
        "temp_payload_matches_rle_contract": temp_payload_matches_rle_contract,
        "final_primary_present": False,
    }


def m3c2_case(recorder, built_source, environment_root, operation_root, label,
              uniform_build, config):
    """Interrupt post-hoc decompression after the first worker tuple."""
    case_config = config["cases"]["m3c2"]
    evidence_config = config["evidence"]
    import numpy as np

    case_root = os.path.join(operation_root, "m3c2")
    require_new(case_root, "m3c2 case root")
    os.makedirs(case_root)

    evidence_root = os.path.join(case_root, "m3c2-evidence")
    require_new(evidence_root, "m3c2 evidence root")
    os.makedirs(evidence_root)
    src_primary = os.path.join(uniform_build, "msbwt.npy")
    evidence = np.load(src_primary, 'r')
    tiled = np.tile(evidence, evidence_config["repeat_count"])
    np.save(os.path.join(evidence_root, "msbwt.npy"), tiled)
    evidence_primary = primary_record(os.path.join(evidence_root, "msbwt.npy"))
    if evidence_primary["shape"][0] != evidence_config["expected_total_symbols"]:
        raise RuntimeError("evidence primary shape differs from expected total symbols")

    rle_root = os.path.join(case_root, "m3c2-rle-clean")
    run_required(
        recorder, label + "-m3c2-compress",
        cli_argv("compress", "-p", "1", evidence_root, rle_root), built_source)
    rle_inventory = inventory(rle_root)
    rle_primary = primary_record(os.path.join(rle_root, "comp_msbwt.npy"))
    if any(item["path"].startswith("comp_msbwt.npy.temp.") for item in rle_inventory["files"]):
        raise RuntimeError("clean evidence compression retained a temp file")

    source_copy = os.path.join(case_root, "m3c2-source-copy")
    copy_tree(rle_root, source_copy)
    source_before = inventory(source_copy)

    dst = os.path.join(case_root, "m3c2-destination")
    require_new(dst, "m3c2 destination")
    os.makedirs(dst)
    failpoint = run_failpoint(
        recorder, os.path.join(environment_root, "failpoint_adapter.py"),
        built_source, case_root, label + "-m3c2-failpoint",
        "m3c2", case_config, source_copy, destination=dst)
    source_after = inventory(source_copy)
    destination = inventory(dst)

    before_map = dict((item["path"], item) for item in source_before["files"])
    after_map = dict((item["path"], item) for item in source_after["files"])
    side_effects = sorted(set(after_map) - set(before_map))
    if side_effects != case_config["source_side_effects"]:
        raise RuntimeError("m3c2 source side effects differ: {0}".format(side_effects))
    if [item["path"] for item in destination["files"]] != ["msbwt.npy"]:
        raise RuntimeError("m3c2 destination file set differs")

    dst_primary = parse_u1_npy(os.path.join(dst, "msbwt.npy"))
    fingerprint = nonzero_region_fingerprint(dst_primary["payload"], evidence_config["compression_worksize"])
    del dst_primary["payload"]

    mode = failpoint["record"].get("mode")
    if mode == "first-tuple-completed" and not fingerprint["prefix_region_any_nonzero"]:
        raise RuntimeError("m3c2 worker reported completion but the first region is all zero")
    if mode == "first-tuple-worker-failed-naturally" and fingerprint["prefix_region_any_nonzero"]:
        raise RuntimeError("m3c2 worker failed but the first region is non-zero")

    return {
        "argv": ["compress -p 1 EVIDENCE_SRC EVIDENCE_RLE",
                 "decompressBWTPoolProcess first tuple -> preallocated msbwt.npy"],
        "evidence_primary": evidence_primary,
        "rle_clean_path": rle_root,
        "rle_clean": rle_inventory,
        "rle_clean_primary": rle_primary,
        "source_before": source_before,
        "source_after": source_after,
        "source_side_effects": side_effects,
        "failpoint": failpoint,
        "worker_mode": mode,
        "destination_path": dst,
        "destination": destination,
        "destination_primary": dst_primary,
        "region_fingerprint": fingerprint,
    }


def m3c4_case(recorder, built_source, environment_root, operation_root, label,
              fixture, config):
    """Interrupt the uniform byte builder and then restart it from scratch."""
    case_config = config["cases"]["m3c4"]
    case_root = os.path.join(operation_root, "m3c4")
    require_new(case_root, "m3c4 case root")
    os.makedirs(case_root)
    fixture_paths = [os.path.join(fixture["fixture_root"], item["path"])
                     for item in fixture["files"]]
    partial = os.path.join(case_root, "m3c4-partial")
    run_required(
        recorder, label + "-m3c4-preprocess",
        cli_argv("pp", "-u", partial, *fixture_paths), built_source)
    preprocess = inventory(partial)
    if preprocess["tree_sha256"] != config["uniform_preprocess"]["tree_sha256"]:
        raise RuntimeError("m3c4 preprocessing tree differs from committed uniform preprocessing")

    failpoint = run_failpoint(
        recorder, os.path.join(environment_root, "failpoint_adapter.py"),
        built_source, case_root, label + "-m3c4-failpoint",
        "m3c4", case_config, partial)
    partial_tree = inventory(partial)
    state_files = sorted(
        item["path"] for item in partial_tree["files"]
        if item["path"].startswith("state.") and item["path"].endswith(".2.npy"))
    if len(state_files) != case_config["partial_minimum_state_files"]:
        raise RuntimeError("m3c4 partial tree has {0} state files, expected {1}: {2}".format(
            len(state_files), case_config["partial_minimum_state_files"], state_files))

    restart = os.path.join(case_root, "m3c4-restart")
    copy_tree(partial, restart)
    restart_exit = run_required(
        recorder, label + "-m3c4-restart",
        cli_argv("cfpp", "-p", "1", "-u", restart), built_source)
    restart_record = recorder.records[-1]
    restart_stdout = read_recorded_stream(recorder, restart_record, "stdout").decode("utf-8", "replace")
    seen_resume = [marker for marker in RESUME_MARKERS if marker in restart_stdout]
    seen_from_scratch = [marker for marker in FROM_SCRATCH_MARKERS if marker in restart_stdout]
    restart_tree = inventory(restart)
    restart_primary = primary_record(os.path.join(restart, "msbwt.npy"))

    clean_partial = os.path.join(case_root, "m3c4-clean-partial")
    run_required(
        recorder, label + "-m3c4-clean-preprocess",
        cli_argv("pp", "-u", clean_partial, *fixture_paths), built_source)
    clean_preprocess = inventory(clean_partial)
    if clean_preprocess != preprocess:
        raise RuntimeError("m3c4 clean preprocessing tree differs from partial preprocessing")
    run_required(
        recorder, label + "-m3c4-clean",
        cli_argv("cfpp", "-p", "1", "-u", clean_partial), built_source)
    clean_tree = inventory(clean_partial)
    clean_primary = primary_record(os.path.join(clean_partial, "msbwt.npy"))

    tree_match = tree_compare(restart_tree, clean_tree)
    primary_equal = restart_primary == clean_primary
    clean_matches_committed = (
        clean_primary["sha256"] == case_config["clean_primary_sha256"])
    restart_matches_committed = (
        restart_primary["sha256"] == case_config["clean_primary_sha256"])

    return {
        "preprocess": preprocess,
        "failpoint": failpoint,
        "partial": partial_tree,
        "state_files": state_files,
        "restart": {
            "exit_code": restart_exit,
            "mode": case_config["restart_mode"],
            "seen_resume_markers": seen_resume,
            "seen_from_scratch_markers": seen_from_scratch,
            "stdout_sha256": hashlib.sha256(restart_stdout.encode("utf-8")).hexdigest(),
        },
        "restart_dir": restart,
        "clean_dir": clean_partial,
        "restart_tree": restart_tree,
        "restart_primary": restart_primary,
        "clean_tree": clean_tree,
        "clean_primary": clean_primary,
        "relationship": {
            "tree_equal": tree_match["matches"],
            "primary_equal": primary_equal,
            "tree_comparison": tree_match,
            "restart_mode": case_config["restart_mode"],
            "clean_matches_committed_primary": clean_matches_committed,
            "restart_matches_committed_primary": restart_matches_committed,
        },
    }


def parser_refusal(recorder, built_source, operation_root, label, case_id,
                   interrupted_destination, source_artifacts, config):
    """Invoke the unchanged CLI against a copy of an interrupted destination."""
    refusal = config["parser_refusals"][case_id]
    dst = os.path.join(operation_root, "refusal-" + case_id + "-destination")
    copy_tree(interrupted_destination, dst)
    src = os.path.join(operation_root, "refusal-" + case_id + "-source")
    copy_tree(source_artifacts, src)
    argv = cli_argv(*[part.replace("SOURCE", src).replace("DESTINATION", dst)
                      for part in refusal["cli"]])
    returncode = recorder.run(label, argv, cwd=built_source)
    record = recorder.records[-1]
    stderr = read_recorded_stream(recorder, record, "stderr")
    stdout = read_recorded_stream(recorder, record, "stdout")
    stderr_text = stderr.decode("utf-8", "replace")
    sanitized = stderr_text.replace(dst, "DESTINATION").replace(src, "SOURCE")
    if returncode != PARSER_REFUSAL_EXIT_CODE:
        raise RuntimeError("parser refusal for {0} exited {1}, expected {2}".format(
            case_id, returncode, PARSER_REFUSAL_EXIT_CODE))
    if "Non-empty directory already exists" not in sanitized:
        raise RuntimeError("parser refusal for {0} lacks the nonempty-destination message".format(
            case_id))
    return {
        "argv": refusal["cli"],
        "exit_code": returncode,
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "sanitized_stderr": sanitized,
        "sanitized_stderr_sha256": hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
    }


def assert_determinism(result, config):
    run_a = result["cases"]["run-a"]
    run_b = result["cases"]["run-b"]
    partial_key = {"m3c1": "destination", "m3c2": "destination", "m3c4": "partial"}
    comparisons = {}
    for case_id in ("m3c1", "m3c2", "m3c4"):
        left = run_a[case_id]
        right = run_b[case_id]
        item = {
            "case": case_id,
            "partial_manifests_identical": left[partial_key[case_id]]["tree_sha256"] == right[partial_key[case_id]]["tree_sha256"],
            "partial_entries_identical": left[partial_key[case_id]] == right[partial_key[case_id]],
            "failpoint_mode_identical": left["failpoint"]["record"].get("mode") == right["failpoint"]["record"].get("mode"),
            "failpoint_exit_identical": left["failpoint"]["exit_code"] == right["failpoint"]["exit_code"],
        }
        if case_id == "m3c1":
            item["temp_primary_identical"] = left["temp_primary"] == right["temp_primary"]
        elif case_id == "m3c2":
            item["destination_primary_identical"] = left["destination_primary"] == right["destination_primary"]
            item["region_fingerprint_identical"] = left["region_fingerprint"] == right["region_fingerprint"]
            item["source_side_effects_identical"] = left["source_side_effects"] == right["source_side_effects"]
        elif case_id == "m3c4":
            item["restart_trees_identical"] = left["restart_tree"] == right["restart_tree"]
            item["clean_trees_identical"] = left["clean_tree"] == right["clean_tree"]
            item["restart_primary_identical"] = left["restart_primary"] == right["restart_primary"]
            item["clean_primary_identical"] = left["clean_primary"] == right["clean_primary"]
        comparisons[case_id] = item
    refusal_comparison = {}
    for refusal_id in ("m3c1", "m3c2"):
        left = run_a["refusals"][refusal_id]
        right = run_b["refusals"][refusal_id]
        refusal_comparison[refusal_id] = {
            "exit_code_identical": left["exit_code"] == right["exit_code"],
            "sanitized_stderr_identical": left["sanitized_stderr"] == right["sanitized_stderr"],
        }
    for case_id, item in comparisons.items():
        if not item["partial_manifests_identical"] or \
                not item["failpoint_mode_identical"] or \
                not item["failpoint_exit_identical"]:
            raise RuntimeError("{0} partial/failpoint state differs across canonical runs".format(case_id))
    for refusal_id, item in refusal_comparison.items():
        if not item["exit_code_identical"] or not item["sanitized_stderr_identical"]:
            raise RuntimeError("parser refusal {0} differs across canonical runs".format(refusal_id))
    return {"cases": comparisons, "parser_refusals": refusal_comparison}


def execute(recorder, built_source, run_dir, fixture_root, golden_root, manifest_path):
    if sys.version_info[:2] != (2, 7) or platform.python_implementation() != "CPython":
        raise RuntimeError("compression milestone 3 requires genuine CPython 2.7")
    config, fixtures, uniform_build = validate_config(manifest_path, golden_root, fixture_root)
    milestone_root = os.path.join(run_dir, "compression-milestone3")
    require_new(milestone_root, "compression milestone 3 result")
    os.makedirs(milestone_root)
    raw_root = os.path.join(milestone_root, "raw")
    os.makedirs(raw_root)
    environment_root = os.path.dirname(os.path.abspath(__file__))
    result = {
        "format": FORMAT, "manifest_sha256": sha256_file(manifest_path),
        "profile_id": config["profile_id"], "route": config["route"],
        "status": "not-run", "cases": {}, "determinism": {},
        "canonical_runs": config["canonical_runs"],
        "failpoint_exit_code": FAILPOINT_EXIT_CODE,
        "natural_failure_exit_code": NATURAL_FAILURE_EXIT_CODE,
    }
    try:
        for run_id in config["canonical_runs"]:
            run_root = os.path.join(raw_root, run_id)
            require_new(run_root, "fresh milestone-3 run root")
            os.makedirs(run_root)
            m3c1 = m3c1_case(
                recorder, built_source, environment_root, run_root,
                run_id + "-m3c1", uniform_build, config)
            m3c2 = m3c2_case(
                recorder, built_source, environment_root, run_root,
                run_id + "-m3c2", uniform_build, config)
            m3c4 = m3c4_case(
                recorder, built_source, environment_root, run_root,
                run_id + "-m3c4", fixtures["uniform"], config)
            refusals = {
                "m3c1": parser_refusal(
                    recorder, built_source, run_root, run_id + "-refusal-m3c1",
                    "m3c1", m3c1["destination_path"],
                    uniform_build, config),
                "m3c2": parser_refusal(
                    recorder, built_source, run_root, run_id + "-refusal-m3c2",
                    "m3c2", m3c2["destination_path"],
                    m3c2["rle_clean_path"], config),
            }
            result["cases"][run_id] = {
                "m3c1": m3c1,
                "m3c2": m3c2,
                "m3c4": m3c4,
                "refusals": refusals,
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
