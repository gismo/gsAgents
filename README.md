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
| `gismo:task-reviewer` | opus | Adversarial per-task gate: PASS / PASS (fix-ups) / FAIL (attacks the change; no routine test re-runs) |
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
before returning a single `CYCLE: PASS / PASS (fix-ups applied) / PASS (review deferred) / FAIL / BLOCKED` verdict. A review whose only
blocking findings are textual (a report claim the diff does not support, a stale
comment) returns the third verdict, `VERDICT: PASS (fix-ups)`: the correction is
applied once, with no second review and no repair round, because a wrong sentence
over correct code should not cost what a wrong tolerance costs. The round-by-round
reports and reviews stay out of the main session's context; the files under
`.claude/plans/<slug>/tasks/` remain the audit trail.

### Two gears: quick and standard

A one-line request should not pay for a twelve-task orchestration. `/gismo:plan`
triages every request against a checkable rubric — at most 2 tasks, no new public API,
no numerical algorithm change, nothing later builds on it, ≲ 5 files — and records the
verdict as a `Mode:` line in `plan.md` (`--quick` / `--full` overrides it).

- **quick** — the orchestrator writes the task file itself when the plan is already
  grounded, dispatches the implementer directly, runs one `gismo:task-reviewer` and at
  most one repair round. No spec-writer wave, no task-lead, no `summary.md`;
  `light`/`none` tasks still get the one-reviewer batch review at final
  verification.
- **standard** — the full machinery below.

`Review: full|measurement|light|none` still scales the *review* within a run; `Mode:` scales the
*machinery around it*. They are independent dials.

### Grounding once instead of N times

In standard mode the spec-writers run concurrently, and left to themselves they
re-scout the same facts — the class everyone extends, the pattern everyone imitates.
So the orchestrator runs a **grounding pre-pass**: one batch of haiku scouts for the
facts more than one task needs, written to `.claude/plans/<slug>/context.md` with
`file:line` citations. Spec-writers read the ledger, scout only what is specific to
their own task, and return `New facts:` in their report. They are dispatched in **waves
of ~4**; between waves the orchestrator — the ledger's single writer, so no append race —
folds the new facts in, and the next wave starts warmer.

### Evidence by reference, standing rules, append-only plans

A report that retypes command output can carry a number that is plausible and
wrong, so every command whose output a report quotes runs through
`/gismo:evidence-log` (`run_logged.sh`): it keeps a verbatim, numbered log under
`.claude/plans/<slug>/tasks/logs/` (command, UTC start and end, interleaved
stdout and stderr, exit code, and a final `STATUS:` line) and prints the log's path, line count and md5. A
report cites `logs/NNN-<slug>.log:L1-L2 (md5 <hash>)` and fences are copies of
those lines, nothing retyped; the reviewer diffs each fence against its log. A
check that failed to start is logged too but is not evidence.

Facts that hold for the whole plan live once, in `.claude/plans/<slug>/rules.md`:
**standing rules**, each factual sentence paired with the command that verifies
it. A task spec never copies them; it names `rules.md` and the md5 the
spec-writer verified it at, and its `## Standing rules check` cites the logged
run that confirmed each rule the task relies on. (These are unrelated to the
*Session rules* section at the top of `/gismo:plan` and `/gismo:implement`, which
govern how the orchestrator behaves in that session, not what is true of the
code.) `plan.md`, `rules.md` and specs are **append-only for premises and
status**: a correction is a dated `Update YYYY-MM-DD (reason): …` paragraph under
the original, so what was believed, and when it stopped being believed, survives;
instruction lines (`Review:`, `Files`, acceptance criteria) are still corrected
in place. The reviewer appends a `## Round N` section per repair round rather
than overwriting, and `dispatches.log` records every implementer pass (`impl`,
`repair`, `fixup`, `evidence`), every review and every review verdict with a UTC
timestamp; spec-writers, scouts and advisor consults are not logged.

### Adjacent sessions and native task tracking

Before dispatching anything, `/gismo:implement` calls `ListAgents` (Claude Code
>= 2.1.224) to see whether another local session is working in the same
worktree or on the same plan, and asks how the two relate. A session is matched
by working directory or by name, so name sessions after the plan:
`claude --name <slug>` (or `/rename <slug>`).

The run's progress is also mirrored into Claude Code's native task list, one task
per task file (subject = the file's basename, dependencies from the
decomposition), with `completed` meaning *reviewed*: the implementer marks its
task `in_progress` and the orchestrator marks it `completed` when the cycle
passes. A task whose review was deferred (`Review: light`/`none`) stays
`in_progress` until the end-of-run batch review passes it. This is optional and never load-bearing — the task files remain the
record. The Task tools are off by default on current models; to enable them add
to `~/.claude/settings.json` (a plugin cannot set it, and it takes effect in new
sessions only, since subagents get the tools only if it was set at session start):

```json
{ "env": { "CLAUDE_CODE_ENABLE_TODO_TOOLS": "1" } }
```

Without it the framework says so once and runs with the task files alone. For
multi-session work on one plan, `CLAUDE_CODE_TASK_LIST_ID=<slug>` stores the
list in `~/.claude/tasks/<slug>/`, and every session started with the same ID
shares it.

