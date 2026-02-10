# CMake Integration for gsAgents

This directory contains CMake integration files for the gsAgent compiler.

## Overview

The CMake integration allows seamless integration of agent instructions with CMake-based projects, particularly the G+Smo library.

## Files

- `CMakeLists.txt` - Main CMake integration file
- `cmake/FetchAgents.cmake` - Agent fetching functionality

## Usage

### Basic Usage

1. Add this directory to your CMake project:
   ```cmake
   add_subdirectory(path/to/gsAgents)
   ```

2. The agents will be automatically fetched during build:
   ```bash
   cmake -B build
   cmake --build build
   ```

### Custom Providers

You can specify which providers to fetch:

```bash
# Fetch only specific providers
cmake -DGISMO_AGENT_PROVIDERS=claude;opencode -B build
cmake --build build

# Fetch all supported providers
cmake -DGISMO_AGENT_PROVIDERS=claude;gemini;opencode;cursor;copilot;windsurf;cline -B build
cmake --build build
```

### Manual Fetching

You can manually fetch agents at any time:

```bash
# Fetch all configured providers
cmake --build . --target fetch-agents

# Fetch specific providers
cmake -DGISMO_AGENT_PROVIDERS=claude;opencode -B build
cmake --build build --target fetch-agents
```

## Provider Support

The integration supports the following AI assistant providers:

- `claude` - Claude Code
- `gemini` - Gemini CLI  
- `opencode` - OpenCode
- `cursor` - Cursor
- `copilot` - GitHub Copilot
- `windsurf` - Windsurf
- `cline` - Cline

## Integration Details

### Local Mode

If you have a local gsAgents clone with provider directories (claude, gemini, opencode, etc.), the integration will create symlinks from your project root to the agent instructions.

### Remote Mode

If no local gsAgents clone is found, the integration will download agent instructions from the GitHub repository:
- `agents-claude` - Claude Code agents
- `agents-gemini` - Gemini CLI agents  
- `agents-opencode` - OpenCode agents
- `agents-cursor` - Cursor agents
- `agents-copilot` - GitHub Copilot agents
- `agents-windsurf` - Windsurf agents
- `agents-cline` - Cline agents

### Symlink Creation

The integration creates symbolic links for:
- Main agent files (CLAUDE.md, GEMINI.md, etc.)
- Agent directories (.claude/agents, .opencode/agents, etc.)
- Command files (.claude/commands, etc.)
- Rule files (.claude/rules, etc.)

## Project Integration

### With G+Smo Library

This integration is designed to work seamlessly with the G+Smo library. When integrated, the agents will be available in the G+Smo build directory and can be used by the build system.

### With Other CMake Projects

You can integrate this with any CMake-based project by adding this directory as a subdirectory and configuring the `GISMO_AGENT_PROVIDERS` variable.

## Troubleshooting

### Missing Agent Directories

If agent directories are not found locally, the integration will fall back to downloading from GitHub. Ensure you have internet connectivity for remote fetching.

### Permission Issues

Symlink creation may require appropriate permissions. Run CMake with sufficient privileges if you encounter permission errors.

### Provider Configuration

If you experience issues with specific providers, try fetching them individually to isolate the problem.

## License

This CMake integration is part of the gsAgent compiler and follows the same licensing terms as the main project.