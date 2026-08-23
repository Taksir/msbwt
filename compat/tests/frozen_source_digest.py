"""Platform-independent frozen-source digests (M3-R64 closure).

The frozen-source SHA-256 pins were originally computed over whatever byte
representation the authoring checkout happened to have (CRLF on the native
Windows machine).  On an LF checkout the same committed content produced
different digests, so the pins accidentally encoded a line-ending transform
instead of the source itself.

The committed Git blobs carry the authoritative logical LF content for every
text source.  These helpers therefore normalize CRLF to LF before digesting,
making the verdict identical on any checkout while still detecting ANY
unauthorized content modification.
"""

import hashlib


def lf_normalized(data):
    """Return *data* with CRLF pairs collapsed to LF."""
    if b"\r\n" in data:
        data = data.replace(b"\r\n", b"\n")
    return data


def lf_sha256_bytes(data):
    """SHA-256 hex digest of the LF-normalized content of *data*."""
    return hashlib.sha256(lf_normalized(data)).hexdigest()


def lf_sha256_file(path):
    """SHA-256 hex digest of the LF-normalized content of the file."""
    with open(path, "rb") as handle:
        return lf_sha256_bytes(handle.read())
