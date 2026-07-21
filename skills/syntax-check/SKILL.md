---
name: syntax-check
description: Fast per-file compile gate for G+Smo C++ files (-fsyntax-only with the build tree's real per-file flags from compile_commands.json). Run on every file you created or edited BEFORE building a target — it catches errors in seconds instead of minutes. Requires compile_commands.json (see /gismo:dev-config).
argument-hint: "[--allow-degraded] <file...>"
allowed-tools: Bash(bash:*)
---

Check that C++ files compile, without linking or building anything:

```
bash ${CLAUDE_PLUGIN_ROOT}/skills/syntax-check/scripts/syntax_check.sh <file> [<file> ...]
```

- Works on `.cpp` and on headers (`.h`/`.hpp` are wrapped in a temporary translation unit that `#include`s them — so a header must be self-contained to pass, which is a G+Smo requirement anyway).
- **`compile_commands.json` in the build dir is required, asserted up front.** Exact per-file flags matter: a submodule file compiled with different defines/includes than the core library must not be silently checked with the wrong ones. If it's missing, the script fails immediately and tells you to run `/gismo:dev-config` (which enables `CMAKE_EXPORT_COMPILE_COMMANDS` and regenerates it for you — a cheap, non-destructive reconfigure, no rebuild triggered).
- Brand-new files not yet in `compile_commands.json` are matched by nearest-neighbour (any entry from a sibling file in the same directory). If even that fails — reconfigure: `cd <builddir> && cmake .`
- `--allow-degraded` bypasses the assertion and falls back to the core library's `flags.make` (library-wide flags) — emergency use only, may miss submodule-specific flags; do not reach for this as a default.
- Last line is `STATUS: OK` or `STATUS: FAIL`; compiler errors go to stderr.

Workflow rule for implementer agents: **syntax-check every touched file first, then build the target** with `/gismo:build-target`. Never skip straight to `make` — a full target build to find a typo wastes minutes.

Caveat: template `.hpp` bodies are only parsed, not instantiated — a passing check does not guarantee the templated code compiles for all instantiations; the target build remains the real test.
