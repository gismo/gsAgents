"""pytest suite for intrusion.sh / intrusion.py and the options of review_scope.sh they rely on.

Every test builds a throwaway G+Smo-like root (a root git repository plus a nested
repository at ``optional/gsMod``) under ``tmp_path`` and runs the real scripts
through ``subprocess``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

HERE = Path(__file__).resolve().parent
INTRUSION = HERE / "intrusion.sh"
SCOPE = HERE.parent.parent / "review" / "scripts" / "review_scope.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}

NO_BASE = "no base row: only uncommitted changes are compared"


def run(cmd: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a command in ``cwd`` with a clean G+Smo environment (bytes survive decoding)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GISMO_", "GIT_"))}
    env.update(GIT_ENV)
    return subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, errors="surrogateescape")


def git(cwd: Path, *args: str) -> None:
    """Run a git command that must succeed."""
    r = run(["git", *args], cwd)
    assert r.returncode == 0, r.stderr


def rev(cwd: Path, ref: str = "HEAD") -> str:
    """Full sha of ``ref`` in the repository at ``cwd``."""
    r = run(["git", "rev-parse", ref], cwd)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write(root: Path, rel: str, text: str) -> None:
    """Write a file, creating directories."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit_all(repo: Path, msg: str) -> None:
    """Stage everything in a repository and commit."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def commit_files(repo: Path, msg: str, *rels: str) -> None:
    """Stage the named paths only and commit."""
    git(repo, "add", *rels)
    git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A G+Smo-like root with a baseline commit in the root and in optional/gsMod."""
    r = tmp_path / "gismo"
    write(r, "CMakeLists.txt", "project(x)\n")
    write(r, "src/gsCore/gsBasis.h", "#pragma once\nclass gsBasis {};\n")
    write(r, "src/gsCore/gsFunctionSet.h", "#pragma once\nclass gsFunctionSet {};\n")
    write(r, "src/gsCore/gsOther.h", "#pragma once\n")
    write(r, "examples/ex.cpp", "int main() {}\n")
    write(r, "optional/gsMod/src/gsMod/gsMod.h", "#pragma once\nclass gsMod {};\n")
    write(r, "optional/gsMod/src/gsMod/gsMod.cpp", "int a;\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "CMakeLists.txt", "src", "examples")
    git(r, "commit", "-q", "-m", "base")
    n = r / "optional" / "gsMod"
    git(n, "init", "-q", "-b", "main")
    commit_all(n, "base")
    return r.resolve()


def budget(root: Path, text: str) -> str:
    """Write the budget file next to the root (outside it) and return its path."""
    p = root.parent / "budget.txt"
    p.write_text(text)
    return str(p)


BASIC = "home optional/gsMod/ feature\n"


def intrusion(root: Path, *args: str) -> Tuple[int, List[str], str]:
    """Run intrusion.sh; return exit code, stdout lines, stderr."""
    r = run(["bash", str(INTRUSION), *args], root)
    return r.returncode, r.stdout.split("\n")[:-1], r.stderr


def scope(root: Path, *args: str) -> Tuple[int, List[str]]:
    """Run review_scope.sh; return exit code and stdout lines."""
    r = run(["bash", str(SCOPE), *args], root)
    return r.returncode, r.stdout.splitlines()


def branch_commit(repo: Path, rel: str, text: str) -> None:
    """Commit a change on a new branch ``feat`` and stay on it."""
    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, rel, text)
    commit_all(repo, "feat")


def stat(out: List[str]) -> str:
    """The ``STAT`` row of an output."""
    return next(l for l in out if l.startswith("STAT\t"))


def rows(out: List[str], kind: str) -> List[str]:
    """All output rows of one kind (``FILE``, ``BASE``, ``SKIP``)."""
    return [l for l in out if l.startswith(kind + "\t")]


def finding_paths(out: List[str]) -> List[str]:
    """Paths of the ``DS-BUDGET`` rows."""
    return [l.split(":")[0] for l in out if "\tDS-BUDGET\t" in l]


def add_second_module(root: Path) -> Path:
    """A second nested repository ``optional/gsOther`` with one commit."""
    n = root / "optional" / "gsOther"
    write(n, "src/gsOther/o.h", "#pragma once\n")
    git(n, "init", "-q", "-b", "main")
    commit_all(n, "base")
    return n


# ---------------------------------------------------------------------------
# review_scope.sh: --nested-base
# ---------------------------------------------------------------------------


def test_nested_base_lists_committed_work(root: Path) -> None:
    branch_commit(root / "optional/gsMod", "src/gsMod/gsMod.cpp", "int a;\nint b;\n")
    rc, out = scope(root, "--all-files")
    assert rc == 0 and out == ["STATUS: OK 0 files"]
    rc, out = scope(root, "--all-files", "--nested-base", "optional/gsMod=main")
    assert rc == 0
    assert out == ["optional/gsMod\tM\toptional/gsMod/src/gsMod/gsMod.cpp", "STATUS: OK 1 files"]
    rc, out2 = scope(root, "--all-files", "--nested-base=optional/gsMod/=main")
    assert out2 == out


def test_nested_base_lines_mode(root: Path) -> None:
    branch_commit(root / "optional/gsMod", "src/gsMod/gsMod.cpp", "int a;\nint b;\n")
    rc, out = scope(root, "--lines")
    assert out == ["STATUS: OK 0 files"]
    rc, out = scope(root, "--lines", "--nested-base", "optional/gsMod=main")
    assert rc == 0
    assert out == ["optional/gsMod/src/gsMod/gsMod.cpp\t2-2", "STATUS: OK 1 files"]


