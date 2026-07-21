---
name: run-tests
description: Build and run G+Smo unit tests, optionally filtered to a suite/test/file prefix. Use after any code change to verify correctness; prefer a filtered run for speed, full run for final verification.
argument-hint: "[suite-or-test-prefix]"
allowed-tools: Bash(bash:*)
---

Build the `unittests` target and run it:

```
bash ${CLAUDE_PLUGIN_ROOT}/skills/run-tests/scripts/run_unittests.sh [prefix ...]
```

- Selectors are **prefix-matched** against suite names, test names, and test source file names (see `unittests/main.cpp`). Suites are conventionally named after their file, e.g. suite `gsMatrixOp_test` lives in `unittests/gsMatrixOp_test.cpp`. So `run_unittests.sh gsKnotVector` runs all knot-vector tests.
- No selector = the full suite (use for final verification; it is slower).
- If the selector matches nothing the binary reports "Did not find any matching test" and exits non-zero — check your prefix against the `unittests/*_test.cpp` (or `optional/<module>/unittests/*_test.cpp`) file names.
- `--no-build` as the first argument skips the build step (only when you *just* built `unittests` yourself).
- Last line is `STATUS: OK|FAIL`.

Notes:
- Submodule tests (e.g. gsKLShell's) compile into the same `unittests` binary when the submodule is enabled, so the same filtering works for them.
- The build requires `GISMO_BUILD_UNITTESTS=ON` in the configured build dir; the script tells you if that's the likely failure.
