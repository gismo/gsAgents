#!/usr/bin/env python3
"""
Multi-Provider Agent Compiler

Compiles universal agent and skill JSON configurations to provider-specific formats.
Supports: Claude Code, OpenCode, GitHub Copilot, Gemini CLI

Usage:
    python3 compiler/compile.py --all
    python3 compiler/compile.py --agent code-reviewer
    python3 compiler/compile.py --skill docx-creation
    python3 compiler/compile.py --provider claude
    python3 compiler/compile.py --validate
"""

import argparse
import json
import os
import sys
from pathlib import Path
from string import Template
import shutil

# Configuration
BASE_DIR = Path(__file__).parent.parent
AGENTS_DIR = BASE_DIR / "agents"
SKILLS_DIR = BASE_DIR / "skills"
COMMANDS_DIR = BASE_DIR / "commands"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = Path(__file__).parent / "templates"
SCHEMA_DIR = Path(__file__).parent / "schema"

# Provider output paths
PROVIDER_PATHS = {
    "claude": OUTPUT_DIR / ".claude",
    "opencode": OUTPUT_DIR / ".opencode",
    "copilot": OUTPUT_DIR / ".github",
}


def load_template(template_name, template_type="agents"):
    """Load a template file."""
    template_path = TEMPLATES_DIR / template_type / template_name
    if not template_path.exists():
        print(f"Error: Template not found: {template_path}")
        sys.exit(1)
    return Template(template_path.read_text())


def load_schema(schema_name):
    """Load a JSON schema."""
    schema_path = SCHEMA_DIR / schema_name
    if schema_path.exists():
        return json.loads(schema_path.read_text())
    return None


def validate_json(data, schema):
    """Basic JSON validation against schema."""
    if not schema:
        return True

    # Check required fields
    required = schema.get("required", [])
    for field in required:
        if field not in data:
            print(f"Validation error: Missing required field '{field}'")
            return False

    return True


def format_tools_claude(tools):
    """Format tools for Claude (PascalCase list)."""
    if not tools or tools is False:
        return ""
    if isinstance(tools, list):
        # Convert to PascalCase
        formatted = [t.capitalize() for t in tools]
        return f"tools: [{', '.join(formatted)}]\n"
    return ""


def format_tools_opencode(tools):
    """Format tools for OpenCode (yaml map)."""
    if not tools or tools is False:
        return ""
    if isinstance(tools, list):
        lines = ["tools:"]
        for tool in tools:
            lines.append(f"  {tool.lower()}: true")
        return "\n".join(lines) + "\n"
    return ""


def format_tools_copilot(tools):
    """Format tools for Copilot (quoted list)."""
    if not tools or tools is False:
        return ""
    if isinstance(tools, list):
        formatted = [f"'{t.lower()}'" for t in tools]
        return f"tools: [{', '.join(formatted)}]\n"
    return ""


def format_permissions_opencode(permissions):
    """Format permissions for OpenCode."""
    if not permissions:
        return ""
    lines = ["permissions:"]
    for key, value in permissions.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines) + "\n"


def format_handoffs_copilot(handoffs):
    """Format handoffs for Copilot."""
    if not handoffs:
        return ""
    lines = ["handoffs:"]
    for handoff in handoffs:
        lines.append(f"  - label: {handoff.get('label', '')}")
        lines.append(f"    agent: {handoff.get('agent', '')}")
        if "prompt" in handoff:
            lines.append(f"    prompt: {handoff['prompt']}")
        if "send" in handoff:
            lines.append(f"    send: {handoff['send']}")
    return "\n".join(lines) + "\n"


def format_mcp_servers_copilot(mcp_servers):
    """Format MCP servers for Copilot."""
    if not mcp_servers:
        return ""
    lines = ["mcpServers:"]
    for name, config in mcp_servers.items():
        lines.append(f"  {name}:")
        for key, value in config.items():
            if isinstance(value, dict):
                lines.append(f"    {key}:")
                for k, v in value.items():
                    lines.append(f"      {k}: {v}")
            elif isinstance(value, list):
                lines.append(f"    {key}:")
                for item in value:
                    lines.append(f"      - {item}")
            else:
                lines.append(f"    {key}: {value}")
    return "\n".join(lines) + "\n"


