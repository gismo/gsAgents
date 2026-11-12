#!/usr/bin/env python3
"""review_lint.py -- deterministic style checks for G+Smo diffs (no model involved).

Usage: review_lint.py [--base REF] [--nested-base optional/MODULE=REF]... [--all-lines]
                      [--no-clang-format] [--linters] [PATH ...]

``--base`` and ``--nested-base`` have the meaning they have for ``review_scope.sh``: the
files of the nested repository ``optional/MODULE`` are compared against the merge base of
REF and ``HEAD`` taken inside that repository. A ref that does not resolve is
``STATUS: FAIL`` with exit 2.

The file list and the added/changed line ranges come from ``review_scope.sh``. A finding is
emitted only when its line lies in a changed range, unless ``--all-lines`` is given (whole
files). File-level rules marked "new files" apply to status ``A`` only. With ``--all-lines``
and explicit PATHs the files under those paths are walked directly, so committed code can be
audited.

Output (stdout, TSV)::

    <path>:<line> TAB <RULE-ID> TAB <major|minor|note> TAB <message>
    SKIP TAB <tool> TAB <reason>
    STAT TAB <path> TAB added=<n> TAB comment=<n> TAB share=<pct>
    STAT TAB TOTAL TAB added=<n> TAB comment=<n> TAB share=<pct>
    STATUS: OK | STATUS: FINDINGS <n> | STATUS: FAIL <reason>

``<n>`` counts major and minor findings; notes are listed but never decide the status. A rule
may report some findings at a lower severity than its table entry (``ID-INTLOOP`` reports
``size_t`` loops as notes). Files with fewer than ``STAT_MIN_ADDED`` added lines get no
per-file ``STAT`` row but still count in the total. ``FMT-CLANG`` yields at most one note per
file, summarising the differing ranges. ``DX-TAG`` flags a backslash command on an added line
only when the same command is absent from the removed line it was edited from; commands
inside ``\\code``/``\\verbatim`` blocks and formulas are never flagged.

Exit: 0 no major or minor findings, 1 otherwise, 2 error.

Environment: GISMO_ROOT (set by review_lint.sh), GISMO_BUILD_DIR (optional, for clang-tidy),
CLANG_FORMAT / CLANG_TIDY / CPPCHECK (optional binary overrides).

Comment detection is a small lexer (:func:`lex`) that tracks ``//``, ``/* */``, raw string
literals, string and character literals across lines; it is not a C++ parser.
"""
import argparse
import difflib
import os
import re
import shlex
import shutil
import subprocess
import sys
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

# ---------------------------------------------------------------------------------------
# Tunable tables
# ---------------------------------------------------------------------------------------

#: Process references (CM-NARR): task, plan, spec and review bookkeeping. They are wrong in
#: a comment and wrong in a user-facing string. Matched case-insensitively against comment
#: text and string-literal contents. One regex fragment per entry. "task 4 of 8" is a
#: progress message, not bookkeeping.
NARRATION_PROCESS_PATTERNS: List[str] = [
    r"\btasks?\s+\d+\b(?!\s+of\s+\d)",
    r"\bsteps?\s+\d+\s+of\s+the\s+plan\b",
    r"\.claude/plans",
    r"\bper\s+(?:the\s+)?(?:spec|plan|ticket)\b",
    r"\bacceptance\s+criteri",
    r"\breview(?:er)?\s+points?\b",
    r"\bTODO\(review\)",
    r"\bas\s+requested\s+by\s+(?:the\s+)?(?:reviewer|user|maintainer|author)\b",
    # "addresses" alone is dominated by memory addresses; require a review-like object.
    r"\baddress(?:es|ed)\s+(?:the\s+)?(?:review|reviewer|feedback|#)",
]

#: Process references matched against comments only: a run-time message may count its own
#: rounds ("Round 1: refine uniformly").
NARRATION_COMMENT_PROCESS_PATTERNS: List[str] = [
    r"(?-i:\bRound\s+\d+\b)",
]

#: Narration of the change to the code (CM-NARR), matched against comments only. A message
#: printed at run time ("removed the duplicate knots") and an algorithm's own steps
#: ("residual changed from the previous iteration", "replaced by its transpose") use the
#: same words, so each entry needs a marker of code history: a subject that is the code
#: ("it previously returned"), a retirement wording ("no longer needed"), or an object that
#: is code ("removed the old loop", "replaced by the helper below").
NARRATION_CHANGE_PATTERNS: List[str] = [
    # "previously computed ..." describes program state; a sentence that opens with
    # "previously" followed by anything else tells the history of the code.
    r"(?:^\s*|[.;:!?]\s+)previously\b(?!\s+(?:\w+ed|set|built|found|made|run|seen|given|chosen|written|read)\b)",
    r"\b(?:it|this|that|we|they|which)\s+previously\b",
    r"\b(?:was|were)\s+previously\s+(?:removed|replaced|renamed|refactored|rewritten|reworked)\b",
    # "the step no longer changes" describes an algorithm; only retirement wording narrates.
    r"\bno\s+longer\s+(?:used|needed|required|necessary|supported)\b",
    # "is used to ..." / "used to denote ..." state a purpose; only a subject followed by
    # "used to" ("it used to return") narrates history.
    r"\b(?:it|this|that|they|we|which|there)\s+used\s+to\b",
    r"\b(?:was|were|has\s+been|have\s+been)\s+(?:removed|replaced|renamed|refactored|rewritten"
    r"|reworked)\s+(?:in\s+favou?r\s+of|because|since|to\s+(?:avoid|fix|reduce|simplify|speed"
    r"|make|allow|enable))\b",
    r"\b(?:has|have)\s+been\s+(?:refactored|rewritten|reworked)\b",
    r"\bremoved\s+the\s+(?:(?:old|former|obsolete|legacy|previous)\s+(?:code|loop|branch"
    r"|implementation|version|helper|workaround|check|call|function|method|logic|approach)"
    r"|workaround|hack|dead\s+code|unused\s+(?:code|variable|function|helper|include"
    r"|parameter|argument|member))\b",
    r"(?<!\bis\s)(?<!\bare\s)(?<!\bbe\s)(?<!\bbeen\s)(?<!\bcould\sbe\s)"
    r"\breplaced\s+(?:by|with)\s+(?:the\s+)?(?:new|helper|function|call|version|method|class"
    r"|implementation|code|loop|below|above)\b",
    # "the old version of the basis" and "old behaviour of gsBSpline" name data or a
    # supported option, so only the code itself counts.
    r"\b(?:old|former|legacy)\s+(?:implementation|code)\b",
    r"\bas\s+requested\b(?!\s+(?:from|by|in|for|at|with)\b)",
    r"\baddress(?:es|ed)\s+(?:the\s+)?(?:comment|point|issue|concern)\b",
    # "patch" is a geometry term in G+Smo ("this patch"), so only code-change nouns count;
    # "this change of variables" is mathematics, so "this change" needs a verb.
    r"\bthis\s+(?:fix(?![-\s]?points?\b)|commit|(?-i:PR))\b",
    r"\bthis\s+change\s+(?:fixes|avoids|removes|adds|introduces|replaces|reverts)\b",
    # A changelog entry opens the comment with a past-tense verb and its object. "Fixed-size",
    # "Changed entries are ...", "Removed elements are ..." and "Updated Lagrangian" describe
    # the program, so the object must be a determiner or a word that marks code ("unused",
    # "redundant") and a hyphen right after the verb excludes compounds. "a" and "to" are
    # too common after most of these verbs ("Fixed a point on the curve", "Changed a to b",
    # "Changed to the reference configuration"), so they count only after the verb where
    # they open a changelog entry: "Added a null check", "Refactored to avoid duplication".
    r"^[\s*/!<]*(?:Added|Fixed|Changed|Refactored|Reverted|Renamed)\s+(?:an|the|this|that)\b(?!-)",
    r"^[\s*/!<]*Added\s+a\b(?!-)(?!\s+to\b)",
    r"^[\s*/!<]*Refactored\s+to\b(?!-)",
    r"^[\s*/!<]*(?:Removed|Replaced)\s+(?:a|an|this|that|unused|redundant|obsolete|unnecessary"
    r"|the\s+(?:redundant|unused|obsolete|unnecessary|old|former|previous|loop|check|include"
    r"|workaround|hack))\b",
    r"^[\s*/!<]*Now\s+(?:uses|returns|calls|takes)\b",
    r"\bwas\s+(?:changed|replaced|removed|renamed)\s+(?:to|by|with|in)\b",
]