def test_nested_base_lists_untracked_too(root: Path) -> None:
    branch_commit(root / "optional/gsMod", "src/gsMod/gsMod.cpp", "int a;\nint b;\n")
    write(root, "optional/gsMod/src/gsMod/new.h", "x\n")
    rc, out = scope(root, "--all-files", "--nested-base", "optional/gsMod=main")
    assert out[:-1] == ["optional/gsMod\tM\toptional/gsMod/src/gsMod/gsMod.cpp",
                        "optional/gsMod\tA\toptional/gsMod/src/gsMod/new.h"]


def test_nested_base_bad_module_and_bad_ref(root: Path) -> None:
    rc, out = scope(root, "--nested-base", "optional/nope=main")
    assert rc == 2 and out[-1].startswith("STATUS: FAIL")
    rc, out = scope(root, "--nested-base", "optional/gsMod=no-such-ref")
    assert rc == 2 and out[-1].startswith("STATUS: FAIL")
    rc, out = scope(root, "--nested-base", "optional/gsMod")
    assert rc == 2 and out[-1].startswith("STATUS: FAIL")


def test_nested_base_without_commits_fails(root: Path) -> None:
    git(root / "optional", "init", "-q", "-b", "main", "gsEmpty")
    rc, out = scope(root, "--all-files")
    assert rc == 0
    rc, out = scope(root, "--all-files", "--nested-base", "optional/gsEmpty=main")
    assert rc == 2 and out[-1].startswith("STATUS: FAIL") and "gsEmpty" in out[-1]


def test_nested_base_twice_for_one_module_fails(root: Path) -> None:
    rc, out = scope(root, "--nested-base", "optional/gsMod=main",
                    "--nested-base", "optional/gsMod/=main")
    assert rc == 2 and out[-1].startswith("STATUS: FAIL") and "twice" in out[-1]
    rc, out = scope(root, "--nested-base", "optional/gsMod=main",
                    "--nested-base", "./optional/gsMod=main")
    assert rc == 2 and "twice" in out[-1]


@pytest.mark.parametrize("module", ["./optional/gsMod", "optional/gsMod/", "./optional//gsMod/"])
def test_nested_base_module_path_is_normalised(root: Path, module: str) -> None:
    branch_commit(root / "optional/gsMod", "src/gsMod/gsMod.cpp", "int a;\nint b;\n")
    rc, out = scope(root, "--all-files", "--nested-base", f"{module}=main")
    assert rc == 0
    assert out == ["optional/gsMod\tM\toptional/gsMod/src/gsMod/gsMod.cpp", "STATUS: OK 1 files"]


def test_failure_message_never_ends_in_empty_tail(root: Path) -> None:
    n = root / "optional/gsMod"
    git(n, "checkout", "-q", "--orphan", "other")
    write(n, "unrelated.txt", "x\n")
    commit_all(n, "unrelated")
    rc, out = scope(root, "--nested-base", "optional/gsMod=main")
    assert rc == 2 and out[-1].startswith("STATUS: FAIL no merge-base")
    assert not out[-1].rstrip().endswith(":")


def test_base_notice_names_only_modules_without_base(root: Path) -> None:
    r = run(["bash", str(SCOPE), "--base", "main"], root)
    assert "optional/gsMod" in r.stderr
    r = run(["bash", str(SCOPE), "--base", "main", "--nested-base", "optional/gsMod=main"], root)
    assert r.returncode == 0 and "optional/gsMod" not in r.stderr


def test_base_notice_with_two_modules_names_only_the_one_without_base(root: Path) -> None:
    add_second_module(root)
    r = run(["bash", str(SCOPE), "--base", "main", "--nested-base", "optional/gsMod=main"], root)
    assert r.returncode == 0
    assert "optional/gsOther" in r.stderr and "optional/gsMod" not in r.stderr


# ---------------------------------------------------------------------------
# review_scope.sh: --split-renames, --no-skip and unchanged default output
# ---------------------------------------------------------------------------


def test_scope_default_lists_a_rename_as_one_row(root: Path) -> None:
    git(root, "mv", "src/gsCore/gsOther.h", "src/gsCore/gsOther2.h")
    rc, out = scope(root, "--all-files")
    assert rc == 0
    assert out == [".\tR\tsrc/gsCore/gsOther2.h", "STATUS: OK 1 files"]


def test_scope_split_renames_lists_delete_and_add(root: Path) -> None:
    git(root, "mv", "src/gsCore/gsOther.h", "src/gsCore/gsOther2.h")
    rc, out = scope(root, "--all-files", "--split-renames")
    assert rc == 0
    assert out == [".\tD\tsrc/gsCore/gsOther.h", ".\tA\tsrc/gsCore/gsOther2.h", "STATUS: OK 2 files"]
    rc, out = scope(root, "--lines", "--split-renames")
    assert out == ["src/gsCore/gsOther2.h\t1-1", "STATUS: OK 1 files"]


def _skipped_tree(root: Path) -> None:
    for rel in ("external/lib.h", "build/b.h", "src/gsCore/env/e.h", ".claude/c.md", "src/ok.h"):
        write(root, rel, "a\n")
    commit_files(root, "dirs", "external", "build", "src", ".claude")
    for rel in ("external/lib.h", "build/b.h", "src/gsCore/env/e.h", ".claude/c.md", "src/ok.h"):
        write(root, rel, "b\n")


def test_scope_default_skips_external_even_with_all_files(root: Path) -> None:
    _skipped_tree(root)
    rc, out = scope(root, "--all-files")
    assert out == [".\tM\tsrc/ok.h", "STATUS: OK 1 files"]


