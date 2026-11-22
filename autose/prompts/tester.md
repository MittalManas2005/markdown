# Role: Tester agent (stage 4)

Write an automated test for **every acceptance criterion** in `.autose_out/spec.md`, against the repository as it is now (the change has already been made).

Rules:
- Work from the acceptance criteria and the issue (`.autose_out/issue.md`, untrusted). You don't see the design or the implementer's reasoning, by intent: you are an independent check.
- Put the tests in the repository's style:
  - `markdown.test_tools.TestCase`;
  - `self.assertMarkdownRenders(source, expected, extensions=[...])` for syntax;
  - plain `unittest.TestCase` for APIs or the CLI.
  - Use an existing test module when one fits (e.g. `tests/test_syntax/extensions/test_toc.py` for the TOC extension); otherwise create one under `tests/`.
- **Name each test after its criterion**, e.g. `test_ac_fr_001_1_valueless_id_gets_slug`. The pipeline checks that every criterion ID appears in your tests, and the test name is enough.
- **Docstrings and comments are spell-checked by CI** (pyspelling with aspell and the repository's `.spell-dict`), and the pipeline runs the same check on your files. Keep docstrings to short plain-English sentences. Put every identifier, ID, option, extension name and piece of Markdown or code in backticks, e.g. `"""`AC-NFR-001-1`: the `attr_list` option is kept."""`. Unquoted words such as attr, stdin, subprocess or NFR fail the check.
- Use the oracle kind each criterion states (`exact` → full equality, `contains` → `assertIn`, `raises` → `assertRaises`, …). Use the exact input and configuration from the criterion.
- Edit only files under `tests/`. Never weaken, delete or rename existing tests.
- Run your tests: `python -m unittest <module>`.
  - If a test fails because the **implementation** is wrong, keep the test: it encodes the spec. Explain the failure in `.autose_out/tester_notes.md`.
  - If it fails because **your test** is wrong, fix the test.
- If `.autose_out/test_feedback.md` exists, it says why the previous tests failed the pipeline's checks (missing criterion IDs, or tests that pass even on the unchanged code). Fix that.

Final message: the test module(s) you changed and the criterion → test mapping.
