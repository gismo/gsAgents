#!/usr/bin/env python3
"""syntax_check.py -- fast per-file compile gate for G+Smo (-fsyntax-only).

Usage: syntax_check.py [--allow-degraded] [--base <ref>] <file> [<file> ...]

--base <ref>: a header is also "new" when it does not exist at the merge base of
<ref> and HEAD in its own repository (covers headers added by commits on the branch).
A header that git detects as a rename of a file present at the merge base is not new,
whether the rename is committed or only staged; without --base a staged rename is not
new either. <ref> must be a ref, not an option.
A <ref> that does not resolve in that repository (or has no merge base with HEAD)
falls back to the git-status test, with one stderr line per repository and ref.

compile_commands.json in $GISMO_BUILD_DIR is REQUIRED (asserted up front) so every
file is checked with its real per-target flags -- a submodule file built with
different defines/includes than the core library must not be silently checked
with the wrong ones. If it is missing, this script fails immediately with
instructions (run /gismo:dev-config, which enables and generates it for you).

Flag resolution per file (once compile_commands.json is confirmed to exist):
  1. Exact entry in compile_commands.json.
  2. Nearest-neighbour: any compile_commands entry whose source lives in the same
     directory (covers brand-new files not yet configured/instantiated).
  3. Borrowed (header-only directories): a file under optional/<module>/ uses an
     entry of the same module; any other file uses the nearest configured
     directory below the repository root (never optional/), else any entry under
     src/. The result line says "(flags from <dir>/)".
  4. --allow-degraded only: CXX_DEFINES/CXX_INCLUDES/CXX_FLAGS from the core
     library's CMakeFiles/gismo.dir/flags.make (library-wide flags -- may miss
     submodule-specific defines/includes; emergency use only).
A file with no flags from any of these is reported "SKIP" and the run continues.

Headers (.h/.hpp) cannot be compiled directly, so they are checked through a
temporary TU that just #includes them; on failure they get one retry with gismo.h
force-included (see check_file). A new .h file (untracked or added relative to HEAD)
that compiles only with that retry is a FAIL: it must be self-contained.

Output: per file, one result line followed by that file's diagnostics, all on
stdout in input order.

Exit: 0 all files pass (STATUS: OK); 1 any failure (STATUS: FAIL); 2 no failure but
at least one skipped file (STATUS: INCOMPLETE), or a setup error with no per-file
lines (STATUS: FAIL).
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from typing import Optional

HEADER_EXT = {".h", ".hpp", ".hh"}


def build_dir():
    bd = os.environ.get("GISMO_BUILD_DIR")
    if not bd or not os.path.isfile(os.path.join(bd, "CMakeCache.txt")):
        sys.stderr.write("syntax_check: GISMO_BUILD_DIR not set/valid (run gismo_env after sourcing gismo_env.sh)\n")
        print("STATUS: FAIL")
        sys.exit(2)
    return bd


def assert_compile_commands(bd, allow_degraded):
    path = os.path.join(bd, "compile_commands.json")
    if os.path.isfile(path):
        return path
    if allow_degraded:
        sys.stderr.write("syntax_check: no compile_commands.json in %s -- "
                         "--allow-degraded set, using library-wide flags.make fallback "
                         "(may miss submodule-specific flags)\n" % bd)
        return None
    sys.stderr.write(
        "syntax_check: compile_commands.json not found in %s\n"
        "This is a hard requirement (per-file flags matter -- a submodule file\n"
        "built with different defines/includes than the core library must not be\n"
        "silently checked with the wrong ones).\n\n"
        "Fix: run `/gismo:dev-config` (it enables CMAKE_EXPORT_COMPILE_COMMANDS and\n"
        "regenerates it for the configured build dir), or manually:\n"
        "    cd %s && cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON .\n\n"
        "Only for emergencies, pass --allow-degraded to fall back to library-wide flags.\n"
        % (bd, bd))
    print("STATUS: FAIL")
    sys.exit(2)


def load_compile_commands(bd):
    path = os.path.join(bd, "compile_commands.json")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return json.load(f)


def entry_args(entry):
    if "arguments" in entry:
        return list(entry["arguments"])
    return shlex.split(entry["command"])


def strip_io_args(args):
    """Remove -c/-o/source-file arguments so we can substitute our own TU."""
    out, skip = [], False
    for a in args[1:]:  # args[0] is the compiler
        if skip:
            skip = False
            continue
        if a == "-o":
            skip = True
            continue
        if a == "-c":
            continue
        if a.endswith((".cpp", ".cxx", ".cc")) and not a.startswith("-"):
            continue
        out.append(a)
    return args[0], out


def flags_from_flags_make(bd):
    """Library-wide fallback flags from CMakeFiles/gismo.dir/flags.make."""
    for dirname in ("gismo.dir", "gismo_static.dir"):
        fm = os.path.join(bd, "CMakeFiles", dirname, "flags.make")
        if not os.path.isfile(fm):
            continue
        compiler, flags = "c++", []
        with open(fm) as f:
            for line in f:
                line = line.strip()
                if line.startswith("# compile CXX with "):
                    compiler = line.split("# compile CXX with ", 1)[1].strip()
                for key in ("CXX_DEFINES", "CXX_INCLUDES", "CXX_FLAGS"):
                    if line.startswith(key + " ="):
                        flags += shlex.split(line.split("=", 1)[1])
        if flags:
            return compiler, flags
    sys.stderr.write("syntax_check: no compile_commands.json and no gismo.dir/flags.make fallback\n")
    print("STATUS: FAIL")
    sys.exit(2)


def entry_source(entry: dict) -> str:
    """Absolute path of the source file an entry compiles."""
    return os.path.abspath(os.path.join(entry.get("directory", ""), entry["file"]))


def entry_flags(entry: dict, bd: str) -> tuple:
    """``(compiler, flags, workdir)`` of one compile_commands.json entry."""
    return strip_io_args(entry_args(entry)) + (entry.get("directory", bd),)


def borrowed_entry(ap: str, cc_entries: list, root: str) -> tuple:
    """Entry whose flags best approximate those of a file without a sibling entry.

    A file under ``<root>/optional/<module>/`` borrows only from entries of that same
    module, because a module's defines and include paths cannot be guessed from
    another one; with none, nothing is returned. Any other file in the repository
    walks up from its directory towards ``<root>`` and returns the first entry found
    below each ancestor (so ``src/gsExpressions/x.h`` borrows from the nearest
    configured directory under ``src/``); the walk never enters ``optional/``.
    Failing that, and for files outside ``root``, any entry of the library itself
    (``<root>/src``).

    :returns: ``(entry, directory the flags were borrowed from)`` or ``(None, None)``.
    """
    root = os.path.abspath(root)
    opt = os.path.join(root, "optional")
    if ap.startswith(opt + os.sep):
        module = os.path.join(opt, ap[len(opt) + 1:].split(os.sep)[0])
        for e in cc_entries:
            if entry_source(e).startswith(module + os.sep):
                return e, module
        return None, None
    anc = os.path.dirname(ap)
    while anc != root and anc.startswith(root + os.sep):
        for e in cc_entries:
            if entry_source(e).startswith(anc + os.sep):
                return e, anc
        anc = os.path.dirname(anc)
    lib = os.path.join(root, "src")
    for e in cc_entries:
        if entry_source(e).startswith(lib + os.sep):
            return e, lib
    return None, None


def resolve_flags(
    path: str, cc_entries: list, bd: str, allow_degraded: bool
) -> Optional[tuple]:
    """Resolve ``(compiler, flags, workdir, note)``, or None if no flags are usable.

    ``note`` is non-empty when the flags were borrowed from another directory.
    """
    ap = os.path.abspath(path)
    for e in cc_entries:
        if entry_source(e) == ap:
            return entry_flags(e, bd) + ("",)
    d = os.path.dirname(ap)
    for e in cc_entries:
        if os.path.dirname(entry_source(e)) == d:
            return entry_flags(e, bd) + ("",)
    root = os.environ.get("GISMO_ROOT", os.path.dirname(bd))
    e, src_dir = borrowed_entry(ap, cc_entries, root)
    if e is not None:
        note = "flags from %s/" % os.path.relpath(src_dir, root)
        return entry_flags(e, bd) + (note,)
    if not allow_degraded:
        return None
    compiler, flags = flags_from_flags_make(bd)
    # Unit-test TUs additionally need UnitTest++ and the core unittests/ dir
    # (gismo_unittest.h); this holds for optional/*/unittests too.
    if "unittests" in ap.split(os.sep):
        flags = flags + ["-I" + os.path.join(root, "optional", "gsUnitTest"),
                         "-I" + os.path.join(root, "unittests")]
    return compiler, flags, bd, ""


def compile_tu(compiler: str, flags: list, workdir: str, tu: str,
               preinclude: str = "") -> subprocess.CompletedProcess:
    """Run ``-fsyntax-only`` on ``tu``, force-including ``preinclude`` if given."""
    cmd = [compiler] + flags
    if preinclude:
        cmd += ["-include", preinclude]
    cmd += ["-fsyntax-only", tu]
    return subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)


def forced_include_missing(stderr: str) -> bool:
    """True if the compiler could not open the force-included ``gismo.h``."""
    return ("gismo.h: No such file" in stderr
            or "'gismo.h' file not found" in stderr)


def _git_out(cwd: str, *args: str) -> Optional[str]:
    """Stripped stdout of ``git -C cwd args``, or None if git fails or is missing."""
    res = _git_bytes(cwd, *args)
    return os.fsdecode(res).strip() if res is not None else None


def _git_bytes(cwd: str, *args: str) -> Optional[bytes]:
    """Raw stdout of ``git -C cwd args``, or None if git fails or is missing.

    Git prints file names as the bytes they have on disk; they need not be valid UTF-8.
    """
    try:
        res = subprocess.run(["git", "-C", cwd, *args], capture_output=True)
    except OSError:
        return None
    return res.stdout if res.returncode == 0 else None


_UNRESOLVED_REPORTED: set = set()


def _report_unresolved_base(top: str, base: str) -> None:
    """Tell once per (repository, ref) that ``base`` gives no merge base there."""
    if (top, base) in _UNRESOLVED_REPORTED:
        return
    _UNRESOLVED_REPORTED.add((top, base))
    sys.stderr.write("syntax_check: --base %s does not resolve, or has no merge base "
                     "with HEAD, in %s; headers there are judged by git status only\n"
                     % (base, top))


def renamed_paths(d: str, mb: str) -> Optional[set]:
    """Paths (relative to the repository top) that are renames between ``mb`` and the index.

    The index holds everything committed since ``mb`` plus what is staged. Parsed from
    NUL-separated ``git diff -M --cached --name-status -z`` output, so paths with
    spaces or other special characters are exact; the paths are returned as bytes
    (compare with ``os.fsencode``) because file names need not be valid UTF-8. Copies
    (``C``) and adds (``A``) are not included. None if git fails or its output cannot
    be parsed.
    """
    out = _git_bytes(d, "diff", "-M", "--cached", "--name-status", "-z", mb)
    if out is None:
        return None
    fields = out.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    renamed, i = set(), 0
    while i < len(fields):
        status = fields[i][:1]
        if status in (b"R", b"C"):
            # status, old path, new path
            if i + 2 >= len(fields):
                return None
            if status == b"R":
                renamed.add(fields[i + 2])
            i += 3
        else:
            if i + 1 >= len(fields):
                return None
            i += 2
    return renamed


def staged_rename_target(d: str, rel: str) -> bool:
    """True if the index renames some path to ``rel`` (a repository-relative path).

    Read from ``git status --porcelain=v1 -z`` over the whole repository: limited to
    the new path, git cannot pair it with the old one and reports an add.
    """
    out = _git_bytes(d, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    if out is None:
        return False
    fields = out.split(b"\0")
    target, i = os.fsencode(rel), 0
    while i < len(fields):
        entry = fields[i]
        if len(entry) < 4:
            i += 1
            continue
        if entry[:1] == b"R" and entry[3:] == target:
            return True
        i += 2 if entry[:1] in (b"R", b"C") or entry[1:2] in (b"R", b"C") else 1
    return False


def absent_at_base(path: str, base: str) -> bool:
    """True if ``path`` is new relative to the merge base of ``base`` and ``HEAD``.

    New means: absent at the merge base and not git-detected as a rename of a file
    that existed there (copies and adds are new). Evaluated in the innermost
    repository containing the file. False when ``base`` does not resolve there or
    there is no common ancestor (reported once per repository and ref on stderr),
    or when git cannot classify the file.
    """
    ap = os.path.abspath(path)
    d = os.path.dirname(ap)
    top = _git_out(d, "rev-parse", "--show-toplevel")
    if not top:
        return False
    mb = _git_out(d, "merge-base", base, "HEAD")
    if not mb:
        _report_unresolved_base(top, base)
        return False
    rel = os.path.relpath(os.path.realpath(ap), os.path.realpath(top))
    try:
        res = subprocess.run(["git", "-C", d, "cat-file", "-e", "%s:%s" % (mb, rel)],
                             capture_output=True)
    except OSError:
        return False
    if res.returncode == 0:
        return False
    renamed = renamed_paths(d, mb)
    return renamed is not None and os.fsencode(rel) not in renamed


def is_new_file(path: str, base: str = "") -> bool:
    """True if ``path`` is untracked or added relative to ``HEAD`` in its own repository.

    The repository is the innermost one containing the file (the root or a nested
    ``optional/<module>``). A file outside any repository, or that git cannot
    classify, is not new. With ``base``, a file is also new when it is absent at the
    merge base of ``base`` and ``HEAD`` (see :func:`absent_at_base`); a ``base`` that
    does not resolve in the file's repository leaves the status-only test.

    :param path: file to classify.
    :param base: ref to compare against, or ``""`` for the status-only test.
    """
    ap = os.path.abspath(path)
    d = os.path.dirname(ap)
    status = _git_bytes(d, "status", "--porcelain=v1", "--untracked-files=all", "--",
                        os.path.basename(ap))
    if status is None:
        return False
    lines = status.splitlines()
    if any(line[:2] == b"??" for line in lines):
        return True
    if any(line[:1] == b"A" or line[1:2] == b"A" for line in lines):
        top = _git_out(d, "rev-parse", "--show-toplevel")
        rel = os.path.relpath(os.path.realpath(ap), os.path.realpath(top)) if top else None
        if rel is None or not staged_rename_target(d, rel):
            return True
    return bool(base) and absent_at_base(path, base)


def check_file(path: str, cc_entries: list, bd: str, allow_degraded: bool,
               base: str = "") -> str:
    """Check one file; print its result line followed by its diagnostics (stdout).

    A header is first compiled standalone. Many G+Smo headers rely on the umbrella
    header having been included by the consuming TU, so on failure it is retried
    once with ``gismo.h`` force-included ahead of it. Passing only on the retry is
    reported as OK with a ``(needs gismo.h)`` marker: the header is not
    self-contained but builds in every real TU. A new ``.h`` file (see
    :func:`is_new_file`) must be self-contained: passing only on the retry is a FAIL
    marked ``(not self-contained: compiles only with gismo.h force-included)``.
    Failing the retry is a genuine FAIL
    and the retry's diagnostics are shown, unless the retry failed only because
    ``gismo.h`` is not on the borrowed include path; then the standalone
    diagnostics, which describe the header itself, are shown.

    :returns: ``"ok"``, ``"fail"``, or ``"skip"`` (no usable compile flags).
    """
    if not os.path.isfile(path):
        print("  FAIL %s" % path)
        print("syntax_check: no such file: %s" % path, flush=True)
        return "fail"
    resolved = resolve_flags(path, cc_entries, bd, allow_degraded)
    if resolved is None:
        print("  SKIP %s  (no compile flags)" % path)
        print("syntax_check: no compile_commands.json entry for this file, none in "
              "its directory, and none that can be borrowed. If it is a brand-new "
              "file, reconfigure first: cd %s && cmake .\n" % bd, flush=True)
        return "skip"
    compiler, flags, workdir, note = resolved
    ext = os.path.splitext(path)[1]
    tu = os.path.abspath(path)
    tmp = None
    if ext in HEADER_EXT:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False)
        # Mimic a real G+Smo TU: consumers see gsForwardDeclarations.h (std prelude,
        # gsConfig, gsDebug) plus gsTemplateTools.h before any other library header,
        # so headers are checked in the same context they are actually consumed in.
        tmp.write('#include <gsCore/gsForwardDeclarations.h>\n'
                  '#include <gsCore/gsTemplateTools.h>\n'
                  '#include "%s"\nint gismo_syntax_check_dummy;\n' % tu)
        tmp.close()
        tu = tmp.name
    marker = ""
    try:
        res = first = compile_tu(compiler, flags, workdir, tu)
        if res.returncode != 0 and tmp:
            retry = compile_tu(compiler, flags, workdir, tu, preinclude="gismo.h")
            if retry.returncode == 0:
                if ext == ".h" and is_new_file(path, base):
                    marker = "  (not self-contained: compiles only with gismo.h force-included)"
                else:
                    marker = "  (needs gismo.h)"
            if retry.returncode == 0 or not forced_include_missing(retry.stderr):
                res = retry
    finally:
        if tmp:
            os.unlink(tmp.name)
    if note:
        marker += "  (%s)" % note
    ok = res.returncode == 0 and "not self-contained" not in marker
    print("  %s %s%s" % ("OK  " if ok else "FAIL", path, marker))
    if not ok:
        print((res.stderr or first.stderr)[-4000:])
    sys.stdout.flush()
    return "ok" if ok else "fail"


def main():
    args = sys.argv[1:]
    allow_degraded = False
    base = ""
    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--allow-degraded":
            allow_degraded = True
        elif a == "--base" or a.startswith("--base="):
            if a == "--base":
                i += 1
                base = args[i] if i < len(args) else ""
            else:
                base = a[len("--base="):]
            if not base or base.startswith("-"):
                sys.stderr.write("syntax_check: --base needs a ref\n")
                print("STATUS: FAIL")
                sys.exit(2)
        else:
            files.append(a)
        i += 1
    if not files:
        sys.stderr.write(__doc__ or "")
        print("STATUS: FAIL")
        sys.exit(2)
    bd = build_dir()
    assert_compile_commands(bd, allow_degraded)
    cc = load_compile_commands(bd)
    results = [check_file(f, cc, bd, allow_degraded, base) for f in files]
    if "fail" in results:
        print("STATUS: FAIL")
        sys.exit(1)
    if "skip" in results:
        print("STATUS: INCOMPLETE")
        sys.exit(2)
    print("STATUS: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
