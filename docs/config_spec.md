# 設定仕様書

## 概要

Hooty の設定は複数のソースから読み込まれ、後勝ちでマージされる:

```
~/.hooty/.credentials → ~/.hooty/config.yaml → 環境変数 / .env → CLI 引数 → プロファイル有効化
       (最低)                  (低)                  (中)              (高)
```

## ディレクトリ構成

```
~/.hooty/
├── config.yaml       # メイン設定ファイル
├── hooty.md          # グローバル指示（推奨）
├── instructions.md   # グローバル指示（レガシー互換）
├── databases.yaml    # DB 接続設定ファイル
├── mcp.yaml          # MCP サーバー設定ファイル
├── sessions.db       # セッション履歴（SQLite）
├── memory.db         # グローバル記憶（SQLite）
├── skills/           # グローバルスキルディレクトリ
├── .skills.json      # グローバル extra_paths 状態
├── projects/                              # プロジェクト単位ディレクトリ
│   └── {name}-{hash8}/                    # ディレクトリ名 + SHA-256 先頭8文字
│       ├── memory.db                      # プロジェクト記憶（SQLite）
│       ├── .skills.json                   # スキル個別 ON/OFF 状態
│       ├── .hooks.json                    # フック個別 ON/OFF 状態
│       └── .mcp.json                      # MCP サーバー個別 ON/OFF 状態
├── pkg/                                   # 自動ダウンロードバイナリ
│   └── {arch}-{os}/                       # 例: x86_64-linux, x86_64-windows
│       └── rg[.exe]                       # ripgrep バイナリ
├── sessions/                              # セッション単位ディレクトリ
│   └── {session-id}/
│       ├── workspace.yaml                 # ワークスペースバインド（作業ディレクトリ記録）
│       ├── stats.json                     # セッション統計（累計 runs, LLM 時間等）
│       ├── tmp/                           # 一時ファイル（プロセス出力、truncation 全文）
│       ├── attachments/                   # 添付画像の保存先（リサイズ済み PNG）
│       ├── snapshots/                     # ファイルスナップショット（--snapshot 有効時）
│       │   ├── _index.json               # スナップショットインデックス
│       │   └── {base64url_path}          # 元ファイル内容のコピー
│       └── shell_history.jsonl            # コマンド実行履歴
└── locks/                                 # セッションロック（fcntl.flock ベース）
```

- 初回起動時に `~/.hooty/` ディレクトリを自動作成する
- REPL 起動時にセッション dir（`sessions/{session-id}/tmp/`）を lazy 作成する
- `config.yaml` が存在しない場合はデフォルト値で動作する
- `databases.yaml` が存在しない場合、DB ツールは無効で動作する

## 設定ファイル（config.yaml）

### 完全な構造

