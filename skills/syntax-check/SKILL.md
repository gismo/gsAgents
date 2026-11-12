---
name: syntax-check
description: Fast per-file compile gate for G+Smo C++ files (-fsyntax-only with the build tree's real per-file flags from compile_commands.json). Run on every file you created or edited BEFORE building a target — it catches errors in seconds instead of minutes. Requires compile_commands.json (see /gismo:dev-config).
argument-hint: "[--allow-degraded] [--base <ref>] <file...>"
allowed-tools: Bash(bash:*)
---

Check that C++ files compile, without linking or building anything:

```
bash ${CLAUDE_PLUGIN_ROOT}/skills/syntax-check/scripts/syntax_check.sh <file> [<file> ...]
```

- Works on `.cpp` and on headers (`.h`/`.hpp` are wrapped in a temporary translation unit that `#include`s them). A header that fails standalone is retried once with `gismo.h` force-included; if that passes it is reported `OK   <path>  (needs gismo.h)` — not self-contained, but it builds in real TUs — and if it still fails it is `FAIL` with the retry's diagnostics. The retry excuses existing headers and every `.hpp`, many of which are not self-contained by design. It does not excuse a new `.h`: one that is untracked or staged as added in its repository, or, with `--base <ref>`, one that does not exist at the merge base of `<ref>` and `HEAD`. Give `--base` when checking a branch, since a header added by an earlier commit looks existing to `git status`. A new `.h` that compiles only with the force-include is `FAIL <path>  (not self-contained: compiles only with gismo.h force-included)` and fails the run, because a new header is where rule HD-SELF can still be met for free.
- A file with neither an entry nor a sibling entry (e.g. a header-only directory) borrows the flags of the nearest configured directory above it (never `optional/`), else of any `src/` entry; the result line then ends in `(flags from <dir>/)`. A file under `optional/<module>/` borrows only from that same module. If no flags can be found the file is reported `  SKIP <path>  (no compile flags)`, the remaining files are still checked, and the run ends `STATUS: INCOMPLETE` with exit 2 (unless something FAILed: `STATUS: FAIL`, exit 1) — treat INCOMPLETE as "not verified", not as a pass.
- **`compile_commands.json` in the build dir is required, asserted up front.** Exact per-file flags matter: a submodule file compiled with different defines/includes than the core library must not be silently checked with the wrong ones. If it's missing, the script fails immediately and tells you to run `/gismo:dev-config` (which enables `CMAKE_EXPORT_COMPILE_COMMANDS` and regenerates it for you — a cheap, non-destructive reconfigure, no rebuild triggered).
- Brand-new files not yet in `compile_commands.json` are matched by nearest-neighbour (any entry from a sibling file in the same directory). If even that fails — reconfigure: `cd <builddir> && cmake .`
- `--allow-degraded` bypasses the assertion and falls back to the core library's `flags.make` (library-wide flags) — emergency use only, may miss submodule-specific flags; do not reach for this as a default.
- Last line is `STATUS: OK`, `STATUS: FAIL` or `STATUS: INCOMPLETE`; everything is written to stdout, each file's result line (`  OK   <path>` / `  FAIL <path>`) followed by its own compiler diagnostics, in input order.

Workflow rule for implementer agents: **syntax-check every touched file first, then build the target** with `/gismo:build-target`. Never skip straight to `make` — a full target build to find a typo wastes minutes.

Caveat: template `.hpp` bodies are only parsed, not instantiated — a passing check does not guarantee the templated code compiles for all instantiations; the target build remains the real test.
