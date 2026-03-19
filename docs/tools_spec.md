# ツール仕様書

## 概要

Hooty は以下の 13 カテゴリのツールを LLM エージェントに提供する:

| カテゴリ | 実装 | 説明 |
|---|---|---|
| コーディングツール | Agno 組み込み `CodingTools` | ファイル操作・シェル実行・コード探索の統合ツールキット |
| PowerShell ツール | 独自 `PowerShellTools` | Windows 環境での PowerShell コマンド実行 |
| ユーザー質問ツール | 独自 `AskUserTools` | LLM からの質問（自由入力・選択肢） |
| メモリツール | Agno 組み込み `update_user_memory` | プロジェクト知識・ユーザー嗜好の永続記憶 |
| GitHub 連携 | Agno 組み込み `GithubTools` | PR・Issue の操作 |
| Web 検索 | Agno 組み込み `DuckDuckGoTools` | DuckDuckGo による Web 検索・ニュース検索 |
| Web サイト読み取り | Hooty 独自 `web_fetch`（httpx + BeautifulSoup） | URL の内容を読み取り（軽量・トークン節約・カスタム User-Agent） |
| SQL データベース | Agno 組み込み `SQLTools` | SQL データベースの操作 |
| MCP 拡張 | Agno 組み込み `MCPTools` | 外部 MCP サーバー経由のツール拡張 |
| プラン管理 | 独自 `PlanTools` | プランの一覧・取得・作成・更新・ステータス変更 |
| プランモード切替（計画→実装） | 独自 `ExitPlanModeTools` | プランモードからコーディングモードへ切り替え |
| プランモード切替（実装→計画） | 独自 `EnterPlanModeTools` | コーディングモードからプランモードへ切り替え |
| サブエージェント | 独自 `SubAgentTools` | サブエージェントへのタスク委譲 |

## ツール組み立て

`tools/__init__.py` の `build_tools(config, plan_mode, confirm_ref)` 関数でツール群を組み立てる。

```
build_tools(config, plan_mode=False, confirm_ref=None, ...)  # + agent_store 等
    │
    ├── HootyCodingTools を生成（常に有効、confirm_ref 付きで ConfirmableCodingTools）
    ├── PowerShellTools を生成（Windows かつ PowerShell が検出された場合）
    ├── AskUserTools を生成（常に有効）
    ├── GithubTools を生成（GITHUB_ACCESS_TOKEN がある場合）
    ├── DuckDuckGoTools を生成（ddgs がインストール済みの場合）
    ├── web_fetch_tools を生成（WebsiteReader ベースの軽量 web_fetch）
    ├── SQLTools を生成（active_db が設定されている場合）
    ├── MCPTools を生成（config.yaml に mcp 設定がある場合）
    ├── ExitPlanModeTools を生成（plan_mode=True の場合）
    ├── EnterPlanModeTools を生成（plan_mode=False の場合）
    ├── SubAgentTools を生成（agent_store がある場合）
    │
    └── List[Toolkit] を返却
```

## 1. コーディングツール

### 概要

`agno.tools.coding.CodingTools` を基に、ファイル操作・シェル実行・コード探索を統合的に提供する。Safe モード対応の `ConfirmableCodingTools` サブクラスにより、書き込み・編集・シェル実行前にユーザー確認を要求できる。

### クラス階層

```
CodingTools (agno)
  └── HootyCodingTools          ← _check_path/read_file/write_file/edit_file/run_shell をオーバーライド
        │                          + apply_patch/move_file/create_directory/tree を追加
        ├── ConfirmableCodingTools  ← Safe モード確認付き
        ├── SelectiveCodingTools    ← disallowed_tools で一部メソッドをブロック（サブエージェント用）
        └── PlanModeCodingTools     ← 書き込み系をブロック（Planning モード / read-only サブエージェント用）
```

### 実装

```python
from hooty.tools.coding_tools import create_coding_tools

# Safe モード無効時
coding_tools = create_coding_tools(
    working_directory=config.working_directory,
    extra_commands=config.allowed_commands,
    shell_timeout=config.shell_timeout,
    idle_timeout=config.idle_timeout,
    tmp_dir=session_tmp_dir,
    session_dir=session_dir,
    add_dirs=config.add_dirs,
)

# Safe モード有効時（confirm_ref が渡された場合）
coding_tools = create_coding_tools(
    working_directory=config.working_directory,
    confirm_ref=confirm_ref,
    extra_commands=config.allowed_commands,
    shell_timeout=config.shell_timeout,
    idle_timeout=config.idle_timeout,
    tmp_dir=session_tmp_dir,
    session_dir=session_dir,
    add_dirs=config.add_dirs,
)
```

`HootyCodingTools` は以下をオーバーライドする:
- `_check_path()` — `extra_read_dirs`（セッション/プロジェクト/追加ディレクトリ）内のパスを読み取り許可
- `_check_command()` — Agno 親クラスのバグあるパスチェックを回避し、シェル演算子ブロック + コマンド許可リストのみ適用
- `read_file()` — `extra_read_dirs` 内のパスに対してディレクトリ一覧機能付きで読み取り
- `write_file()` / `edit_file()` — `_is_in_allowed_base()` で `base_dir` と `additional_base_dirs` 内に制限。`--snapshot` 有効時はスナップショットフック付き（後述）
- `run_shell()` — `shell_runner.run_with_timeout()` を使用。idle timeout 検出、セッション一時ファイル管理、コマンド履歴記録を提供
- `grep()` — 4 段階フォールバック付き grep オーバーライド（後述）

### apply_patch（マルチファイルパッチ）

Claude Code 独自形式（`*** Begin Patch / *** End Patch`）のパッチを解析し、複数ファイルへの変更を 1 回のツール呼び出しで適用する。

**パッチフォーマット:**

```
*** Begin Patch
*** Add File: <path>        ← 新規ファイル作成（全行 + プレフィックス）
*** Update File: <path>     ← 既存ファイル更新（@@ コンテキスト + -/+ 行）
*** Move to: <new_path>     ← Update 内でリネーム（オプション）
*** Delete File: <path>     ← ファイル削除
*** End Patch
```

**実装:** `src/hooty/tools/apply_patch.py` にパーサー + 適用エンジン。`HootyCodingTools.apply_patch()` で呼び出し、パス検証・スナップショットフックを適用。

**コンテキストマッチング（UpdateFile）:** `@@` 行のコンテキスト文字列でファイル内の適用位置を特定する。3 段階フォールバック:
1. 完全一致（行内容がそのまま一致）
2. 空白差異許容（`strip()` 後に一致）
3. 部分一致（コンテキスト文字列を含む行）

**サブクラス対応:**
- `ConfirmableCodingTools`: 確認ダイアログ付き
- `SelectiveCodingTools`: `"apply_patch"` ブロックチェック
- `PlanModeCodingTools`: ブロック（`_APPLY_PATCH_BLOCKED_MSG`）

### move_file / create_directory（専用ファイル管理）

`run_shell` を経由しないファイル移動・ディレクトリ作成ツール。

- `move_file(src, dst)`: `src` と `dst` の両方をパス検証。存在チェック、親ディレクトリ自動作成、スナップショットフック付き
- `create_directory(path)`: パス検証付きでネストディレクトリを作成。非破壊操作のため Planning モードでも利用可能

**サブクラス対応:**
- `ConfirmableCodingTools`: `move_file` は確認ダイアログ付き、`create_directory` は確認なし（非破壊）
- `SelectiveCodingTools`: 両方ともブロックチェック
- `PlanModeCodingTools`: `move_file` はブロック、`create_directory` は許可

### ファイルスナップショットフック

`--snapshot` CLI オプション（または `config.yaml` の `snapshot.enabled: true`）有効時、`HootyCodingTools` の `write_file()` / `edit_file()` にスナップショットフックが挿入される:

1. `super().write_file()` / `super().edit_file()` 呼び出し**前**に `FileSnapshotStore.capture_before_write()` — 初回変更時のみ元ファイル内容を保存（新規ファイルは `__NEW_FILE__` センチネル）
2. 成功後に `FileSnapshotStore.record_after_write()` — ファイルの SHA-256 ハッシュを `last_hash` に記録（外部変更検知用）

スナップショットデータはセッションディレクトリ（`sessions/{id}/snapshots/`）に永続化され、`_index.json` でパス→スナップショットファイルのマッピングを管理する。