```yaml
# ~/.hooty/config.yaml

# デフォルト設定
default:
  profile: sonnet              # 使用するプロファイル名
  stream: true                 # ストリーミング出力: true | false
  debug: false                 # デバッグログ: true | false

# プロバイダ共有ベース設定（接続情報）
providers:
  bedrock:
    region: us-east-1           # AWS リージョン
    sso_auth: false             # AWS SSO 認証を使用するか
    max_input_tokens: 200000    # コンテキストウィンドウ上書き（省略可）
    # api_key は環境変数で設定

  anthropic:
    base_url: ""                # 空 = 直接 Anthropic API、設定 = Azure AI Foundry 経由
    max_input_tokens: 200000    # コンテキストウィンドウ上書き（省略可）
    # api_key は環境変数で設定

  azure:
    endpoint: https://your-endpoint.models.ai.azure.com
    api_version: "2024-05-01-preview"  # 省略可
    max_input_tokens: 128000    # コンテキストウィンドウ上書き（省略可）
    # api_key は環境変数で設定

  azure_openai:
    endpoint: https://your-resource.openai.azure.com
    api_version: "2024-10-21"   # 省略時はデフォルト値
    max_input_tokens: 128000    # コンテキストウィンドウ上書き（省略可）
    # api_key は環境変数で設定

  openai:
    model_id: gpt-5.2           # デフォルトモデル
    max_input_tokens: 128000    # コンテキストウィンドウ上書き（省略可）
    # api_key は環境変数で設定

  ollama:
    model_id: qwen3.5:9b        # デフォルトモデル
    host: ""                    # 空 = localhost:11434
    api_key: ""                 # Ollama Cloud 用（ローカルでは不要）
    max_input_tokens: 262144    # コンテキストウィンドウ上書き（省略可）

# プロファイル定義
profiles:
  sonnet:
    provider: bedrock
    model_id: global.anthropic.claude-sonnet-4-6
  opus:
    provider: bedrock
    model_id: global.anthropic.claude-opus-4-6-v1
  haiku:
    provider: bedrock
    model_id: global.anthropic.claude-haiku-4-5-20251001-v1:0
  claude-direct:
    provider: anthropic
    model_id: claude-sonnet-4-6
  azure-claude:
    provider: anthropic
    model_id: claude-sonnet-4-6
    base_url: "https://my-resource.services.ai.azure.com/v1/"
  azure-sonnet:
    provider: azure
    model_id: claude-sonnet-4-6
  grok4:
    provider: azure
    model_id: grok-4-1-fast-non-reasoning
  gpt52:
    provider: azure_openai
    model_id: gpt-5.2
    endpoint: https://resource-a.openai.azure.com    # プロファイル固有の上書き
    deployment: gpt-5.2
  gpt51:
    provider: azure_openai
    model_id: gpt-5.1
    endpoint: https://resource-b.openai.azure.com    # 別エンドポイント
    deployment: gpt-5.1
  local-qwen:
    provider: ollama
    model_id: qwen3.5:9b
  local-llama:
    provider: ollama
    model_id: llama3.1:8b
    max_input_tokens: 131072

# フクロウ表情設定（省略可）
hooty:
  awake: [9, 21]               # 活動時間帯 [開始, 終了]（両端 inclusive）

# セッション管理（省略可）
session:
  auto_compact: true             # コンテキスト使用率が閾値超過時に自動圧縮
  auto_compact_threshold: 0.7    # 自動圧縮の閾値（70%）

# メモリ設定（省略可）
memory:
  enabled: true                  # メモリ機能の有効/無効

# パッケージマネージャー設定（省略可）
pkg:
  auto_download: true              # true: 自動DL / false: DLしない / 未設定: 初回確認

# ファイルスナップショット設定（省略可）
snapshot:
  enabled: false                 # /diff と /rewind 用のスナップショット追跡

# ファイル添付設定（省略可）
attachment:
  max_files: 20                  # 添付ファイル数の上限
  max_side: 1568                 # 画像リサイズ最大辺（px）
  large_file_tokens: 10000       # テキスト添付の警告閾値（トークン）
  max_total_tokens: 50000        # 全添付合計のハードリミット（トークン）
  context_ratio: 0.25            # コンテキストウィンドウに対する添付上限比率

# Agent Skills 設定（省略可）
skills:
  enabled: true                  # Agent Skills の有効/無効

# Agno フレームワーク設定（省略可）
agno:
  telemetry: false               # Agno テレメトリ送信 (default: false)

# 推論（Reasoning）設定（省略可）
reasoning:
  mode: auto                     # off | on | auto

# LLM API タイムアウト設定（省略可）
api_timeout:
  connect: 30              # TCP 接続確立（秒）
  streaming_read: 180      # ストリーミング時のチャンク間無応答タイムアウト（秒）
  read: 360                # 非ストリーミング時のレスポンス全体待ち（秒）
  write: 30                # リクエスト送信タイムアウト（秒）
  pool: 30                 # コネクションプール接続取得タイムアウト（秒）

# モード別ロール設定（省略可）
roles:
  planning: "You are a senior technical architect."
  coding: "You are a senior software engineer and domain specialist."
```

### 設計ポイント

- `providers:` = プロバイダ共有ベース設定（region, sso_auth, endpoint 等）。同一プロバイダのプロファイル間で共有
- `profiles:` = 名前付きプリセット。`provider` + `model_id` が必須。プロバイダ固有設定のオーバーライドも可能
- プロファイル設定はプロバイダベース設定より優先（profile > providers）
- `default.profile` でデフォルトのプロファイルを指定

### フィールド定義

#### `default` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `profile` | `string` | `""` | 使用するプロファイル名 |
| `stream` | `bool` | `true` | ストリーミング出力の有効化 |
| `debug` | `bool` | `false` | デバッグログの有効化 |

#### `providers.anthropic` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `base_url` | `string` | `""` | エンドポイント URL。空文字 = 直接 Anthropic API、設定 = Azure AI Foundry 経由 |
| `max_input_tokens` | `int` | `null` | コンテキストウィンドウサイズの上書き（省略時は同梱カタログ → 200,000） |

#### `providers.bedrock` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `region` | `string` | `"us-east-1"` | AWS リージョン |
| `sso_auth` | `bool` | `false` | AWS SSO 認証の使用 |
| `max_input_tokens` | `int` | `null` | コンテキストウィンドウサイズの上書き（省略時は同梱カタログ → 200,000） |

#### `providers.azure` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `endpoint` | `string` | （必須） | Azure AI Foundry エンドポイント URL |
| `api_version` | `string` | `null` | API バージョン（省略時は SDK デフォルト） |
| `max_input_tokens` | `int` | `null` | コンテキストウィンドウサイズの上書き（省略時は同梱カタログ → 200,000） |

#### `providers.azure_openai` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `endpoint` | `string` | （必須） | Azure OpenAI Service エンドポイント URL |
| `api_version` | `string` | `"2024-10-21"` | API バージョン |
| `max_input_tokens` | `int` | `null` | コンテキストウィンドウサイズの上書き（省略時は同梱カタログ → 200,000） |

#### `providers.openai` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `model_id` | `string` | `"gpt-5.2"` | OpenAI モデル ID |
| `max_input_tokens` | `int` | `null` | コンテキストウィンドウサイズの上書き（省略時は同梱カタログ → 200,000） |

