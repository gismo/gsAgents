#!/usr/bin/env python3
"""syntax_check.py -- fast per-file compile gate for G+Smo (-fsyntax-only).

Usage: syntax_check.py [--allow-degraded] <file> [<file> ...]

compile_commands.json in $GISMO_BUILD_DIR is REQUIRED (asserted up front) so every
file is checked with its real per-target flags -- a submodule file built with
different defines/includes than the core library must not be silently checked
with the wrong ones. If it is missing, this script fails immediately with
instructions (run /gismo:dev-config, which enables and generates it for you).

Flag resolution per file (once compile_commands.json is confirmed to exist):
  1. Exact entry in compile_commands.json.
  2. Nearest-neighbour: any compile_commands entry whose source lives in the same
     directory (covers brand-new files not yet configured/instantiated).
  3. --allow-degraded only: CXX_DEFINES/CXX_INCLUDES/CXX_FLAGS from the core
     library's CMakeFiles/gismo.dir/flags.make (library-wide flags -- may miss
     submodule-specific defines/includes; emergency use only).

Headers (.h/.hpp) cannot be compiled directly, so they are checked through a
temporary TU that just #includes them.

Exit: 0 all files pass, 1 any failure, 2 setup error. Last stdout line: STATUS: OK|FAIL.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile

HEADER_EXT = {".h", ".hpp", ".hh"}


def build_dir():
    bd = os.environ.get("GISMO_BUILD_DIR")
    if not bd or not os.path.isfile(os.path.join(bd, "CMakeCache.txt")):
        sys.stderr.write("syntax_check: GISMO_BUILD_DIR not set/valid (source gismo_env.sh first)\n")
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


def resolve_flags(path, cc_entries, bd, allow_degraded):
    ap = os.path.abspath(path)
    for e in cc_entries:
        if os.path.abspath(os.path.join(e.get("directory", ""), e["file"])) == ap:
            return strip_io_args(entry_args(e)) + (e.get("directory", bd),)
    d = os.path.dirname(ap)
    for e in cc_entries:
        if os.path.dirname(os.path.abspath(os.path.join(e.get("directory", ""), e["file"]))) == d:
            return strip_io_args(entry_args(e)) + (e.get("directory", bd),)
    if not allow_degraded:
        sys.stderr.write(
            "syntax_check: %s has no compile_commands.json entry and no sibling in "
            "its directory either. If this is a brand-new file, reconfigure first: "
            "cd %s && cmake .\n" % (path, bd))
        print("STATUS: FAIL")
        sys.exit(2)
    compiler, flags = flags_from_flags_make(bd)
    # Unit-test TUs additionally need UnitTest++ and the core unittests/ dir
    # (gismo_unittest.h); this holds for optional/*/unittests too.
    if "unittests" in ap.split(os.sep):
        root = os.environ.get("GISMO_ROOT", os.path.dirname(bd))
        flags = flags + ["-I" + os.path.join(root, "optional", "gsUnitTest"),
                         "-I" + os.path.join(root, "unittests")]
    return compiler, flags, bd


def check_file(path, cc_entries, bd, allow_degraded):
    if not os.path.isfile(path):
        sys.stderr.write("syntax_check: no such file: %s\n" % path)
        return False
    compiler, flags, workdir = resolve_flags(path, cc_entries, bd, allow_degraded)
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
    cmd = [compiler] + flags + ["-fsyntax-only", tu]
    try:
        res = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    finally:
        if tmp:
            os.unlink(tmp.name)
    if res.returncode == 0:
        print("  OK   %s" % path)
        return True
    print("  FAIL %s" % path)
    sys.stderr.write(res.stderr[-4000:] + "\n")
    return False


def main():
    args = sys.argv[1:]
    allow_degraded = "--allow-degraded" in args
    files = [a for a in args if a != "--allow-degraded"]
    if not files:
        sys.stderr.write(__doc__ or "")
        print("STATUS: FAIL")
        sys.exit(2)
    bd = build_dir()
    assert_compile_commands(bd, allow_degraded)
    cc = load_compile_commands(bd)
    ok = all([check_file(f, cc, bd, allow_degraded) for f in files])
    print("STATUS: %s" % ("OK" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
