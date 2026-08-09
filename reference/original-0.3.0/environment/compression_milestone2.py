#!/usr/bin/env python
"""Execute the implemented builder recovery characterization under Python 2.7.

This module is called only after ``probe_legacy`` has built and gated a frozen
source copy.  It records raw Linux-ext4 evidence for the two implemented
restart detectors without patching frozen source:

  R1  direct uniform RLE checkpoint: frozen
      ``MSBWTCompGenCython.createMsbwtFromSeqs`` interrupted by an external
      failpoint at "Finished iteration 2 in", then resumed through the CLI.
  R2  nonuniform multimerge backup: frozen
      ``MultimergeCython.interleaveLevelMerge`` interrupted at "Backup creation
      finished.", then resumed through the CLI.

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


FORMAT = "msbwt-legacy-compression-milestone2-raw-v1"
FAILPOINT_EXIT_CODE = 86
FAILPOINT_TIMEOUT_SECONDS = 900


def poll_with_timeout(process, label):
    """Wait for the failpoint adapter, killing its process group on timeout."""
    deadline = time.time() + FAILPOINT_TIMEOUT_SECONDS
    while process.poll() is None:
        if time.time() > deadline:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.wait()
            raise RuntimeError("failpoint adapter timed out at {0}".format(label))
        time.sleep(0.2)
    return process.returncode


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


def rle_primary_record(path):
    return compression_milestone1.rle_primary_record(path)


def parse_u1_npy(path):
    return compression_milestone1.parse_u1_npy(path)


def validate_config(path, golden_root, fixture_root):
    config = read_json(path)
    if config.get("format") != "msbwt-legacy-compression-milestone2-cases-v1":
        raise RuntimeError("unexpected compression recovery case manifest format")
    if config.get("profile_id") != "py27-late-05a7d6d83862":
        raise RuntimeError("compression recovery case manifest profile differs from verified profile")
    if config.get("route") != "pyx-historical-cython":
        raise RuntimeError("compression recovery case manifest route differs from verified route")
    if config.get("failpoint_exit_code") != FAILPOINT_EXIT_CODE:
        raise RuntimeError("compression recovery failpoint exit code differs")
    fixtures = {
        "uniform": probe_legacy.validate_golden_case(
            fixture_root, config["fixture_cases"]["uniform"]),
        "nonuniform_recovery": probe_legacy.validate_golden_case(
            fixture_root, config["fixture_cases"]["nonuniform_recovery"])
    }
    uniform_pre_root = os.path.abspath(os.path.join(
        golden_root,
        "uniform-multifile", config["profile_id"], config["route"], "pre", "artifacts"))
    pre_actual = inventory(uniform_pre_root)
    pre_contract = config["uniform_preprocess"]
    if pre_actual["tree_sha256"] != pre_contract["tree_sha256"]:
        raise RuntimeError("committed uniform preprocessing tree differs from recovery contract")
    return config, fixtures


def run_failpoint(recorder, adapter_path, built_source, operation_root, label, case_id, case_config,
                  dataset):
    """Invoke the frozen builder through the external failpoint adapter.

    The adapter runs in a new process session (``setsid``) so the harness can
    terminate any remaining multiprocessing pool children of the frozen builder
    after the adapter exits with ``FAILPOINT_EXIT_CODE``.  The adapter's
    stdout/stderr are recorded into the probe command stream for provenance.
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
    index = len(recorder.records) + 1
    stem = "{0:03d}-{1}".format(index, probe_legacy.safe_component(label))
    stdout_name = stem + ".stdout"
    stderr_name = stem + ".stderr"
    stdout_path = os.path.join(recorder.commands_dir, stdout_name)
    stderr_path = os.path.join(recorder.commands_dir, stderr_name)
    # Redirect the adapter's stdout/stderr to files rather than pipes: the
    # forked multiprocessing pool children inherit pipe descriptors, so a pipe
    # read would never see EOF until those children are killed.
    with open(stdout_path, "wb") as stdout_handle:
        with open(stderr_path, "wb") as stderr_handle:
            process = subprocess.Popen(
                argv, cwd=built_source, stdout=stdout_handle, stderr=stderr_handle,
                preexec_fn=os.setsid)
            returncode = poll_with_timeout(process, label)
    # The failpoint adapter calls os._exit, which leaves multiprocessing pool
    # children behind in its process group; terminate the whole group.
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
    if returncode != FAILPOINT_EXIT_CODE:
        raise RuntimeError("failpoint adapter exited {0} instead of {1} at {2}".format(
            returncode, FAILPOINT_EXIT_CODE, label))
    if not os.path.isfile(record_path):
        raise RuntimeError("failpoint adapter did not flush a record at {0}".format(label))
    failpoint_record = read_json(record_path)
    if failpoint_record["triggering_message"] != case_config["failpoint_prefix"] and \
            not failpoint_record["triggering_message"].startswith(case_config["failpoint_prefix"]):
        raise RuntimeError("failpoint record message differs from contract at {0}".format(label))
    return {
        "exit_code": returncode,
        "record": failpoint_record,
        "record_sha256": sha256_file(record_path),
        "log_sha256": sha256_file(log_path),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }


