# LLM プロバイダ仕様書

## 概要

Hooty は以下の 6 つの LLM プロバイダをサポートする:

| プロバイダ | Agno クラス | 主な用途 |
|---|---|---|
| Anthropic | `agno.models.anthropic.Claude` | Claude シリーズ（直接 API / Azure AI Foundry 経由） |
| AWS Bedrock | `agno.models.aws.claude.Claude` / `agno.models.aws.AwsBedrock` | Claude は AwsClaude、その他は AwsBedrock |
| Azure AI Foundry | `agno.models.azure.AzureAIFoundry` | Grok, Llama 4, Phi-4, Mistral 等の非 Claude モデル |
| Azure OpenAI Service | `agno.models.azure.openai_chat.AzureOpenAI` | GPT シリーズ（Azure OpenAI Service デプロイメント） |
| OpenAI | `agno.models.openai.OpenAIChat` | GPT シリーズ（直接 OpenAI API） |
| Ollama | `agno.models.ollama.Ollama` | ローカル LLM（Llama, Qwen, Mistral 等） |

## プロバイダファクトリ

`providers.py` はファクトリパターンで実装する。プロバイダ SDK は遅延インポートする。

```python
def create_model(config: AppConfig) -> Model:
    """設定に基づいて Agno Model インスタンスを生成する"""
```

### 遅延インポート

ユーザーが使用しないプロバイダの SDK がインストールされていなくてもエラーにならないよう、インポートは `create_model()` 内で行う。

```
create_model(config) 呼び出し
    │
    ├── provider == "anthropic"
    │       │
    │       ├── try: from agno.models.anthropic import Claude
    │       │   → 成功: Claude インスタンス生成
    │       │
    │       └── except ImportError:
    │           → "pip install hooty[anthropic] を実行してください" エラー
    │
    ├── provider == "bedrock"
    │       │
    │       ├── Claude モデル ("claude" in model_id):
    │       │   ├── try: from agno.models.aws.claude import Claude (AwsClaude)
    │       │   │   → 成功: AwsClaude インスタンス生成（cache_system_prompt 対応）
    │       │   └── except ImportError: → エラー
    │       │
    │       ├── 非 Claude モデル:
    │       │   ├── try: from agno.models.aws import AwsBedrock
    │       │   │   → 成功: AwsBedrock インスタンス生成
    │       │   └── except ImportError: → エラー
    │       │
    │       └── except ImportError:
    │           → "pip install hooty[aws] を実行してください" エラー
    │
    ├── provider == "azure"
    │       │
    │       ├── try: from agno.models.azure import AzureAIFoundry
    │       │   → 成功: AzureAIFoundry インスタンス生成
    │       │
    │       └── except ImportError:
    │           → "pip install hooty[azure] を実行してください" エラー
    │
    ├── provider == "azure_openai"
    │       │
    │       ├── try: from agno.models.azure.openai_chat import AzureOpenAI
    │       │   → 成功: AzureOpenAI インスタンス生成
    │       │
    │       └── except ImportError:
    │           → "pip install hooty[azure-openai] を実行してください" エラー
    │
    ├── provider == "openai"
    │       │
    │       ├── try: from agno.models.openai import OpenAIChat
    │       │   → 成功: OpenAIChat インスタンス生成
    │       │
    │       └── except ImportError:
    │           → "pip install hooty[openai] を実行してください" エラー
    │
    └── provider == "ollama"
            │
            ├── try: from agno.models.ollama import Ollama
            │   → 成功: Ollama インスタンス生成
            │
            └── except ImportError:
                → "pip install hooty[ollama] を実行してください" エラー
```

## Anthropic

直接 Anthropic API または Azure AI Foundry の Anthropic 互換エンドポイントを介して Claude モデルにアクセスする。`agno.models.anthropic.Claude` クラスを使用し、ネイティブの `messages.count_tokens` API による正確なトークンカウントが利用可能。

### 対応モデル

| モデル | モデル ID | 備考 |
|---|---|---|
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | デフォルト。汎用・高性能 |
| Claude Opus 4.6 | `claude-opus-4-6` | 最上位モデル |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 高速・低コスト |

