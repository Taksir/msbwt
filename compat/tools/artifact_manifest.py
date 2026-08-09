#!/usr/bin/env python3
"""Capture and verify byte-level artifacts from a frozen legacy run.

This is deliberately a host-side Python 3 utility.  It never imports NumPy or
the legacy package, and it never deserializes an ``.npy`` payload.  Its only
job is to record bytes and the small, non-executable ``.npy`` header format so
that a legacy run can be compared before any implementation is modernized.
"""

from __future__ import annotations

import argparse
import ast
import base64
import datetime as _datetime
import hashlib
import io
import json
import locale
import os
import platform
import subprocess
import sys
import time
import tokenize
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


FORMAT_NAME = "msbwt-legacy-artifact-manifest-v1"
TOOL_NAME = "compat.tools.artifact_manifest"
MAX_NPY_HEADER_BYTES = 16 * 1024 * 1024


class ManifestError(Exception):
    """Raised when an input cannot be represented as a safe manifest."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable JSON bytes suitable for hashing and checked-in files."""

    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    """Convert literal-eval results to JSON values without changing meaning."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    raise ManifestError("unsupported scalar in .npy header: {!r}".format(value))


def _normalize_python2_long_literals(header_text: str) -> str:
    """Make Python-2 ``123L`` integer literals acceptable to ``literal_eval``.

    NumPy 1.16 on Python 2 writes shapes such as ``(48L,)``.  Python 3's
    tokenizer exposes the legacy suffix as a separate adjacent ``NAME`` token;
    remove only that exact token pair.  Strings and all other header bytes are
    left alone.  This normalized value is ephemeral: manifests retain the raw
    header text and bytes from the dataset.
    """

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(header_text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise ManifestError("cannot tokenize NumPy header: {}".format(exc))

    normalized = []
    for index, token in enumerate(tokens):
        previous = tokens[index - 1] if index else None
        if (
            token.type == tokenize.NAME
            and token.string in ("L", "l")
            and previous is not None
            and previous.type == tokenize.NUMBER
            and previous.end == token.start
        ):
            continue
        normalized.append(token)
    return tokenize.untokenize(normalized)


def parse_npy_header(path: Path) -> Dict[str, Any]:
    """Read only an ``.npy`` preamble/header; never construct an ndarray."""

    with path.open("rb") as source:
        magic = source.read(6)
        if magic != b"\x93NUMPY":
            raise ManifestError("not a NumPy .npy file")

        version_bytes = source.read(2)
        if len(version_bytes) != 2:
            raise ManifestError("truncated NumPy version")
        major, minor = version_bytes[0], version_bytes[1]
        if major == 1:
            length_bytes = source.read(2)
            length_width = 2
        elif major in (2, 3):
            length_bytes = source.read(4)
            length_width = 4
        else:
            raise ManifestError("unsupported NumPy format version {}.{}".format(major, minor))
        if len(length_bytes) != length_width:
            raise ManifestError("truncated NumPy header length")

        header_length = int.from_bytes(length_bytes, byteorder="little", signed=False)
        if header_length > MAX_NPY_HEADER_BYTES:
            raise ManifestError(
                "NumPy header length {} exceeds safety limit {}".format(
                    header_length, MAX_NPY_HEADER_BYTES
                )
            )
        raw_header = source.read(header_length)
        if len(raw_header) != header_length:
            raise ManifestError("truncated NumPy header")
        payload_offset = 6 + 2 + length_width + header_length

    encoding = "latin-1" if major in (1, 2) else "utf-8"
    try:
        header_text = raw_header.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ManifestError("invalid NumPy header text: {}".format(exc))
    try:
        header_value = ast.literal_eval(_normalize_python2_long_literals(header_text).strip())
    except (MemoryError, RecursionError, ValueError, SyntaxError) as exc:
        raise ManifestError("NumPy header is not a literal dictionary: {}".format(exc))
    if not isinstance(header_value, dict):
        raise ManifestError("NumPy header is not a dictionary")

    required_keys = {"descr", "fortran_order", "shape"}
    missing = sorted(required_keys.difference(header_value))
    if missing:
        raise ManifestError("NumPy header is missing {}".format(", ".join(missing)))
    if not isinstance(header_value["fortran_order"], bool):
        raise ManifestError("NumPy fortran_order is not boolean")
    if not isinstance(header_value["shape"], tuple) or not all(
        isinstance(item, int) and item >= 0 for item in header_value["shape"]
    ):
        raise ManifestError("NumPy shape is not a tuple of non-negative integers")

    file_size = path.stat().st_size
    return {
        "magic_hex": magic.hex(),
        "version": [major, minor],
        "header_length": header_length,
        "header_bytes_hex": raw_header.hex(),
        "header_sha256": sha256_bytes(raw_header),
        "header_text": header_text,
        "dtype_descriptor": _json_safe(header_value["descr"]),
        "fortran_order": header_value["fortran_order"],
        "shape": list(header_value["shape"]),
        "payload_offset": payload_offset,
        "payload_size": file_size - payload_offset,
        "payload_sha256": _sha256_file_segment(path, payload_offset),
    }


def _sha256_file_segment(path: Path, offset: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        source.seek(offset)
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_entries(root: Path) -> Iterable[Tuple[str, Path, str]]:
    """Yield ordinary files and symlinks without following symlink directories."""

    def walk(directory: Path) -> Iterable[Tuple[str, Path, str]]:
        try:
            children = sorted(directory.iterdir(), key=lambda child: child.name)
        except OSError as exc:
            raise ManifestError("cannot list {}: {}".format(directory, exc))
        for child in children:
            relative = _relative_posix(root, child)
            try:
                if child.is_symlink():
                    yield relative, child, "symlink"
                elif child.is_dir():
                    yield from walk(child)
                elif child.is_file():
                    yield relative, child, "file"
                else:
                    yield relative, child, "special"
            except OSError as exc:
                raise ManifestError("cannot inspect {}: {}".format(child, exc))

    yield from walk(root)


def inventory_directory(artifact_dir: os.PathLike[str] | str) -> Dict[str, Any]:
    """Return a deterministic, byte-oriented manifest for ``artifact_dir``."""

    root = Path(artifact_dir).resolve()
    if not root.is_dir():
        raise ManifestError("artifact directory does not exist: {}".format(root))

    artifacts: List[Dict[str, Any]] = []
    for relative, path, entry_type in _iter_entries(root):
        if entry_type == "symlink":
            try:
                target = os.readlink(str(path))
            except OSError as exc:
                raise ManifestError("cannot read symlink {}: {}".format(path, exc))
            artifacts.append({"path": relative, "type": "symlink", "target": target})
            continue
        if entry_type == "special":
            artifacts.append({"path": relative, "type": "special"})
            continue

        entry: Dict[str, Any] = {
            "path": relative,
            "type": "file",
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix.lower() == ".npy":
            try:
                entry["npy"] = parse_npy_header(path)
            except ManifestError as exc:
                # A .npy suffix is not proof of an .npy container.  Preserve the
                # exact file hash and record the parse failure rather than fail an
                # otherwise useful legacy failure artifact.
                entry["npy_error"] = str(exc)
        artifacts.append(entry)

    manifest: Dict[str, Any] = {"format": FORMAT_NAME, "artifacts": artifacts}
    manifest["content_sha256"] = sha256_bytes(canonical_json_bytes(manifest))
    return manifest


def _without_content_hash(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "content_sha256"}


def _verify_manifest_integrity(manifest: Mapping[str, Any]) -> Optional[str]:
    if manifest.get("format") != FORMAT_NAME:
        return "unexpected manifest format: {!r}".format(manifest.get("format"))
    claimed = manifest.get("content_sha256")
    if not isinstance(claimed, str):
        return "manifest lacks content_sha256"
    actual = sha256_bytes(canonical_json_bytes(_without_content_hash(manifest)))
    if claimed != actual:
        return "manifest content_sha256 does not match its canonical content"
    return None


def compare_manifest(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> Dict[str, Any]:
    """Compare manifests and report path-level differences in stable order."""

    expected_error = _verify_manifest_integrity(expected)
    actual_error = _verify_manifest_integrity(actual)
    expected_entries = {item["path"]: item for item in expected.get("artifacts", [])}
    actual_entries = {item["path"]: item for item in actual.get("artifacts", [])}
    expected_paths = set(expected_entries)
    actual_paths = set(actual_entries)
    changed = []
    for path in sorted(expected_paths.intersection(actual_paths)):
        if expected_entries[path] != actual_entries[path]:
            fields = sorted(
                set(expected_entries[path]).union(actual_entries[path])
                - {
                    "path",
                }
            )
            changed.append(
                {
                    "path": path,
                    "fields": [
                        field
                        for field in fields
                        if expected_entries[path].get(field) != actual_entries[path].get(field)
                    ],
                }
            )
    matches = not expected_error and not actual_error and not (
        expected_paths - actual_paths or actual_paths - expected_paths or changed
    )
    return {
        "matches": matches,
        "expected_integrity_error": expected_error,
        "actual_integrity_error": actual_error,
        "expected_content_sha256": expected.get("content_sha256"),
        "actual_content_sha256": actual.get("content_sha256"),
        "added": sorted(actual_paths - expected_paths),
        "removed": sorted(expected_paths - actual_paths),
        "changed": changed,
    }


def write_json(path: os.PathLike[str] | str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json_bytes(value))


def load_json(path: os.PathLike[str] | str) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("cannot load manifest {}: {}".format(path, exc))
    if not isinstance(value, dict):
        raise ManifestError("manifest root is not a JSON object")
    return value


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _require_outside_artifact_tree(output: Path, artifact_dir: Path) -> None:
    if _is_inside(output, artifact_dir):
        raise ManifestError(
            "refusing to write {} inside captured artifact directory {}".format(output, artifact_dir)
        )


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_metadata() -> Dict[str, Any]:
    return {
        "tool": TOOL_NAME,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "locale": locale.setlocale(locale.LC_ALL, None),
    }


def _parse_assignments(assignments: Sequence[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ManifestError("--env requires NAME=VALUE: {!r}".format(assignment))
        name, value = assignment.split("=", 1)
        if not name or "=" in name or "\x00" in name:
            raise ManifestError("invalid environment variable name: {!r}".format(name))
        parsed[name] = value
    return parsed


def capture_command(
    argv: Sequence[str],
    cwd: os.PathLike[str] | str,
    artifact_dir: os.PathLike[str] | str,
    *,
    env_assignments: Optional[Mapping[str, str]] = None,
    record_environment: Sequence[str] = (),
) -> Tuple[Dict[str, Any], int]:
    """Run a command without a shell and return a complete, binary-safe record.

    The returned integer is the child exit status.  A failed child is therefore
    a successful *capture* with a non-zero return value and a fully populated
    record.  Launch failures use 127 and include ``execution_error``.
    """

    if not argv:
        raise ManifestError("capture command is empty")
    run_cwd = Path(cwd).resolve()
    run_artifact_dir = Path(artifact_dir).resolve()
    if not run_cwd.is_dir():
        raise ManifestError("command working directory does not exist: {}".format(run_cwd))

    command_env = os.environ.copy()
    additions = dict(env_assignments or {})
    command_env.update(additions)
    selected_environment = {
        name: command_env.get(name) for name in sorted(set(record_environment).union(additions))
    }
    started = _utc_now()
    started_monotonic = time.monotonic()
    execution_error: Optional[str] = None
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(run_cwd),
            env=command_env,
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except OSError as exc:
        exit_code = 127
        stdout = b""
        stderr = b""
        execution_error = "{}: {}".format(type(exc).__name__, exc)
    finished_monotonic = time.monotonic()
    finished = _utc_now()

    artifact_error: Optional[str] = None
    artifact_manifest: Optional[Dict[str, Any]] = None
    try:
        artifact_manifest = inventory_directory(run_artifact_dir)
    except ManifestError as exc:
        artifact_error = str(exc)

    record: Dict[str, Any] = {
        "format": "msbwt-legacy-run-record-v1",
        "run_metadata": {
            "started_at": started,
            "finished_at": finished,
            "duration_seconds": finished_monotonic - started_monotonic,
            "runtime": _runtime_metadata(),
            "selected_environment": selected_environment,
        },
        "command": {"argv": list(argv), "cwd": str(run_cwd)},
        "result": {
            "exit_code": exit_code,
            "execution_error": execution_error,
            "stdout": {
                "bytes_base64": base64.b64encode(stdout).decode("ascii"),
                "size": len(stdout),
                "sha256": sha256_bytes(stdout),
            },
            "stderr": {
                "bytes_base64": base64.b64encode(stderr).decode("ascii"),
                "size": len(stderr),
                "sha256": sha256_bytes(stderr),
            },
        },
        "artifact_manifest": artifact_manifest,
        "artifact_inventory_error": artifact_error,
    }
    return record, exit_code


def _inventory_command(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.artifact_dir)
    output = Path(args.output)
    _require_outside_artifact_tree(output, artifact_dir)
    write_json(output, inventory_directory(artifact_dir))
    return 0


def _verify_command(args: argparse.Namespace) -> int:
    expected = load_json(args.manifest)
    actual = inventory_directory(args.artifact_dir)
    report = compare_manifest(expected, actual)
    rendered = canonical_json_bytes(report)
    if args.output:
        output = Path(args.output)
        _require_outside_artifact_tree(output, Path(args.artifact_dir))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(rendered)
    else:
        sys.stdout.buffer.write(rendered)
    return 0 if report["matches"] else 1


def _capture_command(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    assignments = _parse_assignments(args.env)
    record_path = Path(args.record)
    artifact_dir = Path(args.artifact_dir)
    _require_outside_artifact_tree(record_path, artifact_dir)
    record, exit_code = capture_command(
        command,
        args.cwd,
        artifact_dir,
        env_assignments=assignments,
        record_environment=args.record_env,
    )
    write_json(record_path, record)
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create deterministic manifests and binary-safe records for frozen legacy runs."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    inventory = subparsers.add_parser(
        "inventory", help="hash a legacy artifact directory without loading array payloads"
    )
    inventory.add_argument("--artifact-dir", required=True, help="directory to inspect read-only")
    inventory.add_argument("--output", required=True, help="manifest JSON path outside artifact-dir")
    inventory.set_defaults(handler=_inventory_command)

    verify = subparsers.add_parser("verify", help="compare a directory to a previously captured manifest")
    verify.add_argument("--artifact-dir", required=True, help="directory to inspect read-only")
    verify.add_argument("--manifest", required=True, help="expected manifest JSON")
    verify.add_argument("--output", help="optional report JSON path outside artifact-dir")
    verify.set_defaults(handler=_verify_command)

    capture = subparsers.add_parser(
        "capture", help="run a command without a shell and record both success and failure"
    )
    capture.add_argument("--cwd", required=True, help="command working directory")
    capture.add_argument("--artifact-dir", required=True, help="directory to inventory after the command")
    capture.add_argument("--record", required=True, help="run-record JSON path outside artifact-dir")
    capture.add_argument(
        "--env", action="append", default=[], metavar="NAME=VALUE", help="set a command environment value"
    )
    capture.add_argument(
        "--record-env",
        action="append",
        default=[],
        metavar="NAME",
        help="include this selected command environment value in run metadata",
    )
    capture.add_argument("command", nargs=argparse.REMAINDER, help="command after --")
    capture.set_defaults(handler=_capture_command)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ManifestError as exc:
        parser.error(str(exc))
    return 2  # pragma: no cover - argparse.error raises SystemExit


# ---------------------------------------------------------------------------
# Frozen RLE safe-decoding (host-side Python 3; no NumPy/pickle/object arrays)
# ---------------------------------------------------------------------------

RLE_SYMBOL_ORDER = "$ACGNT"


def _rle_byte_value(value: Any) -> int:
    return value if isinstance(value, int) else ord(value)


def decode_rle_payload(payload: bytes) -> Dict[str, Any]:
    """Decode a frozen ``|u1`` RLE payload without loading a NumPy array.

    Low three bits index ``RLE_SYMBOL_ORDER`` (``$ACGNT``); the upper five bits
    of consecutive same-symbol bytes are little-endian base-32 run-length
    digits.  The committed uncompressed ``msbwt.npy`` stores the BWT as numeric
    symbol indices, so ``decoded_bytes`` carries those indices and
    ``decoded_sha256`` is computed over them.  ``decoded_symbols`` is the ASCII
    rendering for human-readable records.
    """
    runs: List[Dict[str, Any]] = []
    decoded_bytes = bytearray()
    decoded_symbols = bytearray()
    position = 0
    index = 0
    length = len(payload)
    while index < length:
        symbol_index = _rle_byte_value(payload[index]) & 0x07
        if symbol_index >= len(RLE_SYMBOL_ORDER):
            raise ManifestError(
                "RLE payload encodes an unknown symbol index: {}".format(symbol_index)
            )
        count = 0
        offset = 0
        digit_values: List[int] = []
        while (index + offset) < length and (
            _rle_byte_value(payload[index + offset]) & 0x07
        ) == symbol_index:
            digit = (_rle_byte_value(payload[index + offset]) >> 3) & 0x1F
            digit_values.append(digit)
            count += digit * (32 ** offset)
            offset += 1
        if count <= 0:
            raise ManifestError(
                "RLE payload encodes a non-positive run length: {}".format(count)
            )
        symbol = RLE_SYMBOL_ORDER[symbol_index]
        start = position
        end = position + count
        runs.append(
            {
                "symbol_index": symbol_index,
                "symbol": symbol,
                "count": count,
                "start": start,
                "end": end,
                "digits": offset,
                "digit_values": digit_values,
            }
        )
        decoded_bytes.extend(bytearray([symbol_index]) * count)
        decoded_symbols += symbol.encode("ascii") * count
        position = end
        index += offset
    return {
        "runs": runs,
        "run_count": len(runs),
        "decoded_bytes": bytes(decoded_bytes),
        "decoded_sha256": sha256_bytes(bytes(decoded_bytes)),
        "decoded_length": len(decoded_bytes),
        "decoded_symbols": decoded_symbols.decode("ascii"),
    }


def runs_from_byte_bwt(bwt_bytes: bytes) -> List[Dict[str, Any]]:
    """Group a committed uncompressed BWT (numeric indices) into runs."""
    runs: List[Dict[str, Any]] = []
    position = 0
    index = 0
    length = len(bwt_bytes)
    while index < length:
        symbol_index = _rle_byte_value(bwt_bytes[index])
        offset = 0
        while (index + offset) < length and _rle_byte_value(bwt_bytes[index + offset]) == symbol_index:
            offset += 1
        count = offset
        symbol = RLE_SYMBOL_ORDER[symbol_index] if symbol_index < len(RLE_SYMBOL_ORDER) else "?"
        runs.append(
            {
                "symbol_index": symbol_index,
                "symbol": symbol,
                "count": count,
                "start": position,
                "end": position + count,
                "digits": 0,
                "digit_values": [],
            }
        )
        position += count
        index += count
    return runs


def run_signature(runs: Sequence[Mapping[str, Any]]) -> List[List[int]]:
    """Semantic run boundary/sequence view, ignoring RLE byte-digit encoding."""
    return [[run["symbol"], run["count"], run["start"], run["end"]] for run in runs]


def extract_shape_literal(header_text: str) -> str:
    """Return the raw NumPy shape literal as persisted, preserving ``L`` suffixes."""
    marker = "'shape': "
    index = header_text.find(marker)
    if index < 0:
        raise ManifestError("NumPy header lacks a shape entry: {!r}".format(header_text))
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
                return header_text[start : position + 1]
    raise ManifestError("NumPy header shape literal is unbalanced: {!r}".format(header_text))


def _read_file_bytes(path: Path, offset: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read()


def decode_npy_rle_primary(path: os.PathLike[str] | str) -> Dict[str, Any]:
    """Safe-decode a ``|u1`` RLE ``comp_msbwt.npy`` primary without NumPy.

    Combines NP1 header parsing and the independent RLE decoder into one
    JSON-safe report: payload hash, every encoded digit, run boundaries,
    symbol/count pairs, decoded length, decoded-BWT hash, decoded symbols,
    raw shape literal, dtype, and whole-file hash.
    """
    path_obj = Path(path)
    parsed = parse_npy_header(path_obj)
    if parsed["dtype_descriptor"] != "|u1":
        raise ManifestError("RLE primary dtype is not |u1: {!r}".format(parsed["dtype_descriptor"]))
    decoded = decode_rle_payload(_read_file_bytes(path_obj, parsed["payload_offset"]))
    record = {
        "dtype": parsed["dtype_descriptor"],
        "shape": parsed["shape"],
        "shape_literal": extract_shape_literal(parsed["header_text"]),
        "header_text": parsed["header_text"].rstrip("\n"),
        "header_length": parsed["header_length"],
        "version": parsed["version"],
        "payload_sha256": parsed["payload_sha256"],
        "payload_size": parsed["payload_size"],
        "whole_sha256": sha256_file(path_obj),
        "size": path_obj.stat().st_size,
    }
    record["runs"] = decoded["runs"]
    record["run_count"] = decoded["run_count"]
    record["decoded_length"] = decoded["decoded_length"]
    record["decoded_sha256"] = decoded["decoded_sha256"]
    record["decoded_bwt"] = decoded["decoded_symbols"]
    return record


if __name__ == "__main__":
    raise SystemExit(main())
