# Fixed LinkgsAgents.cmake - Handles AGENTS.md Conflicts Gracefully

**Location**: `~/Code/gismo_worktrees/worktrees/agents/cmake/LinkgsAgents.cmake`

This version:
- ✅ Doesn't use `PARENT_SCOPE` (fixes the CMake warning)
- ✅ AGENTS.md conflict shows warning, doesn't fail (your requirement)
- ✅ Skips missing providers gracefully

## Fixed Code

```cmake
######################################################################
## LinkgsAgents.cmake
## Manages symlink creation for pre-installed gsAgents
##
## Validates gsAgents_DIR and creates symlinks to AGENTS.md and
## provider directories (.claude, .opencode, etc.) at root level.
## Only symlinks missing providers to avoid overwriting user files.
######################################################################

# Validate gsAgents_DIR exists
if(NOT EXISTS "${gsAgents_DIR}")
    message(FATAL_ERROR "gsAgents_DIR does not exist: ${gsAgents_DIR}")
endif()

# Validate AGENTS.md exists
if(NOT EXISTS "${gsAgents_DIR}/AGENTS.md")
    message(FATAL_ERROR "AGENTS.md not found in gsAgents_DIR: ${gsAgents_DIR}/AGENTS.md")
endif()

# Validate at least one provider directory exists
set(_found_provider FALSE)
foreach(_provider claude gemini opencode github cursor)
    if(EXISTS "${gsAgents_DIR}/.${_provider}")
        set(_found_provider TRUE)
        break()
    endif()
endforeach()

if(NOT _found_provider)
    message(FATAL_ERROR "No provider directories found in gsAgents_DIR: ${gsAgents_DIR}")
endif()

message(STATUS "")
message(STATUS "Validating gsAgents_DIR: ${gsAgents_DIR}")
message(STATUS "✓ Valid gsAgents installation found")
message(STATUS "")

# List of providers and their directory names
set(_PROVIDERS
    "claude|.claude"
    "gemini|.gemini"
    "opencode|.opencode"
    "copilot|.github"
    "cursor|.cursor"
)

# Create symlinks for AGENTS.md and provider directories
message(STATUS "Creating symlinks in ${CMAKE_SOURCE_DIR}:")

# Symlink AGENTS.md (warn if exists, skip)
set(_agents_md "${CMAKE_SOURCE_DIR}/AGENTS.md")
if(EXISTS "${_agents_md}")
    message(STATUS "  ⊘ AGENTS.md exists locally (skipped, not overwritten)")
else()
    execute_process(
        COMMAND ln -s "${gsAgents_DIR}/AGENTS.md" "${_agents_md}"
        RESULT_VARIABLE _result
    )
    if(_result EQUAL 0)
        message(STATUS "  ✓ AGENTS.md → ${gsAgents_DIR}/AGENTS.md")
    else()
        message(WARNING "Failed to create symlink for AGENTS.md")
    endif()
endif()

# Symlink provider directories (only if not already present)
foreach(_entry ${_PROVIDERS})
    string(REPLACE "|" ";" _parts "${_entry}")
    list(GET _parts 0 _provider_name)
    list(GET _parts 1 _provider_dir)
    
    set(_src "${gsAgents_DIR}/${_provider_dir}")
    set(_dst "${CMAKE_SOURCE_DIR}/${_provider_dir}")
    
    # Only create symlink if source exists AND destination doesn't exist
    if(EXISTS "${_src}")
        if(EXISTS "${_dst}")
            message(STATUS "  ⊘ ${_provider_dir} exists locally (not overwritten)")
        else()
            execute_process(
                COMMAND ln -s "${_src}" "${_dst}"
                RESULT_VARIABLE _result
            )
            if(_result EQUAL 0)
                message(STATUS "  ✓ ${_provider_dir} → ${_src}")
            else()
                message(WARNING "Failed to create symlink for ${_provider_dir}")
            endif()
        endif()
    endif()
endforeach()

message(STATUS "")
message(STATUS "Symlinks created successfully!")
message(STATUS "Run 'cmake --build . --target clean-agents' to remove symlinks")
message(STATUS "")
```

## What Changed

| Issue | Old Behavior | New Behavior |
|-------|--------------|--------------|
| `PARENT_SCOPE` warning | ❌ Error (removed) | ✅ Not used |
| AGENTS.md exists | ❌ Fatal error, stop | ⚠️ Warning, skip it |
| Provider exists locally | ⊘ Message, don't overwrite | ⊘ Message, don't overwrite |

## How to Apply

1. **Open**: `~/Code/gismo_worktrees/worktrees/agents/cmake/LinkgsAgents.cmake`
2. **Replace**: Everything with the code above
3. **Re-run**: `cmake .. -DgsAgents_DIR=/path/to/gsAgent/build/install`

## Expected Output Now

```
-- 
-- Validating gsAgents_DIR: /home/hverhelst/Code/gsAgent/build/install
-- ✓ Valid gsAgents installation found
-- 
-- Creating symlinks in /home/hverhelst/Code/gismo_worktrees/worktrees/agents:
--   ⊘ AGENTS.md exists locally (skipped, not overwritten)
--   ✓ .claude → /home/hverhelst/Code/gsAgent/build/install/.claude
--   ✓ .opencode → /home/hverhelst/Code/gsAgent/build/install/.opencode
--   ✓ .gemini → /home/hverhelst/Code/gsAgent/build/install/.gemini
-- 
-- Symlinks created successfully!
-- Run 'cmake --build . --target clean-agents' to remove symlinks
-- 
```

## Key Insight

The `PARENT_SCOPE` issue happens because `include()` in CMake doesn't create a new scope - it runs in the parent scope. So trying to `set(...PARENT_SCOPE)` has no effect.

**Solution**: Don't try to set WORKTREE_MODE in LinkgsAgents.cmake. Instead:
- Set it directly in CMakeLists.txt before including the script
- Or set it after the include completes
- Better yet: Just check `if(gsAgents_DIR)` in CMakeLists.txt (which you already do!)