ユーザーは `profiles` セクションで任意のモデル ID を指定可能。

### 認証方式

#### 1. 直接 Anthropic API

`base_url` 未設定の場合、`api.anthropic.com` に直接接続する。

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Agno への渡し方:

```python
Claude(
    id=config.anthropic.model_id,
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
)
```

#### 2. Azure AI Foundry 経由

`base_url` が設定されている場合、Azure AI Foundry の Anthropic 互換エンドポイントに接続する。

API キーは `AZURE_API_KEY` または `ANTHROPIC_API_KEY` のいずれかを使用可能（`AZURE_API_KEY` 優先、未設定なら `ANTHROPIC_API_KEY` にフォールバック）。

```bash
export ANTHROPIC_API_KEY=your-api-key   # or AZURE_API_KEY
```

```yaml
# config.yaml
providers:
  anthropic:
    base_url: "https://my-resource.services.ai.azure.com/v1/"
```

Agno への渡し方:

```python
Claude(
    id=config.anthropic.model_id,
    api_key=os.environ.get("AZURE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"),
    client_params={"base_url": config.anthropic.base_url},
)
```

### Extended Thinking

Claude モデルは Extended Thinking をサポートするが、API パラメータはモデルにより異なる:

- **Opus 4.6+**: `thinking.type: "adaptive"` + `output_config.effort`（`low`/`medium`/`high`）。`budget_tokens` は非推奨
- **その他の Claude**（Sonnet 4.6 等）: `thinking.type: "enabled"` + `budget_tokens`

`_apply_reasoning()` は `supports_adaptive_thinking(model_id)` でモデルを判定し、適切なパラメータを設定する。adaptive 対応モデルは `request_params` 経由で `output_config` を渡す（Agno の `claude.py` がリクエストにマージ）。

### Structured Outputs 互換性

