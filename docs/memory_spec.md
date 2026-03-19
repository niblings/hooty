# メモリ機能仕様書

## 概要

Hooty のメモリ機能は、プロジェクトの設計判断・規約・ユーザー嗜好をセッションを跨いで永続化し、後続のセッションで自動的にコンテキストとして注入する仕組みである。

- **グローバル記憶**: ユーザー嗜好やワークフロー設定など、プロジェクトを横断して有用な知識
- **プロジェクト記憶**: アーキテクチャ決定・コード規約・技術スタック選定など、特定プロジェクトに閉じた知識

## アーキテクチャ

### 二層ストレージ

```
~/.hooty/
├── memory.db                              ← グローバル記憶
├── projects/
│   ├── myapp-a3f1b2c4/
│   │   └── memory.db                      ← プロジェクト記憶
│   └── backend-e7d2f091/
│   │   └── memory.db
│   └── ...
└── ...
```

### プロジェクトディレクトリ名の導出

`projects/` 配下のディレクトリ名は、ワーキングディレクトリの末尾名と SHA-256 ハッシュ先頭 8 文字の組み合わせで一意に決定する。

```python
import hashlib
from pathlib import Path

def project_dir_name(work_dir: Path) -> str:
    """Derive a unique project directory name."""
    slug = work_dir.name
    digest = hashlib.sha256(
        str(work_dir.resolve()).encode()
    ).hexdigest()[:8]
    return f"{slug}-{digest}"
```

例:

| ワーキングディレクトリ | 導出名 |
|---|---|
| `/mnt/d/myapp` | `myapp-a3f1b2c4` |
| `/home/user/projects/backend` | `backend-e7d2f091` |
| `/mnt/d/other/myapp` | `myapp-7b3e9f12`（同名でもハッシュで区別） |

### データフロー

```
セッション開始
  │
  ├── config.py: working_directory → project_dir_name() → projects/ パス解決
  │
  ├── agent_factory.py: MemoryManager 生成
  │     └── プロジェクト memory.db を接続（LLM 読み書き可能）
  │
  ├── agent_factory.py: グローバル記憶の注入
  │     └── _build_global_memory_context() で全件読み込み
  │         → <global_memories> XML として additional_context に注入（読み取り専用）
  │
  ├── Agent 生成時:
  │     ├── enable_agentic_memory=True  → update_user_memory ツール登録
  │     └── add_memories_to_context=True → 既存記憶をシステムメッセージに注入
  │
  ▼
会話ループ
  │
  ├── LLM が決定事項を検出 → update_user_memory(task) を tool_call
  │     └── MemoryManager がプロジェクト memory.db に保存
  │
  └── 毎ターン: プロジェクト記憶 + グローバル記憶がコンテキストに含まれる
```

## ストレージ

### 形式

SQLite（Agno `SqliteDb` + `memory_table`）。

```python
from agno.db.sqlite import SqliteDb

# Global memory
global_memory_db = SqliteDb(
    memory_table="user_memories",
    db_file=str(config.config_dir / "memory.db"),
)

# Project memory
project_memory_db = SqliteDb(
    memory_table="user_memories",
    db_file=str(config.project_dir / "memory.db"),
)
```

### スキーマ

Agno `UserMemory` データクラスをそのまま利用する。

| フィールド | 型 | 説明 |
|---|---|---|
| `memory_id` | `str` | UUID（自動生成） |
| `memory` | `str` | 記憶内容（自然言語テキスト） |
| `topics` | `list[str]` | トピックタグ（検索用） |
| `user_id` | `str` | ユーザー識別子（デフォルト: `"default"`） |
| `agent_id` | `str` | エージェント識別子 |
| `input` | `str` | 記憶のきっかけとなった入力 |
| `created_at` | `int` | 作成タイムスタンプ（epoch 秒） |
| `updated_at` | `int` | 更新タイムスタンプ（epoch 秒） |

### サイズ見積もり

| 記憶件数 | ストレージ | コンテキスト増加 |
|---|---|---|
| 10 件 | ~2 KB | ~200 tokens（0.1%） |
| 50 件 | ~10 KB | ~1,000 tokens（0.5%） |
| 100 件 | ~20 KB | ~2,000 tokens（1.0%） |

