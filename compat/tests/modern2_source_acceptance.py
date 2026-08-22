"""Accepted frozen->modern2 source-diff whitelist (M3-R64-W5 rebaseline).

The frozen original under ``MUS``/``MUSCython`` remains the untouched oracle;
``packages/msbwt-modern2`` may differ ONLY by the line sets below.  Every
accepted line is backed by a documented compatibility entry
(``COMPATIBILITY.md`` milestones 3-9 / W-* entries) or an accepted
Windows-portability repair:

  * milestone 3-6 reader index/count corrections (int() conversions,
    np.add.at float64-bincount replacement)
  * milestone 9 ``numProcs = 1`` CLI fix
  * ``#cython: language_level=2`` headers on migrated pyx modules
  * W-PYSAM lazy ``import pysam``
  * W-BINARY-IO binary-mode opens (pickle framing / CSV newline contract)
  * Windows-portability ``np.save()`` .npy-header normalization
    (``_int_shape`` helper + open_memmap), byte-identical to Linux

Any FUTURE modern2 source line outside these sets fails the guard tests --
rebaselining then requires reviewing and documenting the new drift here.
Do not add entries silently.
"""

# MUS/MultiStringBWT.py
# Milestone 3-6 index fixes; W-PYSAM lazy import; W-BINARY-IO pickle opens; float64 bincount replacement
ACCEPTED_ADDED_MUS_MULTISTRINGBWT_PY = frozenset([
    '    ',
    '            # Windows text-mode newline translation',
    '            # Windows text-mode newline translation',
    '            # Windows text-mode newline translation',
    '            # Windows text-mode newline translation',
    '            # binary mode: pickle framing bytes must not be rewritten by',
    '            # binary mode: pickle framing bytes must not be rewritten by',
    '            # binary mode: pickle framing bytes must not be rewritten by',
    '            # binary mode: pickle framing bytes must not be rewritten by',
    '            endRange = int(self.refFM[binID+1])+1',
    '            endRange = int(self.refFM[binID+1])+1',
    '            endRange = int(self.refFM[endBlock+1])+1',
    "            fp = open(abtFN, 'rb')",
    "            fp = open(abtFN, 'rb')",
    "            fp = open(abtFN, 'wb+')",
    "            fp = open(abtFN, 'wb+')",
    '            np.add.at(ret, letters[0:x-1], counts[0:x-1])',
    '            ret[s:s+runLength] = letters[lInd]',
    '            runLength = int(counts[lInd])',
    '            s += runLength',
    '    # deferred until a BAM file is actually preprocessed.  On Linux this',
    '    # for BAM input, and no pysam distribution exists for CPython 2.7 on',
    '    # native Windows.  FASTQ input never touches pysam, so the import is',
    '    # preserves the historical behavior (pysam is still required for BAM).',
    '    # pysam is imported lazily here (not at module scope): it is only needed',
    '    import pysam',
])
ACCEPTED_REMOVED_MUS_MULTISTRINGBWT_PY = frozenset([
    '            endRange = self.refFM[binID+1]+1',
    '            endRange = self.refFM[binID+1]+1',
    '            endRange = self.refFM[endBlock+1]+1',
    "            fp = open(abtFN, 'r')",
    "            fp = open(abtFN, 'r')",
    "            fp = open(abtFN, 'w+')",
    "            fp = open(abtFN, 'w+')",
    '            ret += np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)',
    '            ret[s:s+counts[lInd]] = letters[lInd]',
    '            s += counts[lInd]',
    'import pysam#@UnresolvedImport',
])

# MUS/CommandLineInterface.py
# Milestone 9 numprocs fix; W-BINARY-IO CSV output open
ACCEPTED_ADDED_MUS_COMMANDLINEINTERFACE_PY = frozenset([
    "        # binary mode: on Windows text mode would write '\\r\\n' line endings,",
    '        # diverging from the Linux byte contract of the CSV output.',
    '        numProcs = 1',
    "        output = open(args.outputFile, 'wb+')",
])
ACCEPTED_REMOVED_MUS_COMMANDLINEINTERFACE_PY = frozenset([
    "        output = open(args.outputFile, 'w+')",
])

