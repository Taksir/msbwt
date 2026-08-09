#!/usr/bin/env python
"""External failpoint adapter for the implemented builder recovery milestone.

This script is Python 2.7 compatible and is harness infrastructure only.  It
never modifies frozen source.  It runs in a new process session, imports the
same frozen function that the CLI dispatches to, and supplies a logger that
recognizes one exact completed-checkpoint message.  When that message is seen
the logger writes a flushed failpoint record and calls ``os._exit(86)`` so the
outer harness can terminate any remaining process-group children and snapshot
the partial tree immutably.

Cases:
  r1  frozen MUSCython.MSBWTCompGenCython.createMsbwtFromSeqs(dataset, 1,
       logger)  -- direct uniform RLE checkpoint at "Finished iteration 2 in"
  r2  frozen MUSCython.MultimergeCython.interleaveLevelMerge(dataset, 1,
       False, logger)  -- nonuniform multimerge backup at
       "Backup creation finished."
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import time

FAILPOINT_EXIT_CODE = 86


def write_json(path, value):
    with open(path, "wb") as handle:
        encoded = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
        if not isinstance(encoded, bytes):
            encoded = encoded.encode("utf-8")
        handle.write(encoded)
        handle.write(b"\n")
        handle.flush()


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True,
                        help="preprocessed dataset directory passed to the frozen builder")
    parser.add_argument("--case", required=True, choices=("r1", "r2"),
                        help="recovery case selector for the frozen entry point")
    parser.add_argument("--failpoint-prefix", required=True,
                        help="exact completed-checkpoint logger message prefix")
    parser.add_argument("--record", required=True,
                        help="flushed failpoint record path outside the dataset")
    parser.add_argument("--log", required=True,
                        help="adapter-observed logger message log path")
    parser.add_argument("--processes", type=int, default=1,
                        help="process count passed to the frozen builder (canonical 1)")
    return parser.parse_args(argv)


class FailpointLogger(object):
    """Logger recognized by the frozen builder that exits 86 at a checkpoint.

    Every message is flushed immediately because ``os._exit`` bypasses normal
    interpreter shutdown.  The first message whose text starts with the exact
    failpoint prefix flushes a record file and terminates the process with
    ``FAILPOINT_EXIT_CODE``.  Message text uses ``str()`` so both the CLI logger
    format and the raw message are visible in the log for the harness to
    compare against the frozen log markers.
    """

    def __init__(self, log_path, failpoint_prefix, record_path, case, dataset):
        self._log_path = log_path
        self._failpoint_prefix = failpoint_prefix
        self._record_path = record_path
        self._case = case
        self._dataset = dataset
        self._triggered = False
        self._messages = []
        self._handle = open(log_path, "wb")
        self._closed = False

    def _emit(self, level, message):
        text = str(message)
        self._messages.append({"level": level, "message": text})
        self._handle.write(("[{0}] {1}: {2}\n".format(level, time.strftime("%Y-%m-%d %H:%M:%S"), text)).encode("utf-8"))
        self._handle.flush()
        if not self._triggered and text.startswith(self._failpoint_prefix):
            self._triggered = True
            self._write_record(text, level)
            self.close()
            os._exit(FAILPOINT_EXIT_CODE)

    def _write_record(self, triggering_message, level):
        write_json(self._record_path, {
            "adapter": "failpoint_adapter.py",
            "case": self._case,
            "dataset": self._dataset,
            "exit_code": FAILPOINT_EXIT_CODE,
            "failpoint_prefix": self._failpoint_prefix,
            "level": level,
            "messages": self._messages,
            "triggering_message": triggering_message,
        })

    def info(self, message):
        self._emit("INFO", message)

    def warning(self, message):
        self._emit("WARNING", message)

    def error(self, message):
        self._emit("ERROR", message)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._handle.flush()
        finally:
            self._handle.close()


def run_case(args, logger):
    if args.case == "r1":
        from MUSCython import MSBWTCompGenCython
        MSBWTCompGenCython.createMsbwtFromSeqs(args.dataset, args.processes, logger)
    else:
        from MUSCython import MultimergeCython
        MultimergeCython.interleaveLevelMerge(args.dataset, args.processes, False, logger)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if sys.version_info[:2] != (2, 7):
        sys.stderr.write("failpoint adapter requires CPython 2.7\n")
        return 127
    if os.path.lexists(args.record):
        sys.stderr.write("failpoint record already exists: {0}\n".format(args.record))
        return 126
    if os.path.lexists(args.log):
        sys.stderr.write("failpoint log already exists: {0}\n".format(args.log))
        return 126
    logger = FailpointLogger(
        args.log, args.failpoint_prefix, args.record, args.case, args.dataset
    )
    try:
        run_case(args, logger)
    except Exception as exc:
        import traceback
        logger.error("{0}: {1}".format(exc.__class__.__name__, exc))
        traceback.print_exc()
        logger.close()
        return 1
    logger.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
