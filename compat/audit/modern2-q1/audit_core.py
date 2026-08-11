#!/usr/bin/env python3
"""Deterministic randomized corpus generator and independent MSBWT oracle for
the modern2 quality audit Q1.

This module is deliberately independent of both the frozen implementation and
the modern2 implementation.  It is pure standard-library Python (no NumPy) so
it runs identically on the host and inside WSL.

Responsibilities:

1. Corpus generation: a seeded, reproducible set of small/medium read
   collections covering the required categories (uniform, nonuniform,
   duplicates, all-identical, prefix/suffix sharing, many dollars, full
   alphabet, N-heavy, single-base, short, moderate, odd/even, mixed lengths,
   repeated motifs, reverse-complement pairs, lexicographically similar),
   plus deterministic per-case query sets.

2. Independent oracle computations on a numeric MSBWT payload:
   - rotation-sorted BWT construction (byte-exact for uniform inputs, where
     the historical ordering is uniquely determined);
   - symbol totals;
   - backward-search substring counts;
   - LF-mapping read recovery (multiset);
   - FM rank rows and char-at-position;
   - base-32 RLE payload decoding;
   - NPY v1 framing/payload extraction (handles Python-2 long literals).

3. Outcome classification A/B/C/D/E per the audit policy and the
   deterministic audit summary.

Seeds are recorded explicitly; every case is regenerable from
(seed, case index).  All outputs are JSON with sort_keys=True so identical
runs produce byte-identical artifacts.
"""

from __future__ import annotations

import ast
import gzip
import hashlib
import io
import json
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

SYMBOLS = "$ACGNT"
SYMBOL_ORDER = {symbol: index for index, symbol in enumerate(SYMBOLS)}
BASE_SYMBOLS = "ACGTN"
QUERY_SYMBOLS = "$ACGTN"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def deterministic_gzip_bytes(raw: bytes) -> bytes:
    """Deterministic gzip of exactly ``raw`` (mtime=0, fixed OS byte).

    Mirrors the committed synthetic-fixture gzip route: RFC 1952 OS field
    (offset 9) pinned to 255 (unknown); everything else produced by the
    local gzip implementation is byte-for-byte what ``gzip`` on the
    execution host will produce when processing the file.
    """
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer,
                       compresslevel=9, mtime=0) as handle:
        handle.write(raw)
    encoded = bytearray(buffer.getvalue())
    encoded[9] = 255
    return bytes(encoded)


# ---------------------------------------------------------------------------
# Corpus generation
# ---------------------------------------------------------------------------

CATEGORY_ORDER = [
    "uniform-reads",
    "nonuniform-reads",
    "duplicates",
    "all-identical",
    "prefix-sharing",
    "suffix-sharing",
    "many-dollars",
    "full-alphabet",
    "n-heavy",
    "single-base",
    "short-reads",
    "moderate-reads",
    "odd-length",
    "even-length",
    "mixed-length",
    "repeated-motifs",
    "revcomp-pairs",
    "lexicographic-similar",
]


def _uniform_mode(category: str) -> bool:
    return category in {
        "uniform-reads", "all-identical", "single-base",
        "odd-length", "even-length",
    }