#### `providers.ollama` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `model_id` | `string` | `"qwen3.5:9b"` | Ollama モデル ID（コロン区切りタグ形式） |
| `host` | `string` | `""` | Ollama サーバーアドレス。空文字 = `localhost:11434` |
| `api_key` | `string` | `""` | Ollama Cloud 用 API キー。空文字 = ローカル（認証不要） |
| `max_input_tokens` | `int` | `null` | コンテキストウィンドウサイズの上書き（省略時は同梱カタログ → 8,192） |

#### `profiles` セクション

各プロファイルは `provider` + `model_id` が必須。プロバイダ固有の設定をオーバーライド可能。

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `provider` | `string` | ✓ | プロバイダ名: `"anthropic"` / `"bedrock"` / `"azure"` / `"azure_openai"` / `"openai"` / `"ollama"` |
| `model_id` | `string` | ✓ | モデル ID |
| `region` | `string` | | Bedrock: AWS リージョンのオーバーライド |
| `endpoint` | `string` | | Azure / Azure OpenAI: エンドポイントのオーバーライド |
| `deployment` | `string` | | Azure OpenAI: デプロイメント名のオーバーライド |
| `api_version` | `string` | | API バージョンのオーバーライド |
| `host` | `string` | | Ollama: サーバーアドレスのオーバーライド |
| `sso_auth` | `bool` | | Bedrock: SSO 認証のオーバーライド |
| `max_input_tokens` | `int` | | コンテキストウィンドウサイズのオーバーライド |
| `base_url` | `string` | | Anthropic: エンドポイント URL のオーバーライド |

#### `roles` セクション

モード別の LLM ロール（人格）を上書きする。未設定の場合はデフォルト値が使用される。片方だけの上書きも可能。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `planning` | `string` | （組み込みデフォルト） | planning モードでの LLM ロール |
| `coding` | `string` | （組み込みデフォルト） | coding モードでの LLM ロール |

```yaml
roles:
  planning: |
    あなたはクラウドインフラに精通したシニアアーキテクトです。
    AWS Well-Architected Framework に基づいた設計を行います。
  coding: |
    あなたは Python と TypeScript のスペシャリストです。
    型安全性とテスタビリティを重視した実装を行います。
```

デフォルト値:

- **planning**: `"You are a senior technical architect. Your responsibility is to analyze requirements, investigate the codebase, and produce clear, actionable design documents and implementation plans."`
- **coding**: `"You are a senior software engineer and domain specialist. Your responsibility is to implement robust, well-tested code changes following the project's conventions and best practices."`

#### `hooty` セクション

フクロウマスコットの表情を制御する時間帯設定。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `awake` | `list[int, int]` | `[9, 21]` | 活動時間帯 `[開始時, 終了時]`（両端 inclusive、0-23）|

`awake: [9, 21]` の場合:
- **8 時** (開始 − 1): squinting `=`（目覚め）
- **9-21 時**: wide open `o`（活動中）
- **22 時** (終了 + 1): squinting `=`（眠くなる）
- **23-7 時**: sleepy `ᴗ`

バリデーション: 2 要素リスト、各要素 0-23、start < end、差が 2 以上。不正値の場合はデフォルト `[9, 21]` にフォールバック。

```yaml
hooty:
  awake: [6, 18]   # 早起きフクロウ
```

#### `session` セクション

コンテキストウィンドウの自動管理に関する設定。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `auto_compact` | `bool` | `true` | コンテキスト使用率が閾値を超えたとき自動でセッション履歴を圧縮する |
| `auto_compact_threshold` | `float` | `0.7` | auto-compact のトリガー閾値（0.0–1.0、コンテキストウィンドウの使用率） |
| `cache_system_prompt` | `bool` | `true` | **Claude 系プロバイダ専用**。Anthropic / Bedrock Claude モデルのシステムプロンプトに `cache_control: {"type": "ephemeral"}` を付与し、2ターン目以降でキャッシュヒット（読み取りコスト 0.1x）する。Azure AI Foundry 経由で Claude を使う場合、`Provider.ANTHROPIC` + `base_url` 設定時のみ有効（`Provider.AZURE` 経由では SDK 制約により無効）。**他の全プロバイダ（Azure OpenAI, OpenAI, Azure AI Foundry の非 Claude モデル, Ollama）はサーバー側で自動的にキャッシュが適用されるため、本設定は無視される** |
| `resume_history` | `int` | `1` | `--resume` / `--continue` でセッション復元時に再表示する過去 Q&A ペアの件数。`0` で無効化 |

```yaml
session:
  auto_compact: true
  auto_compact_threshold: 0.7   # 70% で自動圧縮
  cache_system_prompt: true      # Claude 系プロバイダ専用。他プロバイダはサーバー側自動キャッシュ
  resume_history: 1              # 復元時に表示する過去 Q&A 件数（0=無効）
```

#### `memory` セクション

セッションを跨いだ記憶の永続化に関する設定。詳細は `docs/memory_spec.md` を参照。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `true` | メモリ機能の有効/無効 |

```yaml
memory:
  enabled: true
```

有効時、二層の SQLite データベースで記憶を管理する:

