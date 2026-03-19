# Hooty 利用ガイド

## 1. はじめに

Hooty は対話型 AI コーディングアシスタント CLI です。ターミナル上で LLM と対話しながら、ファイル操作・コード生成・レビュー・GitHub 連携などの開発作業を効率化できます。

このガイドでは Hooty の基本的な使い方を紹介します。

---

## 2. インストール

1. `hooty-windows-x86_64.zip` を任意のフォルダに解凍する
2. 解凍先のフォルダを PATH 環境変数に追加する
3. ターミナルを再起動し、`hooty --version` で動作を確認する

> **注意**: 初回起動時はセキュリティソフトによる検査のため、実行に時間がかかる場合があります。2 回目以降は通常速度で起動します。

```
> hooty --version
Hooty vX.Y.Z
```

---

## 3. セットアップ

### 初回セットアップ

`hooty setup` を実行すると、対話形式でクレデンシャル（認証情報）を設定できます。管理者から受け取ったセットアップコードを貼り付けてください。

```bash
hooty setup
```

セットアップコードの貼り付け後、管理者から受け取ったパスフレーズの入力を求められます。

### セットアップ状態の確認・削除

```bash
# 保存済みクレデンシャルの状態を確認（シークレットはマスク表示）
hooty setup show

# クレデンシャルを削除
hooty setup clear
```

### クレデンシャル期限切れ

セットアップコードに有効期限がある場合、期限切れ後は起動時にエラーが表示されます。管理者から新しいセットアップコードを受け取り、`hooty setup` で適用してください。

---

## 4. 起動と基本操作

### 起動オプション

```bash
hooty [OPTIONS]
```

| オプション | 短縮 | 説明 |
|---|---|---|
| `--profile <name>` | | プロファイル名を指定して起動 |
| `--resume [id]` | `-r` | セッション復元（ID 省略でピッカー表示、ID 指定で直接復元） |
| `--continue` | `-c` | 直近のセッションを復元 |
| `--dir <path>` | `-d` | 作業ディレクトリを指定 |
| `--add-dir <path>` | | 追加作業ディレクトリ（読み書き可、複数指定可） |
| `--debug` | | デバッグログを有効化 |
| `--no-stream` | | ストリーミング出力を無効化 |
| `--no-skills` | | Agent Skills を無効化して起動 |
| `--no-hooks` | | Hooks（ライフサイクルフック）を無効化して起動 |
| `--snapshot` / `--no-snapshot` | | ファイルスナップショットの有効/無効（デフォルト: 有効） |
| `--attach <path>` | `-a` | ファイルを最初のメッセージに添付（複数指定可） |
| `--unsafe` | `-y` | セーフモードを無効化して起動（確認ダイアログをスキップ） |
| `--prompt <text>` | `-p` | 非対話モード（単発実行して終了） |
| `--mcp-debug` | | MCP サーバーの stderr 出力を表示 |
| `--version` | `-v` | バージョンを表示して終了 |

`--resume` と `--continue` は排他です（同時に指定できません）。

### 画面の見方

#### ウェルカムバナー

起動すると、フクロウのマスコットとともにプロファイル名・プロバイダ・モデル・作業ディレクトリが表示されます。

```
   ,___,
   (o,o)    Hooty vX.Y.Z
   /)  )    Profile: sonnet (bedrock / global.anthropic.claude-sonnet-4-6)
  --""--    Working directory: ~/my-project
            Type /help for commands, Ctrl+D to exit
```

#### 応答表示

LLM の応答中は、実行するツールに応じたアイコンが表示されます:

| アイコン | 意味 |
|---|---|
| 🔍 | ファイル読み取り（read_file, find, grep, tree など） |
| ✏️ | ファイル書き込み（write_file, edit_file） |
| ⚡ | シェルコマンド実行 |
| 💭 | 推論（think, analyze — Planning モード） |
| 🌐 | Web 検索・ページ読み取り（web_search, search_news, web_fetch） |
| 🧰 | スキル参照（get_skill_instructions など） |
| 🤖 | サブエージェント実行（run_agent） |

応答完了後にフッターが表示されます:

```
  ● global.anthropic.claude-sonnet-4-6 for 3.2s | ˄12,345 ˅1,234 | ctx 6%
```

| 要素 | 意味 |
|---|---|
| モデル名 | 使用したモデル ID |
| `for Xs` | 応答にかかった時間 |
| `˄N` / `˅N` | 入力トークン数 / 出力トークン数 |
| `ctx N%` | コンテキストウィンドウ使用率 |

コンテキスト使用率は色分けで警告されます:

| 使用率 | 色 | 対応 |
|---|---|---|
| 0–49% | 通常 | 余裕あり |
| 50–79% | 黄色 | 注意 |
| 80–100% | 赤太字 | `/compact` で圧縮を推奨 |

### キーボード操作

| キー | 動作 |
|---|---|
| `Enter` | 入力を送信 |
| `Shift+Tab` | Planning / Coding モードをトグル |
| `Tab` | スラッシュコマンドの補完 |
| `Ctrl+C` | ストリーミング応答をキャンセル |
| `Ctrl+D` × 2 | Hooty を終了 |
| `Esc` × 2 | 入力内容をクリア |
| `\` + `Enter` | マルチライン入力（次の行に続ける） |
| `Ctrl+L` | 画面クリア |
| `Ctrl+X` `Ctrl+E` | 外部エディタで入力を編集（$EDITOR） |
| `!<command>` | シェルエスケープ（LLM を介さず直接シェル実行） |

### シェルエスケープ（Bang Command）

プロンプトで `!` に続けてコマンドを入力すると、LLM を介さずに直接シェルコマンドを実行できます。`git status` の確認や `ls` など、LLM に渡す必要のない操作に便利です。

```
❯ !git status
On branch main
nothing to commit, working tree clean

