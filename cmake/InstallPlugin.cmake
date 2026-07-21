######################################################################
## InstallPlugin.cmake
##
## Adds the gsAgents marketplace and installs the `gismo` plugin.
##
## Invoked in script mode:
##   cmake -DCLAUDE_EXECUTABLE=... -DSOURCE=... -DSCOPE=... -P InstallPlugin.cmake
##
## `marketplace add` is not idempotent -- re-running it once the marketplace is
## already configured exits non-zero. That must not fail the build, so its
## result is inspected rather than allowed to abort, and we fall through to
## `marketplace update` to refresh an existing entry.
######################################################################

if(NOT CLAUDE_EXECUTABLE OR NOT SOURCE OR NOT SCOPE)
    message(FATAL_ERROR "InstallPlugin.cmake requires CLAUDE_EXECUTABLE, SOURCE and SCOPE")
endif()

execute_process(
    COMMAND "${CLAUDE_EXECUTABLE}" plugin marketplace add "${SOURCE}"
    RESULT_VARIABLE _add_result
    OUTPUT_VARIABLE _add_output
    ERROR_VARIABLE  _add_output
)

if(_add_result EQUAL 0)
    message(STATUS "Marketplace added from ${SOURCE}")
else()
    # Most likely already present. Refresh it instead of failing.
    message(STATUS "Marketplace add returned ${_add_result} (likely already configured); updating")
    execute_process(
        COMMAND "${CLAUDE_EXECUTABLE}" plugin marketplace update gsagents
        RESULT_VARIABLE _upd_result
        OUTPUT_VARIABLE _upd_output
        ERROR_VARIABLE  _upd_output
    )
    if(NOT _upd_result EQUAL 0)
        message(FATAL_ERROR
            "Could not add or update the gsagents marketplace.\n"
            "add:    ${_add_output}\n"
            "update: ${_upd_output}")
    endif()
endif()

execute_process(
    COMMAND "${CLAUDE_EXECUTABLE}" plugin install gismo@gsagents --scope "${SCOPE}"
    RESULT_VARIABLE _inst_result
)

if(NOT _inst_result EQUAL 0)
    message(FATAL_ERROR "claude plugin install gismo@gsagents failed (${_inst_result})")
endif()

message(STATUS "Plugin 'gismo' installed (scope: ${SCOPE}). Restart Claude Code to load it.")
