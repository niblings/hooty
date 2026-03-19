# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 言語ルール

- 対話（会話・レビューコメント）: 日本語
- PR・Issues: 日本語
- ソースコード内のコメント: 英語
- マークダウンドキュメント（`.md` ファイル）: 日本語

## プロジェクト概要

Hooty — 対話型 AI コーディングアシスタント CLI。Python + Agno フレームワーク。LLM プロバイダとして AWS Bedrock / Azure AI Foundry をサポート。

## 開発コマンド

パッケージ管理には [uv](https://docs.astral.sh/uv/) を使用する。

```bash
# 依存関係インストール（全エクストラ + 開発ツール）
uv sync --all-extras

# テスト実行（ユニットテストのみ）
uv run pytest -m "not integration"

# 単一テスト実行
uv run pytest tests/test_config.py -v

# リント
uv run ruff check src/ tests/

# 起動
uv run hooty
uv run hooty --provider azure --model claude-sonnet-4-6
```

## アーキテクチャ

```
src/hooty/
├── main.py           # CLI エントリポイント（Typer）→ REPL or Non-Interactive 起動
├── config.py         # 設定管理（YAML + 環境変数 + CLI引数、後勝ちマージ）
├── providers.py      # LLM プロバイダファクトリ（遅延インポート）
├── agent_factory.py  # Agno Agent 組み立て（model + tools + storage）
├── oneshot.py        # Non-Interactive モード（単発実行 → stdout 出力）
├── repl.py           # REPL コア（対話ループ・ストリーミング・Hook・モード遷移・セッション管理）
├── repl_ui.py        # UI コンポーネント（ThinkingIndicator, ScrollableMarkdown, StreamingView, テーマ）
├── commands/         # スラッシュコマンドハンドラー（CommandContext パターン）
└── tools/            # ツール群（ファイル操作・シェル・確認ダイアログ・GitHub・MCP・サブエージェント）
```

完全なファイル一覧は `docs/architecture_spec.md` を参照。

データフロー: `main.py` → `config.py`(設定読込) → `repl.py`(REPL起動) or `oneshot.py`(非対話実行) → `agent_factory.py`(Agent生成) → `providers.py`(LLMモデル) + `tools/`(ツール群) + `skill_store.py`(スキル) + `agent_store.py`(サブエージェント)

コマンドディスパッチ: `repl.py` の `_handle_slash_command()` → `commands/*.py` のモジュールレベル関数。コマンドは `CommandContext` を受け取り、REPL 状態へのアクセスはコールバック経由で行う（直接 `self` を参照しない）。

設定ファイル: `~/.hooty/config.yaml`（YAML）。永続データ: `~/.hooty/sessions.db`, `~/.hooty/memory.db`（SQLite、WAL モード）。ファイル書き込みは `concurrency.atomic_write_text/bytes()` でアトミック化。セッションロックは `fcntl.flock()` でレースフリー。

## Agent Skills

Agno Agent Skills を統合。デフォルト有効。スキルディレクトリ・構造・状態管理・スラッシュコマンドの詳細は `docs/skills_spec.md` を参照。

## Hooks

セッション・メッセージ・ツール利用のライフサイクルでシェルスクリプトをトリガー。イベント一覧・プロトコル・設定の詳細は `docs/hooks_spec.md` を参照。

## Sub-agents

`run_agent()` ツールでサブエージェントにタスクを委譲（独立コンテキスト、結果のみ返却）。エージェント定義・ビルトイン・ツール継承の詳細は `docs/agents_spec.md` を参照。

## 仕様書

詳細な仕様は `docs/` 配下を参照:
- `docs/architecture_spec.md` — 全体アーキテクチャ
- `docs/cli_spec.md` — CLI UI・カラースキーム
- `docs/config_spec.md` — 設定ファイル構造
- `docs/provider_spec.md` — LLM プロバイダ
- `docs/tools_spec.md` — ツール構成
- `docs/non_interactive_spec.md` — Non-Interactive モード
- `docs/skills_spec.md` — Agent Skills（スキルシステム）
- `docs/hooks_spec.md` — Hooks（ライフサイクルイベント）
- `docs/agents_spec.md` — Sub-agents（サブエージェント委譲）
- `docs/setup_guide.md` — セットアップガイド（クレデンシャル配布）
