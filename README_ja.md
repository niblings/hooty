# Hooty

対話型 AI コーディングアシスタント CLI。[Agno](https://github.com/agno-agi/agno) フレームワーク上に構築。

```
   ,___,
   (o,o)    Hooty
   /)  )    Interactive AI coding assistant
  --""--    powered by Agno
```

## 特徴

- **REPL 対話型インターフェース** — Rich ベースのターミナル UI、マークダウンストリーミング表示、Planning / Coding の 2 モード切替
- **Non-Interactive モード** — `hooty -p "プロンプト"` で単発実行。パイプ入力にも対応し、スクリプトや CI/CD から利用可能
- **マルチプロバイダ対応** — Anthropic / Azure AI Foundry / Azure OpenAI / OpenAI / AWS Bedrock / Ollama の 6 プロバイダをサポート。`/model` でセッション中のモデル切替が可能
- **コーディングツール** — ファイル読み書き・編集、シェル実行、コード探索（grep / find / ls）を内蔵。Safe モード（デフォルト ON）で危険な操作に確認ダイアログを表示
- **コンテキストファイル** — グローバル指示（`~/.hooty/hooty.md`）とプロジェクト固有指示（`AGENTS.md` / `CLAUDE.md` 等）で LLM へのカスタム指示を追加。他ツールの指示書とも互換
- **セッション管理** — 会話履歴の永続化・復元・フォーク、コンテキストウィンドウの自動圧縮
- **プロジェクトメモリ** — 設計判断やコーディング規約をプロジェクト単位で記憶し、セッションを跨いで活用
- **外部連携** — GitHub ツール、DuckDuckGo Web 検索、SQL データベース接続
- **MCP サーバー連携** — Model Context Protocol サーバーによるツール拡張
- **Agent Skills** — オープン標準準拠のスキルパッケージでエージェントの専門知識を拡張。プロジェクト固有の規約やワークフローをスキルとして定義し、必要時にオンデマンドでロード（Progressive Discovery）
- **Sub-agents（サブエージェント）** — 複雑なタスクを独立コンテキストのサブエージェントに自動委譲。ビルトイン（`explore` / `implement` / `test-runner` / `assistant` / `web-researcher` / `summarize`）に加え、`agents.yaml` でカスタムエージェントを定義可能。`implement` は edit-test-fix サイクルを隔離コンテキストで実行、`test-runner` はテスト失敗の自動診断・修正、`assistant` は非コーディングタスク（ドキュメント作成・データ分析・ファイル整理）、`web-researcher` は深い Web 調査を実行し、親エージェントのコンテキスト肥大化を防止
- **Hooks（ライフサイクルフック）** — セッション開始・LLM 応答・ツール実行などのイベントでシェルコマンドを自動トリガー。ブロック判定や LLM へのコンテキスト注入も可能
- **ファイルスナップショット** — セッション中の LLM によるファイル変更を自動追跡。`/diff` で差分表示、`/rewind` で巻き戻し
- **Extended Thinking（拡張思考）** — `/reasoning` で Claude の拡張思考を制御。`auto` モードではメッセージ内のキーワード（`think`, `ultrathink`, `熟考` 等）に応じて thinking budget を 3 段階で動的に調整
- **コードレビュー** — `/review` でインタラクティブなコードレビューと自動修正
- **ファイル添付** — `/attach` で画像・テキストファイルをプロンプトに添付。クリップボードペースト（`/attach paste`）、スクリーンキャプチャ（`/attach capture`、Windows / WSL2）にも対応。`--attach` CLI オプションで起動時の事前添付も可能

## インストール

パッケージ管理には [uv](https://docs.astral.sh/uv/) を使用する。

```bash
# uv のインストール（未導入の場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存関係インストール（全エクストラ + 開発ツール）
uv sync --all-extras
```

## セットアップ

`~/.hooty/config.yaml` を編集してプロバイダやモデルを設定する:

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

API キーは環境変数で設定する（例: `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY`）。詳細は[設定仕様書](docs/config_spec.md)を参照。

```bash
# 対話形式でクレデンシャルをセットアップ
hooty setup

# セットアップ状態を確認
hooty setup show
```

## 使い方

```bash
# 起動
hooty

# プロファイル指定
hooty --profile <name>

# 作業ディレクトリ指定
hooty --dir ~/my-project

# セッション復元（インタラクティブ選択）
hooty --resume

# 直近セッションを継続
hooty --continue

# 非対話モード（単発実行）
hooty -p "テストを全部通して"
cat prompt.md | hooty --unsafe > result.md
```

## スラッシュコマンド

| コマンド | 説明 |
|---|---|
| `/help` | コマンド一覧を表示 |
| `/quit` | 終了 |
| `/model` | モデルプロファイルを切り替え |
| `/session` | セッション管理（一覧・復元・削除） |
| `/memory` | プロジェクトメモリの管理 |
| `/compact` | セッション履歴を圧縮 |
| `/review` | ソースコードレビュー |
| `/skills` | Agent Skills の管理（一覧・有効化・手動呼び出し） |
| `/agents` | サブエージェントの一覧・詳細表示 |
| `/hooks` | ライフサイクルフックの管理 |
| `/attach` | ファイル添付（画像・テキスト・クリップボード・キャプチャ） |
| `/mcp` | MCP サーバー一覧・再読み込み |
| `/diff` / `/rewind` | ファイル変更の表示・巻き戻し |
| `/plan` / `/code` | プランニング／コーディングモード切替 |
| `/safe` / `/unsafe` | セーフモード切替 |

詳しい使い方は [利用ガイド](docs/user_guide.md) を参照。

## 開発

```bash
# テスト実行
uv run pytest -m "not integration"

# リント
uv run ruff check src/ tests/
```
