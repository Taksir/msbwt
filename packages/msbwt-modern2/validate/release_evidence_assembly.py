#!/usr/bin/env python3
"""Assemble the enhanced-modern2 release-candidate evidence JSON.

Called by validate/enhanced-release-candidate.sh after all gates finish;
kept as a standalone script (no shell heredoc) so the driver tail cannot
wedge on stdin handling.

Args: RESULT RES_PATH WORK_BASE SDIST_NAME SDIST_SHA SDIST_SIZE
      WHEEL_NAME WHEEL_SHA WHEEL_SIZE COMMIT BRANCH EVIDENCE_OUT
"""

import json
import os
import re
import sys


def main():
    (result, res_path, work, sdist_name, sdist_sha, sdist_size,
     wheel_name, wheel_sha, wheel_size, commit, branch,
     evidence_out) = sys.argv[1:]
    entries = []
    with open(res_path) as handle:
        res_text = handle.read()
    for ln in res_text.strip().splitlines():
        m = re.match(r"^(PASS|FAIL): (.*)$", ln)
        if m:
            entries.append({"status": m.group(1), "check": m.group(2)})

    def import_report(label):
        try:
            with open(os.path.join(work, "import-%s" % label,
                                   "report.json")) as handle:
                return json.load(handle)
        except Exception:
            return {}

    def gate_report(label):
        try:
            with open(os.path.join(work, "gate-%s" % label,
                                   "gate-report.json")) as handle:
                return json.load(handle)
        except Exception:
            return {}

    evidence = {
        "format": "msbwt-modern2-enhanced-release-candidate-evidence-v1",
        "distribution": "msbwt-modern2",
        "version": "0.3.0",
        "branch": branch,
        "commit": commit,
        "status": "release-candidate",
        "result": result,
        "checks": entries,
        "n_pass": sum(1 for e in entries if e["status"] == "PASS"),
        "n_fail": sum(1 for e in entries if e["status"] == "FAIL"),
        "build": {
            "environment":
                "pinned python27-modern2 prefix (bootstrap-modern2.sh)",
            "commands": ["python setup.py sdist",
                         "python setup.py bdist_wheel"],
            "disposable_copy": True,
            "cython_policy":
                "exactly 3.0.12, language_level=2; generated C committed",
        },
        "sdist": {
            "filename": sdist_name,
            "sha256": sdist_sha,
            "size": int(sdist_size),
        },
        "wheel": {
            "filename": wheel_name,
            "sha256": wheel_sha,
            "size": int(wheel_size),
            "tag": wheel_name.split("-", 2)[2].rsplit(".whl", 1)[0],
        },
        "install_environments": [],
        "enhanced_gate": {},
        "tools": {},
        "release_blockers": [],
    }
    for label in ("wheel", "sdist"):
        rep = import_report(label)
        gate = gate_report(label)
        evidence["install_environments"].append({
            "id": "fresh-prefix (%s install)" % label,
            "artifact_installed":
                sdist_name if label == "sdist" else wheel_name,
            "imports": {
                "module_failures": [
                    k for k, v in rep.get("modules", {}).items()
                    if not v.get("ok")
                ],
                "not_site_packages": [
                    v.get("__file__")
                    for v in rep.get("modules", {}).values()
                    if v.get("__file__")
                    and "site-packages" not in v.get("__file__", "")
                ],
                "sys_path_leaks": rep.get("sys_path_leaks", []),
            },
        })
        evidence["enhanced_gate"][label] = {
            "mismatch_count": gate.get("mismatch_count"),
            "integrated_comparisons":
                gate.get("integrated_package", {}).get("comparisons"),
            "reduced_comparisons":
                gate.get("reduced_package", {}).get("comparisons"),
            "integrated_N":
                gate.get("benchmark", {}).get("integrated_N"),
            "reduced_N":
                gate.get("benchmark", {}).get("reduced_N"),
            "rebuild_payload_equal":
                gate.get("reduced_package", {}).get(
                    "rebuild_payload_equal"),
            "rebuild_whole_file_equal":
                gate.get("reduced_package", {}).get(
                    "rebuild_whole_file_equal"),
        }
    out_dir = os.path.dirname(evidence_out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(evidence_out, "w") as handle:
        json.dump(evidence, handle, indent=1, sort_keys=True)
    print("evidence written to %s" % evidence_out)
    print("RESULT: %s" % result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
