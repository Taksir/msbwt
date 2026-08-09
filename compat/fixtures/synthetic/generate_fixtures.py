#!/usr/bin/env python3
"""Generate and verify the first deterministic MSBWT FASTQ fixtures.

The frozen oracle consumes FASTQ records as fixed groups of four lines, reads
the sequence line, and appends its own ``$`` terminator.  These inputs keep
the terminator out of biological sequence data and intentionally use LF only.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_NAME = "fixture-manifest.json"
VALID_BASES = frozenset("ACGNT")


# Each entry is (header, sequence, separator, qualities).  Header/quality
# differences are intentional: the legacy readers ignore them while consuming
# the fixed four-line layout.
FASTQ_RECORDS: Dict[str, Tuple[Tuple[str, str, str, str], ...]] = {
    "uniform-a.fastq": (
        ("@pair-000/1 source=uniform-a", "ACGTN", "+", "IIIII"),
        ("@pair-001/1 duplicate=first", "AAAAA", "+", "#####"),
        ("@pair-002/1 duplicate=second", "ACGTN", "+", "JKLMN"),
        ("@pair-000/2 reverse-complement", "NACGT", "+", "+++++"),
    ),
    "uniform-b.fastq": (
        ("@pair-003/1 tie-across-file", "ACGTN", "+", "?????"),
        ("@pair-004/1 c-homopolymer", "CCCCC", "+", "55555"),
        ("@pair-005/1 g-homopolymer", "GGGGG", "+", "@@@@@"),
        ("@pair-006/1 t-homopolymer", "TTTTT", "+", "ZZZZZ"),
    ),
    "nonuniform.fastq": (
        ("@variable-000 shortest-a", "A", "+", "I"),
        ("@variable-001 prefix-ac", "AC", "+", "JK"),
        ("@variable-002 prefix-acg", "ACG", "+", "###"),
        ("@variable-003 prefix-acgt", "ACGT", "+", "++++"),
        ("@variable-004 all-symbols", "ACGTN", "+", "?????"),
        ("@variable-005 long-t", "TTTTTTT", "+", "5555555"),
        ("@variable-006 shortest-n", "N", "+", "!"),
    ),
}

FIXTURE_PURPOSES = {
    "uniform-multifile": (
        "Uniform five-base reads split across two files; exercises duplicate "
        "sequences, a lexicographic tie across files, A/C/G/N/T coverage, and "
        "paired-looking identifiers."
    ),
    "nonuniform-prefix": (
        "Variable-length reads with prefix relationships, shortest practical "
        "reads, A/C/G/N/T coverage, and a longer homopolymer."
    ),
    "gzip-input": (
        "Byte-for-byte deterministic gzip equivalents for the uniform-a and "
        "nonuniform inputs; exercises the legacy .gz input branch."
    ),
}


def _fastq_bytes(records: Iterable[Tuple[str, str, str, str]]) -> bytes:
    lines: List[str] = []
    for header, sequence, separator, qualities in records:
        lines.extend((header, sequence, separator, qualities))
    raw = ("\n".join(lines) + "\n").encode("ascii")
    _validate_fastq(raw)
    return raw


def _validate_fastq(raw: bytes) -> None:
    """Raise ValueError when a generated file stops being valid simple FASTQ."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("FASTQ is not ASCII") from exc
    if not text.endswith("\n") or "\r" in text:
        raise ValueError("FASTQ must use LF-only lines and end in LF")
    lines = text.splitlines()
    if len(lines) == 0 or len(lines) % 4:
        raise ValueError("FASTQ must contain one or more complete four-line records")
    for record_start in range(0, len(lines), 4):
        header, sequence, separator, qualities = lines[record_start:record_start + 4]
        record_number = record_start // 4 + 1
        if not header.startswith("@"):
            raise ValueError("record %d header lacks @" % record_number)
        if not separator.startswith("+"):
            raise ValueError("record %d separator lacks +" % record_number)
        if not sequence or not set(sequence).issubset(VALID_BASES):
            raise ValueError("record %d contains an invalid biological sequence" % record_number)
        if len(sequence) != len(qualities):
            raise ValueError("record %d sequence/quality lengths differ" % record_number)
        if any(ord(value) < 33 or ord(value) > 126 for value in qualities):
            raise ValueError("record %d contains a non-printable quality" % record_number)