※ コンテキスト比率は 200K トークンウィンドウ基準。

## LLM 連携

### Agent 設定

```python
from agno.memory.manager import MemoryManager

Agent(
    memory_manager=MemoryManager(
        db=memory_db,
        model=model,
    ),
    enable_agentic_memory=True,       # LLM がツールとして記憶操作
    update_memory_on_run=False,       # 毎ターン自動記憶しない（コスト回避）
    add_memories_to_context=True,     # 既存記憶をコンテキスト注入
)
```

### モード別の設定

| パラメータ | 値 | 理由 |
|---|---|---|
| `enable_agentic_memory` | `True` | LLM が自分の判断で `update_user_memory()` を tool_call |
| `update_memory_on_run` | `False` | 毎ターン追加 LLM コールが発生するため不採用 |
| `add_memories_to_context` | `True` | 既存記憶を毎ターンシステムメッセージに注入 |

### コスト影響

| コスト項目 | 影響 |
|---|---|
| LLM コール数 | 増加なし（メイン応答内の tool_call のみ） |
| LLM input tokens | +0.1〜1.0%（記憶件数次第） |
| ストレージ | 数百 KB 以下 |
| レイテンシ | ほぼ変化なし |

### 登録されるツール

`enable_agentic_memory=True` により、Agno が自動的に以下のツールを Agent に登録する。

| ツール名 | 説明 |
|---|---|
| `update_user_memory(task: str)` | 記憶の追加・更新・削除を自然言語タスクとして指示 |

`task` パラメータの例:

```
"add: This project uses JWT with refresh tokens for authentication"
"update memory m-a1b2: Changed from MySQL to PostgreSQL"
"delete memory m-c3d4: No longer using Vercel for deployment"
```

### 記憶ポリシー（instructions への追加）

Planning / Coding 両モードの instructions に以下を追加する。

```
## Memory policy

You have access to `update_user_memory` to manage persistent project knowledge.

### REMEMBER — only these categories:
- Architectural decisions confirmed by the user
  (e.g., "auth uses JWT", "DB is PostgreSQL")
- Project conventions and coding standards
  (e.g., "tests in __tests__/", "use snake_case")
- Technology stack and tooling choices
  (e.g., "deploy to Vercel", "use pnpm")
- User preferences for workflow
  (e.g., "always run tests before commit")
- Explicit user requests ("remember this", "覚えて")

### NEVER remember:
- Current task details, bugs, or errors
- File contents, diffs, or shell output
- Temporary debugging steps
- Questions or clarifications mid-task
- Anything not confirmed or decided by the user

### Rules:
- When in doubt, do NOT remember
- One memory = one fact (keep atomic)
- Update existing memory rather than duplicate
- Only remember after the user confirms a decision,
  not during exploration or discussion
```

### コンテキスト注入形式

`add_memories_to_context=True` により、毎ターンのシステムメッセージに以下が追加される（Agno 標準形式）。

```xml
<user_memories>
ID: m-a1b2c3d4
Memory: This project uses JWT with refresh tokens for authentication

ID: m-e5f6g7h8
Memory: Tests are placed in __tests__/ directory

ID: m-i9j0k1l2
Memory: Use Conventional Commits for commit messages
</user_memories>
```

### 記憶の検索優先順位

コンテキストにはプロジェクト記憶とグローバル記憶の両方が注入される。

```
1. プロジェクト記憶  ← 最優先（具体的・文脈に合致）
2. グローバル記憶    ← フォールバック（汎用的・嗜好ベース）
```

## スラッシュコマンド

### コマンド一覧

| コマンド | 説明 |
|---|---|
| `/memory` | 現在の記憶状況サマリーを表示 |
| `/memory list` | プロジェクト記憶の一覧を表示 |
| `/memory list --global` | グローバル記憶の一覧を表示 |
| `/memory search <keyword>` | プロジェクト＋グローバルを横断キーワード検索 |
| `/memory edit` | インタラクティブ picker でプロジェクト記憶を削除 / global へ移動 |
| `/memory edit --global` | インタラクティブ picker でグローバル記憶を削除 / project へ移動 |

### `/memory`（ステータス表示）

