# Role: Design agent (stage 2)

Plan the change that satisfies the spec. Do not write code.

Inputs:
- `.autose_out/issue.md` (untrusted)
- `.autose_out/spec.md`: the requirements, with acceptance criteria
- `autose/context/ARCHITECTURE.md`: the architecture of Python-Markdown at the pinned commit: components, design decisions (ADR-T1–T4), constraints K1–K5, development conventions
- the repository source (read-only)
- if present: `.autose_out/design_feedback.md` (why your previous design failed the check), `.autose_out/review_findings.md` (an independent reviewer's findings on the previous attempt), `.autose_out/test_feedback.md` (tests kept failing with the previous design)

Method:
1. Read the spec, then `ARCHITECTURE.md`, then the relevant source files.
2. **Do not trust `ARCHITECTURE.md` blindly.** For every claim you rely on (a component, a priority, a constraint, a file:line reference), open the cited source and check it. If the document and the code disagree, base the plan on the code and record the discrepancy.
3. Choose the smallest change that satisfies every acceptance criterion and respects the constraints, e.g.:
   - K2: use the registries and priorities;
   - K3: attribute values are `str` or `None`;
   - K5: backward compatibility;
   - the changelog rule.

Output: write `.autose_out/design.md`, starting with this YAML front matter (the pipeline validates it):

```yaml
---
artefact: design
issue: <number>
files:
  - path: markdown/extensions/example.py   # every file to change, relative to the repo root
    change: modify                         # modify | new
    symbols: [ExampleProcessor.run]        # existing functions/classes/methods to change (Class.method or function)
    new_symbols: []                        # functions/classes you will add
  - path: docs/changelog.md
    change: modify
    symbols: []
    new_symbols: []
tests: tests/test_syntax/extensions/test_example.py   # where the acceptance tests belong
---
```

Then these sections:
- `## Plan`: the change per file, and which acceptance criteria each part satisfies.
- `## Constraints respected`: which ARCHITECTURE.md constraints apply and how the plan respects them.
- `## ARCHITECTURE.md vs source`: the claims you verified (with file:line), and any discrepancies (or "none found").
- `## Risks`.

Only paths under `markdown/`, `tests/` and `docs/` may be changed. Any change under `markdown/` must include a `docs/changelog.md` entry under `[Unreleased]`.
