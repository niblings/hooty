# セットアップガイド

## 概要

Hooty のクレデンシャル配布は **管理者** と **利用者** の 2 ステップで構成されます。

```
管理者                                          利用者
┌────────────────────┐                         ┌────────────────────┐
│ config.yaml        │                         │                    │
│ + 環境変数(APIキー) │                         │                    │
│        ↓           │   セットアップコード     │        ↓           │
│ hooty setup        │ ─────────────────────►  │ hooty setup        │
│   generate         │  (テキスト / チャット)   │   (貼り付け)       │
│        ↓           │                         │        ↓           │
│ HOOTY1:xxxxx...    │                         │ ~/.hooty/           │
│                    │                         │   .credentials     │
└────────────────────┘                         └────────────────────┘
```

- **管理者**: `hooty setup generate` でセットアップコードを生成し、利用者に配布
- **利用者**: `hooty setup` でセットアップコードを貼り付け、クレデンシャルを登録

---

## 1. 管理者: セットアップコードの生成

### 前提条件

- `~/.hooty/config.yaml` にプロバイダ設定・プロファイルが定義済み
- 対象プロバイダの API キーが環境変数に設定済み

### hooty setup generate

```bash
hooty setup generate [OPTIONS]
```

| オプション | デフォルト | 説明 |
|---|---|---|
| `--passphrase <text>` | 自動生成 | パスフレーズを明示指定。省略時はランダム生成（`secrets.token_urlsafe(16)`、22 文字） |
| `--expiry-days <int>` | `30` | 有効期限（日数）。`0` で無期限 |
| `--exclude-profiles <names>` | なし | 除外するプロファイル名（カンマ区切り） |
| `--dump` | `false` | 暗号化せず JSON ペイロードを出力（デバッグ用） |

#### 出力例

```
HOOTY1:abcdefghijklmnop...

  Providers: bedrock, azure
  Profiles: sonnet, opus, haiku
  Secret keys: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AZURE_API_KEY
  Expires: 30 days (at 2026-04-17 01:03)

  ⚠ Share the setup code and passphrase via separate channels
  Passphrase: IfZMfi-3IJFXlA9aFoL6Mg
```

パスフレーズは常に表示されます。`--passphrase` を省略した場合は自動生成されたパスフレーズが表示されます。

### 対応プロバイダと環境変数

| プロバイダ | 環境変数キー | 備考 |
|---|---|---|
| Anthropic（直接） | `ANTHROPIC_API_KEY` | `base_url` 未設定時 |
| Anthropic（Azure AI 経由） | `ANTHROPIC_API_KEY` | `base_url` 設定時 |
| Azure AI Foundry | `AZURE_API_KEY` | `endpoint` 必須 |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | `endpoint` 必須 |
| OpenAI | `OPENAI_API_KEY` | |
| Bedrock（IAM） | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | |
| Bedrock（SSO） | — | `sso_auth: true`（キー不要） |
| Bedrock（Bearer） | — | 対象外（利用者が環境変数で設定） |

> **注意**: `AWS_BEARER_TOKEN_BEDROCK` は一時トークンのため、セットアップコードには含まれません。利用者が自身の環境変数として設定してください。

### プロファイル制御

`config.yaml` に定義された全プロファイルがセットアップコードに含まれます。特定のプロファイルを除外するには `--exclude-profiles` を使用します。

```bash
# dev と local プロファイルを除外
hooty setup generate --exclude-profiles dev,local
```

デフォルトプロファイルが除外対象の場合、残りのプロファイルの先頭がデフォルトになります。

セットアップコードには、残りのプロファイルが参照するプロバイダのみが含まれます（未参照のプロバイダは自動除外）。

### 有効期限

```bash
# 90 日間有効
hooty setup generate --expiry-days 90

# 無期限
hooty setup generate --expiry-days 0
```

デフォルトは **30 日**。期限切れ後、利用者が Hooty を起動すると以下のエラーが表示されます:

```
✗ Credentials expired on 2026-04-06 12:00
```

利用者は管理者から新しいセットアップコードを受け取り、`hooty setup` で再適用する必要があります。