def assert_minimum_checkpoint(root, case_config):
    """Require the named completed checkpoint at the failpoint.

    R1 requires six ``state.<symbol>.<column>.dat`` files plus
    ``fmStarts.<column>.npy`` and ``fmDeltas.<column>.npy``; every matching
    ``inserts.*.<column>.npy`` is retained.  R2 requires the complete backup
    file.  Any extra checkpoint is recorded, never removed.
    """
    files = dict((item["path"], item) for item in inventory(root)["files"])
    column = case_config["partial_checkpoint_column"]
    for name in case_config["partial_minimum_files"]:
        if name not in files:
            raise RuntimeError("partial tree is missing {0}".format(name))
    state_files = sorted(
        item for item in files
        if item.startswith("state.") and item.endswith(".{0}.dat".format(column)))
    if len(state_files) != case_config["partial_minimum_state_files"]:
        raise RuntimeError(
            "partial tree has {0} state files, expected {1}: {2}".format(
                len(state_files), case_config["partial_minimum_state_files"], state_files))
    return {
        "checkpoint_column": column,
        "minimum_files": sorted(case_config["partial_minimum_files"]),
        "state_files": state_files,
        "insert_files": sorted(item for item in files if item.startswith("inserts.")),
        "file_set": sorted(files),
    }


def assert_partial_backup(root, case_config):
    backup = case_config["partial_backup"]
    files = dict((item["path"], item) for item in inventory(root)["files"])
    if backup not in files:
        raise RuntimeError("partial tree is missing complete backup {0}".format(backup))
    if "msbwt.npy" not in files:
        raise RuntimeError("partial tree is missing msbwt.npy beside the backup")
    return {
        "backup": backup,
        "backup_sha256": files[backup]["sha256"],
        "backup_size": files[backup]["size"],
        "file_set": sorted(files),
        "temp_files": sorted(item for item in files if "temp" in item or item.startswith("inter")),
    }


def assert_no_checkpoint_temps(root, checkpoint_patterns):
    forbidden = []
    for item in inventory(root)["files"]:
        name = os.path.basename(item["path"])
        for pattern in checkpoint_patterns:
            if name.startswith(pattern):
                forbidden.append(item["path"])
                break
    if forbidden:
        raise RuntimeError("clean success retained checkpoint/temporary files: {0}".format(forbidden))


def tree_compare(left, right):
    if left == right:
        return {"matches": True}
    left_files = dict((item["path"], item) for item in left["files"])
    right_files = dict((item["path"], item) for item in right["files"])
    left_paths = set(left_files)
    right_paths = set(right_files)
    return {
        "matches": False,
        "added": sorted(right_paths - left_paths),
        "removed": sorted(left_paths - right_paths),
        "changed": sorted(
            item for item in left_paths.intersection(right_paths)
            if left_files[item] != right_files[item]),
    }


def assert_identical_trees(left, right, label):
    comparison = tree_compare(left, right)
    if not comparison["matches"]:
        raise RuntimeError("{0} trees differ: {1}".format(label, comparison))
    return comparison


