---
name: tree
description: Look up where things live in the G+Smo core library (src/ modules, examples, unittest suites) from a pre-generated map — or regenerate that map. Use instead of walking the source tree when locating files or capabilities.
argument-hint: "[--regen]"
allowed-tools: Read, Bash(python3:*)
---

The generated core-library map lives at:

```
.claude/gismo-maps/library-map.md
```

It lists every `src/<module>/` header with its doxygen `@brief`, plus all `examples/` drivers and `unittests/` suites. **Read it (or Grep it) instead of exploring `src/` by hand** — one file answers most "where is X / does gismo have Y" questions.

- **The map is per-checkout and is not shipped with the plugin — on a fresh checkout it does
  not exist yet.** If the file is absent, generate it before answering (do not fall back to
  walking `src/` by hand, and do not report it as an error).
- Invoked with `--regen` (or when the map is missing/stale, e.g. after a large merge): run
  `python3 ${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/tree/scripts/gen_tree.py`
  and report the STATUS line. The output is deterministic; regeneration is cheap (seconds).
- For optional submodules use the companion skill `gismo:module-map` (reference files in `.claude/gismo-maps/modules/`).
