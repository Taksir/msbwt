"""Roadmap 8B.0 - bidirectional (2BWT) correctness prototype
(enhanced-modern3, EXPERIMENTAL).

Purpose: settle whether synchronized forward/reverse intervals are exact
under Holt multi-string semantics before any production bidirectional
backend is designed.  It is a feasibility gate, not a performance feature.

Construction
------------
``build_reverse_companion(forward_dir, reverse_dir)`` recovers every read
from the existing forward MSBWT, reverses it, and builds an ordinary Holt
MSBWT of the reversed reads with the Multimerge constructor.  The forward
package is not modified.  ``reverse_companion.json`` binds the companion
to the forward ``msbwt.npy`` content digest.

Bi-interval state
-----------------
For a pattern ``P`` the state is ``BiInterval(forward, reverse, size)``:
``[forward, forward + size)`` is the forward interval of ``P`` and
``[reverse, reverse + size)`` is the companion interval of ``reverse(P)``.

``extend_left(state, c)`` (``P -> cP``)
    One backward step on the forward index.  Inside the companion
    interval, rows are ordered by the symbol that follows ``reverse(P)``,
    which is the symbol that precedes ``P`` in the forward text, i.e. the
    forward BWT symbol.  So the new companion start is the old one plus the
    number of forward-interval rows whose BWT symbol sorts before ``c``
    (``$`` first: those occurrences start a read).

``extend_right(state, c)`` (``P -> Pc``)
    The same with the roles of the two indexes swapped.

Each call costs one backward step per alphabet symbol on one index (the
symbol counts come from those steps), the standard 2BWT cost.  Patterns
never cross a read boundary, matching linear-read semantics.

Limits of this prototype: the companion holds all recovered reads in
memory during construction, carries no source provenance of its own
(source queries use the forward interval, which the state always holds),
and is uncompressed.  The Multimerge constructor uses ``multiprocessing``;
call it from an importable ``__main__`` (a script file, not ``python -``),
as Python 3.14 defaults to the ``forkserver`` start method on Linux.
"""

import hashlib
import json
import logging
import os
import shutil
import tempfile
from collections import namedtuple

import numpy as np

from MUS.MultiSourceProvenance import BWT_FILENAME


COMPANION_METADATA = "reverse_companion.json"
FORMAT_NAME = "msbwt-reverse-companion"
FORMAT_VERSION = 1
SYMBOLS = b"$ACGNT"          # Holt code order: $=0 A=1 C=2 G=3 N=4 T=5
BASES = SYMBOLS[1:]
IDENTITY = (0, 1, 2, 3, 4, 5)
COMPLEMENT = (0, 5, 3, 2, 4, 1)  # $->$ A<->T C<->G N->N, by code
_COMPLEMENT_TABLE = bytes.maketrans(b"ACGNT", b"TGCNA")


class BidirectionalError(ValueError):
    """Raised for invalid bidirectional indexes or requests."""


BiInterval = namedtuple("BiInterval", ["forward", "reverse", "size"])
BiInterval.__doc__ = (
    "Synchronized intervals: forward [forward, forward+size) holds P, "
    "reverse [reverse, reverse+size) holds reverse(P).")


