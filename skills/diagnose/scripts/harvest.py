#!/usr/bin/env python3
"""Extract structured, provenance-tagged findings from the gsAgents run corpus.

The corpus is the set of artifacts left behind by `/gismo:implement` closed
loops and by ordinary Claude Code sessions: task specs, implementation
reports and adversarial review files under `.claude/plans/<slug>/tasks/`,
session transcripts under `~/.claude/projects/**/*.jsonl`, and curated
memory documents under `~/.claude/projects/*/memory/*.md`.

This script performs extraction only. It never decides what a finding
*means* -- it locates findings, attaches provenance (source path, run slug
or sessionId, git branch where available, timestamp) and a stable
`class_key` so recurrence across sessions can be counted downstream, in
Python, before any language model reads a byte of it.

Format facts this parser depends on (measured against the real corpus,
not assumed):

- Review files accumulate repair rounds *in the same file*, each carrying
  its own ``VERDICT:`` line. A file's verdicts are therefore a *sequence*
  (e.g. ``["FAIL", "PASS"]`` or ``["FAIL", "PASS (FIX-UPS)"]``), never a
  single value. The round boundary is
  sometimes a heading matching ``^#+\\s*Round \\d`` -- but not always: the
  corpus also uses prose headings (``## Re-review (repair round 1)``) or no
  heading at all, only a restated ``VERDICT:`` line. The parser therefore
  treats every ``VERDICT:`` occurrence as a round boundary in its own right,
  with round headers as an additional (redundant where both exist) signal.
- Numbered fix lines (``^\\d+\\.``) are meaningful only inside the
  ``## Required fixes`` region. The same reviewer protocol lists mandatory
  checklist items (comment discipline, ``real_t`` usage, ...) elsewhere in
  the file, so both fix-line extraction and term-frequency counting must be
  scoped to that region -- counting over the whole file conflates the
  checklist with the findings.
- Transcript JSONL records with ``type == "user"`` and a *list*
  ``message.content`` are stored tool results, not typed human input,
  because the SDK reuses the ``user`` role. Only ``str`` content is a
  genuine human message. ``isSidechain`` does not identify subagent output;
  the only reliable discriminator is a ``/subagents/`` path segment.
- Memory-doc frontmatter is YAML-ish and inconsistent across the corpus:
  ``type:`` appears as a top-level key in some docs and nested under
  ``metadata:`` in others.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_ROOTS: List[Path] = [Path.home() / "Code", Path.home() / ".claude" / "projects"]

# The reviewer protocol (TASK_CONTRACT.md) lists these as mandatory checklist
# items, so raw whole-file term frequency over-counts them; they are only a
# genuine finding when they occur inside a "Required fixes" region.
CONVENTION_TERMS: List[str] = [
    "comment",
    "real_t",
    "acceptance criterion",
    "tolerance",
    "std::move",
    "index_t",
    "out of scope",
    "falsification",
    "give()",
    "GISMO_EXPORT",
    "scope creep",
    "hardcoded",
    "narration",
    "uninitialized",
    "TODO",
    "magic number",
    "memory leak",
]

_PROBE_WORDS: Tuple[str, ...] = (
    "again",
    "don't",
    "instead",
    "never",
    "do not",
    "wrong",
    "should have",
)


# ---------------------------------------------------------------------------
# Provenance / class-key
# ---------------------------------------------------------------------------


def make_class_key(text: str, max_len: int = 60) -> str:
    """Normalize finding text into a stable slug for cross-session counting.

    Parameters
    ----------
    text : str
        The raw finding text (a fix line, a message, a passage, ...).
    max_len : int, optional
        Maximum slug length, by default 60.

    Returns
    -------
    str
        A lowercase, alphanumeric+hyphen slug, truncated to `max_len`. Never
        empty -- falls back to ``"unclassified"``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        return "unclassified"
    return slug[:max_len].rstrip("-") or "unclassified"


@dataclass
class Record:
    """One extracted finding, always carrying its provenance.

    Attributes
    ----------
    kind : str
        The extraction axis, e.g. ``"review-fix"``, ``"user-correction"``.
    class_key : str
        Stable slug from `make_class_key`, used for cross-session recurrence.
    text : str
        The verbatim extracted text.
    source_path : str
        Absolute path of the file this was extracted from.
    timestamp : str
        ISO-8601 timestamp: the record's own timestamp if one exists
        (transcripts, memory frontmatter ``modified:``), else the source
        file's mtime.
    run_slug : str, optional
        The `.claude/plans/<slug>` directory name, where applicable. Display
        only -- slugs repeat across sibling repos (e.g. relocated worktrees
        under `Code/Archive/`), so recurrence counting uses `run_id`, not this.
    run_id : str, optional
        The full `.claude/plans/<slug>` directory path, unique across repos
        even when `run_slug` collides.
    session_id : str, optional
        Transcript ``sessionId`` or memory ``originSessionId``, where applicable.
    git_branch : str, optional
        Git branch of the containing repo, where determinable.
    extra : dict
        Axis-specific extras (round number, cwd, ...).
    """

    kind: str
    class_key: str
    text: str
    source_path: str
    timestamp: str
    run_slug: Optional[str] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    git_branch: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "kind": self.kind,
            "class_key": self.class_key,
            "text": self.text,
            "source_path": self.source_path,
            "timestamp": self.timestamp,
            "run_slug": self.run_slug,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "git_branch": self.git_branch,
        }
        d.update(self.extra)
        return d

    def session_unit(self) -> str:
        """The distinct session/run this record belongs to, for recurrence.

        `run_slug` alone is not unique across repos -- the same slug name
        recurs in sibling repos and in relocated worktrees under
        `Code/Archive/` -- so `run_id` (the full plan-dir path) is preferred
        whenever it is set.
        """
        return self.session_id or self.run_id or self.run_slug or self.source_path