def _gzip_bytes(raw: bytes) -> bytes:
    """Encode deterministic gzip bytes, including a fixed unknown OS field."""
    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="", fileobj=buffer, mode="wb", compresslevel=9, mtime=0
    ) as gzip_file:
        gzip_file.write(raw)
    encoded = bytearray(buffer.getvalue())
    # RFC 1952's OS field (offset 9) is implementation-dependent by default.
    # Fix it to 255 (unknown) so the generated fixture header is explicit.
    encoded[9] = 255
    return bytes(encoded)


def expected_files() -> Tuple[Tuple[str, bytes], ...]:
    """Return every generated fixture in its stable manifest order."""
    uniform_a = _fastq_bytes(FASTQ_RECORDS["uniform-a.fastq"])
    nonuniform = _fastq_bytes(FASTQ_RECORDS["nonuniform.fastq"])
    return (
        ("uniform-a.fastq", uniform_a),
        ("uniform-b.fastq", _fastq_bytes(FASTQ_RECORDS["uniform-b.fastq"])),
        ("nonuniform.fastq", nonuniform),
        ("uniform-a.fastq.gz", _gzip_bytes(uniform_a)),
        ("nonuniform.fastq.gz", _gzip_bytes(nonuniform)),
    )


def _file_metadata(name: str, raw: bytes) -> Dict[str, object]:
    return {
        "path": name,
        "kind": "fastq-gzip" if name.endswith(".gz") else "fastq",
        "byte_count": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def expected_manifest(files: Sequence[Tuple[str, bytes]]) -> bytes:
    manifest = {
        "schema_version": 1,
        "generator": {
            "script": "generate_fixtures.py",
            "fastq_line_endings": "LF",
            "gzip": {
                "compression_level": 9,
                "filename_header": "",
                "mtime": 0,
                "os_byte": 255,
            },
        },
        "cases": [
            {
                "id": "uniform-multifile",
                "purpose": FIXTURE_PURPOSES["uniform-multifile"],
                "files": ["uniform-a.fastq", "uniform-b.fastq"],
            },
            {
                "id": "nonuniform-prefix",
                "purpose": FIXTURE_PURPOSES["nonuniform-prefix"],
                "files": ["nonuniform.fastq"],
            },
            {
                "id": "gzip-input",
                "purpose": FIXTURE_PURPOSES["gzip-input"],
                "files": ["uniform-a.fastq.gz", "nonuniform.fastq.gz"],
            },
        ],
        "files": [_file_metadata(name, raw) for name, raw in files],
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def expected_artifacts() -> Tuple[Tuple[str, bytes], ...]:
    files = expected_files()
    return files + ((MANIFEST_NAME, expected_manifest(files)),)


def write_artifacts(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, raw in expected_artifacts():
        (output_dir / name).write_bytes(raw)


def check_artifacts(output_dir: Path) -> List[str]:
    mismatches = []
    for name, expected in expected_artifacts():
        path = output_dir / name
        try:
            actual = path.read_bytes()
        except FileNotFoundError:
            mismatches.append("missing: %s" % path)
            continue
        if actual != expected:
            mismatches.append("drifted: %s" % path)
    return mismatches


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write canonical fixture bytes")
    mode.add_argument("--check", action="store_true", help="fail if canonical bytes drifted")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR,
        help="fixture directory (default: this script's directory)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    output_dir = args.output_dir.resolve()
    if args.write:
        write_artifacts(output_dir)
        print("wrote %d artifacts to %s" % (len(expected_artifacts()), output_dir))
        return 0
    mismatches = check_artifacts(output_dir)
    if mismatches:
        for mismatch in mismatches:
            print(mismatch, file=sys.stderr)
        return 1
    print("fixture bytes match %s" % output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
