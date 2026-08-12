---
name: dev-config
description: Set or switch the G+Smo build directory (e.g. debug vs release), the parallel-jobs cap used by all agent build scripts, and which advisor the implementers use. Writes .claude/gismo-dev.local.json. Run when there are multiple build dirs, after creating a new one, to change the -j limit, or after enabling/disabling Claude Code's advisorModel.
argument-hint: "[build_dir] [jobs] [agent|native]"
allowed-tools: Bash(bash:*), Bash(find:*), Bash(grep:*), Bash(nproc)
---

You configure the per-developer local settings that every G+Smo agent script reads.

The config file is `.claude/gismo-dev.local.json` at the repo root (gitignored):
```json
{ "build_dir": "/abs/path/to/build", "jobs": 4, "advisor": "agent" }
```

## Steps

1. If both arguments were given (`/gismo:dev-config build_debug 4`), skip to step 4.

2. **List candidate build dirs.** Run from the repo root:
   ```
   for d in build*/; do [ -f "$d/CMakeCache.txt" ] && echo "$d: $(grep -m1 '^CMAKE_BUILD_TYPE:' $d/CMakeCache.txt | cut -d= -f2)"; done
   ```
   Show the user each dir with its build type (Release/Debug/RelWithDebInfo). If none exist, tell the user to configure a build directory first (`cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_EXPORT_COMPILE_COMMANDS=ON .`) and stop.

3. **Ask the user** which build dir to use, and how many parallel jobs. For jobs, offer 1 / 2 / 4 (default) and note the hard cap: scripts clamp to `nproc/2` because unbounded `-j` has crashed machines by exhausting RAM.

   Do **not** ask who advises the implementers. `gismo_env.sh` detects that itself by reading `advisorModel` out of the project and user settings files (and honouring `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1`), so it stays correct across `/advisor` and `/advisor off` with no config edit. A hand-set value was the bug: whenever it said `agent` while an advisor was in fact configured, every implementer got both advisors — the exact doubling the switch exists to prevent.

   One case is undetectable: `claude --advisor <model>` is a per-session flag that touches no file. Ask about it only if the user mentions launching that way, and pass `native` to pin it.

4. **Write the config** with the deterministic script (never write the JSON by hand):
   ```
   bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/set_config.sh <build_dir> <jobs> [agent|native]
   ```

5. `set_config.sh` asserts `compile_commands.json` exists in the chosen build dir and, if missing, enables it automatically (`cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON .` — a cache-var flip, no rebuild triggered) before writing the config. This is required: `/gismo:syntax-check` refuses to run without it (exact per-file flags matter — a submodule file must never be checked with the core library's generic flags). Confirm to the user what was set, including the build type of the selected dir.
