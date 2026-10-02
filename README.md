# msBWT

Tools for building, merging, compressing and querying multi-string
Burrows–Wheeler transforms (MSBWTs) of sequencing reads. An MSBWT is a compact,
searchable index of a whole set of reads: you can count any k-mer in it without
going back to the FASTQ files.

This is a maintenance fork of [holtjma/msbwt](https://github.com/holtjma/msbwt)
by James Holt and Leonard McMillan (UNC-Chapel Hill). The original algorithms,
command-line interface, import paths and on-disk formats are kept. The fork adds
a Python 3 port and some extra features for working with merged indexes.

## Install

The Python 3 port is `msbwt-modern3` (`packages/msbwt-modern3`). It needs
CPython 3.14 or newer, NumPy 2.5 or newer, and a C compiler, because the core is
Cython; installing from source takes a few minutes while it compiles.

```bash
git clone https://github.com/Taksir/msbwt
cd msbwt
pip install ./packages/msbwt-modern3
```

A PyPI release under the name `pymsbwt` is planned but not published yet. The
Python 2.7 line (`packages/msbwt-modern2`) is frozen and not on PyPI; its README
has the install steps. Don't install both distributions into one environment:
they provide the same `MUS` and `MUSCython` packages and the same `msbwt` command.

## Build an index

Reads are plain or gzipped FASTQ. Use `-u` when every read has the same length;
without it the merge-based builder is used.

```bash
# straight from FASTQ
msbwt cffq -p 1 -u OUT reads-a.fastq reads-b.fastq

# or in two steps
msbwt pp -u OUT reads-a.fastq reads-b.fastq
msbwt cfpp -p 1 -u OUT

# merge two existing indexes
msbwt merge -p 1 MERGED A_DIR B_DIR

# convert between the byte format and the run-length (RLE) format
msbwt compress -p 1 OUT OUT.rle
msbwt decompress -p 1 OUT.rle OUT.byte

# make an RLE index from a raw BWT text file
msbwt convert -i raw.txt OUT
```

`-p` sets the number of processes. Input that ends partway through a FASTQ record
is rejected with an error.

## Query

```bash
# count one k-mer (the last line printed is the count)
msbwt query OUT ACGTA

# count many k-mers, one per line, written as CSV
msbwt massquery OUT kmers.txt counts.csv
```

From Python:

```python
from MUSCython import MultiStringBWTCython

bwt = MultiStringBWTCython.loadBWT("OUT")
print(bwt.countOccurrencesOfSeq("ACGTA"))
```

K-mers may use the characters `$ A C G N T`. Reverse complements are not
counted unless you pass `-r` to `massquery`.

## Extra tools

Installing the package also adds these commands, each with `--help`:

| Command | What it does |
|---|---|
| `msbwt-remove-sources` | drop chosen samples from a merged index without rebuilding |
| `msbwt-lcp` | add an LCP array to an existing index |
| `msbwt-bwt-tags` | attach row-aligned arrays to an index |
| `msbwt-quality-sidecar` | store FASTQ quality strings alongside the index |
| `msbwt-retrofit-read-provenance` | record which read each BWT row came from |
| `msbwt-benchmark-index` | report storage use of an index |

Per-sample counts over a merged index are available from Python through
`MUS.MultiSourceQuery.MultiSourceBWT`. The wiki has worked examples.

## Index files

A built index is a directory of `.npy` files; `msbwt.npy` (or `comp_msbwt.npy`
for RLE) is the one that matters and the rest can be rebuilt. The format is
documented on the wiki and in [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## Limits

- BAM input is not supported in the Python 3 port.
- Tested on Windows x86-64 and Linux x86-64 with CPython 3.14. Other platforms
  and Python versions are untested, so don't assume they work.
- Behaviour changes from the original are listed in
  [COMPATIBILITY.md](COMPATIBILITY.md).

## More documentation

- [Wiki](https://github.com/Taksir/msbwt/wiki): usage guides and the Python API
- [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md): release status, compatibility
  rules, verified baseline, repository layout
- [docs/modernization/](docs/modernization/): design notes, bug tracker, release notes

## References

Holt, J. and McMillan, L. "Merging of multi-string BWTs with applications."
*Bioinformatics* (2014): btu584.

Holt, J. and McMillan, L. "Constructing Burrows-Wheeler transforms of large
string collections via merging." *Proceedings of the 5th ACM Conference on
Bioinformatics, Computational Biology, and Health Informatics*, ACM, 2014.

The construction approach for equal-length reads follows Bauer et al.,
"Lightweight BWT construction for very large string collections."

## License

MIT, as in the original project. Original copyright, license and attribution are
preserved; see `LICENSE` and `AUTHORS`. This fork is maintained by Taksir and does
not claim authorship of the MSBWT algorithms.