#: Capitalised words that are not emphasis (CM-EMPH). Words with fewer than four distinct
#: letters (``YYYYMMDD``, ``VVRRPP`` version templates) and words that also occur in the
#: file's code are skipped as well.
EMPH_ALLOWLIST: Set[str] = {
    "NURBS", "GISMO", "TODO", "FIXME", "NOTE", "XXX", "CMAKE", "OPENMP", "MATLAB",
    "PARAVIEW", "EIGEN", "TRILINOS", "PETSC", "HYPRE", "CUDA", "LAPACK", "UMFPACK",
    "SUPERLU", "PARDISO", "CHOLMOD", "MUMPS", "GMRES", "MINRES", "BICGSTAB", "HTTPS",
    "ASCII", "NDEBUG", "DOXYGEN", "LATEX", "BSPLINE", "THBSPLINE", "HBSPLINE", "STL",
    "SPARSE", "MPI", "OPENCASCADE", "GMSH", "UNICODE", "TRUE", "FALSE", "UTF", "HDF",
    "ISOGEOMETRIC", "KNOTS", "NVIDIA", "METIS",
}

#: Doxygen commands that must use the ``@`` form (DX-TAG).
DX_COMMANDS: frozenset = frozenset(
    "brief param return returns tparam ingroup sa see note warning todo file class "
    "struct def ref cite code endcode copydoc throws pre post defgroup addtogroup name "
    "details author date deprecated bug remark remarks internal verbatim endverbatim".split())

#: Doxygen commands that open a block of literal text, mapped to the command that closes it.
DX_BLOCK_END: Dict[str, str] = {"code": "endcode", "verbatim": "endverbatim"}

#: Constructs newer than C++14 (ID-CXX17), matched against code with comments and strings
#: blanked. Applies under src/, examples/ and unittests/ of the root repository only.
CXX17_PATTERNS: List[Tuple[str, str]] = [
    (r"\bstd::(?:optional|variant|any|string_view|filesystem)\b", "C++17 library facility"),
    (r"\bif\s+constexpr\b", "if constexpr"),
    (r"\bauto\s*(?:&{1,2})?\s*\[", "structured binding"),
    (r"\[\[\s*(?:nodiscard|maybe_unused)\s*\]\]", "C++17 attribute"),
]
CXX17_DIRS: Tuple[str, ...] = ("src/", "examples/", "unittests/")

#: Loop-variable types that must be ``index_t`` (ID-INTLOOP). Only the classic three-clause
#: header matches: the variable is followed by an initialiser (``=``, ``(``, ``{``) or ``;``,
#: never by the ``:`` of a range-based for. ``short_t`` (dimensions, small counts) does not
#: match.
INTLOOP_RE = re.compile(
    r"\bfor\s*\(\s*(?:const\s+)?(unsigned\s+int|unsigned|int|std::size_t|size_t)\s+\w+\s*[=({;]")

#: Loop-variable types of :data:`INTLOOP_RE` that are reported as a note instead of the
#: rule's default severity: ``size_t`` is the right type for a std container, and a line-based
#: check cannot see the container's type.
INTLOOP_NOTE_TYPES: frozenset = frozenset({"size_t", "std::size_t"})

#: A file with fewer added lines than this gets no per-file comment-share ``STAT`` row; the
#: share of a handful of lines is not meaningful. Such files still count in the total.
STAT_MIN_ADDED = 30

#: Longest list of differing ranges spelled out in a ``FMT-CLANG`` message.
FMT_MAX_RANGES = 10

#: Leading comment lines searched for the licence header of a new file (HD-FILE/MPL/AUTHOR).
HEADER_SCAN_CAP = 120

#: Extensions treated as C++ sources (all rules) and as scripts (whitespace rules only).
CXX_EXT = (".h", ".hpp", ".cpp", ".cxx", ".cc")
CXX_SRC_EXT = (".cpp", ".cxx", ".cc")
WS_ONLY_NAMES = ("CMakeLists.txt",)
WS_ONLY_EXT = (".py", ".cmake")

SEVERITY: Dict[str, str] = {
    "WS-TAB": "minor", "WS-TRAIL": "minor", "WS-CRLF": "minor",
    "CM-NARR": "major", "CM-LINEREF": "minor", "CM-EMPH": "note", "CM-DEAD": "minor",
    "HD-FILE": "major", "HD-MPL": "major", "HD-AUTHOR": "major", "HD-PRAGMA": "major",
    "HD-HPPTAIL": "major", "NS-CLOSE": "minor", "DX-TAG": "minor",
    "ID-COUT": "major", "ID-MOVE": "note", "ID-INTLOOP": "major", "ID-CXX17": "major",
    "EX-NAME": "major", "EX-RETURN": "minor", "EX-INCLUDE": "major", "EX-GISMOH": "minor",
    "EX-GETVALUES": "minor", "UT-NAME": "major", "UT-SUITE": "major", "UT-INCLUDE": "major",
    "FMT-CLANG": "note", "EXT-TIDY": "note", "EXT-CPPCHECK": "note",
}

PROCESS_RE = re.compile("|".join("(?:%s)" % p for p in NARRATION_PROCESS_PATTERNS), re.I)
COMMENT_NARRATION_RE = re.compile(
    "|".join("(?:%s)" % p for p in NARRATION_PROCESS_PATTERNS + NARRATION_COMMENT_PROCESS_PATTERNS
             + NARRATION_CHANGE_PATTERNS), re.I)
