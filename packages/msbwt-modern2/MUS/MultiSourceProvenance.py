r"""Identity-preserving multi-source provenance for merged MSBWTs
(Feature 2, enhanced-modern2).

This module generalizes the two-source provenance of Feature 1
(``MUS.SourceIndex`` over ``inter0.npy``) to any number of original input
sources by composing the repository's existing Holt/McMillan *two-way* merge
(``MUSCython.GenericMerge.mergeTwoMSBWTs``).  Every two-way merge already
leaves a packed ``inter0.npy`` aligned with the new merged BWT rows:

    bit == 0  -> row came from the first (left) input BWT
    bit == 1  -> row came from the second (right) input BWT

(bits packed least-significant-bit first within each byte, matching
``GenericMerge.setBit_p`` / ``getBit_p``; see Feature 1).  This module turns
the per-merge bitvectors into a portable binary provenance tree:

    A --\
         AB --\
    B --/      \
                ABCD
    C --\      /
         CD --/
    D --/

Every leaf has a stable source ID.  Every internal node records the exact
interleave used to create that node.  The final merged directory copies every
internal interleave into ``provenance/interleaves`` so constituent identity
does not depend on keeping intermediate merge directories.

Persisted files (all under the merged BWT directory):

- ``provenance.json``                       AUTHORITATIVE manifest
- ``provenance/interleaves/<node-id>.npy``  AUTHORITATIVE interleave copies
- ``inter0.npy``                            baseline authoritative root
                                            interleave (unchanged; Feature 1
                                            reads it directly)

The manifest carries content digests (``msbwt_sha256``, per-node
``interleave_sha256``, per-source ``bwt_sha256``) so that a same-length
replaced BWT, a manifest copied from another index, or a same-length
same-count replaced interleave can never silently produce wrong source
assignments: ``validate_manifest`` recomputes every digest and raises
``ProvenanceError`` on any mismatch.

The public functions are pure Python/NumPy.  The actual BWT merge is injected
as a callable; ``holt_merge_two`` is the adapter for the repository's
``MUSCython.GenericMerge.mergeTwoMSBWTs``.

No per-source QUERY semantics are implemented here: Feature 3 is the query
layer.  ``extract_constituent_bwt`` is a correctness/regression oracle that
materializes one constituent BWT from the final package; Feature 3 will
project query intervals with rank instead.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""

from __future__ import absolute_import

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import uuid

import numpy as np


MANIFEST_FILENAME = "provenance.json"
PROVENANCE_DIRNAME = "provenance"
INTERLEAVE_DIRNAME = "interleaves"
INTERLEAVE_FILENAME = "inter0.npy"
BWT_FILENAME = "msbwt.npy"
FORMAT_NAME = "msbwt-multisource-provenance"
FORMAT_VERSION = 1


class ProvenanceError(ValueError):
    """Raised when provenance metadata or interleaves are inconsistent."""


# ---------------------------------------------------------------------------
# small path / io helpers (plain os.path only: the Path type is not
# available in the Python 2.7 standard library)
# ---------------------------------------------------------------------------


def _bwt_length(bwt_dir):
    bwt_path = os.path.join(bwt_dir, BWT_FILENAME)
    if not os.path.exists(bwt_path):
        raise ProvenanceError("missing BWT file: %s" % bwt_path)
    arr = np.load(bwt_path, mmap_mode="r")
    if arr.ndim != 1:
        raise ProvenanceError("%s must be one-dimensional" % bwt_path)
    return int(arr.shape[0])


def _array_sha256(array):
    """sha256 hex digest of the contiguous array bytes.

    Covers the stored array content only (like the Feature-1 interleave
    identity digest), not the .npy file header.  Deterministic across
    np.save versions because it is computed from the array bytes.
    """
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _manifest_path(bwt_dir):
    return os.path.join(bwt_dir, MANIFEST_FILENAME)


def _provenance_dir(bwt_dir):
    return os.path.join(bwt_dir, PROVENANCE_DIRNAME)


def _interleave_store_dir(bwt_dir):
    return os.path.join(
        _provenance_dir(bwt_dir), INTERLEAVE_DIRNAME)


def _new_node_id():
    return str(uuid.uuid4())


def _new_source_id():
    return str(uuid.uuid4())


def _atomic_replace(source_path, dest_path):
    """Replace ``dest_path`` with ``source_path`` atomically where possible.

    Python 2.7 has no ``os.replace``; ``os.rename`` is atomic on POSIX
    (same filesystem), which is the pinned modern2 runtime.  Python 3 uses
    ``os.replace`` when available.
    """
    if hasattr(os, "replace"):
        os.replace(source_path, dest_path)
    else:
        os.rename(source_path, dest_path)


def _atomic_write_json(path, manifest):
    """Write a JSON manifest atomically: tmp file -> flush -> fsync -> rename.

    A half-written authoritative file is never left looking valid: readers
    either see the old manifest or the complete new one.

    The manifest is serialized with ``ensure_ascii`` escapes (pure ASCII
    bytes) and written in binary mode, so the same code path works on
    Python 2.7 (where ``json.dump`` emits ``str``) and Python 3 (where it
    emits ``str`` that must be encoded).
    """
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
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
    _atomic_replace(tmp_path, path)


# ---------------------------------------------------------------------------
# manifest construction
# ---------------------------------------------------------------------------


def _source_record(source_id, source_name, length, bwt_sha256):
    return {
        "id": str(source_id),
        "name": str(source_name) if source_name is not None else str(source_id),
        "length": int(length),
        "bwt_sha256": str(bwt_sha256),
    }


def _leaf_node(source):
    return {
        "type": "leaf",
        "source_id": source["id"],
        "length": int(source["length"]),
    }


def _merge_node(left_root, right_root, interleave_relpath, node_id,
                interleave_sha256):
    return {
        "type": "merge",
        "node_id": str(node_id),
        "length": int(left_root["length"]) + int(right_root["length"]),
        "interleave": str(interleave_relpath).replace(os.sep, "/"),
        "interleave_sha256": str(interleave_sha256),
        "left": left_root,
        "right": right_root,
    }


def _manifest(root, sources, bwt_length, bwt_sha256):
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "bwt_length": int(bwt_length),
        "msbwt_sha256": str(bwt_sha256),
        "sources": list(sources),
        "root": root,
    }


def save_manifest(bwt_dir, manifest):
    """Write the provenance manifest atomically."""
    path = _manifest_path(bwt_dir)
    _atomic_write_json(path, manifest)
    return path


def load_manifest(bwt_dir, validate=True):
    """Load the provenance manifest (validating by default)."""
    path = _manifest_path(bwt_dir)
    if not os.path.exists(path):
        raise ProvenanceError("provenance manifest not found: %s" % path)
    try:
        with open(path, "rb") as fp:
            manifest = json.load(fp)
    except ValueError as exc:
        # truncated/corrupt JSON must fail loudly, never parse partially
        raise ProvenanceError(
            "provenance manifest is not valid JSON: %s: %s" % (path, exc))
    if validate:
        validate_manifest(bwt_dir, manifest)
    return manifest


def initialize_leaf_provenance(
    bwt_dir,
    source_id=None,
    source_name=None,
    overwrite=False,
):
    """Attach a stable identity to a standalone/single-source MSBWT.

    This changes no BWT bytes.  If a manifest already exists it is returned
    unless ``overwrite`` is explicitly requested.

    Source IDs are stable string identities: user-specified ``source_id``
    (recommended) or a generated UUID.  ASCII ids are recommended; ids are
    stored verbatim in the JSON manifest and survive save/reload unchanged.
    """
    existing = _manifest_path(bwt_dir)
    if os.path.exists(existing) and not overwrite:
        return load_manifest(bwt_dir)

    length = _bwt_length(bwt_dir)
    if source_id is None:
        source_id = _new_source_id()
    if source_name is None:
        source_name = str(source_id)
    bwt_sha256 = _array_sha256(
        np.ascontiguousarray(np.load(
            os.path.join(bwt_dir, BWT_FILENAME), mmap_mode="r")))

    source = _source_record(source_id, source_name, length, bwt_sha256)
    manifest = _manifest(_leaf_node(source), [source], length, bwt_sha256)
    save_manifest(bwt_dir, manifest)
    validate_manifest(bwt_dir, manifest)
    return manifest


def ensure_provenance(bwt_dir, source_id=None, source_name=None):
    """Load existing provenance or initialize a leaf manifest.

    An existing manifest is authoritative: explicit ``source_id`` /
    ``source_name`` apply only when no manifest exists yet (use
    ``initialize_leaf_provenance(..., overwrite=True)`` to re-identify).
    """
    if os.path.exists(_manifest_path(bwt_dir)):
        return load_manifest(bwt_dir)
    return initialize_leaf_provenance(
        bwt_dir,
        source_id=source_id,
        source_name=source_name,
    )


def list_sources(bwt_dir):
    """Return source records in stable manifest order."""
    return list(load_manifest(bwt_dir)["sources"])


def source_ids(bwt_dir):
    """Return source IDs in stable manifest order."""
    return [src["id"] for src in list_sources(bwt_dir)]


def source_ids_from_manifest(manifest):
    """Return source IDs from an in-memory manifest (stable order)."""
    return [src["id"] for src in manifest["sources"]]


# ---------------------------------------------------------------------------
# interleave packing / unpacking
# ---------------------------------------------------------------------------


def _pack_little_endian_bits(bits):
    """Pack 0/1 bits exactly like GenericMerge: bit i is 1 << (i & 7)."""
    bits = np.asarray(bits, dtype=np.uint8).reshape(-1)
    out = np.zeros((bits.shape[0] + 7) // 8, dtype=np.uint8)
    for offset in range(8):
        selected = bits[offset::8]
        if selected.size:
            out[: selected.size] |= selected << np.uint8(offset)
    return out


def unpack_interleave(interleave_path, total_bits):
    """Return the valid interleave bits, little-endian within every byte.

    The final stored byte may contain padding bits beyond ``total_bits``;
    they are never returned.
    """
    packed = np.load(interleave_path, mmap_mode="r")
    if packed.ndim != 1 or packed.dtype != np.dtype("uint8"):
        raise ProvenanceError(
            "interleave must be a one-dimensional uint8 array: %s"
            % interleave_path)
    total_bits = int(total_bits)
    needed = (total_bits + 7) // 8
    if packed.shape[0] < needed:
        raise ProvenanceError(
            "interleave %s is too short for %d rows"
            % (interleave_path, total_bits))
    if total_bits == 0:
        return np.empty(0, dtype=np.uint8)

    used = np.asarray(packed[:needed], dtype=np.uint8)
    shifts = np.arange(8, dtype=np.uint8)
    bits = ((used[:, None] >> shifts[None, :]) & np.uint8(1)).reshape(-1)
    return bits[:total_bits]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def validate_manifest(bwt_dir, manifest=None):
    """Validate format/version, digests, source IDs, tree lengths, and every
    saved interleave.

    Everything inconsistent raises ``ProvenanceError``; there is no silent
    acceptance path.  Digest checks make same-length content replacement
    (BWT or interleave) and manifests copied from another index detectable.
    """
    bwt_dir = str(bwt_dir)
    if manifest is None:
        path = _manifest_path(bwt_dir)
        if not os.path.exists(path):
            raise ProvenanceError("provenance manifest not found: %s" % path)
        try:
            with open(path, "rb") as fp:
                manifest = json.load(fp)
        except ValueError as exc:
            raise ProvenanceError(
                "provenance manifest is not valid JSON: %s: %s" % (path, exc))

    if manifest.get("format") != FORMAT_NAME:
        raise ProvenanceError("unsupported provenance format: %r"
                              % (manifest.get("format"),))
    if int(manifest.get("version", -1)) != FORMAT_VERSION:
        raise ProvenanceError(
            "unsupported provenance version: %r (supported: %d)"
            % (manifest.get("version"), FORMAT_VERSION))

    bwt_path = os.path.join(bwt_dir, BWT_FILENAME)
    actual_bwt_length = _bwt_length(bwt_dir)
    if int(manifest.get("bwt_length", -1)) != actual_bwt_length:
        raise ProvenanceError(
            "manifest BWT length does not match msbwt.npy")

    if "msbwt_sha256" not in manifest:
        raise ProvenanceError(
            "manifest missing msbwt_sha256 identity field (unsupported "
            "pre-digest provenance manifest)")
    actual_msbwt_sha256 = _array_sha256(
        np.ascontiguousarray(np.load(bwt_path, mmap_mode="r")))
    if str(manifest["msbwt_sha256"]) != actual_msbwt_sha256:
        raise ProvenanceError(
            "manifest msbwt_sha256 does not match msbwt.npy content "
            "(same-length replaced BWT or metadata copied from another index)")

    source_records = manifest.get("sources", [])
    if not isinstance(source_records, list) or not source_records:
        raise ProvenanceError("manifest has no source records")
    ids = [str(src["id"]) for src in source_records]
    if len(ids) != len(set(ids)):
        raise ProvenanceError("duplicate source IDs in manifest")
    for src in source_records:
        if "bwt_sha256" not in src:
            raise ProvenanceError(
                "source record %r missing bwt_sha256 identity field"
                % (src.get("id"),))
    source_map = {str(src["id"]): src for src in source_records}

    def validate_node(node, is_root):
        node_type = node.get("type")
        node_length = int(node.get("length", -1))
        if node_length < 0:
            raise ProvenanceError("negative/missing node length")

        if node_type == "leaf":
            sid = str(node.get("source_id"))
            if sid not in source_map:
                raise ProvenanceError(
                    "leaf source missing from source table: %s" % sid)
            if int(source_map[sid]["length"]) != node_length:
                raise ProvenanceError("leaf length mismatch for %s" % sid)
            if is_root:
                # a standalone leaf manifest must describe THIS directory's
                # msbwt.npy; inside a merged tree the leaf BWT is the
                # original standalone file (recorded, not present here)
                if str(source_map[sid]["bwt_sha256"]) != actual_msbwt_sha256:
                    raise ProvenanceError(
                        "leaf bwt_sha256 does not match msbwt.npy content")
            return [sid]

        if node_type != "merge":
            raise ProvenanceError("unknown node type: %r" % node_type)

        left_ids = validate_node(node["left"], False)
        right_ids = validate_node(node["right"], False)
        left_length = int(node["left"]["length"])
        right_length = int(node["right"]["length"])
        if node_length != left_length + right_length:
            raise ProvenanceError("merge node length != child total")

        interleave_path = os.path.join(bwt_dir, str(node["interleave"]))
        if not os.path.exists(interleave_path):
            raise ProvenanceError("missing saved interleave: %s"
                                  % interleave_path)
        if "interleave_sha256" not in node:
            raise ProvenanceError(
                "merge node %r missing interleave_sha256 identity field"
                % (node.get("node_id"),))
        stored_sha256 = _array_sha256(
            np.ascontiguousarray(
                np.load(interleave_path, mmap_mode="r")))
        if str(node["interleave_sha256"]) != stored_sha256:
            raise ProvenanceError(
                "saved interleave %s does not match its manifest digest "
                "(same-length replaced interleave)" % interleave_path)
        bits = unpack_interleave(interleave_path, node_length)
        ones = int(bits.sum(dtype=np.uint64))
        zeros = node_length - ones
        if zeros != left_length or ones != right_length:
            raise ProvenanceError(
                "interleave counts do not match child lengths at node %s: "
                "zeros=%d expected=%d, ones=%d expected=%d"
                % (
                    node.get("node_id"),
                    zeros,
                    left_length,
                    ones,
                    right_length,
                )
            )
        return left_ids + right_ids

    root = manifest.get("root")
    if root is None:
        raise ProvenanceError("manifest has no root node")
    tree_ids = validate_node(root, True)
    if tree_ids != ids:
        raise ProvenanceError(
            "source table order does not match provenance leaf order")
    if int(root["length"]) != actual_bwt_length:
        raise ProvenanceError("root length does not match BWT length")
    return True


# ---------------------------------------------------------------------------
# merging with provenance
# ---------------------------------------------------------------------------


def _collect_leaf_ids(node):
    if node["type"] == "leaf":
        return [node["source_id"]]
    return _collect_leaf_ids(node["left"]) + _collect_leaf_ids(node["right"])


def _copy_child_interleaves(child_dir, output_dir):
    child_store = _interleave_store_dir(child_dir)
    if not os.path.isdir(child_store):
        return
    output_store = _interleave_store_dir(output_dir)
    if not os.path.isdir(output_store):
        os.makedirs(output_store)

    for filename in sorted(os.listdir(child_store)):
        if not filename.endswith(".npy"):
            continue
        source_path = os.path.join(child_store, filename)
        dest = os.path.join(output_store, filename)
        if os.path.exists(dest):
            # Internal node IDs are UUIDs.  A collision should mean the exact
            # same content; any byte difference makes the package
            # inconsistent and must fail loudly.
            source_sha256 = _array_sha256(
                np.ascontiguousarray(np.load(source_path, mmap_mode="r")))
            dest_sha256 = _array_sha256(
                np.ascontiguousarray(np.load(dest, mmap_mode="r")))
            if source_sha256 != dest_sha256:
                raise ProvenanceError(
                    "interleave node collision with different content: %s"
                    % filename)
            continue
        shutil.copy2(source_path, dest)


def _copy_root_interleave(output_dir, node_id):
    root_interleave = os.path.join(output_dir, INTERLEAVE_FILENAME)
    if not os.path.exists(root_interleave):
        raise ProvenanceError(
            "two-way merge did not create %s" % root_interleave)
    dest_dir = _interleave_store_dir(output_dir)
    if not os.path.isdir(dest_dir):
        os.makedirs(dest_dir)
    dest = os.path.join(dest_dir, str(node_id) + ".npy")
    shutil.copy2(root_interleave, dest)
    relpath = os.path.join(
        PROVENANCE_DIRNAME, INTERLEAVE_DIRNAME, os.path.basename(dest))
    sha256 = _array_sha256(
        np.ascontiguousarray(np.load(dest, mmap_mode="r")))
    return relpath.replace(os.sep, "/"), sha256


def _call_merge(merge_two_func, left_dir, right_dir, output_dir, num_procs,
                logger):
    """Call injected merge with a small compatibility surface.

    The compiled Cython signature is positional
    ``mergeTwoMSBWTs(input1, input2, merged, numProcs, logger)`` and (under
    Python 2) does not accept keyword arguments.  Try keywords first (the
    documented call shape for test adapters), then fall back to positional on
    an argument-signature TypeError only.
    """
    try:
        return merge_two_func(
            str(left_dir),
            str(right_dir),
            str(output_dir),
            num_procs=num_procs,
            logger=logger,
        )
    except TypeError as exc:
        text = str(exc)
        signature_markers = (
            "unexpected keyword",
            "positional argument",
            "required positional",
            "takes ",
        )
        if not any(marker in text for marker in signature_markers):
            raise
        return merge_two_func(
            str(left_dir), str(right_dir), str(output_dir), num_procs, logger
        )


def merge_two_with_provenance(
    left_dir,
    right_dir,
    output_dir,
    merge_two_func,
    num_procs=1,
    logger=None,
    left_source_id=None,
    left_source_name=None,
    right_source_id=None,
    right_source_name=None,
):
    """Merge two MSBWTs and preserve their complete constituent identities.

    ``merge_two_func`` must create at least:

    - ``<output>/msbwt.npy``
    - ``<output>/inter0.npy``

    with Holt/McMillan semantics: bit 0 selects the left input and bit 1
    selects the right input for each merged row.
    """
    left_dir = str(left_dir)
    right_dir = str(right_dir)
    output_dir = str(output_dir)
    if logger is None:
        logger = logging.getLogger(__name__)

    left_manifest = ensure_provenance(
        left_dir,
        source_id=left_source_id,
        source_name=left_source_name,
    )
    right_manifest = ensure_provenance(
        right_dir,
        source_id=right_source_id,
        source_name=right_source_name,
    )

    left_ids = {src["id"] for src in left_manifest["sources"]}
    right_ids = {src["id"] for src in right_manifest["sources"]}
    overlap = sorted(left_ids & right_ids)
    if overlap:
        raise ProvenanceError(
            "refusing to merge overlapping constituent IDs: %s"
            % ", ".join(overlap)
        )

    # Feature 9: never silently discard read-level provenance.  If both
    # children carry it, merge it automatically after the BWT/provenance
    # merge; if only one child has it, fail before the expensive merge.
    from MUS.ReadProvenance import (
        merge_two_read_provenance,
        read_provenance_exists,
    )
    left_has_read_provenance = read_provenance_exists(left_dir)
    right_has_read_provenance = read_provenance_exists(right_dir)
    if left_has_read_provenance != right_has_read_provenance:
        raise ProvenanceError(
            "read-level provenance is present on only one merge input; "
            "initialize/retrofit both children before merging so "
            "read provenance is not silently lost"
        )

    # Feature 12: validate BWT-row tag schemas before the expensive BWT
    # merge.  One-sided tags are permitted only when the tag explicitly
    # declares a missing value; otherwise the merge fails rather than
    # silently dropping or fabricating annotation values.
    from MUS.BWTTags import validate_tag_merge_compatibility
    tag_merge_plan = validate_tag_merge_compatibility(
        left_dir,
        right_dir,
    )

    if os.path.exists(output_dir):
        if os.listdir(output_dir):
            raise ProvenanceError(
                "output directory must be empty: %s" % output_dir)
    else:
        os.makedirs(output_dir)

    _call_merge(
        merge_two_func,
        left_dir,
        right_dir,
        output_dir,
        num_procs,
        logger,
    )

    actual_length = _bwt_length(output_dir)
    expected_length = (
        int(left_manifest["bwt_length"]) + int(right_manifest["bwt_length"])
    )
    if actual_length != expected_length:
        raise ProvenanceError(
            "merged BWT length %d != child total %d"
            % (actual_length, expected_length)
        )

    node_id = _new_node_id()
    _copy_child_interleaves(left_dir, output_dir)
    _copy_child_interleaves(right_dir, output_dir)
    root_relpath, root_sha256 = _copy_root_interleave(output_dir, node_id)

    root = _merge_node(
        left_manifest["root"],
        right_manifest["root"],
        root_relpath,
        node_id,
        root_sha256,
    )
    sources = list(left_manifest["sources"]) + list(right_manifest["sources"])
    manifest = _manifest(
        root, sources, actual_length,
        _array_sha256(
            np.ascontiguousarray(np.load(
                os.path.join(output_dir, BWT_FILENAME), mmap_mode="r"))))
    save_manifest(output_dir, manifest)
    validate_manifest(output_dir, manifest)

    if left_has_read_provenance and right_has_read_provenance:
        merge_two_read_provenance(left_dir, right_dir, output_dir)

    if tag_merge_plan:
        from MUS.BWTTags import merge_two_tag_arrays
        merge_two_tag_arrays(
            left_dir,
            right_dir,
            output_dir,
            plan=tag_merge_plan,
        )

    return manifest


def holt_merge_two(left_dir, right_dir, output_dir, num_procs=1, logger=None):
    """Adapter for ``GenericMerge.mergeTwoMSBWTs`` in the Holt repository.

    The original Cython signature uses ``char *`` and therefore expects
    bytes: under Python 3 the paths are ``os.fsencode``d; under Python 2
    ``str`` is already bytes.
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    from MUSCython import GenericMerge

    def as_bytes(path):
        if hasattr(os, "fsencode"):
            return os.fsencode(str(path))
        return str(path)

    return GenericMerge.mergeTwoMSBWTs(
        as_bytes(left_dir), as_bytes(right_dir), as_bytes(output_dir),
        int(num_procs), logger
    )