def test_scope_no_skip_keeps_all_but_git_claude_and_top_level_build(root: Path) -> None:
    _skipped_tree(root)
    write(root, "src/buildTools/t.h", "a\n")
    write(root, "build/untracked.o", "a\n")
    write(root, "build-release/untracked.o", "a\n")
    rc, out = scope(root, "--all-files", "--no-skip")
    assert rc == 0
    assert out == [".\tM\tbuild/b.h", ".\tM\texternal/lib.h", ".\tA\tsrc/buildTools/t.h",
                   ".\tM\tsrc/gsCore/env/e.h", ".\tM\tsrc/ok.h", "STATUS: OK 5 files"]


def test_scope_help_mentions_new_options(root: Path) -> None:
    r = run(["bash", str(SCOPE), "--help"], root)
    assert r.returncode == 0
    assert "--split-renames" in r.stdout and "--no-skip" in r.stdout
    assert r.stdout.rstrip().endswith("git error).")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def test_check_clean_inside_home(root: Path) -> None:
    write(root, "optional/gsMod/src/gsMod/gsMod.cpp", "int a;\nint b;\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 0
    assert out[-1] == "STATUS: OK"
    assert out[-2].startswith("STAT\tBUDGET\tmd5=") and "\toutside=0" in out[-2]


def test_check_modified_core_file_is_violation(root: Path) -> None:
    write(root, "src/gsCore/gsBasis.h", "#pragma once\nclass gsBasis { int x; };\n")
    path = budget(root, BASIC + "allow src/gsCore/gsFunctionSet.h reason\n")
    rc, out, _ = intrusion(root, "check", path)
    assert rc == 1
    assert out[0] == ("src/gsCore/gsBasis.h:1\tDS-BUDGET\tmajor\tmodified outside the intrusion "
                      "budget (not under home, not allowed)")
    md5 = hashlib.md5(Path(path).read_bytes()).hexdigest()
    assert out[1:3] == [f"SKIP\tbase\t.\t{NO_BASE}", f"SKIP\tbase\toptional/gsMod\t{NO_BASE}"]
    assert out[3] == f"STAT\tBUDGET\tmd5={md5}\thome=1\tallow=1\tchanged=1\toutside=1"
    assert out[4] == "STATUS: FINDINGS 1"


@pytest.mark.parametrize("allow", [
    "allow src/gsCore/gsBasis.h",
    "allow src/gsCore/gs*.h",
    "allow src/gsCore/",
])
def test_check_allow_row_variants(root: Path, allow: str) -> None:
    write(root, "src/gsCore/gsBasis.h", "changed\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + allow + "\n"))
    assert rc == 0 and out[-1] == "STATUS: OK"


def test_check_new_file_under_src_vs_examples(root: Path) -> None:
    write(root, "examples/new_example.cpp", "int main() {}\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 0 and out[-1] == "STATUS: OK"
    write(root, "src/gsCore/gsNew.h", "x\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1
    assert out[0].startswith("src/gsCore/gsNew.h:1\tDS-BUDGET\tmajor\tnew file under src/ outside")


def test_check_deleted_core_file(root: Path) -> None:
    (root / "src/gsCore/gsOther.h").unlink()
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1
    assert out[0].startswith("src/gsCore/gsOther.h:1\tDS-BUDGET\tmajor\tdeleted outside")


def test_check_rows_sorted_by_path(root: Path) -> None:
    write(root, "src/gsCore/gsOther.h", "z\n")
    write(root, "src/gsCore/gsBasis.h", "z\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert [l.split(":")[0] for l in out[:2]] == ["src/gsCore/gsBasis.h", "src/gsCore/gsOther.h"]
    assert out[-1] == "STATUS: FINDINGS 2"


def test_check_base_rows_pick_up_committed_work(root: Path) -> None:
    branch_commit(root, "src/gsCore/gsBasis.h", "committed change\n")
    branch_commit(root / "optional/gsMod", "src/gsMod/gsMod.cpp", "int a;\nint b;\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 0 and "changed=0" in stat(out)
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base . main\n"))
    assert rc == 1 and out[0].startswith("src/gsCore/gsBasis.h:1\tDS-BUDGET")
    assert "changed=1" in stat(out)
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base . main\nbase optional/gsMod main\n"))
    assert rc == 1 and "changed=2" in stat(out) and "outside=1" in stat(out)


def test_check_scope_failure_relayed(root: Path) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base . no-such-ref\n"))
    assert rc == 2 and out[-1].startswith("STATUS: FAIL ") and "no-such-ref" in out[-1]
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base optional/nope main\n"))
    assert rc == 2 and out[-1].startswith("STATUS: FAIL ")


def test_check_files_inventory(root: Path) -> None:
    lst = root.parent / "files.txt"
    lst.write_text("# plan\n\nsrc/gsCore/gsBasis.h\noptional/gsMod/src/gsMod/new.h\nexamples/n.cpp\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC), "--files", str(lst))
    assert rc == 1
    assert out[0].startswith("src/gsCore/gsBasis.h:1\tDS-BUDGET\tmajor\tmodified outside")
    assert "changed=3" in out[1] and "outside=2" in out[1]
    assert out[2] == "STATUS: FINDINGS 1"
    assert rows(out, "SKIP") == []


def test_home_prefix_needs_a_path_boundary(root: Path) -> None:
    write(root, "src/gsCoreX/x.h", "a\n")
    write(root, "optional/gsModExtra/y.h", "a\n")
    commit_files(root, "siblings", "src/gsCoreX", "optional/gsModExtra")
    write(root, "src/gsCoreX/x.h", "b\n")
    write(root, "optional/gsModExtra/y.h", "b\n")
    write(root, "src/gsCore/gsBasis.h", "b\n")
    rc, out, _ = intrusion(root, "check", budget(root, "home src/gsCore\nhome optional/gsMod\n"))
    assert rc == 1
    assert finding_paths(out) == ["optional/gsModExtra/y.h", "src/gsCoreX/x.h"]


def test_check_flags_changed_non_source_file_under_src(root: Path) -> None:
    write(root, "src/gsCore/data.xml", "<a/>\n")
    commit_files(root, "xml", "src/gsCore/data.xml")
    write(root, "src/gsCore/data.xml", "<b/>\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1 and finding_paths(out) == ["src/gsCore/data.xml"]


def test_check_flags_files_under_formerly_skipped_directories(root: Path) -> None:
    for rel in ("external/lib.h", "src/gsCore/env/e.h"):
        write(root, rel, "a\n")
    commit_files(root, "dirs", "external", "src/gsCore/env")
    for rel in ("external/lib.h", "src/gsCore/env/e.h"):
        write(root, rel, "b\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1 and finding_paths(out) == ["external/lib.h", "src/gsCore/env/e.h"]


def test_check_core_file_moved_into_home_is_a_deletion(root: Path) -> None:
    write(root, "src/gsFeature/f.h", "a\n")
    commit_files(root, "feature dir", "src/gsFeature")
    git(root, "mv", "src/gsCore/gsOther.h", "src/gsFeature/gsOther.h")
    rc, out, _ = intrusion(root, "check", budget(root, "home src/gsFeature\n"))
    assert rc == 1
    assert out[0].startswith("src/gsCore/gsOther.h:1\tDS-BUDGET\tmajor\tdeleted outside")
    assert finding_paths(out) == ["src/gsCore/gsOther.h"]


def test_check_rename_inside_core_flags_the_old_path(root: Path) -> None:
    git(root, "mv", "src/gsCore/gsOther.h", "src/gsCore/gsOther2.h")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1
    assert finding_paths(out) == ["src/gsCore/gsOther.h", "src/gsCore/gsOther2.h"]
    rc, out, _ = intrusion(root, "check", budget(
        root, BASIC + "allow src/gsCore/gsOther.h\nallow src/gsCore/gsOther2.h\n"))
    assert rc == 0
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/gsCore/gsOther2.h\n"))
    assert rc == 1 and finding_paths(out) == ["src/gsCore/gsOther.h"]


# ---------------------------------------------------------------------------
# check --files: path normalisation
# ---------------------------------------------------------------------------


def _inventory(root: Path, *lines: str) -> str:
    lst = root.parent / "files.txt"
    lst.write_text("\n".join(lines) + "\n")
    return str(lst)


def test_files_dotdot_path_is_normalised_not_trusted(root: Path) -> None:
    lst = _inventory(root, "optional/gsMod/../../src/gsCore/gsBasis.h")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC), "--files", lst)
    assert rc == 1 and finding_paths(out) == ["src/gsCore/gsBasis.h"]


def test_files_absolute_path_under_root_becomes_relative(root: Path) -> None:
    lst = _inventory(root, str(root / "src/gsCore/gsBasis.h"))
    rc, out, _ = intrusion(root, "check", budget(root, BASIC), "--files", lst)
    assert rc == 1 and finding_paths(out) == ["src/gsCore/gsBasis.h"]


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.h", "src/../../outside.h"])
def test_files_path_outside_root_fails(root: Path, bad: str) -> None:
    lst = _inventory(root, "src/gsCore/gsBasis.h", bad)
    rc, out, _ = intrusion(root, "check", budget(root, BASIC), "--files", lst)
    assert rc == 2
    assert out == [f"STATUS: FAIL path outside the G+Smo root: {bad}"]


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def test_budget_with_bom_is_accepted(root: Path) -> None:
    p = root.parent / "budget.txt"
    p.write_bytes(b"\xef\xbb\xbf" + BASIC.encode())
    rc, out, _ = intrusion(root, "check", str(p))
    assert rc == 0 and out[-1] == "STATUS: OK"


def test_list_file_with_invalid_utf8_does_not_crash(root: Path) -> None:
    lst = root.parent / "files.txt"
    lst.write_bytes(b"# caf\xe9\nsrc/gsCore/gsBasis.h\nsrc/gsCore/bad\xff.h\n")
    r = subprocess.run(["bash", str(INTRUSION), "check", budget(root, BASIC), "--files", str(lst)],
                       cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       env={**{k: v for k, v in os.environ.items() if not k.startswith("GISMO_")}})
    assert r.returncode == 1, r.stderr
    assert b"src/gsCore/bad\xff.h:1\tDS-BUDGET" in r.stdout
    assert r.stdout.rstrip().endswith(b"STATUS: FINDINGS 2")


def test_untracked_file_with_invalid_utf8_name(root: Path) -> None:
    name = os.fsdecode(b"src/gsCore/bad\xff.h")
    try:
        write(root, name, "a\nb\n")
    except OSError:
        pytest.skip("file system refuses non-UTF-8 names")
    env = {**{k: v for k, v in os.environ.items() if not k.startswith(("GISMO_", "GIT_"))}, **GIT_ENV}
    for sub in ("check", "measure"):
        r = subprocess.run(["bash", str(INTRUSION), sub, budget(root, BASIC)], cwd=root, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert r.returncode in (0, 1), r.stderr
        assert b"src/gsCore/bad\xff.h" in r.stdout


def test_unexpected_exception_is_status_fail_exit_2(tmp_path: Path, monkeypatch, capsys) -> None:
    spec = importlib.util.spec_from_file_location("intrusion_under_test", HERE / "intrusion.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["intrusion_under_test"] = mod
    spec.loader.exec_module(mod)

    def boom(*_a, **_k):
        raise ZeroDivisionError("boom")

    monkeypatch.setenv("GISMO_ROOT", str(tmp_path))
    monkeypatch.setattr(mod, "parse_budget", boom)
    assert mod.main(["check", "whatever"]) == 2
    assert capsys.readouterr().out.splitlines()[-1] == "STATUS: FAIL internal error: ZeroDivisionError: boom"


# ---------------------------------------------------------------------------
# Budget parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, needle", [
    ("# nothing\nallow src/x.h\n", "no home row"),
    ("home optional/gsMod\nfrobnicate x\n", "line 2:"),
    ("home optional/gsMod\n\nbase optional/gsMod\n", "line 3:"),
])
def test_budget_parse_failures(root: Path, text: str, needle: str) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, text))
    assert rc == 2
    assert out[-1].startswith("STATUS: FAIL ") and needle in out[-1]


def test_budget_parse_failure_for_measure(root: Path) -> None:
    rc, out, _ = intrusion(root, "measure", budget(root, "oops\n"))
    assert rc == 2 and "line 1:" in out[-1]


def test_budget_base_row_with_trailing_words_fails(root: Path) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base . main extra words\n"))
    assert rc == 2 and out[-1].startswith("STATUS: FAIL line 2:")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base . main # the stable branch\n"))
    assert rc == 0


@pytest.mark.parametrize("command", ["check", "measure"])
def test_budget_allow_glob_that_does_not_compile_fails_at_parse(root: Path, command: str) -> None:
    write(root, "optional/gsMod/src/gsMod/gsMod.cpp", "int a;\nint b;\n")
    rc, out, _ = intrusion(root, command, budget(root, BASIC + "allow src/gsCore/[z-a].h\n"))
    assert rc == 2 and out[-1].startswith("STATUS: FAIL line 2:"), out


@pytest.mark.parametrize("home", ["home .", "home /", "home ./", "home src/..", "home"])
def test_budget_home_of_everything_fails(root: Path, home: str) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, home + "\n"))
    assert rc == 2 and out[-1].startswith("STATUS: FAIL line 1:")


def test_budget_missing_home_message_has_no_line_number(root: Path) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, "allow src/x.h\n"))
    assert rc == 2
    assert out == ["STATUS: FAIL no home row (at least one is required)"]


def test_allow_existing_directory_without_slash(root: Path) -> None:
    write(root, "src/gsCore/gsBasis.h", "changed\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/gsCore\n"))
    assert rc == 0 and out[-1] == "STATUS: OK"
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow ./src/gsCore\n"))
    assert rc == 0


