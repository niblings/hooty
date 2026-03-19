# Sub-agents 仕様書

## 概要

サブエージェント機能は、メインエージェント（Planning/Coding 両モード）から独立したコンテキストウィンドウでタスクを実行する仕組みを提供する。親エージェントには最終結果のみ返却されるため、コンテキストの効率的な利用が可能。

## アーキテクチャ

```
Parent Agent (Planning/Coding)
  │
  ├─ run_agent("explore", "タスク説明")
  │     │
  │     └─ Sub-agent (ephemeral)
  │           ├─ 独立コンテキストウィンドウ
  │           ├─ 親ツールを継承（disallowed_tools で除外）
  │           ├─ Skills/Memory/DB なし
  │           └─ 結果テキスト → 親に返却
  │
  └─ 親は結果のみ受信（中間ツール呼び出しは見えない）
```

## エージェント定義

### 3層構造

1. **ビルトイン** (`src/hooty/data/agents.yaml`) — パッケージ同梱、削除不可
2. **グローバル** (`~/.hooty/agents.yaml`) — ユーザー全プロジェクト共通
3. **プロジェクト** (`.hooty/agents.yaml`) — プロジェクト固有

### マージ順序（後勝ち）

```
src/hooty/data/agents.yaml (builtin) < ~/.hooty/agents.yaml (global) < .hooty/agents.yaml (project)
```

### YAML フォーマット

```yaml
agents:
  agent_name:
    description: "エージェントの説明（LLM が選択に使用）"
    instructions: |
      サブエージェントへのシステム指示
    disallowed_tools:
      - write_file
      - edit_file
    model:                    # 省略時: 親モデルを継承
      provider: bedrock
      model_id: claude-haiku
    max_turns: 25             # デフォルト: 25
    max_output_tokens: 4000   # デフォルト: 4000
```

### フィールド定義

| フィールド | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `description` | str | 必須 | — | LLM がエージェント選択に使う説明文 |
| `instructions` | str | 必須 | — | サブエージェントのシステム指示 |
| `disallowed_tools` | list[str] | 任意 | `[]` | 拒否ツール名リスト |
| `model` | dict | 任意 | null（親継承） | `{provider, model_id}` で別モデル指定 |
| `max_turns` | int | 任意 | 25 | arun の最大イテレーション |
| `max_output_tokens` | int | 任意 | 4000 | 結果の最大文字数 |
| `requires_config` | list[str] | 任意 | `[]` | 実行に必要な config フラグ（未満足時はユーザーに確認ダイアログ表示） |

### `requires_config` フィールド

サブエージェントの実行に必要な設定フラグを宣言する。実行前に `SubAgentTools._ensure_required_config()` が各フラグをチェックし、未満足の場合はユーザーに Y/N ダイアログを表示する。

現在サポートされるフラグ:

| フラグ | 対応する config | ダイアログ内容 |
|---|---|---|
| `web_search` | `config.web_search` | `/websearch` の有効化を確認 |

**ダイアログ例（`web_search` 未有効時）:**

```
┌─● web-researcher requires Web search ──────┐
│                                             │
│  [Y]  Yes, enable /websearch                │
│  [N]  No, cancel                            │
│                                             │
└─────────────────────────────────────────────┘
```

- Y → `config.web_search = True`（`/websearch` トグルと同等、Agent 再生成なしで実行継続）
- N → サブエージェント実行キャンセル、キャンセルメッセージを返却

**Non-interactive モード**: ダイアログなしで自動拒否。

## ビルトインエージェント

### explore

コードベースの広範な探索・深いリサーチ。read-only ツールのみ使用。

- **disallowed_tools**: write_file, edit_file, apply_patch, move_file, create_directory, run_shell, run_powershell
- **max_turns**: 25
- **max_output_tokens**: 4000

### implement

コード変更の実装 — ファイル書き込み・編集・コマンド実行・エラー修正を隔離コンテキストで実行。親の edit-test-fix サイクルによるコンテキスト肥大化を防ぐ。

- **disallowed_tools**: なし（全ツール利用可能）
- **max_turns**: 30
- **max_output_tokens**: 3000
- **compress_tool_results**: 自動有効（書き込みツールを持つエージェントに自動適用）

