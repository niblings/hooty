---
name: skill-creator
description: Interactively create a new skill with proper structure and format
disable-model-invocation: true
---

# Skill Creator

Create a new Hooty skill through an interactive wizard. If `$ARGUMENTS` is provided, use it as the starting point (skill name and/or description). Otherwise, ask the user.

## Step 1 — Gather requirements

Ask the user (skip questions already answered via `$ARGUMENTS`):

1. **Skill name** — lowercase, hyphenated (e.g. `lint-checker`)
2. **Purpose** — what does this skill do? (one sentence)
3. **Invocation mode** — should the LLM call it automatically, or manual-only (`/skills invoke`)?
4. **User-invocable** — can users invoke it manually? (default: yes)
5. **References** — any reference docs to include in `references/`?
6. **Scripts** — any helper scripts to include in `scripts/`?

## Step 2 — Load the format spec

Call `get_skill_reference("skill-creator", "skill-format.md")` to retrieve the full SKILL.md format specification. Follow it precisely when generating files.

## Step 3 — Generate skill files

Create the following files:

- `SKILL.md` — frontmatter (name, description, flags) + instructions body
- `references/*.md` — reference documents if the user requested them
- `scripts/*` — helper scripts if the user requested them

Write clear, actionable instructions in the SKILL.md body. Follow the Progressive Discovery pattern: keep the main instructions concise and put detailed reference material in `references/`.

## Step 4 — Choose placement

Ask the user where to place the skill:

- **Project** (`<project-root>/.hooty/skills/<name>/`) — only this project
- **Global** (`~/.hooty/skills/<name>/`) — available in all projects

Then create the files at the chosen location.

## Step 5 — Verify

After creating the files, tell the user to run:

```
/skills reload
/skills info <name>
```

to confirm the skill was detected correctly.

## Rules

- Always include `name` and `description` in the frontmatter
- Set `disable-model-invocation: true` if the user chose manual-only mode
- Set `user-invocable: false` only if the user explicitly requests it
- Use English for code comments and file content per project conventions
- Do NOT overwrite existing skills without explicit user confirmation
