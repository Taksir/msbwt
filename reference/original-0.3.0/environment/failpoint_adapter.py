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
  m3c1  non-resumable post-hoc compression: call the frozen
       MUS.MSBWTGen.compressBWTPoolProcess once for the first bin tuple, then
       exit 86 before the parent join step runs.  The destination retains the
       complete comp_msbwt.npy.temp.<bin>.npy chunk and no final primary.
  m3c2  non-resumable post-hoc decompression: replicate the frozen
       MUS.MSBWTGen.decompressBWT preallocation and tuple dispatch, then call
       the frozen MUS.MSBWTGen.decompressBWTPoolProcess for the first tuple.
       If that worker completes, exit 86 before the second tuple; if the frozen
       worker itself raises (the committed decompression failure contract),
       record the natural failure and exit NATURAL_FAILURE_EXIT_CODE.
  m3c4  uniform byte builder: frozen MUSCython.MSBWTGenCython.createMsbwtFromSeqs
       interrupted at "Finished iteration 2 in".  The byte builder has no
       checkpoint scan, so a later CLI run restarts from scratch.
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import time

FAILPOINT_EXIT_CODE = 86
NATURAL_FAILURE_EXIT_CODE = 87
COMPRESSION_WORKSIZE = 1000000


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
                        help="dataset directory passed to the frozen worker")
    parser.add_argument("--case", required=True,
                        choices=("r1", "r2", "m3c1", "m3c2", "m3c4"),
                        help="recovery/failure case selector for the frozen entry point")
    parser.add_argument("--destination", default=None,
                        help="interrupted destination directory for m3c1/m3c2")
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


def run_byte_builder_case(args, logger):
    # The adapter is executed by script path, so its working directory (the
    # frozen build root passed by the harness) is not automatically on
    # sys.path.  Insert it so the compiled MUSCython extensions resolve.
    sys.path.insert(0, os.getcwd())
    from MUSCython import MSBWTGenCython
    MSBWTGenCython.createMsbwtFromSeqs(args.dataset, args.processes, logger)


def run_compression_worker_case(args, logger):
    """Call the frozen post-hoc compression worker once, then exit 86.

    The frozen ``compressBWT`` parent would otherwise compute the bin tuples,
    run every ``compressBWTPoolProcess`` worker, then join the temp chunks into
    ``comp_msbwt.npy`` and delete the temp files.  This adapter replicates only
    the dispatch of the first bin and exits before any parent join step, so the
    destination retains the complete ``comp_msbwt.npy.temp.<bin>.npy`` chunk
    and never receives the final primary.
    """
    sys.path.insert(0, os.getcwd())
    from MUS import MSBWTGen
    import numpy as np

    if args.destination is None:
        raise RuntimeError("m3c1 requires --destination")
    inputFN = os.path.join(args.dataset, "msbwt.npy")
    bwt = np.load(inputFN, 'r')
    numBins = max(args.processes, bwt.shape[0] / COMPRESSION_WORKSIZE)
    startIndex = 0
    endIndex = bwt.shape[0] / numBins
    tempFN = os.path.join(args.destination, 'comp_msbwt.npy.temp.0.npy')
    tup = (inputFN, startIndex, endIndex, tempFN)
    logger.info('Invoking compressBWTPoolProcess for first tuple {0}'.format(repr(tup)))
    ret = MSBWTGen.compressBWTPoolProcess(tup)
    logger.info('compressBWTPoolProcess returned size {0}'.format(ret[0]))
    write_json(args.record, {
        "adapter": "failpoint_adapter.py",
        "case": args.case,
        "dataset": args.dataset,
        "destination": args.destination,
        "exit_code": FAILPOINT_EXIT_CODE,
        "mode": "first-worker-completed",
        "first_tuple": {
            "input_fn": inputFN,
            "start_index": startIndex,
            "end_index": endIndex,
            "temp_fn": tempFN,
        },
        "worker_returned_size": ret[0],
        "num_bins": numBins,
    })
    logger.close()
    os._exit(FAILPOINT_EXIT_CODE)