def r1_case(recorder, built_source, environment_root, operation_root, label, fixture, config):
    """Run one direct uniform RLE checkpoint interrupt/resume/clean family."""
    case_config = config["cases"]["r1"]
    case_root = os.path.join(operation_root, "r1")
    require_new(case_root, "r1 case root")
    os.makedirs(case_root)

    partial = os.path.join(case_root, "r1-partial")
    fixture_paths = [os.path.join(fixture["fixture_root"], item["path"]) for item in fixture["files"]]
    run_required(
        recorder, label + "-r1-preprocess",
        cli_argv("pp", "-u", partial, *fixture_paths), built_source)
    preprocess = inventory(partial)
    if preprocess["tree_sha256"] != config["uniform_preprocess"]["tree_sha256"]:
        raise RuntimeError("r1 preprocessing tree differs from committed uniform preprocessing")

    failpoint = run_failpoint(
        recorder, os.path.join(environment_root, "failpoint_adapter.py"),
        built_source, case_root, label + "-r1-failpoint", "r1", case_config, partial)
    partial_tree = inventory(partial)
    checkpoint = assert_minimum_checkpoint(partial, case_config)

    resume = os.path.join(case_root, "r1-resume")
    copy_tree(partial, resume)
    resume_exit = run_required(
        recorder, label + "-r1-resume",
        cli_argv("cfpp", "-p", "1", "-u", "-c", resume), built_source)
    resume_stdout = read_recorded_stream(
        recorder, recorder.records[-1], "stdout")
    if case_config["resume_log_marker"] not in resume_stdout.decode("utf-8"):
        raise RuntimeError("r1 resume log lacks marker {0!r}".format(
            case_config["resume_log_marker"]))
    assert_no_checkpoint_temps(resume, ("state.", "fmStarts.", "fmDeltas.", "inserts.",
                                        "comp_msbwt.npy.temp."))
    resumed_tree = inventory(resume)
    resumed_primary = rle_primary_record(os.path.join(resume, "comp_msbwt.npy"))

    clean_partial = os.path.join(case_root, "r1-clean-partial")
    run_required(
        recorder, label + "-r1-clean-preprocess",
        cli_argv("pp", "-u", clean_partial, *fixture_paths), built_source)
    clean_preprocess = inventory(clean_partial)
    if clean_preprocess != preprocess:
        raise RuntimeError("r1 clean preprocessing tree differs from partial preprocessing")
    clean_exit = run_required(
        recorder, label + "-r1-clean",
        cli_argv("cfpp", "-p", "1", "-u", "-c", clean_partial), built_source)
    assert_no_checkpoint_temps(clean_partial, ("state.", "fmStarts.", "fmDeltas.", "inserts.",
                                               "comp_msbwt.npy.temp."))
    clean_tree = inventory(clean_partial)
    clean_primary = rle_primary_record(os.path.join(clean_partial, "comp_msbwt.npy"))

    tree_match = assert_identical_trees(resumed_tree, clean_tree, "r1 resumed/clean")
    if resumed_primary != clean_primary:
        raise RuntimeError("r1 resumed comp_msbwt.npy differs from clean control")

    return {
        "preprocess": preprocess,
        "failpoint": failpoint,
        "partial": partial_tree,
        "checkpoint": checkpoint,
        "resume": {"exit_code": resume_exit,
                   "log_marker": case_config["resume_log_marker"],
                   "stdout_sha256": hashlib.sha256(resume_stdout).hexdigest()},
        "resume_dir": resume,
        "clean_dir": clean_partial,
        "resumed_tree": resumed_tree,
        "resumed_primary": resumed_primary,
        "clean_tree": clean_tree,
        "clean_primary": clean_primary,
        "resume_equals_clean_tree": tree_match,
        "resume_equals_clean_primary": resumed_primary == clean_primary,
    }


