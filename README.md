# Hooty

Interactive AI coding assistant CLI built on the [Agno](https://github.com/agno-agi/agno) framework.

[日本語版 README](README_ja.md)

```
   ,___,
   (o,o)    Hooty
   /)  )    Interactive AI coding assistant
  --""--    powered by Agno
```

## Features

- **REPL Interface** - Rich-based terminal UI with Markdown streaming, Planning / Coding dual-mode
- **Non-Interactive Mode** - `hooty -p "prompt"` for one-shot execution; supports pipe input for scripts and CI/CD
- **Multi-Provider Support** - Anthropic / Azure AI Foundry / Azure OpenAI / OpenAI / AWS Bedrock / Ollama; switch models mid-session with `/model`
- **Coding Tools** - Built-in file read/write/edit, shell execution, code search (grep / find / ls); Safe mode (default ON) shows confirmation dialogs for dangerous operations
- **Context Files** - Global instructions (`~/.hooty/hooty.md`) and project-specific instructions (`AGENTS.md` / `CLAUDE.md` etc.) for custom LLM directives; compatible with other tools' instruction files
- **Session Management** - Persistent conversation history with restore, fork, and automatic context window compaction
- **Project Memory** - Store design decisions and coding conventions per project, reusable across sessions
- **External Integrations** - GitHub tools, DuckDuckGo web search, SQL database connections
- **MCP Server Integration** - Extend tools via Model Context Protocol servers
- **Agent Skills** - Open-standard skill packages for extending agent expertise; define project-specific conventions and workflows as skills, loaded on-demand (Progressive Discovery)
- **Sub-agents** - Automatically delegate complex tasks to sub-agents with isolated contexts; built-in agents (`explore` / `implement` / `test-runner` / `assistant` / `web-researcher` / `summarize`) plus custom agents via `agents.yaml`
- **Hooks (Lifecycle Hooks)** - Trigger shell commands on session start, LLM response, tool execution, and other events; supports blocking decisions and context injection
- **File Snapshots** - Automatic tracking of LLM file changes during sessions; `/diff` for diffs, `/rewind` to roll back
- **Extended Thinking** - Control Claude's extended thinking with `/reasoning`; `auto` mode dynamically adjusts thinking budget in 3 levels based on keywords (`think`, `ultrathink`, etc.)
- **Code Review** - Interactive code review and auto-fix with `/review`
- **File Attachments** - Attach images and text files with `/attach`; supports clipboard paste (`/attach paste`) and screen capture (`/attach capture`, Windows / WSL2); also `--attach` CLI option for pre-attaching at startup

## Installation

Uses [uv](https://docs.astral.sh/uv/) for package management.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (all extras + dev tools)
uv sync --all-extras
```

## Setup

Edit `~/.hooty/config.yaml` to configure providers and models:

```yaml
# ~/.hooty/config.yaml
default:
  profile: sonnet

providers:
  azure_openai:
    endpoint: https://your-resource.openai.azure.com

profiles:
  sonnet:
    provider: anthropic
    model_id: claude-sonnet-4-6
  gpt:
    provider: azure_openai
    model_id: gpt-5.4
    deployment: gpt-5.4
```

API keys are set via environment variables (e.g. `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY`). See [Config Spec](docs/config_spec.md) for details.

```bash
# Interactive credential setup
hooty setup

# Check setup status
hooty setup show
```

## Usage

```bash
# Start
hooty

# With a profile
hooty --profile <name>

# Specify working directory
hooty --dir ~/my-project

# Resume a session (interactive selection)
hooty --resume

# Continue the most recent session
hooty --continue

# Non-interactive mode (one-shot)
hooty -p "run all the tests"
cat prompt.md | hooty --unsafe > result.md
```

## Slash Commands

| Command | Description |
|---|---|
| `/help` | Show command list |
| `/quit` | Exit |
| `/model` | Switch model profile |
| `/session` | Session management (list / restore / delete) |
| `/memory` | Manage project memory |
| `/compact` | Compact session history |
| `/review` | Source code review |
| `/skills` | Manage Agent Skills (list / enable / invoke) |
| `/agents` | List / inspect sub-agents |
| `/hooks` | Manage lifecycle hooks |
| `/attach` | Attach files (images / text / clipboard / capture) |
| `/mcp` | MCP server list / reload |
| `/diff` / `/rewind` | Show / revert file changes |
| `/plan` / `/code` | Switch Planning / Coding mode |
| `/safe` / `/unsafe` | Toggle Safe mode |

See the [User Guide](docs/user_guide.md) for details.

## Development

```bash
# Run tests
uv run pytest -m "not integration"

# Lint
uv run ruff check src/ tests/
```
