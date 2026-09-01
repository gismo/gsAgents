"""pytest suite for harvest.py.

Every test builds its own synthetic tree under `tmp_path` -- none of these
tests ever read the real corpus (`~/Code`, `~/.claude/projects`).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HARVEST_PATH = Path(__file__).parent / "harvest.py"
_spec = importlib.util.spec_from_file_location("harvest", _HARVEST_PATH)
assert _spec is not None and _spec.loader is not None
harvest = importlib.util.module_from_spec(_spec)
sys.modules["harvest"] = harvest
_spec.loader.exec_module(harvest)


# ---------------------------------------------------------------------------
# make_class_key
# ---------------------------------------------------------------------------


def test_make_class_key_normalizes_and_truncates():
    key = harvest.make_class_key("Gap 3 remark asserts causation!! (the note forbids)")
    assert key == key.lower()
    assert all(c.isalnum() or c == "-" for c in key)
    assert len(key) <= 60


def test_make_class_key_empty_falls_back():
    assert harvest.make_class_key("!!!???") == "unclassified"


# ---------------------------------------------------------------------------
# Review parser: round splitting + verdict sequence
# ---------------------------------------------------------------------------


def test_review_round1_fail_round2_pass_yields_sequence():
    text = (
        "VERDICT: FAIL\n\n"
        "## Required fixes\n\n"
        "1. **Fix the guard.** Detail about the guard.\n\n"
        "---\n\n"
        "# Round 2 (re-review after fixes)\n\n"
        "VERDICT: PASS\n\n"
        "All fixes verified in the artifact.\n"
    )
    parsed = harvest.parse_review_text(text)
    assert parsed.verdict_sequence == ["FAIL", "PASS"]
    assert len(parsed.verdict_sequence) <= parsed.round_count


def test_review_single_round_single_verdict():
    text = "VERDICT: PASS\n\nEverything checks out.\n"
    parsed = harvest.parse_review_text(text)
    assert parsed.verdict_sequence == ["PASS"]
    assert parsed.round_count == 1


def test_verdict_count_never_exceeds_round_count():
    text = (
        "VERDICT: FAIL\n\n"
        "# Round 2\n\n"
        "VERDICT: PASS\n\n"
        "# Round 3\n\n"
        "no verdict line in this round at all\n"
    )
    parsed = harvest.parse_review_text(text)
    assert len(parsed.verdict_sequence) <= parsed.round_count
    assert parsed.verdict_sequence == ["FAIL", "PASS"]


def test_round_boundary_without_any_heading_still_yields_full_sequence():
    # Measured on the real corpus: some review files restate VERDICT for a
    # repair round with no "Round N" heading (or any heading at all)
    # marking the boundary -- only the VERDICT line itself changes.
    text = (
        "VERDICT: FAIL\n\n"
        "## Required fixes\n\n"
        "1. **Fix the off-by-one.** Detail.\n\n"
        "## Notes for the orchestrator\n\n"
        "Nothing else to flag.\n\n"
        "VERDICT: PASS\n\n"
        "Re-ran independently, fix confirmed applied.\n"
    )
    parsed = harvest.parse_review_text(text)
    assert parsed.verdict_sequence == ["FAIL", "PASS"]
    assert len(parsed.verdict_sequence) <= parsed.round_count


def test_round_boundary_marked_by_prose_heading_not_matching_round_n():
    # Measured on the real corpus: "## Re-review (repair round 1)" -- the
    # word "round" is not the first token after the heading marker, so it
    # does not match the `^#+\s*Round\s+\d+` pattern; the boundary must
    # still be found via the VERDICT restatement itself.
    text = (
        "VERDICT: FAIL\n\n"
        "## Required fix (blocking)\n\n"
        "1. **Guard the null case.** Detail.\n\n"
        "## Re-review (repair round 1)\n\n"
        "VERDICT: PASS\n\n"
        "Fix verified in the artifact.\n"
    )
    parsed = harvest.parse_review_text(text)
    assert parsed.verdict_sequence == ["FAIL", "PASS"]


# ---------------------------------------------------------------------------
# Review parser: fix-line extraction scoped to Required fixes region
# ---------------------------------------------------------------------------


def test_fix_line_extraction_scoped_to_required_fixes_region():
    text = (
        "VERDICT: FAIL\n\n"
        "## Required fixes\n\n"
        "1. **Inside the region.** Detail that belongs to the finding.\n\n"
        "## Do NOT change\n\n"
        "- Some blessed item, not a fix.\n\n"
        "## Some other numbered list\n\n"
        "1. Outside the region -- must not be extracted as a fix.\n"
    )
    parsed = harvest.parse_review_text(text)
    fix_texts = [f.text for f in parsed.fixes]
    assert len(parsed.fixes) == 1
    assert "Inside the region" in fix_texts[0]
    assert not any("Outside the region" in t for t in fix_texts)


def test_fix_lines_appear_verbatim_in_source_text():
    text = (
        "VERDICT: FAIL\n\n"
        "## Required fixes\n\n"
        "1. **First fix.** Detail one.\n"
        "2. **Second fix.** Detail two.\n"
    )
    parsed = harvest.parse_review_text(text)
    assert len(parsed.fixes) == 2
    for fix in parsed.fixes:
        assert fix.text in text


def test_convention_term_counting_scoped_to_required_fixes_region():
    text = (
        "VERDICT: FAIL\n\n"
        "## Required fixes\n\n"
        "1. **Missing tolerance check.** Uses tolerance incorrectly.\n\n"
        "## What was verified\n\n"
        "Every comment was checked for comment discipline; comment style ok.\n"
    )
    parsed = harvest.parse_review_text(text)
    # Both "tolerance" occurrences sit inside the Required-fixes region.
    assert parsed.term_hits["tolerance"] == 2
    assert parsed.term_hits["comment"] == 0


# ---------------------------------------------------------------------------
# Report parser
# ---------------------------------------------------------------------------


def test_report_result_and_status_tallies():
    text = (
        "STATUS: OK\n\nSTATUS: OK\n\nSTATUS: FAIL\n\nRESULT: DONE\n"
    )
    parsed = harvest.parse_report_text(text)
    assert parsed.result_tallies == {"DONE": 1}
    assert parsed.status_tallies == {"OK": 2, "FAIL": 1}


def test_report_advisor_line_extraction():
    text = "Advisor: native (GISMO_ADVISOR=native; not consulted).\n\nRESULT: DONE\n"
    parsed = harvest.parse_report_text(text)
    assert parsed.advisor_lines == ["native (GISMO_ADVISOR=native; not consulted)."]


def test_report_deviation_extraction_skips_trivial_none():
    text = (
        "## Deviations from the spec\n\n"
        "None.\n\n"
        "RESULT: DONE\n"
    )
    parsed = harvest.parse_report_text(text)
    assert parsed.deviations == []


def test_report_deviation_extraction_captures_real_deviation():
    text = (
        "## Deviations from the spec\n\n"
        "Used a stack-based fallback instead of the heap allocator the spec named.\n\n"
        "RESULT: DONE\n"
    )
    parsed = harvest.parse_report_text(text)
    assert len(parsed.deviations) == 1
    assert "stack-based fallback" in parsed.deviations[0]


def test_blocked_passage_captures_context_before_result_blocked():
    text = (
        "## What happened\n\n"
        "The scan measured only 2 distinct leaves, short of the target.\n\n"
        "RESULT: BLOCKED\n"
    )
    passage = harvest.blocked_passage(text)
    assert "2 distinct leaves" in passage


# ---------------------------------------------------------------------------
# Transcript parser
# ---------------------------------------------------------------------------


def test_subagents_transcript_path_detected():
    assert harvest.is_subagent_transcript(Path("/x/y/subagents/z.jsonl")) is True
    assert harvest.is_subagent_transcript(Path("/x/y/session.jsonl")) is False


def test_subagents_transcript_contributes_zero_user_messages(tmp_path):
    sub_dir = tmp_path / "projects" / "proj" / "subagents"
    sub_dir.mkdir(parents=True)
    transcript = sub_dir / "sub.jsonl"
    record = {
        "type": "user",
        "isMeta": False,
        "message": {"role": "user", "content": "genuine looking human text"},
        "sessionId": "s1",
        "gitBranch": "main",
        "timestamp": "2026-01-01T00:00:00Z",
        "cwd": "/x",
    }
    transcript.write_text(json.dumps(record) + "\n")

    assert harvest.is_subagent_transcript(transcript) is True

    index_entries, records, _ = harvest.build_records([tmp_path], since=None)
    assert not any(r.source_path == str(transcript) for r in records)


def test_transcript_list_content_excluded_str_content_included(tmp_path):
    transcript = tmp_path / "session.jsonl"
    list_record = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "x"}]},
        "sessionId": "s1",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    str_record = {
        "type": "user",
        "message": {"role": "user", "content": "please don't do that again"},
        "sessionId": "s1",
        "gitBranch": "main",
        "timestamp": "2026-01-02T00:00:00Z",
        "cwd": "/x",
    }
    transcript.write_text(json.dumps(list_record) + "\n" + json.dumps(str_record) + "\n")

    messages = list(harvest.iter_transcript_user_messages(transcript))
    assert len(messages) == 1
    assert messages[0]["text"] == "please don't do that again"


def test_transcript_meta_and_markup_records_excluded(tmp_path):
    transcript = tmp_path / "session.jsonl"
    records = [
        {"type": "user", "isMeta": True, "message": {"content": "caveat text"}, "timestamp": "t"},
        {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}, "timestamp": "t"},
        {"type": "user", "message": {"content": "[Request interrupted by user]"}, "timestamp": "t"},
        {"type": "assistant", "message": {"content": "not a user record"}, "timestamp": "t"},
        {"type": "user", "message": {"content": "a genuine human message"}, "timestamp": "t"},
    ]
    transcript.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    messages = list(harvest.iter_transcript_user_messages(transcript))
    assert len(messages) == 1
    assert messages[0]["text"] == "a genuine human message"


def test_correction_probe_detection():
    assert harvest.is_correction_probe("It's too tight, again!!") is True
    assert harvest.is_correction_probe("please build the target now") is False


# ---------------------------------------------------------------------------
# Memory-doc parser
# ---------------------------------------------------------------------------


def test_memory_type_top_level():
    text = (
        "---\n"
        "name: python venv location\n"
        "type: feedback\n"
        "originSessionId: 62da0f30-4511-4ce0-bc44-3578a86adb9a\n"
        "---\n\n"
        "Always activate the venv first.\n"
    )
    parsed = harvest.parse_memory_text(text)
    assert parsed.doc_type == "feedback"
    assert parsed.origin_session_id == "62da0f30-4511-4ce0-bc44-3578a86adb9a"


def test_memory_type_nested_under_metadata():
    text = (
        "---\n"
        "name: presentation-feedback-style\n"
        "metadata: \n"
        "  node_type: memory\n"
        "  type: feedback\n"
        "  originSessionId: bddf8939-fe01-4224-a008-c07b1cb63f59\n"
        "  modified: 2026-07-22T14:03:57.219Z\n"
        "---\n\n"
        "Give critical, detailed feedback.\n"
    )
    parsed = harvest.parse_memory_text(text)
    assert parsed.doc_type == "feedback"
    assert parsed.origin_session_id == "bddf8939-fe01-4224-a008-c07b1cb63f59"
    assert parsed.modified == "2026-07-22T14:03:57.219Z"


def test_memory_star_findings_and_wikilinks():
    text = (
        "---\nname: x\ntype: project\n---\n\n"
        "See [[project_related_doc]] for background.\n\n"
        "★★★ **The run's biggest find: something broke.** More detail follows.\n\n"
        "★★ A smaller finding.\n"
    )
    parsed = harvest.parse_memory_text(text)
    assert parsed.wikilinks == ["project_related_doc"]
    assert len(parsed.star_findings) == 2
    assert parsed.star_findings[0][0] == "★★★"
    assert "biggest find" in parsed.star_findings[0][1]


# ---------------------------------------------------------------------------
# End-to-end pipeline invariants
# ---------------------------------------------------------------------------


def _build_minimal_corpus(tmp_path: Path) -> None:
    plan_dir = tmp_path / "repo" / ".claude" / "plans" / "demo-plan"
    tasks_dir = plan_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "01-do-thing.md").write_text(
        "# Task 01: Do the thing\nAgent: gismo:implementer\nReview: full\n\n## Goal\n...\n"
    )
    (tasks_dir / "01-review.md").write_text(
        "VERDICT: FAIL\n\n"
        "## Required fixes\n\n"
        "1. **Do the thing correctly.** Detail about the fix.\n"
    )
    (tasks_dir / "01-report.md").write_text(
        "RESULT: BLOCKED\n\n"
        "Ran out of time before finishing the measurement.\n\n"
        "RESULT: BLOCKED\n"
    )

    project_dir = tmp_path / "projects" / "proj"
    project_dir.mkdir(parents=True)
    transcript = project_dir / "sess.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"content": "please don't do that again"},
                "sessionId": "s1",
                "gitBranch": "main",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": "/x",
            }
        )
        + "\n"
    )

    memory_dir = project_dir / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "feedback_example.md").write_text(
        "---\nname: example\ntype: feedback\n---\n\n"
        "★★★ **Big finding.** Something that recurred.\n"
    )


def test_every_emitted_record_has_source_path_and_timestamp(tmp_path):
    _build_minimal_corpus(tmp_path)
    index_entries, records, _ = harvest.build_records([tmp_path], since=None)
    assert records, "expected at least one extracted record"
    for rec in records:
        assert rec.source_path
        assert rec.timestamp


def test_harvest_writes_all_expected_outputs(tmp_path):
    _build_minimal_corpus(tmp_path)
    out_dir = tmp_path / "out"
    harvest.harvest([tmp_path], out_dir, since=None)

    assert (out_dir / "index.jsonl").is_file()
    assert (out_dir / "summary.md").is_file()
    assert (out_dir / "recurrence.json").is_file()
    for filename in harvest._SLICE_KIND_MAP:
        assert (out_dir / "slices" / filename).is_file()
    assert (out_dir / "slices" / "conventions.tsv").is_file()

    index_lines = (out_dir / "index.jsonl").read_text().splitlines()
    assert len(index_lines) == 1
    entry = json.loads(index_lines[0])
    assert entry["slug"] == "demo-plan"
    assert entry["verdict_tallies"] == {"FAIL": 1}
    assert entry["result_tallies"] == {"BLOCKED": 2}

    recurrence = json.loads((out_dir / "recurrence.json").read_text())
    assert all(isinstance(by_key, dict) for by_key in recurrence.values())
    assert all(
        isinstance(count, int) and count >= 1
        for by_key in recurrence.values()
        for count in by_key.values()
    )

    fixes_text = (out_dir / "slices" / "review-fixes.md").read_text()
    review_file = (
        tmp_path / "repo" / ".claude" / "plans" / "demo-plan" / "tasks" / "01-review.md"
    )
    assert str(review_file) in fixes_text
    assert "demo-plan" in fixes_text

    corrections_text = (out_dir / "slices" / "user-corrections.md").read_text()
    assert "s1" in corrections_text
    assert "main" in corrections_text


def test_recurrence_distinguishes_same_slug_in_different_repos(tmp_path):
    # Two sibling repos reusing the same plan slug for genuinely different work
    # must count as two distinct runs -- run_slug alone collides, so the unit
    # has to derive from run_id.
    #
    # The scenario deliberately uses *different* content. Same-slug pairs whose
    # contents are byte-identical are relocated copies of one run, not two runs,
    # and are deduplicated upstream in `iter_plan_dirs`; see
    # `test_byte_identical_archived_run_is_deduplicated`.
    for repo_name, fix in (("repo-a", "First defect."), ("repo-b", "Second defect.")):
        tasks_dir = tmp_path / repo_name / ".claude" / "plans" / "shared-slug" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "01-review.md").write_text(
            f"VERDICT: FAIL\n\n## Required fixes\n\n1. **{fix}** Detail.\n"
        )

    _, records, _ = harvest.build_records([tmp_path], since=None)
    fix_records = [r for r in records if r.kind == "review-fix"]
    assert len(fix_records) == 2
    units = {r.session_unit() for r in fix_records}
    assert len(units) == 2, "same slug in two repos must not collapse into one session unit"


def test_since_filter_excludes_older_artifacts(tmp_path):
    _build_minimal_corpus(tmp_path)
    review_file = tmp_path / "repo" / ".claude" / "plans" / "demo-plan" / "tasks" / "01-review.md"
    old_time = 1_000_000_000  # 2001-09-09, well before any plausible --since date
    import os

    os.utime(review_file, (old_time, old_time))

    from datetime import date

    index_entries, records, _ = harvest.build_records([tmp_path], since=date(2026, 1, 1))
    assert not any(r.source_path == str(review_file) for r in records)


def test_recurrence_is_grouped_by_kind_so_acknowledgements_cannot_outrank_findings(
    tmp_path,
):
    """An acknowledgement repeated across many sessions must not appear in the
    user-correction ranking. On the real corpus "continue" recurs across 56
    runs; pooled with corrections it outranks every substantive finding."""
    proj = tmp_path / "projects" / "-proj"
    proj.mkdir(parents=True)
    for i in range(3):
        (proj / f"s{i}.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": f"s{i}",
                        "timestamp": "2026-08-01T00:00:00Z",
                        "message": {"role": "user", "content": text},
                    }
                )
                for text in ("continue", "No, you should have used the helper instead")
            )
            + "\n"
        )

    _, records, _ = harvest.build_records([tmp_path], since=None)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    recurrence = harvest.write_recurrence(records, out_dir)

    assert "user-correction" in recurrence
    ack_keys = [k for k in recurrence.get("user-correction", {}) if "continue" in k]
    assert not ack_keys, f"acknowledgement leaked into corrections: {ack_keys}"
    assert any("continue" in k for k in recurrence.get("user-message", {}))


def _write_run(base, repo, slug, fix_text):
    tasks = base / repo / ".claude" / "plans" / slug / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "01-review.md").write_text(
        f"VERDICT: FAIL\n\n## Required fixes\n\n1. **{fix_text}**\n"
    )
    return tasks.parent


def test_byte_identical_archived_run_is_deduplicated(tmp_path):
    """An archived worktree is a copy, not a second run. Counting both inflates
    every distinct-run recurrence figure."""
    _write_run(tmp_path, "live", "shared-slug", "the same defect")
    _write_run(tmp_path, "Archive/live-old", "shared-slug", "the same defect")

    found = list(harvest.iter_plan_dirs([tmp_path]))
    assert len(found) == 1, [str(p) for p in found]


def test_same_slug_with_different_contents_is_kept_as_two_runs(tmp_path):
    """Dedup is on content, not slug -- genuinely different runs both survive."""
    _write_run(tmp_path, "repo_a", "shared-slug", "defect one")
    _write_run(tmp_path, "repo_b", "shared-slug", "a different defect")

    found = list(harvest.iter_plan_dirs([tmp_path]))
    assert len(found) == 2, [str(p) for p in found]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