agno 2.5.10 以降、Claude モデルの structured outputs 判定はプレフィックスベースに改善された（[agno#6643](https://github.com/agno-agi/agno/pull/6643)）。Claude 3.x 系は `NON_STRUCTURED_OUTPUT_PREFIXES = ("claude-3-",)` で非サポート判定、Claude 4.0 の一部エイリアスは `NON_STRUCTURED_OUTPUT_ALIASES` で非サポート判定、それ以外（Claude 4.1 以降）はデフォルトでサポートと判定される。Hooty 側のワークアラウンド（旧 `_fix_structured_outputs_detection()`）は不要になったため削除済み。

### トークンカウント

`agno.models.anthropic.Claude` はネイティブの `messages.count_tokens` API を使用するため、tiktoken の補正ハックが不要。圧縮閾値は **70%**（Bedrock Claude と同等）に設定される。

### 必要パッケージ

```
pip install hooty[anthropic]
# → anthropic がインストールされる
```

## AWS Bedrock

### 対応モデル

| モデル | モデル ID | 備考 |
|---|---|---|
| Claude Sonnet 4.6 | `global.anthropic.claude-sonnet-4-6` | デフォルト。汎用・高性能 |
| Claude 3.5 Haiku | `anthropic.claude-3-5-haiku-20241022-v1:0` | 高速・低コスト |
| Amazon Nova Pro | `amazon.nova-pro-v1:0` | Amazon 独自モデル |
| Mistral Large | `mistral.mistral-large-2402-v1:0` | Mistral 社の大規模モデル |

ユーザーは `profiles` セクションで任意のモデル ID を指定可能。

### 認証方式

4 つの認証方式をサポートする:

#### 1. API キー認証（ベアラートークン）

最も簡単な方法。AWS マネジメントコンソールで API キーを発行し、環境変数に設定する。

```bash
export AWS_BEARER_TOKEN_BEDROCK=your-api-key
export AWS_REGION=us-east-1
```

boto3 が `AWS_BEARER_TOKEN_BEDROCK` 環境変数を自動検出するため、Agno への明示的な認証情報の引き渡しは不要。

```python
AwsBedrock(
    id=config.bedrock.model_id,
    aws_region=config.bedrock.region,
)
```

参考: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html

#### 2. アクセスキー認証（環境変数）

```bash
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
```

Agno への渡し方:

```python
AwsBedrock(
    id=config.bedrock.model_id,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    aws_region=config.bedrock.region,
)
```

#### 3. AWS SSO 認証

事前に `aws configure sso` および `aws sso login` でセットアップ済みの場合:

```yaml
# config.yaml
providers:
  bedrock:
    sso_auth: true
    region: us-east-1
```

Agno への渡し方:

```python
AwsBedrock(
    id=config.bedrock.model_id,
    aws_region=config.bedrock.region,
    aws_sso_auth=True,
)
```

#### 4. デフォルトクレデンシャルチェーン

`AWS_BEARER_TOKEN_BEDROCK`、`AWS_ACCESS_KEY_ID`、`sso_auth` のいずれも未設定の場合、boto3 のデフォルトクレデンシャルチェーン（`~/.aws/credentials`、IAM ロール等）にフォールバックする。

### 必要パッケージ

```
pip install hooty[aws]
# → boto3, aioboto3 がインストールされる
```

## Azure AI Foundry

### 対応モデル

| モデル | モデル ID | 備考 |
|---|---|---|
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | デフォルト。汎用・高性能 |
| Grok 4.1 Fast (推論) | `grok-4-1-fast-reasoning` | 最新。高速推論モード |
| Grok 4.1 Fast (非推論) | `grok-4-1-fast-non-reasoning` | 最新。高速非推論モード |
| Grok 4 | `grok-4` | xAI 推論モデル |
| Grok 4 Fast (推論) | `grok-4-fast-reasoning` | 高速推論モード |
| Grok 4 Fast (非推論) | `grok-4-fast-non-reasoning` | 高速非推論モード |
| Grok 3 | `grok-3` | xAI テキスト生成モデル |
| Grok 3 Mini | `grok-3-mini` | 軽量版 |
| Grok Code Fast | `grok-code-fast-1` | コーディング特化 |
| Llama 4 Maverick | `Llama-4-Maverick-17B-128E-Instruct-FP8` | Meta 社。1M コンテキスト |
| Llama 4 Scout | `Llama-4-Scout-17B-16E-Instruct` | Meta 社。10M コンテキスト |
| Phi-4 | `Phi-4` | Microsoft の小型高性能モデル |
| Phi-3.5 Mini | `Phi-3.5-mini-instruct` | 軽量モデル |
| Llama 3.1 405B | `Meta-Llama-3.1-405B-Instruct` | 大規模モデル |
| Llama 3.1 70B | `Meta-Llama-3.1-70B-Instruct` | 中規模モデル |
| Mistral Large | `Mistral-large` | Mistral 社の大規模モデル |

ユーザーは `profiles` セクションで任意のモデル ID を指定可能。

### 認証方式

#### API キー認証

```bash
export AZURE_API_KEY=your-api-key
export AZURE_ENDPOINT=https://your-resource.models.ai.azure.com
```

Agno への渡し方:

```python
AzureAIFoundry(
    id=config.azure.model_id,
    api_key=os.environ.get("AZURE_API_KEY"),
    azure_endpoint=config.azure.endpoint,
)
```

### エンドポイント

Azure AI Foundry のエンドポイントは Azure Portal で確認する。形式:

```
https://<resource-name>.<region>.models.ai.azure.com
```

`config.yaml` の `endpoint` フィールドまたは環境変数 `AZURE_ENDPOINT` で設定する。

### 必要パッケージ

```
pip install hooty[azure]
# → azure-ai-inference がインストールされる
```

## Azure OpenAI Service

### 対応モデル

| モデル | モデル ID | 備考 |
|---|---|---|
| GPT-5.4 | `gpt-5.4` | 最新。1M コンテキスト |
| GPT-5.4 Pro | `gpt-5.4-pro` | 最新。Pro 版 |
| GPT-5.3 Codex | `gpt-5.3-codex` | コーディング特化 |
| GPT-5.2 | `gpt-5.2` | デフォルト |
| GPT-5.2 Chat | `gpt-5.2-chat` | チャット最適化 |
| GPT-5.1 | `gpt-5.1` | 前世代 |
| GPT-5 | `gpt-5` | GPT-5 シリーズ初代 |

ユーザーは `profiles` セクションで任意のモデル ID を指定可能。

### 認証方式

#### API キー認証

```bash
export AZURE_OPENAI_API_KEY=your-api-key
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
export AZURE_OPENAI_DEPLOYMENT=gpt-5.2-chat
```

Agno への渡し方:

```python
AzureOpenAI(
    id=config.azure_openai.model_id,
    api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
    azure_endpoint=config.azure_openai.endpoint,
    azure_deployment=config.azure_openai.deployment,
    api_version=config.azure_openai.api_version,
)
```

### エンドポイント

Azure OpenAI Service のエンドポイントは Azure Portal で確認する。形式:

```
https://<resource-name>.openai.azure.com
```

`config.yaml` の `endpoint` フィールドまたは環境変数 `AZURE_OPENAI_ENDPOINT` で設定する。

### デプロイメント

Azure OpenAI Service ではモデルを「デプロイメント」として作成する。デプロイメント名は `config.yaml` の `deployment` フィールドまたは環境変数 `AZURE_OPENAI_DEPLOYMENT` で設定する（必須）。

### Reasoning（`reasoning_effort`）対応

GPT-5.2+ は `reasoning_effort` パラメータで推論の深さを制御できる。Hooty は `/reasoning` コマンドのキーワード検出レベルに応じて `low` / `medium` / `high` を設定する。

| `/reasoning` レベル | `reasoning_effort` |
|---|---|
| level1（`think` 等） | `low` |
| level2（`megathink` 等） | `medium` |
| level3（`ultrathink` 等） | `high` |
| auto でキーワードなし | 設定しない（`None`） |

**バリアント別の制約:**

| バリアント | サポートする effort | クランプ動作 |
|---|---|---|
| `-pro`（gpt-5.2-pro 等） | `high` のみ | 全レベルで `high` に固定 |
| `-chat`（gpt-5.3-chat 等） | `medium` のみ | 全レベルで `medium` に固定 |
| その他（gpt-5.2, gpt-5.4 等） | `low` / `medium` / `high` | レベルに応じて設定 |

**動作の違い（Anthropic との比較）:**

| | Anthropic Extended Thinking（Opus 4.6+: adaptive） | Anthropic Extended Thinking（その他: enabled） | Azure OpenAI Reasoning |
|---|---|---|---|
| thinking.type | `adaptive` | `enabled` + `budget_tokens` | — |
| 推論量の制御 | `output_config.effort`（`low`/`medium`/`high`） | `budget_tokens`（4K/10K/30K） | `reasoning_effort`（`low`/`medium`/`high`） |
| ストリーム中の思考テキスト | `reasoning_content` として返る | `reasoning_content` として返る | 返らない |
| ストリーム中インジケーター | `Extended thinking...` | `Extended thinking...` | `Reasoning...`（TTFT 待機中のみ） |
| 完了後のトークン数 | `reasoning_tokens` | `reasoning_tokens` | `completion_tokens_details.reasoning_tokens` |
| フッター表示 | `💭 N chars` / `💭 N chars (💭 M tokens)` | `💭 N chars` / `💭 N chars (💭 M tokens)` | `💭 N tokens` |

**注意:** `reasoning_effort: low` ではモデルが reasoning をスキップすることがあり、`reasoning_tokens=0` になる場合がある。

### 必要パッケージ

```
pip install hooty[azure-openai]
# → openai がインストールされる
```

## OpenAI（直接 API）

### 概要

直接 OpenAI API（`api.openai.com`）を介して GPT モデルにアクセスする。`agno.models.openai.OpenAIChat` クラスを使用。Azure OpenAI Service 経由ではなく、OpenAI の直接 API を使う場合に選択する。

### 対応モデル

| モデル | モデル ID | 備考 |
|---|---|---|
| GPT-5.4 | `gpt-5.4` | 最新。1M コンテキスト |
| GPT-5.4 Pro | `gpt-5.4-pro` | Pro 版 |
| GPT-5.3 Codex | `gpt-5.3-codex` | コーディング特化 |
| GPT-5.2 | `gpt-5.2` | デフォルト |
| GPT-5.2 Chat | `gpt-5.2-chat` | チャット最適化 |
| GPT-5.1 | `gpt-5.1` | 前世代 |
| GPT-5 | `gpt-5` | GPT-5 シリーズ初代 |

ユーザーは `profiles` セクションで任意のモデル ID を指定可能。

### 認証方式

#### API キー認証

```bash
export OPENAI_API_KEY=sk-...
```

Agno への渡し方:

```python
OpenAIChat(
    id=config.openai.model_id,
    api_key=get_secret("OPENAI_API_KEY"),
)
```

### Reasoning（`reasoning_effort`）対応

Azure OpenAI Service と同様、GPT-5.2+ は `reasoning_effort` パラメータで推論の深さを制御できる。動作は Azure OpenAI Service セクションを参照。

### config.yaml 設定例

```yaml
providers:
  openai:
    model_id: gpt-5.2

profiles:
  openai-gpt54:
    provider: openai
    model_id: gpt-5.4
  openai-codex:
    provider: openai
    model_id: gpt-5.3-codex
```

### 必要パッケージ

```
pip install hooty[openai]
# → openai がインストールされる
```

## Ollama（ローカル LLM）

### 概要

ローカルまたは Ollama Cloud で動作する LLM にアクセスする。`agno.models.ollama.Ollama` クラスを使用。

### 対応モデル

Hooty はエージェントフレームワーク（Agno）経由でツール（ファイル操作・シェル実行等）を使用するため、**tools（function calling）をサポートするモデルが必須**。`ollama show <model>` の `Capabilities` に `tools` が含まれていることを確認すること。

> **tools 非対応モデル（使用不可）:** `phi3`, `phi4`, `gemma2` 等 — `does not support tools` エラーになる。

| モデル | モデル ID | コンテキスト長 |
|---|---|---:|
| Qwen 3.5 9B | `qwen3.5:9b` | 262,144 |
| Llama 3.1 8B | `llama3.1:8b` | 131,072 |
| Llama 3.3 70B | `llama3.3:70b` | 131,072 |
| CodeLlama 13B | `codellama:13b` | 16,384 |
| DeepSeek Coder V2 | `deepseek-coder-v2` | 131,072 |
| Qwen 2.5 Coder 7B | `qwen2.5-coder:7b` | 32,768 |
| Mistral | `mistral` | 32,768 |

Ollama のモデル ID はコロン区切りのタグ形式（例: `qwen3.5:9b`, `llama3.1:8b`）。ユーザーは `profiles` セクションで `ollama pull` 済みの任意の **tools 対応** モデルを指定可能。

### 認証方式

#### 1. ローカル（デフォルト）

ローカルの Ollama サーバ（`localhost:11434`）に接続する。認証不要。

```python
Ollama(id=config.ollama.model_id)
```

#### 2. リモートホスト

別マシンの Ollama サーバに接続する場合:

```yaml
# config.yaml
providers:
  ollama:
    model_id: qwen3.5:9b
    host: "http://remote-server:11434"
```

または環境変数:

```bash
export OLLAMA_HOST=http://remote-server:11434
```

#### 3. Ollama Cloud

Ollama Cloud を利用する場合は `host` と `api_key` を設定:

```yaml
providers:
  ollama:
    model_id: qwen3.5:9b
    host: "https://cloud.ollama.com"
    api_key: "olk-..."
```

### コンテキスト長

`model_catalog.json` にモデルごとのコンテキスト長とケーパビリティフラグを登録。カタログに存在しないモデルは保守的なデフォルト値 **8,192** トークンにフォールバック。`max_input_tokens` で明示的に上書き可能。

### config.yaml 設定例

```yaml
providers:
  ollama:
    model_id: qwen3.5:9b
    host: ""                    # empty = localhost:11434
    max_input_tokens: 262144

profiles:
  local-qwen:
    provider: ollama
    model_id: qwen3.5:9b
  local-llama:
    provider: ollama
    model_id: llama3.1:8b
    max_input_tokens: 131072
  local-codellama:
    provider: ollama
    model_id: codellama:13b
    max_input_tokens: 16384
```

### 必要パッケージ

```
pip install hooty[ollama]
# → ollama がインストールされる
```

## トークンカウントと tiktoken 乖離

### 背景

Agno フレームワークはトークンカウントに [tiktoken](https://github.com/openai/tiktoken) (`o200k_base` エンコーディング) を使用する。これは GPT 系モデル用のトークナイザであり、Claude のトークナイザとは異なる。

- **GPT シリーズ（Azure OpenAI / OpenAI）**: tiktoken `o200k_base` は正しいトークナイザのため、乖離なし
- **Claude シリーズ（Bedrock）**: tiktoken は Claude の実トークン数を**常に過小評価**する

### 計測結果

`samples/compare_token_counts.py` により tiktoken と Bedrock Converse API（`usage.inputTokens`）を比較した結果:

| カテゴリ | 内容 | tiktoken | Bedrock 実測 | 乖離率 |
|---|---|---:|---:|---:|
| `english_prose` | 英語技術文書 | 159 | 177 | **-10.2%** |
| `japanese_prose` | 日本語技術文書 | 238 | 299 | **-20.4%** |
| `mixed_text` | 日英混合テキスト | 124 | 164 | **-24.4%** |
| `python_code` | Python ソースコード | 265 | 322 | **-17.7%** |
| `json_schema` | ツール定義 JSON Schema | 223 | 270 | **-17.4%** |
| `conversation` | マルチターン会話 | 312 | 397 | **-21.4%** |
| | | | **平均乖離率** | **-18.6%** |

- 計測モデル: Haiku 4.5, Sonnet 4.5, Sonnet 4.6（全モデルで同一結果 — Claude ファミリーは共通トークナイザ）
- 日本語・日英混合テキストで乖離が最大（-20〜-24%）、英語のみが最小（-10%）

### 現在の対策

`providers.py` で Bedrock Claude の `count_tokens` を基底クラス（tiktoken）にモンキーパッチし、カウント結果に補正係数 ×1.2 を乗算する。`agent_factory.py` の圧縮閾値はコンテキストウィンドウの **70%** で、×1.2 補正込みの Bedrock Claude では実質 **≒84%** で発火する。

### 補正方針

モデル ID に `claude` を含む場合のみ、tiktoken のカウント結果に補正係数 **1.2** を乗算する（`providers.py` のモンキーパッチ内で適用）。

| 条件 | 補正 | 圧縮閾値 | 実質発火点 |
|---|---|---|---|
| Anthropic（直接 / Azure 経由） | なし（ネイティブ API） | 70% | 70% |
| Bedrock + Claude (`"claude" in model_id`) | ×1.2 | 70% | ≒84% |
| Bedrock + その他（Nova, Mistral 等） | なし | 70% | 70% |
| Azure OpenAI + GPT | なし | 70% | 70% |
| OpenAI + GPT | なし | 70% | 70% |
| Ollama | なし | 70% | 70% |

- GPT シリーズ（Azure OpenAI / OpenAI）や Bedrock の非 Claude モデルには補正不要（tiktoken が正確、または乖離が未測定）
- 補正係数はモンキーパッチ内で完結し、Agno 本体に変更なし
- 計測スクリプト: `samples/compare_token_counts.py`

## Prompt Caching

### 概要

マルチターンの会話でシステムプロンプト（instructions + context + memories）を毎回送信するコストを削減するため、Prompt Caching を有効化する。`config.yaml` の `session.cache_system_prompt`（デフォルト `true`）で制御。

- **明示的な `cache_control` 指定が必要なのは Claude 系（Anthropic / Bedrock / Azure AI Foundry 経由 Anthropic SDK）のみ** — `cache_system_prompt=True` によりシステムプロンプトに `cache_control: {"type": "ephemeral"}` が付与される
- **他の全プロバイダ（Azure OpenAI, OpenAI, Azure AI Foundry, Ollama）はサーバー側で自動的にキャッシュが適用される** — コード変更・設定不要
- `cache_system_prompt` は Claude 系にのみ作用し、他プロバイダでは無視される

### プロバイダ別対応状況

| プロバイダ | 制御方式 | キャッシュ制御 | TTL | `cache_read_tokens` | `cache_write_tokens` |
|-----------|---------|-------------|-----|---------------------|----------------------|
| Anthropic Claude | 明示的 | `cache_system_prompt=True` | 5 分（デフォルト） | ✅ | ✅ |
| AWS Bedrock Claude | 明示的 | `cache_system_prompt=True`（AwsClaude 経由） | 5 分（デフォルト） | ✅ | ✅ |
| Azure AI Foundry（`Provider.ANTHROPIC` + `base_url`） | 明示的 | `cache_system_prompt=True` | 5 分（デフォルト） | ✅ | ✅ |
| Azure AI Foundry（`Provider.AZURE`） | 自動 | サーバー側自動（`cache_system_prompt` 非対応） | サーバー依存 | ✅ | ❌ |
| Azure OpenAI | 自動 | サーバー側自動（設定不要） | 最大 24 時間 | ✅ | ❌ |
| OpenAI | 自動 | サーバー側自動（設定不要） | サーバー依存 | ✅ | ❌ |
| Ollama | なし | エンジン内蔵 KV キャッシュ（API 制御不要） | モデルロード中 | ❌ | ❌ |

### プロバイダ別動作詳細

#### Anthropic Claude（直接 API / Azure AI Foundry 経由 Anthropic SDK）

- 明示的オプトイン: `cache_system_prompt=True` によりシステムプロンプトに `cache_control: {"type": "ephemeral"}` が付与される
- TTL: デフォルト 5 分。`extended_cache_time` で 1 時間に延長可能（Agno は対応済みだが Hooty では未対応、将来検討）
- 最小トークン: モデル依存（1,024〜4,096）— 短すぎるシステムプロンプトではキャッシュが作成されない
- コスト: キャッシュ書き込み 1.25x、キャッシュ読み取り 0.1x（基本入力トークン比）
- 2 ターン目以降でキャッシュヒット → 入力トークンコスト大幅削減

#### AWS Bedrock Claude

- Anthropic 直接 API と同等（AwsClaude が Anthropic Claude を継承）
- InvokeModel API 経由で `cache_control` ヘッダーが送信される
- 1 時間 TTL（`extended_cache_time`）は Claude Opus 4.5, Sonnet 4.5, Haiku 4.5 以降で利用可能

#### Azure AI Foundry（Claude / Grok 等）

- **`Provider.AZURE`（`AzureAIFoundry` クラス）:** `azure.ai.inference` SDK 経由のため `cache_system_prompt` **非対応**。Agno の `AzureAIFoundry` クラスにキャッシュ制御パラメータがない。サーバー側の自動キャッシュのみ利用可能
- **`Provider.ANTHROPIC` + `base_url` 設定:** Anthropic SDK 経由のため `cache_system_prompt` **対応**。Azure AI Foundry 上の Claude モデルで明示的キャッシュが必要な場合はこちらを推奨
- Grok-4 等の非 Claude モデルは GPT 同様にサーバー側で自動的にキャッシュが適用される（明示的指定不要）
- `cached_tokens` はレスポンスから読み取り、フッターに表示

#### Azure OpenAI

- 完全自動（コード変更不要、オプトアウト不可）
- 先頭 1,024 トークン + 128 トークン単位でプレフィックスマッチ
- 読み取り割引あり、書き込み追加費用なし
- キャッシュ期間: 最大 24 時間（トラフィック量に応じてエビクション）

#### Ollama

- API レベルのキャッシュ制御なし
- 推論エンジン内蔵の KV キャッシュが自動適用（`keep_alive` でモデルがメモリに残る間有効）
- `cache_system_prompt` 設定は無視される

### Bedrock Claude のクラス選択

Bedrock で Claude モデル（`model_id` に `"claude"` を含む）を使用する場合、`agno.models.aws.claude.Claude`（AwsClaude）を使用する。AwsClaude は `agno.models.anthropic.Claude` を継承しており、`cache_system_prompt` パラメータをサポートする。

非 Claude モデル（Amazon Nova, Mistral 等）は従来どおり `agno.models.aws.AwsBedrock` を使用する。

> **注意:** AwsClaude と AwsBedrock は認証パラメータ名が異なる（`aws_access_key` vs `aws_access_key_id`、`aws_secret_key` vs `aws_secret_access_key`）。SSO 認証は AwsClaude では `boto3.Session()` を渡す方式となる。

### フッター表示

キャッシュトークンはフッターで `»` 記号で表示される。全プロバイダ共通で Agno の `RunMetrics.cache_read_tokens` から取得する。

```
● claude-sonnet-4-6 for 3.2s | ˄12,345 ˅890 »10,200 | ctx 45%
● gpt-5.2 for 2.1s | ˄8,000 ˅500 »6,500 | ctx 30%
```

debug モードでは `cache_write_tokens` も `«` 記号で表示する。

## モデルカタログ

`src/hooty/data/model_catalog.json` にプロバイダ別のモデルメタデータをバンドルする。`scripts/update_model_catalog.py` で LiteLLM のマスターデータから自動生成。`ollama` セクションは手動管理。

### カタログエントリ構造

各モデルエントリは以下のフィールドを持つ dict:

| フィールド | 型 | 説明 |
|---|---|---|
| `max_input_tokens` | `int` | コンテキスト長（必須） |
| `supports_vision` | `bool` | 画像入力（Vision）対応。`True` のみ記録、未記載 = `False` |
| `supports_reasoning` | `bool` | ネイティブ推論（Extended Thinking / Reasoning Effort）対応。`True` のみ記録、未記載 = `False` |
| `supports_function_calling` | `bool` | ツール呼び出し（Function Calling）対応 |
| `supports_response_schema` | `bool` | 構造化出力（Structured Outputs）対応 |

```json
{
  "claude-sonnet-4-6": {
    "max_input_tokens": 200000,
    "supports_vision": true,
    "supports_reasoning": true,
    "supports_function_calling": true,
    "supports_response_schema": true
  }
}
```

### 後方互換性

値が `int` の場合は `{"max_input_tokens": int}` として扱う（移行期間中の安全策）。`_lookup_model_catalog()` の戻り値（`int | None`）は変更なし。

### ケーパビリティの利用箇所

| フラグ | 利用箇所 | フォールバック |
|---|---|---|
| `supports_vision` | `config.supports_vision()` — 画像入力対応の判定 | Anthropic/Bedrock/Azure: model_id に "claude" を含む場合 `True` |
| `supports_reasoning` | `config.supports_thinking()` — `/reasoning` の有効判定 | Anthropic: Haiku 3/3.5 除外リスト、Azure OpenAI: GPT-5.2+ 正規表現 |
| `supports_response_schema` | agno 2.5.10 のプレフィックスベース検出で処理（Hooty 側ワークアラウンド削除済み） | — |
| `supports_function_calling` | 将来利用（現在は情報のみ） | — |

### カタログ更新

```bash
python scripts/update_model_catalog.py              # フル更新（新モデル追加 + 既存更新）
python scripts/update_model_catalog.py --update-only # 既存キーのみ更新
```

LiteLLM から抽出するプロバイダ: `anthropic`, `bedrock`, `azure`, `azure_openai`, `openai`。`ollama` は手動管理。

## 共通仕様

### モデル切り替え

実行中に `/model` コマンドでインタラクティブなプロファイルピッカーを開き、プロバイダを跨いだモデル切り替えができる。切り替え時:

1. ピッカーで選択したプロファイルを `activate_profile()` で有効化
2. バリデーションチェック（認証情報の確認）
3. Agent を再生成
4. セッションは継続（会話履歴は保持）
5. バリデーション失敗時は前のプロファイルに自動復帰

### エラーハンドリング

| エラー種別 | 対応 |
|---|---|
| SDK 未インストール | `ImportError` → インストールコマンドを案内 |
| 認証情報不足 | バリデーションエラー → 必要な設定を案内 |
| API 接続失敗 | ネットワークエラー → リトライなし、エラーメッセージ表示 |
| モデル ID 不正 | API エラー → モデル ID の確認を案内 |
| クォータ超過 | API エラー → レートリミットメッセージ表示 |
