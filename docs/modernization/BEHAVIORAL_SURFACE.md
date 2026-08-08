# Behavioral surface and persistent-file inventory

This inventory is derived from source at commit `7503346`. “Public” means externally callable/importable or installed, not that the repository documented or tested it. Every listed surface needs characterization before its implementation changes.

## Import surface

Installed top-level packages are `MUS` and `MUSCython`. Their initializers are empty. The README recommends:

```python
import MUSCython.MultiStringBWTCython as MultiStringBWT
msbwt = MultiStringBWT.loadBWT('/path/to/directory')
msbwt.countOccurrencesOfSeq('CAT')
```

All of these module paths are externally importable and must initially be treated as public:

- `MUS.CommandLineInterface`, `MUS.MSBWTGen`, `MUS.MultiStringBWT`, `MUS.TranscriptBuilder`, `MUS.util`
- `MUSCython.AlignmentUtil`, `BasicBWT`, `ByteBWTCython`, `CompressToRLE`, `GenericMerge`, `LCPGen`, `LZW_BWTCython`, `MSBWTCompGenCython`, `MSBWTGenCython`, `MultimergeCython`, `MultiStringBWTCython`, `RLE_BWTCython`

Python 2 implicit-relative imports are observable because some users may also have imported sibling names after manipulating `sys.path`. Preserve documented/package-qualified imports first; measure unqualified usage before deciding whether shims are needed.

## Installed command

The distribution installs `bin/msbwt`, which calls `MUS.CommandLineInterface.mainRun()`.

| Command | Options and positionals | Source dispatch and outputs |
|---|---|---|
| global | `-V`, `--version`, `-h` | Reports script name plus `0.3.0`; argparse text/exit codes are contract surfaces |
| `cffq` | `[-p N] [-u|--uniform] [-c|--compressed] OUT FASTQ...` | Uniform: Cython column builder or direct RLE builder. Non-uniform: multimerge builder; `-c` only logs an error. Creates output directory during parsing. |
| `pp` | `[-u|--uniform] OUT FASTQ...` | Uniform writes column arrays, offsets, about. Non-uniform writes raw per-read BWT/offset files and no about file. |
| `cfpp` | `[-p N] [-u|--uniform] [-c|--compressed] DIR` | Consumes preprocessed artifacts; does not invoke wrapper cleanup. |
| `merge` | `[-p N] OUT INPUT...` | Intended for exactly two inputs via `GenericMerge`; default `-p 1` reaches an undefined local `numProcs` and raises `NameError`. More than two logs an error without work. |
| `query` | `[-d|--dump-seqs] DIR KMER` | Prints count; optionally recovered sequence and dollar ID per match. Loader may create auxiliary files. |
| `massquery` | `[-r|--rev-comp] DIR KMER_FILE OUTPUT` | CSV header `k-mer,counts` plus optional `revCompCounts`; one input line per output line. |
| `compress` | `[-p N] SRC_DIR DST_DIR` | Pure-Python RLE compressor writes `comp_msbwt.npy`; rejects identical source/destination strings after destination creation. |
| `decompress` | `[-p N] SRC_DIR DST_DIR` | Pure-Python RLE reader writes `msbwt.npy`. |
| `convert` | `[-i TEXT_BWT] DST_DIR` | Cython streaming text-to-RLE converter; stdin when `-i` is absent. Accepts `$ACGNT` and newline. |

CLI characterization must capture exit status, stdout, stderr, timestamped log lines, directory side effects on parse errors, overwrite behavior, option aliases/defaults, invalid process counts, missing/extra inputs, compressed/uncompressed preference, and partial artifacts after failure. Preserve source-visible bugs only in the legacy oracle; modern fixes require documented intentional deviations.

## Core compiled object API

`MultiStringBWTCython.loadBWT(bwtDir, useMemmap=True, logger=None)` returns:

