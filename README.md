[![Sync Agent Providers](https://github.com/gismo/gsAgents2/actions/workflows/deploy.yml/badge.svg)](https://github.com/gismo/gsAgents2/actions/workflows/deploy.yml)

# gsAgents - Multi-Provider Agent Compiler

A unified agent and skill compilation system that transforms universal JSON configurations into provider-specific formats for Claude Code, OpenCode, GitHub Copilot, and Gemini CLI.

## Repository Structure

```
gsAgent/
├── agents/                 # Universal agent JSON configurations
├── skills/                 # Universal skill JSON configurations
├── compiler/               # Compilation engine and templates
│   ├── compile.py          # Main compilation script
│   ├── templates/          # Provider-specific templates
│   └── schema/            # JSON schemas
├── output/                 # Compiled provider-specific outputs
├── .github/workflows/      # GitHub Actions for deployment
└── AGENTS.md              # Universal instructions
```

## Quick Start

1. **Initialize deployment structure:**
   ```bash
   ./init-deploy.sh
   ```

2. **Add your agent configurations:**
   - Place agent JSON files in `agents/` directory
   - Place skill JSON files in `skills/` directory

3. **Compile and validate:**
   ```bash
   python3 compiler/compile.py --validate
   python3 compiler/compile.py --all
   ```

4. **Deploy:**
   - Commit and push to trigger GitHub Actions
   - Agents will be compiled and deployed to separate branches

## Compilation Process

The compiler transforms universal JSON configurations into provider-specific formats:

### Unified JSON Format
```json
{
  "name": "security-auditor",
  "description": "Security-focused code auditor",
  "tools": ["read", "grep", "glob", "bash"],
  "permissions": {
    "edit": "deny",
    "bash": "ask"
  },
  "model": "sonnet",
  "color": "red",
  "temperature": 0.5,
  "providers": {
    "claude": true,
    "opencode": true,
    "copilot": true,
    "gemini": false
  }
}
```

### Provider-Specific Output

#### Claude Code (`.claude/agents/`)
```yaml
---
name: security-auditor
description: Security-focused code auditor
tools: [Read, Grep, Glob, Bash]
color: red
---

[Prompt content]
```

#### OpenCode (`.opencode/agents/`)
```yaml
---
description: Security-focused code auditor
tools:
  read: true
  grep: true
  glob: true
  bash: true
model: sonnet
temperature: 0.5
---

[Prompt content]
```

#### GitHub Copilot (`.github/agents/`)
```yaml
---
name: security-auditor
description: Security-focused code auditor
tools: ['read', 'grep', 'glob', 'bash']
---

[Prompt content]
```

## GitHub Actions Workflow

The repository includes a CI/CD pipeline that:

1. **Triggers on push to main branch**
2. **Compiles agents for each provider** (claude, copilot, opencode)
3. **Deploys to separate branches:**
   - `agents-claude` - Claude Code agents
   - `agents-copilot` - GitHub Copilot agents  
   - `agents-opencode` - OpenCode agents
4. **Creates release artifacts** for each provider

## Supported Providers

- **Claude Code** - `.claude/` directory
- **OpenCode** - `.opencode/` directory  
- **GitHub Copilot** - `.github/` directory
- **Gemini CLI** - `.gemini/` directory (skills only)

## Commands

```bash
# Validate all configurations
python3 compiler/compile.py --validate

# Compile all agents and skills
python3 compiler/compile.py --all

# Compile specific agent
python3 compiler/compile.py --agent security-auditor

# Compile for specific provider
python3 compiler/compile.py --provider claude --all

# Compile only agents
python3 compiler/compile.py --agents-only

# Compile only skills
python3 compiler/compile.py --skills-only
```

## File Naming Conventions

- **Agents:** `agents/{agent-name}.json`
- **Skills:** `skills/{skill-name}.json`
- **Compiled agents:** `output/.{provider}/agents/{agent-name}.{ext}`
- **Compiled skills:** `output/.{provider}/skills/{skill-name}/SKILL.md`

## Provider-Specific Notes

- **Claude:** Uses PascalCase for tools, supports color and model
- **OpenCode:** Uses YAML format with boolean values for tools
- **Copilot:** Uses quoted strings for tools, supports handoffs and MCP servers
- **Gemini:** Skills only, no agent support

## Deployment Branches

Each provider gets its own deployment branch:
- `agents-claude` - Claude Code agents
- `agents-copilot` - GitHub Copilot agents
- `agents-opencode` - OpenCode agents

## Requirements

- Python 3.7+
- pip packages: jinja2, schema
- GitHub repository with Actions enabled

## License

This repository follows the standard open-source licensing model for AI agent configurations.
