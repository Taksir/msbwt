"""Remove/unmerge constituent sources from a merged MSBWT without FASTQ
rebuild (Feature 10, enhanced-modern2).

The operation does NOT rebuild from FASTQ and does NOT reconstruct
standalone constituent BWTs.  It exploits the central invariant
established by Features 1-3:

    a merged BWT is a stable interleaving of its constituent BWT rows.

Deleting every row belonging to the removed source(s) therefore leaves the
BWT row stream for the retained collection in its existing relative suffix
order, which is exactly the BWT of the retained collection.

The provenance tree is pruned simultaneously:

* subtrees containing only retained sources are reused (original
  interleave files copied unchanged);
* subtrees containing only removed sources disappear;
* one-child internal nodes collapse;
* partially retained two-child nodes receive a filtered interleave
  (only those nodes get new node IDs/interleaves).

Feature-9 read provenance is filtered by the corresponding dollar-row mask
and mate dollar IDs are translated into the new read-ID space.  Feature-7
source metadata is pruned to retained sources (groups intersected with the
retained collection).

Persistence classification

- Output ``msbwt.npy``, ``provenance.json``,
  ``provenance/interleaves/*``, ``inter0.npy`` (when the reduced root is a
  merge node), ``read_provenance.npy`` + ``read_provenance.json`` (when
  the input carries them) -- AUTHORITATIVE, exactly as for Features 2/9.
- ``source_metadata.json`` -- MUTABLE / REBUILDABLE (Feature 7), pruned to
  retained sources.
- ``provenance/ranks/*`` -- DERIVED / REBUILDABLE; never copied from the
  input (old rank caches can never survive incorrectly); rebuilt lazily by
  Feature-3 queries, or eagerly when ``build_rank_indexes=True``.

Atomic output behavior

The reduced package is built inside a temporary sibling directory and only
published (rename) after the BWT write, provenance write, manifest
validation, read-provenance filtering, metadata filtering, and optional
rank construction all succeed.  A failed removal never leaves an output
directory that passes validation while incomplete.  The input package is
never modified.

Rejected requests: input == output, remove every source, retain zero
sources, empty remove selection, retain-all no-op, existing output without
explicit ``overwrite=True``.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""

from __future__ import absolute_import

import json
import os
import shutil
import sys
import tempfile
import uuid

import numpy as np
from numpy.lib.format import open_memmap

from MUS.MultiSourceProvenance import (
    BWT_FILENAME,
    FORMAT_NAME,
    FORMAT_VERSION,
    INTERLEAVE_FILENAME,
    INTERLEAVE_DIRNAME,
    MANIFEST_FILENAME,
    PROVENANCE_DIRNAME,
    ProvenanceError,
    _array_sha256,
    _pack_little_endian_bits,
    load_manifest,
    save_manifest,
    unpack_interleave,
    validate_manifest,
)
from MUS.MultiSourceQuery import (
    MultiSourceQueryIndex,
    RANK_DIRNAME,
)
from MUS.ReadProvenance import (
    filter_read_provenance,
    read_provenance_exists,
)
from MUS.BWTTags import (
    filter_tag_arrays,
    tags_exist,
)
from MUS.QualitySidecar import (
    filter_quality_sidecar_metadata,
    quality_sidecar_exists,
)
from MUS.SourceMetadata import (
    METADATA_FILENAME,
    SourceMetadataCatalog,
)


class SourceRemovalError(ValueError):
    """Raised when a Feature-10 source-removal request is invalid."""


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


def _atomic_publish(temp_dir, output_dir):
    """Atomically publish the validated temporary package."""
    if hasattr(os, "replace"):
        os.replace(temp_dir, output_dir)
    else:
        os.rename(temp_dir, output_dir)


def _node_sources(node):
    if node["type"] == "leaf":
        return frozenset([str(node["source_id"])])
    return _node_sources(node["left"]) | _node_sources(node["right"])


def _deep_copy_node(node):
    if node["type"] == "leaf":
        return {
            "type": "leaf",
            "source_id": str(node["source_id"]),
            "length": int(node["length"]),
        }
    return {
        "type": "merge",
        "node_id": str(node["node_id"]),
        "length": int(node["length"]),
        "interleave": str(node["interleave"]),
        "interleave_sha256": str(node["interleave_sha256"]),
        "left": _deep_copy_node(node["left"]),
        "right": _deep_copy_node(node["right"]),
    }


def _new_merge_node(left, right, relpath, node_id, interleave_sha256):
    return {
        "type": "merge",
        "node_id": str(node_id),
        "length": int(left["length"]) + int(right["length"]),
        "interleave": str(relpath).replace(os.sep, "/"),
        "interleave_sha256": str(interleave_sha256),
        "left": left,
        "right": right,
    }


def _write_interleave(output_dir, node_id, bits):
    store = os.path.join(
        output_dir, PROVENANCE_DIRNAME, INTERLEAVE_DIRNAME)
    if not os.path.isdir(store):
        os.makedirs(store)

    path = os.path.join(store, "%s.npy" % node_id)
    packed = _pack_little_endian_bits(bits)
    np.save(path, packed)
    relpath = os.path.join(
        PROVENANCE_DIRNAME, INTERLEAVE_DIRNAME,
        os.path.basename(path)).replace(os.sep, "/")
    # Production digest contract: every merge node carries the content
    # digest of its interleave so a same-length replaced interleave can
    # never silently produce wrong source assignments.
    return relpath, _array_sha256(np.ascontiguousarray(packed))


class _PruneResult(object):
    __slots__ = ("node", "state", "mask")

    # state:
    #   "all"     every original row under this node survives
    #   "none"    no original row survives
    #   "partial" mask contains surviving original rows
    def __init__(self, node, state, mask=None):
        self.node = node
        self.state = state
        self.mask = mask


def _materialize_child_mask(result, length):
    if result.state == "all":
        return np.ones(int(length), dtype=np.bool_)
    if result.state == "none":
        return np.zeros(int(length), dtype=np.bool_)
    return result.mask


def _prune_tree(node, keep_source_ids, input_dir, output_dir, stats):
    node_sources = _node_sources(node)

    if node_sources <= keep_source_ids:
        stats["subtrees_reused"] += 1
        return _PruneResult(_deep_copy_node(node), "all")

    if not (node_sources & keep_source_ids):
        if node["type"] == "leaf":
            stats["leaves_removed"] += 1
        else:
            stats["subtrees_removed"] += 1
        return _PruneResult(None, "none")

    if node["type"] == "leaf":
        # A leaf cannot be partially selected.
        raise SourceRemovalError(
            "internal pruning error at leaf %s" % node["source_id"]
        )

    left_result = _prune_tree(
        node["left"],
        keep_source_ids,
        input_dir,
        output_dir,
        stats,
    )
    right_result = _prune_tree(
        node["right"],
        keep_source_ids,
        input_dir,
        output_dir,
        stats,
    )

    bits = unpack_interleave(
        os.path.join(input_dir, str(node["interleave"])),
        int(node["length"]),
    )

    left_mask = _materialize_child_mask(
        left_result,
        int(node["left"]["length"]),
    )
    right_mask = _materialize_child_mask(
        right_result,
        int(node["right"]["length"]),
    )

    parent_mask = np.empty(
        int(node["length"]),
        dtype=np.bool_,
    )
    branch0 = bits == 0
    parent_mask[branch0] = left_mask
    parent_mask[~branch0] = right_mask

    left_alive = left_result.node is not None
    right_alive = right_result.node is not None

    if not left_alive and not right_alive:
        return _PruneResult(None, "none")

    if left_alive and not right_alive:
        stats["nodes_collapsed"] += 1
        return _PruneResult(left_result.node, "partial", parent_mask)

    if right_alive and not left_alive:
        stats["nodes_collapsed"] += 1
        return _PruneResult(right_result.node, "partial", parent_mask)

    filtered_bits = bits[parent_mask]
    new_node_id = str(uuid.uuid4())
    relpath, interleave_sha256 = _write_interleave(
        output_dir, new_node_id, filtered_bits)
    new_node = _new_merge_node(
        left_result.node,
        right_result.node,
        relpath,
        new_node_id,
        interleave_sha256,
    )

    expected = (
        int(left_result.node["length"])
        + int(right_result.node["length"])
    )
    if int(filtered_bits.shape[0]) != expected:
        raise SourceRemovalError(
            "filtered interleave length %d != retained child total %d"
            % (filtered_bits.shape[0], expected)
        )

    stats["nodes_rewritten"] += 1
    return _PruneResult(new_node, "partial", parent_mask)


def _copy_reused_interleaves(node, input_dir, output_dir):
    """Copy interleaves referenced by reused original nodes."""
    if node["type"] == "leaf":
        return

    src = os.path.join(input_dir, str(node["interleave"]))
    dst = os.path.join(output_dir, str(node["interleave"]))
    if not os.path.exists(dst):
        dst_dir = os.path.dirname(dst)
        if not os.path.isdir(dst_dir):
            os.makedirs(dst_dir)
        shutil.copy2(src, dst)

    _copy_reused_interleaves(node["left"], input_dir, output_dir)
    _copy_reused_interleaves(node["right"], input_dir, output_dir)


def _write_filtered_bwt(
    input_dir,
    output_dir,
    keep_mask,
    chunk_rows=8 * 1024 * 1024,
):
    input_bwt = np.load(
        os.path.join(input_dir, BWT_FILENAME),
        mmap_mode="r",
    )
    mask = np.asarray(keep_mask, dtype=np.bool_)
    if mask.shape != input_bwt.shape:
        raise SourceRemovalError(
            "root keep mask shape %r != BWT shape %r"
            % (mask.shape, input_bwt.shape)
        )

    output_length = int(np.count_nonzero(mask))
    output_path = os.path.join(output_dir, BWT_FILENAME)
    output = open_memmap(
        str(output_path),
        mode="w+",
        dtype=input_bwt.dtype,
        shape=(output_length,),
    )

    write_pos = 0
    chunk_rows = max(1, int(chunk_rows))
    for start in range(0, input_bwt.shape[0], chunk_rows):
        end = min(start + chunk_rows, input_bwt.shape[0])
        local_mask = mask[start:end]
        count = int(np.count_nonzero(local_mask))
        if count:
            output[write_pos: write_pos + count] = (
                input_bwt[start:end][local_mask]
            )
            write_pos += count

    output.flush()
    del output

    if write_pos != output_length:
        raise SourceRemovalError(
            "filtered BWT wrote %d rows, expected %d"
            % (write_pos, output_length)
        )
    return output_length


def _filter_metadata_document(document, kept_source_ids):
    if document is None:
        return None

    kept_source_ids = set(str(x) for x in kept_source_ids)
    output = {
        "format": document.get("format", "msbwt-source-metadata"),
        "version": int(document.get("version", 1)),
        "sources": {},
        "groups": {},
    }

    for sid, record in document.get("sources", {}).items():
        if str(sid) in kept_source_ids:
            output["sources"][str(sid)] = dict(record)

    for name, members in document.get("groups", {}).items():
        output["groups"][str(name)] = [
            str(sid)
            for sid in members
            if str(sid) in kept_source_ids
        ]

    return output


def _load_metadata_document(input_dir, source_metadata_path=None):
    if source_metadata_path is not None:
        path = str(source_metadata_path)
    else:
        path = os.path.join(input_dir, METADATA_FILENAME)

    if not os.path.exists(path):
        return None, None

    with open(path, "rb") as fp:
        return json.load(fp), path


def _save_filtered_metadata(output_dir, document, kept_source_ids):
    if document is None:
        return None

    filtered = _filter_metadata_document(document, kept_source_ids)
    path = os.path.join(output_dir, METADATA_FILENAME)
    _atomic_write_json(path, filtered)
    return path


def _build_all_rank_indexes(output_dir, rank_stride_bytes=64):
    index = MultiSourceQueryIndex(
        output_dir,
        rank_stride_bytes=rank_stride_bytes,
        mmap=True,
        use_saved_rank=False,
    )
    for node_id in sorted(index._nodes_by_id):
        index._get_rank_index(node_id)
    return index.save_loaded_rank_indexes()


def _resolve_selection(
    input_dir,
    sources=None,
    group=None,
    where=None,
    source_metadata_path=None,
):
    qindex = MultiSourceQueryIndex(
        input_dir,
        mmap=True,
        use_saved_rank=True,
    )

    modes = (
        int(sources is not None)
        + int(group is not None)
        + int(where is not None)
    )
    if modes != 1:
        raise SourceRemovalError(
            "specify exactly one of sources, group, or where"
        )

    if sources is not None:
        return qindex.resolve_source_ids(sources)

    metadata_document, metadata_path = _load_metadata_document(
        input_dir,
        source_metadata_path=source_metadata_path,
    )
    if metadata_document is None:
        raise SourceRemovalError(
            "group/where removal requires source metadata"
        )

    catalog = SourceMetadataCatalog(
        qindex.list_sources(),
        document=metadata_document,
    )
    if group is not None:
        return catalog.group_sources(group)
    return catalog.resolve_selection(where=where)


def retain_sources(
    input_dir,
    output_dir,
    keep_sources,
    source_metadata_path=None,
    overwrite=False,
    build_rank_indexes=False,
    rank_stride_bytes=64,
    chunk_rows=8 * 1024 * 1024,
):
    """Create a new MSBWT containing only ``keep_sources``.

    This is Feature 10's core operation.  ``keep_sources`` accepts stable
    source IDs or unique source names.

    The input package is never mutated.  The output is built in a
    temporary sibling directory and atomically published only after the
    complete package validates.
    """
    input_dir = str(input_dir)
    output_dir = str(output_dir)

    if os.path.abspath(input_dir) == os.path.abspath(output_dir):
        raise SourceRemovalError(
            "Feature 10 requires a distinct output directory"
        )

    manifest = load_manifest(input_dir, validate=True)
    qindex = MultiSourceQueryIndex(
        input_dir,
        mmap=True,
        use_saved_rank=True,
    )
    keep_ids = qindex.resolve_source_ids(keep_sources)

    if not keep_ids:
        raise SourceRemovalError(
            "cannot retain zero sources"
        )

    all_ids = [
        str(source["id"])
        for source in manifest["sources"]
    ]
    keep_set = frozenset(keep_ids)
    if keep_set == frozenset(all_ids):
        raise SourceRemovalError(
            "selection retains every source; nothing to remove"
        )

    if os.path.exists(output_dir) and not overwrite:
        raise SourceRemovalError(
            "output already exists: %s" % output_dir
        )

    metadata_document, _ = _load_metadata_document(
        input_dir,
        source_metadata_path=source_metadata_path,
    )

    output_parent = os.path.dirname(output_dir)
    if not os.path.isdir(output_parent):
        os.makedirs(output_parent)
    temp_dir = tempfile.mkdtemp(
        prefix=".%s.point10-" % os.path.basename(output_dir),
        dir=output_parent,
    )

    stats = {
        "input_sources": len(all_ids),
        "retained_sources": len(keep_ids),
        "removed_sources": len(all_ids) - len(keep_ids),
        "input_bwt_rows": int(manifest["bwt_length"]),
        "output_bwt_rows": 0,
        "subtrees_reused": 0,
        "subtrees_removed": 0,
        "leaves_removed": 0,
        "nodes_collapsed": 0,
        "nodes_rewritten": 0,
        "read_provenance_preserved": False,
        "bwt_tags_preserved": False,
        "bwt_tag_count": 0,
        "quality_sidecar_preserved": False,
        "rank_indexes_built": 0,
    }

    try:
        prune = _prune_tree(
            manifest["root"],
            keep_set,
            input_dir,
            temp_dir,
            stats,
        )

        if prune.node is None:
            raise SourceRemovalError(
                "source selection removed every row"
            )

        if prune.state == "all":
            raise SourceRemovalError(
                "internal error: full selection should have been rejected"
            )
        if prune.state != "partial":
            raise SourceRemovalError(
                "unexpected root prune state: %s" % prune.state
            )

        root_mask = prune.mask
        output_length = _write_filtered_bwt(
            input_dir,
            temp_dir,
            root_mask,
            chunk_rows=chunk_rows,
        )
        stats["output_bwt_rows"] = output_length

        retained_source_records = [
            dict(source)
            for source in manifest["sources"]
            if str(source["id"]) in keep_set
        ]

        output_manifest = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "bwt_length": int(output_length),
            # Production digest contract: bind the manifest to the new BWT
            # content so a same-length replaced BWT is always detected.
            "msbwt_sha256": _array_sha256(
                np.ascontiguousarray(np.load(
                    os.path.join(temp_dir, BWT_FILENAME),
                    mmap_mode="r",
                ))
            ),
            "sources": retained_source_records,
            "root": prune.node,
        }

        # Copy original interleaves for any completely retained/reused nodes.
        _copy_reused_interleaves(
            prune.node,
            input_dir,
            temp_dir,
        )

        save_manifest(temp_dir, output_manifest)
        validate_manifest(temp_dir, output_manifest)

        # Preserve the root interleave convention expected by Holt/Feature 1.
        root_interleave = os.path.join(temp_dir, INTERLEAVE_FILENAME)
        if prune.node["type"] == "merge":
            shutil.copy2(
                os.path.join(temp_dir, str(prune.node["interleave"])),
                root_interleave,
            )

        # Feature 12: every BWT-row tag is filtered with the exact same
        # survival mask as msbwt.npy, preserving 1:1 row alignment.
        if tags_exist(input_dir):
            tag_store = filter_tag_arrays(
                input_dir,
                temp_dir,
                root_mask,
                chunk_rows=chunk_rows,
            )
            stats["bwt_tags_preserved"] = True
            stats["bwt_tag_count"] = len(tag_store.list_tags())

        # Filter Feature-9 read provenance using the '$'-row prefix.
        if read_provenance_exists(input_dir):
            input_bwt = np.load(
                os.path.join(input_dir, BWT_FILENAME),
                mmap_mode="r",
            )
            input_read_count = int(np.count_nonzero(input_bwt == 0))
            dollar_keep_mask = root_mask[:input_read_count]
            filter_read_provenance(
                input_dir,
                temp_dir,
                dollar_keep_mask,
            )
            stats["read_provenance_preserved"] = True

        # Q1: regenerate the quality sidecar metadata for the reduced
        # package (the quality tag itself was already filtered with the
        # exact BWT survival mask above).
        if quality_sidecar_exists(input_dir):
            filter_quality_sidecar_metadata(
                input_dir,
                temp_dir,
            )
            stats["quality_sidecar_preserved"] = True

        _save_filtered_metadata(
            temp_dir,
            metadata_document,
            keep_ids,
        )

        if build_rank_indexes and prune.node["type"] == "merge":
            written = _build_all_rank_indexes(
                temp_dir,
                rank_stride_bytes=rank_stride_bytes,
            )
            stats["rank_indexes_built"] = len(written)

        # Final validation after all optional files are written.
        validate_manifest(temp_dir)

        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        _atomic_publish(temp_dir, output_dir)

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    stats["retained_source_ids"] = list(keep_ids)
    stats["removed_source_ids"] = [
        sid for sid in all_ids if sid not in keep_set
    ]
    stats["rows_removed"] = (
        stats["input_bwt_rows"]
        - stats["output_bwt_rows"]
    )
    return stats


def remove_sources(
    input_dir,
    output_dir,
    sources=None,
    group=None,
    where=None,
    source_metadata_path=None,
    overwrite=False,
    build_rank_indexes=False,
    rank_stride_bytes=64,
    chunk_rows=8 * 1024 * 1024,
):
    """Remove source(s)/group from a merged MSBWT without FASTQ rebuilding."""
    remove_ids = _resolve_selection(
        input_dir,
        sources=sources,
        group=group,
        where=where,
        source_metadata_path=source_metadata_path,
    )

    qindex = MultiSourceQueryIndex(
        input_dir,
        mmap=True,
        use_saved_rank=True,
    )
    all_ids = [
        str(source["id"])
        for source in qindex.list_sources()
    ]
    remove_set = frozenset(remove_ids)

    if not remove_set:
        raise SourceRemovalError(
            "selection matches zero sources"
        )
    if remove_set == frozenset(all_ids):
        raise SourceRemovalError(
            "cannot remove all sources"
        )

    keep_ids = [
        sid for sid in all_ids
        if sid not in remove_set
    ]

    return retain_sources(
        input_dir,
        output_dir,
        keep_ids,
        source_metadata_path=source_metadata_path,
        overwrite=overwrite,
        build_rank_indexes=build_rank_indexes,
        rank_stride_bytes=rank_stride_bytes,
        chunk_rows=chunk_rows,
    )
