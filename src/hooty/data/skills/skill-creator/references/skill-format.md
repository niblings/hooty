# SKILL.md Format Specification

## Directory structure

Each skill lives in its own directory:

```
<skill-name>/
├── SKILL.md              # Frontmatter + instructions (required)
├── scripts/              # Executable scripts (optional)
│   └── run.sh
└── references/           # Reference documents (optional)
    └── some-doc.md
```

## SKILL.md format

A SKILL.md file has two parts: YAML frontmatter and a markdown instructions body.

```markdown
---
name: my-skill
description: A short description of what this skill does
---

# My Skill

Instructions for the LLM go here...
```

## Frontmatter fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | yes | — | Unique skill identifier (lowercase, hyphenated) |
| `description` | string | yes | — | One-line summary shown in `/skills list` |
| `disable-model-invocation` | bool | no | `false` | When `true`, LLM cannot auto-invoke; manual only via `/skills invoke` |
| `user-invocable` | bool | no | `true` | When `false`, only the LLM can use it; users cannot call `/skills invoke` |

## The `$ARGUMENTS` placeholder

Use `$ARGUMENTS` in the instructions body to reference arguments passed by the user:

```
/skills invoke my-skill some arguments here
```

The string `"some arguments here"` replaces `$ARGUMENTS` in the instructions. Design instructions to handle both cases:
- `$ARGUMENTS` is present → use it as input
- `$ARGUMENTS` is empty → ask the user or use a default

## scripts/ directory

Place executable scripts (shell, Python, etc.) in `scripts/`. The LLM can retrieve them using:

```
get_skill_script("skill-name", "run.sh")
```

Use scripts for repeatable operations like linting, formatting, or code generation.

## references/ directory

Place supplementary documents in `references/`. The LLM can retrieve them using:

```
get_skill_reference("skill-name", "some-doc.md")
```

Use references for detailed specifications, templates, or examples that would bloat the main instructions.

## Progressive Discovery pattern

Keep the main SKILL.md instructions **concise and action-oriented**. Move detailed reference material into `references/` and instruct the LLM to fetch it when needed.

**Good pattern:**

```markdown
## Step 1 — Analyze
Read the target file.

## Step 2 — Load template
Call `get_skill_reference("my-skill", "template.md")` to get the output template.

## Step 3 — Generate
Produce output following the template.
```

**Anti-pattern (avoid):**

```markdown
## Instructions
Here is a 200-line template embedded directly in the instructions...
```

Benefits:
- Smaller initial prompt → faster startup
- LLM only loads what it needs for the current step
- Easier to maintain and update individual references

## Placement and priority

Skills are discovered from multiple locations. **Later sources override earlier ones** (same-name wins):

1. `~/.hooty/skills/` — user global (lowest priority)
2. `<project>/.github/skills/` → `<project>/.claude/skills/` → `<project>/.hooty/skills/` — project (highest priority)

Choose placement based on scope:
- **Project skills** — project-specific workflows (linting rules, deploy scripts)
- **Global skills** — personal utilities useful across all projects

## Examples

### Builtin: explain-code (LLM auto-invocable)

```yaml
---
name: explain-code
description: Explain code in plain language with visual diagrams
---
```

No `disable-model-invocation` → LLM can call it automatically when it sees a relevant request. Uses `references/diagram-examples.md` for ASCII art examples.

### Builtin: project-summary (manual-only)

```yaml
---
name: project-summary
description: Generate a read-only project structure summary
disable-model-invocation: true
---
```

`disable-model-invocation: true` → only callable via `/skills invoke project-summary`. Appropriate for heavy read-only analysis that shouldn't trigger automatically.

## Writing good instructions

1. **Start with a clear goal** — first line should say what the skill does
2. **Number your steps** — LLMs follow numbered sequences reliably
3. **Specify tool usage** — tell the LLM which tools to use (e.g. `read_file`, `run_shell`)
4. **Set boundaries** — explicitly state what the skill should NOT do (read-only? no file creation?)
5. **Handle `$ARGUMENTS`** — always consider the case where arguments are and aren't provided
6. **Keep it under 50 lines** — offload details to `references/`