- `ByteBWTCython.ByteBWT` when `msbwt.npy` exists;
- otherwise `RLE_BWTCython.RLE_BWT` when `comp_msbwt.npy` exists;
- otherwise `LZW_BWTCython.LZW_BWT` when `comp_msbwt.dat` exists.

The load preference is itself a contract. The common `BasicBWT` Python-callable methods are:

- statistics/search: `getTotalSize`, `getSymbolCount`, `getBinBits`, `countOccurrencesOfSeq`, `findIndicesOfStr`, `findIndicesOfRegex`, `findStrWithError`, `findPatternWithError`, `findReadsMatchingSeq`, `findKmerWithError`, `findKmerWithErrors`;
- low-level access: `getCharAtIndex`, `getOccurrenceOfCharAtIndex`, `iterInit`, `iterNext`, `getSequenceDollarID`, `recoverString`;
- pileup/LCP-assisted analysis: `countPileup`, `countSeqMatches`, `countStrandedSeqMatches`, `countStrandedSeqMatchesNoOther`, `findKmerThreshold`, `findKmerThresholdStranded`, `findKTOtherStranded`.

Subclasses add or expose:

- byte: `loadMsbwt`, `constructTotalCounts`, `constructFMIndex`, `getBWTRange`, `getFullFMAtIndex`;
- RLE: the same reader operations plus `getCompSize`, `decompressBlocks`, `removeStrings`, `findReadsMatchingSeqWithError`, and `findReadsMatchingSeqWithError2`;
- LZW: `getTotalTime`, `getCompSize`, `loadMsbwt`, `constructAuxiliary`, `decompressBin`, `getFullFMAtIndex`.

Important observable inconsistencies need tests: compiled methods accept/return Python 2 `bytes`/`str`; pure-Python methods accept strings; base `findReadsMatchingSeq` returns an empty set while RLE overrides it; LCP-assisted methods can be called without an LCP guard; `useMemmap=True` opens arrays read/write; invalid bytes silently map as `$` in compiled queries.

## Builder, preprocessing, and utility APIs

`MUSCython.MultiStringBWTCython` exports `createMSBWTFromSeqs`, `createMSBWTCompFromSeqs`, `createMSBWTFromFastq`, `createMSBWTCompFromFastq`, `createMSBWTFromBam`, `createMSBWTFromFasta`, `preprocessFastqs`, `preprocessBams`, `preprocessFastas` (spelling is public), `mergeSubSorts`, `cleanupTemporaryFiles`, `compareKmerProfiles`, `parseProfileLine`, and `reverseComplement`.

`MUSCython.MultimergeCython` separately exports sequence/FASTA/FASTQ builders and preprocessors, two-BWT merge, interleave merge, iterators, `formatSeqsForMerge`, `memoryBWT`, `interleaveLevelMerge`, and lower-level range/build functions. `GenericMerge` exports its own `mergeTwoMSBWTs` and `interleaveTwoBwts`.

`MSBWTGenCython` and the older `MUS.MSBWTGen` expose construction, compression, decompression, sequence-file writing, and auxiliary cleanup functions. Several are pool workers whose signatures may nevertheless have external callers. `MSBWTCompGenCython.createMsbwtFromSeqs` is the direct compressed uniform builder.

`MUS.util` exports CLI validators plus `fastaIterator` and `fastqIterator`. `MUS.MultiStringBWT` exposes older `BasicBWT`, `MultiStringBWT`, and `CompressedMSBWT` classes and parallel builder/profile/transcript functions. Do not assume these are replaceable by the Cython classes until import/use telemetry or compatibility policy says so.

## Other compiled/public analysis APIs

- `AlignmentUtil`: `fullAlign`, `fullED_score`, `fullED_minimize`, `fullAlign_noGO`, `alignChanges`. Return values, scoring/tie-breaking, empty strings, overflow, and bytes handling require goldens.
- `LCPGen`: `lcpGenerator` and `linearLcpGenerator`. Both return a `<u1` array; they do not save `lcps.npy` themselves.
- `CompressToRLE.compressInput`: raw text/stdin conversion with a handcrafted NumPy v1 header.
- `TranscriptBuilder`: `PathNode`, `PathEdge`, and `Assembler` with `extendSeed`/`getGraphResults`; settings dictionary keys form a configuration API.

