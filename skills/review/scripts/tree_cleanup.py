#!/usr/bin/env python3
"""tree_cleanup.py -- one-off mechanical cleanup of the tracked C++ files of a G+Smo tree.

Usage: tree_cleanup.py <whitespace|doxygen-tags> [--apply] [PATH ...]

Passes:

``whitespace``
    strip trailing whitespace, expand each tab in *leading* indentation to four spaces and
    convert CRLF to LF. Tabs after the first non-blank character are only counted. Lines that
    start or end inside a raw string literal are left alone, since their whitespace is data.
``doxygen-tags``
    rewrite ``\\cmd`` to ``@cmd`` for the commands in ``review_lint.DX_COMMANDS``, inside
    doxygen comments only and never inside formula delimiters (``\\f$ .. \\f$``,
    ``\\f[ .. \\f]``, ``\\f{..} .. \\f}``).

Default is a dry run (per-file counts and a total). ``--apply`` refuses to run when
``git status`` shows changes to tracked files of the target repository, so the resulting
diff is the cleanup alone; it never commits. After applying, a proof is computed and printed:

* whitespace: ``git diff -w --quiet`` must succeed (only whitespace differs from HEAD; submodule state is ignored);
* doxygen-tags: every differing character against ``git show HEAD:<path>`` must be a
  ``\\`` turned into ``@`` in front of a listed command, inside a doxygen comment outside
  formulas, so that undoing exactly those edits reproduces the old blob.

Default PATHs are ``src examples unittests`` of the root repository. A nested repository under
``optional/`` is processed only when named explicitly, with all git commands run there.
Only tracked ``.h .hpp .cpp`` files are touched; ``external/`` is skipped.

Exit: 0 ok, 1 proof failure, 2 usage or refusal. Last stdout line is ``STATUS: ...``.
"""
import argparse
import os
import re
import subprocess
import sys
from typing import Dict, List, NoReturn, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from review_lint import DX_COMMANDS, dx_hits, lex  # noqa: E402

EXTENSIONS = (".h", ".hpp", ".cpp")
DEFAULT_PATHS = ("src", "examples", "unittests")
INDENT_WIDTH = 4


def clean_whitespace(data: str) -> Tuple[str, Dict[str, int]]:
    """Apply the whitespace pass to the text of one file.

    :param data: file contents decoded as latin-1 (byte-transparent)
    :returns: the new text and counters ``trail``, ``tabs``, ``crlf``, ``inline_tabs``
    """
    counts = {"trail": 0, "tabs": 0, "crlf": 0, "inline_tabs": 0}
    parts = data.split("\n")
    bodies = [p[:-1] if p.endswith("\r") else p for p in parts]
    infos = lex(bodies)
    out: List[str] = []
    for i, part in enumerate(parts):
        if i > 0 and infos[i - 1].in_raw_end:
            out.append(part)
            continue
        has_cr = part.endswith("\r")
        body = bodies[i]
        ends_in_raw = infos[i].in_raw_end
        if not ends_in_raw:
            stripped = body.rstrip(" \t")
            if stripped != body:
                counts["trail"] += 1
                body = stripped
            if has_cr:
                counts["crlf"] += 1
                has_cr = False
        lead_len = len(body) - len(body.lstrip(" \t"))
        lead = body[:lead_len]
        if "\t" in lead:
            counts["tabs"] += lead.count("\t")
            body = lead.replace("\t", " " * INDENT_WIDTH) + body[lead_len:]
        counts["inline_tabs"] += body.lstrip(" ").count("\t")
        out.append(body + ("\r" if has_cr else ""))
    return "\n".join(out), counts


def rewrite_doxygen_tags(data: str) -> Tuple[str, int]:
    """Apply the doxygen-tags pass to the text of one file.

    :param data: file contents decoded as latin-1
    :returns: the new text and the number of rewritten commands
    """
    parts = data.split("\n")
    bodies = [p[:-1] if p.endswith("\r") else p for p in parts]
    hits = dx_hits(bodies, lex(bodies))
    for idx, col, _ in hits:
        parts[idx] = parts[idx][:col] + "@" + parts[idx][col + 1:]
    return "\n".join(parts), len(hits)


