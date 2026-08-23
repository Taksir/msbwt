"""Read-only host-side regression tests for msbwt-modern2 milestone 10
(remaining public surface audit + closure).

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 public surface inventory, the convert/
CompressToRLE migration, the committed convert oracle golden, the stub
classification policy, and the milestone evidence without requiring the WSL
Python-2 environment.  The runtime validation lives in
packages/msbwt-modern2/validate/public-surface-milestone10.sh (WSL).
"""

import ast
import json
import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
from modern2_source_acceptance import assert_source_within_acceptance

MUS = PACKAGE / "MUS"
MUSCYN = PACKAGE / "MUSCython"
FROZEN = REPOSITORY_ROOT / "MUS"
FROZEN_CYN = REPOSITORY_ROOT / "MUSCython"
GOLDENS = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
CONVERT_GOLDEN = GOLDENS / "convert-milestone10"
DOCS = REPOSITORY_ROOT / "docs" / "modernization"
FROZEN_MANIFEST = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "frozen-source.sha256"

CYTHON_PIN = "3.0.12"
FROZEN_COMPRESS_TO_RLE_PYX = "1ef40aba3d9551ec5e3b656f30cbdc01f1e9c0e750b0830b7bd928d329ff8ab2"
FROZEN_CLI_PY = "5265558e9a04e41eab33493a4fed440e2c640c1198b99ae493810647d1b23189"
# M3-R64 closure: platform-independent pins over the committed LF content.
FROZEN_COMPRESS_TO_RLE_PYX_LF = "c54981f7915a95fbf6150385d5d21bc136ad0af11a37f12e5a493783130f5722"
FROZEN_CLI_PY_LF = "e9799313bd9233d5f9973a7606c0c6b7d0db549156899f93162e112bd1a3c845"
FROZEN_MULTISTRINGBWT_PY = "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0"
UNIFORM_CONVERT_SHA256 = "121ffb41838b696ed0c543345794f8dad36525373e4d7427de8a45d298ec009b"
NONUNIFORM_CONVERT_SHA256 = "5fb45204712b0177803104d27a8170f11c159ed4f666c1b2521bc8fc614c7517"
UNIFORM_PAYLOAD_SHA256 = "6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb"
NONUNIFORM_PAYLOAD_SHA256 = "5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363"

# Public CLI subcommands exposed by the modern2 CommandLineInterface parser
# (frozen parser preserved; modern2 differs only by the documented
# `numProcs = 1` merge fix, COMPATIBILITY.md entry 2).
CLI_SUBCOMMANDS = {
    "cffq": "MultiStringBWT.createMSBWT(Comp)?FromFastq / Multimerge.createMSBWTFromFastq",
    "pp": "MultiStringBWT.preprocessFastqs / Multimerge.preprocessFastqs",
    "cfpp": "MSBWTGenCython.createMsbwtFromSeqs / MSBWTCompGenCython.createMsbwtFromSeqs / Multimerge.interleaveLevelMerge",
    "merge": "GenericMerge.mergeTwoMSBWTs",
    "query": "MultiStringBWT.loadBWT + findIndicesOfStr + recoverString",
    "massquery": "MultiStringBWT.loadBWT + countOccurrencesOfSeq + reverseComplement",
    "compress": "MSBWTGen.compressBWT (pure Python)",
    "decompress": "MSBWTGen.decompressBWT (pure Python)",
    "convert": "CompressToRLE.compressInput (migrated Cython, milestone 10)",
}

