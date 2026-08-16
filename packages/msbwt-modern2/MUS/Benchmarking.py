"""Feature 13A - whole-index structural and query benchmark harness
(enhanced-modern2).

The benchmark is deliberately representation-aware but backend-neutral.

It answers:

* N: number of BWT rows;
* r: number of BWT runs;
* r/N and mean run length;
* physical bytes and payload bytes by index layer;
* provenance-tree logical bit cost;
* read-provenance bytes/read;
* Feature-12 tag bytes/row;
* Q1 quality layer semantics (physically a Point-12 tag, never double
  counted);
* Feature-11A LCP bytes/row (``lcps.npy``);
* a simple naive run-encoding size model;
* optional query latency on an already-loaded MultiSourceBWT-like object;
* machine-readable backend/framework contract (``MUS.BackendContract``).

The harness never rebuilds the BWT merely to inspect it.  Feature 13A
does NOT implement a new backend.

Python 2.7 compatibility is required (CPython 2.7.18 / NumPy 1.16.6); this
module also runs unchanged under Python 3 for host-side testing.
"""

from __future__ import absolute_import

import json
import math
import os
import platform
import sys
import time

from collections import OrderedDict

import numpy as np

from MUS.BackendContract import (
    LegacyBWTAdapter,
    contract_document,
    inspect_framework,
)
from MUS.BWTTags import BWTTagStore, tags_exist
from MUS.MultiSourceProvenance import (
    BWT_FILENAME,
    load_manifest,
)
from MUS.ReadProvenance import (
    ReadProvenanceIndex,
    read_provenance_exists,
)
from MUS.QualitySidecar import (
    QUALITY_META_FILENAME,
    QUALITY_TAG_NAME,
    QualitySidecar,
    quality_sidecar_exists,
)
from MUS.LCP import (
    LCPIndex,
    lcp_exists,
)


BENCHMARK_FORMAT = "msbwt-point13a-benchmark"
BENCHMARK_VERSION = 1

DEFAULT_PATTERNS = (
    b"A",
    b"C",
    b"G",
    b"T",
    b"AC",
    b"CG",
    b"GT",
    b"ACG",
    b"CGT",
    b"ACGT",
    b"AAAA",
    b"TTTT",
)


class BenchmarkError(ValueError):
    pass


def _monotonic():
    if hasattr(time, "perf_counter"):
        return time.perf_counter()
    return time.time()


def _cpu_count():
    if hasattr(os, "cpu_count"):
        return os.cpu_count()
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except Exception:
        return None


