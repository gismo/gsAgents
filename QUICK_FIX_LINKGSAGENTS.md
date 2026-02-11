# Quick Fix: LinkgsAgents.cmake Errors

## What You're Seeing

```
CMake Warning (dev) at cmake/LinkAgents.cmake:34 (set):
  Cannot set "WORKTREE_MODE": current scope has no parent.
```

AND

```
CMake Error at cmake/LinkAgents.cmake:56 (message):
  AGENTS.md already exists locally. Cannot symlink.
```

## Quick Fix (2 steps)

### Step 1: Replace LinkgsAgents.cmake

Copy the fixed version from: `WORKTREE_AGENTS_LINKGSAGENTS_FIXED.md`

Replace the entire content of: `~/Code/gismo_worktrees/worktrees/agents/cmake/LinkgsAgents.cmake`

### Step 2: Reconfigure

```bash
cd ~/Code/gismo_worktrees/worktrees/agents/build
cmake .. -DgsAgents_DIR=/home/hverhelst/Code/gsAgent/build/install
```

## What Changes

| Behavior | Before | After |
|----------|--------|-------|
| CMake warning | ❌ Yes | ✅ No |
| AGENTS.md exists | ❌ Fatal error | ⚠️ Warning + skip |
| Local .claude/ exists | ⚠️ Warning + skip | ⚠️ Warning + skip |

## Expected Output

```
-- Validating gsAgents_DIR: /home/hverhelst/Code/gsAgent/build/install
-- ✓ Valid gsAgents installation found
-- 
-- Creating symlinks in /home/hverhelst/Code/gismo_worktrees/worktrees/agents:
--   ⊘ AGENTS.md exists locally (skipped, not overwritten)
--   ✓ .claude → /home/hverhelst/Code/gsAgent/build/install/.claude
--   ✓ .opencode → /home/hverhelst/Code/gsAgent/build/install/.opencode
-- 
-- Symlinks created successfully!
```

## Why This Happens

**PARENT_SCOPE issue:**
- `include()` doesn't create a new scope in CMake
- Can't use `set(...PARENT_SCOPE)` inside included files
- Fixed by not trying to set WORKTREE_MODE in the script

**AGENTS.md as error:**
- Original design: Treat as fatal error
- Your requirement: Just warn and skip
- Fixed by using `message(STATUS ...)` instead of `message(FATAL_ERROR ...)`

Done! ✅