# Documented public import/export matrix (BEHAVIORAL_SURFACE.md symbol index).
MODULE_SYMBOLS = {
    "MUS/CommandLineInterface.py": ["initLogger", "mainRun"],
    "MUS/MSBWTGen.py": [
        "bwtInitialInsertionsPoolCall", "bwtPartialInsertPoolCall", "debugDump",
        "createFromSeqs", "iterateCreateFromSeqs", "writeSeqsToFiles",
        "mergeNewMSBWTPoolCall", "mergeNewMSBWT", "compressBWT",
        "compressBWTPoolProcess", "decompressBWT", "decompressBWTPoolProcess",
        "clearAuxiliaryData"],
    "MUS/MultiStringBWT.py": [
        "BasicBWT", "MultiStringBWT", "CompressedMSBWT", "loadBWT",
        "createMSBWTFromSeqs", "createMSBWTFromFastq", "createMSBWTFromBam",
        "customiter", "preprocessFastqs", "preprocessBams", "mergeNewSeqs",
        "compareKmerProfiles", "parseProfileLine",
        "interactiveTranscriptConstruction", "reverseComplement"],
    "MUS/TranscriptBuilder.py": ["PathNode", "PathEdge", "Assembler"],
    "MUS/util.py": [
        "readableFastqFile", "readableNpyFile", "writableNpyFile",
        "newDirectory", "existingDirectory", "newOrExistingDirectory",
        "validKmer", "fastaIterator", "fastqIterator", "VERSION", "PKG_VERSION"],
    "MUSCython/AlignmentUtil.pyx": ["fullAlign", "fullED_score", "fullED_minimize", "fullAlign_noGO", "alignChanges"],
    "MUSCython/BasicBWT.pyx": ["BasicBWT"],
    "MUSCython/ByteBWTCython.pyx": ["ByteBWT"],
    "MUSCython/CompressToRLE.pyx": ["compressInput"],
    "MUSCython/GenericMerge.pyx": ["mergeTwoMSBWTs", "interleaveTwoBwts"],
    "MUSCython/LZW_BWTCython.pyx": ["LZW_BWT"],
    "MUSCython/MSBWTCompGenCython.pyx": ["createMsbwtFromSeqs", "iterateMsbwtCreate"],
    "MUSCython/MSBWTGenCython.pyx": [
        "createMsbwtFromSeqs", "iterateMsbwtCreate", "compressBWT",
        "compressBWTPoolProcess", "decompressBWT", "decompressBWTPoolProcess",
        "clearAuxiliaryData", "writeSeqsToFiles", "createFromSeqs",
        "iterateCreateFromSeqs", "bwtInitialInsertionsPoolCall",
        "bwtPartialInsertPoolCall", "debugDump", "testThreading", "runFunc"],
    "MUSCython/MultiStringBWTCython.pyx": [
        "loadBWT", "createMSBWTFromSeqs", "createMSBWTCompFromSeqs",
        "createMSBWTFromFastq", "createMSBWTCompFromFastq", "createMSBWTFromBam",
        "createMSBWTFromFasta", "customiter", "preprocessFastqs",
        "preprocessBams", "preprocessFastas", "mergeSubSorts",
        "cleanupTemporaryFiles", "compareKmerProfiles", "parseProfileLine",
        "reverseComplement"],
    "MUSCython/MultimergeCython.pyx": [
        "createMSBWTFromSeqs", "preprocessSeqs", "createMSBWTFromFasta",
        "preprocessFasta", "createMSBWTFromFastq", "preprocessFastqs",
        "mergeTwoMSBWTs", "mergeUsingInterleave", "fastaIterator",
        "fastqIterator", "formatSeqsForMerge", "memoryBWT",
        "interleaveLevelMerge", "levelIterator", "buildViaMerge256",
        "rangeIterator", "rangeSolve_thread"],
    "MUSCython/RLE_BWTCython.pyx": ["RLE_BWT"],
}

# Stub policy: the only remaining stub, with its documented classification.
DEAD_STUBS = {
    "MUSCython/LCPGen.py": ["lcpGenerator", "linearLcpGenerator"],
}


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as source:
        return json.load(source)


def sha256_file(path):
    digest = __import__("hashlib").sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def module_symbols(path):
    """Extract def/class/constant names without parsing (the sources are
    Python-2 files, so ast.parse is unsafe under host Python 3).  Every
    identifier on a def/cpdef/class header line counts (cpdef lines carry
    C return types before the function name)."""
    text = Path(path).read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:def|cpdef|class|cdef\s+class)\s+", stripped):
            names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped))
    names.update(re.findall(r"^([A-Z][A-Z0-9_]*)\s*=", text, re.MULTILINE))
    return names


def unified_diff_lines(frozen_path, modern_path):
    frozen_text = Path(frozen_path).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    modern_text = Path(modern_path).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    frozen_lines = frozen_text.splitlines()
    modern_lines = modern_text.splitlines()
    # simple line diff without importing difflib classes repeatedly
    import difflib
    diff = list(difflib.unified_diff(frozen_lines, modern_lines, lineterm=""))
    added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
    return added, removed