### Comments that survive the commit

Agents narrate their diffs in comments: "removed the old loop because…", "added for
task 3". That is useful scaffolding while implementing and noise once it lands. The
framework handles it twice over. **Prevention**: the implementer protocol puts change
reasoning in `NN-report.md`, where it already belongs, and the reviewer flags
scaffolding left in the source. **Safety net**: `/gismo:tidy` runs over the run's diff
before the final conformance check (or standalone on any dirty tree), stripping diff
narration while keeping doxygen, theory links, complexity notes and real TODOs.

Cost control rests on an asymmetry: **writing is cheap, checking is expensive.**
A well-grounded spec (opus `gismo:spec-writer`) lets the three implementers run
on sonnet, while the adversarial gate that has to catch what they missed stays
on opus (`gismo:task-reviewer`). The loop-driver is sonnet — it dispatches,
reads verdicts and steers a running agent back on course, but implements
nothing itself.

Every working agent may delegate lookups downward instead of reading the library
itself: `gismo:scout` (haiku) answers one settled fact per call with a
`file:line` citation, and `gismo:indexer` (sonnet) handles questions that need
real exploration. Spawn rules: the orchestrator spawns spec-writers and
task-leads; a task-lead spawns its task's agent and the reviewer, and may
message those two — and only those two — while they run; spec-writer,
the implementers, the reviewer, doc-writer and debugger may spawn scout and
indexer; the three implementers may additionally spawn `gismo:advisor` (opus,
capped at 2 per task); scout, indexer and advisor spawn nothing.

Each agent also pins an `effort:` tier in its frontmatter, the reasoning-effort
counterpart of `model:`: `high` for `gismo:task-reviewer`; `low` for the
mechanical `gismo:builder`, `gismo:unittest-runner` and `gismo:scout`; `medium`
for every other agent.

### Verifying the tiers actually held

The `model:` line in an agent file states an intention, not an outcome: an
explicit `model` argument on the `Agent` call overrides the frontmatter, and a
`subagent_type` that fails to resolve falls back to a generic agent running at
the caller's tier. Neither is visible in the agent definition, so the tiering —
and the cost model that rests on it — has to be checked against the transcripts,
which record the resolved model on every message.

```
/gismo:audit-models                      # or, directly:
scripts/audit-agent-models.py            # every session for this project
scripts/audit-agent-models.py --quiet    # mismatches only; exit 1 if any
```

Transcripts are per-machine, so this audits runs that happened where you run
it — not another machine, and not a cloud session.

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
in-cycle adversarial review. `measurement` tasks — a data file plus an analysis
script — are also reviewed in-cycle, but there is nothing to attack in a CSV, so
the reviewer re-derives the headline numbers and diffs every fence in the report
against its log instead. `light`/`none` tasks defer their review into
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
**detected, not configured**: `gismo_env.sh` reads `advisorModel` out of the
project and user settings files and surfaces the answer to every agent as
`GISMO_ADVISOR`.

| `GISMO_ADVISOR` | Who advises | Detected when |
|---|---|---|
| `agent` (default) | The `gismo:advisor` subagent, at three trigger points | No `advisorModel` in settings, or `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` |
| `native` | Claude Code's own advisor, inherited by every subagent | `advisorModel` is set — including via `/advisor` |

So `/advisor opus` and `/advisor off` take effect on the next agent run with no
config edit. The value is detected rather than set by hand because a hand-set
`agent` while an advisor is in fact configured would advise every implementer
twice — precisely what the switch exists to prevent.
The `advisor` key in `.claude/gismo-dev.local.json` survives for the one
undetectable case, `claude --advisor <model>`, which touches no file; it can
only escalate to `native`, never talk the detector out of one it found.

Worth knowing before you enable it: subagents inherit the advisor and apply the
[pairing check](https://code.claude.com/docs/en/advisor#choose-an-advisor-model)
against their own model, so `advisorModel: opus` attaches an opus advisor to
*every* gismo subagent that accepts one — the haiku scout included. A one-fact
lookup does not need an opus second opinion; if that shows up in your bill,
that is where it comes from.

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
| `/gismo:plan` | Triage (quick/standard) + planning conventions → `plan.md` (+ decomposition) |
| `/gismo:implement` | Closed-loop orchestration of an approved plan, in either mode |
| `/gismo:evidence-log` | Run a command through a verbatim numbered logger; reports cite log path and line range |
| `/gismo:tidy` | Strip change-narration comments from the diff before committing |
| `/gismo:dev-config` | Set build dir + parallel-jobs cap |
| `/gismo:build-target` | Guarded `make <target>` — the only sanctioned build |
| `/gismo:syntax-check` | Per-file `-fsyntax-only` gate via `compile_commands.json` |
| `/gismo:run-tests` | Build + run unit tests, optionally filtered |
| `/gismo:tree` | Core-library map (src/, examples/, unittests/) |
| `/gismo:module-map` | Per-submodule context for `optional/` modules |
| `/gismo:audit-models` | Check each subagent ran on the tier its definition declares |
| `/gismo:diagnose` | Mine past runs, transcripts and memory for recurring agent defects |

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