def r2_case(recorder, built_source, environment_root, operation_root, label, fixture, config):
    """Run one nonuniform multimerge backup interrupt/resume/clean family."""
    case_config = config["cases"]["r2"]
    case_root = os.path.join(operation_root, "r2")
    require_new(case_root, "r2 case root")
    os.makedirs(case_root)

    partial = os.path.join(case_root, "r2-partial")
    fixture_paths = [os.path.join(fixture["fixture_root"], item["path"]) for item in fixture["files"]]
    run_required(
        recorder, label + "-r2-preprocess",
        cli_argv("pp", partial, *fixture_paths), built_source)
    preprocess = inventory(partial)

    failpoint = run_failpoint(
        recorder, os.path.join(environment_root, "failpoint_adapter.py"),
        built_source, case_root, label + "-r2-failpoint", "r2", case_config, partial)
    partial_tree = inventory(partial)
    backup = assert_partial_backup(partial, case_config)

    resume = os.path.join(case_root, "r2-resume")
    copy_tree(partial, resume)
    resume_exit = run_required(
        recorder, label + "-r2-resume",
        cli_argv("cfpp", "-p", "1", resume), built_source)
    resume_stdout = read_recorded_stream(
        recorder, recorder.records[-1], "stdout")
    if case_config["resume_log_marker"] not in resume_stdout.decode("utf-8"):
        raise RuntimeError("r2 resume log lacks marker {0!r}".format(
            case_config["resume_log_marker"]))
    assert_no_checkpoint_temps(resume, ("backup.", "msbwt.temp.", "inter"))
    resumed_tree = inventory(resume)
    resumed_primary = parse_u1_npy(os.path.join(resume, "msbwt.npy"))
    resumed_primary_record = {
        "sha256": resumed_primary["sha256"],
        "size": resumed_primary["size"],
        "dtype": resumed_primary["dtype"],
        "shape": resumed_primary["shape"],
        "shape_literal": resumed_primary["shape_literal"],
        "payload_sha256": resumed_primary["payload_sha256"],
    }

    clean_partial = os.path.join(case_root, "r2-clean-partial")
    run_required(
        recorder, label + "-r2-clean-preprocess",
        cli_argv("pp", clean_partial, *fixture_paths), built_source)
    clean_preprocess = inventory(clean_partial)
    if clean_preprocess != preprocess:
        raise RuntimeError("r2 clean preprocessing tree differs from partial preprocessing")
    clean_exit = run_required(
        recorder, label + "-r2-clean",
        cli_argv("cfpp", "-p", "1", clean_partial), built_source)
    assert_no_checkpoint_temps(clean_partial, ("backup.", "msbwt.temp.", "inter"))
    clean_tree = inventory(clean_partial)
    clean_primary = parse_u1_npy(os.path.join(clean_partial, "msbwt.npy"))
    clean_primary_record = {
        "sha256": clean_primary["sha256"],
        "size": clean_primary["size"],
        "dtype": clean_primary["dtype"],
        "shape": clean_primary["shape"],
        "shape_literal": clean_primary["shape_literal"],
        "payload_sha256": clean_primary["payload_sha256"],
    }

    tree_match = assert_identical_trees(resumed_tree, clean_tree, "r2 resumed/clean")
    if resumed_primary_record != clean_primary_record:
        raise RuntimeError("r2 resumed msbwt.npy differs from clean control")

    return {
        "preprocess": preprocess,
        "failpoint": failpoint,
        "partial": partial_tree,
        "backup": backup,
        "resume": {"exit_code": resume_exit,
                   "log_marker": case_config["resume_log_marker"],
                   "stdout_sha256": hashlib.sha256(resume_stdout).hexdigest()},
        "resume_dir": resume,
        "clean_dir": clean_partial,
        "resumed_tree": resumed_tree,
        "resumed_primary": resumed_primary_record,
        "clean_tree": clean_tree,
        "clean_primary": clean_primary_record,
        "resume_equals_clean_tree": tree_match,
        "resume_equals_clean_primary": resumed_primary_record == clean_primary_record,
    }


def run_reader(recorder, environment_root, built_source, dataset, copy_path,
               fixture_root, case_id, output, label):
    return compression_milestone1.run_reader(
        recorder, environment_root, built_source, dataset, copy_path,
        fixture_root, case_id, output, label)


def reader_evidence(recorder, environment_root, built_source, raw_root, fixture_root, datasets):
    """Run fixture-derived compiled-reader checks on disposable copies.

    ``datasets`` maps a label to ``(dataset_dir, reader_case_id)``.  Every
    dataset is copied before loading so pristine evidence is never mutated.
    """
    root = os.path.join(raw_root, "reader-evidence")
    require_new(root, "reader evidence root")
    os.makedirs(root)
    results = {}
    for label, (dataset, case_id) in sorted(datasets.items()):
        results[label] = run_reader(
            recorder, environment_root, built_source, dataset,
            os.path.join(root, label + "-copy"), fixture_root, case_id,
            os.path.join(root, label + ".json"), "reader-" + label)
    return results


