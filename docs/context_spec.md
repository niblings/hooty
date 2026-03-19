# コンテキスト管理仕様書

## 概要

Hooty のシステムプロンプト（Agent instructions）にユーザー定義のコンテキストを追加する仕組み。グローバル指示とプロジェクト固有指示の 2 種類をサポートし、他の AI コーディングアシスタントの指示ファイルとも互換性を持つ。

```
ハードコード基本指示  +  グローバル指示  +  プロジェクト固有指示  →  Agent に渡す
    (既存)               (~/.hooty/)        (プロジェクトルート)
```

## コンテキストファイルの種類

| 種類 | パス | 役割 |
|---|---|---|
| グローバル指示 | `~/.hooty/hooty.md` または `instructions.md` | 全プロジェクト共通のカスタム指示 |
| プロジェクト固有指示 | プロジェクトルートの対象ファイル | プロジェクト固有のコーディング規約・指示 |

### グローバル指示（`~/.hooty/hooty.md` / `instructions.md`）

全プロジェクト共通のカスタム指示を記述する Markdown ファイル。

| 優先度 | ファイル名 | 備考 |
|---|---|---|
| 1 | `~/.hooty/hooty.md` | Hooty 固有 |
| 2 | `~/.hooty/instructions.md` | レガシー互換 |

- 両方存在する場合: ファイルサイズが大きい方を 1 つ採用（同サイズなら優先度順）
- どちらも存在しない場合: サイレントスキップ（エラーなし）
- 用途例: 言語設定、コーディングスタイル、レビュー方針など

```markdown
# ~/.hooty/hooty.md の例

- 回答は日本語で行うこと
- コードにはコメントを英語で記述すること
- テストを書く際は pytest を使用すること
```

### プロジェクト固有指示

プロジェクトルートに配置された指示ファイル。他の AI コーディングアシスタントで使用されるファイルを自動検出する。

## プロジェクト固有指示の自動選択ロジック

### 対象ファイル（優先度順）

| 優先度 | ファイル名 | 互換性 |
|---|---|---|
| 1 | `AGENTS.md` | Hooty 固有 |
| 2 | `CLAUDE.md` | Claude Code |
| 3 | `.github/copilot-instructions.md` | GitHub Copilot |

### 選択ルール

```
プロジェクトルートから対象ファイルを探索
    │
    ├── 存在するファイルが 1 つだけ → そのファイルを使用
    │
    ├── 複数存在 → ファイルサイズが最大のものを 1 つ採用
    │
    └── いずれも存在しない → プロジェクト固有指示なし（グローバルのみ）
```

- 探索対象はプロジェクトルート（`config.working_directory`）直下のみ（再帰探索しない）
- `.github/copilot-instructions.md` のみサブディレクトリ内を参照する
- ファイルサイズが同一の場合は優先度順（上の表の順）で選択する

## コンテキスト合成

### 合成順序

すべて **追記（append）方式** で合成する:

```
1. ハードコード基本指示（agent_factory.py の既存 instructions）
2. グローバル指示（~/.hooty/instructions.md）
3. プロジェクト固有指示（自動選択された 1 ファイル）
4. plan_mode 指示（動的追加）
```

### Agno パラメータマッピング

| Agno パラメータ | 内容 | 変更 |
|---|---|---|
| `instructions` | ハードコード基本指示 + plan_mode 指示 | 変更なし |
| `use_instruction_tags` | `True` — instructions を `<instructions>` タグで囲む | **新規追加** |
| `additional_context` | グローバル指示 + プロジェクト固有指示 | **新規追加** |

`additional_context` は文字列として渡す。各セクションを XML タグで囲み、LLM にとって境界を明確にする:

```xml
<global_instructions>
（~/.hooty/instructions.md の内容）
</global_instructions>

<project_instructions>
（プロジェクト固有指示ファイルの内容）
</project_instructions>
```

- どちらか一方のみ存在する場合も対応するタグで囲んで渡す
- 両方とも存在しない場合は `additional_context` を設定しない

## 制約

| 項目 | 値 |
|---|---|
| ファイルサイズ上限 | 64 KB |
| エンコーディング | UTF-8 |
| ファイル不在時 | サイレントスキップ |

### ファイルサイズ上限の動作

- 64 KB を超えるファイルは **読み込みをスキップ** する
- 警告ログを出力する: `Context file exceeds 64KB limit, skipping: <path>`
- コンソールにも警告を表示する: `⚠ コンテキストファイルが 64KB を超えています: <path>`

### エラーハンドリング

| 状況 | 対応 |
|---|---|
| ファイルが存在しない | サイレントスキップ（後方互換性 100%） |
| ファイルサイズ超過（> 64KB） | 警告ログ出力、該当ファイルをスキップ |
| UTF-8 デコードエラー | 警告ログ出力、該当ファイルをスキップ |
| ファイル読み取り権限なし | 警告ログ出力、該当ファイルをスキップ |

