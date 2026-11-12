"""pytest suite for review_scope.sh, review_lint.py and tree_cleanup.py.

Every test builds a throwaway G+Smo-like root under ``tmp_path`` and runs the real scripts
through ``subprocess`` (the lint rules are also exercised in-process through ``lint_text``).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pytest

HERE = Path(__file__).resolve().parent
SCOPE = HERE / "review_scope.sh"
LINT = HERE / "review_lint.sh"
CLEANUP = HERE / "tree_cleanup.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _load(name: str):
    """Import a script of this directory as a module."""
    sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lint = _load("review_lint")
cleanup = _load("tree_cleanup")


def run(cmd: Sequence[str], cwd: Path, extra: Optional[Dict[str, str]] = None
        ) -> subprocess.CompletedProcess:
    """Run a command in ``cwd`` with a clean G+Smo environment."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GISMO_", "GIT_"))}
    env.update(GIT_ENV)
    env.update(extra or {})
    return subprocess.run(list(cmd), cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, errors="surrogateescape")


def git(cwd: Path, *args: str) -> str:
    """Run a git command that must succeed; return its stdout."""
    r = run(["git", *args], cwd)
    assert r.returncode == 0, r.stderr
    return r.stdout


def write(root: Path, rel: str, text: str) -> None:
    """Write a file, creating directories."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit_all(repo: Path, msg: str = "c") -> None:
    """Stage everything and commit."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def make_root(base: Path, name: str = "gismo", commit: bool = True, repo: bool = True) -> Path:
    """Create a G+Smo-like root (CMakeLists.txt and src/gsCore), by default a git repository
    with one baseline commit."""
    r = base / name
    write(r, "CMakeLists.txt", "project(x)\n")
    write(r, "src/gsCore/gsBasis.h", "#pragma once\nclass gsBasis {};\n")
    write(r, "src/gsCore/gsOther.cpp", "int a;\n")
    if not repo:
        return r.resolve()
    assert run(["git", "init", "-q", "-b", "main"], r).returncode == 0
    if commit:
        commit_all(r, "base")
    return r.resolve()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_root(tmp_path)


def scope(root: Path, *args: str) -> Tuple[int, List[str]]:
    """Run review_scope.sh; return exit code and stdout lines."""
    r = run(["bash", str(SCOPE), *args], root)
    return r.returncode, r.stdout.splitlines()


# ---------------------------------------------------------------------------------------
# A1: colour
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("setting", ["color.diff", "color.ui"])
def test_a1_scope_lines_ignore_colour_configuration(root: Path, setting: str) -> None:
    write(root, "src/gsCore/gsBasis.h", "#pragma once\nclass gsBasis {};\nint added;\n")
    git(root, "config", setting, "always")
    rc, out = scope(root, "--lines")
    assert rc == 0
    assert "src/gsCore/gsBasis.h\t3-3" in out
    assert out[-1] == "STATUS: OK 1 files"


# ---------------------------------------------------------------------------------------
# A2: repositories without commits
# ---------------------------------------------------------------------------------------

def test_a2_root_without_commits_lists_untracked_files(tmp_path: Path) -> None:
    r = make_root(tmp_path, commit=False)
    rc, out = scope(r)
    assert rc == 0
    assert ".\tA\tsrc/gsCore/gsBasis.h" in out
    assert ".\tA\tsrc/gsCore/gsOther.cpp" in out
    assert out[-1] == "STATUS: OK 3 files"


def test_a2_root_without_commits_lines_are_whole_files(tmp_path: Path) -> None:
    r = make_root(tmp_path, commit=False)
    rc, out = scope(r, "--lines")
    assert rc == 0
    assert "src/gsCore/gsBasis.h\t1-2" in out
    assert "src/gsCore/gsOther.cpp\t1-1" in out
    assert out[-1] == "STATUS: OK 3 files"


def test_a2_staged_files_without_commits_are_added(tmp_path: Path) -> None:
    r = make_root(tmp_path, commit=False)
    git(r, "add", "src/gsCore/gsBasis.h")
    rc, out = scope(r, "--lines")
    assert rc == 0
    assert "src/gsCore/gsBasis.h\t1-2" in out
    assert out[-1] == "STATUS: OK 3 files"


def test_a2_nested_without_commits_lists_untracked_files(root: Path) -> None:
    n = root / "optional" / "gsMod"
    write(n, "src/gsMod/gsMod.h", "#pragma once\n")
    git(n, "init", "-q", "-b", "main")
    rc, out = scope(root)
    assert rc == 0
    assert "optional/gsMod\tA\toptional/gsMod/src/gsMod/gsMod.h" in out


