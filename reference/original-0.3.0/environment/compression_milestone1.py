#!/usr/bin/env python
"""Execute the source-resolved clean RLE characterization under Python 2.7.

This module is called only after ``probe_legacy`` has built and gated a frozen
source copy.  It records raw Linux-ext4 evidence; host-side tooling performs
safe NPY parsing and promotion after every relationship below passes.
"""
from __future__ import print_function

import hashlib
import json
import os
import platform
import shutil
import sys
import traceback

import probe_legacy


FORMAT = "msbwt-legacy-compression-milestone1-raw-v1"
DERIVED_INPUT_FILES = set((
    "totalCounts.npy", "fmIndex.npy", "totalCounts.p",
    "comp_fmIndex.npy", "comp_refIndex.npy"
))


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
    result = []
    if not os.path.isdir(root) or os.path.islink(root):
        raise RuntimeError("artifact tree is not an ordinary directory: {0}".format(root))
    for current, directories, filenames in os.walk(root):
        directories.sort()
        filenames.sort()
        for directory in directories:
            if os.path.islink(os.path.join(current, directory)):
                raise RuntimeError("artifact tree contains a symlink directory")
        for filename in filenames:
            path = os.path.join(current, filename)
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeError("artifact tree contains a non-regular file")
            result.append({
                "path": os.path.relpath(path, root).replace(os.sep, "/"),
                "sha256": sha256_file(path),
                "size": os.path.getsize(path)
            })
    return {
        "files": result,
        "tree_sha256": probe_legacy.oracle_tree_sha256(root)
    }


def require_new(path, label):
    if os.path.lexists(path):
        raise RuntimeError("{0} already exists: {1}".format(label, path))


def copy_tree(source, destination):
    require_new(destination, "copy destination")
    shutil.copytree(source, destination)
    if probe_legacy.oracle_tree_sha256(source) != probe_legacy.oracle_tree_sha256(destination):
        raise RuntimeError("tree changed while copying {0}".format(source))


def assert_no_derived_input_files(root):
    paths = set(item["path"] for item in inventory(root)["files"])
    unexpected = sorted(paths.intersection(DERIVED_INPUT_FILES))
    if unexpected:
        raise RuntimeError("starting artifact contains derived reader files: {0}".format(unexpected))


def validate_config(path, golden_root, fixture_root):
    config = read_json(path)
    if config.get("format") != "msbwt-legacy-compression-milestone1-cases-v1":
        raise RuntimeError("unexpected compression case manifest format")
    if config.get("profile_id") != "py27-late-05a7d6d83862":
        raise RuntimeError("compression case manifest profile differs from verified profile")
    if config.get("route") != "pyx-historical-cython":
        raise RuntimeError("compression case manifest route differs from verified route")
    resolved = {}
    for key, value in sorted(config["starting_artifacts"].items()):
        source = os.path.abspath(os.path.join(golden_root, *value["path"].split("/")))
        actual = inventory(source)
        if actual["tree_sha256"] != value["tree_sha256"]:
            raise RuntimeError("starting tree hash mismatch for {0}".format(key))
        if value.get("primary"):
            primary = os.path.join(source, value["primary"])
            if sha256_file(primary) != value["primary_sha256"]:
                raise RuntimeError("starting primary hash mismatch for {0}".format(key))
        assert_no_derived_input_files(source)
        resolved[key] = source
    fixtures = {
        "uniform": probe_legacy.validate_golden_case(
            fixture_root, config["fixture_cases"]["uniform"]),
        "nonuniform": probe_legacy.validate_golden_case(
            fixture_root, config["fixture_cases"]["nonuniform"])
    }
    return config, resolved, fixtures


def cli_argv(*arguments):
    return [sys.executable, "-c", probe_legacy.CLI_MAIN] + list(arguments)


def run_required(recorder, label, argv, cwd):
    returncode = recorder.run(label, argv, cwd=cwd)
    if returncode != 0:
        raise RuntimeError("required command failed at {0} with exit {1}".format(label, returncode))
    return returncode


def file_record(path):
    if not os.path.isfile(path):
        raise RuntimeError("required primary is missing: {0}".format(path))
    return {"sha256": sha256_file(path), "size": os.path.getsize(path)}


def assert_no_success_temps(root):
    forbidden = []
    for item in inventory(root)["files"]:
        name = os.path.basename(item["path"])
        if (name.startswith("comp_msbwt.npy.temp.") or name.startswith("state.") or
                name.startswith("fmStarts.") or name.startswith("fmDeltas.") or
                name.startswith("inserts.")):
            forbidden.append(item["path"])
    if forbidden:
        raise RuntimeError("clean success retained temporary/checkpoint files: {0}".format(forbidden))