`TranscriptBuilder` settings observed in source include `kmerSize`, `countK`, `pathThreshold`, `overloadThreshold`, `drawDollarTerminals`, `trackReads`, `trackPairs`, `isMerged`, `interleaveFN`, `useMemmap`, `maxDistance`, and required `numNodes`.

## Complete Python-callable symbol index

This table prevents grouped descriptions above from being mistaken for a representative sample. It lists every source-level `class`, `def`, or `cpdef` found in the current `.py`/`.pyx` files. Dunder constructors and class methods are shown under their class. C-only `cdef` helpers are internal compiled implementation surfaces; the installed `BasicBWT.pxd` exposes a separate downstream Cython ABI discussed below.

| Module/class | Python-callable symbols |
|---|---|
| `MUS.CommandLineInterface` | `initLogger`, `mainRun` |
| `MUS.MSBWTGen` | `bwtInitialInsertionsPoolCall`, `bwtPartialInsertPoolCall`, `debugDump`, `createFromSeqs`, `iterateCreateFromSeqs`, `writeSeqsToFiles`, `mergeNewMSBWTPoolCall`, `mergeNewMSBWT`, `compressBWT`, `compressBWTPoolProcess`, `decompressBWT`, `decompressBWTPoolProcess`, `clearAuxiliaryData` |
| `MUS.MultiStringBWT.BasicBWT` | `__init__`, `constructIndexing`, `countOccurrencesOfSeq`, `findIndicesOfStr`, `getSequenceDollarID`, `recoverString`, `getTotalSize` |
| `MUS.MultiStringBWT.MultiStringBWT` | `loadMsbwt`, `constructTotalCounts`, `constructFMIndex`, `getCharAtIndex`, `getBWTRange`, `getOccurrenceOfCharAtIndex`, `getFullFMAtIndex`, `createKmerProfile` |
| `MUS.MultiStringBWT.CompressedMSBWT` | `loadMsbwt`, `constructTotalCounts`, `constructFMIndex`, `getCharAtIndex`, `getBWTRange`, `decompressBlocks`, `getOccurrenceOfCharAtIndex`, `getFullFMAtIndex` |
| `MUS.MultiStringBWT` module | `loadBWT`, `createMSBWTFromSeqs`, `createMSBWTFromFastq`, `createMSBWTFromBam`, `customiter`, `preprocessFastqs`, `preprocessBams`, `mergeNewSeqs`, `compareKmerProfiles`, `parseProfileLine`, `interactiveTranscriptConstruction`, `reverseComplement` |
| `MUS.TranscriptBuilder.PathNode` | `__init__`, `firstTimeExtension`, `followNewHistory` |
| `MUS.TranscriptBuilder.PathEdge` | `__init__` |
| `MUS.TranscriptBuilder.Assembler` | `__init__`, `extendSeed`, `getGraphResults` |
| `MUS.util` | `readableFastqFile`, `readableNpyFile`, `writableNpyFile`, `newDirectory`, `existingDirectory`, `newOrExistingDirectory`, `validKmer`, `fastaIterator`, `fastqIterator` |
| `MUSCython.AlignmentUtil` | `fullAlign`, `fullED_score`, `fullED_minimize`, `fullAlign_noGO`, `alignChanges` |
| `MUSCython.BasicBWT.BasicBWT` | `__init__`, `getTotalSize`, `getSymbolCount`, `getBinBits`, `countOccurrencesOfSeq`, `findIndicesOfStr`, `findIndicesOfRegex`, `findStrWithError`, `findPatternWithError`, `findReadsMatchingSeq`, `findKmerWithError`, `findKmerWithErrors`, `getCharAtIndex`, `getOccurrenceOfCharAtIndex`, `iterInit`, `iterNext`, `getSequenceDollarID`, `recoverString`, `countPileup`, `countSeqMatches`, `countStrandedSeqMatches`, `countStrandedSeqMatchesNoOther`, `findKmerThreshold`, `findKmerThresholdStranded`, `findKTOtherStranded` |
| `MUSCython.ByteBWTCython.ByteBWT` | `loadMsbwt`, `constructTotalCounts`, `constructFMIndex`, `getCharAtIndex`, `getBWTRange`, `getOccurrenceOfCharAtIndex`, `getFullFMAtIndex` |
| `MUSCython.CompressToRLE` | `compressInput` |
| `MUSCython.GenericMerge` | `mergeTwoMSBWTs`, `interleaveTwoBwts` |
| `MUSCython.LCPGen` | `lcpGenerator`, `linearLcpGenerator` |
| `MUSCython.LZW_BWTCython.LZW_BWT` | `getTotalTime`, `getCompSize`, `loadMsbwt`, `constructAuxiliary`, `decompressBin`, `getCharAtIndex`, `getOccurrenceOfCharAtIndex`, `getFullFMAtIndex`, `iterInit`, `iterNext` |
| `MUSCython.MSBWTCompGenCython` | `createMsbwtFromSeqs`, `iterateMsbwtCreate` |
| `MUSCython.MSBWTGenCython` | `createMsbwtFromSeqs`, `iterateMsbwtCreate`, `compressBWT`, `compressBWTPoolProcess`, `decompressBWT`, `decompressBWTPoolProcess`, `clearAuxiliaryData`, `writeSeqsToFiles`, `createFromSeqs`, `iterateCreateFromSeqs`, `bwtInitialInsertionsPoolCall`, `bwtPartialInsertPoolCall`, `debugDump`, `testThreading`, `runFunc` |
| `MUSCython.MultimergeCython` | `createMSBWTFromSeqs`, `preprocessSeqs`, `createMSBWTFromFasta`, `preprocessFasta`, `createMSBWTFromFastq`, `preprocessFastqs`, `mergeTwoMSBWTs`, `mergeUsingInterleave`, `fastaIterator`, `fastqIterator`, `formatSeqsForMerge`, `memoryBWT`, `interleaveLevelMerge`, `levelIterator`, `buildViaMerge256`, `rangeIterator`, `rangeSolve_thread` |
| `MUSCython.MultiStringBWTCython` | `loadBWT`, `createMSBWTFromSeqs`, `createMSBWTCompFromSeqs`, `createMSBWTFromFastq`, `createMSBWTCompFromFastq`, `createMSBWTFromBam`, `createMSBWTFromFasta`, `customiter`, `preprocessFastqs`, `preprocessBams`, `preprocessFastas`, `mergeSubSorts`, `cleanupTemporaryFiles`, `compareKmerProfiles`, `parseProfileLine`, `reverseComplement` |
| `MUSCython.RLE_BWTCython.RLE_BWT` | `getCompSize`, `loadMsbwt`, `constructTotalCounts`, `constructFMIndex`, `getCharAtIndex`, `getBWTRange`, `decompressBlocks`, `getOccurrenceOfCharAtIndex`, `getFullFMAtIndex`, `removeStrings`, `findReadsMatchingSeq`, `findReadsMatchingSeqWithError`, `findReadsMatchingSeqWithError2` |