# MUS/MSBWTGen.py
# Windows portability: np.save shape normalization comments/_int_shape usage in construction temp writers
ACCEPTED_ADDED_MUS_MSBWTGEN_PY = frozenset([
    '        copyArr.base.close()',
    "    # (Windows portability) np.load(fn, 'r') keeps the last temporary file",
    '    # (Windows portability) totalSize can be a py2 long on Windows (numpy',
    '    # fails on Windows while a mapping is open).',
    "    # intp arithmetic), which would write an 'L'-suffixed shape literal into",
    '    # memory-mapped here; close it so the files can be removed (os.remove()',
    '    # the .npy header and diverge from the Linux byte contract; normalize it.',
    "    finalBWT = np.lib.format.open_memmap(outputFN, 'w+', '<u1', (int(totalSize),))",
    "    if getattr(copyArr, 'base', None) is not None:",
])
ACCEPTED_REMOVED_MUS_MSBWTGEN_PY = frozenset([
    "    finalBWT = np.lib.format.open_memmap(outputFN, 'w+', '<u1', (totalSize,))",
])

# MUSCython/GenericMerge.pyx
# language_level=2 header; _int_shape helper; np.save normalization comments/open_memmap
ACCEPTED_ADDED_MUSCYTHON_GENERICMERGE_PYX = frozenset([
    '',
    '                                        _int_shape((<object>inter0).shape))',
    '            (<object>inter1).base.close()',
    '        # (Windows portability) close the interleave mapping before removal.',
    '        # (Windows portability) np.save() writes py2-long shape elements into',
    "        # the .npy header on Windows ('L'-suffixed literals), diverging from",
    '        # the Linux byte contract; open_memmap() with a normalized int shape',
    '        # writes byte-identical headers everywhere.',
    "        _mm = np.lib.format.open_memmap(interleaveFN0, 'w+', inter0.dtype,",
    '        _mm[:] = inter0',
    '        del _mm',
    '        if (<object>inter1).base is not None:',
    '    return tuple(int(x) for x in shape)',
    '# (Windows portability) np.save() writes py2-long shape elements into .npy',
    '# Linux.  Plain Python def so it stays callable from Cython code.',
    '# headers on Windows; normalize to ints so headers are byte-identical to',
    '#cython: language_level=2',
    'def _int_shape(shape):',
])
ACCEPTED_REMOVED_MUSCYTHON_GENERICMERGE_PYX = frozenset([
    '        np.save(interleaveFN0, inter0)',
])

# MUSCython/MultimergeCython.pyx
# language_level=2 header; _int_shape helper; np.save normalization comments/open_memmap; cumsum dtype comment
ACCEPTED_ADDED_MUSCYTHON_MULTIMERGECYTHON_PYX = frozenset([
    '',
    '                                        _int_shape((<object>inter0).shape))',
    '                                        _int_shape((<object>seqs).shape))',
    '            (<object>inter0).base.close()',
    '            (<object>inter1).base.close()',
    '            (<object>inter1).base.close()',
    '            (<object>msbwtOut).base.close()',
    '        # (Windows portability) close the interleave mapping before removal.',
    '        # (Windows portability) close the interleave mappings before removal.',
    '        # (Windows portability) close the mapping before removal.',
    '        # (Windows portability) np.save() writes arr.shape elements (py2',
    '        # (Windows portability) np.save() writes py2-long shape elements into',
    '        # diverging from the Linux byte contract; open_memmap() with a',
    "        # longs on Windows) into the .npy header as 'L'-suffixed literals,",
    '        # normalized int shape writes byte-identical headers everywhere.',
    "        # the .npy header on Windows ('L'-suffixed literals), diverging from",
    '        # the Linux byte contract; open_memmap() with a normalized int shape',
    '        # writes byte-identical headers everywhere.',
    "        _mm = np.lib.format.open_memmap(interleaveFN0, 'w+', inter0.dtype,",
    "        _mm = np.lib.format.open_memmap(mergedDir+'/msbwt.npy', 'w+', seqs.dtype,",
    '        _mm[:] = inter0',
    '        _mm[:] = seqs',
    '        del _mm',
    '        del _mm',
    '        if (<object>inter0).base is not None:',
    '        if (<object>inter1).base is not None:',
    '        if (<object>inter1).base is not None:',
    '        if (<object>msbwtOut).base is not None:',
    "    # (Windows portability) np.cumsum(u4) - u4 promotes to C 'unsigned long',",
    '    # keeps the fmOffsets result 64-bit on both platforms with identical',
    '    # values.',
    '    # which is 32-bit on Windows (64-bit on Linux); forcing the cumsum dtype',
    "    cdef np.ndarray[np.uint64_t, ndim=1, mode='c'] fmOffsets = np.cumsum(totalCounts, dtype='<u8')-totalCounts",
    '    return tuple(int(x) for x in shape)',
    '# (Windows portability) np.save() writes py2-long shape elements into .npy',
    '# Linux.  Plain Python def so it stays callable from Cython code.',
    '# headers on Windows; normalize to ints so headers are byte-identical to',
    '#cython: language_level=2',
    'def _int_shape(shape):',
])
ACCEPTED_REMOVED_MUSCYTHON_MULTIMERGECYTHON_PYX = frozenset([
    '        np.save(interleaveFN0, inter0)',
    "        np.save(mergedDir+'/msbwt.npy', seqs)",
    "    cdef np.ndarray[np.uint64_t, ndim=1, mode='c'] fmOffsets = np.cumsum(totalCounts)-totalCounts",
])

