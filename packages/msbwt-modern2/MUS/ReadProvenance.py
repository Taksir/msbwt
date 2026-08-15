"""Lossless read-level provenance for provenance-preserving merged MSBWTs
(Feature 9, enhanced-modern2).

Feature 9 stores one compact record per string/read, indexed by the MSBWT
"dollar ID" returned by ``BasicBWT.getSequenceDollarID``.

Design choice
-------------
Features 1-3 already make both of these derivable from a merged dollar row:

* stable source ID (Feature 2 provenance tree);
* source-local dollar/read ID (Feature 3 rank projection).

Feature 9 therefore does NOT duplicate them in the persistent record.  The
persistent read record stores only information that cannot be recovered from
the BWT/provenance tree:

    origin_file_id : uint32   4 bytes
    origin_read_id : uint64   8 bytes
    mate_dollar_id : uint64   8 bytes
    --------------------------
                             20 bytes/read

The NumPy dtype is packed (``align=False``) and exactly 20 bytes.  The file is
a normal ``read_provenance.npy`` (memory-mappable) accompanied by a small
``read_provenance.json`` carrying format/version, per-source metadata
(optional input-file name tables) and the identity binding to the current
BWT.

Central invariant
-----------------
For every BWT row ``x``::

    dollar_id = bwt.getSequenceDollarID(x)

identifies the logical read, and::

    read_provenance[dollar_id]

holds the exact metadata of that original read.  ``mate_dollar_id`` is
translated through every merge, so mate lookup is O(1) after provenance
decoding of the returned row.

Merge ordering
--------------
For a two-way Holt/McMillan merge, the first ``R_left + R_right`` rows of the
merged suffix/BWT order are exactly the child ``$`` rows (``$`` is the
smallest symbol), and the first ``R_left + R_right`` bits of the final
``inter0.npy`` describe how the two child dollar-row orders were interleaved.
Feature 9 stable-merges the two child read-provenance arrays according to
that prefix; no second per-symbol read-identity array is needed.  The BWT
itself is unchanged.

Persistence classification
--------------------------
- ``read_provenance.npy``     AUTHORITATIVE (read identity; see below).
- ``read_provenance.json``    AUTHORITATIVE metadata (format/version,
  identity binding, optional input-file tables).

The JSON carries ``bwt_sha256`` equal to the validated ``provenance.json``
``msbwt_sha256`` of the current BWT, so a same-length stale/copied
read-provenance pair from another index can never silently produce wrong read
identity: every load validates format, version, record size, read count
against the BWT ``$`` row count, source metadata against the provenance
manifest, and the BWT identity binding.  Any inconsistency raises
``ReadProvenanceError``; there is no silent acceptance path.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""

from __future__ import absolute_import

import json
import os
import struct
import sys

import numpy as np

from MUS.MultiSourceProvenance import (
    BWT_FILENAME,
    INTERLEAVE_FILENAME,
    load_manifest,
)


READ_PROVENANCE_FILENAME = "read_provenance.npy"
READ_PROVENANCE_META_FILENAME = "read_provenance.json"
FORMAT_NAME = "msbwt-read-provenance"
FORMAT_VERSION = 1

UINT32_UNKNOWN = np.iinfo(np.uint32).max
UINT64_UNKNOWN = np.iinfo(np.uint64).max

READ_DTYPE = np.dtype(
    [
        ("origin_file_id", "<u4"),
        ("origin_read_id", "<u8"),
        ("mate_dollar_id", "<u8"),
    ],
    align=False,
)

if READ_DTYPE.itemsize != 20:
    raise RuntimeError("Feature-9 read provenance dtype must remain 20 bytes")


class ReadProvenanceError(ValueError):
    """Raised when read-provenance data are missing or inconsistent."""


def _atomic_write_json(path, document):
    """Write a JSON document atomically: tmp file -> flush -> rename.

    Matches the MultiSourceProvenance/SourceMetadata pattern: serialized with
    ASCII escapes, binary mode, so the same code path works on Python 2.7
    (str) and Python 3 (encoded bytes).
    """
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
            # best-effort durability; the rename is still atomic
            pass
    if hasattr(os, "replace"):
        os.replace(tmp_path, path)
    else:
        os.rename(tmp_path, path)


def read_provenance_path(bwt_dir):
    return os.path.join(str(bwt_dir), READ_PROVENANCE_FILENAME)


def read_provenance_meta_path(bwt_dir):
    return os.path.join(str(bwt_dir), READ_PROVENANCE_META_FILENAME)


def read_provenance_exists(bwt_dir):
    return (
        os.path.exists(read_provenance_path(bwt_dir))
        and os.path.exists(read_provenance_meta_path(bwt_dir))
    )


def _count_dollars(bwt_dir):
    path = os.path.join(str(bwt_dir), BWT_FILENAME)
    if not os.path.exists(path):
        raise ReadProvenanceError("missing uncompressed BWT: %s" % path)
    bwt = np.load(path, mmap_mode="r")
    if bwt.ndim != 1:
        raise ReadProvenanceError("msbwt.npy must be one-dimensional")
    # Holt's hard-coded alphabet uses numeric symbol 0 for '$'.
    return int(np.count_nonzero(bwt == 0))


def _bwt_identity_sha256(bwt_dir, manifest):
    """Identity binding for the current BWT from the validated manifest.

    ``load_manifest(..., validate=True)`` already recomputes the content
    digest of ``msbwt.npy``, so no extra hashing is performed here.
    """
    value = manifest.get("msbwt_sha256")
    if value is None:
        raise ReadProvenanceError(
            "provenance manifest has no msbwt_sha256 identity field"
        )
    return str(value)


def _npy_payload_offset(path):
    """Byte offset of the array payload inside an .npy file.

    The .npy format is stable: 6-byte magic, version byte pair, header
    length (uint16 for major version 1, uint32 for major version 2+),
    header text, then the raw array bytes.  This lets us reject truncated
    or trailing-garbage array files loudly instead of discovering the
    truncation at first element access (memory-mapped reads past EOF are
    undefined behavior).
    """
    with open(path, "rb") as fp:
        magic = fp.read(8)
    if magic[:6] != b"\x93NUMPY":
        raise ReadProvenanceError("not a .npy file: %s" % path)
    # ord(bytes-slice) is the Python-2/3-neutral way to read one byte value.
    major = ord(magic[6:7])
    if major == 1:
        with open(path, "rb") as fp:
            fp.seek(8)
            header_len = struct.unpack("<H", fp.read(2))[0]
        return 8 + 2 + header_len
    with open(path, "rb") as fp:
        fp.seek(8)
        header_len = struct.unpack("<I", fp.read(4))[0]
    return 8 + 4 + header_len


def _verify_npy_exact_size(path, records):
    expected = _npy_payload_offset(path) + int(records.size * records.itemsize)
    actual = os.path.getsize(path)
    if actual != expected:
        raise ReadProvenanceError(
            "read provenance file has unexpected size: %s "
            "(expected %d bytes for %d records, found %d; truncated or "
            "tampered array)"
            % (path, expected, int(records.size), actual)
        )


def _unpack_prefix_bits(interleave_path, count):
    count = int(count)
    if count < 0:
        raise ValueError("count must be non-negative")
    if count == 0:
        return np.empty(0, dtype=np.uint8)

    packed = np.load(interleave_path, mmap_mode="r")
    if packed.ndim != 1 or packed.dtype != np.dtype("uint8"):
        raise ReadProvenanceError(
            "interleave must be one-dimensional uint8: %s" % interleave_path
        )

    needed = (count + 7) // 8
    if packed.shape[0] < needed:
        raise ReadProvenanceError(
            "interleave too short for %d prefix bits: %s"
            % (count, interleave_path)
        )

    used = np.asarray(packed[:needed], dtype=np.uint8)
    shifts = np.arange(8, dtype=np.uint8)
    bits = ((used[:, None] >> shifts[None, :]) & np.uint8(1)).reshape(-1)
    return bits[:count]


def _as_u32(value):
    if value is None:
        return np.uint32(UINT32_UNKNOWN)
    value = int(value)
    if value < 0:
        return np.uint32(UINT32_UNKNOWN)
    if value >= int(UINT32_UNKNOWN):
        raise ValueError("uint32 provenance field out of range: %d" % value)
    return np.uint32(value)


def _as_u64(value):
    if value is None:
        return np.uint64(UINT64_UNKNOWN)
    value = int(value)
    if value < 0:
        return np.uint64(UINT64_UNKNOWN)
    if value >= int(UINT64_UNKNOWN):
        raise ValueError("uint64 provenance field out of range: %d" % value)
    return np.uint64(value)


def _unknown_to_none(value, unknown):
    value = int(value)
    if value == int(unknown):
        return None
    return value


class _ReadTable(object):
    def __init__(self, records, source_metadata=None):
        # Preserve np.memmap subclasses when loading the on-disk table.
        if not isinstance(records, np.ndarray):
            records = np.asarray(records)
        if records.dtype != READ_DTYPE:
            records = np.asarray(records, dtype=READ_DTYPE)
        if records.ndim != 1:
            raise ReadProvenanceError(
                "read provenance must be one-dimensional"
            )
        self.records = records
        self.source_metadata = {
            str(k): dict(v)
            for k, v in (source_metadata or {}).items()
        }

    @property
    def read_count(self):
        return int(self.records.shape[0])


def _save_table(bwt_dir, table):
    bwt_dir = str(bwt_dir)
    manifest = load_manifest(bwt_dir, validate=True)
    known_sources = {str(s["id"]) for s in manifest["sources"]}
    extra_metadata = sorted(set(table.source_metadata) - known_sources)
    if extra_metadata:
        raise ReadProvenanceError(
            "read metadata references unknown sources: %s"
            % ", ".join(extra_metadata)
        )

    expected_reads = _count_dollars(bwt_dir)
    if table.read_count != expected_reads:
        raise ReadProvenanceError(
            "read-provenance count %d != number of '$' rows %d"
            % (table.read_count, expected_reads)
        )

    np.save(
        read_provenance_path(bwt_dir),
        np.asarray(table.records, dtype=READ_DTYPE),
    )

    metadata = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "read_count": table.read_count,
        "record_bytes": READ_DTYPE.itemsize,
        "bwt_sha256": _bwt_identity_sha256(bwt_dir, manifest),
        "source_metadata": table.source_metadata,
        "ordering": "msbwt-dollar-id",
        "fields": [
            "origin_file_id",
            "origin_read_id",
            "mate_dollar_id",
        ],
    }
    _atomic_write_json(read_provenance_meta_path(bwt_dir), metadata)
    return metadata


def _load_table(bwt_dir, mmap=True, validate=True):
    bwt_dir = str(bwt_dir)
    data_path = read_provenance_path(bwt_dir)
    meta_path = read_provenance_meta_path(bwt_dir)
    if not os.path.exists(data_path) or not os.path.exists(meta_path):
        raise ReadProvenanceError(
            "read provenance not found in %s" % bwt_dir
        )

    try:
        with open(meta_path, "rb") as fp:
            metadata = json.load(fp)
    except ValueError as exc:
        raise ReadProvenanceError(
            "read provenance metadata is not valid JSON: %s: %s"
            % (meta_path, exc)
        )
    if metadata.get("format") != FORMAT_NAME:
        raise ReadProvenanceError("unsupported read provenance format")
    if int(metadata.get("version", -1)) != FORMAT_VERSION:
        raise ReadProvenanceError("unsupported read provenance version")
    if metadata.get("ordering") != "msbwt-dollar-id":
        raise ReadProvenanceError("unsupported read provenance ordering")
    if int(metadata.get("record_bytes", -1)) != READ_DTYPE.itemsize:
        raise ReadProvenanceError("unexpected read provenance record size")

    mmap_mode = "r" if mmap else None
    try:
        records = np.load(data_path, mmap_mode=mmap_mode)
    except (ValueError, OSError, IOError) as exc:
        # corrupt/truncated .npy (bad header or mmap length beyond EOF;
        # Windows raises OSError, POSIX/NumPy ValueError) must fail loudly
        # as read-provenance corruption, never silently.
        raise ReadProvenanceError(
            "cannot load read provenance array %s: %s" % (data_path, exc)
        )
    if records.dtype != READ_DTYPE:
        raise ReadProvenanceError(
            "unexpected read provenance dtype: %r" % (records.dtype,)
        )
    # Memory mapping defers I/O: verify the on-disk file length now so a
    # truncated or tampered array fails loudly at load time instead of
    # surfacing as undefined behavior on later element access.
    _verify_npy_exact_size(data_path, records)

    table = _ReadTable(
        records,
        source_metadata=metadata.get("source_metadata", {}),
    )
    if int(metadata.get("read_count", -1)) != table.read_count:
        raise ReadProvenanceError(
            "read count mismatch between NPY and JSON metadata"
        )

    if validate:
        manifest = load_manifest(bwt_dir, validate=True)
        known_sources = {str(s["id"]) for s in manifest["sources"]}
        if not set(table.source_metadata).issubset(known_sources):
            raise ReadProvenanceError(
                "read metadata references source absent from "
                "provenance.json"
            )
        if table.read_count != _count_dollars(bwt_dir):
            raise ReadProvenanceError(
                "read provenance length differs from '$' count"
            )
        if metadata.get("bwt_sha256") != _bwt_identity_sha256(
            bwt_dir, manifest
        ):
            raise ReadProvenanceError(
                "read provenance identity does not match the current BWT "
                "(copied/stale read_provenance array from another index)"
            )

    return table


def _leaf_source_id(bwt_dir):
    manifest = load_manifest(bwt_dir, validate=True)
    if len(manifest["sources"]) != 1 or manifest["root"]["type"] != "leaf":
        raise ReadProvenanceError(
            "leaf read provenance requires a single-source MSBWT"
        )
    return str(manifest["sources"][0]["id"])


def _records_to_leaf_table(source_id, records, source_metadata=None):
    records = list(records)
    n = len(records)
    arr = np.empty(n, dtype=READ_DTYPE)

    for i, record in enumerate(records):
        record = dict(record)
        local_id = int(record.get("source_read_id", i))
        if local_id != i:
            raise ReadProvenanceError(
                "leaf records must be supplied in local dollar-ID order; "
                "record %d has source_read_id=%d" % (i, local_id)
            )

        arr["origin_file_id"][i] = _as_u32(record.get("origin_file_id"))
        arr["origin_read_id"][i] = _as_u64(record.get("origin_read_id"))

        mate_local = record.get("mate_source_read_id")
        if mate_local is None:
            arr["mate_dollar_id"][i] = np.uint64(UINT64_UNKNOWN)
        else:
            mate_local = int(mate_local)
            if mate_local < 0 or mate_local >= n:
                raise ReadProvenanceError(
                    "mate_source_read_id %d outside [0,%d)"
                    % (mate_local, n)
                )
            # In a single-source leaf, local dollar ID == global dollar ID.
            arr["mate_dollar_id"][i] = np.uint64(mate_local)

    return _ReadTable(
        arr,
        source_metadata={
            str(source_id): dict(source_metadata or {})
        },
    )


def initialize_leaf_read_provenance(
    bwt_dir,
    records,
    source_metadata=None,
    overwrite=False,
):
    """Initialize a one-source MSBWT from records in local dollar-ID order."""
    bwt_dir = str(bwt_dir)
    if read_provenance_exists(bwt_dir) and not overwrite:
        return ReadProvenanceIndex(bwt_dir)

    source_id = _leaf_source_id(bwt_dir)
    table = _records_to_leaf_table(
        source_id,
        records,
        source_metadata=source_metadata,
    )
    _save_table(bwt_dir, table)
    return ReadProvenanceIndex(bwt_dir)


def _parse_about_array(about):
    """Return list of (file_id, read_id) from legacy about.npy layouts."""
    names = about.dtype.names
    if names:
        if about.ndim != 1 or len(names) < 2:
            raise ReadProvenanceError(
                "legacy about.npy structured dtype needs two fields"
            )
        f0, f1 = names[:2]
        return [(int(row[f0]), int(row[f1])) for row in about]

    arr = np.asarray(about)
    if arr.ndim == 2 and arr.shape[1] >= 2:
        return [(int(row[0]), int(row[1])) for row in arr]

    raise ReadProvenanceError(
        "unrecognized legacy about.npy layout: %r" % (about.dtype,)
    )


def initialize_leaf_read_provenance_from_about(
    bwt_dir,
    input_files=None,
    overwrite=False,
):
    """Import Holt's legacy ``about.npy`` into Feature-9 provenance.

    Current Holt preprocessing writes ``about.npy`` in the same sorted-string
    order used for BWT construction.  Feature 9 uses that as local dollar-ID
    order.

    Legacy ``about.npy`` does not contain file names, only numeric file IDs.
    ``input_files`` optionally restores that lookup table.
    """
    bwt_dir = str(bwt_dir)
    about_path = os.path.join(bwt_dir, "about.npy")
    if not os.path.exists(about_path):
        raise ReadProvenanceError(
            "legacy about.npy not found: %s" % about_path
        )

    about = np.load(about_path, mmap_mode="r")
    parsed = _parse_about_array(about)
    records = [
        {
            "source_read_id": i,
            "origin_file_id": file_id,
            "origin_read_id": read_id,
        }
        for i, (file_id, read_id) in enumerate(parsed)
    ]
    metadata = {}
    if input_files is not None:
        metadata["input_files"] = [str(x) for x in input_files]

    return initialize_leaf_read_provenance(
        bwt_dir,
        records,
        source_metadata=metadata,
        overwrite=overwrite,
    )


def _merge_tables(left, right, bits):
    n_left = left.read_count
    n_right = right.read_count
    total = n_left + n_right
    bits = np.asarray(bits, dtype=np.uint8)
    if bits.ndim != 1 or bits.shape[0] != total:
        raise ReadProvenanceError(
            "read interleave length %d != child read total %d"
            % (bits.shape[0], total)
        )

    ones = int(bits.sum(dtype=np.uint64))
    zeros = total - ones
    if zeros != n_left or ones != n_right:
        raise ReadProvenanceError(
            "read interleave child counts mismatch: "
            "zeros=%d expected=%d, ones=%d expected=%d"
            % (zeros, n_left, ones, n_right)
        )

    left_positions = np.flatnonzero(bits == 0).astype(np.uint64)
    right_positions = np.flatnonzero(bits == 1).astype(np.uint64)

    out = np.empty(total, dtype=READ_DTYPE)
    out[left_positions] = left.records
    out[right_positions] = right.records

    # Translate child-local/global dollar IDs for mate references into output
    # dollar IDs.  Mate relationships are kept within their source dataset.
    left_mates = np.asarray(left.records["mate_dollar_id"], dtype=np.uint64)
    right_mates = np.asarray(right.records["mate_dollar_id"], dtype=np.uint64)

    for child_records, child_positions, child_mates in (
        (left.records, left_positions, left_mates),
        (right.records, right_positions, right_mates),
    ):
        known = child_mates != np.uint64(UINT64_UNKNOWN)
        if np.any(known):
            mate_indices = child_mates[known]
            if int(mate_indices.max()) >= child_records.shape[0]:
                raise ReadProvenanceError(
                    "child mate dollar ID outside child read range"
                )
            output_rows = child_positions[np.flatnonzero(known)]
            out["mate_dollar_id"][output_rows] = child_positions[
                mate_indices.astype(np.intp)
            ]

    metadata = {}
    for table in (left, right):
        for sid, record in table.source_metadata.items():
            metadata[str(sid)] = dict(record)

    return _ReadTable(out, source_metadata=metadata)


def merge_two_read_provenance(left_dir, right_dir, output_dir):
    """Merge child read provenance using the output root interleave prefix."""
    left = _load_table(left_dir, mmap=True, validate=True)
    right = _load_table(right_dir, mmap=True, validate=True)
    output_dir = str(output_dir)

    total_reads = left.read_count + right.read_count
    bits = _unpack_prefix_bits(
        os.path.join(output_dir, INTERLEAVE_FILENAME),
        total_reads,
    )
    merged = _merge_tables(left, right, bits)
    _save_table(output_dir, merged)
    return ReadProvenanceIndex(output_dir)


def _leaf_read_counts_from_tree(merged_bwt_dir):
    from MUS.MultiSourceQuery import MultiSourceQueryIndex

    merged_bwt_dir = str(merged_bwt_dir)
    total_reads = _count_dollars(merged_bwt_dir)
    index = MultiSourceQueryIndex(
        merged_bwt_dir,
        mmap=True,
        use_saved_rank=True,
    )
    result = {}
    for source in index.list_sources():
        sid = str(source["id"])
        low, high = index.project_interval(
            sid,
            0,
            total_reads,
        )
        result[sid] = int(high - low)
    return result


def build_read_provenance_from_leaf_records(
    merged_bwt_dir,
    records_by_source,
    source_metadata_by_source=None,
    overwrite=False,
):
    """Retrofit a finished multi-merged MSBWT without re-merging it.

    Replays only the saved provenance interleaves (the first
    ``left_reads + right_reads`` bits at every merge node), never the BWT
    merge itself.  The BWT and ``provenance.json`` bytes are unchanged.
    """
    merged_bwt_dir = str(merged_bwt_dir)
    if read_provenance_exists(merged_bwt_dir) and not overwrite:
        return ReadProvenanceIndex(merged_bwt_dir)

    manifest = load_manifest(merged_bwt_dir, validate=True)
    source_ids = [str(s["id"]) for s in manifest["sources"]]
    records_by_source = {
        str(k): list(v) for k, v in records_by_source.items()
    }
    metadata_by_source = {
        str(k): dict(v)
        for k, v in (source_metadata_by_source or {}).items()
    }

    missing = [sid for sid in source_ids if sid not in records_by_source]
    extra = sorted(set(records_by_source) - set(source_ids))
    if missing or extra:
        raise ReadProvenanceError(
            "leaf record source mismatch; missing=%r extra=%r"
            % (missing, extra)
        )

    expected_counts = _leaf_read_counts_from_tree(merged_bwt_dir)
    leaf_tables = {}
    for sid in source_ids:
        table = _records_to_leaf_table(
            sid,
            records_by_source[sid],
            source_metadata=metadata_by_source.get(sid, {}),
        )
        if table.read_count != expected_counts[sid]:
            raise ReadProvenanceError(
                "source %s has %d read records but provenance projects %d "
                "'$' rows"
                % (sid, table.read_count, expected_counts[sid])
            )
        leaf_tables[sid] = table

    def build(node):
        if node["type"] == "leaf":
            return leaf_tables[str(node["source_id"])]

        left = build(node["left"])
        right = build(node["right"])
        total_reads = left.read_count + right.read_count
        bits = _unpack_prefix_bits(
            os.path.join(merged_bwt_dir, str(node["interleave"])),
            total_reads,
        )
        return _merge_tables(left, right, bits)

    table = build(manifest["root"])
    _save_table(merged_bwt_dir, table)
    return ReadProvenanceIndex(merged_bwt_dir)


def retrofit_read_provenance_from_leaf_dirs(
    merged_bwt_dir,
    leaf_dirs_by_source,
    input_files_by_source=None,
    overwrite=False,
):
    """Retrofit final read provenance from original leaf directories.

    Each leaf directory may already carry Feature-9 read provenance (used
    directly, including its source metadata) or the legacy ``about.npy``
    (parsed as numeric file ID / read ID pairs; ``input_files_by_source``
    optionally restores the filename table).
    """
    merged_bwt_dir = str(merged_bwt_dir)
    manifest = load_manifest(merged_bwt_dir, validate=True)
    source_ids = [str(s["id"]) for s in manifest["sources"]]
    leaf_dirs_by_source = {
        str(k): str(v) for k, v in leaf_dirs_by_source.items()
    }

    records_by_source = {}
    metadata_by_source = {}

    for sid in source_ids:
        if sid not in leaf_dirs_by_source:
            raise ReadProvenanceError(
                "missing leaf directory for source %s" % sid
            )
        leaf_dir = leaf_dirs_by_source[sid]

        if read_provenance_exists(leaf_dir):
            leaf_index = ReadProvenanceIndex(leaf_dir)
            records = []
            for local_id in range(leaf_index.read_count):
                record = leaf_index.record(local_id)
                records.append(
                    {
                        "source_read_id": local_id,
                        "origin_file_id": record["origin_file_id"],
                        "origin_read_id": record["origin_read_id"],
                        "mate_source_read_id": (
                            None
                            if record["mate_dollar_id"] is None
                            else int(record["mate_dollar_id"])
                        ),
                    }
                )
            records_by_source[sid] = records
            metadata_by_source[sid] = leaf_index.source_metadata(sid)
            continue

        about_path = os.path.join(leaf_dir, "about.npy")
        if not os.path.exists(about_path):
            raise ReadProvenanceError(
                "source %s has neither Feature-9 provenance nor about.npy"
                % sid
            )
        about = np.load(about_path, mmap_mode="r")
        parsed = _parse_about_array(about)
        records_by_source[sid] = [
            {
                "source_read_id": i,
                "origin_file_id": file_id,
                "origin_read_id": read_id,
            }
            for i, (file_id, read_id) in enumerate(parsed)
        ]
        metadata_by_source[sid] = {}
        if input_files_by_source is not None:
            files = input_files_by_source.get(sid)
            if files is not None:
                metadata_by_source[sid]["input_files"] = [
                    str(x) for x in files
                ]

    return build_read_provenance_from_leaf_records(
        merged_bwt_dir,
        records_by_source,
        source_metadata_by_source=metadata_by_source,
        overwrite=overwrite,
    )


class ReadProvenanceIndex(object):
    """Read identity lookup by merged MSBWT dollar ID."""

    def __init__(
        self,
        bwt_dir,
        mmap=True,
        validate=True,
        source_index=None,
    ):
        self.bwt_dir = str(bwt_dir)
        self.table = _load_table(
            self.bwt_dir,
            mmap=mmap,
            validate=validate,
        )
        self.manifest = load_manifest(self.bwt_dir, validate=True)
        self._sources = {
            str(source["id"]): dict(source)
            for source in self.manifest["sources"]
        }
        self._source_ids_by_name = {}
        for sid, record in self._sources.items():
            name = str(record.get("name", sid))
            self._source_ids_by_name.setdefault(name, []).append(sid)

        if source_index is None:
            from MUS.MultiSourceQuery import MultiSourceQueryIndex

            source_index = MultiSourceQueryIndex(
                self.bwt_dir,
                mmap=mmap,
                use_saved_rank=True,
            )
        self.source_index = source_index
        self._local_to_global = None

    @property
    def read_count(self):
        return self.table.read_count

    @staticmethod
    def record_bytes():
        return READ_DTYPE.itemsize

    def _resolve_source(self, source):
        source = str(source)
        if source in self._sources:
            return source
        matches = self._source_ids_by_name.get(source, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError("ambiguous source name: %s" % source)
        raise KeyError("unknown source: %s" % source)

    def source_read_count(self, source):
        sid = self._resolve_source(source)
        low, high = self.source_index.project_interval(
            sid,
            0,
            self.read_count,
        )
        return int(high - low)

    def record(self, dollar_id):
        dollar_id = int(dollar_id)
        if dollar_id < 0 or dollar_id >= self.read_count:
            raise IndexError(
                "dollar ID %d outside [0,%d)"
                % (dollar_id, self.read_count)
            )

        sid, local_read_id = self.source_index.locate_row_source(dollar_id)
        row = self.table.records[dollar_id]

        record = {
            "dollar_id": dollar_id,
            "source_id": sid,
            "source_name": str(self._sources[sid].get("name", sid)),
            "source_read_id": int(local_read_id),
            "origin_file_id": _unknown_to_none(
                row["origin_file_id"],
                UINT32_UNKNOWN,
            ),
            "origin_read_id": _unknown_to_none(
                row["origin_read_id"],
                UINT64_UNKNOWN,
            ),
            "mate_dollar_id": _unknown_to_none(
                row["mate_dollar_id"],
                UINT64_UNKNOWN,
            ),
        }
        record["paired"] = record["mate_dollar_id"] is not None

        source_metadata = self.table.source_metadata.get(sid, {})
        input_files = source_metadata.get("input_files")
        if (
            input_files is not None
            and record["origin_file_id"] is not None
            and 0 <= record["origin_file_id"] < len(input_files)
        ):
            record["origin_file"] = str(
                input_files[record["origin_file_id"]]
            )
        else:
            record["origin_file"] = None

        return record

    def records(self, dollar_ids):
        return [self.record(i) for i in dollar_ids]

    def _build_local_to_global(self):
        mapping = {}
        for dollar_id in range(self.read_count):
            sid, local = self.source_index.locate_row_source(dollar_id)
            key = (sid, int(local))
            if key in mapping:
                raise ReadProvenanceError(
                    "duplicate source/local read identity: %r" % (key,)
                )
            mapping[key] = dollar_id
        self._local_to_global = mapping

    def find_dollar_id(self, source, source_read_id):
        sid = self._resolve_source(source)
        if self._local_to_global is None:
            self._build_local_to_global()
        key = (sid, int(source_read_id))
        if key not in self._local_to_global:
            raise KeyError(
                "unknown source/local read identity: %r" % (key,)
            )
        return int(self._local_to_global[key])

    def mate(self, dollar_id):
        record = self.record(dollar_id)
        mate_dollar = record["mate_dollar_id"]
        if mate_dollar is None:
            return None
        return self.record(mate_dollar)

    def source_metadata(self, source):
        sid = self._resolve_source(source)
        return dict(self.table.source_metadata.get(sid, {}))


def filter_read_provenance(
    input_bwt_dir,
    output_bwt_dir,
    keep_dollar_mask,
):
    """Filter Feature-9 read provenance to surviving merged dollar rows.

    ``keep_dollar_mask`` is aligned to the *input* MSBWT dollar-ID order.
    Output records preserve that stable relative order.  Global mate dollar
    IDs are translated into the output dollar-ID space; mates whose partner
    was removed become ``UINT64_UNKNOWN`` (unpaired).

    Source/local read identity is not rewritten here because Feature 9
    derives it from the output provenance tree (Feature 10's filtered
    tree).

    The output table is re-validated against the output package (read
    count vs ``$`` rows, source metadata vs the output manifest, and the
    output BWT identity binding), so a wrong mask can never silently
    produce a mismatched table.
    """
    input_bwt_dir = str(input_bwt_dir)
    output_bwt_dir = str(output_bwt_dir)

    table = _load_table(
        input_bwt_dir,
        mmap=True,
        validate=True,
    )
    mask = np.asarray(keep_dollar_mask, dtype=np.bool_)
    if mask.ndim != 1 or mask.shape[0] != table.read_count:
        raise ReadProvenanceError(
            "keep_dollar_mask length %d != input read count %d"
            % (
                mask.shape[0] if mask.ndim == 1 else -1,
                table.read_count,
            )
        )

    kept_old_ids = np.flatnonzero(mask).astype(np.int64)
    old_to_new = np.full(table.read_count, -1, dtype=np.int64)
    old_to_new[kept_old_ids] = np.arange(
        kept_old_ids.shape[0],
        dtype=np.int64,
    )

    output_records = np.asarray(
        table.records[mask],
        dtype=READ_DTYPE,
    ).copy()

    mates = np.asarray(
        output_records["mate_dollar_id"],
        dtype=np.uint64,
    )
    known = mates != np.uint64(UINT64_UNKNOWN)
    if np.any(known):
        old_mates = mates[known].astype(np.int64)
        if (
            int(old_mates.min()) < 0
            or int(old_mates.max()) >= table.read_count
        ):
            raise ReadProvenanceError(
                "input mate dollar ID outside input read range"
            )

        translated = old_to_new[old_mates]
        output_values = np.full(
            translated.shape[0],
            np.uint64(UINT64_UNKNOWN),
            dtype=np.uint64,
        )
        survive = translated >= 0
        output_values[survive] = translated[survive].astype(
            np.uint64
        )
        output_records["mate_dollar_id"][known] = output_values

    output_manifest = load_manifest(
        output_bwt_dir,
        validate=True,
    )
    kept_source_ids = {
        str(source["id"])
        for source in output_manifest["sources"]
    }
    output_metadata = {
        sid: dict(record)
        for sid, record in table.source_metadata.items()
        if sid in kept_source_ids
    }

    output_table = _ReadTable(
        output_records,
        source_metadata=output_metadata,
    )
    _save_table(output_bwt_dir, output_table)