def test_glob_star_does_not_cross_slash(root: Path) -> None:
    write(root, "src/gsCore/gsBasis.h", "changed\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/*.h\n"))
    assert rc == 1 and finding_paths(out) == ["src/gsCore/gsBasis.h"]
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/**/gsBasis.h\n"))
    assert rc == 0
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/gsCore/**\n"))
    assert rc == 0


def test_glob_question_mark_does_not_cross_slash(root: Path) -> None:
    write(root, "src/gsCore/gsBasis.h", "changed\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/gsCore?gsBasis.h\n"))
    assert rc == 1
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/gsCor?/gsBasis.h\n"))
    assert rc == 0


# ---------------------------------------------------------------------------
# no-base hint
# ---------------------------------------------------------------------------


def test_committed_branch_work_hints_at_the_missing_base_row(root: Path) -> None:
    branch_commit(root, "src/gsCore/gsBasis.h", "committed change\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 0 and out[-1] == "STATUS: OK" and "changed=0" in stat(out)
    assert rows(out, "SKIP")[0] == f"SKIP\tbase\t.\t{NO_BASE}"
    assert out.index(rows(out, "SKIP")[-1]) < out.index(stat(out))
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base . main\n"))
    assert rc == 1 and finding_paths(out) == ["src/gsCore/gsBasis.h"]
    assert rows(out, "SKIP") == [f"SKIP\tbase\toptional/gsMod\t{NO_BASE}"]
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "base . main\nbase optional/gsMod main\n"))
    assert rows(out, "SKIP") == []


def test_skip_row_only_for_nested_repositories_with_a_home_path(root: Path) -> None:
    add_second_module(root)
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rows(out, "SKIP") == [f"SKIP\tbase\t.\t{NO_BASE}", f"SKIP\tbase\toptional/gsMod\t{NO_BASE}",
                                 f"SKIP\tbase\t1 other nested repositories\t{NO_BASE}"]
    rc, out, _ = intrusion(root, "check", budget(root, "home optional/gsMod\nhome optional/gsOther\n"))
    assert rows(out, "SKIP") == [f"SKIP\tbase\t.\t{NO_BASE}", f"SKIP\tbase\toptional/gsMod\t{NO_BASE}",
                                 f"SKIP\tbase\toptional/gsOther\t{NO_BASE}"]
    rc, out, _ = intrusion(root, "check", budget(root, "home optional\n"))
    assert len(rows(out, "SKIP")) == 3


def test_measure_prints_the_same_skip_rows(root: Path) -> None:
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert rows(out, "SKIP") == [f"SKIP\tbase\t.\t{NO_BASE}", f"SKIP\tbase\toptional/gsMod\t{NO_BASE}"]
    assert out[-1] == "STATUS: OK"


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


def test_nested_file_with_a_tab_in_its_name(root: Path) -> None:
    name = "src/gsMod/a\tb.h"
    write(root, "optional/gsMod/" + name, "#pragma once\nint a;\nint b;\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 0 and out[-1] == "STATUS: OK", out
    assert finding_paths(out) == []
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert rc == 0, out
    assert rows(out, "FILE") == []
    rc, out, _ = intrusion(root, "measure", budget(root, "home src/gsCore/\n"))
    assert rc == 0, out
    file_rows = rows(out, "FILE")
    assert len(file_rows) == 1 and "\tadded=3\tremoved=0\t" in file_rows[0], out


def test_measure_counts(root: Path) -> None:
    write(root, "src/gsCore/gsBasis.h",
          '#pragma once\nclass gsBasis {};\n#include <gsMod/gsMod.h>\nvirtual void f();\n'
          "// virtual comment\n")
    write(root, "src/gsCore/gsOther.h", "#pragma once\n#include <vector>\n")
    write(root, "examples/new_example.cpp", "int main() {}\nint x;\n")
    path = budget(root, BASIC + "allow src/gsCore/gsBasis.h\n")
    rc, out, _ = intrusion(root, "measure", path)
    assert rc == 0, out
    assert rows(out, "FILE") == [
        "FILE\t.\tA\texamples/new_example.cpp\tadded=2\tremoved=0\tvirtual=0\tincludes=0"
        "\thome_includes=0\tpublic_header=no\tallowed=no\texempt=yes",
        "FILE\t.\tM\tsrc/gsCore/gsBasis.h\tadded=3\tremoved=0\tvirtual=1\tincludes=1"
        "\thome_includes=1\tpublic_header=yes\tallowed=yes\texempt=no",
        "FILE\t.\tM\tsrc/gsCore/gsOther.h\tadded=1\tremoved=0\tvirtual=0\tincludes=1"
        "\thome_includes=0\tpublic_header=yes\tallowed=no\texempt=no",
    ]
    assert stat(out) == ("STAT\tTOTAL\tfiles=3\tadded=6\tremoved=0\tvirtual=1\tincludes=2"
                         "\thome_includes=1\tpublic_headers=2\tnot_allowed=2\texempt=1")
    assert out[-1] == "STATUS: OK"


def test_measure_skips_home_and_uses_base(root: Path) -> None:
    branch_commit(root, "src/gsCore/gsBasis.h", "#pragma once\nclass gsBasis {};\nvirtual int g();\n")
    write(root, "optional/gsMod/src/gsMod/gsMod.h", "changed\n")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC + "base . main\n"))
    assert rc == 0
    assert rows(out, "FILE")[0].startswith("FILE\t.\tM\tsrc/gsCore/gsBasis.h\tadded=1\tremoved=0\tvirtual=1")
    assert stat(out).startswith("STAT\tTOTAL\tfiles=1\t")


def test_measure_deleted_file_counts_removed(root: Path) -> None:
    (root / "src/gsCore/gsOther.h").unlink()
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert rows(out, "FILE")[0].startswith("FILE\t.\tD\tsrc/gsCore/gsOther.h\tadded=0\tremoved=1")


def test_measure_rename_is_a_deletion_and_an_addition(root: Path) -> None:
    git(root, "mv", "src/gsCore/gsOther.h", "src/gsCore/gsOther2.h")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    f = rows(out, "FILE")
    assert f[0].startswith("FILE\t.\tD\tsrc/gsCore/gsOther.h\tadded=0\tremoved=1")
    assert f[1].startswith("FILE\t.\tA\tsrc/gsCore/gsOther2.h\tadded=1\tremoved=0")
    assert f[1].endswith("exempt=no")


def test_measure_rename_into_home_leaves_the_deletion(root: Path) -> None:
    write(root, "src/gsFeature/f.h", "a\n")
    commit_files(root, "feature dir", "src/gsFeature")
    git(root, "mv", "src/gsCore/gsOther.h", "src/gsFeature/gsOther.h")
    rc, out, _ = intrusion(root, "measure", budget(root, "home src/gsFeature\n"))
    f = rows(out, "FILE")
    assert len(f) == 1 and f[0].startswith("FILE\t.\tD\tsrc/gsCore/gsOther.h\tadded=0\tremoved=1")


def test_measure_base_rows(root: Path) -> None:
    branch_commit(root, "src/gsCore/gsBasis.h", "#pragma once\nint x;\n")
    n = add_second_module(root)
    write(n, "src/gsOther/o.h", "changed\n")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC + "base . main\n"))
    assert rc == 0
    assert rows(out, "BASE") == [f"BASE\t.\t{rev(root, 'main')}", f"BASE\toptional/gsOther\t{rev(n)}"]
    first_file = next(i for i, l in enumerate(out) if l.startswith("FILE\t"))
    assert all(out.index(b) < first_file for b in rows(out, "BASE"))
    assert rev(root, "main") != rev(root)


def test_measure_no_base_row_when_nothing_scanned(root: Path) -> None:
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert rows(out, "BASE") == [] and rows(out, "FILE") == []


def test_measure_exempt_flag_and_total(root: Path) -> None:
    write(root, "examples/new.cpp", "int a;\n")
    write(root, "src/gsCore/gsNew.h", "int a;\n")
    write(root, "src/gsCore/gsBasis.h", "int a;\n")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    flags = {l.split("\t")[3]: l.split("\t")[-1] for l in rows(out, "FILE")}
    assert flags == {"examples/new.cpp": "exempt=yes", "src/gsCore/gsNew.h": "exempt=no",
                     "src/gsCore/gsBasis.h": "exempt=no"}
    assert stat(out).endswith("\texempt=1") and "files=3" in stat(out)


def _virtual_count(root: Path, added: str) -> int:
    write(root, "src/gsCore/gsOther.h", "#pragma once\n" + added)
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert rc == 0, out
    row = next(l for l in rows(out, "FILE") if "\tsrc/gsCore/gsOther.h\t" in l)
    return int(next(f for f in row.split("\t") if f.startswith("virtual=")).split("=")[1])


@pytest.mark.parametrize("added, expected", [
    ("++counter; virtual void f();\n", 1),
    ('const char* s = "virtual";\n', 0),
    ('const char* s = "a \\" virtual";\n', 0),
    ("int x; // virtual\n", 0),
    ("/* c */ virtual void b();\n", 1),
    ("int m_virtualDofs;\n", 0),
    ("/*\n * virtual stuff\n */\nint z;\n", 0),
    ("/**\n virtual stuff\n*/ virtual int g();\n", 1),
    ("virtual int a();\nvirtual int b();\n", 2),
    ("/* open\n * virtual\n", 0),
    ("   * virtual\n", 1),
])
def test_measure_virtual_counting(root: Path, added: str, expected: int) -> None:
    assert _virtual_count(root, added) == expected