def _small_params(category: str, rng: random.Random) -> Dict[str, Any]:
    """Pick (read count, length range) for a small case of this category."""
    if category == "uniform-reads":
        return {"count": rng.randint(3, 12), "length": rng.randint(2, 12)}
    if category == "nonuniform-reads":
        return {"count": rng.randint(3, 10), "lengths": (1, 16)}
    if category == "duplicates":
        return {"count": rng.randint(4, 12), "length": rng.randint(2, 10)}
    if category == "all-identical":
        return {"count": rng.randint(2, 10), "length": rng.randint(1, 12)}
    if category == "prefix-sharing":
        return {"count": rng.randint(3, 10), "lengths": (2, 14)}
    if category == "suffix-sharing":
        return {"count": rng.randint(3, 10), "lengths": (2, 14)}
    if category == "many-dollars":
        return {"count": rng.randint(14, 26), "lengths": (1, 3)}
    if category == "full-alphabet":
        return {"count": rng.randint(4, 10), "lengths": (2, 12)}
    if category == "n-heavy":
        return {"count": rng.randint(3, 10), "lengths": (2, 14)}
    if category == "single-base":
        return {"count": rng.randint(2, 10), "length": 1}
    if category == "short-reads":
        return {"count": rng.randint(3, 12), "lengths": (1, 4)}
    if category == "moderate-reads":
        return {"count": rng.randint(3, 10), "lengths": (8, 24)}
    if category == "odd-length":
        return {"count": rng.randint(3, 10), "length": rng.choice([3, 5, 7, 9, 11])}
    if category == "even-length":
        return {"count": rng.randint(3, 10), "length": rng.choice([2, 4, 6, 8, 10])}
    if category == "mixed-length":
        return {"count": rng.randint(3, 10), "lengths": (1, 20)}
    if category == "repeated-motifs":
        return {"count": rng.randint(3, 10), "lengths": (2, 16)}
    if category == "revcomp-pairs":
        return {"count": rng.randint(2, 6), "lengths": (2, 10)}
    if category == "lexicographic-similar":
        return {"count": rng.randint(3, 10), "length": rng.randint(2, 8)}
    raise ValueError(category)


def _medium_params(category: str, rng: random.Random) -> Dict[str, Any]:
    if category == "uniform-reads":
        return {"count": rng.randint(16, 30), "length": rng.randint(8, 24)}
    if category == "nonuniform-reads":
        return {"count": rng.randint(16, 30), "lengths": (2, 30)}
    if category == "duplicates":
        return {"count": rng.randint(16, 30), "length": rng.randint(6, 16)}
    if category == "all-identical":
        return {"count": rng.randint(10, 20), "length": rng.randint(4, 16)}
    if category == "prefix-sharing":
        return {"count": rng.randint(16, 30), "lengths": (4, 30)}
    if category == "suffix-sharing":
        return {"count": rng.randint(16, 30), "lengths": (4, 30)}
    if category == "many-dollars":
        return {"count": rng.randint(40, 60), "lengths": (1, 3)}
    if category == "full-alphabet":
        return {"count": rng.randint(16, 30), "lengths": (4, 24)}
    if category == "n-heavy":
        return {"count": rng.randint(16, 30), "lengths": (4, 26)}
    if category == "single-base":
        return {"count": rng.randint(8, 16), "length": 1}
    if category == "short-reads":
        return {"count": rng.randint(16, 30), "lengths": (1, 5)}
    if category == "moderate-reads":
        return {"count": rng.randint(10, 20), "lengths": (12, 40)}
    if category == "odd-length":
        return {"count": rng.randint(10, 20), "length": rng.choice([9, 11, 13, 15])}
    if category == "even-length":
        return {"count": rng.randint(10, 20), "length": rng.choice([8, 10, 12, 14])}
    if category == "mixed-length":
        return {"count": rng.randint(16, 30), "lengths": (1, 40)}
    if category == "repeated-motifs":
        return {"count": rng.randint(10, 20), "lengths": (2, 30)}
    if category == "revcomp-pairs":
        return {"count": rng.randint(8, 14), "lengths": (2, 16)}
    if category == "lexicographic-similar":
        return {"count": rng.randint(10, 20), "length": rng.randint(4, 12)}
    raise ValueError(category)


_COMPLEMENT = str.maketrans("ACGTN", "TGCAN")


def reverse_complement(seq: str) -> str:
    return seq.translate(_COMPLEMENT)[::-1]


def _pick_lengths(rng: random.Random, count: int, low: int, high: int,
                  uniform_length: Optional[int]) -> List[int]:
    if uniform_length is not None:
        return [uniform_length] * count
    return [rng.randint(low, high) for _ in range(count)]