**ツール選択ルール**: 専用ツールを `run_shell` より常に優先する:
- `read_file`（NOT `cat`/`head`/`tail`）、`edit_file`（NOT `sed`/`awk`）、`grep`/`find`/`ls`/`tree` ツール（NOT shell 版）
- `move_file`（NOT `mv`）、`create_directory`（NOT `mkdir`）、`apply_patch`（マルチファイル変更）
- `run_shell` は検証コマンド（test/lint）やビルドツール等、専用ツールがない操作のみ

**委譲ガイドライン**: 親は以下を提供する:
1. 対象ファイルと変更内容の明確な記述
2. 検証コマンド（テスト、lint、型チェック）

**レポート形式**: `SUCCESS` / `PARTIAL` / `FAILED` のステータスと、変更ファイル一覧・検証結果・課題を構造化レポートで返却。

### web-researcher

Web 検索とページ読み取りを組み合わせた深い Web 調査。隔離コンテキストで実行し、構造化レポートを返却。

- **disallowed_tools**: write_file, edit_file, apply_patch, move_file, create_directory, run_shell, run_powershell
- **requires_config**: `[web_search]` — `/websearch` OFF 時は Y/N ダイアログで確認後に有効化
- **max_turns**: 12
- **max_output_tokens**: 5000

**ツールバジェット（instructions で制限）:**
- `web_search` / `search_news`: 合計最大 3 回
- `web_fetch`: 最大 5 回

**リサーチ戦略:**
1. 1〜2 回の `web_search` で候補 URL を取得
2. 上位 3〜5 件を `web_fetch(max_chars=50000)` で読み取り
3. 重要な不足があれば 1 回のフォローアップ検索

**403 / Access Denied ハンドリング:**
- 連続 403 が発生したドメインはそれ以上探索しない
- フォールバック: `web_search` で `site:domain keyword` を検索

**レポート形式:** サマリー（最大 5 行）+ ソースごとの URL・タイトル・要点 + アクセス不能 URL リスト

### test-runner

テスト実行 → 失敗解析 → ソース修正 → 再実行のサイクルを自動化する専門エージェント。

- **disallowed_tools**: なし（全ツール利用可能）
- **max_turns**: 40
- **max_output_tokens**: 3000
- **compress_tool_results**: 自動有効

**4 フェーズ:**
1. **フレームワーク検出** — プロジェクトファイルからテストフレームワークを自動検出（pytest, jest, vitest, go test, cargo test, JUnit）
2. **テスト実行** — 親から指定されたコマンド、または自動検出したコマンドでテストを実行
3. **失敗解析** — 失敗の分類（assertion failure / runtime error / import error / timeout）と優先度付け
4. **修正 & 再実行** — ソースコードの修正 → 再テスト（問題ごとに最大 3 リトライ）

**ツール選択ルール**: implement と同様に専用ツールを優先する。`run_shell` はテストコマンドやビルドツール等のみ。

**委譲ガイドライン**: 親は以下を提供する:
1. テストコマンド（例: `uv run pytest tests/test_foo.py`）
2. オプション: スコープや既知の失敗に関するコンテキスト

**レポート形式**: `SUCCESS` / `PARTIAL` / `FAILED` のステータスと、テスト結果サマリー・適用した修正・残存する失敗を構造化レポートで返却。

**implement との使い分け:**

| 観点 | implement | test-runner |
|------|-----------|-------------|
| 入力 | 親が「何をどう変えるか」を明示 | 「テストを通せ」だけでよい |
| 戦略 | ファイル変更 → 検証 | テスト実行 → 失敗解析 → ソース特定 → 修正 → 再テスト |
| ユースケース | 機能実装、リファクタ | テスト修正、TDD、CI 失敗調査 |

### assistant

汎用タスク実行エージェント。コーディング以外のタスク（ドキュメント作成、データ分析、システム管理、ファイル整理、レポート作成）を隔離コンテキストで実行する。

- **disallowed_tools**: なし（全ツール利用可能）
- **max_turns**: 25
- **max_output_tokens**: 5000

**対象タスク:**
- ドキュメント作成・編集
- データ分析・集計
- システム管理・ファイル操作
- ローカルファイルからのレポート作成

**Web 検索の制約:**
- `web_search` / `search_news` は使用不可（instructions で禁止）
- `web_fetch` は親が明示的に提供した単一 URL のみ許可
- 広範な Web 調査が必要な場合は `web-researcher` を使用すること

**ツール選択ルール**: implement と同様に専用ツールを優先する。

