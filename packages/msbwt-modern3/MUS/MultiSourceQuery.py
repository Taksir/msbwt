"""Constituent-specific queries over a provenance-preserving multi-merged
MSBWT (Features 3-9, enhanced-modern2).

This is the additive query layer over the verified Feature-2 provenance tree
(``MUS.MultiSourceProvenance``) and the verified Feature-1 rank primitive
(``MUS.SourceIndex.TwoSourceInterleaveIndex``).  It adapts the
Point-3/4/5/6/7/8A candidates (``research/feature-candidates/3/``, ``4/``,
``5 and 6/``, ``7/``, ``8a/``) into the msbwt-modern2 production tree
with hardened rank-cache identity, the strict sequence-normalization
contract of ``MUS.SourceIndex``, and the source metadata selection
machinery.

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

Feature 7 adds subset/group/predicate selection: mutable biological labels
live in ``MUS.SourceMetadata`` (``source_metadata.json`` or an external
file), never in the BWT or ``provenance.json``; ``countSubset`` /
``querySubset`` / ``countGroup`` / ``queryGroup`` / ``countWhere`` /
``queryWhere`` resolve a selection to stable source IDs and descend the
provenance tree once with two pruning modes (skip branches containing no
selected source; complete-subtree shortcut when every leaf below a node is
selected).

Feature 8A adds source-aware one-symbol sequence extension WITHOUT a
reverse FM-index: ``extend`` / ``extendLeft`` / ``extendRight`` with the
default biological alphabet ``ACGNT``.  Left extension reuses the parent
interval via ``givenRange`` (1 full search + |alphabet| incremental FM
steps); right extension performs one ordinary exact search per candidate
(``P + base``) and honestly reports the asymmetry.  ``$`` is excluded from
left extension (end-marker/backward-step semantics are cyclic) but allowed
for right extension with an explicit alphabet.  Any source / subset /
group / where selection (Features 3 and 7) applies to every candidate
interval.

Feature 9 adds read-level provenance: ``locate_row_source`` maps any merged
BWT row to ``(source_id, source_local_row)`` through the provenance tree
(the row-level analogue of interval projection), and ``MultiSourceBWT``
gains ``readProvenance`` / ``rowReadProvenance`` / ``readMate`` /
``readsContaining`` over the verified ``MUS.ReadProvenance`` layer
(Feature 9).  ``readsContaining`` returns unique reads (duplicate
identities preserved) with exact per-read occurrence counts, optionally
restricted to one source / subset / metadata group / predicate, with
provenance-tree row prefiltering before LF walks for selected-source
queries.

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
"""

import hashlib
import heapq
import os
import sys
import zipfile

import numpy as np

from MUS.MultiSourceProvenance import (
    ProvenanceError,
    load_manifest,
)
from MUS.SourceIndex import TwoSourceInterleaveIndex, _POPCOUNT
from MUS.SourceMetadata import (
    METADATA_FILENAME,
    SourceMetadataCatalog,
    SourceMetadataError,
)
from MUS.BWTTags import (
    BWTTagError,
    BWTTagStore,
    tags_exist,
)
from MUS.QualitySidecar import (
    QualitySidecar,
    QualitySidecarError,
    QUALITY_TAG_NAME,
    quality_sidecar_exists,
)
from MUS.LCP import (
    LCPError,
    LCPIndex,
    lcp_exists,
)


RANK_DIRNAME = "ranks"
RANK_FILE_SUFFIX = ".npz"

# Feature 8A extension alphabet: default biological alphabet; '$' is valid
# for right extension only (left extension by the end-marker is rejected
# because MSBWT end-marker/backward-step behavior has cyclic/read-boundary
# semantics, not ordinary linear left context).
DEFAULT_EXTENSION_ALPHABET = b"ACGNT"
VALID_EXTENSION_SYMBOLS = frozenset(ord(symbol) for symbol in "$ACGNT")

# zipfile.BadZipFile (Python 3) / zipfile.BadZipfile (Python 2.7)
_ZIP_BAD = getattr(zipfile, "BadZipFile", None) or getattr(
    zipfile, "BadZipfile", None
)


class MultiSourceQueryError(ValueError):
    """Raised when a constituent query cannot be resolved safely."""


def _byte_symbol(value):
    """One-byte string for a byte value."""
    if isinstance(value, int):
        return bytes([value])
    return value