class CliInventoryTests(unittest.TestCase):
    def test_all_public_subcommands_present(self):
        text = (PACKAGE / "MUS" / "CommandLineInterface.py").read_text(encoding="utf-8")
        for name in CLI_SUBCOMMANDS:
            self.assertIn("sp.add_parser('%s'" % name, text, name)

    def test_cli_dispatch_wiring(self):
        text = (PACKAGE / "MUS" / "CommandLineInterface.py").read_text(encoding="utf-8")
        # convert must dispatch to the migrated CompressToRLE
        self.assertIn("CompressToRLE.compressInput(args.inputTextFN, args.dstDir)", text)
        # compress/decompress must dispatch to the pure-Python MSBWTGen paths
        self.assertIn("MSBWTGen.compressBWT(args.srcDir", text)
        self.assertIn("MSBWTGen.decompressBWT(args.srcDir", text)
        # massquery wiring
        self.assertIn("msbwt.countOccurrencesOfSeq(kmer)", text)
        self.assertIn("MultiStringBWT.reverseComplement(kmer)", text)
        # merge dispatch
        self.assertIn("GenericMerge.mergeTwoMSBWTs", text)

    def test_frozen_cli_untouched(self):
        # platform-independent: hashes the committed LF content
        from frozen_source_digest import lf_sha256_file
        self.assertEqual(lf_sha256_file(FROZEN / "CommandLineInterface.py"),
                         FROZEN_CLI_PY_LF)

    def test_modern2_cli_diff_is_only_the_numprocs_fix(self):
        added, removed = unified_diff_lines(
            FROZEN / "CommandLineInterface.py",
            PACKAGE / "MUS" / "CommandLineInterface.py")
        # M3-R64-W5 rebaseline: numprocs fix plus W-BINARY-IO CSV open.
        assert_source_within_acceptance(self, "MUS/CommandLineInterface.py")
        self.assertIn("        numProcs = 1", added)


class ImportExportMatrixTests(unittest.TestCase):
    def test_documented_symbols_exist_in_sources(self):
        for relative, symbols in MODULE_SYMBOLS.items():
            path = PACKAGE / relative
            self.assertTrue(path.exists(), relative)
            present = module_symbols(path)
            missing = [name for name in symbols if name not in present]
            self.assertEqual(missing, [], relative)

    def test_every_modern2_pyx_carries_language_level_2(self):
        for relative in MODULE_SYMBOLS:
            if not relative.endswith(".pyx"):
                continue
            text = (PACKAGE / relative).read_text(encoding="utf-8")
            self.assertIn("#cython: language_level=2", text, relative)

    def test_migrated_modules_have_generated_c_from_cython_3_0_12(self):
        for relative in MODULE_SYMBOLS:
            if not relative.endswith(".pyx"):
                continue
            c_path = PACKAGE / (relative[:-4] + ".c")
            self.assertTrue(c_path.exists(), str(c_path))
            banner = c_path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            self.assertIn("Generated by Cython 3.0.12", banner, relative)


class CompressToRleMigrationTests(unittest.TestCase):
    def test_frozen_pyx_hash(self):
        # platform-independent: hashes the committed LF content
        from frozen_source_digest import lf_sha256_file
        self.assertEqual(
            lf_sha256_file(FROZEN_CYN / "CompressToRLE.pyx"),
            FROZEN_COMPRESS_TO_RLE_PYX_LF)

    def test_modern2_pyx_diff_is_exactly_language_level(self):
        added, removed = unified_diff_lines(
            FROZEN_CYN / "CompressToRLE.pyx",
            MUSCYN / "CompressToRLE.pyx")
        # M3-R64-W5 rebaseline: language_level header only (no drift).
        assert_source_within_acceptance(self, "MUSCython/CompressToRLE.pyx")
        self.assertIn("#cython: language_level=2", added)

    def test_stub_removed(self):
        self.assertFalse((MUSCYN / "CompressToRLE.py").exists())
        self.assertFalse((MUSCYN / "CompressToRLE.pyc").exists())

    def test_setup_builds_compress_to_rle(self):
        text = (PACKAGE / "setup.py").read_text(encoding="utf-8")
        self.assertIn("'CompressToRLE'", text)


