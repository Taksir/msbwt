"""Feature 11A - exact post-construction LCP for Holt-style msBWTs
(enhanced-modern2).

This module deliberately implements the safe retrofit path first:

    existing final msBWT
        -> recover each indexed string through the existing BWT API
        -> induce the generalized suffix coordinates implicit in BWT order
        -> generalized Kasai pass
        -> lcps.npy + lcp.json

No FASTQ files are required and the BWT is not rebuilt or re-merged.

Why ``lcps.npy`` instead of only ``lcp.npy``?
---------------------------------------------
The upstream Holt ``BasicBWT`` implementations already look for ``lcps.npy``
and expose it to legacy LCP-assisted query code.  We therefore preserve that
filename and convention directly:

    lcps[i] = LCP(SA[i], SA[i+1])       for 0 <= i < N-1

The modern canonical boundary convention used by :class:`LCPIndex` is:

    LCP[0] = 0
    LCP[i] = lcps[i-1]                  for 1 <= i < N

String-collection terminator semantics
---------------------------------------
The theoretical multi-string BWT assigns a distinct ordered terminator to every
string, even though practical implementations store one shared ``$`` byte.  As
in the collection-LCP literature, the distinct terminators do *not* contribute
to biological LCP length.  Therefore identical biological suffixes in different
reads have an LCP equal to the number of shared biological symbols (not plus
one for ``$``); two terminal-only suffixes have LCP 0.

The implementation uses temporary mmap-backed arrays; working-disk cost is
O(N), resident RAM is dominated by one recovered read plus OS page cache.
This baseline is intended to remain the exact correctness oracle for any later
succinct BWT-only construction.

Persistence classification

- ``lcps.npy``  AUTHORITATIVE adjacency array (uint32/uint64, length
  ``N - 1``).  Stale/corrupt protection: length, dtype, metadata row/read
  counts, max-LCP consistency, terminator-prefix zero boundaries, and
  LCP > max read length all validated loudly on load.
- ``lcp.json``  AUTHORITATIVE metadata (format/version/algorithm,
  conventions, terminator semantics, counts, max LCP, construction info).

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""


import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np
from numpy.lib.format import open_memmap

from MUS.MultiSourceProvenance import BWT_FILENAME


LCP_ARRAY_FILENAME = "lcps.npy"
LCP_METADATA_FILENAME = "lcp.json"
FORMAT_NAME = "msbwt-lcp"
FORMAT_VERSION = 1
ALGORITHM_NAME = "lf-recovery-generalized-kasai"
TERMINATOR_SEMANTICS = "virtual-distinct-ordered-dollar-excluded-from-lcp"


class LCPError(ValueError):
    """Raised for invalid, incomplete, or inconsistent LCP layers."""


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


def _atomic_replace(source_path, dest_path):
    if hasattr(os, "replace"):
        os.replace(source_path, dest_path)
    elif os.name == "nt" and os.path.exists(dest_path):
        os.remove(dest_path)
        os.rename(source_path, dest_path)
    else:
        os.rename(source_path, dest_path)


def _monotonic():
    if hasattr(time, "perf_counter"):
        return time.perf_counter()
    return time.time()


def _first_byte(sequence):
    """First byte value of a bytes sequence (py2/3 compatible)."""
    value = sequence[0]
    if isinstance(value, int):
        return value
    return ord(value)


def lcp_array_path(bwt_dir):
    return os.path.join(str(bwt_dir), LCP_ARRAY_FILENAME)


def lcp_metadata_path(bwt_dir):
    return os.path.join(str(bwt_dir), LCP_METADATA_FILENAME)


def lcp_exists(bwt_dir):
    return (
        os.path.exists(lcp_array_path(bwt_dir))
        and os.path.exists(lcp_metadata_path(bwt_dir))
    )


def _load_bwt_rows(bwt_dir):
    path = os.path.join(str(bwt_dir), BWT_FILENAME)
    if not os.path.exists(path):
        raise LCPError("missing BWT: %s" % path)
    bwt = np.load(path, mmap_mode="r", allow_pickle=False)
    if bwt.ndim != 1:
        raise LCPError("msbwt.npy must be one-dimensional")
    return bwt


def _load_compiled_bwt(bwt_dir, mmap=True):
    try:
        from MUSCython import MultiStringBWTCython as MultiStringBWT
    except ImportError as exc:
        raise LCPError(
            "compiled MUSCython is unavailable; pass an already-loaded BWT "
            "object exposing recoverString(..., withIndex=True)"
        )
    return MultiStringBWT.loadBWT(
        str(bwt_dir),
        useMemmap=bool(mmap),
    )


def _normalize_recovered(value):
    if isinstance(value, str):
        value = value.encode("ascii")
    elif isinstance(value, bytearray):
        value = bytes(value)
    elif isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, bytes):
        raise LCPError(
            "recoverString must return bytes/str sequence, got %r"
            % (type(value),)
        )
    return value


def _recover_with_rows(bwt, dollar_id):
    recovered = bwt.recoverString(
        int(dollar_id),
        withIndex=True,
    )
    if not isinstance(recovered, tuple) or len(recovered) != 2:
        raise LCPError(
            "recoverString(..., withIndex=True) must return "
            "(sequence, row_indices)"
        )

    sequence, rows = recovered
    sequence = _normalize_recovered(sequence)
    rows = [int(x) for x in rows]

    if len(sequence) != len(rows):
        raise LCPError(
            "dollar ID %d recovered %d symbols but %d row indices"
            % (dollar_id, len(sequence), len(rows))
        )
    if not sequence or _first_byte(sequence) != ord("$"):
        raise LCPError(
            "dollar ID %d recovery must begin with '$' under Holt semantics"
            % dollar_id
        )
    if rows[0] != int(dollar_id):
        raise LCPError(
            "dollar ID %d recovered terminal row %d; expected its own "
            "terminal suffix row"
            % (dollar_id, rows[0])
        )
    if b"$" in sequence[1:]:
        raise LCPError(
            "dollar ID %d recovery crossed a read boundary" % dollar_id
        )

    return sequence, rows


def _index_dtype(n_rows):
    # Reserve the maximum value as an unassigned sentinel.
    if int(n_rows) < np.iinfo(np.uint32).max:
        return np.dtype("<u4")
    return np.dtype("<u8")


def _lcp_dtype(max_read_length):
    if int(max_read_length) <= np.iinfo(np.uint32).max:
        return np.dtype("<u4")
    return np.dtype("<u8")


def _prepare_generalized_coordinates(
    bwt_dir,
    bwt,
    temp_dir,
    n_rows,
    read_count,
):
    """Recover reads and create mmap-backed coordinate permutations.

    ``text.npy`` is a concatenation of each biological read followed by
    byte 0.  It therefore has exactly N entries: one per biological base
    plus one virtual distinct-terminator *slot* per read.  Byte 0 is used
    only as a comparison stop marker; terminators are never counted as LCP
    symbols.

    ``sa_coord[row]`` maps BWT/SA row -> text coordinate.
    ``rank_by_coord[coord]`` maps text coordinate -> BWT/SA row.
    """
    temp_dir = str(temp_dir)
    index_dtype = _index_dtype(n_rows)
    sentinel = np.iinfo(index_dtype).max

    text = open_memmap(
        os.path.join(temp_dir, "text.npy"),
        mode="w+",
        dtype=np.uint8,
        shape=(n_rows,),
    )
    text[:] = 0

    sa_coord = open_memmap(
        os.path.join(temp_dir, "sa_coord.npy"),
        mode="w+",
        dtype=index_dtype,
        shape=(n_rows,),
    )
    sa_coord[:] = sentinel

    rank_by_coord = open_memmap(
        os.path.join(temp_dir, "rank_by_coord.npy"),
        mode="w+",
        dtype=index_dtype,
        shape=(n_rows,),
    )
    rank_by_coord[:] = sentinel

    read_starts = open_memmap(
        os.path.join(temp_dir, "read_starts.npy"),
        mode="w+",
        dtype=np.uint64,
        shape=(read_count + 1,),
    )

    coord = 0
    max_read_length = 0

    for dollar_id in range(read_count):
        read_starts[dollar_id] = coord
        sequence, rows = _recover_with_rows(bwt, dollar_id)
        bases = sequence[1:]
        max_read_length = max(max_read_length, len(bases))

        expected_len = len(bases) + 1
        if len(rows) != expected_len:
            raise LCPError(
                "dollar ID %d has inconsistent recovery length" % dollar_id
            )
        if coord + expected_len > n_rows:
            raise LCPError(
                "recovered strings exceed BWT row count while processing "
                "dollar ID %d" % dollar_id
            )

        # Biological positions.
        for pos, row in enumerate(rows[1:]):
            if row < 0 or row >= n_rows:
                raise LCPError(
                    "dollar ID %d recovered out-of-range row %d"
                    % (dollar_id, row)
                )
            if int(sa_coord[row]) != int(sentinel):
                raise LCPError(
                    "BWT row %d appears in more than one recovered read "
                    "cycle" % row
                )
            target_coord = coord + pos
            symbol = bases[pos]
            text[target_coord] = (
                ord(symbol) if not isinstance(symbol, int) else symbol)
            sa_coord[row] = target_coord
            rank_by_coord[target_coord] = row

        # Virtual terminal coordinate. It stores byte 0 and therefore halts
        # LCP comparison before a terminator can contribute to the LCP value.
        terminal_coord = coord + len(bases)
        terminal_row = rows[0]
        if int(sa_coord[terminal_row]) != int(sentinel):
            raise LCPError(
                "terminal BWT row %d appears in more than one read cycle"
                % terminal_row
            )
        sa_coord[terminal_row] = terminal_coord
        rank_by_coord[terminal_coord] = terminal_row

        coord += expected_len

    read_starts[read_count] = coord

    if coord != n_rows:
        raise LCPError(
            "recovered collection accounts for %d coordinates but BWT has "
            "%d rows" % (coord, n_rows)
        )

    # The recovery cycles must form a permutation of all BWT rows.
    if np.any(sa_coord == sentinel):
        missing = int(np.count_nonzero(sa_coord == sentinel))
        raise LCPError(
            "%d BWT rows were not assigned to any recovered read cycle"
            % missing
        )
    if np.any(rank_by_coord == sentinel):
        missing = int(np.count_nonzero(rank_by_coord == sentinel))
        raise LCPError(
            "%d text coordinates were not assigned a suffix-array row"
            % missing
        )

    text.flush()
    sa_coord.flush()
    rank_by_coord.flush()
    read_starts.flush()

    return {
        "text": text,
        "sa_coord": sa_coord,
        "rank_by_coord": rank_by_coord,
        "read_starts": read_starts,
        "index_dtype": index_dtype,
        "max_read_length": int(max_read_length),
    }


def _generalized_kasai(
    temp_arrays,
    output_path,
    n_rows,
    read_count,
):
    text = temp_arrays["text"]
    sa_coord = temp_arrays["sa_coord"]
    rank_by_coord = temp_arrays["rank_by_coord"]
    read_starts = temp_arrays["read_starts"]
    max_read_length = temp_arrays["max_read_length"]

    dtype = _lcp_dtype(max_read_length)
    output_len = max(0, n_rows - 1)
    lcps = open_memmap(
        str(output_path),
        mode="w+",
        dtype=dtype,
        shape=(output_len,),
    )
    if output_len:
        lcps[:] = 0

    max_lcp = 0

    # Generalized Kasai.  h is reset at every read boundary because the next
    # biological suffix after a terminal belongs to another independent text.
    for read_id in range(read_count):
        start = int(read_starts[read_id])
        next_start = int(read_starts[read_id + 1])
        terminal_coord = next_start - 1
        h = 0

        for coord in range(start, terminal_coord):
            rank = int(rank_by_coord[coord])
            if rank == 0:
                h = 0
                continue

            prev_coord = int(sa_coord[rank - 1])

            # The virtual terminator byte is 0 and is deliberately not
            # counted.  Since every read carries one such byte, comparison
            # can never run outside the mmap array.
            while (
                int(text[coord + h]) != 0
                and int(text[prev_coord + h]) != 0
                and int(text[coord + h]) == int(text[prev_coord + h])
            ):
                h += 1

            lcps[rank - 1] = h
            if h > max_lcp:
                max_lcp = h
            if h:
                h -= 1

    lcps.flush()
    return lcps, int(max_lcp), dtype


def construct_lcp_from_bwt(
    bwt_dir,
    bwt=None,
    overwrite=False,
    mmap=True,
    temp_parent=None,
    validate=True,
):
    """Construct exact multi-string LCP from an existing final msBWT.

    Parameters
    ----------
    bwt_dir : path-like
        Existing Holt-style MSBWT package containing ``msbwt.npy``.
    bwt : optional object
        Loaded BWT exposing ``recoverString(dollar_id, withIndex=True)``.
        If omitted, the function loads the package through compiled
        MUSCython.
    overwrite : bool
        Replace an existing Feature-11A LCP layer.
    mmap : bool
        Passed to the compiled loader when ``bwt`` is omitted.
    temp_parent : optional path-like
        Parent directory for O(N) temporary mmap files.  Defaults to a
        sibling temporary directory beside the target BWT package.
    validate : bool
        Run structural validation after the atomic install.
    """
    bwt_dir = str(bwt_dir)
    if not os.path.isdir(bwt_dir):
        raise LCPError("BWT directory does not exist: %s" % bwt_dir)

    final_array = lcp_array_path(bwt_dir)
    final_meta = lcp_metadata_path(bwt_dir)

    if (os.path.exists(final_array) or os.path.exists(final_meta)) and \
            not overwrite:
        raise LCPError(
            "LCP output already exists; pass overwrite=True to replace it"
        )

    raw_bwt = _load_bwt_rows(bwt_dir)
    n_rows = int(raw_bwt.shape[0])
    read_count = int(np.count_nonzero(raw_bwt == 0))

    if n_rows and read_count <= 0:
        raise LCPError(
            "BWT contains rows but no '$' terminator symbols"
        )

    if bwt is None:
        bwt = _load_compiled_bwt(bwt_dir, mmap=mmap)

    if hasattr(bwt, "getTotalSize"):
        backend_size = int(bwt.getTotalSize())
        if backend_size != n_rows:
            raise LCPError(
                "loaded BWT reports %d rows but msbwt.npy has %d"
                % (backend_size, n_rows)
            )

    parent = (
        str(temp_parent)
        if temp_parent is not None
        else os.path.dirname(bwt_dir)
    )
    if not os.path.isdir(parent):
        os.makedirs(parent)
    temp_root = tempfile.mkdtemp(
        prefix=".%s-lcp11a-" % os.path.basename(bwt_dir),
        dir=parent,
    )
    temp_array = os.path.join(temp_root, LCP_ARRAY_FILENAME)

    started = _monotonic()
    try:
        arrays = _prepare_generalized_coordinates(
            bwt_dir,
            bwt,
            temp_root,
            n_rows,
            read_count,
        )
        lcps, max_lcp, lcp_dtype = _generalized_kasai(
            arrays,
            temp_array,
            n_rows,
            read_count,
        )

        metadata = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "algorithm": ALGORITHM_NAME,
            "array_file": LCP_ARRAY_FILENAME,
            "array_dtype": lcp_dtype.str,
            "array_length": max(0, n_rows - 1),
            "bwt_file": BWT_FILENAME,
            "bwt_rows": n_rows,
            # Identity binding: the validated provenance manifest's digest
            # of the CURRENT BWT, so a same-length replaced BWT can never
            # silently consume a stale LCP layer.
            "bwt_sha256": _bwt_identity_sha256(bwt_dir),
            "read_count": read_count,
            "max_read_length": arrays["max_read_length"],
            "max_lcp": max_lcp,
            "terminator_semantics": TERMINATOR_SEMANTICS,
            "stored_convention": (
                "lcps[i] = LCP(SA[i], SA[i+1]); shared stored '$' acts "
                "as virtual distinct ordered terminators and contributes 0 "
                "symbols to the LCP"
            ),
            "canonical_convention": (
                "LCP[0] = 0; LCP[i] = lcps[i-1] for 1 <= i < N"
            ),
            "source": "existing-final-bwt-no-fastq-no-remerge",
            "working_storage": (
                "O(N) temporary mmap-backed text/coordinate arrays; later "
                "succinct BWT-only construction may replace this baseline"
            ),
            "construction_seconds": float(_monotonic() - started),
        }

        # Ensure all mmap writers release the files before atomic install.
        try:
            del lcps
        except Exception:
            pass
        for key in ("text", "sa_coord", "rank_by_coord", "read_starts"):
            try:
                del arrays[key]
            except Exception:
                pass

        # Atomic-enough install: array first, metadata last.  A complete
        # layer is recognized only when both are present and validate
        # together.
        if os.path.exists(final_array):
            os.remove(final_array)
        _atomic_replace(str(temp_array), str(final_array))
        _atomic_write_json(final_meta, metadata)

        if validate:
            validate_lcp(bwt_dir, full=True)

        return metadata

    except Exception:
        # If metadata was never installed, remove a partially replaced array.
        if os.path.exists(final_array) and not os.path.exists(final_meta):
            try:
                os.remove(final_array)
            except Exception:
                pass
        raise
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def load_lcp_metadata(bwt_dir):
    path = lcp_metadata_path(bwt_dir)
    if not os.path.exists(path):
        raise LCPError("LCP metadata not found: %s" % path)
    try:
        with open(path, "rb") as fp:
            doc = json.load(fp)
    except ValueError as exc:
        raise LCPError(
            "LCP metadata is not valid JSON: %s: %s" % (path, exc))
    if doc.get("format") != FORMAT_NAME:
        raise LCPError(
            "unsupported LCP format: %r" % doc.get("format")
        )
    if int(doc.get("version", -1)) != FORMAT_VERSION:
        raise LCPError(
            "unsupported LCP version: %r" % doc.get("version")
        )
    if doc.get("array_file") != LCP_ARRAY_FILENAME:
        raise LCPError("unexpected LCP array filename")
    if doc.get("terminator_semantics") != TERMINATOR_SEMANTICS:
        raise LCPError("unexpected LCP terminator semantics")
    return doc


def _bwt_identity_sha256(bwt_dir):
    """Identity binding: the validated manifest digest of the current BWT.

    ``load_manifest(..., validate=True)`` already recomputes the content
    digest of ``msbwt.npy``, so no extra hashing is performed here.
    """
    from MUS.MultiSourceProvenance import load_manifest
    manifest = load_manifest(str(bwt_dir), validate=True)
    value = manifest.get("msbwt_sha256")
    if value is None:
        raise LCPError(
            "provenance manifest has no msbwt_sha256 identity field"
        )
    return str(value)


def validate_lcp(bwt_dir, full=True):
    bwt_dir = str(bwt_dir)
    metadata = load_lcp_metadata(bwt_dir)
    bwt = _load_bwt_rows(bwt_dir)
    n_rows = int(bwt.shape[0])
    read_count = int(np.count_nonzero(bwt == 0))

    arr_path = lcp_array_path(bwt_dir)
    if not os.path.exists(arr_path):
        raise LCPError("LCP array not found: %s" % arr_path)
    arr = np.load(arr_path, mmap_mode="r", allow_pickle=False)

    if arr.ndim != 1:
        raise LCPError("lcps.npy must be one-dimensional")
    if int(arr.shape[0]) != max(0, n_rows - 1):
        raise LCPError(
            "LCP array length %d != expected %d for %d BWT rows"
            % (arr.shape[0], max(0, n_rows - 1), n_rows)
        )
    if arr.dtype.kind != "u":
        raise LCPError("lcps.npy must use an unsigned integer dtype")
    if int(metadata.get("bwt_rows", -1)) != n_rows:
        raise LCPError("LCP metadata BWT-row count is stale")
    if int(metadata.get("read_count", -1)) != read_count:
        raise LCPError("LCP metadata read count is stale")
    if int(metadata.get("array_length", -1)) != arr.shape[0]:
        raise LCPError("LCP metadata array length is stale")
    if metadata.get("bwt_sha256") != _bwt_identity_sha256(bwt_dir):
        raise LCPError(
            "LCP identity does not match the current BWT "
            "(same-length replaced BWT or copied stale LCP layer)"
        )

    if full and arr.size:
        observed_max = int(np.max(arr))
        if observed_max != int(metadata.get("max_lcp", -1)):
            raise LCPError(
                "LCP metadata max_lcp=%r but array maximum is %d"
                % (metadata.get("max_lcp"), observed_max)
            )
        max_read_length = int(metadata.get("max_read_length", -1))
        if observed_max > max_read_length:
            raise LCPError(
                "LCP value %d exceeds maximum read length %d"
                % (observed_max, max_read_length)
            )

        # With distinct virtual terminators, all boundaries among the initial
        # terminal suffixes have LCP zero.  The terminal/base bucket boundary
        # is also zero.
        zero_prefix_boundaries = min(read_count, arr.shape[0])
        if zero_prefix_boundaries and np.any(
            arr[:zero_prefix_boundaries] != 0
        ):
            raise LCPError(
                "terminator-prefix LCP boundaries must be zero under "
                "distinct-endmarker semantics"
            )

    return metadata


class LCPIndex(object):
    """Mmap-friendly view of the upstream-compatible ``lcps.npy`` layer."""

    def __init__(self, bwt_dir, mmap=True, validate=True):
        self.bwt_dir = str(bwt_dir)
        self.metadata = (
            validate_lcp(self.bwt_dir, full=True)
            if validate
            else load_lcp_metadata(self.bwt_dir)
        )
        self.values = np.load(
            lcp_array_path(self.bwt_dir),
            mmap_mode="r" if mmap else None,
            allow_pickle=False,
        )
        self.n_rows = int(self.metadata["bwt_rows"])

    def __len__(self):
        return self.n_rows

    def adjacent(self, left_row):
        """LCP between ``left_row`` and ``left_row + 1``."""
        left_row = int(left_row)
        if left_row < 0 or left_row >= self.n_rows - 1:
            raise IndexError(
                "left row %d outside valid adjacent range [0,%d)"
                % (left_row, max(0, self.n_rows - 1))
            )
        return int(self.values[left_row])

    def boundary(self, row):
        """Canonical LCP[row], with LCP[0] = 0."""
        row = int(row)
        if row < 0 or row >= self.n_rows:
            raise IndexError(
                "row %d outside [0,%d)" % (row, self.n_rows)
            )
        if row == 0:
            return 0
        return int(self.values[row - 1])

    def between_rows(self, left_row, right_row):
        """Exact LCP of arbitrary suffix-array rows via the RMQ identity.

        This baseline performs a direct minimum scan.  Point 11C may later
        add a compressed RMQ structure without changing the semantics.
        """
        left_row = int(left_row)
        right_row = int(right_row)
        if left_row < 0 or right_row < 0:
            raise IndexError("rows must be non-negative")
        if left_row >= self.n_rows or right_row >= self.n_rows:
            raise IndexError("row outside LCP index")
        if left_row == right_row:
            # Self-LCP is not stored.  Returning the maximum read length
            # would be misleading because the exact suffix length is not
            # encoded here.
            raise LCPError(
                "between_rows requires two distinct suffix-array rows"
            )
        if left_row > right_row:
            left_row, right_row = right_row, left_row
        return int(np.min(self.values[left_row:right_row]))

    @property
    def max_lcp(self):
        return int(self.metadata["max_lcp"])

    @property
    def read_count(self):
        return int(self.metadata["read_count"])