**委譲ガイドライン**: 親は以下を提供する:
1. タスクの明確な説明と期待する出力形式
2. 関連ファイルパスやデータソース（該当する場合）

**レポート形式**: `SUCCESS` / `PARTIAL` / `FAILED` のステータスと、出力内容・判断事項・課題を構造化レポートで返却。

**web-researcher との使い分け:**

| 観点 | assistant | web-researcher |
|------|-----------|----------------|
| 入力 | ローカルファイル・データ | Web 上の情報 |
| ツール | ファイル操作・シェル中心 | web_search + web_fetch |
| ユースケース | ドキュメント作成、データ加工 | 技術調査、最新情報の取得 |

### summarize

ファイル・モジュール・クラスの要約生成。親に圧縮した文脈を返す。

- **disallowed_tools**: write_file, edit_file, apply_patch, move_file, create_directory, run_shell, run_powershell
- **max_turns**: 15
- **max_output_tokens**: 2000

## ツール継承モデル

### 常に除外（NEVER_INHERIT）

| ツール | 理由 |
|---|---|
| `exit_plan_mode` / `enter_plan_mode` | モード遷移は親専用 |
| `run_agent` | 入れ子呼び出し禁止 |
| `ask_user` | サブは自律実行のみ |
| `think` / `analyze` | 推論ツールは親専用 |

### 継承されるツール

親が持つツールのうち、NEVER_INHERIT と disallowed_tools に含まれないものすべて:

- CodingTools（read_file, grep, find, ls, tree, write_file, edit_file, apply_patch, move_file, create_directory, run_shell）
- PowerShellTools（PowerShell がインストールされている環境のみ — Windows / Linux with pwsh）
- Web 検索・読み取り
- GitHub ツール

### disallowed_tools による除外

agents.yaml でサブエージェントごとに拒否リストを定義:

```yaml
agents:
  explore:
    disallowed_tools:
      - write_file
      - edit_file
      - apply_patch
      - move_file
      - create_directory
      - run_shell
      - run_powershell
```

### CodingTools の粒度制御（SelectiveCodingTools）

`disallowed_tools` に CodingTools の書き込みメソッド（`write_file`, `edit_file`, `apply_patch`, `move_file`, `create_directory`, `run_shell`）を個別に指定できる。コア 3 メソッド（`write_file`, `edit_file`, `run_shell`）がすべてブロックされた場合は `PlanModeCodingTools`（read-only）、一部のみブロックされた場合は `SelectiveCodingTools` が使われる。

| disallowed_tools の内容 | 使用クラス | 動作 |
|---|---|---|
| `{write_file, edit_file, run_shell}` 以上 | `PlanModeCodingTools` | 全 write/shell ブロック（read-only） |
| `{run_shell}` のみ | `SelectiveCodingTools` | shell ブロック、write/edit は確認付き |
| `{write_file, edit_file}` のみ | `SelectiveCodingTools` | write/edit ブロック、shell は確認付き |
| `{}` 空 | `ConfirmableCodingTools` | 全メソッド確認付き |

例: shell なしの書き込みエージェント:

```yaml
agents:
  writer:
    description: "Write files but no shell"
    instructions: "You can write files but cannot run shell commands."
    disallowed_tools: [run_shell, run_powershell]
```

### MCP/SQL ツールの将来対応

MCP/SQL ツールはツール継承ではなく、専用サブエージェントとして実現する予定:

- `sql_expert`: DB 接続 + クエリツール
- `browser_expert`: Playwright MCP による Web 操作

各専用エージェントが MCP サーバー/DB 接続のライフサイクルを内包する設計。

## タスク分解（Task Decomposition）

複数フェーズや複数成果物を含むリクエストは、単一のモノリシックなサブエージェント呼び出しではなく、直列的なサブエージェント呼び出しに分解する。

### 分解の流れ

1. **分析** — リクエストを独立した作業単位に分割
2. **選択** — 各単位に最適なサブエージェントを選択
3. **逐次実行** — 各結果をレビューし、次のタスクを必要に応じて調整
4. **統合** — 全サブエージェント完了後、結果をユーザー向けに統合

### 例

「キャッシュレイヤーを追加してテストを書いて」:
```
explore（現在のアーキテクチャ理解）→ implement（キャッシュ追加）→ test-runner（テスト実行・修正）
```

### 分解しないケース