class ConvertOracleGoldenTests(unittest.TestCase):
    def test_golden_layout(self):
        expected = [
            "convert-evidence.json",
            "determinism-run-a-run-b.json",
            "profile-provenance.json",
            "regeneration.json",
            "relationship-convert-vs-posthoc.json",
            "relationship-reader.json",
            "inputs/uniform.txt",
            "inputs/nonuniform.txt",
            "uniform/secondary-regenerated-source/manifest.json",
            "uniform/secondary-regenerated-source/artifacts/comp_msbwt.npy",
            "nonuniform/secondary-regenerated-source/manifest.json",
            "nonuniform/secondary-regenerated-source/artifacts/comp_msbwt.npy",
        ]
        for relative in expected:
            self.assertTrue((CONVERT_GOLDEN / relative).exists(), relative)

    def test_artifact_bytes(self):
        uniform = CONVERT_GOLDEN / "uniform" / "secondary-regenerated-source" / "artifacts" / "comp_msbwt.npy"
        nonuniform = CONVERT_GOLDEN / "nonuniform" / "secondary-regenerated-source" / "artifacts" / "comp_msbwt.npy"
        self.assertEqual(sha256_file(uniform), UNIFORM_CONVERT_SHA256)
        self.assertEqual(sha256_file(nonuniform), NONUNIFORM_CONVERT_SHA256)
        for path, payload in ((uniform, UNIFORM_PAYLOAD_SHA256), (nonuniform, NONUNIFORM_PAYLOAD_SHA256)):
            data = path.read_bytes()
            self.assertEqual(data[:6], b"\x93NUMPY")
            header_len = data[8] | (data[9] << 8)
            self.assertEqual(header_len, 86)
            header = data[10:10 + header_len]
            self.assertIn(b"'descr': '|u1'", header)
            self.assertEqual(__import__("hashlib").sha256(data[10 + header_len:]).hexdigest(), payload)

    def test_evidence_record_consistency(self):
        evidence = load_json(CONVERT_GOLDEN / "convert-evidence.json")
        self.assertEqual(evidence["format"], "msbwt-legacy-convert-milestone10-raw-v1")
        self.assertEqual(
            len({evidence["runs"]["uniform"][k] for k in ("run-a", "run-b", "stdin")}), 1)
        self.assertEqual(
            len({evidence["runs"]["nonuniform"][k] for k in ("run-a", "run-b")}), 1)
        self.assertEqual(evidence["runs"]["uniform"]["run-a"], UNIFORM_CONVERT_SHA256)
        self.assertEqual(evidence["runs"]["nonuniform"]["run-a"], NONUNIFORM_CONVERT_SHA256)
        self.assertEqual(evidence["uniform"]["sha256"], UNIFORM_CONVERT_SHA256)
        self.assertEqual(evidence["nonuniform"]["sha256"], NONUNIFORM_CONVERT_SHA256)
        self.assertEqual(evidence["uniform"]["npy"]["shape"], [22])
        self.assertEqual(evidence["nonuniform"]["npy"]["shape"], [16])
        self.assertEqual(evidence["uniform"]["npy"]["payload_offset"], 96)
        self.assertEqual(evidence["nonuniform"]["npy"]["payload_offset"], 96)

    def test_relationship_records(self):
        relationship = load_json(CONVERT_GOLDEN / "relationship-convert-vs-posthoc.json")
        self.assertTrue(relationship["encoding_identical_to_posthoc_compress"])
        self.assertEqual(relationship["uniform_converted_payload_sha256"], UNIFORM_PAYLOAD_SHA256)
        self.assertEqual(relationship["nonuniform_converted_payload_sha256"], NONUNIFORM_PAYLOAD_SHA256)
        reader = load_json(CONVERT_GOLDEN / "relationship-reader.json")
        for key in ("reader_u", "reader_n"):
            self.assertTrue(reader[key]["queries_match"], key)
            self.assertTrue(reader[key]["recovery_matches"], key)
        self.assertEqual(reader["reader_u"]["reader_class"], "RLE_BWT")
        self.assertEqual(reader["reader_u"]["total_size"], 48)
        self.assertEqual(reader["reader_n"]["total_size"], 30)

    def test_regeneration_record(self):
        regen = load_json(CONVERT_GOLDEN / "regeneration.json")
        self.assertEqual(regen["oracle_class"], "secondary-regenerated-source")
        self.assertEqual(regen["cython_version"], "0.29.36")
        self.assertEqual(regen["pyx_sha256"], FROZEN_COMPRESS_TO_RLE_PYX)
        self.assertTrue(regen["regenerated_c_different_from_committed"])

    def test_harness_script_committed(self):
        harness = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "convert_oracle_milestone10.sh"
        self.assertTrue(harness.exists())
        text = harness.read_text(encoding="utf-8")
        self.assertIn("convert_oracle_milestone10.sh", text)
        self.assertIn("UNIFORM_BWT=", text)
        self.assertIn("reader_smoke.py", text)