- **グローバル記憶**: `~/.hooty/memory.db` — ユーザー嗜好やワークフロー設定
- **プロジェクト記憶**: `~/.hooty/projects/{name}-{hash8}/memory.db` — プロジェクト固有の設計判断・規約

プロジェクトディレクトリ名は `ワーキングディレクトリ末尾名-SHA256先頭8文字` で一意に導出される。

#### `snapshot` セクション

ファイルスナップショット追跡の制御。LLM によるファイル変更を追跡し、`/diff` で差分表示、`/rewind` で巻き戻しを可能にする。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `false` | スナップショット追跡の有効/無効 |

```yaml
snapshot:
  enabled: true
```

CLI 引数 `--snapshot` / `--no-snapshot` で起動時に上書き可能（CLI > config.yaml）。無効時は `/diff` と `/rewind` は disabled メッセージを表示する。

#### `attachment` セクション

`/attach` コマンドによるファイル添付の制御。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `max_files` | `int` | `20` | 添付ファイル数の上限 |
| `max_side` | `int` | `1568` | 画像リサイズの最大辺（px）。Claude 推奨値 |
| `large_file_tokens` | `int` | `10000` | テキスト添付時の警告閾値（推定トークン数） |
| `max_total_tokens` | `int` | `50000` | 全添付合計のハードリミット（推定トークン数） |
| `context_ratio` | `float` | `0.25` | コンテキストウィンドウに対する添付上限比率 |

```yaml
attachment:
  max_files: 20
  max_side: 1568
  large_file_tokens: 10000
  max_total_tokens: 50000
  context_ratio: 0.25
```

実効ハードリミットは `min(max_total_tokens, context_limit × context_ratio)` で計算される。画像は添付時に即座にリサイズされ、セッションディレクトリ（`sessions/{id}/attachments/`）に PNG で保存される。

#### `skills` セクション

Agent Skills の全体制御。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `true` | Agent Skills 機能の有効/無効 |

```yaml
skills:
  enabled: true
```

CLI 引数 `--no-skills` で起動時に無効化可能（`skills.enabled = false` と同等）。実行中は `/skills on` / `/skills off` でトグルできる。

個別スキルの ON/OFF 状態は `~/.hooty/projects/{slug}/.skills.json` に永続化される。

#### `agno` セクション

Agno フレームワークの動作制御。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `telemetry` | `bool` | `false` | Agno テレメトリ送信の有効/無効 |

```yaml
agno:
  telemetry: false    # Agno テレメトリ送信 (default: false)
```

メインエージェント・サブエージェントの両方に適用される。

#### `reasoning` セクション

ネイティブ推論の制御。モデルカタログの `supports_reasoning` フラグで対応モデルを判定する（プロバイダ非依存）。カタログ未登録モデルは以下のフォールバックルールで判定:

- **Anthropic**（直接 API / Azure AI Foundry 経由）: Extended Thinking（`model.thinking`）。Haiku 3/3.5 を除く Claude モデル
- **Azure OpenAI / OpenAI**: Reasoning Effort（`model.reasoning_effort`）。GPT-5.2 以降（バリアント含む: chat, codex, pro, mini 等）
- **Bedrock / Azure AI Foundry**: カタログに `supports_reasoning: true` があるモデル（Claude, Grok reasoning 系等）

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `mode` | `string` | `"auto"` | 推論モード: `off`（無効）/ `on`（常時有効）/ `auto`（キーワード検出時のみ有効） |
| `auto_level` | `int` | `1` | auto モードでキーワードなし時のデフォルトレベル（0=推論なし, 1-3） |
| `keywords` | `dict` | （組み込みデフォルト） | レベル別キーワードの上書き（省略時は組み込みデフォルト使用） |

```yaml
reasoning:
  mode: auto
  keywords:
    level1: ["think", "考えて"]
    level2: ["think hard", "megathink", "よく考えて"]
    level3: ["ultrathink", "熟考"]
```

##### 3 レベルシステム

ユーザーのメッセージ内のキーワードに応じて、リクエスト単位で推論レベルを動的に設定する。Anthropic / OpenAI 両方で同じ UX を提供するため、プロバイダ非依存の 3 レベルに統一している。

**モード動作:**

| モード | キーワードなし | キーワードあり |
|--------|--------------|--------------|
| `off` | 推論無効 | 推論無効 |
| `on` | level2（デフォルト）で常時有効 | キーワードのレベルで有効 |
| `auto` | 推論無効（コスト節約） | キーワードのレベルで有効 |

**レベル → プロバイダ別パラメータ変換:**

| Level | Anthropic Opus 4.6+（`adaptive` + `effort`） | Anthropic その他（`enabled` + `budget_tokens`） | Azure OpenAI (`reasoning_effort`) |
|-------|----------------------------------------------|------------------------------------------------|-----------------------------------|
| `level1` | `low` | 4,000 | `low` |
| `level2` | `medium` | 10,000 | `medium` |
| `level3` | `high` | 30,000 | `high` |

> **注意:** Opus 4.6+ では `thinking.type: "adaptive"` + `output_config.effort` を使用する。Sonnet 等その他の Claude モデルは従来の `thinking.type: "enabled"` + `budget_tokens` を維持する。
>
> **注意:** GPT-5.2-pro 等の `-pro` バリアントは `high` のみサポートのため、全レベルで `high` にクランプされる。`-chat` バリアント（gpt-5.3-chat 等）は `medium` のみサポートのため、全レベルで `medium` にクランプされる。