- 単純なリクエストが1つのサブエージェントに自然にフィットする場合
- 密結合な変更を分割すると整合性が損なわれる場合

### assistant と web-researcher のルーティング

| タスク種別 | 委譲先 |
|-----------|--------|
| ドキュメント作成、データ加工、ファイル整理 | `assistant` |
| Web 検索、URL 読み取りを伴う調査 | `web-researcher` |
| コード探索・理解 | `explore` |
| コード変更の実装 | `implement` |
| テスト実行・修正 | `test-runner` |

## 実行モデル

### エフェメラル実行

- サブエージェントはセッション DB を共有しない
- Skills / Memory は無効
- 入れ子呼び出し不可（run_agent はサブに含まれない）
- 確認ダイアログは confirm_ref を共有（親の "All" 承認がサブにも適用）
- Reasoning（thinking）は常に無効

### ツール結果圧縮

書き込み可能なサブエージェント（`write_file`/`edit_file`/`run_shell` のいずれかが disallowed にない）は、自動的に `compress_tool_results=True` + `CompressionManager` が設定される。圧縮閾値はコンテキスト上限の 50%。

これにより `implement` のような多数のツール呼び出しを行うエージェントが、自身のコンテキストウィンドウ内でオーバーフローすることを防ぐ。read-only エージェント（`explore`, `summarize`）には適用されない。

### コンテキスト継承

サブエージェントは以下を継承:
- **instructions**: agents.yaml の instructions フィールド
- **additional_context**: グローバル指示（hooty.md）+ プロジェクト指示（CLAUDE.md 等）
- **working_directory**: 親と同じ作業ディレクトリ

### Ctrl+C キャンセル伝播

ユーザーが Ctrl+C を押すと、メインの asyncio タスクが即座にキャンセルされると同時に、`sub_agent_runner.cancel_event`（`threading.Event`）がセットされる。サブエージェントの `_arun_sub_agent()` はイベントループの各イテレーションでこのフラグをチェックし、セット済みなら `break` でループを脱出する。

- **POSIX (Linux/macOS/WSL2)**: `add_signal_handler(SIGINT)` → asyncio タスク即時キャンセル + `cancel_event.set()`
- **Windows**: `KeyboardInterrupt` catch → 同様に `cancel_event.set()`。ただしツール実行中および完了後 5 秒間は `SetConsoleCtrlHandler` が stale `CTRL_C_EVENT` を抑制するため、`KeyboardInterrupt` 自体が発生しない。この間はキャンセル不可。キャンセル成功時は `ProactorEventLoop` を新規作成して差し替えた後、`_reset_async_clients()` でモデルの `async_client` と agno グローバル `httpx.AsyncClient` をリセットする（古いループに紐付いた HTTP コネクションの stale 参照を解消）。`CancelledError` 発生時も同様にループを再作成する。`KeyboardInterrupt` ハンドラ内の `run_until_complete(asyncio.sleep(0))` は Windows ではスキップする（壊れた ProactorEventLoop の IOCP select でハングするため）
- `cancel_event` は `_stream_response()` 開始時に `clear()` でリセットされる

**制約**: サブエージェントがツール実行中（LLM 応答待ち・シェルコマンド実行中）の場合、次のイベント到達までキャンセルチェックに到達しない。ただしメイン側は即座に REPL プロンプトに復帰するため、ユーザー体験上は即時中断となる。

### ストリーミング実行

`agent.arun(task, stream=True)` でストリーミング実行し、ツール呼び出しイベントを REPL のツリー表示に反映:

```
🤖 explore: "プロジェクト構造を調査して"
 ├─ 🔍 read_file  (src/main.py)
 ├─ 🔍 grep  (handle_request)
 ├─ 🔍 read_file  (src/handlers.py)
 └─ ✓ Complete (3 tool calls)
```

サブエージェント実行中は `Live` の `refresh_per_second` を 4 → 2 に低減し、ConPTY 環境でのスピナー残留を軽減する。完了時に 4 に復帰。

ヒント表示はツール引数から主要パラメータを抽出して表示する（`_HINT_KEY` マッピング）:

