#!/usr/bin/env python
"""Manage Q1 exact FASTQ quality sidecars.

Examples
--------
Initialize one standalone BWT from its original FASTQs:

    python tools/quality_sidecar.py init-leaf \
        --input /data/sample00 \
        --fastq sample00_R1.fastq.gz

Retrofit an existing merged package from already-Q1-enabled standalone
BWTs (replays saved provenance interleaves; no BWT re-merge):

    python tools/quality_sidecar.py retrofit-merged \
        --input /data/merged10 \
        --source sample00=/data/sample00 \
        --source sample01=/data/sample01

Validate:

    python tools/quality_sidecar.py validate --input /data/merged10

Recover one sequence/quality pair:

    python tools/quality_sidecar.py recover \
        --input /data/merged10 \
        --dollar-id 123
"""

import argparse
import json

from MUS.QualitySidecar import (
    QualitySidecar,
    initialize_leaf_quality_from_fastqs,
    retrofit_merged_quality_from_leaf_arrays,
    validate_quality_sidecar,
)


def source_assignment(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "expected SOURCE_ID=LEAF_BWT_DIR"
        )
    sid, path = value.split("=", 1)
    if not sid or not path:
        raise argparse.ArgumentTypeError(
            "expected SOURCE_ID=LEAF_BWT_DIR"
        )
    return sid, path


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init-leaf")
    p.add_argument("--input", required=True)
    p.add_argument(
        "--fastq",
        action="append",
        required=True,
        help="original FASTQ/FASTQ.GZ; repeat in original file-ID order",
    )
    p.add_argument("--about", default=None)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--no-verify-sequences",
        action="store_true",
    )

    p = sub.add_parser("retrofit-merged")
    p.add_argument("--input", required=True)
    p.add_argument(
        "--source",
        action="append",
        required=True,
        type=source_assignment,
        help="SOURCE_ID=standalone_tagged_BWT_dir; repeat",
    )
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("validate")
    p.add_argument("--input", required=True)

    p = sub.add_parser("recover")
    p.add_argument("--input", required=True)
    p.add_argument("--dollar-id", type=int, required=True)

    args = parser.parse_args()
    if args.command is None:
        parser.print_usage()
        return 2

    if args.command == "init-leaf":
        from MUSCython import MultiStringBWTCython as MultiStringBWT

        bwt = MultiStringBWT.loadBWT(
            str(args.input),
            useMemmap=True,
        )
        metadata = initialize_leaf_quality_from_fastqs(
            args.input,
            bwt,
            args.fastq,
            about_path=args.about,
            overwrite=args.overwrite,
            verify_sequences=not args.no_verify_sequences,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True))
        return

    if args.command == "retrofit-merged":
        arrays = {}
        for sid, directory in args.source:
            leaf = QualitySidecar(
                directory,
                mmap=True,
                validate=True,
            )
            arrays[sid] = leaf.values

        metadata = retrofit_merged_quality_from_leaf_arrays(
            args.input,
            arrays,
            overwrite=args.overwrite,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True))
        return

    if args.command == "validate":
        metadata = validate_quality_sidecar(
            args.input,
            full=True,
        )
        print(
            json.dumps(
                {
                    "valid": True,
                    "metadata": metadata,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    from MUSCython import MultiStringBWTCython as MultiStringBWT

    bwt = MultiStringBWT.loadBWT(
        str(args.input),
        useMemmap=True,
    )
    sidecar = QualitySidecar(
        args.input,
        mmap=True,
        validate=True,
    )
    sequence, quality = sidecar.recover_sequence_and_quality(
        bwt,
        args.dollar_id,
    )
    print(
        json.dumps(
            {
                "dollar_id": args.dollar_id,
                "sequence": sequence.decode("ascii"),
                # latin1 is a reversible byte-to-Unicode mapping for display.
                "quality": quality.decode("latin1"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
