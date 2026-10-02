#!/usr/bin/env python
"""Manage the Feature-11A exact LCP layer.

Examples
--------
Construct (no FASTQ, no BWT rebuild):

    python tools/lcp.py construct --input /data/merged10

Validate:

    python tools/lcp.py validate --input /data/merged10

Inspect:

    python tools/lcp.py inspect --input /data/merged10

Maximal repeats (Feature 11C), one JSON record per line:

    python tools/lcp.py repeats --input /data/merged10 \
        --min-length 25 --min-sources 3 --include-sources
"""

import argparse
import json

from MUS.LCP import (
    LCPIndex,
    construct_lcp_from_bwt,
    validate_lcp,
)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("construct")
    p.add_argument("--input", required=True)
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("validate")
    p.add_argument("--input", required=True)

    p = sub.add_parser("inspect")
    p.add_argument("--input", required=True)

    p = sub.add_parser(
        "repeats", help="list maximal repeats with source support")
    p.add_argument("--input", required=True)
    p.add_argument("--min-length", type=int, default=1)
    p.add_argument("--max-length", type=int, default=None)
    p.add_argument("--min-occurrences", type=int, default=2)
    p.add_argument("--min-sources", type=int, default=None)
    p.add_argument("--max-sources", type=int, default=None)
    p.add_argument("--supermaximal", action="store_true")
    p.add_argument("--group", default=None,
                   help="report and filter counts for a metadata group")
    p.add_argument("--min-selected", type=int, default=None)
    p.add_argument("--include-sources", action="store_true")
    p.add_argument("--include-read-count", action="store_true")
    p.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    if args.command is None:
        parser.print_usage()
        return 2

    if args.command == "construct":
        metadata = construct_lcp_from_bwt(
            args.input,
            overwrite=args.overwrite,
        )
        print(json.dumps(metadata, indent=2, sort_keys=True))
        return

    if args.command == "validate":
        metadata = validate_lcp(args.input, full=True)
        print(
            json.dumps(
                {"valid": True, "metadata": metadata},
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command == "repeats":
        from MUS.MultiSourceQuery import MultiSourceBWT
        msbwt = MultiSourceBWT.load(args.input)
        for record in msbwt.maximalRepeats(
            min_length=args.min_length,
            max_length=args.max_length,
            min_occurrences=args.min_occurrences,
            supermaximal=args.supermaximal,
            min_sources=args.min_sources,
            max_sources=args.max_sources,
            group=args.group,
            min_selected=args.min_selected,
            include_sources=args.include_sources,
            include_read_count=args.include_read_count,
            limit=args.limit,
        ):
            record["sequence"] = record["sequence"].decode("ascii")
            print(json.dumps(record, sort_keys=True))
        return

    index = LCPIndex(args.input, mmap=True, validate=True)
    print(
        json.dumps(
            {
                "valid": True,
                "metadata": index.metadata,
                "n_rows": index.n_rows,
                "boundaries": int(index.values.shape[0]),
                "max_lcp": index.max_lcp,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