**キーワード → レベルマッピング:**

| Level | デフォルトキーワード |
|-------|---------------------|
| `level1` | `think`, `考えて` |
| `level2` | `think a lot`, `think deeply`, `think hard`, `think more`, `megathink`, `もっと考えて`, `たくさん考えて`, `よく考えて`, `長考` |
| `level3` | `think harder`, `think longer`, `think really hard`, `think very hard`, `ultrathink`, `熟考`, `深く考えて`, `しっかり考えて` |

検出順は最も長いキーワードから先にマッチする（例: `think harder` は `think hard` より先に検出）。

**キーワードのカスタマイズ:**

`config.yaml` の `reasoning.keywords` で各レベルのキーワードを**置き換え**（マージではない）できる。省略したレベルは組み込みデフォルト（`src/hooty/data/thinking_keywords.yaml`）を使用する。

```yaml
reasoning:
  mode: auto
  keywords:
    level1: ["think", "考えて"]           # level1 のみ置き換え
    # level2, level3 は省略 → デフォルト
```

##### ストリーミング表示

推論中のインジケーターテキストはプロバイダにより異なる:

| 状態 | Anthropic | Azure OpenAI |
|---|---|---|
| 推論中 | `"Extended thinking..."` | `"Reasoning..."` |
| 推論完了サマリー | `"💭 Extended thinking (N chars)"` | `"💭 Reasoning (N chars)"` |

> **注意:** Azure OpenAI は reasoning トークンをストリームで返さないため、インジケーターが表示されない場合がある。推論自体はサーバー側で実行されている。

##### その他

- CLI 引数 `--reasoning on` / `--reasoning auto` で起動時に有効化可能
- 環境変数 `HOOTY_REASONING=on|auto|true` でも設定可能
- 実行中は `/reasoning` コマンドでモード切替（`/reasoning [on|off|auto]`）
- `on` / `auto` モードでも、非対応モデルでは自動的に inactive になる
- mode はユーザーの意図として保持され、`/model` で対応モデルに切替えると自動的に active に戻る
- 推論はネイティブ推論のみを使用する（ReasoningTools CoT フォールバックは廃止済み）。`/reasoning` トグルは `_reasoning_active` を更新し、`_apply_reasoning()` が run ごとにモデルパラメータを動的に設定する
- Opus 4.6+ では `thinking.type: "adaptive"` + `output_config.effort` を使用し、その他の Claude モデルでは従来の `thinking.type: "enabled"` + `budget_tokens` を使用する。判定は `supports_adaptive_thinking()` による model_id の正規表現マッチ

#### `pkg` セクション

パッケージマネージャーの制御。ripgrep 等の外部バイナリの自動ダウンロードを管理する。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `auto_download` | `bool \| null` | `null`（未設定） | `true`: 不足パッケージを自動ダウンロード。`false`: ダウンロードしない。未設定: 初回起動時にダイアログで確認し結果を保存 |

```yaml
pkg:
  auto_download: true
```

ダウンロードされたバイナリは `~/.hooty/pkg/{arch}-{os}/` に配置される。REPL 起動時に不足パッケージがある場合、設定に応じてダイアログ表示または自動ダウンロードが行われる。

#### `api_timeout` セクション

LLM API の HTTP タイムアウトを全プロバイダ共通で設定する。ストリーミングと非ストリーミングで read タイムアウトを分離し、ハングした接続を適切な時間で検知する。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `connect` | `int` | `30` | TCP 接続確立タイムアウト（秒） |
| `streaming_read` | `int` | `180` | ストリーミング時のチャンク間無応答タイムアウト（秒）。ストリーミングでは各チャンク受信でタイマーがリセットされるため、この値は「最初のチャンクまでの最大待ち時間」に等しい |
| `read` | `int` | `360` | 非ストリーミング時のレスポンス全体待ちタイムアウト（秒） |
| `write` | `int` | `30` | リクエスト送信タイムアウト（秒）。ペイロードはチャンク分割送信されるため、各チャンクの書き込みに適用される |
| `pool` | `int` | `30` | コネクションプールからの接続取得タイムアウト（秒） |

**ストリーミング vs 非ストリーミング:**

- ストリーミング（`stream: true`、デフォルト）: `streaming_read` が適用される。サーバーがチャンクを送信するたびにタイマーがリセットされるため、正常な応答では長くても数秒の沈黙しか発生しない。180 秒の無応答はサーバー側のハング（コールドスタート、キュー待ち等）を示唆する
- 非ストリーミング（`stream: false`）: `read` が適用される。サーバーがレスポンス全体を生成し終わるまで待つため、長めの値が必要

**プロバイダ別の適用方法:**

