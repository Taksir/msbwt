"""Read-only host-side release-candidate tests for msbwt-modern2.

These tests run under the host Python 3 (like the other compat tests) and
protect the release packaging surface without requiring the WSL Python-2
environment:

- distribution metadata (setup.py) and version consistency with MUS.util;
- required package content (MUS sources, MUSCython .pyx/.pxd/.c, CLI
  script, LICENSE/AUTHORS/README);
- MANIFEST.in coverage and the no-unintended-content rule (tests,
  evidence, environment, validate are NOT packaged);
- README bug-list consistency with the legacy bug tracker;
- release evidence JSON schema (when the evidence file is committed);
- wheel/sdist content audits (only when the locally built artifacts are
  present under the gitignored dist/ directory).

The runtime fresh-install validation lives in
packages/msbwt-modern2/validate/release-candidate.sh (WSL).
"""

import json
import re
import unittest
import zipfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
MUS = PACKAGE / "MUS"
MUSCYN = PACKAGE / "MUSCython"
DOCS = REPOSITORY_ROOT / "docs" / "modernization"
BUG_TRACKER = DOCS / "MODERN2_LEGACY_BUG_TRACKER.md"
PACKAGE_README = PACKAGE / "README.md"
EVIDENCE = PACKAGE / "evidence" / "release-candidate.json"
DIST = PACKAGE / "dist"

EXPECTED_VERSION = "0.3.0"

EXTENSION_NAMES = [
    "AlignmentUtil", "BasicBWT", "ByteBWTCython", "CompressToRLE",
    "GenericMerge", "MSBWTCompGenCython", "MSBWTGenCython",
    "MultiStringBWTCython", "MultimergeCython", "RLE_BWTCython",
    "LZW_BWTCython",
]

# Proven tracker entries: (status category, distinctive README phrase)
# Order matches MODERN2_LEGACY_BUG_TRACKER.md rows 1-8.
TRACKER_EXPECTATIONS = [
    ("fixed", "slice indices must be integers"),
    ("fixed", "multi-block decompression"),
    ("fixed", "refFM"),
    ("fixed", "getFullFMAtIndex"),
    ("fixed", "numProcs"),
    ("generated-code defect", "GenericMerge"),
    ("documented legacy quirk", "first newline"),
    ("documented legacy quirk", "cannot concatenate"),
]


class TestDistributionMetadata(unittest.TestCase):
    def test_setup_py_declares_expected_metadata(self):
        text = (PACKAGE / "setup.py").read_text(encoding="utf-8")
        self.assertIn("name='msbwt-modern2'", text)
        self.assertIn("version=util.VERSION", text)
        self.assertIn("license='MIT'", text)
        self.assertIn("author='James Holt'", text)
        self.assertIn("scripts=['bin/msbwt']", text)
        self.assertIn("packages=['MUS', 'MUSCython']", text)
        self.assertIn("'BasicBWT.pxd'", text)
        self.assertIn("install_requires=['pysam', 'numpy']", text)
        self.assertIn("zip_safe=False", text)
        for name in EXTENSION_NAMES:
            self.assertIn("'%s'" % name, text)

    def test_version_matches_mus_util(self):
        text = (MUS / "util.py").read_text(encoding="utf-8")
        self.assertIn("VERSION = '%s'" % EXPECTED_VERSION, text)
        self.assertIn("PKG_VERSION = VERSION", text)

    def test_license_authors_present_and_consistent_with_root(self):
        for name in ("LICENSE", "AUTHORS"):
            pkg = (PACKAGE / name).read_bytes()
            root = (REPOSITORY_ROOT / name).read_bytes()
            self.assertEqual(pkg, root, name)


class TestRequiredPackageContent(unittest.TestCase):
    def test_mus_sources_present(self):
        for name in ("__init__.py", "CommandLineInterface.py", "MSBWTGen.py",
                     "MultiStringBWT.py", "TranscriptBuilder.py", "util.py"):
            self.assertTrue((MUS / name).is_file(), name)

    def test_muscython_sources_present(self):
        self.assertTrue((MUSCYN / "__init__.py").is_file())
        self.assertTrue((MUSCYN / "BasicBWT.pxd").is_file())
        self.assertTrue((MUSCYN / "LCPGen.py").is_file())
        for name in EXTENSION_NAMES:
            self.assertTrue((MUSCYN / (name + ".pyx")).is_file(), name + ".pyx")
            self.assertTrue((MUSCYN / (name + ".c")).is_file(), name + ".c")

    def test_cli_script_and_docs_present(self):
        self.assertTrue((PACKAGE / "bin" / "msbwt").is_file())
        self.assertTrue((PACKAGE / "MANIFEST.in").is_file())
        self.assertTrue((PACKAGE / "setup.py").is_file())
        self.assertTrue(PACKAGE_README.is_file())

    def test_manifest_in_covers_distribution_and_excludes_scratch(self):
        text = (PACKAGE / "MANIFEST.in").read_text(encoding="utf-8")
        for rule in ("include LICENSE", "include AUTHORS", "include README.md",
                     "include bin/msbwt",
                     "recursive-include MUS *.py",
                     "recursive-include MUSCython *.py *.pyx *.pxd *.c"):
            self.assertIn(rule, text)
        # nothing under tests/ evidence/ environment/ validate/ is packaged
        self.assertNotIn("tests", text)
        self.assertNotIn("evidence", text)
        self.assertNotIn("environment", text)
        self.assertNotIn("validate", text)