LINEREF_RE = re.compile(
    r"\b[\w./-]+\.(?:h|hpp|cpp|cxx|cc|py|cmake)\s*:\s*\d+|\blines?\s+\d+", re.I)
EMPH_RE = re.compile(r"\b[A-Z]{5,}\b(?!\s*\()")
DX_TOKEN_RE = re.compile(r"(?<!\\)([\\@])(f[$\[\]{}]|[A-Za-z]+)")
DEAD_RES = [
    re.compile(r"^(?:return|break|continue|throw|delete|goto)\b[^;]*;$"),
    re.compile(r"^[A-Za-z_][\w:.\->\[\]<>]*\(.*\)\s*;$"),
    re.compile(r"^[A-Za-z_][\w:.\->\[\]<>*&]*(?:\s+[*&]?[A-Za-z_][\w:.\->\[\]]*)?"
               r"\s*(?:=|\+=|-=|\*=|/=)\s*[^=;].*;$"),
    re.compile(r"^(?:const\s+)?(?:[\w:]+<[^;]*>|real_t|index_t|int|unsigned|size_t|bool|auto"
               r"|gs\w+|std::\w+)[&*]?\s+[&*]?[A-Za-z_]\w*(?:\[[^\]]*\])?\s*;$"),
]
DEAD_BRACE_RES = [
    re.compile(r"^[{}]$"),
    re.compile(r"^}\s*else(?:\s+if\s*\(.*\))?\s*{$"),
    re.compile(r"^(?:if|for|while|switch|else|do|try|catch|namespace|struct|class)\b.*{$"),
    re.compile(r"^.*\)\s*{$"),
]


# ---------------------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------------------

class Seg(NamedTuple):
    """A comment segment on one line.

    :param start: first column of the comment text (after the opening marker)
    :param end: one past the last column of the comment text
    :param doxy: whether the enclosing comment is a doxygen comment
    :param kind: ``"line"`` for ``//``-style, ``"block"`` for ``/* */``-style
    :param ends: whether a block comment is closed on this line
    """
    start: int
    end: int
    doxy: bool
    kind: str
    ends: bool


class LineInfo:
    """Lexical view of one source line.

    :ivar code: the line with comments blanked and string/char literal contents blanked
        (length preserved, quotes kept)
    :ivar segs: comment segments on this line
    :ivar strs: ``(start, end)`` spans of string-literal contents
    :ivar in_raw_end: whether the line ends inside a raw string literal
    :ivar in_lit_end: whether the line ends inside a string or character literal continued
        by a trailing backslash
    """
    __slots__ = ("code", "segs", "strs", "in_raw_end", "in_lit_end")

    def __init__(self, code: str, segs: List[Seg], strs: List[Tuple[int, int]],
                 in_raw_end: bool, in_lit_end: bool = False) -> None:
        self.code = code
        self.segs = segs
        self.strs = strs
        self.in_raw_end = in_raw_end
        self.in_lit_end = in_lit_end

    @property
    def in_literal_end(self) -> bool:
        """Whether the line ends inside any multi-line literal (raw or backslash-continued)."""
        return self.in_raw_end or self.in_lit_end


def _numeric_separator(line: str, i: int) -> bool:
    """Return True when the apostrophe at ``line[i]`` is a C++14 digit separator."""
    j = i - 1
    while j >= 0 and (line[j].isalnum() or line[j] == "_"):
        j -= 1
    return j < i - 1 and line[j + 1].isdigit()


def lex(lines: Sequence[str]) -> List[LineInfo]:
    """Classify every character of a C++ file as code, comment or literal.

    Handles ``//`` (with backslash continuation), ``/* */``, ``///``, ``/** */``, string
    and character literals with escapes (also continued over lines by a trailing backslash),
    raw string literals and digit separators.

    :param lines: source lines without line terminators
    :returns: one :class:`LineInfo` per line
    """
    infos: List[LineInfo] = []
    mode = "none"  # none | block | raw
    block_doxy = False
    raw_close = ""
    lit_quote = '"'  # delimiter of the string or character literal open in mode "lit"
    cont = False   # previous line was a // comment ending in a backslash
    cont_doxy = False
    for line in lines:
        n = len(line)
        code = list(line)
        segs: List[Seg] = []
        strs: List[Tuple[int, int]] = []
        i = 0
        if mode == "block":
            j = line.find("*/")
            if j < 0:
                segs.append(Seg(0, n, block_doxy, "block", False))
                infos.append(LineInfo(" " * n, segs, strs, False))
                continue
            segs.append(Seg(0, j, block_doxy, "block", True))
            code[0:j + 2] = " " * (j + 2)
            mode = "none"
            i = j + 2
        elif mode == "raw":
            j = line.find(raw_close)
            if j < 0:
                strs.append((0, n))
                infos.append(LineInfo(" " * n, segs, strs, True))
                continue
            strs.append((0, j))
            code[0:j + len(raw_close) - 1] = " " * (j + len(raw_close) - 1)
            mode = "none"
            i = j + len(raw_close)
        elif mode == "lit":
            j, spliced = _scan_literal(line, 0, lit_quote)
            if lit_quote == '"':
                strs.append((0, j))
            if j >= n:
                mode = "lit" if spliced else "none"
                infos.append(LineInfo(" " * n, segs, strs, False, spliced))
                continue
            code[0:j] = " " * j
            mode = "none"
            i = j + 1
        elif cont:
            segs.append(Seg(0, n, cont_doxy, "line", False))
            cont = n > 0 and line[-1] == "\\"
            infos.append(LineInfo(" " * n, segs, strs, False))
            continue
        while i < n:
            c = line[i]
            two = line[i:i + 2]
            if two == "//":
                doxy = (line.startswith("///", i) and not line.startswith("////", i)) \
                    or line.startswith("//!", i)
                segs.append(Seg(i + 2, n, doxy, "line", False))
                code[i:n] = " " * (n - i)
                cont = line[-1] == "\\"
                cont_doxy = doxy
                i = n
            elif two == "/*":
                doxy = (line.startswith("/**", i) and not line.startswith("/**/", i)
                        and not line.startswith("/***", i)) or line.startswith("/*!", i)
                j = line.find("*/", i + 2)
                if j < 0:
                    segs.append(Seg(i + 2, n, doxy, "block", False))
                    code[i:n] = " " * (n - i)
                    mode = "block"
                    block_doxy = doxy
                    i = n
                else:
                    segs.append(Seg(i + 2, j, doxy, "block", True))
                    code[i:j + 2] = " " * (j + 2 - i)
                    i = j + 2
            elif c == '"':
                k = i - 1
                while k >= 0 and (line[k].isalnum() or line[k] == "_"):
                    k -= 1
                prefix = line[k + 1:i]
                if prefix in ("R", "u8R", "uR", "UR", "LR"):
                    p = line.find("(", i + 1)
                    if p > 0 and p - i - 1 <= 16:
                        close = ")" + line[i + 1:p] + '"'
                        j = line.find(close, p + 1)
                        if j < 0:
                            strs.append((i + 1, n))
                            code[i + 1:n] = " " * (n - i - 1)
                            mode = "raw"
                            raw_close = close
                            i = n
                        else:
                            strs.append((i + 1, j))
                            code[i + 1:j] = " " * (j - i - 1)
                            i = j + len(close)
                        continue
                j, spliced = _scan_literal(line, i + 1, '"')
                strs.append((i + 1, j))
                code[i + 1:j] = " " * (j - i - 1)
                if spliced:
                    mode, lit_quote = "lit", '"'
                i = j + 1
            elif c == "'":
                if _numeric_separator(line, i):
                    i += 1
                    continue
                j, spliced = _scan_literal(line, i + 1, "'")
                code[i + 1:j] = " " * (j - i - 1)
                if spliced:
                    mode, lit_quote = "lit", "'"
                i = j + 1
            else:
                i += 1
        infos.append(LineInfo("".join(code), segs, strs, mode == "raw", mode == "lit"))
    return infos


