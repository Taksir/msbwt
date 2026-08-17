# Windows parity matrix

Cross-platform parity comparison: Linux/WSL modern2 oracle vs native Windows
modern2 candidate.  All golden values are from the committed frozen evidence
(`compat/goldens/original-0.3.0/`) and modern2 test constants.

| Capability | Linux/WSL | Native Windows | Comparison | Result |
|-----------|:---------:|:--------------:|------------|--------|
| import MUS/MUSCython/CLI | ✓ | ✓ | semantics identical | PASS |
| import all 11 MUSCython modules | ✓ | ✓ | semantics identical | PASS |
| uniform pp+cfpp (-p 1) | ✓ | ✓ | bytes identical | PASS |
| uniform pp+cfpp (-p 2) | ✓ | ✓ | bytes identical | PASS |
| uniform pp+cfpp (-p 4) | ✓ | ✓ | bytes identical | PASS |
| uniform msbwt.npy SHA-256 | ✓ dd91d69e... | ✓ dd91d69e... | exact | PASS |
| uniform payload SHA-256 | ✓ 75134b48... | ✓ 75134b48... | exact | PASS |
| nonuniform pp+cfpp | ✓ | ✓ | bytes identical | PASS |
| nonuniform payload SHA-256 | ✓ 7a97b19a... | ✓ 7a97b19a... | exact | PASS |
| reader queries (ACGTN=3 AAAAA=1 CCCCC=1 AGCTA=0) | ✓ | ✓ | semantic | PASS |
| compress | ✓ | ✓ | bytes identical | PASS |
| compressed query parity | ✓ | ✓ | semantic | PASS |
| decompress | ✓ | ✓ | bytes identical | PASS |
| decompression contract | ✓ f536d60f... | ✓ f536d60f... | exact | PASS |
| merge -p 2 | ✓ | ✓ | bytes identical | PASS |
| merged BWT == golden | ✓ dd91d69e... | ✓ dd91d69e... | exact | PASS |
| process-count invariance (-p 1/2/4) | ✓ | ✓ | exact | PASS |
| all 464 py2 tests | ✓ (464 OK) | ✓ (464 OK, 2 skipped for pysam) | full suite | PASS |
| gzip FASTQ | ✓ | ✓ | semantic | PASS |
| byte reader (ByteBWTCython) | ✓ | ✓ | semantic | PASS |
| RLE reader (RLE_BWTCython) | ✓ | ✓ | semantic | PASS |
| FM/index construction | ✓ | ✓ | semantic | PASS |
| FM queries | ✓ | ✓ | semantic | PASS |
| recovery/checkpoint | ✓ | ✓ | semantic | PASS |
| 9 CLI commands | ✓ | ✓ | semantic | PASS |
| CFFQ (create from FASTQ) | ✓ | ✓ | semantic | PASS |
| PP (preprocess) | ✓ | ✓ | semantic | PASS |
| CFPP (build from preprocessed) | ✓ | ✓ | semantic | PASS |
| merge | ✓ | ✓ | semantic | PASS |
| query | ✓ | ✓ | semantic | PASS |
| massquery | ✓ | ✓ | semantic | PASS |
| compress | ✓ | ✓ | semantic | PASS |
| decompress | ✓ | ✓ | semantic | PASS |
| convert | ✓ | ✓ | semantic | PASS |
| frozen-source integrity | ✓ | ✓ | hash identical | PASS |
| pysam availability | ✓ (0.15.4) | ✗ (not installed; PEP 508 marker excludes it) | BAM input unsupported | DEVIATION |
| Python unicode width | UCS4 | UCS2 | inherent platform diff | DEVIATION |
| totalCounts.p pickle bytes | ✓ c038b778... | differs (shape longs) | semantic (same values) | DEVIATION |
