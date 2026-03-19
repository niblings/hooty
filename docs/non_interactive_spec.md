# Non-Interactive モード仕様書

## 概要

REPL を起動せず、プロンプトを受け取り、結果を標準出力に返す非対話モード。
Unix パイプラインやスクリプトからの利用を想定する。

## CLI インターフェース

### 新規オプション

| オプション | 短縮 | 型 | 説明 |
|---|---|---|---|
| `--prompt` | `-p` | `str` | プロンプトテキスト |
| `--unsafe` | `-y` | `bool` | Safe モード無効化（確認ダイアログをスキップ） |
| `--output-format` | — | `str` | 出力形式（将来拡張用。初期は `text` のみ） |

`--unsafe` は対話モード（REPL）でも有効。起動時から `/unsafe` 状態で開始する。

### 既存オプションの変更

| オプション | 変更前 | 変更後 |
|---|---|---|
| `--profile` | `-p` | 短縮なし（`--profile` のみ） |

### 起動条件

以下のいずれかが成立した場合、Non-Interactive モードで起動する:

1. `--prompt (-p)` が指定された
2. stdin が非 TTY（パイプ入力）

優先度: `--prompt` > stdin

stdin が非 TTY かつ `--prompt` も指定された場合、`--prompt` の値を使い stdin は無視する。

## 入出力

### 入力

```bash
# --prompt で直接指定
hooty -p "テストを全部通して"

# パイプで stdin から入力
cat prompt.md | hooty
echo "README を翻訳して" | hooty

# --unsafe で確認なし実行
hooty --unsafe -p "lint 修正して" --dir ./project
hooty --unsafe --profile my-profile -p "ビルドして"

# 対話モードでも --unsafe は有効（起動時から /unsafe 状態）
hooty --unsafe
hooty --unsafe --profile my-profile
```

### 出力

| チャネル | 内容 |
|---|---|
| **stdout** | LLM のレスポンス本文（プレーン Markdown） |
| **stderr** | メタ情報（モデル名、トークン数、実行時間）、エラー、ツール実行ログ |

```bash
# stdout のみリダイレクト（メタ情報はターミナルに残る）
hooty -p "構造を説明して" > result.md

# stderr も抑制
hooty -p "構造を説明して" > result.md 2>/dev/null

# stderr のみ確認
hooty -p "テスト実行" > /dev/null
```

### 終了コード

| コード | 意味 |
|---|---|
| `0` | 正常終了 |
| `1` | LLM エラー（API エラー、タイムアウト等） |
| `2` | 設定エラー（認証情報不足、プロファイル不正等） |

## ツール・インタラクションの挙動

### 確認ダイアログ（Safe モード）

| モード | `--unsafe` あり | `--unsafe` なし |
|---|---|---|
| 対話（REPL） | 確認スキップ（`/unsafe` と同等） | 確認ダイアログ表示（デフォルト） |
| 非対話 | 確認スキップ | デフォルト拒否 |

非対話 + `--unsafe` なしの場合、確認が必要な操作（write_file, edit_file, run_shell）は
拒否され、LLM には `"User denied the operation (non-interactive mode)."` が返る。
拒否した旨を stderr に出力する。

### ask_user ツール

非対話モードでは `ask_user()` は即座に `"(no response)"` を返却する。

LLM への instructions に以下を追加し、呼び出し自体を抑制する:

```
Non-interactive mode: ask_user() is unavailable. Make reasonable decisions autonomously.
```

### ストリーミング

非対話モードではストリーミングを使用しない（`stream=False`）。
LLM の応答完了後に stdout へ一括出力する。

## セッション

| 項目 | 挙動 |
|---|---|
| デフォルト | 一時セッション（永続化しない） |
| `--resume (-r) <id>` 指定時 | 既存セッションを再利用（履歴を引き継ぐ） |
| `--continue (-c)` 指定時 | 最新セッションを再利用 |
| メモリ | 有効（プロジェクト知識は読み書きする） |
| 会話ログ | 記録する（project history に残る） |

## スキル・MCP・外部ツール

REPL モードと同様に動作する。config.yaml の設定に従う。

- Skills: 有効（`--no-skills` で無効化可）
- MCP: 有効（config.yaml に設定があれば）
- GitHub / Web: config の設定に従う

## 将来拡張

### --output-format json（将来）

```bash
hooty -p "構造を説明して" --output-format json
```

```json
{
  "content": "## プロジェクト構造\n\n...",
  "model": "claude-sonnet-4-6",
  "profile": "bedrock-claude",
  "tokens": {
    "input": 12340,
    "output": 1856,
    "reasoning": 0
  },
  "elapsed": 8.42,
  "tool_calls": 3,
  "exit_code": 0
}
```

## 実装方針

### 影響範囲

| ファイル | 変更内容 |
|---|---|
| `main.py` | `--prompt`, `--unsafe` オプション追加。`--profile` の `-p` 短縮を削除。非対話モード分岐 |
| `oneshot.py` (新規) | 非対話モードのエントリポイント。Agent 生成 → 実行 → stdout 出力 |
| `config.py` | `AppConfig` に `unsafe: bool` フィールド追加 |
| `repl.py` | 起動時に `config.unsafe` を `confirm_ref[0]` に反映 |
| `tools/confirm.py` | 非対話 + safe 時のデフォルト拒否動作を追加 |
| `tools/ask_user_tools.py` | 非対話フラグ参照、即座に `NO_RESPONSE` 返却 |
| `agent_factory.py` | 非対話時の instructions 追加（ask_user 抑制） |

### 既存コードの再利用

- `agent_factory.create_agent()` — そのまま使用
- `providers.create_model()` — そのまま使用
- `tools.build_tools()` — そのまま使用
- `config.load_config()` — そのまま使用

REPL (`repl.py`) への変更は `--unsafe` の初期値反映のみ。