`BasicBWT.pxd` additionally exposes `bwtRange`, the cdef layout of `BasicBWT`, and Cython-callable helpers such as `fillBin`, `fillFmAtIndex`, `getOccurrenceOfCharAtRange`, `findRangeOfStr`, `countPileup_c`, `countOccurrencesOfSeq_c`, `getOccurrenceOfCharAtIndex_c`, and `findRangeOfStr_c`. Downstream `.pyx` modules may cimport this file, so ABI/source-compatibility tests and a deliberate versioning policy are required even though these names are not ordinary Python attributes.

## Input formats

| Input | Implemented interpretation | Required characterization |
|---|---|---|
| FASTQ/plain | Every line with zero-based index `1 mod 4` is sequence; names and qualities ignored | LF/CRLF, missing lines, blank lines, duplicate reads, lowercase/IUPAC, `$`, multiple files |
| FASTQ/gzip | Same logic via `gzip.open(..., 'r')` | gzip metadata does not affect dataset; bytes/text differences; corrupt/truncated streams |
| FASTA | API only; multiline records, first `>` starts record | gzip support differs by iterator; empty records; multiple files; final record |
| BAM | API only; assumes name sorting; restores orientation using flag `0x10`, pairs via `0x40` | exact pysam field/version behavior, secondary/supplementary records, missing mates, empty BAM |
| raw text BWT | `convert`; `$ACGNT` plus ignored LF | empty input, CRLF, no final newline, long runs, invalid symbols |
| dataset directory | Filename-based detection with no manifest/version | missing/truncated/mixed primary and stale auxiliary files |
| k-mer | CLI restricts characters to `$ACGNT`; API generally does not validate | empty, invalid, lowercase, Unicode/bytes, `$` placement |
| k-mer file | Text lines, only `\n` stripped | blank/CRLF/invalid lines and output escaping |

