# msbwt-modern2 quality audit Q1 -- Python-2 reader probe.
#
# Runs INSIDE the Python-2.7 environment (frozen oracle or modern2) against a
# manifest of disposable BWT directories and records implementation results
# for the audit's reader/FM/recovery/cache-regeneration families:
#
#   - reader class and total size;
#   - getCharAtIndex at sampled positions;
#   - getFullFMAtIndex FM rows at sampled positions;
#   - countOccurrencesOfSeq for the generated query list (exceptions are
#     recorded, not hidden);
#   - recoverString at every dollar position (multiset);
#   - derived-file inventory + SHA-256 after first load;
#   - cache regeneration: delete derived files, reload, require identical
#     derived bytes.
#
# This file must remain valid Python 2.7 (no f-strings, no annotations).
# The probe never writes into a build directory: every load runs on a
# disposable copy created by the executor.
from __future__ import print_function

import hashlib
import json
import os
import shutil
import sys


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def file_hashes(directory):
    result = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            result[name] = sha256_file(path)
    return result


def safe_call(fn, *args, **kwargs):
    """Return (ok, value); exceptions are recorded as evidence."""
    try:
        return True, fn(*args, **kwargs)
    except Exception as exc:  # noqa
        return False, {"type": type(exc).__name__, "message": str(exc)}


def probe_dir(entry):
    directory = entry["dir"]
    kind = entry["kind"]
    from MUSCython import MultiStringBWTCython as CompiledBWT
    before = set(os.listdir(directory))
    ok, loaded = safe_call(CompiledBWT.loadBWT, directory, useMemmap=False,
                           logger=None)
    if not ok:
        return {"load_error": loaded}
    result = {"reader_class": type(loaded).__name__}
    ok, total = safe_call(loaded.getTotalSize)
    if not ok:
        return {"load_error": total}
    result["total_size"] = int(total)

    # getCharAtIndex
    chars = {}
    fm = {}
    for position in entry["positions"]:
        ok, value = safe_call(loaded.getCharAtIndex, position)
        if ok:
            chars[position] = int(value)
        else:
            chars[position] = value
        ok, row = safe_call(loaded.getFullFMAtIndex, position)
        if ok:
            fm[position] = [int(v) for v in row]
        else:
            fm[position] = row
    result["char_at"] = chars
    result["fm_at"] = fm

    # queries
    queries = {}
    for query in entry["queries"]:
        # Python 2: json.load returns unicode, but the compiled reader
        # declares its query parameter as `str` (bytes).
        query = str(query).encode("ascii") if isinstance(query, unicode) else query
        ok, value = safe_call(loaded.countOccurrencesOfSeq, query)
        if ok:
            queries[query] = int(value)
        else:
            queries[query] = value
    result["queries"] = queries

    # recovery from every dollar position
    recovery = []
    for position in range(int(total)):
        ok, value = safe_call(loaded.getCharAtIndex, position)
        if not ok:
            recovery.append({"error": value})
            break
        if int(value) == 0:
            ok, string = safe_call(loaded.recoverString, position)
            recovery.append(string if ok else {"error": string})
    result["recovery"] = recovery

    # derived-file inventory
    created = sorted(set(os.listdir(directory)) - before)
    result["derived_files"] = {name: sha256_file(os.path.join(directory, name))
                               for name in created}

    # cache regeneration (only on the flagged subset)
    if entry.get("regen"):
        for name in created:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                os.remove(path)
        ok, loaded2 = safe_call(CompiledBWT.loadBWT, directory,
                                useMemmap=False, logger=None)
        if not ok:
            result["regen"] = {"load_error": loaded2}
        else:
            created2 = sorted(set(os.listdir(directory)) - before)
            hashes2 = {name: sha256_file(os.path.join(directory, name))
                       for name in created2}
            result["regen"] = {
                "derived_files": hashes2,
                "identical": hashes2 == result["derived_files"],
                "total_size": int(loaded2.getTotalSize()),
            }
    return result


def main():
    argv = sys.argv[1:]
    manifest_path = None
    out_path = None
    index = 0
    while index < len(argv):
        if argv[index] == "--manifest":
            manifest_path = argv[index + 1]
            index += 2
        elif argv[index] == "--out":
            out_path = argv[index + 1]
            index += 2
        else:
            index += 1
    if not manifest_path or not out_path:
        raise SystemExit("usage: reader_probe.py --manifest M --out O")
    with open(manifest_path, "r") as handle:
        manifest = json.load(handle)
    regen_set = set(manifest.get("regen", []))
    results = {}
    for entry in manifest["dirs"]:
        entry = dict(entry)
        entry["regen"] = entry["case"] in regen_set
        results[entry["case"]] = probe_dir(entry)
    with open(out_path, "w") as handle:
        json.dump(results, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