# MUSCython/RLE_BWTCython.pyx
# language_level=2 header; milestone-5 endRange int() fix; _int_shape helper; np.save normalization comments/open_memmap
ACCEPTED_ADDED_MUSCYTHON_RLE_BWTCYTHON_PYX = frozenset([
    '',
    '                                            _int_shape((<object>self.totalCounts).shape))',
    '            # (Windows portability) np.save() writes py2-long shape elements',
    '            # diverging from the Linux byte contract; open_memmap() with a',
    "            # into the .npy header on Windows ('L'-suffixed literals),",
    '            # normalized int shape writes byte-identical headers everywhere.',
    '            (<object>delIndices).base.close()',
    "            _mm = np.lib.format.open_memmap(abtFN, 'w+', self.totalCounts.dtype,",
    '            _mm[:] = self.totalCounts',
    '            del _mm',
    '            endRange = int(self.refFM[endBlock+1])+1',
    '        # (Windows portability) close the deletion-index mapping first;',
    "        # 0x0A bytes inside the binary index data into '\\r\\n' pairs.",
    '        # binary mode: on Windows the C runtime would otherwise translate',
    '        # os.remove() fails on Windows while a memory mapping is open.',
    "        cdef FILE * fp = fopen(deletionFN, 'w+b')",
    '        if (<object>delIndices).base is not None:',
    '    return tuple(int(x) for x in shape)',
    '# (Windows portability) np.save() writes py2-long shape elements into .npy',
    '# Linux.  Plain Python def so it stays callable from Cython code.',
    '# headers on Windows; normalize to ints so headers are byte-identical to',
    '#cython: language_level=2',
    'def _int_shape(shape):',
])
ACCEPTED_REMOVED_MUSCYTHON_RLE_BWTCYTHON_PYX = frozenset([
    '            endRange = self.refFM[endBlock+1]+1',
    '            np.save(abtFN, self.totalCounts)',
    "        cdef FILE * fp = fopen(deletionFN, 'w+')",
])

# MUSCython/CompressToRLE.pyx
# language_level=2 header
ACCEPTED_ADDED_MUSCYTHON_COMPRESSTORLE_PYX = frozenset([
    '        # below is binary so the RLE payload bytes are never rewritten.',
    '        # bytes (the BWT text input is newline-terminated).  The OUTPUT stream',
    "        # endings to '\\n', matching the Linux behavior for the same input",
    '        # text mode on the input: Windows text-mode reads translate CRLF line',
    "    # (0x0A) bytes inside the RLE payload into '\\r\\n' pairs, corrupting the",
    "    # binary mode: on Windows the C runtime would otherwise translate '\\n'",
    '    # output; Linux text mode is already byte-transparent.',
    "    cdef FILE * outputStream = fopen(outputFN, 'w+b')",
    '#cython: language_level=2',
])
ACCEPTED_REMOVED_MUSCYTHON_COMPRESSTORLE_PYX = frozenset([
    "    cdef FILE * outputStream = fopen(outputFN, 'w+')",
])

