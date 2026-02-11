######################################################################
## FetchAgents.cmake
## This file is part of the gsAgent compiler.
##
## Downloads agent instruction files from the remote gsAgents repository.
## Output goes to the build directory: <build>/.provider/<type>/
## This keeps the source tree clean.
##
## Supported providers: claude, gemini, opencode, cursor, copilot,
##                      windsurf, cline
######################################################################

# Include config written by CMakeLists.txt (if it exists from old runs)
# In script mode, all variables should be passed via -D flags
set(_config_file "${CMAKE_BINARY_DIR}/fetch_config.cmake")
if(EXISTS "${_config_file}")
    include("${_config_file}")
endif()

# Set up paths for script mode
# In script mode, CMAKE_SOURCE_DIR and CMAKE_BINARY_DIR are not set, so we use the passed values
if(DEFINED GISMO_CMAKE_SOURCE_DIR)
    set(CMAKE_SOURCE_DIR "${GISMO_CMAKE_SOURCE_DIR}")
endif()
if(DEFINED GISMO_CMAKE_BINARY_DIR)
    set(CMAKE_BINARY_DIR "${GISMO_CMAKE_BINARY_DIR}")
endif()

# Provider link registry maps: provider/type -> relative path under build/
# Agents are downloaded to build directory, not source tree
set(_AGENT_LINKS
    "claude/agents|.claude/agents"
    "claude/commands|.claude/commands"
    "claude/skills|.claude/skills"
    "claude/rules|.claude/rules"
    "gemini/agents|.gemini/agents"
    "gemini/commands|.gemini/commands"
    "gemini/skills|.gemini/skills"
    "gemini/rules|.gemini/rules"
    "opencode/agents|.opencode/agents"
    "opencode/commands|.opencode/commands"
    "opencode/skills|.opencode/skills"
    "opencode/rules|.opencode/rules"
    "copilot/agents|.github/agents"
    "copilot/commands|.github/commands"
    "copilot/skills|.github/skills"
    "cursor/agents|.cursor/agents"
    "cursor/commands|.cursor/commands"
    "cursor/skills|.cursor/skills"
)

function(_get_agent_dir_name PROVIDER_TYPE OUT_VAR)
    foreach(_entry ${_AGENT_LINKS})
        string(REPLACE "|" ";" _parts "${_entry}")
        list(GET _parts 0 _prov_type)
        list(GET _parts 1 _rel_path)
        if(_prov_type STREQUAL "${PROVIDER_TYPE}")
            set(${OUT_VAR} "${_rel_path}" PARENT_SCOPE)
            return()
        endif()
    endforeach()
    set(${OUT_VAR} "" PARENT_SCOPE)
endfunction()

function(fetch_gismo_agents)
    if(GISMO_AGENTS_FORCE_DOWNLOAD)
        message(STATUS "gsAgent Fetcher: Force-download enabled")
    else()
        message(STATUS "gsAgent Fetcher: Downloading agents (use -DGISMO_AGENTS_FORCE_DOWNLOAD=ON to re-download)")
    endif()

    # Set defaults if not specified via CMakeLists.txt
    if(NOT GISMO_AGENT_PROVIDERS)
        set(GISMO_AGENT_PROVIDERS claude;opencode)
    endif()
    if(NOT GISMO_AGENT_TYPES)
        set(GISMO_AGENT_TYPES agents;commands;skills;rules)
    endif()

    # Track if any files were downloaded
    set(_downloaded_count 0)

    # --- Get AGENTS.md ---
    if(GISMO_AGENTS_FORCE_DOWNLOAD OR NOT EXISTS "${CMAKE_BINARY_DIR}/AGENTS.md")
        set(_base "https://raw.githubusercontent.com/gismo/gsAgents/refs/heads/main/AGENTS.md")
        file(DOWNLOAD "${_base}" "${CMAKE_BINARY_DIR}/AGENTS.md" STATUS _st)
        list(GET _st 0 _code)
        if(NOT _code EQUAL 0)
            message(STATUS "  AGENTS.md download failed, skipping.")
        else()
            message(STATUS "  Downloaded AGENTS.md")
            math(EXPR _downloaded_count "${_downloaded_count} + 1")
        endif()
    endif()

    # --- Download agents, commands, skills, rules ---
    set(_had_any_files 0)

    foreach(_type ${GISMO_AGENT_TYPES})
        foreach(_prov ${GISMO_AGENT_PROVIDERS})
            _get_agent_dir_name("${_prov}/${_type}" _rel_path)
            if(NOT _rel_path)
                continue()
            endif()

            set(_base "https://raw.githubusercontent.com/gismo/gsAgents/refs/heads/output-${_prov}/${_rel_path}")
            set(_manifest_file "${CMAKE_BINARY_DIR}/${_prov}_${_type}_manifest.txt")
            file(DOWNLOAD "${_base}/manifest.txt" "${_manifest_file}" STATUS _st)
            list(GET _st 0 _code)
            if(NOT _code EQUAL 0)
                continue()
            endif()

            file(READ "${_manifest_file}" _raw)
            string(STRIP "${_raw}" _raw)
            separate_arguments(_items NATIVE_COMMAND "${_raw}")

            foreach(_item ${_items})
                if(_type STREQUAL "skills")
                    string(FIND "${_item}" "/" _has_slash)
                    if(_has_slash EQUAL -1)
                        set(_filename "${_item}/SKILL.md")
                    else()
                        set(_filename "${_item}")
                    endif()
                else()
                    set(_filename "${_item}.md")
                endif()

                set(_dest "${CMAKE_BINARY_DIR}/${_rel_path}/${_filename}")

                if(EXISTS "${_dest}" AND NOT GISMO_AGENTS_FORCE_DOWNLOAD)
                    continue()
                endif()

                get_filename_component(_destdir "${_dest}" DIRECTORY)
                if(_destdir AND NOT IS_DIRECTORY "${_destdir}")
                    file(MAKE_DIRECTORY "${_destdir}")
                endif()

                file(DOWNLOAD "${_base}/${_filename}" "${_dest}" STATUS _dl)
                list(GET _dl 0 _dlc)
                if(_dlc EQUAL 0)
                    message(STATUS "-> [${_prov}/${_item}]: Downloaded ${_filename}")
                    set(_had_any_files 1)
                    math(EXPR _downloaded_count "${_downloaded_count} + 1")
                else()
                    message(STATUS "-> [${_prov}/${_item}]: Failed to download ${_filename}")
                endif()
            endforeach()
        endforeach()
    endforeach()
    
    # Print summary
    if(_downloaded_count GREATER 0)
        message(STATUS "Fetch complete: ${_downloaded_count} files downloaded/processed")
    elseif(_had_any_files EQUAL 0 AND NOT GISMO_AGENTS_FORCE_DOWNLOAD)
        message(STATUS "All agents already up-to-date (no files downloaded)")
    else()
        message(STATUS "Fetch complete: no new files downloaded")
    endif()
endfunction()

# Only run fetch when in script mode (cmake -P)
if(DEFINED CMAKE_SCRIPT_MODE_FILE)
    fetch_gismo_agents()
endif()
