#!/usr/bin/env python
"""Remove/unmerge sources from a provenance-preserving MSBWT.

Examples
--------
Remove explicit sources:

    python tools/remove_sources.py \
        --input /data/merged10 \
        --output /data/merged7 \
        --remove sample00,sample02,sample09

Remove a named metadata group:

    python tools/remove_sources.py \
        --input /data/merged10 \
        --output /data/control \
        --group case \
        --metadata /project/source_metadata.json

Retain only selected sources:

    python tools/remove_sources.py \
        --input /data/merged10 \
        --output /data/panel \
        --keep sample01,sample05,sample08
"""

from __future__ import print_function

import argparse
import json

from MUS.SourceRemoval import (
    remove_sources,
    retain_sources,
)


def parse_where(values):
    if not values:
        return None
    result = {}
    for item in values:
        if "=" not in item:
            raise ValueError("--where must use KEY=VALUE")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)

    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--remove",
        help="comma-separated stable source IDs/names to remove",
    )
    selection.add_argument(
        "--keep",
        help="comma-separated stable source IDs/names to retain",
    )
    selection.add_argument(
        "--group",
        help="named metadata group to remove",
    )
    selection.add_argument(
        "--where",
        action="append",
        metavar="KEY=VALUE",
        help="metadata predicate to remove; repeat for AND",
    )

    parser.add_argument(
        "--metadata",
        default=None,
        help="optional external source_metadata.json",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--build-ranks", action="store_true")
    parser.add_argument(
        "--rank-stride-bytes",
        type=int,
        default=64,
    )

    args = parser.parse_args()

    common = {
        "source_metadata_path": args.metadata,
        "overwrite": args.overwrite,
        "build_rank_indexes": args.build_ranks,
        "rank_stride_bytes": args.rank_stride_bytes,
    }

    if args.keep is not None:
        stats = retain_sources(
            args.input,
            args.output,
            [x for x in args.keep.split(",") if x],
            **common
        )
    elif args.remove is not None:
        stats = remove_sources(
            args.input,
            args.output,
            sources=[x for x in args.remove.split(",") if x],
            **common
        )
    elif args.group is not None:
        stats = remove_sources(
            args.input,
            args.output,
            group=args.group,
            **common
        )
    else:
        stats = remove_sources(
            args.input,
            args.output,
            where=parse_where(args.where),
            **common
        )

    print(json.dumps(stats, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
