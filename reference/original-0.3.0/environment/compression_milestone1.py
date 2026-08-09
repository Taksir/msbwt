#!/usr/bin/env python
"""Execute the source-resolved clean RLE characterization under Python 2.7.

This module is called only after ``probe_legacy`` has built and gated a frozen
source copy.  It records raw Linux-ext4 evidence; host-side tooling performs
safe NPY parsing and promotion after every relationship below passes.
"""
from __future__ import print_function

import ast
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import sys
import traceback

import probe_legacy


FORMAT = "msbwt-legacy-compression-milestone1-raw-v1"
DERIVED_INPUT_FILES = set((
    "totalCounts.npy", "fmIndex.npy", "totalCounts.p",
    "comp_fmIndex.npy", "comp_refIndex.npy"
))
# Frozen RLE symbol order: low three bits index this table (0..5).
SYMBOL_ORDER = "$ACGNT"


def _byte_value(value):
    """Return an int for either an int (Python 3 bytes) or a 1-char str (Py2)."""
    if isinstance(value, int):
        return value
    return ord(value)


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


def extract_shape_literal(header_text):
    """Return the raw NumPy shape literal as persisted, preserving ``L`` suffixes.

    Frozen post-hoc compression writes ``(N,)`` while the direct Cython builder
    writes ``(NL,)`` under Python 2.  Both are valid; the difference is a
    compatibility contract, so the raw literal is recorded without normalization.
    """
    marker = "'shape': "
    index = header_text.find(marker)
    if index < 0:
        raise RuntimeError("NumPy header lacks a shape entry: {0!r}".format(header_text))
    index += len(marker)
    depth = 0
    start = index
    for position in range(index, len(header_text)):
        character = header_text[position]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return header_text[start:position + 1]
    raise RuntimeError("NumPy header shape literal is unbalanced: {0!r}".format(header_text))


