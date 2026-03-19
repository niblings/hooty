---
name: project-summary
description: Generate a read-only project structure summary
disable-model-invocation: true
---

# Project Summary Skill

Analyze the **$ARGUMENTS** directory (default: current project root) and produce a **read-only** summary report. Do NOT modify any files.

## What to report

1. **Directory tree** — List top-level files and directories (max 2 levels deep)
2. **Language breakdown** — Count files by extension (.py, .md, .yaml, etc.)
3. **Key files** — Identify README, config files, entry points, and test directories
4. **Dependencies** — List from pyproject.toml, requirements.txt, or package.json if present
5. **Git status** — Current branch, last 3 commits (one-line), clean/dirty state

## Rules

- This is a **read-only analysis**. Do NOT create, edit, or delete any files.
- Do NOT run any commands that modify state (no install, no build, no git checkout).
- Only use read-only tools: `read_file`, `grep`, `find`, `ls`, `run_shell` with read-only commands (e.g. `git log`, `git status`, `wc -l`).

## Output format

Present the summary as a structured markdown report with the sections above.