# ---------------------------------------------------------------------------
# Review-file parser
# ---------------------------------------------------------------------------

_ROUND_HEADER_RE = re.compile(r"^#{1,6}\s*Round\s+\d+", re.IGNORECASE | re.MULTILINE)
# ``PASS (fix-ups)`` is a third verdict, not a decorated PASS: it routes a
# textual-only defect to a one-shot correction instead of a repair round, so a
# tally that folds it into PASS loses exactly the signal this measures. The
# alternation is ordered most-specific-first, and the word boundary sits inside
# the plain alternatives -- after ``)`` it would never match.
_VERDICT_RE = re.compile(
    r"^VERDICT:\s*(PASS\s*\(fix-ups\)|PASS\b|FAIL\b)",
    re.IGNORECASE | re.MULTILINE,
)


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$", re.MULTILINE)
_REQUIRED_FIXES_TITLE_RE = re.compile(r"required\s+fix", re.IGNORECASE)
# "Required fix-ups" is the PASS (fix-ups) list; it also matches the pattern above,
# so it is tested first.
_REQUIRED_FIXUPS_TITLE_RE = re.compile(r"required\s+fix-?ups?", re.IGNORECASE)
_NUMBERED_LINE_RE = re.compile(r"^(\d+)\.[ \t]+(.+?)\s*$", re.MULTILINE)


_FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def mask_fences(text: str) -> str:
    """Return `text` with the content of fenced code blocks replaced by spaces.

    Offsets, line breaks and the fence delimiter lines are preserved, so a match
    position in the masked text indexes the original. Reports quote logs whose
    lines start with ``#`` (``# command:``, ``# exit:``); scanned as-is those
    look like headings and would truncate the section that cites them. A fence
    left unclosed runs to the end of the text, as in CommonMark.
    """
    out: List[str] = []
    fence = ""
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if not fence:
            m = _FENCE_OPEN_RE.match(body)
            if m:
                fence = m.group(1)
            out.append(line)
            continue
        closing = body.strip()
        if closing and set(closing) == {fence[0]} and len(closing) >= len(fence):
            fence = ""
            out.append(line)
        else:
            out.append(re.sub(r"[^\r\n]", " ", line))
    return "".join(out)


def normalize_verdict(raw: str) -> str:
    """Canonicalize a matched verdict to ``PASS``, ``PASS (FIX-UPS)`` or ``FAIL``."""
    collapsed = " ".join(raw.split()).upper()
    return "PASS (FIX-UPS)" if collapsed.startswith("PASS") and "FIX-UPS" in collapsed else collapsed


@dataclass
class ReviewFix:
    """One numbered line, scoped to a `## Required fixes` (FAIL) or
    `## Required fix-ups` (PASS (fix-ups)) region."""

    round_index: int
    number: int
    text: str
    fixup: bool = False
    verdict: str = ""


@dataclass
class ReviewParse:
    """Result of parsing one review file's full text."""

    verdict_sequence: List[str]
    round_count: int
    fixes: List[ReviewFix]
    term_hits: Dict[str, int]


def split_review_rounds(text: str) -> List[str]:
    """Split a review file into round segments.

    A round header (``# Round N`` or a close variant) is one boundary
    signal, but it is not the *only* one the corpus uses: some review
    files mark a repair round with prose instead (``## Re-review (repair
    round 1)``), and some restate ``VERDICT:`` with no boundary heading at
    all. Every ``VERDICT:`` line is therefore also treated as the start of
    a new round segment -- this is the signal that cannot be silently
    missing, since a round without a verdict is not a round. Boundaries
    are the sorted union of round-header positions and verdict positions;
    a header with no verdict inside its segment still counts as a round
    (so "no more verdicts than round headers" holds even when the two
    signals disagree on where a boundary falls). Both are searched with
    fenced blocks masked: a quoted ``# Round 2`` or ``VERDICT: FAIL`` inside a
    fence is not a boundary, and no boundary falls inside a fence.
    """
    masked = mask_fences(text)
    header_starts = {m.start() for m in _ROUND_HEADER_RE.finditer(masked)}
    verdict_starts = {m.start() for m in _VERDICT_RE.finditer(masked)}
    boundaries = sorted(header_starts | verdict_starts)
    if not boundaries:
        return [text]
    if boundaries[0] != 0:
        boundaries.insert(0, 0)
    bounds = boundaries + [len(text)]
    return [
        text[bounds[i] : bounds[i + 1]]
        for i in range(len(bounds) - 1)
        if bounds[i] < bounds[i + 1]
    ]