def parse_u1_npy(path):
    """Inspect a v1 ``|u1`` NPY primary without loading an array.

    Returns the raw header text, raw shape literal, logical shape, dtype, and
    payload bytes/hash.  The raw payload is not retained in JSON records; only
    its hash and decoded products are persisted.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    sha256 = hashlib.sha256(data).hexdigest()
    if data[:6] != b"\x93NUMPY":
        raise RuntimeError("RLE primary is not a NumPy NPY file: {0}".format(path))
    major = ord(data[6:7])
    minor = ord(data[7:8])
    if major != 1:
        raise RuntimeError("RLE primary is not NPY v1: {0} (version {1}.{2})".format(path, major, minor))
    header_length = struct.unpack("<H", data[8:10])[0]
    raw_header = data[10:10 + header_length]
    if len(raw_header) != header_length:
        raise RuntimeError("RLE primary NPY header is truncated: {0}".format(path))
    payload = data[10 + header_length:]
    header_text = raw_header.decode("latin-1")
    shape_literal = extract_shape_literal(header_text)
    normalized = re.sub(r"(?<=[0-9])[Ll]", "", shape_literal)
    try:
        shape = list(ast.literal_eval(normalized))
    except (ValueError, SyntaxError):
        raise RuntimeError("cannot parse NumPy shape literal: {0!r}".format(shape_literal))
    dtype_match = re.search(r"'descr':\s*'([^']*)'", header_text)
    if dtype_match is None:
        raise RuntimeError("NumPy header lacks a dtype descriptor: {0!r}".format(header_text))
    dtype = dtype_match.group(1)
    if dtype != "|u1":
        raise RuntimeError("RLE primary dtype is not |u1: {0!r} ({1})".format(dtype, path))
    expected_payload_size = 1
    for dimension in shape:
        expected_payload_size *= dimension
    if len(payload) != expected_payload_size:
        raise RuntimeError(
            "RLE primary |u1 payload size {0} is inconsistent with shape {1} ({2})".format(
                len(payload), shape, path))
    return {
        "sha256": sha256,
        "size": len(data),
        "version": [major, minor],
        "header_length": header_length,
        "header_text": header_text.rstrip("\n"),
        "shape_literal": shape_literal,
        "dtype": dtype,
        "shape": shape,
        "payload_size": len(payload),
        "payload": payload,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }


def decode_rle_payload(payload):
    """Independently decode a frozen RLE payload without using the legacy reader.

    Low three bits index ``SYMBOL_ORDER`` (``$ACGNT``); the upper five bits of
    consecutive same-symbol bytes are little-endian base-32 run-length digits.
    The committed uncompressed ``msbwt.npy`` stores the BWT as numeric symbol
    indices (0..5), so ``decoded_bytes`` carries those indices and
    ``decoded_sha256`` is computed over them.  ``decoded_symbols`` is the ASCII
    rendering for human-readable records.  This is the safe-decoding gate
    required by the plan and does not load or trust any NumPy array.
    """
    runs = []
    decoded_bytes = bytearray()
    decoded_symbols = bytearray()
    position = 0
    index = 0
    length = len(payload)
    while index < length:
        symbol_index = _byte_value(payload[index]) & 0x07
        if symbol_index >= len(SYMBOL_ORDER):
            raise RuntimeError("RLE payload encodes an unknown symbol index: {0}".format(symbol_index))
        count = 0
        offset = 0
        digit_values = []
        while (index + offset) < length and (_byte_value(payload[index + offset]) & 0x07) == symbol_index:
            digit = (_byte_value(payload[index + offset]) >> 3) & 0x1F
            digit_values.append(digit)
            count += digit * (32 ** offset)
            offset += 1
        if count <= 0:
            raise RuntimeError("RLE payload encodes a non-positive run length: {0}".format(count))
        symbol = SYMBOL_ORDER[symbol_index]
        start = position
        end = position + count
        runs.append({
            "symbol_index": symbol_index,
            "symbol": symbol,
            "count": count,
            "start": start,
            "end": end,
            "digits": offset,
            "digit_values": digit_values
        })
        decoded_bytes.extend(bytearray([symbol_index]) * count)
        decoded_symbols += symbol.encode("ascii") * count
        position = end
        index += offset
    return {
        "runs": runs,
        "run_count": len(runs),
        "decoded_bytes": bytes(decoded_bytes),
        "decoded_sha256": hashlib.sha256(bytes(decoded_bytes)).hexdigest(),
        "decoded_length": len(decoded_bytes),
        "decoded_symbols": decoded_symbols.decode("ascii"),
    }


def runs_from_byte_bwt(bwt_bytes):
    """Group a committed uncompressed BWT (numeric symbol indices) into runs.

    This is an independent cross-check: the RLE-decoded run structure must match
    the run structure of the authoritative uncompressed ``msbwt.npy`` payload.
    """
    runs = []
    position = 0
    index = 0
    length = len(bwt_bytes)
    while index < length:
        symbol_index = _byte_value(bwt_bytes[index])
        offset = 0
        while (index + offset) < length and _byte_value(bwt_bytes[index + offset]) == symbol_index:
            offset += 1
        count = offset
        symbol = SYMBOL_ORDER[symbol_index] if symbol_index < len(SYMBOL_ORDER) else "?"
        runs.append({
            "symbol_index": symbol_index,
            "symbol": symbol,
            "count": count,
            "start": position,
            "end": position + count,
            "digits": 0
        })
        position += count
        index += count
    return runs


def rle_primary_record(path):
    """Build a JSON-safe primary record including the safe-decoded RLE report."""
    parsed = parse_u1_npy(path)
    decoded = decode_rle_payload(parsed.pop("payload"))
    record = {
        "sha256": parsed["sha256"],
        "size": parsed["size"],
        "dtype": parsed["dtype"],
        "shape": parsed["shape"],
        "shape_literal": parsed["shape_literal"],
        "payload_sha256": parsed["payload_sha256"],
        "payload_size": parsed["payload_size"],
        "header_text": parsed["header_text"],
        "header_length": parsed["header_length"],
        "version": parsed["version"],
    }
    record["runs"] = decoded["runs"]
    record["run_count"] = decoded["run_count"]
    record["decoded_length"] = decoded["decoded_length"]
    record["decoded_sha256"] = decoded["decoded_sha256"]
    record["decoded_bwt"] = decoded["decoded_symbols"]
    record.pop("decoded_bytes", None)
    return record


def validate_config(path, golden_root, fixture_root):
    config = read_json(path)
    if config.get("format") != "msbwt-legacy-compression-milestone1-cases-v1":
        raise RuntimeError("unexpected compression case manifest format")
    if config.get("profile_id") != "py27-late-05a7d6d83862":
        raise RuntimeError("compression case manifest profile differs from verified profile")
    if config.get("route") != "pyx-historical-cython":
        raise RuntimeError("compression case manifest route differs from verified route")
    starts = {}
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
        starts[key] = source
    fixtures = {
        "uniform": probe_legacy.validate_golden_case(
            fixture_root, config["fixture_cases"]["uniform"]),
        "nonuniform": probe_legacy.validate_golden_case(
            fixture_root, config["fixture_cases"]["nonuniform"])
    }
    route_contract = config.get("successful_route_contract")
    if route_contract is None or route_contract.get("routes") is None:
        raise RuntimeError("compression case manifest lacks successful_route_contract")
    byte_primaries = {}
    for case_key, start_key in (("uniform", "uniform_build"), ("nonuniform", "nonuniform_build")):
        primary_path = os.path.join(starts[start_key], "msbwt.npy")
        parsed = parse_u1_npy(primary_path)
        byte_runs = runs_from_byte_bwt(parsed["payload"])
        byte_primaries[case_key] = {
            "sha256": parsed["sha256"],
            "payload_sha256": parsed["payload_sha256"],
            "decoded_sha256": parsed["payload_sha256"],
            "decoded_length": parsed["payload_size"],
            "runs": byte_runs,
            "shape": parsed["shape"],
            "shape_literal": parsed["shape_literal"],
        }
    return config, starts, fixtures, route_contract, byte_primaries


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


def read_recorded_stream(recorder, record, field):
    path = os.path.join(recorder.output_dir, record[field])
    with open(path, "rb") as handle:
        return handle.read()


def assert_u1_npy_bytes(path, expected_shape, expected_sha256, expected_payload_sha256):
    """Inspect a v1 NPY header/payload as bytes without loading the array."""
    with open(path, "rb") as handle:
        data = handle.read()
    if sha256_file(path) != expected_sha256:
        raise RuntimeError("preallocated destination whole-file hash differs")
    if data[:8] != b"\x93NUMPY\x01\x00":
        raise RuntimeError("preallocated destination is not an NPY v1 file")
    header_length = struct.unpack("<H", data[8:10])[0]
    header = data[10:10 + header_length]
    payload = data[10 + header_length:]
    shape_text = "'shape': ({0},)".format(expected_shape[0]).encode("ascii")
    if b"'descr': '|u1'" not in header or shape_text not in header:
        raise RuntimeError("preallocated destination metadata differs")
    if len(payload) != expected_shape[0] or payload != b"\x00" * expected_shape[0]:
        raise RuntimeError("preallocated destination is not the expected all-zero payload")
    if hashlib.sha256(payload).hexdigest() != expected_payload_sha256:
        raise RuntimeError("preallocated destination payload hash differs")
    return {
        "dtype": "|u1", "shape": expected_shape, "payload_size": len(payload),
        "payload_sha256": expected_payload_sha256,
        "sha256": expected_sha256, "size": len(data)
    }


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
    primary = rle_primary_record(os.path.join(destination, "comp_msbwt.npy"))
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


def decompress_expected_failure_case(recorder, built_source, operation_root, label,
                                     compressed_source, contract, case_contract):
    source = os.path.join(operation_root, "source")
    destination = os.path.join(operation_root, "destination")
    copy_tree(compressed_source, source)
    before = inventory(source)
    before_paths = [item["path"] for item in before["files"]]
    if before_paths != ["comp_msbwt.npy"]:
        raise RuntimeError("decompression source copy is not pristine: {0}".format(before_paths))
    if before["files"][0]["sha256"] != case_contract["compressed_sha256"]:
        raise RuntimeError("decompression compressed input hash differs")
    argv = cli_argv("decompress", "-p", "1", source, destination)
    returncode = recorder.run(label, argv, cwd=built_source)
    record = recorder.records[-1]
    stderr = read_recorded_stream(recorder, record, "stderr")
    if returncode != contract["exit_code"]:
        raise RuntimeError("expected decompression exit {0}, got {1}".format(
            contract["exit_code"], returncode))
    if hashlib.sha256(stderr).hexdigest() != contract["stderr_sha256"]:
        raise RuntimeError("decompression stderr hash differs from frozen contract")
    stderr_text = stderr.decode("utf-8")
    if stderr_text.rstrip().split("\n")[-1] != contract["exception"]:
        raise RuntimeError("decompression final exception differs from frozen contract")
    for location in contract["traceback_locations"]:
        if location not in stderr_text:
            raise RuntimeError("decompression traceback lacks {0}".format(location))
    after = inventory(source)
    output = inventory(destination)
    before_map = dict((item["path"], item) for item in before["files"])
    after_map = dict((item["path"], item) for item in after["files"])
    if after_map.get("comp_msbwt.npy") != before_map["comp_msbwt.npy"]:
        raise RuntimeError("decompression mutated compressed primary")
    side_effects = sorted(set(after_map) - set(before_map))
    if side_effects != contract["source_side_effects"]:
        raise RuntimeError("decompression source side effects differ: {0}".format(side_effects))
    if [item["path"] for item in output["files"]] != ["msbwt.npy"]:
        raise RuntimeError("decompression destination file set differs")
    primary = assert_u1_npy_bytes(
        os.path.join(destination, "msbwt.npy"), case_contract["output_shape"],
        case_contract["output_sha256"], case_contract["output_payload_sha256"])
    return {
        "status": "expected-failure",
        "argv": ["decompress", "-p", "1", "SOURCE_COPY", "DESTINATION"],
        "exit_code": returncode,
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "exception": contract["exception"],
        "source_before": before,
        "source_after": after,
        "source_side_effects": side_effects,
        "expected_source_manifest_content_sha256": case_contract["source_manifest_content_sha256"],
        "destination": output,
        "expected_destination_manifest_content_sha256": case_contract["destination_manifest_content_sha256"],
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
    primary = rle_primary_record(os.path.join(destination, "comp_msbwt.npy"))
    return {
        "argv": [
            ["pp", "-u", "DESTINATION", "uniform-a.fastq", "uniform-b.fastq"],
            ["cfpp", "-p", str(processes), "-u", "-c", "DESTINATION"]
        ],
        "preprocess": pre,
        "destination": output,
        "primary": primary,
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
    primary = rle_primary_record(os.path.join(destination, "comp_msbwt.npy"))
    return {
        "argv": ["cffq", "-p", str(processes), "-u", "-c", "DESTINATION",
                 "uniform-a.fastq", "uniform-b.fastq"],
        "destination": output,
        "primary": primary,
        "about": file_record(os.path.join(destination, "about.npy"))
    }


def run_group(recorder, built_source, raw_root, run_id, processes, starts, fixtures,
              decompression_contract=None):
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

    if decompression_contract is not None:
        for case_name, operation_name, compressed_root in (
                ("uniform", "uniform-decompress", uniform_compress_root),
                ("nonuniform", "nonuniform-decompress", nonuniform_compress_root)):
            failure_root = os.path.join(group_root, operation_name)
            os.makedirs(failure_root)
            result["operations"][operation_name] = decompress_expected_failure_case(
                recorder, built_source, failure_root,
                run_id + "-decompress-" + case_name,
                os.path.join(compressed_root, "destination"),
                decompression_contract, decompression_contract["cases"][case_name])

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


def run_signature(runs):
    """Semantic run boundary/sequence view, ignoring RLE byte-digit encoding."""
    return [[run["symbol"], run["count"], run["start"], run["end"]] for run in runs]


def assert_group_relationships(group, route_contract, byte_primaries):
    """Gate one run group under the resolved post-hoc/direct compatibility policy.

    Whole-file equality is required only within the same route and between the
    direct split and wrapper.  Post-hoc and direct whole files are permitted to
    differ by the documented NumPy shape literal (``(N,)`` versus ``(NL,)``).
    Across the uniform routes the RLE payload, run sequence, decoded length, and
    decoded BWT must be identical, and the decoded BWT must equal the committed
    uncompressed byte primary.  The nonuniform post-hoc decoded BWT must equal
    its committed nonuniform byte primary.
    """
    operations = group["operations"]
    routes = route_contract["routes"]
    for name in ("uniform-posthoc", "uniform-direct-split",
                 "uniform-direct-wrapper", "nonuniform-posthoc"):
        primary = operations[name]["primary"]
        expected = routes[name]
        if primary["sha256"] != expected["whole_sha256"]:
            raise RuntimeError("route {0} whole-file primary differs: {1} != {2}".format(
                name, primary["sha256"], expected["whole_sha256"]))
        if primary["shape_literal"] != expected["shape_literal"]:
            raise RuntimeError("route {0} shape literal differs: {1!r} != {2!r}".format(
                name, primary["shape_literal"], expected["shape_literal"]))
        if primary["decoded_sha256"] != expected["decoded_bwt_sha256"]:
            raise RuntimeError("route {0} decoded BWT hash differs from contract".format(name))
        if primary["decoded_length"] != expected["decoded_length"]:
            raise RuntimeError("route {0} decoded length differs from contract".format(name))
    split = operations["uniform-direct-split"]["primary"]
    wrapper = operations["uniform-direct-wrapper"]["primary"]
    if split["sha256"] != wrapper["sha256"] or split["shape_literal"] != wrapper["shape_literal"]:
        raise RuntimeError("direct split/wrapper whole-file RLE primary differs")
    if operations["uniform-direct-split"]["about"] != operations["uniform-direct-wrapper"]["about"]:
        raise RuntimeError("uniform split/wrapper about.npy differs")
    reference = operations["uniform-posthoc"]["primary"]
    reference_signature = run_signature(reference["runs"])
    for name in ("uniform-direct-split", "uniform-direct-wrapper"):
        primary = operations[name]["primary"]
        if primary["shape"] != reference["shape"]:
            raise RuntimeError("uniform cross-route logical shape differs for {0}".format(name))
        if primary["payload_sha256"] != reference["payload_sha256"]:
            raise RuntimeError("uniform cross-route RLE payload differs for {0}".format(name))
        if run_signature(primary["runs"]) != reference_signature:
            raise RuntimeError("uniform cross-route run sequence differs for {0}".format(name))
        if primary["decoded_sha256"] != reference["decoded_sha256"] or \
                primary["decoded_length"] != reference["decoded_length"]:
            raise RuntimeError("uniform cross-route decoded BWT differs for {0}".format(name))
    if reference["payload_sha256"] != route_contract["uniform_payload_sha256"]:
        raise RuntimeError("uniform RLE payload sha differs from contract")
    if reference["shape"] != route_contract["uniform_logical_shape"]:
        raise RuntimeError("uniform logical shape differs from contract")
    if reference["decoded_sha256"] != byte_primaries["uniform"]["decoded_sha256"]:
        raise RuntimeError("uniform decoded BWT differs from committed byte primary")
    if reference_signature != run_signature(byte_primaries["uniform"]["runs"]):
        raise RuntimeError("uniform decoded runs differ from committed byte primary")
    if reference["decoded_length"] != byte_primaries["uniform"]["decoded_length"]:
        raise RuntimeError("uniform decoded length differs from committed byte primary")
    if reference["decoded_bwt"] != route_contract["uniform_decoded_bwt"]:
        raise RuntimeError("uniform decoded BWT symbols differ from contract")
    nonuniform = operations["nonuniform-posthoc"]["primary"]
    if nonuniform["decoded_sha256"] != byte_primaries["nonuniform"]["decoded_sha256"]:
        raise RuntimeError("nonuniform decoded BWT differs from committed byte primary")
    if run_signature(nonuniform["runs"]) != run_signature(byte_primaries["nonuniform"]["runs"]):
        raise RuntimeError("nonuniform decoded runs differ from committed byte primary")
    if nonuniform["decoded_length"] != byte_primaries["nonuniform"]["decoded_length"]:
        raise RuntimeError("nonuniform decoded length differs from committed byte primary")
    if nonuniform["shape"] != route_contract["nonuniform_logical_shape"]:
        raise RuntimeError("nonuniform logical shape differs from contract")


def assert_determinism(canonical_a, canonical_b, process_two):
    for operation in sorted(canonical_a["operations"]):
        left = canonical_a["operations"][operation]
        right = canonical_b["operations"][operation]
        for field in ("source_before", "source_after", "destination", "preprocess"):
            if field in left and left[field] != right.get(field):
                raise RuntimeError("canonical retained trees differ for {0} {1}".format(operation, field))
        if left["primary"] != right["primary"]:
            raise RuntimeError("canonical primary differs for {0}".format(operation))
        if operation in process_two["operations"] and \
                left["primary"] != process_two["operations"][operation]["primary"]:
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
        "uniform-direct-wrapper-rle": ("run-a/uniform-direct-wrapper/destination", config["fixture_cases"]["uniform"])
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
    config, starts, fixtures, route_contract, byte_primaries = validate_config(
        manifest_path, golden_root, fixture_root)
    milestone_root = os.path.join(run_dir, "compression-milestone1")
    require_new(milestone_root, "compression milestone result")
    os.makedirs(milestone_root)
    raw_root = os.path.join(milestone_root, "raw")
    os.makedirs(raw_root)
    result = {
        "format": FORMAT, "manifest_sha256": sha256_file(manifest_path),
        "profile_id": config["profile_id"], "route": config["route"],
        "status": "not-run", "groups": {}, "starting_artifacts": {},
        "case_order": config["successful_case_order"],
        "expected_failure_order": config["expected_failure_order"],
        "route_contract": route_contract
    }
    for key, path in sorted(starts.items()):
        result["starting_artifacts"][key] = inventory(path)
    result["byte_primaries"] = byte_primaries
    try:
        for run_id in config["canonical_runs"]:
            group = run_group(
                recorder, built_source, raw_root, run_id,
                config["canonical_processes"], starts, fixtures,
                config["decompression_expected_failure"])
            assert_group_relationships(group, route_contract, byte_primaries)
            result["groups"][run_id] = group
        process_group = run_group(
            recorder, built_source, raw_root, "run-p2",
            config["comparison_processes"], starts, fixtures)
        assert_group_relationships(process_group, route_contract, byte_primaries)
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