def verify_doxygen_rewrite(old: str, new: str) -> List[str]:
    """Check that ``new`` differs from ``old`` only by ``\\cmd`` -> ``@cmd`` rewrites.

    Every differing character must be a backslash in ``old`` and ``@`` in ``new``, directly
    followed by a whole word from ``DX_COMMANDS``, located by the lexer inside a doxygen
    comment outside formulas. Undoing exactly those edits must reproduce ``old``.

    :param old: text of the file at HEAD
    :param new: text of the file after the pass
    :returns: a list of problems; empty means the proof holds
    """
    problems: List[str] = []
    old_lines, new_lines = old.split("\n"), new.split("\n")
    if len(old_lines) != len(new_lines):
        return ["line count changed: %d -> %d" % (len(old_lines), len(new_lines))]
    bodies = [p[:-1] if p.endswith("\r") else p for p in old_lines]
    allowed = {(i, c) for i, c, _ in dx_hits(bodies, lex(bodies))}
    rebuilt: List[str] = []
    for i, (a, b) in enumerate(zip(old_lines, new_lines)):
        if a == b:
            rebuilt.append(b)
            continue
        if len(a) != len(b):
            problems.append("line %d: length changed" % (i + 1))
            rebuilt.append(b)
            continue
        chars = list(b)
        for c, (x, y) in enumerate(zip(a, b)):
            if x == y:
                continue
            word = re.match(r"[A-Za-z]+", a[c + 1:])
            if x != "\\" or y != "@":
                problems.append("line %d col %d: '%s' -> '%s' is not a tag rewrite" % (i + 1, c + 1, x, y))
            elif not word or word.group(0) not in DX_COMMANDS:
                problems.append("line %d col %d: '\\%s' is not a listed command" % (i + 1, c + 1, word.group(0) if word else ""))
            elif (i, c) not in allowed:
                problems.append("line %d col %d: not inside a doxygen comment outside a formula" % (i + 1, c + 1))
            else:
                chars[c] = "\\"
        rebuilt.append("".join(chars))
    if not problems and "\n".join(rebuilt) != old:
        problems.append("undoing the rewrites does not reproduce the old text")
    return problems


