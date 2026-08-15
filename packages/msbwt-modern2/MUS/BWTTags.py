"""Generic fixed-width arrays aligned to MSBWT rows (Feature 12,
enhanced-modern2).

A BWT tag is any NumPy array whose first dimension equals ``msbwt.npy``
length:

    tag.shape[0] == number of BWT rows

and ``tag[x]`` belongs to exactly the same logical BWT row as
``msbwt[x]`` through every supported lifecycle operation (attach,
retrofit, two-way/balanced merge, query, source/group filter, Feature-10
source removal).

This is intentionally an engineering layer (row-aligned auxiliary arrays
are an established, non-novel pattern); its value here is lifecycle
integration with the verified Features 1-10.

Persistent format
-----------------
- ``bwt_tags.json``   AUTHORITATIVE registry: maps the human-readable tag
  name to ``filename`` (a hash of the logical name, so user-controlled
  names never become filesystem paths), ``dtype``, ``tail_shape``,
  ``description``, and the missing-value policy.
- ``bwt_tags/tag_<sha256-prefix>.npy``   AUTHORITATIVE row-aligned array
  (ordinary mmap-able .npy; one file per tag).

Dtype policy
------------
Only primitive fixed-width NumPy dtypes are supported (bool, integer,
float, fixed-width bytes/Unicode, datetime/timedelta primitives).
``object`` and structured dtypes are rejected: they weaken safe no-pickle
loading, mmap behavior, schema checks, and stable merge semantics.

Missing-value policy
--------------------
A tag may exist on only some sources when an explicit scalar missing
value is declared; otherwise a one-sided tag fails the merge BEFORE the
expensive BWT merge.  Feature 12 never silently loses or fabricates
annotation values.

Lifecycle guarantees
--------------------
- attach/retrofit never change the BWT;
- two-way and balanced merges automatically stable-interleave tags using
  the exact same ``inter0.npy`` bits that interleaved the BWT rows
  (bit 0 consumes the next left tag row, bit 1 the next right tag row);
- Feature-10 source removal filters every tag with the exact BWT-row
  survival mask (chunked, mmap-backed output);
- merged/retrofitted/filtered tag arrays stay ordinary mmap-able .npy
  files; large temporaries are never materialized fully in RAM.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""

from __future__ import absolute_import

import gc
import hashlib
import json
import os
import shutil
import sys
import tempfile

import numpy as np
from numpy.lib.format import open_memmap

from MUS.MultiSourceProvenance import (
    BWT_FILENAME,
    INTERLEAVE_FILENAME,
    load_manifest,
)


REGISTRY_FILENAME = "bwt_tags.json"
TAG_DIRNAME = "bwt_tags"
FORMAT_NAME = "msbwt-bwt-tags"
FORMAT_VERSION = 1

_MISSING_UNSET = object()


class BWTTagError(ValueError):
    """Raised for invalid or incompatible BWT-aligned tags."""


def _atomic_write_json(path, document):
    """Write a JSON document atomically (tmp file -> rename)."""
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if sys.version_info[0] == 3:
        payload = payload.encode("utf-8")
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as fp:
        fp.write(payload)
        fp.flush()
        try:
            os.fsync(fp.fileno())
        except (OSError, IOError):
            pass
    if hasattr(os, "replace"):
        os.replace(tmp_path, path)
    else:
        os.rename(tmp_path, path)


def _atomic_replace(source_path, dest_path):
    if hasattr(os, "replace"):
        os.replace(source_path, dest_path)
    else:
        os.rename(source_path, dest_path)


def _name_text(name):
    """Normalize a tag name to text (unicode on py2, str on py3).

    JSON registry keys are unicode on Python 2 and str on Python 3; this
    keeps lookups consistent and hashing deterministic across versions.
    """
    if sys.version_info[0] == 2:
        if isinstance(name, unicode):  # noqa: F821
            return name
        return name.decode("utf-8")
    if isinstance(name, bytes):
        return name.decode("utf-8")
    return str(name)


def _name_bytes(name):
    return _name_text(name).encode("utf-8")


def _bytes_to_hex(value):
    """Python-2/3-neutral hex encoding of bytes."""
    if sys.version_info[0] == 2:
        return value.encode("hex")
    return value.hex()


def _hex_to_bytes(value):
    """Python-2/3-neutral hex decoding to bytes."""
    if sys.version_info[0] == 2:
        return value.decode("hex")
    return bytes.fromhex(value)


def registry_path(bwt_dir):
    return os.path.join(str(bwt_dir), REGISTRY_FILENAME)


def tag_dir(bwt_dir):
    return os.path.join(str(bwt_dir), TAG_DIRNAME)


def tags_exist(bwt_dir):
    path = registry_path(bwt_dir)
    if not os.path.exists(path):
        return False
    doc = _read_registry(bwt_dir)
    return bool(doc["tags"])


def _empty_registry():
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "tags": {},
    }


def _read_registry(bwt_dir):
    path = registry_path(bwt_dir)
    if not os.path.exists(path):
        return _empty_registry()

    try:
        with open(path, "rb") as fp:
            doc = json.load(fp)
    except ValueError as exc:
        raise BWTTagError(
            "BWT-tag registry is not valid JSON: %s: %s" % (path, exc))
    if doc.get("format") != FORMAT_NAME:
        raise BWTTagError(
            "unsupported BWT-tag registry format: %r"
            % doc.get("format")
        )
    if int(doc.get("version", -1)) != FORMAT_VERSION:
        raise BWTTagError(
            "unsupported BWT-tag registry version: %r"
            % doc.get("version")
        )
    if not isinstance(doc.get("tags"), dict):
        raise BWTTagError("BWT-tag registry 'tags' must be an object")
    return doc


def _write_registry(bwt_dir, doc):
    _atomic_write_json(registry_path(bwt_dir), doc)


def _tag_filename(name):
    digest = hashlib.sha256(_name_bytes(name)).hexdigest()[:20]
    return "%s/tag_%s.npy" % (TAG_DIRNAME, digest)


def _validate_name(name):
    name = _name_text(name)
    if not name:
        raise BWTTagError("tag name cannot be empty")
    if "\x00" in name:
        raise BWTTagError("tag name cannot contain NUL")
    return name


def _normalize_dtype(dtype):
    dtype = np.dtype(dtype)
    if dtype.hasobject:
        raise BWTTagError(
            "object-containing tag dtypes are not supported"
        )
    if dtype.fields is not None:
        raise BWTTagError(
            "structured tag dtypes are not supported; use multiple "
            "primitive tags"
        )
    return dtype


def _json_scalar(value):
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "hex": _bytes_to_hex(value),
        }
    if isinstance(value, float):
        if np.isnan(value):
            return {"kind": "float", "value": "nan"}
        if np.isposinf(value):
            return {"kind": "float", "value": "inf"}
        if np.isneginf(value):
            return {"kind": "float", "value": "-inf"}
    if isinstance(value, (bool, int, float, str)) or value is None:
        return {"kind": "json", "value": value}
    raise BWTTagError(
        "missing value is not JSON-serializable: %r" % (value,)
    )


def _decode_scalar(doc, dtype):
    kind = doc.get("kind")
    if kind == "bytes":
        value = _hex_to_bytes(doc["hex"])
    elif kind == "float":
        token = doc["value"]
        value = {
            "nan": np.nan,
            "inf": np.inf,
            "-inf": -np.inf,
        }[token]
    elif kind == "json":
        value = doc.get("value")
    else:
        raise BWTTagError(
            "unknown serialized scalar kind: %r" % kind
        )
    try:
        return np.asarray(value, dtype=dtype).item()
    except Exception as exc:
        raise BWTTagError(
            "missing value %r incompatible with dtype %s"
            % (value, dtype)
        )


def _bwt_length(bwt_dir):
    path = os.path.join(str(bwt_dir), BWT_FILENAME)
    if not os.path.exists(path):
        raise BWTTagError("missing BWT: %s" % path)
    bwt = np.load(path, mmap_mode="r")
    if bwt.ndim != 1:
        raise BWTTagError("msbwt.npy must be one-dimensional")
    return int(bwt.shape[0])


def _schema_from_values(
    name,
    values,
    description=None,
    missing_value=_MISSING_UNSET,
):
    arr = np.asarray(values)
    dtype = _normalize_dtype(arr.dtype)
    if arr.ndim < 1:
        raise BWTTagError("tag array must have at least one dimension")

    missing = {"enabled": False}
    if missing_value is not _MISSING_UNSET:
        cast = np.asarray(missing_value, dtype=dtype)
        if cast.ndim != 0:
            raise BWTTagError(
                "missing value must be scalar for tag %s" % name
            )
        missing = {
            "enabled": True,
            "value": _json_scalar(cast.item()),
        }

    return {
        "filename": _tag_filename(name),
        "dtype": dtype.str,
        "tail_shape": [int(x) for x in arr.shape[1:]],
        "description": (
            None if description is None else str(description)
        ),
        "missing": missing,
    }


def _schema_core(schema):
    return (
        str(schema["dtype"]),
        tuple(int(x) for x in schema.get("tail_shape", [])),
        bool(schema.get("missing", {}).get("enabled", False)),
        json.dumps(
            schema.get("missing", {}),
            sort_keys=True,
            allow_nan=False,
        ),
    )


def _validate_schema_file(bwt_dir, name, schema, bwt_length=None):
    dtype = _normalize_dtype(np.dtype(schema["dtype"]))
    tail = tuple(int(x) for x in schema.get("tail_shape", []))
    if any(x < 0 for x in tail):
        raise BWTTagError("negative tag tail dimension")

    path = os.path.join(str(bwt_dir), str(schema["filename"]))
    if not os.path.exists(path):
        raise BWTTagError(
            "tag %s file missing: %s" % (name, path)
        )
    arr = np.load(path, mmap_mode="r", allow_pickle=False)

    if arr.dtype != dtype:
        raise BWTTagError(
            "tag %s dtype %s != registry %s"
            % (name, arr.dtype, dtype)
        )
    expected_tail = tuple(arr.shape[1:])
    if expected_tail != tail:
        raise BWTTagError(
            "tag %s tail shape %r != registry %r"
            % (name, expected_tail, tail)
        )
    if bwt_length is None:
        bwt_length = _bwt_length(bwt_dir)
    if arr.shape[0] != int(bwt_length):
        raise BWTTagError(
            "tag %s has %d rows but BWT has %d"
            % (name, arr.shape[0], bwt_length)
        )
    return arr


def attach_tag(
    bwt_dir,
    name,
    values,
    description=None,
    missing_value=_MISSING_UNSET,
    overwrite=False,
):
    """Attach/replace one row-aligned tag without changing the MSBWT."""
    bwt_dir = str(bwt_dir)
    name = _validate_name(name)
    bwt_length = _bwt_length(bwt_dir)

    arr = np.asarray(values)
    if arr.ndim < 1:
        raise BWTTagError("tag array must have at least one dimension")
    _normalize_dtype(arr.dtype)
    if arr.shape[0] != bwt_length:
        raise BWTTagError(
            "tag %s has %d rows but BWT has %d"
            % (name, arr.shape[0], bwt_length)
        )

    doc = _read_registry(bwt_dir)
    if name in doc["tags"] and not overwrite:
        raise BWTTagError("tag already exists: %s" % name)

    schema = _schema_from_values(
        name,
        arr,
        description=description,
        missing_value=missing_value,
    )
    out_path = os.path.join(bwt_dir, schema["filename"])
    out_dir = os.path.dirname(out_path)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    np.save(out_path, arr, allow_pickle=False)

    doc["tags"][name] = schema
    _write_registry(bwt_dir, doc)
    return schema


def _remove_file_robust(path):
    """Remove a tag array file, closing lingering memory maps first.

    Windows keeps memory-mapped files locked; a bounded GC retry makes
    removal work even when a ``BWTTagStore`` still references the array.
    """
    for attempt in range(3):
        try:
            os.remove(path)
            return
        except (OSError, IOError):
            gc.collect()
            if attempt == 2:
                raise


def remove_tag(bwt_dir, name):
    bwt_dir = str(bwt_dir)
    name = _name_text(name)
    doc = _read_registry(bwt_dir)
    if name not in doc["tags"]:
        raise KeyError("unknown tag: %s" % name)

    path = os.path.join(bwt_dir, str(doc["tags"][name]["filename"]))
    if os.path.exists(path):
        _remove_file_robust(path)
    del doc["tags"][name]
    if doc["tags"]:
        _write_registry(bwt_dir, doc)
    else:
        reg = registry_path(bwt_dir)
        if os.path.exists(reg):
            os.remove(reg)


class BWTTagStore(object):
    """Validated mmap-friendly access to BWT-aligned tags."""

    def __init__(self, bwt_dir, mmap=True, validate=True):
        self.bwt_dir = str(bwt_dir)
        self.mmap = bool(mmap)
        self.registry = _read_registry(self.bwt_dir)
        self.bwt_length = _bwt_length(self.bwt_dir)
        self._arrays = {}

        if validate:
            self.validate()

    def validate(self):
        for name, schema in self.registry["tags"].items():
            _validate_schema_file(
                self.bwt_dir,
                name,
                schema,
                bwt_length=self.bwt_length,
            )
        return True

    def list_tags(self):
        return sorted(self.registry["tags"])

    def has_tag(self, name):
        return _name_text(name) in self.registry["tags"]

    def schema(self, name):
        name = _name_text(name)
        if name not in self.registry["tags"]:
            raise KeyError("unknown tag: %s" % name)
        return dict(self.registry["tags"][name])

    def array(self, name):
        name = _name_text(name)
        if name not in self.registry["tags"]:
            raise KeyError("unknown tag: %s" % name)
        if name not in self._arrays:
            mode = "r" if self.mmap else None
            self._arrays[name] = np.load(
                os.path.join(
                    self.bwt_dir,
                    str(self.registry["tags"][name]["filename"]),
                ),
                mmap_mode=mode,
                allow_pickle=False,
            )
        return self._arrays[name]

    def interval(self, name, start, end):
        start = int(start)
        end = int(end)
        if start < 0 or end < start or end > self.bwt_length:
            raise IndexError(
                "invalid tag interval [%d,%d) for %d rows"
                % (start, end, self.bwt_length)
            )
        return self.array(name)[start:end]

    def release(self):
        """Drop cached tag arrays (closes memory maps).

        Useful before removing/overwriting tag files on platforms where
        open memory maps lock the underlying file (e.g. Windows).
        """
        self._arrays.clear()
        gc.collect()
        return True

    def value_counts(self, name, start=0, end=None):
        if end is None:
            end = self.bwt_length
        values = self.interval(name, start, end)
        if values.ndim != 1:
            raise BWTTagError(
                "value_counts requires a scalar tag; %s has tail shape %r"
                % (name, values.shape[1:])
            )
        unique, counts = np.unique(values, return_counts=True)
        return unique, counts


def validate_tag_merge_compatibility(left_dir, right_dir):
    """Return a merge plan and fail before BWT merge on unsafe tag mismatch."""
    left_doc = _read_registry(left_dir)
    right_doc = _read_registry(right_dir)
    left_tags = left_doc["tags"]
    right_tags = right_doc["tags"]

    plan = []
    for name in sorted(set(left_tags) | set(right_tags)):
        left_schema = left_tags.get(name)
        right_schema = right_tags.get(name)

        if left_schema is not None:
            _validate_schema_file(left_dir, name, left_schema)
        if right_schema is not None:
            _validate_schema_file(right_dir, name, right_schema)

        if left_schema is not None and right_schema is not None:
            if _schema_core(left_schema) != _schema_core(right_schema):
                raise BWTTagError(
                    "tag %s has incompatible merge schemas" % name
                )
            schema = dict(left_schema)
            # Description is informational; preserve left unless absent.
            if (
                schema.get("description") is None
                and right_schema.get("description") is not None
            ):
                schema["description"] = right_schema["description"]
            plan.append(
                {
                    "name": name,
                    "schema": schema,
                    "left_present": True,
                    "right_present": True,
                }
            )
            continue

        schema = dict(left_schema or right_schema)
        if not schema.get("missing", {}).get("enabled", False):
            side = "right" if left_schema is not None else "left"
            raise BWTTagError(
                "tag %s is absent on %s input and has no declared "
                "missing value" % (name, side)
            )
        plan.append(
            {
                "name": name,
                "schema": schema,
                "left_present": left_schema is not None,
                "right_present": right_schema is not None,
            }
        )

    return plan


def _iter_interleave_chunks(
    interleave_path,
    total_rows,
    chunk_rows=8 * 1024 * 1024,
):
    """Yield little-endian interleave bits in bounded row chunks."""
    total_rows = int(total_rows)
    if total_rows < 0:
        raise ValueError("total_rows must be non-negative")
    if total_rows == 0:
        return

    chunk_rows = max(8, int(chunk_rows))
    chunk_rows -= chunk_rows % 8
    packed = np.load(
        str(interleave_path),
        mmap_mode="r",
        allow_pickle=False,
    )

    for start in range(0, total_rows, chunk_rows):
        end = min(start + chunk_rows, total_rows)
        byte_start = start // 8
        byte_end = (end + 7) // 8
        data = np.asarray(
            packed[byte_start:byte_end],
            dtype=np.uint8,
        )
        shifts = np.arange(8, dtype=np.uint8)
        bits = (
            (data[:, None] >> shifts[None, :])
            & np.uint8(1)
        ).reshape(-1)
        yield start, end, bits[: end - start]


def _missing_scalar(schema):
    missing = schema.get("missing", {})
    if not missing.get("enabled", False):
        raise BWTTagError("tag has no declared missing value")
    dtype = np.dtype(schema["dtype"])
    return _decode_scalar(missing["value"], dtype)


def _create_output_registry(output_dir, plan):
    doc = _empty_registry()
    for item in plan:
        name = item["name"]
        schema = dict(item["schema"])
        # Deterministic filename for the output tag name.
        schema["filename"] = _tag_filename(name)
        doc["tags"][name] = schema
    if plan:
        _write_registry(output_dir, doc)
    return doc


def merge_two_tag_arrays(
    left_dir,
    right_dir,
    output_dir,
    plan=None,
    chunk_rows=8 * 1024 * 1024,
):
    """Stable-interleave all compatible child tags into the output MSBWT."""
    left_dir = str(left_dir)
    right_dir = str(right_dir)
    output_dir = str(output_dir)

    if plan is None:
        plan = validate_tag_merge_compatibility(
            left_dir,
            right_dir,
        )
    if not plan:
        return BWTTagStore(output_dir, validate=True)

    left_len = _bwt_length(left_dir)
    right_len = _bwt_length(right_dir)
    total = left_len + right_len
    if _bwt_length(output_dir) != total:
        raise BWTTagError(
            "output BWT length does not equal child BWT total"
        )

    output_doc = _create_output_registry(output_dir, plan)
    out_tag_dir = tag_dir(output_dir)
    if not os.path.isdir(out_tag_dir):
        os.makedirs(out_tag_dir)

    left_store = BWTTagStore(left_dir, mmap=True, validate=True)
    right_store = BWTTagStore(right_dir, mmap=True, validate=True)

    outputs = {}
    left_arrays = {}
    right_arrays = {}
    for item in plan:
        name = item["name"]
        schema = output_doc["tags"][name]
        dtype = np.dtype(schema["dtype"])
        shape = (total,) + tuple(schema.get("tail_shape", []))
        outputs[name] = open_memmap(
            os.path.join(output_dir, str(schema["filename"])),
            mode="w+",
            dtype=dtype,
            shape=shape,
        )
        if item["left_present"]:
            left_arrays[name] = left_store.array(name)
        if item["right_present"]:
            right_arrays[name] = right_store.array(name)

    left_pos = 0
    right_pos = 0

    for start, end, bits in _iter_interleave_chunks(
        os.path.join(output_dir, INTERLEAVE_FILENAME),
        total,
        chunk_rows=chunk_rows,
    ):
        zero_mask = bits == 0
        one_mask = ~zero_mask
        n_left = int(np.count_nonzero(zero_mask))
        n_right = int(bits.shape[0] - n_left)

        for item in plan:
            name = item["name"]
            out = outputs[name]
            chunk = out[start:end]

            if item["left_present"]:
                chunk[zero_mask] = left_arrays[name][
                    left_pos: left_pos + n_left
                ]
            else:
                chunk[zero_mask] = _missing_scalar(item["schema"])

            if item["right_present"]:
                chunk[one_mask] = right_arrays[name][
                    right_pos: right_pos + n_right
                ]
            else:
                chunk[one_mask] = _missing_scalar(item["schema"])

        left_pos += n_left
        right_pos += n_right

    if left_pos != left_len or right_pos != right_len:
        raise BWTTagError(
            "interleave consumed child tag rows incorrectly: "
            "left %d/%d right %d/%d"
            % (left_pos, left_len, right_pos, right_len)
        )

    for out in outputs.values():
        out.flush()
    outputs.clear()

    return BWTTagStore(output_dir, mmap=True, validate=True)


def filter_tag_arrays(
    input_dir,
    output_dir,
    keep_mask,
    chunk_rows=8 * 1024 * 1024,
):
    """Filter all tags by the same Feature-10 BWT-row survival mask."""
    input_dir = str(input_dir)
    output_dir = str(output_dir)

    store = BWTTagStore(input_dir, mmap=True, validate=True)
    names = store.list_tags()
    if not names:
        return BWTTagStore(output_dir, validate=True)

    mask = np.asarray(keep_mask, dtype=np.bool_)
    if mask.ndim != 1 or mask.shape[0] != store.bwt_length:
        raise BWTTagError(
            "tag keep mask length does not match input BWT"
        )
    output_length = int(np.count_nonzero(mask))
    if _bwt_length(output_dir) != output_length:
        raise BWTTagError(
            "tag filter output length does not match output BWT"
        )

    doc = _empty_registry()
    outputs = {}
    arrays = {}

    for name in names:
        schema = store.schema(name)
        schema["filename"] = _tag_filename(name)
        doc["tags"][name] = schema
        dtype = np.dtype(schema["dtype"])
        shape = (output_length,) + tuple(
            schema.get("tail_shape", [])
        )
        out_path = os.path.join(output_dir, str(schema["filename"]))
        out_dir = os.path.dirname(out_path)
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        outputs[name] = open_memmap(
            str(out_path),
            mode="w+",
            dtype=dtype,
            shape=shape,
        )
        arrays[name] = store.array(name)

    write_pos = 0
    chunk_rows = max(1, int(chunk_rows))
    for start in range(0, store.bwt_length, chunk_rows):
        end = min(start + chunk_rows, store.bwt_length)
        local_mask = mask[start:end]
        count = int(np.count_nonzero(local_mask))
        if not count:
            continue
        for name in names:
            outputs[name][write_pos: write_pos + count] = (
                arrays[name][start:end][local_mask]
            )
        write_pos += count

    if write_pos != output_length:
        raise BWTTagError(
            "tag filter wrote %d rows, expected %d"
            % (write_pos, output_length)
        )

    for out in outputs.values():
        out.flush()
    outputs.clear()
    _write_registry(output_dir, doc)
    return BWTTagStore(output_dir, mmap=True, validate=True)


def _open_leaf_tag_value(value):
    """Open a supplied leaf tag array, mmap-ing .npy paths when possible.

    Python 2 registry round-trips produce unicode path strings, so both
    ``str`` and (on py2) ``unicode`` are treated as paths.
    """
    if isinstance(value, str) or (
        sys.version_info[0] == 2 and isinstance(value, unicode)  # noqa: F821
    ):
        return np.load(
            str(value),
            mmap_mode="r",
            allow_pickle=False,
        )
    return np.asarray(value)


def build_tag_from_leaf_arrays(
    merged_bwt_dir,
    name,
    arrays_by_source,
    description=None,
    missing_value=_MISSING_UNSET,
    overwrite=False,
    chunk_rows=8 * 1024 * 1024,
):
    """Retrofit one tag onto an already multi-merged package out-of-core.

    ``arrays_by_source`` maps stable source ID to either:

    * a NumPy array/memmap, or
    * a path to a ``.npy`` array.

    Each leaf array must be aligned to that source's standalone BWT rows.

    Internal provenance interleaves are replayed into temporary mmap-backed
    arrays.  The final root array is atomically installed into
    ``bwt_tags/`` without changing or re-merging ``msbwt.npy``.
    """
    merged_bwt_dir = str(merged_bwt_dir)
    name = _validate_name(name)
    manifest = load_manifest(merged_bwt_dir, validate=True)
    source_ids = [str(s["id"]) for s in manifest["sources"]]

    supplied = {
        str(k): v for k, v in arrays_by_source.items()
    }
    extra = sorted(set(supplied) - set(source_ids))
    if extra:
        raise BWTTagError(
            "tag %s supplied arrays for unknown sources %r"
            % (name, extra)
        )

    missing_sources = [
        sid for sid in source_ids if sid not in supplied
    ]
    if missing_sources and missing_value is _MISSING_UNSET:
        raise BWTTagError(
            "tag %s missing for sources %r without declared missing value"
            % (name, missing_sources)
        )

    exemplar = None
    for sid in source_ids:
        if sid in supplied:
            exemplar = _open_leaf_tag_value(supplied[sid])
            break
    if exemplar is None:
        raise BWTTagError("no leaf array supplied for tag %s" % name)

    schema = _schema_from_values(
        name,
        exemplar,
        description=description,
        missing_value=missing_value,
    )
    dtype = np.dtype(schema["dtype"])
    tail = tuple(schema["tail_shape"])

    leaf_arrays = {}
    for source in manifest["sources"]:
        sid = str(source["id"])
        expected = int(source["length"])

        if sid in supplied:
            arr = _open_leaf_tag_value(supplied[sid])
            _normalize_dtype(arr.dtype)
            if arr.dtype != dtype or tuple(arr.shape[1:]) != tail:
                raise BWTTagError(
                    "source %s tag %s schema mismatch"
                    % (sid, name)
                )
            if arr.shape[0] != expected:
                raise BWTTagError(
                    "source %s tag %s rows %d != source BWT length %d"
                    % (sid, name, arr.shape[0], expected)
                )
            leaf_arrays[sid] = arr
        else:
            leaf_arrays[sid] = None

    current_doc = _read_registry(merged_bwt_dir)
    if name in current_doc["tags"] and not overwrite:
        raise BWTTagError("tag already exists: %s" % name)

    temp_root = tempfile.mkdtemp(
        prefix=".point12-tag-%s-" % hashlib.sha256(
            _name_bytes(name)
        ).hexdigest()[:8],
        dir=merged_bwt_dir,
    )
    temp_paths = []

    def make_missing_leaf(sid, length):
        path = os.path.join(temp_root, "missing-%s.npy" % hashlib.sha256(
            _name_bytes(sid)
        ).hexdigest()[:12])
        arr = open_memmap(
            str(path),
            mode="w+",
            dtype=dtype,
            shape=(int(length),) + tail,
        )
        arr[...] = _missing_scalar(schema)
        arr.flush()
        del arr
        temp_paths.append(path)
        return np.load(
            str(path),
            mmap_mode="r",
            allow_pickle=False,
        )

    def build(node):
        if node["type"] == "leaf":
            sid = str(node["source_id"])
            arr = leaf_arrays[sid]
            if arr is None:
                arr = make_missing_leaf(
                    sid,
                    int(node["length"]),
                )
            return arr, None

        left, left_temp = build(node["left"])
        right, right_temp = build(node["right"])
        total = int(node["length"])

        path = os.path.join(temp_root, "%s.npy" % str(node["node_id"]))
        out = open_memmap(
            str(path),
            mode="w+",
            dtype=dtype,
            shape=(total,) + tail,
        )

        left_pos = 0
        right_pos = 0
        for start, end, bits in _iter_interleave_chunks(
            os.path.join(merged_bwt_dir, str(node["interleave"])),
            total,
            chunk_rows=chunk_rows,
        ):
            zero = bits == 0
            one = ~zero
            n_left = int(np.count_nonzero(zero))
            n_right = int(bits.shape[0] - n_left)

            chunk = out[start:end]
            if n_left:
                chunk[zero] = left[
                    left_pos: left_pos + n_left
                ]
            if n_right:
                chunk[one] = right[
                    right_pos: right_pos + n_right
                ]
            left_pos += n_left
            right_pos += n_right

        if (
            left_pos != int(node["left"]["length"])
            or right_pos != int(node["right"]["length"])
        ):
            raise BWTTagError(
                "retrofit interleave consumption mismatch at node %s"
                % node["node_id"]
            )

        out.flush()
        del out

        # Child temporary arrays are no longer needed after their merge.
        # Drop the memmap references first so Windows releases the locks.
        del left, right
        gc.collect()
        for child_temp in (left_temp, right_temp):
            if child_temp is not None and os.path.exists(child_temp):
                _remove_file_robust(child_temp)

        temp_paths.append(path)
        return (
            np.load(
                str(path),
                mmap_mode="r",
                allow_pickle=False,
            ),
            path,
        )

    try:
        root_array, root_temp = build(manifest["root"])

        # A one-source manifest returns the original leaf directly.  Copy it
        # chunkwise into a temporary .npy so installation remains uniform.
        if root_temp is None:
            root_temp = os.path.join(temp_root, "root.npy")
            out = open_memmap(
                str(root_temp),
                mode="w+",
                dtype=dtype,
                shape=root_array.shape,
            )
            chunk_rows = max(1, int(chunk_rows))
            for start in range(0, root_array.shape[0], chunk_rows):
                end = min(
                    start + chunk_rows,
                    root_array.shape[0],
                )
                out[start:end] = root_array[start:end]
            out.flush()
            del out

        final_schema = dict(schema)
        final_schema["filename"] = _tag_filename(name)
        final_path = os.path.join(merged_bwt_dir, final_schema["filename"])
        final_dir = os.path.dirname(final_path)
        if not os.path.isdir(final_dir):
            os.makedirs(final_dir)

        # If replacing, remove only the old tag's array after the new root
        # is completely built.
        old_schema = current_doc["tags"].get(name)
        if old_schema is not None:
            old_path = os.path.join(
                merged_bwt_dir, str(old_schema["filename"]))
            if os.path.exists(old_path) and os.path.abspath(
                    old_path) != os.path.abspath(final_path):
                _remove_file_robust(old_path)

        # Drop the root memmap reference so the rename is not blocked by
        # an open memory map (Windows).
        del root_array
        gc.collect()

        # rename is atomic within the same filesystem.
        _atomic_replace(str(root_temp), str(final_path))

        current_doc["tags"][name] = final_schema
        _write_registry(merged_bwt_dir, current_doc)

        # Validate final row alignment before reporting success.
        _validate_schema_file(
            merged_bwt_dir,
            name,
            final_schema,
            bwt_length=int(manifest["bwt_length"]),
        )
        return final_schema

    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def build_tags_from_leaf_arrays(
    merged_bwt_dir,
    tags,
    overwrite=False,
):
    """Retrofit multiple named tags.

    ``tags`` maps name -> dict with:
        arrays_by_source
        description (optional)
        missing_value (optional)
    """
    result = {}
    for name, spec in tags.items():
        kwargs = {
            "merged_bwt_dir": merged_bwt_dir,
            "name": name,
            "arrays_by_source": spec["arrays_by_source"],
            "description": spec.get("description"),
            "overwrite": overwrite,
        }
        if "missing_value" in spec:
            kwargs["missing_value"] = spec["missing_value"]
        result[name] = build_tag_from_leaf_arrays(**kwargs)
    return result
