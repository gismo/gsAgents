######################################################################
## CMakeLists.txt
## This file is part of the gsAgent compiler.
##
## Integrates agent fetching with CMake build system.
######################################################################

cmake_minimum_required(VERSION 3.16)
project(gsAgents LANGUAGES NONE)

# Default agent providers to fetch
if(NOT GISMO_AGENT_PROVIDERS)
    set(GISMO_AGENT_PROVIDERS claude gemini opencode)
endif()

# Default types to fetch (agents, commands, skills, rules)
if(NOT GISMO_AGENT_TYPES)
    set(GISMO_AGENT_TYPES agents commands skills rules)
endif()

# Include the agent fetching functionality
include(cmake/FetchAgents.cmake)

# Add custom target to fetch agents
add_custom_target(fetch-agents
    COMMAND ${CMAKE_COMMAND} -DGISMO_AGENT_PROVIDERS="${GISMO_AGENT_PROVIDERS}" -DGISMO_AGENT_TYPES="${GISMO_AGENT_TYPES}" -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/FetchAgents.cmake
    COMMENT "Fetching agent instructions for providers: ${GISMO_AGENT_PROVIDERS} types: ${GISMO_AGENT_TYPES}"
    VERBATIM
)

# Create a default target if none exists
if(NOT TARGET default)
    add_custom_target(default)
    add_dependencies(default fetch-agents)
endif()

message(STATUS "gsAgents CMake integration ready")
message(STATUS "Available providers: claude, gemini, opencode, cursor, copilot, windsurf, cline")
message(STATUS "Current providers: ${GISMO_AGENT_PROVIDERS}")
message(STATUS "")
message(STATUS "To fetch agents manually:")
message(STATUS "  cmake --build . --target fetch-agents")
message(STATUS "")
message(STATUS "To customize providers:")
message(STATUS "  cmake -DGISMO_AGENT_PROVIDERS=claude;opencode")
