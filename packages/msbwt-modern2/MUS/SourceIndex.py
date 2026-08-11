"""
Source-aware queries for two-way merged MSBWTs (Feature 1, enhanced-modern2).

The Holt/McMillan two-way merge (``MUSCython.GenericMerge.mergeTwoMSBWTs``)
leaves ``inter0.npy`` in the merged BWT directory.  It is a packed bitvector
aligned with the merged BWT rows:

    bit == 0  -> row/symbol came from the first input BWT
    bit == 1  -> row/symbol came from the second input BWT

Bit ``x`` of the vector corresponds to merged BWT row ``x``
(``GenericMerge.interleaveTwoBwts`` reads the bit at row ``x`` to decide which
input BWT supplies that row's symbol).  Bits are packed least-significant-bit
first within each byte, matching ``GenericMerge.setBit_p`` /
``GenericMerge.getBit_p`` (``bit i within byte = 1 << (i & 7)``).

The interleave byte capacity is ``(len1 + len2) / 8 + 1``, so the final byte
may contain padding bits beyond the valid BWT rows.  The valid bit count is
always taken from the merged ``msbwt.npy`` length; padding bits never
contribute to any rank result.

For a query ``Q`` the merged FM interval ``[l, h) =
merged.findIndicesOfStr(Q)`` is computed once, then:

    source1_count = rank1(h) - rank1(l)
    source0_count = (h - l) - source1_count

which satisfies the mathematical invariants

    count_source0(Q) == standalone_source0.countOccurrencesOfSeq(Q)
    count_source1(Q) == standalone_source1.countOccurrencesOfSeq(Q)
    count_source0(Q) + count_source1(Q) == merged.countOccurrencesOfSeq(Q)

provided the merged BWT is the BWT of the union read multiset (verified for
modern2 merges) and ``inter0.npy`` carries the row provenance (verified
against an independent rotation-sort oracle in the Feature-1 evidence).

This module intentionally stays in Python.  It depends only on NumPy and the
public ``findIndicesOfStr`` method of an MSBWT object, so it can be integrated
without modifying the Cython FM-index implementation.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""

from __future__ import absolute_import

import hashlib
import os
import zipfile

import numpy as np


# np.unpackbits(bitorder="little") is not used so this code remains compatible
# with older NumPy versions (1.16.6).  This table is also faster for small
# rank tails.
_POPCOUNT = np.asarray([bin(i).count("1") for i in range(256)], dtype=np.uint8)


# zipfile.BadZipFile (Python 3) / zipfile.BadZipfile (Python 2.7)
_ZIP_BAD = getattr(zipfile, "BadZipFile", None) or getattr(
    zipfile, "BadZipfile", None
)


class TwoSourceInterleaveIndex(object):
    """Rank/access index over the packed two-source merge interleave.

    Parameters
    ----------
    packed_bits : ndarray(uint8)
        Packed ``inter0.npy`` bytes.
    total_bits : int
        Number of valid BWT rows/bits.  The final storage byte may contain
        padding bits and therefore this value must be known separately.
    rank_stride_bytes : int, optional
        Store one uint64 rank sample every this many packed bytes.
        The default of 64 bytes means at most 63 full bytes plus one partial
        byte are popcounted for each rank query.
    rank_prefix : ndarray(uint64), optional
        Previously built rank samples.  If omitted, they are built eagerly.
    """

    INTERLEAVE_FILENAME = "inter0.npy"
    BWT_FILENAME = "msbwt.npy"
    RANK_FILENAME = "inter0_rank.npz"

    def __init__(
        self,
        packed_bits,
        total_bits,
        rank_stride_bytes=64,
        rank_prefix=None,
    ):
        packed_bits = np.asarray(packed_bits)
        if packed_bits.dtype != np.dtype("uint8"):
            raise TypeError("packed_bits must have dtype uint8")
        if packed_bits.ndim != 1:
            raise ValueError("packed_bits must be one-dimensional")

        total_bits = int(total_bits)
        rank_stride_bytes = int(rank_stride_bytes)

        if total_bits < 0:
            raise ValueError("total_bits must be non-negative")
        if rank_stride_bytes <= 0:
            raise ValueError("rank_stride_bytes must be positive")

        needed_bytes = (total_bits + 7) // 8
        if packed_bits.shape[0] < needed_bytes:
            raise ValueError(
                "interleave is too short: need %d bytes for %d bits, found %d"
                % (needed_bytes, total_bits, packed_bits.shape[0])
            )

        self.packed_bits = packed_bits
        self.total_bits = total_bits
        self.rank_stride_bytes = rank_stride_bytes
        self._used_bytes = needed_bytes

        if rank_prefix is None:
            self.rank_prefix = self._build_rank_prefix()
        else:
            rank_prefix = np.asarray(rank_prefix, dtype=np.uint64)
            expected = self._num_rank_blocks() + 1
            if rank_prefix.ndim != 1 or rank_prefix.shape[0] != expected:
                raise ValueError(
                    "rank_prefix has shape %r; expected (%d,)"
                    % (rank_prefix.shape, expected)
                )
            self.rank_prefix = rank_prefix

    @classmethod
    def from_directory(
        cls,
        merged_bwt_dir,
        rank_stride_bytes=64,
        use_saved_rank=True,
        mmap=True,
    ):
        """Load ``inter0.npy`` and infer valid bit length from ``msbwt.npy``.

        Inferring the length from the merged BWT is important because
        ``inter0.npy`` is byte-packed and may contain padding bits in its final
        byte.

        A saved ``inter0_rank.npz`` is used only if it is byte-identical in
        every way that can affect source counts: matching ``total_bits``,
        matching stride, a matching content digest of the current
        ``inter0.npy``, a matching total 1-bit count, and an internally
        consistent sampled prefix.  A stale, corrupt, truncated, or
        incompatible cache is DERIVED data and is silently rebuilt from
        ``inter0.npy``; it is never allowed to produce wrong counts.
        """
        interleave_path = os.path.join(merged_bwt_dir, cls.INTERLEAVE_FILENAME)
        bwt_path = os.path.join(merged_bwt_dir, cls.BWT_FILENAME)

        if not os.path.exists(interleave_path):
            raise IOError(
                "Two-source provenance not found: %s is missing" % interleave_path
            )
        if not os.path.exists(bwt_path):
            raise IOError(
                "Cannot determine merged BWT length: %s is missing" % bwt_path
            )

        mmap_mode = "r" if mmap else None
        packed = np.load(interleave_path, mmap_mode=mmap_mode)
        bwt = np.load(bwt_path, mmap_mode=mmap_mode)
        if bwt.ndim != 1:
            raise ValueError("msbwt.npy must be one-dimensional")
        total_bits = int(bwt.shape[0])

        rank_path = os.path.join(merged_bwt_dir, cls.RANK_FILENAME)
        if use_saved_rank and os.path.exists(rank_path):
            try:
                saved = np.load(rank_path, allow_pickle=False)
                saved_total_bits = int(saved["total_bits"][0])
                saved_stride = int(saved["rank_stride_bytes"][0])
                if (
                    saved_total_bits == total_bits
                    and saved_stride == int(rank_stride_bytes)
                    and cls._saved_cache_matches(saved, packed)
                ):
                    prefix = np.asarray(saved["rank_prefix"], dtype=np.uint64)
                    needed = (total_bits + 7) // 8
                    num_blocks = (
                        (needed + rank_stride_bytes - 1) // rank_stride_bytes
                        if needed else 0
                    )
                    saved_ones = int(saved["inter0_total_ones"][0])
                    if cls._prefix_consistent(prefix, num_blocks, saved_ones):
                        return cls(
                            packed,
                            total_bits,
                            rank_stride_bytes=rank_stride_bytes,
                            rank_prefix=prefix,
                        )
            except (
                IOError,
                OSError,
                KeyError,
                ValueError,
                TypeError,
                _ZIP_BAD,
            ):
                # A stale/corrupt rank cache is derived data.  Ignore it and
                # rebuild from inter0.npy rather than making the MSBWT unusable
                # or returning wrong source counts.
                pass

        return cls(
            packed,
            total_bits,
            rank_stride_bytes=rank_stride_bytes,
        )

    @staticmethod
    def _interleave_digest(packed):
        """Content digest of the full stored ``inter0.npy`` array bytes."""
        return hashlib.sha256(np.ascontiguousarray(packed).tobytes()).hexdigest()

    @classmethod
    def _saved_cache_matches(cls, saved, packed):
        """Return True when the saved cache identifies THIS interleave content.

        The identity is the content digest of the full stored array plus the
        total 1-bit count over the valid storage bytes (the quantity that
        ``rank_prefix[-1]`` must equal).  A replaced or modified
        ``inter0.npy`` with the same byte length therefore fails the identity
        check and the cache is rebuilt.
        """
        try:
            digest_key = saved["inter0_sha256"]
            ones_key = saved["inter0_total_ones"]
        except KeyError:
            # Pre-identity caches (candidate-era format without the content
            # digest) cannot prove they belong to this interleave; treat them
            # as incompatible and rebuild.
            return False
        saved_digest = bytes(digest_key.flat[0])
        if isinstance(saved_digest, bytes):
            saved_digest = saved_digest.decode("ascii")
        if saved_digest != cls._interleave_digest(packed):
            return False
        total_bits = int(saved["total_bits"][0])
        needed_bytes = (total_bits + 7) // 8
        if int(ones_key[0]) != cls._count_ones(packed, needed_bytes):
            return False
        return True

    @classmethod
    def _count_ones(cls, packed, used_bytes):
        """Total 1 bits over the first ``used_bytes`` stored bytes.

        Matches the accumulation performed by ``_build_rank_prefix`` so
        ``prefix[-1] == inter0_total_ones`` is a valid internal consistency
        check.  Padding bits beyond ``used_bytes`` are excluded.
        """
        return int(
            _POPCOUNT[np.ascontiguousarray(packed)[:used_bytes]].sum(
                dtype=np.uint64
            )
        )

    @staticmethod
    def _prefix_consistent(prefix, num_blocks, expected_total_ones):
        """Internal consistency of a loaded rank prefix."""
        if prefix.ndim != 1:
            return False
        if prefix.shape[0] != num_blocks + 1:
            return False
        if int(prefix[0]) != 0:
            return False
        if int(prefix[-1]) != expected_total_ones:
            return False
        prev = 0
        for value in prefix:
            cur = int(value)
            if cur < prev:
                return False
            prev = cur
        return True

    def _num_rank_blocks(self):
        if self._used_bytes == 0:
            return 0
        return (
            self._used_bytes + self.rank_stride_bytes - 1
        ) // self.rank_stride_bytes

    def _build_rank_prefix(self):
        """Build sampled counts of 1-bits at rank-block boundaries."""
        num_blocks = self._num_rank_blocks()
        prefix = np.zeros(num_blocks + 1, dtype=np.uint64)

        for block_id in range(num_blocks):
            start = block_id * self.rank_stride_bytes
            end = min(start + self.rank_stride_bytes, self._used_bytes)
            # Padding in a partial final byte can be counted here, but no valid
            # rank query can use the prefix *after* that final partial byte.
            # rank1(total_bits) masks the partial byte itself, so padding never
            # contributes to a user-visible rank result.
            block_count = _POPCOUNT[self.packed_bits[start:end]].sum(
                dtype=np.uint64
            )
            prefix[block_id + 1] = prefix[block_id] + block_count

        return prefix

    def save_rank_index(self, merged_bwt_dir):
        """Persist the sampled rank directory as derived data.

        The persisted file is DERIVED / REBUILDABLE.  Deleting it never
        destroys information; it is deterministically rebuilt from
        ``inter0.npy`` plus the merged BWT length.

        Persisted fields (``inter0_rank.npz``, an uncompressed zip of .npy
        members):

        - ``rank_prefix``: uint64 array of length ``num_blocks + 1``; sample
          ``i`` is the number of source-1 bits in ``[0, i * stride)`` bytes.
        - ``total_bits``: uint64 scalar, the valid row count.
        - ``rank_stride_bytes``: uint64 scalar, the sampling stride.
        - ``inter0_sha256``: S64 ASCII hex digest of the full stored
          ``inter0.npy`` array bytes (cache identity).
        - ``inter0_total_ones``: uint64 scalar, total 1 bits over the valid
          storage bytes (cache identity + prefix consistency).
        """
        rank_path = os.path.join(merged_bwt_dir, self.RANK_FILENAME)
        np.savez(
            rank_path,
            rank_prefix=self.rank_prefix,
            total_bits=np.asarray([self.total_bits], dtype=np.uint64),
            rank_stride_bytes=np.asarray(
                [self.rank_stride_bytes], dtype=np.uint64
            ),
            inter0_sha256=np.asarray(
                [self._interleave_digest(self.packed_bits)], dtype="S64"
            ),
            inter0_total_ones=np.asarray(
                [self._count_ones(self.packed_bits, self._used_bytes)],
                dtype=np.uint64
            ),
        )
        return rank_path

    def _check_position(self, position, allow_end=True):
        position = int(position)
        high = self.total_bits if allow_end else self.total_bits - 1
        if position < 0 or position > high:
            if allow_end:
                raise IndexError(
                    "position %d outside [0, %d]" % (position, self.total_bits)
                )
            raise IndexError(
                "position %d outside [0, %d)" % (position, self.total_bits)
            )
        return position

    def _check_interval(self, start, end):
        start = self._check_position(start, allow_end=True)
        end = self._check_position(end, allow_end=True)
        if end < start:
            raise ValueError("end must be >= start")
        return start, end

    def rank1(self, position):
        """Return number of source-1 bits in ``[0, position)``."""
        position = self._check_position(position, allow_end=True)
        if position == 0:
            return 0

        byte_index = position >> 3
        bit_offset = position & 0x7

        block_id = byte_index // self.rank_stride_bytes
        block_start = block_id * self.rank_stride_bytes

        total = int(self.rank_prefix[block_id])

        # Full bytes after the sampled boundary and before position.
        if byte_index > block_start:
            total += int(
                _POPCOUNT[
                    self.packed_bits[block_start:byte_index]
                ].sum(dtype=np.uint64)
            )

        # Low-order bits in the byte containing position.
        if bit_offset:
            mask = (1 << bit_offset) - 1
            total += int(
                _POPCOUNT[
                    int(self.packed_bits[byte_index]) & mask
                ]
            )

        return total

    def rank0(self, position):
        """Return number of source-0 bits in ``[0, position)``."""
        position = self._check_position(position, allow_end=True)
        return position - self.rank1(position)

    def source_at(self, position):
        """Return 0 or 1 for the source of one merged BWT row."""
        position = self._check_position(position, allow_end=False)
        byte_value = int(self.packed_bits[position >> 3])
        return (byte_value >> (position & 0x7)) & 0x1

    def count_source(self, source_id, start, end):
        """Count rows from one source in merged interval ``[start, end)``."""
        start, end = self._check_interval(start, end)
        source_id = int(source_id)

        if source_id == 1:
            return self.rank1(end) - self.rank1(start)
        if source_id == 0:
            return (end - start) - (
                self.rank1(end) - self.rank1(start)
            )
        raise ValueError("two-source index accepts source_id 0 or 1")

    def counts(self, start, end):
        """Return ``(source0_count, source1_count)`` for ``[start, end)``."""
        start, end = self._check_interval(start, end)
        source1 = self.rank1(end) - self.rank1(start)
        source0 = (end - start) - source1
        return source0, source1


class TwoSourceBWT(object):
    """Small wrapper adding source-aware counts to an existing merged MSBWT."""

    def __init__(
        self,
        bwt,
        source_index,
        source_names=("source0", "source1"),
    ):
        if len(source_names) != 2:
            raise ValueError("source_names must contain exactly two names")
        self.bwt = bwt
        self.source_index = source_index
        self.source_names = tuple(source_names)

        # Fail early if caller accidentally pairs the index with another BWT.
        if hasattr(bwt, "getTotalSize"):
            bwt_size = int(bwt.getTotalSize())
            if bwt_size != source_index.total_bits:
                raise ValueError(
                    "BWT has %d rows but source index has %d bits"
                    % (bwt_size, source_index.total_bits)
                )

    @classmethod
    def load(
        cls,
        merged_bwt_dir,
        source_names=("source0", "source1"),
        rank_stride_bytes=64,
        use_saved_rank=True,
        mmap=True,
        logger=None,
    ):
        """Load a merged MSBWT and its two-source provenance index."""
        from MUSCython import MultiStringBWTCython as MultiStringBWT

        bwt = MultiStringBWT.loadBWT(
            merged_bwt_dir,
            useMemmap=mmap,
            logger=logger,
        )
        source_index = TwoSourceInterleaveIndex.from_directory(
            merged_bwt_dir,
            rank_stride_bytes=rank_stride_bytes,
            use_saved_rank=use_saved_rank,
            mmap=mmap,
        )
        return cls(
            bwt,
            source_index,
            source_names=source_names,
        )

    def findIndicesOfStr(self, seq, givenRange=None):
        """Delegate to the underlying MSBWT (legacy query semantics)."""
        seq = _normalize_sequence(seq)
        if givenRange is None:
            return self.bwt.findIndicesOfStr(seq)
        return self.bwt.findIndicesOfStr(seq, givenRange)

    def countOccurrencesOfSeq(self, seq, givenRange=None):
        """Preserve the normal merged-total count API."""
        seq = _normalize_sequence(seq)
        if givenRange is None:
            return self.bwt.countOccurrencesOfSeq(seq)
        return self.bwt.countOccurrencesOfSeq(seq, givenRange)

    def countOccurrencesBySource(self, seq, givenRange=None):
        """Return exact counts from source 0 and source 1.

        The FM search is performed once on the merged BWT.  The returned
        interval is then counted against the packed source interleave.

        Returns a dict with keys ``sequence`` (bytes), ``interval`` (l, h),
        ``total`` (h - l), and one key per source name.
        """
        seq = _normalize_sequence(seq)
        if givenRange is None:
            low, high = self.bwt.findIndicesOfStr(seq)
        else:
            low, high = self.bwt.findIndicesOfStr(seq, givenRange)

        source0, source1 = self.source_index.counts(low, high)

        return {
            "sequence": seq,
            "interval": (int(low), int(high)),
            "total": int(high - low),
            self.source_names[0]: int(source0),
            self.source_names[1]: int(source1),
        }


def _normalize_sequence(seq):
    """Normalize a query to the legacy byte-string contract.

    Explicit Python-2-compatible contract (no silent encoding surprises):

    - ``bytes`` (which in Python 2 is ``str``): returned unchanged;
    - ``str`` (Python 3 only): encoded as ASCII (non-ASCII raises
      ``UnicodeEncodeError``);
    - ``unicode`` (Python 2 only): encoded as ASCII (non-ASCII raises
      ``UnicodeEncodeError``);
    - anything else: ``TypeError``.
    """
    if isinstance(seq, bytes):
        return seq
    if not hasattr(seq, "encode"):
        raise TypeError(
            "sequence must be bytes/str (or ASCII unicode), got %s"
            % type(seq).__name__
        )
    # Python 2 str (bytes) already returned above; this branch is either
    # Python 2 unicode or Python 3 str.  ASCII encoding is explicit so a
    # non-ASCII query fails loudly instead of being silently mangled.
    return seq.encode("ascii")


def countOccurrencesBySource(
    msbwt,
    source_index,
    seq,
    source_names=("source0", "source1"),
    givenRange=None,
):
    """Functional API for source-aware counts.

    This is the lowest-friction integration point for existing code that
    already has a loaded MSBWT object.
    """
    wrapper = TwoSourceBWT(
        msbwt,
        source_index,
        source_names=source_names,
    )
    return wrapper.countOccurrencesBySource(seq, givenRange=givenRange)


# Python-style alias for new code while retaining the repository's camelCase
# naming convention above.
count_occurrences_by_source = countOccurrencesBySource