def compress_case(recorder, built_source, operation_root, label, source_artifacts, processes):
    source = os.path.join(operation_root, "source")
    destination = os.path.join(operation_root, "destination")
    copy_tree(source_artifacts, source)
    before = inventory(source)
    run_required(
        recorder, label,
        cli_argv("compress", "-p", str(processes), source, destination), built_source)
    after = inventory(source)
    output = inventory(destination)
    primary = file_record(os.path.join(destination, "comp_msbwt.npy"))
    assert_no_success_temps(destination)
    if before != after:
        raise RuntimeError("post-hoc compression mutated its byte source")
    return {
        "argv": ["compress", "-p", str(processes), "SOURCE", "DESTINATION"],
        "source_before": before,
        "source_after": after,
        "destination": output,
        "primary": primary
    }


def decompress_case(recorder, built_source, operation_root, label, compressed_source, processes):
    source = os.path.join(operation_root, "source")
    destination = os.path.join(operation_root, "destination")
    copy_tree(compressed_source, source)
    before = inventory(source)
    run_required(
        recorder, label,
        cli_argv("decompress", "-p", str(processes), source, destination), built_source)
    after = inventory(source)
    output = inventory(destination)
    primary = file_record(os.path.join(destination, "msbwt.npy"))
    return {
        "argv": ["decompress", "-p", str(processes), "SOURCE_COPY", "DESTINATION"],
        "source_before": before,
        "source_after": after,
        "source_side_effects": sorted(
            set(item["path"] for item in after["files"]) -
            set(item["path"] for item in before["files"])),
        "destination": output,
        "primary": primary
    }


def direct_split_case(recorder, built_source, operation_root, label, fixture, processes):
    destination = os.path.join(operation_root, "destination")
    fixture_paths = [os.path.join(fixture["fixture_root"], item["path"]) for item in fixture["files"]]
    run_required(
        recorder, label + "-pp",
        cli_argv("pp", "-u", destination, *fixture_paths), built_source)
    pre = inventory(destination)
    run_required(
        recorder, label + "-cfpp",
        cli_argv("cfpp", "-p", str(processes), "-u", "-c", destination), built_source)
    output = inventory(destination)
    assert_no_success_temps(destination)
    return {
        "argv": [
            ["pp", "-u", "DESTINATION", "uniform-a.fastq", "uniform-b.fastq"],
            ["cfpp", "-p", str(processes), "-u", "-c", "DESTINATION"]
        ],
        "preprocess": pre,
        "destination": output,
        "primary": file_record(os.path.join(destination, "comp_msbwt.npy")),
        "about": file_record(os.path.join(destination, "about.npy"))
    }


def direct_wrapper_case(recorder, built_source, operation_root, label, fixture, processes):
    destination = os.path.join(operation_root, "destination")
    fixture_paths = [os.path.join(fixture["fixture_root"], item["path"]) for item in fixture["files"]]
    run_required(
        recorder, label,
        cli_argv("cffq", "-p", str(processes), "-u", "-c", destination, *fixture_paths),
        built_source)
    output = inventory(destination)
    assert_no_success_temps(destination)
    return {
        "argv": ["cffq", "-p", str(processes), "-u", "-c", "DESTINATION",
                 "uniform-a.fastq", "uniform-b.fastq"],
        "destination": output,
        "primary": file_record(os.path.join(destination, "comp_msbwt.npy")),
        "about": file_record(os.path.join(destination, "about.npy"))
    }


def run_group(recorder, built_source, raw_root, run_id, processes, starts, fixtures):
    group_root = os.path.join(raw_root, run_id)
    require_new(group_root, "fresh run group")
    os.makedirs(group_root)
    result = {"processes": processes, "operations": {}}

    uniform_compress_root = os.path.join(group_root, "uniform-posthoc")
    os.makedirs(uniform_compress_root)
    result["operations"]["uniform-posthoc"] = compress_case(
        recorder, built_source, uniform_compress_root,
        run_id + "-compress-uniform", starts["uniform_build"], processes)

    nonuniform_compress_root = os.path.join(group_root, "nonuniform-posthoc")
    os.makedirs(nonuniform_compress_root)
    result["operations"]["nonuniform-posthoc"] = compress_case(
        recorder, built_source, nonuniform_compress_root,
        run_id + "-compress-nonuniform", starts["nonuniform_build"], processes)

    uniform_roundtrip_root = os.path.join(group_root, "uniform-roundtrip")
    os.makedirs(uniform_roundtrip_root)
    result["operations"]["uniform-roundtrip"] = decompress_case(
        recorder, built_source, uniform_roundtrip_root,
        run_id + "-decompress-uniform",
        os.path.join(uniform_compress_root, "destination"), processes)

    nonuniform_roundtrip_root = os.path.join(group_root, "nonuniform-roundtrip")
    os.makedirs(nonuniform_roundtrip_root)
    result["operations"]["nonuniform-roundtrip"] = decompress_case(
        recorder, built_source, nonuniform_roundtrip_root,
        run_id + "-decompress-nonuniform",
        os.path.join(nonuniform_compress_root, "destination"), processes)

    split_root = os.path.join(group_root, "uniform-direct-split")
    os.makedirs(split_root)
    result["operations"]["uniform-direct-split"] = direct_split_case(
        recorder, built_source, split_root, run_id + "-direct-split",
        fixtures["uniform"], processes)

    wrapper_root = os.path.join(group_root, "uniform-direct-wrapper")
    os.makedirs(wrapper_root)
    result["operations"]["uniform-direct-wrapper"] = direct_wrapper_case(
        recorder, built_source, wrapper_root, run_id + "-direct-wrapper",
        fixtures["uniform"], processes)
    return result