def _normalize_extension_alphabet(alphabet, direction):
    """Validate/normalize an extension alphabet (dedup, symbol check)."""
    if alphabet is None:
        alphabet = DEFAULT_EXTENSION_ALPHABET
    if isinstance(alphabet, str):
        alphabet = alphabet.encode("ascii")
    elif isinstance(alphabet, bytearray):
        alphabet = bytes(alphabet)
    elif not isinstance(alphabet, bytes):
        alphabet = bytes(alphabet)

    seen = set()
    normalized = []
    for raw in alphabet:
        # Python 3 iterates bytes as ints.
        value = raw if isinstance(raw, int) else ord(raw)
        if value not in VALID_EXTENSION_SYMBOLS:
            raise ValueError(
                "extension alphabet contains unsupported symbol byte %r"
                % value
            )
        if direction == "left" and value == ord("$"):
            raise ValueError(
                "left extension by '$' is intentionally disabled because "
                "the MSBWT end-marker has cyclic/boundary semantics; use "
                "DNA symbols A/C/G/N/T for linear left context"
            )
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    if not normalized:
        raise ValueError("extension alphabet cannot be empty")
    return bytes(normalized)


def _normalize_sequence(seq):
    """Explicit normalization (contract of SourceIndex).

    ``bytes`` is returned unchanged; ``str`` is encoded as ASCII (non-ASCII
    raises ``UnicodeEncodeError``); anything else raises ``TypeError``.
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

        # subtree source sets (Feature 7): frozenset of constituent IDs
        # below every node, keyed by node identity
        self._subtree_sources = {}
        self._index_subtree_sources(self.manifest["root"])

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

    def _node_cache_key(self, node):
        if node["type"] == "leaf":
            return ("leaf", str(node["source_id"]))
        return ("merge", str(node["node_id"]))

    def _index_subtree_sources(self, node):
        """Return/cache the frozenset of constituent IDs below ``node``."""
        node_type = node["type"]
        key = self._node_cache_key(node)

        if node_type == "leaf":
            result = frozenset([str(node["source_id"])])
        elif node_type == "merge":
            result = (
                self._index_subtree_sources(node["left"])
                | self._index_subtree_sources(node["right"])
            )
        else:
            raise ProvenanceError(
                "unknown provenance node type: %r" % node_type
            )

        self._subtree_sources[key] = result
        return result

    def subtree_sources(self, node):
        return self._subtree_sources[self._node_cache_key(node)]

    def resolve_source_ids(self, sources):
        """Resolve/deduplicate arbitrary source IDs/names in provenance
        order."""
        seen = set()
        resolved = []
        for source in sources:
            sid = self.resolve_source(source)
            if sid not in seen:
                resolved.append(sid)
                seen.add(sid)
        resolved.sort(key=self._source_order.__getitem__)
        return resolved

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

    def locate_row_source(self, row_index, trace=False):
        """Map one merged BWT row to ``(source_id, source_local_row)``.

        This is the row-level analogue of interval projection (Feature 3).
        At each merge node the interleave bit selects the child; the rank of
        that bit gives the child's local row index.  Returns
        ``(source_id, source_local_row)``, or with ``trace=True`` the same
        pair plus the per-node step records.
        """
        row_index = int(row_index)
        if row_index < 0 or row_index >= self.total_bits:
            raise IndexError(
                "row index %d outside [0,%d)"
                % (row_index, self.total_bits)
            )

        node = self.manifest["root"]
        local_index = row_index
        steps = []

        while node["type"] != "leaf":
            node_id = str(node["node_id"])
            rank_index = self._get_rank_index(node_id)
            branch = int(rank_index.source_at(local_index))

            if branch == 0:
                child_index = int(rank_index.rank0(local_index))
                child = node["left"]
            else:
                child_index = int(rank_index.rank1(local_index))
                child = node["right"]

            if trace:
                steps.append(
                    {
                        "node_id": node_id,
                        "branch": branch,
                        "parent_row": int(local_index),
                        "child_row": int(child_index),
                    }
                )

            local_index = child_index
            node = child

        result = (
            str(node["source_id"]),
            int(local_index),
        )
        if trace:
            return result[0], result[1], steps
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

    def subset_count_interval(
        self,
        start,
        end,
        sources,
        include_stats=False,
    ):
        """Return the exact aggregate count for an arbitrary source subset.

        The traversal has two pruning modes (Feature 7):

        * a provenance branch containing no selected source is skipped;
        * if *all* leaves below a node are selected, ``r-l`` is returned
          directly without descending farther (complete-subtree shortcut).

        The second rule lets metadata groups aligned with provenance
        subtrees aggregate in fewer rank operations than summing Point-3
        queries.
        """
        start, end = self._check_interval(start, end)
        selected = frozenset(self.resolve_source_ids(sources))

        stats = {
            "root_interval_size": int(end - start),
            "selected_sources": len(selected),
            "internal_nodes_visited": 0,
            "branches_pruned_empty_interval": 0,
            "branches_pruned_unselected": 0,
            "subtree_shortcuts": 0,
            "rank_nodes_loaded_before": self.loaded_rank_node_count,
        }

        if not selected or start == end:
            stats["rank_nodes_loaded_after"] = self.loaded_rank_node_count
            stats["rank_nodes_loaded_for_query"] = 0
            if include_stats:
                return 0, stats
            return 0

        def descend(node, l, r):
            if l == r:
                stats["branches_pruned_empty_interval"] += 1
                return 0

            node_sources = self.subtree_sources(node)
            overlap = node_sources & selected
            if not overlap:
                stats["branches_pruned_unselected"] += 1
                return 0

            # Every source under this node is selected, so the node's
            # interval is already the exact aggregate count for that whole
            # subtree.
            if node_sources <= selected:
                stats["subtree_shortcuts"] += 1
                return int(r - l)

            if node["type"] == "leaf":
                return int(r - l)

            stats["internal_nodes_visited"] += 1
            rank_index = self._get_rank_index(str(node["node_id"]))

            left_l = rank_index.rank0(l)
            left_r = rank_index.rank0(r)
            right_l = rank_index.rank1(l)
            right_r = rank_index.rank1(r)

            return (
                descend(node["left"], left_l, left_r)
                + descend(node["right"], right_l, right_r)
            )

        count = int(descend(self.manifest["root"], start, end))

        stats["rank_nodes_loaded_after"] = self.loaded_rank_node_count
        stats["rank_nodes_loaded_for_query"] = (
            stats["rank_nodes_loaded_after"]
            - stats["rank_nodes_loaded_before"]
        )

        if include_stats:
            return count, stats
        return count

    def subset_counts_interval(
        self,
        start,
        end,
        sources,
        include_intervals=False,
        include_stats=False,
    ):
        """Return exact nonzero per-source counts inside a requested
        subset."""
        start, end = self._check_interval(start, end)
        selected_ids = self.resolve_source_ids(sources)
        selected = frozenset(selected_ids)

        stats = {
            "root_interval_size": int(end - start),
            "selected_sources": len(selected),
            "internal_nodes_visited": 0,
            "branches_pruned_empty_interval": 0,
            "branches_pruned_unselected": 0,
            "leaves_reported": 0,
            "rank_nodes_loaded_before": self.loaded_rank_node_count,
        }
        results = []

        if not selected or start == end:
            stats["rank_nodes_loaded_after"] = self.loaded_rank_node_count
            stats["rank_nodes_loaded_for_query"] = 0
            if include_stats:
                return results, stats
            return results

        def descend(node, l, r):
            if l == r:
                stats["branches_pruned_empty_interval"] += 1
                return

            node_sources = self.subtree_sources(node)
            if not (node_sources & selected):
                stats["branches_pruned_unselected"] += 1
                return

            if node["type"] == "leaf":
                sid = str(node["source_id"])
                if sid not in selected:
                    stats["branches_pruned_unselected"] += 1
                    return
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

            stats["internal_nodes_visited"] += 1
            rank_index = self._get_rank_index(str(node["node_id"]))

            left_l = rank_index.rank0(l)
            left_r = rank_index.rank0(r)
            right_l = rank_index.rank1(l)
            right_r = rank_index.rank1(r)

            descend(node["left"], left_l, left_r)
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


class MultiSourceBWT(object):
    """Wrap a Feature-2 merged MSBWT with constituent-specific query
    methods."""

    def __init__(self, bwt, source_index, source_metadata=None,
                 read_provenance=None, bwt_tags=None, quality_sidecar=None,
                 lcp_index=None):
        self.bwt = bwt
        self.source_index = source_index
        self.read_provenance = read_provenance
        self.bwt_tags = bwt_tags
        self.quality_sidecar = quality_sidecar
        self.lcp_index = lcp_index
        if source_metadata is None:
            source_metadata = SourceMetadataCatalog(
                source_index.list_sources()
            )
        self.source_metadata = source_metadata
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
        source_metadata_path=None,
    ):
        """Load a real Holt/McMillan MSBWT plus Feature-2 provenance.

        ``source_metadata.json`` inside the merged directory is loaded
        automatically (if present); an external metadata file can be
        supplied explicitly via ``source_metadata_path``.

        Feature-9 ``read_provenance.npy`` / ``read_provenance.json`` are
        loaded automatically when present.
        """
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
        if source_metadata_path is None:
            source_metadata = SourceMetadataCatalog.load(
                merged_bwt_dir,
                source_index.list_sources(),
                required=False,
            )
        else:
            source_metadata = SourceMetadataCatalog.from_file(
                source_metadata_path,
                source_index.list_sources(),
            )

        read_provenance = None
        from MUS.ReadProvenance import ReadProvenanceIndex
        from MUS.ReadProvenance import read_provenance_exists

        if read_provenance_exists(merged_bwt_dir):
            read_provenance = ReadProvenanceIndex(
                merged_bwt_dir,
                mmap=mmap,
                validate=True,
                source_index=source_index,
            )

        bwt_tags = None
        if tags_exist(merged_bwt_dir):
            bwt_tags = BWTTagStore(
                merged_bwt_dir,
                mmap=mmap,
                validate=True,
            )

        quality_sidecar = None
        if quality_sidecar_exists(merged_bwt_dir):
            quality_sidecar = QualitySidecar(
                merged_bwt_dir,
                mmap=mmap,
                validate=True,
            )

        lcp_index = None
        if lcp_exists(merged_bwt_dir):
            lcp_index = LCPIndex(
                merged_bwt_dir,
                mmap=mmap,
                validate=True,
            )

        return cls(
            bwt,
            source_index,
            source_metadata=source_metadata,
            read_provenance=read_provenance,
            bwt_tags=bwt_tags,
            quality_sidecar=quality_sidecar,
            lcp_index=lcp_index,
        )

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

    def _resolve_subset_selection(
        self,
        sources=None,
        group=None,
        where=None,
    ):
        if sources is not None:
            # Accept source names as well as IDs for the direct subset API.
            resolved = self.source_index.resolve_source_ids(sources)
            return resolved

        return self.source_metadata.resolve_selection(
            group=group,
            where=where,
        )

    def countSubset(
        self,
        seq,
        sources=None,
        group=None,
        where=None,
        givenRange=None,
        include_stats=False,
    ):
        """Count exact occurrences across an arbitrary source subset/group."""
        selected = self._resolve_subset_selection(
            sources=sources,
            group=group,
            where=where,
        )
        seq = _normalize_sequence(seq)
        merged_low, merged_high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )

        if include_stats:
            count, stats = self.source_index.subset_count_interval(
                merged_low,
                merged_high,
                selected,
                include_stats=True,
            )
            stats.update(
                {
                    "merged_interval": (int(merged_low), int(merged_high)),
                    "merged_count": int(merged_high - merged_low),
                    "selected_source_ids": list(selected),
                    "selected_source_count": len(selected),
                    "count": int(count),
                }
            )
            return {
                "sequence": seq,
                "merged_interval": (int(merged_low), int(merged_high)),
                "merged_count": int(merged_high - merged_low),
                "selected_source_ids": list(selected),
                "selected_source_count": len(selected),
                "count": int(count),
                "stats": stats,
            }

        return int(
            self.source_index.subset_count_interval(
                merged_low,
                merged_high,
                selected,
                include_stats=False,
            )
        )

    def querySubset(
        self,
        seq,
        sources=None,
        group=None,
        where=None,
        givenRange=None,
        include_intervals=False,
        include_stats=False,
    ):
        """Return aggregate and exact nonzero constituent counts for a
        subset."""
        selected = self._resolve_subset_selection(
            sources=sources,
            group=group,
            where=where,
        )
        seq = _normalize_sequence(seq)
        merged_low, merged_high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )

        if include_stats:
            records, stats = self.source_index.subset_counts_interval(
                merged_low,
                merged_high,
                selected,
                include_intervals=include_intervals,
                include_stats=True,
            )
        else:
            records = self.source_index.subset_counts_interval(
                merged_low,
                merged_high,
                selected,
                include_intervals=include_intervals,
                include_stats=False,
            )
            stats = None

        result = {
            "sequence": seq,
            "merged_interval": (int(merged_low), int(merged_high)),
            "merged_count": int(merged_high - merged_low),
            "selected_source_ids": list(selected),
            "selected_source_count": len(selected),
            "count": int(sum(record["count"] for record in records)),
            "sources": records,
        }
        if include_stats:
            result["stats"] = stats
        return result

    def countGroup(
        self,
        seq,
        group,
        givenRange=None,
        include_stats=False,
    ):
        return self.countSubset(
            seq,
            group=group,
            givenRange=givenRange,
            include_stats=include_stats,
        )

    def queryGroup(
        self,
        seq,
        group,
        givenRange=None,
        include_intervals=False,
        include_stats=False,
    ):
        return self.querySubset(
            seq,
            group=group,
            givenRange=givenRange,
            include_intervals=include_intervals,
            include_stats=include_stats,
        )

    def countWhere(
        self,
        seq,
        where,
        givenRange=None,
        include_stats=False,
    ):
        return self.countSubset(
            seq,
            where=where,
            givenRange=givenRange,
            include_stats=include_stats,
        )

    def queryWhere(
        self,
        seq,
        where,
        givenRange=None,
        include_intervals=False,
        include_stats=False,
    ):
        return self.querySubset(
            seq,
            where=where,
            givenRange=givenRange,
            include_intervals=include_intervals,
            include_stats=include_stats,
        )

    def _extension_selection(self, source=None, sources=None, group=None,
                             where=None):
        """Resolve exactly one extension selection mode."""
        modes = (
            int(source is not None)
            + int(sources is not None)
            + int(group is not None)
            + int(where is not None)
        )
        if modes > 1:
            raise ValueError(
                "use only one of source, sources, group, or where for an "
                "extension query"
            )
        if source is not None:
            return ("source", self.source_index.resolve_source(source))
        if sources is not None:
            return ("subset", self.source_index.resolve_source_ids(sources))
        if group is not None:
            return ("subset", self.source_metadata.group_sources(group))
        if where is not None:
            if not isinstance(where, dict):
                raise ValueError("where must be a mapping")
            return ("subset", self.source_metadata.select_where(**where))
        return ("merged", None)

    def _count_extension_interval(self, interval, selection):
        low, high = interval
        mode, payload = selection
        if mode == "merged":
            return int(high - low), None
        if mode == "source":
            source_interval = self.source_index.project_interval(
                payload,
                low,
                high,
            )
            return int(source_interval[1] - source_interval[0]), (
                source_interval)
        if mode == "subset":
            return int(
                self.source_index.subset_count_interval(
                    low,
                    high,
                    payload,
                    include_stats=False,
                )
            ), None
        raise AssertionError("unknown extension selection mode")

    def extend(
        self,
        seq,
        direction="left",
        alphabet=None,
        source=None,
        sources=None,
        group=None,
        where=None,
        include_zero=True,
        include_intervals=False,
        include_stats=False,
    ):
        """Return exact one-symbol extensions using the existing one-way
        MSBWT.

        ``direction='left'`` uses one full FM search for ``seq`` followed
        by incremental backward-search steps (``givenRange``) from the
        returned interval: cost = 1 full search + |alphabet| FM steps.

        ``direction='right'`` does not require a reverse FM-index: each
        candidate ``seq + base`` is searched independently with the
        ordinary forward MSBWT: cost = |alphabet| full searches.  Exact,
        but honestly asymmetric.

        Selection modes: ``source`` (one constituent), ``sources`` /
        ``group`` / ``where`` (subset aggregation, Feature 7), or merged
        (whole index).  Exactly one selector is allowed.
        """
        seq = _normalize_sequence(seq)
        if not isinstance(seq, bytes) or len(seq) == 0:
            raise ValueError(
                "extension queries require a non-empty byte/string pattern")

        direction = str(direction).lower()
        if direction not in ("left", "right"):
            raise ValueError("direction must be 'left' or 'right'")

        alphabet = _normalize_extension_alphabet(alphabet, direction)
        selection = self._extension_selection(
            source=source,
            sources=sources,
            group=group,
            where=where,
        )

        full_searches = 0
        incremental_extension_calls = 0
        extensions = []
        parent_interval = None

        if direction == "left":
            parent_interval = self.findIndicesOfStr(seq)
            full_searches = 1
            candidate_intervals = []
            for base_value in alphabet:
                base = _byte_symbol(base_value)
                interval = self.findIndicesOfStr(
                    base, givenRange=parent_interval)
                incremental_extension_calls += 1
                candidate_intervals.append((base, interval))
        else:
            candidate_intervals = []
            for base_value in alphabet:
                base = _byte_symbol(base_value)
                interval = self.findIndicesOfStr(seq + base)
                full_searches += 1
                candidate_intervals.append((base, interval))

        for base, interval in candidate_intervals:
            count, source_interval = self._count_extension_interval(
                interval,
                selection,
            )
            if not include_zero and count == 0:
                continue

            extended = base + seq if direction == "left" else seq + base
            record = {
                "base": base,
                "sequence": extended,
                "count": int(count),
            }
            if include_intervals:
                record["merged_interval"] = (
                    int(interval[0]), int(interval[1]))
                record["merged_count"] = int(interval[1] - interval[0])
                if source_interval is not None:
                    record["source_interval"] = (
                        int(source_interval[0]),
                        int(source_interval[1]),
                    )
            extensions.append(record)

        result = {
            "pattern": seq,
            "direction": direction,
            "alphabet": alphabet,
            "selection_mode": selection[0],
            "extensions": extensions,
        }
        if selection[0] == "source":
            result["source_id"] = selection[1]
        elif selection[0] == "subset":
            result["selected_source_ids"] = list(selection[1])

        if include_stats:
            result["stats"] = {
                "full_fm_searches": full_searches,
                "incremental_extension_calls": incremental_extension_calls,
                "candidate_extensions": len(alphabet),
                "extensions_returned": len(extensions),
                "parent_interval": (
                    (int(parent_interval[0]), int(parent_interval[1]))
                    if parent_interval is not None
                    else None
                ),
            }
        return result

    def extendLeft(self, seq, **kwargs):
        kwargs["direction"] = "left"
        return self.extend(seq, **kwargs)

    def extendRight(self, seq, **kwargs):
        kwargs["direction"] = "right"
        return self.extend(seq, **kwargs)

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

    def _require_read_provenance(self):
        if self.read_provenance is None:
            raise MultiSourceQueryError(
                "read-level provenance is not available for this MSBWT; "
                "initialize/retrofit Feature-9 read_provenance first"
            )
        return self.read_provenance

    def readProvenance(self, dollar_id):
        """Return stable source/origin metadata for one MSBWT dollar ID."""
        return self._require_read_provenance().record(dollar_id)

    def rowReadProvenance(self, row_index, include_offset=False):
        """Resolve one BWT row to its owning read and provenance record.

        Internally ``getSequenceDollarID`` (an LF walk) maps the row to its
        dollar ID, then the read-provenance record is returned.  With
        ``include_offset=True`` the LF offset (position of the row within
        its read) is also returned as ``lf_offset``.
        """
        provenance = self._require_read_provenance()

        if include_offset:
            dollar_id, offset = self.bwt.getSequenceDollarID(
                int(row_index),
                True,
            )
        else:
            dollar_id = self.bwt.getSequenceDollarID(int(row_index))
            offset = None

        record = provenance.record(int(dollar_id))
        record["row_index"] = int(row_index)
        if include_offset:
            record["lf_offset"] = int(offset)
        return record

    def readMate(self, dollar_id):
        """Return mate provenance record or ``None`` when unpaired."""
        return self._require_read_provenance().mate(dollar_id)

    def readsContaining(
        self,
        seq,
        source=None,
        sources=None,
        group=None,
        where=None,
        givenRange=None,
        include_sequence=False,
        include_quality=False,
        include_rows=False,
        max_occurrences=None,
    ):
        """Return unique reads containing ``seq`` with exact occurrence
        counts.

        This is the correctness-first Feature-9 baseline.  It enumerates the
        merged FM interval and calls ``getSequenceDollarID`` for matching
        rows.  For source/group/where filters it first resolves each
        candidate row through the provenance tree
        (``MultiSourceQueryIndex.locate_row_source``) and discards rows from
        unselected sources BEFORE the LF walk.

        Duplicate reads are preserved as distinct read identities (identical
        sequences never collapse).  The method is exact but output-sensitive
        in the number of merged occurrences; a future locate/select
        acceleration can replace the internals without changing this API.
        """
        read_index = self._require_read_provenance()
        seq = _normalize_sequence(seq)
        merged_low, merged_high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )

        modes = (
            int(source is not None)
            + int(sources is not None)
            + int(group is not None)
            + int(where is not None)
        )
        if modes > 1:
            raise ValueError(
                "use only one of source, sources, group, or where"
            )

        selected = None
        selection_mode = "merged"
        if source is not None:
            selected = frozenset(
                [self.source_index.resolve_source(source)]
            )
            selection_mode = "source"
        elif sources is not None:
            selected = frozenset(
                self.source_index.resolve_source_ids(sources)
            )
            selection_mode = "subset"
        elif group is not None:
            selected = frozenset(
                self.source_metadata.group_sources(group)
            )
            selection_mode = "group"
        elif where is not None:
            selected = frozenset(
                self.source_metadata.resolve_selection(where=where)
            )
            selection_mode = "where"

        if max_occurrences is not None:
            max_occurrences = int(max_occurrences)
            if max_occurrences < 0:
                raise ValueError("max_occurrences must be non-negative")

        found = {}
        scanned = 0
        lf_walks = 0
        source_prefilter_skips = 0

        for row_index in range(int(merged_low), int(merged_high)):
            if max_occurrences is not None and scanned >= max_occurrences:
                break
            scanned += 1

            row_source = None
            if selected is not None:
                row_source, _ = self.source_index.locate_row_source(
                    row_index
                )
                if row_source not in selected:
                    source_prefilter_skips += 1
                    continue

            dollar_id = int(self.bwt.getSequenceDollarID(row_index))
            lf_walks += 1
            record = read_index.record(dollar_id)

            if row_source is not None and record["source_id"] != row_source:
                raise MultiSourceQueryError(
                    "row provenance and read provenance disagree at row "
                    "%d: %s != %s"
                    % (
                        row_index,
                        row_source,
                        record["source_id"],
                    )
                )

            entry = found.get(dollar_id)
            if entry is None:
                entry = dict(record)
                entry["occurrence_count"] = 0
                if include_rows:
                    entry["rows"] = []
                found[dollar_id] = entry

            entry["occurrence_count"] += 1
            if include_rows:
                entry["rows"].append(int(row_index))

        reads = [
            found[dollar_id]
            for dollar_id in sorted(found)
        ]

        if include_sequence:
            for record in reads:
                recovered = self.bwt.recoverString(
                    int(record["dollar_id"])
                )
                record["sequence"] = recovered

        if include_quality:
            quality_sidecar = self._require_quality_sidecar()
            for record in reads:
                record["quality"] = quality_sidecar.recover_quality(
                    self.bwt,
                    int(record["dollar_id"]),
                )

        return {
            "sequence": seq,
            "merged_interval": (
                int(merged_low),
                int(merged_high),
            ),
            "merged_occurrences": int(merged_high - merged_low),
            "selection_mode": selection_mode,
            "selected_source_ids": (
                None if selected is None else sorted(
                    selected,
                    key=self.source_index._source_order.__getitem__,
                )
            ),
            "reads": reads,
            "unique_read_count": len(reads),
            "reported_occurrences": int(
                sum(r["occurrence_count"] for r in reads)
            ),
            "stats": {
                "interval_rows_scanned": int(scanned),
                "lf_walks": int(lf_walks),
                "source_prefilter_skips": int(source_prefilter_skips),
                "truncated": bool(
                    max_occurrences is not None
                    and scanned < int(merged_high - merged_low)
                ),
            },
        }

    def _require_bwt_tags(self):
        if self.bwt_tags is None:
            raise MultiSourceQueryError(
                "BWT-aligned tags are not available for this MSBWT"
            )
        return self.bwt_tags

    def listTags(self):
        """Return registered Feature-12 BWT-row tag names."""
        return self._require_bwt_tags().list_tags()

    def tagSchema(self, name):
        return self._require_bwt_tags().schema(name)

    def rowTag(self, row_index, name):
        """Return one tag value aligned to one merged BWT row."""
        row_index = int(row_index)
        if row_index < 0 or row_index >= self.source_index.total_bits:
            raise IndexError(
                "row index %d outside [0,%d)"
                % (row_index, self.source_index.total_bits)
            )
        return self._require_bwt_tags().array(name)[row_index]

    def tagInterval(self, name, start, end):
        """Return a direct view of a contiguous merged BWT interval."""
        return self._require_bwt_tags().interval(name, start, end)

    def _resolve_tag_selection(
        self,
        source=None,
        sources=None,
        group=None,
        where=None,
    ):
        modes = (
            int(source is not None)
            + int(sources is not None)
            + int(group is not None)
            + int(where is not None)
        )
        if modes > 1:
            raise ValueError(
                "use only one of source, sources, group, or where"
            )

        if source is not None:
            return (
                "source",
                frozenset(
                    [self.source_index.resolve_source(source)]
                ),
            )
        if sources is not None:
            return (
                "subset",
                frozenset(
                    self.source_index.resolve_source_ids(sources)
                ),
            )
        if group is not None:
            return (
                "group",
                frozenset(
                    self.source_metadata.group_sources(group)
                ),
            )
        if where is not None:
            return (
                "where",
                frozenset(
                    self.source_metadata.resolve_selection(where=where)
                ),
            )
        return "merged", None

    def tagValues(
        self,
        seq,
        name,
        source=None,
        sources=None,
        group=None,
        where=None,
        givenRange=None,
        include_rows=False,
        max_rows=None,
    ):
        """Return exact tag values on BWT rows matching ``seq``.

        Without a source/group selector, the FM interval is contiguous and
        this operation is a direct tag-array slice.  With a selector,
        candidate rows are source-filtered through the provenance tree and
        only retained row indices are gathered (Feature 12).
        """
        store = self._require_bwt_tags()
        if not store.has_tag(name):
            raise KeyError("unknown tag: %s" % name)

        seq = _normalize_sequence(seq)
        low, high = self.findIndicesOfStr(
            seq,
            givenRange=givenRange,
        )
        low = int(low)
        high = int(high)

        selection_mode, selected = self._resolve_tag_selection(
            source=source,
            sources=sources,
            group=group,
            where=where,
        )

        if max_rows is not None:
            max_rows = int(max_rows)
            if max_rows < 0:
                raise ValueError("max_rows must be non-negative")

        arr = store.array(name)

        if selected is None:
            end = high
            truncated = False
            if max_rows is not None and end - low > max_rows:
                end = low + max_rows
                truncated = True
            values = arr[low:end]
            rows = (
                np.arange(low, end, dtype=np.int64)
                if include_rows
                else None
            )
            scanned = int(end - low)
        else:
            row_list = []
            scanned = 0
            truncated = False
            for row in range(low, high):
                scanned += 1
                sid, _ = self.source_index.locate_row_source(row)
                if sid not in selected:
                    continue
                if (
                    max_rows is not None
                    and len(row_list) >= max_rows
                ):
                    truncated = True
                    break
                row_list.append(row)

            rows_array = np.asarray(row_list, dtype=np.int64)
            values = arr[rows_array]
            rows = rows_array if include_rows else None

        result = {
            "sequence": seq,
            "tag": str(name),
            "schema": store.schema(name),
            "merged_interval": (low, high),
            "merged_occurrences": int(high - low),
            "selection_mode": selection_mode,
            "selected_source_ids": (
                None
                if selected is None
                else sorted(
                    selected,
                    key=self.source_index._source_order.__getitem__,
                )
            ),
            "value_count": int(values.shape[0]),
            "values": values,
            "stats": {
                "candidate_rows_scanned": int(scanned),
                "truncated": bool(truncated),
            },
        }
        if include_rows:
            result["rows"] = rows
        return result

    def tagValueCounts(
        self,
        seq,
        name,
        source=None,
        sources=None,
        group=None,
        where=None,
        givenRange=None,
    ):
        """Count exact values of a scalar tag over matching/selected rows."""
        result = self.tagValues(
            seq,
            name,
            source=source,
            sources=sources,
            group=group,
            where=where,
            givenRange=givenRange,
            include_rows=False,
        )
        values = result["values"]
        if values.ndim != 1:
            raise BWTTagError(
                "tagValueCounts requires scalar tag %s; got tail shape %r"
                % (name, values.shape[1:])
            )
        unique, counts = np.unique(values, return_counts=True)
        result = dict(result)
        result.pop("values")
        result["counts"] = [
            {
                "value": value.item()
                if isinstance(value, np.generic)
                else value,
                "count": int(count),
            }
            for value, count in zip(unique, counts)
        ]
        return result

    def _require_quality_sidecar(self):
        if self.quality_sidecar is None:
            raise MultiSourceQueryError(
                "exact FASTQ quality sidecar is not available for this "
                "MSBWT"
            )
        return self.quality_sidecar

    def hasQuality(self):
        """True when the exact FASTQ quality sidecar is loaded."""
        return self.quality_sidecar is not None

    def qualityForRow(self, row_index):
        """Return the exact FASTQ quality byte for one suffix-start row."""
        return self._require_quality_sidecar().quality_for_row(
            row_index
        )

    def readQuality(self, dollar_id):
        """Recover one read's exact original FASTQ quality line."""
        return self._require_quality_sidecar().recover_quality(
            self.bwt,
            int(dollar_id),
        )

    def readSequenceAndQuality(self, dollar_id):
        """Recover exact biological sequence and FASTQ quality bytes."""
        return (
            self._require_quality_sidecar()
            .recover_sequence_and_quality(
                self.bwt,
                int(dollar_id),
            )
        )

    def readFastqData(self, dollar_id):
        """Return sequence, quality and Feature-9 provenance when available."""
        sidecar = self._require_quality_sidecar()
        return sidecar.record(
            self.bwt,
            int(dollar_id),
            read_provenance=self.read_provenance,
        )

    def qualityValues(
        self,
        seq,
        source=None,
        sources=None,
        group=None,
        where=None,
        givenRange=None,
        include_rows=False,
        max_rows=None,
    ):
        """Return quality of the first base of each matching suffix
        occurrence.

        Because Q1 quality is suffix-start aligned, a normal FM interval
        for pattern ``P`` directly indexes the quality byte of ``P``'s
        first base.  The Feature-3/7 selectors apply through the Feature-12
        tag-query machinery.
        """
        self._require_quality_sidecar()
        return self.tagValues(
            seq,
            QUALITY_TAG_NAME,
            source=source,
            sources=sources,
            group=group,
            where=where,
            givenRange=givenRange,
            include_rows=include_rows,
            max_rows=max_rows,
        )

    def _require_lcp_index(self):
        if self.lcp_index is None:
            raise MultiSourceQueryError(
                "LCP layer is not available for this MSBWT"
            )
        return self.lcp_index

    def hasLCP(self):
        """True when the Feature-11A LCP layer is loaded."""
        return self.lcp_index is not None

    def lcpAt(self, row):
        """Canonical boundary LCP[row]; ``LCP[0] == 0`` always."""
        return self._require_lcp_index().boundary(row)

    def lcpAdjacent(self, left_row):
        """``LCP(SA[left_row], SA[left_row + 1])`` (stored convention)."""
        return self._require_lcp_index().adjacent(left_row)

    def lcpBetweenRows(self, left_row, right_row):
        """Exact LCP between arbitrary suffix rows via the RMQ identity.

        ``LCP(SA[i], SA[j]) = min(lcps[i:j])`` for ``i < j``; the baseline
        performs a direct minimum scan (an RMQ accelerator may replace it
        later without changing semantics).
        """
        return self._require_lcp_index().between_rows(
            left_row, right_row)


# PEP-8 aliases for new code; camelCase methods intentionally match the
# repository's existing API style.
MultiSourceQuery = MultiSourceBWT
