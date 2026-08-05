---
name: build-target
description: Build a named G+Smo make target safely (never bare make, jobs capped). Use for any compilation of the library, examples, or tests. This wraps make with the guards agents must not bypass.
argument-hint: "<target> [jobs]"
allowed-tools: Bash(bash:*)
---

Build a G+Smo target by running the guarded wrapper — never call `make` directly:

```
bash ${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/build-target/scripts/build_target.sh <target> [jobs]
```

Rules the wrapper enforces (do not work around them):
- **A target is mandatory.** Bare `make` builds every example in the library and can run for hours.
- **`all` and `examples` are refused** unless `--yes-really` is passed; only do that when the user explicitly asked for a full build.
- **Jobs are clamped** to the configured cap (`.claude/gismo-dev.local.json`, default 4, hard cap `nproc/2`). Unbounded `-j` has crashed development machines by filling RAM.

Behaviour:
- The build dir comes from `/gismo:dev-config`'s config, or is auto-detected when exactly one `build*/` exists. If the script errors with "multiple build dirs", run `/gismo:dev-config` first.
- On failure it prints the last 40 lines and the path to the full log. If the target is unknown after adding a new `.cpp`, reconfigure with `(cd <builddir> && cmake .)` and retry once.
- The last line is always `STATUS: OK` or `STATUS: FAIL` — check it, not just the absence of errors.

Common targets: `gismo` (core library), `unittests` (all unit tests, needs `GISMO_BUILD_UNITTESTS=ON`), or any example/driver basename (e.g. `poisson_example` for `examples/poisson_example.cpp`).
