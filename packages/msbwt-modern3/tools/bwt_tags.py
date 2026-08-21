#!/usr/bin/env python
"""Manage Feature-12 BWT-aligned tag arrays.

Examples
--------
List tags:

    python tools/bwt_tags.py list --input /data/merged10

Attach a complete merged-row array:

    python tools/bwt_tags.py attach \
        --input /data/merged10 \
        --name quality_bin \
        --array quality_bin.npy \
        --description "quality bin per BWT row"

Retrofit from standalone leaf-aligned arrays without re-merging the BWT:

    python tools/bwt_tags.py retrofit \
        --input /data/merged10 \
        --name read_pos \
        --source sample00=sample00_read_pos.npy \
        --source sample01=sample01_read_pos.npy

Remove:

    python tools/bwt_tags.py remove \
        --input /data/merged10 \
        --name read_pos
"""

import argparse
import json

import numpy as np

from MUS.BWTTags import (
    BWTTagStore,
    attach_tag,
    build_tag_from_leaf_arrays,
    remove_tag,
)


def source_assignment(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "expected SOURCE_ID=ARRAY.npy"
        )
    sid, path = value.split("=", 1)
    if not sid or not path:
        raise argparse.ArgumentTypeError(
            "expected SOURCE_ID=ARRAY.npy"
        )
    return sid, path


def parse_missing(raw):
    if raw is None:
        return None, False
    try:
        return json.loads(raw), True
    except ValueError:
        return raw, True


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("list")
    p.add_argument("--input", required=True)

    p = sub.add_parser("validate")
    p.add_argument("--input", required=True)

    p = sub.add_parser("attach")
    p.add_argument("--input", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--array", required=True)
    p.add_argument("--description", default=None)
    p.add_argument(
        "--missing-value",
        default=None,
        help="JSON scalar; enables one-sided merge filling",
    )
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("retrofit")
    p.add_argument("--input", required=True)
    p.add_argument("--name", required=True)
    p.add_argument(
        "--source",
        action="append",
        type=source_assignment,
        required=True,
        help="SOURCE_ID=leaf_aligned_array.npy; repeat",
    )
    p.add_argument("--description", default=None)
    p.add_argument(
        "--missing-value",
        default=None,
        help="JSON scalar; required when some sources have no array",
    )
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("remove")
    p.add_argument("--input", required=True)
    p.add_argument("--name", required=True)

    args = parser.parse_args()
    if args.command is None:
        parser.print_usage()
        return 2

    if args.command == "list":
        store = BWTTagStore(args.input, mmap=True)
        result = {}
        for name in store.list_tags():
            arr = store.array(name)
            result[name] = {
                "schema": store.schema(name),
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.command == "validate":
        store = BWTTagStore(args.input, mmap=True, validate=True)
        print(
            json.dumps(
                {
                    "valid": True,
                    "bwt_rows": store.bwt_length,
                    "tags": store.list_tags(),
                },
                indent=2,
            )
        )
        return

    if args.command == "remove":
        remove_tag(args.input, args.name)
        print("removed:", args.name)
        return

    missing, has_missing = parse_missing(
        getattr(args, "missing_value", None)
    )

    if args.command == "attach":
        values = np.load(
            args.array,
            mmap_mode="r",
            allow_pickle=False,
        )
        kwargs = {
            "bwt_dir": args.input,
            "name": args.name,
            "values": values,
            "description": args.description,
            "overwrite": args.overwrite,
        }
        if has_missing:
            kwargs["missing_value"] = missing
        schema = attach_tag(**kwargs)
        print(json.dumps(schema, indent=2, sort_keys=True))
        return

    arrays = dict(args.source)
    kwargs = {
        "merged_bwt_dir": args.input,
        "name": args.name,
        "arrays_by_source": arrays,
        "description": args.description,
        "overwrite": args.overwrite,
    }
    if has_missing:
        kwargs["missing_value"] = missing

    schema = build_tag_from_leaf_arrays(**kwargs)
    print(json.dumps(schema, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
