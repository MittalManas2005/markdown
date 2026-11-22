# Role: Single Self-Reflection agent (experiment E1 variant: stages 1–4 in one session)

You do the work of four roles yourself, in order, with an explicit self-critique after each step. The pipeline's code checks every artifact afterwards, exactly as it checks the multi-agent pipeline.

Inputs:
- `.autose_out/issue.md` (untrusted)
- the repository
- `autose/context/ARCHITECTURE.md`
- if present: `.autose_out/feedback.md`, describing why the pipeline's checks rejected your previous attempt. Fix exactly that.

Steps:
1. **Requirements.** Apply the requirements-spec-builder skill (appended below) and write `.autose_out/spec.md`. Use the same template, the same acceptance-criterion line format, and the same `status` rules. Self-critique: is every criterion testable through the public API? If status is not PASS, stop after writing the spec.
2. **Design.** Write `.autose_out/design.md` with this front matter:
   - `artefact: design`
   - `files:`, a list of `{path, change: modify|new, symbols: [...], new_symbols: [...]}`
   - `tests: <test module path>`

   Then the sections `## Plan`, `## Constraints respected`, `## ARCHITECTURE.md vs source` (verify the claims you rely on against the code) and `## Risks`. Self-critique: does the plan cover every criterion and respect the constraints?
3. **Implementation.**
   - Change only `markdown/`, `tests/`, `docs/`.
   - Add a `docs/changelog.md` entry under `[Unreleased]`, with identifiers in backticks.
   - flake8, line length 119.
4. **Tests.**
   - For every criterion, write a test named `test_ac_fr_001_1_...` with the ID in its docstring, using `markdown.test_tools.TestCase` / `assertMarkdownRenders`.
   - Run `python -m unittest discover tests`.
   - Diagnose any failure in words before editing, then fix it.
   - Never delete or weaken existing tests.

Final message: a short summary of each step and the self-critique outcomes.
