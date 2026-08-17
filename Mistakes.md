# Mistakes

Reference table of mistakes made during this project. Each entry records
**what went wrong**, **why**, and **the lesson learned**. Agent code should
consult this file before starting similar porting/testing work to avoid
repeating the same errors.

---

## M1 — R6034 dialogs popped up on user's screen

**What happened:** Diagnosing the `msvcr90.dll` load failure required calling
`LoadLibraryW` on `msvcr90.dll` from test processes, which triggered the
Windows R6034 ("An application has made an attempt to load the C runtime
library incorrectly") error dialog. These appeared twice, disrupting the
user.

**Why:** On Windows 10/11, loading `msvcr90.dll` via `LoadLibraryW` without
a valid SxS activation context triggers the R6034 dialog before the
exception is raised.

**Lesson:** Never call `LoadLibraryW` on CRT DLLs (`msvcr90.dll`, `msvcrt.dll`,
etc.) from Python test scripts. Use static inspection (`objdump -p`,
`dumpbin /imports`) instead. If dynamic loading is unavoidable, load the
CRT only through a process that already has it loaded (e.g., `python.exe`
import chain), or wrap the call in a subprocess that catches the dialog.

---

## M2 — CRLF text-mode confusion in file I/O

**What happened:** Changed `fopen(fn, 'r')` to `fopen(fn, 'rb')` in
`CompressToRLE.pyx` to fix output CRLF corruption, but this also changed
the *input* read mode. On Windows, committed golden input files have CRLF
line endings (due to `git checkout` without `core.autocrlf=false`), so
reading in binary mode produced `\r` bytes that the symbol parser rejected.

**Why:** Applied the binary-mode fix symmetrically (both input and output)
without considering that text-mode input provides useful CRLF→LF
normalization on Windows.

**Lesson:** When fixing binary/text mode issues on Windows, distinguish
**input** (often benefits from text-mode CRLF normalization) from **output**
(must be binary to avoid `\r\n` corruption). Always check the committed
golden files for existing CRLF content and `git config core.autocrlf`.

---

## M3 — np.save header L-suffix platform confusion (reversed interpretation)

**What happened:** Spent significant debugging time believing Windows
produced the WRONG header (L-suffixed `(54L,)`) while Linux produced
`(54,)`. In reality, Windows produced `(54L,)` = the CORRECT frozen
golden, while Linux modern2 produced `(54L,)` matching the test constant
(`6c8370ed`). Misread the `assertEqual` diff direction (`-` = actual,
`+` = expected).

**Why:** Python `unittest.assertEqual` outputs the *first* argument (actual)
with `-` and the *second* (expected) with `+`. I reversed which was which.

**Lesson:** Always confirm the diff direction by reading the source line:
`assertEqual(LEFT, RIGHT)` → LEFT `-` = actual, RIGHT `+` = expected.
Before investigating platform diffs, **run the same operation on both
platforms and compare headers directly** rather than relying on test output
parsing.

---

## M4 — Smoke script tool-retry infinite loop

**What happened:** The smoke test script ran dozens of times producing
6.7MB of output, because the bash tool retried the failing command on
non-zero exit, creating a visible "infinite loop."

**Why:** The smoke script produced Python exit code 1 on failure; the
tool automatically retried the command with a larger timeout, which also
failed, triggering another retry, etc.

**Lesson:** When running Python scripts via the bash tool, always ensure the
script produces clean output before interpreting "looping" behavior. Use
`timeout` parameters on the first run to prevent runaway retries. For long
test suites, redirect output to a file and check exit code separately rather
than piping stdout.

---

## M5 — Wrong working directory for build_ext

**What happened:** Ran `python setup.py build_ext` from the repo root
(`msbwt-win/`) instead of `packages/msbwt-modern2/`, accidentally building
the legacy root `setup.py` and regenerating the frozen-area `MUSCython/*.c`
files and creating `MUS/__init__.pyc`.

**Why:** Forgot to verify the working directory before invoking the build.
The root `setup.py` is the legacy Holt build, not the modern2 one.

**Lesson:** Always verify the working directory (`pwd`) before any build
command. In monorepos, use absolute `workdir` parameters explicitly rather
than assuming the current directory. Check for the target `setup.py`
before invoking.

---

## M6 — Missing `if __name__ == '__main__':` guard in debug scripts

**What happened:** Windows `multiprocessing.spawn` re-executes the
`__main__` module when forking worker processes. Debug scripts without the
guard caused the worker to re-run the top-level test code, spawning
infinite child processes until killed.

**Why:** On Linux, `multiprocessing.Pool` uses `fork` (no re-execution);
on Windows, `spawn` re-imports the `__main__` module. The standard guard
was missing from several standalone debug scripts.

**Lesson:** On Windows, **every script that uses `multiprocessing`**
(even debug/test scripts) must wrap all module-level execution inside
`if __name__ == '__main__':`. This applies to test harnesses, smoke
scripts, and any standalone Python file that invokes `Pool`, `Process`,
or `Queue`.

---

## M7 — `robocopy /XD build` removed golden artifact directories

**What happened:** Used `robocopy /XD build` to exclude the build output
directory when copying the worktree to the validation copy, but this also
excluded the golden `compat/goldens/.../build/` directories containing
committed test artifacts.

**Why:** `robocopy /XD build` excludes *all* directories named `build` at
any depth, not just the top-level build output.

**Lesson:** When using `robocopy /XD`, list the *full relative path* of
each directory to exclude (e.g., `/XD build /XD dist`), or use
`/XF *.def *.o` patterns instead. Never use short directory names that
could match unintended nested directories.

---

## M8 — Stale `.pyc` files after removing `.py`

**What happened:** Removed `pysam.py` from `site-packages` to test
clean ImportError behavior, but `pysam.pyc` remained. The stale `.pyc`
loaded instead, causing the pin test to see the stub's `__version__`
instead of ImportError.

**Why:** On Windows (and Linux), Python checks for `.pyc` before `.py`. A
stale `.pyc` with a deleted `.py` still loads.

**Lesson:** Always remove `.pyc` files when removing `.py` files, especially
in test environments where the presence/absence of a module is being
asserted. Use `find ... -name "*.pyc" -delete` or explicit removal.

---

## M9 — Frozen overlay not applied initially

**What happened:** The modern2 test suite requires the frozen original files
(MUS/MultiStringBWT.py etc.) overlaid at the repository root, which is
done by the Linux oracle via the reconstruct script. Missing this overlay
caused widespread test failures that looked like production bugs but were
actually test-environment setup issues.

**Why:** Assumed the test suite ran against the git-tracked root files.
Actually, the test suite uses `MSBWT_MODERN2_REPO` to find the root `MUS/`
and expects those files to match the hash-verified frozen projection
(95ac0b86...), not the git blob (a6d77f71...).

**Lesson:** Before running any test suite, read its `setUpClass` and
fixture setup to understand the full environment requirements. Check for
`os.path.join(REPO, "MUS", ...)` paths and verify that the REPO root
contains the expected files. The frozen projection files live in WSL at
`/home/mytho/.local/share/msbwt-audit-q1/frozen/` and must be synced
for Windows validation.

---

## M10 — CRLF in committed golden input files

**What happened:** The `convert` CLI tests failed because the committed
golden input files (`uniform.txt`) had CRLF line endings on disk (from
`git checkout` with `core.autocrlf=true`), causing `\r` bytes to reach
the symbol parser.

**Why:** The `.gitattributes` does not cover `compat/goldens/` text files,
so `core.autocrlf=true` (Windows default) converted LF→CRLF on checkout.

**Lesson:** Before diagnosing CRLF-related test failures, run
`git config core.autocrlf` and check the actual bytes of committed golden
files with `hexdump -C` or `od -c`. Add `/compat/goldens/** text eol=lf`
to `.gitattributes` if needed, or document the checkout expectation.

---

## M11 — Cython cannot iterate typed ndarray `.shape` in genexpr

**What happened:** Wrote `tuple(int(x) for x in self.totalCounts.shape)`
in Cython code. Cython treated `.shape` as returning a C `npy_intp *`
pointer on a typed `cdef np.ndarray`, and the genexpr's `for x in`
failed with "Cannot convert npy_intp * to Python object."

**Why:** Cython treats typed ndarray attributes as C-level accesses. The
`.shape` of a `cdef np.ndarray` returns the raw C pointer, not a Python
tuple.

**Lesson:** When iterating or passing ndarray shapes in Cython, cast to
`object` first: `(<object>self.totalCounts).shape` returns a Python tuple.
Define a Python-level helper function (e.g., `_int_shape(shape)`) to avoid
repeating the cast. Alternatively, use `np.asarray()` to convert to
a Python-accessible view.

---

## M12 — Pool join required before file removal on Windows

**What happened:** Fixed individual memmap-close sites but missed that
`multiprocessing.Pool` workers hold file mappings until `close()` completes.
Adding `myPool.close()` was not enough; needed `myPool.join()` before
removing files that workers had memory-mapped.

**Why:** `Pool.close()` prevents new tasks but does not wait for existing
workers to finish. Workers' `np.load(..., 'r+')` mappings remain open
until the worker process exits (triggered by `join()`).

**Lesson:** Always call `myPool.close()` followed by `myPool.join()` before
removing files that may be memory-mapped by pool workers. This is
especially critical on Windows where `os.remove()` fails with Error 32
(sharing violation) while a mapping is open. On Linux this is silent
because `unlink()` succeeds on memory-mapped files.

---

## M13 — Pickle byte framing diverges for numpy arrays on Windows vs Linux

**What happened:** Fresh-pickled `totalCounts.p` files (protocol 0) produced
different SHA-256 hashes on Windows vs Linux, because numpy pickles array
shapes as Python longs on Windows (`(6L,)`) vs ints on Linux (`(6,)`).

**Why:** On Windows CPython 2.7, `numpy.ndarray.shape` returns a tuple of
Python `long` objects (because `npy_intp` is 64-bit and exceeds py2's 32-bit
`int`), which pickle serializes with the `L` marker. On Linux, the same
values fit in 32-bit `int`.

**Lesson:** When comparing pickled numpy arrays across platforms, either
(a) compare the unpickled logical content (dtype, values) rather than
pickle bytes, or (b) normalize the shape tuple before pickling. This is
an unavoidable numpy platform difference that cannot be fixed without
changing the pickle representation.

---

## M14 — Cython np.save header L-suffix differs from open_memmap

**What happened:** `np.save()` on Windows writes py2-long shape elements
into `.npy` headers (producing `54L` vs `54`), while `open_memmap()` with
`tuple(int(x) for x in shape)` writes int-normalized headers. This caused
hash mismatches for committed golden artifacts.

**Why:** `np.save` uses the array's `.shape` getter, which returns py2
longs on Windows (numpy's C converter uses `PyLong_FromSsize_t`). The
test constants were recorded from Linux (no L-suffix). The fix is to
replace `np.save` with `open_memmap` + copy using a normalized shape.

**Lesson:** On CPython 2.7 Windows, always normalize shape tuples with
`tuple(int(x) for x in shape)` before passing to format writers.
Document this in any code that produces committed `.npy` artifacts.

---

## M15 — Cython typed ndarray close before os.remove

**What happened:** `np.memmap()` + `del variable` in Cython did not release
the file handle on Windows, because Cython's typed ndarray buffer
acquisition keeps the base reference alive until function epilogue.

**Why:** Cython's `cdef np.ndarray[...]` with `mode='c'` acquires a buffer
reference to the ndarray's base (the mmap). `del variable` decrements the
reference but does not release the buffer until the function epilogue.
The file handle remains open, preventing `os.remove()`.

**Lesson:** In Cython, explicitly close the memmap's underlying mmap before
removing the file:
```cython
if (<object>arr).base is not None:
    (<object>arr).base.close()
os.remove(filename)
```
This must be done BEFORE `del`, not after. Test on Windows; it works on
Linux because `unlink()` succeeds on mapped files.

---

## M16 — Windows multiprocessing spawn re-imports `__main__`

**What happened:** Test scripts without `if __name__ == '__main__':` guard
caused infinite spawn loops when `multiprocessing.Pool` was used, because
`spawn` re-imports the `__main__` module.

**Why:** On Windows, `multiprocessing` uses `spawn` (not `fork`), which
re-executes the `__main__` module in child processes. Module-level code
runs again, creating another Pool, triggering another spawn, etc.

**Lesson:** Every script that imports or uses `multiprocessing` must wrap
its execution logic in `if __name__ == '__main__':`. This is the single
most common Windows portability issue for multiprocessing code. Check ALL
files that call `multiprocessing.Pool`, `Process`, or `Queue`.

---

## M17 — `os.rename()` fails on mapped files on Windows

**What happened:** `iterateMsbwtCreate` called `os.rename()` on a file
that was still memory-mapped by a `np.load(fn, 'r+')` call, causing
WindowsError Error 32.

**Why:** On Windows, renaming a file that has an open memory mapping
fails with ERROR_SHARING_VIOLATION. On Linux, `rename()` succeeds
regardless of open mappings.

**Lesson:** On Windows, any `os.remove()` or `os.rename()` on a file
that has been opened with `np.load(..., 'r+')` or `np.memmap()` must
be preceded by closing the mapping. Check for this pattern:
```python
arr = np.load(fn, 'r+')  # or np.memmap(...)
# ... use arr ...
del arr  # NOT sufficient in Cython!
os.remove(fn)  # fails on Windows while mapping is open
```

---

## M18 — `numpy.intp` → `unsigned long` cumsum dtype mismatch on Windows

**What happened:** `np.cumsum(totalCounts)` where `totalCounts` is
`<u4` (uint32) produces an `unsigned long` result on Windows, which is
32-bit (vs 64-bit on Linux). Assigning this to a `cdef np.uint64_t`
view raises a buffer dtype mismatch.

**Why:** On Windows x64, `unsigned long` is 32-bit; `np.cumsum` of uint32
promotes to the C `unsigned long` (np.ulong), which has different NumPy
format than uint64_t. On Linux x64, `unsigned long` is 64-bit, so the
promotion matches uint64_t.

**Lesson:** When assigning numpy results to typed Cython views, always
specify the dtype explicitly:
```cython
fmOffsets = np.cumsum(totalCounts, dtype='<u8') - totalCounts
```
Never rely on implicit dtype promotion for cross-platform compatibility.

---

## M19 — `git worktree` and accidental builds in wrong directories

**What happened:** Ran `setup.py build_ext` from the repo root multiple
times, accidentally building the legacy (non-modern2) setup.py and
regenerating frozen-area MUSCython/*.c files that should never be
modified.

**Why:** The repo root also has a `setup.py` (the legacy Holt build). When
using `workdir` in commands, the default can be wrong.

**Lesson:** Always verify the exact working directory before build
commands. Use absolute paths. In monorepos with multiple `setup.py` files,
always specify the full path to the correct one, or `cd` explicitly.

---

## M20 — Missing spawn guard in standalone diagnostic scripts

**What happened:** Created several `debug_*.py` scripts to diagnose issues
on Windows. These scripts had module-level multiprocessing code but no
`if __name__ == '__main__':` guard, causing them to hang indefinitely
when the tool retried them.

**Why:** Forgot that Windows `multiprocessing.spawn` re-imports `__main__`
in child processes. The scripts had module-level code that imported
modules using multiprocessing (e.g., `import MUSCython`), which was
harmless, but the actual test code was also at module level.

**Lesson:** When creating any Python script for diagnostic purposes on
Windows, always wrap the execution block in `if __name__ == '__main__':`
as the first check. This is a one-line safety net that prevents spawn
loops regardless of what the script imports.

---

## M21 — `open(fn, 'r+')` for pickle on Windows corrupts framing

**What happened:** Pickle files written with `open(fn, 'w+')` (text mode)
on Windows had `\r\n` inserted where `\n` was intended, corrupting the
pickle framing and causing `ImportError: No module named multiarray` when
reading with `open(fn, 'rb')`.

**Why:** Python's text-mode `open` on Windows translates `\n` → `\r\n` on
write, and `\r\n` → `\n` on read. Pickle uses `\n` as the line delimiter
in protocol 0. Writing in text mode corrupts the framing; reading in
binary mode then exposes the corruption.

**Lesson:** All pickle file I/O must use binary mode (`'rb'`/`'wb'`) on
Windows. This applies to `pickle.dump` and `pickle.load`, as well as any
format that uses structured line-oriented framing (e.g., numpy's old
`np.save` text headers). Check all `open()` calls in modules that do
serialization.