# MUS/util.py
# Windows-portability atomic_replace/atomic_write_json helpers used by validate drivers
ACCEPTED_ADDED_MUS_UTIL_PY = frozenset([
    '',
    '',
    '',
    '',
    '',
    '            os.fsync(fp.fileno())',
    '            pass',
    '        except (OSError, IOError):',
    '        fp.flush()',
    '        json.dump(document, fp, indent=2, sort_keys=True)',
    '        os.remove(dest_path)',
    '        os.rename(source_path, dest_path)',
    '        os.rename(source_path, dest_path)',
    '        os.replace(source_path, dest_path)',
    '        try:',
    '    """',
    '    """Replace dest_path with source_path atomically.',
    '    """Write a JSON document atomically: tmp file -> flush -> rename."""',
    '    Python 2.7 has no os.replace.  On POSIX, os.rename is atomic; on',
    '    Windows, os.rename fails if dest_path already exists.  This helper',
    '    atomic_replace(tmp_path, str(path))',
    '    dir_name = os.path.dirname(path) or "."',
    '    elif os.name == "nt" and os.path.exists(dest_path):',
    '    else:',
    '    if hasattr(os, "replace"):',
    '    import json',
    '    removes dest_path first on Windows before renaming.',
    '    tmp_path = os.path.join(dir_name, ".tmp_%s.json" % os.getpid())',
    '    with open(tmp_path, "w") as fp:',
    'def atomic_replace(source_path, dest_path):',
    'def atomic_write_json(path, document):',
])
ACCEPTED_REMOVED_MUS_UTIL_PY = frozenset([
])

# MUSCython/MSBWTCompGenCython.pyx
# Windows-portability np.save normalization edits
ACCEPTED_ADDED_MUSCYTHON_MSBWTCOMPGENCYTHON_PYX = frozenset([
    '    ',
    '        ',
    "            # 0x0A bytes inside the binary state data into '\\r\\n' pairs.",
    '            # binary mode: on Windows the C runtime would otherwise translate',
    '            (<object>tempBWT).base.close()',
    "            tempFP = fopen(tempFN, 'w+b')",
    "        # 'r+') mappings open, and Windows refuses to remove files that have",
    "        # (Windows portability) close this state file's mapping before it is",
    '        # (Windows portability) wait for the workers to exit before removing',
    '        # (Windows text mode would corrupt 0x0A bytes in the BWT data).',
    '        # an open memory mapping.',
    '        # binary mode: see the note at the state-file creation above',
    '        # removed below (os.remove() fails on Windows while a mapping is open).',
    '        # the state files below: a still-running worker keeps its np.load(..,',
    '        (<object>initialInserts).base.close()',
    '        if (<object>tempBWT).base is not None:',
    '        myPool.join()',
    "        nextBwtFP = fopen(nextSymbolFN, 'w+b')",
    '    # (Windows portability) the parent no longer needs its own view of the',
    '    # below can remove inserts.initial.npy (os.remove() fails on Windows',
    '    # initial-inserts file; close the mapping so the first column cleanup',
    '    # while a mapping is open).',
    '    if initialInserts is not None and (<object>initialInserts).base is not None:',
    '#cython: language_level=2',
])
ACCEPTED_REMOVED_MUSCYTHON_MSBWTCOMPGENCYTHON_PYX = frozenset([
    "            tempFP = fopen(tempFN, 'w+')",
    "        nextBwtFP = fopen(nextSymbolFN, 'w+')",
])

