---
name: diagnose
description: Mine the closed-loop execution traces this framework has already left on disk — task specs, implementation reports, adversarial reviews, session transcripts and memory documents — and produce a ranked report of what agents recurrently get wrong. Use before tuning the agent or skill files, so the change is driven by measured recurrence rather than by whichever failure the current session happens to remember.
argument-hint: "[--roots <path>...] [--since YYYY-MM-DD]"
allowed-tools: Read, Write, Grep, Glob, Bash, Agent
---

You are running a diagnostics pass over this framework's own history. The premise: every
`/gismo:implement` run left task specs, reports and reviews behind, and every session left
a transcript in which the user corrected agents in their own words. That corpus is the
empirical record of how these skills actually behave. Nothing else reads it.

Your job is to turn it into a ranked, cited report. **You are not tuning the skills in this
skill** — that is a separate decision the user makes from the report you produce.

## The division of labour, and why it is drawn here

- **Python extracts and counts.** Provenance, verdict sequences, recurrence across
  sessions — all mechanical, all deterministic, all cheap. Anything countable is counted
  before an agent sees it.
- **Haiku taxonomizes.** Each miner reads one pre-filtered slice and groups it. The slice
  is small and the question is "what categories are these", never "what does this mean".
- **You judge.** Ranking, attribution to a specific rule in a specific file, and the
  recommendation are yours.

The script exists to make the miners' job small. Without it every miner would re-grep the
whole corpus; with it each reads a few hundred lines. This is the same move `context.md`
makes inside `/gismo:implement` — ground the shared facts once so parallel agents never
re-scout them.

## 1. Extract

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/diagnose/scripts/harvest.py \
    --roots ~/Code ~/.claude/projects \
    --out .claude/diagnostics/$(date +%F)
```

Stdlib only, no build, no network. It writes `index.jsonl`, `summary.md`,
`recurrence.json` and a `slices/` directory.

Read `summary.md` and `recurrence.json` yourself — they are small, and `recurrence.json`
is the answer to the actual question ("what did agents *keep* getting wrong"), already
computed. Do not read the slices; they are the miners' input, not yours.

## 2. Fan out — cheap models only

Dispatch one miner per slice, **all in a single message**, each on **haiku**.

This rule is not a cost preference, it is a recorded correction. An earlier run fanned a
catalog agent out into eleven expensive sub-agents and burned the user's budget; the
instruction that followed was *"Use CHEAP subagents, NEVER spawn fable!"* Generic agent
types (`Explore`, `Plan`, `general-purpose`, `fork`) **inherit the caller's model**, so
dispatching one without an explicit cheap `model` silently runs it on yours. Always pass
`model: haiku` here. Never dispatch more than one wave without stating the cost first.

Give each miner a mechanical, taxonomic question:

> Read `<slice path>`. Group the items into recurring categories. For each category report:
> a short name, the count, and two verbatim examples WITH their provenance lines. Do not
> interpret, do not recommend fixes, do not read any other file.

Haiku is safe here precisely because the slice is pre-filtered and the question is
taxonomic. It is not safe for synthesis — never ask a miner what a pattern implies.

## 3. The confound you must not walk into

**Raw term frequency over whole review files is meaningless.** The reviewer protocol in
`TASK_CONTRACT.md` lists comment discipline, conventions and falsification as mandatory
checks, so those words appear in most reviews as *checklist*, not as *finding*. Measured:
"comment" occurs in 69% of all review files.

`harvest.py` therefore scopes term counting to the required-fixes region. If you find
yourself quoting a frequency that came from anywhere else, it is not evidence. A
diagnostics pipeline that manufactures a confident wrong answer is worse than none — that
failure mode is the reason this skill exists.

Two more traps the corpus sets:

- **Review files accumulate repair rounds in one file.** A file can hold both a round-1
  `FAIL` and a round-2 `PASS`. Per-file verdict counts are wrong; the script emits verdict
  *sequences*, and the FAIL→PASS round count is the interesting statistic. A third
  verdict, `PASS (FIX-UPS)`, marks a text-only correction pass over a sound artifact: it
  cost no repair round, so read `FAIL → PASS (FIX-UPS)` as one repair round (the FAIL) and
  a lone `PASS (FIX-UPS)` as zero — never fold it into `PASS` or into `FAIL`.
- **Frequency is not severity.** A defect appearing 200 times in doc tasks matters less
  than one appearing 5 times in numerics. Weight by blast radius, and say which you used.

## 4. Aggregate into `patterns.md`

Write `.claude/diagnostics/<date>/patterns.md`. One entry per recurring pattern, ranked:

- **What recurs** — one line.
- **How often, and across how many distinct runs or sessions** (from `recurrence.json` —
  distinct sessions, not raw hits; ten hits in one run is one incident).
- **Two verbatim citations** with file paths.
- **Which rule it indicts** — the specific file and section (`agents/implementer.md`,
  `TASK_CONTRACT.md` §comment-discipline, `skills/plan/SKILL.md` §2). A pattern that
  cannot be attributed to a rule is a finding about the corpus, not about the framework;
  file it separately rather than inventing a rule for it.
- **Whether a memory already documents it.** If a `type: feedback` document names this
  and it recurred *after* that document was written, the defect is not that the lesson was
  unlearned — it is that the memory never reached the session. Say so; the fix is
  different.

End with what you could NOT conclude. A pattern you suspect but cannot count belongs in an
"unsupported by the data" section, not in the ranking.

## 5. Hand back

Report the top patterns in chat with their counts, and name the concrete edits each would
imply. **Do not make those edits.** The user decides which findings become changes —
several will be judgment calls about scope rather than defects, and a diagnostics pass that
edits the thing it measures cannot be re-run as a control.

One class of finding is worth surfacing on its own: `type: feedback` memory documents that
are scoped to one project directory but state a general rule (model and cost rules,
git-safety rules, verification discipline). Those never load in other projects. Promoting
them is a change the user can bank without touching a single skill — but *which* are
genuinely cross-project is a judgment call to put to the user, never one to decide here.

## Safety

Read-only over the corpus. Never write anywhere but `.claude/diagnostics/<date>/`, which
is gitignored. Never commit, never touch the git index, never `git stash`. The transcripts
and memory documents contain the user's private working notes — they stay on disk and in
the report; nothing goes to a network service.
