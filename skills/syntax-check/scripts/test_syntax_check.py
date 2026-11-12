"""Tests for syntax_check.py (HD-SELF) and the GISMO_NDEBUG / staleness logic of gismo_env.sh.

Each test builds a throwaway G+Smo-like tree with a ``compile_commands.json`` that points at
the system C++ compiler. Set ``SYNTAX_CHECK_PY`` / ``GISMO_ENV_SH`` to run the tests against
another copy of the scripts.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SYNTAX_CHECK = Path(os.environ.get("SYNTAX_CHECK_PY", HERE / "syntax_check.py"))
GISMO_ENV = Path(os.environ.get("GISMO_ENV_SH", HERE.parent.parent / "dev-config" / "scripts" / "gismo_env.sh"))
CXX = shutil.which("g++") or shutil.which("c++")

pytestmark = pytest.mark.skipif(CXX is None, reason="no C++ compiler installed")

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=GIT_ENV)


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def entry(root: Path, rel: str, extra: str = "") -> dict:
    return {
        "directory": str(root / "build"),
        "file": str(root / rel),
        "command": f"{CXX} -std=c++14 {extra} -I{root / 'src'} -I{root / 'include'} "
                   f"-c {root / rel} -o x.o",
    }


def make_tree(base: Path, entries: list[dict] | None = None) -> Path:
    """G+Smo-like root with a build dir, the prelude headers and a ``gismo.h`` that defines ``gsT``."""
    root = base / "gismo"
    write(root / "CMakeLists.txt")
    write(root / "src/gsCore/gsForwardDeclarations.h", "#pragma once\n")
    write(root / "src/gsCore/gsTemplateTools.h", "#pragma once\n")
    write(root / "src/gsCore/gsA.cpp", "int a;\n")
    write(root / "include/gismo.h", "#pragma once\ntypedef int gsT;\n")
    write(root / "build/CMakeCache.txt")
    if entries is None:
        entries = [entry(root, "src/gsCore/gsA.cpp")]
    write(root / "build/compile_commands.json", json.dumps(entries))
    return root


def run_check(root: Path, *files: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GISMO_ROOT": str(root), "GISMO_BUILD_DIR": str(root / "build")}
    return subprocess.run([sys.executable, str(SYNTAX_CHECK), *map(str, files)],
                          capture_output=True, text=True, env=env)


def commit_all(repo: Path) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = make_tree(tmp_path)
    git(root, "init", "-q")
    return root


NEEDS_GISMO = "#pragma once\ngsT x;\n"
SELF_CONTAINED = "#pragma once\nint y;\n"


# --- B1 -----------------------------------------------------------------------------------

def test_untracked_h_needing_gismo_fails(tree: Path) -> None:
    commit_all(tree)
    h = write(tree / "src/gsCore/gsNew.h", NEEDS_GISMO)
    res = run_check(tree, h)
    assert f"  FAIL {h}  (not self-contained: compiles only with gismo.h force-included)" in res.stdout
    assert res.stdout.rstrip().endswith("STATUS: FAIL")
    assert res.returncode == 1


def test_added_h_needing_gismo_fails(tree: Path) -> None:
    commit_all(tree)
    h = write(tree / "src/gsCore/gsNew.h", NEEDS_GISMO)
    git(tree, "add", str(h))
    res = run_check(tree, h)
    assert "not self-contained" in res.stdout and res.returncode == 1


def test_existing_h_needing_gismo_is_ok(tree: Path) -> None:
    h = write(tree / "src/gsCore/gsOld.h", NEEDS_GISMO)
    commit_all(tree)
    res = run_check(tree, h)
    assert f"  OK   {h}  (needs gismo.h)" in res.stdout
    assert res.returncode == 0 and res.stdout.rstrip().endswith("STATUS: OK")


def test_new_hpp_needing_gismo_is_ok(tree: Path) -> None:
    commit_all(tree)
    h = write(tree / "src/gsCore/gsNew.hpp", NEEDS_GISMO)
    res = run_check(tree, h)
    assert f"  OK   {h}  (needs gismo.h)" in res.stdout
    assert res.returncode == 0


def test_new_self_contained_h_is_ok(tree: Path) -> None:
    commit_all(tree)
    h = write(tree / "src/gsCore/gsNew.h", SELF_CONTAINED)
    res = run_check(tree, h)
    assert f"  OK   {h}\n" in res.stdout and res.returncode == 0


def test_nested_repository_decides_newness(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    mod = root / "optional/gsMod"
    write(mod / "m.cpp", "int m;\n")
    write(mod / "old.h", NEEDS_GISMO)
    cc = json.loads((root / "build/compile_commands.json").read_text())
    cc.append(entry(root, "optional/gsMod/m.cpp"))
    write(root / "build/compile_commands.json", json.dumps(cc))
    git(root, "init", "-q")
    git(mod, "init", "-q")
    commit_all(mod)
    commit_all(root)
    new = write(mod / "new.h", NEEDS_GISMO)
    res = run_check(root, mod / "old.h", new)
    assert f"  OK   {mod / 'old.h'}  (needs gismo.h)" in res.stdout
    assert f"  FAIL {new}  (not self-contained: compiles only with gismo.h force-included)" in res.stdout
    assert res.returncode == 1


def test_new_h_that_does_not_compile_even_with_gismo_keeps_diagnostics(tree: Path) -> None:
    commit_all(tree)
    h = write(tree / "src/gsCore/gsBad.h", "#pragma once\nthis is not c++;\n")
    res = run_check(tree, h)
    assert f"  FAIL {h}\n" in res.stdout and "error" in res.stdout and res.returncode == 1


# --- B2 -----------------------------------------------------------------------------------

def env_probe(root: Path, script: str, **extra: str) -> list[str]:
    """Run ``script`` after sourcing gismo_env.sh from ``root``; one stdout line per echo."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GISMO_")}
    env.update(extra)
    res = subprocess.run(["bash", "-c", f'source "{GISMO_ENV}"; cd "{root}"; {script}'],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    return res.stdout.split("\n")[:-1]


def ndebug(tmp_path: Path, entries: list[tuple[str, bool]], cache: str = "") -> str:
    """``GISMO_NDEBUG`` for entries given as ``(file relative to the root, has -DNDEBUG)``."""
    root = make_tree(tmp_path)
    ccs = [entry(root, rel, "-DNDEBUG" if nd else "") for rel, nd in entries]
    write(root / "build/compile_commands.json", json.dumps(ccs))
    write(root / "build/CMakeCache.txt", cache)
    return env_probe(root, 'gismo_env; echo "$GISMO_NDEBUG"')[0]


def test_external_entry_does_not_flip_ndebug(tmp_path: Path) -> None:
    assert ndebug(tmp_path, [("src/gsCore/gsA.cpp", False), ("external/zlib/z.c", True)]) == "0"


def test_all_src_entries_ndebug(tmp_path: Path) -> None:
    assert ndebug(tmp_path, [("src/gsCore/gsA.cpp", True), ("src/gsCore/gsB.cpp", True),
                             ("external/zlib/z.c", False)]) == "1"


def test_disagreeing_src_entries_are_unknown(tmp_path: Path) -> None:
    assert ndebug(tmp_path, [("src/gsCore/gsA.cpp", True), ("src/gsCore/gsB.cpp", False)]) == "unknown"


def test_no_src_entries_are_unknown(tmp_path: Path) -> None:
    assert ndebug(tmp_path, [("external/zlib/z.c", True)]) == "unknown"


def test_entry_outside_root_is_ignored(tmp_path: Path) -> None:
    assert ndebug(tmp_path, [("src/gsCore/gsA.cpp", False), ("../elsewhere/src/q.cpp", True)]) == "0"


def test_cache_with_ndebug_keeps_precedence(tmp_path: Path) -> None:
    cache = "CMAKE_BUILD_TYPE:STRING=Release\nCMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG\n"
    assert ndebug(tmp_path, [("src/gsCore/gsA.cpp", False)], cache) == "1"


def test_values_are_recomputed_on_second_call(tmp_path: Path) -> None:
    root_a = make_tree(tmp_path / "a")
    root_b = make_tree(tmp_path / "b")
    write(root_a / "build/compile_commands.json", json.dumps([entry(root_a, "src/gsCore/gsA.cpp", "-DNDEBUG")]))
    write(root_b / "build/compile_commands.json", json.dumps([entry(root_b, "src/gsCore/gsA.cpp")]))
    write(root_b / "build/CMakeCache.txt", "CMAKE_BUILD_TYPE:STRING=Debug\n")
    out = env_probe(
        root_a,
        'gismo_env; echo "$GISMO_ROOT $GISMO_NDEBUG ${GISMO_BUILD_TYPE}"; '
        f'cd "{root_b}"; gismo_env; echo "$GISMO_ROOT $GISMO_BUILD_DIR $GISMO_NDEBUG $GISMO_BUILD_TYPE"',
    )
    assert out[0] == f"{root_a} 1 unknown"
    assert out[1] == f"{root_b} {root_b / 'build'} 0 Debug"


def test_preset_values_survive_second_call(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    out = env_probe(root, 'gismo_env; gismo_env; echo "$GISMO_JOBS $GISMO_NDEBUG"',
                    GISMO_JOBS="1", GISMO_NDEBUG="0")
    assert out == ["1 0"]


def test_value_assigned_between_calls_survives(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    out = env_probe(root, 'gismo_env; GISMO_JOBS=1; GISMO_NDEBUG=1; gismo_env; '
                          'echo "$GISMO_JOBS $GISMO_NDEBUG"')
    assert out == ["1 1"]


def test_untouched_derived_value_is_still_recomputed(tmp_path: Path) -> None:
    root_a = make_tree(tmp_path / "a")
    root_b = make_tree(tmp_path / "b")
    out = env_probe(root_a, f'gismo_env; cd "{root_b}"; gismo_env; echo "$GISMO_ROOT"')
    assert out == [str(root_b)]


def test_ndebug_compares_paths_through_symlinks(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(root)
    write(root / "build/compile_commands.json",
          json.dumps([entry(root, "src/gsCore/gsA.cpp", "-DNDEBUG")]))
    out = env_probe(link, 'gismo_env; echo "$GISMO_NDEBUG"', GISMO_ROOT=str(link))
    assert out == ["1"]


@pytest.mark.parametrize("extra,expected", [
    ("-DNDEBUG", "1"),
    ("-DNDEBUG=1", "1"),
    ("-D NDEBUG", "1"),
    ("-D NDEBUG=1", "1"),
    ("-DNDEBUGX", "0"),
    ("-DNDEBUG -UNDEBUG", "0"),
    ("-DNDEBUG -U NDEBUG", "0"),
    ("-UNDEBUG -DNDEBUG", "1"),
    ("-U NDEBUG -D NDEBUG", "1"),
])
def test_ndebug_reads_arguments_as_tokens(tmp_path: Path, extra: str, expected: str) -> None:
    root = make_tree(tmp_path)
    write(root / "build/CMakeCache.txt", "CMAKE_BUILD_TYPE:STRING=Debug\n")
    write(root / "build/compile_commands.json",
          json.dumps([entry(root, "src/gsCore/gsA.cpp", extra)]))
    assert env_probe(root, 'gismo_env; echo "$GISMO_NDEBUG"')[0] == expected


@pytest.mark.parametrize("cache_flags,expected", [
    ("-O3 -DNDEBUG", "1"),
    ("-DNDEBUG=1", "1"),
    ("-D NDEBUG", "1"),
    ("-UNDEBUG -DNDEBUG", "1"),
    ("-DNDEBUG -UNDEBUG", "0"),
    ("-DNDEBUG -U NDEBUG", "0"),
    ("-DNDEBUGX", "0"),
])
def test_cache_ndebug_reads_flags_as_tokens(tmp_path: Path, cache_flags: str, expected: str) -> None:
    cache = f"CMAKE_BUILD_TYPE:STRING=Release\nCMAKE_CXX_FLAGS_RELEASE:STRING={cache_flags}\n"
    assert ndebug(tmp_path, [("src/gsCore/gsA.cpp", False)], cache) == expected


# --- --base ---------------------------------------------------------------------------------

def run_check_base(root: Path, base: str, *files: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GISMO_ROOT": str(root), "GISMO_BUILD_DIR": str(root / "build")}
    return subprocess.run([sys.executable, str(SYNTAX_CHECK), "--base", base, *map(str, files)],
                          capture_output=True, text=True, env=env)


@pytest.fixture
def branch_tree(tree: Path) -> Path:
    """Repository on ``main`` with one commit, then a feature branch checked out."""
    write(tree / "src/gsCore/gsOld.h", NEEDS_GISMO)
    git(tree, "checkout", "-q", "-b", "main")
    commit_all(tree)
    git(tree, "checkout", "-q", "-b", "feature")
    return tree


def test_base_flags_header_committed_on_branch(branch_tree: Path) -> None:
    h = write(branch_tree / "src/gsCore/gsNew.h", NEEDS_GISMO)
    commit_all(branch_tree)
    res = run_check_base(branch_tree, "main", h)
    assert f"  FAIL {h}  (not self-contained: compiles only with gismo.h force-included)" in res.stdout
    assert res.returncode == 1


def test_without_base_committed_header_is_ok(branch_tree: Path) -> None:
    h = write(branch_tree / "src/gsCore/gsNew.h", NEEDS_GISMO)
    commit_all(branch_tree)
    res = run_check(branch_tree, h)
    assert f"  OK   {h}  (needs gismo.h)" in res.stdout and res.returncode == 0


def test_base_keeps_header_existing_at_base_ok(branch_tree: Path) -> None:
    h = branch_tree / "src/gsCore/gsOld.h"
    res = run_check_base(branch_tree, "main", h)
    assert f"  OK   {h}  (needs gismo.h)" in res.stdout and res.returncode == 0


def test_base_that_does_not_resolve_falls_back(branch_tree: Path) -> None:
    h = write(branch_tree / "src/gsCore/gsNew.h", NEEDS_GISMO)
    commit_all(branch_tree)
    res = run_check_base(branch_tree, "no-such-ref", h)
    assert f"  OK   {h}  (needs gismo.h)" in res.stdout and res.returncode == 0
    assert "Traceback" not in res.stderr


def test_unresolvable_base_is_reported_once_per_repository_and_ref(branch_tree: Path) -> None:
    h1 = write(branch_tree / "src/gsCore/gsNew1.h", NEEDS_GISMO)
    h2 = write(branch_tree / "src/gsCore/gsNew2.h", NEEDS_GISMO)
    commit_all(branch_tree)
    res = run_check_base(branch_tree, "mian", h1, h2)
    assert res.returncode == 0
    lines = [ln for ln in res.stderr.splitlines() if "mian" in ln]
    assert len(lines) == 1
    assert str(branch_tree) in lines[0] and "git status only" in lines[0]


def test_base_without_merge_base_is_reported(branch_tree: Path) -> None:
    git(branch_tree, "checkout", "-q", "--orphan", "unrelated")
    h = write(branch_tree / "src/gsCore/gsNew.h", NEEDS_GISMO)
    commit_all(branch_tree)
    res = run_check_base(branch_tree, "main", h)
    assert "main" in res.stderr and "git status only" in res.stderr
    assert res.returncode == 0


def test_base_renamed_header_is_not_new(branch_tree: Path) -> None:
    old = branch_tree / "src/gsCore/gsOld.h"
    renamed = branch_tree / "src/gsCore/gsRenamed.h"
    old.rename(renamed)
    added = write(branch_tree / "src/gsCore/gsAdded.h", NEEDS_GISMO + "int z;\n")
    commit_all(branch_tree)
    res = run_check_base(branch_tree, "main", renamed, added)
    assert f"  OK   {renamed}  (needs gismo.h)" in res.stdout
    assert f"  FAIL {added}  (not self-contained" in res.stdout
    assert res.returncode == 1


def test_base_rename_to_path_with_space_is_not_new(branch_tree: Path) -> None:
    old = branch_tree / "src/gsCore/gsOld.h"
    renamed = branch_tree / "src/gsCore/gs Renamed.h"
    old.rename(renamed)
    commit_all(branch_tree)
    res = run_check_base(branch_tree, "main", renamed)
    assert f"  OK   {renamed}  (needs gismo.h)" in res.stdout
    assert res.returncode == 0


def test_base_copy_is_still_new(branch_tree: Path) -> None:
    copy = write(branch_tree / "src/gsCore/gsCopy.h", NEEDS_GISMO)
    commit_all(branch_tree)
    res = run_check_base(branch_tree, "main", copy)
    assert f"  FAIL {copy}  (not self-contained" in res.stdout
    assert res.returncode == 1


def test_base_without_value_is_an_error(branch_tree: Path) -> None:
    h = write(branch_tree / "src/gsCore/gsNew.h", NEEDS_GISMO)
    env = {**os.environ, "GISMO_ROOT": str(branch_tree),
           "GISMO_BUILD_DIR": str(branch_tree / "build")}
    res = subprocess.run([sys.executable, str(SYNTAX_CHECK), str(h), "--base"],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 2
    assert "--base needs a ref" in res.stderr
    assert "OK" not in res.stdout and "FAIL " not in res.stdout.replace("STATUS: FAIL", "")