def test_a2_nested_base_on_repository_without_commits_still_fails(root: Path) -> None:
    n = root / "optional" / "gsMod"
    write(n, "src/gsMod/gsMod.h", "#pragma once\n")
    git(n, "init", "-q", "-b", "main")
    rc, out = scope(root, "--nested-base", "optional/gsMod=main")
    assert rc == 2
    assert out[-1] == "STATUS: FAIL --nested-base: optional/gsMod has no commits"


# ---------------------------------------------------------------------------------------
# A3: --digest
# ---------------------------------------------------------------------------------------

def digest(root: Path, *args: str) -> str:
    rc, out = scope(root, "--digest", *args)
    assert rc == 0, out
    assert len(out) == 1 and len(out[0]) == 32, out
    return out[0]


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def test_a3_digest_value(root: Path) -> None:
    write(root, "src/gsCore/gsBasis.h", "new\n")
    write(root, "src/gsCore/gsNew.h", "x\n")
    (root / "src/gsCore/gsOther.cpp").unlink()
    expected = "".join(f"{s} {p} {h}\n" for s, p, h in sorted([
        ("M", "src/gsCore/gsBasis.h", md5("new\n")),
        ("A", "src/gsCore/gsNew.h", md5("x\n")),
        ("D", "src/gsCore/gsOther.cpp", "-"),
    ]))
    assert digest(root) == md5(expected)


def test_a3_digest_sees_untracked_files_and_content_changes(root: Path) -> None:
    d0 = digest(root)
    write(root, "src/gsCore/gsNew.h", "x\n")
    d1 = digest(root)
    write(root, "src/gsCore/gsNew.h", "y\n")
    d2 = digest(root)
    assert len({d0, d1, d2}) == 3
    write(root, "src/gsCore/gsNew.h", "x\n")
    assert digest(root) == d1


def test_a3_digest_sees_nested_repositories(root: Path) -> None:
    n = root / "optional" / "gsMod"
    write(n, "src/gsMod/gsMod.h", "a\n")
    git(n, "init", "-q", "-b", "main")
    commit_all(n)
    d0 = digest(root)
    write(n, "src/gsMod/gsMod.h", "b\n")
    d1 = digest(root)
    write(n, "src/gsMod/gsNew.h", "b\n")
    d2 = digest(root)
    assert len({d0, d1, d2}) == 3


def test_a3_digest_honours_path_restriction_and_base(root: Path) -> None:
    git(root, "checkout", "-q", "-b", "feat")
    write(root, "src/gsCore/gsBasis.h", "committed\n")
    commit_all(root)
    write(root, "src/gsCore/gsNew.h", "x\n")
    only = digest(root, "src/gsCore/gsNew.h")
    assert only == md5("A src/gsCore/gsNew.h %s\n" % md5("x\n"))
    both = digest(root, "--base", "main")
    assert both == md5("A src/gsCore/gsNew.h %s\nM src/gsCore/gsBasis.h %s\n"
                       % (md5("x\n"), md5("committed\n")))
    assert digest(root) != both


def test_a3_digest_of_nothing_is_stable(root: Path) -> None:
    assert digest(root) == md5("")


# ---------------------------------------------------------------------------------------
# A4: CM-NARR
# ---------------------------------------------------------------------------------------

def rule_lines(rule: str, source: str, path: str = "src/gsCore/x.cpp", status: str = "M"
               ) -> List[int]:
    """Line numbers on which ``rule`` fires for ``source`` (whole file checked)."""
    found, _, _ = lint.lint_text(path, source, status, None, False)
    return sorted({f.line for f in found if f.rule == rule})


MUST_FLAG_NARR = [
    "// previously this used a dense solve",
    "// Previously the loop ran over all patches",
    "// it previously returned an empty vector",
    "// removed the old loop",
    "// removed the unused variable",
    "// replaced by the helper below",
    "// this was replaced in favour of the new routine",
    "// task 3 of the refactoring",
    "// step 2 of the plan",
    "// per the spec the knots stay sorted",
    "// addresses review feedback",
    "// review point 4: use index_t",
    "// TODO(review): check the sign",
    "// see .claude/plans/gismo-0.10.0 for the derivation",
    "// this fix avoids the crash on empty input",
    "// it used to return zero here",
    "// no longer needed after the refactor",
    "// Round 2 changes",
    "// as requested by the reviewer",
    "// done as requested",
    "// the old implementation was quadratic",
    "/* removed the dead code */",
    'gsInfo << "see .claude/plans/x";',
    'gsInfo << "task 4 output";',
    'gsWarn << "per the spec this is deprecated";',
    'gsInfo << "addresses review point 2";',
    "// Added a null check",
    "// Fixed the off-by-one in the loop bound",
    "// Changed the tolerance to 1e-10",
    "// Now uses std::vector instead of a raw array",
    "// Refactored to avoid duplication",
    "// Reverted the previous change",
    "// Removed unused include",
    "// Removed the redundant check",
    "// Replaced the loop with std::transform",
    "// This was changed to fix issue #123",
    "// The old code recomputed the basis",
    "// This used to be a loop",
    "// Hoisted out of the loop as requested",
]

