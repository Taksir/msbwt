"""M3-R64 closure: hostile mutation tests for platform-independent pins."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from frozen_source_digest import lf_sha256_bytes  # noqa: E402

KNOWN_LF = "125fdc96338ac6f97e569c9f63e923c4b201414bb2eeff36ea12c4c39f8776ea"


class HostileMutationTests(unittest.TestCase):
    def test_lf_and_crlf_representations_same_verdict(self):
        # the frozen source, in either checkout representation, must digest
        # to the same platform-independent pin
        repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        src = os.path.join(repo, "MUS", "MultiStringBWT.py")
        with open(src, "rb") as fp:
            raw = fp.read()
        lf_only = raw.replace(b"\r\n", b"\n")
        crlf = lf_only.replace(b"\n", b"\r\n")
        self.assertEqual(lf_sha256_bytes(raw), KNOWN_LF)
        self.assertEqual(lf_sha256_bytes(lf_only), KNOWN_LF)
        self.assertEqual(lf_sha256_bytes(crlf), KNOWN_LF)

    def test_unauthorized_modification_detected(self):
        data = b"line1\nline2\n"
        crlf = data.replace(b"\n", b"\r\n")
        base = lf_sha256_bytes(crlf)
        mutated = crlf.replace(b"line2", b"lineX")
        self.assertNotEqual(lf_sha256_bytes(mutated), base)
        # deletion / addition also detected
        self.assertNotEqual(lf_sha256_bytes(b"line1\n"), base)
        self.assertNotEqual(lf_sha256_bytes(b"line1\nline2\nline3\n"), base)

    def test_binary_content_still_byte_exact_when_needed(self):
        # binary files (no CRLF semantics) hash identically raw vs normalized
        # only when they contain no CRLF pairs; document the boundary.
        pure_lf = b"\x00\x01binary\x02\n"
        self.assertEqual(lf_sha256_bytes(pure_lf),
                         __import__("hashlib").sha256(pure_lf).hexdigest())


if __name__ == "__main__":
    unittest.main()