| プロバイダ | SDK | 適用方法 |
|---|---|---|
| Anthropic 直接 / Azure AI Foundry | anthropic SDK | `httpx.Timeout` via `client_params` |
| AWS Bedrock (Claude) | anthropic SDK | 同上 |
| AWS Bedrock (非 Claude) | boto3 | `botocore.config.Config` |
| Azure OpenAI | openai SDK | `httpx.Timeout` via `client_params` |
| OpenAI | openai SDK | `httpx.Timeout` via `client_params` |
| Ollama | ollama | 未適用（ローカル実行） |

サブエージェントは常にストリーミングモード（`stream: true`）で実行されるため、`streaming_read` が適用される。

#### `tools` セクション

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `allowed_commands` | `list[string]` | `[]` | シェル実行で追加許可するコマンド名のリスト |
| `shell_operators` | `object` | （下記参照） | シェル演算子の許可/ブロック制御 |
| `shell_timeout` | `int` | `120` | シェルコマンドの最大実行時間（秒） |
| `idle_timeout` | `int` | `0` | 無出力タイムアウト（秒、0=無効）。指定秒数出力がなければプロセスを kill する |
| `ignore_dirs` | `list[string]` | `[]` | ls/find/grep/tree で追加除外するディレクトリ名のリスト。`.gitignore` から自動抽出されるディレクトリに加えて追加される |
| `mcp_debug` | `bool` | `false` | MCP サーバーの stderr をそのまま端末に表示する（`--mcp-debug` CLI フラグと同等）。`false` の場合、stderr は `logger.debug` にリダイレクトされ `--debug` 時のみ表示される |

CodingTools と PowerShellTools の両方に適用される。組み込みの開発ツールコマンド（`git`, `python`, `node` 等）に加えて、ユーザー固有のコマンドを許可できる。

```yaml
tools:
  allowed_commands:
    - terraform
    - kubectl
    - helm
    - ansible
  shell_operators:
    pipe: true          # | をセグメント検証付きで許可（デフォルト: true）
    chain: true         # && || ; をセグメント検証付きで許可（デフォルト: true）
    redirect: false     # > >> < を許可（デフォルト: false）
  shell_timeout: 600     # 10分（巨大ビルド向け）
  idle_timeout: 60       # 60秒出力なしで kill
  ignore_dirs:
    - .zig-cache
    - zig-out
    - .terraform
  mcp_debug: false       # true で MCP stderr を端末に直接表示
```

**`shell_operators` フィールド:**

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `pipe` | `bool` | `true` | パイプ（`\|`）を許可。各セグメントの先頭コマンドを許可リストで個別検証 |
| `chain` | `bool` | `true` | チェーン（`&&`, `\|\|`, `;`）を許可。各セグメントの先頭コマンドを許可リストで個別検証 |
| `redirect` | `bool` | `false` | リダイレクト（`>`, `>>`, `<`）を許可。`2>&1` / `N>/dev/null` は安全パターンとして常時許可 |

コマンド置換（`$(...)`, `` `...` ``）は許可リスト検証をバイパスするため、設定に関わらず常時ブロックされる。

**タイムアウト動作:**

- `shell_timeout`: コマンドの実行時間が指定秒数を超えるとプロセスを終了する。デフォルト 120 秒。
- `idle_timeout`: 出力がなく指定秒数が経過するとハングしたプロセスと判断して kill する。0 で無効（デフォルト）。有効時はプロセス出力を一時ファイルにリダイレクトし、`os.path.getsize()` でポーリングして出力の有無を検出する。

**コマンド実行履歴:**

`idle_timeout` や `shell_timeout` の有無に関わらず、シェルコマンド実行ごとにセッションディレクトリの `shell_history.jsonl` に記録が追記される。各エントリには以下が含まれる:

- `timestamp`: 実行時刻（UTC ISO 8601）
- `command`: 実行コマンド
- `returncode`: 終了コード
- `duration_seconds`: 実行時間（秒）
- `timed_out` / `idle_timed_out`: タイムアウトフラグ
- `output_file`: 大きい出力の保存先パス（該当時のみ）

## MCP サーバー設定ファイル（mcp.yaml）

`~/.hooty/mcp.yaml`（グローバル）および `<working_dir>/.hooty/mcp.yaml`（プロジェクト固有）で MCP サーバー接続を管理する。両方が存在する場合、プロジェクト側が後勝ちでマージされる（同名サーバーはプロジェクト側が上書き、プロジェクト固有サーバーは追加）。

### 構造

```yaml
# ~/.hooty/mcp.yaml

servers:
  # stdio 接続の例
  filesystem:
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - /home/user/projects
    env:
      MCP_LOG_LEVEL: debug
    timeout: 30           # 接続・ツール実行タイムアウト（秒、省略時 30）

  # URL 接続の例（Streamable HTTP — デフォルト）
  my-server:
    url: http://localhost:8080/mcp
    timeout: 60

  # URL 接続の例（レガシー SSE）
  legacy-server:
    url: http://localhost:8080/sse
    transport: sse

  # URL 接続 + 認証ヘッダー
  authed-api:
    url: https://api.example.com/mcp
    headers:
      Authorization: Bearer <token>
      X-Custom-Header: value
```

`servers` キー配下に各 MCP サーバーを名前付きで定義する。接続方式により異なるフィールドを使用する。