MUST_NOT_FLAG_NARR = [
    "// Refactored to-do list",
    'gsWarn << "removed the duplicate knots";',
    'gsInfo << "changed from " << a << " to " << b;',
    'gsInfo << "replaced by the average of " << n << " values";',
    'gsWarn << "the previous time step failed";',
    'gsWarn << "no longer converges when the tolerance is zero";',
    'gsInfo << "previously computed values are reused";',
    "// residual changed from the previous iteration",
    "// the previous time step is stored in m_old",
    "// no longer converges when the tolerance is zero",
    "// replaced by its transpose",
    "// updated in place",
    "// removed the duplicate knots before the insertion",
    "// the entry was removed from the list",
    "// previously computed values are reused",
    "// A is replaced by the average of its neighbours",
    "// step 2: assemble the matrix",
    "// this change of variables maps to the unit square",
    "// used to denote the boundary side",
    "// the old values are overwritten by the update",
    "// the step no longer changes the pattern",
    "// this patch is refined twice",
    "// the solution changed from one level to the next",
    "// This fix-point iteration converges",
    "// This fixed-point iteration converges",
    "// This fix point is attracting",
    "// Use the old version of the basis if p < 2",
    "// old behaviour of gsBSpline is kept",
    "// x was previously set by the caller",
    "// Updated Lagrangian formulation",
    "// Fixed-size blocks avoid reallocation",
    "// Removed elements are kept in m_trash",
    "// Changed entries are marked in the mask",
    "// Added to the stiffness matrix",
    "// Changed to the reference configuration",
    "// Fixed a point on the curve",
    "// Changed a to b in the matrix",
    'const char* a = "Added the null check";',
    'const char* a = R"(Added the null check)";',
    'const char* a = R"(// Added the null check)";',
    'gsInfo << "Processing task 4 of 8";',
    'gsInfo << "Round 1: refine uniformly";',
]


@pytest.mark.parametrize("line", MUST_FLAG_NARR)
def test_a4_narration_is_flagged(line: str) -> None:
    assert rule_lines("CM-NARR", line + "\n") == [1], line


@pytest.mark.parametrize("line", MUST_NOT_FLAG_NARR)
def test_a4_runtime_and_algorithm_text_is_not_flagged(line: str) -> None:
    assert rule_lines("CM-NARR", line + "\n") == [], line


def test_a4_lists_are_long_enough() -> None:
    assert len(MUST_FLAG_NARR) >= 10 and len(MUST_NOT_FLAG_NARR) >= 10


# ---------------------------------------------------------------------------------------
# A5: DX-TAG inside code blocks, per-line suppression
# ---------------------------------------------------------------------------------------

DX_BLOCKS = [
    ("\\code", "\\endcode"),
    ("@code", "@endcode"),
    ("\\verbatim", "\\endverbatim"),
    ("@verbatim", "@endverbatim"),
    ("\\code{.cpp}", "\\endcode"),
]


@pytest.mark.parametrize("opener,closer", DX_BLOCKS)
def test_a5_no_dx_tag_inside_blocks(opener: str, closer: str) -> None:
    src = ("/**\n * %s\n * \\note literal\n * \\brief literal\n * %s\n */\nint f();\n"
           % (opener, closer))
    assert 3 not in rule_lines("DX-TAG", src, "src/gsCore/x.h")
    assert 4 not in rule_lines("DX-TAG", src, "src/gsCore/x.h")


def test_a5_dx_tag_resumes_after_block() -> None:
    src = ("/// @code\n/// \\note literal\n/// @endcode\n/// \\brief real\nint f();\n")
    assert rule_lines("DX-TAG", src, "src/gsCore/x.h") == [4]


