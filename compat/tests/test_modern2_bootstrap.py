"""Read-only host-side regression tests for the msbwt-modern2 distribution.

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 package structure, version pins, Python-2
compatibility evidence, and milestone evidence without requiring the WSL
Python-2 environment.  The runtime build/slice validation lives in
packages/msbwt-modern2/validate/bootstrap-milestone1.sh (WSL).
"""

import json
import re
import unittest
from pathlib import Path

from modern2_source_acceptance import assert_source_within_acceptance

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
ENV_DIR = PACKAGE / "environment"
LOCK_DIR = ENV_DIR / "locks"
MUSCYN = PACKAGE / "MUSCython"
MSBWT_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
CYTHON_PIN = "3.0.12"
MIGRATED_MODULES = [
    "AlignmentUtil",
    "BasicBWT",
    "ByteBWTCython",
    "CompressToRLE",
    "GenericMerge",
    "MSBWTCompGenCython",
    "MSBWTGenCython",
    "MultiStringBWTCython",
    "MultimergeCython",
    "RLE_BWTCython",
    "LZW_BWTCython",
]
STUB_MODULES = ["LCPGen"]


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as source:
        return json.load(source)


class PackageLayoutTests(unittest.TestCase):
    def test_package_layout(self):
        expected_roots = [
            PACKAGE / "setup.py",
            PACKAGE / "MANIFEST.in",
            PACKAGE / "README.md",
            PACKAGE / "bin" / "msbwt",
            PACKAGE / "MUS" / "__init__.py",
            PACKAGE / "MUS" / "CommandLineInterface.py",
            PACKAGE / "MUS" / "MultiStringBWT.py",
            PACKAGE / "MUS" / "MSBWTGen.py",
            PACKAGE / "MUS" / "TranscriptBuilder.py",
            PACKAGE / "MUS" / "util.py",
            PACKAGE / "MUSCython" / "__init__.py",
            PACKAGE / "MUSCython" / "BasicBWT.pxd",
            ENV_DIR / "bootstrap-modern2.sh",
            ENV_DIR / "build-modern2.sh",
            PACKAGE / "validate" / "bootstrap-milestone1.sh",
            PACKAGE / "tests" / "test_bootstrap_py2.py",
            PACKAGE / "evidence" / "bootstrap-milestone1.json",
        ]
        for path in expected_roots:
            self.assertTrue(path.exists(), str(path))

    def test_migrated_modules_have_pyx_pxd_and_generated_c(self):
        for name in MIGRATED_MODULES:
            self.assertTrue((MUSCYN / (name + ".pyx")).exists(), name)
            self.assertTrue((MUSCYN / (name + ".c")).exists(), name)
        self.assertTrue((MUSCYN / "BasicBWT.pxd").exists())

    def test_stub_modules_present_and_explicit(self):
        for name in STUB_MODULES:
            text = (MUSCYN / (name + ".py")).read_text(encoding="utf-8")
            self.assertIn("NotImplementedError", text)
            self.assertIn("DEAD/PRIVATE", text)
            self.assertIn("MODERN2_MILESTONE10_PUBLIC_SURFACE", text)

    def test_no_stale_legacy_generated_c_in_package(self):
        for name in STUB_MODULES:
            self.assertFalse((MUSCYN / (name + ".c")).exists(), name)