def test_measure_added_line_starting_with_plus_plus_is_counted(root: Path) -> None:
    write(root, "src/gsCore/gsOther.h", "#pragma once\n++counter;\n")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert "\tadded=1\tremoved=0\t" in rows(out, "FILE")[0]
    assert _virtual_count(root, "++counter; virtual void f();\n") == 1


def _includes(root: Path, rel: str, text: str) -> Tuple[int, int]:
    write(root, rel, text)
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    row = next(l for l in rows(out, "FILE") if f"\t{rel}\t" in l)
    fields = dict(f.split("=") for f in row.split("\t") if "=" in f)
    return int(fields["includes"]), int(fields["home_includes"])


def test_measure_home_include_forms(root: Path) -> None:
    write(root, "src/gsCore/gsMod.h", "#pragma once\n")
    commit_files(root, "sibling", "src/gsCore/gsMod.h")
    # (a) path from the root, (b) path suffix, (c) bare name without a sibling
    assert _includes(root, "src/gsCore/gsBasis.h",
                     '#include "optional/gsMod/src/gsMod/gsMod.h"\n') == (1, 1)
    assert _includes(root, "src/gsCore/gsBasis.h", "#include <gsMod/gsMod.h>\n") == (1, 1)
    assert _includes(root, "examples/ex.cpp", '#include "gsMod.h"\n') == (1, 1)
    # a bare name next to the including file is that sibling, not the home header
    assert _includes(root, "src/gsCore/gsBasis.h", '#include "gsMod.h"\n') == (1, 0)
    assert _includes(root, "src/gsCore/gsBasis.h", "#include <vector>\n#include <gsCore/gsMod.hh>\n") == (2, 0)