def execute(recorder, built_source, run_dir, fixture_root, golden_root, manifest_path):
    if sys.version_info[:2] != (2, 7) or platform.python_implementation() != "CPython":
        raise RuntimeError("compression recovery milestone requires genuine CPython 2.7")
    config, fixtures = validate_config(manifest_path, golden_root, fixture_root)
    milestone_root = os.path.join(run_dir, "compression-milestone2")
    require_new(milestone_root, "compression recovery milestone result")
    os.makedirs(milestone_root)
    raw_root = os.path.join(milestone_root, "raw")
    os.makedirs(raw_root)
    environment_root = os.path.dirname(os.path.abspath(__file__))
    result = {
        "format": FORMAT, "manifest_sha256": sha256_file(manifest_path),
        "profile_id": config["profile_id"], "route": config["route"],
        "status": "not-run", "cases": {}, "fixture_cases": {},
        "canonical_runs": config["canonical_runs"],
        "failpoint_exit_code": FAILPOINT_EXIT_CODE,
    }
    for case_id in ("r1", "r2"):
        result["cases"][case_id] = {"runs": {}, "partial_determinism": {}, "resume_equals_clean": {}}
    for key, info in sorted(fixtures.items()):
        result["fixture_cases"][key] = {
            "case_id": info["case_id"],
            "files": [item["path"] for item in info["files"]],
        }
    partials = {"r1": {}, "r2": {}}
    try:
        for run_id in config["canonical_runs"]:
            run_root = os.path.join(raw_root, run_id)
            require_new(run_root, "fresh recovery run root")
            os.makedirs(run_root)
            r1 = r1_case(
                recorder, built_source, environment_root, run_root,
                run_id + "-r1", fixtures["uniform"], config)
            result["cases"]["r1"]["runs"][run_id] = r1
            partials["r1"][run_id] = r1["partial"]
            r2 = r2_case(
                recorder, built_source, environment_root, run_root,
                run_id + "-r2", fixtures["nonuniform_recovery"], config)
            result["cases"]["r2"]["runs"][run_id] = r2
            partials["r2"][run_id] = r2["partial"]

        run_a, run_b = config["canonical_runs"]
        for case_id in ("r1", "r2"):
            left = partials[case_id][run_a]
            right = partials[case_id][run_b]
            comparison = tree_compare(left, right)
            result["cases"][case_id]["partial_determinism"] = {
                "runs": [run_a, run_b],
                "matches": comparison["matches"],
                "comparison": comparison,
            }
            if not comparison["matches"]:
                raise RuntimeError("{0} partial manifests differ across canonical runs".format(case_id))
            resumed_a = result["cases"][case_id]["runs"][run_a]["resumed_tree"]
            clean_a = result["cases"][case_id]["runs"][run_a]["clean_tree"]
            resumed_b = result["cases"][case_id]["runs"][run_b]["resumed_tree"]
            clean_b = result["cases"][case_id]["runs"][run_b]["clean_tree"]
            resumed_match = tree_compare(resumed_a, resumed_b)
            clean_match = tree_compare(clean_a, clean_b)
            result["cases"][case_id]["resume_equals_clean"] = {
                "run_a": result["cases"][case_id]["runs"][run_a]["resume_equals_clean_tree"],
                "run_b": result["cases"][case_id]["runs"][run_b]["resume_equals_clean_tree"],
                "resumed_a_equals_resumed_b": resumed_match["matches"],
                "clean_a_equals_clean_b": clean_match["matches"],
            }
            if not resumed_match["matches"] or not clean_match["matches"]:
                raise RuntimeError("{0} resumed/clean results differ across canonical runs".format(case_id))

        datasets = {}
        for case_id in ("r1", "r2"):
            reader_case = config["cases"][case_id]["reader_case"]
            for run_id in config["canonical_runs"]:
                run = result["cases"][case_id]["runs"][run_id]
                datasets["{0}-resumed-{1}".format(case_id, run_id)] = (run["resume_dir"], reader_case)
                datasets["{0}-clean-{1}".format(case_id, run_id)] = (run["clean_dir"], reader_case)
        result["readers"] = reader_evidence(
            recorder, environment_root, built_source, raw_root, fixture_root, datasets)
        for label, reader in sorted(result["readers"].items()):
            if reader["status"] != "passed":
                raise RuntimeError("recovery reader check failed for {0}".format(label))
        result["status"] = "passed"
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = "{0}: {1}".format(exc.__class__.__name__, exc)
        result["traceback"] = traceback.format_exc()
        raise
    finally:
        probe_legacy.write_json(os.path.join(milestone_root, "raw-result.json"), result)