## インストラクション自動検出

メッセージ送信前（`_send_to_agent()`）にインストラクションファイルの変更を自動検出し、変更があれば Agent を自動再生成する。セッション中に `CLAUDE.md` や `~/.hooty/hooty.md` を編集した場合、次のメッセージ送信時に自動的に最新の内容が反映される。

- **検出方法:** `context_fingerprint()` が対象ファイルの SHA-256 コンテンツハッシュを計算し、前回のフィンガープリントと比較する。mtime に依存しないため WSL2/NTFS 環境でも安定動作
- **検出対象:** グローバル指示（`~/.hooty/hooty.md` / `instructions.md`）およびプロジェクト固有指示（`AGENTS.md` / `CLAUDE.md` / `.github/copilot-instructions.md`）の追加・削除・内容変更
- **タイミング:** 毎メッセージ送信前。スキル変更検出と同時に実行される
- **表示:** `Instructions changed — agent reloaded.`（スキル変更と同時の場合は `Instructions & Skills changed — agent reloaded.`）

## `/context` スラッシュコマンド

現在のモデル情報、コンテキストファイルの読み込み状態、コンテキストウィンドウの使用状況を表示する。

### コマンド

| コマンド | 説明 |
|---|---|
| `/context` | モデル情報・コンテキストファイル・コンテキストウィンドウ使用状況を表示 |

### 表示例

数回やりとり後:

```
❯ /context

  Current Model:
    Provider:  bedrock
    Model ID:  global.anthropic.claude-sonnet-4-6
    Profile:   aws-sonnet-4-6
    Streaming: ✓
    Reasoning: ✓ (auto)
    Vision:    ✓

  Context:
    Global instructions: /home/user/.hooty/hooty.md (0.3 KB, 4 LoC)
    Project instructions: CLAUDE.md (3.1 KB, 73 LoC)

  Context window:
    ████████░░░░░░░░░░░░ 42% (84,000 / 200,000 tokens)
    Source:          last request

    History:         5 runs, 23 messages (last 3 in context)
    Session summary: active (1,200 chars)
    Compressed:      4 tool results
```

セッション統計あり:

```
❯ /context

  Current Model:
    Provider:  bedrock
    Model ID:  global.anthropic.claude-sonnet-4-6
    Streaming: ✓
    Reasoning: ✓ (auto)
    Vision:    ✓

  Context:
    Global instructions: /home/user/.hooty/hooty.md (0.3 KB, 4 LoC)
    Project instructions: CLAUDE.md (3.1 KB, 73 LoC)

  Context window:
    ████████░░░░░░░░░░░░ 42% (84,000 / 200,000 tokens)
    Source:          last request

    History:         5 runs, 23 messages (last 3 in context)
    Session summary: active (1,200 chars)
    Compressed:      4 tool results
    Stats:           session:5m 12s  runs:5  LLM:28.3s  avg:5.7s  TTFT:1.23s
```

セッション統計あり（`--resume` 再開後、累計あり）:

```
❯ /context

  Current Model:
    Provider:  bedrock
    Model ID:  global.anthropic.claude-sonnet-4-6
    Streaming: ✓
    Reasoning: ✓ (auto)
    Vision:    ✓

  Context:
    Global instructions: /home/user/.hooty/hooty.md (0.3 KB, 4 LoC)
    Project instructions: CLAUDE.md (3.1 KB, 73 LoC)

  Context window:
    ████████░░░░░░░░░░░░ 42% (84,000 / 200,000 tokens)
    Source:          last request

    History:         5 runs, 23 messages (last 3 in context)
    Session summary: active (1,200 chars)
    Compressed:      4 tool results
    Stats:           session:30s  runs:1 (20)  LLM:7.5s (3m 24s)  avg:7.5s (10.2s)  TTFT:0.35s (0.47s)
```

初回（LLM 呼び出し前）:

```
❯ /context

  Current Model:
    Provider:  bedrock
    Model ID:  global.anthropic.claude-sonnet-4-6
    Streaming: ✓
    Reasoning: ✓ (auto)
    Vision:    ✓

  Context:
    Global instructions: /home/user/.hooty/hooty.md (0.3 KB, 4 LoC)
    Project instructions: CLAUDE.md (3.1 KB, 73 LoC)

  Context window:
    ░░░░░░░░░░░░░░░░░░░░ -- (200,000 tokens available)

    History:         no runs yet
    Session summary: none
```

ファイルが存在しない場合:

```
❯ /context

  Current Model:
    Provider:  bedrock
    Model ID:  global.anthropic.claude-sonnet-4-6
    Streaming: ✓
    Reasoning: ✗
    Vision:    ✓

  Context:
    Global instructions: none
    Project instructions: none

  Context window:
    ░░░░░░░░░░░░░░░░░░░░ -- (200,000 tokens available)

    History:         no runs yet
    Session summary: none
```