引数なしで現在の記憶状況を表示する。

```
  Project memory: 12 entries  (~/.hooty/projects/myapp-a3f1b2c4/memory.db)
  Global memory:   5 entries  (~/.hooty/memory.db)
  Last updated: 2 hours ago
```

### `/memory list`

プロジェクト記憶の一覧をテーブル形式で表示する。

```
  Project memories (myapp-a3f1b2c4):

  ID        Topics            Memory                          Updated
  m-a1b2    arch, db          Uses PostgreSQL + Prisma ORM    3 hours ago
  m-c3d4    convention        Tests in __tests__/ directory   1 day ago
  m-e5f6    convention        Conventional Commits style      2 days ago
```

`--global` フラグ指定時はグローバル記憶を表示する。

### `/memory search <keyword>`

プロジェクト記憶とグローバル記憶を横断してキーワード検索する。`memory` テキストと `topics` の両方を対象とする。

```
  Found 2 memories:

  [project] m-g7h8   auth          JWT with refresh tokens        1 day ago
  [global]  m-i9j0   preference    Prefers bcrypt for hashing     5 days ago
```

### `/memory edit`

インタラクティブ picker を使ってプロジェクト記憶を管理する（削除 / スコープ間移動）。`purge_picker` と同じ UI パターン（チェックボックス複数選択）を使用する。

```
┌ Manage project memories — 0/8 selected ──────────────────────────────────┐
│                                                                           │
│  ▸ ☐  1  m-a1b2  arch, db        Uses PostgreSQL + Prisma…               │
│    ☐  2  m-c3d4  convention      Tests in __tests__/ dir…                │
│    ☐  3  m-e5f6  convention      Conventional Commits sty…               │
│    ☐  4  m-g7h8  auth            JWT with refresh tokens…                │
│    ☐  5  m-i9j0  stack           Frontend is Next.js 15…                 │
│    ☐  6  m-k1l2  deploy          Uses Vercel for deploym…                │
│    ☐  7  m-m3n4  testing         Integration tests need …                │
│    ☐  8  m-o5p6  arch            Monorepo with turborepo…                │
│                                                                           │
│  ↑↓ navigate  Space toggle  a all  d delete  m move → global  Esc cancel │
└───────────────────────────────────────────────────────────────────────────┘
```

操作キー:

| キー | 動作 |
|---|---|
| `↑` / `↓` | カーソル移動 |
| `Space` | チェック/アンチェック切り替え |
| `a` | 全選択/全解除トグル |
| `d` / `Enter` | チェック済み記憶を削除 |
| `m` | チェック済み記憶を反対スコープに移動（project → global / global → project） |
| `Esc` / `q` | キャンセル |

`--global` フラグ指定時はグローバル記憶を対象とし、`m` キーの移動先は project になる。

#### スコープ間移動の影響

移動は次回セッション起動時から反映される（現セッション中の Agent コンテキストは変わらない）。

- **project → global（promote）**: MemoryManager 管理下から外れ、`<global_memories>` XML として全プロジェクトで読み取り専用で共有される
- **global → project（demote）**: `<global_memories>` から消え、現プロジェクトの MemoryManager 管理下に入る（LLM が更新・削除可能になる）

#### 全削除

`a`（全選択）→ `d`（削除）で全記憶削除が可能。専用の `/memory clear` コマンドは設けない。

### `/project purge`

> **注:** v0.7.0 で `/memory purge` から `/project purge` に移動。対象はメモリエントリではなくプロジェクトディレクトリ全体であるため、より適切な名前に変更。

孤立したプロジェクトディレクトリ（`~/.hooty/projects/{slug}-{hash8}/`）を検出・削除する。

#### メタデータファイル `.meta.json`

プロジェクトディレクトリ作成時に `.meta.json` を書き込み、元のワーキングディレクトリパスを記録する。

```json
{
  "working_directory": "/mnt/d/myapp",
  "created_at": 1740000000
}
```

#### 孤立の判定

| 状態 | 判定 | picker デフォルト |
|---|---|---|
| `.meta.json` あり、パス存在しない | 孤立 | チェック ON |
| `.meta.json` なし | 不明（孤立候補） | チェック OFF |
| `.meta.json` あり、パス存在する | 有効 → 表示しない | — |

