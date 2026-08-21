"""Editable source metadata and named groups for multi-source MSBWTs
(Feature 7, enhanced-modern2).

This module intentionally keeps biological/cohort metadata outside the BWT
and outside ``provenance.json``.  Provenance defines immutable source
identity and merge structure (AUTHORITATIVE); this file defines mutable
user metadata such as:

    case/control
    batch
    tissue
    cohort
    named source sets

Changing metadata therefore never requires rebuilding or re-merging the
MSBWT.  The catalog validates that every referenced source exists in the
immutable provenance manifest, and rejects unknown sources, malformed
documents, wrong format/version, and conflicting group definitions.

This is the Feature-7 adaptation of the Point-7 candidate
(``research/feature-candidates/7/SourceMetadata.py``) with:
- atomic ``save`` (tmp file + rename) so a torn metadata file is never
  left looking valid;
- JSON decode failures wrapped as ``SourceMetadataError`` (loud failure).

Persistence classification:

- ``source_metadata.json`` (inside the merged directory, or any external
  JSON file supplied at load time) -- MUTABLE / REBUILDABLE user metadata.
  It never affects BWT bytes, ``provenance.json``, or any query semantics
  except through the explicitly requested subset/group/predicate selection.
  A missing file is not an error (loads an empty catalog); a corrupt file
  fails loudly.
"""

import json
import os
import sys

METADATA_FILENAME = "source_metadata.json"
METADATA_FORMAT = "msbwt-source-metadata"
METADATA_VERSION = 1


class SourceMetadataError(ValueError):
    """Raised for invalid group/metadata definitions."""


def _atomic_write_json(path, document):
    """Write a metadata document atomically (tmp file -> rename).

    ``os.replace`` on Python 3, ``os.rename`` on Python 2 (atomic on the
    same POSIX filesystem).  JSON is serialized with ``ensure_ascii``
    escapes (pure ASCII) and written in binary mode.
    """
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
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
    if hasattr(os, "replace"):
        os.replace(tmp_path, path)
    elif os.name == "nt" and os.path.exists(path):
        os.remove(path)
        os.rename(tmp_path, path)
    else:
        os.rename(tmp_path, path)


def _load_json_document(path):
    """Read a JSON document, wrapping decode failures loudly."""
    try:
        with open(path, "rb") as fp:
            return json.load(fp)
    except ValueError as exc:
        raise SourceMetadataError(
            "source metadata is not valid JSON: %s: %s" % (path, exc))