## Persistent file contract

The format is a directory protocol with implicit detection. “Primary” means not reproducible without another primary/input artifact. “Derived” means safely rebuildable in principle, although old code may not do so safely.

### Primary and provenance files

| Pattern | Producer | Exact source-defined representation | Consumer/status |
|---|---|---|---|
| `msbwt.npy` | all uncompressed builders, merge, decompress | Real `.npy`, C-order `uint8`, one symbol code 0..5 per BWT position | Preferred by generic loader; authoritative byte BWT |
| `comp_msbwt.npy` | RLE builder, compress, convert | Real `.npy` `uint8`; low 3 bits symbol, high 5 bits one base-32 run-length digit; consecutive same-symbol bytes are increasing powers, least-significant digit first | RLE reader; primary compressed BWT |
| `comp_msbwt.dat` | no writer in tree | Raw LZW bytes; byte 0 is bin-bit power, bytes 1..8 encode uncompressed length most-significant byte first, remaining coding is reader-defined | LZW reader only; legacy compatibility surface |
| `comp_offsets.npy` | no writer in tree | Real `.npy` read by LZW as integer offsets | LZW reader only; dtype/shape need legacy specimen |
| `about.npy` | sorted FASTQ/FASTA/BAM preprocessors | Real `.npy` structured array. Normal records: `(<u1 file_id, <u8 read_id)`; intended BAM: two additional mate fields `(<u1, <u8)` | Provenance, not recoverable from BWT; current BAM path is defective |
| `inter0.npy` | `GenericMerge` | Real `.npy` `uint8`, bit-packed choice of input BWT, one bit per merged BWT position | Retained merge provenance/interleave; transcript code appears to treat it as element-per-read, requiring characterization |
| `lcps.npy` | external caller must save `LCPGen` result | Real `.npy` `<u1`, one capped LCP value per uncompressed BWT position | Optional; unlocks LCP-assisted APIs and is modified by RLE deletion |

`origins.npy` is recognized by transcript code only to raise an unimplemented-handling exception. `abt.npy` is read by paired transcript tracking, but current preprocessing writes `about.npy`. These stale names are historical compatibility clues, not established working formats.

### Preprocessing files: mode-dependent collisions