継承チェーンにより `ConfirmableCodingTools` / `PlanModeCodingTools` も自動対応:
- `ConfirmableCodingTools`: 確認キャンセル時は `super()` が呼ばれず `HootyCodingTools.write_file` に到達しないのでスナップショット不要
- `PlanModeCodingTools`: `write_file` / `edit_file` はブロックされるので到達しない

`ConfirmableCodingTools` は `write_file()`, `edit_file()`, `run_shell()` の実行前にユーザー確認を要求する。`PlanModeCodingTools` は Plan モード専用で、`write_file()` / `edit_file()` を完全にブロックし `exit_plan_mode()` への遷移を誘導、`run_shell()` のみ確認付きで許可する。

確認ダイアログ（`_confirm_action()`）は `threading.Lock` で直列化されており、agno の並列ツール呼び出し（`asyncio.to_thread()`）で複数のダイアログが同時に表示される問題を防止する。ロック取得後に `_auto_approve` を再チェック（double-checked locking）するため、先行スレッドが "A"（All）を選択した場合、後続スレッドはダイアログなしで即承認される。

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `read_file` | ファイルを行番号付きで読み取り | `file_path: str`, `offset: int = 0`, `limit: int = None` |
| `edit_file` | テキストマッチによる部分編集 | `file_path: str`, `old_text: str`, `new_text: str` |
| `write_file` | ファイルの新規作成・上書き（親ディレクトリ自動作成） | `file_path: str`, `contents: str` |
| `apply_patch` | Claude Code 形式のマルチファイルパッチを適用 | `patch: str` |
| `move_file` | ファイルの移動・リネーム（親ディレクトリ自動作成） | `src: str`, `dst: str` |
| `create_directory` | ディレクトリの作成（ネスト対応） | `path: str` |
| `run_shell` | シェルコマンドの実行（タイムアウト付き） | `command: str`, `timeout: int = None` |
| `grep` | ファイル内容のパターン検索 | `pattern: str`, `path: str = None`, `ignore_case: bool = False`, `include: str = None`, `context: int = 0`, `limit: int = 100`, `ignore: bool = True` |
| `find` | グロブパターンによるファイル検索 | `pattern: str`, `path: str = None`, `limit: int = 500`, `ignore: bool = True` |
| `ls` | ディレクトリ内容の一覧 | `path: str = None`, `limit: int = 500`, `ignore: bool = True` |
| `tree` | 再帰的なディレクトリツリー表示 | `path: str = None`, `depth: int = 3`, `limit: int = 200`, `ignore: bool = True` |

### セキュリティ