def assert_group_relationships(group, starts):
    operations = group["operations"]
    if operations["uniform-roundtrip"]["primary"]["sha256"] != \
            sha256_file(os.path.join(starts["uniform_build"], "msbwt.npy")):
        raise RuntimeError("uniform decompress(compress(msbwt)) differs byte-for-byte")
    if operations["nonuniform-roundtrip"]["primary"]["sha256"] != \
            sha256_file(os.path.join(starts["nonuniform_build"], "msbwt.npy")):
        raise RuntimeError("nonuniform decompress(compress(msbwt)) differs byte-for-byte")
    uniform_hashes = set(operations[name]["primary"]["sha256"] for name in (
        "uniform-posthoc", "uniform-direct-split", "uniform-direct-wrapper"))
    if len(uniform_hashes) != 1:
        raise RuntimeError("uniform post-hoc/split/wrapper RLE primaries differ")
    if operations["uniform-direct-split"]["about"] != operations["uniform-direct-wrapper"]["about"]:
        raise RuntimeError("uniform split/wrapper about.npy differs")


def assert_determinism(canonical_a, canonical_b, process_two):
    for operation in sorted(canonical_a["operations"]):
        left = canonical_a["operations"][operation]
        right = canonical_b["operations"][operation]
        for field in ("source_before", "source_after", "destination", "preprocess"):
            if field in left and left[field] != right.get(field):
                raise RuntimeError("canonical retained trees differ for {0} {1}".format(operation, field))
        if left["primary"] != right["primary"]:
            raise RuntimeError("canonical primary differs for {0}".format(operation))
        if left["primary"] != process_two["operations"][operation]["primary"]:
            raise RuntimeError("process-count primary differs for {0}".format(operation))


def unsupported_cases(recorder, built_source, raw_root, starts, fixtures):
    root = os.path.join(raw_root, "unsupported")
    require_new(root, "unsupported evidence root")
    os.makedirs(root)
    result = {}

    cfpp_root = os.path.join(root, "nonuniform-cfpp")
    os.makedirs(cfpp_root)
    cfpp_dataset = os.path.join(cfpp_root, "dataset")
    copy_tree(starts["nonuniform_pre"], cfpp_dataset)
    before = inventory(cfpp_dataset)
    cfpp_exit = recorder.run(
        "unsupported-nonuniform-cfpp",
        cli_argv("cfpp", "-p", "1", "-c", cfpp_dataset), cwd=built_source)
    after = inventory(cfpp_dataset)
    result["nonuniform-cfpp"] = {
        "argv": ["cfpp", "-p", "1", "-c", "N_PREPROCESSED_COPY"],
        "exit_code": cfpp_exit, "before": before, "after": after,
        "comp_msbwt_exists": os.path.exists(os.path.join(cfpp_dataset, "comp_msbwt.npy"))
    }

    cffq_root = os.path.join(root, "nonuniform-cffq")
    os.makedirs(cffq_root)
    cffq_dataset = os.path.join(cffq_root, "dataset")
    fixture_paths = [os.path.join(fixtures["nonuniform"]["fixture_root"], item["path"])
                     for item in fixtures["nonuniform"]["files"]]
    cffq_exit = recorder.run(
        "unsupported-nonuniform-cffq",
        cli_argv("cffq", "-p", "1", "-c", cffq_dataset, *fixture_paths), cwd=built_source)
    result["nonuniform-cffq"] = {
        "argv": ["cffq", "-p", "1", "-c", "N_UNSUPPORTED", "nonuniform.fastq"],
        "exit_code": cffq_exit,
        "after": inventory(cffq_dataset),
        "comp_msbwt_exists": os.path.exists(os.path.join(cffq_dataset, "comp_msbwt.npy"))
    }
    for name, evidence in result.items():
        if evidence["exit_code"] != 0 or evidence["comp_msbwt_exists"]:
            raise RuntimeError("unsupported nonuniform behavior conflicts with plan: {0}".format(name))
    return result