# MUSCython/MSBWTGenCython.pyx
# Windows-portability np.save normalization edits
ACCEPTED_ADDED_MUSCYTHON_MSBWTGENCYTHON_PYX = frozenset([
    '    ',
    '                (<object>currentBwt).base.close()',
    '            # (Windows portability) close the read mapping before the rename;',
    '            # Windows cannot rename a file that still has an open memory',
    '            # mapping (sharing violation).',
    '            (<object>copyArr).base.close()',
    '            if (<object>currentBwt).base is not None:',
    "        # 'r+') mappings open, and Windows refuses to remove files that have",
    "        # (Windows portability) np.load(fn, 'r+') returns a memory-mapped",
    '        # (Windows portability) wait for the workers to exit before removing',
    '        # an open memory mapping.',
    '        # array; close each mapping here so the intermediate files can be',
    '        # removed below (os.remove() fails on Windows while a mapping is open).',
    '        # the state files below: a still-running worker keeps its np.load(..,',
    '        (<object>initialInserts).base.close()',
    '        (<object>initialInserts).base.close()',
    '        (<object>tempBWT).base.close()',
    '        if (<object>copyArr).base is not None:',
    '        myPool.join()',
    "    # (Windows portability) close the parent's own mappings first: the",
    '    # (Windows portability) the parent no longer needs its own view of the',
    '    # below can remove inserts.initial.npy (os.remove() fails on Windows',
    '    # initial-inserts file; close the mapping so the first column cleanup',
    '    # initial-inserts memmap and the last state-file read mapping would',
    '    # otherwise block os.remove() below.',
    '    # while a mapping is open).',
    '    if (<object>initialInserts).base is not None:',
    '    if (<object>initialInserts).base is not None:',
    '    if (<object>tempBWT).base is not None:',
    '#cython: language_level=2',
])
ACCEPTED_REMOVED_MUSCYTHON_MSBWTGENCYTHON_PYX = frozenset([
])

# MUSCython/MultiStringBWTCython.pyx
# Windows-portability np.save normalization edits
ACCEPTED_ADDED_MUSCYTHON_MULTISTRINGBWTCYTHON_PYX = frozenset([
    '    ',
    '        (<object>seqArrayMmap).base.close()',
    '    # (Windows portability) Cython holds the typed memmap view alive until the',
    '    # deferred until a BAM file is actually preprocessed.  On Linux this',
    '    # explicitly close it so the temporary file can be removed (os.remove()',
    '    # fails with a sharing violation on Windows while a mapping is open).',
    '    # for BAM input, and no pysam distribution exists for CPython 2.7 on',
    '    # function epilogue, so the underlying file mapping is still open here;',
    '    # native Windows.  FASTQ input never touches pysam, so the import is',
    '    # preserves the historical behavior (pysam is still required for BAM).',
    '    # pysam is imported lazily here (not at module scope): it is only needed',
    '    if (<object>seqArrayMmap).base is not None:',
    '    import pysam',
    '#cython: language_level=2',
])
ACCEPTED_REMOVED_MUSCYTHON_MULTISTRINGBWTCYTHON_PYX = frozenset([
    'import pysam#@UnresolvedImport',
])


def assert_source_within_acceptance(testcase, rel_path):
    """Assert the modern2 file differs from frozen only by accepted lines."""
    import difflib
    import sys
    mod = sys.modules[type(testcase).__module__]
    repo = getattr(testcase, "REPOSITORY_ROOT", None)
    if repo is None:
        repo = getattr(mod, "REPOSITORY_ROOT")
    frozen = repo / rel_path
    if not frozen.exists():
        pkg = getattr(testcase, "PACKAGE", None)
        if pkg is None:
            pkg = getattr(mod, "PACKAGE")
        frozen = pkg.parent.parent / rel_path
    pkg = getattr(testcase, "PACKAGE", None)
    if pkg is None:
        pkg = getattr(mod, "PACKAGE")
    modern = pkg / rel_path
    a = frozen.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    b = modern.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    added, removed = [], []
    for line in difflib.unified_diff(a.splitlines(), b.splitlines(),
                                     lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    key = rel_path.replace("/", "_").replace(".", "_").upper()
    acc_a = globals()["ACCEPTED_ADDED_" + key]
    acc_r = globals()["ACCEPTED_REMOVED_" + key]
    unexpected_added = sorted(set(added) - acc_a)
    unexpected_removed = sorted(set(removed) - acc_r)
    testcase.assertFalse(unexpected_added,
                         "%s: unexpected added lines" % rel_path)
    testcase.assertFalse(unexpected_removed,
                         "%s: unexpected removed lines" % rel_path)
    return added, removed
