######################################################################
## CMakeLists.txt
## This file is part of gsAgents.
##
## Optional installation of the G+Smo agent plugin via the Claude Code CLI.
## There is no build or generation step: the repository *is* the plugin, and
## the CLI's own plugin mechanism performs the install.
######################################################################

cmake_minimum_required(VERSION 3.16)
project(gsAgents LANGUAGES NONE)

# =============================================================================
# Options
# =============================================================================

option(GISMO_INSTALL_AGENTS
       "Install the G+Smo agent plugin into the Claude Code CLI" OFF)

# user    -> available in every project for this user (default)
# project -> recorded in the project's .claude/settings.json (shared with the team)
# local   -> this checkout only, not shared
set(GISMO_AGENTS_SCOPE "user" CACHE STRING
    "Plugin installation scope: user, project, or local")
set_property(CACHE GISMO_AGENTS_SCOPE PROPERTY STRINGS "user" "project" "local")

# Where the marketplace is added from. Defaults to this checkout so a developer
# can install the working tree; point it at the GitHub repo for a released copy.
set(GISMO_AGENTS_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}" CACHE STRING
    "Marketplace source: a local path or a GitHub owner/repo")

# =============================================================================
# Install target
# =============================================================================

find_program(CLAUDE_EXECUTABLE claude)

if(GISMO_INSTALL_AGENTS)
    if(NOT CLAUDE_EXECUTABLE)
        message(FATAL_ERROR
            "GISMO_INSTALL_AGENTS=ON but the 'claude' CLI was not found on PATH. "
            "Install Claude Code, or set GISMO_INSTALL_AGENTS=OFF.")
    endif()

    # Validate before touching the user's configuration: a malformed manifest
    # should fail here rather than half-install.
    add_custom_target(validate-agents
        COMMAND ${CLAUDE_EXECUTABLE} plugin validate "${CMAKE_CURRENT_SOURCE_DIR}"
        COMMENT "Validating the gismo plugin manifest"
    )

    # Delegated to a script so a re-run over an already-configured marketplace
    # updates rather than fails. Safe to invoke repeatedly.
    add_custom_target(install-agents
        COMMAND ${CMAKE_COMMAND}
                -DCLAUDE_EXECUTABLE=${CLAUDE_EXECUTABLE}
                -DSOURCE=${GISMO_AGENTS_SOURCE}
                -DSCOPE=${GISMO_AGENTS_SCOPE}
                -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/InstallPlugin.cmake"
        COMMENT "Installing the gismo plugin (scope: ${GISMO_AGENTS_SCOPE})"
    )
    add_dependencies(install-agents validate-agents)

    add_custom_target(uninstall-agents
        COMMAND ${CLAUDE_EXECUTABLE} plugin uninstall gismo
        COMMENT "Uninstalling the gismo plugin"
    )
endif()

# =============================================================================
# Status
# =============================================================================

message(STATUS "")
message(STATUS "=== gsAgents ===")
if(GISMO_INSTALL_AGENTS)
    message(STATUS "  Plugin install: ENABLED (scope: ${GISMO_AGENTS_SCOPE})")
    message(STATUS "  Source:         ${GISMO_AGENTS_SOURCE}")
    message(STATUS "  Run: cmake --build . --target install-agents")
else()
    message(STATUS "  Plugin install: disabled (-DGISMO_INSTALL_AGENTS=ON to enable)")
endif()
message(STATUS "")
