# G+Smo conventions

The single statement of what G+Smo code looks like. Writers (`gismo:implementer`,
`gismo:example-writer`, `gismo:test-writer`, `gismo:doc-writer`) follow it; reviewers
(`gismo:style-checker`, `gismo:task-reviewer`) check against it. A rule that is not written
here is not a finding.

## How to read a rule

Every rule has an ID, a severity and a checker.

- **Severity.** `major`: must be fixed before merge. `minor`: should be fixed; cheap.
  `note`: reported for the author's judgement, never counted against the change.
- **Checker.** `script`: decided by `scripts/review_lint.sh`, with no model involved. `script + style`: the script checks that the thing is present, the style checker that it is right.
  `style`: needs reading, done by `gismo:style-checker`. `review`: needs understanding of
  behaviour, done by `gismo:task-reviewer`.
- **Scope.** A rule applies to lines the change added or modified. Older code in a touched
  file is not reported, however it looks: a review is about the change, and mixing
  unrelated reformatting into a diff makes it harder to read. Rules marked *new files*
  apply only to files the change creates.

The rules are strict and context-free wherever that is possible, so that a script can
decide them and two runs give the same answer. Where the existing tree disagrees with a
rule, the rule wins for new code; the tree is brought in line by `scripts/tree_cleanup.sh`,
not by individual changes.

Language level: **C++14** is the ceiling for `src/`, `examples/` and `unittests/`, because
that is what the project's CI compiles. `optional/` modules set their own standard and are
not checked.

## 1. Whitespace and layout

| ID | Sev | Checker | Rule |
|---|---|---|---|
| WS-TAB | minor | script | Indent with 4 spaces. No tab characters in indentation. |
| WS-TRAIL | minor | script | No trailing whitespace. |
| WS-CRLF | minor | script | LF line endings. |
| FMT-BRACE | minor | style | Allman braces: the opening brace of a class, function, namespace or control statement sits on its own line. |
| NS-CLOSE | minor | script | `namespace gismo` is closed with exactly `} // namespace gismo`; its contents are not indented. |
| FMT-CLANG | note | script | Where the tree has a `.clang-format` and the tool is installed, changed lines match it. |

## 2. File structure

| ID | Sev | Checker | Rule |
|---|---|---|---|
| HD-FILE | major | script + style | *New files.* The file opens with `/** @file <basename>` followed by an `@brief` line. |
| HD-MPL | major | script + style | *New files.* The header block carries the MPL 2.0 notice, word for word as in `src/gsCore/gsFunction.h`. |
| HD-AUTHOR | major | script + style | *New files.* `Author(s):` names a person: the output of `git config user.name`. Never blank, never copied from the file used as a template, never an AI attribution. |
| HD-PRAGMA | major | script | *New files.* A `.h` file uses `#pragma once`. |
| HD-SPLIT | major | style | A class template is declared in `gsFoo.h`, defined in `gsFoo.hpp`, and instantiated in `gsFoo_.cpp` with `CLASS_TEMPLATE_INST`. A non-template free function is declared `GISMO_EXPORT` in the `.h` and defined in a `.cpp` (the library builds with hidden visibility, so an unexported symbol does not link). |
| HD-HPPTAIL | major | script | *New files.* A `.h` with a `.hpp` ends, after the namespace, with `#include GISMO_HPP_HEADER(gsFoo.hpp)` inside `#ifndef GISMO_BUILD_LIB`. |
| HD-SELF | major | review | A header compiles when it is the first include of a translation unit. `/gismo:syntax-check` on the header is the test. |
| HD-INCL | minor | style | Library headers are included as `<gsModule/gsFile.h>`. Include order is not prescribed; do not reorder existing includes. |

## 3. Naming

| ID | Sev | Checker | Rule |
|---|---|---|---|
| NM-CLASS | major | style | Classes are `gsCamelCase`. Exempt: expression types (`grad_expr`), types in `internal::`, small local structs. |
| NM-MEMBER | major | style | Data members carry the `m_` prefix. |
| NM-METHOD | minor | style | Methods and free functions are `camelCase`. The `_into` suffix marks a variant that writes to an output argument (`eval_into`). |
| NM-TYPEDEF | minor | style | The usual aliases keep their usual names: `Base`, `Ptr`, `uPtr`, `Scalar`. |
| NM-ONE | major | style | One concept has one name within a change: the same argument is not `c` in one signature and `comp` in the next, the same quantity is not `localCount` here and `patchSize` there, and two booleans do not express nearly the same condition. Argument order for the same pair of arguments is the same everywhere. |
| NM-VERB | minor | style | A helper that throws is named `ensure*`; `check*` returns a result. Follow whichever prefix the file already uses for the same behaviour. |
| NM-CLASH | major | review | A new name in `namespace gismo` does not collide with an existing one. |

