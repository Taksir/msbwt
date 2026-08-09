#!/usr/bin/env python
"""Verify the implementation projection used by the frozen 0.3.0 oracle.

This script is Python 2.7 and Python 3 compatible so it can be run before a
container is available.  It validates only files tracked at the audited commit;
new documentation and external harness files are intentionally ignored.
"""
from __future__ import print_function

import argparse
import hashlib
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(SCRIPT_DIR, "frozen-source.sha256")


def read_manifest(path):
    entries = []
    with open(path, "rb") as handle:
        for number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line or line.startswith(b"#"):
                continue
            pieces = line.split(None, 1)
            if len(pieces) != 2 or len(pieces[0]) != 64:
                raise ValueError("invalid manifest line {0}".format(number))
            digest, relative = pieces
            try:
                digest_text = digest.decode("ascii").lower()
            except AttributeError:
                digest_text = digest.lower()
            try:
                relative_text = relative.decode("utf-8")
            except AttributeError:
                relative_text = relative
            if os.path.isabs(relative_text) or ".." in relative_text.split("/"):
                raise ValueError("unsafe manifest path on line {0}".format(number))
            entries.append((digest_text, relative_text))
    if not entries:
        raise ValueError("manifest has no entries")
    return entries


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def verify(source, manifest):
    mismatches = []
    for expected, relative in read_manifest(manifest):
        path = os.path.join(source, *relative.split("/"))
        if not os.path.isfile(path):
            mismatches.append((relative, "missing", expected, None))
            continue
        actual = sha256_file(path)
        if actual != expected:
            mismatches.append((relative, "sha256", expected, actual))
    return mismatches


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="repository root containing frozen source files")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="SHA-256 manifest path")
    args = parser.parse_args(argv)

    source = os.path.abspath(args.source)
    mismatches = verify(source, args.manifest)
    if mismatches:
        for relative, reason, expected, actual in mismatches:
            print("FAIL {0}: {1}; expected={2}; actual={3}".format(relative, reason, expected, actual))
        return 1
    print("OK frozen source projection: {0} files".format(len(read_manifest(args.manifest))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
