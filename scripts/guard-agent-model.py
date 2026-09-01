#!/usr/bin/env python3
"""PreToolUse guard: refuse Agent calls that override a gismo agent's tier,
and refuse a generic agent type dispatched with no tier at all.

An explicit `model` argument on the Agent tool takes precedence over the agent
file's frontmatter, so a dispatcher can silently promote the haiku scout to opus
and nothing in the agent definition would show it. This denies such calls at the
point of dispatch, with a reason the caller sees.

Generic types (`Explore`, `Plan`, `general-purpose`, `fork`, or no
`subagent_type` at all) declare no model of their own — they inherit the
caller's, so omitting `model` silently runs them on whatever tier the caller
is. This also denies that, per the dispatch rule in TASK_CONTRACT.md.

The plugin wires this itself in `hooks/hooks.json`, so it is active on install
with no configuration. Calls to agents outside this plugin, and calls whose
model is on the tier the agent already declares, are left to the normal
permission flow.
"""

import json
import re
import sys
from pathlib import Path

TIER = re.compile(r"haiku|sonnet|opus|fable")
GENERIC_TYPES = {"", "explore", "plan", "general-purpose", "fork"}


def declared_tiers(agents_dir):
    """Minimal frontmatter read — kept local so the hook stays a single file."""
    declared = {}
    for path in sorted(Path(agents_dir).glob("*.md")):
        name, model, in_frontmatter = path.stem, None, False
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


def deny(reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0  # malformed input is not this hook's problem

    tool_input = payload.get("tool_input") or {}
    override = tool_input.get("model")
    subagent = tool_input.get("subagent_type") or ""

    if not override and subagent.lower() in GENERIC_TYPES:
        deny(
            "Generic subagent types inherit the caller's model tier; pass "
            "model: haiku or sonnet (see TASK_CONTRACT.md §Dispatch rule)."
        )
        return 0

    if not override or not subagent:
        return 0

    # `gismo:scout` in a call, `scout.md` on disk.
    bare = subagent.split(":")[-1]
    declared = declared_tiers(Path(__file__).resolve().parent.parent / "agents")
    want = declared.get(bare)
    if not want:
        return 0

    # Frontmatter names a tier ("haiku"); a caller may pass either a tier or a
    # concrete id ("claude-haiku-4-5-20251001"). Same tier either way is not an
    # override. An unrecognised string is denied — a model this guard cannot
    # place against a tier is exactly the case worth stopping.
    found = TIER.search(override)
    if found and found.group(0) == want:
        return 0

    deny(
        f"{subagent} declares model: {want}; this call passes model={override}, "
        f"which overrides it. Drop the model argument to run {bare} on its own "
        f"tier, or dispatch a different agent if you need {override}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
