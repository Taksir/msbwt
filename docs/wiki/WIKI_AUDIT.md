# Wiki audit (msbwt.wiki.git @ d6d9008)

The wiki was checked against a fresh build of `msbwt-modern3` 0.3.0 on
CPython 3.14.0rc2 (Linux x86-64).  Checked: every `MUS`/`MUSCython` import and
symbol named on any page, the Python examples (byte and RLE indexes, both
loaders, `recoverString`), all enhanced `MultiStringBWT` / `TwoSourceBWT` methods,
the subcommands of every console script, internal wiki links, and the legacy
`convert` quirks.  Result: the pages are accurate for modern3.

| Page | Finding | Action |
|---|---|---|
| `README.md` | Leftover staging note saying the wiki "does not exist yet"; shows up as a public page and is not linked | remove |
| `Wiki.md` | One-line stub duplicating `Home` | remove |
| `Constructing-the-MSBWT` | No mention that a truncated FASTQ is now an error | add note |
| `Constructing-the-MSBWT` | `convert` quirk quotes the Python 2 `TypeError` text only | add the Python 3 text |
| `Queries-with-the-Python-API`, `BasicBWT-API` | `recoverString` returns `bytes` from the `MUSCython` loader but `str` from the pure-Python loader | state both |
| `Persistent-Files-and-Compatibility` | `totalCounts.p` not listed | add row (derived cache, restricted reader) |
| `Installation`, `Home` | Described locally built 0.3.0 wheels for two platforms | rewrite for `pip install pymsbwt` 0.4.0 and the published wheel platforms |

## Additions for pymsbwt 0.5.0

The wiki was still at `1456ae2` (the patch above had not been applied), so the
patch now contains the rows above **plus** the 0.5.0 changes:

| Page | Change |
|---|---|
| `LCP-Retrofit`, `Source-Removal`, `Persistent-Files-and-Compatibility` | source removal keeps the LCP layer (Feature 11B); `--drop-lcp` now optional; new `lcp.json` fields |
| `LCP-Intervals-and-Maximal-Repeats` (new) | Feature 11C: `maximalRepeats`, `lcpIntervals`, `msbwt-lcp repeats` |
| `Bidirectional-Search-Experimental` (new) | experimental 2BWT companion and FMD screen |
| `Constructing-the-MSBWT` | uppercase `ACGNT` input requirement and the new `ValueError` (M3-S2-INPUT) |
| `Enhanced-Features-Overview`, `Home`, `_Sidebar` | new rows, links and "not included" list |

Every Python and CLI example on the two new pages was run against a real
Holt-built, provenance-merged index with an LCP layer before publishing.
New features are labelled "since 0.5.0" so readers on 0.4.0 are not misled.

## Applying

`wiki-refresh.patch` contains every change above and also deletes a stray empty
`wiki-refresh.patch` file that an earlier failed attempt committed to the wiki.
It is written against wiki commit `1456ae2` and was checked to apply cleanly to a
fresh clone.  Apply it from the root of the wiki checkout, pointing at the file
inside your clone of this repository (do not copy it around first; check it is
not empty, it should be about 28 KB):

    git apply --ignore-whitespace /path/to/wiki-refresh.patch
    git add -A && git commit -m "wiki: refresh for modern3" && git push origin master

(`--ignore-whitespace` makes it work on Windows checkouts with CRLF line endings.)
