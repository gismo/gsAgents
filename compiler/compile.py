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

# Configuration
BASE_DIR = Path(__file__).parent.parent
AGENTS_DIR = BASE_DIR / "agents"
SKILLS_DIR = BASE_DIR / "skills"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = Path(__file__).parent / "templates"
SCHEMA_DIR = Path(__file__).parent / "schema"

# Provider output paths
PROVIDER_PATHS = {
    "claude": OUTPUT_DIR / ".claude",
    "opencode": OUTPUT_DIR / ".opencode",
    "copilot": OUTPUT_DIR / ".github",
    "gemini": OUTPUT_DIR / ".gemini",
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


def compile_agent_for_provider(agent_data, provider):
    """Compile agent data for a specific provider."""
    # Check if enabled for this provider
    providers = agent_data.get("providers", {})
    if not providers.get(provider, True):
        return None

    # Load template
    template_name = f"{provider}.md.j2"
    template = load_template(template_name, template_type="agents")

    # Prepare context based on provider
    context = {
        "name": agent_data.get("name", ""),
        "description": agent_data.get("description", ""),
        "prompt": agent_data.get("prompt", ""),
    }

    if provider == "claude":
        context["tools_section"] = format_tools_claude(agent_data.get("tools"))
        context["model_section"] = (
            f"model: {agent_data['model']}\n" if agent_data.get("model") else ""
        )
        context["color_section"] = (
            f"color: {agent_data['color']}\n" if agent_data.get("color") else ""
        )

    elif provider == "opencode":
        context["tools_section"] = format_tools_opencode(agent_data.get("tools"))
        context["model_section"] = (
            f"model: {agent_data['model']}\n" if agent_data.get("model") else ""
        )
        context["temperature_section"] = (
            f"temperature: {agent_data['temperature']}\n"
            if agent_data.get("temperature") is not None
            else ""
        )
        context["max_iterations_section"] = (
            f"maxIterations: {agent_data['maxIterations']}\n"
            if agent_data.get("maxIterations")
            else ""
        )
        context["permissions_section"] = format_permissions_opencode(
            agent_data.get("permissions")
        )

    elif provider == "copilot":
        context["tools_section"] = format_tools_copilot(agent_data.get("tools"))
        context["model_section"] = (
            f"model: {agent_data['model']}\n" if agent_data.get("model") else ""
        )
        context["handoffs_section"] = format_handoffs_copilot(
            agent_data.get("handoffs")
        )
        context["mcp_servers_section"] = format_mcp_servers_copilot(
            agent_data.get("mcpServers")
        )
        context["target_section"] = (
            f"target: {agent_data['target']}\n" if agent_data.get("target") else ""
        )

    elif provider == "gemini":
        # Gemini doesn't support agents in the same way
        return None

    return template.substitute(context)


def compile_skill_for_provider(skill_data, provider):
    """Compile skill data for a specific provider."""
    # Check if enabled for this provider
    providers = skill_data.get("providers", {})
    if not providers.get(provider, True):
        return None

    # Load template
    template = load_template("skill.md.j2", template_type="skills")

    # Prepare context
    context = {
        "name": skill_data.get("name", ""),
        "description": skill_data.get("description", ""),
        "instructions": skill_data.get("instructions", ""),
        "version": skill_data.get("version", "1.0.0"),
        "tags": ", ".join(skill_data.get("tags", [])),
    }

    return template.substitute(context)


def write_agent_output(agent_name, content, provider):
    """Write compiled agent to output directory."""
    provider_dir = PROVIDER_PATHS[provider]
    agents_dir = provider_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Determine file extension
    if provider == "copilot":
        output_file = agents_dir / f"{agent_name}.agent.md"
    else:
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


def write_skill_output(skill_name, content, provider):
    """Write compiled skill to output directory."""
    provider_dir = PROVIDER_PATHS[provider]
    skills_dir = provider_dir / "skills" / skill_name
    skills_dir.mkdir(parents=True, exist_ok=True)

    output_file = skills_dir / "SKILL.md"
    output_file.write_text(content)
    print(f"  Written: {output_file}")


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
        if provider == "gemini":
            continue  # Skip gemini for agents

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
    providers_to_compile = providers or ["claude", "opencode", "gemini"]
    compiled_count = 0

    for provider in providers_to_compile:
        if provider == "copilot":
            continue  # Skip copilot for skills

        content = compile_skill_for_provider(skill_data, provider)
        if content:
            write_skill_output(skill_name, content, provider)
            compiled_count += 1

    print(f"  Compiled to {compiled_count} provider(s)")
    return True


def compile_all_agents(providers=None):
    """Compile all agents in the agents directory."""
    if not AGENTS_DIR.exists():
        print(f"Agents directory not found: {AGENTS_DIR}")
        return

    print("\n=== Compiling All Agents ===")
    agent_files = list(AGENTS_DIR.glob("*.json"))

    if not agent_files:
        print("No agent files found.")
        return

    success_count = 0
    for agent_file in agent_files:
        if compile_agent(agent_file, providers):
            success_count += 1

    print(f"\n✓ Compiled {success_count}/{len(agent_files)} agents")


def compile_all_skills(providers=None):
    """Compile all skills in the skills directory."""
    if not SKILLS_DIR.exists():
        print(f"Skills directory not found: {SKILLS_DIR}")
        return

    print("\n=== Compiling All Skills ===")
    skill_files = list(SKILLS_DIR.glob("*.json"))

    if not skill_files:
        print("No skill files found.")
        return

    success_count = 0
    for skill_file in skill_files:
        if compile_skill(skill_file, providers):
            success_count += 1

    print(f"\n✓ Compiled {success_count}/{len(skill_files)} skills")


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
