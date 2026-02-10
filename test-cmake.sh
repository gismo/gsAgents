# Test CMake Integration

# Create a build directory
mkdir -p build

# Configure with CMake
cmake -S . -B build

# Build and fetch agents
cmake --build build --target fetch-agents

# Check if agents were fetched
ls -la build/output/
ls -la build/output/.claude/agents/manifest.txt
ls -la build/output/.opencode/agents/manifest.txt
ls -la build/output/.github/agents/manifest.txt

# Check if symlinks were created
ls -la CLAUDE.md
ls -la .opencode/agents/manifest.txt

# Clean up
#rm -rf build