### パスフレーズ

セットアップコードは常にパスフレーズで暗号化されます。

- `--passphrase` **省略時**: `secrets.token_urlsafe(16)` でランダムパスフレーズを自動生成（22 文字、128 ビットエントロピー）
- `--passphrase <text>` **指定時**: 指定した文字列をパスフレーズとして使用

いずれの場合も、利用者はセットアップコード適用時にパスフレーズの入力が必要です。セットアップコードとパスフレーズを **別々の経路** で配布することを推奨します（例: コードはチャット、パスフレーズは口頭）。

### JSON ダンプ（--dump）

```bash
hooty setup generate --dump
```

暗号化前の JSON ペイロードを標準出力に表示します。デバッグ・検証用途です。

---

## 2. 利用者: セットアップコードの適用

### hooty setup

```bash
hooty setup
```

1. 既存クレデンシャルがある場合、上書き確認が表示される
2. セットアップコードの貼り付けを求められる
3. パスフレーズの入力を求められる
4. デコード成功で `~/.hooty/.credentials` に暗号化保存

```
✓ Credentials saved
```

### 適用後の動作

- クレデンシャルは `~/.hooty/.credentials` にマシンバインド暗号化で保存
- プロバイダ設定・プロファイル・デフォルトプロファイルが反映される
- 次回の `hooty` 起動時から自動的に読み込まれる

**設定の優先順位**（後勝ち）:

```
.credentials < config.yaml < 環境変数 < CLI引数
```

利用者が `config.yaml` や環境変数で独自の設定を持つ場合、それらがクレデンシャルより優先されます。

### hooty setup show

保存済みクレデンシャルの状態を確認します（シークレットはマスク表示）。

```bash
hooty setup show
```

```
  Default profile: sonnet
  Profiles: sonnet, opus, haiku
  Credential is valid (expires at 2026-04-06 12:00)
```

### hooty setup clear

保存済みクレデンシャルを削除します。

```bash
hooty setup clear
```

```
✓ Credentials cleared.
```

---

## 3. セキュリティ

### シークレットの隔離

クレデンシャル由来の API キーは `os.environ` に設定されません。プロセス内メモリ（`_credential_secrets`）に保持され、`get_secret()` 関数を通じて参照されます。

```
get_secret(key)
  → _credential_secrets[key]   ← クレデンシャル由来（最優先）
  → os.environ[key]            ← 環境変数フォールバック
```

これにより:

- **子プロセス**（シェルコマンド、Hooks、MCP サーバー）にシークレットが渡らない
- 利用者が自身で設定した環境変数は従来どおり動作する
- クレデンシャルと環境変数の両方がある場合、**クレデンシャルが優先**

### AWS_BEARER_TOKEN_BEDROCK

一時トークン（Bearer Token）はクレデンシャルの対象外です。利用者が環境変数 `AWS_BEARER_TOKEN_BEDROCK` を設定すると、botocore が自動的に解決します。

### .credentials ファイルの保護

| 保護機構 | 詳細 |
|---|---|
| マシンバインド暗号化 | `hostname` + `username` から導出したパスフレーズで PBKDF2 + Fernet 暗号化 |
| ファイルパーミッション | `0600`（所有者のみ読み書き） |
| 別マシンでの復号不可 | ホスト名・ユーザー名が異なると復号に失敗する |

---

## 4. トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `Credentials expired on ...` | セットアップコードの有効期限切れ | 管理者に新しいセットアップコードを依頼し、`hooty setup` で再適用 |
| `Decryption failed: invalid passphrase or corrupted code` | パスフレーズの誤り、またはコードの破損 | パスフレーズを確認。解決しない場合は管理者に再生成を依頼 |
| 別マシンで起動できない | `.credentials` はマシンバインドのため移動不可 | 新しいマシンで `hooty setup` を再実行 |
| `cryptography package is required for setup` | `cryptography` パッケージ未インストール | `uv sync --extra enterprise` を実行 |
| `No provider credentials found to bundle` | 環境変数が未設定、またはプロファイル未定義 | `config.yaml` と環境変数を確認 |