def run_reader(recorder, environment_root, built_source, dataset, copy_path,
               fixture_root, case_id, output, label, coexistence_primary=None):
    argv = [
        sys.executable, os.path.join(environment_root, "reader_smoke.py"),
        "--source", built_source, "--dataset", dataset, "--copy", copy_path,
        "--fixture-root", fixture_root, "--case", case_id, "--output", output
    ]
    if coexistence_primary:
        argv.extend(["--coexistence-compressed-primary", coexistence_primary])
    run_required(recorder, label, argv, built_source)
    return read_json(output)


def reader_evidence(recorder, environment_root, built_source, raw_root, fixture_root, config):
    root = os.path.join(raw_root, "reader-evidence")
    require_new(root, "reader evidence root")
    os.makedirs(root)
    datasets = {
        "uniform-posthoc-rle": ("run-a/uniform-posthoc/destination", config["fixture_cases"]["uniform"]),
        "nonuniform-posthoc-rle": ("run-a/nonuniform-posthoc/destination", config["fixture_cases"]["nonuniform"]),
        "uniform-direct-split-rle": ("run-a/uniform-direct-split/destination", config["fixture_cases"]["uniform"]),
        "uniform-direct-wrapper-rle": ("run-a/uniform-direct-wrapper/destination", config["fixture_cases"]["uniform"]),
        "uniform-roundtrip-byte": ("run-a/uniform-roundtrip/destination", config["fixture_cases"]["uniform"]),
        "nonuniform-roundtrip-byte": ("run-a/nonuniform-roundtrip/destination", config["fixture_cases"]["nonuniform"])
    }
    results = {}
    for label, (relative, case_id) in sorted(datasets.items()):
        results[label] = run_reader(
            recorder, environment_root, built_source, os.path.join(raw_root, *relative.split("/")),
            os.path.join(root, label + "-copy"), fixture_root, case_id,
            os.path.join(root, label + ".json"), "reader-" + label)
    results["uniform-coexistence"] = run_reader(
        recorder, environment_root, built_source,
        os.path.join(raw_root, "run-a", "uniform-posthoc", "source"),
        os.path.join(root, "uniform-coexistence-copy"), fixture_root,
        config["fixture_cases"]["uniform"], os.path.join(root, "uniform-coexistence.json"),
        "reader-uniform-coexistence",
        os.path.join(raw_root, "run-a", "uniform-posthoc", "destination", "comp_msbwt.npy"))
    return results


def execute(recorder, built_source, run_dir, fixture_root, golden_root, manifest_path):
    if sys.version_info[:2] != (2, 7) or platform.python_implementation() != "CPython":
        raise RuntimeError("compression milestone requires genuine CPython 2.7")
    config, starts, fixtures = validate_config(manifest_path, golden_root, fixture_root)
    milestone_root = os.path.join(run_dir, "compression-milestone1")
    require_new(milestone_root, "compression milestone result")
    os.makedirs(milestone_root)
    raw_root = os.path.join(milestone_root, "raw")
    os.makedirs(raw_root)
    result = {
        "format": FORMAT, "manifest_sha256": sha256_file(manifest_path),
        "profile_id": config["profile_id"], "route": config["route"],
        "status": "not-run", "groups": {}, "starting_artifacts": {},
        "case_order": config["successful_case_order"]
    }
    for key, path in sorted(starts.items()):
        result["starting_artifacts"][key] = inventory(path)
    try:
        for run_id in config["canonical_runs"]:
            group = run_group(
                recorder, built_source, raw_root, run_id,
                config["canonical_processes"], starts, fixtures)
            assert_group_relationships(group, starts)
            result["groups"][run_id] = group
        process_group = run_group(
            recorder, built_source, raw_root, "run-p2",
            config["comparison_processes"], starts, fixtures)
        assert_group_relationships(process_group, starts)
        result["groups"]["run-p2"] = process_group
        assert_determinism(
            result["groups"][config["canonical_runs"][0]],
            result["groups"][config["canonical_runs"][1]], process_group)
        result["unsupported"] = unsupported_cases(
            recorder, built_source, raw_root, starts, fixtures)
        result["readers"] = reader_evidence(
            recorder, os.path.dirname(os.path.abspath(__file__)), built_source,
            raw_root, fixture_root, config)
        result["status"] = "passed"
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = "{0}: {1}".format(exc.__class__.__name__, exc)
        result["traceback"] = traceback.format_exc()
        raise
    finally:
        probe_legacy.write_json(os.path.join(milestone_root, "raw-result.json"), result)