class VersionPinTests(unittest.TestCase):
    def test_setup_py_gates_cython_3_0_x(self):
        text = (PACKAGE / "setup.py").read_text(encoding="utf-8")
        self.assertIn("language_level=2", text)
        self.assertIn("_cython_version.startswith('3.0.')", text)
        self.assertIn("Cython 3.1+ and 0.29.x are not supported", text)

    def test_wheel_lock_pins_cython_3_0_12(self):
        lines = (LOCK_DIR / "modern2-wheels.txt").read_text(encoding="utf-8").splitlines()
        cython_line = next(line for line in lines if line.startswith("Cython @"))
        self.assertIn("Cython-3.0.12-py2.py3-none-any.whl", cython_line)
        self.assertIn("sha256:0038c9bae46c459669390e53a1ec115f8096b2e4647ae007ff1bf4e6dee92806", cython_line)
        pinned = [line for line in lines if "Cython @ " not in line or "3.0.12" in line]
        self.assertEqual(len(pinned), len(lines))

    def test_profile_record_pins_exact_versions(self):
        profile = load_json(ENV_DIR / "modern2-profile.json")
        self.assertEqual(profile["format"], "msbwt-modern2-environment-v1")
        self.assertEqual(profile["profile_id"], "modern2-python27-3.0.12")
        cython = next(p for p in profile["python_packages"] if p["name"] == "Cython")
        self.assertEqual(cython["version"], CYTHON_PIN)
        self.assertEqual(cython["artifact_sha256"], "0038c9bae46c459669390e53a1ec115f8096b2e4647ae007ff1bf4e6dee92806")
        versions = {p["name"]: p["version"] for p in profile["python_packages"]}
        self.assertEqual(versions["numpy"], "1.16.6")
        self.assertEqual(versions["pysam"], "0.15.4")
        self.assertEqual(versions["pip"], "20.3.4")
        self.assertEqual(versions["setuptools"], "44.1.1")
        self.assertEqual(versions["wheel"], "0.37.1")
        self.assertIn("Cython 3.1+ and 0.29.x are prohibited", profile["cython_policy"])

    def test_bootstrap_script_asserts_pinned_versions(self):
        text = (ENV_DIR / "bootstrap-modern2.sh").read_text(encoding="utf-8")
        self.assertIn("==('3.0.12','1.16.6','0.15.4','20.3.4','44.1.1','0.37.1')", text)