# ---------------------------------------------------------------------------
# multi-source balanced merge
# ---------------------------------------------------------------------------


def _copy_bwt_package(source_dir, output_dir):
    if os.path.exists(output_dir):
        raise ProvenanceError("output already exists: %s" % output_dir)
    shutil.copytree(source_dir, output_dir)


def merge_many_balanced(
    input_dirs,
    output_dir,
    merge_two_func=holt_merge_two,
    source_ids=None,
    source_names=None,
    num_procs=1,
    logger=None,
    work_dir=None,
    keep_work=False,
):
    """Balanced pairwise multi-source merge built from the two-way merge.

    For 8 inputs the merge shape is approximately ``8 -> 4 -> 2 -> 1``
    rather than a degenerate ``((((A+B)+C)+D)+...)`` tree, keeping source
    path depth logarithmic.  Any other tree shape is equally supported via
    repeated ``merge_two_with_provenance`` calls; correctness never depends
    on the tree being balanced.

    ``source_ids`` / ``source_names`` are applied in input order to leaves
    that do not already have a manifest.
    """
    input_dirs = [str(p) for p in input_dirs]
    if not input_dirs:
        raise ValueError("at least one input MSBWT is required")
    output_dir = str(output_dir)
    if os.path.exists(output_dir):
        if os.listdir(output_dir):
            raise ProvenanceError(
                "output directory must be empty: %s" % output_dir)
        os.rmdir(output_dir)

    n = len(input_dirs)
    if source_ids is not None and len(source_ids) != n:
        raise ValueError("source_ids length must match input_dirs")
    if source_names is not None and len(source_names) != n:
        raise ValueError("source_names length must match input_dirs")

    # Attach identities before any merge so duplicates are detected early.
    for i, bwt_dir in enumerate(input_dirs):
        ensure_provenance(
            bwt_dir,
            source_id=None if source_ids is None else source_ids[i],
            source_name=None if source_names is None else source_names[i],
        )

    all_ids = []
    for bwt_dir in input_dirs:
        all_ids.extend(source_ids_from_manifest(load_manifest(bwt_dir)))
    duplicates = sorted({sid for sid in all_ids if all_ids.count(sid) > 1})
    if duplicates:
        raise ProvenanceError(
            "duplicate constituent IDs before merge: %s" % ", ".join(duplicates)
        )

    if n == 1:
        _copy_bwt_package(input_dirs[0], output_dir)
        return load_manifest(output_dir)

    if logger is None:
        logger = logging.getLogger(__name__)

    owns_work_dir = work_dir is None
    if work_dir is None:
        work_root = tempfile.mkdtemp(prefix="msbwt_multisource_")
    else:
        work_root = str(work_dir)
        if not os.path.isdir(work_root):
            os.makedirs(work_root)

    current = list(input_dirs)
    level = 0
    try:
        while len(current) > 1:
            next_level = []
            pair_count = (len(current) + 1) // 2
            for pair_index in range(pair_count):
                left_index = 2 * pair_index
                if left_index + 1 >= len(current):
                    next_level.append(current[left_index])
                    continue

                left = current[left_index]
                right = current[left_index + 1]
                is_final = len(current) == 2
                if is_final:
                    parent = output_dir
                else:
                    parent = os.path.join(
                        work_root, "level_%03d_pair_%05d" % (level, pair_index))

                merge_two_with_provenance(
                    left,
                    right,
                    parent,
                    merge_two_func=merge_two_func,
                    num_procs=num_procs,
                    logger=logger,
                )
                next_level.append(parent)
            current = next_level
            level += 1

        if current[0] != output_dir:
            _copy_bwt_package(current[0], output_dir)
        return load_manifest(output_dir)
    finally:
        if owns_work_dir and not keep_work:
            shutil.rmtree(work_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# constituent recovery (correctness oracle; not the Feature-3 query layer)
# ---------------------------------------------------------------------------


def _node_contains_source(node, source_id):
    if node["type"] == "leaf":
        return node["source_id"] == source_id
    return _node_contains_source(node["left"], source_id) or _node_contains_source(
        node["right"], source_id
    )


def extract_constituent_bwt(bwt_dir, source_id):
    """Recover one constituent BWT exactly from final BWT + provenance tree.

    This is primarily a correctness/regression operation for Feature 2.  It
    materializes intermediate streams and is not intended as the Feature 3
    query implementation.
    """
    bwt_dir = str(bwt_dir)
    manifest = load_manifest(bwt_dir, validate=True)
    source_id = str(source_id)
    known = {src["id"] for src in manifest["sources"]}
    if source_id not in known:
        raise KeyError("unknown source ID: %s" % source_id)
    return _extract_from_manifest(manifest, bwt_dir, source_id)


def _extract_from_manifest(manifest, bwt_dir, source_id):
    """Internal extraction: filter the final BWT through the interleave tree.

    ``manifest`` must already be loaded (and validated by the caller)."""
    bwt_dir = str(bwt_dir)
    stream = np.asarray(
        np.load(os.path.join(bwt_dir, BWT_FILENAME), mmap_mode="r"))
    node = manifest["root"]

    while node["type"] != "leaf":
        bits = unpack_interleave(
            os.path.join(bwt_dir, str(node["interleave"])), node["length"])
        if _node_contains_source(node["left"], source_id):
            stream = stream[bits == 0]
            node = node["left"]
        else:
            stream = stream[bits == 1]
            node = node["right"]

        if int(stream.shape[0]) != int(node["length"]):
            raise ProvenanceError(
                "projected stream length does not match child node")

    if node["source_id"] != source_id:
        raise ProvenanceError("source traversal ended at wrong leaf")
    return np.asarray(stream, dtype=np.uint8)


def extract_all_constituent_bwts(bwt_dir):
    """Recover every constituent BWT; dict keyed by source ID."""
    bwt_dir = str(bwt_dir)
    manifest = load_manifest(bwt_dir, validate=True)
    return {
        src["id"]: _extract_from_manifest(manifest, bwt_dir, src["id"])
        for src in manifest["sources"]
    }
