"""Stdlib tests for the host-side frozen-oracle capture tooling."""

import base64
import importlib.util
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("artifact_manifest", TOOL_PATH)
artifact_manifest = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(artifact_manifest)


def write_test_npy(path, major, header_text, payload):
    encoded_header = header_text.encode("latin-1" if major in (1, 2) else "utf-8")
    length_width = 2 if major == 1 else 4
    with Path(path).open("wb") as target:
        target.write(b"\x93NUMPY" + bytes((major, 0)))
        target.write(len(encoded_header).to_bytes(length_width, "little"))
        target.write(encoded_header)
        target.write(payload)


@contextmanager
def workspace_temporary_directory():
    """Create a Windows-safe workspace directory and remove it afterward.

    ``tempfile`` requests mode 0700.  On this Google Drive-backed Windows
    workspace that mode produces an unreadable directory, so tests use the
    ordinary inherited workspace permissions instead.
    """

    base = Path(__file__).parents[1] / ".tmp-tests"
    base.mkdir(exist_ok=True)
    temporary = base / ("run-" + uuid.uuid4().hex)
    temporary.mkdir()
    try:
        yield str(temporary)
    finally:
        shutil.rmtree(temporary)
        try:
            base.rmdir()
        except OSError:
            # A concurrent test still owns a child, or cleanup already removed it.
            pass


class ArtifactManifestTests(unittest.TestCase):
    def test_inventory_hashes_files_and_handles_a_weird_filename(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary) / "oracle"
            root.mkdir()
            (root / "nested").mkdir()
            data_path = root / "nested" / "strange [name] ☃.txt"
            data_path.write_bytes(b"legacy\x00bytes\n")

            manifest = artifact_manifest.inventory_directory(root)

            self.assertEqual(manifest["format"], artifact_manifest.FORMAT_NAME)
            self.assertEqual(manifest["artifacts"][0]["path"], "nested/strange [name] ☃.txt")
            self.assertEqual(manifest["artifacts"][0]["size"], 13)
            self.assertEqual(
                manifest["content_sha256"],
                artifact_manifest.sha256_bytes(
                    artifact_manifest.canonical_json_bytes(
                        {"format": manifest["format"], "artifacts": manifest["artifacts"]}
                    )
                ),
            )

    def test_parses_npy_v1_and_v2_headers_without_numpy(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            header = "{'descr': '<u8', 'fortran_order': False, 'shape': (2,), }\n"
            write_test_npy(root / "one.npy", 1, header, b"\x01" * 16)
            write_test_npy(root / "two.npy", 2, header, b"\x02" * 16)

            manifest = artifact_manifest.inventory_directory(root)
            one, two = manifest["artifacts"]
            self.assertEqual(one["npy"]["version"], [1, 0])
            self.assertEqual(two["npy"]["version"], [2, 0])
            for entry in (one, two):
                self.assertEqual(entry["npy"]["dtype_descriptor"], "<u8")
                self.assertEqual(entry["npy"]["shape"], [2])
                self.assertFalse(entry["npy"]["fortran_order"])
                self.assertEqual(entry["npy"]["payload_size"], 16)

    def test_rejects_oversized_npy_header_before_reading_it(self):
        with workspace_temporary_directory() as temporary:
            path = Path(temporary) / "oversized.npy"
            declared = artifact_manifest.MAX_NPY_HEADER_BYTES + 1
            path.write_bytes(b"\x93NUMPY\x02\x00" + declared.to_bytes(4, "little"))

            with self.assertRaisesRegex(artifact_manifest.ManifestError, "safety limit"):
                artifact_manifest.parse_npy_header(path)

    def test_compare_detects_hash_drift(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary) / "oracle"
            root.mkdir()
            target = root / "primary.bin"
            target.write_bytes(b"before")
            expected = artifact_manifest.inventory_directory(root)
            target.write_bytes(b"after")

            report = artifact_manifest.compare_manifest(
                expected, artifact_manifest.inventory_directory(root)
            )

            self.assertFalse(report["matches"])
            self.assertEqual(report["changed"], [{"path": "primary.bin", "fields": ["sha256", "size"]}])

    def test_capture_records_success_and_failure_bytes(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "seed.bin").write_bytes(b"seed")

            success, success_code = artifact_manifest.capture_command(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok\\x00')"],
                root,
                artifacts,
                env_assignments={"GOLDEN_TOOL_TEST": "yes"},
                record_environment=("GOLDEN_TOOL_TEST",),
            )
            failure, failure_code = artifact_manifest.capture_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'partial'); sys.stderr.buffer.write(b'bad\\xff'); sys.exit(7)",
                ],
                root,
                artifacts,
            )

            self.assertEqual(success_code, 0)
            self.assertEqual(
                base64.b64decode(success["result"]["stdout"]["bytes_base64"]), b"ok\x00"
            )
            self.assertEqual(
                success["run_metadata"]["selected_environment"]["GOLDEN_TOOL_TEST"], "yes"
            )
            self.assertEqual(failure_code, 7)
            self.assertIsNone(failure["result"]["execution_error"])
            self.assertEqual(
                base64.b64decode(failure["result"]["stdout"]["bytes_base64"]), b"partial"
            )
            self.assertEqual(
                base64.b64decode(failure["result"]["stderr"]["bytes_base64"]), b"bad\xff"
            )
            self.assertIsNotNone(failure["artifact_manifest"])

    def test_cli_verify_returns_nonzero_for_drift(self):
        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "data.bin").write_bytes(b"one")
            manifest_path = root / "manifest.json"
            artifact_manifest.write_json(manifest_path, artifact_manifest.inventory_directory(artifacts))
            (artifacts / "data.bin").write_bytes(b"two")

            self.assertEqual(
                artifact_manifest.main(
                    [
                        "verify",
                        "--artifact-dir",
                        str(artifacts),
                        "--manifest",
                        str(manifest_path),
                        "--output",
                        str(root / "verify-report.json"),
                    ]
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