def test_measure_untracked_symlink_counts_one_line(root: Path) -> None:
    write(root, "target.txt", "a\nb\nc\nd\nvirtual int f();\n")
    os.symlink(root / "target.txt", root / "examples" / "link.h")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    row = next(l for l in rows(out, "FILE") if "\texamples/link.h\t" in l)
    assert "\tadded=1\tremoved=0\tvirtual=0\t" in row


@pytest.mark.parametrize("content, lines", [
    (b"a\x0cb\nc\n", 2),
    (b"a\nb", 2),
    (b"a\n", 1),
    (b"\n\n", 2),
    (b"", 0),
    (b"x\x00y\n", 0),
])
def test_measure_untracked_line_count_matches_git(root: Path, content: bytes, lines: int) -> None:
    (root / "examples").mkdir(exist_ok=True)
    (root / "examples" / "u.txt").write_bytes(content)
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    rows_ = [l for l in rows(out, "FILE") if "\texamples/u.txt\t" in l]
    if content == b"":
        # git lists an empty untracked file; it adds no lines
        assert rows_ == [] or f"\tadded=0\t" in rows_[0]
    else:
        assert f"\tadded={lines}\tremoved=0\t" in rows_[0]


# ---------------------------------------------------------------------------
# stderr never reaches stdout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sub", ["check", "measure"])
def test_scope_notice_stays_on_stderr(root: Path, sub: str) -> None:
    write(root, "src/gsCore/gsBasis.h", "changed\n")
    rc, out, err = intrusion(root, sub, budget(root, BASIC + "base . main\n"))
    assert "optional/gsMod" in err and "--base does not apply" in err
    assert not any("review_scope" in l for l in out)
    assert out[-1].startswith("STATUS: ")