## 4. Idioms

| ID | Sev | Checker | Rule |
|---|---|---|---|
| ID-TYPES | major | style | Floating-point quantities are `real_t`, never `double` or `float`, so the library still builds with other coefficient types. |
| ID-INTLOOP | major | script | Loop counters, sizes and anything that indexes a matrix, a basis or a DoF are `index_t`. `int`, `unsigned` and `size_t` in those roles are findings. `int` is right for `argc`, return codes and third-party APIs that ask for it. |
| ID-COUT | major | script | Output goes through `gsInfo`, `gsWarn` and `gsDebug`, never `std::cout`, `std::cerr` or `printf`. |
| ID-MOVE | major | style | Ownership of a G+Smo object (matrix, basis, geometry, `uPtr`) is transferred with `give(x)`, not `std::move(x)`. `std::move` on a plain standard-library value is fine. |
| ID-CXX17 | major | script | No C++17 or later in `src/`, `examples/`, `unittests/`. |
| ID-GUARD | major | review | `GISMO_ENSURE` validates input and state at construction, setup and API entry: it survives a Release build. `GISMO_ASSERT` states an invariant inside a per-element or per-quadrature-point loop: it costs nothing in Release and checks nothing there. A guard that protects against wrong results or out-of-bounds access and sits in a hot loop should be hoisted out of the loop, not turned into an `ENSURE`. Neither macro may throw inside an OpenMP parallel region. |
| ID-INIT | major | review | Every data member has a value after every constructor, including the default and copy constructors; prefer a default member initialiser. |
| ID-STREAM | minor | style | Code that changes stream formatting (`std::scientific`, `setprecision`) restores it. |

## 5. Comments and documentation

A comment is written for someone reading the file who never saw the change that produced
it. What changed and why belongs in the commit message and the pull request.

| ID | Sev | Checker | Rule |
|---|---|---|---|
| CM-NARR | major | script | No narration of the change and no process references, in comments or in string literals (an option description is user-facing text): "previously", "removed the", "replaced by", task or step numbers, "per the spec", review rounds, paths into `.claude/`. |
| CM-LINEREF | minor | script | A comment does not cite a line number in a source file; the number is wrong after the next edit. Name the function instead. |
| CM-DEAD | minor | script | No commented-out code. |
| CM-EMPH | note | script | No emphasis by capital letters in comments. |
| CM-REPEAT | minor | style | A rationale is stated once, where it applies, not repeated at each use. A contract (what the function does, requires and returns) is kept apart from the reasoning behind the design. |
| CM-VOLUME | note | script + style | The share of comment lines among added lines is reported per file. The number is never a finding by itself: theory-heavy solver code is meant to be documented. It is a prompt to look for CM-REPEAT and CM-NARR. |
| DX-TAG | minor | script | Doxygen commands use the `@` form: `@brief`, `@param`, `@return`, `@tparam`, `@ingroup`. Formula delimiters stay `\f$ … \f$`. |
| DX-PUBLIC | major | style | Every new public class, method, free function and typedef has a doxygen block. A one-line `@brief` is enough for a trivial getter. |
| DX-TRUE | major | review | Documentation states what the code does: option names match the names registered in the code, return values and failure behaviour are described for every branch, counts and cost claims are correct, and nothing advertises a feature that the change removed. A doxygen sentence that is false is a defect of the same weight as a wrong line of code, because callers program against it. |
| DX-CLAIM | major | review | A comment does not assert a measurement that nobody made ("converges at order 2", "twice as fast") unless the number is reproduced by an example or test that the comment names. |

## 6. Examples

| ID | Sev | Checker | Rule |
|---|---|---|---|
| EX-NAME | major | script | *New files.* In core `examples/` a file is `<topic>_example.cpp`. In an optional module it follows that module's existing scheme. |
| EX-GISMOH | minor | script | *New files.* An example includes `<gismo.h>` and uses `using namespace gismo;`. |
| EX-CMD | major | style | Options are declared as local variables with defaults and registered with `gsCmdLine` (`addInt`, `addReal`, `addString`, `addSwitch`). The description of each option and the file's header comment say what the code does. |
| EX-GETVALUES | minor | script | Parsing is `try { cmd.getValues(argc,argv); } catch (int rv) { return rv; }`. |
| EX-RETURN | minor | script | `main` returns `EXIT_SUCCESS` or `EXIT_FAILURE`. |
| EX-DEFAULT | major | review | With no arguments the example runs to completion in seconds, so it serves as a smoke test. Verified by running it when the review builds; otherwise marked UNVERIFIED. |
| EX-PLOT | major | style | ParaView output is written only behind a switch named `plot`, off by default. |
| EX-INCLUDE | major | script | An example is standalone: it never includes another example. A helper used by one example lives in an anonymous namespace in that file; a helper used by several belongs in the library. |
| EX-COMMENT | major | style | An example is read as documentation, so each stage carries a comment saying what it does and why: reading the input, building the basis, setting boundary conditions, assembling, solving, post-processing. A non-default choice (a refinement count, a penalty value, a solver option) says why it has that value. See **Commenting examples and tests** below. |
| EX-SIBLING | minor | style | A new example reads like its nearest sibling in the same directory: same order of sections (options, input, setup, solve, output), same way of reporting results. Name the sibling and the difference. |
| EX-CONV | minor | style | A convergence study prints its error table and the observed order, and states the expected order in a comment. |