def _file_sha256(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            block = fp.read(chunk)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def _load_compiled(bwt_dir, mmap=True):
    from MUSCython import MultiStringBWTCython
    return MultiStringBWTCython.loadBWT(str(bwt_dir), useMemmap=mmap)


def _symbol(value):
    if isinstance(value, str):
        value = value.encode("ascii")
    if isinstance(value, int):
        value = bytes([value])
    value = bytes(value)
    if len(value) != 1 or value not in BASES:
        raise BidirectionalError(
            "extension symbol must be one of A, C, G, N, T; got %r" % value)
    return value


def _recover_reads(bwt, read_count):
    """Every read of ``bwt`` exactly once.

    LF is a permutation of the rows; each of its cycles spells one or
    more ``$``-separated reads.  Holt construction gives one read per
    cycle, but walking cycles keeps this exact for any valid collection
    BWT.
    """
    seen = np.zeros(read_count, dtype=np.bool_)
    reads = []
    for dollar_id in range(read_count):
        if seen[dollar_id]:
            continue
        recovered, rows = bwt.recoverString(dollar_id, withIndex=True)
        recovered = bytes(recovered)
        rows = np.asarray(rows, dtype=np.int64)
        dollar_rows = rows[rows < read_count]
        if recovered[:1] != b"$" or np.any(seen[dollar_rows]):
            raise BidirectionalError(
                "inconsistent LF cycle at dollar ID %d" % dollar_id)
        seen[dollar_rows] = True
        pieces = recovered[1:].split(b"$")
        if len(pieces) != dollar_rows.size or not all(pieces):
            raise BidirectionalError(
                "LF cycle at dollar ID %d does not split into reads"
                % dollar_id)
        reads.extend(pieces)
    if not seen.all() or len(reads) != read_count:
        raise BidirectionalError(
            "recovered %d reads, expected %d" % (len(reads), read_count))
    return reads


def build_reverse_companion(forward_dir, reverse_dir, overwrite=False,
                            num_procs=1, logger=None):
    """Build the reversed-read companion of an existing forward MSBWT.

    No FASTQ is needed: reads are recovered from the forward BWT.  The
    companion is built in a temporary sibling directory and published only
    after it loads and its symbol counts match the forward index.
    """
    from MUSCython import MultimergeCython

    forward_dir = str(forward_dir)
    reverse_dir = str(reverse_dir)
    if os.path.abspath(forward_dir) == os.path.abspath(reverse_dir):
        raise BidirectionalError("companion needs its own directory")
    if os.path.exists(reverse_dir) and not overwrite:
        raise BidirectionalError("output already exists: %s" % reverse_dir)
    logger = logger or logging.getLogger("msbwt.bidirectional")

    forward_rows = np.load(
        os.path.join(forward_dir, BWT_FILENAME), mmap_mode="r")
    read_count = int(np.count_nonzero(forward_rows == 0))
    if read_count == 0:
        raise BidirectionalError("forward BWT holds no reads")
    forward = _load_compiled(forward_dir)

    reversed_reads = []
    for read in _recover_reads(forward, read_count):
        # Multimerge requires '$'-terminated input; an unterminated
        # periodic read makes its worker loop forever.
        reversed_reads.append(read[::-1].decode("ascii") + "$")

    parent = os.path.dirname(os.path.abspath(reverse_dir))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    temp_dir = tempfile.mkdtemp(
        prefix=".%s.reverse-" % os.path.basename(reverse_dir), dir=parent)
    try:
        MultimergeCython.createMSBWTFromSeqs(
            reversed_reads, temp_dir, int(num_procs), False, logger)
        companion_rows = np.load(
            os.path.join(temp_dir, BWT_FILENAME), mmap_mode="r")
        forward_counts = np.bincount(forward_rows, minlength=6)
        companion_counts = np.bincount(companion_rows, minlength=6)
        if not np.array_equal(forward_counts, companion_counts):
            raise BidirectionalError(
                "companion symbol counts %r differ from forward %r"
                % (companion_counts.tolist(), forward_counts.tolist()))
        metadata = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "status": "experimental-8B.0",
            "forward_bwt_sha256": _file_sha256(
                os.path.join(forward_dir, BWT_FILENAME)),
            "companion_bwt_sha256": _file_sha256(
                os.path.join(temp_dir, BWT_FILENAME)),
            "bwt_rows": int(forward_rows.shape[0]),
            "read_count": read_count,
            "transform": "reverse (not reverse complement)",
        }
        with open(os.path.join(temp_dir, COMPANION_METADATA), "w") as fp:
            json.dump(metadata, fp, indent=2, sort_keys=True)
            fp.write("\n")
        if os.path.exists(reverse_dir):
            shutil.rmtree(reverse_dir)
        os.rename(temp_dir, reverse_dir)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return metadata


def load_companion_metadata(forward_dir, reverse_dir):
    """Validate the companion binding and return its metadata."""
    path = os.path.join(str(reverse_dir), COMPANION_METADATA)
    if not os.path.exists(path):
        raise BidirectionalError("companion metadata not found: %s" % path)
    with open(path) as fp:
        metadata = json.load(fp)
    if metadata.get("format") != FORMAT_NAME or \
            int(metadata.get("version", -1)) != FORMAT_VERSION:
        raise BidirectionalError("unsupported companion format")
    if metadata["forward_bwt_sha256"] != _file_sha256(
            os.path.join(str(forward_dir), BWT_FILENAME)):
        raise BidirectionalError(
            "companion was built for a different forward BWT")
    if metadata["companion_bwt_sha256"] != _file_sha256(
            os.path.join(str(reverse_dir), BWT_FILENAME)):
        raise BidirectionalError("companion msbwt.npy was modified")
    return metadata


