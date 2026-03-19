# Agent Skills 仕様書

## 概要

Hooty は Agno Agent Skills（[オープン標準](https://agentskills.io)）を統合している。デフォルト有効。`--no-skills` で無効化起動。

## スキルディレクトリ（検出順 = 優先度昇順）

同名スキルは後勝ち（上書き）。

1. `src/hooty/data/skills/` — ビルトインスキル（最低優先度）
2. `~/.hooty/skills/` — グローバルスキル
3. `/skills add` で登録した追加パス（`.skills.json` に永続化）
4. `<project>/.github/skills/` → `<project>/.claude/skills/` → `<project>/.hooty/skills/` — プロジェクトスキル

## スキル構造

```
<skill-name>/
├── SKILL.md              # フロントマター + instructions（必須）
├── scripts/              # 実行スクリプト（任意）
└── references/           # 参照ドキュメント（任意）
```

## フロントマター制御

| フィールド | デフォルト | 説明 |
|---|---|---|
| `disable-model-invocation` | `false` | `true` で LLM 自動利用禁止。`/skills invoke <name>` で手動呼び出し専用 |
| `user-invocable` | `true` | `false` で手動呼び出し不可。LLM のみ利用 |

## 状態管理

- **全体トグル:** `config.yaml` の `skills.enabled`（`/skills on|off`）
- **個別 ON/OFF:** `~/.hooty/projects/<slug>/.skills.json`（`/skills` ピッカーで切替）

## Agent 統合

`agent_factory.py` の `_build_skills()` が `agno.skills.Skills` を構築し、`Agent(skills=...)` に渡す。LLM は以下のツールで Progressive Discovery する:

- `get_skill_instructions()` — スキルの指示を取得
- `get_skill_reference()` — 参照ドキュメントを取得
- `get_skill_script()` — 実行スクリプトを取得

### スキル自動検出

メッセージ送信前（`_send_to_agent()`）にスキルディレクトリの変更を自動検出し、変更があれば Agent を自動再生成する。`skill-creator` スキルで新スキルを作成した場合など、`/skills reload` なしで即座に LLM から利用可能になる。

- **検出方法:** `skill_fingerprint()` が全スキルディレクトリの SKILL.md 生コンテンツを SHA-256 でハッシュし、前回のフィンガープリントと比較する。frontmatter パースや `scripts/` `references/` スキャンは行わない軽量実装
- **検出対象:** SKILL.md の追加・削除・内容変更（frontmatter + body）
- **タイミング:** 毎メッセージ送信前。変更検出時は旧 Agent の HTTP クライアント・MCP 接続をクリーンアップ後に再生成
- **表示:** `Skills changed — agent reloaded.`（インストラクション変更と同時の場合は `Instructions & Skills changed — agent reloaded.`）

## ビルトインスキル

| スキル | 説明 | LLM 自動呼び出し |
|---|---|---|
| `explain-code` | コードの平易な説明 + ASCII フロー図 | 可 |
| `project-summary` | プロジェクト構造サマリー | 不可（`disable-model-invocation: true`） |
| `skill-creator` | 対話的に新しいスキルを作成するウィザード | 不可（`disable-model-invocation: true`） |

## スラッシュコマンド

| コマンド | 説明 |
|---|---|
| `/<skill-name> [args]` | スキルをトップレベルから直接呼び出し（下記「トップレベルショートカット」参照） |
| `/skills` | インタラクティブピッカー（各スキル ON/OFF 切替） |
| `/skills list` | 登録済み全スキル一覧表示 |
| `/skills info <name>` | スキル詳細表示 |
| `/skills invoke <name> [args]` | スキルを手動呼び出し |
| `/skills reload` | スキルを再検出・再読込 |
| `/skills on` | Skills 機能を全体 ON |
| `/skills off` | Skills 機能を全体 OFF |

### トップレベルショートカット

`user-invocable` かつ `enabled` なスキルは、`/skills invoke <name>` を経由せず `/<name> [args]` で直接呼び出せる。

```
/explain-code main.py      ← /skills invoke explain-code main.py と同等
/project-summary            ← disable-model-invocation スキルもショートカット可
```

**ディスパッチルール:**

1. 既存のスラッシュコマンド（`/help`, `/skills` 等）が最優先
2. 既存コマンドに一致しない場合、スキル名をリアルタイムで `discover_skills()` から検索
3. `user_invocable=True` かつ `enabled=True` のスキルにマッチすれば呼び出し
4. マッチしなければ従来の「Unknown command」エラー

**Tab 補完:** スキルコマンドは補完リストにも自動追加される。パフォーマンスのため補完時はキャッシュを参照し、`discover_skills()` は呼ばない。

**キャッシュ更新タイミング:** REPL 起動時、スキル変更自動検知時（fingerprint 変化）、`/skills reload|on|off` 実行時。

**除外条件:**
- `user_invocable=False` のスキル（LLM 自動専用）
- `enabled=False` のスキル（`/skills` ピッカーで OFF にしたもの）
- 既存コマンド名と衝突するスキル（例: `help` という名前のスキルは `/<name>` にならない）

## インジケーター

スキルツール呼び出し時は 🧰 アイコン（`#a0c0e0`）で表示。

## 実装ファイル

| ファイル | 内容 |
|---|---|
| `src/hooty/skill_store.py` | スキル検出・状態管理（SkillInfo, discover/load/save）、`skill_fingerprint()` による変更検出 |
| `src/hooty/skill_picker.py` | `/skills` 用インタラクティブ複数選択ピッカー UI |
| `src/hooty/commands/skills.py` | スラッシュコマンドハンドラー（`refresh_skill_commands` コールバック呼び出し含む） |
| `src/hooty/repl.py` | トップレベルショートカット（`_try_skill_shortcut`, `_refresh_skill_commands`, `_skill_command_cache`）、補完統合 |
| `src/hooty/commands/__init__.py` | `CommandContext.refresh_skill_commands` コールバック |