### Current Model 表示の詳細

現在アクティブなプロバイダ・モデル・能力フラグを表示する。

| 項目 | ソース | 備考 |
|---|---|---|
| Provider | `config.provider.value` | `bedrock`, `azure` 等 |
| Model ID | `ctx.get_model_id()` | 実際に使用中のモデル ID |
| Profile | `config.active_profile` | 空の場合は行自体を非表示 |
| Streaming | `config.stream` | `✓`（緑）/ `✗`（dim） |
| Reasoning | `supports_thinking(config)` + `config.reasoning.mode` | `✓ (auto)` / `✓ (on)` / `✗` |
| Vision | `supports_vision(config)` | `✓`（緑）/ `✗`（dim） |

### コンテキストウィンドウ表示の詳細

#### プログレスバー

`█`（U+2588）と `░`（U+2591）で幅 20 のバーを描画する。

| 使用率 | 色 | Rich スタイル |
|---|---|---|
| 0–49% | ゴールド | `#E6C200` |
| 50–79% | 黄 | `yellow` |
| 80–100% | 赤太字 | `bold red` |
| LLM 未呼び出し | グレー | `dim`（`░` のみ、`--` 表示） |

#### データソース

| データ | 取得元 | 備考 |
|---|---|---|
| input_tokens | ストリーミング時: `ModelRequestCompletedEvent.input_tokens`（最後の API コールの値）。非ストリーミング時: 最後のアシスタントメッセージの `metrics.input_tokens`（per-request 値）。いずれも取得不可時は `last_run.metrics.input_tokens`（累積値）にフォールバック。取得ソースを `Source` 行で表示（`last request` / `last run (sum)`） | `CommandContext.get_last_request_input_tokens()` 経由 |
| cache_tokens | `last_run.messages` の最後のアシスタントメッセージの `metrics.cache_read_tokens` + `cache_write_tokens` | input_tokens に加算してコンテキストウィンドウ使用量とする（Anthropic API はキャッシュトークンを `input_tokens` と別に報告するため） |
| context_limit | `_get_context_limit()` | 既存メソッド |
| runs / messages | `agent.db.get_session(session_id, SessionType.AGENT).runs` | |
| session summary | `session.summary` | AgentSession のフィールド |
| compressed count | `msg.role == "tool" and msg.compressed_content is not None` | Message モデルのフィールド |
| history_runs_limit | `agent.num_history_runs` (= 3) | Agent の設定値 |

#### 表示項目

| 項目 | 表示例 | 備考 |
|---|---|---|
| Source | `last request` / `last run (sum)` | トークン数の取得元を dim テキストで表示。`last request` = per-request 値（正確）、`last run (sum)` = run 累計値（フォールバック）。トークン数が 0 の場合は非表示 |
| History | `5 runs, 23 messages (last 3 in context)` | runs が `num_history_runs` 超のとき注記を付加 |
| Session summary | `active (1,200 chars)` / `none` | `/compact` 後に active になる |
| Compressed | `4 tool results` | 圧縮済みツール結果数（0 の場合は行自体を非表示） |
| Stats | `session:5m 12s  runs:5  LLM:28.3s  avg:5.7s  TTFT:1.23s` | セッション統計（runs=0 かつ累計なしの場合は行自体を非表示）。`--resume` 再開後は `runs:1 (20)` のように現在値 (累計値) を並列表示 |

## 実装対象ファイル

| ファイル | 変更内容 |
|---|---|
| `src/hooty/context.py` | コンテキストファイルの探索・読み込み・合成、`context_fingerprint()` による変更検出 |
| `src/hooty/agent_factory.py` | `load_context()` 呼び出し、`additional_context` パラメータ追加 |
| `src/hooty/commands/session.py` | `/context` スラッシュコマンド（`cmd_context()`） |
| `tests/test_context.py` | **新規作成** — コンテキスト機能のテスト |

### `src/hooty/context.py` の主要インターフェース

```python
def find_project_instructions(project_root: Path) -> Path | None:
    """Search for project instruction file and return its path.

    Searches for AGENTS.md, CLAUDE.md, .github/copilot-instructions.md
    in priority order. If multiple exist, selects the largest file.

    Returns None if no instruction file is found.
    """

def load_context(
    config_dir: Path,
    project_root: Path,
) -> tuple[str | None, ContextInfo]:
    """Load and merge context from global and project instruction files.

    Returns (merged context string or None, ContextInfo).
    """
```

### `agent_factory.py` の変更

```python
from hooty.context import load_context

def create_agent(config, *, plan_mode=False, confirm_ref=None):
    # ... existing code ...

    # Context (additional_context)
    additional_context, _ = load_context(
        config_dir=config.config_dir,
        project_root=Path(config.working_directory),
    )

    return Agent(
        # ... existing parameters ...
        additional_context=additional_context,  # NEW
    )
```
