# Standing rules (every agent in a `/gismo:implement` run)

These hold in every plan. A plan's `rules.md` carries only the facts specific to that plan (which
paths are tracked, which target builds what, which tolerance was pre-registered), each with its
verifying command; it never re-types a rule from this file, and a spec never restates one. Each rule
names the mechanism to use instead, because a blocklist covers only the commands someone thought of.

- **Files are created and changed with Write and Edit.** No shell duplication of repo files in any
  form (`cp`, `mv`, `cat a > b`, `tee`, `dd`, `install`, `rsync`), no `sed -i`, no output redirect
  into a source file. Read the file, then Write or Edit the new content.
- **The user commits.** No git write command (`add`, `commit`, `checkout`, `restore`, `stash`,
  `reset`, `rebase`, `merge`), and never `git worktree prune`, even when a git error message
  suggests it: report the worktree error and stop. Read-only git (`status`, `diff`, `log`, `show`,
  `rev-parse`) is fine.
- **Builds go through `build_target.sh`, tests through `run_unittests.sh`** (both under
  `${CLAUDE_PLUGIN_ROOT}/skills/`). They cap the job count and refuse an unnamed target; bare
  `make`, `-j`, removing or reconfiguring a build directory are covered in **Build safety** of
  `${CLAUDE_PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md`.
- **A denied command is reported, never replaced.** If the permission system denies a command,
  stop and say which one and what it was for. Do not retry it as a neighbour (`rm -r` for `rm -rf`,
  `mv` as `cp` then `rm`): the denial is the rule firing, and a substitute reaches the same effect
  by a path nobody approved.
- **Whether assertions are live is read, never assumed.** `GISMO_NDEBUG` (from
  `bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh`) is `1` when `GISMO_ASSERT`
  and `assert` are compiled out, `0` when live, `unknown` when undecidable. A test or a claim that
  depends on an assertion firing states the value it read; with `unknown` or `1` it does not claim
  that the assertion was exercised. Build type does not decide it (G+Smo's `RelWithDebInfo` keeps
  assertions live).
- **Comments explain the code, never the change.** The full rule, with what stays, is **Comment
  discipline** in `${CLAUDE_PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md`; the mechanical part of
  it is checked by `review_lint.sh` (rule IDs `CM-*`, in
  `${CLAUDE_PLUGIN_ROOT}/skills/review/CONVENTIONS.md`).
