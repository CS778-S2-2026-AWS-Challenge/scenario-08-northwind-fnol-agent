# repo-governance-for-novice

Repository governance skill for the Northwind FNOL repository
(`CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent`). The rules
live in [`SKILL.md`](SKILL.md) and its twelve chapter files; `SKILL.md` is the
entry point and contains the file index. The rule text is agent-agnostic plain
Markdown — any coding agent that can read files can follow it.

This directory is simultaneously:

- a plain **Claude Code skill** (`SKILL.md` at the root),
- a **single-skill Claude Code plugin** (`.claude-plugin/plugin.json`),
- a **single-plugin marketplace** (`.claude-plugin/marketplace.json`, plugin
  source `./`),
- an **npm package** (`package.json`).

Pick whichever channel fits your setup.

## Channel A — In-repository deployment (how this repo consumes it)

The canonical copy for the Northwind FNOL repository lives at
`docs/skills/repo-governance-for-novice/`. The repository's `AGENT.md` routes
every coding agent (Claude Code, Codex CLI/desktop/VS Code, ChatGPT, Copilot,
and others) to `SKILL.md` there. No installation is needed — agents read the
Markdown directly.

## Channel B — Copy into a Claude Code skills directory

```
# project scope
cp -r repo-governance-for-novice <your-project>/.claude/skills/

# or personal scope
cp -r repo-governance-for-novice ~/.claude/skills/
```

Note: if you keep the bundled `.claude-plugin/` directory, Claude Code
promotes the folder to a plugin (invocation becomes
`/repo-governance-for-novice:...`). Delete `.claude-plugin/` (and optionally
`package.json` and this README) to keep it a plain skill invoked as
`/repo-governance-for-novice`.

## Channel C — Claude Code plugin marketplace

This directory is its own marketplace, so:

```
/plugin marketplace add <path-or-git-source-of-this-directory>
/plugin install repo-governance-for-novice@repo-governance-for-novice-marketplace
```

A local checkout path, a dedicated git repository containing this directory at
its root, or a marketplace entry in any other marketplace pointing here
(`{"source": "git-subdir", ...}` or `{"source": "npm", "package":
"repo-governance-for-novice"}`) all work. Validate before distributing:

```
claude plugin validate .
claude --plugin-dir .
```

## Channel D — npm

`package.json` is publish-ready (`npm publish` from this directory). Consumers
can then either reference the package from a marketplace entry
(`{"source": "npm", "package": "repo-governance-for-novice"}`) or
`npm pack` / download and copy the contents per Channel B.

## Adapting to another repository

The skill is written for the Northwind FNOL repository but designed for
minimal-cost porting. See the "Adapting this skill to another repository"
section at the end of `SKILL.md` for the exact list of anchors to edit
(maintainer handle, CODEOWNERS block, Kanban URL, contract-document paths,
quality-gate scripts, stack descriptions).

## Versioning

The skill version (see the version line in `SKILL.md`) is the source of truth
and is cited by the PR template's Governance confirmation. Keep
`.claude-plugin/plugin.json` and `package.json` versions in step with it when
releasing.