def _format_scalar(key, value):
    """Format scalar value without quotes for bools/numbers, quote strings when needed."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return f"{key}: {str(value).lower()}\n"
    if isinstance(value, (int, float)):
        return f"{key}: {value}\n"
    s = str(value)
    if "\n" in s:
        return f"{key}: |\n  " + "\n  ".join(s.splitlines()) + "\n"
    # quote if contains colon or leading/trailing spaces
    if ":" in s or s.strip() != s:
        return f'{key}: "{s}"\n'
    return f"{key}: {s}\n"


def compile_entity_for_provider(entity_data, provider, template_type="agents"):
    """Generic entity (agent/skill/command) compiler for a provider.

    Produces a markdown string by populating provider-specific template with
    a context built from entity_data. Re-uses existing formatters for tools,
    permissions, handoffs and mcpServers.
    """
    # Check if enabled for this provider
    providers = entity_data.get("providers", {})
    if not providers.get(provider, True):
        return None

    template_name = f"{provider}.md.j2"
    template = load_template(template_name, template_type=template_type)

    # Base context
    context = {
        "name": entity_data.get("name", ""),
        "description": entity_data.get("description", ""),
        "prompt": entity_data.get("prompt", ""),
    }

    # Common properties and their section keys
    # model, color, temperature, maxIterations, target
    context["model_section"] = _format_scalar("model", entity_data.get("model"))
    context["color_section"] = _format_scalar("color", entity_data.get("color"))
    context["temperature_section"] = _format_scalar(
        "temperature", entity_data.get("temperature")
    )
    # Note: templates expect max_iterations_section
    context["max_iterations_section"] = _format_scalar(
        "maxIterations", entity_data.get("maxIterations")
    )
    context["target_section"] = _format_scalar("target", entity_data.get("target"))

    # Tools (provider specific formatting)
    if provider == "claude":
        context["tools_section"] = format_tools_claude(entity_data.get("tools"))
    elif provider == "opencode":
        context["tools_section"] = format_tools_opencode(entity_data.get("tools"))
    elif provider == "copilot":
        context["tools_section"] = format_tools_copilot(entity_data.get("tools"))
    else:
        context["tools_section"] = ""

    # Permissions (opencode)
    context["permissions_section"] = (
        format_permissions_opencode(entity_data.get("permissions"))
        if provider == "opencode"
        else ""
    )

    # Handoffs and mcpServers (copilot)
    context["handoffs_section"] = (
        format_handoffs_copilot(entity_data.get("handoffs"))
        if provider == "copilot"
        else ""
    )
    context["mcp_servers_section"] = (
        format_mcp_servers_copilot(entity_data.get("mcpServers"))
        if provider == "copilot"
        else ""
    )

    return template.substitute(context)


def compile_agent_for_provider(agent_data, provider):
    return compile_entity_for_provider(agent_data, provider, template_type="agents")


def compile_skill_for_provider(skill_data, provider):
    return compile_entity_for_provider(skill_data, provider, template_type="skills")


def compile_command_for_provider(command_data, provider):
    return compile_entity_for_provider(command_data, provider, template_type="agents")


def write_agent_output(agent_name, content, provider):
    """Write compiled agent to output directory."""
    provider_dir = PROVIDER_PATHS[provider]
    agents_dir = provider_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # File extension
    output_file = agents_dir / f"{agent_name}.md"
    output_file.write_text(content)
    print(f"  Written: {output_file}")

    # Create manifest entry
    manifest_file = agents_dir / "manifest.txt"
    if not manifest_file.exists():
        manifest_file.write_text(f"{agent_name}\n")
    else:
        current_content = manifest_file.read_text().strip()
        if agent_name not in current_content:
            manifest_file.write_text(f"{current_content}\n{agent_name}\n")


def write_command_output(command_name, content, provider):
    """Write compiled command to output directory (treat like agents)."""
    provider_dir = PROVIDER_PATHS[provider]
    commands_dir = provider_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    output_file = commands_dir / f"{command_name}.md"
    output_file.write_text(content)
    print(f"  Written: {output_file}")

    # Create/update manifest in commands/ directory
    manifest_file = commands_dir / "manifest.txt"
    if not manifest_file.exists():
        manifest_file.write_text(f"{command_name}\n")
    else:
        current_content = manifest_file.read_text().strip()
        if command_name not in current_content:
            manifest_file.write_text(f"{current_content}\n{command_name}\n")


def write_skill_output(skill_name, content, provider):
    """Write compiled skill to output directory."""
    provider_dir = PROVIDER_PATHS[provider]
    # Place SKILL.md in output/.provider/<skill-name>/SKILL.md
    skill_dir = provider_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    output_file = skill_dir / "SKILL.md"
    output_file.write_text(content)
    print(f"  Written: {output_file}")

    # Copy other files and folders from skill source directory (e.g., examples.md, reference.md, scripts/)

    # (Actual copying of other files is handled by add_skill_files)

    # Add skill directory name to manifest
    # Write a simple manifest listing skills for this provider
    manifest_file = provider_dir / "manifest.txt"
    if not manifest_file.exists():
        manifest_file.write_text(f"{skill_name}\n")
    else:
        current_content = manifest_file.read_text().strip()
        if skill_name not in current_content:
            manifest_file.write_text(f"{current_content}\n{skill_name}\n")


def add_skill_files(skill_name, provider):
    """Copy non-compiled files from skills/<skill_name> to output/<provider>/skills/<skill_name>.

    Skill directories contain a .json (which is compiled into SKILL.md) and
    other artifacts (examples.md, reference.md, scripts/, ...) which should be
    copied verbatim for the provider output. JSON files are skipped.
    """
    if provider not in PROVIDER_PATHS:
        print(f"  Warning: Unknown provider '{provider}', skipping copying skill files")
        return

    src_dir = SKILLS_DIR / skill_name
    if not src_dir.exists():
        print(f"  Warning: Skill source directory not found: {src_dir}")
        return

    dest_dir = PROVIDER_PATHS[provider] / "skills" / skill_name
    dest_dir.mkdir(parents=True, exist_ok=True)

    for item in src_dir.iterdir():
        # Skip the JSON source file (it's compiled, not copied)
        if item.is_file() and item.suffix.lower() == ".json":
            continue

        dest_path = dest_dir / item.name
        try:
            if item.is_dir():
                # If destination exists, remove and replace to keep output deterministic
                if dest_path.exists():
                    shutil.rmtree(dest_path)
                shutil.copytree(item, dest_path)
                print(f"  Copied directory: {item} -> {dest_path}")
            else:
                shutil.copy2(item, dest_path)
                print(f"  Copied file: {item} -> {dest_path}")
        except Exception as e:
            print(f"  Warning: Failed to copy {item} -> {dest_path}: {e}")


def compile_agent(agent_file, providers=None):
    """Compile a single agent file."""
    print(f"\nCompiling agent: {agent_file.name}")

    # Load and validate
    agent_data = json.loads(agent_file.read_text())
    schema = load_schema("agent.schema.json")

    if not validate_json(agent_data, schema):
        print(f"  Error: Validation failed for {agent_file.name}")
        return False

    agent_name = agent_data.get("name")
    if not agent_name:
        print(f"  Error: Agent name not found in {agent_file.name}")
        return False

    # Compile for each provider
    providers_to_compile = providers or ["claude", "opencode", "copilot"]
    compiled_count = 0

    for provider in providers_to_compile:
        content = compile_agent_for_provider(agent_data, provider)
        if content:
            write_agent_output(agent_name, content, provider)
            compiled_count += 1

    print(f"  Compiled to {compiled_count} provider(s)")
    return True


def compile_skill(skill_file, providers=None):
    """Compile a single skill file."""
    print(f"\nCompiling skill: {skill_file.name}")

    # Load and validate
    skill_data = json.loads(skill_file.read_text())
    schema = load_schema("skill.schema.json")

    if not validate_json(skill_data, schema):
        print(f"  Error: Validation failed for {skill_file.name}")
        return False

    skill_name = skill_data.get("name")
    if not skill_name:
        print(f"  Error: Skill name not found in {skill_file.name}")
        return False

    # Compile for each provider
    providers_to_compile = providers or ["claude", "opencode"]
    compiled_count = 0

    for provider in providers_to_compile:
        content = compile_skill_for_provider(skill_data, provider)
        if content:
            write_skill_output(skill_name, content, provider)
            add_skill_files(skill_name, provider)  # Copy additional skill files
            compiled_count += 1

    print(f"  Compiled to {compiled_count} provider(s)")
    return True


def compile_all_agents(providers=None):
    """Compile all agents in the agents directory."""
    if not AGENTS_DIR.exists():
        print(f"Agents directory not found: {AGENTS_DIR}")
        return

    agent_files = list(AGENTS_DIR.glob("*.json"))

    # Compile agents
    print("\n=== Compiling All Agents ===")
    success_count = 0
    for agent_file in agent_files:
        if compile_agent(agent_file, providers):
            success_count += 1

    # Compile commands separately
    command_files = []
    if COMMANDS_DIR.exists():
        command_files = list(COMMANDS_DIR.glob("*.json"))

    total_commands = len(command_files)
    command_success = 0
    if total_commands > 0:
        print("\n=== Compiling All Commands ===")
        for cmd_file in command_files:
            print(f"\nCompiling command: {cmd_file.name}")
            try:
                cmd_data = json.loads(cmd_file.read_text())
            except json.JSONDecodeError as e:
                print(f"  Error: JSON decode error in {cmd_file.name}: {e}")
                continue
            # Validate with command schema
            schema = load_schema("command.schema.json")
            if not validate_json(cmd_data, schema):
                print(f"  Error: Validation failed for {cmd_file.name}")
                continue

            cmd_name = cmd_data.get("name")
            if not cmd_name:
                print(f"  Error: Command name not found in {cmd_file.name}")
                continue

            for provider in providers or ["claude", "opencode", "copilot"]:
                content = compile_command_for_provider(cmd_data, provider)
                if content:
                    write_command_output(cmd_name, content, provider)
                    command_success += 1

    total = len(agent_files) + total_commands
    print(f"\n✓ Compiled {success_count}/{len(agent_files)} agents")
    if total_commands > 0:
        print(f"✓ Compiled {command_success}/{total_commands} commands")
    print(f"\n✓ Compiled {success_count + command_success}/{total} agents+commands")


def compile_all_skills(providers=None):
    """Compile all skills in the skills directory."""
    if not SKILLS_DIR.exists():
        print(f"Skills directory not found: {SKILLS_DIR}")
        return

    print("\n=== Compiling All Skills ===")
    # New layout: each skill is a subdirectory under skills/<skill-name>/
    skill_dirs = [p for p in SKILLS_DIR.iterdir() if p.is_dir()]

    # Fallback: allow legacy JSON files directly in SKILLS_DIR
    legacy_jsons = list(SKILLS_DIR.glob("*.json"))

    total = len(skill_dirs) + len(legacy_jsons)
    if total == 0:
        print("No skills found.")
        return

    success_count = 0

    # Compile skills found as subdirectories
    for sd in skill_dirs:
        # Prefer <skilldir>/<skilldir>.json if present, otherwise first .json
        json_candidates = list(sd.glob("*.json"))
        if not json_candidates:
            print(f"  Skipping {sd.name}: no .json descriptor found")
            continue
        preferred = sd / f"{sd.name}.json"
        if preferred.exists():
            skill_file = preferred
        else:
            skill_file = json_candidates[0]

        if compile_skill(skill_file, providers):
            success_count += 1

    # Compile legacy json files located directly in SKILLS_DIR
    for skill_file in legacy_jsons:
        if compile_skill(skill_file, providers):
            success_count += 1

    print(f"\n✓ Compiled {success_count}/{total} skills")


def validate_all():
    """Validate all agents and skills without compiling."""
    print("\n=== Validating All Configurations ===")

    all_valid = True

    # Validate agents
    if AGENTS_DIR.exists():
        agent_schema = load_schema("agent.schema.json")
        for agent_file in AGENTS_DIR.glob("*.json"):
            try:
                agent_data = json.loads(agent_file.read_text())
                if validate_json(agent_data, agent_schema):
                    print(f"✓ {agent_file.name}")
                else:
                    print(f"✗ {agent_file.name}")
                    all_valid = False
            except json.JSONDecodeError as e:
                print(f"✗ {agent_file.name} - JSON error: {e}")
                all_valid = False

    # Validate skills
    if SKILLS_DIR.exists():
        skill_schema = load_schema("skill.schema.json")
        for skill_file in SKILLS_DIR.glob("*.json"):
            try:
                skill_data = json.loads(skill_file.read_text())
                if validate_json(skill_data, skill_schema):
                    print(f"✓ {skill_file.name}")
                else:
                    print(f"✗ {skill_file.name}")
                    all_valid = False
            except json.JSONDecodeError as e:
                print(f"✗ {skill_file.name} - JSON error: {e}")
                all_valid = False

    if all_valid:
        print("\n✓ All configurations are valid")
    else:
        print("\n✗ Some configurations have errors")

    return all_valid


def main():
    parser = argparse.ArgumentParser(
        description="Compile agents and skills to provider-specific formats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 compiler/compile.py --all
  python3 compiler/compile.py --agent code-reviewer
  python3 compiler/compile.py --skill docx-creation
  python3 compiler/compile.py --provider claude --all
  python3 compiler/compile.py --validate
        """,
    )

    parser.add_argument(
        "--all", action="store_true", help="Compile all agents and skills"
    )
    parser.add_argument(
        "--agent", metavar="NAME", help="Compile specific agent by name"
    )
    parser.add_argument(
        "--skill", metavar="NAME", help="Compile specific skill by name"
    )
    parser.add_argument(
        "--agents-only", action="store_true", help="Compile only agents"
    )
    parser.add_argument(
        "--skills-only", action="store_true", help="Compile only skills"
    )
    parser.add_argument(
        "--provider",
        metavar="PROV",
        action="append",
        choices=["claude", "opencode", "copilot", "gemini"],
        help="Compile for specific provider(s)",
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate without compiling"
    )

    args = parser.parse_args()

    # Validate mode
    if args.validate:
        validate_all()
        return

    # Require at least one action
    if not (
        args.all or args.agent or args.skill or args.agents_only or args.skills_only
    ):
        parser.print_help()
        sys.exit(1)

    providers = args.provider

    # Compile specific agent
    if args.agent:
        agent_file = AGENTS_DIR / f"{args.agent}.json"
        if not agent_file.exists():
            print(f"Error: Agent not found: {agent_file}")
            sys.exit(1)
        compile_agent(agent_file, providers)
        return

    # Compile specific skill
    if args.skill:
        skill_file = SKILLS_DIR / f"{args.skill}.json"
        if not skill_file.exists():
            print(f"Error: Skill not found: {skill_file}")
            sys.exit(1)
        compile_skill(skill_file, providers)
        return

    # Compile all
    if args.all or args.agents_only:
        compile_all_agents(providers)

    if args.all or args.skills_only:
        compile_all_skills(providers)

    print("\n=== Compilation Complete ===")


if __name__ == "__main__":
    main()
