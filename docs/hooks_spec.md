# Hooks 仕様書

## 概要

Hooty の Hooks 機能は、セッション・LLM 会話・ツール利用のライフサイクルでシェルスクリプトをトリガーし、ブロック/許可の判定や LLM へのコンテキスト注入を可能にする。v1 は command タイプのみをサポート。

## 設定ファイル

### スコープ階層（リスト連結マージ）

1. `~/.hooty/hooks.yaml` — グローバル（`source: "global"`）
2. `<project>/.hooty/hooks.yaml` — プロジェクト固有（`source: "project"`）

同一イベントのエントリはリスト連結（グローバル先、プロジェクト後）。各エントリに `source` フィールドが自動付与され、`/hooks list` やピッカーで表示される。

### 設定例

```yaml
hooks:
  SessionStart:
    - command: "~/scripts/audit-start.sh"
      timeout: 5

  PreToolUse:
    - command: "~/scripts/lint-gate.sh"
      matcher: "write_file|create_file"
      blocking: true
      timeout: 3

  UserPromptSubmit:
    - command: "~/scripts/prompt-filter.sh"
      blocking: true
      timeout: 5

  Stop:
    - command: "~/scripts/post-response.sh"
      async: true

  SubagentStart:
    - command: "~/scripts/log-subagent.sh"
      matcher: "explore"

  SubagentEnd:
    - command: "~/scripts/log-subagent-result.sh"
```

### フィールド定義

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `command` | str | (必須) | 実行するシェルコマンド |
| `matcher` | str | `""` | 正規表現フィルタ（イベント固有フィールドに対して適用） |
| `blocking` | bool | `false` | exit 2 でアクション阻止可能にする |
| `async` | bool | `false` | バックグラウンド実行（結果を待たない） |
| `timeout` | int | `5` | タイムアウト秒数 |

## イベント一覧

| Event | カテゴリ | トリガーポイント | blocking 可 |
|---|---|---|---|
| `SessionStart` | Session | REPL ループ開始直前 / oneshot 実行直前 / `/new` 後 | No |
| `SessionEnd` | Session | REPL 終了時 / oneshot 完了時 / `/new` 前 | No |
| `UserPromptSubmit` | Message | `_send_to_agent()` 冒頭 | **Yes** |
| `Stop` | Message | レスポンス完了後 | No |
| `ResponseError` | Message | `_send_to_agent()` 例外ハンドラ | No |
| `PreToolUse` | Tool | ストリーム内 tool_call_started | **Yes** (v1: warning のみ) |
| `PostToolUse` | Tool | ストリーム内 tool_call_completed | No |
| `PostToolUseFailure` | Tool | ツール実行失敗時 | No |
| `PermissionRequest` | Tool | `_confirm_action()` 冒頭 | **Yes** |
| `ModeSwitch` | Agent | plan/coding 自動遷移時 | No |
| `SubagentStart` | Agent | サブエージェント起動時 | No |
| `SubagentEnd` | Agent | サブエージェント終了時 | No |
| `Notification` | System | 将来拡張用（v1 では未使用） | No |

### セッション切替時の発火順序

`/new` コマンドでセッションを切り替えた場合、以下の順序でフックが発火する:

1. `SessionEnd` — 現在のセッションの終了
2. （セッション切替処理）
3. `SessionStart` — 新しいセッションの開始

`/quit`、`Ctrl+D`、プロセス終了時は `SessionEnd` のみ発火。

### サブエージェント実行時の発火順序

`run_agent()` ツール呼び出し時、以下の順序でフックが発火する:

1. `SubagentStart` — サブエージェント起動直前（`agent_name`, `task`）
2. （サブエージェント実行 — 独立コンテキストで動作）
3. `SubagentEnd` — サブエージェント完了後（`agent_name`, `task`, `tool_call_count`, `result_length`, `elapsed`, `error`）

いずれも非 blocking。サブエージェント実行をフックで阻止することはできない。エラー発生時は `SubagentEnd` の `error` フィールドにエラーメッセージが格納される。

### セッション ID について

`SessionStart` / `SessionEnd` で渡される `session_id` は、会話が行われずにセッションが終了した場合、DB に永続化されないエフェメラルな ID となる。セッション監査ログではこの点を考慮すること。

### Matcher 対象フィールド

| イベント | matcher 対象 |
|---|---|
| PreToolUse / PostToolUse / PostToolUseFailure / PermissionRequest | `tool_name` |
| UserPromptSubmit | `message` |
| SubagentStart / SubagentEnd | `agent_name` |
| その他 | matcher 非対応（設定しても無視） |

## プロトコル

### 入力: stdin に JSON

```json
{
  "hook_event": "PreToolUse",
  "session_id": "abc-123",
  "cwd": "/path/to/project",
  "timestamp": "2026-03-06T10:00:00+00:00",
  "tool_name": "write_file",
  "tool_input": {"path": "src/main.py", "content": "..."}
}
```

各イベント固有フィールドはトップレベルにフラット展開。

**SubagentStart の例:**

```json
{
  "hook_event": "SubagentStart",
  "session_id": "abc-123",
  "cwd": "/path/to/project",
  "timestamp": "2026-03-07T10:00:00+00:00",
  "agent_name": "explore",
  "task": "プロジェクト構造を調査して"
}
```

**SubagentEnd の例:**