class Python2CompatibilityTests(unittest.TestCase):
    # MUS/MultiStringBWT.py carries the documented modern2 decompression
    # fix (see COMPATIBILITY.md entry 1 and
    # docs/modernization/MODERN2_MILESTONE3_DECOMPRESSION.md): the exact
    # three-line diff vs the frozen original is asserted by
    # test_modern2_decompression.DecompressionFixSourceTests, so the
    # bootstrap byte-identity gate exempts only this one documented file.
    # MUS/CommandLineInterface.py carries the documented modern2 merge -p 1
    # fix (see COMPATIBILITY.md entry 2 and
    # docs/modernization/MODERN2_MILESTONE9_GENERIC_MERGE.md): the exact
    # one-line diff vs the frozen original is asserted by
    # test_modern2_generic_merge.SourcePolicyTests.
    # M3-R64-W5: MSBWTGen.py carries the accepted Windows-portability
    # temp-writer np.save normalization; its exact diff is whitelisted
    # line-by-line in modern2_source_acceptance.py.
    DOCUMENTED_DEVIATIONS = ("MUS/MultiStringBWT.py",
                             "MUS/CommandLineInterface.py",
                             "MUS/MSBWTGen.py",
                             # Windows-portability atomic-rename helpers
                             "MUS/util.py")

    def test_mus_pure_python_files_match_frozen_manifest(self):
        frozen_manifest = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "frozen-source.sha256"
        expected = {}
        for line in frozen_manifest.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^[0-9a-f]{64}\s+(.+)$", line)
            if not match:
                continue
            declaration = match.group(1)
            source = declaration.split(" <- ", 1)[-1]
            expected[source] = line.split()[0]
        for relative, digest in expected.items():
            if not relative.startswith("MUS/") or not relative.endswith(".py"):
                continue
            source_path = REPOSITORY_ROOT / relative
            candidate = PACKAGE / relative
            self.assertTrue(candidate.exists(), relative)
            source_bytes = source_path.read_bytes().replace(b"\r\n", b"\n")
            candidate_bytes = candidate.read_bytes().replace(b"\r\n", b"\n")
            if relative in self.DOCUMENTED_DEVIATIONS:
                self.assertNotEqual(candidate_bytes, source_bytes, relative)
                continue
            self.assertEqual(candidate_bytes, source_bytes, relative)

    def test_documented_deviation_is_covered_by_exact_diff_test(self):
        decompression_tests = (REPOSITORY_ROOT / "compat" / "tests" /
                               "test_modern2_decompression.py").read_text(
            encoding="utf-8")
        self.assertIn("test_modern2_diff_vs_frozen_is_exactly_the_index_fix",
                      decompression_tests)
        self.assertIn("MUS/MultiStringBWT.py", decompression_tests)
        merge_tests = (REPOSITORY_ROOT / "compat" / "tests" /
                       "test_modern2_generic_merge.py").read_text(
            encoding="utf-8")
        self.assertIn("test_modern2_cli_diff_is_exactly_the_numprocs_fix",
                      merge_tests)
        self.assertIn("MUS/CommandLineInterface.py", merge_tests)

    def test_documented_deviation_is_covered_by_acceptance_checker(self):
        # M3-R64-W6 (audit A-2): every DOCUMENTED_DEVIATIONS entry must be
        # enforced by the closed-set acceptance checker, not merely exempted
        # from the frozen-manifest byte-equality gate above.
        bootstrap_tests = Path(__file__).read_text(encoding="utf-8")
        for relative in ("MUS/MSBWTGen.py", "MUS/util.py"):
            self.assertIn('assert_source_within_acceptance(self, "%s")'
                          % relative, bootstrap_tests, relative)

    def test_msbwtgen_py_diff_within_accepted_closed_set(self):
        # M3-R64-W6 (audit A-2): live enforcement - the current MSBWTGen.py
        # deviation must be exactly the accepted closed set; any other line
        # fails here.
        assert_source_within_acceptance(self, "MUS/MSBWTGen.py")

    def test_util_py_diff_within_accepted_closed_set(self):
        # M3-R64-W6 (audit A-2): live enforcement - see above.
        assert_source_within_acceptance(self, "MUS/util.py")

    def test_acceptance_checker_rejects_unauthorized_drift(self):
        # Hostile regression (M3-R64-W6; hardened by M3-SOL-R1): prove the
        # acceptance helper enforces EXACT accepted identity using throwaway
        # copies of the real modern2 tree (Modern2 production source is
        # untouched).  The former set-membership guard accepted duplicated,
        # relocated or reordered allowlisted lines; the pinned-digest guard
        # must reject every one of those transformations.
        import shutil
        import tempfile

        import modern2_source_acceptance as acceptance

        class StrictCase(object):
            """Minimal stand-in exposing the attrs/helper contract used by
            assert_source_within_acceptance()."""

            def __init__(self, repository_root, package):
                self.REPOSITORY_ROOT = Path(repository_root)
                self.PACKAGE = Path(package)

            def assertFalse(self, expr, msg=None):
                if expr:
                    raise AssertionError(msg or "expected false")

            def assertEqual(self, left, right, msg=None):
                if left != right:
                    raise AssertionError(msg or "expected equal")

        rel_path = "MUS/util.py"
        expected_digest = acceptance.ACCEPTED_SHA256[rel_path]
        # Frozen original (same resolution as the guard's own fallback:
        # the root-level MUS tree is the frozen oracle checkout).
        frozen_src = REPOSITORY_ROOT / "MUS" / "util.py"
        self.assertTrue(frozen_src.exists())
        original_lines = ((PACKAGE / rel_path).read_bytes()
                          .replace(b"\r\n", b"\n").decode("utf-8")
                          .split("\n"))
        if original_lines and original_lines[-1] == "":
            original_lines.pop()

        # An allowlisted code line that really occurs in the accepted file.
        dup_line = next(line for line in original_lines
                        if line.strip() == "os.fsync(fp.fileno())")
        self.assertIn(dup_line, acceptance.ACCEPTED_ADDED_MUS_UTIL_PY)

        mutations = {
            "unapproved-add": ["AUDIT_MUTATION_UNAPPROVED = 1"]
                              + original_lines,
            "deletion": original_lines[1:],
            "modification": [original_lines[0] + "  # unauthorized tweak"]
                             + original_lines[1:],
            "duplicate-allowlisted-line": ([dup_line] + original_lines),
            "relocate-allowlisted-line": (original_lines[1:]
                                           + [original_lines[0]]),
            "reorder": ([original_lines[0], original_lines[2],
                         original_lines[1]] + original_lines[3:]),
        }

        def build(modern_bytes):
            work = Path(tempfile.mkdtemp(prefix="m3solr1-oracle-"))
            self.addCleanup(shutil.rmtree, str(work), True)
            frozen_root = work / "repo"
            pkg_root = work / "pkg"
            (pkg_root / "MUS").mkdir(parents=True)
            frozen_dir = frozen_root / "MUS"
            frozen_dir.mkdir(parents=True)
            if frozen_src.exists():
                shutil.copyfile(frozen_src, frozen_dir / "util.py")
            (pkg_root / rel_path).write_bytes(modern_bytes)
            return StrictCase(frozen_root, pkg_root)

        def lines_to_bytes(lines):
            return "".join(line + "\n" for line in lines).encode("utf-8")

        # The unmodified real accepted state passes BOTH gates.
        assert_source_within_acceptance(
            build(lines_to_bytes(original_lines)), rel_path)

        # CRLF re-encoding of the identical content must still pass: the
        # pin is deliberately checkout-line-ending independent.
        assert_source_within_acceptance(
            build(("\r\n".join(original_lines) + "\r\n").encode("utf-8")),
            rel_path)

        # Every hostile transformation must fail.
        for label, mutated in mutations.items():
            with self.assertRaises(AssertionError, msg=label):
                assert_source_within_acceptance(
                    build(lines_to_bytes(mutated)), rel_path)

        # Direct primitive check: digest mismatch is detected even when the
        # caller only has raw bytes (no files involved).
        with self.assertRaises(AssertionError):
            acceptance.assert_exact_accepted_content(
                self, b"tampered\n", expected_digest, rel_path)
        acceptance.assert_exact_accepted_content(
            self, lines_to_bytes(original_lines), expected_digest, rel_path)

    def test_pyx_files_carry_language_level_2(self):
        for name in MIGRATED_MODULES:
            text = (MUSCYN / (name + ".pyx")).read_text(encoding="utf-8")
            self.assertIn("#cython: language_level=2", text, name)
            self.assertLess(text.index("#cython: language_level=2"), 10, name)

    def test_generated_c_is_cython_3_0_12(self):
        for name in MIGRATED_MODULES:
            banner = (MUSCYN / (name + ".c")).read_text(encoding="utf-8", errors="replace").splitlines()[0]
            self.assertIn("Generated by Cython 3.0.12", banner, name)

    def test_no_python3_only_runtime_syntax(self):
        scan_patterns = [
            (re.compile(r"\bpathlib\b"), "pathlib"),
            (re.compile(r"\byield from\b"), "yield from"),
            (re.compile(r"\bnonlocal\b"), "nonlocal"),
            (re.compile(r"\basync\s+def\b"), "async def"),
            (re.compile(r"from __future__ import annotations"), "future annotations"),
            (re.compile(r"open\([^)]*encoding="), "open encoding kwarg"),
        ]
        for path in sorted((PACKAGE / "MUS").glob("*.py")) + sorted((MUSCYN).glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for pattern, label in scan_patterns:
                self.assertIsNone(pattern.search(text), "{} in {}: {}".format(label, path.name, pattern))


class GeneratedCTracebackTests(unittest.TestCase):
    def test_generated_c_uses_relative_pyx_paths(self):
        for name in ("BasicBWT", "MultiStringBWTCython"):
            text = (MUSCYN / (name + ".c")).read_text(encoding="utf-8", errors="replace")
            self.assertIn('"MUSCython/%s.pyx"' % name, text)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(PACKAGE / "evidence" / "bootstrap-milestone1.json")
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], CYTHON_PIN)
        self.assertEqual(evidence["build"]["cython"], CYTHON_PIN)
        self.assertEqual(evidence["build"]["modules"], 8)
        self.assertEqual(evidence["slice"], {
            "build_match": True, "case": "uniform-multifile",
            "pre_match": True, "status": "ok"})

    def test_evidence_matches_golden_primary_hash(self):
        golden_build = (
            REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0" /
            "uniform-multifile" / "py27-late-05a7d6d83862" / "pyx-historical-cython" /
            "build" / "manifest.json")
        manifest = load_json(golden_build)
        primary = next(entry for entry in manifest["artifacts"] if entry["path"] == "msbwt.npy")
        self.assertEqual(primary["sha256"], MSBWT_SHA256)
        self.assertEqual(primary["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(primary["npy"]["shape"], [48])
        self.assertEqual(
            primary["npy"]["payload_sha256"],
            "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e")


if __name__ == "__main__":
    unittest.main()
