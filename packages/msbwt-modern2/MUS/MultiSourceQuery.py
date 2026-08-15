"""Constituent-specific queries over a provenance-preserving multi-merged
MSBWT (Features 3-6, enhanced-modern2).

This is the additive query layer over the verified Feature-2 provenance tree
(``MUS.MultiSourceProvenance``) and the verified Feature-1 rank primitive
(``MUS.SourceIndex.TwoSourceInterleaveIndex``).  It adapts the Point-3/4/5/6
candidates (``research/feature-candidates/3/``, ``4/``, ``5 and 6/``) into
the msbwt-modern2 production tree with:

- Python 2.7 compatibility (the candidate used the Python-3-only ``Path``
  type, which does not exist in the Python 2.7 standard library);
- hardened rank-cache identity: persisted rank samples carry the interleave
  content digest and total 1-bit count so a same-length replaced interleave
  can never silently consume a stale cache (mirrors the verified Feature-1
  cache contract);
- the strict sequence-normalization contract of ``MUS.SourceIndex``.

Algorithm
---------

For a merged FM interval ``[l, r)`` and a requested constituent source, the
interval is projected down the source's root-to-leaf path.  At a left edge::

    [l, r) -> [rank0(l), rank0(r))

and at a right edge::

    [l, r) -> [rank1(l), rank1(r))

Because every two-way merge is a stable interleaving of the child
suffix/BWT orders (verified in Features 1-2), the final interval is the
constituent-local FM interval and its length is the exact number of
occurrences of the pattern in that constituent.  For a balanced tree with
``F`` sources a single constituent query costs one merged FM search plus
O(log F) rank projections.

Feature 4 adds the sparse source-listing layer: ``nonzeroSources`` /
``listSourcesWithOccurrences`` perform ONE merged FM search and then
descend the provenance tree once, projecting the interval to both children
at every internal node and pruning empty subtrees, so only constituents
with positive counts are materialized (exact counts, deterministic
provenance/input order, optional constituent-local intervals and traversal
statistics).

Features 5-6 add the aggregate layers: ``sourceFrequency`` /
``countSourcesWithOccurrences`` (Feature 5) is a count-only traversal that
returns the number of constituents containing the pattern without
materializing source dictionaries, and ``topSources`` /
``topSourcesByAbundance`` (Feature 6) returns the exact top-k constituents
by occurrence count from the Feature-4 sparse candidates with deterministic
tie-breaking (larger count first, then provenance/input source order).

The implementation is intentionally pure Python/NumPy and lazy-loads only
the interleave rank indexes required by queried source paths.  It does not
modify Holt/McMillan's FM-index or merge algorithm.

Persistence classification (per the enhanced-modern2 persistence rule):

- ``provenance.json`` + ``provenance/interleaves/<node-id>.npy`` +
  ``inter0.npy`` -- AUTHORITATIVE (Feature 2); this module only reads them.
- ``provenance/ranks/<node-id>.npz`` -- DERIVED / REBUILDABLE rank samples.
  They can always be rebuilt from the authoritative interleaves; a stale,
  corrupt, truncated, or identity-mismatching cache is silently rebuilt and
  never used to produce counts.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""

from __future__ import absolute_import

import hashlib
import heapq
import os
import zipfile

import numpy as np

from MUS.MultiSourceProvenance import (
    ProvenanceError,
    load_manifest,
)
from MUS.SourceIndex import TwoSourceInterleaveIndex, _POPCOUNT


RANK_DIRNAME = "ranks"
RANK_FILE_SUFFIX = ".npz"

# zipfile.BadZipFile (Python 3) / zipfile.BadZipfile (Python 2.7)
_ZIP_BAD = getattr(zipfile, "BadZipFile", None) or getattr(
    zipfile, "BadZipfile", None
)


class MultiSourceQueryError(ValueError):
    """Raised when a constituent query cannot be resolved safely."""


def _normalize_sequence(seq):
    """Explicit Python-2-compatible normalization (contract of SourceIndex).

    ``bytes`` (Python 2 ``str``) is returned unchanged; ``str`` (Python 3)
    and ``unicode`` (Python 2) are encoded as ASCII (non-ASCII raises
    ``UnicodeEncodeError``); anything else raises ``TypeError``.
    """
    if isinstance(seq, bytes):
        return seq
    if not hasattr(seq, "encode"):
        raise TypeError(
            "sequence must be bytes/str (or ASCII unicode), got %s"
            % type(seq).__name__
        )
    return seq.encode("ascii")


class MultiSourceQueryIndex(object):
    """Project merged FM intervals into any constituent source.

    Parameters
    ----------
    merged_bwt_dir : str
        Final Feature-2 merged BWT directory containing ``provenance.json``
        and the saved internal-node interleaves.
    rank_stride_bytes : int, optional
        Sampling stride used by ``TwoSourceInterleaveIndex``.
    mmap : bool, optional
        Memory-map interleave arrays instead of eagerly copying them.
    use_saved_rank : bool, optional
        Load per-node rank caches from ``provenance/ranks`` when available
        and identity-valid.
    validate_manifest : bool, optional
        Validate the provenance manifest (digests, tree lengths) on load.

    Notes
    -----
    The object precomputes only source -> branch-path metadata.  Rank
    indexes are loaded lazily as source paths are queried, which matters for
    large provenance trees when an application accesses only a few
    constituents.
    """

    def __init__(
        self,
        merged_bwt_dir,
        rank_stride_bytes=64,
        mmap=True,
        use_saved_rank=True,
        validate_manifest=True,
    ):
        self.merged_bwt_dir = str(merged_bwt_dir)
        self.rank_stride_bytes = int(rank_stride_bytes)
        self.mmap = bool(mmap)
        self.use_saved_rank = bool(use_saved_rank)

        if self.rank_stride_bytes <= 0:
            raise ValueError("rank_stride_bytes must be positive")

        self.manifest = load_manifest(
            self.merged_bwt_dir,
            validate=validate_manifest,
        )
        self.total_bits = int(self.manifest["root"]["length"])

        self._sources_by_id = {}
        self._source_ids_by_name = {}
        for source in self.manifest["sources"]:
            sid = str(source["id"])
            name = str(source.get("name", sid))
            self._sources_by_id[sid] = source
            self._source_ids_by_name.setdefault(name, []).append(sid)

        self._paths = {}
        self._nodes_by_id = {}
        self._build_paths(self.manifest["root"], [])

        # provenance/input order index, the deterministic tie-breaker for
        # equal-abundance top-k results (Feature 5/6)
        self._source_order = {
            str(source["id"]): i
            for i, source in enumerate(self.manifest["sources"])
        }

        # Lazy cache: node_id -> TwoSourceInterleaveIndex.
        self._rank_indexes = {}

    @property
    def source_count(self):
        return len(self._sources_by_id)

    @property
    def loaded_rank_node_count(self):
        """Number of internal-node rank indexes materialized so far."""
        return len(self._rank_indexes)

    def list_sources(self):
        return list(self.manifest["sources"])

    def resolve_source(self, source):
        """Resolve a stable source ID or an unambiguous source name."""
        source = str(source)
        if source in self._sources_by_id:
            return source

        matches = self._source_ids_by_name.get(source, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise MultiSourceQueryError(
                "source name %r is ambiguous; use a stable source ID" % source
            )
        raise KeyError("unknown source ID/name: %s" % source)

    def source_record(self, source):
        sid = self.resolve_source(source)
        return dict(self._sources_by_id[sid])

    def source_path(self, source):
        """Return a copy of the source's root-to-leaf branch path.

        Each item is ``(node_id, branch)`` where branch 0 selects the left
        child and branch 1 selects the right child.
        """
        sid = self.resolve_source(source)
        return list(self._paths[sid])

    def _build_paths(self, node, path):
        node_type = node["type"]
        if node_type == "leaf":
            sid = str(node["source_id"])
            if sid in self._paths:
                raise ProvenanceError(
                    "duplicate leaf source ID in tree: %s" % sid
                )
            self._paths[sid] = list(path)
            return

        if node_type != "merge":
            raise ProvenanceError(
                "unknown provenance node type: %r" % node_type
            )

        node_id = str(node["node_id"])
        if node_id in self._nodes_by_id:
            raise ProvenanceError("duplicate internal node ID: %s" % node_id)
        self._nodes_by_id[node_id] = node

        self._build_paths(node["left"], path + [(node_id, 0)])
        self._build_paths(node["right"], path + [(node_id, 1)])

    def _rank_cache_path(self, node_id):
        return os.path.join(
            self.merged_bwt_dir,
            "provenance",
            RANK_DIRNAME,
            str(node_id) + RANK_FILE_SUFFIX,
        )

    @staticmethod
    def _array_sha256(array):
        """Content digest of the full stored interleave array bytes."""
        return hashlib.sha256(
            np.ascontiguousarray(array).tobytes()
        ).hexdigest()

    def _load_saved_rank(self, node_id, expected_bits, packed):
        """Load a saved rank cache only when it provably matches this node.

        Identity is bound to the authoritative interleave content (digest of
        the full stored array) and the total 1-bit count over the valid
        storage bytes.  A stale, corrupt, truncated, or incompatible cache is
        DERIVED data: it is silently ignored (rebuilt from the interleave)
        and can never produce wrong counts.
        """
        if not self.use_saved_rank:
            return None
        path = self._rank_cache_path(node_id)
        if not os.path.exists(path):
            return None
        try:
            saved = np.load(path, allow_pickle=False)
            saved_total_bits = int(saved["total_bits"][0])
            saved_stride = int(saved["rank_stride_bytes"][0])
            if (
                saved_total_bits != int(expected_bits)
                or saved_stride != self.rank_stride_bytes
            ):
                return None
            try:
                digest_key = saved["interleave_sha256"]
                ones_key = saved["interleave_total_ones"]
            except KeyError:
                # Pre-identity caches cannot prove they belong to this
                # interleave; treat them as incompatible and rebuild.
                return None
            saved_digest = bytes(digest_key.flat[0])
            if isinstance(saved_digest, bytes):
                saved_digest = saved_digest.decode("ascii")
            if saved_digest != self._array_sha256(packed):
                return None
            needed_bytes = (int(expected_bits) + 7) // 8
            if int(ones_key[0]) != self._count_ones(packed, needed_bytes):
                return None
            prefix = np.asarray(saved["rank_prefix"], dtype=np.uint64)
            num_blocks = self._rank_block_count(needed_bytes,
                                                self.rank_stride_bytes)
            if not self._prefix_consistent(prefix, num_blocks, int(ones_key[0])):
                return None
            return prefix
        except (
            IOError,
            OSError,
            KeyError,
            ValueError,
            TypeError,
            _ZIP_BAD,
        ):
            # Derived cache only.  A corrupt/stale file should never make the
            # primary provenance structure unusable.
            return None

    @staticmethod
    def _count_ones(packed, used_bytes):
        """Total 1 bits over the first ``used_bytes`` stored bytes."""
        return int(
            _POPCOUNT[np.ascontiguousarray(packed)[:used_bytes]].sum(
                dtype=np.uint64
            )
        )

    @staticmethod
    def _rank_block_count(used_bytes, stride):
        if used_bytes == 0:
            return 0
        return (used_bytes + stride - 1) // stride

    @staticmethod
    def _prefix_consistent(prefix, num_blocks, expected_total_ones):
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

    def _get_rank_index(self, node_id):
        node_id = str(node_id)
        if node_id in self._rank_indexes:
            return self._rank_indexes[node_id]

        node = self._nodes_by_id[node_id]
        interleave_path = os.path.join(
            self.merged_bwt_dir, str(node["interleave"])
        )
        mmap_mode = "r" if self.mmap else None
        packed = np.load(interleave_path, mmap_mode=mmap_mode)
        total_bits = int(node["length"])
        rank_prefix = self._load_saved_rank(node_id, total_bits, packed)

        rank_index = TwoSourceInterleaveIndex(
            packed,
            total_bits=total_bits,
            rank_stride_bytes=self.rank_stride_bytes,
            rank_prefix=rank_prefix,
        )
        self._rank_indexes[node_id] = rank_index
        return rank_index

    def save_loaded_rank_indexes(self):
        """Persist rank samples for internal nodes loaded by queries.

        Only nodes already touched by source queries are written.  This keeps
        preprocessing incremental for very large multi-source trees.

        Persisted fields (``provenance/ranks/<node-id>.npz``, an uncompressed
        zip of .npy members):

        - ``rank_prefix``: uint64 array of sampled 1-bit counts;
        - ``total_bits``: uint64 scalar, the node's row count;
        - ``rank_stride_bytes``: uint64 scalar, the sampling stride;
        - ``interleave_sha256``: S64 ASCII hex digest of the full stored
          interleave array bytes (cache identity);
        - ``interleave_total_ones``: uint64 scalar, total 1 bits over the
          valid storage bytes (cache identity + prefix consistency).

        The file is DERIVED / REBUILDABLE.  Deleting it never destroys
        information; it is deterministically rebuilt from the authoritative
        interleave plus the manifest length.
        """
        rank_dir = os.path.join(
            self.merged_bwt_dir, "provenance", RANK_DIRNAME
        )
        if not os.path.isdir(rank_dir):
            os.makedirs(rank_dir)
        written = []
        for node_id, rank_index in self._rank_indexes.items():
            path = self._rank_cache_path(node_id)
            packed = rank_index.packed_bits
            used_bytes = (rank_index.total_bits + 7) // 8
            np.savez(
                path,
                rank_prefix=rank_index.rank_prefix,
                total_bits=np.asarray([rank_index.total_bits], dtype=np.uint64),
                rank_stride_bytes=np.asarray(
                    [rank_index.rank_stride_bytes], dtype=np.uint64
                ),
                interleave_sha256=np.asarray(
                    [self._array_sha256(packed)], dtype="S64"
                ),
                interleave_total_ones=np.asarray(
                    [self._count_ones(packed, used_bytes)], dtype=np.uint64
                ),
            )
            written.append(path)
        return written

    def _check_interval(self, start, end):
        start = int(start)
        end = int(end)
        if start < 0 or end < start or end > self.total_bits:
            raise IndexError(
                "merged interval [%d, %d) outside [0, %d)"
                % (start, end, self.total_bits)
            )
        return start, end

    def project_interval(self, source, start, end, trace=False):
        """Project merged interval ``[start, end)`` to one constituent.

        Returns
        -------
        tuple
            ``(local_start, local_end)`` by default.

        If ``trace=True`` returns ``((local_start, local_end), steps)`` where
        each step records the interval before/after one provenance-tree rank
        projection.  The trace is useful for tests/debugging and is not
        needed for normal queries.
        """
        sid = self.resolve_source(source)
        start, end = self._check_interval(start, end)

        l = start
        r = end
        steps = []
        for node_id, branch in self._paths[sid]:
            rank_index = self._get_rank_index(node_id)
            before = (l, r)
            if branch == 0:
                l = rank_index.rank0(l)
                r = rank_index.rank0(r)
            else:
                l = rank_index.rank1(l)
                r = rank_index.rank1(r)

            if trace:
                steps.append(
                    {
                        "node_id": node_id,
                        "branch": branch,
                        "before": before,
                        "after": (int(l), int(r)),
                    }
                )

        result = (int(l), int(r))
        if trace:
            return result, steps
        return result

    def count_interval(self, source, start, end):
        local_start, local_end = self.project_interval(source, start, end)
        return local_end - local_start

    def nonzero_sources_interval(
        self,
        start,
        end,
        include_intervals=False,
        include_stats=False,
    ):
        """List only constituents with nonzero counts in ``[start, end)``.

        This is the Feature-4 sparse document/source-listing primitive.
        Instead of projecting the same merged interval independently down
        every source path, it descends the provenance tree once.  At each
        internal node, the parent interval is projected to the left and
        right child using rank0 and rank1.  A child whose projected interval
        is empty is pruned immediately, so no rank structures below that
        branch are touched.

        Parameters
        ----------
        start, end : int
            Merged-BWT interval ``[start, end)``.
        include_intervals : bool, optional
            Include each leaf's exact constituent-local FM interval.
        include_stats : bool, optional
            Return ``(results, stats)`` with traversal counters useful for
            testing/profiling.  These counters are descriptive only and do
            not alter query behavior.

        Returns
        -------
        list of dict
            One record per nonzero source, in provenance/input order.  Every
            record contains ``source_id``, ``source_name`` and exact
            ``count``.
        """
        start, end = self._check_interval(start, end)

        stats = {
            "root_interval_size": int(end - start),
            "internal_nodes_visited": 0,
            "branches_pruned": 0,
            "leaves_reported": 0,
            "rank_nodes_loaded_before": self.loaded_rank_node_count,
        }
        results = []

        if start == end:
            stats["rank_nodes_loaded_after"] = self.loaded_rank_node_count
            stats["rank_nodes_loaded_for_query"] = 0
            if include_stats:
                return results, stats
            return results

        def descend(node, l, r):
            if l == r:
                # This guard is normally reached before recursion, but
                # keeping it here makes the pruning invariant explicit and
                # robust.
                stats["branches_pruned"] += 1
                return

            node_type = node["type"]
            if node_type == "leaf":
                sid = str(node["source_id"])
                source = self._sources_by_id[sid]
                record = {
                    "source_id": sid,
                    "source_name": str(source.get("name", sid)),
                    "count": int(r - l),
                }
                if include_intervals:
                    record["source_interval"] = (int(l), int(r))
                results.append(record)
                stats["leaves_reported"] += 1
                return

            if node_type != "merge":
                raise ProvenanceError(
                    "unknown provenance node type: %r" % node_type
                )

            stats["internal_nodes_visited"] += 1
            rank_index = self._get_rank_index(str(node["node_id"]))

            left_l = rank_index.rank0(l)
            left_r = rank_index.rank0(r)
            right_l = rank_index.rank1(l)
            right_r = rank_index.rank1(r)

            if left_l == left_r:
                stats["branches_pruned"] += 1
            else:
                descend(node["left"], left_l, left_r)

            if right_l == right_r:
                stats["branches_pruned"] += 1
            else:
                descend(node["right"], right_l, right_r)

        descend(self.manifest["root"], start, end)

        stats["rank_nodes_loaded_after"] = self.loaded_rank_node_count
        stats["rank_nodes_loaded_for_query"] = (
            stats["rank_nodes_loaded_after"]
            - stats["rank_nodes_loaded_before"]
        )

        if include_stats:
            return results, stats
        return results

    def source_frequency_interval(
        self,
        start,
        end,
        include_stats=False,
    ):
        """Count how many constituent sources are nonzero in ``[start, end)``.

        This is the Feature-5 count-only document/source-frequency
        primitive.  It uses the same sparse provenance traversal as
        ``nonzero_sources_interval`` but does not allocate source-result
        dictionaries or materialize source IDs: at each nonempty leaf it
        increments one integer.

        The count is exact.  Empty child intervals are pruned immediately.
        """
        start, end = self._check_interval(start, end)

        stats = {
            "root_interval_size": int(end - start),
            "internal_nodes_visited": 0,
            "branches_pruned": 0,
            "nonzero_leaves": 0,
            "rank_nodes_loaded_before": self.loaded_rank_node_count,
        }

        if start == end:
            stats["rank_nodes_loaded_after"] = self.loaded_rank_node_count
            stats["rank_nodes_loaded_for_query"] = 0
            if include_stats:
                return 0, stats
            return 0

        def count_nonzero(node, l, r):
            if l == r:
                stats["branches_pruned"] += 1
                return 0

            node_type = node["type"]
            if node_type == "leaf":
                stats["nonzero_leaves"] += 1
                return 1

            if node_type != "merge":
                raise ProvenanceError(
                    "unknown provenance node type: %r" % node_type
                )

            stats["internal_nodes_visited"] += 1
            rank_index = self._get_rank_index(str(node["node_id"]))

            left_l = rank_index.rank0(l)
            left_r = rank_index.rank0(r)
            right_l = rank_index.rank1(l)
            right_r = rank_index.rank1(r)

            total = 0
            if left_l == left_r:
                stats["branches_pruned"] += 1
            else:
                total += count_nonzero(node["left"], left_l, left_r)

            if right_l == right_r:
                stats["branches_pruned"] += 1
            else:
                total += count_nonzero(node["right"], right_l, right_r)

            return total

        frequency = int(count_nonzero(self.manifest["root"], start, end))

        stats["rank_nodes_loaded_after"] = self.loaded_rank_node_count
        stats["rank_nodes_loaded_for_query"] = (
            stats["rank_nodes_loaded_after"]
            - stats["rank_nodes_loaded_before"]
        )

        if include_stats:
            return frequency, stats
        return frequency

    def top_sources_interval(
        self,
        start,
        end,
        k,
        include_intervals=False,
        include_stats=False,
    ):
        """Return the exact top-k nonzero sources for merged interval.

        Feature 6 intentionally uses the already-correct Feature-4 sparse
        listing as its baseline.  Selection is bounded by ``k`` via
        ``heapq.nlargest`` rather than sorting an F-length zero-filled
        vector.

        Ordering is deterministic:

        1. larger exact occurrence count first;
        2. provenance/input source order for ties.
        """
        start, end = self._check_interval(start, end)
        k = int(k)
        if k < 0:
            raise ValueError("k must be non-negative")

        if include_stats:
            sources, sparse_stats = self.nonzero_sources_interval(
                start,
                end,
                include_intervals=include_intervals,
                include_stats=True,
            )
        else:
            sources = self.nonzero_sources_interval(
                start,
                end,
                include_intervals=include_intervals,
                include_stats=False,
            )
            sparse_stats = None

        if k == 0 or not sources:
            top = []
        elif k >= len(sources):
            # Feature-4 results are in stable provenance order, so this
            # produces the desired count-descending / source-order tie
            # break.
            top = sorted(
                sources,
                key=lambda rec: (
                    -int(rec["count"]),
                    self._source_order[str(rec["source_id"])],
                ),
            )
        else:
            indexed = list(enumerate(sources))
            selected = heapq.nlargest(
                k,
                indexed,
                key=lambda item: (int(item[1]["count"]), -item[0]),
            )
            top = [item[1] for item in selected]

        if include_stats:
            stats = dict(sparse_stats)
            stats.update(
                {
                    "k": k,
                    "nonzero_sources_considered": len(sources),
                    "sources_returned": len(top),
                }
            )
            return top, stats
        return top


class MultiSourceBWT(object):
    """Wrap a Feature-2 merged MSBWT with constituent-specific query
    methods."""

    def __init__(self, bwt, source_index):
        self.bwt = bwt
        self.source_index = source_index
        if hasattr(bwt, "getTotalSize"):
            bwt_size = int(bwt.getTotalSize())
            if bwt_size != source_index.total_bits:
                raise MultiSourceQueryError(
                    "BWT has %d rows but provenance root has %d rows"
                    % (bwt_size, source_index.total_bits)
                )

    @classmethod
    def load(
        cls,
        merged_bwt_dir,
        rank_stride_bytes=64,
        mmap=True,
        use_saved_rank=True,
        logger=None,
    ):
        """Load a real Holt/McMillan MSBWT plus Feature-2 provenance."""
        from MUSCython import MultiStringBWTCython as MultiStringBWT

        bwt = MultiStringBWT.loadBWT(
            str(merged_bwt_dir),
            useMemmap=mmap,
            logger=logger,
        )
        source_index = MultiSourceQueryIndex(
            merged_bwt_dir,
            rank_stride_bytes=rank_stride_bytes,
            mmap=mmap,
            use_saved_rank=use_saved_rank,
        )
        return cls(bwt, source_index)

    def findIndicesOfStr(self, seq, givenRange=None):
        seq = _normalize_sequence(seq)
        if givenRange is None:
            return self.bwt.findIndicesOfStr(seq)
        return self.bwt.findIndicesOfStr(seq, givenRange)

    def findIndicesForSource(self, seq, source, givenRange=None):
        """Return the constituent-local FM interval for ``seq``."""
        merged_interval = self.findIndicesOfStr(seq, givenRange=givenRange)
        return self.source_index.project_interval(
            source,
            merged_interval[0],
            merged_interval[1],
        )

    def countOccurrencesForSource(self, seq, source, givenRange=None):
        """Count ``seq`` in one constituent using one merged FM search."""
        low, high = self.findIndicesForSource(
            seq,
            source,
            givenRange=givenRange,
        )
        return int(high - low)

    def nonzeroSources(
        self,
        seq,
        givenRange=None,
        include_intervals=False,
        include_stats=False,
    ):
        """Search once and return only sources containing ``seq``.

        Each returned source has its exact occurrence count.  Empty
        provenance branches are pruned during descent, so this does not
        materialize an F-length vector of zero counts.
        """
        seq = _normalize_sequence(seq)
        merged_low, merged_high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )

        if include_stats:
            sources, stats = self.source_index.nonzero_sources_interval(
                merged_low,
                merged_high,
                include_intervals=include_intervals,
                include_stats=True,
            )
            stats.update(
                {
                    "merged_interval": (int(merged_low), int(merged_high)),
                    "merged_count": int(merged_high - merged_low),
                    "sources_reported": len(sources),
                }
            )
            return {
                "sequence": seq,
                "merged_interval": (int(merged_low), int(merged_high)),
                "merged_count": int(merged_high - merged_low),
                "sources": sources,
                "stats": stats,
            }

        sources = self.source_index.nonzero_sources_interval(
            merged_low,
            merged_high,
            include_intervals=include_intervals,
            include_stats=False,
        )
        return sources

    # More explicit synonym for callers who prefer the roadmap terminology.
    listSourcesWithOccurrences = nonzeroSources

    def sourceFrequency(
        self,
        seq,
        givenRange=None,
        include_stats=False,
    ):
        """Return number of constituent sources containing ``seq`` exactly.

        Feature 5: a dedicated count-only provenance traversal (no sparse
        source-dictionary materialization).  One merged FM search.
        """
        seq = _normalize_sequence(seq)
        merged_low, merged_high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )

        if include_stats:
            frequency, stats = self.source_index.source_frequency_interval(
                merged_low,
                merged_high,
                include_stats=True,
            )
            stats.update(
                {
                    "merged_interval": (int(merged_low), int(merged_high)),
                    "merged_count": int(merged_high - merged_low),
                    "source_frequency": int(frequency),
                }
            )
            return {
                "sequence": seq,
                "merged_interval": (int(merged_low), int(merged_high)),
                "merged_count": int(merged_high - merged_low),
                "source_frequency": int(frequency),
                "source_count": int(self.source_index.source_count),
                "stats": stats,
            }

        return int(
            self.source_index.source_frequency_interval(
                merged_low,
                merged_high,
                include_stats=False,
            )
        )

    # Synonym for callers who prefer the roadmap terminology.
    countSourcesWithOccurrences = sourceFrequency

    def topSources(
        self,
        seq,
        k=10,
        givenRange=None,
        include_intervals=False,
        include_stats=False,
    ):
        """Return the exact top-k constituent sources by occurrence count.

        Feature 6: one merged FM search, Feature-4 sparse candidates,
        bounded top-k selection (heapq.nlargest when k < support size).
        Ties are broken by provenance/input source order.
        """
        seq = _normalize_sequence(seq)
        merged_low, merged_high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )

        if include_stats:
            sources, stats = self.source_index.top_sources_interval(
                merged_low,
                merged_high,
                k,
                include_intervals=include_intervals,
                include_stats=True,
            )
            stats.update(
                {
                    "merged_interval": (int(merged_low), int(merged_high)),
                    "merged_count": int(merged_high - merged_low),
                }
            )
            return {
                "sequence": seq,
                "merged_interval": (int(merged_low), int(merged_high)),
                "merged_count": int(merged_high - merged_low),
                "k": int(k),
                "sources": sources,
                "stats": stats,
            }

        return self.source_index.top_sources_interval(
            merged_low,
            merged_high,
            k,
            include_intervals=include_intervals,
            include_stats=False,
        )

    # Synonym for callers who prefer the roadmap terminology.
    topSourcesByAbundance = topSources

    def querySource(self, seq, source, givenRange=None, include_trace=False):
        """Return a rich constituent-specific exact-query result."""
        seq = _normalize_sequence(seq)
        source_id = self.source_index.resolve_source(source)
        source_record = self.source_index.source_record(source_id)

        merged_low, merged_high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )

        if include_trace:
            source_interval, trace = self.source_index.project_interval(
                source_id,
                merged_low,
                merged_high,
                trace=True,
            )
        else:
            source_interval = self.source_index.project_interval(
                source_id,
                merged_low,
                merged_high,
            )
            trace = None

        source_low, source_high = source_interval
        source_count = int(source_high - source_low)
        merged_count = int(merged_high - merged_low)

        result = {
            "sequence": seq,
            "source_id": source_id,
            "source_name": str(source_record.get("name", source_id)),
            "source_interval": (int(source_low), int(source_high)),
            "count": source_count,
            "present": bool(source_count),
            "merged_interval": (int(merged_low), int(merged_high)),
            "merged_count": merged_count,
            "fraction_of_merged_occurrences": (
                float(source_count) / merged_count if merged_count else 0.0
            ),
            "path_depth": len(self.source_index.source_path(source_id)),
        }
        if include_trace:
            result["projection_trace"] = trace
        return result


# PEP-8 aliases for new code; camelCase methods intentionally match the
# repository's existing API style.
MultiSourceQuery = MultiSourceBWT
