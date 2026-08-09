"""Host-side guards for the manifest-driven clean RLE oracle milestone."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT_ROOT = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment"
MANIFEST_PATH = ENVIRONMENT_ROOT / "compression-milestone1-cases.json"
RUNNER_PATH = ENVIRONMENT_ROOT / "compression_milestone1.py"
PROBE_PATH = ENVIRONMENT_ROOT / "probe_legacy.py"
READER_PATH = ENVIRONMENT_ROOT / "reader_smoke.py"

sys.path.insert(0, str(ENVIRONMENT_ROOT))
SPEC = importlib.util.spec_from_file_location("compression_milestone1", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
compression_milestone1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compression_milestone1)


@contextmanager
def writable_temporary_directory():
    path = REPOSITORY_ROOT / (".compression-harness-test-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path)


class CompressionMilestone1HarnessTests(unittest.TestCase):
    def test_manifest_pins_profile_route_sources_and_execution_order(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            manifest["format"], "msbwt-legacy-compression-milestone1-cases-v1"
        )
        self.assertEqual(manifest["profile_id"], "py27-late-05a7d6d83862")
        self.assertEqual(manifest["route"], "pyx-historical-cython")
        self.assertEqual(manifest["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(manifest["canonical_processes"], 1)
        self.assertEqual(manifest["comparison_processes"], 2)
        self.assertEqual(
            manifest["successful_case_order"],
            [
                "uniform-posthoc",
                "nonuniform-posthoc",
                "uniform-direct-split",
                "uniform-direct-wrapper",
            ],
        )
        self.assertEqual(
            manifest["expected_failure_order"],
            ["uniform-decompress", "nonuniform-decompress"],
        )
        self.assertEqual(
            manifest["starting_artifacts"]["uniform_build"]["tree_sha256"],
            "842bfc80080ca553ee23f07eb3da7616df96822cee7d774d163c1c2058d0132e",
        )
        self.assertEqual(
            manifest["starting_artifacts"]["nonuniform_build"]["tree_sha256"],
            "ad4aa043feb549e0af861ffde0deca11f8ac0b030c5305183f61f04f5f4d8c0a",
        )

    def test_runner_records_the_exact_cli_contract(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")

        for required in (
            'cli_argv("compress", "-p", str(processes), source, destination)',
            'cli_argv("decompress", "-p", "1", source, destination)',
            'cli_argv("pp", "-u", destination, *fixture_paths)',
            'cli_argv("cfpp", "-p", str(processes), "-u", "-c", destination)',
            'cli_argv("cffq", "-p", str(processes), "-u", "-c", destination, *fixture_paths)',
            'cli_argv("cfpp", "-p", "1", "-c", cfpp_dataset)',
            'cli_argv("cffq", "-p", "1", "-c", cffq_dataset, *fixture_paths)',
        ):
            self.assertIn(required, source)
        self.assertNotIn("failpoint", source.lower())
        self.assertNotIn("recovery-nonuniform-259", source)

    def test_decompression_uses_narrow_expected_failure_contract(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        contract = manifest["decompression_expected_failure"]
        source = RUNNER_PATH.read_text(encoding="utf-8")

        self.assertEqual(contract["exit_code"], 1)
        self.assertEqual(
            contract["stderr_sha256"],
            "227471aa531ec114ada93c2507f6b621df8109d70324b7217285efd518904ac4",
        )
        self.assertEqual(
            contract["source_side_effects"],
            ["comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"],
        )
        self.assertIn("def decompress_expected_failure_case", source)
        self.assertNotIn("uniform-roundtrip", source)
        self.assertNotIn("nonuniform-roundtrip", source)
        self.assertIn('returncode != contract["exit_code"]', source)
        self.assertIn('hashlib.sha256(stderr).hexdigest() != contract["stderr_sha256"]', source)
        self.assertIn('side_effects != contract["source_side_effects"]', source)
        self.assertIn("assert_u1_npy_bytes", source)

    def test_expected_failure_capture_executes_and_is_distinct_from_success(self) -> None:
        stderr = (
            '  File "MUS/CommandLineInterface.py", line 175\n'
            '  File "MUS/MSBWTGen.py", line 1203\n'
            '  File "MUS/MSBWTGen.py", line 1222\n'
            '  File "MUS/MultiStringBWT.py", line 608\n'
            '  File "MUS/MultiStringBWT.py", line 662\n'
            "TypeError: slice indices must be integers or None or have an __index__ method\n"
        ).encode("utf-8")

        with writable_temporary_directory() as temporary:
            root = Path(temporary)
            compressed = root / "compressed"
            compressed.mkdir()
            compressed_primary = b"frozen compressed primary"
            (compressed / "comp_msbwt.npy").write_bytes(compressed_primary)

            payload = b"\x00" * 4
            header_text = "{'descr': '|u1', 'fortran_order': False, 'shape': (4,), }"
            padding = 16 - ((10 + len(header_text) + 1) % 16)
            header = (header_text + (" " * padding) + "\n").encode("ascii")
            npy_bytes = b"\x93NUMPY\x01\x00" + len(header).to_bytes(2, "little") + header + payload

            class FakeRecorder:
                def __init__(self, output_dir: Path) -> None:
                    self.output_dir = str(output_dir)
                    self.records = []
                    (output_dir / "commands").mkdir(parents=True)

                def run(self, label, argv, cwd=None):  # noqa: ANN001
                    source = Path(argv[-2])
                    destination = Path(argv[-1])
                    for name in ("comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"):
                        (source / name).write_bytes(name.encode("ascii"))
                    destination.mkdir()
                    (destination / "msbwt.npy").write_bytes(npy_bytes)
                    stderr_path = Path(self.output_dir) / "commands" / "failure.stderr"
                    stderr_path.write_bytes(stderr)
                    stdout_path = Path(self.output_dir) / "commands" / "failure.stdout"
                    stdout_path.write_bytes(b"")
                    self.records.append({
                        "label": label,
                        "returncode": 1,
                        "stderr": "commands/failure.stderr",
                        "stdout": "commands/failure.stdout",
                    })
                    return 1

            contract = {
                "exit_code": 1,
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                "exception": "TypeError: slice indices must be integers or None or have an __index__ method",
                "traceback_locations": [
                    'MUS/CommandLineInterface.py", line 175',
                    'MUS/MSBWTGen.py", line 1203',
                    'MUS/MSBWTGen.py", line 1222',
                    'MUS/MultiStringBWT.py", line 608',
                    'MUS/MultiStringBWT.py", line 662',
                ],
                "source_side_effects": ["comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"],
            }
            case_contract = {
                "compressed_sha256": hashlib.sha256(compressed_primary).hexdigest(),
                "source_manifest_content_sha256": "1" * 64,
                "destination_manifest_content_sha256": "2" * 64,
                "output_sha256": hashlib.sha256(npy_bytes).hexdigest(),
                "output_shape": [4],
                "output_payload_sha256": hashlib.sha256(payload).hexdigest(),
            }
            recorder = FakeRecorder(root / "recording")
            operation = root / "operation"
            operation.mkdir()

            result = compression_milestone1.decompress_expected_failure_case(
                recorder, str(root), str(operation), "expected", str(compressed),
                contract, case_contract,
            )

            self.assertEqual(result["status"], "expected-failure")
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["argv"], [
                "decompress", "-p", "1", "SOURCE_COPY", "DESTINATION"
            ])
            self.assertEqual(result["primary"]["dtype"], "|u1")
            self.assertEqual(result["primary"]["shape"], [4])

    def test_probe_requires_all_milestone_inputs_and_historical_pyx_route(self) -> None:
        source = PROBE_PATH.read_text(encoding="utf-8")

        self.assertIn('args.route != "pyx-historical-cython"', source)
        self.assertIn('not args.fixture_root or not args.golden_root', source)
        self.assertIn('not args.install_dependencies', source)
        self.assertIn('platform.python_implementation() != "CPython"', source)

    def test_reader_probe_records_dollar_ids_and_coexistence_preference(self) -> None:
        source = READER_PATH.read_text(encoding="utf-8")

        self.assertIn('"recovered_by_dollar_id"', source)
        self.assertIn('result["reader_class"] != "ByteBWT"', source)
        self.assertIn('rle_reader.__class__.__name__ != "RLE_BWT"', source)
        self.assertIn('os.remove(os.path.join(args.copy, "msbwt.npy"))', source)


if __name__ == "__main__":
    unittest.main()
