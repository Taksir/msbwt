"""M3-R64-W1 regression: F13A rank-contract normalization.

Contract (``MUS/BackendContract.py`` BACKEND_PRIMITIVES):
    rank(c, i) = Occ(c, i)          -- pure occurrence count

Holt legacy primitive ``getOccurrenceOfCharAtIndex(c, i)`` returns
``C[c] + Occ(c, i)`` (full-FM/LF-stepping value; FM samples are seeded from
the cumulative-count array).  Pre-repair ``LegacyBWTAdapter.rank`` delegated
verbatim to whichever probe matched first, so wrapping a Holt-only backend
silently returned ``C[c] + Occ(c, i)``.  The repaired adapter normalizes the
Holt fallback via ``raw(c, i) - raw(c, 0)`` (``Occ(x, 0) == 0`` makes
``raw(x, 0) == C[x]``), keeps the preferred pure-Occ path untouched, and
passes generic ``rank`` backends through unmodified.
"""

import unittest

from MUS.BackendContract import LegacyBWTAdapter

ROWS = [1, 0, 1, 1, 2, 0, 1]
VC_LEN = 6


def _cumulative():
    counts = [ROWS.count(s) for s in range(VC_LEN)]
    cumulative = []
    running = 0
    for symbol in range(VC_LEN):
        cumulative.append(running)
        running += counts[symbol]
    return cumulative


class HoltOnlyBackend(object):
    """Exposes ONLY the Holt-style full-FM primitive (C[c] + Occ(c, i))."""

    def __init__(self):
        self.cumulative = _cumulative()
        self.calls = []

    def getOccurrenceOfCharAtIndex(self, symbol, index):
        self.calls.append((symbol, index))
        return self.cumulative[symbol] + sum(
            1 for row in ROWS[:index] if row == symbol
        )

    def getTotalSize(self):
        return len(ROWS)


class PureOccBackend(object):
    """Exposes ONLY a genuine pure-Occ primitive."""

    def getOccurrence(self, symbol, index):
        return sum(1 for row in ROWS[:index] if row == symbol)

    def getTotalSize(self):
        return len(ROWS)


class GenericRankBackend(object):
    """Exposes ONLY its own contract-compliant ``rank``."""

    def __init__(self):
        self.seen = None

    def rank(self, symbol, position):
        self.seen = (symbol, position)
        return sum(1 for row in ROWS[:position] if row == symbol)

    def getTotalSize(self):
        return len(ROWS)


class RankNormalizationTests(unittest.TestCase):
    def test_holt_only_backend_returns_pure_occ(self):
        backend = HoltOnlyBackend()
        adapter = LegacyBWTAdapter(backend)
        for symbol in (0, 1, 2, 5):
            for position in range(len(ROWS) + 1):
                expected = sum(
                    1 for row in ROWS[:position] if row == symbol
                )
                self.assertEqual(
                    adapter.rank(symbol, position),
                    expected,
                    (symbol, position),
                )

    def test_holt_normalization_uses_c_offset_probe(self):
        backend = HoltOnlyBackend()
        adapter = LegacyBWTAdapter(backend)
        adapter.rank(1, 3)
        # raw(c, i) and raw(c, 0) must both have been consulted.
        self.assertIn((1, 3), backend.calls)
        self.assertIn((1, 0), backend.calls)

    def test_rank_zero_is_zero_for_every_symbol(self):
        adapter = LegacyBWTAdapter(HoltOnlyBackend())
        for symbol in range(VC_LEN):
            self.assertEqual(adapter.rank(symbol, 0), 0)

    def test_pure_occ_backend_path_unchanged(self):
        backend = PureOccBackend()
        adapter = LegacyBWTAdapter(backend)
        for symbol in (0, 1, 2):
            for position in range(len(ROWS) + 1):
                expected = sum(
                    1 for row in ROWS[:position] if row == symbol
                )
                self.assertEqual(
                    adapter.rank(symbol, position),
                    expected,
                    (symbol, position),
                )

    def test_generic_rank_backend_passthrough_unnormalized(self):
        backend = GenericRankBackend()
        adapter = LegacyBWTAdapter(backend)
        expected = sum(1 for row in ROWS[:4] if row == 1)
        self.assertEqual(adapter.rank(1, 4), expected)
        self.assertEqual(backend.seen, (1, 4))

    def test_capability_reporting_unchanged(self):
        for backend in (
            HoltOnlyBackend(),
            PureOccBackend(),
            GenericRankBackend(),
        ):
            adapter = LegacyBWTAdapter(backend)
            self.assertTrue(adapter.has_capability("rank"))


if __name__ == "__main__":
    unittest.main()