#### 表示例

```
┌ Purge orphaned projects — 1/2 selected ─────────────────┐
│                                                           │
│  ▸ ☑  1  myapp-a3f1b2c4   /mnt/d/myapp (not found)      │
│    ☐  2  backend-e7d2f091  (metadata missing)  12 mem.   │
│                                                           │
│  ↑↓ navigate  Space toggle  a all  d delete  Esc cancel  │
└───────────────────────────────────────────────────────────┘
```

操作キー:

| キー | 動作 |
|---|---|
| `↑` / `↓` | カーソル移動 |
| `Space` | チェック/アンチェック切り替え |
| `a` | 全選択/全解除トグル |
| `d` / `Enter` | チェック済みプロジェクトを削除（`shutil.rmtree()`） |
| `Esc` / `q` | キャンセル |

## UI コンポーネント共通化

### `checkbox_select()`

`purge_picker.py` と `/memory edit` で共通のチェックボックス複数選択 UI を `ui.py` に抽出する。

```python
# ui.py
def checkbox_select(
    items: list[T],
    format_row: Callable[[int, T, bool, bool], str],
    title: str,
    console: Console,
    default_checked: bool = False,
) -> list[T] | None:
    """Interactive multi-select with checkboxes.

    Args:
        items: List of items to select from.
        format_row: Callback to format a row.
            (index, item, is_selected, is_checked) -> markup string
        title: Panel title.
        console: Rich Console instance.
        default_checked: Whether items are checked by default.

    Returns:
        List of checked items, or None if cancelled.
    """
```

利用箇所:

| 利用元 | `default_checked` | 備考 |
|---|---|---|
| `purge_picker` | `True` | 全選択状態から除外する方式 |
| `/memory edit` | `False` | 未選択状態から選ぶ方式 |

## セッションとプロジェクトの紐付け

### セッション metadata へのプロジェクト情報保存

セッション作成時に `working_directory` を Agno セッションの `metadata` に保存する。

```python
# session metadata
metadata = {
    "working_directory": config.working_directory,
}
```

### `/session` 表示の拡張

引数なしの `/session` でプロジェクトパスを表示する。

```
  Session: 1ffe37d9
  Project: /mnt/d/myapp  (myapp-a3f1b2c4)
  Tokens:  in:37,699  out:1,094  total:38,793
```

### `/session list` 表示の拡張

`Project` 列と `Forked` 列を表示する。`working_directory` の末尾ディレクトリ名を表示し、`metadata` が無い旧セッションは `—` を表示する。フォーク元がある場合は `⑂ <短縮ID>` を表示する。

```
  ID         Forked       Updated             Runs   Project          First message
  ────────── ──────────── ────────────────── ────── ──────────────── ──────────────────────
  df703442   ⑂ 8ec62bf0  2026-03-03 03:11      1   myapp            ps とは
  8ec62bf0   —            2026-03-03 03:10      1   myapp            ls とは
  c3d4e5f6   —            2026-02-27 09:00      1   —                テスト
```

## 設定

### `config.yaml` への追加

```yaml
memory:
  enabled: true              # メモリ機能の有効/無効（デフォルト: true）
```

### `AppConfig` への追加プロパティ

| プロパティ | 型 | 説明 |
|---|---|---|
| `memory_enabled` | `bool` | メモリ機能の有効/無効 |
| `project_dir` | `Path` | `~/.hooty/projects/{slug}-{hash}/` |
| `project_memory_db_path` | `str` | `project_dir / "memory.db"` |
| `global_memory_db_path` | `str` | `config_dir / "memory.db"` |

### ディレクトリ構造（全体）

```
~/.hooty/
├── config.yaml
├── memory.db                    ← グローバル記憶
├── sessions.db
├── locks/
├── projects/
│   ├── myapp-a3f1b2c4/
│   │   ├── .meta.json           ← プロジェクトメタデータ
│   │   └── memory.db            ← プロジェクト記憶
│   └── backend-e7d2f091/
│       ├── .meta.json
│       └── memory.db
└── sessions/
    └── {session-id}/
        ├── tmp/
        └── plans/
```
