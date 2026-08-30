# §9 Documentation standards

This file defines repository documentation structure, writing-type discipline,
English style, and the API documentation and versioning policy.

## 9.1 Repository structure and file additions

- `CHANGELOG.md`, `CONTRIBUTING.md`, and `SECURITY.md` are **not introduced**:
  git diff and commit history satisfy the traceability need, and there is no
  external-contributor or vulnerability-disclosure scenario.
- Repository security settings (secret scanning, push protection, Dependabot
  alerts) are repository-side configuration, not skill rules. Git LFS and the
  GitHub Skills course do not apply.

## 9.2 Writing-type discipline (Diátaxis)

Per the Diátaxis framework, documents divide into four types along two
questions — "guides action vs. provides understanding" × "serves learning vs.
serves work": Tutorial / How-to guide / Reference / Explanation. Diátaxis
explicitly opposes building directories around the four types; this clause is
a **writing discipline** only and is orthogonal to the current directory
layers.

1. **Classify before writing**: before writing or substantially revising any
   reader-facing document, decide which of the four types it is, or whether it
   is "outside the four types" (process documents such as SPEC, `docs/status`,
   `docs/research`).
2. **One document, one type, that type's discipline**: a tutorial does not
   explain or offer options — it guarantees the learner succeeds at every
   step; a how-to guide contains only actions — usefulness over completeness;
   a reference only describes — neutral, authoritative, structured to mirror
   the product, with no procedures; an explanation only discusses reasoning
   and trade-offs, with no instructions or specification statements.
3. **No mixed writing; link instead of digressing**: when out-of-type content
   appears (procedures inside a reference, theory inside a tutorial), compress
   it to one sentence and link to the document of the correct type. Do not
   expand it.
4. **Classify README paragraph by paragraph**: a README may contain several
   types, but classify each paragraph separately and follow each type's
   discipline; do not mix types within a paragraph.
5. **Mapping for this repository**: `docs/api.md` → reference; `docs/design/`
   → primarily explanation (interface and data-structure definitions inside it
   follow reference discipline); SPEC gets no quadrant label, but its
   specification content follows reference discipline (neutral, unambiguous,
   authoritative).
6. **This clause does not change the directory structure**: type labeling is a
   writing discipline, not an archiving rule; the current
   root/design/status/research/archive layering remains authoritative.

## 9.3 English writing style

Based on the GitHub Docs style guide and best practices (docs-site-specific
mechanisms removed):

1. **Voice and sentence length**: active voice and present tense by default;
   one idea per sentence, one topic per paragraph.
2. **Structure first**: open every document with 1–3 sentences stating its
   purpose and scope; inverted pyramid — conclusions and key information
   first, details after.
3. **Headings**: sentence case; start at H2 and never skip levels; no
   duplicate same-level headings; use the imperative verb form ("Configure X",
   not "Configuring X").
4. **Lists and tables**: every list needs an introductory sentence; capitalize
   the first letter of each item and end with a period only for complete
   sentences; every table cell must have a value — write "None" or
   "Not applicable" for empty values, never "N/A". (This rule governs
   **documentation** tables; UI tables display "–" for empty values, see
   `frontend-design.md` section 11.4 rule 2 — do not mix the two.)
5. **Code blocks**: always tag fenced blocks with a language; commands without
   a `$` prompt and output as comments, so the block is copyable as a whole;
   explanatory text goes before the block; placeholders in all-caps with
   hyphens (`YOUR-BRANCH-NAME`).
6. **Links**: link text is the target document's title, introduced with "For
   more information, see …"; the same link appears at most once per document;
   never "click here".
7. **Terminology**: write words out ("repository", not "repo"); expand
   abbreviations on first use; keep spelling and capitalization consistent
   across the repository; use inclusive language (allowlist / denylist /
   default branch).
8. **Time and versions**: write version constraints as "X or later"; avoid
   wording that expires ("currently", "soon", "new"); dates as `YYYY-MM-DD`.
9. **In-text naming**: file names, directory names, commands, and code
   identifiers always in backticks.
10. **Single responsibility**: one document covers one or two tasks or
    concepts; beyond that, split and cross-link.

## 9.4 API documentation and versioning policy

- **API documentation**: OpenAPI Specification (OAS 3.x). No full
  contract-first migration; use **automatic export plus a CI drift check**
  (the backend is FastAPI, so the spec is generated from code; mechanism in
  `ci-checks.md`). `docs/api.md` remains the human-readable contract
  authority; the spec snapshot is only a drift sentinel.
- **Versioning and change logs**: Semantic Versioning and Keep a Changelog are
  **not introduced** (no externally released versions; git history provides
  traceability). Conventional Commits stays (details in `pr-workflow.md`
  section 5.1).

Writing discipline: prefer short, topic-focused documents and maintain the
directory indexes; state facts, decisions, assumptions, prototype rules, and
open questions separately. Status records must state reproducible evidence and
its limitations.