```json
{
  "hook_event": "SubagentEnd",
  "session_id": "abc-123",
  "cwd": "/path/to/project",
  "timestamp": "2026-03-07T10:00:15+00:00",
  "agent_name": "explore",
  "task": "プロジェクト構造を調査して",
  "tool_call_count": 8,
  "result_length": 2450,
  "elapsed": 14.73,
  "error": ""
}
```

### 出力: exit code + stdout/stderr

| Exit code | 意味 |
|---|---|
| 0 | 成功。stdout が JSON なら解析、プレーンテキストなら additionalContext 扱い |
| 2 | ブロック（blocking=true のフックのみ有効）。stderr を reason として使用 |
| その他 | 非ブロッキングエラー（WARNING ログ、処理続行） |

**stderr の扱い:**

- exit 0 の場合: stderr は `logger.debug` で出力（`--debug` フラグで確認可能）
- exit 2 の場合: stderr を `reason` として使用
- その他の exit code: stderr を `error` として WARNING ログに出力

> **Tips:** REPL 環境では stderr が画面に表示されないため、デバッグ目的の出力には stdout JSON の `additionalContext` を使用するか、`--debug` フラグで起動すること。

### stdout JSON（exit 0 時、任意）

```json
{
  "decision": "allow",
  "reason": "All checks passed",
  "additionalContext": "Lint: 0 warnings"
}
```

### LLM コンテキスト注入

`additionalContext` フィールドが存在する場合、メッセージに `<hook_context>` ブロックとして追加:

- `UserPromptSubmit` → 現在のメッセージに即時追加
- `Stop` → 次のターンに繰り越し
- `SessionStart` → 最初のメッセージに追加

## PermissionRequest ゲート

`PermissionRequest` は最も実用的なゲート。`confirm.py` の `_confirm_action()` 冒頭で発火:

- exit 2 → ツール拒否（return False）
- `decision: "allow"` → ユーザー確認スキップ（自動承認）
- それ以外 → 既存の対話的確認に進む

`description` フィールドにコマンド内容やファイルパスが含まれるため、最も詳細なデータが利用可能。

## CLI フラグ

```bash
uv run hooty --no-hooks    # Hooks 無効で起動
```

## スラッシュコマンド

| コマンド | 説明 |
|---|---|
| `/hooks` | インタラクティブピッカー（各フック ON/OFF 切替） |
| `/hooks list` | 登録済み全フック一覧表示（source ラベル付き） |
| `/hooks on` | Hooks 機能を全体 ON |
| `/hooks off` | Hooks 機能を全体 OFF |
| `/hooks reload` | hooks.yaml を再読込 |

### `/hooks list` 表示例

```
  Hooks (3 registered, enabled)

  SessionStart
    ✓ ~/scripts/audit-start.sh           project  timeout: 5s

  PreToolUse
    ✓ ~/scripts/lint-gate.sh             global  write_file|create_file  blocking  timeout: 3s

  UserPromptSubmit
    ✓ ~/scripts/prompt-filter.sh         global  blocking  timeout: 5s
```

各エントリに `global` / `project` の source ラベルが表示される。マルチラインコマンドは 1 行目のみ表示（35 文字で切り詰め）。

## 状態管理

- グローバル ON/OFF: `AppConfig.hooks_enabled`（デフォルト `True`）
- 個別 ON/OFF: `~/.hooty/projects/<slug>/.hooks.json`

```json
{"disabled_hooks": ["PreToolUse:~/scripts/lint-gate.sh"]}
```

キー形式: `{event}:{command}` で一意識別。

## データモデル

### HookEntry

```python
@dataclass
class HookEntry:
    command: str
    matcher: str = ""
    blocking: bool = False
    async_exec: bool = False   # YAML key: "async"
    timeout: int = 5
    enabled: bool = True
    source: str = ""           # "global" or "project" (auto-assigned on load)
```

`source` フィールドは `load_hooks_config()` でファイルの読み込み元に応じて自動設定される。YAML ファイルには記述不要。

### HookResult

```python
@dataclass
class HookResult:
    success: bool
    exit_code: int = 0
    decision: str = ""          # "allow" | "block" | ""
    reason: str = ""
    additional_context: str = ""
    error: str = ""
```

## 実装ファイル

| ファイル | 内容 |
|---|---|
| `src/hooty/hooks.py` | データモデル + 設定ロード + 実行エンジン + 状態管理 |
| `src/hooty/hooks_picker.py` | `/hooks` ピッカー UI |
| `tests/test_hooks.py` | ユニットテスト（39+ tests） |

## 実装上の注意

### 非同期/同期の境界

- `emit_hook()` は async 関数。REPL のストリーミングループ内など async コンテキストから呼び出す
- `emit_hook_sync()` は sync ラッパー。`_fire_session_end()` 等の同期コンテキストから呼び出す
- `_fire_session_end()` は `asyncio.run()` で新しいイベントループを作成して実行する（既存ループの状態に依存しない）

### confirm.py との連携

`confirm.py` の `_hooks_ref` リスト（`[hooks_config, session_id, cwd, loop]`）を通じてフック設定を参照。`repl.py` の `_update_hooks_ref()` で値を更新。フック関連のスラッシュコマンド（`/hooks`, `/hooks list` 等）は `commands/hooks_cmd.py` に実装。

## v1 制約

- `PreToolUse` の blocking は Agno ストリーム内で実行中断不可のため WARNING ログのみ
- `PostToolUseFailure` は Agno ストリームでの成功/失敗区別が限定的
- `Notification` イベントは将来拡張用（v1 では未使用）