def _scan_literal(line: str, start: int, quote: str) -> Tuple[int, bool]:
    """Find the end of a string or character literal whose contents begin at ``start``.

    :param line: the source line
    :param start: column of the first character after the opening quote (or of the line)
    :param quote: the closing delimiter, ``"`` or ``'``
    :returns: ``(column of the closing quote or len(line), whether a trailing backslash
        continues the literal on the next line)``
    """
    n = len(line)
    j = start
    while j < n and line[j] != quote:
        if line[j] == "\\" and j == n - 1:
            return n, True
        j += 2 if line[j] == "\\" else 1
    return min(j, n), False


#: The text in front of the ``{`` of a lambda body: introducer, parameters, specifiers and
#: trailing return type (``[&](int k) mutable -> int``).
LAMBDA_HEAD_RE = re.compile(
    r"\[[^\[\]{};]*\]\s*(?:\([^{};]*\))?\s*(?:(?:mutable|noexcept|constexpr)\s*)*"
    r"(?:->\s*[^{};]+?)?\s*$")


def main_own_code(infos: Sequence[LineInfo]) -> Dict[int, str]:
    """Return the code of ``main``'s own statements, by 1-based line number.

    The body of a top-level ``main(...)`` is scanned with lambda bodies blanked out, so a
    ``return`` inside a lambda is not mistaken for one of ``main``. Lines outside ``main``
    are absent from the result.
    """
    own: Dict[int, str] = {}
    depth = 0
    state = "seek"  # seek -> sig (saw "main(") -> body
    lambdas: List[bool] = []  # one entry per open brace of the body: is it a lambda body?
    in_lambda = 0
    stmt = ""  # code since the last ';', '{' or '}' of the body
    for ln, info in enumerate(infos, 1):
        buf: List[str] = []
        for ch_i, ch in enumerate(info.code):
            if state == "seek" and depth == 0 and ch == "(" \
                    and re.search(r"\bmain\s*$", info.code[:ch_i]):
                state = "sig"
            elif ch == "{":
                depth += 1
                if state == "sig" and depth == 1:
                    state = "body"
                elif state == "body":
                    is_lambda = LAMBDA_HEAD_RE.search(stmt) is not None
                    lambdas.append(is_lambda)
                    in_lambda += is_lambda
                    stmt = ""
            elif ch == "}":
                depth -= 1
                if state == "body" and depth == 0:
                    state = "seek"
                elif state == "body" and lambdas:
                    # The closing brace of a lambda belongs to the lambda, not to main.
                    buf.append(" " if in_lambda else ch)
                    in_lambda -= lambdas.pop()
                    stmt = ""
                    continue
            elif ch == ";" and state == "sig" and depth == 0:
                state = "seek"
            if state == "body":
                if ch in ";{}":
                    stmt = ""
                else:
                    stmt += ch
            buf.append(ch if state == "body" and not in_lambda else " ")
        if state == "body" or any(c != " " for c in buf):
            own[ln] = "".join(buf)
        if state == "body":
            stmt += " "
    return own


def dx_hits(lines: Sequence[str], infos: Sequence[LineInfo]) -> List[Tuple[int, int, str]]:
    """Find backslash doxygen commands inside doxygen comments.

    Text between formula delimiters (``\\f$ ... \\f$``, ``\\f[ ... \\f]``,
    ``\\f{env}{ ... \\f}``) and between ``code``/``endcode`` or ``verbatim``/``endverbatim``
    (written with ``\\`` or ``@``) is literal and skipped, as are all commands outside
    doxygen comments. The block commands themselves are reported like any other command.

    :param lines: source lines without terminators
    :param infos: output of :func:`lex` for ``lines``
    :returns: ``(line index, column of the backslash, command name)`` triples
    """
    hits: List[Tuple[int, int, str]] = []
    inline = display = False
    block = ""  # name of the end command that closes the literal block we are in
    for idx, (line, info) in enumerate(zip(lines, infos)):
        doxy_segs = [s for s in info.segs if s.doxy]
        if not doxy_segs:
            inline = display = False
            block = ""
            continue
        for seg in doxy_segs:
            for m in DX_TOKEN_RE.finditer(line, seg.start, seg.end):
                lead, name = m.group(1), m.group(2)
                glued = m.start(1) > 0 and (line[m.start(1) - 1].isalnum() or line[m.start(1) - 1] == "_")
                if block:
                    if name == block:
                        block = ""
                        if lead == "\\" and not glued:
                            hits.append((idx, m.start(1), name))
                    continue
                if name == "f$":
                    inline = not inline
                elif name in ("f[", "f{"):
                    display = True
                elif name in ("f]", "f}"):
                    display = False
                elif not inline and not display and name in DX_COMMANDS and not glued:
                    if lead == "\\":
                        hits.append((idx, m.start(1), name))
                    if name in DX_BLOCK_END:
                        block = DX_BLOCK_END[name]
            if seg.kind == "block" and seg.ends:
                inline = display = False
                block = ""
    return hits


# ---------------------------------------------------------------------------------------
# Per-file checks
# ---------------------------------------------------------------------------------------

class Finding(NamedTuple):
    """One lint finding.

    :param severity: overrides the rule's entry in :data:`SEVERITY` when set
    """
    path: str
    line: int
    rule: str
    message: str
    severity: Optional[str] = None


def severity_of(f: Finding) -> str:
    """Return the effective severity of a finding (per-finding override, else per rule)."""
    return f.severity or SEVERITY[f.rule]


def _comment_text(line: str, info: LineInfo) -> str:
    return " ".join(line[s.start:s.end] for s in info.segs)


#: Words that occur in statements and therefore do not count towards prose (CM-DEAD).
STATEMENT_WORDS: frozenset = frozenset(
    "return break continue throw delete goto const unsigned signed int long short char bool "
    "double float void auto static extern inline new sizeof typename template struct class "
    "enum union namespace using typedef else case default do while for if switch try catch "
    "true false nullptr this public private protected virtual explicit mutable volatile "
    "register constexpr operator".split())

