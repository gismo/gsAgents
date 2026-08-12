#!/usr/bin/env python3
"""Audit which model each gismo subagent actually ran on.

Agent frontmatter declares an intended tier (`model: haiku`), but the tier that
actually billed is decided at dispatch time: an explicit `model` argument on the
Agent call overrides the frontmatter, and a name that fails to resolve falls back
to a generic agent inheriting the caller's model. Neither shows up in the agent
file. This reads the session transcripts, which record the resolved model on
every assistant message, and compares it against what the agent files declare.

    scripts/audit-agent-models.py                 # this project, all sessions
    scripts/audit-agent-models.py --session <id>  # one session
    scripts/audit-agent-models.py --quiet         # print only mismatches

Exit status is 1 when an agent ran on a tier it did not declare, so it can be
used as a hook or a CI gate.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# Frontmatter says `haiku`; the transcript says `claude-haiku-4-5-20251001`.
TIERS = ("haiku", "sonnet", "opus", "fable")


def tier_of(model_id):
    """Map a concrete model id onto its tier name, or None if unrecognised."""
    if not model_id:
        return None
    for tier in TIERS:
        if tier in model_id:
            return tier
    return None


def declared_tiers(agents_dir):
    """Read `model:` out of every agent file's frontmatter."""
    declared = {}
    for path in sorted(Path(agents_dir).glob("*.md")):
        name, model = path.stem, None
        in_frontmatter = False
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.rstrip() == "---":
                    if in_frontmatter:
                        break
                    in_frontmatter = True
                    continue
                if in_frontmatter:
                    match = re.match(r"^(name|model):\s*(\S+)", line)
                    if match and match.group(1) == "model":
                        model = match.group(2).strip("\"'")
                    elif match:
                        name = match.group(2).strip("\"'")
        declared[name] = model
    return declared


def project_dir(cwd):
    """Claude Code stores transcripts under a path-mangled project directory."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))


def agent_overrides(main_transcript):
    """Map toolUseId -> model explicitly passed on the Agent call, if any.

    A caller-supplied model beats the frontmatter, so this distinguishes "the
    dispatcher asked for the wrong tier" from "the harness ignored the file".
    """
    overrides = {}
    try:
        handle = open(main_transcript, encoding="utf-8")
    except OSError:
        return overrides
    with handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = entry.get("message", {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("name") == "Agent":
                    payload = block.get("input") or {}
                    overrides[block.get("id")] = (
                        payload.get("model"),
                        payload.get("subagent_type"),
                    )
    return overrides


def scan_session(session_dir, main_transcript):
    """Yield one record per subagent run in a session."""
    subagents = session_dir / "subagents"
    if not subagents.is_dir():
        return
    overrides = agent_overrides(main_transcript)
    for meta_path in sorted(subagents.glob("*.meta.json")):
        transcript = meta_path.with_name(meta_path.name.replace(".meta.json", ".jsonl"))
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        models = defaultdict(int)
        try:
            handle = open(transcript, encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("type") == "assistant":
                    models[entry.get("message", {}).get("model")] += 1
        if not models:
            continue
        override, requested_type = overrides.get(meta.get("toolUseId"), (None, None))
        yield {
            "agent": meta.get("agentType"),
            "requested": requested_type,
            "override": override,
            "depth": meta.get("spawnDepth"),
            "models": dict(models),
            "session": session_dir.name,
            "description": meta.get("description", ""),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=os.getcwd(), help="project whose sessions to audit")
    parser.add_argument("--agents", help="directory of agent .md files (default: alongside this script)")
    parser.add_argument("--session", help="audit only this session id")
    parser.add_argument("--quiet", action="store_true", help="print mismatches only")
    args = parser.parse_args()

    agents_dir = Path(args.agents) if args.agents else Path(__file__).resolve().parent.parent / "agents"
    declared = declared_tiers(agents_dir) if agents_dir.is_dir() else {}
    if not declared:
        print(f"no agent definitions found in {agents_dir}", file=sys.stderr)
        return 2

    root = project_dir(args.cwd)
    if not root.is_dir():
        print(f"no transcripts for {args.cwd} (looked in {root})", file=sys.stderr)
        return 2

    sessions = [d for d in sorted(root.iterdir()) if d.is_dir()]
    if args.session:
        sessions = [d for d in sessions if d.name == args.session]

    runs, mismatches = [], []
    for session_dir in sessions:
        for run in scan_session(session_dir, root / f"{session_dir.name}.jsonl"):
            runs.append(run)
            # An agent this repo does not define (Explore, general-purpose) has no
            # declared tier to violate — but it is worth seeing, since a failed
            # `gismo:*` lookup silently becomes one of these at the caller's tier.
            want = declared.get(run["agent"])
            if not want:
                continue
            got = {tier_of(m) for m in run["models"]}
            if got - {want}:
                mismatches.append(run)

    if not runs:
        print("no subagent runs recorded")
        return 0

    if not args.quiet:
        print(f"{len(runs)} subagent run(s) across {len(sessions)} session(s)\n")
        width = max(len(r["agent"] or "?") for r in runs)
        for run in runs:
            want = declared.get(run["agent"]) or "-"
            got = ", ".join(sorted({tier_of(m) or m for m in run["models"]}))
            flag = "  <-- MISMATCH" if run in mismatches else ""
            note = f"  [call passed model={run['override']}]" if run["override"] else ""
            print(f"  {(run['agent'] or '?'):<{width}}  declared={want:<7} ran={got}{note}{flag}")

    if mismatches:
        print(f"\n{len(mismatches)} agent run(s) did not use their declared tier:")
        for run in mismatches:
            got = ", ".join(sorted({tier_of(m) or m for m in run["models"]}))
            print(f"  {run['agent']}: declared {declared[run['agent']]}, ran {got}")
            if run["override"]:
                print(f"    the Agent call passed model={run['override']} explicitly")
            print(f"    session {run['session']}, depth {run['depth']}: {run['description']}")
        return 1

    if not args.quiet:
        print("\nall runs matched their declared tier")
    return 0


if __name__ == "__main__":
    sys.exit(main())