class LcpGenClassificationTests(unittest.TestCase):
    def test_lcpgen_stub_classified_dead_private(self):
        text = (MUSCYN / "LCPGen.py").read_text(encoding="utf-8")
        self.assertIn("DEAD/PRIVATE", text)
        self.assertIn("NotImplementedError", text)

    def test_lcpgen_unreachable_from_public_paths(self):
        # no CLI dispatch, no importer anywhere in MUS/MUSCython (frozen or
        # modern2) other than the stub itself and the frozen setup.py
        cli_text = (PACKAGE / "MUS" / "CommandLineInterface.py").read_text(encoding="utf-8")
        self.assertNotIn("LCPGen", cli_text)
        for root in (MUS, MUSCYN, FROZEN, FROZEN_CYN):
            for path in sorted(root.glob("*.py")) + sorted(root.glob("*.pyx")):
                if path.name in ("LCPGen.py", "LCPGen.pyx"):
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("LCPGen", text, str(path))

    def test_no_other_stubs_remain(self):
        # every non-LCPGen module in the modern2 package must be a real
        # implementation (pyx + generated C, or pure python)
        for relative in MODULE_SYMBOLS:
            self.assertTrue((PACKAGE / relative).exists(), relative)
        stub_names = [p.name for p in sorted(MUSCYN.glob("*.py"))
                      if p.name != "__init__.py"]
        self.assertEqual(stub_names, ["LCPGen.py"])


class CompressBwtClassificationTests(unittest.TestCase):
    def test_pyx_compressbwt_present_but_not_on_cli_path(self):
        pyx_text = (MUSCYN / "MSBWTGenCython.pyx").read_text(encoding="utf-8")
        self.assertIn("def compressBWT(", pyx_text)
        cli_text = (PACKAGE / "MUS" / "CommandLineInterface.py").read_text(encoding="utf-8")
        self.assertNotIn("MSBWTGenCython.compressBWT", cli_text)
        # the public `compress` command uses the pure-Python implementation
        self.assertIn("MSBWTGen.compressBWT(", cli_text)

    def test_pyx_compressbwt_has_no_importers(self):
        # the Cython compressBWT is never referenced outside its own module;
        # the CLI references only the pure-Python MUS.MSBWTGen.compressBWT
        for root in (MUS, MUSCYN, FROZEN, FROZEN_CYN):
            for path in sorted(root.glob("*.py")) + sorted(root.glob("*.pyx")):
                if path.name == "MSBWTGenCython.pyx":
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("MSBWTGenCython.compressBWT", text, str(path))
        cli_text = (PACKAGE / "MUS" / "CommandLineInterface.py").read_text(encoding="utf-8")
        self.assertIn("MSBWTGen.compressBWT(", cli_text)


class MilestoneDocumentationTests(unittest.TestCase):
    def test_milestone_doc_exists(self):
        doc = DOCS / "MODERN2_MILESTONE10_PUBLIC_SURFACE.md"
        self.assertTrue(doc.exists())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("convert", text)
        self.assertIn("CompressToRLE", text)
        self.assertIn("LCPGen", text)
        self.assertIn("massquery", text)

    def test_legacy_bug_tracker_exists_with_proven_entries(self):
        tracker = DOCS / "MODERN2_LEGACY_BUG_TRACKER.md"
        self.assertTrue(tracker.exists())
        text = tracker.read_text(encoding="utf-8")
        for required in (
                "float64", "refFM", "weighted-bincount", "numProcs",
                "GenericMerge", "slice indices", "decompress"):
            self.assertIn(required, text)

    def test_evidence_record_consistent(self):
        evidence = load_json(PACKAGE / "evidence" / "public-surface-milestone10.json")
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], CYTHON_PIN)
        self.assertEqual(evidence["build"]["modules"], 11)

    def test_convert_evidence_record_committed(self):
        evidence = load_json(PACKAGE / "evidence" / "public-surface-milestone10.json")
        self.assertEqual(evidence["convert"]["run-a_uniform"], UNIFORM_CONVERT_SHA256)
        self.assertEqual(evidence["convert"]["run-a_nonuniform"], NONUNIFORM_CONVERT_SHA256)
        self.assertTrue(evidence["convert"]["uniform_matches_oracle"])
        self.assertTrue(evidence["convert"]["nonuniform_matches_oracle"])
        self.assertEqual(evidence["convert"]["uniform_payload"], UNIFORM_PAYLOAD_SHA256)
        self.assertEqual(evidence["convert"]["nonuniform_payload"], NONUNIFORM_PAYLOAD_SHA256)


if __name__ == "__main__":
    unittest.main()
