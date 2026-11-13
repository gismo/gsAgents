#!/usr/bin/env python3
"""Intrusion budget for a G+Smo feature: which files may change outside its home.

A budget file lists the directories a feature owns (``home``), the base refs
to diff against (``base``) and the few files outside home that may change
(``allow``). ``check`` gates a diff or a planned file inventory against it;
``measure`` reports how large the real intrusion outside home is.

Budget file format (whitespace-separated columns, the last column runs to the
end of the line, blank lines and ``#`` lines are ignored; paths must not
contain spaces)::

    home    optional/gsKLShell/        feature lives here
    base    .                          stable
    base    optional/gsKLShell         main
    allow   src/gsCore/gsFunctionSet.h one new virtual with a default body

``base`` takes exactly a repository and a ref (a trailing ``# comment`` is
allowed). ``allow`` takes a file, a directory (existing, or written with a
trailing ``/``) or a glob in which ``*`` and ``?`` stay inside one path
component and ``**`` crosses components. ``home`` may not cover the whole tree.

All paths are relative to the G+Smo root (``GISMO_ROOT``). Output is TSV in the
lint row format, closed by a ``STATUS:`` line; exit 0 ok, 1 findings, 2 failure
(including any unexpected internal error).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

SCOPE_SCRIPT = Path(__file__).resolve().parent.parent.parent / "review" / "scripts" / "review_scope.sh"

# Public API headers live in src/ of the core or of an optional module.
SRC_RE = re.compile(r"^(optional/[^/]+/)?src/")
# New examples, unit tests and documentation extend nothing the library builds on, so
# no budget restricts them. Any other new file (a CMake script, a CI workflow) can
# change how the core is built and needs an allow row.
FREE_RE = re.compile(r"^(optional/[^/]+/)?(examples|unittests|doc|docs)/")
# An allow row that admits both paths of a pair admits every directory of the core, or
# every optional module, whatever its spelling: such a row is no budget.
WHOLE_AREA_PROBES = (
    ("src/", ("src/gsZzProbeA/a.h", "src/gsZzProbeB/b.h")),
    ("optional/", ("optional/gsZzProbeA/src/a.h", "optional/gsZzProbeB/src/b.h")),
)
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')
VIRTUAL_RE = re.compile(r"\bvirtual\b")
CHAR_LITERAL_RE = re.compile(r"'(?:\\.|[^\\'])'")
SKIP_WALK = {".git", "external", ".claude", "__pycache__"}
NO_BASE_HINT = "no base row: only uncommitted changes are compared"
# git treats a file as binary when a NUL occurs in its first 8000 bytes.
BINARY_PROBE = 8000


class Failure(Exception):
    """A condition that ends the run with ``STATUS: FAIL``."""


@dataclass
class Budget:
    """Parsed budget file.

    :param homes: root-relative home paths, without trailing slash.
    :param bases: repository (``.`` or nested path) -> base ref.
    :param allows: normalised allow patterns; directories end with ``/``.
    :param md5: md5 hex digest of the budget file bytes.
    """

    homes: List[str] = field(default_factory=list)
    bases: Dict[str, str] = field(default_factory=dict)
    allows: List[str] = field(default_factory=list)
    md5: str = ""

    def in_home(self, path: str) -> bool:
        """True when ``path`` equals or lies under a home path."""
        return any(path == h or path.startswith(h + "/") for h in self.homes)

    def allowed(self, path: str) -> bool:
        """True when ``path`` matches an allow row (directory prefix or glob)."""
        for a in self.allows:
            if not GLOB_CHARS.search(a):
                literal = a.rstrip("/")
                if path == literal or path.startswith(literal + "/"):
                    return True
            elif re.fullmatch(glob_to_regex(a), path, re.DOTALL):
                return True
        return False

    def inside(self, path: str) -> bool:
        """True when ``path`` is inside the budget (home or allowed)."""
        return self.in_home(path) or self.allowed(path)


def norm(path: str) -> str:
    """Strip a leading ``./`` from a root-relative path."""
    while path.startswith("./"):
        path = path[2:]
    return path


GLOB_CHARS = re.compile(r"[*?\[]")

_GIT_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def git_unquote(path: str) -> str:
    """Undo git's C-style quoting of a path.

    git prints a path in double quotes, with backslash escapes, when the name
    holds a tab, a newline, a double quote or a backslash, whatever
    ``core.quotepath`` says. Left quoted, such a path matches neither a home
    nor ``src/`` and would pass the gate unseen.

    :param path: path as printed by git.
    :returns: the real path; unchanged when it was not quoted.
    """
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1]
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\" and i + 1 < n:
            nxt = body[i + 1]
            if nxt in _GIT_ESCAPES:
                out.append(_GIT_ESCAPES[nxt])
                i += 2
                continue
            if i + 3 < n + 0 and body[i + 1:i + 4].isdigit():
                out.append(int(body[i + 1:i + 4], 8) & 0xFF)
                i += 4
                continue
        out += c.encode("utf-8", errors="surrogateescape")
        i += 1
    return out.decode("utf-8", errors="surrogateescape")


def show(path: str) -> str:
    """A path as printed in an output row: tabs and newlines escaped, so one row stays one row."""
    return path.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n") \
        if ("\t" in path or "\n" in path) else path


def glob_to_regex(pattern: str) -> str:
    """Translate an allow glob into a regular expression for ``re.fullmatch``.

    ``*`` and ``?`` do not match ``/``; ``**/`` matches zero or more whole
    directories and a ``**`` elsewhere matches anything including ``/``; a
    character class ``[...]`` (``!`` or ``^`` negates) never matches ``/``.
    ``fnmatch`` is not used because its ``*`` crosses ``/``, which would let
    ``src/*.h`` allow ``src/gsCore/x.h``.

    :param pattern: root-relative glob.
    :returns: regular expression source.
    """
    out: List[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                j = i + 2
                while j < n and pattern[j] == "*":
                    j += 1
                if j < n and pattern[j] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
            else:
                body = pattern[i + 1:j]
                negate = body[:1] in ("!", "^")
                if negate:
                    body = body[1:]
                body = body.replace("\\", "\\\\").replace("[", "\\[")
                out.append("(?!/)[" + ("^" if negate else "") + body + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def root_relative(root: str, path: str) -> str:
    """Normalise a user-supplied path to a root-relative POSIX path.

    An absolute path under the root becomes relative. The result never starts
    with ``..``.

    :param root: real path of the G+Smo root.
    :param path: path as written.
    :returns: normalised path; ``"."`` for the root itself.
    :raises Failure: when the path lies outside the root.
    """
    p = posixpath.normpath(path)
    if posixpath.isabs(p):
        candidates = [root]
        env_root = os.environ.get("GISMO_ROOT")
        if env_root:
            candidates.append(posixpath.normpath(os.path.abspath(env_root)))
        for r in candidates:
            if p == r:
                return "."
            if p.startswith(r.rstrip("/") + "/"):
                p = p[len(r.rstrip("/")) + 1:]
                break
        else:
            raise Failure(f"path outside the G+Smo root: {path}")
    if p == ".." or p.startswith("../"):
        raise Failure(f"path outside the G+Smo root: {path}")
    return p


def parse_budget(budget_path: Path, root: str) -> Budget:
    """Parse a budget file.

    :param budget_path: path of the budget file.
    :param root: real path of the G+Smo root (to recognise directory allows).
    :returns: the parsed budget.
    :raises Failure: on an unreadable file, an unknown row kind, a ``base`` row
        that is not exactly ``base <repo> <ref>``, a duplicate ``base``
        repository, a path outside the root, a ``home`` or ``allow`` that
        covers the whole tree, an ``allow`` that covers all of ``src/`` or
        every optional module, or no ``home`` row.
    """
    try:
        raw = budget_path.read_bytes()
    except OSError as e:
        raise Failure(f"cannot read budget file {budget_path}: {e.strerror}")
    budget = Budget(md5=hashlib.md5(raw).hexdigest())
    lines = raw.decode("utf-8-sig", errors="replace").splitlines()

    def row_path(no: int, written: str) -> str:
        try:
            return root_relative(root, written)
        except Failure as e:
            raise Failure(f"line {no}: {e}")

    for no, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split(None, 3)
        kind = parts[0]
        if kind == "home":
            if len(parts) < 2:
                raise Failure(f"line {no}: home row needs a path")
            h = row_path(no, parts[1])
            if h == ".":
                raise Failure(f"line {no}: home '{parts[1]}' covers the whole tree; "
                              f"name the feature's directory")
            budget.homes.append(h)
        elif kind == "base":
            if len(parts) < 3:
                raise Failure(f"line {no}: base row needs a repository and a ref")
            if len(parts) > 3 and not parts[3].startswith("#"):
                raise Failure(f"line {no}: unexpected text after the ref: {parts[3]}")
            repo = row_path(no, parts[1])
            if repo in budget.bases:
                raise Failure(f"line {no}: duplicate base row for {repo}")
            budget.bases[repo] = parts[2]
        elif kind == "allow":
            if len(parts) < 2:
                raise Failure(f"line {no}: allow row needs a path or glob")
            written = parts[1]
            a = row_path(no, written)
            if a == ".":
                raise Failure(f"line {no}: allow '{written}' covers the whole tree")
            if GLOB_CHARS.search(a.split("/", 1)[0]):
                raise Failure(f"line {no}: allow '{written}' must begin with a directory name, "
                              f"not a wildcard: a glob over the whole tree is no budget")
            if GLOB_CHARS.search(a):
                try:
                    re.compile(glob_to_regex(a), re.DOTALL)
                except re.error as e:
                    raise Failure(f"line {no}: allow '{written}' is not a valid glob: {e}")
            one = Budget(allows=[a])
            for area, probes in WHOLE_AREA_PROBES:
                if all(one.allowed(p) for p in probes):
                    raise Failure(f"line {no}: allow '{written}' covers all of {area}: "
                                  f"name the directories or files that may change")
            budget.allows.append(a)
        else:
            raise Failure(f"line {no}: unknown row kind '{kind}'")
    if not budget.homes:
        raise Failure("no home row (at least one is required)")
    return budget


def scope_files(root: str, budget: Budget) -> List[Tuple[str, str, str]]:
    """Run ``review_scope.sh`` for every changed file, with the budget's bases.

    Renames are split into a deletion and an addition and no directory is
    skipped, so a core file cannot change out of sight.

    :param root: G+Smo root; the scope script runs there.
    :param budget: parsed budget.
    :returns: ``(repo, status, path)`` triples sorted by path.
    :raises Failure: when the scope script fails (its reason is relayed).
    """
    cmd = ["bash", str(SCOPE_SCRIPT), "--all-files", "--split-renames", "--no-skip"]
    for repo, ref in budget.bases.items():
        if repo == ".":
            cmd += ["--base", ref]
        else:
            cmd += ["--nested-base", f"{repo}={ref}"]
    r = subprocess.run(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.stderr:
        sys.stderr.write(r.stderr.decode("utf-8", errors="surrogateescape"))
    out = r.stdout.decode("utf-8", errors="surrogateescape").split("\n")
    if r.returncode != 0:
        reason = next((l for l in reversed(out) if l.startswith("STATUS: FAIL")), "")
        raise Failure(reason[len("STATUS: FAIL"):].strip() or f"review_scope exited {r.returncode}")
    rows: List[Tuple[str, str, str]] = []
    for l in out:
        if not l or l.startswith("STATUS:"):
            continue
        repo, st, path = l.split("\t", 2)
        # The scope prefixes a nested repository's path before git's quoting, so the
        # quotes open after "<repo>/".
        if repo != "." and path.startswith(repo + "/"):
            path = repo + "/" + git_unquote(path[len(repo) + 1:])
        else:
            path = git_unquote(path)
        rows.append((repo, st, path))
    return sorted(rows, key=lambda t: t[2])


def listed_files(root: str, list_file: Path) -> List[Tuple[str, str, str]]:
    """Read a file inventory; status ``M`` for paths on disk, ``A`` otherwise.

    :param root: G+Smo root.
    :param list_file: one path per line, root-relative or absolute under the
        root; blank lines and ``#`` lines are ignored.
    :returns: ``(repo, status, path)`` triples sorted by path; ``repo`` is ``"?"``.
    :raises Failure: when the list file cannot be read or a path lies outside the root.
    """
    try:
        text = list_file.read_bytes().decode("utf-8-sig", errors="surrogateescape")
    except OSError as e:
        raise Failure(f"cannot read list file {list_file}: {e.strerror}")
    rows = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        p = root_relative(root, s)
        if p == ".":
            raise Failure(f"path outside the G+Smo root: {s}")
        rows.add(("?", "M" if os.path.lexists(os.path.join(root, p)) else "A", p))
    return sorted(rows, key=lambda t: t[2])


def nested_repos(root: str) -> List[str]:
    """Nested repositories ``optional/<module>`` (own ``.git``), sorted."""
    base = os.path.join(root, "optional")
    if not os.path.isdir(base):
        return []
    return sorted(f"optional/{d}" for d in os.listdir(base)
                  if os.path.exists(os.path.join(base, d, ".git")))


def no_base_rows(root: str, budget: Budget) -> List[str]:
    """``SKIP`` rows for repositories that matter but have no ``base`` row.

    The root repository always matters; a nested repository does when a home
    path lies in it. Without a base only uncommitted work is compared, which
    hides everything already committed on a branch.
    """
    nested = nested_repos(root)
    with_home = [n for n in nested
                 if any(h == n or h.startswith(n + "/") or n.startswith(h + "/")
                        for h in budget.homes)]
    rows = [f"SKIP\tbase\t{r}\t{NO_BASE_HINT}" for r in ["."] + with_home
            if r not in budget.bases]
    others = [n for n in nested if n not in with_home and n not in budget.bases]
    if others:
        rows.append(f"SKIP\tbase\t{len(others)} other nested repositories\t{NO_BASE_HINT}")
    return rows


def violation_message(status: str, path: str) -> Optional[str]:
    """Describe why a change outside the budget is a violation, or ``None``.

    :param status: ``A``, ``M``, ``D`` or ``R``.
    :param path: root-relative path.
    """
    if status == "M":
        return "modified"
    if status == "D":
        return "deleted"
    if status == "R":
        return "renamed"
    if status == "A" and SRC_RE.match(path):
        return "new file under src/"
    if status == "A" and not FREE_RE.match(path):
        return "new file that is not an example, unit test or documentation"
    return None


def cmd_check(root: str, budget: Budget, list_file: Optional[Path]) -> int:
    """Gate the changed files against the budget; print rows and the status line.

    :returns: process exit code (0 ok, 1 findings).
    """
    if list_file:
        rows = listed_files(root, list_file)
        skips: List[str] = []
    else:
        rows = scope_files(root, budget)
        skips = no_base_rows(root, budget)
    outside = [r for r in rows if not budget.inside(r[2])]
    findings = []
    for _repo, st, path in outside:
        what = violation_message(st, path)
        if what:
            findings.append((path, what))
    for path, what in findings:
        print(f"{show(path)}:1\tDS-BUDGET\tmajor\t{what} outside the intrusion budget "
              f"(not under home, not allowed)")
    for s in skips:
        print(s)
    print(f"STAT\tBUDGET\tmd5={budget.md5}\thome={len(budget.homes)}\tallow={len(budget.allows)}"
          f"\tchanged={len(rows)}\toutside={len(outside)}")
    if findings:
        print(f"STATUS: FINDINGS {len(findings)}")
        return 1
    print("STATUS: OK")
    return 0


def git(root: str, repo: str, *args: str) -> Tuple[int, str]:
    """Run git inside ``repo`` (root-relative) and return ``(returncode, stdout)``."""
    d = root if repo == "." else os.path.join(root, repo)
    r = subprocess.run(["git", "--literal-pathspecs", "-C", d, "-c", "core.quotepath=off", *args],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode, r.stdout.decode("utf-8", errors="surrogateescape")


def diff_base(root: str, budget: Budget, repo: str, cache: Dict[str, str]) -> str:
    """Full commit sha a repository is diffed from.

    That is the merge base with the budget's ref for the repository, else ``HEAD``.
    """
    if repo not in cache:
        ref = budget.bases.get(repo)
        if ref is None:
            rc, out = git(root, repo, "rev-parse", "--verify", "HEAD")
        else:
            rc, out = git(root, repo, "merge-base", ref, "HEAD")
        if rc != 0 or not out.strip():
            raise Failure(f"no merge-base between '{ref or 'HEAD'}' and HEAD in {repo}"
                          if ref else f"no commit to diff against in {repo}")
        cache[repo] = out.strip()
    return cache[repo]


def home_header_suffixes(root: str, budget: Budget) -> Set[str]:
    """All trailing path-component sequences of every file under a home path.

    An include target names a home header when it equals one of these suffixes.
    Complexity: O(files * depth) time and space.
    """
    suffixes: Set[str] = set()

    def add(rel: str) -> None:
        comps = rel.split("/")
        for i in range(len(comps)):
            suffixes.add("/".join(comps[i:]))

    for h in budget.homes:
        ap = os.path.join(root, h)
        if os.path.isfile(ap):
            add(h)
            continue
        for d, subs, files in os.walk(ap):
            subs[:] = [s for s in subs if s not in SKIP_WALK and not s.startswith("build")]
            for f in files:
                add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    return suffixes


def parse_hunks(patch: str) -> List[List[str]]:
    """Added lines of a ``-U0`` patch, grouped by hunk.

    Everything before the first ``@@`` line (the ``---``/``+++`` header) is
    skipped, so an added line that itself begins with ``++`` is kept.
    """
    hunks: List[List[str]] = []
    cur: Optional[List[str]] = None
    for line in patch.split("\n"):
        if line.startswith("@@"):
            cur = []
            hunks.append(cur)
        elif cur is not None and line.startswith("+"):
            cur.append(line[1:])
    return hunks


def file_diff(root: str, budget: Budget, repo: str, status: str, path: str,
              cache: Dict[str, str]) -> Tuple[int, int, List[List[str]]]:
    """Added count, removed count and added lines (per hunk) of one changed file.

    An untracked file (no diff output) counts its lines as git would: the
    number of ``\\n`` bytes plus one for an unterminated last line. A symbolic
    link counts one line and is never read through; a binary file counts 0/0.
    """
    rel = path if repo == "." else path[len(repo) + 1:]
    base = diff_base(root, budget, repo, cache)
    rc, numstat = git(root, repo, "diff", "--no-renames", "--numstat", base, "--", rel)
    if rc != 0:
        raise Failure(f"git diff --numstat failed in {repo} for {path}")
    if numstat.strip():
        a, r_, _ = numstat.split("\t", 2)
        if a == "-":
            return 0, 0, []
        rc, patch = git(root, repo, "diff", "--no-renames", "--no-color", "-U0", base, "--", rel)
        return int(a), int(r_), parse_hunks(patch)
    ap = os.path.join(root, path)
    if status == "A":
        if os.path.islink(ap):
            return 1, 0, []
        if os.path.isfile(ap):
            data = Path(ap).read_bytes()
            if b"\0" in data[:BINARY_PROBE]:
                return 0, 0, []
            count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
            lines = data.decode("utf-8", errors="surrogateescape").split("\n")
            if data.endswith(b"\n") or not data:
                lines.pop()
            return count, 0, [lines]
    return 0, 0, []


def strip_code(line: str, in_block: bool) -> Tuple[str, bool]:
    """Remove comments and string/character literals from one line of C++.

    :param line: source line.
    :param in_block: True when a ``/* */`` comment is open at the start of the line.
    :returns: the remaining code and whether a block comment is open at the end.
    """
    out: List[str] = []
    i, n = 0, len(line)
    while i < n:
        if in_block:
            j = line.find("*/", i)
            if j < 0:
                return "".join(out), True
            i = j + 2
            in_block = False
            out.append(" ")
            continue
        c = line[i]
        if c == '"':
            i += 1
            while i < n and line[i] != '"':
                i += 2 if line[i] == "\\" else 1
            i += 1
            out.append('""')
        elif c == "'" and CHAR_LITERAL_RE.match(line, i):
            i = CHAR_LITERAL_RE.match(line, i).end()  # type: ignore[union-attr]
            out.append("' '")
        elif line.startswith("//", i):
            break
        elif line.startswith("/*", i):
            in_block = True
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out), in_block


def count_virtual(hunks: List[List[str]]) -> int:
    """Added lines that use the word ``virtual`` in code (not comments or strings).

    Block-comment state is tracked across the added lines of one hunk.
    """
    n = 0
    for hunk in hunks:
        in_block = False
        for line in hunk:
            code, in_block = strip_code(line, in_block)
            if VIRTUAL_RE.search(code):
                n += 1
    return n


def is_home_include(root: str, budget: Budget, suffixes: Set[str], path: str, target: str) -> bool:
    """True when an ``#include`` in ``path`` points into a home path.

    The target counts when (a) it lies under a home path as written from the
    root, (b) it has a directory part and a file with that path suffix exists
    under a home path, or (c) it is a bare file name, no such file sits next to
    the including file, and a file of that name exists under a home path.
    """
    t = norm(target)
    if budget.in_home(t):
        return True
    if t not in suffixes:
        return False
    if "/" in t:
        return True
    sibling = os.path.join(root, posixpath.dirname(path), t)
    return not os.path.exists(sibling)


def exempt(status: str, path: str) -> bool:
    """True for a new example, unit test or documentation file (what ``check`` does not flag)."""
    return status == "A" and bool(FREE_RE.match(path))


def cmd_measure(root: str, budget: Budget) -> int:
    """Print ``SKIP``/``BASE`` rows, one FILE row per changed file outside home, and a TOTAL row.

    :returns: process exit code (0).
    """
    rows = [r for r in scope_files(root, budget) if not budget.in_home(r[2])]
    suffixes = home_header_suffixes(root, budget)
    cache: Dict[str, str] = {}
    files: List[str] = []
    tot = dict(added=0, removed=0, virtual=0, includes=0, home_includes=0,
               public_headers=0, not_allowed=0, exempt=0)
    for repo, st, path in rows:
        added, removed, hunks = file_diff(root, budget, repo, st, path, cache)
        virtual = count_virtual(hunks)
        includes = home_inc = 0
        for hunk in hunks:
            for l in hunk:
                m = INCLUDE_RE.match(l)
                if not m:
                    continue
                includes += 1
                if is_home_include(root, budget, suffixes, path, m.group(1)):
                    home_inc += 1
        public = path.endswith(".h") and bool(SRC_RE.match(path))
        allowed = budget.allowed(path)
        ex = exempt(st, path)
        files.append(f"FILE\t{repo}\t{st}\t{show(path)}\tadded={added}\tremoved={removed}\tvirtual={virtual}"
                     f"\tincludes={includes}\thome_includes={home_inc}"
                     f"\tpublic_header={'yes' if public else 'no'}\tallowed={'yes' if allowed else 'no'}"
                     f"\texempt={'yes' if ex else 'no'}")
        tot["added"] += added
        tot["removed"] += removed
        tot["virtual"] += virtual
        tot["includes"] += includes
        tot["home_includes"] += home_inc
        tot["public_headers"] += int(public)
        tot["not_allowed"] += int(not allowed)
        tot["exempt"] += int(ex)
    out: List[str] = no_base_rows(root, budget)
    repos = sorted({r[0] for r in rows}, key=lambda r: (r != ".", r))
    out += [f"BASE\t{repo}\t{diff_base(root, budget, repo, cache)}" for repo in repos]
    out += files
    out.append(f"STAT\tTOTAL\tfiles={len(rows)}\tadded={tot['added']}\tremoved={tot['removed']}"
               f"\tvirtual={tot['virtual']}\tincludes={tot['includes']}"
               f"\thome_includes={tot['home_includes']}\tpublic_headers={tot['public_headers']}"
               f"\tnot_allowed={tot['not_allowed']}\texempt={tot['exempt']}")
    out.append("STATUS: OK")
    print("\n".join(out))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point.

    :param argv: argument list, default ``sys.argv[1:]``.
    :returns: process exit code (0 ok, 1 findings, 2 failure or internal error).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="surrogateescape")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Intrusion budget check and measurement.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check", help="gate changed files against the budget")
    pc.add_argument("budget")
    pc.add_argument("--files", help="file inventory to check instead of the working diff")
    pm = sub.add_parser("measure", help="measure the diff outside home")
    pm.add_argument("budget")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        if e.code not in (0, None):
            print("STATUS: FAIL bad arguments")
            return 2
        return 0
    try:
        root = os.path.realpath(os.environ.get("GISMO_ROOT", ""))
        if not os.path.isdir(root):
            raise Failure("not inside a G+Smo checkout")
        budget = parse_budget(Path(args.budget), root)
        if args.cmd == "check":
            return cmd_check(root, budget, Path(args.files) if args.files else None)
        return cmd_measure(root, budget)
    except Failure as e:
        print(f"intrusion: {e}", file=sys.stderr)
        print(f"STATUS: FAIL {e}")
        return 2
    except Exception as e:  # exit 1 is reserved for findings
        print(f"intrusion: internal error: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"STATUS: FAIL internal error: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
