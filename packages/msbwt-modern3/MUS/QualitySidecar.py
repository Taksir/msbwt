"""Q1 - exact lossless FASTQ quality sidecar for msBWT
(enhanced-modern2, implemented as a strict Point-12 specialization).

The sidecar is implemented as a reserved Point-12 uint8 tag:

    fastq_quality_ascii

Alignment
---------
For the suffix/BWT row whose suffix starts at read position ``p``:

    quality[row] = original FASTQ quality byte at p

The terminal ``$`` suffix row stores 255.

This is intentionally *suffix-start-row* alignment rather than
"preceding BWT-symbol" alignment.  Holt's
``recoverString(..., withIndex=True)`` returns the suffix-row path in
original read order, so exact quality recovery requires one ordinary read
recovery traversal and direct tag gathers.

Storage semantics
-----------------
The values are stored through Point 12 in ``bwt_tags/*.npy`` under the
reserved tag name; ``quality_sidecar.json`` records the semantic contract.
No Phred conversion is performed; quality bytes are preserved exactly as
they appear on the FASTQ quality line, excluding the line terminator.
``255`` is a reserved terminal-sentinel marker only - it is NOT a
Point-12 missing-value declaration, because one-sided quality merges must
fail rather than synthesize quality.

Scope honesty
-------------
Q1 preserves exactly: sequence, quality line, and (with Feature 9) origin
file/read identity.  FASTQ header text is not preserved; a byte-for-byte
recreation of the complete original FASTQ file including arbitrary headers
is outside Q1.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""


import gzip
import json
import os
import shutil
import struct
import sys
import tempfile

import numpy as np
from numpy.lib.format import open_memmap

from MUS.BWTTags import (
    BWTTagError,
    BWTTagStore,
    attach_tag,
    build_tag_from_leaf_arrays,
    tags_exist,
)
from MUS.MultiSourceProvenance import (
    BWT_FILENAME,
    load_manifest,
)
from MUS.ReadProvenance import (
    ReadProvenanceIndex,
    read_provenance_exists,
)


QUALITY_META_FILENAME = "quality_sidecar.json"
QUALITY_TAG_NAME = "fastq_quality_ascii"
QUALITY_DTYPE = np.dtype("uint8")
NO_QUALITY = np.uint8(255)
FORMAT_NAME = "msbwt-fastq-quality-sidecar"
FORMAT_VERSION = 1
ALIGNMENT = "suffix-first-base"
ENCODING = "raw-fastq-quality-byte"


def _release_memmap(obj):
    """M3-R64-W1 (R-Q): flush and close a memmap's underlying handle.

    On Windows, deleting a file fails while any memory mapping over it is
    open; quality-build temporaries are removed with shutil.rmtree(), so
    every mapping must be explicitly released beforehand.
    """
    if obj is None:
        return
    try:
        flush = getattr(obj, "flush", None)
        if callable(flush):
            flush()
    except Exception:
        pass
    mmap_handle = getattr(obj, "_mmap", None)
    if mmap_handle is not None:
        try:
            mmap_handle.close()
        except Exception:
            pass


class QualitySidecarError(ValueError):
    """Raised for invalid, incomplete, or inconsistent quality sidecars."""


def _atomic_write_json(path, document):
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
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
    elif os.name == "nt" and os.path.exists(path):
        os.remove(path)
        os.rename(tmp_path, path)
    else:
        os.rename(tmp_path, path)


def _one_byte(value):
    """One-byte string for a byte value."""
    return bytes([value])


def _is_dollar_symbol(symbol):
    """True when ``symbol`` is the '$' terminator byte.

    Python 2 iterates ``str`` as 1-char strings; Python 3 iterates
    ``bytes`` as ints.
    """
    if isinstance(symbol, int):
        return symbol == ord("$")
    return symbol == "$"


def quality_meta_path(bwt_dir):
    return os.path.join(str(bwt_dir), QUALITY_META_FILENAME)


def _bwt_length_and_read_count(bwt_dir):
    path = os.path.join(str(bwt_dir), BWT_FILENAME)
    if not os.path.exists(path):
        raise QualitySidecarError("missing BWT: %s" % path)
    bwt = np.load(path, mmap_mode="r", allow_pickle=False)
    if bwt.ndim != 1:
        raise QualitySidecarError("msbwt.npy must be one-dimensional")
    return int(bwt.shape[0]), int(np.count_nonzero(bwt == 0))


def _base_metadata(bwt_dir, input_files=None, builder=None):
    bwt_dir = str(bwt_dir)
    manifest = load_manifest(bwt_dir, validate=True)
    bwt_rows, read_count = _bwt_length_and_read_count(bwt_dir)
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "tag_name": QUALITY_TAG_NAME,
        "dtype": QUALITY_DTYPE.str,
        "alignment": ALIGNMENT,
        "encoding": ENCODING,
        "exact_bytes": True,
        "terminal_sentinel": int(NO_QUALITY),
        "bwt_rows": bwt_rows,
        "read_count": read_count,
        "source_count": len(manifest["sources"]),
        "input_files": (
            None
            if input_files is None
            else [str(x) for x in input_files]
        ),
        "builder": builder,
        "semantics": (
            "For a suffix row beginning at read position p, the tag stores "
            "the exact FASTQ quality byte Q[p]. The terminal-$ suffix row "
            "stores sentinel 255."
        ),
    }


def _write_metadata(bwt_dir, metadata):
    _atomic_write_json(quality_meta_path(bwt_dir), metadata)
    return metadata


def _load_metadata(bwt_dir):
    path = quality_meta_path(bwt_dir)
    if not os.path.exists(path):
        raise QualitySidecarError(
            "quality sidecar metadata not found: %s" % path
        )
    try:
        with open(path, "rb") as fp:
            doc = json.load(fp)
    except ValueError as exc:
        raise QualitySidecarError(
            "quality sidecar metadata is not valid JSON: %s: %s"
            % (path, exc)
        )
    if doc.get("format") != FORMAT_NAME:
        raise QualitySidecarError(
            "unsupported quality sidecar format: %r"
            % doc.get("format")
        )
    if int(doc.get("version", -1)) != FORMAT_VERSION:
        raise QualitySidecarError(
            "unsupported quality sidecar version: %r"
            % doc.get("version")
        )
    if doc.get("tag_name") != QUALITY_TAG_NAME:
        raise QualitySidecarError("unexpected quality tag name")
    if doc.get("alignment") != ALIGNMENT:
        raise QualitySidecarError(
            "unsupported quality alignment: %r"
            % doc.get("alignment")
        )
    if doc.get("encoding") != ENCODING:
        raise QualitySidecarError(
            "unsupported quality encoding: %r"
            % doc.get("encoding")
        )
    if int(doc.get("terminal_sentinel", -1)) != int(NO_QUALITY):
        raise QualitySidecarError(
            "unexpected terminal quality sentinel"
        )
    return doc


def quality_sidecar_exists(bwt_dir):
    bwt_dir = str(bwt_dir)
    if not os.path.exists(quality_meta_path(bwt_dir)):
        return False
    if not tags_exist(bwt_dir):
        return False
    try:
        store = BWTTagStore(bwt_dir, mmap=True, validate=False)
        return store.has_tag(QUALITY_TAG_NAME)
    except Exception:
        return False


def validate_quality_sidecar(bwt_dir, full=True):
    """Validate metadata, tag schema, and terminal/base coverage."""
    bwt_dir = str(bwt_dir)
    metadata = _load_metadata(bwt_dir)
    store = BWTTagStore(bwt_dir, mmap=True, validate=True)

    if not store.has_tag(QUALITY_TAG_NAME):
        raise QualitySidecarError(
            "quality metadata exists but Point-12 tag %s is missing"
            % QUALITY_TAG_NAME
        )

    schema = store.schema(QUALITY_TAG_NAME)
    arr = store.array(QUALITY_TAG_NAME)

    if arr.dtype != QUALITY_DTYPE or arr.ndim != 1:
        raise QualitySidecarError(
            "quality tag must be one-dimensional uint8"
        )

    # Q1 uses 255 only for terminal suffix rows. It is not a Point-12
    # "missing value", because one-sided quality merges must fail.
    if schema.get("missing", {}).get("enabled", False):
        raise QualitySidecarError(
            "quality tag must not declare a Point-12 missing-value policy"
        )

    bwt_rows, read_count = _bwt_length_and_read_count(bwt_dir)
    if arr.shape[0] != bwt_rows:
        raise QualitySidecarError(
            "quality rows %d != BWT rows %d"
            % (arr.shape[0], bwt_rows)
        )

    if int(metadata.get("bwt_rows", -1)) != bwt_rows:
        raise QualitySidecarError(
            "quality metadata BWT-row count is stale"
        )
    if int(metadata.get("read_count", -1)) != read_count:
        raise QualitySidecarError(
            "quality metadata read count is stale"
        )

    if full:
        if read_count:
            if not np.all(arr[:read_count] == NO_QUALITY):
                raise QualitySidecarError(
                    "the first read_count suffix rows must carry terminal "
                    "quality sentinel 255"
                )
        if bwt_rows > read_count:
            if np.any(arr[read_count:] == NO_QUALITY):
                raise QualitySidecarError(
                    "non-terminal suffix row carries reserved quality "
                    "sentinel 255"
                )

    return metadata


def _normalize_quality_bytes(value):
    if isinstance(value, str):
        value = value.encode("latin1")
    elif isinstance(value, bytearray):
        value = bytes(value)
    elif isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, bytes):
        raise TypeError("quality must be bytes-like or str")
    if _one_byte(int(NO_QUALITY)) in value:
        raise QualitySidecarError(
            "quality byte 255 is reserved for terminal suffix rows"
        )
    return value


def _normalize_sequence_bytes(value):
    if isinstance(value, str):
        return value.encode("ascii")
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if not isinstance(value, bytes):
        raise TypeError("sequence must be bytes-like or str")
    return value


def _recover_sequence_and_rows(bwt, dollar_id):
    recovered = bwt.recoverString(
        int(dollar_id),
        withIndex=True,
    )
    if (
        not isinstance(recovered, tuple)
        or len(recovered) != 2
    ):
        raise QualitySidecarError(
            "BWT recoverString(..., withIndex=True) must return "
            "(sequence, row_indices)"
        )

    sequence, rows = recovered
    sequence = _normalize_sequence_bytes(sequence)
    rows = [int(x) for x in rows]

    if len(sequence) != len(rows):
        raise QualitySidecarError(
            "recoverString returned %d symbols but %d row indices"
            % (len(sequence), len(rows))
        )
    return sequence, rows


def _fill_quality_rows(
    bwt_dir,
    bwt,
    read_count,
    record_for_dollar,
    temp_parent=None,
    verify_sequences=True,
):
    """Build a temporary mmap row array using one recovery traversal/read."""
    bwt_dir = str(bwt_dir)
    bwt_rows, actual_reads = _bwt_length_and_read_count(bwt_dir)
    if int(read_count) != actual_reads:
        raise QualitySidecarError(
            "quality input read count %d != BWT read count %d"
            % (read_count, actual_reads)
        )

    temp_root = tempfile.mkdtemp(
        prefix=".q1-quality-build-",
        dir=(
            str(temp_parent)
            if temp_parent is not None
            else bwt_dir
        ),
    )
    temp_path = os.path.join(temp_root, "quality_rows.npy")

    out = open_memmap(
        str(temp_path),
        mode="w+",
        dtype=QUALITY_DTYPE,
        shape=(bwt_rows,),
    )
    out[:] = NO_QUALITY

    try:
        for dollar_id in range(actual_reads):
            expected_sequence, quality = record_for_dollar(dollar_id)
            quality = _normalize_quality_bytes(quality)
            if expected_sequence is not None:
                expected_sequence = _normalize_sequence_bytes(
                    expected_sequence
                )

            recovered, rows = _recover_sequence_and_rows(
                bwt,
                dollar_id,
            )

            base_rows = []
            base_symbols = bytearray()
            for symbol, row in zip(recovered, rows):
                if _is_dollar_symbol(symbol):
                    # Every read contributes one terminal suffix row.
                    out[row] = NO_QUALITY
                else:
                    base_rows.append(row)
                    base_symbols.append(ord(symbol)
                                        if not isinstance(symbol, int)
                                        else symbol)

            if len(base_rows) != len(quality):
                raise QualitySidecarError(
                    "read %d recovered %d bases but FASTQ quality has %d "
                    "bytes"
                    % (
                        dollar_id,
                        len(base_rows),
                        len(quality),
                    )
                )

            if (
                verify_sequences
                and expected_sequence is not None
                and bytes(base_symbols) != expected_sequence
            ):
                raise QualitySidecarError(
                    "read %d sequence mismatch between BWT recovery and "
                    "FASTQ/origin data" % dollar_id
                )

            if base_rows:
                out[np.asarray(base_rows, dtype=np.int64)] = (
                    np.frombuffer(quality, dtype=np.uint8)
                )

        out.flush()

        if actual_reads:
            if not np.all(out[:actual_reads] == NO_QUALITY):
                raise QualitySidecarError(
                    "quality build did not place sentinel on all terminal "
                    "suffix rows"
                )
        if bwt_rows > actual_reads:
            if np.any(out[actual_reads:] == NO_QUALITY):
                raise QualitySidecarError(
                    "quality build left one or more base suffix rows "
                    "unassigned"
                )

        return temp_root, temp_path

    except Exception:
        _release_memmap(out)
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def initialize_leaf_quality_from_records(
    bwt_dir,
    bwt,
    qualities_by_dollar_id,
    sequences_by_dollar_id=None,
    overwrite=False,
    verify_sequences=True,
):
    """Initialize exact quality from leaf-dollar-ordered records.

    ``qualities_by_dollar_id[d]`` is the original quality line for the read
    whose standalone msBWT dollar ID is ``d``.

    ``sequences_by_dollar_id`` is optional but strongly recommended for
    independent sequence/quality validation.
    """
    bwt_dir = str(bwt_dir)
    qualities = list(qualities_by_dollar_id)
    sequences = (
        None
        if sequences_by_dollar_id is None
        else list(sequences_by_dollar_id)
    )

    if sequences is not None and len(sequences) != len(qualities):
        raise QualitySidecarError(
            "sequence and quality record counts differ"
        )

    def record_for_dollar(dollar_id):
        seq = (
            None
            if sequences is None
            else sequences[dollar_id]
        )
        return seq, qualities[dollar_id]

    temp_root, temp_path = _fill_quality_rows(
        bwt_dir,
        bwt,
        len(qualities),
        record_for_dollar,
        verify_sequences=verify_sequences,
    )

    values = None
    try:
        values = np.load(
            str(temp_path),
            mmap_mode="r",
            allow_pickle=False,
        )
        attach_tag(
            bwt_dir,
            QUALITY_TAG_NAME,
            values,
            description=(
                "Exact FASTQ quality byte aligned to suffix-start BWT row; "
                "255 marks the terminal-$ suffix row."
            ),
            overwrite=overwrite,
        )
    finally:
        # R-Q: release the mapping BEFORE deleting the temporary directory;
        # an open mapping blocks file removal on Windows.
        _release_memmap(values)
        shutil.rmtree(temp_root, ignore_errors=True)

    metadata = _base_metadata(
        bwt_dir,
        builder="leaf-records",
    )
    _write_metadata(bwt_dir, metadata)
    validate_quality_sidecar(bwt_dir, full=True)
    return metadata


class _FastqArchive(object):
    """Temporary disk-backed random-access FASTQ sequence/quality archive."""

    def __init__(self, root, metadata):
        self.root = str(root)
        self.metadata = metadata
        self._opened = {}

    @staticmethod
    def _open_fastq(path):
        path = str(path)
        if path.lower().endswith(".gz"):
            return gzip.open(path, "rb")
        return open(path, "rb")

    @classmethod
    def build(cls, fastq_paths, temp_parent=None):
        paths = [str(p) for p in fastq_paths]
        root = tempfile.mkdtemp(
            prefix=".q1-fastq-archive-",
            dir=(
                None
                if temp_parent is None
                else str(temp_parent)
            ),
        )

        files = []
        try:
            for file_id, path in enumerate(paths):
                seq_path = os.path.join(
                    root, "file_%04d_seq.bin" % file_id)
                qual_path = os.path.join(
                    root, "file_%04d_qual.bin" % file_id)
                off_path = os.path.join(
                    root, "file_%04d_offsets.u64" % file_id)

                cumulative = 0
                count = 0
                src = cls._open_fastq(path)
                try:
                    seq_out = open(seq_path, "wb")
                    try:
                        qual_out = open(qual_path, "wb")
                        try:
                            off_out = open(off_path, "wb")
                            try:
                                off_out.write(struct.pack("<Q", 0))
                                while True:
                                    header = src.readline()
                                    if not header:
                                        break
                                    sequence = src.readline()
                                    plus = src.readline()
                                    quality = src.readline()
                                    if not sequence or not plus or not quality:
                                        raise QualitySidecarError(
                                            "truncated FASTQ record in %s "
                                            "at record %d" % (path, count)
                                        )
                                    if not header.startswith(b"@"):
                                        raise QualitySidecarError(
                                            "FASTQ header does not begin "
                                            "with @ in %s at record %d"
                                            % (path, count)
                                        )
                                    if not plus.startswith(b"+"):
                                        raise QualitySidecarError(
                                            "FASTQ separator does not begin "
                                            "with + in %s at record %d"
                                            % (path, count)
                                        )

                                    sequence = sequence.rstrip(b"\r\n")
                                    quality = quality.rstrip(b"\r\n")
                                    if len(sequence) != len(quality):
                                        raise QualitySidecarError(
                                            "FASTQ sequence/quality length "
                                            "mismatch in %s at record %d: "
                                            "%d != %d"
                                            % (
                                                path,
                                                count,
                                                len(sequence),
                                                len(quality),
                                            )
                                        )
                                    _normalize_quality_bytes(quality)

                                    seq_out.write(sequence)
                                    qual_out.write(quality)
                                    cumulative += len(sequence)
                                    off_out.write(
                                        struct.pack("<Q", cumulative)
                                    )
                                    count += 1
                            finally:
                                off_out.close()
                        finally:
                            qual_out.close()
                    finally:
                        seq_out.close()
                finally:
                    src.close()

                files.append(
                    {
                        "file_id": file_id,
                        "path": str(path),
                        "record_count": count,
                        "base_bytes": cumulative,
                        "sequence_file": os.path.basename(seq_path),
                        "quality_file": os.path.basename(qual_path),
                        "offset_file": os.path.basename(off_path),
                    }
                )

            metadata = {
                "files": files,
                "file_count": len(files),
                "read_count": int(
                    sum(f["record_count"] for f in files)
                ),
                "base_bytes": int(
                    sum(f["base_bytes"] for f in files)
                ),
            }
            return cls(root, metadata)

        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

    def _file_views(self, file_id):
        file_id = int(file_id)
        if file_id < 0 or file_id >= len(self.metadata["files"]):
            raise QualitySidecarError(
                "FASTQ origin file ID out of range: %d" % file_id
            )
        if file_id not in self._opened:
            info = self.metadata["files"][file_id]
            offsets = np.memmap(
                os.path.join(self.root, info["offset_file"]),
                dtype="<u8",
                mode="r",
            )
            seq = np.memmap(
                os.path.join(self.root, info["sequence_file"]),
                dtype="uint8",
                mode="r",
            )
            qual = np.memmap(
                os.path.join(self.root, info["quality_file"]),
                dtype="uint8",
                mode="r",
            )
            self._opened[file_id] = (
                info,
                offsets,
                seq,
                qual,
            )
        return self._opened[file_id]

    def record(self, file_id, read_id):
        info, offsets, seq, qual = self._file_views(file_id)
        read_id = int(read_id)
        if read_id < 0 or read_id >= int(info["record_count"]):
            raise QualitySidecarError(
                "FASTQ origin read ID out of range: file %d read %d"
                % (file_id, read_id)
            )
        start = int(offsets[read_id])
        end = int(offsets[read_id + 1])
        return (
            np.asarray(seq[start:end], dtype=np.uint8).tobytes(),
            np.asarray(qual[start:end], dtype=np.uint8).tobytes(),
        )

    def close(self):
        # R-Q: release every open view mapping before removing the archive
        # directory (open mappings block deletion on Windows).
        for opened in self._opened.values():
            for view in opened[1:]:
                _release_memmap(view)
        self._opened.clear()
        shutil.rmtree(self.root, ignore_errors=True)


def _about_origin_reader(about_path):
    about = np.load(
        str(about_path),
        mmap_mode="r",
        allow_pickle=False,
    )
    if about.ndim != 1 and not (
        about.ndim == 2 and about.shape[1] >= 2
    ):
        raise QualitySidecarError(
            "unsupported about.npy shape: %r" % (about.shape,)
        )

    names = about.dtype.names

    def origin(dollar_id):
        row = about[int(dollar_id)]
        if names:
            if len(names) < 2:
                raise QualitySidecarError(
                    "about.npy structured dtype needs at least two fields"
                )
            return int(row[names[0]]), int(row[names[1]])
        return int(row[0]), int(row[1])

    return int(about.shape[0]), origin


def initialize_leaf_quality_from_fastqs(
    bwt_dir,
    bwt,
    fastq_paths,
    about_path=None,
    overwrite=False,
    verify_sequences=True,
    temp_parent=None,
):
    """Retrofit a standalone Holt msBWT directly from its original FASTQs.

    The legacy ``about.npy`` (or Feature-9 read provenance) maps standalone
    dollar IDs to ``(origin_file_id, origin_read_id)``.  FASTQ records are
    archived in a temporary disk-backed representation, so the original
    FASTQ order does not need to match dollar-ID/sorted-string order.
    """
    bwt_dir = str(bwt_dir)
    fastq_paths = [str(p) for p in fastq_paths]

    if about_path is None:
        about_path = os.path.join(bwt_dir, "about.npy")
    else:
        about_path = str(about_path)

    archive = _FastqArchive.build(
        fastq_paths,
        temp_parent=temp_parent,
    )
    try:
        if os.path.exists(about_path):
            read_count, origin = _about_origin_reader(
                about_path
            )
        elif read_provenance_exists(bwt_dir):
            rp = ReadProvenanceIndex(
                bwt_dir,
                mmap=True,
                validate=True,
            )
            read_count = rp.read_count

            def origin(dollar_id):
                record = rp.record(dollar_id)
                if (
                    record["origin_file_id"] is None
                    or record["origin_read_id"] is None
                ):
                    raise QualitySidecarError(
                        "read provenance lacks origin FASTQ identity for "
                        "dollar ID %d" % dollar_id
                    )
                return (
                    record["origin_file_id"],
                    record["origin_read_id"],
                )
        else:
            raise QualitySidecarError(
                "need about.npy or Point-9 read provenance to map dollar "
                "IDs back to FASTQ records"
            )

        def record_for_dollar(dollar_id):
            file_id, read_id = origin(dollar_id)
            return archive.record(file_id, read_id)

        temp_root, temp_path = _fill_quality_rows(
            bwt_dir,
            bwt,
            read_count,
            record_for_dollar,
            temp_parent=temp_parent,
            verify_sequences=verify_sequences,
        )
        values = None
        try:
            values = np.load(
                str(temp_path),
                mmap_mode="r",
                allow_pickle=False,
            )
            attach_tag(
                bwt_dir,
                QUALITY_TAG_NAME,
                values,
                description=(
                    "Exact FASTQ quality byte aligned to suffix-start BWT "
                    "row; 255 marks terminal-$ suffix row."
                ),
                overwrite=overwrite,
            )
        finally:
            # R-Q: release the mapping BEFORE deleting the temporary
            # directory; an open mapping blocks file removal on Windows.
            _release_memmap(values)
            shutil.rmtree(temp_root, ignore_errors=True)

        metadata = _base_metadata(
            bwt_dir,
            input_files=fastq_paths,
            builder="leaf-fastq-retrofit",
        )
        metadata["verified_sequences"] = bool(
            verify_sequences
        )
        _write_metadata(bwt_dir, metadata)
        validate_quality_sidecar(bwt_dir, full=True)
        return metadata

    finally:
        archive.close()


def attach_quality_from_row_values(
    bwt_dir,
    values,
    overwrite=False,
    builder="row-values",
):
    """Attach a precomputed suffix-row-aligned quality array.

    This is useful for deterministic fixtures and external preprocessors.
    """
    values = np.asarray(values)
    if values.dtype != QUALITY_DTYPE:
        values = values.astype(QUALITY_DTYPE, copy=False)
    if values.ndim != 1:
        raise QualitySidecarError(
            "quality row array must be one-dimensional"
        )

    attach_tag(
        bwt_dir,
        QUALITY_TAG_NAME,
        values,
        description=(
            "Exact FASTQ quality byte aligned to suffix-start BWT row; "
            "255 marks terminal-$ suffix row."
        ),
        overwrite=overwrite,
    )
    metadata = _base_metadata(
        bwt_dir,
        builder=builder,
    )
    _write_metadata(bwt_dir, metadata)
    validate_quality_sidecar(bwt_dir, full=True)
    return metadata


def retrofit_merged_quality_from_leaf_arrays(
    merged_bwt_dir,
    arrays_by_source,
    overwrite=False,
):
    """Replay Point-2 interleaves to retrofit quality onto an existing merge."""
    build_tag_from_leaf_arrays(
        merged_bwt_dir,
        QUALITY_TAG_NAME,
        arrays_by_source,
        description=(
            "Exact FASTQ quality byte aligned to suffix-start BWT row; "
            "255 marks terminal-$ suffix row."
        ),
        overwrite=overwrite,
    )
    metadata = _base_metadata(
        merged_bwt_dir,
        builder="merged-provenance-replay",
    )
    _write_metadata(merged_bwt_dir, metadata)
    validate_quality_sidecar(merged_bwt_dir, full=True)
    return metadata


def _has_quality_tag(bwt_dir):
    try:
        if not tags_exist(bwt_dir):
            return False
        return BWTTagStore(
            bwt_dir,
            mmap=True,
            validate=False,
        ).has_tag(QUALITY_TAG_NAME)
    except Exception:
        return False


def preflight_quality_merge(left_dir, right_dir):
    """Fail before BWT merge on incomplete/inconsistent Q1 state."""
    states = []
    for directory in (left_dir, right_dir):
        meta = os.path.exists(quality_meta_path(directory))
        tag = _has_quality_tag(directory)
        if meta != tag:
            raise QualitySidecarError(
                "quality sidecar is internally incomplete in %s: "
                "metadata=%s tag=%s"
                % (directory, meta, tag)
            )
        if meta:
            validate_quality_sidecar(
                directory,
                full=True,
            )
        states.append(meta)

    if states[0] != states[1]:
        raise QualitySidecarError(
            "quality sidecar is present on only one merge input; "
            "exact FASTQ quality must never be silently synthesized"
        )
    return bool(states[0])


def merge_quality_sidecar_metadata(
    left_dir,
    right_dir,
    output_dir,
):
    """Preserve Q1 semantic metadata after Point-12 interleaves the tag."""
    left_exists = quality_sidecar_exists(left_dir)
    right_exists = quality_sidecar_exists(right_dir)

    if left_exists != right_exists:
        raise QualitySidecarError(
            "quality sidecar is present on only one merge input"
        )
    if not left_exists:
        return None

    left = validate_quality_sidecar(left_dir, full=True)
    right = validate_quality_sidecar(right_dir, full=True)

    for field in (
        "tag_name",
        "dtype",
        "alignment",
        "encoding",
        "exact_bytes",
        "terminal_sentinel",
    ):
        if left.get(field) != right.get(field):
            raise QualitySidecarError(
                "quality sidecar merge mismatch for field %s"
                % field
            )

    metadata = _base_metadata(
        output_dir,
        builder="automatic-merge",
    )
    metadata["child_builders"] = [
        left.get("builder"),
        right.get("builder"),
    ]
    _write_metadata(output_dir, metadata)
    validate_quality_sidecar(output_dir, full=True)
    return metadata


def filter_quality_sidecar_metadata(
    input_dir,
    output_dir,
):
    """Preserve Q1 metadata after Point-10 filters the Point-12 quality tag."""
    if not quality_sidecar_exists(input_dir):
        return None

    validate_quality_sidecar(input_dir, full=True)
    metadata = _base_metadata(
        output_dir,
        builder="point10-filter",
    )
    _write_metadata(output_dir, metadata)
    validate_quality_sidecar(output_dir, full=True)
    return metadata


class QualitySidecar(object):
    """Exact quality recovery and query helper."""

    def __init__(
        self,
        bwt_dir,
        mmap=True,
        validate=True,
    ):
        self.bwt_dir = str(bwt_dir)
        self.store = BWTTagStore(
            self.bwt_dir,
            mmap=mmap,
            validate=validate,
        )
        if not self.store.has_tag(QUALITY_TAG_NAME):
            raise QualitySidecarError(
                "quality tag not found"
            )
        self.values = self.store.array(QUALITY_TAG_NAME)
        self.metadata = (
            validate_quality_sidecar(
                self.bwt_dir,
                full=validate,
            )
            if validate
            else _load_metadata(self.bwt_dir)
        )

    @property
    def bwt_rows(self):
        return int(self.values.shape[0])

    @property
    def read_count(self):
        return int(self.metadata["read_count"])

    def quality_byte_for_row(self, row_index):
        row_index = int(row_index)
        if row_index < 0 or row_index >= self.bwt_rows:
            raise IndexError(
                "row index %d outside [0,%d)"
                % (row_index, self.bwt_rows)
            )
        value = int(self.values[row_index])
        return None if value == int(NO_QUALITY) else value

    def quality_for_row(self, row_index):
        value = self.quality_byte_for_row(row_index)
        if value is None:
            return None
        return _one_byte(value)

    def recover_quality(self, bwt, dollar_id):
        """Recover the exact original FASTQ quality line for one read."""
        sequence, rows = _recover_sequence_and_rows(
            bwt,
            dollar_id,
        )
        out = bytearray()
        for symbol, row in zip(sequence, rows):
            value = int(self.values[row])
            if _is_dollar_symbol(symbol):
                if value != int(NO_QUALITY):
                    raise QualitySidecarError(
                        "terminal suffix row %d lacks quality sentinel"
                        % row
                    )
                continue
            if value == int(NO_QUALITY):
                raise QualitySidecarError(
                    "base suffix row %d has terminal sentinel"
                    % row
                )
            out.append(value)
        return bytes(out)

    def recover_sequence_and_quality(
        self,
        bwt,
        dollar_id,
    ):
        sequence, _ = _recover_sequence_and_rows(
            bwt,
            dollar_id,
        )
        bases = bytearray()
        for symbol in sequence:
            if not _is_dollar_symbol(symbol):
                bases.append(ord(symbol) if not isinstance(symbol, int)
                             else symbol)
        bases = bytes(bases)
        quality = self.recover_quality(
            bwt,
            dollar_id,
        )
        if len(bases) != len(quality):
            raise QualitySidecarError(
                "recovered sequence/quality lengths differ"
            )
        return bases, quality

    def record(
        self,
        bwt,
        dollar_id,
        read_provenance=None,
    ):
        sequence, quality = self.recover_sequence_and_quality(
            bwt,
            dollar_id,
        )
        result = {
            "dollar_id": int(dollar_id),
            "sequence": sequence,
            "quality": quality,
        }
        if read_provenance is not None:
            result["provenance"] = read_provenance.record(
                int(dollar_id)
            )
        return result


def quality_ascii_to_phred(values, offset=33):
    """Convert quality bytes for analysis only; persisted data remain exact."""
    arr = np.asarray(values, dtype=np.int16)
    offset = int(offset)
    result = arr - offset
    if np.any(result < 0):
        raise QualitySidecarError(
            "one or more quality bytes are below Phred ASCII offset %d"
            % offset
        )
    return result
