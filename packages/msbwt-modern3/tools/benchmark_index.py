#!/usr/bin/env python
"""Feature 13A benchmark/contract command-line tool.

Examples
--------
Structural inspection (works without compiled MUSCython):

    python tools/benchmark_index.py inspect \
        --input /data/merged10 \
        --output benchmark.json

Compare multiple indexes:

    python tools/benchmark_index.py compare \
        --index ten=/data/merged10 \
        --index seven=/data/merged7 \
        --output comparison.json

Query benchmark (requires real compiled MUSCython):

    python tools/benchmark_index.py query \
        --input /data/merged10 \
        --patterns A,AC,ACGT \
        --source sample07 \
        --tag source_slot \
        --repeats 20 \
        --output query.json

Export the backend contract:

    python tools/benchmark_index.py contract \
        --output backend_contract.json
"""

import argparse
import json
import os
import sys

from MUS.BackendContract import contract_document
from MUS.Benchmarking import (
    benchmark_queries,
    compare_reports,
    inspect_index,
    save_report,
)
from MUS.MultiSourceQuery import MultiSourceBWT


def parse_labeled_index(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "expected LABEL=PATH"
        )
    label, path = value.split("=", 1)
    if not label or not path:
        raise argparse.ArgumentTypeError(
            "expected LABEL=PATH"
        )
    return label, path


def patterns_from_arg(raw):
    if raw is None:
        return None
    return [
        token.encode("ascii")
        for token in raw.split(",")
        if token
    ]


def emit(data, output=None):
    text = json.dumps(
        data,
        indent=2,
        sort_keys=True,
    )
    if output:
        save_report(output, data)
    print(text)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("inspect")
    p.add_argument("--input", required=True)
    p.add_argument("--output")

    p = sub.add_parser("compare")
    p.add_argument(
        "--index",
        action="append",
        type=parse_labeled_index,
        required=True,
        help="LABEL=PATH; repeat",
    )
    p.add_argument("--output")

    p = sub.add_parser("query")
    p.add_argument("--input", required=True)
    p.add_argument(
        "--patterns",
        default=None,
        help="comma-separated ASCII patterns",
    )
    p.add_argument("--source", default=None)
    p.add_argument("--tag", default=None)
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--warmup", type=int, default=2)
    p.add_argument("--repeats", type=int, default=10)
    p.add_argument(
        "--include-read-listing",
        action="store_true",
    )
    p.add_argument("--metadata", default=None)
    p.add_argument("--output")

    p = sub.add_parser("contract")
    p.add_argument("--output")

    args = parser.parse_args()
    if args.command is None:
        parser.print_usage()
        return 2

    if args.command == "inspect":
        emit(
            inspect_index(args.input),
            args.output,
        )
        return

    if args.command == "compare":
        reports = {
            label: inspect_index(path)
            for label, path in args.index
        }
        emit(
            {
                "reports": reports,
                "comparison": compare_reports(reports),
            },
            args.output,
        )
        return

    if args.command == "contract":
        emit(
            contract_document(),
            args.output,
        )
        return

    wrapped = MultiSourceBWT.load(
        args.input,
        mmap=True,
        source_metadata_path=args.metadata,
    )
    report = benchmark_queries(
        wrapped,
        patterns=patterns_from_arg(args.patterns),
        warmup=args.warmup,
        repeats=args.repeats,
        source=args.source,
        top_k=args.top_k,
        tag_name=args.tag,
        include_read_listing=args.include_read_listing,
    )
    emit(report, args.output)


if __name__ == "__main__":
    main()