def git(repo: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off"] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def whitespace_proof(repo: str) -> Tuple[bool, List[str]]:
    """Return whether the working tree differs from HEAD in whitespace only.

    :returns: ``(ok, files that still differ after ignoring whitespace)``
    """
    if git(repo, "diff", "-w", "--quiet", "--ignore-submodules=all").returncode == 0:
        return True, []
    rows = git(repo, "diff", "-w", "--numstat", "--ignore-submodules=all").stdout.decode("utf-8", "replace")
    bad = []
    for row in rows.splitlines():
        a_, d_, name = (row.split("\t") + ["", "", ""])[:3]
        if (a_, d_) != ("0", "0"):
            bad.append(name)
    return False, bad or ["(git diff -w reports a difference; inspect with git diff -w)"]


def doxygen_proof(repo: str, files: Sequence[str]) -> Tuple[bool, List[str]]:
    """Check every changed file against its HEAD blob with :func:`verify_doxygen_rewrite`."""
    bad: List[str] = []
    for f in files:
        blob = git(repo, "show", "HEAD:" + f)
        if blob.returncode != 0:
            bad.append("%s: no HEAD blob" % f)
            continue
        with open(os.path.join(repo, f), "rb") as fh:
            new = fh.read().decode("latin-1")
        for p in verify_doxygen_rewrite(blob.stdout.decode("latin-1"), new)[:3]:
            bad.append("%s: %s" % (f, p))
    return not bad, bad


def locate(root: str, paths: Sequence[str]) -> Dict[str, List[str]]:
    """Group the requested paths by the git repository that owns them.

    :returns: mapping repository directory -> paths relative to it
    """
    nested = [os.path.join(root, "optional", d) for d in sorted(os.listdir(os.path.join(root, "optional")))
              if os.path.exists(os.path.join(root, "optional", d, ".git"))] \
        if os.path.isdir(os.path.join(root, "optional")) else []
    groups: Dict[str, List[str]] = {}
    if not paths:
        groups[root] = [p for p in DEFAULT_PATHS if os.path.exists(os.path.join(root, p))]
        return groups
    for p in paths:
        ap = os.path.realpath(p)
        if ap != root and not ap.startswith(root + os.sep):
            raise ValueError("path outside the G+Smo root: " + p)
        repo = root
        for n in nested:
            if ap == n or ap.startswith(n + os.sep):
                repo = n
        groups.setdefault(repo, []).append(os.path.relpath(ap, repo))
    return groups


def is_regular(path: str) -> bool:
    """Return whether ``path`` is a regular file and not a symlink.

    ``git ls-files`` also lists tracked files deleted from the working tree, and symlinks.
    """
    return os.path.isfile(path) and not os.path.islink(path)


def tracked_files(repo: str, paths: Sequence[str]) -> List[str]:
    r = git(repo, "ls-files", "-z", "--", *paths)
    files = [f for f in r.stdout.decode("utf-8", "replace").split("\0") if f]
    return sorted(f for f in files
                  if f.endswith(EXTENSIONS) and "external" not in f.split("/") and is_regular(os.path.join(repo, f)))


class _Parser(argparse.ArgumentParser):
    """Argument parser whose errors end with a ``STATUS: FAIL`` line and exit code 2."""

    def error(self, message: str) -> NoReturn:
        print("tree_cleanup: " + message, file=sys.stderr)
        print("STATUS: FAIL usage: %s" % message)
        sys.exit(2)


def run(argv: Optional[List[str]] = None) -> int:
    """Parse the arguments and run the requested pass; see the module docstring."""
    ap = _Parser(description="Mechanical cleanup of an existing G+Smo tree.")
    ap.add_argument("mode", choices=("whitespace", "doxygen-tags"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("paths", nargs="*")
    ns = ap.parse_intermixed_args(argv)

    root = os.environ.get("GISMO_ROOT")
    if not root or not os.path.isdir(root):
        print("STATUS: FAIL GISMO_ROOT not set (run through tree_cleanup.sh)")
        return 2
    root = os.path.realpath(root)
    try:
        groups = locate(root, ns.paths)
    except ValueError as e:
        print("STATUS: FAIL %s" % e)
        return 2

    if ns.apply:
        for repo in groups:
            st = git(repo, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules")
            if st.returncode != 0:
                print("STATUS: FAIL %s is not a git repository" % repo)
                return 2
            if st.stdout.strip():
                print("tree_cleanup: refusing to apply, tracked files in %s have uncommitted changes:" % repo)
                for l in st.stdout.decode("utf-8", "replace").splitlines()[:10]:
                    print("  " + l)
                print("STATUS: FAIL dirty tree")
                return 2

    totals = {"files": 0, "trail": 0, "tabs": 0, "crlf": 0, "inline_tabs": 0, "tags": 0}
    changed_by_repo: Dict[str, List[str]] = {}
    for repo, paths in groups.items():
        for f in tracked_files(repo, paths):
            full = os.path.join(repo, f)
            with open(full, "rb") as fh:
                raw = fh.read()
            if b"\0" in raw:
                continue
            data = raw.decode("latin-1")
            label = os.path.relpath(full, root)
            if ns.mode == "whitespace":
                new, c = clean_whitespace(data)
                totals["inline_tabs"] += c["inline_tabs"]
                if new == data:
                    continue
                desc = "trail=%d\ttabs=%d\tcrlf=%d\tinline_tabs_kept=%d" % (
                    c["trail"], c["tabs"], c["crlf"], c["inline_tabs"])
                for k in ("trail", "tabs", "crlf"):
                    totals[k] += c[k]
            else:
                new, n = rewrite_doxygen_tags(data)
                if new == data:
                    continue
                desc = "tags=%d" % n
                totals["tags"] += n
            totals["files"] += 1
            print("%s\t%s" % (label, desc))
            if ns.apply:
                with open(full, "wb") as fh:
                    fh.write(new.encode("latin-1"))
                changed_by_repo.setdefault(repo, []).append(f)

    if ns.mode == "whitespace":
        print("TOTAL\tfiles=%d\ttrail=%d\ttabs=%d\tcrlf=%d\tinline_tabs_kept=%d" % (
            totals["files"], totals["trail"], totals["tabs"], totals["crlf"], totals["inline_tabs"]))
    else:
        print("TOTAL\tfiles=%d\ttags=%d" % (totals["files"], totals["tags"]))
    if not ns.apply:
        print("STATUS: OK %d files would change (dry run; pass --apply)" % totals["files"])
        return 0

    failed: List[str] = []
    for repo, files in changed_by_repo.items():
        if ns.mode == "whitespace":
            ok, bad = whitespace_proof(repo)
            print("PROOF\t%s\tgit diff -w --quiet\t%s" % (os.path.relpath(repo, root), "pass" if ok else "FAIL"))
        else:
            ok, bad = doxygen_proof(repo, files)
            print("PROOF\t%s\tonly '\\'->'@' before listed commands in doxygen comments\t%s" % (
                os.path.relpath(repo, root), "pass" if ok else "FAIL"))
        failed.extend(bad)
    if failed:
        for b in failed:
            print("OFFENDER\t%s" % b)
        print("STATUS: FAIL proof")
        return 1
    print("STATUS: OK %d files changed" % totals["files"])
    if ns.mode == "whitespace":
        msg = "style: strip trailing whitespace, expand leading tabs, normalise line endings"
        body = "Mechanical cleanup by tree_cleanup.sh whitespace; git diff -w is empty."
    else:
        msg = "style: use the @ form of doxygen commands"
        body = "Mechanical cleanup by tree_cleanup.sh doxygen-tags; only '\\' -> '@' before listed commands."
    print("Suggested commit message:\n  %s\n\n  %s" % (msg, body))
    print("Reminder: add the new commit hash to .git-blame-ignore-revs.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Run :func:`run`; an unexpected exception ends in ``STATUS: FAIL`` with exit code 2."""
    try:
        return run(argv)
    except Exception as e:  # noqa: BLE001
        print("tree_cleanup: unexpected %s: %s" % (type(e).__name__, e), file=sys.stderr)
        print("STATUS: FAIL unexpected %s: %s" % (type(e).__name__, e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