def test_a5_formula_delimiters_still_suppress() -> None:
    src = "/// text \\f$ \\param x \\f$ and \\f[ \\note y \\f]\n/// \\brief real\nint f();\n"
    assert rule_lines("DX-TAG", src, "src/gsCore/x.h") == [2]


def test_a5_suppression_is_per_line_not_per_hunk(root: Path) -> None:
    write(root, "src/gsCore/x.h", "/// \\param a first\nint f(int a);\n")
    commit_all(root)
    write(root, "src/gsCore/x.h",
          "/// \\param a first arg\n/// \\param c a brand new parameter\nint f(int a, int c);\n")
    r = run(["bash", str(LINT), "--no-clang-format"], root)
    rows = [l.split("\t") for l in r.stdout.splitlines() if "\tDX-TAG\t" in l]
    assert [x[0] for x in rows] == ["src/gsCore/x.h:2"], r.stdout


# ---------------------------------------------------------------------------------------
# A6: tree_cleanup doxygen-tags leaves blocks alone
# ---------------------------------------------------------------------------------------

def cleanup_run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["bash", str(CLEANUP), *args], root)


def test_a6_doxygen_tags_leaves_code_blocks_alone(root: Path) -> None:
    text = ("/**\n * \\brief Demo\n * \\code\n * \\note literal\n * \\endcode\n"
            " * @verbatim\n * \\param literal\n * @endverbatim\n */\nint f();\n")
    write(root, "src/gsCore/x.h", text)
    commit_all(root)
    r = cleanup_run(root, "doxygen-tags", "--apply")
    assert r.returncode == 0, r.stdout
    new = (root / "src/gsCore/x.h").read_text()
    assert " * \\note literal\n" in new and " * \\param literal\n" in new
    assert " * @brief Demo\n * @code\n" in new and " * @endcode\n" in new


# ---------------------------------------------------------------------------------------
# A7: whitespace pass keeps literals; proofs
# ---------------------------------------------------------------------------------------

CONT_STRING = ('const char *s = "abc\\\n\tdef  \\\n\tghi";\nint x;  \n')


def test_a7_whitespace_pass_leaves_continued_string_alone() -> None:
    new, _ = cleanup.clean_whitespace(CONT_STRING)
    assert new == 'const char *s = "abc\\\n\tdef  \\\n\tghi";\nint x;\n'


def test_a7_whitespace_pass_leaves_raw_and_char_literals_alone() -> None:
    src = 'auto r = R"x(\n\ta  \n)x";  \nchar c = \'\\\n\t\';\n'
    new, _ = cleanup.clean_whitespace(src)
    assert new == 'auto r = R"x(\n\ta  \n)x";  \nchar c = \'\\\n\t\';\n'


def test_a7_whitespace_pass_still_expands_indentation() -> None:
    new, c = cleanup.clean_whitespace("void f() {\n\tint a;  \r\n}\n")
    assert new == "void f() {\n    int a;\n}\n" and c["tabs"] == 1 and c["crlf"] == 1


def test_a7_whitespace_apply_end_to_end(root: Path) -> None:
    write(root, "src/gsCore/x.cpp", "void f() {\n\tconst char *s = \"abc\\\n\tdef\";  \n}\n")
    commit_all(root)
    r = cleanup_run(root, "whitespace", "--apply")
    assert r.returncode == 0, r.stdout
    assert (root / "src/gsCore/x.cpp").read_text() == \
        "void f() {\n    const char *s = \"abc\\\n\tdef\";  \n}\n"
    assert "STATUS: OK 1 files changed" in r.stdout


def _faulty(monkeypatch: pytest.MonkeyPatch, mode: str, edit) -> None:
    """Replace the pass of ``mode`` by one that also performs the hand-made bad ``edit``."""
    name = "clean_whitespace" if mode == "whitespace" else "rewrite_doxygen_tags"
    good = getattr(cleanup, name)

    def bad(data: str):
        new, extra = good(data)
        return edit(new), extra
    monkeypatch.setattr(cleanup, name, bad)


def _apply_in_process(root: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
                      capsys: pytest.CaptureFixture) -> Tuple[int, str]:
    monkeypatch.setenv("GISMO_ROOT", str(root))
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    rc = cleanup.main([mode, "--apply"])
    return rc, capsys.readouterr().out


def _assert_refused(root: Path, rel: str, before: str, rc: int, out: str) -> None:
    """The file ``rel`` was left as ``before`` and reported on a ``SKIP`` row; the run is not a
    proof failure."""
    assert (root / rel).read_text() == before, out
    rows = [l.split("\t") for l in out.splitlines() if l.startswith("SKIP\t")]
    assert [r[1] for r in rows] == [rel] and rows[0][2], out
    assert rc == 0 and "STATUS: OK 0 files changed, 1 skipped" in out.splitlines(), out
    assert "FAIL" not in out