#: English function words; two or more in one comment make it a sentence (CM-DEAD).
PROSE_WORDS: frozenset = frozenset(
    "is are was were be been the an of and or with without to in on at by from as it its "
    "this that these those which where when then than not no we our their has have can "
    "will would should may must also only each every both either".split())


def _looks_like_prose(t: str) -> bool:
    """Return whether a comment body ending in ``;`` is a sentence rather than a statement.

    A sentence contains a run of three plain lowercase words separated by single spaces
    (words that are not C++ keywords and carry no call, member or scope syntax), or two
    English function words. String-literal contents are ignored.
    """
    t = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', '""', t)
    toks = list(re.finditer(r"\S+", t))
    run, prev_end, stop = 0, -2, 0
    for m in toks:
        w = m.group(0)
        plain = re.fullmatch(r"[a-z]{2,}", w) is not None and w not in STATEMENT_WORDS
        run = run + 1 if plain and m.start() - prev_end == 1 else (1 if plain else 0)
        prev_end = m.end()
        if run >= 3:
            return True
        if w.strip(",.:;()") in PROSE_WORDS:
            stop += 1
    return stop >= 2


def _is_dead_code(text: str) -> bool:
    """Decide whether a ``//`` comment body reads like a C++ statement."""
    t = text.strip()
    if t.endswith(";"):
        return not _looks_like_prose(t) and any(r.match(t) for r in DEAD_RES)
    if t.endswith("{") or t.endswith("}"):
        return any(r.match(t) for r in DEAD_BRACE_RES)
    return False


def lint_text(path: str, data: str, status: str, changed: Optional[Set[int]],
              sibling_hpp: bool, removed: Optional[Dict[int, Set[str]]] = None
              ) -> Tuple[List[Finding], int, int]:
    """Run every text-level rule on one file.

    :param path: path relative to the G+Smo root (decides which rules apply)
    :param data: file contents decoded as latin-1 (byte-transparent)
    :param status: scope status; ``"A"`` enables the new-file rules
    :param changed: 1-based line numbers to report on, or ``None`` for all lines
    :param sibling_hpp: whether a ``<stem>.hpp`` exists beside a new ``.h``
    :param removed: for each added line, the backslash doxygen commands on the lines its hunk
        removed (see :func:`removed_dx_commands`); DX-TAG skips a command found there, since
        the tag predates the edit. ``None`` flags every backslash command on a checked line
    :returns: ``(findings, added line count, comment line count)`` over the checked lines
    """
    raw_lines = data.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()
    lines = [l[:-1] if l.endswith("\r") else l for l in raw_lines]
    name = os.path.basename(path)
    out: List[Finding] = []
    is_cxx = path.endswith(CXX_EXT)
    ws_only = name in WS_ONLY_NAMES or path.endswith(WS_ONLY_EXT)
    if not (is_cxx or ws_only):
        return out, 0, 0
    total = len(lines)
    sel = set(range(1, total + 1)) if changed is None else {n for n in changed if 1 <= n <= total}

    def add(ln: int, rule: str, msg: str, severity: Optional[str] = None) -> None:
        out.append(Finding(path, ln, rule, msg, severity))

    crlf = [i + 1 for i, l in enumerate(raw_lines) if l.endswith("\r") and (i + 1) in sel]
    if crlf:
        add(crlf[0], "WS-CRLF", "CRLF line ending (%d line%s)" % (len(crlf), "s" if len(crlf) > 1 else ""))
    for ln in sorted(sel):
        line = lines[ln - 1]
        stripped = line.lstrip(" \t")
        if "\t" in line[:len(line) - len(stripped)]:
            add(ln, "WS-TAB", "tab in leading indentation")
        if line != line.rstrip(" \t"):
            add(ln, "WS-TRAIL", "trailing whitespace")
    added = len(sel)
    if ws_only:
        comment_lines = 0
        if path.endswith(".py"):
            comment_lines = sum(1 for n in sel if lines[n - 1].lstrip().startswith("#"))
        return out, added, comment_lines

    infos = lex(lines)
    comment_lines = sum(1 for n in sel if infos[n - 1].segs and not infos[n - 1].code.strip())
    code_words: Set[str] = set()
    for info in infos:
        code_words.update(re.findall(r"\b[A-Z]{5,}\b", info.code))

    parts = path.split("/")
    dirs = parts[:-1]
    main_code = main_own_code(infos) if "examples" in dirs else {}
    in_examples = "examples" in dirs
    is_src = path.endswith(CXX_SRC_EXT)
    new = status == "A"
    stem = name.rsplit(".", 1)[0]

    for ln in sorted(sel):
        line, info = lines[ln - 1], infos[ln - 1]
        code = info.code
        ctext = _comment_text(line, info)
        if ctext or info.strs:
            texts = [(ctext, COMMENT_NARRATION_RE)] + [(line[a:b], PROCESS_RE) for a, b in info.strs]
            for t, rx in texts:
                m = rx.search(t)
                if m:
                    add(ln, "CM-NARR", "change narration or process reference: '%s'" % m.group(0))
                    break
        if ctext:
            m = LINEREF_RE.search(ctext)
            if m:
                add(ln, "CM-LINEREF", "comment cites a source line number: '%s'" % m.group(0))
            for m in EMPH_RE.finditer(ctext):
                w = m.group(0)
                if w in EMPH_ALLOWLIST or w in code_words or len(set(w)) < 4:
                    continue
                add(ln, "CM-EMPH", "capitalised emphasis: '%s'" % w)
                break
        if not code.strip():
            for s in info.segs:
                if s.kind == "line" and not s.doxy and _is_dead_code(line[s.start:s.end]):
                    add(ln, "CM-DEAD", "commented-out code")
                    break
        if re.match(r"^\s*}\s*(?://|/\*)", line) and code.strip() == "}" \
                and re.search(r"\bgismo\b(?!::)", ctext) and line.rstrip() != "} // namespace gismo":
            add(ln, "NS-CLOSE", "namespace gismo must close with exactly '} // namespace gismo'")
        if re.search(r"\bstd::(?:cout|cerr)\b|\bprintf\s*\(", code):
            add(ln, "ID-COUT", "std::cout/std::cerr/printf; use gsInfo/gsWarn/gsDebug")
        if re.search(r"\bstd::move\s*\(", code):
            add(ln, "ID-MOVE", "std::move: acceptable only on non-G+Smo values")
        m = INTLOOP_RE.search(code)
        if m:
            ltype = re.sub(r"\s+", " ", m.group(1))
            if ltype in INTLOOP_NOTE_TYPES:
                add(ln, "ID-INTLOOP", "loop variable of type '%s': right for a std container, "
                    "index_t for a matrix, basis or DoF index" % ltype, "note")
            else:
                add(ln, "ID-INTLOOP", "loop variable of type '%s'; use index_t" % ltype)
        if path.startswith(CXX17_DIRS):
            for pat, what in CXX17_PATTERNS:
                m = re.search(pat, code)
                if m:
                    add(ln, "ID-CXX17", "%s ('%s'); C++14 is the ceiling" % (what, m.group(0).strip()))
                    break
        if re.search(r"\breturn\s+(?:0|1|-\s*1)\s*;", main_code.get(ln, "")):
            add(ln, "EX-RETURN", "main() must return EXIT_SUCCESS/EXIT_FAILURE")
        if in_examples and is_src and code.lstrip().startswith("#") \
                and re.match(r'\s*#\s*include\s*["<][^">]*\.cpp[">]', line):
            add(ln, "EX-INCLUDE", "example includes another .cpp")
        if re.search(r"\.getValues\s*\(\s*argc\b", code):
            prev = " ".join(infos[k].code for k in range(max(0, ln - 3), ln))
            if not re.search(r"\btry\b", prev):
                add(ln, "EX-GETVALUES", "getValues(argc, ...) must be inside try")

    for ln, col, tag in dx_hits(lines, infos):
        if (ln + 1) in sel and not (removed and tag in removed.get(ln + 1, ())):
            add(ln + 1, "DX-TAG", "use '@%s' instead of '\\%s'" % (tag, tag))

    # --- file-level rules, reported on line 1 ---
    if 1 in sel or total == 0:
        if name.endswith("_test.cpp") and dirs and dirs[-1] == "unittests":
            if not re.search(r"\bSUITE\s*\(\s*%s\s*\)" % re.escape(stem), "\n".join(i.code for i in infos)):
                add(1, "UT-SUITE", "no SUITE(%s)" % stem)
        if new:
            _new_file_rules(path, name, stem, dirs, lines, infos, sibling_hpp, add)
    return out, added, comment_lines