class TestReadmeBugListConsistency(unittest.TestCase):
    def test_readme_covers_every_proven_tracker_entry(self):
        readme = PACKAGE_README.read_text(encoding="utf-8")
        for status, phrase in TRACKER_EXPECTATIONS:
            self.assertIn(phrase, readme,
                          "README missing tracker phrase %r" % phrase)

    def test_tracker_rows_are_the_proven_eight(self):
        text = BUG_TRACKER.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines()
                if line.startswith("| ") and "|" in line[3:]
                and not line.startswith("| #")]
        rows = [line for line in rows if "|--|" not in line
                and "Status values" not in line]
        self.assertEqual(len(rows), 8, "tracker must contain exactly 8 rows")
        allowed = ("fixed", "generated-code defect", "documented legacy quirk",
                   "intentionally preserved")
        for row in rows:
            status_cell = row.split("|")[6]
            self.assertTrue(any(status_cell.strip().startswith(a)
                                for a in allowed), row)

    def test_readme_does_not_claim_unproven_features(self):
        readme = PACKAGE_README.read_text(encoding="utf-8")
        self.assertIn("**not** a Python 3 package", readme)
        self.assertIn("not published on a", readme)
        self.assertIn("no other platform is claimed", readme)


class TestReleaseEvidence(unittest.TestCase):
    def test_release_evidence_schema(self):
        if not EVIDENCE.is_file():
            self.skipTest("release-candidate.json not committed yet")
        data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        for key in ("format", "commit", "distribution", "version", "branch",
                    "reference_profile", "sdist", "wheel", "install_environments",
                    "cli_smoke", "workflow_hashes", "test_counts",
                    "frozen_verification", "q1_evidence", "release_blockers"):
            self.assertIn(key, data, key)
        profile = data["reference_profile"]
        for key in ("python", "cython", "numpy", "pysam", "compiler"):
            self.assertIn(key, profile, "reference_profile." + key)
        for artifact in ("sdist", "wheel"):
            for key in ("filename", "sha256", "size"):
                self.assertIn(key, data[artifact], artifact + "." + key)
        self.assertIsInstance(data["release_blockers"], list)
        self.assertEqual(data["release_blockers"], [])
        for env in data["install_environments"]:
            self.assertEqual(env["result"].startswith("ALL-PASS"), True, env["id"])


class TestBuiltArtifacts(unittest.TestCase):
    """Content audits of the locally built artifacts (present only when the
    release build was run; dist/ is gitignored and not part of the repo)."""

    def _artifacts(self):
        if not DIST.is_dir():
            return None
        files = sorted(DIST.glob("*.tar.gz")) + sorted(DIST.glob("*.whl"))
        if not files:
            return None
        return files

    def test_sdist_contains_required_sources(self):
        files = self._artifacts()
        if not files:
            self.skipTest("built artifacts not present in dist/")
        sdist = next((f for f in files if f.suffix == ".gz"), None)
        if sdist is None:
            self.skipTest("no sdist in dist/")
        import tarfile
        with tarfile.open(str(sdist), "r:gz") as tf:
            names = set(tf.getnames())
        prefix = "msbwt-modern2-0.3.0/"
        for rel in ("MUS/util.py", "MUS/MultiStringBWT.py",
                    "MUSCython/CompressToRLE.pyx", "MUSCython/CompressToRLE.c",
                    "MUSCython/BasicBWT.pxd", "bin/msbwt", "setup.py",
                    "MANIFEST.in", "LICENSE", "AUTHORS", "README.md",
                    "PKG-INFO"):
            self.assertIn(prefix + rel, names, rel)
        # every extension must ship .pyx and .c
        for name in EXTENSION_NAMES:
            self.assertIn(prefix + "MUSCython/%s.pyx" % name, names)
            self.assertIn(prefix + "MUSCython/%s.c" % name, names)
        # tests/evidence/environment must NOT be in the sdist
        for rel in names:
            if rel.startswith(prefix) and rel != prefix:
                tail = rel[len(prefix):]
                self.assertNotIn(tail.split("/", 1)[0],
                                 ("tests", "evidence", "environment",
                                  "validate"),
                                 rel)

    def test_wheel_contains_extensions_and_metadata(self):
        files = self._artifacts()
        if not files:
            self.skipTest("built artifacts not present in dist/")
        wheel = next((f for f in files if f.suffix == ".whl"), None)
        if wheel is None:
            self.skipTest("no wheel in dist/")
        with zipfile.ZipFile(str(wheel)) as zf:
            names = set(zf.namelist())
        self.assertIn("MUS/util.py", names)
        self.assertIn("MUSCython/LCPGen.py", names)
        self.assertIn("MUSCython/BasicBWT.pxd", names)
        for name in EXTENSION_NAMES:
            self.assertIn("MUSCython/%s.so" % name, names, name)
        self.assertTrue(any(n.startswith("msbwt_modern2-0.3.0.dist-info/")
                            for n in names))
        self.assertTrue(any(n.endswith(".data/scripts/msbwt") for n in names))
        # .pyx/.c sources are not shipped in the wheel
        self.assertFalse(any(n.endswith(".pyx") or n.endswith(".c")
                             for n in names))


if __name__ == "__main__":
    unittest.main()