def test_a7_whitespace_proof_refuses_when_a_literal_changes(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    text = 'const char *s = "abc\\\n\tdef";\nint a;  \n'
    write(root, "src/gsCore/x.cpp", text)
    commit_all(root)
    _faulty(monkeypatch, "whitespace", lambda t: t.replace("\tdef", "    def"))
    rc, out = _apply_in_process(root, monkeypatch, "whitespace", capsys)
    _assert_refused(root, "src/gsCore/x.cpp", text, rc, out)


def test_a7_whitespace_proof_refuses_when_code_changes(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    text = "int a = 1;  \nint b = 2;\n"
    write(root, "src/gsCore/x.cpp", text)
    commit_all(root)
    _faulty(monkeypatch, "whitespace", lambda t: t.replace("int b = 2;", "int b = 3;"))
    rc, out = _apply_in_process(root, monkeypatch, "whitespace", capsys)
    _assert_refused(root, "src/gsCore/x.cpp", text, rc, out)


def test_a7_whitespace_proof_refuses_when_a_raw_literal_changes(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    text = 'auto r = R"x(\n  a\n)x";\nint a;  \n'
    write(root, "src/gsCore/x.cpp", text)
    commit_all(root)
    _faulty(monkeypatch, "whitespace", lambda t: t.replace("  a\n", "  a \n"))
    rc, out = _apply_in_process(root, monkeypatch, "whitespace", capsys)
    _assert_refused(root, "src/gsCore/x.cpp", text, rc, out)


def test_a7_whitespace_dry_run_reports_refused_files(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    write(root, "src/gsCore/x.cpp", "int a = 1;  \nint b = 2;\n")
    write(root, "src/gsCore/y.cpp", "int c;  \n")
    commit_all(root)
    _faulty(monkeypatch, "whitespace", lambda t: t.replace("int b = 2;", "int b = 3;"))
    monkeypatch.setenv("GISMO_ROOT", str(root))
    assert cleanup.main(["whitespace"]) == 0
    out = capsys.readouterr().out
    assert [l.split("\t")[1] for l in out.splitlines() if l.startswith("SKIP\t")] == ["src/gsCore/x.cpp"]
    assert out.splitlines()[-1] == \
        "STATUS: OK 1 files would change, 1 skipped (dry run; pass --apply)", out


def test_a7_tree_wide_proof_still_fails_the_run(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    write(root, "src/gsCore/x.cpp", "int a;  \n")
    commit_all(root)
    monkeypatch.setattr(cleanup, "proof", lambda repo, files, verify: (False, ["x: boom"]))
    rc, out = _apply_in_process(root, monkeypatch, "whitespace", capsys)
    assert rc == 1 and out.splitlines()[-1] == "STATUS: FAIL proof", out
    assert "OFFENDER\tx: boom" in out


def test_a7_whitespace_proof_passes_for_real_pass(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    write(root, "src/gsCore/x.cpp",
          'void f() {\n\tconst char *s = "a\\\n\tb"; // c  \n\t/* x\n\t   y */\n}\nint a;  \r\n')
    commit_all(root)
    rc, out = _apply_in_process(root, monkeypatch, "whitespace", capsys)
    assert rc == 0 and "STATUS: OK 1 files changed" in out, out


DX_SRC = "/// \\brief Demo\n/// \\code\n/// \\note literal\n/// \\endcode\nint f();\n"


def test_a7_doxygen_proof_refuses_rewrite_inside_a_block(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    write(root, "src/gsCore/x.h", DX_SRC)
    commit_all(root)
    _faulty(monkeypatch, "doxygen", lambda t: t.replace("\\note literal", "@note literal"))
    rc, out = _apply_in_process(root, monkeypatch, "doxygen-tags", capsys)
    _assert_refused(root, "src/gsCore/x.h", DX_SRC, rc, out)


def test_a7_doxygen_proof_refuses_rewrite_in_code_or_literal(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    text = '/// \\brief Demo\nconst char *s = "\\note x";\nint f();\n'
    write(root, "src/gsCore/x.h", text)
    commit_all(root)
    _faulty(monkeypatch, "doxygen", lambda t: t.replace('"\\note x"', '"@note x"'))
    rc, out = _apply_in_process(root, monkeypatch, "doxygen-tags", capsys)
    _assert_refused(root, "src/gsCore/x.h", text, rc, out)


def test_a7_doxygen_proof_refuses_other_edit(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    write(root, "src/gsCore/x.h", DX_SRC)
    commit_all(root)
    _faulty(monkeypatch, "doxygen", lambda t: t.replace("Demo", "Demx"))
    rc, out = _apply_in_process(root, monkeypatch, "doxygen-tags", capsys)
    _assert_refused(root, "src/gsCore/x.h", DX_SRC, rc, out)


def test_a7_doxygen_proof_passes_for_real_pass(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    write(root, "src/gsCore/x.h",
          DX_SRC + "/** \\param a first \\f$ \\note \\f$\n * \\return r\n */\nint g(int a);\n"
          'const char *s = "\\note";\n')
    commit_all(root)
    rc, out = _apply_in_process(root, monkeypatch, "doxygen-tags", capsys)
    assert rc == 0 and "STATUS: OK 1 files changed" in out, out
    new = (root / "src/gsCore/x.h").read_text()
    assert '"\\note"' in new and "/// \\note literal" in new and "@return r" in new


# ---------------------------------------------------------------------------------------
# A8: top-level guard, failing clang-format
# ---------------------------------------------------------------------------------------

def lint_env(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISMO_ROOT", str(root))
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(root)


def test_a8_unexpected_exception_ends_in_status_fail(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    write(root, "src/gsCore/gsBasis.h", "#pragma once\nint changed;\n")
    lint_env(root, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(lint, "lint_text", boom)
    rc = lint.main(["--no-clang-format"])
    out = capsys.readouterr().out
    assert rc == 2
    assert out.splitlines()[-1] == "STATUS: FAIL internal error: RuntimeError: kaputt"


def test_a8_failing_clang_format_is_a_skip_row(root: Path) -> None:
    write(root, ".clang-format", "BasedOnStyle: LLVM\n")
    fake = root.parent / "fake_clang_format.py"
    fake.write_text("import sys\nsys.stderr.write('bad config\\n')\nsys.exit(1)\n")
    write(root, "src/gsCore/gsBasis.h", "#pragma once\nint changed;\n")
    r = run(["bash", str(LINT)], root, {"CLANG_FORMAT": "python3 %s" % fake})
    assert "SKIP\tclang-format\tfailed: bad config" in r.stdout.splitlines(), r.stdout


def test_a8_missing_clang_format_is_a_skip_row(root: Path) -> None:
    write(root, ".clang-format", "BasedOnStyle: LLVM\n")
    write(root, "src/gsCore/gsBasis.h", "#pragma once\nint changed;\n")
    r = run(["bash", str(LINT)], root, {"CLANG_FORMAT": "/nonexistent/clang-format"})
    assert "SKIP\tclang-format\tbinary not found" in r.stdout.splitlines(), r.stdout


# ---------------------------------------------------------------------------------------
# A9: tree_cleanup dry-run failures, non-UTF-8 names
# ---------------------------------------------------------------------------------------

def test_a9_dry_run_outside_git_fails(tmp_path: Path) -> None:
    r = make_root(tmp_path, repo=False)
    out = run(["bash", str(CLEANUP), "whitespace"], r)
    assert out.returncode == 2, out.stdout
    assert out.stdout.splitlines()[-1].startswith("STATUS: FAIL"), out.stdout


def test_a9_nonexistent_path_fails(root: Path) -> None:
    out = run(["bash", str(CLEANUP), "whitespace", "src/nope"], root)
    assert out.returncode == 2, out.stdout
    assert out.stdout.splitlines()[-1].startswith("STATUS: FAIL"), out.stdout


def test_a9_non_utf8_file_names_are_processed(root: Path) -> None:
    name = os.fsdecode(b"src/gsCore/gs\xe9.cpp")
    p = os.path.join(str(root), name)
    with open(p, "wb") as fh:
        fh.write(b"int a;  \n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "x")
    out = run(["bash", str(CLEANUP), "whitespace", "--apply"], root)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "STATUS: OK 1 files changed" in out.stdout, out.stdout
    with open(p, "rb") as fh:
        assert fh.read() == b"int a;\n"


# ---------------------------------------------------------------------------------------
# A10: EX-RETURN and lambdas
# ---------------------------------------------------------------------------------------

EX = "examples/demo_example.cpp"


def test_a10_return_in_lambda_is_not_flagged() -> None:
    src = ("int main(int argc, char** argv)\n{\n    auto f = [&](int k) {\n"
           "        return 0;\n    };\n    auto g = [] { return 1; };\n"
           "    std::function<int()> h = [=]() mutable -> int\n    {\n        return -1;\n    };\n"
           "    return 0;\n}\n")
    assert rule_lines("EX-RETURN", src, EX) == [11]


def test_a10_own_returns_still_flagged() -> None:
    src = ("int main()\n{\n    if (x) { return 1; }\n    auto f = [] { return 0; };\n"
           "    return 0;\n}\n")
    assert rule_lines("EX-RETURN", src, EX) == [3, 5]


def test_a10_return_after_lambda_on_same_line_is_flagged() -> None:
    src = "int main()\n{\n    auto f = [] { return 0; }; return 0;\n}\n"
    assert rule_lines("EX-RETURN", src, EX) == [3]


def test_a1_lint_finds_modified_lines_under_colour_configuration(root: Path) -> None:
    git(root, "config", "color.diff", "always")
    write(root, "src/gsCore/gsBasis.h", "#pragma once\nclass gsBasis {};\nint x;  \n")
    r = run(["bash", str(LINT), "--no-clang-format"], root)
    assert "src/gsCore/gsBasis.h:3\tWS-TRAIL\tminor\ttrailing whitespace" in r.stdout.splitlines()


# ---------------------------------------------------------------------------------------
# --nested-base in review_lint
# ---------------------------------------------------------------------------------------

@pytest.fixture
def nested_root(root: Path) -> Path:
    """Root with the nested repository optional/gsMod: one base commit, then a commit that adds
    a line with trailing whitespace; the working tree is clean."""
    n = root / "optional" / "gsMod"
    write(n, "src/gsMod/gsMod.h", "#pragma once\nint a;\n")
    git(n, "init", "-q", "-b", "main")
    commit_all(n, "base")
    git(n, "tag", "base")
    write(n, "src/gsMod/gsMod.h", "#pragma once\nint a;\nint b;  \n")
    commit_all(n, "work")
    return root


def lint_rows(root: Path, *args: str) -> Tuple[int, List[str]]:
    r = run(["bash", str(LINT), "--no-clang-format", *args], root)
    return r.returncode, r.stdout.splitlines()


def test_nested_base_reports_committed_module_work(nested_root: Path) -> None:
    row = "optional/gsMod/src/gsMod/gsMod.h:3\tWS-TRAIL\tminor\ttrailing whitespace"
    rc, out = lint_rows(nested_root)
    assert row not in out and rc == 0, out
    rc, out = lint_rows(nested_root, "--nested-base", "optional/gsMod=base")
    assert row in out and rc == 1, out
    assert out[-1] == "STATUS: FINDINGS 1"


def test_nested_base_with_unknown_ref_fails(nested_root: Path) -> None:
    rc, out = lint_rows(nested_root, "--nested-base", "optional/gsMod=nope")
    assert rc == 2 and out[-1].startswith("STATUS: FAIL"), out


# ---------------------------------------------------------------------------------------
# tree_cleanup: the proof and the rewrite end a formula at the same place
# ---------------------------------------------------------------------------------------

def test_unterminated_formula_ends_at_blank_line(root: Path) -> None:
    write(root, "src/gsCore/x.h", "/// \\f$ a\n\n/// \\ref b\n")
    commit_all(root)
    r = cleanup_run(root, "doxygen-tags", "--apply")
    assert r.returncode == 0, r.stdout
    assert (root / "src/gsCore/x.h").read_text() == "/// \\f$ a\n\n/// @ref b\n"
    assert "STATUS: OK 1 files changed" in r.stdout
    assert any(l.startswith("PROOF") and l.endswith("pass") for l in r.stdout.splitlines())


def test_unterminated_formula_ends_after_block_comment() -> None:
    old = "/** \\f$ a */\n/// \\ref b\n"
    assert cleanup.verify_doxygen_rewrite(old, "/** \\f$ a */\n/// @ref b\n") == []


def test_proof_refuses_rewrite_inside_open_formula() -> None:
    old = "/// \\f$ a\n/// \\ref b\n"
    assert cleanup.verify_doxygen_rewrite(old, "/// \\f$ a\n/// @ref b\n") != []
    old = "/// \\f[ a\n/// \\ref b\n/// \\f]\n"
    assert cleanup.verify_doxygen_rewrite(old, "/// \\f[ a\n/// @ref b\n/// \\f]\n") != []


def _rewrite_is_proved(old: str) -> bool:
    new, _ = cleanup.rewrite_doxygen_tags(old)
    return cleanup.verify_doxygen_rewrite(old, new) == []


def test_formula_state_survives_code_on_a_doxygen_line() -> None:
    old = "/// \\f$ a\nint y; ///< \\f$ q\n/// \\ref b\n"
    assert _rewrite_is_proved(old)


def test_formula_state_survives_start_of_a_block_comment() -> None:
    old = "/// \\f$ a\n/*! \\f$\n \\ref q */\n"
    assert _rewrite_is_proved(old)


DX_PIECES = [
    "/// \\f$ a", "/// \\f$", "/// \\f[ x", "/// \\f]", "/// \\ref b", "/// \\code",
    "/// \\endcode", "/// text", "//! \\f$ a", "//! \\ref c", "int y; ///< \\f$ q",
    "int y; ///< \\ref q", "int z;", "", "// \\ref plain", "//// \\ref four",
    "/** \\f$ a */", "/** \\ref z */", "/*! \\f$\n \\ref q */", "/**\n * \\f[\n * \\ref w\n */",
    "/* \\ref no */", 'const char *s = "\\ref";', "/// \\f$ a \\f$ \\ref d",
    "/// \\verbatim", "/// \\endverbatim", "/// \\f{align}{ x", "/// \\f}",
    "/// \\f$ a \\", "//! x \\", "/// \\f[ a \\\\", "", "", "@code", "@endcode",
    "/// @code", "/// @endcode", "/** \\f$ a\n\n \\ref b */", "/**\n\n * \\ref x\n */",
    "/* x\n y */", "/// \\ref k \\f$", 'auto s = R"(\n/// \\f$\n)";', "///< \\f] \\ref p",
]

#: Separators between pieces: LF, CRLF, a blank line, and two pieces on one line.
DX_JOINS = ["\n", "\n", "\r\n", "\n\n", "\r\n\r\n", " "]

#: Inputs on which the two lexers legitimately disagree about where a comment is: an unbalanced
#: quote before a ``///`` and an unterminated ``/**``.
DX_DISAGREEING = [
    "#error don't /// \\f$\n/// \\ref b\n",
    'x"; /// \\f$\n/// \\ref b\n',
    "/// \\ref a\nwe don't /// \\f$\n/// \\ref b\n",
    "/** \\ref a\n * \\ref b\n",
]


def test_rewrite_and_proof_agree_on_random_comment_sequences() -> None:
    import random
    rng = random.Random(20240607)
    for _ in range(1500):
        pieces = [rng.choice(DX_PIECES) for _ in range(rng.randint(2, 8))]
        old = pieces[0]
        for p in pieces[1:]:
            old += rng.choice(DX_JOINS) + p
        old += "\n"
        new, _ = cleanup.rewrite_doxygen_tags(old)
        assert cleanup.verify_doxygen_rewrite(old, new) == [], old


def test_continued_comment_before_empty_line_is_one_comment_block(root: Path) -> None:
    text = "/// \\f$ a \\\n\n/// \\f$ \\ref b\n"
    write(root, "src/gsCore/x.h", text)
    commit_all(root)
    r = cleanup_run(root, "doxygen-tags", "--apply")
    assert r.returncode == 0, r.stdout
    assert (root / "src/gsCore/x.h").read_text() == "/// \\f$ a \\\n\n/// \\f$ @ref b\n"
    assert "STATUS: OK 1 files changed" in r.stdout.splitlines(), r.stdout
    assert any(l.startswith("PROOF") and l.endswith("pass") for l in r.stdout.splitlines())


@pytest.mark.parametrize("text", DX_DISAGREEING)
def test_file_on_which_the_lexers_disagree_is_not_written(root: Path, text: str) -> None:
    write(root, "src/gsCore/x.h", text)
    commit_all(root)
    for args in (("doxygen-tags",), ("doxygen-tags", "--apply")):
        r = cleanup_run(root, *args)
        assert r.returncode == 0, r.stdout
        rows = [l.split("\t") for l in r.stdout.splitlines() if l.startswith("SKIP\t")]
        assert [x[1] for x in rows] == ["src/gsCore/x.h"] and rows[0][2], r.stdout
        assert "FAIL" not in r.stdout
        status = [l for l in r.stdout.splitlines() if l.startswith("STATUS:")]
        assert len(status) == 1 and ", 1 skipped" in status[0], r.stdout
        assert (root / "src/gsCore/x.h").read_text() == text
    assert git(root, "status", "--porcelain", "--untracked-files=no") == ""
