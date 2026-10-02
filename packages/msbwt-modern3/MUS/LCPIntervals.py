"""Feature 11C - baseline LCP-interval applications over the Feature-11A
layer (enhanced-modern3).

Everything here is established suffix-array technique (Abouelhoda, Kurtz
and Ohlebusch's enhanced suffix arrays); nothing in this module is claimed
as novel.  What it adds is the integration with the existing msBWT layers:
an LCP interval is an ordinary merged-BWT interval ``[start, end)``, so the
Feature 3-7 source/group queries and Feature-9 read queries apply to it
unchanged.

Definitions (all under the Feature-11A terminator semantics: every read has
its own virtual terminator, which contributes 0 to an LCP)

``lcp-interval``
    Rows ``[start, end)`` with ``end - start >= 2`` and value ``l >= 1``
    such that every adjacent LCP inside is ``>= l``, at least one equals
    ``l``, and the boundary LCPs just outside are ``< l``.  These are the
    internal nodes of the generalized suffix tree of the reads; the node's
    string is the common ``l``-prefix of the rows.

``maximal repeat``
    A string occurring at least twice that can be extended neither to the
    right (it is an lcp-interval string) nor to the left (the BWT symbols
    of its rows are not all the same).  A ``$`` among those symbols marks
    an occurrence at a read start; distinct terminators make such an
    interval left-maximal.

``supermaximal repeat``
    A maximal repeat that is not a substring of another maximal repeat:
    its interval has no nested lcp-interval and the BWT symbols of its rows
    are pairwise distinct (each ``$`` counted as distinct).

Rows, intervals and the stored ``lcps.npy`` convention match Feature 11A:
``lcps[i] = LCP(SA[i], SA[i+1])``.

Complexity: one sequential pass over ``lcps.npy``.  Stretches below
``min_lcp`` are skipped with NumPy; the bottom-up stack runs in Python over
the remaining positions, so a large ``min_lcp`` is much faster than
``min_lcp=1``.  Spelling a repeat costs one LF walk over a single read.
"""

from collections import namedtuple

import numpy as np


DOLLAR = 0
ALPHABET = b"$ACGNT"


class LCPIntervalError(ValueError):
    """Raised for invalid LCP-interval requests."""


LCPInterval = namedtuple("LCPInterval", ["lcp", "start", "end"])
LCPInterval.__doc__ = (
    "An lcp-interval: rows [start, end) share a prefix of length lcp.")


def _check_bounds(min_lcp, max_lcp, min_size):
    min_lcp = int(min_lcp)
    if min_lcp < 1:
        raise LCPIntervalError("min_lcp must be >= 1")
    if max_lcp is not None:
        max_lcp = int(max_lcp)
        if max_lcp < min_lcp:
            raise LCPIntervalError("max_lcp must be >= min_lcp")
    min_size = int(min_size)
    if min_size < 2:
        raise LCPIntervalError("min_size must be >= 2")
    return min_lcp, max_lcp, min_size


def iter_lcp_intervals(
    lcps,
    min_lcp=1,
    max_lcp=None,
    min_size=2,
    chunk_rows=4 * 1024 * 1024,
):
    """Yield every lcp-interval with ``min_lcp <= lcp <= max_lcp`` and at
    least ``min_size`` rows.

    ``lcps`` is the stored adjacent array (length ``N - 1``), typically the
    mmap from :class:`MUS.LCP.LCPIndex`.  Intervals are produced in
    bottom-up order: a child before its parent, and siblings left to
    right.  Memory is the chunk plus the stack (bounded by the maximum
    LCP).
    """
    min_lcp, max_lcp, min_size = _check_bounds(min_lcp, max_lcp, min_size)
    n = int(lcps.shape[0])
    chunk_rows = max(1, int(chunk_rows))
    stack = []  # (lcp, start row) of open intervals, lcp increasing

    def close(value, boundary, out):
        # Close every open interval whose lcp exceeds ``value``; each ends
        # at row ``boundary`` inclusive.  Returns the leftmost start row.
        left = boundary
        while stack and value < stack[-1][0]:
            lcp, left = stack.pop()
            if (
                boundary + 1 - left >= min_size
                and (max_lcp is None or lcp <= max_lcp)
            ):
                out.append(LCPInterval(lcp, left, boundary + 1))
        return left

    for chunk_start in range(0, n, chunk_rows):
        chunk_end = min(n, chunk_start + chunk_rows)
        block = np.asarray(lcps[chunk_start:chunk_end])
        keep = block >= min_lcp
        # Visit every qualifying boundary plus the first below-threshold
        # boundary after a run (it closes the open intervals).
        previous = np.empty_like(keep)
        previous[0] = bool(stack)
        previous[1:] = keep[:-1]
        visit = np.flatnonzero(keep | previous)
        out = []
        for offset, value in zip(visit.tolist(), block[visit].tolist()):
            left = close(value, chunk_start + offset, out)
            if value >= min_lcp and (not stack or value > stack[-1][0]):
                stack.append((value, left))
        for interval in out:
            yield interval

    out = []
    close(-1, n, out)
    for interval in out:
        yield interval