❯ !python --version
Python 3.12.0
```

- `!` を入力するとプロンプトが `!` に変わり、テキストがオレンジ色になります（シェルモード表示）
- コマンドは作業ディレクトリで実行されます
- 異常終了時はエグジットコードが表示されます（正常終了時は表示なし）
- `!!` でリテラルな `!` をシェルに渡せます
- `Esc` × 2 でシェルモードをキャンセルして通常入力に戻れます
- 実行結果は会話履歴に記録されません（LLM のコンテキストに影響しません）

### 終了

以下のいずれかで終了できます:

- `/quit` または `/exit` コマンド
- `Ctrl+D` × 2

---

## 5. 対話モード

Hooty には 2 つの対話モードがあります。

### Coding モード（デフォルト）

通常の対話モードです。LLM がファイルの読み書き・シェルコマンド実行・コード生成などを直接行います。

### Planning モード

設計・調査に特化したモードです。コードの読み取り・検索は自由にできますが、ファイル書き込みはブロックされます。深い推論のために、Native Reasoning（Extended Thinking）を使用します。プランの作成・更新は PlanTools（`plans_create` / `plans_update`）で行います。

| 操作 | Planning モード | Coding モード |
|---|---|---|
| ファイル読み取り・検索 | ○ | ○ |
| ファイル書き込み・編集 | ✗（ブロック） | ○ |
| シェル実行 | △（確認付き） | ○ |
| プラン管理（PlanTools） | ○ | ○ |

### モード切替

| 方法 | 動作 |
|---|---|
| `Shift+Tab` | モードをトグル |
| `/plan` | Planning モードに切替 |
| `/code` | Coding モードに切替 |
| `/auto` | 自動遷移トグル — ON にするとモード遷移時の確認ダイアログをスキップ |

ターミナル下部のモードラインに現在のモードが表示されます。`/auto` が ON の場合は `🚀 coding (auto)` / `💡 planning (auto)` と表示されます。

### Plan → Coding 自動遷移

Planning モードで設計が完了すると、LLM が自動遷移を提案します。以下のフローで Coding モードへ切り替わります:

1. 「Execute Plan」の承認ダイアログが表示される
2. 承認すると「Switch to coding mode?」の確認が表示される
3. 承認すると Coding モードに切り替わり、計画に基づいた実装が自動で開始される

いずれかのステップで拒否すると、Planning モードに留まります。

`/auto` が ON の場合、ステップ 2 の確認はスキップされ即座に遷移します。Coding → Planning 遷移も同様にスキップされます。

### Extended Thinking（拡張思考）

`/reasoning` コマンドで Claude の拡張思考（Extended Thinking）を制御できます。トグル順は `off → auto → on → off` です。

| モード | 動作 |
|---|---|
| `off` | 拡張思考を無効化 |
| `auto` | メッセージ内のキーワードに応じて自動で有効化（コスト節約） |
| `on` | 常時有効（キーワードで budget を上書き） |

`auto` モードでは、`auto_level` 設定（デフォルト `1`）により、キーワードなしでも常にレベル 1 の Extended Thinking が有効です。メッセージにキーワードを含めると、より高い budget に引き上げられます:

| レベル | キーワード例 | budget |
|---|---|---|
| Level 1 | （デフォルト、キーワード不要） | 4,000 |
| Level 2 | `think hard`, `megathink`, `よく考えて` | 10,000 |
| Level 3 | `ultrathink`, `熟考` | 30,000 |

キーワードは `config.yaml` の `reasoning.keywords`、デフォルトレベルは `reasoning.auto_level`（0-3）でカスタマイズできます。`auto_level: 0` にすると、キーワードなし時は推論なしになります。

> **モデルによる動作の違い:** Claude Opus 4.6+ は adaptive thinking（`effort` ベース）を使用し、レベルに応じて `low` / `medium` / `high` が設定されます。その他の Claude モデル（Sonnet 4.6 等）は従来の `budget_tokens` ベースです。Azure OpenAI の GPT モデルは `reasoning_effort` パラメータで制御されます（`-chat` バリアントは `medium` のみ、`-pro` バリアントは `high` 固定）。ユーザーが意識する必要はなく、内部で自動的に適切なパラメータに変換されます。

### プラン管理

Planning モードで作成されたプランはプロジェクト単位で永続化され、セッションを跨いで参照できます。

**スラッシュコマンド:**

| コマンド | 説明 |
|---|---|
| `/plans` | インタラクティブピッカー（`v` で閲覧、`d` で削除） |
| `/plans search <keyword>` | キーワードでプランを検索 |

**PlanTools（LLM が使用するツール）:**

LLM は以下のツールでプランの CRUD 操作を行います。Planning / Coding 両モードで常に有効です。

| ツール | 説明 |
|---|---|
| `plans_list(status_filter)` | プラン一覧（status でフィルタ可） |
| `plans_get(plan_id)` | プラン本文を取得（short_id prefix マッチ） |
| `plans_search(keyword)` | キーワード検索 |
| `plans_create(body, summary)` | 新規作成（同セッション内の active プランを自動 cancel） |
| `plans_update(plan_id, body, summary)` | 既存プランを in-place 更新（plan_id 維持） |
| `plans_update_status(plan_id, status)` | ステータス変更（active / completed / pending / cancelled） |

Planning モードでの典型的なワークフロー:

1. `plans_list()` / `plans_get()` で既存プランを確認
2. `plans_create(body, summary)` で新規プラン作成
3. ユーザーフィードバックに基づき `plans_update(plan_id, body)` で精緻化
4. `exit_plan_mode(summary, plan_id=plan_id)` でプランを coding agent に引き継ぎ

---

## 6. セーフモード

ファイル書き込みやシェル実行の前にユーザー確認を求めるモードです。デフォルトで有効です。`--unsafe` オプションまたは `/unsafe` コマンドで無効化できます。

| コマンド | 動作 |
|---|---|
| `/safe` | セーフモードを有効化 |
| `/unsafe` | セーフモードを無効化 |

### アクセス制限モデル

| 操作 | safe mode ON | safe mode OFF（`/unsafe`） |
|---|---|---|
| ファイル操作（read/write/edit/grep/find/ls/tree） | ワーキングディレクトリに制限 | ワーキングディレクトリに制限 |
| シェルコマンド（run_shell） | 確認ダイアログ → ユーザーが判断 | 制限なし（パス自由） |
| パイプ（`\|`）・チェーン（`&&`, `\|\|`, `;`） | セグメント単位で許可リスト検証 | セグメント単位で許可リスト検証 |
| リダイレクト（`>`, `>>`, `<`） | ブロック（`2>&1` 等は許可） | ブロック（`2>&1` 等は許可） |
| コマンド置換（`$(`, `` ` ``） | 常にブロック | 常にブロック |
| 未登録コマンド | 常にブロック | 常にブロック |

ファイル操作は常にワーキングディレクトリ（+ `--add-dir` で追加したディレクトリ）に制限されます。シェルコマンドのパスアクセスは、safe mode ON ではユーザー確認ダイアログがゲートとして機能し、safe mode OFF ではユーザーが意図的に制限を解除したものとして扱います。

パイプ（`|`）とチェーン（`&&`, `||`, `;`）はデフォルトで許可されていますが、各セグメントの先頭コマンドが許可リストで個別に検証されます。`config.yaml` の `tools.shell_operators` で演算子ごとに許可/ブロックを制御できます。

### 確認ダイアログ

セーフモード有効時、ファイル書き込み・編集・シェル実行の前に確認ダイアログが表示されます:

```
╭─ ⚠  Write File ───────────────────────╮
│    samples/demo.py                      │
│    ❯ Yes, approve this action.          │
│      No, reject this action.            │
│      All, approve remaining actions.    │
│      Quit, cancel execution.            │
╰─────────────────────────────────────────╯
```

| キー | 動作 |
|---|---|
| `Y` | この 1 回のみ承認 |
| `N` | 拒否 |
| `A` | 承認し、このターン内の以降の確認を自動承認 |
| `Q` | レスポンス全体を中断 |

LLM が複数のツールを同時に呼び出した場合でも、確認ダイアログは 1 つずつ順番に表示されます。`A`（All）を選択すると、残りのツール呼び出しはすべて自動承認されます。

---

## 7. セッション管理

Hooty は対話履歴をセッションとして自動保存します。

### セッションの復元

| 方法 | 説明 |
|---|---|
| `hooty --resume` (`-r`) | インタラクティブなセッション選択画面から復元 |
| `hooty --resume <id>` (`-r <id>`) | 指定 ID のセッションを直接復元 |
| `hooty --continue` (`-c`) | 直近のセッションを復元 |
| `/session resume [id]` | REPL 内でセッションを復元（ID 省略でピッカー表示） |

### 会話履歴の再表示

`--resume` または `--continue` でセッションを復元すると、過去の Q&A ペアが REPL 形式で自動的に再表示されます。これにより、前回の会話の続きを自然に把握できます。

```
─────────────────────────────────────────────────────────────
❯ テストを実行して
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
テストを実行しました。全 42 件パス、失敗 0 件です。
```

- デフォルトでは直近 1 件の Q&A を表示します
- 表示件数は `config.yaml` の `session.resume_history` で変更できます（`0` で無効化）
- 長い応答は 4,000 文字に切り詰められます

```yaml
session:
  resume_history: 3    # 直近 3 件を表示
```

### ワークスペース不一致の警告

セッションは作成時の作業ディレクトリ（working directory）を記憶しています。異なるディレクトリからセッションを再開すると、警告が表示されます:

```
  🚫 Workspace mismatch
  Session directory:  /home/user/project-a
  Current directory:  /home/user/project-b
  Session will rebind on next interaction.
```

- そのまま会話を続けると、セッションは現在のディレクトリにリバインドされます
- 即終了した場合、元のディレクトリバインドが保持されます
- セッションピッカー（`--resume`）や `/session list` では、現在のディレクトリと異なるセッションに 🚫 マーカーが表示されます

### セッション一覧・フォーク・新規

| コマンド | 説明 |
|---|---|
| `/session` | 現在のセッション ID・プロジェクトパス・統計を表示 |
| `/session agents` | サブエージェント実行の内訳テーブルを表示 |
| `/session list` | 保存済みセッションの一覧を表示（🚫 でディレクトリ不一致を表示） |
| `/fork` | 現在のセッションをフォーク（サマリーを引き継いだ新セッション） |
| `/new` | 新しいセッションを開始 |

### セッション履歴の圧縮

長い対話を続けるとコンテキストウィンドウの上限に近づきます。以下の方法で圧縮できます:

- **手動圧縮**: `/compact` コマンドでセッション履歴を要約に圧縮
- **自動圧縮**: コンテキスト使用率が閾値（デフォルト 70%）を超えると自動で圧縮
- **状況確認**: `/context` コマンドでコンテキストウィンドウの使用状況を確認

```
❯ /compact

  Compacting session history...
  ✓ Compacted 12 runs (87 messages) into summary
```

自動圧縮は `config.yaml` の `session.auto_compact` と `session.auto_compact_threshold` で制御できます。

### 会話履歴ログ

`/compact` を実行するとセッション内の個別ターンは要約に置き換えられますが、ユーザー入力と LLM 最終回答のペアは JSONL 形式で自動保存されています:

```
~/.hooty/projects/{name}-{hash}/history/{session-id}.jsonl
```

各行は以下のフィールドを持つ JSON オブジェクトです:

| フィールド | 内容 |
|---|---|
| `timestamp` | ISO 8601 タイムスタンプ（UTC） |
| `session_id` | セッション ID |
| `model` | 使用モデル |
| `input` | ユーザーの質問テキスト |
| `output` | LLM の最終回答（Markdown） |
| `output_tokens` | 出力トークン数 |

過去の会話を振り返りたい場合は、LLM に「これまでの会話を振り返りたい」と依頼すると、`read_file()`/`grep()`/`find()` でログを参照・検索できます。

### 古いセッションの削除

```
# デフォルト: 90日以上前のセッションを対象
/session purge

# 日数を指定
/session purge 30
```

インタラクティブなチェックボックス UI で、削除するセッションを選択できます。

---

## 8. プロジェクトメモリ

Hooty はプロジェクトの設計判断や規約をセッションを跨いで記憶します。

### 二層構造

| 層 | 保存先 | 用途 |
|---|---|---|
| グローバル記憶 | `~/.hooty/memory.db` | 全プロジェクト共通の嗜好・ワークフロー設定 |
| プロジェクト記憶 | `~/.hooty/projects/<slug>/memory.db` | プロジェクト固有の設計判断・コード規約 |

### 記憶の仕組み

LLM が対話中に設計判断やユーザーの確認事項を検出すると、自動で記憶に保存します。「覚えて」と明示的に依頼して記憶させることもできます。記憶された情報は次回以降のセッションでコンテキストに自動注入されます。

### メモリ管理コマンド

| コマンド | 説明 |
|---|---|
| `/memory` | 記憶状況のサマリーを表示 |
| `/memory list` | プロジェクト記憶の一覧を表示 |
| `/memory list --global` | グローバル記憶の一覧を表示 |
| `/memory search <keyword>` | プロジェクト＋グローバルを横断キーワード検索 |
| `/memory edit` | プロジェクト記憶をインタラクティブに削除 / global へ移動 |
| `/memory edit --global` | グローバル記憶をインタラクティブに削除 / project へ移動 |

メモリ機能は `config.yaml` の `memory.enabled` で無効化できます（デフォルト: 有効）。

---

## 9. ファイル添付

`/attach` コマンドまたは `--attach` CLI オプションで画像やテキストファイルをプロンプトに添付できます。添付はスタックに蓄積され、次のメッセージ送信時にまとめて LLM に送られます。

### CLI からの添付

起動時に `--attach` (`-a`) オプションでファイルを事前添付できます。REPL モードでは最初のプロンプトに、Non-Interactive モードでは指定したプロンプトにまとめて送信されます。

```bash
# REPL 起動時に事前添付 → 最初のメッセージで送信
hooty --attach screenshot.png

# Non-Interactive: 画像解析
hooty -p "このエラーを修正して" --attach error.png

# 複数ファイル
hooty -p "分析して" -a trace.log -a metrics.json

# パイプ連携
echo "説明して" | hooty -a screenshot.png

# --dir との組み合わせ（--attach の相対パスは起動元 CWD 基準）
hooty --dir ../other-project --attach ./local-file.txt
```

### REPL での添付

```
# ファイルパスを指定して添付
❯ /attach screenshot.png

  📎 Attachment (1): screenshot.png [image, 2560x1440 » 1568x882, ~1842 tokens]

# 複数ファイルを同時に添付（クォートでスペース入りパスに対応）
❯ /attach 'スクリーンショット 2026-03-13.png' main.py

  📎 Attachment (2): スクリーンショット 2026-03-13.png [image, 1568x745, ~1557 tokens]
  📎 Attachment (3): main.py [text, 4.1KB, ~1400 tokens]

# クリップボードから添付（スクリーンショットやコピーしたファイル）
❯ /attach paste

  Checking clipboard...
  📎 Attachment (2): paste_20260313_120000.png [image, 922x300, ~368 tokens]

# ディレクトリを指定するとそのディレクトリをルートにファイルピッカーを起動
❯ /attach src/

# 引数省略でファイルピッカーを起動（上位ディレクトリへの遷移も可能）
❯ /attach
```

`/attach paste` は Windows / WSL2 / macOS に対応しています。スクリーンショットをクリップボードにコピーした状態や、Explorer / Finder でファイルをコピー（Ctrl+C / Cmd+C）した状態で実行できます。同じ画像を複数回ペーストした場合は自動的に重複排除されます。

添付がある間はプロンプトに `[📎 N]` が表示されます:

```
[📎 3] ❯ この画像の内容を説明して
```

メッセージ送信後、添付は自動的にクリアされます。

### 対応ファイル形式

| 種類 | 拡張子 |
|---|---|
| 画像 | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp` |
| テキスト | `.txt`, `.md`, `.log`, `.json`, `.yaml`, `.yml`, `.xml`, `.py`, `.rs`, `.js`, `.ts`, `.java`, `.go`, `.toml`, `.html`, `.css`, `.sh` |

画像は添付時に最大辺 1568px にリサイズされ、PNG で保存されます。Vision 非対応モデルでは画像添付が拒否されます。

### スクリーンキャプチャ

`/attach capture` でウィンドウやモニターのスクリーンショットを撮影し、画像として添付できます。Windows / WSL2 環境で利用可能です（PowerShell 経由で Win32 API を使用）。

```
# アクティブウィンドウをキャプチャ（3秒の切替猶予あり）
❯ /attach capture

  💡 'active' captures the foreground window. Switch now...
  ⏳ 3s...
  📎 Attachment (1): capture_active_20260313_143000.png [image, 1920x1080 » 1568x882, ~1842 tokens]

# 特定プロセスのウィンドウ
❯ /attach capture chrome.exe

# ウィンドウタイトルで検索（部分一致）
❯ /attach capture "Design Doc"

# モニター指定（0 = プライマリ）
❯ /attach capture 0
❯ /attach capture primary

# 遅延キャプチャ（3秒後に撮影）
❯ /attach capture chrome.exe --delay 3

# 連続キャプチャ（3枚を5秒間隔で）
❯ /attach capture "Design Doc" --delay 2 --repeat 3 --interval 5
```

#### キャプチャ対象

| 指定方法 | 例 | 説明 |
|---|---|---|
| （なし）/ `active` | `/attach capture` | アクティブ（前面）ウィンドウ |
| `0` / `primary` | `/attach capture 0` | プライマリモニター |
| `1`, `2` | `/attach capture 1` | モニター番号 |
| `*.exe` | `/attach capture chrome.exe` | プロセス名 |
| クラス名 | `/attach capture Notepad` | ウィンドウクラス名 |
| `"タイトル"` | `/attach capture "Design Doc"` | ウィンドウタイトル（部分一致） |

#### オプション

| オプション | デフォルト | 説明 |
|---|---|---|
| `--delay N` | 0 | N 秒後にキャプチャ（最大 30） |
| `--repeat N` | 1 | N 枚連続でキャプチャ（最大 5） |
| `--interval N` | — | 連続キャプチャの間隔秒数（5〜30、`--repeat` 使用時は必須） |

- `active` 指定時はキャプチャ前に 3 秒のカウントダウンが自動的に入ります（ウィンドウ切替の猶予）
- カウントダウン中は `Ctrl+C` でキャンセルできます
- ヘルプ: `/attach capture --help`

#### キャプチャ設定

`config.yaml` の `attachment.capture` セクションでオプションの上限をカスタマイズできます:

```yaml
attachment:
  capture:
    delay_max: 30        # --delay の最大値
    repeat_max: 5        # --repeat の最大値
    interval_min: 5      # --interval の最小値
    interval_max: 30     # --interval の最大値
```

### 添付の管理

| コマンド | 説明 |
|---|---|
| `/attach paste` | クリップボードから画像・ファイルを添付（Windows / WSL2 / macOS） |
| `/attach capture [target]` | スクリーンキャプチャで画像を添付（Windows / WSL2） |
| `/attach list` | インタラクティブピッカーを起動（Space でトグル、d で選択削除） |
| `/attach clear` | 全添付をクリア |

### 制限

| 設定項目 | デフォルト | 説明 |
|---|---|---|
| `max_files` | 20 | 添付ファイル数の上限 |
| `max_total_tokens` | 50,000 | 全添付合計のトークンハードリミット |
| `context_ratio` | 0.25 | コンテキストウィンドウに対する添付上限比率 |

同一ファイル（フルパス一致）の重複添付は自動的に排除されます。`/new` でセッションを切り替えるとスタックは自動リセットされます。

設定は `config.yaml` の `attachment` セクションでカスタマイズできます:

```yaml
attachment:
  max_files: 20
  max_side: 1568
  large_file_tokens: 10000
  max_total_tokens: 50000
  context_ratio: 0.25
```

---

## 10. コードレビュー

`/review` コマンドでインタラクティブなコードレビューを実行できます。

### ワークフロー

1. **ファイル/ディレクトリ選択** — レビュー対象をピッカーで選択
2. **レビュー種別選択** — 以下の種別から選択

| 種別 | 観点 |
|---|---|
| General | バグ・セキュリティ・パフォーマンス・品質・構造を総合的にレビュー |
| Security | 脆弱性・認証情報の露出・入力バリデーション |
| Performance | ボトルネック・N+1 クエリ・不要なアロケーション |
| Architecture | モジュール結合度・関心の分離・拡張性 |
| Bug Hunt | ロジックエラー・境界条件・未ハンドルの例外 |
| Custom | 自由記述のレビュー観点を指定 |

3. **指摘の確認** — LLM がコードを読み取り、指摘事項を一覧表示
4. **修正指示** — 指摘の中から修正したいものを選択し、カスタム指示を追加して自動修正

---

## 11. Sub-agents（サブエージェント）

複雑なタスクや広範な調査を LLM が自動的にサブエージェントに委譲します。サブエージェントは独立したコンテキストウィンドウで動作し、親エージェントには最終結果のみ返却されるため、メインのコンテキストが汚れません。

### ビルトインエージェント

| エージェント | 説明 |
|---|---|
| `explore` | コードベースの広範な探索・調査（read-only） |
| `implement` | コード変更の実装 — edit-test-fix サイクルを隔離コンテキストで実行 |
| `test-runner` | テスト実行 → 失敗解析 → ソース修正 → 再実行の自動化 |
| `assistant` | 汎用タスク実行 — ドキュメント作成、データ分析、システム操作、ファイル整理 |
| `web-researcher` | Web 検索 + ページ読み取りによる深い Web 調査 |
| `summarize` | ファイル・モジュール・クラスの要約生成（read-only） |

LLM が必要に応じて自動的にサブエージェントを選択・呼び出します。ユーザーが明示的に操作する必要はありません。

### implement エージェント

`implement` は親エージェントのコンテキストウィンドウ肥大化を防ぐために設計されたエージェントです。複数ファイルにまたがる実装やテスト・lint のリトライサイクルを独立したコンテキストで実行し、親には構造化レポート（SUCCESS / PARTIAL / FAILED）のみを返却します。

親エージェントが `implement` に委譲する場合:
1. 対象ファイルと変更内容の明確な記述
2. 検証コマンド（テスト、lint、型チェック）

を提供します。書き込み可能なサブエージェントにはツール結果の自動圧縮（`compress_tool_results`）が適用されるため、多数のツール呼び出しを行ってもサブエージェント自身のコンテキストもオーバーフローしません。

### test-runner エージェント

`test-runner` はテスト失敗の診断と修正に特化したエージェントです。テストコマンドを受け取り、以下の 4 フェーズで自動的にテストを通します:

1. **フレームワーク検出** — プロジェクトファイルから pytest / jest / vitest / go test 等を自動検出
2. **テスト実行** — 指定されたコマンド（または自動検出したコマンド）でテストを実行
3. **失敗解析** — 失敗の分類（assertion / runtime error / import error）と優先度付け
4. **修正 & 再実行** — ソースコードを修正し再テスト（問題ごとに最大 3 リトライ）

`implement` との使い分け: `implement` は「何をどう変えるか」を親が明示する場合に使い、`test-runner` は「テストを通せ」という指示だけで失敗原因の特定から修正までを任せる場合に使います。

### web-researcher エージェント

`web-researcher` は `web_search` と `web_fetch` を組み合わせた深い Web 調査を隔離コンテキストで実行します。複数の Web ページを読み込む調査は、メインエージェントのコンテキストを大量に消費するため、専用のサブエージェントに委譲します。

**ツールバジェット（過剰な呼び出しを防止）:**
- `web_search` / `search_news`: 合計最大 3 回
- `web_fetch`: 最大 5 回
- `max_turns`: 12

**`/websearch` が無効な場合の動作:**

`web-researcher` は `web_search` を必要とするため、`/websearch` が OFF の場合は実行前に確認ダイアログが表示されます:

```
╭─ 🌐 web-researcher requires Web search ──────────────────╮
│                                                          │
│     [Y]  Yes, enable /websearch                          │
│     [N]  No, cancel                                      │
│                                                          │
╰──────────────────────────────────────────────────────────╯
```

Y を選択すると `/websearch` が自動的に有効化され、リサーチが開始されます。

### assistant エージェント

`assistant` はコーディング以外の汎用タスクを実行するエージェントです。ドキュメント作成、データ分析・集計、ファイル整理、レポート作成など、ローカルファイルベースのタスクを隔離コンテキストで実行します。

**Web 検索との分離:** `assistant` は Web 検索を行いません。Web 調査が必要なタスクは `web-researcher` に自動ルーティングされます。`web_fetch` は親が明示的に URL を指定した場合のみ使用します。

| 観点 | assistant | web-researcher |
|------|-----------|----------------|
| 入力 | ローカルファイル・データ | Web 上の情報 |
| ツール | ファイル操作・シェル中心 | web_search + web_fetch |
| ユースケース | ドキュメント作成、データ加工 | 技術調査、最新情報の取得 |

### カスタムエージェントの定義

`~/.hooty/agents.yaml`（グローバル）または `<project>/.hooty/agents.yaml`（プロジェクト）でカスタムエージェントを追加できます:

```yaml
agents:
  reviewer:
    description: "コードレビュー専門エージェント"
    instructions: |
      コードを読み取り、品質・セキュリティの観点からレビューを行ってください。
    disallowed_tools:
      - write_file
      - edit_file
    max_turns: 20
    max_output_tokens: 3000
```

同名のエージェント定義は後勝ちでマージされます（ビルトイン < グローバル < プロジェクト）。

### 管理コマンド

| コマンド | 説明 |
|---|---|
| `/agents` | 利用可能なサブエージェント一覧を表示 |
| `/agents info <name>` | エージェントの詳細を表示 |
| `/agents reload` | agents.yaml を再読み込み |

### 実行統計

`/session` でサブエージェントの利用統計（合計）が表示されます。`/session agents` でエージェントごとの内訳を確認できます。

---

## 12. Hooks（ライフサイクルフック）

セッション・LLM 応答・ツール実行などのイベントで、シェルコマンドを自動トリガーする仕組みです。ログ収集・通知・カスタムバリデーションなどに利用できます。

### 設定

グローバル（`~/.hooty/hooks.yaml`）とプロジェクト固有（`<project>/.hooty/hooks.yaml`）の 2 箇所に設定でき、リスト連結でマージされます。

```yaml
# hooks.yaml
hooks:
  SessionStart:
    - command: "echo 'Session started'"
  PostToolUse:
    - command: "~/scripts/log-tool.sh"
      matcher: "run_shell"    # run_shell のみにフィルタ
      async: true             # バックグラウンドで実行
  UserPromptSubmit:
    - command: "~/scripts/validate.sh"
      blocking: true          # exit 2 で送信をブロック可能
```

### 主なイベント

| イベント | タイミング | ブロック可能 |
|---|---|---|
| `SessionStart` | セッション開始時 | No |
| `SessionEnd` | セッション終了時 | No |
| `UserPromptSubmit` | ユーザー入力送信時 | Yes |
| `PreToolUse` | ツール実行前 | Yes |
| `PostToolUse` | ツール実行後 | No |
| `PermissionRequest` | 確認ダイアログ表示時 | Yes |
| `SubagentStart` | サブエージェント起動時 | No |
| `SubagentEnd` | サブエージェント終了時 | No |

ブロック可能なイベントでは、フックスクリプトが exit code 2 を返すとアクションが阻止されます。

### 管理コマンド

| コマンド | 説明 |
|---|---|
| `/hooks` | インタラクティブピッカーで個別 ON/OFF を切替 |
| `/hooks list` | 登録済みフック一覧を表示 |
| `/hooks on` / `/hooks off` | Hooks 機能の全体 ON/OFF |
| `/hooks reload` | hooks.yaml を再読み込み |

`--no-hooks` オプションで無効化して起動することもできます。

---

## 13. ファイルスナップショット

セッション中に LLM がファイルに加えた変更を自動追跡します。変更の確認や巻き戻しに利用できます。

### /diff — 変更の確認

`/diff` コマンドでセッション中のファイル変更を unified diff 形式で表示します。

```
❯ /diff

  File changes in this session:
  ✏️ modified  src/app.py
  ✚ created   src/utils.py

  --- src/app.py (original)
  +++ src/app.py (current)
  @@ -10,3 +10,5 @@
   def main():
       ...
  +    setup_logging()
  +    run()
```

### /rewind — 変更の巻き戻し

`/rewind` コマンドでファイルを変更前の状態に復元します。

- **引数なし** — 全変更ファイルを巻き戻し
- **ファイル選択** — インタラクティブピッカーで個別に選択

巻き戻し後、セッション履歴が自動的にコンパクト化され、LLM のコンテキストがリセットされます。新規作成されたファイルは削除され、削除されたファイルは再作成されます。

### 設定

デフォルトで有効です。`--no-snapshot` で無効化、または `config.yaml` の `snapshot.enabled` で制御できます。

---

## 14. モデルとプロファイル

### モデル切替

`/model` コマンドでインタラクティブなプロファイルピッカーを開き、セットアップ済みのモデルを切り替えられます。起動時に `--profile <name>` で指定することもできます。

```bash
# 起動時にプロファイル指定
hooty --profile opus

# REPL 内で切替
/model
```

利用可能なプロファイル（モデル）はセットアップコードに含まれています。プロファイルを追加・変更したい場合は管理者に相談してください。

### プロバイダ設定

`config.yaml` の `providers` セクションでプロバイダごとのデフォルト値を設定できます。`profiles` で個別のプロファイルを定義し、プロバイダ設定を上書きできます。

#### AWS Bedrock

```yaml
providers:
  bedrock:
    model_id: global.anthropic.claude-sonnet-4-6
    region: us-east-1
    sso_auth: false             # true = AWS SSO 認証を使用
    max_input_tokens: 200000    # 省略時はモデルカタログの値
```

#### Anthropic API（直接）

```yaml
providers:
  anthropic:
    model_id: claude-sonnet-4-6
    base_url: ""                # 空 = api.anthropic.com
    max_input_tokens: 200000
```

環境変数 `ANTHROPIC_API_KEY` が必要です。

#### Azure AI Foundry

```yaml
providers:
  azure:
    model_id: claude-sonnet-4-6
    endpoint: "https://<resource>.services.ai.azure.com/"
    api_version: "2025-04-01-preview"   # 省略時は SDK デフォルト
    max_input_tokens: 200000
```

#### Azure OpenAI Service

```yaml
providers:
  azure_openai:
    model_id: gpt-5.2
    endpoint: "https://<resource>.openai.azure.com/"
    deployment: my-deployment
    api_version: "2024-10-21"
    max_input_tokens: 128000
```

---

## 15. ツール

### ファイル操作・シェル実行

常に有効なコアツールです。

| 関数 | 説明 |
|---|---|
| `read_file` | ファイルを行番号付きで読み取り |
| `write_file` | ファイルの新規作成・上書き |
| `edit_file` | テキストマッチによる部分編集 |
| `apply_patch` | Claude Code 形式のマルチファイルパッチを適用 |
| `move_file` | ファイルの移動・リネーム |
| `create_directory` | ディレクトリの作成 |
| `run_shell` | シェルコマンドの実行 |
| `grep` | パターン検索 |
| `find` | グロブパターンによるファイル検索 |
| `ls` | ディレクトリ内容の一覧 |
| `tree` | ディレクトリ構造の階層表示 |

シェル実行にはコマンド許可リストがあり、`git`, `python`, `npm` などの開発ツールがデフォルトで許可されています。追加のコマンドは `config.yaml` の `tools.allowed_commands` で許可できます。

```yaml
tools:
  allowed_commands:
    - terraform
    - kubectl
```

Windows 環境では PowerShell コマンドレット（`Get-ChildItem`, `Select-String` など）も利用できます。

### GitHub 連携

環境変数 `GITHUB_ACCESS_TOKEN` が設定されている場合に有効になります。`/github` コマンドで on/off を切り替えられます。

```bash
export GITHUB_ACCESS_TOKEN=ghp_xxxxxxxxxxxx
```

PR の作成・一覧取得、Issue の作成・一覧取得などが可能です。

### Web 検索・Web 調査

`/websearch` コマンドで DuckDuckGo 検索を有効化します（デフォルト: 無効）。URL の内容読み取り（`web_fetch`）は常時有効です。

複数ソースを調査する場合は、LLM が自動的に `web-researcher` サブエージェントに委譲します（[11. Sub-agents](#web-researcher-エージェント) を参照）。`web_fetch` は `max_chars` パラメータ（デフォルト 20,000、最大 80,000）で取得量を調整でき、web-researcher は `max_chars=50000` で長いページもほぼ全文取得します。

### SQL データベース

`~/.hooty/databases.yaml` にデータベース接続を登録し、`/database connect <name>` で接続します。

```yaml
# ~/.hooty/databases.yaml
databases:
  local: "sqlite:///./data/app.db"
  analytics: "postgresql://admin:pass@localhost:5432/mydb"
```

| コマンド | 説明 |
|---|---|
| `/database list` | 登録済み DB 一覧 |
| `/database connect <name>` | 指定 DB に接続 |
| `/database disconnect` | 接続を解除 |
| `/database add <name> <url>` | DB 接続を追加 |
| `/database remove <name>` | DB 接続を削除 |

### MCP 拡張ツール

`~/.hooty/mcp.yaml` で外部 MCP（Model Context Protocol）サーバーを登録し、ツールを拡張できます。stdio 接続と URL 接続（Streamable HTTP / SSE）に対応しています。

```yaml
# ~/.hooty/mcp.yaml
servers:
  filesystem:
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - /home/user/projects

  my-server:
    url: http://localhost:8080/mcp

  # 認証ヘッダー付き URL 接続
  authed-api:
    url: https://api.example.com/mcp
    headers:
      Authorization: Bearer <token>
```

`/mcp` で接続中のサーバー一覧を表示し、`/mcp reload` で `mcp.yaml` を再読み込みできます。

スラッシュコマンドでもサーバーを追加・削除できます:

```
/mcp add my-api https://api.example.com
/mcp add --transport sse --header "Authorization: Bearer tok" my-sse http://localhost:3000/sse
/mcp add -e API_KEY=secret my-tool node server.js
/mcp remove my-api
```

| オプション | 説明 |
|---|---|
| `--global` | グローバル mcp.yaml に書き込み（省略時はプロジェクト mcp.yaml） |
| `--header` / `-h` | HTTP ヘッダーを指定（URL 接続のみ、複数指定可） |
| `--transport http\|sse` | トランスポート種別を指定（デフォルト: `http`） |
| `-e` / `--env` | 環境変数を指定（`KEY=VALUE` 形式、複数指定可） |

> **WSL ユーザー向け:** WSL2 から Windows `.exe`（`.cmd` / `.bat` 含む）を MCP サーバーとして使う場合、`env` で指定した環境変数は自動的には Windows プロセスに渡りません。Hooty は WSL 環境を自動検出し、`WSLENV` を付与して環境変数を転送します。特別な設定は不要です。

---

## 16. Agent Skills

Agent Skills はエージェントに専門知識を提供する拡張パッケージです。コーディング規約・レビュー基準・デプロイ手順など、プロジェクト固有のナレッジをスキルとして定義できます。[Agent Skills オープン標準](https://agentskills.io)に準拠しており、Claude Code / Codex CLI 等と共通利用可能です。

### 特徴

- **デフォルト有効** — 起動時にスキルが自動ロードされます。`--no-skills` で無効化起動が可能です
- **Progressive Discovery** — LLM はスキルの概要だけをシステムプロンプトで把握し、必要時にのみ詳細をロードします。コンテキストウィンドウの圧迫を防ぎます
- **グローバル + プロジェクト** — 全プロジェクト共通のスキルとプロジェクト固有のスキルを使い分けられます

### スキルの配置

スキルは以下のディレクトリに配置します（下にあるほど優先度が高い）:

| ディレクトリ | スコープ |
|---|---|
| `src/hooty/data/skills/` | ビルトイン（パッケージ同梱、最低優先） |
| `~/.hooty/skills/` | グローバル（全プロジェクト共通） |
| グローバル extra_paths | `/skills add --global` で登録 |
| プロジェクト extra_paths | `/skills add` で登録 |
| `<project>/.github/skills/` | プロジェクト（GitHub 推奨パス） |
| `<project>/.claude/skills/` | プロジェクト（Claude Code 互換） |
| `<project>/.hooty/skills/` | プロジェクト（Hooty 固有、最高優先） |

同名スキルがある場合は優先度の高いディレクトリのものが使われます。例えば `.hooty/skills/review/` は `.claude/skills/review/` を上書きします。

### スキルの構造

各スキルは以下の構造のディレクトリです:

```
my-skill/
├── SKILL.md              # 指示書（必須）
├── scripts/              # 実行スクリプト（任意）
│   └── check.sh
└── references/           # 参照ドキュメント（任意）
    └── guide.md
```

`SKILL.md` は YAML フロントマター + マークダウン本文で構成されます:

```markdown
---
name: code-review
description: Python code review checklist
---

# Code Review

レビュー時は以下のチェックリストに従ってください...
```

### フロントマター制御

| フィールド | デフォルト | 説明 |
|---|---|---|
| `name` | ディレクトリ名 | スキルの識別名 |
| `description` | （空） | スキルの概要 |
| `disable-model-invocation` | `false` | `true` にすると LLM が自動利用できなくなる。`/skills invoke` での手動呼び出し専用 |
| `user-invocable` | `true` | `false` にすると手動呼び出し不可。LLM のみが利用 |

### ビルトインスキル

パッケージに同梱されているスキルです。

| スキル | 説明 | 呼び出し方 |
|---|---|---|
| `explain-code` | コードを平易に説明し、ASCII フロー図で可視化 | LLM が自動利用 |
| `project-summary` | プロジェクト構造のサマリーを生成（read-only） | `/skills invoke project-summary` |
| `skill-creator` | 対話ウィザードで新しいスキルを作成 | `/skills invoke skill-creator [name]` |

`project-summary` と `skill-creator` は `disable-model-invocation: true` のため、LLM が自動で使うことはありません。手動呼び出し専用です。

### 手動呼び出し

`disable-model-invocation: true` のスキルは LLM が自動で使うことはありません。代わりに `/skills invoke` で手動実行します:

```
/skills invoke deploy staging
```

スキルの instructions 内の `$ARGUMENTS` が引数に置換され、LLM に送信されます。

### トップレベルショートカット

`user-invocable` なスキルは `/<skill-name> [args]` で直接呼び出せます。`/skills invoke` を経由する必要はありません。

```
/explain-code main.py      ← /skills invoke explain-code main.py と同等
/project-summary            ← disable-model-invocation スキルもショートカット可
```

**ディスパッチルール:**

1. 既存のスラッシュコマンド（`/help`, `/skills` 等）が最優先
2. 既存コマンドに一致しない場合、スキル名で検索
3. `user-invocable` かつ有効なスキルにマッチすれば呼び出し
4. マッチしなければ「Unknown command」エラー

Tab 補完にもスキル名が自動追加されるため、`/` の後に Tab キーで候補を確認できます。

### スキル・インストラクションの自動検出

スキルファイル（SKILL.md）やインストラクションファイル（CLAUDE.md, hooty.md 等）の変更は自動的に検出されます。`/skills reload` を手動で実行する必要はありません。`skill-creator` スキルで新しいスキルを作成した場合も、即座に利用可能になります。

### スキル管理コマンド

| コマンド | 説明 |
|---|---|
| `/skills` | インタラクティブピッカーで個別 ON/OFF を切替 |
| `/skills list` | スキル一覧を表示（名前・ソース・状態） |
| `/skills info <name>` | スキル詳細（instructions プレビュー・scripts・references） |
| `/skills invoke <name> [args]` | 手動呼び出し（`$ARGUMENTS` を置換して LLM に送信） |
| `/skills add [--global] <path>` | 外部スキルディレクトリを追加 |
| `/skills remove [--global] <path>` | 外部スキルディレクトリを削除 |
| `/skills reload` | ディスクからスキルを再読み込み → Agent 再生成 |
| `/skills on` | スキル機能を全体で有効化 |
| `/skills off` | スキル機能を全体で無効化 |

### 外部スキルディレクトリの追加・削除

標準のスキルディレクトリ以外にも、任意のディレクトリをスキルソースとして登録できます。

```bash
# プロジェクトスコープで追加（現在のプロジェクトでのみ有効）
/skills add /path/to/my-skills

# グローバルスコープで追加（全プロジェクトで有効）
/skills add --global /path/to/shared-skills

# 削除
/skills remove /path/to/my-skills
/skills remove --global /path/to/shared-skills
```

- パスは絶対パスに正規化されて保存されます
- 追加時にディレクトリの存在チェックが行われます
- プロジェクトスコープの状態は `~/.hooty/projects/<slug>/.skills.json` に保存されます
- グローバルスコープの状態は `~/.hooty/.skills.json` に保存されます
- `--global` フラグはどの位置でも指定可能です（例: `/skills add --global /path` も `/skills add /path --global` も同じ動作）

### 有効/無効の仕組み

3 段階の制御があります:

1. **全体トグル** — `config.yaml` の `skills.enabled` または `/skills on|off`
2. **個別 ON/OFF** — `/skills` ピッカーで切替。状態は `~/.hooty/projects/<slug>/.skills.json` に永続化
3. **フロントマター** — `disable-model-invocation: true` のスキルは Agent に含めない（手動呼び出し専用）

### 設定

```yaml
# ~/.hooty/config.yaml
skills:
  enabled: true           # デフォルト有効
```

---

## 17. 設定ファイル

### config.yaml

メインの設定ファイルです。`~/.hooty/config.yaml` に配置します。セットアップコードで自動生成されますが、以下のセクションは手動でカスタマイズできます。

```yaml
# セッション管理
session:
  auto_compact: true
  auto_compact_threshold: 0.7

# メモリ
memory:
  enabled: true

# モード別ロール（カスタマイズ例）
roles:
  planning: "あなたはシニアアーキテクトです。"
  coding: "あなたは Python のスペシャリストです。"

# ツール
tools:
  allowed_commands:
    - terraform
    - kubectl
  shell_timeout: 120
  idle_timeout: 0

# 推論（Extended Thinking）
reasoning:
  mode: auto          # off / on / auto
  auto_level: 1       # auto 時のデフォルトレベル（0=推論なし, 1-3）

# Agent Skills
skills:
  enabled: true
```

### databases.yaml / mcp.yaml

データベース接続と MCP サーバーはそれぞれ独立した設定ファイルで管理します。

- `~/.hooty/databases.yaml` — DB 接続設定（[14. ツール](#sql-データベース) を参照）
- `~/.hooty/mcp.yaml` — MCP サーバー設定（[14. ツール](#mcp-拡張ツール) を参照）

### コンテキストファイル（hooty.md / AGENTS.md）

LLM へのカスタム指示を追加するファイルです。

**グローバル指示**（`~/.hooty/` に配置、全プロジェクト共通）:

| ファイル | 備考 |
|---|---|
| `hooty.md` | Hooty 固有 |
| `instructions.md` | 汎用的な指示書 |

両方存在する場合はファイルサイズが大きい方が選択されます。言語設定・コーディングスタイル・レビュー方針など、全プロジェクト共通のルールを記述します。

**プロジェクト固有指示**（プロジェクトルートに配置）:

| ファイル | 備考 |
|---|---|
| `AGENTS.md` | 汎用的な指示書 |
| `CLAUDE.md` | Claude Code 互換 |
| `.github/copilot-instructions.md` | GitHub Copilot 互換 |

複数存在する場合はファイルサイズが大きい方が選択されます。そのプロジェクト特有のルールや技術スタックの情報を記述します。

いずれもファイルサイズ上限は 64 KB です。

### 環境変数

| 環境変数 | 説明 |
|---|---|
| `GITHUB_ACCESS_TOKEN` | GitHub 連携用トークン |
| `HOOTY_PROFILE` | デフォルトプロファイルの指定 |


---

## 18. スラッシュコマンド一覧

### モード切替

| コマンド | 説明 |
|---|---|
| `/code` | Coding モードに切替 |
| `/plan` | Planning モードに切替 |
| `/auto` | 自動遷移トグル（ON で確認ダイアログをスキップ） |
| `/safe` | セーフモードを有効化 |
| `/unsafe` | セーフモードを無効化 |

### 作業ディレクトリ

| コマンド | 説明 |
|---|---|
| `/add-dir [path]` | 追加作業ディレクトリを登録（引数省略時はディレクトリピッカー） |
| `/list-dirs` | 現在の許可ディレクトリ一覧を表示 |

`--add-dir` CLI オプションまたは `/add-dir` で追加したディレクトリは、`base_dir` と同等にファイルの読み書きが可能です。セッションスコープ（永続化しない）で、`/new` 実行時に `/add-dir` で追加した分はリセットされます。

### セッション管理

| コマンド | 説明 |
|---|---|
| `/session` | 現在のセッション情報を表示 |
| `/session agents` | サブエージェント実行の内訳テーブル |
| `/session list` | 保存済みセッション一覧 |
| `/session resume [id]` | セッションを復元 |
| `/session purge [days]` | 古いセッションを削除（デフォルト: 90日） |
| `/new` | 新しいセッションを開始 |
| `/fork` | 現在のセッションをフォーク |
| `/compact` | セッション履歴を圧縮 |
| `/context` | モデル情報・コンテキストファイル・ウィンドウ使用状況を表示 |
| `/diff` | セッション中のファイル変更を表示 |
| `/rewind` | ファイル変更を巻き戻し |

### メモリ

| コマンド | 説明 |
|---|---|
| `/memory` | 記憶状況サマリーを表示 |
| `/memory list [--global]` | 記憶の一覧を表示 |
| `/memory search <keyword>` | キーワード検索 |
| `/memory edit [--global]` | インタラクティブに記憶を削除 / 移動 |
### プロジェクト管理

| コマンド | 説明 |
|---|---|
| `/project purge` | 孤立プロジェクトディレクトリを削除 |

### ディレクトリ管理

| コマンド | 説明 |
|---|---|
| `/add-dir [path]` | 追加作業ディレクトリを登録 |
| `/list-dirs` | 許可ディレクトリ一覧を表示 |

### ファイル添付

| コマンド | 説明 |
|---|---|
| `/attach [path...]` | ファイルを添付（引数省略でファイルピッカー） |
| `/attach paste` | クリップボードから添付（Windows / WSL2 / macOS） |
| `/attach capture [target]` | スクリーンキャプチャで画像を添付（Windows / WSL2） |
| `/attach list` | 添付ファイルの管理ピッカー |
| `/attach clear` | 全添付をクリア |

### ツール制御

| コマンド | 説明 |
|---|---|
| `/model` | モデルプロファイルを切替 |
| `/reasoning` | Extended Thinking モードをトグル（off → auto → on → off） |
| `/plans` | プラン管理ピッカー（閲覧・削除） |
| `/plans search <keyword>` | キーワードでプランを検索 |
| `/github` | GitHub ツールの on/off |
| `/websearch` | Web 検索ツールの on/off |
| `/database` | DB 接続管理 |
| `/mcp` | MCP サーバー一覧 |
| `/mcp add [--global] <name> <command\|url>` | MCP サーバーを追加 |
| `/mcp remove [--global] <name>` | MCP サーバーを削除 |
| `/mcp list` | MCP サーバー一覧を表示 |
| `/mcp reload` | mcp.yaml を再読み込み |
| `/skills` | スキルピッカー（個別 ON/OFF 切替） |
| `/skills list` | スキル一覧を表示 |
| `/skills info <name>` | スキル詳細を表示 |
| `/skills invoke <name> [args]` | スキルを手動呼び出し |
| `/<skill-name> [args]` | スキルをトップレベルから直接呼び出し（`/skills invoke` のショートカット） |
| `/skills add [--global] <path>` | 外部スキルディレクトリを追加 |
| `/skills remove [--global] <path>` | 外部スキルディレクトリを削除 |
| `/skills reload` | ディスクからスキルを再読み込み |
| `/skills on` / `/skills off` | スキル機能の全体 ON/OFF |
| `/agents` | サブエージェント一覧を表示 |
| `/agents info <name>` | エージェント詳細を表示 |
| `/agents reload` | agents.yaml を再読み込み |
| `/hooks` | フックピッカー（個別 ON/OFF 切替） |
| `/hooks list` | 登録済みフック一覧を表示 |
| `/hooks on` / `/hooks off` | Hooks 機能の全体 ON/OFF |
| `/hooks reload` | hooks.yaml を再読み込み |
| `/rescan` | PATH を再スキャンしてコマンドリストを更新 |

### その他

| コマンド | 説明 |
|---|---|
| `/review` | ソースコードレビュー |
| `/help` | コマンド一覧を表示 |
| `/quit` / `/exit` | Hooty を終了 |
| `!<command>` | シェルエスケープ（LLM を介さず直接シェル実行） |

---

## 19. トラブルシューティング

### セットアップ未完了

```
⚠ No configuration found.
```

`hooty setup` でクレデンシャルを設定してください。管理者からセットアップコードを受け取る必要があります。

### クレデンシャル期限切れ

```
✗ Credentials expired on 2026-03-01 10:00
```

管理者から新しいセットアップコードを受け取り、`hooty setup` で適用してください。古いクレデンシャルは `hooty setup clear` で削除できます。

### コンテキスト上限

フッターの `ctx` が 80% を超えたり、応答が不安定になった場合は:

- `/compact` でセッション履歴を圧縮する
- `/new` で新しいセッションを開始する（前のセッションは `--resume` で復元可能）

### MCP サーバー接続失敗

- `~/.hooty/mcp.yaml` の設定内容を確認してください
- `/mcp reload` で設定を再読み込みしてください
- `--mcp-debug` オプション付きで起動すると、MCP サーバーの stderr 出力を確認できます

### シェルコマンドが拒否される

許可されていないコマンドを実行しようとするとブロックされます。`config.yaml` の `tools.allowed_commands` にコマンドを追加してください。

```yaml
tools:
  allowed_commands:
    - your-command
```

`/rescan` で PATH を再スキャンすると、新しくインストールしたコマンドが認識されます。

