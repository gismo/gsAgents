######################################################################
## FetchAgents.cmake
## This file is part of the gsAgent compiler.
##
## Creates symlinks from the project root to agent instruction files
## in output/<provider>/agents/. Falls back to downloading from GitHub.
##
## Supported providers: claude, gemini, opencode, cursor, copilot,
##                      windsurf, cline
######################################################################

# Provider link registry: PROVIDER|ROOT_PATH|AGENTS_PATH
# ROOT_PATH  is relative to CMAKE_SOURCE_DIR (the project root).
# AGENTS_PATH is relative to output/.

set(_AGENT_LINKS
    "claude|CLAUDE.md|claude/agents/CLAUDE.md"
    "claude|.claude/commands|claude/commands"
    "claude|.claude/agents|claude/agents"
    "claude|.claude/rules|claude/rules"
    "gemini|GEMINI.md|gemini/agents/GEMINI.md"
    "opencode|.opencode/agents|opencode/agents"
    "cursor|.cursorrules|cursor/.cursorrules"
    "copilot|.github/copilot-instructions.md|copilot/copilot-instructions.md"
    "windsurf|.windsurfrules|windsurf/.windsurfrules"
    "cline|.clinerules|cline/.clinerules"
)

# Create or refresh a symlink, creating parent dirs as needed.
function(_agent_symlink LINK_PATH TARGET_PATH LABEL)
    get_filename_component(_dir "${LINK_PATH}" DIRECTORY)
    if(_dir AND NOT IS_DIRECTORY "${_dir}")
        file(MAKE_DIRECTORY "${_dir}")
    endif()
    if(IS_SYMLINK "${LINK_PATH}")
        file(REMOVE "${LINK_PATH}")
    endif()
    if(NOT EXISTS "${LINK_PATH}")
        file(CREATE_LINK "${TARGET_PATH}" "${LINK_PATH}" SYMBOLIC)
        message(STATUS "  -> ${LABEL}")
    else()
        message(STATUS "  -> ${LINK_PATH} exists (not a symlink), skipping")
    endif()
endfunction()

# Return the first ROOT_PATH for a provider (used by legacy/remote modes).
function(_agent_primary_file PROVIDER OUT_VAR)
    foreach(_entry ${_AGENT_LINKS})
        string(REPLACE "|" ";" _parts "${_entry}")
        list(GET _parts 0 _prov)
        list(GET _parts 1 _root)
        if(_prov STREQUAL "${PROVIDER}")
            set(${OUT_VAR} "${_root}" PARENT_SCOPE)
            return()
        endif()
    endforeach()
    set(${OUT_VAR} "" PARENT_SCOPE)
endfunction()

function(fetch_gismo_agents)
    set(_dir "${CMAKE_SOURCE_DIR}")

    if(EXISTS "${_dir}/output/claude/agents" OR EXISTS "${_dir}/output/gemini/agents"
       OR EXISTS "${_dir}/output/cursor/agents")
        # --- Local mode: native provider directories ---
        message(STATUS "gsAgent Fetcher: Using local gsAgent clone")

        foreach(_prov ${GISMO_AGENT_PROVIDERS})
            set(_found FALSE)
            foreach(_entry ${_AGENT_LINKS})
                string(REPLACE "|" ";" _parts "${_entry}")
                list(GET _parts 0 _p)
                list(GET _parts 1 _root)
                list(GET _parts 2 _target)
                if(NOT _p STREQUAL "${_prov}")
                    continue()
                endif()
                set(_found TRUE)
                set(_abs "${_dir}/output/${_target}")
                if(NOT EXISTS "${_abs}")
                    message(STATUS "  -> [${_prov}]: ${_target} not found, skipping")
                    continue()
                endif()
                _agent_symlink("${CMAKE_SOURCE_DIR}/${_root}" "${_abs}"
                    "[${_prov}]: Linked ${_root} -> output/${_target}")
            endforeach()
            if(NOT _found)
                message(WARNING "Unknown agent provider: ${_prov}")
            endif()
        endforeach()

    else()
        # --- Remote fallback: download from GitHub ---
        message(STATUS "gsAgent Fetcher: Downloading from GitHub")

        foreach(_prov ${GISMO_AGENT_PROVIDERS})
            set(_base "https://raw.githubusercontent.com/gismo/gsAgents2/refs/heads/agents-${_prov}")

            file(DOWNLOAD "${_base}/manifest.txt"
                 "${CMAKE_BINARY_DIR}/manifest_${_prov}.txt" STATUS _st)
            list(GET _st 0 _code)
            if(NOT _code EQUAL 0)
                message(STATUS "  No manifest for ${_prov}, skipping.")
                continue()
            endif()

            _agent_primary_file(${_prov} _filename)
            if(NOT _filename)
                continue()
            endif()

            file(READ "${CMAKE_BINARY_DIR}/manifest_${_prov}.txt" _raw)
            string(STRIP "${_raw}" _raw)
            separate_arguments(_agents NATIVE_COMMAND "${_raw}")

            foreach(_agent ${_agents})
                set(_dest "${CMAKE_SOURCE_DIR}/${_filename}")
                get_filename_component(_destdir "${_dest}" DIRECTORY)
                if(_destdir AND NOT IS_DIRECTORY "${_destdir}")
                    file(MAKE_DIRECTORY "${_destdir}")
                endif()

                file(DOWNLOAD "${_base}/${_agent}/${_filename}" "${_dest}" STATUS _dl)
                list(GET _dl 0 _dlc)
                if(_dlc EQUAL 0)
                    message(STATUS "  -> [${_prov}/${_agent}]: Downloaded ${_filename}")
                else()
                    # Legacy .filename fallback
                    file(DOWNLOAD "${_base}/${_agent}/.filename"
                         "${CMAKE_BINARY_DIR}/${_agent}_${_prov}.name" STATUS _fn)
                    list(GET _fn 0 _fnc)
                    if(_fnc EQUAL 0)
                        file(READ "${CMAKE_BINARY_DIR}/${_agent}_${_prov}.name" _real)
                        string(STRIP "${_real}" _real)
                        file(DOWNLOAD "${_base}/${_agent}/${_real}" "${_dest}")
                        message(STATUS "  -> [${_prov}/${_agent}]: Downloaded via .filename")
                    endif()
                endif()
            endforeach()
        endforeach()
    endif()
endfunction()