| Construction path | `seqs` representation | `offsets` representation |
|---|---|---|
| uniform Cython column builder | `seqs.npy.0.npy` through `seqs.npy.(L-1).npy`, each real `.npy` `<u1` shape `(read_count,)`; columns are stored in reverse sequence order | real `offsets.npy`, `<u8`, shape `(1,)`, value `L` including terminal `$` |
| variable-length insertion builder | real `seqs.npy` in Cython or historical `seqs.npy.npy` in pure Python, `<u1` concatenated encoded sorted `$`-terminated sequences | real `.npy` `<u8`, shape `(read_count+1,)`, leading 0 then cumulative ends |
| `MultimergeCython` non-uniform path | headerless raw file named `seqs.npy`, `<u1`, concatenated per-read cyclic BWTs in input order | headerless raw file named `offsets.npy`, `<u8`; leading 0 plus cumulative ends for variable reads, or one read length for uniform mode |

These representations are not interchangeable merely because names match. `pp`/`cfpp`, `cffq`, public builder selection, `--uniform`, and the specific module determine the decoder.

### Derived query indexes

| File | Representation and meaning |
|---|---|
| `totalCounts.npy` | Real `.npy` `<u8`, shape `(6,)`, symbol totals; current compiled readers |
| `totalCounts.p` | Python pickle of counts; older pure reader; unsafe for untrusted input and Python-version sensitive |
| `fmIndex.npy` | Real `.npy` `<u8`, shape approximately `(ceil((N+1)/2048), 6)`; cumulative counts plus alphabet starts for byte BWT |
| `comp_fmIndex.npy` | Real `.npy` `<u8`, shape `(ceil((N+1)/2048), 6)`; RLE sampled cumulative/offset counts |
| `comp_refIndex.npy` | Real `.npy` `<u8`, one compressed-byte start reference per RLE sample |
| `lzw_fmIndex.npy` | Real `.npy` `<u8`, shape `(sample_count+1, 6)`; LZW sampled index |

`auxiliary.npy` and `backrefs.npy` are deleted by cleanup but have no current writer or consumer. They require historical/specimen research before removal from compatibility handling.

### Recovery and temporary artifacts

- uniform uncompressed: `inserts.initial.npy`, `inserts.*.npy`, `state.<symbol>.<column>.npy`, plus legacy `msbwt.npy.<key>.<column>.npy` and `*.tempInserts.npy` forms;
- uniform direct RLE: `state.<symbol>.<column>.dat`, `fmStarts.<column>.npy`, `fmDeltas.<column>.npy`, and `inserts.*.<column>.npy`;
- variable multimerge: `backup.<group_size>.npy`, `msbwt.temp.<offset>.npy`, `inter0.<offset>.npy`, and `inter1.<offset>.npy`;
- generic/old merge: `inter1.npy`, `temp.0.npy`, `temp.1.npy`;
- compression: `comp_msbwt.npy.temp.<bin>.npy`;
- preprocessing: `seqs.npy.sortTemp.<id>.npy`, `seqs.npy.temp.npy`;
- LCP: `lcpList.<level>.dat`, raw little-endian uint64 work queues;
- deletion: `deletion_indices.dat`, raw indexes, deleted on successful completion.

Recovery artifacts are observable after interruption and some are deliberately consumed on restart. Tests must cover clean success, controlled interruption, restart, stale unrelated artifacts, and cleanup boundaries.

## Output formats beyond datasets

- `massquery` produces comma-separated text with a fixed header and no quoting.
- `createKmerProfile` writes `total,<sqrt(sum(count^2))>` then sorted `kmer,count` lines.
- `compareKmerProfiles` returns `(max absolute normalized delta, Euclidean delta, sum of deltas, normalized dot product)`.
- alignment APIs return lists/tuples/scores defined by their implementations; transcript assembly returns node and edge tuple lists.
- logger output goes to stdout with `[YYYY-MM-DD HH:MM:SS] LEVEL: message`; query count/data share that stream.

## Configuration and implicit constants

There are no environment-variable or config-file inputs. Important constants are embedded in code: alphabet size 6, FM sample bin `2^11`, RLE 3 symbol bits/5 count bits, preprocessing chunk sizes, compression bins, multimerge thresholds, and query algorithm thresholds. Changing any can affect files, ordering, performance, logging, or recovery and therefore requires characterization.