def removed_dx_commands(repo_dir: str, ref: str, path: str) -> Dict[int, Set[str]]:
    """Map each added line to the backslash doxygen commands of the removed line it replaces.

    Runs ``git diff -U0`` and, per hunk, pairs every added line with the removed line it was
    edited from: positionally when the hunk removes and adds the same number of lines, else
    greedily by text similarity (at least :data:`DX_PAIR_RATIO`). The commands of
    :data:`DX_COMMANDS` written as ``\\cmd`` on that removed line are the value. DX-TAG uses
    this to tell a tag the change introduced from one that was already there while other
    text on the line was edited; an added line without a counterpart gets no entry, so a
    tag it carries is reported even when another line of the hunk had the same command. A
    rename is not followed (``path`` alone is diffed), so a renamed file reports as all added.

    :param repo_dir: working directory of the git repository holding ``path``
    :param ref: revision the working tree is compared with
    :param path: file path relative to ``repo_dir``
    :returns: ``{new line number: commands}``; empty when git fails or nothing was removed
    """
    try:
        r = _run(["git", "-c", "core.quotepath=off", "diff", "--no-color", "-U0", ref, "--", path],
                repo_dir)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if r.returncode != 0:
        return {}
    out: Dict[int, Set[str]] = {}
    start = 0
    old: List[str] = []
    new: List[str] = []

    def flush() -> None:
        for k, j in _pair_lines(old, new):
            cmds = {m.group(2) for m in DX_TOKEN_RE.finditer(old[j])
                    if m.group(1) == "\\" and m.group(2) in DX_COMMANDS}
            if cmds:
                out[start + k] = cmds

    for l in r.stdout.split("\n"):
        h = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", l)
        if h:
            flush()
            start = int(h.group(1))
            old, new = [], []
        elif l.startswith("-") and not l.startswith("---"):
            old.append(l[1:])
        elif l.startswith("+") and not l.startswith("+++"):
            new.append(l[1:])
    flush()
    return out


#: Smallest :class:`difflib.SequenceMatcher` ratio at which an added line counts as the edit
#: of a removed line when the hunk removes and adds different numbers of lines.
DX_PAIR_RATIO = 0.6


def _pair_lines(old: List[str], new: List[str]) -> List[Tuple[int, int]]:
    """Pair the added lines of a hunk with the removed lines they were edited from.

    :param old: removed lines of one ``-U0`` hunk
    :param new: added lines of the same hunk
    :returns: ``(index into new, index into old)`` pairs, each line used at most once
    """
    if len(old) == len(new):
        return list(zip(range(len(new)), range(len(old))))
    cand = sorted(((difflib.SequenceMatcher(None, o.strip(), n.strip()).ratio(), k, j)
                   for k, n in enumerate(new) for j, o in enumerate(old)), reverse=True)
    used_new: Set[int] = set()
    used_old: Set[int] = set()
    pairs: List[Tuple[int, int]] = []
    for ratio, k, j in cand:
        if ratio < DX_PAIR_RATIO:
            break
        if k not in used_new and j not in used_old:
            used_new.add(k)
            used_old.add(j)
            pairs.append((k, j))
    return pairs


def _new_file_rules(path: str, name: str, stem: str, dirs: List[str], lines: List[str],
                    infos: List[LineInfo], sibling_hpp: bool, add) -> None:
    """Apply the rules that only concern newly created files."""
    if name == "gsConfig.h" or name.endswith("ConfigExt.h"):
        return
    if any(re.search(r"generated|do\s+not\s+edit", l, re.I) for l in lines[:5]):
        return
    # The leading comment block(s): everything before the first code or preprocessor line.
    end = next((k for k, i in enumerate(infos) if i.code.strip()), len(lines))
    block = lines[:min(end, HEADER_SCAN_CAP)]
    m = None
    for l in block:
        m = re.search(r"/\*\*\s*@file\s+(\S+)", l)
        if m:
            break
    if not m:
        add(1, "HD-FILE", "no '/** @file %s' in the leading comment block" % name)
    elif m.group(1) != name:
        add(1, "HD-FILE", "@file names '%s', file is '%s'" % (m.group(1), name))
    top = "\n".join(block)
    if not re.search(r"Mozilla Public|\bMPL\b", top):
        add(1, "HD-MPL", "header lacks the Mozilla Public License text")
    am = re.search(r"Author\(s\):[ \t]*(.*)", top)
    if not am or not re.sub(r"\*/", "", am.group(1)).strip():
        add(1, "HD-AUTHOR", "no 'Author(s):' with a name")
    if name.endswith(".h"):
        if not any(re.match(r"\s*#\s*pragma\s+once\b", i.code) for i in infos):
            add(1, "HD-PRAGMA", "new header without '#pragma once'")
        if sibling_hpp:
            pat = re.compile(r"#\s*include\s+GISMO_HPP_HEADER\(\s*%s\.hpp\s*\)" % re.escape(stem))
            ok = False
            for k, l in enumerate(lines):
                if pat.search(l):
                    window = " ".join(lines[max(0, k - 3):k])
                    ok = bool(re.search(r"#\s*ifndef\s+GISMO_BUILD_LIB\b", window))
                    break
            if not ok:
                add(1, "HD-HPPTAIL", "sibling %s.hpp not included via GISMO_HPP_HEADER inside "
                    "#ifndef GISMO_BUILD_LIB" % stem)
    if name.endswith(CXX_SRC_EXT):
        if dirs == ["examples"] and not name.endswith("_example.cpp"):
            add(1, "EX-NAME", "core example must be named *_example.cpp")
        if "examples" in dirs and not re.search(r"#\s*include\s*<gismo\.h>", "\n".join(lines)):
            add(1, "EX-GISMOH", "new example without #include <gismo.h>")
        if dirs and dirs[-1] == "unittests" and name != "main.cpp" and not name.endswith("_test.cpp"):
            add(1, "UT-NAME", "unit test file must be named *_test.cpp")
        if name.endswith("_test.cpp") and dirs and dirs[-1] == "unittests" \
                and not re.search(r'#\s*include\s*"gismo_unittest\.h"', "\n".join(lines)):
            add(1, "UT-INCLUDE", 'new test without #include "gismo_unittest.h"')