- ファイル操作（`read_file`/`write_file`/`edit_file`/`apply_patch`/`move_file`/`create_directory`/`grep`/`find`/`ls`/`tree`）は `base_dir` 配下に制限（`restrict_to_base_dir=True`、`_check_path` で検証）。`run_shell` はパス制限なし
- **追加作業ディレクトリ（`additional_base_dirs`）**: `--add-dir` / `/add-dir` で指定したディレクトリ。`read_file`/`write_file`/`edit_file`/`apply_patch`/`move_file`/`create_directory`/`grep`/`find`/`ls`/`tree` がアクセス可能。シェルの cwd は `base_dir` 固定
- **追加読み取りディレクトリ（`extra_read_dirs`）**: セッションディレクトリ・プロジェクトディレクトリ・追加作業ディレクトリを `_check_path` オーバーライドで読み取り許可
- ディレクトリトラバーサル（`../` 等）は Agno 側で防止
- シェル演算子制御（`tools.shell_operators` で設定可能）:
  - コマンド置換（`$(`, `` ` ``）— 常時ブロック（許可リスト検証をバイパスするため）
  - パイプ（`|`）— デフォルト許可、各セグメントを許可リストで個別検証
  - チェーン（`&&`, `||`, `;`）— デフォルト許可、各セグメントを許可リストで個別検証
  - リダイレクト（`>`, `>>`, `<`）— デフォルトブロック。`2>&1` / `N>/dev/null` は安全パターンとして常時許可
- コマンド許可リスト制で未登録コマンドの実行を防止（パイプ/チェーンの各セグメントも個別検証）
- 出力上限: 2000 行 / 50KB（超過分は一時ファイルに保存）
- **stdin=/dev/null**: 全サブプロセスに `stdin=subprocess.DEVNULL` を指定。インタラクティブモードを持つ CLI ツール（`python`, `node`, `pnpm` 等）が引数なしで呼ばれた場合、stdin 入力待ちでハングせず即座に EOF を受け取って終了する。`shell=True` でのシェル内リダイレクト（heredoc `<<EOF`、パイプ `|`、ファイルリダイレクト `< file`）には影響しない
- エンコーディング: 全 `subprocess.run` に `encoding="utf-8", errors="replace"` を指定。Windows のデフォルト (cp932) による `UnicodeDecodeError` を防止
- CTRL+C (KeyboardInterrupt) 時にプロセスを確実に kill しクリーンアップ
- **Windows プロセス分離**: 全 `subprocess.run` / `subprocess.Popen` に `creationflags=CREATE_NEW_PROCESS_GROUP` を指定。subprocess 実行に起因する stale `CTRL_C_EVENT` による誤キャンセル（"Response cancelled"）を防止。`grep` の subprocess にも同様に適用
- **Windows CTRL_C_EVENT 抑制**: `SetConsoleCtrlHandler` API でツール実行中および完了後 5 秒間（`_WIN_STALE_WINDOW`）の `CTRL_C_EVENT` を抑制。並列ツール実行時の複数 stale イベントにも対応。**トレードオフ**: この間は `Ctrl+C` によるキャンセルが効かない
- **Windows コンソール入力バッファ flush**: Safe モード確認ダイアログ後に `msvcrt.kbhit()`/`msvcrt.getwch()` で ConPTY のエスケープシーケンス エコーバックを drain し、後続の入力読み取りへの干渉を防止
- `idle_timeout` 有効時、プロセスハングを自動検出して kill
- **`_check_command` オーバーライド**: Agno 親クラスのバグあるパスチェック（チルダ未展開・バックスラッシュ未検出）を回避するため、`HootyCodingTools` で常時オーバーライド。シェル演算子制御 + コマンド許可リストのみ適用。パスチェックは行わない — safe mode ON ではユーザー確認ダイアログがゲート、safe mode OFF ではユーザーが意図的に制限を解除。Agent instructions でワーキングディレクトリ情報を伝達し、LLM の行動をガイドする
- **シェル演算子制御（`tools.shell_operators`）**: パイプ/チェーン演算子はデフォルトで許可し、各セグメントの先頭コマンドを許可リストで個別検証する。コマンド置換（`$(`, `` ` ``）は許可リスト検証をバイパスするため常時ブロック。リダイレクトはデフォルトブロックだが `tools.shell_operators.redirect: true` で許可可能。`2>&1` / `N>/dev/null` 等の安全な stderr リダイレクトパターンは常時許可

### grep オーバーライド（rg 優先 + 4 段階フォールバック）

Agno の `CodingTools.grep()` は外部の `grep` コマンドに依存しているため、Windows 環境（`Git\usr\bin` が PATH にないケース等）では動作しない。`HootyCodingTools` は `grep()` をオーバーライドし、以下の優先順位で自動フォールバックする:

```
1. ~/.hooty/pkg/<os-arch>/rg  (GitHub Releases から自動ダウンロード)
2. PATH 上の rg               (ユーザーがインストール済み)
3. PATH 上の grep              (Linux/macOS/Git for Windows)
4. Python 純正実装             (依存ゼロ、最終手段)
```

#### バックエンド検出

`HootyCodingTools.__init__` で `pkg_manager.find_pkg("rg")` → `shutil.which("grep")` の順に検出し、`_grep_backend` 属性（`"rg"` / `"grep"` / `"python"`）に記録する。`/rescan` コマンドで Agent を再生成すると検出もリフレッシュされる。

#### ripgrep バックエンド（`_grep_rg`）

`[rg, -n, --no-heading]` で `file:line:match` フォーマットを保証。`include` は `--glob` に変換。`.gitignore` は rg がネイティブに処理。`_ignore_dirs` の各ディレクトリを `--glob !{dir}` で追加除外。`encoding="utf-8", errors="replace"` でデコード。

#### システム grep バックエンド（`_grep_cmd`）

`["grep", "-rn"]` + `-i`, `-C N`, `--include`。`_ignore_dirs` の各ディレクトリを `--exclude-dir {dir}` で除外。`encoding="utf-8", errors="replace"` でデコード。

#### Python フォールバック（`_grep_python`）

外部コマンドに一切依存しない純正実装:

- ファイル走査: `pathlib.Path.rglob()`、`include` 指定時はそのグロブパターンで絞り込み
- ディレクトリ除外: `_ignore_dirs` に含まれるディレクトリ配下をスキップ
- バイナリ判定: 先頭 8192 バイトに `\x00` があればスキップ
- パターンマッチ: `re.compile()` による正規表現（`ignore_case` 対応）
- コンテキスト行: マッチ行 ± context 行を収集、非隣接グループ間に `--` セパレータ
- 出力形式: `relative/path:行番号:マッチ行`（コンテキスト行は `relative/path:行番号-行内容`）
- エンコーディング: `errors="replace"` で安全にデコード

#### ディレクトリ除外ルール

`ls`/`find`/`grep`/`tree` の全ツール・全バックエンドが共通の `_ignore_dirs` を参照する。`ignore=True`（デフォルト）で除外が有効、`ignore=False` で除外なし検索が可能。

```
_ALWAYS_IGNORE = {".git"}  ← 常時除外

.gitignore あり:
  _ALWAYS_IGNORE ∪ .gitignore 抽出 ∪ config.yaml tools.ignore_dirs

.gitignore なし（非 git プロジェクト）:
  _ALWAYS_IGNORE ∪ _FALLBACK_IGNORE_DIRS ∪ config.yaml tools.ignore_dirs
```

- `.gitignore` 抽出: ルートの `.gitignore` のみ解析。単純名のみ（ワイルドカード・パスセパレータ・否定なし）。末尾 `/` は strip（例: `dist/` → `dist`）
- `_FALLBACK_IGNORE_DIRS`: `.gitignore` がない場合の最小フォールバック — `node_modules`, `__pycache__`, `.venv`
- `config.yaml tools.ignore_dirs`: ユーザー定義の追加除外ディレクトリ

#### パッケージマネージャー（`pkg_manager.py`）

ripgrep の自動ダウンロードを含む汎用バイナリパッケージ管理。将来 `fd`, `bat` 等の追加にも対応可能。

```
~/.hooty/pkg/
├── x86_64-windows/
│   └── rg.exe
├── x86_64-linux/
│   └── rg
└── aarch64-darwin/
    └── rg
```

| 関数 | 説明 |
|---|---|
| `find_pkg(name)` | ローカルキャッシュ → PATH の順に検索（ダウンロードしない） |
| `ensure_pkg(name)` | `find_pkg` で見つからなければ GitHub Releases からダウンロード |
| `missing_packages()` | 現プラットフォームで未インストールのパッケージ一覧を返す |
| `platform_tag()` | `{arch}-{os}` 形式のプラットフォームタグ（例: `x86_64-windows`） |
| `pkg_dir()` | managed パッケージディレクトリのパスを返す（存在しなければ `None`） |

#### `run_shell` からの利用

`coding_tools.py` のモジュールロード時に `pkg_dir()` で managed パッケージディレクトリを `os.environ["PATH"]` に追加する（Git usr/bin の追加と同じパターン）。これによりサブプロセスが managed バイナリ（`rg` 等）を自動的に継承する。また `rg` は `_SHELL_UTILS` 許可コマンドリストに含まれており、`_filter_available_commands()` で PATH 上に存在する場合のみ有効化される。

#### REPL 起動時のダウンロード確認

REPL 起動直後（Agent 生成前）に `missing_packages()` で不足パッケージをチェック:

- **初回**（`pkg.auto_download` 未設定）: `hotkey_select` ダイアログでパッケージ一覧と GitHub ソースを表示し Y/N を確認。結果を `config.yaml` に保存
- **承認済み**（`pkg.auto_download: true`）: 自動ダウンロード
- **拒否済み**（`pkg.auto_download: false`）: 何もしない（grep は Python フォールバックで動作）

```yaml
# ~/.hooty/config.yaml
pkg:
  auto_download: true  # true / false / 未設定(初回確認)
```

### 許可コマンド一覧

CodingTools デフォルト（`grep`, `find`, `ls` 等）に加え、共有開発ツールコマンド（`dev_commands.py`）とシェルユーティリティを追加する。

#### PATH フィルタリング

許可コマンドリストは `shutil.which()` で **実際に PATH 上に存在するコマンドのみ** にフィルタリングされる（`_filter_available_commands()`）。これにより、Windows 環境で `grep` 等の Unix コマンドが PATH にない場合、LLM に実行不可能なコマンドを提示しなくなる。フィルタ結果はセッション中キャッシュされ、`/rescan` コマンドで手動リフレッシュできる。

フィルタは以下の 2 箇所を検索する:
1. **PATH**（`shutil.which(cmd)`）
2. **作業ディレクトリ**（`shutil.which(cmd, path=base_dir)`）— `mvnw`, `gradlew` 等のプロジェクトローカルラッパーを検出

`shutil.which()` は Windows の `PATHEXT`（`.exe`, `.bat`, `.cmd` 等）を自動的に考慮するため、`gradlew.bat` のようなラッパーも正しく検出される。

このフィルタは CodingTools と PowerShellTools の両方に適用される（PowerShell の組み込みコマンドレットはフィルタ対象外）。

#### 共有開発ツールコマンド（CodingTools / PowerShellTools 共通）

| カテゴリ | コマンド |
|---|---|
| 汎用 | `git`, `make`, `docker`, `docker-compose` |
| Python | `python`, `python3`, `pip`, `pip3`, `uv`, `ruff`, `pytest`, `mypy`, `pyright` |
| JavaScript / TypeScript | `node`, `npm`, `npx`, `yarn`, `pnpm`, `bun`, `deno`, `tsc`, `tsx` |
| Java | `java`, `javac`, `mvn`, `mvnw`, `gradle`, `gradlew` |
| Go | `go`, `gofmt`, `gopls` |
| Rust | `cargo`, `rustc`, `rustup`, `rustfmt` |
| C / C++ | `gcc`, `g++`, `clang`, `clang++`, `cmake`, `ninja` |
| Ruby | `ruby`, `gem`, `bundle`, `rake` |
| .NET | `dotnet` |

#### シェルユーティリティ（CodingTools のみ）

| カテゴリ | コマンド |
|---|---|
| ネットワーク | `curl`, `wget` |
| 環境・システム情報 | `which`, `env`, `pwd`, `date`, `uname`, `whoami`, `id`, `nproc` |
| テキスト処理 | `tee`, `xargs`, `sed`, `awk`, `nl`, `paste`, `comm`, `tac`, `rev`, `expand`, `unexpand` |
| ファイル情報 | `file`, `stat` |
| パス操作 | `basename`, `dirname`, `realpath`, `readlink` |
| チェックサム | `md5sum`, `sha256sum` |
| アーカイブ・圧縮 | `tar`, `zip`, `unzip`, `gzip`, `gunzip`, `zcat`, `bzip2`, `bunzip2`, `xz`, `unxz` |
| managed パッケージ | `rg` |

#### ユーザー定義コマンド

`config.yaml` の `tools.allowed_commands` で追加のコマンドを許可できる。CodingTools と PowerShellTools の両方に適用される。

```yaml
# ~/.hooty/config.yaml
tools:
  allowed_commands:
    - terraform
    - kubectl
    - helm
```

## 2. GitHub 連携ツール

### 実装

`agno.tools.github.GithubTools` を使用する。`GITHUB_ACCESS_TOKEN` 環境変数が設定されている場合のみ有効化する。

```python
from agno.tools.github import GithubTools

github_tools = GithubTools()
```

### 提供される関数

| 関数 | 説明 |
|---|---|
| `search_repositories` | リポジトリ検索 |
| `get_repository` | リポジトリ情報の取得 |
| `list_pull_requests` | PR 一覧の取得 |
| `get_pull_request` | PR 詳細の取得 |
| `create_pull_request` | PR の作成 |
| `list_issues` | Issue 一覧の取得 |
| `get_issue` | Issue 詳細の取得 |
| `create_issue` | Issue の作成 |

### 認証

```bash
export GITHUB_ACCESS_TOKEN=ghp_xxxxxxxxxxxx
```

- `GITHUB_ACCESS_TOKEN` が未設定の場合、`build_tools()` で `GithubTools` を生成せずスキップする
- エラーにはしない（GitHub 機能は任意）

### 使用例

```
> このリポジトリの未対応 Issue を一覧して

  ⚙ list_issues(repo="user/repo", state="open")

  オープンな Issue は以下の通りです:

  #42 バグ: ログイン画面でエラーが発生する
  #38 機能要望: ダークモード対応
  #35 ドキュメント: API リファレンスの更新

>
```

## 3. SQL データベースツール

### 概要

SQL データベースの操作機能を提供する。Agno 組み込みの `SQLTools` を使用する。接続設定は `~/.hooty/databases.yaml` に複数定義可能で、`/database connect <name>` スラッシュコマンドで接続先を切り替える。

### 制約

Agno の SQLTools は関数名が固定（`list_tables`, `describe_table`, `run_sql_query`）で、複数インスタンスを Agent に追加すると関数名が衝突する。そのため **接続は常に1つだけ** とし、切り替え方式で対応する。

### 設定（databases.yaml）

```yaml
# ~/.hooty/databases.yaml

databases:
  local: "sqlite:///./data/app.db"
  analytics: "postgresql://admin:secret@localhost:5432/mydb"
  staging: "mysql://user:pass@host/db"
```

`databases` キー配下に `名前: SQLAlchemy接続URL` のフラットなマッピングで定義する。

### 実装

```python
from agno.tools.sql import SQLTools

sql_tools = SQLTools(db_url="sqlite:///./data/app.db")
```

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `list_tables` | テーブル一覧を取得 | なし |
| `describe_table` | テーブルのスキーマを表示 | `table_name: str` |
| `run_sql_query` | SQL クエリを実行 | `query: str` |

### スラッシュコマンド

| コマンド | 説明 |
|---|---|
| `/database` | 現在の接続先を表示 |
| `/database list` | 登録済み DB 一覧を表示 |
| `/database connect <name>` | 指定 DB に接続（Agent 再生成） |
| `/database disconnect` | DB 接続を解除（Agent 再生成） |
| `/database add <name> <url>` | DB 接続を追加（databases.yaml に保存） |
| `/database remove <name>` | DB 接続を削除（databases.yaml から削除） |

### 有効化条件

- `databases.yaml` に少なくとも 1 つの DB が登録されていること
- `/database connect <name>` で接続先が選択されていること
- `sqlalchemy` がインストール済みであること（agno の sql 依存に含まれる）

### 使用例

```
> /database connect local

  ✓ DB 'local' に接続しました

> ユーザーテーブルの構造を教えて

  ⚙ describe_table(table_name="users")

  users テーブルのスキーマ:
  - id: INTEGER (PRIMARY KEY)
  - name: VARCHAR(100)
  - email: VARCHAR(200)

>
```

## 4. MCP 拡張ツール

### 概要

MCP（Model Context Protocol）を使用して、ユーザーが自由にツールを追加できる仕組みを提供する。MCP サーバーの設定は `~/.hooty/mcp.yaml`（グローバル）および `<working_dir>/.hooty/mcp.yaml`（プロジェクト固有）で管理する。

### 設定

グローバルとプロジェクト固有の 2 階層で設定する。両方が存在する場合、プロジェクト側が後勝ちでマージされる（Agents パターン — dict 置換・後勝ち）。

```yaml
# ~/.hooty/mcp.yaml（グローバル）
servers:
  # stdio 接続: コマンドを起動して stdin/stdout で通信
  filesystem:
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - /home/user/documents

  # Streamable HTTP 接続（デフォルト）
  my-api:
    url: http://localhost:8080/mcp

  # URL 接続 + 認証ヘッダー
  authed-api:
    url: https://api.example.com/mcp
    headers:
      Authorization: Bearer <token>

  # 環境変数付き stdio 接続
  database:
    command: python
    args: ["-m", "mcp_server_sqlite", "mydb.sqlite"]
    env:
      MCP_LOG_LEVEL: debug
```

> **WSL 環境での注意:** WSL2 から Windows `.exe`（`.cmd` / `.bat` 含む）を MCP stdio サーバーとして起動する場合、`env` で指定した環境変数は自動的には Windows プロセスに転送されない。WSL は `WSLENV` 環境変数に列挙された変数名のみを Windows プロセスに転送する仕組みのため、Hooty は WSL 検出時に `env` の全キーを `WSLENV` に自動付与する。ネイティブ Linux バイナリには `WSLENV` は無害（WSL interop のみが参照）。

```yaml
# <project>/.hooty/mcp.yaml（プロジェクト固有）
servers:
  # プロジェクト専用の Playwright MCP
  playwright:
    command: npx
    args: [-y, "@anthropic-ai/mcp-server-playwright"]

  # グローバルの filesystem を上書き（スコープをプロジェクトに限定）
  filesystem:
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - /mnt/d/project
```

**マージ戦略:**
- 同名サーバー: プロジェクト側の定義で **完全置換**
- プロジェクト固有サーバー: **追加**
- サーバー名 = 名前空間。両方使いたい場合はキー名を分ける（例: `filesystem` + `project-fs`）

### ツール名前空間

MCP ツールは `mcp__{サーバー名}__{ツール名}` の形式で LLM に公開される。これは Claude Code が確立し、Docker MCP Gateway・MetaMCP 等が採用する業界標準パターン。

**目的:** 組み込みツール（`read_file`, `edit_file` 等）との名前衝突を回避する。

**例:** `mcp.yaml` に `filesystem` サーバーを定義した場合:

| MCP 元ツール名 | 公開名 |
|---|---|
| `read_file` | `mcp__filesystem__read_file` |
| `search_files` | `mcp__filesystem__search_files` |
| `list_directory` | `mcp__filesystem__list_directory` |

複数サーバーを同時利用する場合も名前空間で分離される:

| サーバー名 | 公開ツール例 |
|---|---|
| `filesystem` | `mcp__filesystem__read_file` |
| `playwright` | `mcp__playwright__navigate` |
| `database` | `mcp__database__query` |

**実装:** Agno の `MCPTools(tool_name_prefix=...)` パラメータを使用。`tool_name_prefix="mcp__{name}_"` を渡すと、Agno が `{prefix}_{tool_name}` に展開し `mcp__{name}__{tool_name}` となる。

### 個別 ON/OFF

サーバー個別の有効/無効状態は `~/.hooty/projects/<slug>/.mcp.json` に永続化される。Skills（`.skills.json`）・Hooks（`.hooks.json`）と同じパターン。

- `/mcp`（引数なし）: インタラクティブピッカーで切り替え
- `/mcp add [--global] [--transport http|sse] [-h/--header "Key: Value" ...] <name> <url>`: URL ベースサーバーを追加（ヘッダー・トランスポート指定可）
- `/mcp add [--global] [-e/--env KEY=VAL ...] <name> <command> [args...]`: stdio サーバーを追加
- `/mcp remove [--global] <name>`: サーバーを削除
- `/mcp list`: 全サーバー一覧（ソース・有効/無効表示）
- `/mcp reload`: 両ファイルから再ロード + Agent 再生成

### 実装

`tools/mcp_tools.py` で設定ファイルから MCP サーバー一覧を読み取り、それぞれの `MCPTools` インスタンスを生成する。

```python
from agno.tools.mcp import MCPTools

def create_mcp_tools(mcp_config: dict, *, mcp_debug: bool = False) -> tuple[list[MCPTools], list[str]]:
    """MCP 設定から MCPTools インスタンスのリストを生成する。

    Returns (tools, warnings) — warnings はスピナー後に表示するため遅延。
    """
    tools, warnings = [], []
    for name, server_config in mcp_config.items():
        # バリデーション: config が dict か、command/url が非空 string か、
        # args が list か、env が dict か をチェック。
        # 違反時は warnings に追加してスキップ。
        prefix = f"mcp__{name}_"  # Agno adds "_" → "mcp__{name}__tool"
        if "url" in server_config:
            tools.append(MCPTools(url=..., tool_name_prefix=prefix))
        elif "command" in server_config:
            tool = MCPTools(server_params=StdioServerParameters(...), tool_name_prefix=prefix)
            _suppress_stdio_stderr(tool, server_name=name, passthrough=mcp_debug)
            tools.append(tool)
    return tools, warnings
```

### 接続ライフサイクル

```
Hooty 起動
    │
    ▼
mcp.yaml を読み込み（global → project 後勝ちマージ）
    │
    ▼
.mcp.json の disabled サーバーを除外
    │
    ▼
各 MCP サーバーの MCPTools インスタンスを生成
  （バリデーション: command/url の型・空値、args/env の型チェック）
  （警告は config._mcp_warnings に蓄積 → スピナー後に表示）
    │
    ▼
Agent のツールリストに追加（mcp__{name}__ プレフィックス付き）
    │
    ▼
バナー表示後: check_mcp_health() — 各 MCPTools に connect() を試行
    ├── ✓ connected: 接続成功
    ├── ✗ failed to connect: 接続失敗（_initialized=False）
    └── ✗ not responding: 接続済みだが ping 失敗
    │
    ▼
（対話中、LLM が必要に応じて MCP ツールを呼び出し）
    │
    ▼
Agent 再作成時（モード切替・セッション切替・/mcp reload 等）
    ├── _close_mcp_tools() で旧 MCPTools を明示的に close
    ├── stdio: _StderrPipe.mute() → close()（シャットダウンノイズ抑制）
    └── 新しい Agent が connect → close サイクルを再開
    │
    ▼
Hooty 終了時
    ├── os._exit(0) で強制終了（MCP close / loop shutdown はスキップ）
    ├── os._exit により全サブプロセス・コネクションが暗黙的に解放される
    └── 注: _close_mcp_tools() / _shutdown_loop() は os._exit 前に実行すると
        ProactorEventLoop の IOCP select でハングする可能性があるため省略
```

#### stdio 接続の stderr 管理（`_StderrPipe`）

Agno は MCPTools を **毎回の agent run で connect → close するサイクル** で運用する。stdio 接続では `stdio_client(errlog=...)` で stderr 出力先を制御する。

`anyio.open_process` は `stderr` パラメータに `fileno()` を持つ実ファイルを要求するため、純 Python のファイルライクオブジェクトは使えない。`_StderrPipe` は `os.pipe()` で実ファイルディスクリプタを作成し、デーモンスレッドで read 側を消費して `logger.debug` に転送する:

- `_patched_connect()`: 毎回新しい `_StderrPipe` を作成し `tool._stderr_pipe` に保持
- `_patched_close()`: `mute()` でシャットダウンノイズを抑制後、`close()` でパイプとスレッドをクリーンアップ
- `passthrough=True`（`--mcp-debug`）: `logger.debug` に加えて `sys.stderr` にも echo
- `passthrough=False`（デフォルト）: `logger.debug` のみ（`--debug` 時に可視化）

| モード | stderr の行き先 |
|---|---|
| 通常 | `logger.debug`（非表示） |
| `--debug` | `logger.debug`（DEBUG レベルで表示） |
| `--mcp-debug` | `logger.debug` + `sys.stderr`（端末に直接表示） |
| `tools.mcp_debug: true` | `--mcp-debug` と同等 |

#### WSL 環境での環境変数転送（WSLENV）

WSL2 から Windows プロセス（`.exe` / `.cmd` / `.bat`）を起動する場合、`subprocess.Popen(env=dict)` で設定した環境変数は WSL→Windows interop 境界を越えて転送されない。WSL は `WSLENV` 環境変数に列挙された変数名のみを Windows プロセスに転送する。

Hooty は以下のロジックで自動対応する:

1. `_is_wsl()`: `/proc/version` に `"microsoft"` が含まれるかで WSL を検出（`lru_cache` でキャッシュ）
2. WSL 上かつ `env` が指定されている場合、`env` の全キーを `WSLENV` に追加（既存の `WSLENV` があればマージ）
3. ネイティブ Linux バイナリは `WSLENV` を無視するため、コマンドが `.exe` かどうかの判定は不要

| 条件 | 動作 |
|---|---|
| WSL 以外 | 変更なし |
| WSL + env なし | 変更なし |
| WSL + env あり | env の全キーを `WSLENV` に追加 |

#### Agent 再作成時の MCP クローズ

Agent を再作成する全箇所で、新 Agent 生成前に `_close_mcp_tools()` を呼び出す:

| 箇所 | トリガー |
|---|---|
| `_send_to_agent()` | plan mode 不一致による暗黙の Agent 再作成 |
| `_auto_transition_to_code()` | Planning → Coding モード切替 |
| `_auto_transition_to_plan()` | Coding → Planning モード切替 |
| `_switch_session()` | セッション切替 |
| `/mcp reload` | MCP サーバー設定の再読み込み |
| `/mcp`（picker） | MCP サーバーの有効/無効切替 |

Agno が run 終了時に既に close している場合、`_initialized` チェックにより二重 close はスキップされる。`CommandContext` に `close_mcp_tools` / `run_mcp_health_check` コールバックを追加し、コマンドモジュールからも呼び出し可能にしている。

### エラーハンドリング

#### 起動時ヘルスチェック（`check_mcp_health()`）

バナー表示直後に全 MCP ツールの接続を試行し、結果を表示する:

```
  ✓ MCP server 'dify-kb' connected
  ✗ MCP server 'broken-srv' failed to connect
  Use '/mcp reload' to retry failed connections.
```

Agno SDK は `MCPTools.connect()` の失敗を `log_error()` するだけで例外を送出しないため、Hooty 層でヘルスチェックを行い、ユーザーに明示的なフィードバックを提供する。`/mcp reload` 後にも同じヘルスチェックが実行される。

#### mcp.yaml バリデーション

`create_mcp_tools()` で以下のバリデーションを実行。違反時は警告メッセージを返し、該当サーバーをスキップする:

| チェック項目 | エラーメッセージ |
|---|---|
| `server_config` が dict でない | `config must be a mapping` |
| `url` が非空 string でない | `url must be a non-empty string` |
| `command` が非空 string でない | `command must be a non-empty string` |
| `args` が list でない | `args must be a list` |
| `env` が dict でない | `env must be a mapping` |
| `url` も `command` もない | `url or command is required` |
| その他の例外（pydantic 等） | 最初の行のみ表示 |

#### 実行時エラー分類

| エラーメッセージに含まれる語 | 分類 | 表示 |
|---|---|---|
| `mcp` / `stdio` | MCP 接続エラー | `✗ MCP connection error` + `/mcp reload` 案内 |
| `cancelled` | ユーザーキャンセル | `✗ Request was cancelled` |
| `too long` / `token` | セッション長超過 | `✗ Session history is too long` |
| その他 | 汎用エラー | `✗ {error message}` |

#### その他

| 状況 | 対応 |
|---|---|
| MCP サーバーの起動失敗 | 警告メッセージを表示し、該当サーバーをスキップ。他のツールは有効 |
| `mcp` パッケージ未インストール | `pip install hooty[mcp]` を案内 |

### 必要パッケージ

```
pip install hooty[mcp]
# → mcp パッケージがインストールされる
```

## 5. Web 検索ツール

### 概要

DuckDuckGo を使った Web 検索機能を提供する。Agno 組み込みの `DuckDuckGoTools` を使用する。デフォルトは無効で、`/websearch` コマンドで有効化する。`ddgs` パッケージが未インストールの場合は有効化してもスキップされる。

### 実装

```python
from agno.tools.duckduckgo import DuckDuckGoTools

search_tools = DuckDuckGoTools(search=True, news=True, fixed_max_results=3)
```

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `web_search` | Web 検索を実行 | `query: str`, `max_results: int = 5` |
| `search_news` | ニュース検索を実行 | `query: str`, `max_results: int = 5` |

### 有効化条件

- `/websearch` コマンドで有効化（デフォルト OFF）
- `ddgs` パッケージがインストール済みであること
- 環境変数やトークンは不要（DuckDuckGo は認証不要）
- `ddgs` が未インストールの場合、エラーにはせずスキップする
- コンテキスト消費を抑えるため `fixed_max_results=3` で検索結果件数を制限

### 必要パッケージ

```
pip install hooty[search]
# → ddgs パッケージがインストールされる
```

### 使用例

```
> Pythonの最新バージョンについて調べて

  ⚙ web_search(query="Python latest version 2026")

  Python の最新バージョンは 3.14 です。
  2026年1月にリリースされました。

>
```

## 6. Web サイト読み取りツール

### 概要

指定した URL の内容を読み取る機能を提供する。httpx + BeautifulSoup で直接実装し、カスタム User-Agent（`hooty/{version}`）を全リクエストに適用する。

**設計方針（コンテキスト消費削減）:**
- **デフォルトはクロールしない** — `max_depth=1`, `max_links=1`（1 ページのみ取得）
- **テキスト切り詰め** — デフォルト 20,000 文字で切り詰め。`max_chars` パラメータで最大 80,000 まで拡大可能（web-researcher 等の深い調査用）
- **JSON ラッパー不要** — プレーンテキストを直接返却
- **上限クランプ** — LLM がパラメータを拡大しても `max_depth` ≤ 2, `max_links` ≤ 3 に制限（暴走防止）
- **カスタム User-Agent** — `hooty/{version} (Interactive AI coding assistant)` を全リクエストに設定

> **背景:** Agno の `WebsiteTools.web_fetch()` は内部で `WebsiteReader(max_depth=3, max_links=10)` を使い、1 URL のリクエストで最大 10 ページをクロールする。天気のような単純なクエリでも 186k トークンを消費しコンテキストがほぼ枯渇する問題があった。`WebsiteReader` はカスタムヘッダーを渡す手段がないため、httpx + BeautifulSoup による直接実装に置き換えた。

### 実装

```python
import httpx
from bs4 import BeautifulSoup
from agno.tools import Toolkit
from hooty import __version__

_DEFAULT_MAX_CHARS = 20_000
_ABSOLUTE_MAX_CHARS = 80_000
_TIMEOUT = 10
_HEADERS = {"User-Agent": f"hooty/{__version__} (Interactive AI coding assistant)"}

def web_fetch(url: str, max_depth: int = 1, max_links: int = 1, max_chars: int = 20000) -> str:
    max_depth = max(1, min(max_depth, 2))
    max_links = max(1, min(max_links, 3))
    max_chars = max(1000, min(max_chars, _ABSOLUTE_MAX_CHARS))
    resp = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    soup = BeautifulSoup(resp.text, "html.parser")
    text = _extract_main_content(soup)
    # ... 同一ドメインリンク追跡・テキスト結合・切り詰め・エラーハンドリング

toolkit = Toolkit(name="web_fetch", tools=[web_fetch])
```

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `web_fetch` | URL の内容を読み取り | `url: str`, `max_depth: int = 1`（最大 2）, `max_links: int = 1`（最大 3）, `max_chars: int = 20000`（最大 80000） |

### 有効化条件

- デフォルト ON（常時有効、Web 検索とは独立）
- `httpx` + `beautifulsoup4` パッケージがインストール済みであること（本体依存に含まれる）
- 環境変数やトークンは不要
- カスタム User-Agent: `hooty/{version} (Interactive AI coding assistant)`

### デバッグログ

`--debug` 有効時、以下のログが出力される:

| ログ | タイミング |
|---|---|
| `[web] web_fetch: <URL> (max_depth=N, max_links=N)` | リクエスト開始時 |
| `[web] web_fetch: fetched <page> (N chars)` | 各ページ取得時 |
| `[web] web_fetch: truncating N -> 20000 chars` | 切り詰め発生時 |
| `[web] web_fetch: returning N chars (N pages)` | 最終結果 |
| `[web] web_fetch: error reading <URL>: <reason>` | エラー時 |

### 必要パッケージ

```
pip install hooty[search]
# → ddgs>=9.11.3, beautifulsoup4 パッケージがインストールされる
```

### 使用例

```
> https://example.com/release-notes の内容を要約して

  ⚙ web_fetch(url="https://example.com/release-notes")

  リリースノートの要約:
  - v2.0: 新しい API エンドポイントの追加
  - v1.9: パフォーマンス改善

>
```

## 7. 推論（Plan モード）

### 概要

Plan モード時に深い推論能力を提供する。ネイティブ推論（Anthropic: Extended Thinking / Azure OpenAI GPT-5.2+: Reasoning Effort）のみを使用する。CoT フォールバック（Agno `ReasoningTools`）は廃止済み。

推論はデフォルト `auto` モードで、ユーザーのメッセージ内のキーワード（`think`, `ultrathink` 等）に応じてリクエスト単位でレベルを動的に設定する。`auto_level`（デフォルト `1`）でキーワードなし時のデフォルトレベルを指定可能。デフォルトでは常にレベル 1 の推論が有効。

### 動作マトリクス

| モデル | reasoning mode | Native Reasoning |
|---|---|---|
| Anthropic Sonnet / Opus (対応モデル) | on / auto | 有効（Extended Thinking） |
| Azure OpenAI GPT-5.2+ | on / auto | 有効（reasoning_effort） |
| Bedrock / Azure AI Foundry (Claude, Grok reasoning 系) | on / auto | 有効（カタログ `supports_reasoning` 判定） |
| ネイティブ推論非対応モデル | on / auto | 無効（キーワードも `auto_level` も無視） |

### `/reasoning` ・ `/model` 切替時の動作

- `/reasoning` トグル: `_reasoning_active` を更新し UI に反映する。ツール構成は変わらないため Agent 再生成は不要。`_apply_reasoning()` が run ごとにモデルパラメータを動的に設定する。
- `/model` 切替: Plan モード時はツールを再利用せず必ず再構築する。`create_model()` が `_reasoning_active` を更新した後に `build_tools()` が実行されるため、新モデルの対応状況が正しく反映される。

### ExitPlanModeTools（Plan → Coding 遷移）

Plan モード時に登録される（ReasoningTools の有無に関わらず常時）。LLM が計画完了時に `exit_plan_mode()` を呼ぶことで、Plan → Coding モードの自動遷移を開始する。

```python
from hooty.tools.exit_plan_mode_tools import ExitPlanModeTools

tools.append(ExitPlanModeTools(
    auto_execute_ref=auto_execute_ref,
    pending_plan_ref=pending_plan_ref,
))
```

| 関数 | 説明 | 引数 |
|------|------|------|
| `exit_plan_mode` | Coding モードへの遷移を提案 | `plan_summary: str` |

呼び出し時: `auto_execute_ref[0] = True` + `pending_plan_ref[0] = plan_summary` を即座にセット。REPL がレスポンス終了後に `● Switch to coding mode?` 確認を表示し、承認されれば自動遷移を処理する。ツール内でのユーザー確認（`_confirm_action`）は行わない（REPL 側の 1 回のみ）。

### EnterPlanModeTools（Coding → Planning 遷移）

Coding モード時に登録される。LLM が `enter_plan_mode()` を呼ぶことで、Coding → Planning モードの遷移を開始する。

```python
from hooty.tools.enter_plan_mode_tools import EnterPlanModeTools

tools.append(EnterPlanModeTools(
    enter_plan_ref=enter_plan_ref,
    pending_reason_ref=pending_reason_ref,
    pending_revise_ref=pending_revise_ref,
))
```

| 関数 | 説明 | 引数 |
|------|------|------|
| `enter_plan_mode` | Planning モードへの遷移を提案 | `reason: str`, `revise: bool = False` |

呼び出し後: `enter_plan_ref[0] = True` をセット。REPL がレスポンス終了後に選択 UI を表示する。

**選択 UI（直前プランあり）:**

| 選択肢 | 動作 |
|--------|------|
| R: Revise current plan | 直前プランファイルを参照して Planning 開始 |
| Y: Yes, start new plan | 新規 Planning 開始 |
| N: No, keep coding | Coding モード継続 |
| C: Cancel | Coding モード継続 |

LLM の `revise` パラメータにより、R または Y がデフォルト（先頭）になる。直前プランがない場合は R 選択肢を省略した 3 択（Y/N/C）になる。

**Coding コンテキストの引き継ぎ:** 遷移時に coding LLM の最終レスポンス（`_last_response_text`）を `<prior_coding_context>` ブロックとして Planning Agent への自動送信メッセージに含める。未決定の質問がある場合、Planning Agent は `ask_user()` で確認してからプランを確定する。

### Planning モード時のシステム命令

Planning モードでは以下の命令が Agent のシステムプロンプトに追加される:

> You are in PLANNING mode.
> YOUR PRIMARY OUTPUT IS A MARKDOWN DOCUMENT — a specification, design, or implementation plan. You are a technical writer and architect in this mode, NOT a coder.
> NEVER produce implementation code (source code, diffs, patches) in your response. Code snippets are allowed ONLY as brief illustrative examples within the design document (e.g. API signatures, config samples, pseudocode). Full function bodies or file contents are forbidden.
> Workflow: (1) investigate the codebase with read-only tools, (2) use extended thinking for deep reasoning, (3) write a structured markdown plan as your response, (4) call exit_plan_mode() to hand off to coding mode.
> Read-only tools (read_file, grep, find, ls, tree) are free to use for investigation.
> write_file and edit_file are DISABLED — do NOT call them.
> run_shell requires user approval and should only be used for analysis (e.g. tests, diagnostics).
> When your plan is ready, call exit_plan_mode() with a brief summary to switch to coding mode.
> Format your plan as clean, structured markdown with headings, tables, and bullet lists.

### Plan → Coding プランファイル引き継ぎ

Planning モードから Coding モードへ遷移する際、`_clear_session_runs()` で Planning 履歴を削除するため、LLM が出力した詳細な設計ドキュメントが失われる。この問題を解決するため、Planning モードのレスポンス全文をマークダウンファイルとして永続化し、Coding Agent に引き継ぐ。

#### 保存先

```
~/.hooty/projects/<slug>/plans/{uuid}.md
```

`AppConfig.project_plans_dir` プロパティで取得可能。プランはプロジェクト単位で共有され、セッションをまたいで参照できる。

#### 保存タイミング

`exit_plan_mode()` 呼び出し後、REPL のモード遷移確認で承認されると `_save_plan_file()` が呼ばれる。Planning モードの最後の LLM レスポンス全文（`_last_response_text`）をファイルに書き出す。保存されたパスは `_last_plan_file` に記録され、次回の `enter_plan_mode()` で Revise 選択時に参照される。

#### Coding Agent への引き継ぎ

auto-execute メッセージでプランファイルのパスを渡す:

```
Implement the following plan.
The full design document is saved at:
  /home/user/.hooty/projects/<slug>/plans/{uuid}.md
Read it with read_file() before starting implementation.
Do not re-read source files already analyzed in the plan.

Plan summary: {plan_summary}
```

プランファイルが存在しない場合（空レスポンス等）は従来通りプランサマリーのみを渡す。

#### 追加読み取りディレクトリ（extra_read_dirs）

`HootyCodingTools` は `_check_path()` をオーバーライドし、`extra_read_dirs` リスト内のパスを読み取り許可する。初期値としてセッションディレクトリ（`~/.hooty/sessions/{id}/`）、プロジェクトディレクトリ（`~/.hooty/projects/<slug>/`）、および追加作業ディレクトリ（`additional_base_dirs`）が設定される。

これにより `read_file`/`grep`/`find`/`ls`/`tree` がこれらのディレクトリ配下にアクセス可能になり、会話ログの検索やプランファイルの読み取りに `run_shell` を使う必要がなくなる。

#### 追加作業ディレクトリ（additional_base_dirs）

`--add-dir` CLI オプションまたは `/add-dir` スラッシュコマンドで指定された追加ディレクトリ。`base_dir` と同等の読み書き権限を持つ:

- `write_file`/`edit_file`: `_is_in_allowed_base()` で `base_dir` と `additional_base_dirs` の両方をチェック
- `run_shell`: パス制限なし（`_check_command` はシェル演算子 + コマンド許可リストのみ）。cwd は `base_dir` 固定

`/add-dir` でランタイム追加すると、`config.add_dirs` に追加され Agent が再生成される。instructions にも追加ディレクトリ情報が含まれ、LLM に明示的に通知される。

## 8. PowerShell ツール

### 概要

Windows 環境で PowerShell のコマンドレット（`Get-ChildItem`, `Select-String` 等）を直接実行する機能を提供する。CodingTools の `run_shell`（cmd.exe 経由）を置き換えるのではなく、**両方を併用**する形で登録される。

### 実装

`tools/powershell_tools.py` で `PowerShellTools(Toolkit)` を独自実装。

```python
from hooty.tools.powershell_tools import create_powershell_tools

ps_tools = create_powershell_tools(working_directory, confirm_ref=confirm_ref)
# PowerShell 未検出時は None を返す
```

PowerShell の検出は `shutil.which` で行い、`pwsh`（PowerShell Core 7+）を優先、なければ `powershell.exe` にフォールバックする。

コマンドはリスト形式で安全に実行する。`shell_runner.run_with_timeout()` を使用し、idle timeout やコマンド履歴記録に対応:

```python
from hooty.tools.shell_runner import run_with_timeout

result = run_with_timeout(
    [powershell_path, "-NoProfile", "-NonInteractive", "-Command", command],
    cwd=str(base_dir), max_timeout=shell_timeout, idle_timeout=idle_timeout,
    shell=False, tmp_dir=tmp_dir,
)
```

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `run_powershell` | PowerShell コマンドの実行（タイムアウト付き） | `command: str`, `timeout: int = None` |

### セキュリティ

**危険パターンのブロック**（case-insensitive サブストリングマッチ）:

- `Invoke-Expression` / `iex` — PowerShell の eval 相当
- `Start-Process` — 外部プロセス起動
- `Invoke-WebRequest`, `Invoke-RestMethod` — ネットワークアクセス
- `Set-ExecutionPolicy` — セキュリティ設定変更
- `Add-Type`, `[System.Reflection.Assembly]` — 任意 .NET コード読み込み
- `DownloadString`, `DownloadFile` — ネットワークダウンロード

**コマンドレット許可リスト**:

| カテゴリ | コマンドレット |
|---|---|
| ファイル操作 | `Get-ChildItem`, `Get-Content`, `Set-Content`, `New-Item`, `Copy-Item`, `Move-Item`, `Remove-Item`, `Rename-Item` |
| 探索 | `Select-String`, `Test-Path`, `Resolve-Path`, `Get-Location` |
| 整形 | `Format-Table`, `Format-List`, `Sort-Object`, `Where-Object`, `Select-Object`, `ForEach-Object` |
| 文字列・ユーティリティ | `Out-String`, `Join-Path`, `Split-Path`, `Get-Unique`, `Measure-Object`, `Group-Object`, `Compare-Object` |
| 変換 | `ConvertTo-Json`, `ConvertFrom-Json`, `ConvertTo-Csv`, `ConvertFrom-Csv` |
| 開発ツール | 共有開発ツールコマンド（上記テーブル参照） + ユーザー定義コマンド |

**パイプ `|` の扱い**: CodingTools はパイプをブロックするが、PowerShell ではパイプが基本構文のため許可する。各パイプセグメントの先頭トークンを許可リストで個別に検証する。

**出力制限**: CodingTools と同様、2000 行 / 50KB で切り詰め。超過分は一時ファイルに保存。一時ファイルは `atexit` で自動削除。

**idle timeout**: CodingTools と同様、`config.yaml` の `tools.idle_timeout` で設定可能。ハングしたプロセスを自動検出して kill する。

### 有効化条件

- `sys.platform == "win32"` であること（Windows のみ）
- `pwsh` または `powershell` が `PATH` 上に存在すること
- CodingTools を置き換えず、両方が登録される

## 9. メモリツール（Agentic Memory）

### 概要

セッションを跨いでプロジェクト知識・ユーザー嗜好を永続記憶する機能を提供する。Agno の `enable_agentic_memory` により、LLM が自らの判断で `update_user_memory` ツールを呼び出す。詳細な仕様は `docs/memory_spec.md` を参照。

### 実装

```python
from agno.memory.manager import MemoryManager
from agno.db.sqlite import SqliteDb

memory_db = SqliteDb(
    memory_table="user_memories",
    db_file=config.project_memory_db_path,
)

Agent(
    memory_manager=MemoryManager(db=memory_db, model=model),
    enable_agentic_memory=True,       # LLM がツールとして記憶操作
    update_memory_on_run=False,       # 毎ターン自動記憶しない（コスト回避）
    add_memories_to_context=True,     # 既存記憶をコンテキスト注入
)
```

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `update_user_memory` | 記憶の追加・更新・削除を自然言語タスクとして指示 | `task: str` |

Agno が `enable_agentic_memory=True` 時に自動登録する。Hooty 側でのツール生成コードは不要。

### 記憶ポリシー

LLM の instructions に記憶ポリシーを記述し、ノイズを排除する。

**記憶すべき（シグナル）:**
- ユーザーが確認した設計判断（認証方式、DB 選定等）
- プロジェクト規約（ディレクトリ構成、命名規則等）
- 技術スタック・ツーリング選定
- ユーザーが明示的に「覚えて」と要求した情報

**記憶すべきでない（ノイズ）:**
- 現在のタスク詳細、バグ、エラー
- ファイル内容、diff、シェル出力
- 一時的なデバッグ手順
- 未確定の議論・探索中の情報

### コスト影響

| コスト項目 | 影響 |
|---|---|
| LLM コール数 | 増加なし（メイン応答内の tool_call のみ） |
| LLM input tokens | +0.1〜1.0%（記憶件数次第） |
| ストレージ | 数百 KB 以下 |

### 有効化条件

- `config.yaml` の `memory.enabled` が `true`（デフォルト）
- 追加パッケージ不要（Agno に含まれる）

## 10. ユーザー質問ツール

### 概要

LLM が推論中にユーザーへ質問できるツール。曖昧な要件の確認や、複数のアプローチ間の選択をユーザーに委ねる用途で使用する。Planning / Coding 両モードで常に有効。Safe モード設定に依存しない。

### 実装

```python
from hooty.tools.ask_user_tools import AskUserTools

tools.append(AskUserTools())
```

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `ask_user` | ユーザーに質問し回答を取得 | `question: str`, `choices: str \| None = None` |

### パラメータ

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `question` | `str` | はい | 質問テキスト |
| `choices` | `str \| None` | いいえ | カンマ区切りまたは改行区切りの選択肢 |

### 動作例

Rich Panel ベースのセレクターで表示する。タイトルに `❓ Question for you`、ボディに質問文を表示する。

**自由テキスト入力:**
```
╭─ ❓ Question for you ────────────────────────────╮
│                                                   │
│    ファイルの命名規則はどちらを使いますか？        │
│                                                   │
│    █                                              │
│                                                   │
│    ←→ move  BS del  Enter submit  Esc cancel      │
╰───────────────────────────────────────────────────╯
```

**選択肢付き（Other 行あり）:**
```
╭─ ❓ Question for you ────────────────────────────────────╮
│                                                           │
│    テストフレームワークはどれを使いますか？               │
│                                                           │
│    ❯ 1. pytest                                            │
│      2. unittest                                          │
│      3. nose2                                             │
│      Other: type to enter...                              │
│                                                           │
│    ↑↓ move  Enter select  1-3 shortcut                    │
│    type to enter Other  Esc cancel                        │
╰──────────────────────────────────────────────────────────╯
```

`choices` パラメータ指定時は `allow_other=True` が自動適用され、番号選択肢の下に「Other」自由入力行が表示される。ユーザーは固定選択肢を選ぶか、Other 行でカスタム回答をテキスト入力できる。

- `number_select` の戻り値: `int`（選択肢インデックス）、`str`（Other テキスト）、`None`（キャンセル）
- Other 行で文字をタイプすると入力モードに切り替わる
- `up` キーで入力モードから選択肢リストに戻る
- `space` / `enter` で Other 行にフォーカス → 入力モード開始

**Multi-Q wizard（単一Q対応）:**

`**Q1. …**` 形式の見出し + 番号付き選択肢が 1 問以上あれば wizard UI を表示する（従来は 2 問以上が必要だった）。各質問に Other 行が付き、自由入力も可能。

```
╭─ ❓ Question for you (1/1) ──────────────────────────────╮
│                                                           │
│    **Q1. CLI library?**                                   │
│                                                           │
│    ❯ 1. argparse                                          │
│      2. typer                                             │
│      Other: type to enter...                              │
│                                                           │
│    ↑↓ select  Tab Other→  Enter select→next  Esc cancel   │
╰──────────────────────────────────────────────────────────╯
```

### エッジケース

| 入力 | 動作 |
|---|---|
| Enter（空テキスト） | `"(no response)"` を返す |
| Esc / Ctrl+C（選択肢モード） | `"(no response)"` を返す |
| Esc / Ctrl+C（テキスト入力モード） | `"(no response)"` を返す |
| Other 行で Enter（空テキスト） | 入力モードのまま（確定しない） |
| Other 行で Enter（テキストあり） | Other テキストを `str` として返す |

### 使用ガイドライン

- 回答が実装方針に **実質的に影響する** 場合のみ使用する
- 自明な選択や LLM が合理的に判断できる場合は使用しない
- 1 回のレスポンスで複数回呼ぶのは避ける
- `choices` パラメータ使用時に「Other」「その他」を選択肢に含めない（UI が自動追加するため）

### 有効化条件

- 常に有効（Planning / Coding 両モード）
- Safe モード設定に依存しない
- 追加パッケージ不要

## 11. プラン管理ツール（PlanTools）

### 概要

LLM がプランの一覧取得・内容確認・作成・更新・ステータス変更を行うための CRUD ツール。`PlanTools` Toolkit として実装され、Planning / Coding 両モードで常に有効。

### 実装

```python
from hooty.tools.plan_tools import PlanTools

tools.append(PlanTools(config=config, session_id_ref=session_id_ref))
```

`session_id_ref` は `list[str]` で、REPL のセッション ID と同期される。`plans_create` 時にセッション ID を使用して同セッション内の旧 active プランを自動 cancel する（`pending` は保護される）。

### 提供される関数

| 関数 | 説明 | 引数 |
|---|---|---|
| `plans_list` | プラン一覧（status フィルタ可） | `status_filter: str = ""` |
| `plans_get` | プラン本文取得（short_id prefix マッチ） | `plan_id: str` |
| `plans_search` | キーワード検索（大小文字区別なし） | `keyword: str` |
| `plans_create` | 新規プラン作成（同セッション active を自動 cancel） | `body: str`, `summary: str = ""` |
| `plans_update` | 既存プランの本文を in-place 更新（plan_id 維持） | `plan_id: str`, `body: str`, `summary: str = ""` |
| `plans_update_status` | ステータス変更（active / completed / pending / cancelled） | `plan_id: str`, `status: str` |

### plans_get の切り詰め

本文が 10,000 文字を超える場合、切り詰めて `read_file()` でのフルアクセスを案内する。

### Planning モードでのワークフロー

1. `plans_list()` / `plans_get()` で既存プランを確認
2. `plans_create(body, summary)` で新規プラン作成 → plan_id を取得
3. ユーザーフィードバックに基づき `plans_update(plan_id, body)` で段階的に精緻化
4. `exit_plan_mode(summary, plan_id=plan_id)` でプランを coding agent に引き継ぎ

### Coding モードでの使用

- `plans_list()` で既存プランの状態を確認（`enter_plan_mode()` の revise 判断に使用）
- `plans_get()` で実装中のプラン内容を参照

### exit_plan_mode との連携

`exit_plan_mode(plan_summary, plan_id)` に `plan_id` を渡すと、REPL は `_save_plan_file()`（`_last_response_text` の保存）をスキップし、`plan_id` で指定された既存プランファイルを直接 coding agent に引き継ぐ。`plan_id` 未指定時は従来動作（最終レスポンスの保存）にフォールバック。

### 有効化条件

- 常に有効（Planning / Coding 両モード）
- 追加パッケージ不要

## コンテキスト最適化

### ツール結果圧縮（CompressionManager）

`agent_factory.py` で `CompressionManager` を設定。ツール結果（ファイル読み取り、コマンド出力等）が 3 件以上蓄積すると LLM で自動圧縮する。

```python
from agno.compression.manager import CompressionManager

Agent(
    compress_tool_results=True,
    compression_manager=CompressionManager(compress_tool_results_limit=3),
)
```

圧縮時に保持される情報: 数値・統計、日時、エンティティ名、URL・ID・バージョン、引用

### セッションサマリー（SessionSummaryManager）

各 run 終了時にセッション全体の要約を生成。次回以降は過去のメッセージの代わりにサマリーをコンテキストに含める。

```python
Agent(
    enable_session_summaries=True,
    add_session_summary_to_context=True,
)
```

### 履歴ウィンドウ

直近 5 回の run のメッセージのみをコンテキストに含める。

```python
Agent(
    add_history_to_context=True,
    num_history_runs=5,
)
```

## ツールの有効化条件まとめ

| ツール | 有効化条件 | 必須パッケージ |
|---|---|---|
| HootyCodingTools / ConfirmableCodingTools（apply_patch / move_file / create_directory / tree 含む） | 常に有効 | なし（agno に含まれる） |
| PowerShellTools / ConfirmablePowerShellTools | Windows かつ PowerShell が検出された場合 | なし |
| AskUserTools | 常に有効 | なし |
| Agentic Memory (`update_user_memory`) | `memory.enabled: true`（デフォルト） | なし（agno に含まれる） |
| ネイティブ推論 | reasoning mode が on/auto かつ対応モデル | なし |
| GithubTools | `GITHUB_ACCESS_TOKEN` 環境変数が設定済み | `PyGithub` |
| DuckDuckGoTools | `ddgs` パッケージがインストール済み | `ddgs` |
| web_fetch_tools | 常時有効（httpx + BeautifulSoup） | `httpx`, `beautifulsoup4` |
| SQLTools | `/database connect` で接続先が選択済み | `sqlalchemy` |
| MCPTools | `config.yaml` に `mcp` セクションが存在 | `mcp` |
| PlanTools | 常に有効（Planning / Coding 両モード） | なし |
