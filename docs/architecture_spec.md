# アーキテクチャ仕様書

## 概要

**Hooty** は ターミナル上で動作する対話型 CLI ツールである。Python + Agno フレームワーク上に構築し、LLM プロバイダとして AWS Bedrock / Azure AI Foundry / Azure OpenAI Service / Ollama をサポートする。

## システム構成図

```
┌─────────────────────────────────────────────────┐
│                    Hooty CLI                    │
│                                                 │
│  ┌───────────┐    ┌──────────────────────────┐  │
│  │  main.py  │───▶│        repl.py           │  │
│  │  (Typer)  │    │  (対話ループ・UI 表示)    │  │
│  └───────────┘    └────────────┬─────────────┘  │
│                                │                │
│                    ┌───────────▼─────────────┐  │
│                    │    agent_factory.py      │  │
│                    │  (Agent 組み立て)        │  │
│                    └───┬───────────┬─────────┘  │
│                        │           │            │
│           ┌────────────▼──┐  ┌─────▼─────────┐  │
│           │  providers.py │  │    tools/      │  │
│           │  (LLM 接続)   │  │  (ツール群)    │  │
│           └───┬───────┬───┘  └──┬──┬──┬──┬───┘  │
│               │       │        │  │  │  │       │
│               ▼       ▼        ▼  ▼  ▼  ▼       │
│           ┌──────┐┌──────┐┌──────┐┌──────┐        │
│           │Azure ││Azure ││Bedro-││Olla- │ File  │
│           │AI    ││OpenAI││ck    ││ma    │ Shell │
│           └──────┘└──────┘└──────┘└──────┘ GH MCP│
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │              config.py                   │   │
│  │  (YAML設定 + 環境変数 + CLI引数)         │   │
│  └──────────────────────────────────────────┘   │
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │          永続化層 (SQLite + JSONL)          │   │
│  │  sessions.db                             │   │
│  │  memory.db (global)                      │   │
│  │  projects/{name}-{hash}/memory.db        │   │
│  │  projects/{name}-{hash}/history/*.jsonl  │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## モジュール構成

```
src/hooty/
├── __init__.py           # パッケージ定義・バージョン
├── main.py               # CLI エントリポイント（Typer）
├── config.py             # 設定管理
├── providers.py          # LLM プロバイダファクトリ
├── agent_factory.py      # Agent 組み立て
├── repl.py               # REPL コア（対話ループ・ストリーミング・Hook・モード遷移・セッション管理）
├── repl_ui.py            # UI コンポーネント（ThinkingIndicator, ScrollableMarkdown, StreamingView, テーマ）
├── commands/             # スラッシュコマンドハンドラー
│   ├── __init__.py       # CommandContext データクラス
│   ├── session.py        # /session, /new, /fork, /compact, /context
│   ├── skills.py         # /skills とサブコマンド
│   ├── files.py          # /diff, /rewind, /review, /add-dir, /list-dirs
│   ├── memory.py         # /memory とサブコマンド
│   ├── database.py       # /database とサブコマンド
│   ├── hooks_cmd.py      # /hooks とサブコマンド
│   ├── model.py          # /model, /reasoning
│   ├── plans.py          # /plans とサブコマンド
│   ├── agents.py         # /agents とサブコマンド
│   ├── misc.py           # /help, /quit, /safe, /unsafe, /rescan
│   ├── mode.py           # /plan, /code, /auto
│   ├── project.py        # /project とサブコマンド
│   ├── mcp_cmd.py        # /mcp とサブコマンド
│   ├── web_cmd.py        # /websearch トグル
│   └── github_cmd.py     # /github トグル
├── concurrency.py        # 並行処理ユーティリティ（WAL モード SQLite エンジン、アトミックファイル書き込み）
├── workspace.py          # セッション ↔ Working Directory バインディング（workspace.yaml）
├── session_lock.py       # セッションロック（fcntl.flock ベース排他制御、Windows は PID フォールバック）
├── session_store.py      # セッション検索・パージ・孤立ディレクトリ掃除
├── session_picker.py     # --resume 用インタラクティブセッション選択 UI（Project カラム・🚫 不一致マーカー付き）
├── purge_picker.py       # /session purge 用インタラクティブ複数選択 UI
├── memory_picker.py      # /memory edit 用インタラクティブ複数選択 UI（削除 + スコープ間移動）
├── memory_store.py       # メモリ検索・削除・移動・プロジェクトディレクトリ管理
├── project_store.py      # プロジェクトメタデータ・孤立検出・削除
├── project_purge_picker.py # /project purge 用インタラクティブ複数選択 UI
├── skill_store.py        # スキル検出・状態管理（SkillInfo, discover/load/save）
├── skill_picker.py       # /skills 用インタラクティブ複数選択ピッカー UI
├── file_picker.py        # /review・/add-dir 用ファイル/ディレクトリピッカー UI
├── plan_store.py         # プラン永続化（save/list/search/get/delete・ステータス管理）
├── plan_picker.py        # /plans 用統合ピッカー UI（view + delete）
├── file_snapshot.py      # ファイルスナップショット（/diff・/rewind 用変更追跡）
├── conversation_log.py   # 会話履歴ログ（Q&Aペア → JSONL 追記）
├── review.py             # /review データ型・プロンプト組み立て・JSON パース
├── review_picker.py      # /review 用レビュー指摘の多選択ピッカー UI
├── session_stats.py      # セッション統計（RunStats / SessionStats / PersistedStats）
├── ui.py                 # 共通 UI プリミティブ（Panel セレクター・テキスト入力・checkbox_select）
├── data/
│   ├── model_catalog.json  # モデルカタログ（コンテキスト長 + ケーパビリティフラグ）
│   ├── prompts.yaml        # システムプロンプトテンプレート
│   ├── agents.yaml         # ビルトインサブエージェント定義
│   ├── thinking_keywords.yaml # Thinking キーワード
│   └── skills/             # ビルトインスキル
│       ├── explain-code/   # コード説明 + ASCII フロー図
│       └── project-summary/ # プロジェクト構造サマリー（手動呼び出し専用）
└── tools/
    ├── __init__.py       # ツール組み立て（build_tools）
    ├── confirm.py        # 確認ダイアログ（Safe モード用）
    ├── coding_tools.py   # コーディングツール（ファイル操作・シェル・探索）
    ├── ask_user_tools.py # ユーザー質問ツール（LLM→人間への質問）
    ├── github_tools.py   # GitHub 連携
    └── mcp_tools.py      # MCP サーバー接続管理
