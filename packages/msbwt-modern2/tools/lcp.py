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
"""

from __future__ import print_function

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