def _generate_reads(category: str, params: Dict[str, Any],
                    rng: random.Random) -> List[str]:
    """Generate the read list for one case; returns None-safe valid reads."""
    count = params["count"]
    uniform_length = params.get("length")
    low, high = params.get("lengths", (1, 12))
    lengths = _pick_lengths(rng, count, low, high, uniform_length)

    if category == "uniform-reads":
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(lengths[0]))
                for _ in range(count)]
    if category == "nonuniform-reads":
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(n)) for n in lengths]
    if category == "duplicates":
        pool = ["".join(rng.choice(BASE_SYMBOLS) for _ in range(lengths[0]))
                for _ in range(max(2, count // 2))]
        reads = []
        for index in range(count):
            reads.append(pool[rng.randrange(len(pool))])
        return reads
    if category == "all-identical":
        base = "".join(rng.choice(BASE_SYMBOLS) for _ in range(lengths[0]))
        return [base] * count
    if category == "prefix-sharing":
        prefix = "".join(rng.choice(BASE_SYMBOLS) for _ in range(rng.randint(2, 4)))
        reads = []
        for n in lengths:
            tail = "".join(rng.choice(BASE_SYMBOLS) for _ in range(max(0, n - len(prefix))))
            reads.append((prefix + tail)[:n])
        return reads
    if category == "suffix-sharing":
        suffix = "".join(rng.choice(BASE_SYMBOLS) for _ in range(rng.randint(2, 4)))
        reads = []
        for n in lengths:
            head = "".join(rng.choice(BASE_SYMBOLS) for _ in range(max(0, n - len(suffix))))
            combined = (head + suffix)
            reads.append(combined[len(combined) - n:])
        return reads
    if category == "many-dollars":
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(n)) for n in lengths]
    if category == "full-alphabet":
        reads = []
        for n in lengths:
            seq = [rng.choice(BASE_SYMBOLS) for _ in range(max(1, n - 2))]
            for symbol in "ACGTN":
                seq.append(symbol)
            reads.append("".join(seq))
        return reads
    if category == "n-heavy":
        reads = []
        for n in lengths:
            seq = "".join(rng.choice("ACGTN") for _ in range(n))
            while seq.count("N") < n * 0.3:
                seq = "".join(rng.choice("NNNNNACGT") for _ in range(n))
            reads.append(seq)
        return reads
    if category == "single-base":
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(1)) for _ in range(count)]
    if category == "short-reads":
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(n)) for n in lengths]
    if category == "moderate-reads":
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(n)) for n in lengths]
    if category in ("odd-length", "even-length"):
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(lengths[0]))
                for _ in range(count)]
    if category == "mixed-length":
        return ["".join(rng.choice(BASE_SYMBOLS) for _ in range(n)) for n in lengths]
    if category == "repeated-motifs":
        motifs = ["ACGT", "TTAG", "NNAC", "GGG"]
        reads = []
        for n in lengths:
            motif = rng.choice(motifs)
            repeat = (motif * ((n // len(motif)) + 1))[:n]
            reads.append(repeat)
        return reads
    if category == "revcomp-pairs":
        reads = []
        for _ in range(count // 2):
            n = rng.randint(low, high)
            first = "".join(rng.choice(BASE_SYMBOLS) for _ in range(n))
            reads.append(first)
            reads.append(reverse_complement(first))
        if count % 2:
            n = rng.randint(low, high)
            reads.append("".join(rng.choice(BASE_SYMBOLS) for _ in range(n)))
        return reads[:count]
    if category == "lexicographic-similar":
        base = "".join(rng.choice("AC") for _ in range(lengths[0]))
        reads = []
        for offset in range(count):
            position = offset % len(base)
            replacement = rng.choice("GTN")
            seq = list(base)
            seq[position] = replacement
            reads.append("".join(seq))
        return reads
    raise ValueError(category)


def _generate_queries(case: Dict[str, Any], rng: random.Random) -> List[str]:
    """Deterministic query list for a case (independent of any implementation)."""
    reads = case["reads"]
    queries: List[str] = []
    seen = set()

    def add(query: str) -> None:
        if query not in seen:
            seen.add(query)
            queries.append(query)

    for symbol in "ACGTN":
        add(symbol)
    add("$")
    # random substrings from reads (length 2-4)
    for _ in range(6):
        read = rng.choice(reads)
        if len(read) >= 2:
            start = rng.randrange(len(read) - 1)
            end = min(len(read), start + rng.randint(2, 4))
            add(read[start:end])
    # complete reads (up to 3 distinct)
    for read in sorted(set(reads))[:3]:
        add(read)
    # absent strings over ACGT (count must be 0)
    for _ in range(4):
        length = rng.randint(2, 4)
        candidate = "".join(rng.choice("ACGT") for _ in range(length))
        add(candidate)
    # N-containing (mixed)
    for _ in range(3):
        length = rng.randint(2, 4)
        candidate = "".join(rng.choice("ACGTN") for _ in range(length))
        add(candidate)
    # repeated symbols
    for symbol in ("A", "T", "N"):
        add(symbol * rng.randint(2, 4))
    if case["medium"]:
        for _ in range(8):
            read = rng.choice(reads)
            if len(read) >= 3:
                start = rng.randrange(len(read) - 2)
                end = min(len(read), start + rng.randint(3, 6))
                add(read[start:end])
    return queries


def generate_case(seed: int, index: int, category: str, medium: bool,
                  rng: random.Random) -> Dict[str, Any]:
    params = _medium_params(category, rng) if medium else _small_params(category, rng)
    reads = _generate_reads(category, params, rng)
    uniform = _uniform_mode(category)
    if not uniform:
        # nonuniform mode requires at least two distinct lengths to exercise
        # the multimerge path meaningfully; force a small spread if needed.
        distinct = set(reads)
        if len(distinct) > 1 and all(len(r) == len(reads[0]) for r in reads):
            reads[-1] = reads[-1][:-1]
    case = {
        "id": "c%04d" % index,
        "index": index,
        "category": category,
        "medium": medium,
        "uniform": uniform,
        "reads": reads,
        "seed": seed,
    }
    case_rng = random.Random(seed * 1000003 + index * 7919)
    case["queries"] = _generate_queries(case, case_rng)
    case["sample_positions"] = _sample_positions(case)
    return case


def _sample_positions(case: Dict[str, Any]) -> List[int]:
    total = sum(len(read) + 1 for read in case["reads"])
    positions = [0, 1]
    if total > 2:
        positions.append(total // 2)
    if total > 1:
        positions.append(total - 1)
    case_rng = random.Random(case["seed"] * 31 + case["index"])
    while len(positions) < min(12, total):
        positions.append(case_rng.randrange(total))
    return sorted(set(p for p in positions if 0 <= p < total))


def generate_corpus(seed: int, small_count: int = 150,
                    medium_count: int = 15) -> Dict[str, Any]:
    """Generate the full audit corpus deterministically from ``seed``."""
    rng = random.Random(seed)
    cases: List[Dict[str, Any]] = []
    categories = CATEGORY_ORDER

    def next_category(counter: List[int]) -> str:
        category = categories[counter[0] % len(categories)]
        counter[0] += 1
        return category

    counter = [0]
    for _ in range(small_count):
        category = next_category(counter)
        cases.append(generate_case(seed, len(cases), category, False, rng))
    for _ in range(medium_count):
        category = next_category(counter)
        cases.append(generate_case(seed, len(cases), category, True, rng))

    corpus = {
        "format": "modern2-q1-corpus-v1",
        "seed": seed,
        "small_count": small_count,
        "medium_count": medium_count,
        "cases": cases,
    }
    return corpus


# ---------------------------------------------------------------------------
# Independent oracle computations
# ---------------------------------------------------------------------------


def rotation_sort_bwt(reads: Sequence[str]) -> bytes:
    """Numeric payload of the rotation-sorted MSBWT (unique ordering)."""
    rotations: List[str] = []
    for read in reads:
        for char in read:
            if char not in SYMBOL_ORDER:
                raise ValueError("read contains a non-ACGN symbol: {0!r}".format(read))
        terminated = read + "$"
        length = len(terminated)
        for start in range(length):
            rotations.append(terminated[start:] + terminated[:start])
    rotations.sort()
    return bytes(SYMBOL_ORDER[rotation[-1]] for rotation in rotations)


def symbol_counts(payload: bytes) -> List[int]:
    counts = [0] * len(SYMBOLS)
    for value in payload:
        counts[value] += 1
    return counts


def expected_symbol_counts(reads: Sequence[str]) -> List[int]:
    counts = [0] * len(SYMBOLS)
    for read in reads:
        for char in read:
            counts[SYMBOL_ORDER[char]] += 1
        counts[0] += 1
    return counts


def expected_substring_counts(reads: Sequence[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for read in reads:
        for start in range(len(read)):
            for end in range(start + 1, len(read) + 1):
                substring = read[start:end]
                counts[substring] = counts.get(substring, 0) + 1
    return counts


def _occurrence_tables(payload: bytes) -> Tuple[Dict[str, int], List[Dict[str, int]]]:
    counts = symbol_counts(payload)
    c_table: Dict[str, int] = {}
    running = 0
    for symbol in SYMBOLS:
        c_table[symbol] = running
        running += counts[SYMBOL_ORDER[symbol]]
    occ: List[Dict[str, int]] = []
    tally = {symbol: 0 for symbol in SYMBOLS}
    for value in payload:
        tally[SYMBOLS[value]] += 1
        occ.append(dict(tally))
    return c_table, occ


def backward_count(payload: bytes, pattern: str) -> int:
    c_table, occ = _occurrence_tables(payload)
    lo, hi = 0, len(payload)
    for char in reversed(pattern):
        if char not in SYMBOL_ORDER:
            raise ValueError("pattern contains a non-ACGN symbol: {0!r}".format(pattern))
        lo = c_table[char] + (occ[lo - 1][char] if lo > 0 else 0)
        hi = c_table[char] + (occ[hi - 1][char] if hi > 0 else 0)
        if lo >= hi:
            return 0
    return hi - lo


def backward_counts_many(payload: bytes, patterns: Sequence[str]) -> Dict[str, int]:
    """Backward-search counts for many patterns with a single occurrence pass."""
    c_table, occ = _occurrence_tables(payload)
    counts: Dict[str, int] = {}
    for pattern in patterns:
        lo, hi = 0, len(payload)
        for char in reversed(pattern):
            if char not in SYMBOL_ORDER:
                raise ValueError("pattern contains a non-ACGN symbol: {0!r}".format(pattern))
            lo = c_table[char] + (occ[lo - 1][char] if lo > 0 else 0)
            hi = c_table[char] + (occ[hi - 1][char] if hi > 0 else 0)
            if lo >= hi:
                break
        counts[pattern] = hi - lo
    return counts


def substring_count_in_reads(reads: Sequence[str], pattern: str) -> int:
    if pattern == "$":
        return len(reads)
    total = 0
    for read in reads:
        start = 0
        while True:
            found = read.find(pattern, start)
            if found < 0:
                break
            total += 1
            start = found + 1
    return total


def lf_recover_reads(payload: bytes) -> List[str]:
    """Recover the read multiset from the payload via LF mapping."""
    n = len(payload)
    counts = symbol_counts(payload)
    c_table: Dict[str, int] = {}
    running = 0
    for symbol in SYMBOLS:
        c_table[symbol] = running
        running += counts[SYMBOL_ORDER[symbol]]
    occ: List[Dict[str, int]] = []
    tally = {symbol: 0 for symbol in SYMBOLS}
    for value in payload:
        tally[SYMBOLS[value]] += 1
        occ.append(dict(tally))

    def lf(index: int) -> int:
        symbol = SYMBOLS[payload[index]]
        return c_table[symbol] + occ[index][symbol] - 1

    reads = []
    for start in range(n):
        if payload[start] != 0:
            continue
        reversed_chars = []
        index = start
        while True:
            index = lf(index)
            if payload[index] == 0:
                break
            reversed_chars.append(SYMBOLS[payload[index]])
        reads.append("".join(reversed(reversed_chars)))
    return sorted(reads)


def fm_rank_row(payload: bytes, position: int) -> List[int]:
    """Independent FM row at ``position``: [C(s) + occ(s, position) for s]."""
    counts = symbol_counts(payload)
    c_table: Dict[str, int] = {}
    running = 0
    for symbol in SYMBOLS:
        c_table[symbol] = running
        running += counts[SYMBOL_ORDER[symbol]]
    tally = {symbol: 0 for symbol in SYMBOLS}
    for value in payload[:position]:
        tally[SYMBOLS[value]] += 1
    return [c_table[symbol] + tally[symbol] for symbol in SYMBOLS]


# ---------------------------------------------------------------------------
# NPY v1 framing + RLE decoding (independent of the reader code)
# ---------------------------------------------------------------------------


def parse_npy_v1(raw: bytes) -> Dict[str, Any]:
    """Parse a NumPy v1 array file; returns dtype/header/payload.

    Handles Python-2 long literals such as ``(48L,)`` in the header dict.
    """
    if raw[:6] != b"\x93NUMPY":
        raise ValueError("not a NumPy v1 file")
    version = raw[6:8]
    if version[0] != 1:
        raise ValueError("unsupported NPY version: {0}".format(version))
    header_len = int.from_bytes(raw[8:10], "little")
    header_text = raw[10:10 + header_len].decode("ascii")
    if "L" in header_text:
        # Python-2 long literals: (48L,) / 48L
        header_text = header_text.replace("L,", ",").replace("L}", "}")
    header = ast.literal_eval(header_text)
    payload_offset = 10 + header_len
    # NPY v1 aligns the payload to a 64-byte boundary
    if payload_offset % 64:
        payload_offset += 64 - (payload_offset % 64)
    payload = raw[payload_offset:]
    if len(payload) != _expected_payload_size(header):
        raise ValueError("payload size mismatch for {0}".format(header))
    return {"dtype": header["descr"], "shape": header["shape"],
            "fortran_order": header["fortran_order"], "payload": payload}


def _expected_payload_size(header: Dict[str, Any]) -> int:
    import operator
    from functools import reduce
    itemsize = {"|u1": 1, "|i1": 1, "<u8": 8, "<i8": 8, "|u8": 8}.get(
        header["descr"])
    if itemsize is None:
        raise ValueError("unsupported dtype: {0}".format(header["descr"]))
    count = reduce(operator.mul, header["shape"], 1)
    return count * itemsize


def decode_rle(payload: bytes) -> Tuple[List[int], List[int]]:
    """Independent base-32 RLE decoder; returns (run_lengths, symbol_list).

    The historical encoding stores run counts base-32 with the LEAST
    significant digit first (the encoder writes ``delta & mask`` then
    ``delta /= numPower``; the reader reconstructs with
    ``digit * numPower ** power`` where power 0 is the first digit).
    """
    symbols: List[int] = []
    run_lengths: List[int] = []
    prev_sym: Optional[int] = None
    digits: List[int] = []
    for byte in payload:
        sym = byte & 7
        digit = byte >> 3
        if sym != prev_sym:
            if digits:
                total = sum(d * (32 ** power)
                            for power, d in enumerate(digits))
                run_lengths.append(total)
                symbols.extend([prev_sym] * total)  # type: ignore[list-item]
            digits = []
            prev_sym = sym
        digits.append(digit)
    if digits:
        total = sum(d * (32 ** power) for power, d in enumerate(digits))
        run_lengths.append(total)
        symbols.extend([prev_sym] * total)  # type: ignore[list-item]
    return run_lengths, symbols


# ---------------------------------------------------------------------------
# Classification and summary
# ---------------------------------------------------------------------------


def classify(frozen: Optional[Any], modern2: Optional[Any],
             oracle: Optional[Any]) -> str:
    """Classify one three-way comparison per the audit policy."""
    f_ok = frozen is not None
    m_ok = modern2 is not None
    o_ok = oracle is not None
    if f_ok and m_ok and o_ok:
        if frozen == modern2 and modern2 == oracle:
            return "A"
        if frozen == modern2:
            return "B"
        if modern2 == oracle:
            return "C"
        if frozen == oracle:
            return "D"
        return "E"
    if f_ok and m_ok:
        return "A" if frozen == modern2 else "B" if False else "E-partial"
    return "E-incomplete"


def summarize(results: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic summary of an executed audit run."""
    return {
        "classifications": sorted(results.get("classifications", {}).items()),
        "counts": dict(sorted(results.get("counts", {}).items())),
        "failures": sorted(results.get("failures", []), key=lambda f: f["case"]),
        "family_counts": dict(sorted(results.get("family_counts", {}).items())),
    }


def json_dump(data: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def json_load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
