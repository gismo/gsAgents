[![Validate plugin](https://github.com/gismo/gsAgents/actions/workflows/validate-plugin.yml/badge.svg)](https://github.com/gismo/gsAgents/actions/workflows/validate-plugin.yml)

# gsAgents — G+Smo developer agent plugin

A Claude Code plugin providing a cost-tiered, closed-loop agent framework for
developing the [G+Smo](https://github.com/gismo/gismo) isogeometric analysis
library: specialist agents for implementation, testing, examples, docs and
review, plus guarded build / test / syntax-check skills.

Build safety is built in: every compilation goes through a guarded wrapper that
refuses bare `make` (which would build all ~61 examples) and caps `-j` (unbounded
parallelism has exhausted RAM and crashed machines).

## What's in the plugin

**Agents** (dispatched via the Agent tool as `gismo:<name>`):

| Agent | Tier | Role |
|---|---|---|
| `gismo:implementer` | sonnet | Library code in `src/`, `optional/*/src` |
| `gismo:test-writer` | sonnet | UnitTest++ suites |
| `gismo:example-writer` | sonnet | Runnable drivers in `examples/` |
| `gismo:task-reviewer` | opus | Adversarial per-task PASS/FAIL gate (attacks the change; no routine test re-runs) |
| `gismo:task-lead` | sonnet | Per-task loop-driver: implement → review → repair cycles |
| `gismo:spec-writer` | opus | Expands one decomposition line into a grounded task spec |
| `gismo:doc-writer` | sonnet | Doxygen / tutorials / README |
| `gismo:builder` | sonnet | Guarded `make` wrapper |
| `gismo:unittest-runner` | sonnet | Build + run + analyse tests |
| `gismo:debugger` | sonnet | GDB / Valgrind |
| `gismo:indexer` | sonnet | Codebase exploration (reads generated maps) |
| `gismo:scout` | haiku | One-shot factual lookups (`file:line`, signatures) |
| `gismo:advisor` | opus | Mid-task consultant for the sonnet implementers |

The per-task closed loop runs as **nested subagents** (requires Claude Code
>= 2.1.172): `/gismo:implement` dispatches one `gismo:task-lead` per task,
which spawns the task's implementer and then `gismo:task-reviewer`, re-dispatching
the implementer with the review file on `VERDICT: FAIL` — up to 2 repair rounds —
before returning a single `CYCLE: PASS/FAIL/BLOCKED` verdict. The round-by-round
reports and reviews stay out of the main session's context; the files under
`.claude/plans/<slug>/tasks/` remain the audit trail.

Cost control rests on an asymmetry: **writing is cheap, checking is expensive.**
A well-grounded spec (opus `gismo:spec-writer`) lets the three implementers run
on sonnet, while the adversarial gate that has to catch what they missed stays
on opus (`gismo:task-reviewer`). The loop-driver is sonnet — it only dispatches
and reads verdicts.

Every working agent may delegate lookups downward instead of reading the library
itself: `gismo:scout` (haiku) answers one settled fact per call with a
`file:line` citation, and `gismo:indexer` (sonnet) handles questions that need
real exploration. Spawn rules: the orchestrator spawns spec-writers and
task-leads; a task-lead spawns its task's agent and the reviewer; spec-writer,
the implementers, the reviewer, doc-writer and debugger may spawn scout and
indexer; the three implementers may additionally spawn `gismo:advisor` (opus,
capped at 2 per task); scout, indexer and advisor spawn nothing.

### Verifying the tiers actually held

The `model:` line in an agent file states an intention, not an outcome: an
explicit `model` argument on the `Agent` call overrides the frontmatter, and a
`subagent_type` that fails to resolve falls back to a generic agent running at
the caller's tier. Neither is visible in the agent definition, so the tiering —
and the cost model that rests on it — has to be checked against the transcripts,
which record the resolved model on every message.

```
scripts/audit-agent-models.py            # every session for this project
scripts/audit-agent-models.py --quiet    # mismatches only; exit 1 if any
```

Each run is reported as `declared=<tier> ran=<tier>`, and a mismatch names the
cause — whether the dispatching call passed a `model` argument or the harness
resolved something else.

The first case is caught before it costs anything: the plugin ships a
`PreToolUse` hook (`hooks/hooks.json` → `scripts/guard-agent-model.py`) that
denies any `Agent` call passing a `model` that contradicts the target agent's
frontmatter, with a reason the caller sees. It needs no configuration and does
nothing to calls that pass no model, or that target an agent outside this
plugin. The prose rule it enforces is in `TASK_CONTRACT.md`; the hook exists
because that rule has been broken in practice — an orchestrator once appended
"use opus for the implementer and reviewer sub-dispatches" to a task-lead
prompt, silently reverting the sonnet/opus split for a whole run.

The ceremony also scales with risk: each task spec carries a `Review:` level,
fixed by the orchestrator at decomposition time. `full` tasks get the
in-cycle adversarial review; `light`/`none` tasks defer their review into
ONE end-of-run batch pass (diff-vs-spec read for `light`, evidence sanity
for `none`, plus a cross-task consistency look the per-task reviews can't
give) — so trivial tasks are cheap, nothing ships unreviewed, and a task
that fails its batch review is repaired under the full cycle.

The orchestrator therefore never writes the bulk artifacts: it decomposes the
plan into one compact line per task and dispatches a `gismo:spec-writer` to
ground each one against the real tree (exact paths, signatures, patterns to
imitate). A pointer the plan names but the tree lacks comes back as a
**grounding gap** before any opus agent is dispatched.

### Advice for the sonnet implementers — exactly one advisor

The sonnet tiers assume a good spec. Where the spec runs out, the implementers
get advice rather than guessing — from **one** source, never two. Which one is
a config switch, `advisor` in `.claude/gismo-dev.local.json` (set by
`/gismo:dev-config`, surfaced to every agent as `GISMO_ADVISOR`):

| `advisor` | Who advises | Use when |
|---|---|---|
| `agent` (default) | The `gismo:advisor` subagent, at two mandatory points | No Claude Code advisor configured |
| `native` | Claude Code's own advisor, inherited by every subagent | You have `advisorModel` set |

Set it to `native` if you run with `advisorModel`, and the implementers skip
`gismo:advisor` entirely — you are advised once, by the better mechanism. Run
`/gismo:dev-config` again after `/advisor off` to switch back.

**`gismo:advisor` (opus) — the shipped fallback.** Three trigger points, capped
at 2 consults per task — the first two fire on need, the third on risk:

| Trigger | When |
|---|---|
| Open decision | About to commit to a numerical or API approach the spec left open — before the code is written |
| Stuck loop | Two failed build/test cycles on the same error, before a third attempt |
| Completion check | Before writing the report — mandatory on `Review: full`, optional on `light`/`none` |

The middle trigger mirrors a heuristic Claude's native advisor uses, and it is
where a cheaper model gains most: told which *layer* the problem is in rather
than handed a third variation of the same fix. The third is risk-scaled for the
same reason `Review:` is — a trivial change should not buy an opus opinion to
bless it. Unlike a reviewer it
is consultative, not binding, and it runs *during* the work so a defect is
fixed before the report rather than bouncing back through a repair round. It
reads the task spec and the working diff itself instead of trusting the
caller's summary, and answers with one of three verdicts:

| Verdict | Meaning |
|---|---|
| `ADVICE: PROCEED` | The call is within the implementer's latitude — recommendation + next step |
| `ADVICE: SPEC DECIDES` | The spec already settles it; the implementer misread it |
| `ADVICE: BLOCKED` | The spec is genuinely defective — report `RESULT: BLOCKED`, orchestrator repairs it |

That third verdict is the point: the advisor never invents a decision the spec
should have made, so consulting it cannot quietly paper over a spec defect.
Verdict lines go into the report, where the reviewer can see what was advised
and whether it was followed.

**Claude Code's native [advisor](https://code.claude.com/docs/en/advisor) — the
better mechanism when you have it.** Set

```json
{ "advisorModel": "opus" }
```

(or `/advisor opus`, or `claude --advisor opus`) and **subagents inherit it**,
so every sonnet agent runs the canonical *Sonnet main + Opus advisor* pairing.
It sees the full conversation, so it costs no context handoff and needs no
summarising by the caller. Its one limitation is that Claude decides when to
call it — there is no way to force a consult — which is why the framework ships
`gismo:advisor` for setups that don't have it.

Note the pairing rule cuts the other way for the opus agents: an Opus 4.7+ main
accepts only another Opus 4.7+ (or Fable) as advisor, so `spec-writer` and
`task-reviewer` gain nothing from `advisorModel: sonnet`.

### Overriding the model tiers

The `model:` values above are **defaults**, not hard constraints — each is just a
pin in the agent's frontmatter (`agents/*.md`). You can override them without
editing any files:

- **Session-wide:** set `CLAUDE_CODE_SUBAGENT_MODEL=<alias>` to force *every*
  agent onto one model for that session — e.g. `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`
  to run the whole framework cheaper, or `=opus` for maximum capability. This
  takes precedence over the frontmatter pins.
- **Per agent, permanently:** edit the `model:` line in that agent's file (valid
  aliases: `opus`, `sonnet`, `haiku`, `fable`, or a full model id).
- **Unpin entirely:** remove the `model:` line (or set `model: inherit`) and that
  agent runs on your **main session's** model instead of a fixed tier.

### Prompting standards

The agent and skill prompts follow Anthropic's official model-specific
prompting guides — [Opus 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5),
[Sonnet 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5),
[Fable 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5).
In particular: reviewers report with coverage first and filter downstream
(never "only high-severity"); verification lives in an independent
fresh-context reviewer rather than "double-check your work" instructions;
subagent spawning is explicitly capped; task specs carry the full
specification up front (zero-discovery rule); and reports must ground every
claim in tool-result evidence. Keep these properties when editing prompts.

**Skills** (invoke as `/gismo:<name>`):

| Skill | Purpose |
|---|---|
| `/gismo:plan` | Planning conventions → `plan.md` + task files |
| `/gismo:implement` | Closed-loop orchestration of an approved plan |
| `/gismo:dev-config` | Set build dir + parallel-jobs cap |
| `/gismo:build-target` | Guarded `make <target>` — the only sanctioned build |
| `/gismo:syntax-check` | Per-file `-fsyntax-only` gate via `compile_commands.json` |
| `/gismo:run-tests` | Build + run unit tests, optionally filtered |
| `/gismo:tree` | Core-library map (src/, examples/, unittests/) |
| `/gismo:module-map` | Per-submodule context for `optional/` modules |

## Installation

### Via the Claude Code CLI

```bash
claude plugin marketplace add gismo/gsAgents
claude plugin install gismo@gsagents
```

Or, from a local checkout of this repo:

```bash
claude plugin marketplace add /path/to/gsAgents
claude plugin install gismo@gsagents
```

### Via the G+Smo CMake flag (optional)

For developers who want the install driven from their G+Smo build configuration:

```bash
cmake -DGISMO_INSTALL_AGENTS=ON \
      -DGISMO_AGENTS_SOURCE=/path/to/gsAgents \
      -DGISMO_AGENTS_SCOPE=user .
cmake --build . --target install-agents
```

`GISMO_AGENTS_SCOPE` is `user` (default), `project`, or `local`. The target
validates the manifest before touching your configuration and is safe to re-run.
Opting out (the default, `GISMO_INSTALL_AGENTS=OFF`) leaves your tree untouched.

## Repository layout

```
gsAgents/
├── .claude-plugin/
│   ├── plugin.json         # plugin manifest
│   └── marketplace.json    # this repo doubles as its own marketplace
├── agents/*.md             # agent definitions (Claude format)
├── skills/<name>/          # SKILL.md + scripts/, per the Agent Skills standard
├── cmake/InstallPlugin.cmake
└── CMakeLists.txt          # optional install flag
```

There is **no build or generation step**: the repository *is* the plugin. Skills
reference their bundled scripts via `${CLAUDE_PLUGIN_ROOT}`, which the CLI
resolves at load time.

## Generated context maps

`/gismo:tree` and `/gismo:module-map` generate per-checkout maps into
`<gismo-root>/.claude/gismo-maps/` — they are project data, not shipped with the
plugin (one install serves many worktrees). On a fresh checkout the maps do not
exist yet; the skills generate them on first use.

## Scope

gsAgents currently targets **Claude Code only**. GitHub Copilot CLI and OpenCode
were evaluated and deferred — see `PLUGIN_MIGRATION_BRIEF.md` for the provider
research and the rationale.