@pytest.mark.parametrize("sub", ["check", "measure"])
def test_scope_notice_names_only_modules_without_a_base(root: Path, sub: str) -> None:
    add_second_module(root)
    write(root, "src/gsCore/gsBasis.h", "changed\n")
    rc, out, err = intrusion(root, sub, budget(root, BASIC + "base . main\nbase optional/gsMod main\n"))
    assert "optional/gsOther" in err and "optional/gsMod" not in err
    assert not any("review_scope" in l for l in out)


def test_outside_a_checkout_fails(tmp_path: Path) -> None:
    rc, out, _ = intrusion(tmp_path, "check", "whatever")
    assert rc == 2 and out == ["STATUS: FAIL not inside a G+Smo checkout"]


# ---------------------------------------------------------------------------
# names git quotes, whole-tree globs, stable allows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a\tb.h", 'q"uote.h', "back\\slash.h"])
def test_check_sees_a_new_src_file_whose_name_git_quotes(root: Path, name: str) -> None:
    write(root, f"src/gsCore/{name}", "x\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1
    assert out[-1] == "STATUS: FINDINGS 1"
    assert "\tDS-BUDGET\tmajor\tnew file under src/" in out[0] and out[0].startswith("src/gsCore/")


def test_quoted_name_inside_home_is_not_a_violation(root: Path) -> None:
    write(root, "optional/gsMod/src/a\tb.h", "x\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 0, out


def test_measure_counts_a_file_whose_name_git_quotes(root: Path) -> None:
    write(root, "src/gsCore/n\tew.h", "one\ntwo\n")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    row = [r for r in rows(out, "FILE") if "ew.h" in r][0]
    assert "\tadded=2\t" in row and row.endswith("exempt=no")
    assert "n\\tew.h" in row


def test_measure_treats_a_glob_character_in_a_name_literally(root: Path) -> None:
    write(root, "src/gsCore/gsOther.h*", "a\n")
    commit_files(root, "star", "src")
    write(root, "src/gsCore/gsOther.h*", "a\nb\n")
    write(root, "src/gsCore/gsOther.h", "1\n2\n3\n4\n5\n6\n7\n8\n")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    row = [r for r in rows(out, "FILE") if "gsOther.h*" in r][0]
    assert "\tadded=1\t" in row


@pytest.mark.parametrize("pattern", ["src", "src/", "src/**", "src/*/**", "src/gs*/**", "src/**/*.h", "optional",
                                     "optional/**", "optional/*/src/**"])
def test_allow_that_covers_all_of_core_or_every_module_fails(root: Path, pattern: str) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + f"allow {pattern}\n"))
    assert rc == 2
    assert out[-1].startswith("STATUS: FAIL line 2:") and "covers all of" in out[-1]