class SourceMetadataCatalog(object):
    """Resolve named groups and metadata predicates to stable source IDs."""

    def __init__(self, source_records, document=None):
        self._source_records = [dict(record) for record in source_records]
        self._source_ids = [str(record["id"])
                            for record in self._source_records]
        self._source_id_set = set(self._source_ids)
        self._source_order = {
            sid: i for i, sid in enumerate(self._source_ids)
        }

        if document is None:
            document = {
                "format": METADATA_FORMAT,
                "version": METADATA_VERSION,
                "sources": {},
                "groups": {},
            }
        self.document = self._normalize_document(document)

    @classmethod
    def from_file(cls, metadata_path, source_records):
        path = str(metadata_path)
        if not os.path.exists(path):
            raise IOError("source metadata file not found: %s" % path)
        return cls(source_records, document=_load_json_document(path))

    @classmethod
    def load(cls, merged_bwt_dir, source_records, required=False):
        path = os.path.join(str(merged_bwt_dir), METADATA_FILENAME)
        if not os.path.exists(path):
            if required:
                raise IOError("source metadata file not found: %s" % path)
            return cls(source_records)

        return cls(source_records, document=_load_json_document(path))

    def _normalize_document(self, document):
        if not isinstance(document, dict):
            raise SourceMetadataError(
                "metadata document must be a JSON object")

        fmt = document.get("format", METADATA_FORMAT)
        version = int(document.get("version", METADATA_VERSION))
        if fmt != METADATA_FORMAT:
            raise SourceMetadataError(
                "unsupported metadata format: %r" % fmt)
        if version != METADATA_VERSION:
            raise SourceMetadataError(
                "unsupported metadata version: %r" % version)

        sources = document.get("sources", {})
        groups = document.get("groups", {})
        if not isinstance(sources, dict):
            raise SourceMetadataError("'sources' must be an object")
        if not isinstance(groups, dict):
            raise SourceMetadataError("'groups' must be an object")

        normalized_sources = {}
        for raw_sid, record in sources.items():
            sid = str(raw_sid)
            self._validate_source_id(sid)
            if record is None:
                record = {}
            if not isinstance(record, dict):
                raise SourceMetadataError(
                    "metadata for source %s must be an object" % sid)
            normalized_sources[sid] = dict(record)

        normalized_groups = {}
        for raw_name, members in groups.items():
            name = str(raw_name)
            if not name:
                raise SourceMetadataError("group name cannot be empty")
            if not isinstance(members, list):
                raise SourceMetadataError(
                    "group %s must be a list of source IDs" % name)
            normalized_groups[name] = self._normalize_source_list(members)

        return {
            "format": METADATA_FORMAT,
            "version": METADATA_VERSION,
            "sources": normalized_sources,
            "groups": normalized_groups,
        }

    def _validate_source_id(self, source_id):
        source_id = str(source_id)
        if source_id not in self._source_id_set:
            raise SourceMetadataError(
                "metadata references unknown source ID: %s" % source_id)
        return source_id

    def _normalize_source_list(self, sources):
        seen = set()
        result = []
        for raw in sources:
            sid = self._validate_source_id(str(raw))
            if sid not in seen:
                result.append(sid)
                seen.add(sid)

        # Canonicalize all groups/subsets to provenance source order.
        result.sort(key=self._source_order.__getitem__)
        return result

    def save(self, merged_bwt_dir):
        path = os.path.join(str(merged_bwt_dir), METADATA_FILENAME)
        _atomic_write_json(path, self.document)
        return path

    def list_groups(self):
        return sorted(self.document["groups"])

    def define_group(self, name, sources):
        name = str(name)
        if not name:
            raise SourceMetadataError("group name cannot be empty")
        self.document["groups"][name] = self._normalize_source_list(sources)
        return list(self.document["groups"][name])

    def delete_group(self, name):
        name = str(name)
        if name not in self.document["groups"]:
            raise KeyError("unknown group: %s" % name)
        del self.document["groups"][name]

    def group_sources(self, name):
        name = str(name)
        if name not in self.document["groups"]:
            raise KeyError("unknown group: %s" % name)
        return list(self.document["groups"][name])

    def set_source_metadata(self, source, **fields):
        sid = self._validate_source_id(str(source))
        record = self.document["sources"].setdefault(sid, {})
        for key, value in fields.items():
            record[str(key)] = value
        return dict(record)

    def source_metadata(self, source):
        sid = self._validate_source_id(str(source))
        return dict(self.document["sources"].get(sid, {}))

    @staticmethod
    def _value_matches(actual, expected):
        if isinstance(expected, (list, tuple, set)):
            return actual in expected
        if isinstance(actual, list):
            return expected in actual
        return actual == expected

    def select_where(self, **criteria):
        """Return source IDs whose metadata exactly matches all criteria.

        List-valued source metadata is treated as membership.  An expected
        iterable means "actual equals any one of these values".
        """
        result = []
        for sid in self._source_ids:
            record = self.document["sources"].get(sid, {})
            matched = True
            for key, expected in criteria.items():
                if key not in record:
                    matched = False
                    break
                if not self._value_matches(record[key], expected):
                    matched = False
                    break
            if matched:
                result.append(sid)
        return result

    def resolve_selection(self, sources=None, group=None, where=None):
        """Resolve exactly one subset selector into stable source IDs."""
        modes = (
            int(sources is not None)
            + int(group is not None)
            + int(where is not None)
        )
        if modes > 1:
            raise SourceMetadataError(
                "use only one of sources, group, or where per selection"
            )

        if sources is not None:
            return self._normalize_source_list(sources)
        if group is not None:
            return self.group_sources(group)
        if where is not None:
            if not isinstance(where, dict):
                raise SourceMetadataError("where must be a mapping")
            return self.select_where(**where)

        # No selector means all sources.
        return list(self._source_ids)
