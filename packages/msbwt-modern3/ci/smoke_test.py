"""Smoke test run against an *installed* pymsbwt wheel (see .github/workflows/release.yml).

Builds a tiny index through the real CLI and checks counts against a naive count,
a gzip round trip, RLE compress/decompress, and the console scripts.
"""
import gzip
import importlib.metadata
import os
import random
import shutil
import subprocess
import sys
import tempfile


def run(*args):
    res = subprocess.run(list(args), capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit("FAILED: %s\n%s" % (" ".join(args), res.stderr[-1500:]))
    return res.stdout


def run_fail(expected, *args):
    """Run a command that must fail fast with ``expected`` in stderr (no hang)."""
    try:
        res = subprocess.run(list(args), capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise SystemExit("HUNG: %s" % " ".join(args))
    if res.returncode == 0 or expected not in res.stderr:
        raise SystemExit("EXPECTED FAILURE %r: %s\nrc=%d\n%s"
                         % (expected, " ".join(args), res.returncode, res.stderr[-1500:]))


def naive_count(reads, kmer):
    return sum(r[i:i + len(kmer)] == kmer for r in reads for i in range(len(r) - len(kmer) + 1))


def main():
    version = importlib.metadata.version("pymsbwt")
    printed = run("msbwt", "-V")
    assert version in printed.split(), (
        "msbwt -V printed %r but the installed package version is %r (msbwt resolved to %r)"
        % (printed, version, shutil.which("msbwt")))
    for script in ("msbwt-lcp", "msbwt-bwt-tags", "msbwt-remove-sources", "msbwt-quality-sidecar",
                   "msbwt-retrofit-read-provenance", "msbwt-benchmark-index"):
        run(script, "--help")
    run("msbwt-lcp", "repeats", "--help")

    random.seed(7)
    reads = ["".join(random.choice("ACGT") for _ in range(24)) for _ in range(60)]
    text = "".join("@r%d\n%s\n+\n%s\n" % (i, s, "I" * len(s)) for i, s in enumerate(reads))
    with tempfile.TemporaryDirectory() as tmp:
        plain, gz = os.path.join(tmp, "r.fastq"), os.path.join(tmp, "r.fastq.gz")
        with open(plain, "w", newline="\n") as fp:
            fp.write(text)
        with gzip.open(gz, "wt", newline="\n") as fp:
            fp.write(text)
        a, b = os.path.join(tmp, "idx_plain"), os.path.join(tmp, "idx_gz")
        run("msbwt", "cffq", "-p", "1", "-u", a, plain)
        run("msbwt", "cffq", "-p", "1", "-u", b, gz)
        with open(os.path.join(a, "msbwt.npy"), "rb") as f1, open(os.path.join(b, "msbwt.npy"), "rb") as f2:
            assert f1.read() == f2.read(), "gzip and plain input built different indexes"
        for kmer in ("ACG", "GATTA", reads[0][:8], "TTTTTT"):
            got = int(run("msbwt", "query", a, kmer).strip().splitlines()[-1])
            assert got == naive_count(reads, kmer), (kmer, got, naive_count(reads, kmer))
        rle, back = os.path.join(tmp, "idx_rle"), os.path.join(tmp, "idx_back")
        run("msbwt", "compress", "-p", "1", a, rle)
        run("msbwt", "decompress", "-p", "1", rle, back)
        with open(os.path.join(a, "msbwt.npy"), "rb") as f1, open(os.path.join(back, "msbwt.npy"), "rb") as f2:
            assert f1.read() == f2.read(), "compress/decompress round trip changed the BWT"
        assert int(run("msbwt", "query", rle, "ACG").strip().splitlines()[-1]) == naive_count(reads, "ACG")
        # M3-S2-INPUT: soft-masked reads are rejected in both construction modes
        masked = os.path.join(tmp, "masked.fastq")
        with open(masked, "w", newline="\n") as fp:
            fp.write(text + "@m\n%s\n+\n%s\n" % (reads[0].lower(), "I" * len(reads[0])))
        run_fail("invalid symbol", "msbwt", "cffq", "-p", "1", "-u", os.path.join(tmp, "m_u"), masked)
        run_fail("invalid symbol", "msbwt", "cffq", "-p", "1", os.path.join(tmp, "m_nu"), masked)
    print("pymsbwt %s smoke test passed on %s" % (version, sys.platform))


if __name__ == "__main__":
    main()