class BidirectionalIndex(object):
    """Synchronized search over a forward index and a partner index.

    The partner holds ``T(P)`` for each pattern ``P``: the reversed-read
    companion with ``T = reverse`` (2BWT), or the same index with
    ``T = reverse complement`` when it contains both strands (FMD-index).
    With ``tau`` the per-symbol map (identity, or complement),
    ``T(cP) = T(P) tau(c)`` and ``T(Pc) = tau(c) T(P)``.  Inside a
    partner interval, rows are ordered by the symbol that follows ``T(P)``,
    which is ``tau`` of the symbol preceding ``P`` in the forward index;
    that gives each child's offset from one set of backward steps.
    """

    def __init__(self, forward_bwt, partner_bwt, complement=False):
        self.forward = forward_bwt
        self.partner = partner_bwt
        self.complement = bool(complement)
        self.tau = COMPLEMENT if self.complement else IDENTITY
        self.total = int(forward_bwt.getTotalSize())
        if int(partner_bwt.getTotalSize()) != self.total:
            raise BidirectionalError(
                "forward has %d rows but partner has %d"
                % (self.total, partner_bwt.getTotalSize()))

    @classmethod
    def load(cls, forward_dir, reverse_dir, mmap=True):
        """2BWT: forward package plus its reversed-read companion."""
        load_companion_metadata(forward_dir, reverse_dir)
        return cls(_load_compiled(forward_dir, mmap),
                   _load_compiled(reverse_dir, mmap))

    def transform(self, pattern):
        """``T(P)``: the partner-side spelling of ``pattern``."""
        pattern = _pattern_bytes(pattern)[::-1]
        if self.complement:
            pattern = pattern.translate(_COMPLEMENT_TABLE)
        return pattern

    def empty_pattern(self):
        """State for the empty pattern: every row on both sides."""
        return BiInterval(0, 0, self.total)

    def search(self, pattern):
        """State computed directly by two ordinary searches (the oracle
        the incremental path must reproduce)."""
        pattern = _pattern_bytes(pattern)
        if not pattern:
            return self.empty_pattern()
        f_lo, f_hi = self.forward.findIndicesOfStr(pattern)
        r_lo, r_hi = self.partner.findIndicesOfStr(self.transform(pattern))
        size = int(f_hi) - int(f_lo)
        if size != int(r_hi) - int(r_lo):
            raise BidirectionalError(
                "forward/partner counts differ for %r" % pattern)
        if size == 0:
            return BiInterval(0, 0, 0)
        return BiInterval(int(f_lo), int(r_lo), size)

    @staticmethod
    def _children(index, start, size):
        """Backward-extend ``[start, start+size)`` by every base; return
        {base code: (lo, hi)} and per-symbol preceding counts by code."""
        children = {}
        counts = [0] * len(SYMBOLS)
        for code in range(1, len(SYMBOLS)):
            lo, hi = index.findIndicesOfStr(
                SYMBOLS[code:code + 1], (int(start), int(start) + int(size)))
            children[code] = (int(lo), int(hi))
            counts[code] = int(hi) - int(lo)
        counts[0] = int(size) - sum(counts)   # rows preceded by '$'
        return children, counts

    def _extend_all(self, state, left):
        if state.size == 0:
            return {bytes([b]): BiInterval(0, 0, 0) for b in BASES}
        tau = self.tau
        result = {}
        if left:
            # Step the forward index by c; partner offset counts rows whose
            # following symbol d sorts before tau(c): those are forward
            # rows preceded by tau(d).
            children, counts = self._children(
                self.forward, state.forward, state.size)
            for code in range(1, len(SYMBOLS)):
                lo, hi = children[code]
                other = state.reverse + sum(
                    counts[tau[d]] for d in range(tau[code]))
                result[SYMBOLS[code:code + 1]] = (
                    BiInterval(lo, other, hi - lo) if hi > lo
                    else BiInterval(0, 0, 0))
        else:
            # Step the partner by tau(c); forward offset counts rows whose
            # following symbol e sorts before c: partner rows preceded by
            # tau(e).
            children, counts = self._children(
                self.partner, state.reverse, state.size)
            for code in range(1, len(SYMBOLS)):
                lo, hi = children[tau[code]]
                other = state.forward + sum(
                    counts[tau[e]] for e in range(code))
                result[SYMBOLS[code:code + 1]] = (
                    BiInterval(other, lo, hi - lo) if hi > lo
                    else BiInterval(0, 0, 0))
        return result

    def extend_left_all(self, state):
        """All one-symbol left extensions ``cP`` of ``state``."""
        return self._extend_all(state, left=True)

    def extend_right_all(self, state):
        """All one-symbol right extensions ``Pc`` of ``state``."""
        return self._extend_all(state, left=False)

    def extend_left(self, state, symbol):
        return self.extend_left_all(state)[_symbol(symbol)]

    def extend_right(self, state, symbol):
        return self.extend_right_all(state)[_symbol(symbol)]


def _pattern_bytes(pattern):
    if isinstance(pattern, str):
        pattern = pattern.encode("ascii")
    pattern = bytes(pattern)
    for value in pattern:
        if value not in BASES:
            raise BidirectionalError(
                "pattern symbols must be A, C, G, N, T; got %r" % pattern)
    return pattern