| ツール | ヒント内容 |
|--------|-----------|
| `read_file`, `write_file`, `edit_file` | ファイルパス（cwd からの相対パス） |
| `apply_patch` | パッチ内のファイルパス一覧（`*** Add/Update/Delete File:` から抽出） |
| `move_file` | 移動元パス |
| `create_directory` | ディレクトリパス |
| `run_shell`, `run_powershell` | コマンドの先頭行（60 文字でトランケート） |
| `grep`, `find` | 検索パターン |
| `ls` | ディレクトリパス |
| `web_fetch` | URL |
| `web_search`, `search_news` | 検索クエリ |

## Hooks 連携

サブエージェントの起動・終了時に Hooks イベントが発火する。非 blocking（サブエージェント実行をブロックしない）。

### SubagentStart

サブエージェント起動時に発火。

| フィールド | 型 | 説明 |
|---|---|---|
| `agent_name` | str | サブエージェント名（matcher 対象） |
| `task` | str | 親から渡されたタスク説明 |

### SubagentEnd

サブエージェント終了時に発火。

| フィールド | 型 | 説明 |
|---|---|---|
| `agent_name` | str | サブエージェント名（matcher 対象） |
| `task` | str | 親から渡されたタスク説明 |
| `tool_call_count` | int | ツール呼び出し回数 |
| `result_length` | int | 結果テキストの文字数 |
| `elapsed` | float | 実行時間（秒） |
| `error` | str | エラーメッセージ（成功時は空文字列） |

### hooks.yaml 設定例

```yaml
hooks:
  SubagentStart:
    - command: "echo 'Sub-agent started'"
      matcher: "explore"         # explore エージェントのみ
  SubagentEnd:
    - command: "~/scripts/log_subagent.sh"
```

## スラッシュコマンド

| コマンド | 説明 |
|---|---|
| `/agents` | 利用可能なサブエージェント一覧表示 |
| `/agents info <name>` | エージェント詳細表示 |
| `/agents reload` | agents.yaml 再読み込み |

## セッション統計

サブエージェントの実行統計はセッション統計に蓄積され、`/session` と `/session agents` で確認できる。

### `/session`（引数なし）

Stats 行の後にサブエージェント合計行が表示される（使用時のみ）:

```
  Session: abc123
  Project: /home/user/project  (my-project)
  Tokens:  in:50,000  out:8,000  total:58,000
  Cost:    $0.1234
  Stats:   session:12m 30s  runs:5  LLM:45.2s  avg:9.0s  TTFT:1.20s
  Agents:  runs:8  tools:42  time:1m 15s  in:12,000  out:3,500
```

### `/session agents`

エージェントごとの内訳テーブルを表示:

```
  Sub-agent runs:

  Agent          Runs  Tools      Time   In tokens  Out tokens
  explore           3     18     45.2s       6,000       1,500
  summarize         1      3      5.1s       1,200         400
  ─────────────────────────────────────────────────────────────
  Total             4     21     50.3s       7,200       1,900
```

サブエージェント未使用時は Agents 行は非表示、`/session agents` は「No sub-agent runs in this session.」と表示。

### 統計収集

- `_arun_sub_agent` で `RunEvent.run_completed` をキャッチし、`metrics.input_tokens` / `metrics.output_tokens` を取得
- `SubAgentRunStats`（agent_name, elapsed, tool_calls, input_tokens, output_tokens, error）を `SessionStats.sub_agent_runs` に蓄積
- `_session_stats_ref` module-level ref で REPL の `SessionStats` インスタンスを共有
- `PersistedStats` に 6 フィールド（runs, elapsed, tool_calls, input_tokens, output_tokens, errors）を追加し、`stats.json` で永続化

## ファイル構成

| ファイル | 役割 |
|---|---|
| `src/hooty/agent_store.py` | AgentDef データモデル、YAML パース、マージロジック |
| `src/hooty/data/agents.yaml` | ビルトインエージェント定義 |
| `src/hooty/tools/sub_agent_tools.py` | SubAgentTools Toolkit（run_agent 登録）、`_session_stats_ref` |
| `src/hooty/tools/sub_agent_runner.py` | サブエージェント実行エンジン、トークンキャプチャ、統計投入 |
| `src/hooty/session_stats.py` | `SubAgentRunStats` データクラス、`SessionStats` サブエージェント properties |
| `tests/test_agent_store.py` | agent_store のユニットテスト |
| `tests/test_sub_agent_tools.py` | SubAgentTools・`_session_stats_ref` のユニットテスト |
| `tests/test_coding_tools.py` | SelectiveCodingTools・`create_coding_tools` blocked_tools のユニットテスト |