**stdio 接続:**

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `command` | `string` | （必須） | 実行コマンド |
| `args` | `list[string]` | `[]` | コマンド引数 |
| `env` | `dict[string, string]` | `null` | 追加の環境変数（省略可） |
| `timeout` | `int` | `30` | 接続・ツール実行タイムアウト（秒） |

**URL 接続（Streamable HTTP / SSE）:**

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `url` | `string` | （必須） | MCP サーバーの URL |
| `transport` | `string` | `"http"` | トランスポート種別: `"http"`（streamable-http）または `"sse"`。`"streamable-http"` も後方互換で受け付ける |
| `headers` | `dict[string, string]` | `null` | HTTP ヘッダー（認証トークン等）。指定時は `SSEClientParams` / `StreamableHTTPClientParams` 経由で Agno に渡される |
| `timeout` | `int` | `30` | 接続・ツール実行タイムアウト（秒） |

### プロジェクト固有設定

プロジェクトのワーキングディレクトリに `<working_dir>/.hooty/mcp.yaml` を配置すると、そのプロジェクト固有の MCP サーバーを定義できる。フォーマットはグローバル `mcp.yaml` と同一。

```yaml
# <project>/.hooty/mcp.yaml
servers:
  project-playwright:
    command: npx
    args: ["-y", "@anthropic-ai/mcp-server-playwright"]
  project-db:
    url: http://localhost:3000/mcp
```

**マージ戦略（Agents パターン — dict 置換・後勝ち）:**

1. グローバル `~/.hooty/mcp.yaml` をベースにロード
2. プロジェクト `<working_dir>/.hooty/mcp.yaml` で上書きマージ
   - 同名サーバー: プロジェクト側の定義で完全置換
   - プロジェクト固有サーバー: 追加

**ソース表示:** `/mcp list` で各サーバーの定義元（`global` / `project`）が表示される。

### 個別 ON/OFF 状態

サーバー個別の有効/無効状態は `~/.hooty/projects/<slug>/.mcp.json` に永続化される。Skills（`.skills.json`）・Hooks（`.hooks.json`）と同じパターン。

- `/mcp`（引数なし）でインタラクティブピッカーを表示し、サーバーの有効/無効を切り替えられる
- 無効化されたサーバーは `/mcp list` で dim 表示される

### ツール名前空間

MCP ツールは `mcp__{サーバー名}__{ツール名}` 形式で LLM に公開される。Claude Code が確立し Docker MCP Gateway・MetaMCP が採用する業界標準パターン。

**目的:** 組み込みツール（`read_file`, `edit_file` 等）との名前衝突を回避する。

**例:** `mcp.yaml` のキー名がそのまま名前空間になる:

```yaml
servers:
  filesystem:       # → mcp__filesystem__read_file, mcp__filesystem__search_files, ...
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user]
  playwright:       # → mcp__playwright__navigate, mcp__playwright__screenshot, ...
    command: npx
    args: [-y, "@anthropic-ai/mcp-server-playwright"]
```

同じ MCP サーバーを異なるスコープで複数使いたい場合は、キー名を変えて名前空間を分離する:

```yaml
# グローバル mcp.yaml
servers:
  filesystem:             # → mcp__filesystem__read_file（/home/user/documents）
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/documents]

# プロジェクト mcp.yaml
servers:
  project-fs:             # → mcp__project_fs__read_file（プロジェクトディレクトリ）
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /mnt/d/project]
```

> **注意:** サーバー名にハイフン `-` を含む場合、ツール名では `_` に正規化される（例: `project-fs` → `mcp__project_fs__`）。これは MCP 仕様のツール名文字制約（`^[a-zA-Z0-9_-]{1,64}$`）との整合性による。

## データベース設定ファイル（databases.yaml）

`config.yaml` とは別のファイル `~/.hooty/databases.yaml` で SQL データベース接続を管理する。

### 構造

```yaml
# ~/.hooty/databases.yaml

databases:
  local: "sqlite:///./data/app.db"
  analytics: "postgresql://admin:secret@localhost:5432/mydb"
  staging: "mysql://user:pass@host/db"
```

`databases` キー配下に `名前: SQLAlchemy接続URL` のフラットなマッピングで定義する。

### 管理

databases.yaml はスラッシュコマンドで管理する:

| コマンド | 説明 |
|---|---|
| `/database list` | 登録済み DB 一覧を表示 |
| `/database connect <name>` | 指定 DB に接続 |
| `/database disconnect` | DB 接続を解除 |
| `/database add <name> <url>` | DB 接続を追加（databases.yaml に保存） |
| `/database remove <name>` | DB 接続を削除（databases.yaml から削除） |

## 環境変数

### シークレット（API キー等）

シークレットは **YAML に書かず**、環境変数または `.env` ファイルで管理する。

