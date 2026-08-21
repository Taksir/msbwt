#!/usr/bin/env python
"""Retrofit Feature-9 read provenance onto an existing merged MSBWT.

This tool consumes each leaf's Feature-9 read provenance (or Holt's legacy
``about.npy``) and replays only the saved provenance interleaves, so the
merged ``msbwt.npy`` and ``provenance.json`` bytes are never rewritten.

Example
-------
python tools/retrofit_read_provenance.py \
    --merged /data/merged10 \
    --source sample00=/data/sample00 \
    --source sample01=/data/sample01 \
    ... \
    --overwrite

Each leaf directory may already contain Feature-9 read provenance or may
retain Holt's legacy ``about.npy``.
"""

import argparse

from MUS.ReadProvenance import retrofit_read_provenance_from_leaf_dirs


def parse_assignment(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "expected SOURCE_ID=PATH"
        )
    key, path = value.split("=", 1)
    if not key or not path:
        raise argparse.ArgumentTypeError(
            "expected SOURCE_ID=PATH"
        )
    return key, path


def parse_files_assignment(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "expected SOURCE_ID=file1,file2,..."
        )
    key, raw = value.split("=", 1)
    files = [p for p in raw.split(",") if p]
    return key, files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--merged", required=True)
    parser.add_argument(
        "--source",
        action="append",
        type=parse_assignment,
        required=True,
        help="stable SOURCE_ID=leaf_BWT_directory; repeat per source",
    )
    parser.add_argument(
        "--input-files",
        action="append",
        type=parse_files_assignment,
        default=[],
        help=(
            "optional SOURCE_ID=file1.fastq,file2.fastq mapping because "
            "legacy about.npy stores numeric file IDs but not filenames"
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    leaf_dirs = dict(args.source)
    input_files = dict(args.input_files)

    index = retrofit_read_provenance_from_leaf_dirs(
        args.merged,
        leaf_dirs,
        input_files_by_source=input_files or None,
        overwrite=args.overwrite,
    )

    print("read provenance written")
    print("reads:", index.read_count)
    print("record bytes:", index.record_bytes())


if __name__ == "__main__":
    main()