def child_intervals(lcps, interval):
    """Return the children of ``interval`` as ``(start, end, lcp)`` tuples.

    Children are separated by the boundaries whose LCP equals the parent's
    value.  A singleton child (one suffix, a suffix-tree leaf) has
    ``lcp = None``; any other child is itself an lcp-interval.
    """
    lcp, start, end = int(interval[0]), int(interval[1]), int(interval[2])
    if end - start < 2:
        raise LCPIntervalError("an lcp-interval has at least two rows")
    inner = np.asarray(lcps[start:end - 1])
    if inner.size == 0 or int(inner.min()) != lcp:
        raise LCPIntervalError(
            "rows [%d, %d) are not an lcp-interval with value %d"
            % (start, end, lcp))
    cuts = (np.flatnonzero(inner == lcp) + start + 1).tolist()
    edges = [start] + cuts + [end]
    children = []
    for left, right in zip(edges[:-1], edges[1:]):
        if right - left == 1:
            children.append((left, right, None))
        else:
            children.append(
                (left, right, int(np.min(lcps[left:right - 1]))))
    return children


def preceding_symbols(bwt_rows, start, end):
    """BWT symbols of rows ``[start, end)`` (the characters preceding each
    suffix; 0 is ``$``)."""
    return np.asarray(bwt_rows[int(start):int(end)])


def is_left_maximal(bwt_rows, start, end):
    """True when the occurrences of the interval string do not all share
    the same preceding character."""
    symbols = preceding_symbols(bwt_rows, start, end)
    if symbols.size == 0:
        raise LCPIntervalError("empty interval")
    low = int(symbols.min())
    return low == DOLLAR or low != int(symbols.max())


def is_supermaximal(lcps, bwt_rows, interval):
    """True when ``interval`` is a supermaximal repeat (see module doc)."""
    for _, _, child_lcp in child_intervals(lcps, interval):
        if child_lcp is not None:
            return False
    symbols = preceding_symbols(bwt_rows, interval[1], interval[2])
    bases = symbols[symbols != DOLLAR]
    return int(np.unique(bases).size) == int(bases.size)


def iter_maximal_repeats(
    lcps,
    bwt_rows,
    min_length=1,
    max_length=None,
    min_occurrences=2,
    supermaximal=False,
    chunk_rows=4 * 1024 * 1024,
):
    """Yield the lcp-intervals that are maximal (or supermaximal) repeats.

    ``bwt_rows`` is the raw ``msbwt.npy`` symbol array (mmap is fine).
    """
    if int(bwt_rows.shape[0]) != int(lcps.shape[0]) + 1:
        raise LCPIntervalError(
            "BWT has %d rows but the LCP array implies %d"
            % (bwt_rows.shape[0], lcps.shape[0] + 1))
    for interval in iter_lcp_intervals(
        lcps,
        min_lcp=min_length,
        max_lcp=max_length,
        min_size=min_occurrences,
        chunk_rows=chunk_rows,
    ):
        if supermaximal:
            if is_supermaximal(lcps, bwt_rows, interval):
                yield interval
        elif is_left_maximal(bwt_rows, interval.start, interval.end):
            yield interval


def interval_sequence(bwt, interval):
    """Spell the string of ``interval`` (its first ``lcp`` symbols).

    ``bwt`` must expose the Holt API ``getSequenceDollarID(row,
    returnOffset=True)`` and ``recoverString(dollar_id)``, which returns
    ``'$' + read``.  Cost: one LF walk over the read holding the first
    row's suffix.
    """
    lcp, start = int(interval[0]), int(interval[1])
    dollar_id, offset = bwt.getSequenceDollarID(start, returnOffset=True)
    recovered = bwt.recoverString(int(dollar_id))
    if isinstance(recovered, str):
        recovered = recovered.encode("ascii")
    recovered = bytes(recovered)
    sequence = recovered[1 + int(offset):1 + int(offset) + lcp]
    if len(sequence) != lcp or b"$" in sequence:
        raise LCPIntervalError(
            "row %d: recovered %r is shorter than lcp %d; the LCP layer "
            "does not match this BWT" % (start, sequence, lcp))
    return sequence