def _median(values):
    values = sorted(float(x) for x in values)
    n = len(values)
    if n == 0:
        return None
    if n % 2 == 1:
        return values[n // 2]
    return (values[n // 2 - 1] + values[n // 2]) / 2.0


def _mean(values):
    values = [float(x) for x in values]
    if not values:
        return None
    return sum(values) / len(values)


def environment_snapshot():
    total_memory = None
    meminfo = "/proc/meminfo"
    if os.path.exists(meminfo):
        try:
            with open(meminfo, "r") as fp:
                for line in fp:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        total_memory = int(parts[1]) * 1024
                        break
        except Exception:
            total_memory = None

    return {
        "python_version": sys.version.split()[0],
        "numpy_version": np.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": _cpu_count(),
        "total_memory_bytes": total_memory,
    }


def _file_size(path):
    path = str(path)
    if not os.path.exists(path):
        return 0
    return int(os.path.getsize(path))


def _npy_payload_bytes(path):
    path = str(path)
    if not os.path.exists(path):
        return 0
    arr = np.load(path, mmap_mode="r", allow_pickle=False)
    return int(arr.nbytes)


def _iter_files(root):
    root = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            yield os.path.join(dirpath, filename)


def _relative(path, root):
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def _classify_file(relative_path):
    rel = str(relative_path).replace("\\", "/")

    if rel == "msbwt.npy":
        return "bwt"
    if rel in ("comp_msbwt.npy", "compressed_msbwt.npy"):
        return "bwt"
    if rel == "inter0.npy":
        return "root_interleave_compat"
    if rel == "provenance.json":
        return "provenance_manifest"
    if rel.startswith("provenance/interleaves/"):
        return "provenance_interleaves"
    if rel.startswith("provenance/ranks/"):
        return "provenance_ranks"
    if rel in ("read_provenance.npy", "read_provenance.json"):
        return "read_provenance"
    if rel == "source_metadata.json":
        return "source_metadata"
    if rel == QUALITY_META_FILENAME:
        return "quality_sidecar_metadata"
    if rel == "bwt_tags.json":
        return "bwt_tags_registry"
    if rel.startswith("bwt_tags/"):
        return "bwt_tags_arrays"
    if rel in ("lcps.npy", "lcp.npy", "lcp.json"):
        return "lcp"
    if rel in (
        "naive_suffix_rows.json",
        "reads.json",
        "FIXTURE_MANIFEST.json",
        "POINT9_FIXTURE_MANIFEST.json",
        "POINT10_FIXTURE_MANIFEST.json",
        "POINT12_FIXTURE_MANIFEST.json",
        "POINT12_REDUCED_FIXTURE_MANIFEST.json",
    ):
        return "test_oracle_fixture"
    return "other"


def disk_breakdown(index_dir):
    index_dir = str(index_dir)
    layers = OrderedDict()
    files = []

    for path in _iter_files(index_dir):
        rel = _relative(path, index_dir)
        layer = _classify_file(rel)
        size = _file_size(path)
        record = {
            "path": rel,
            "layer": layer,
            "physical_bytes": size,
        }

        if rel.endswith(".npy"):
            try:
                record["payload_bytes"] = _npy_payload_bytes(path)
            except Exception:
                record["payload_bytes"] = None
        else:
            record["payload_bytes"] = None

        files.append(record)
        bucket = layers.setdefault(
            layer,
            {
                "file_count": 0,
                "physical_bytes": 0,
                "known_payload_bytes": 0,
            },
        )
        bucket["file_count"] += 1
        bucket["physical_bytes"] += size
        if record["payload_bytes"] is not None:
            bucket["known_payload_bytes"] += int(
                record["payload_bytes"]
            )

    physical_total = int(sum(
        row["physical_bytes"] for row in files
    ))
    production_total = int(sum(
        row["physical_bytes"]
        for row in files
        if row["layer"] != "test_oracle_fixture"
    ))
    intrinsic_total = int(sum(
        row["physical_bytes"]
        for row in files
        if row["layer"] not in (
            "test_oracle_fixture",
            "root_interleave_compat",
        )
    ))

    return {
        "layers": layers,
        "files": files,
        "physical_total_bytes": physical_total,
        "production_total_bytes": production_total,
        "intrinsic_total_excluding_root_interleave_copy_bytes": (
            intrinsic_total
        ),
    }


def bwt_run_metrics(
    index_dir,
    chunk_rows=8 * 1024 * 1024,
):
    """Count BWT runs and symbols by sequential mmap scan."""
    path = os.path.join(str(index_dir), BWT_FILENAME)
    if not os.path.exists(path):
        raise BenchmarkError("missing msbwt.npy: %s" % path)

    bwt = np.load(
        path,
        mmap_mode="r",
        allow_pickle=False,
    )
    if bwt.ndim != 1:
        raise BenchmarkError("msbwt.npy must be one-dimensional")

    n = int(bwt.shape[0])
    if n == 0:
        return {
            "N": 0,
            "r": 0,
            "r_over_N": None,
            "mean_run_length": None,
            "symbol_counts": {},
            "dtype": str(bwt.dtype),
            "payload_bytes": int(bwt.nbytes),
        }

    chunk_rows = max(1, int(chunk_rows))
    run_count = 0
    previous_last = None
    symbol_counts = {}

    for start in range(0, n, chunk_rows):
        end = min(start + chunk_rows, n)
        chunk = np.asarray(bwt[start:end])
        if chunk.shape[0] == 0:
            continue

        unique, counts = np.unique(
            chunk,
            return_counts=True,
        )
        for symbol, count in zip(unique, counts):
            key = str(
                symbol.item()
                if isinstance(symbol, np.generic)
                else symbol
            )
            symbol_counts[key] = (
                symbol_counts.get(key, 0) + int(count)
            )

        local_runs = 1
        if chunk.shape[0] > 1:
            local_runs += int(
                np.count_nonzero(chunk[1:] != chunk[:-1])
            )

        if previous_last is not None and chunk[0] == previous_last:
            local_runs -= 1

        run_count += local_runs
        previous_last = chunk[-1]

    return {
        "N": n,
        "r": int(run_count),
        "r_over_N": float(run_count) / float(n),
        "mean_run_length": float(n) / float(run_count),
        "symbol_counts": symbol_counts,
        "dtype": str(bwt.dtype),
        "payload_bytes": int(bwt.nbytes),
    }


def _tree_metrics(node, depth=0):
    if node["type"] == "leaf":
        return {
            "leaf_count": 1,
            "internal_nodes": 0,
            "interleave_logical_bits": 0,
            "max_depth": depth,
            "weighted_leaf_depth_rows": (
                int(node["length"]) * depth
            ),
        }

    left = _tree_metrics(node["left"], depth + 1)
    right = _tree_metrics(node["right"], depth + 1)

    return {
        "leaf_count": (
            left["leaf_count"] + right["leaf_count"]
        ),
        "internal_nodes": (
            1
            + left["internal_nodes"]
            + right["internal_nodes"]
        ),
        "interleave_logical_bits": (
            int(node["length"])
            + left["interleave_logical_bits"]
            + right["interleave_logical_bits"]
        ),
        "max_depth": max(
            left["max_depth"],
            right["max_depth"],
        ),
        "weighted_leaf_depth_rows": (
            left["weighted_leaf_depth_rows"]
            + right["weighted_leaf_depth_rows"]
        ),
    }


def provenance_metrics(index_dir, n_rows=None):
    index_dir = str(index_dir)
    manifest_path = os.path.join(index_dir, "provenance.json")
    if not os.path.exists(manifest_path):
        return {
            "available": False,
        }

    manifest = load_manifest(
        index_dir,
        validate=True,
    )
    if n_rows is None:
        n_rows = int(manifest["bwt_length"])

    metrics = _tree_metrics(manifest["root"])
    bits = int(metrics["interleave_logical_bits"])

    ranks_dir = os.path.join(index_dir, "provenance", "ranks")
    rank_files = (
        [os.path.join(ranks_dir, name)
         for name in sorted(os.listdir(ranks_dir))
         if name.endswith(".npz")]
        if os.path.isdir(ranks_dir)
        else []
    )

    metrics.update(
        {
            "available": True,
            "source_count": len(manifest["sources"]),
            "interleave_logical_bytes_packed": int(
                math.ceil(bits / 8.0)
            ),
            "interleave_logical_bits_per_bwt_row": (
                float(bits) / float(n_rows)
                if n_rows
                else None
            ),
            "mean_source_tree_depth_weighted_by_rows": (
                float(metrics["weighted_leaf_depth_rows"])
                / float(n_rows)
                if n_rows
                else None
            ),
            "rank_cache_file_count": len(rank_files),
            "rank_cache_physical_bytes": int(
                sum(_file_size(p) for p in rank_files)
            ),
        }
    )
    return metrics


def read_provenance_metrics(index_dir, n_rows=None):
    index_dir = str(index_dir)
    if not read_provenance_exists(index_dir):
        return {"available": False}

    index = ReadProvenanceIndex(
        index_dir,
        mmap=True,
        validate=True,
    )
    data_path = os.path.join(index_dir, "read_provenance.npy")
    meta_path = os.path.join(index_dir, "read_provenance.json")

    read_count = int(index.read_count)
    payload = _npy_payload_bytes(data_path)
    physical = _file_size(data_path) + _file_size(meta_path)

    return {
        "available": True,
        "read_count": read_count,
        "record_bytes": int(index.record_bytes()),
        "payload_bytes": int(payload),
        "physical_bytes": int(physical),
        "payload_bytes_per_read": (
            float(payload) / float(read_count)
            if read_count
            else None
        ),
        "physical_bytes_per_read": (
            float(physical) / float(read_count)
            if read_count
            else None
        ),
        "reads_per_bwt_row": (
            float(read_count) / float(n_rows)
            if n_rows
            else None
        ),
    }


def tag_metrics(index_dir, n_rows=None):
    index_dir = str(index_dir)
    if not tags_exist(index_dir):
        return {"available": False}

    store = BWTTagStore(
        index_dir,
        mmap=True,
        validate=True,
    )

    tags = OrderedDict()
    payload_total = 0
    physical_total = _file_size(
        os.path.join(index_dir, "bwt_tags.json")
    )

    for name in store.list_tags():
        arr = store.array(name)
        schema = store.schema(name)
        path = os.path.join(index_dir, str(schema["filename"]))
        payload = int(arr.nbytes)
        physical = _file_size(path)

        payload_total += payload
        physical_total += physical

        tags[name] = {
            "dtype": str(arr.dtype),
            "shape": [int(x) for x in arr.shape],
            "tail_shape": [
                int(x) for x in arr.shape[1:]
            ],
            "payload_bytes": payload,
            "physical_bytes": physical,
            "payload_bytes_per_bwt_row": (
                float(payload) / float(n_rows)
                if n_rows
                else None
            ),
        }

    return {
        "available": True,
        "tag_count": len(tags),
        "tags": tags,
        "payload_bytes": int(payload_total),
        "physical_bytes": int(physical_total),
        "payload_bytes_per_bwt_row": (
            float(payload_total) / float(n_rows)
            if n_rows
            else None
        ),
    }


def quality_metrics(index_dir, n_rows=None):
    """Report Q1 quality storage without double-counting the Point-12 tag.

    The quality payload physically resides as a Point-12 tag array (already
    counted in ``tag_metrics`` / ``bwt_tags_arrays``); this section reports
    its semantics separately.
    """
    index_dir = str(index_dir)
    if not quality_sidecar_exists(index_dir):
        return {"available": False}

    sidecar = QualitySidecar(
        index_dir,
        mmap=True,
        validate=True,
    )
    schema = sidecar.store.schema(QUALITY_TAG_NAME)
    tag_path = os.path.join(index_dir, str(schema["filename"]))
    payload = int(sidecar.values.nbytes)
    tag_physical = _file_size(tag_path)
    meta_physical = _file_size(
        os.path.join(index_dir, QUALITY_META_FILENAME)
    )

    return {
        "available": True,
        "tag_name": QUALITY_TAG_NAME,
        "alignment": sidecar.metadata["alignment"],
        "encoding": sidecar.metadata["encoding"],
        "terminal_sentinel": sidecar.metadata["terminal_sentinel"],
        "read_count": sidecar.read_count,
        "payload_bytes": payload,
        "tag_physical_bytes": int(tag_physical),
        "metadata_physical_bytes": int(meta_physical),
        "payload_bytes_per_bwt_row": (
            float(payload) / float(n_rows)
            if n_rows
            else None
        ),
        "note": (
            "quality payload is already included in Point-12 tag totals; "
            "this section reports its semantics separately"
        ),
    }


def lcp_metrics(index_dir, n_rows=None):
    """Feature-11A LCP accounting (``lcps.npy``, stored boundary count)."""
    index_dir = str(index_dir)
    if not lcp_exists(index_dir):
        return {
            "available": False,
            "expected_files": [
                "lcps.npy",
                "lcp.json",
            ],
        }

    index = LCPIndex(
        index_dir,
        mmap=True,
        validate=True,
    )
    array_path = os.path.join(index_dir, "lcps.npy")
    meta_path = os.path.join(index_dir, "lcp.json")
    physical = _file_size(array_path) + _file_size(meta_path)
    payload = int(index.values.nbytes)

    return {
        "available": True,
        "dtype": str(index.values.dtype),
        "stored_boundaries": int(index.values.shape[0]),
        "bwt_rows": int(index.n_rows),
        "max_lcp": int(index.max_lcp),
        "payload_bytes": payload,
        "physical_bytes": int(physical),
        "payload_bytes_per_bwt_row": (
            float(payload) / float(n_rows)
            if n_rows
            else None
        ),
        "stored_convention": (
            "lcps[i] = LCP(SA[i], SA[i+1]); length N-1"
        ),
    }


def naive_run_encoding_model(run_metrics):
    """Simple storage model; not a full r-index size prediction.

    Models each run as:
        symbol byte + uint32 run length
    or:
        symbol byte + uint64 run length

    This deliberately excludes rank/select samples, SA samples, document
    data, and implementation overhead.
    """
    r = int(run_metrics["r"])
    n = int(run_metrics["N"])
    payload = int(run_metrics["payload_bytes"])

    u32 = r * (1 + 4)
    u64 = r * (1 + 8)

    return {
        "description": (
            "naive RLE payload only; excludes FM/r-index/query auxiliaries"
        ),
        "symbol_plus_uint32_length_bytes": int(u32),
        "symbol_plus_uint64_length_bytes": int(u64),
        "uint32_model_bytes_per_bwt_row": (
            float(u32) / float(n) if n else None
        ),
        "uint64_model_bytes_per_bwt_row": (
            float(u64) / float(n) if n else None
        ),
        "uint32_model_vs_raw_bwt_payload_ratio": (
            float(u32) / float(payload)
            if payload
            else None
        ),
        "uint64_model_vs_raw_bwt_payload_ratio": (
            float(u64) / float(payload)
            if payload
            else None
        ),
    }


def inspect_index(index_dir):
    index_dir = str(index_dir)

    t0 = _monotonic()
    runs = bwt_run_metrics(index_dir)
    n = int(runs["N"])

    disk = disk_breakdown(index_dir)
    provenance = provenance_metrics(
        index_dir,
        n_rows=n,
    )
    reads = read_provenance_metrics(
        index_dir,
        n_rows=n,
    )
    tags = tag_metrics(
        index_dir,
        n_rows=n,
    )
    quality = quality_metrics(
        index_dir,
        n_rows=n,
    )
    lcp = lcp_metrics(
        index_dir,
        n_rows=n,
    )

    production = int(disk["production_total_bytes"])
    bwt_physical = int(
        disk["layers"].get("bwt", {}).get("physical_bytes", 0)
    )
    bwt_payload = int(runs["payload_bytes"])
    layer_ranking = sorted(
        [
            {
                "layer": name,
                "physical_bytes": int(values["physical_bytes"]),
                "fraction_of_production_bytes": (
                    float(values["physical_bytes"]) / float(production)
                    if production and name != "test_oracle_fixture"
                    else None
                ),
            }
            for name, values in disk["layers"].items()
            if name != "test_oracle_fixture"
        ],
        key=lambda row: row["physical_bytes"],
        reverse=True,
    )

    run_model = naive_run_encoding_model(runs)
    auxiliary_physical = max(0, production - bwt_physical)

    report = {
        "format": BENCHMARK_FORMAT,
        "version": BENCHMARK_VERSION,
        "index_dir": str(index_dir),
        "structure": {
            "N": n,
            "r": int(runs["r"]),
            "r_over_N": runs["r_over_N"],
            "mean_run_length": runs["mean_run_length"],
            "bwt_dtype": runs["dtype"],
            "bwt_symbol_counts": runs["symbol_counts"],
        },
        "storage": {
            "disk": disk,
            "bytes_per_bwt_row_production_total": (
                float(production) / float(n)
                if n
                else None
            ),
            "provenance": provenance,
            "read_provenance": reads,
            "tags": tags,
            "quality": quality,
            "lcp": lcp,
        },
        "compression_models": {
            "naive_run_encoding": run_model,
        },
        "decision_summary": {
            "bwt_physical_fraction_of_production": (
                float(bwt_physical) / float(production)
                if production else None
            ),
            "auxiliary_physical_bytes": int(auxiliary_physical),
            "auxiliary_physical_to_raw_bwt_payload_ratio": (
                float(auxiliary_physical) / float(bwt_payload)
                if bwt_payload else None
            ),
            "naive_u32_rle_smaller_than_raw_bwt_payload": bool(
                run_model["symbol_plus_uint32_length_bytes"] < bwt_payload
            ),
            "largest_production_layers": layer_ranking[:5],
            "lcp_present": bool(lcp.get("available", False)),
        },
        "inspection_seconds": float(
            _monotonic() - t0
        ),
        "environment": environment_snapshot(),
    }
    return report


def _percentile(values, q):
    if not values:
        return None
    values = sorted(float(x) for x in values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * float(q)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    fraction = pos - lo
    return (
        values[lo] * (1.0 - fraction)
        + values[hi] * fraction
    )


def _time_calls(callables, warmup=1, repeats=5):
    warmup = max(0, int(warmup))
    repeats = max(1, int(repeats))

    for _ in range(warmup):
        for fn in callables:
            fn()

    observations = []
    for _ in range(repeats):
        for fn in callables:
            start = _monotonic()
            fn()
            observations.append(
                (_monotonic() - start) * 1e6
            )

    return {
        "calls": len(observations),
        "median_us": float(_median(observations)),
        "mean_us": float(_mean(observations)),
        "p95_us": float(_percentile(observations, 0.95)),
        "min_us": float(min(observations)),
        "max_us": float(max(observations)),
    }


def _normalize_pattern(pattern):
    if isinstance(pattern, bytes):
        return pattern
    return str(pattern).encode("ascii")


def benchmark_queries(
    msbwt,
    patterns=None,
    warmup=1,
    repeats=5,
    source=None,
    top_k=3,
    tag_name=None,
    include_read_listing=False,
):
    """Benchmark existing Features 1-12/Q1 semantics on a loaded object.

    This is intentionally a semantic benchmark.  A future compressed
    backend should be benchmarked through the same MultiSourceBWT-facing
    operations.
    """
    if patterns is None:
        patterns = DEFAULT_PATTERNS
    patterns = [
        _normalize_pattern(p) for p in patterns
    ]
    if not patterns:
        raise BenchmarkError("patterns cannot be empty")

    result = OrderedDict()

    backend = getattr(msbwt, "bwt", msbwt)
    adapter = LegacyBWTAdapter(backend)

    result["count"] = _time_calls(
        [
            (lambda p=p: adapter.count(p))
            for p in patterns
        ],
        warmup=warmup,
        repeats=repeats,
    )

    result["find_interval"] = _time_calls(
        [
            (lambda p=p: adapter.find_interval(p))
            for p in patterns
        ],
        warmup=warmup,
        repeats=repeats,
    )

    if source is None:
        source_index = getattr(msbwt, "source_index", None)
        if source_index is not None:
            sources = source_index.list_sources()
            if sources:
                source = str(sources[0]["id"])

    if (
        source is not None
        and callable(
            getattr(
                msbwt,
                "countOccurrencesForSource",
                None,
            )
        )
    ):
        result["source_count"] = _time_calls(
            [
                (
                    lambda p=p: msbwt.countOccurrencesForSource(
                        p, source
                    )
                )
                for p in patterns
            ],
            warmup=warmup,
            repeats=repeats,
        )

    if callable(getattr(msbwt, "nonzeroSources", None)):
        result["sparse_sources"] = _time_calls(
            [
                (lambda p=p: msbwt.nonzeroSources(p))
                for p in patterns
            ],
            warmup=warmup,
            repeats=repeats,
        )

    if callable(getattr(msbwt, "sourceFrequency", None)):
        result["source_frequency"] = _time_calls(
            [
                (lambda p=p: msbwt.sourceFrequency(p))
                for p in patterns
            ],
            warmup=warmup,
            repeats=repeats,
        )

    if callable(getattr(msbwt, "topSources", None)):
        result["top_sources"] = _time_calls(
            [
                (
                    lambda p=p: msbwt.topSources(
                        p,
                        k=int(top_k),
                    )
                )
                for p in patterns
            ],
            warmup=warmup,
            repeats=repeats,
        )

    if (
        tag_name is not None
        and callable(getattr(msbwt, "tagValues", None))
    ):
        result["tag_values"] = _time_calls(
            [
                (
                    lambda p=p: msbwt.tagValues(
                        p,
                        tag_name,
                    )
                )
                for p in patterns
            ],
            warmup=warmup,
            repeats=repeats,
        )

    if (
        include_read_listing
        and callable(getattr(msbwt, "readsContaining", None))
    ):
        result["read_listing"] = _time_calls(
            [
                (
                    lambda p=p: msbwt.readsContaining(p)
                )
                for p in patterns
            ],
            warmup=warmup,
            repeats=repeats,
        )

    return {
        "patterns": [
            p.decode("ascii") for p in patterns
        ],
        "warmup": int(warmup),
        "repeats": int(repeats),
        "source": source,
        "top_k": int(top_k),
        "tag_name": tag_name,
        "operations": result,
        "framework_contract": inspect_framework(msbwt),
        "environment": environment_snapshot(),
    }


def benchmark_build_operation(
    name,
    builder,
    repeats=1,
):
    """Time a caller-supplied construction/build operation.

    The caller owns cleanup and should provide a builder that creates a
    fresh output per call.  This keeps 13A backend-neutral and avoids
    shell execution.
    """
    repeats = max(1, int(repeats))
    observations = []
    results = []

    for _ in range(repeats):
        start = _monotonic()
        value = builder()
        observations.append(
            _monotonic() - start
        )
        results.append(value)

    return {
        "name": str(name),
        "repeats": repeats,
        "median_seconds": float(_median(observations)),
        "mean_seconds": float(_mean(observations)),
        "min_seconds": float(min(observations)),
        "max_seconds": float(max(observations)),
        "results": results,
    }


def compare_reports(reports):
    """Compare structural reports using a compact backend-selection table."""
    rows = []
    for label, report in reports.items():
        structure = report["structure"]
        storage = report["storage"]
        provenance = storage["provenance"]
        reads = storage["read_provenance"]
        tags = storage["tags"]
        quality = storage["quality"]
        lcp = storage["lcp"]

        rows.append(
            {
                "label": str(label),
                "N": int(structure["N"]),
                "r": int(structure["r"]),
                "r_over_N": structure["r_over_N"],
                "mean_run_length": structure["mean_run_length"],
                "production_bytes": int(
                    storage["disk"]["production_total_bytes"]
                ),
                "bytes_per_bwt_row": (
                    storage["bytes_per_bwt_row_production_total"]
                ),
                "provenance_bits_per_bwt_row": (
                    provenance.get(
                        "interleave_logical_bits_per_bwt_row"
                    )
                    if provenance.get("available")
                    else None
                ),
                "rank_cache_bytes": (
                    provenance.get(
                        "rank_cache_physical_bytes"
                    )
                    if provenance.get("available")
                    else None
                ),
                "read_provenance_bytes": (
                    reads.get("physical_bytes")
                    if reads.get("available")
                    else 0
                ),
                "tag_payload_bytes_per_bwt_row": (
                    tags.get("payload_bytes_per_bwt_row")
                    if tags.get("available")
                    else 0
                ),
                "quality_payload_bytes_per_bwt_row": (
                    quality.get("payload_bytes_per_bwt_row")
                    if quality.get("available")
                    else 0
                ),
                "lcp_payload_bytes_per_bwt_row": (
                    lcp.get("payload_bytes_per_bwt_row")
                    if lcp.get("available")
                    else 0
                ),
            }
        )

    return rows


def _atomic_write_json(path, document):
    payload = json.dumps(
        document, indent=2, sort_keys=True) + "\n"
    if sys.version_info[0] == 3:
        payload = payload.encode("utf-8")
    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "wb") as fp:
        fp.write(payload)
        fp.flush()
        try:
            os.fsync(fp.fileno())
        except (OSError, IOError):
            pass
    if hasattr(os, "replace"):
        os.replace(tmp_path, str(path))
    elif os.name == "nt" and os.path.exists(str(path)):
        os.remove(str(path))
        os.rename(tmp_path, str(path))
    else:
        os.rename(tmp_path, str(path))
    return path


def save_report(path, report):
    _atomic_write_json(path, report)
    return path


def full_benchmark_document(
    index_dir,
    query_report=None,
    build_reports=None,
):
    structural = inspect_index(index_dir)
    document = {
        "format": BENCHMARK_FORMAT,
        "version": BENCHMARK_VERSION,
        "structural": structural,
        "query": query_report,
        "build": list(build_reports or []),
        "backend_contract": contract_document(),
    }
    return document