| 環境変数 | 対応する設定 | 説明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API キー | Anthropic API の認証キー（直接 API / Azure 経由 共通） |
| `ANTHROPIC_BASE_URL` | `providers.anthropic.base_url` | Anthropic エンドポイント URL のオーバーライド |
| `AWS_BEARER_TOKEN_BEDROCK` | Bedrock API キー | Bedrock のベアラートークン認証（最も簡単） |
| `AWS_ACCESS_KEY_ID` | AWS アクセスキー | Bedrock のアクセスキー認証 |
| `AWS_SECRET_ACCESS_KEY` | AWS シークレットキー | Bedrock のアクセスキー認証 |
| `AWS_REGION` | `providers.bedrock.region` | AWS リージョン |
| `AZURE_API_KEY` | Azure API キー | Azure AI Foundry の認証キー |
| `AZURE_ENDPOINT` | `providers.azure.endpoint` | Azure AI Foundry エンドポイント URL |
| `AZURE_API_VERSION` | `providers.azure.api_version` | Azure AI Foundry API バージョン |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API キー | Azure OpenAI Service の認証キー |
| `AZURE_OPENAI_ENDPOINT` | `providers.azure_openai.endpoint` | Azure OpenAI Service エンドポイント URL |
| `AZURE_OPENAI_DEPLOYMENT` | `providers.azure_openai.deployment` | Azure OpenAI デプロイメント名 |
| `AZURE_OPENAI_API_VERSION` | `providers.azure_openai.api_version` | Azure OpenAI API バージョン |
| `OPENAI_API_KEY` | OpenAI API キー | OpenAI 直接 API の認証キー |
| `OLLAMA_HOST` | `providers.ollama.host` | Ollama サーバーアドレス |
| `GITHUB_ACCESS_TOKEN` | GitHub トークン | GitHub API の認証 |

### アプリケーション設定

| 環境変数 | 対応する設定 | 説明 |
|---|---|---|
| `HOOTY_PROFILE` | `default.profile` | 使用するプロファイル名 |
| `HOOTY_DEBUG` | `default.debug` | デバッグモード |
| `HOOTY_REASONING` | `reasoning.mode` | 推論モード（`on` / `auto` / `true` → on） |

### `.env` ファイル

プロジェクトルートまたはカレントディレクトリに `.env` ファイルを配置可能。`python-dotenv` で自動読み込みする。

```bash
# .env
AZURE_API_KEY=your-api-key-here
GITHUB_ACCESS_TOKEN=ghp_xxxxxxxxxxxx
AWS_REGION=us-west-2
```

## CLI 引数による上書き

CLI 引数は全ての設定を上書きする（最高優先度）。

| CLI 引数 | 上書き対象 |
|---|---|
| `--profile <name>` | 使用するプロファイル |
| `--dir <path>` | 作業ディレクトリ |
| `--debug` | `default.debug` = `true` |
| `--no-stream` | `default.stream` = `false` |
| `--no-skills` | `skills.enabled` = `false` |
| `--snapshot` | `snapshot.enabled` = `true` |
| `--no-snapshot` | `snapshot.enabled` = `false` |
| `--attach <path>` | 起動時にファイルを添付スタックに追加（複数指定可、CWD 基準で resolve） |

## 設定読み込みの処理フロー

```
1. デフォルト値で AppConfig を初期化
       │
       ▼
2. ~/.hooty/.credentials を読み込み（存在する場合）
   プロバイダ設定 + プロファイル + 環境変数を適用
   ※ 有効期限切れの場合は CredentialExpiredError で即座に終了
       │
       ▼
3. ~/.hooty/config.yaml を読み込み（存在する場合）
   providers, profiles, default.profile 等を上書き
       │
       ▼
4. .env ファイルを読み込み（python-dotenv）
       │
       ▼
5. 環境変数を読み込み
   HOOTY_PROFILE, HOOTY_DEBUG 等を上書き
       │
       ▼
6. CLI 引数を適用
   --profile, --debug, --no-stream 等を上書き
       │
       ▼
7. プロファイル有効化
   active_profile が設定されていれば activate_profile() を実行
       │
       ▼
8. セットアップ存在チェック
   - config.yaml と .credentials の両方が存在しない場合、
     セットアップ案内メッセージを表示して終了
   - 片方でも存在すれば次のステップへ進む
       │
       ▼
9. バリデーション
   - 選択プロバイダに必要な認証情報が揃っているか確認
   - 不足がある場合はエラーメッセージを表示して終了
```

## バリデーションルール

| プロバイダ | 必須項目 |
|---|---|
| `anthropic` | `ANTHROPIC_API_KEY`（`base_url` 設定時は `AZURE_API_KEY` も可） |
| `bedrock` | `AWS_BEARER_TOKEN_BEDROCK`、または `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`、または `sso_auth: true` |
| `azure` | `AZURE_API_KEY` + `endpoint`（YAML または `AZURE_ENDPOINT`） |
| `azure_openai` | `AZURE_OPENAI_API_KEY` + `endpoint` + `deployment`（YAML または環境変数） |
| `openai` | `OPENAI_API_KEY` |
| `ollama` | なし（ローカル実行のため認証不要） |

バリデーション失敗時のメッセージ例:

```
✗ AWS Bedrock の認証情報が不足しています。
  以下のいずれかを設定してください:
  - 環境変数 AWS_BEARER_TOKEN_BEDROCK を設定（API キー認証）
  - 環境変数 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY を設定
  - config.yaml で sso_auth: true を設定
```