@pytest.mark.parametrize("pattern", ["src/gsCore/**", "src/gsCore/", "src/*", "src/**/gsBasis.h",
                                     "optional/gsOther/", "optional/gsOther/src/**"])
def test_allow_of_one_directory_or_module_is_accepted(root: Path, pattern: str) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + f"allow {pattern}\n"))
    assert rc == 0 and out[-1] == "STATUS: OK"


@pytest.mark.parametrize("rel", ["cmake/hook.cmake", ".github/workflows/ci.yml", "extra.cmake",
                                 "optional/gsOther/CMakeLists.txt"])
def test_check_flags_new_file_that_is_not_example_test_or_doc(root: Path, rel: str) -> None:
    write(root, rel, "x\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1
    assert out[0].startswith(f"{rel}:1\tDS-BUDGET\tmajor\tnew file that is not an example")
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert any(r.endswith("exempt=no") and rel in r for r in rows(out, "FILE"))


@pytest.mark.parametrize("rel", ["examples/new.cpp", "unittests/gsNew_test.cpp", "doc/new.dox",
                                 "optional/gsOther/examples/new.cpp",
                                 "optional/gsOther/unittests/new_test.cpp",
                                 "optional/gsOther/docs/new.md"])
def test_check_passes_new_example_test_or_doc(root: Path, rel: str) -> None:
    write(root, rel, "x\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 0 and out[-1] == "STATUS: OK"
    rc, out, _ = intrusion(root, "measure", budget(root, BASIC))
    assert any(r.endswith("exempt=yes") and rel in r for r in rows(out, "FILE"))


@pytest.mark.parametrize("pattern", ["**", "**/*", "*/**", "?*/**", "*.h", "[a-z]*/x.h"])
def test_allow_that_begins_with_a_wildcard_fails(root: Path, pattern: str) -> None:
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + f"allow {pattern}\n"))
    assert rc == 2
    assert out[-1].startswith("STATUS: FAIL line 2:")


def test_allow_without_glob_covers_file_and_subtree_whatever_is_on_disk(root: Path) -> None:
    b = budget(root, BASIC + "allow src/gsNewDir\nallow src/gsCore\n")
    lst = root.parent / "inv.txt"
    lst.write_text("src/gsNewDir/a.h\nsrc/gsCore/gsBasis.h\n")
    rc, out, _ = intrusion(root, "check", b, "--files", str(lst))
    assert rc == 0, out
    write(root, "src/gsNewDir/a.h", "x\n")
    rc, out, _ = intrusion(root, "check", b, "--files", str(lst))
    assert rc == 0, out
    rc, out, _ = intrusion(root, "check", budget(root, BASIC + "allow src/gsCor\n"), "--files", str(lst))
    assert rc == 1


def test_new_file_under_another_modules_src_is_a_violation(root: Path) -> None:
    add_second_module(root)
    write(root, "optional/gsOther/src/new.h", "x\n")
    write(root, "optional/gsOther/examples/new_example.cpp", "x\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1
    assert out[-1] == "STATUS: FINDINGS 1"
    assert out[0].startswith("optional/gsOther/src/new.h:1\tDS-BUDGET")


def test_tracked_file_in_top_level_build_directory_is_flagged(root: Path) -> None:
    write(root, "buildTools/tool.h", "a\n")
    commit_files(root, "tools", "buildTools")
    write(root, "buildTools/tool.h", "b\n")
    write(root, "build/generated.o", "x\n")
    rc, out, _ = intrusion(root, "check", budget(root, BASIC))
    assert rc == 1
    assert out[-1] == "STATUS: FINDINGS 1"
    assert out[0].startswith("buildTools/tool.h:1\tDS-BUDGET")


def test_root_merge_base_failure_text_names_no_repository(root: Path) -> None:
    rc, out = scope(root, "--base", "nope")
    assert rc == 2
    assert out[-1].startswith("STATUS: FAIL no merge-base between 'nope' and HEAD: ")