```

### リポジトリルート

| ファイル | 説明 |
|---------|------|
| `NOTICE.md` | サードパーティライブラリのライセンス一覧（`scripts/update_notice.sh` で自動生成） |
| `scripts/update_notice.sh` | `pip-licenses` を実行し `NOTICE.md` を再生成するスクリプト |

## モジュール間の依存関係

```
main.py
  └── config.py          設定を読み込む
  └── repl.py            REPL を起動する
        ├── commands/*         スラッシュコマンドを処理する（CommandContext 経由）
        ├── repl_ui.py         UI コンポーネントを提供する
        └── agent_factory.py   Agent を生成する
              ├── providers.py       LLM モデルを生成する
              │     ├── agno.models.azure.AzureAIFoundry
              │     ├── agno.models.azure.openai_chat.AzureOpenAI
              │     └── agno.models.aws.AwsBedrock
              ├── tools/__init__.py  ツール群を組み立てる
              │     ├── coding_tools.py   → agno.tools.coding.CodingTools
              │     ├── github_tools.py   → agno.tools.github.GithubTools
              │     └── mcp_tools.py      → agno.tools.mcp.MCPTools
              ├── agno.db.sqlite.SqliteDb           (セッション永続化)
              └── agno.memory.manager.MemoryManager  (Agentic Memory)

commands/* → CommandContext のコールバック経由のみ（repl.py に直接依存しない）
```

## データフロー

### 1. 起動フロー

```
ユーザー実行: $ hooty --provider bedrock
    │
    ▼
main.py: CLI 引数パース（Typer）
    │
    ▼
config.py: 設定読み込み
    ~/.hooty/config.yaml → 環境変数 → CLI引数（後勝ち）
    │
    ▼
repl.py: REPL インスタンス生成
    │
    ▼
agent_factory.py: Agent 組み立て
    ├── providers.py: LLM モデル生成
    ├── tools/: ツール群インスタンス化
    ├── SqliteDb: セッションストレージ接続
    └── Memory: メモリストレージ接続
    │
    ▼
repl.py: ウェルカムバナー表示 → 入力待ちループ開始
```

### 2. 対話フロー

```
ユーザー入力: "src/main.py を読んで"
    │
    ▼
repl.py: スラッシュコマンド判定 → commands/* にディスパッチ or 通常メッセージ
    │
    ▼
repl.py: _send_to_agent()
    ├── インストラクション変更検出（context_fingerprint）
    ├── スキル変更検出（skill_fingerprint）
    └── 変更あり → 旧 Agent クリーンアップ + Agent 再生成
    │
    ▼
agent.print_response(input, stream=True, session_id=...)
    │
    ▼
Agno Agent:
    ├── LLM にプロンプト送信（会話履歴付き）
    ├── LLM がツールコール決定 → read_file("src/main.py")
    ├── ツール実行 → 結果を LLM に返却
    ├── LLM が最終応答生成
    └── ストリーミングでターミナルに出力
    │
    ▼
repl.py: 次の入力待ち
```

### 3. セッション管理フロー

```
新規セッション:
    session_id = UUID 自動生成
    初回メッセージ送信時: workspace.yaml にカレントディレクトリを記録
    │
    ▼
会話ごとに:
    Agent が SqliteDb に会話履歴を保存
    Agent が Memory に重要情報を抽出・保存
    │
    ▼
次回起動時:
    $ hooty --resume [id] / --continue
    → workspace.yaml と現在のディレクトリを比較
    → 不一致なら 🚫 Workspace mismatch 警告を表示
    → 最初のメッセージ送信時にリバインド（即終了なら保持）
```

## 永続化

| データ | 格納先 | 用途 |
|---|---|---|
| セッション履歴 | `~/.hooty/sessions.db` | 会話の継続・復元 |
| セッション統計 | `~/.hooty/sessions/{session_id}/stats.json` | 累計統計の永続化（runs, LLM時間, TTFT 等） |
| ワークスペースバインド | `~/.hooty/sessions/{session_id}/workspace.yaml` | セッションと作業ディレクトリの紐付け |
| グローバル記憶 | `~/.hooty/memory.db` | ユーザー嗜好・ワークフロー設定の長期記憶 |
| プロジェクト記憶 | `~/.hooty/projects/{name}-{hash8}/memory.db` | プロジェクト固有の設計判断・規約・技術スタック |
| 会話ログ | `~/.hooty/projects/{name}-{hash8}/history/{session-id}.jsonl` | ユーザー入力 + LLM 最終回答の Q&A ペア（JSONL） |

セッション統計は JSON ファイルで永続化し、`/session purge` の `shutil.rmtree` で自動削除される。会話ログは JSONL 形式でターンごとにリアルタイム追記される。その他は SQLite を使用し、Agno の `SqliteDb`（`memory_table` パラメータ）を利用する。

### 多重起動ロバストネス

複数の Hooty インスタンスが同時起動した際のデータ破損・ロック競合を防ぐための仕組み:

| 機構 | 対象 | 実装 |
|---|---|---|
| **SQLite WAL モード** | `sessions.db`, `memory.db`（グローバル/プロジェクト） | `concurrency.create_wal_engine()` — `journal_mode=WAL` + `busy_timeout=10000` + `synchronous=NORMAL` で読み書き並行を許可 |
| **アトミックファイル書き込み** | `config.yaml`, `databases.yaml`, `.credentials`, `.skills.json`, `.hooks.json`, `.meta.json`, `plans/*.md`, `workspace.yaml`, `stats.json`, `snapshots/_index.json` | `concurrency.atomic_write_text/bytes()` — 同一ディレクトリに一時ファイルを作成し `os.replace()` でアトミック置換。書き込み中に異常終了しても元ファイルは無傷 |
| **fcntl.flock セッションロック** | `locks/*.lock` | `session_lock.py` — `fcntl.flock(LOCK_EX \| LOCK_NB)` で TOCTOU フリーの排他ロック。プロセスクラッシュ時は OS が自動解放。Windows では PID ベースにフォールバック |

### プロジェクトディレクトリの導出

ワーキングディレクトリから一意のプロジェクトディレクトリ名を導出する:

```
ディレクトリ名 = {末尾ディレクトリ名}-{SHA-256(フルパス)先頭8文字}
例: /mnt/d/myapp → myapp-a3f1b2c4
```

同名ディレクトリが別パスにある場合もハッシュで衝突しない。詳細は `docs/memory_spec.md` を参照。

## 技術スタック

| レイヤー | 技術 |
|---|---|
| AI エージェント | Agno (`agno.agent.Agent`) |
| LLM プロバイダ | AWS Bedrock / Azure AI Foundry / Azure OpenAI Service |
| CLI フレームワーク | Typer |
| ターミナル UI | Rich |
| 設定管理 | PyYAML + python-dotenv |
| 永続化 | SQLite（Agno 組み込み） |
| パッケージ管理 | uv + hatchling |
| テスト | pytest |
| リンター | Ruff |