def run_decompression_worker_case(args, logger):
    """Replicate the frozen decompression preallocation and first worker tuple.

    The frozen ``decompressBWT`` parent preallocates ``<dst>/msbwt.npy`` and
    computes the ``(src, dst, start, end)`` tuples.  This adapter replicates
    exactly those steps, calls the frozen ``decompressBWTPoolProcess`` for the
    first tuple, and exits 86 before the second tuple.  If the frozen worker
    itself raises (the committed profile-specific decompression failure), the
    natural failure is recorded and the adapter exits
    ``NATURAL_FAILURE_EXIT_CODE`` so the harness can distinguish an induced
    interruption from a worker failure.
    """
    sys.path.insert(0, os.getcwd())
    from MUS import MSBWTGen
    from MUS import MultiStringBWT
    import numpy as np

    if args.destination is None:
        raise RuntimeError("m3c2 requires --destination")
    msbwt = MultiStringBWT.CompressedMSBWT()
    msbwt.loadMsbwt(args.dataset, None)
    totalSize = msbwt.getTotalSize()
    outputFile = np.lib.format.open_memmap(
        os.path.join(args.destination, 'msbwt.npy'), 'w+', '<u1', (totalSize,))
    del outputFile

    worksize = COMPRESSION_WORKSIZE
    tups = [None] * (totalSize / worksize + 1)
    x = 0
    if totalSize > worksize:
        for x in xrange(0, totalSize / worksize):
            tups[x] = (args.dataset, args.destination, x * worksize, (x + 1) * worksize)
        tups[-1] = (args.dataset, args.destination, (x + 1) * worksize, totalSize)
    else:
        tups[0] = (args.dataset, args.destination, 0, totalSize)

    logger.info('Preallocated msbwt.npy totalSize={0}; tuples={1}'.format(totalSize, len(tups)))
    logger.info('Invoking decompressBWTPoolProcess for first tuple {0}'.format(repr(tups[0])))
    try:
        MSBWTGen.decompressBWTPoolProcess(tups[0])
    except Exception as exc:
        import traceback
        logger.error('decompressBWTPoolProcess first tuple raised {0}: {1}'.format(
            exc.__class__.__name__, exc))
        formatted = traceback.format_exc()
        traceback.print_exc()
        locations = [line.strip() for line in formatted.split("\n")
                     if 'File "' in line]
        write_json(args.record, {
            "adapter": "failpoint_adapter.py",
            "case": args.case,
            "dataset": args.dataset,
            "destination": args.destination,
            "exit_code": NATURAL_FAILURE_EXIT_CODE,
            "mode": "first-tuple-worker-failed-naturally",
            "exception_type": exc.__class__.__name__,
            "exception": str(exc),
            "traceback_locations": locations,
            "total_size": totalSize,
            "tuple_count": len(tups),
            "first_tuple": list(tups[0]),
        })
        logger.close()
        os._exit(NATURAL_FAILURE_EXIT_CODE)
    logger.info('decompressBWTPoolProcess first tuple completed')
    write_json(args.record, {
        "adapter": "failpoint_adapter.py",
        "case": args.case,
        "dataset": args.dataset,
        "destination": args.destination,
        "exit_code": FAILPOINT_EXIT_CODE,
        "mode": "first-tuple-completed",
        "total_size": totalSize,
        "tuple_count": len(tups),
        "first_tuple": list(tups[0]),
    })
    logger.close()
    os._exit(FAILPOINT_EXIT_CODE)


def run_case(args, logger):
    if args.case in ("r1", "r2"):
        # The adapter is executed by script path, so its working directory (the
        # frozen build root passed by the harness) is not automatically on
        # sys.path.  Insert it so the compiled MUSCython extensions resolve.
        sys.path.insert(0, os.getcwd())
        if args.case == "r1":
            from MUSCython import MSBWTCompGenCython
            MSBWTCompGenCython.createMsbwtFromSeqs(args.dataset, args.processes, logger)
        else:
            from MUSCython import MultimergeCython
            MultimergeCython.interleaveLevelMerge(args.dataset, args.processes, False, logger)
    elif args.case == "m3c4":
        run_byte_builder_case(args, logger)
    elif args.case == "m3c1":
        run_compression_worker_case(args, logger)
    elif args.case == "m3c2":
        run_decompression_worker_case(args, logger)
    else:  # pragma: no cover - argparse restricts the choices
        raise RuntimeError("unknown case {0}".format(args.case))


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