def required_fixes_regions(segment: str) -> List[Tuple[bool, str]]:
    """Return ``(is_fixup, text)`` for the spans headed by a "Required fixes"
    or "Required fix-ups" heading (or a close variant), bounded by the next
    heading of any level or EOF."""
    masked = mask_fences(segment)
    headings = list(_HEADING_RE.finditer(masked))
    regions = []
    for i, h in enumerate(headings):
        title = h.group(2)
        is_fixup = bool(_REQUIRED_FIXUPS_TITLE_RE.search(title))
        if is_fixup or _REQUIRED_FIXES_TITLE_RE.search(title):
            start = h.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(segment)
            regions.append((is_fixup, segment[start:end]))
    return regions


def parse_review_text(text: str) -> ReviewParse:
    """Parse one review file's contents into its verdict sequence, scoped
    fix lines, and scoped convention-term hit counts."""
    segments = split_review_rounds(text)
    verdict_sequence: List[str] = []
    fixes: List[ReviewFix] = []
    term_hits: Dict[str, int] = {term: 0 for term in CONVENTION_TERMS}

    for round_index, segment in enumerate(segments, start=1):
        verdict_match = _VERDICT_RE.search(mask_fences(segment))
        segment_verdict = ""
        if verdict_match:
            segment_verdict = normalize_verdict(verdict_match.group(1))
            verdict_sequence.append(segment_verdict)

        for is_fixup, region in required_fixes_regions(segment):
            for num_match in _NUMBERED_LINE_RE.finditer(region):
                fixes.append(
                    ReviewFix(
                        round_index=round_index,
                        number=int(num_match.group(1)),
                        text=num_match.group(2).strip(),
                        fixup=is_fixup,
                        verdict=segment_verdict,
                    )
                )
            lowered = region.lower()
            for term in CONVENTION_TERMS:
                term_hits[term] += lowered.count(term.lower())

    return ReviewParse(verdict_sequence, len(segments), fixes, term_hits)


# ---------------------------------------------------------------------------
# Report-file parser
# ---------------------------------------------------------------------------

_RESULT_RE = re.compile(r"^RESULT:\s*(DONE|BLOCKED)\b", re.MULTILINE)
_FIXUPS_RE = re.compile(r"^FIXUPS:\s*(APPLIED|BLOCKED)\b", re.MULTILINE)
_STATUS_RE = re.compile(r"^STATUS:\s*(OK|FAIL)\b", re.MULTILINE)
_ADVISOR_RE = re.compile(r"^Advisor:\s*(.+)$", re.MULTILINE)
_TRIVIAL_DEVIATION_RE = re.compile(r"^(none|n/?a|-)\.?$", re.IGNORECASE)
_BLOCKED_LINE_RE = re.compile(r"^RESULT:\s*BLOCKED\b", re.MULTILINE)
_RESULT_LINE_RE = re.compile(r"^RESULT:\s*(DONE|BLOCKED)\b", re.MULTILINE)


@dataclass
class ReportParse:
    """Result of parsing one report file's full text."""

    result_tallies: Dict[str, int]
    fixups_tallies: Dict[str, int]
    status_tallies: Dict[str, int]
    advisor_lines: List[str]
    deviations: List[str]


def parse_report_text(text: str) -> ReportParse:
    """Parse one report file's final ``RESULT:`` line, ``FIXUPS:`` lines,
    ``STATUS:`` lines, ``Advisor:`` lines, and non-trivial deviation passages.

    A report grows by appended ``## Round N`` sections, each ending in its own
    completion line, so the file's result is the last ``RESULT:`` line in it
    (``result_tallies`` holds that one entry, or none); earlier rounds'
    results are superseded. ``FIXUPS:`` lines are counted apart.
    """
    masked = mask_fences(text)
    result_tallies: Dict[str, int] = {}
    result_matches = list(_RESULT_RE.finditer(masked))
    if result_matches:
        result_tallies[result_matches[-1].group(1)] = 1

    fixups_tallies: Dict[str, int] = {}
    for m in _FIXUPS_RE.finditer(masked):
        fixups_tallies[m.group(1)] = fixups_tallies.get(m.group(1), 0) + 1

    status_tallies: Dict[str, int] = {}
    for m in _STATUS_RE.finditer(text):
        status_tallies[m.group(1)] = status_tallies.get(m.group(1), 0) + 1

    advisor_lines = [m.group(1).strip() for m in _ADVISOR_RE.finditer(text)]

    deviations: List[str] = []
    headings = list(_HEADING_RE.finditer(masked))
    for i, h in enumerate(headings):
        if "deviation" not in h.group(2).lower():
            continue
        start = h.end()
        # The region ends at the next heading, or -- since a report's final
        # section has no heading after it -- at the trailing RESULT: line,
        # whichever comes first.
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        result_match = _RESULT_LINE_RE.search(masked, start)
        if result_match and result_match.start() < end:
            end = result_match.start()
        body = text[start:end].strip()
        if body and not _TRIVIAL_DEVIATION_RE.match(body):
            deviations.append(body)

    return ReportParse(
        result_tallies, fixups_tallies, status_tallies, advisor_lines, deviations
    )