# ---------------------------------------------------------------------------------------
# External tools
# ---------------------------------------------------------------------------------------

def _which(env_var: str, binary: str) -> Optional[List[str]]:
    """Locate a tool; ``$ENV_VAR`` may hold a full command line (e.g. a wrapper script)."""
    cand = os.environ.get(env_var)
    if cand:
        argv = shlex.split(cand)
        return argv if argv and shutil.which(argv[0]) else None
    found = shutil.which(binary)
    return [found] if found else None


def _run(cmd: List[str], cwd: str, stdin: Optional[str] = None, timeout: int = 600):
    return subprocess.run(cmd, cwd=cwd, input=stdin, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True,
                          encoding="latin-1", timeout=timeout)


def clang_format_findings(binary: List[str], root: str, path: str, data: str,
                          changed: Optional[Set[int]]) -> Tuple[List[Finding], Optional[str]]:
    """Report that ``clang-format --lines`` would alter the changed ranges.

    A hunk whose old and new lines are all comments or blank is ignored: clang-format
    reflows comments and ASCII tables that are laid out by hand. The remaining hunks are
    summarised in a single note per file, located at the first of them.

    :returns: zero or one finding, and an error string if clang-format failed
    """
    cmd = binary + ["--style=file", "--assume-filename=" + os.path.join(root, path)]
    if changed is not None:
        for a, b in _ranges(changed):
            cmd.append("--lines=%d:%d" % (a, b))
    try:
        r = _run(cmd, root, stdin=data)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], str(e)
    if r.returncode != 0:
        return [], (r.stderr.strip().splitlines() or ["exit %d" % r.returncode])[0]
    old, new = data.split("\n"), r.stdout.split("\n")
    def prose_only(infos: List[LineInfo], lo: int, hi: int) -> bool:
        return all(not infos[k].code.strip() for k in range(lo, hi))

    old_infos, new_infos = lex(old), lex(new)
    hunks: List[Tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal" or (prose_only(old_infos, i1, i2) and prose_only(new_infos, j1, j2)):
            continue
        first = max(i1 + 1, 1)
        hunks.append((first, max(i2, first)))
    if not hunks:
        return [], None
    shown = ", ".join(str(a) if a == b else "%d-%d" % (a, b) for a, b in hunks[:FMT_MAX_RANGES])
    if len(hunks) > FMT_MAX_RANGES:
        shown += ", ..."
    msg = "%d range%s differ%s from .clang-format: %s" % (
        len(hunks), "" if len(hunks) == 1 else "s", "s" if len(hunks) == 1 else "", shown)
    return [Finding(path, hunks[0][0], "FMT-CLANG", msg)], None


def _ranges(lines: Iterable[int]) -> List[Tuple[int, int]]:
    """Collapse line numbers into inclusive ``(start, end)`` runs."""
    runs: List[Tuple[int, int]] = []
    for n in sorted(lines):
        if runs and n == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    return runs


def external_findings(kind: str, binary: List[str], root: str, build_dir: str, path: str,
                      changed: Optional[Set[int]]) -> Tuple[List[Finding], Optional[str]]:
    """Run clang-tidy or cppcheck on one file and keep diagnostics on changed lines."""
    abspath = os.path.join(root, path)
    if kind == "tidy":
        cmd = binary + ["-p", build_dir, "--quiet", abspath]
        rx = re.compile(r"^(.+?):(\d+):\d+: (?:warning|error): (.*?)(?: \[([^\]]+)\])?$")
        rule = "EXT-TIDY"
    else:
        cmd = binary + ["--enable=warning,performance,portability", "--quiet",
                        "--template={file}:{line}:{id}:{message}", abspath]
        rx = re.compile(r"^(.+?):(\d+):([^:]+):(.*)$")
        rule = "EXT-CPPCHECK"
    try:
        r = _run(cmd, root)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], str(e)
    out: List[Finding] = []
    for l in (r.stdout + "\n" + r.stderr).splitlines():
        m = rx.match(l)
        if not m:
            continue
        ln = int(m.group(2))
        if changed is not None and ln not in changed:
            continue
        if os.path.realpath(m.group(1)) != os.path.realpath(abspath):
            continue
        if kind == "tidy":
            msg = "%s [%s]" % (m.group(3), m.group(4) or "-")
        else:
            msg = "%s [%s]" % (m.group(4).strip(), m.group(3))
        out.append(Finding(path, ln, rule, msg))
    return out, None


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------

def fail(reason: str) -> None:
    sys.stderr.write("review_lint: %s\n" % reason)
    print("STATUS: FAIL %s" % reason)
    sys.exit(2)


