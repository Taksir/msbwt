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
| `Installation` | Describes locally built wheels only | update after the PyPI release (`pip install pymsbwt`) |

`wiki-refresh.patch` contains the first five rows.  Apply it from the root of
the wiki checkout:

    git apply --ignore-whitespace /path/to/wiki-refresh.patch
    git add -A && git commit -m "wiki: refresh for modern3" && git push origin master

(`--ignore-whitespace` makes it work on Windows checkouts with CRLF line endings.)