def blocked_passage(text: str) -> str:
    """Return the paragraph immediately preceding a ``RESULT: BLOCKED``
    line (the last one, the file's result), which is where reports state
    the concrete blocker."""
    matches = list(_BLOCKED_LINE_RE.finditer(text))
    if not matches:
        return "RESULT: BLOCKED"
    end = matches[-1].start()
    context = text[max(0, end - 600) : end]
    paragraphs = [p.strip() for p in context.split("\n\n") if p.strip()]
    return paragraphs[-1] if paragraphs else "RESULT: BLOCKED"


# ---------------------------------------------------------------------------
# Transcript parser
# ---------------------------------------------------------------------------


def is_subagent_transcript(path: Path) -> bool:
    """True if `path` is under a `/subagents/` directory segment.

    Measured discriminator: `isSidechain` is always False in top-level
    files and does not identify subagent output; the path segment does.
    """
    return "/subagents/" in path.as_posix()


def iter_transcript_user_messages(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield genuine typed human messages from one transcript JSONL file.

    A record qualifies when ``type == "user"``, it is not ``isMeta``,
    ``message.content`` is a ``str`` (list content is a stored tool result,
    reusing the ``user`` role -- excluded), and the content does not start
    with ``"<"`` (slash-command / caveat wrapper markup) or
    ``"[Request interrupted"``.
    """
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "user" or rec.get("isMeta"):
                continue
            message = rec.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            if content.startswith("<") or content.startswith("[Request interrupted"):
                continue
            yield {
                "text": content,
                "session_id": rec.get("sessionId"),
                "git_branch": rec.get("gitBranch"),
                "timestamp": rec.get("timestamp"),
                "cwd": rec.get("cwd"),
            }


def is_correction_probe(text: str) -> bool:
    """True if `text` contains one of the measured correction-probe terms
    (again/don't/instead/never/do not/wrong/should have)."""
    lowered = text.lower()
    return any(probe in lowered for probe in _PROBE_WORDS)


# ---------------------------------------------------------------------------
# Memory-doc parser
# ---------------------------------------------------------------------------

_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
_STAR_RE = re.compile(r"(★{2,3})\s*(.*)$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse a lightweight YAML-ish frontmatter block.

    Only flat scalar keys and one level of nesting are supported -- the
    corpus never nests deeper than the ``metadata:`` block some docs wrap
    ``type:``/``originSessionId:``/``modified:`` in (others keep those keys
    top-level; both conventions coexist in the corpus).

    Returns
    -------
    (frontmatter, body) : tuple[dict, str]
        `frontmatter` is empty if `text` has no leading ``---`` block.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return {}, text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        return {}, text

    fm: Dict[str, Any] = {}
    nested_key: Optional[str] = None
    for line in lines[1:end_idx]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = _KEY_RE.match(line.strip())
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip().strip('"')
        if indent == 0:
            if value == "":
                fm[key] = {}
                nested_key = key
            else:
                fm[key] = value
                nested_key = None
        elif nested_key is not None and isinstance(fm.get(nested_key), dict):
            fm[nested_key][key] = value

    body = "\n".join(lines[end_idx + 1 :])
    return fm, body


def _frontmatter_value(fm: Dict[str, Any], key: str) -> Optional[str]:
    """Read `key` checking the top level first, then a nested `metadata:`
    block -- the corpus uses both conventions for the same keys."""
    value = fm.get(key)
    if isinstance(value, str):
        return value
    metadata = fm.get("metadata")
    if isinstance(metadata, dict):
        nested = metadata.get(key)
        if isinstance(nested, str):
            return nested
    return None


@dataclass
class MemoryParse:
    """Result of parsing one memory document."""

    doc_type: Optional[str]
    name: Optional[str]
    origin_session_id: Optional[str]
    modified: Optional[str]
    star_findings: List[Tuple[str, str]]
    wikilinks: List[str]


def extract_star_findings(body: str) -> List[Tuple[str, str]]:
    """Return ``(marker, finding_text)`` pairs for every ``★★``/``★★★``
    marked line in `body`."""
    return [(m.group(1), m.group(2).strip()) for m in _STAR_RE.finditer(body)]


def extract_wikilinks(body: str) -> List[str]:
    """Return the target names of every ``[[wiki-link]]`` in `body`."""
    return _WIKILINK_RE.findall(body)


def parse_memory_text(text: str) -> MemoryParse:
    """Parse one memory document: frontmatter `type:` (top-level or nested
    under `metadata:`), `★★★`/`★★` findings, and `[[wiki-link]]` targets."""
    fm, body = parse_frontmatter(text)
    return MemoryParse(
        doc_type=_frontmatter_value(fm, "type"),
        name=_frontmatter_value(fm, "name"),
        origin_session_id=_frontmatter_value(fm, "originSessionId"),
        modified=_frontmatter_value(fm, "modified"),
        star_findings=extract_star_findings(body),
        wikilinks=extract_wikilinks(body),
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _plan_dir_fingerprint(plan_dir: Path) -> Optional[str]:
    """SHA-256 over the sorted `tasks/*.md` contents, or None if there are none."""
    tasks_dir = plan_dir / "tasks"
    if not tasks_dir.is_dir():
        return None
    digest = hashlib.sha256()
    empty = True
    for task_file in sorted(tasks_dir.glob("*.md")):
        try:
            digest.update(task_file.read_bytes())
        except OSError:
            continue
        empty = False
    return None if empty else digest.hexdigest()


def iter_plan_dirs(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield every `.claude/plans/<slug>` directory under `roots`, deduplicated
    by content.

    Archived worktrees are *copies*, not history: measured on this corpus, 64 of
    138 run directories share a slug with another location and 39 of 40 sampled
    pairs are byte-identical. Yielding both would make one run look like two,
    which inflates every distinct-run recurrence count -- the single number this
    tool exists to produce. Deduplicate on the hash of the task artifacts, not on
    the slug: a same-slug pair whose contents genuinely differ is two real runs
    and both are kept.
    """
    seen_paths = set()
    seen_fingerprints = set()
    for root in roots:
        root = root.expanduser()
        if not root.is_dir():
            continue
        for plans_dir in root.glob("**/.claude/plans"):
            if not plans_dir.is_dir():
                continue
            for plan_dir in sorted(plans_dir.iterdir()):
                if not plan_dir.is_dir() or plan_dir in seen_paths:
                    continue
                seen_paths.add(plan_dir)
                fingerprint = _plan_dir_fingerprint(plan_dir)
                if fingerprint is not None:
                    if fingerprint in seen_fingerprints:
                        continue
                    seen_fingerprints.add(fingerprint)
                yield plan_dir


def iter_transcript_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield every `.jsonl` transcript file under `roots`."""
    seen = set()
    for root in roots:
        root = root.expanduser()
        if not root.is_dir():
            continue
        for path in root.glob("**/*.jsonl"):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def iter_memory_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield every `memory/*.md` document under `roots`."""
    seen = set()
    for root in roots:
        root = root.expanduser()
        if not root.is_dir():
            continue
        for path in root.glob("**/memory/*.md"):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def artifact_after(path: Path, since: Optional[date]) -> bool:
    """True if `path`'s mtime is on/after `since` (always True if `since`
    is None, or if the mtime cannot be read)."""
    if since is None:
        return True
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        return True
    return mtime >= since


def iso_mtime(path: Path) -> str:
    """The file's mtime as an ISO-8601 timestamp, used as provenance for
    markdown artifacts that carry no per-record timestamp of their own."""
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat()


@lru_cache(maxsize=None)
def git_branch_for(repo_root: Path) -> Optional[str]:
    """Best-effort current branch of the repo at `repo_root`, or None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None


def _repo_root_for(plan_dir: Path) -> Path:
    """The repo root above a `.claude/plans/<slug>` directory."""
    try:
        return plan_dir.parents[2]
    except IndexError:
        return plan_dir.parent


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _harvest_run_dirs(
    roots: List[Path], since: Optional[date]
) -> Tuple[List[Dict[str, Any]], List[Record], Dict[str, Dict[str, int]]]:
    index_entries: List[Dict[str, Any]] = []
    records: List[Record] = []
    conventions_totals: Dict[str, Dict[str, int]] = {
        term: {"count": 0, "files": 0} for term in CONVENTION_TERMS
    }

    for plan_dir in iter_plan_dirs(roots):
        tasks_dir = plan_dir / "tasks"
        if not tasks_dir.is_dir():
            continue
        slug = plan_dir.name
        repo_root = _repo_root_for(plan_dir)
        branch = git_branch_for(repo_root)

        task_files = sorted(tasks_dir.glob("*.md"))
        review_files = [f for f in task_files if fnmatch.fnmatch(f.name, "*review*.md")]
        report_files = [f for f in task_files if fnmatch.fnmatch(f.name, "*report*.md")]
        spec_files = [f for f in task_files if f not in review_files and f not in report_files]

        agent_types = set()
        review_levels: Dict[str, int] = {}
        for spec_file in spec_files:
            try:
                spec_text = spec_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            agent_match = re.search(r"^Agent:\s*(\S+)", spec_text, re.MULTILINE)
            if agent_match:
                agent_types.add(agent_match.group(1))
            review_match = re.search(r"^Review:\s*(\S+)", spec_text, re.MULTILINE)
            if review_match:
                level = review_match.group(1)
                review_levels[level] = review_levels.get(level, 0) + 1

        mtimes: List[str] = []
        verdict_tallies: Dict[str, int] = {}
        total_rounds = 0
        for review_file in review_files:
            if not artifact_after(review_file, since):
                continue
            try:
                text = review_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            timestamp = iso_mtime(review_file)
            mtimes.append(timestamp)
            parsed = parse_review_text(text)
            total_rounds += parsed.round_count
            for verdict in parsed.verdict_sequence:
                verdict_tallies[verdict] = verdict_tallies.get(verdict, 0) + 1
            for term, count in parsed.term_hits.items():
                if count:
                    conventions_totals[term]["count"] += count
                    conventions_totals[term]["files"] += 1
            for fix in parsed.fixes:
                records.append(
                    Record(
                        kind="review-fixup" if fix.fixup else "review-fix",
                        class_key=make_class_key(fix.text),
                        text=fix.text,
                        source_path=str(review_file),
                        timestamp=timestamp,
                        run_slug=slug,
                        run_id=str(plan_dir),
                        git_branch=branch,
                        extra={
                            "round": fix.round_index,
                            "number": fix.number,
                            "verdict_class": fix.verdict,
                            "verdict_sequence": parsed.verdict_sequence,
                        },
                    )
                )

        result_tallies: Dict[str, int] = {}
        fixups_tallies: Dict[str, int] = {}
        status_tallies: Dict[str, int] = {}
        advisor_line_count = 0
        deviation_count = 0
        no_result_reports = 0
        for report_file in report_files:
            if not artifact_after(report_file, since):
                continue
            try:
                text = report_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            timestamp = iso_mtime(report_file)
            mtimes.append(timestamp)
            parsed_report = parse_report_text(text)
            for key, count in parsed_report.result_tallies.items():
                result_tallies[key] = result_tallies.get(key, 0) + count
            if not parsed_report.result_tallies:
                no_result_reports += 1
            for key, count in parsed_report.fixups_tallies.items():
                fixups_tallies[key] = fixups_tallies.get(key, 0) + count
            for key, count in parsed_report.status_tallies.items():
                status_tallies[key] = status_tallies.get(key, 0) + count
            advisor_line_count += len(parsed_report.advisor_lines)
            for advisor_line in parsed_report.advisor_lines:
                records.append(
                    Record(
                        kind="report-advisor",
                        class_key=make_class_key(advisor_line),
                        text=advisor_line,
                        source_path=str(report_file),
                        timestamp=timestamp,
                        run_slug=slug,
                        run_id=str(plan_dir),
                        git_branch=branch,
                    )
                )
            deviation_count += len(parsed_report.deviations)
            for deviation in parsed_report.deviations:
                records.append(
                    Record(
                        kind="report-deviation",
                        class_key=make_class_key(deviation),
                        text=deviation,
                        source_path=str(report_file),
                        timestamp=timestamp,
                        run_slug=slug,
                        run_id=str(plan_dir),
                        git_branch=branch,
                    )
                )
            if "BLOCKED" in parsed_report.result_tallies:
                blocker_text = blocked_passage(text)
                records.append(
                    Record(
                        kind="report-blocked",
                        class_key=make_class_key(blocker_text),
                        text=blocker_text,
                        source_path=str(report_file),
                        timestamp=timestamp,
                        run_slug=slug,
                        run_id=str(plan_dir),
                        git_branch=branch,
                    )
                )

        index_entries.append(
            {
                "repo": str(repo_root),
                "slug": slug,
                "plan_dir": str(plan_dir),
                "git_branch": branch,
                "task_count": len(spec_files),
                "agent_types_used": sorted(agent_types),
                "review_levels": review_levels,
                "review_file_count": len(review_files),
                "report_file_count": len(report_files),
                "verdict_tallies": verdict_tallies,
                "total_rounds": total_rounds,
                "result_tallies": result_tallies,
                "no_result_reports": no_result_reports,
                "fixups_tallies": fixups_tallies,
                "status_tallies": status_tallies,
                "advisor_line_count": advisor_line_count,
                "deviation_count": deviation_count,
                "mtime_min": min(mtimes) if mtimes else None,
                "mtime_max": max(mtimes) if mtimes else None,
            }
        )

    return index_entries, records, conventions_totals


def _harvest_transcripts(roots: List[Path], since: Optional[date]) -> List[Record]:
    records: List[Record] = []
    for transcript_file in iter_transcript_files(roots):
        if is_subagent_transcript(transcript_file):
            continue
        if not artifact_after(transcript_file, since):
            continue
        for message in iter_transcript_user_messages(transcript_file):
            timestamp = message["timestamp"] or iso_mtime(transcript_file)
            base_extra = {"cwd": message["cwd"]}
            records.append(
                Record(
                    kind="user-message",
                    class_key=make_class_key(message["text"]),
                    text=message["text"],
                    source_path=str(transcript_file),
                    timestamp=timestamp,
                    session_id=message["session_id"],
                    git_branch=message["git_branch"],
                    extra=dict(base_extra),
                )
            )
            if is_correction_probe(message["text"]):
                records.append(
                    Record(
                        kind="user-correction",
                        class_key=make_class_key(message["text"]),
                        text=message["text"],
                        source_path=str(transcript_file),
                        timestamp=timestamp,
                        session_id=message["session_id"],
                        git_branch=message["git_branch"],
                        extra=dict(base_extra),
                    )
                )
    return records


def _harvest_memory(roots: List[Path], since: Optional[date]) -> List[Record]:
    records: List[Record] = []
    for memory_file in iter_memory_files(roots):
        if not artifact_after(memory_file, since):
            continue
        try:
            text = memory_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_memory_text(text)
        timestamp = parsed.modified or iso_mtime(memory_file)
        class_key_basis = parsed.name or text.strip()[:200]

        if parsed.doc_type == "feedback":
            records.append(
                Record(
                    kind="memory-feedback",
                    class_key=make_class_key(class_key_basis),
                    text=text.strip(),
                    source_path=str(memory_file),
                    timestamp=timestamp,
                    session_id=parsed.origin_session_id,
                    extra={"doc_type": parsed.doc_type},
                )
            )
        for marker, finding in parsed.star_findings:
            records.append(
                Record(
                    kind="memory-star-finding",
                    class_key=make_class_key(finding),
                    text=f"{marker} {finding}",
                    source_path=str(memory_file),
                    timestamp=timestamp,
                    session_id=parsed.origin_session_id,
                    extra={"doc_type": parsed.doc_type, "marker": marker},
                )
            )
        for link in parsed.wikilinks:
            records.append(
                Record(
                    kind="memory-wikilink",
                    class_key=make_class_key(link),
                    text=link,
                    source_path=str(memory_file),
                    timestamp=timestamp,
                    session_id=parsed.origin_session_id,
                    extra={"doc_type": parsed.doc_type},
                )
            )
    return records


def build_records(
    roots: List[Path], since: Optional[date]
) -> Tuple[List[Dict[str, Any]], List[Record], Dict[str, Dict[str, int]]]:
    """Walk `roots` and extract every record across the four parsers.

    Returns
    -------
    (index_entries, records, conventions_totals)
        `index_entries` is one dict per run directory. `records` is the
        flat list feeding every slice file and `recurrence.json`.
        `conventions_totals` is the per-term ``{"count", "files"}`` tally
        for `conventions.tsv`, scoped to Required-fixes regions only.
    """
    index_entries, records, conventions_totals = _harvest_run_dirs(roots, since)
    records.extend(_harvest_transcripts(roots, since))
    records.extend(_harvest_memory(roots, since))
    return index_entries, records, conventions_totals


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

_SLICE_KIND_MAP: Dict[str, Tuple[str, ...]] = {
    "review-fixes.md": ("review-fix",),
    "review-fixups.md": ("review-fixup",),
    "report-blocked.md": ("report-blocked",),
    "report-deviations.md": ("report-deviation",),
    "user-corrections.md": ("user-correction",),
    "memory-feedback.md": ("memory-feedback", "memory-star-finding", "memory-wikilink"),
}


def _format_record_md(rec: Record) -> str:
    provenance = [f"timestamp: {rec.timestamp}"]
    if rec.run_slug:
        provenance.append(f"slug: {rec.run_slug}")
    if rec.session_id:
        provenance.append(f"session: {rec.session_id}")
    if rec.git_branch:
        provenance.append(f"branch: {rec.git_branch}")
    header = f"- source: `{rec.source_path}` (" + ", ".join(provenance) + ")"
    return f"{header}\n\n  {rec.text}\n"


def write_index_jsonl(index_entries: List[Dict[str, Any]], out_dir: Path) -> None:
    """Write one JSON object per run directory to `index.jsonl`."""
    with (out_dir / "index.jsonl").open("w", encoding="utf-8") as fh:
        for entry in index_entries:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


def write_slices(records: List[Record], slices_dir: Path) -> None:
    """Write one markdown file per axis, each item printing its provenance."""
    slices_dir.mkdir(parents=True, exist_ok=True)
    for filename, kinds in _SLICE_KIND_MAP.items():
        kind_set = set(kinds)
        items = [r for r in records if r.kind in kind_set]
        title = filename[: -len(".md")].replace("-", " ").title()
        with (slices_dir / filename).open("w", encoding="utf-8") as fh:
            fh.write(f"# {title}\n\n")
            for rec in items:
                fh.write(_format_record_md(rec))
                fh.write("\n")


def write_conventions_tsv(conventions_totals: Dict[str, Dict[str, int]], slices_dir: Path) -> None:
    """Write the Required-fixes-scoped term-frequency table."""
    slices_dir.mkdir(parents=True, exist_ok=True)
    with (slices_dir / "conventions.tsv").open("w", encoding="utf-8") as fh:
        fh.write("term\tcount\tfiles\n")
        for term in CONVENTION_TERMS:
            totals = conventions_totals[term]
            fh.write(f"{term}\t{totals['count']}\t{totals['files']}\n")


def write_recurrence(records: List[Record], out_dir: Path) -> Dict[str, Dict[str, int]]:
    """Write `recurrence.json`: per record kind, per `class_key`, the count of
    distinct sessions/runs it appears in.

    Grouping by kind is load-bearing, not cosmetic. `user-message` is the
    unfiltered superset of `user-correction`, and its class keys are dominated
    by acknowledgements -- "continue" recurs across 56 runs. Pooling all kinds
    into one ranking buries every substantive finding under that noise, which
    is the one outcome this pipeline exists to prevent. Rank within a kind;
    never across kinds.
    """
    by_kind: Dict[str, Dict[str, set]] = {}
    for rec in records:
        by_kind.setdefault(rec.kind, {}).setdefault(rec.class_key, set()).add(
            rec.session_unit()
        )
    recurrence = {
        kind: {key: len(units) for key, units in by_key.items()}
        for kind, by_key in by_kind.items()
    }
    with (out_dir / "recurrence.json").open("w", encoding="utf-8") as fh:
        json.dump(recurrence, fh, indent=2, sort_keys=True)
    return recurrence


def write_summary(
    index_entries: List[Dict[str, Any]],
    records: List[Record],
    out_dir: Path,
    since: Optional[date],
) -> None:
    """Write the human-readable `summary.md`."""
    verdict_totals: Dict[str, int] = {}
    result_totals: Dict[str, int] = {}
    fixups_totals: Dict[str, int] = {}
    status_totals: Dict[str, int] = {}
    no_result_total = 0
    for entry in index_entries:
        no_result_total += entry.get("no_result_reports", 0)
        for key, count in entry["verdict_tallies"].items():
            verdict_totals[key] = verdict_totals.get(key, 0) + count
        for key, count in entry["result_tallies"].items():
            result_totals[key] = result_totals.get(key, 0) + count
        for key, count in entry.get("fixups_tallies", {}).items():
            fixups_totals[key] = fixups_totals.get(key, 0) + count
        for key, count in entry["status_tallies"].items():
            status_totals[key] = status_totals.get(key, 0) + count

    kind_counts: Dict[str, int] = {}
    for rec in records:
        kind_counts[rec.kind] = kind_counts.get(rec.kind, 0) + 1

    lines = ["# Diagnostics harvest summary", ""]
    if since is not None:
        lines.append(f"Filter: artifacts modified on or after {since.isoformat()}.")
        lines.append("")
    lines.append(f"Run directories indexed: {len(index_entries)}")
    lines.append(f"Verdict tallies (review files): {verdict_totals}")
    lines.append(f"Final RESULT per report file (last RESULT line in each): {result_totals}")
    lines.append(f"Report files with no RESULT line (incl. RESULT lines lost to an unclosed fence): {no_result_total}")
    lines.append(f"FIXUPS lines (report files): {fixups_totals}")
    lines.append(f"STATUS tallies (report files): {status_totals}")
    lines.append("")
    lines.append("## Extracted record counts")
    for kind in sorted(kind_counts):
        lines.append(f"- {kind}: {kind_counts[kind]}")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def harvest(roots: List[Path], out_dir: Path, since: Optional[date] = None) -> None:
    """Run the full extraction pipeline and write every output file.

    Parameters
    ----------
    roots : list[pathlib.Path]
        Directories to scan for run dirs, transcripts and memory docs.
    out_dir : pathlib.Path
        Destination directory; created if missing.
    since : datetime.date, optional
        Only consider artifacts (files) whose mtime is on/after this date.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    slices_dir = out_dir / "slices"
    index_entries, records, conventions_totals = build_records(roots, since)
    write_index_jsonl(index_entries, out_dir)
    write_slices(records, slices_dir)
    write_conventions_tsv(conventions_totals, slices_dir)
    write_recurrence(records, out_dir)
    write_summary(index_entries, records, out_dir, since)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="harvest.py",
        description=(
            "Extract structured, provenance-tagged findings from the gsAgents "
            "run corpus (review files, reports, transcripts, memory docs). "
            "Extraction only -- it never classifies what a finding means."
        ),
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        metavar="PATH",
        default=None,
        help="Directories to scan (default: ~/Code and ~/.claude/projects).",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help="Output directory (default: .claude/diagnostics/<today>/).",
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        default=None,
        help="Only consider artifacts modified on/after this date.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    roots = (
        [Path(r).expanduser() for r in args.roots]
        if args.roots
        else [r.expanduser() for r in DEFAULT_ROOTS]
    )
    out_dir = (
        Path(args.out).expanduser()
        if args.out
        else Path(".claude/diagnostics") / date.today().isoformat()
    )
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None

    harvest(roots, out_dir, since)
    print(f"wrote diagnostics to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