def run_scope(args: List[str], env: Dict[str, str], quiet: bool = False) -> List[str]:
    """Run review_scope.sh and return its stdout lines without the STATUS line."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_scope.sh")
    r = subprocess.run(["bash", script] + args, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
    if r.returncode != 0:
        fail("review_scope failed: " + (r.stdout.strip().splitlines() or ["?"])[-1])
    if r.stderr and not quiet:
        sys.stderr.write(r.stderr)
    return [l for l in r.stdout.splitlines() if l and not l.startswith("STATUS:")]


def parse_ranges(lines: Iterable[str]) -> Dict[str, Set[int]]:
    out: Dict[str, Set[int]] = {}
    for l in lines:
        path, rng = l.split("\t")
        a, b = rng.split("-")
        out.setdefault(path, set()).update(range(int(a), int(b) + 1))
    return out


def walk_paths(root: str, paths: List[str]) -> List[str]:
    """Enumerate lintable files under explicit paths (root-relative result)."""
    exts = CXX_EXT + WS_ONLY_EXT
    found: List[str] = []
    for p in paths:
        ap = os.path.realpath(p)
        if os.path.isfile(ap):
            found.append(os.path.relpath(ap, root))
            continue
        for d, subs, files in os.walk(ap):
            subs[:] = [s for s in subs if s not in ("external", ".git", ".claude") and not s.startswith("build")]
            for f in files:
                if f.endswith(exts) or f in WS_ONLY_NAMES:
                    found.append(os.path.relpath(os.path.join(d, f), root))
    return sorted(set(found))


def run(argv: Optional[List[str]] = None) -> int:
    """Parse the arguments, lint the selected files and print the report; see the module docstring."""
    ap = argparse.ArgumentParser(description="Deterministic style checks on a G+Smo diff.")
    ap.add_argument("--base")
    ap.add_argument("--nested-base", action="append", default=[], metavar="MODULE=REF")
    ap.add_argument("--all-lines", action="store_true")
    ap.add_argument("--no-clang-format", action="store_true")
    ap.add_argument("--linters", action="store_true")
    ap.add_argument("paths", nargs="*")
    ns = ap.parse_args(argv)

    root = os.environ.get("GISMO_ROOT", "")
    if not os.path.isdir(root):
        fail("GISMO_ROOT not set (run through review_lint.sh)")
    root = os.path.realpath(root)
    env = dict(os.environ, GISMO_ROOT=root)
    scope_args: List[str] = (["--base", ns.base] if ns.base else [])
    nested_refs: Dict[str, str] = {}
    for spec in ns.nested_base:
        scope_args += ["--nested-base", spec]
        mod, _, nref = spec.partition("=")
        nested_refs[os.path.normpath(mod)] = nref
    scope_args += ns.paths

    status: Dict[str, str] = {}
    repo_of: Dict[str, str] = {}
    for l in run_scope(scope_args, env):
        repo, st, p = l.split("\t")
        status[p] = st
        repo_of[p] = repo
    ranges: Optional[Dict[str, Set[int]]] = None
    if ns.all_lines and ns.paths:
        files = walk_paths(root, ns.paths)
    else:
        files = sorted(p for p, st in status.items() if st != "D")
        if not ns.all_lines:
            ranges = parse_ranges(run_scope(["--lines"] + scope_args, env, quiet=True))

    cf_bin: Optional[List[str]] = None
    skips: List[Tuple[str, str]] = []
    if ns.no_clang_format:
        skips.append(("clang-format", "disabled by --no-clang-format"))
    elif not os.path.isfile(os.path.join(root, ".clang-format")):
        skips.append(("clang-format", "no .clang-format in the tree"))
    else:
        cf_bin = _which("CLANG_FORMAT", "clang-format")
        if not cf_bin:
            skips.append(("clang-format", "binary not found"))
    tidy_bin = cppcheck_bin = None
    build_dir = os.environ.get("GISMO_BUILD_DIR", "")
    if ns.linters:
        tidy_bin = _which("CLANG_TIDY", "clang-tidy")
        if not tidy_bin:
            skips.append(("clang-tidy", "binary not found"))
        elif not os.path.isfile(os.path.join(root, ".clang-tidy")):
            skips.append(("clang-tidy", "no .clang-tidy in the tree")); tidy_bin = None
        elif not os.path.isfile(os.path.join(build_dir, "compile_commands.json")):
            skips.append(("clang-tidy", "no compile_commands.json in the build dir")); tidy_bin = None
        cppcheck_bin = _which("CPPCHECK", "cppcheck")
        if not cppcheck_bin:
            skips.append(("cppcheck", "binary not found"))

    findings: List[Finding] = []
    stats: List[Tuple[str, int, int]] = []
    tool_errors: Dict[str, str] = {}
    for path in files:
        full = os.path.join(root, path)
        try:
            with open(full, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if b"\0" in raw:
            continue
        data = raw.decode("latin-1")
        changed = None if ranges is None else ranges.get(path, set())
        if changed is not None and not changed:
            continue
        st = status.get(path, "M")
        hpp = os.path.exists(os.path.join(os.path.dirname(full), os.path.basename(path).rsplit(".", 1)[0] + ".hpp"))
        removed = None
        if changed is not None and st != "A" and path.endswith(CXX_EXT):
            repo = repo_of.get(path, ".")
            nested = repo != "."
            ref = "HEAD"
            base_ref = nested_refs.get(repo) if nested else ns.base
            if base_ref:
                mb = _run(["git", "merge-base", base_ref, "HEAD"],
                          os.path.join(root, repo) if nested else root)
                ref = mb.stdout.strip() if mb.returncode == 0 and mb.stdout.strip() else "HEAD"
            removed = removed_dx_commands(os.path.join(root, repo) if nested else root, ref,
                                          path[len(repo) + 1:] if nested else path)
        fnd, added, com = lint_text(path, data, st, changed, hpp, removed)
        findings.extend(fnd)
        if path.endswith(CXX_EXT + (".py",)):
            stats.append((path, added, com))
        if path.endswith(CXX_EXT):
            if cf_bin:
                f, err = clang_format_findings(cf_bin, root, path, data, changed)
                findings.extend(f)
                if err:
                    tool_errors.setdefault("clang-format", err)
            if tidy_bin and path.endswith(CXX_SRC_EXT):
                f, err = external_findings("tidy", tidy_bin, root, build_dir, path, changed)
                findings.extend(f)
                if err:
                    tool_errors.setdefault("clang-tidy", err)
            if cppcheck_bin:
                f, err = external_findings("cppcheck", cppcheck_bin, root, build_dir, path, changed)
                findings.extend(f)
                if err:
                    tool_errors.setdefault("cppcheck", err)
    for tool, err in tool_errors.items():
        skips.append((tool, "failed: " + err))

    findings.sort(key=lambda f: (f.path, f.line, f.rule))
    seen: Set[Tuple[str, int, str]] = set()
    # Notes are printed but do not decide the status: a gate that bounces work on a
    # note would reject, e.g., a legitimate std::move of a standard-library value.
    blocking = 0
    for f in findings:
        key = (f.path, f.line, f.rule)
        if key in seen and f.rule != "DX-TAG":
            continue
        seen.add(key)
        sev = severity_of(f)
        if sev != "note":
            blocking += 1
        print("%s:%d\t%s\t%s\t%s" % (f.path, f.line, f.rule, sev, f.message.replace("\t", " ")))
    for tool, reason in skips:
        print("SKIP\t%s\t%s" % (tool, reason))
    ta = tc = 0
    for path, added, com in stats:
        ta += added
        tc += com
        if added >= STAT_MIN_ADDED:
            print("STAT\t%s\tadded=%d\tcomment=%d\tshare=%.1f" % (path, added, com, 100.0 * com / added))
    print("STAT\tTOTAL\tadded=%d\tcomment=%d\tshare=%.1f" % (ta, tc, 100.0 * tc / ta if ta else 0.0))
    if blocking:
        print("STATUS: FINDINGS %d" % blocking)
        return 1
    print("STATUS: OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Run :func:`run`; an unexpected exception ends in ``STATUS: FAIL`` with exit code 2.

    Exit code 1 is reserved for findings, so a crash must not reach the caller as one.
    """
    try:
        return run(argv)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("review_lint: unexpected %s: %s\n" % (type(e).__name__, e))
        print("STATUS: FAIL internal error: %s: %s" % (type(e).__name__, e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
