---
name: explain-code
description: Explain code in plain language with visual diagrams
---

# Explain Code Skill

When asked to explain code, follow this structured approach. This is a **read-only** skill — do NOT modify any files.

## Steps

1. **Read** the target file or function using `read_file`
2. **Summarize** what it does in one sentence (plain language, no jargon)
3. **Walk through** the logic step by step, numbering each step
4. **Draw a flow diagram** using ASCII art to visualize the control flow
5. **List key concepts** — explain any patterns, idioms, or non-obvious techniques used

## Output format

```
## Summary
<one-sentence plain-language summary>

## Step-by-step
1. ...
2. ...

## Flow diagram
<ASCII art>

## Key concepts
- **<concept>**: <explanation>
```

## Rules

- Do NOT modify, create, or delete any files
- Use simple language — assume the reader is a junior developer
- If the code is longer than 50 lines, focus on the main logic path first
- When $ARGUMENTS is provided, explain that specific file or function