## 7. Unit tests

| ID | Sev | Checker | Rule |
|---|---|---|---|
| UT-NAME | major | script | *New files.* A test file is `<name>_test.cpp`. |
| UT-INCLUDE | major | script | *New files.* It includes `"gismo_unittest.h"` first. |
| UT-SUITE | major | script | It contains `SUITE(<file name without .cpp>)`. Helpers live in an anonymous namespace inside the suite. |
| UT-COMMENT | major | style | A test can be reviewed without running it. Each `TEST` opens with a comment naming the property it verifies and where the expected result comes from (an analytic value, a manufactured solution, a reference computed another way). Inside, each block of lines — set up, act, check — has a comment saying what it does, and each expected value or tolerance says where it comes from. See **Commenting examples and tests** below. |
| UT-FAIL | major | review | Every test can fail. Findings: an assertion on the code's own output, a tolerance loose enough to pass anything, an arm that no input reaches, a skipped case counted as passed. |
| UT-NDEBUG | major | review | A test of an assertion uses `CHECK_THROW_IN_DEBUG`; `CHECK_THROW` on a `GISMO_ASSERT` fails or reads out of bounds in a Release build. A test that only checks something in Debug says so. |
| UT-FLOAT | major | style | Floating-point results are compared with `CHECK_CLOSE` and a stated tolerance, never `==`. A comparison helper returns infinity when either side is not finite, so that NaN does not pass. |
| UT-COVER | major | review | New public API is exercised by a test. A fixed bug has a test that fails without the fix. |

### Commenting examples and tests

Examples and tests are held to a higher commenting standard than library code, because
they are read far more often than they are changed: by the maintainers who must decide
whether a test really tests something, by users learning the library, and by agents
reviewing the change. A reader should be able to follow what happens block by block
without reconstructing it from the calls.

What a block comment says is the *intent* — what this block establishes and what the
reader should expect — not a paraphrase of the syntax:

```cpp
// Reference: the L2 projection of a polynomial of degree <= p is exact, so the
// error must vanish up to round-off for every refinement level.
TEST(L2projection_reproducesPolynomials)
{
    // Geometry and basis: unit square, bi-quadratic, refined twice so that the
    // basis has interior knots (a single element would hide assembly errors).
    ...

    // Project f(x,y) = x^2 + xy, which lies in the spline space.
    ...

    // The projection must equal f at points that are not quadrature nodes.
    // Tolerance: 100 * machine epsilon, the conditioning of the mass matrix here.
    CHECK_CLOSE(...);
}
```

Not acceptable, because each says only what the line below already shows:
`// create basis`, `// loop over patches`, `// check result`.

A comment is needed at each block, not each line. A test or example whose blocks carry
intent comments has a high comment share; that is expected here and is not a CM-VOLUME
concern.

## 8. Numerics and performance

All checked by `gismo:task-reviewer`; a finding needs the line and the input that breaks it.

| ID | Sev | Rule |
|---|---|---|
| NU-OVERFLOW | major | A product of sizes or DoF counts cannot overflow `index_t`. |
| NU-TOL | major | A tolerance is named, has a stated reason for its value, and scales with the problem where the quantity does. Round-off-level values are not compared with a relative tolerance. |
| NU-CANCEL | major | No subtraction of nearly equal quantities, division by an unguarded value, or exact comparison of a floating-point value with zero on a path that decides control flow. |
| NU-ALLOC | major | No heap allocation per element or per quadrature point: temporaries are sized once outside the loop. |
| NU-ALIAS | major | Eigen expressions do not alias: `noalias()` only where the destination does not appear on the right, and no `auto` holding an expression whose operands die. |
| NU-CAST | major | No narrowing cast of `real_t` to an integer type on a value that can be NaN or out of range. |
| NU-COMPLEX | minor | A new algorithm states its complexity in the doxygen of its entry point. |
