# Changelog

[Keep a Changelog](https://keepachangelog.com/) 形式に準拠。

## [0.6.10] — 2026-03-24

### Added

- **`/attach capture` macOS 対応** — macOS ネイティブの `screencapture` コマンドと `pyobjc-framework-Quartz`（`CGWindowListCopyWindowInfo`）によるウィンドウ列挙で、Windows / WSL2 と同等のスクリーンキャプチャ機能を macOS でも利用可能に。ターゲット指定（active / モニタ番号 / アプリ名 / ウィンドウタイトル）、`--delay`、`--repeat`、`--interval` オプションすべて対応
  - `capture.py`: `_MacWindow` dataclass、`_list_macos_windows()`（`CGWindowListCopyWindowInfo` で z-order 順にウィンドウ列挙）、`_resolve_macos_target()`（ターゲット文字列 → `screencapture` 引数への解決）、`_capture_macos()`（macOS キャプチャバックエンド）を追加。`capture_screen()` をプラットフォームディスパッチに変更し既存 Windows ロジックを `_capture_windows()` に抽出
  - `commands/attach.py`: ヘルプテキストに macOS 権限注記を追加、対応プラットフォーム表記を更新
  - `pyproject.toml`: `macos-capture` optional dependency（`pyobjc-framework-Quartz`）追加
  - `packaging/hooty.spec`: macOS ビルド時に `Quartz`・`objc` を hidden import に追加

### Fixed

- **`main.py` の例外型チェックを `isinstance()` に変更** — `type(e).__name__ == "CredentialExpiredError"` / `"ConfigFileError"` の文字列比較を `isinstance()` による直接型チェックに修正。リファクタリング耐性の向上と同名別クラスの誤認防止
- **`oneshot.py` のテンポラリディレクトリ削除漏れ修正** — `_process_attach_files()` で `tempfile.mkdtemp()` が例外発生時にクリーンアップされない問題を `try-finally` でラップして修正

- **`api_timeout` の `write`/`pool` タイムアウト独立化** — `httpx.Timeout` の `write` と `pool` が `api_read_timeout`（360s）を流用していた対応漏れを修正。それぞれ独立した設定値 `api_write_timeout`/`api_pool_timeout`（デフォルト 30s）を導入し、`config.yaml` の `api_timeout.write`/`api_timeout.pool` で個別に設定可能にした
  - `config.py`: `AppConfig` に `api_write_timeout`, `api_pool_timeout` フィールド追加、YAML パース対応
  - `providers.py`: `_build_httpx_timeout()` で新しい設定値を参照

- **PreToolUse フックのブロッキング実装** — `PreToolUse` フックの `blocking: true` + exit code 2 が実際にツール実行を阻止できるようになった。従来はストリーミングイベント（`tool_call_started`）で発火していたため、Agno が既にツール実行を開始しており WARNING ログのみだった。Agno の `tool_hooks` ミドルウェアを使い、ツール実行 **前** にフックを発火するよう変更
  - `hooks.py`: `_agno_pre_tool_hook()` — Agno tool_hooks ミドルウェア追加。ブロック時は `[BLOCKED]` メッセージを LLM に返却、`additional_context` はツール結果に付加
  - `agent_factory.py`: `Agent(tool_hooks=[_agno_pre_tool_hook])` で全ツールに接続
  - `repl.py`: 旧 `_fire_pre_tool_use()` メソッドと呼び出しを削除（二重発火防止）
  - `oneshot.py`: `_hooks_ref` セットアップ追加（非対話モードでもブロック動作）
  - `hooks_spec.md`: v1 制約から PreToolUse の記述を削除、実装詳細を追記
  - `tool_input`（ツール引数）を stdin JSON に含めるようになり、`run_shell` のコマンド内容検査等が可能に

## [0.6.9] — 2026-03-21

### Added

- **`/copy` コマンド** — 直前の LLM 応答をクリップボードにコピー。`/copy N` で N 番目に新しい応答を指定可能。Windows / WSL2 / macOS / Linux 対応（Windows/WSL2 は PowerShell + Base64 パイプで文字化けを回避）
  - `clipboard.py`: `write_clipboard()` 関数追加。`detect_platform()` を再利用し、Windows/WSL2 は `_write_clipboard_powershell()` で Base64 エンコード経由、macOS は `pbcopy`、Linux は `xclip` / `xsel` フォールバック
  - `commands/misc.py`: `cmd_copy()` ハンドラ追加。N=1 は `get_last_response_text()` から高速取得、N≧2 は `conversation_log.load_recent_history()` で JSONL から取得
  - `repl.py`: `SLASH_COMMANDS` / `handlers` に `/copy` 登録
  - `docs/user_guide.md`: コマンド一覧に `/copy` 追加

- **OpenAI 直接 API プロバイダ** — `openai` プロバイダを追加。`api.openai.com` 経由で GPT-5 シリーズを直接利用可能に。Azure OpenAI Service（`azure_openai`）経由に加え、OpenAI の直接 API にも対応
  - `config.py`: `Provider.OPENAI` enum 値、`OpenAIConfig` dataclass、`AppConfig.openai` フィールド追加。`_apply_yaml()` / `activate_profile()` / `validate_config()` / `supports_thinking()` / `supports_vision()` に `openai` ブランチ追加
  - `providers.py`: `_create_openai_model()` ファクトリ関数追加（`agno.models.openai.OpenAIChat` を使用）
  - `model_catalog.py`: `get_context_limit()` に `openai` ブランチ追加
  - `scripts/update_model_catalog.py`: LiteLLM からトップレベル `gpt-5+` キーを `openai` セクションとして抽出するロジック追加
  - `src/hooty/data/model_catalog.json`: `openai` セクション自動生成（31 モデル）
  - `pyproject.toml`: `openai = ["openai"]` extra 追加、`all` extra に `openai` 追加
  - `docs/provider_spec.md`: OpenAI セクション追加（認証・設定例・reasoning 対応・必要パッケージ）

## [0.6.8] — 2026-03-18

### Added

- **スキル・インストラクション自動検出** — メッセージ送信前にスキルディレクトリ（`.hooty/skills/` 等）およびインストラクションファイル（`CLAUDE.md`, `~/.hooty/hooty.md` 等）の変更を自動検出し、変更があれば Agent を自動再生成する。`skill-creator` スキルで新スキルを作成した場合など、`/skills reload` なしで即座に LLM から利用可能に
  - `skill_store.py`: `skill_fingerprint()` — SKILL.md 生コンテンツの SHA-256 ハッシュによるコンテンツベースのフィンガープリント。`discover_skills()` と同じディレクトリを軽量スキャン（frontmatter パース・scripts/references スキャン不要）
  - `context.py`: `context_fingerprint()` — インストラクションファイルの SHA-256 コンテンツハッシュ。WSL2/NTFS で不安定な mtime に依存しない
  - `repl.py`: `_send_to_agent()` でフィンガープリントを比較し、変更時に `_close_mcp_tools()` + `_close_agent_model()` で旧 Agent をクリーンアップ後に再生成。変更内容に応じて `Instructions changed`, `Skills changed`, `Instructions & Skills changed` を表示
  - 対象ファイル: `skill_store.py`, `context.py`, `repl.py`
  - テストファイル: `tests/test_skill_store.py`, `tests/test_context.py`

- **スキルのトップレベルスラッシュコマンド化** — `user-invocable` なスキルを `/skills invoke <name>` ではなく `/<name> [args]` でトップレベルから直接呼び出し可能に。既存コマンドが優先され、衝突しないスキルのみフォールバックとしてディスパッチされる。Tab 補完リストにもスキル名が自動追加される
  - `repl.py`: `_skill_command_cache` によるキャッシュ管理、`_refresh_skill_commands()` でキャッシュ更新、`_try_skill_shortcut()` でフォールバックディスパッチ、`_SlashCommandCompleter` にスキル補完を統合
  - `commands/__init__.py`: `CommandContext` に `refresh_skill_commands` コールバック追加
  - `commands/skills.py`: `/skills reload`, `/skills on`, `/skills off` でキャッシュ更新呼び出し
  - キャッシュ更新タイミング: REPL 起動時、スキル変更自動検知時、`/skills reload|on|off` 時
  - テストファイル: `tests/test_repl_skill_shortcut.py`

### Improved

- **Opus 4.6 Adaptive Thinking 対応** — Opus 4.6+ の Extended Thinking で deprecated の `thinking.type: "enabled"` + `budget_tokens` に代わり、`thinking.type: "adaptive"` + `output_config.effort` を使用するよう移行。Sonnet 等その他の Claude モデルは従来方式を維持
  - `config.py`: `supports_adaptive_thinking()` ヘルパー追加（model_id の正規表現マッチで Opus 4.6+ を判定）
  - `repl.py`: `_apply_reasoning()` で adaptive 対応モデルは `model.thinking = {"type": "adaptive"}` + `model.request_params = {"output_config": {"effort": ...}}` を設定。無効化時に `request_params` もクリーンアップ
  - 対象ファイル: `config.py`, `repl.py`, `docs/config_spec.md`, `docs/provider_spec.md`

### Changed

- **Agno 2.5.9 → 2.5.10 アップグレード** — 3 件のバグ修正を取り込み
  - Claude 構造化出力検出がプレフィックスベースに改善（[agno#6643](https://github.com/agno-agi/agno/pull/6643)）— Hooty 側のワークアラウンド `_fix_structured_outputs_detection()` を削除
  - MCP ツールのセッション重複作成によるデッドロック防止（[agno#6821](https://github.com/agno-agi/agno/pull/6821)）
  - ストリーミング時のツール重複実行修正（[agno#6579](https://github.com/agno-agi/agno/pull/6579)）— Azure OpenAI プロバイダ利用時に恩恵
  - 対象ファイル: `uv.lock`, `providers.py`

### Fixed

- **GPT-5.x `-chat` バリアントの `reasoning_effort` クランプ** — `gpt-5.3-chat` 等の `-chat` バリアントが `medium` のみサポートする制約に対応。`-pro` の `high` クランプと同様に、`-chat` では全レベルで `medium` に固定
  - 対象ファイル: `repl.py`, `docs/config_spec.md`, `docs/provider_spec.md`

- **Plan mode 切替時の Agent model クリーンアップ漏れ修正** — `_send_to_agent()` 内の plan mode 切替で `_close_agent_model()` が呼ばれておらず、旧 Agent の HTTP クライアントが GC 任せになり `Unclosed client session` / `Unclosed connector` 警告が出ていた問題を修正
  - 対象ファイル: `repl.py`

### Security

- **`_BUILTIN_PASSPHRASE` 廃止 — ランダムパスフレーズ自動生成** — `hooty setup generate` で `--passphrase` 省略時にハードコードされた内蔵キーで暗号化していた問題（実質平文と同等）を修正。省略時は `secrets.token_urlsafe(16)` でランダムパスフレーズを自動生成し、常にセキュアな暗号化を保証
  - `generate_setup_code()` の戻り値を `tuple[str, str]`（setup_code, passphrase_used）に変更
  - `decode_setup_code()` の `passphrase` 引数を必須化（`str`）。旧 simple モード（flag 0x00）のコードはエラー
  - `needs_passphrase()` 関数を削除（常にパスフレーズ必須のため不要）
  - `hooty setup` （利用者側）は常にパスフレーズ入力を要求
  - 対象ファイル: `credentials.py`, `main.py`, `docs/setup_guide.md`
  - テストファイル: `tests/test_credentials.py`

## [0.6.7] — 2026-03-17

### Improved

- **LLM API タイムアウト設定** — ストリーミング/非ストリーミングで分離した HTTP タイムアウトを全プロバイダ共通で設定可能に。SDK デフォルト（read=600 秒）では Azure AI Foundry 等のサーバー側ハングを 10 分間検知できなかった問題を解消
  - `api_timeout.connect`: TCP 接続確立（デフォルト 30 秒）
  - `api_timeout.streaming_read`: ストリーミング時のチャンク間無応答（デフォルト 180 秒）
  - `api_timeout.read`: 非ストリーミング時のレスポンス全体待ち（デフォルト 360 秒）
  - 対象プロバイダ: Anthropic 直接、Azure AI Foundry、AWS Bedrock（Claude / 非 Claude）、Azure OpenAI
  - サブエージェントにも親の設定が自動継承される（常にストリーミングモードで `streaming_read` が適用）
  - 対象ファイル: `config.py`, `providers.py`, `tools/sub_agent_runner.py`, `docs/config_spec.md`
- **`/mcp add` / `/mcp remove` 改善** — `--header`・`--transport` オプション追加、scope フラグを `--global` に統一
  - `--header "Key: Value"`（`-h`）: URL ベースサーバーに認証ヘッダー等を指定可能（複数指定可）。Agno の `SSEClientParams` / `StreamableHTTPClientParams` 経由で渡される
  - `--transport http|sse`: URL サーバーのトランスポートを明示指定（デフォルト `http` = streamable-http）。`sse` 指定時は mcp.yaml に `transport: sse` を書き込み
  - `--scope global|project` を廃止し `--global` フラグに統一（`/skills`・`/memory` と同じパターン）
  - `-e` の長形式 `--env` を追加
  - mcp.yaml に `headers` フィールドを新設（URL 接続のみ）
  - mcp.yaml の `transport` 値を `http` / `sse` に統一（`streamable-http` も後方互換で受け付ける）。`/mcp list` 等の表示も `http` に変更
  - 対象ファイル: `commands/mcp_cmd.py`, `tools/mcp_tools.py`, `mcp_picker.py`, `repl.py`, `docs/tools_spec.md`, `docs/config_spec.md`, `docs/cli_spec.md`, `docs/user_guide.md`
  - テストファイル: `tests/test_mcp_add_remove.py`, `tests/test_mcp_tools.py`

### Fixed

- **Windows CTRL-C によるサブエージェント/シェル中断** — Windows でツール実行中の Ctrl+C が完全に無視されていた問題を修正。`cancel_event`・`_interrupt_event`・`task.cancel()` を遅延キャンセルパターンで伝播し、実行中のシェルコマンドの kill、サブエージェントの停止、メインタスクのキャンセルを実現
  - `shell_runner.py`: `_interrupt_event`（`threading.Event`）を導入。`_run_simple` を `Popen` + ポーリングに変更し割り込み可能に。`_run_with_idle_watch` にも interrupt チェックを追加。セット済みの場合は後続コマンドも即スキップ
  - `sub_agent_runner.py`: `run_sub_agent` の `future.result(timeout=600)` を 1 秒ポーリングに変更し `cancel_event` を毎秒チェック。Bedrock リトライ検出（`botocore.retryhandler` ロガー）を追加
  - `repl.py`: Windows console-ctrl handler から `cancel_event`/`_interrupt_event` をセットし、`_win_deferred_cancel` で遅延タスクキャンセル。`_win_active_task`/`_win_active_loop` でメインタスクもキャンセル対象に
  - `confirm.py`: `_clear_win_cancel_state()` でダイアログ終了後にキャンセル状態をクリア（ダイアログ中の CTRL-C が後続実行を汚染する問題を防止）
  - 対象ファイル: `tools/shell_runner.py`, `tools/sub_agent_runner.py`, `tools/confirm.py`, `tools/sub_agent_tools.py`, `repl.py`
- **Windows 終了時ハング修正** — レスポンスキャンセル（Ctrl+C）後に `/quit` や Ctrl+D で終了できなくなるバグを修正。3 つの原因に対処:
  1. `_run_async()` の `CancelledError` ハンドラで Windows のループ再作成が漏れていた問題を修正（`KeyboardInterrupt` ハンドラと同様に `ProactorEventLoop` を差し替え）
  2. `KeyboardInterrupt` ハンドラ内の `run_until_complete(asyncio.sleep(0))` が壊れた ProactorEventLoop の IOCP select でハングする問題を修正（Windows ではスキップ）
  3. `run()` の `finally` ブロックで MCP close / loop shutdown を省略（`os._exit(0)` が全リソースを解放するため不要。グレースフルシャットダウンの待ち時間による終了遅延も解消）
  - 対象ファイル: `repl.py`, `docs/cli_spec.md`, `docs/agents_spec.md`, `docs/tools_spec.md`

## [0.6.6] — 2026-03-15

### Improved

- **ストリーミング表示の行単位バッファリング** — Markdown 再パースを改行到達時のみに削減。500ms タイマーフォールバックで改行なしの長い行でも進捗表示を維持
  - 対象ファイル: `repl.py`, `docs/cli_spec.md`
- **MCP サーバー接続のエラーハンドリング改善** — 起動時にヘルスチェックを実行し、接続状態を `✓ connected` / `✗ failed to connect` で表示。Agno SDK が接続失敗を飲み込む問題を Hooty 層で補完
  - `check_mcp_health()`: Agent 初期化後に各 MCP ツールへ `connect()` を試行し、結果を即座にフィードバック
  - stderr を `/dev/null` から `_StderrPipe`（`os.pipe()` + デーモンスレッド）に変更。`--debug` 時に MCP サーバーの stderr が `logger.debug` 経由で可視化。`--mcp-debug` 時は `sys.stderr` にも echo
  - シャットダウン時の `_StderrPipe.mute()` でプロセス終了ノイズを抑制
  - `cancelled` エラーを MCP 接続エラー（`/mcp reload` 案内）とユーザーキャンセルに正しく分類
  - `/mcp reload` 後にもヘルスチェックを実行（`CommandContext.run_mcp_health_check` コールバック経由）
  - `create_mcp_tools()` の警告をリストで返却し、スピナー終了後に表示（スピナー中の表示崩れ解消）
  - `config.yaml` の `tools.mcp_debug` で `--mcp-debug` 相当の設定を永続化可能に
  - mcp.yaml のバリデーション強化: `command` / `url` の型・空値チェック、`args` / `env` の型チェック
  - 対象ファイル: `tools/mcp_tools.py`, `tools/__init__.py`, `repl.py`, `config.py`, `commands/__init__.py`, `commands/mcp_cmd.py`, `docs/tools_spec.md`, `docs/config_spec.md`
  - 新規ファイル: `tests/test_mcp_tools.py`
- **`/mcp list`・`/database list`・`/skills list` のテーブル表示** — Rich `Table` によるカラム整列表示に統一。`/session list` と同じスタイル（ヘッダー区切り線付き）
  - 対象ファイル: `commands/mcp_cmd.py`, `commands/database.py`, `commands/skills.py`

### Changed

- **プランステータスを 4 ステータスに再編** — `superseded` を廃止し、意味が明確な 4 ステータス（`active` / `completed` / `pending` / `cancelled`）に再編。`pending`（棚上げ）は新プラン作成時の自動キャンセルから保護される。不明なステータス（レガシーの `superseded` 含む）は読み込み時に `cancelled` として扱う
  - 対象ファイル: `plan_store.py`, `tools/plan_tools.py`, `docs/cli_spec.md`, `docs/tools_spec.md`, `docs/user_guide.md`
- **reasoning デフォルト `off` → `auto`** — 推論モードのデフォルトを `auto` に変更。`auto_level` 設定でキーワードなし時のデフォルトレベルも指定可能（0=推論なし, 1-3）
- **`auto_level` デフォルト `0` → `1`** — `auto` モード時、キーワードなしでも常にレベル 1 の Extended Thinking が有効に。`auto_level=0` では LLM が応答本文に `<thinking>` タグをテキストとして出力する場合があったが、常時 Extended Thinking を有効にすることで推論が `reasoning_content` 側に流れ、応答がクリーンになる
- **ReasoningTools（CoT フォールバック）廃止** — Plan モードで非対応モデル向けに提供していた `think()`/`analyze()` ツール（Agno `ReasoningTools`）を完全削除。主要モデル（Claude / GPT / Grok）はすべてネイティブ推論をサポートしているため不要に
- **Plan モード instructions から `think()`/`analyze()` 参照削除** — Planning ワークフローの instructions を固定文言（`use extended thinking for deep reasoning`）に統一。条件分岐（`reasoning_active` フラグ）とテンプレート変数（`{reasoning_step}`）も削除
- **`read_url` → `web_fetch` リネーム** — URL 取得ツールの関数名・Toolkit 名・ファクトリ名を一括リネーム（`read_url` → `web_fetch`, `create_web_reader_tools` → `create_web_fetch_tools`, Toolkit `web_reader` → `web_fetch`）。エージェント instructions 内のツール名参照も全て更新
  - 対象ファイル: `tools/search_tools.py`, `tools/__init__.py`, `tools/sub_agent_runner.py`, `tools/sub_agent_tools.py`, `repl.py`, `agent_store.py`, `data/agents.yaml`

### Added

- **`/auto` コマンド — モード自動遷移トグル** — `exit_plan_mode()` / `enter_plan_mode()` 実行時の確認ダイアログ（`hotkey_select`）をスキップし、即座にモード遷移するセッション内トグル。ツールバーに `(auto)` 表示。config.yaml / CLI フラグ不要
  - 対象ファイル: `repl.py`, `commands/__init__.py`, `commands/mode.py`, `docs/cli_spec.md`, `docs/user_guide.md`, `docs/architecture_spec.md`
- **`/context` に Current Model セクション追加** — プロバイダ・モデル ID・プロファイル・Streaming/Reasoning/Vision の能力フラグを一覧表示。デバッグや設定確認が容易に
  - 対象ファイル: `commands/session.py`, `docs/context_spec.md`, `docs/cli_spec.md`, `docs/user_guide.md`
- **プロジェクト固有 MCP 設定サポート** — `<working_dir>/.hooty/mcp.yaml` でプロジェクト固有の MCP サーバーを定義可能に。グローバル `~/.hooty/mcp.yaml` と後勝ちマージ（同名サーバーはプロジェクト側が上書き）。`/mcp list` でソース表示（global/project）、`/mcp`（引数なし）でインタラクティブピッカーによる個別 ON/OFF 切替に対応
  - 新規ファイル: `mcp_picker.py`, `tests/test_mcp_config.py`
  - 対象ファイル: `config.py`, `commands/mcp_cmd.py`, `docs/config_spec.md`
- **MCP ツール名前空間** — MCP ツールを `mcp__{サーバー名}__{ツール名}` 形式で公開するように変更。組み込みツール（`read_file`, `edit_file` 等）との名前衝突を回避。Claude Code・Docker MCP Gateway・MetaMCP が採用する業界標準パターンに準拠
  - 対象ファイル: `tools/mcp_tools.py`, `docs/tools_spec.md`
- **`web_fetch` の Content-Type 対応** — レスポンスの Content-Type に応じた適切なハンドリングを追加。HTML は従来通り BeautifulSoup でパース、plain text / JSON / markdown 等はそのまま返却、バイナリはエラーメッセージを返却。非 HTML レスポンスでのリンク追跡もスキップ
  - 対象ファイル: `tools/search_tools.py`, `tests/test_search_tools.py`
- **DuckDuckGo 検索の `region` パラメータ対応** — Web 検索（`/websearch`）で DuckDuckGo の地域フィルター（`kl` パラメータ）を設定可能に。デフォルトは `"jp-jp"`（日本語・日本）で、日本語の検索結果を優先的に取得する。`config.yaml` の `tools.web_search_region` で変更可能（例: `"us-en"` で英語・アメリカ）
  - 対象ファイル: `config.py`, `tools/search_tools.py`, `tools/__init__.py`

### Fixed

- **`/context` コンテキストウィンドウ トークン数の正確性改善** — コンテキストウィンドウ使用量にキャッシュトークン（`cache_read_tokens` + `cache_write_tokens`）を加算するように修正。Anthropic API はキャッシュトークンを `input_tokens` と別に報告するため、従来はキャッシュ分が除外された過小な値（例: 324 tokens）が表示されていた。合わせて以下も修正:
  - run footer の `˄` 表示をキャッシュ込み合計に変更（プロバイダ間で「コンテキストに送ったトークン数」として統一）
  - `/context` にトークン取得ソース（`Source: last request` / `last run (sum)`）を表示
  - 非ストリーミングモードで per-request トークンを取得（最後のアシスタントメッセージのメトリクスから抽出）
  - falsy チェック `if inp:` → `if inp is not None:` に修正（`input_tokens=0` が無視されるエッジケース対応）
  - auto-compact の閾値判定にもキャッシュトークンを加算
  - 対象ファイル: `repl.py`, `commands/session.py`, `docs/cli_spec.md`, `docs/context_spec.md`
- **MCP stdio: WSL 環境で Windows .exe サーバーに `env` が渡されない問題を修正** — WSL→Windows interop では `subprocess.Popen(env=dict)` で設定した環境変数が自動的には Windows プロセスに転送されない。WSL の `WSLENV` 環境変数に列挙された変数名のみが転送される仕組みのため、`mcp.yaml` の `env` に指定した全キーを `WSLENV` に自動付与するように修正
  - 対象ファイル: `tools/mcp_tools.py`, `tests/test_mcp_config.py`
- **MCP stdio セッション終了時のエラー修正** — `stdio_client` の anyio cancel scope がタスク不一致でクリーンアップに失敗する問題を修正。shutdown 前に MCPTools を明示的に close するように変更。また `devnull` のライフタイムを MCP 接続に合わせ、接続中の premature close を防止
- **MCP stdio 2回目接続エラーの修正** — `devnull` を1回だけ open して connect/close サイクルで使い回していたため、2回目の `_connect()` で「I/O operation on closed file」が発生する問題を修正。`devnull` を `_patched_connect()` 内で毎回新しく open し、`_patched_close()` で close するサイクルに変更。加えて Agent 再作成の全箇所（モード切替・セッション切替・`/mcp reload`・`/mcp` picker）で旧 MCP 接続を事前にクローズするセーフティネットを追加
  - 対象ファイル: `tools/mcp_tools.py`, `repl.py`, `commands/__init__.py`, `commands/mcp_cmd.py`

### Documentation

- **MCP stdio の WSL 環境変数転送（WSLENV）をドキュメントに追記** — WSL2 から Windows `.exe` / `.cmd` / `.bat` を MCP サーバーとして使う場合の `WSLENV` 自動付与の仕組み・動作条件・影響範囲を tools_spec.md と user_guide.md に記載
  - 対象ファイル: `docs/tools_spec.md`, `docs/user_guide.md`
- **プロンプトキャッシングのドキュメント拡充** — プロバイダ別の動作差異（明示的 vs 自動）、TTL、コスト影響、Azure AI Foundry の制約（`Provider.AZURE` 経由では `cache_system_prompt` 非対応）を詳細に記載
  - 対象ファイル: `docs/provider_spec.md`, `docs/config_spec.md`

### Improved

- **`/attach` にディレクトリパス指定時のピッカーフォールバック** — `/attach .` や `/attach src/` のようにディレクトリを指定した場合、そのディレクトリをルートとしてファイルピッカーを自動起動するように改善。従来は「unsupported file format」エラーになっていた
  - 対象ファイル: `commands/attach.py`
- **多重起動ロバストネス強化** — 複数の Hooty インスタンスを同時起動した際のデータ破損・ロック競合を防止
  - **SQLite WAL モード** — 全 SQLite DB（`sessions.db`, グローバル/プロジェクト `memory.db`）を WAL モード + `busy_timeout=10s` で作成。複数プロセスの同時読み書きで "database is locked" エラーが発生しなくなった
  - **アトミックファイル書き込み** — `config.yaml`, `.credentials`, `.skills.json`, `.hooks.json`, `.meta.json`, `plans/*.md`, `workspace.yaml`, `stats.json`, `snapshots/_index.json` 等の全共有ファイル書き込みを `tempfile.mkstemp()` + `os.replace()` によるアトミック置換に変更。書き込み中のクラッシュでファイルが破損しなくなった
  - **fcntl.flock セッションロック** — セッションロックを PID ファイルベース（TOCTOU 脆弱性あり）から `fcntl.flock(LOCK_EX | LOCK_NB)` に変更。プロセスクラッシュ時は OS が自動解放。Windows（fcntl なし）では従来の PID ベースにフォールバック
  - 新規ファイル: `concurrency.py`（`create_wal_engine`, `atomic_write_text`, `atomic_write_bytes`）
  - 対象ファイル: `agent_factory.py`, `session_store.py`, `memory_store.py`, `session_lock.py`, `config.py`, `credentials.py`, `skill_store.py`, `hooks.py`, `project_store.py`, `plan_store.py`, `workspace.py`, `session_stats.py`, `file_snapshot.py`

## [v0.6.5] — 2026-03-13

### Added

- **`assistant` サブエージェント** — 非コーディングタスク（ドキュメント作成、データ分析、システム操作、ファイル整理）を隔離コンテキストで実行する汎用エージェント。Web 検索は不可（`web-researcher` と明確に分離）
  - 対象ファイル: `data/agents.yaml`, `tools/sub_agent_tools.py`, `docs/agents_spec.md`
- **タスク分解（Task Decomposition）指示** — 複数フェーズを含むリクエストを直列的なサブエージェント呼び出しに分解するガイドラインを Coding モード instructions に追加
  - 対象ファイル: `data/prompts.yaml`, `tools/sub_agent_tools.py`, `docs/agents_spec.md`
- **Anthropic SDK リトライログをサブエージェント UI に表示** — サブエージェント実行中の API リトライ（429/500 等）を `⚠` 付きでツリー表示に反映。`anthropic._base_client` の INFO ログをキャプチャ
  - 対象ファイル: `tools/sub_agent_runner.py`, `repl.py`
- **`--debug` モードに `anthropic` ロガーを追加** — Anthropic SDK の内部ログ（リトライ・レート制限等）がデバッグ出力に含まれるように
  - 対象ファイル: `repl.py`
- **`NOTICE.md` — サードパーティライセンス一覧** — `pip-licenses` で全依存ライブラリの名前・バージョン・ライセンス種別・URL を自動生成。Apache-2.0 の NOTICE 義務を充足
  - `scripts/update_notice.sh` で再生成可能
  - `pip-licenses` を dev 依存に追加

### Changed

- **Planning モードの role テキストを汎用化** — "senior technical architect" → "senior technical architect and analytical advisor" に拡張。分析レポート・設計文書の作成能力を明示
  - 対象ファイル: `data/prompts.yaml`
- **Coding モードの role テキストを汎用化** — "senior software engineer and domain specialist" → "senior software engineer and versatile task executor" に拡張。コーディング以外の汎用タスク対応を明示
  - 対象ファイル: `data/prompts.yaml`
- **メモリポリシーを拡張** — REMEMBER カテゴリに「ユーザーのコミュニケーション・出力に関する嗜好」と「ユーザーが確認したドメイン知識」を追加
  - 対象ファイル: `data/prompts.yaml`
- **`web-researcher` / `assistant` のルーティング境界を明確化** — Web 検索が必要なタスクは `web-researcher`、ローカルファイルベースのタスクは `assistant` に委譲するガイドラインをサブエージェント選択ガイドに追加
  - 対象ファイル: `data/prompts.yaml`, `data/agents.yaml`, `tools/sub_agent_tools.py`

### Fixed

- **Windows で CTRL+D 終了後にシェルに戻らずハングするバグを修正** — 2 つの原因を修正: (1) `cmd_quit()` がイベントループを `SessionEnd` Hook 発火前に閉じていた → `cmd_quit()` から `shutdown_loop()` を除去し、`Repl.run()` の `finally` ブロックで正しい順序（SessionEnd → shutdown）で実行。(2) `shutdown_default_executor(timeout=None)` がデフォルトの無限待ちで Windows ProactorEventLoop をブロック → `timeout=2` を設定
  - 対象ファイル: `repl.py`, `commands/misc.py`
- **Windows ProactorEventLoop の終了時エラーを抑制** — `loop.close()` 前に null exception handler を設定し、`CancelledError` や weak reference `TypeError` が stderr に出力されるのを防止
  - 対象ファイル: `repl.py`
- **ストリーミング応答の二重描画を修正** — `live.update(streaming_view)` がコンテンツチャンクごとに呼ばれず、4Hz の自動リフレッシュ間に入力が重複表示されていた。`live.update()` を条件ブロックの外に移動し、毎チャンクで更新するよう修正
  - 対象ファイル: `repl.py`
- **`read_url` の httpx コネクションリークを修正** — `httpx.get()` がエフェメラルクライアントを作成して TCP コネクションを閉じずに返していた。`httpx.Client` コンテキストマネージャに置き換え、`with` ブロック終了時に確実にクローズ
  - 対象ファイル: `tools/search_tools.py`
- **GPT-5 / GPT-5.1 の reasoning テスト期待値を修正** — `model_catalog.json` で `supports_reasoning: true` に更新済みだったが、テストが旧来の `False` 期待のままだった。テストをカタログの実態に合わせて更新
  - 対象ファイル: `tests/test_providers.py`

## [v0.6.4] — 2026-03-13

### Changed

- **`web_reader`（URL 読み取り）をデフォルト有効化** — `read_url` は軽量（1 ページ / デフォルト 20,000 文字上限）のため常時有効に変更。`beautifulsoup4` を本体依存に移動
- **`/web` → `/websearch` にリネーム** — DuckDuckGo 検索のみをトグルするコマンドに変更。URL 読み取りは常時有効のためトグル対象外に
- **`search` extra を `ddgs` のみに簡素化** — `beautifulsoup4` は本体依存に移動したため `search` extra は `ddgs` パッケージのみ

- **Web サイト読み取りツールを軽量化（コンテキスト消費削減）** — Agno の `WebsiteTools` を Hooty 独自の軽量 `read_url` ツールに置き換え
  - デフォルト `max_depth=1`, `max_links=1` でクロールせず 1 ページのみ取得（LLM がパラメータで拡大可能、上限クランプ: `max_depth` ≤ 2, `max_links` ≤ 3）
  - 抽出テキストを 20,000 文字で切り詰め（≒ 5,000〜7,000 トークン）
  - JSON Document ラッパーを廃止しプレーンテキストを直接返却
  - `WebsiteReader` のエラー（403 Forbidden、コンテンツ抽出失敗等）をキャッチし、LLM が別 URL をリトライ可能に
  - `--debug` で URL アクセスログ・文字数・切り詰め状況を出力
  - 従来: 天気のような単純クエリ 1 回で 186k トークン消費 → 改善後: 約 1,500〜7,000 トークン（ctx 3〜4%）
  - 対象ファイル: `tools/search_tools.py`, `tools/__init__.py`, `docs/tools_spec.md`
- **`ddgs` パッケージを `>=9.11.3` に更新** — `primp` の impersonate 警告（`Impersonate '...' does not exist, using 'random'`）が解消。`fake-useragent`, `brotli`, `socksio` が依存から除外され軽量化
  - 対象ファイル: `pyproject.toml`, `uv.lock`

### Added

- **`/attach` コマンド — ファイル添付機能** — 画像・テキストファイルをプロンプトに添付し、次のメッセージ送信時にまとめて LLM に送信する
  - 画像（PNG/JPEG/GIF/WebP）: 添付時に即座にリサイズ（`max_side` デフォルト 1568px）し PNG で保存。Vision 非対応モデルでは添付を拒否
  - テキスト（`.py`, `.js`, `.xml`, `.md` 等 17 種）: UTF-8 読み込み、トークン推定付き。大きいファイルは警告表示
  - スタック管理: 重複パスの排除、ファイル数上限（`max_files` デフォルト 20）、トークンハードリミット（`max_total_tokens` / `context_ratio`）
  - クォート付きスペース入りパス・複数ファイル同時指定に対応（`shlex` パース）
  - `/attach paste` — クリップボードから画像やファイルを直接添付（Windows / WSL2 / macOS 対応）。同一画像の重複添付はピクセルハッシュで自動排除
  - `/attach capture [target]` — スクリーンキャプチャを撮影して画像添付（Windows / WSL2 対応）
    - ターゲット指定: アクティブウィンドウ（デフォルト）、モニター番号、プロセス名（`.exe`）、ウィンドウクラス名、タイトル部分一致
    - `--delay N` で遅延キャプチャ（最大 30 秒）、`--repeat N --interval N` で連続キャプチャ（最大 5 枚）
    - PowerShell + Win32 API で直接 PNG ファイルに保存（クリップボード非経由）
    - `active` ターゲット時は自動 3 秒カウントダウン（ウィンドウ切り替え猶予）
    - カウントダウン表示（秒数、カーソル非表示）、Ctrl+C でキャンセル可能
    - 存在しないモニター番号やウィンドウ指定時のエラー表示
    - `/attach capture --help` でヘルプ表示
    - `config.yaml` の `attachment.capture` セクションで制限値をカスタマイズ可能
  - `/attach list` — インタラクティブピッカー（Space トグル、d キーで削除）
  - `/attach clear` — 全添付クリア
  - `--attach` (`-a`) CLI オプション — 起動時にファイルを事前添付（複数指定可）。REPL では最初のメッセージに、Non-Interactive モードでは `--prompt` と組み合わせて画像・テキストを LLM に送信
  - 相対パスは起動元 CWD 基準で解決（`--dir` の影響を受けない）
  - Non-Interactive モードでは一時ディレクトリに画像を保存し、送信後に自動削除（セッションディレクトリを汚さない）
  - プロンプトインジケーター `[📎 N]❯` で添付数を表示、送信後に自動クリア
  - `/new` でのセッション切り替え時にスタック自動リセット
  - `config.yaml` の `attachment` セクションで全パラメータをカスタマイズ可能
  - `Pillow>=12.1.1` を必須依存に追加
  - 対象ファイル: `attachment.py`, `attachment_picker.py`, `clipboard.py`, `capture.py`, `commands/attach.py`, `config.py`, `repl.py`, `oneshot.py`, `main.py`, `pyproject.toml`, `packaging/hooty.spec`

- **`/session purge` の最小日数を 0 に変更** — `/session purge 0` で当日のセッションもパージ対象にできるように
  - 対象ファイル: `commands/session.py`

### Fixed

- **全ピッカーの Space トグルが効かないバグを修正** — `_read_key()` がスペースを `"space"` として返すのに、各ピッカーが `" "` と比較していた問題を修正
  - 対象ファイル: `plan_picker.py`, `memory_picker.py`, `review_picker.py`, `skill_picker.py`, `hooks_picker.py`, `purge_picker.py`, `project_purge_picker.py`

- **モデルカタログに `supports_vision` フラグを追加** — 画像入力（Vision）対応をカタログレベルで判定可能に。`config.supports_vision()` ヘルパー関数を追加（カタログ優先 → Claude フォールバック）。LiteLLM ソースから `supports_vision` を自動抽出し、Claude 全モデル・GPT-5 系等で `true`
  - 対象ファイル: `scripts/update_model_catalog.py`, `data/model_catalog.json`, `config.py`, `docs/provider_spec.md`
- **`web-researcher` サブエージェント追加** — `web_search` + `read_url` を組み合わせた深い Web 調査を隔離コンテキストで実行。`/websearch` OFF 時は 🌐 Y/N ダイアログで確認後に有効化（`requires_config` フィールド）。ツールバジェット制限（`web_search` 最大 3 回、`read_url` 最大 5 回、`max_turns: 12`）で過剰な呼び出しを防止
- **`read_url` にカスタム User-Agent 設定 + `max_chars` パラメータ追加** — Agno の `WebsiteReader` を排除し、httpx + BeautifulSoup で直接実装。全リクエストに `hooty/{version}` User-Agent を適用。`max_chars` パラメータ（デフォルト 20,000、最大 80,000）で LLM がページごとの取得量を調整可能に
- **`AgentDef` に `requires_config` フィールド追加** — サブエージェント実行前に必要な config フラグを宣言し、未満足時にユーザー確認ダイアログを表示
- **サブエージェントのツールヒントに `read_url`・`web_search`・`search_news` を追加** — ツリー表示で URL や検索クエリを表示

- **モデルカタログにケーパビリティフラグを導入** — `model_catalog.json` の各エントリを `int` → `dict` 構造に拡張し、`supports_vision` / `supports_reasoning` / `supports_function_calling` / `supports_response_schema` フラグを追加
  - `supports_thinking()` がカタログの `supports_reasoning` フラグを最優先で参照するようになり、Bedrock / Azure AI Foundry の Claude や Grok reasoning 系モデルでも推論が正しく有効化される
  - `_fix_structured_outputs_detection()` がカタログの `supports_response_schema` を参照するようになり、新モデル追加時のハードコード修正が不要に
  - `get_model_capabilities()` API を `model_catalog.py` に追加。モデルのケーパビリティを dict で取得可能
  - カタログ未登録モデルは従来のハードコードルールにフォールバック（後方互換性維持）
  - 値が `int`（旧形式）の場合は `{"max_input_tokens": int}` として自動変換（後方互換）
  - `scripts/update_model_catalog.py` が LiteLLM から capability フラグを自動抽出。Anthropic 直接 API エントリも抽出対象に追加
  - `/reasoning` の inactive メッセージを "not supported by current provider" → "not supported by current model" に修正
  - ollama セクションに `qwen3.5:4b` を追加
  - 対象ファイル: `model_catalog.py`, `config.py`, `providers.py`, `data/model_catalog.json`, `scripts/update_model_catalog.py`, `commands/model.py`, `docs/provider_spec.md`, `docs/config_spec.md`, `docs/architecture_spec.md`

## [v0.6.3] — 2026-03-12

### Added

- **`--resume` / `--continue` 時に過去の会話履歴を再表示** — セッション復元時に前回の Q&A ペアを REPL と同じフォーマット（ルール線・プロンプト・セパレータ・Markdown 応答）で再表示し、会話の続きとして自然に再開できるようにした
  - 表示件数は `session.resume_history` で設定可能（デフォルト `1`、`0` で無効化）
  - REPL 内の `/session resume` でも同様に表示
  - 既存の会話ログ（`conversation_log.py`）を再利用。新たに `full_output` フィールド（LLM 応答全文）を追加し、`load_recent_history()` で直近 N 件を取得
  - Agno DB からの最終応答をフォールバックとして使用（ログファイル不在時）
  - 長い応答は 4000 文字に切り詰めて表示
  - 対象ファイル: `config.py`, `repl.py`, `conversation_log.py`, `docs/config_spec.md`, `docs/cli_spec.md`

- **Bang Command（`!command`）— REPL シェルエスケープ** — `!` プレフィックスで LLM を介さずシェルコマンドを直接実行
  - `!` 入力で shell mode に切替: プロンプト `❯` → `!`（オレンジ）、入力テキストもオレンジ色に変化
  - ステータスバーが `⚡ shell mode (Esc×2 to cancel)` に切替
  - stdout/stderr はターミナルに直接出力（Ctrl+C で中断可能）
  - stdin は `/dev/null`（prompt_toolkit との競合防止）
  - 非ゼロ終了コードを `exit code: N` で表示
  - Esc×2 で通常モードに復帰、Ctrl+D twice で終了可能
  - shell mode 中は Shift+Tab（plan/code 切替）を抑止
  - Windows: `locale.getpreferredencoding()` によるコンソールエンコーディング対応（CP932）
  - 対象ファイル: `repl.py`, `commands/misc.py`, `docs/cli_spec.md`

### Changed

- **モデルカタログを最新化（2026-03-12）** — LiteLLM ソースから `model_catalog.json` を更新
  - Azure OpenAI: GPT-5.4 / GPT-5.4 Pro（1M コンテキスト）、GPT-5.3 Chat / GPT-5.3 Codex を追加
  - `provider_spec.md` に GPT-5.4 / GPT-5.3 の記載を追加
  - `scripts/update_model_catalog.py`: 手動管理セクション（`anthropic`, `ollama`）がスクリプト実行時に消えるバグを修正。既存カタログのキー順序を保持するよう `_build_catalog()` を改善
  - 対象ファイル: `data/model_catalog.json`, `docs/provider_spec.md`, `scripts/update_model_catalog.py`

### Fixed

- **Windows で Ctrl+C キャンセル後に次のクエリが "Thinking..." のままハングするバグを修正** — `KeyboardInterrupt` 後に `ProactorEventLoop` を差し替える際、モデルの `async_client` と agno グローバル `httpx.AsyncClient` が古い（closed な）イベントループに紐付いたまま残っていた。次の `arun()` 呼び出しで `get_async_client()` が stale なクライアントを返し、HTTP/2 コネクションが新ループ上で動作できずハングしていた
  - `_reset_async_clients()` メソッドを追加: モデルの `async_client` と `agno.utils.http._global_async_client` を同期的に close して `None` にリセット（次回呼び出し時に新ループ上で遅延再生成）
  - イベントループ差し替え直後に `_reset_async_clients()` と `_update_hooks_ref()` を呼び出し（hooks 用ループ参照も更新）
  - 対象ファイル: `repl.py`

## [v0.6.2] — 2026-03-11

### Fixed

- **Windows で "Response cancelled" が勝手に発生するバグを修正** — Windows 上で subprocess 実行中〜完了直後に stale な `CTRL_C_EVENT` が発生し、ユーザー操作なしに `KeyboardInterrupt` → "Response cancelled" が発生していた問題を修正
  - `shell_runner.py`: `subprocess.CREATE_NEW_PROCESS_GROUP` で子プロセスをコンソールグループから分離。`_run_simple()` に `KeyboardInterrupt` ハンドラ追加
  - `repl.py`: Windows `SetConsoleCtrlHandler` API でツール実行中および完了後 5 秒間の stale `CTRL_C_EVENT` を抑制
  - `confirm.py`: 確認ダイアログ後に `msvcrt.kbhit()`/`msvcrt.getwch()` で ConPTY のエスケープシーケンス エコーバックを drain
  - `coding_tools.py`: grep の `subprocess.run()` にも `CREATE_NEW_PROCESS_GROUP` を適用
  - 対象ファイル: `repl.py`, `tools/shell_runner.py`, `tools/confirm.py`, `tools/coding_tools.py`

## [v0.6.1] — 2026-03-11

### Added

- **Ollama プロバイダ** — ローカル LLM（Ollama）を5番目のプロバイダとして追加。`agno.models.ollama.Ollama` クラスを使用
  - `Provider.OLLAMA` enum 値、`OllamaConfig` データクラス（`model_id`, `host`, `api_key`, `max_input_tokens`）を追加
  - ローカル実行（`localhost:11434`）、リモートホスト、Ollama Cloud の3パターンをサポート
  - 環境変数 `OLLAMA_HOST` で Ollama サーバーアドレスを設定可能（Ollama 公式の環境変数名）
  - 認証不要のため `validate_config()` はパススルー
  - モデルカタログに Ollama セクション追加（Llama 3.x, CodeLlama, Qwen 3.5/2.5, Mistral, Phi, Gemma2, DeepSeek 等）
  - カタログ未登録モデルは保守的デフォルト 8,192 トークンにフォールバック。`max_input_tokens` で上書き可能
  - プロファイル・サブエージェントの model_id 切替に対応
  - `pyproject.toml` に `ollama` extra 追加（`pip install hooty[ollama]`）
  - 対象ファイル: `config.py`, `providers.py`, `model_catalog.py`, `data/model_catalog.json`, `repl.py`, `tools/sub_agent_runner.py`, `pyproject.toml`
- **Prompt Caching** — Claude モデルのシステムプロンプトキャッシュを有効化し、入力トークンコスト削減とレイテンシ改善を実現
  - Anthropic（直接 API / Azure AI Foundry 経由）: `agno.models.anthropic.Claude` の `cache_system_prompt=True` で有効化
  - AWS Bedrock（Claude モデル）: `agno.models.aws.claude.Claude` に切り替え、`cache_system_prompt=True` で有効化。非 Claude モデルは従来の `AwsBedrock` を継続使用
  - OpenAI 系（Azure OpenAI / Azure AI Foundry）: サーバー側自動キャッシュのため変更不要
  - `config.yaml` の `session.cache_system_prompt`（デフォルト `true`）で制御。`false` でキャッシュ無効化可能
  - メインエージェント・サブエージェント両方で有効（サブエージェントは親の設定を継承）
  - フッターにキャッシュトークン表示を追加: `»{cache_read_tokens}`（debug モードでは `«{cache_write_tokens}` も表示）
  - `SessionStats` / `PersistedStats` にキャッシュトークンフィールド（`cache_read_tokens`, `cache_write_tokens`）を追加し永続化
  - 対象ファイル: `config.py`, `providers.py`, `session_stats.py`, `repl.py`, `tools/sub_agent_runner.py`
- **表示幅ベースの文字列切り詰め** — CJK 文字の表示幅（2カラム）を考慮した `truncate_display()` ユーティリティを追加
  - `unicodedata.east_asian_width` で Wide/Fullwidth 文字を判定し、ターミナル表示カラム幅ベースで切り詰め
  - CJK 文字の途中で切断しない安全なトランケーション
  - 対象ファイル: `text_utils.py`（新規）、`session_store.py`、`memory_store.py`、`plan_store.py`

### Changed

- **agno 2.5.8 → 2.5.9 にアップグレード** — HITL + `add_history_to_context` のバグ修正、ツールパラメータ記述の `(None)` 除去等の恩恵を受ける。`pyproject.toml` の下限を `>=2.5.9` に引き上げ
- **PyInstaller spec に Ollama 依存を追加** — `hiddenimports` に `agno.models.ollama`、`ollama`、`httpx` を追加。Ollama プロバイダが PyInstaller ビルドに含まれるよう修正
  - 対象ファイル: `packaging/hooty.spec`
- **YAML 設定ファイルのパースエラーをユーザーフレンドリーに** — `config.yaml` / `databases.yaml` / `mcp.yaml` のパースエラー時に Python トレースバックではなく、ファイル名・行番号・エラー内容を簡潔に表示して終了するよう改善。`ConfigFileError` 例外クラスと `_load_yaml_file()` ヘルパーを追加
  - 対象ファイル: `config.py`, `main.py`
- **`compress_ratio` を全モデル 0.7 に統一** — Ollama 等の非 Claude モデル追加に伴い、プロバイダ別の分岐（Claude 0.7 / その他 0.5）を廃止してシンプル化
  - 対象ファイル: `agent_factory.py`
- **`/memory purge` → `/project purge` に移動** — 対象がメモリエントリではなくプロジェクトディレクトリ全体であるため、より適切な `/project` コマンドに移動。`commands/project.py` を新設し、`commands/memory.py` から purge 機能を分離
  - 対象ファイル: `commands/project.py`（新規）、`commands/memory.py`、`repl.py`、`commands/misc.py`
- **`/session list` を Rich Table に置き換え** — f-string 手動整列から Rich `Table` に変更。マークアップタグや CJK 文字による幅ずれ・折り返し崩れを解消
  - 対象ファイル: `commands/session.py`
- **ディレクトリ不一致マーカーを ⚠ → 🚫 に変更** — `session_picker.py`、`/session list`、resume 時の Workspace mismatch 警告で使用するマーカーを統一変更
  - 対象ファイル: `session_picker.py`、`commands/session.py`、`repl.py`
- **`_build_thinking_keywords()` のキャッシュ導入** — 毎メッセージごとのキーワードリスト再構築を回避
  - `_load_default_thinking_keywords()` に `@lru_cache(maxsize=1)` を追加（YAML ファイル読み込みを初回のみに）
  - `_build_thinking_keywords()` にモジュールレベルキャッシュを導入（`config.reasoning.keywords` の内容が変わらない限り前回の結果を再利用）
  - 対象ファイル: `config.py`

### Fixed

- **`/session purge` クラッシュ修正** — `_create_storage()` は `@contextmanager` だが `with` なしで呼び出していたため、`AttributeError` でプロセスが異常終了。孤立ディレクトリカウント時と progress バー内削除処理の2箇所を `with` 文に修正
  - 対象ファイル: `commands/session.py`
- **`apply_patch.py` — while 条件の整理** — `UpdateFile` パーサーの while ループ条件を括弧で明確化し、冗長な `@@` チェックとデッドコード3箇所（到達不能な `if i >= len(lines): break`、既にフィルタ済みの `if cur.startswith("*** "): break`）を削除
  - 対象ファイル: `tools/apply_patch.py`
- **`memory_store.py` — `move_memories()` のデータロスリスク修正** — `upsert` → `delete` の非トランザクション操作を個別 `try/except` で保護。upsert 失敗時は delete をスキップ（データロス防止）、delete 失敗時は重複が残るが安全側に倒す設計
  - 対象ファイル: `memory_store.py`
- **SQLite 接続リソースリーク修正** — `_create_storage()` / `_create_memory_db()` を `@contextmanager` 化し、全呼び出し箇所を `with` 文に変更。`finally` で `db.close()` を確実に呼び、GC 任せのリソース解放を排除
  - 対象ファイル: `session_store.py`、`memory_store.py`
- **文字列切り詰め時のマルチバイト文字切断修正** — `str[:47]` による文字数ベースの切り詰めを表示カラム幅ベースの `truncate_display()` に置き換え。CJK テキストが意図した表示幅を超える問題と、結合文字・サロゲートペアの途中切断を防止
  - 対象ファイル: `session_store.py`（preview）、`memory_store.py`（memory_text）、`plan_store.py`（summary）
- **`plan_store.py` — YAML インジェクション修正** — `_build_frontmatter()` の f-string 手書きを `yaml.dump()` に置き換え、`summary` にコロン・引用符・`#`・`{}`・`[]` 等の YAML 特殊文字が含まれても frontmatter が壊れないように修正。`_parse_frontmatter()` も `yaml.safe_load()` に統一し、書き込みと読み込みのラウンドトリップを保証
  - 対象ファイル: `plan_store.py`
- **Windows でイベントループが close されない問題を修正** — `_shutdown_loop()` の `sys.platform != "win32"` ガード条件を削除し、全プラットフォームで `loop.close()` を呼ぶように変更
  - 対象ファイル: `repl.py`
- **asyncio プライベート API（`_close_self_pipe` / `_make_self_pipe`）使用の除去** — Windows の `KeyboardInterrupt` 後のループ再利用に CPython 内部 API を使用していた箇所を、ループを新規作成して差し替える方式に変更。Python バージョン変更での破壊リスクを排除
  - 対象ファイル: `repl.py`
- **サブエージェントタイムアウト時のリソースリーク修正** — `ThreadPoolExecutor` + `asyncio.run()` で実行中のサブエージェントがタイムアウトした場合に `cancel_event.set()` で停止通知 → 短時間待機 → `pool.shutdown(wait=False)` でクリーンアップするように変更
  - 対象ファイル: `tools/sub_agent_runner.py`
- **ゾンビプロセス発生の修正** — `_kill_process()` で `proc.kill()` 後の `proc.wait(timeout=2)` が `TimeoutExpired` を送出した場合に外側の `except OSError: pass` に飲まれてゾンビ化していた構造を解消。各段階（terminate/kill/wait）を分離し、SIGKILL 後は `timeout=10` で十分に待機
  - 対象ファイル: `tools/shell_runner.py`
- **MCP サーバー接続時の未閉ファイルハンドル修正** — モジュールレベルの `open(os.devnull, "w")` を `_patched_connect()` 内に移動し、`finally` ブロックで `close()` を確実に呼ぶように変更
  - 対象ファイル: `tools/mcp_tools.py`
- **`KeyboardInterrupt` がタイムアウトと混同される問題を修正** — `ShellResult` に `interrupted` フィールドを追加し、ユーザー中断時は `timed_out=True` ではなく `interrupted=True` を返すように変更。呼び出し側で「Command interrupted by user」と正しいメッセージを表示
  - 対象ファイル: `tools/shell_runner.py`、`tools/coding_tools.py`、`tools/powershell_tools.py`
- **`_sync_output` 例外時にカーソル非表示のままになる問題を修正** — `finally` ブロック内の `bsu.show_cursor()` を `try/except` で個別に保護し、broken pipe 等で失敗しても後続のコンソール復元（`_file` / `_write_buffer` の差し替え戻し）が必ず実行されるように変更
  - 対象ファイル: `repl.py`

## [v0.6.0] — 2026-03-10

### Enhanced

- **`ask_user` の Other 自由入力対応** — 全セレクター UI で固定選択肢に加えて自由入力（Other）が利用可能に
  - `number_select` に `allow_other` パラメータを追加。番号選択肢の下に「Other: type to enter...」行を描画し、テキスト入力モードへの切替・カーソル操作・ペースト処理に対応
  - `choices` パラメータ経由の選択肢に自動で Other 行を付与。戻り値は `int | str | None`（選択肢インデックス / Other テキスト / キャンセル）
  - 非 TTY フォールバックも対応（数値以外の入力を Other テキストとして返却）
  - 対象ファイル: `ui.py`, `tools/ask_user_tools.py`

- **Multi-Q wizard の単一 Q 対応** — `_parse_multi_questions` の閾値を 2→1 に変更。`**Q1. …**` 形式の単一質問でも wizard UI（Other 行付き）が表示されるように
  - 対象ファイル: `tools/ask_user_tools.py`

- **`ask_user` instructions の強化** — LLM 向けガイダンスを判断フロー（decision tree）形式に再構成
  - `choices` パラメータの使用を "MUST" に強化、Other/その他を choices に含めない指示を明記
  - 4 パターン（固定選択肢 / 複数サブ質問 / トグルリスト / 自由テキスト）の使い分けを明示
  - 対象ファイル: `tools/ask_user_tools.py`

### Added

- **ビルトインスキル `skill-creator`** — 対話的に新しいスキルを作成するウィザード（`disable-model-invocation: true`、手動呼び出し専用）
  - `/skills invoke skill-creator [スキル名や概要]` でヒアリング → リファレンス取得 → ファイル生成 → 配置先選択 → 検証案内の一連のフローを実行
  - `references/skill-format.md` に SKILL.md フォーマット仕様・フロントマター一覧・Progressive Discovery パターン・ベストプラクティスを収録
  - 配置場所: `src/hooty/data/skills/skill-creator/`

- **プランステータス管理** — プランファイルに `status` フィールド（`active` / `superseded` / `completed`）を追加
  - 同セッション内で新しいプランを保存すると、旧 `active` プランを自動的に `superseded` に更新
  - `exit_plan_mode()` → Coding 遷移成功時にプランを `completed` にマーク
  - `/plans` ピッカー・検索結果にステータスアイコンを色付きで表示（● 緑 = active、◌ dim = superseded、✓ シアン = completed）
  - 対象ファイル: `plan_store.py`, `plan_picker.py`, `commands/plans.py`, `repl.py`

- **`exit_plan_mode()` の summary 構造化** — Coding エージェントへの引き継ぎ情報を改善
  - Planning モードの LLM に `"Goal: ... | Changes: ... | Verify: ..."` フォーマットでの summary 記述を指示
  - Coding エージェントがプランファイル全文を読まずとも要点を把握可能に
  - 対象ファイル: `data/prompts.yaml`

- **`tree` ツール** — 再帰的なディレクトリツリー表示ツールを追加
  - `ls`（単一ディレクトリ）と異なり、ネストされた階層構造を `├──` / `└──` コネクタ付きで可視化
  - `depth`（再帰深度、デフォルト 3）、`limit`（最大エントリ数、デフォルト 200）、`ignore`（`.gitignore` パターン除外）パラメータ
  - ディレクトリ優先ソート、シンボリックリンクディレクトリの再帰防止
  - `explore` / `summarize` エージェント（`run_shell` 禁止）がプロジェクト構造を直接把握可能に
  - 対象ファイル: `tools/coding_tools.py`, `data/agents.yaml`, `data/prompts.yaml`

- **managed パッケージを `run_shell` から利用可能に** — `pkg_manager` が管理するバイナリ（`rg` 等）を LLM の `run_shell()` から直接呼び出せるように
  - モジュールロード時に managed パッケージディレクトリ（`~/.hooty/pkg/{platform}/`）を `os.environ["PATH"]` に追加（Git usr/bin と同じパターン）
  - `rg` を `_SHELL_UTILS` 許可コマンドリストに追加（PATH に存在する場合のみ有効化）
  - `pkg_manager.py` に `pkg_dir()` ユーティリティ関数を追加
  - 対象ファイル: `tools/coding_tools.py`, `pkg_manager.py`

- **`DEV_TOOL_COMMANDS` に C/C++ と Ruby を追加** — `run_shell` の許可コマンドリストに 10 コマンドを追加
  - C/C++: `gcc`, `g++`, `clang`, `clang++`, `cmake`, `ninja`
  - Ruby: `ruby`, `gem`, `bundle`, `rake`
  - 対象ファイル: `tools/dev_commands.py`, `docs/tools_spec.md`

### Changed

- **依存パッケージのバージョン制約を更新** — `pyproject.toml` の minimum バージョンを実際に利用中のバージョンに合わせて引き上げ
  - `agno` : `>=2.5.7` → `>=2.5.8` — Human-Readable Agent ID 導入等（Hooty へのコード変更は不要）
  - `typer` : `>=0.15` → `>=0.24.1` — Python 3.9 サポート廃止の breaking change を含むが Hooty は Python 3.12+ のため影響なし
  - `rich` : `>=13.0` → `>=14.3.3`
  - `pytest` : `>=8.0` → `>=9.0` — `PytestRemovedIn9Warning` のエラー昇格等の breaking change を含むが Hooty テストへの影響なし

### Fixed

- **インタラクティブ CLI ハング防止（stdin=/dev/null）** — `run_shell()` 経由のサブプロセスが stdin 入力待ちでハングする問題を修正
  - `shell_runner.py` の `_run_simple()` / `_run_with_idle_watch()` 両パスに `stdin=subprocess.DEVNULL` を追加。インタラクティブモードを持つ CLI（`python`, `node`, `pnpm` 等）が引数なしで呼ばれた場合に即座に EOF を受け取り終了する
  - `shell=True` でのシェル内リダイレクト（heredoc、パイプ、ファイルリダイレクト）には影響なし
  - coding モード instructions に「stdin は /dev/null であり、インタラクティブコマンドは即 EOF で失敗する」警告を追加
  - `run_shell()` docstring に stdin=/dev/null の説明を追記
  - 対象ファイル: `tools/shell_runner.py`, `tools/coding_tools.py`, `data/prompts.yaml`, `docs/tools_spec.md`

- **`tree` ツールのアイコンマッピング欠落を修正** — `_tool_bullet()` のマッピングに `tree` が未登録で、デフォルトアイコン（⚙️）で表示されていた。ファイル読取グループ（🔍 `#80c8c8`）に追加
  - 対象ファイル: `repl.py`

- **CLAUDE.md のスキル追加パス記述を修正** — `config.yaml` の `skills.extra_paths` と記載されていたが、実際は `/skills add` コマンドで `.skills.json` に永続化される仕組みであるため修正

- **スピナーのスクロールバック残留修正（第2弾）** — WSL/ConPTY 環境でブレイユ文字がスクロールバックに残る問題への追加対策
  - `_BSUWriter` にカーソル hide/show（`\033[?25l` / `\033[?25h`）を追加。`_sync_output()` コンテキスト全体でカーソルを非表示にし、フレーム間のちらつきを防止
  - プロセス異常終了時のカーソル消失を防ぐため `atexit` ハンドラを登録
  - `ScrollableMarkdown` のオーバーフロー装飾を全廃。アニメーション付きブレイユ行・プレフィックス装飾ともに削除し、古い行を静かにトリミングするのみに（ConPTY がどんな装飾文字もスクロールバックに焼き付けるため）
  - `StreamingView` を新設 — `ScrollableMarkdown`（`max_height - 1` 行）と `ThinkingIndicator`（1 行）を合成表示。コンテンツストリーミング停止後も下部のスピナー＋経過秒数が動き続け、LLM 処理中であることが視覚的に分かるように
  - non-streaming `Live` に `transient=True` と `refresh_per_second=4` を追加（streaming Live と設定を統一）
  - `confirm.py` / `ask_user_tools.py` の `live.stop()` 後に `_erase_live_area()` で残留行を明示消去
  - 対象ファイル: `repl_ui.py`, `repl.py`, `tools/confirm.py`, `tools/ask_user_tools.py`

## [0.5.4] - 2026-03-09

### Added

- **ビルトインスキル** — `explain-code`（コード説明 + ASCII 図）と `project-summary`（プロジェクト構造サマリー）を `src/hooty/data/skills/` にビルトインとして同梱
  - `.claude/skills/explain-code/` と `.hooty/skills/project-summary/` から移動
  - プロジェクトスキル・グローバルスキルで同名上書き可能（後勝ち）
  - PyInstaller バンドル（`hooty.spec`）に `data/skills/` ディレクトリを追加

### Fixed

- **スピナーのスクロールバック残留を修正** — WSL ConPTY 環境でスクロールバックにブレイユ文字（⠏ ⠙ ⠸ 等）が残骸として残る問題を修正
  - `_BSUWriter` にフレームバッチング（`begin_frame()` / `end_frame()`）を追加し、cursor-up + erase + 新コンテンツを 1 つの BSU/ESU ペアでアトミックに出力
  - `_sync_output()` が `Console._write_buffer()` をラップしてバッチングを自動適用
  - サブエージェント実行中は `refresh_per_second` を 4 → 2 に低減し、ConPTY タイミング競合の発生確率を軽減
  - 対象ファイル: `repl_ui.py`, `repl.py`

- **`/skills list` の状態カラム幅を統一** — `ON` / `OFF` / `⊘ manual` の表示幅が不揃いで後続カラム（名前・ソース・説明）がずれていた問題を修正。すべて 8 文字幅に統一

- **`_build_skills()` にビルトインディレクトリが未登録** — `discover_skills()` はビルトインスキルを検出するが、`_build_skills()` の Agno ローダーに含まれておらず LLM のスキルツール（`get_skill_instructions` 等）で利用できなかった問題を修正

- **`ctx %` 計算を最後の API コールの `input_tokens` に変更** — `RunResponse.metrics.input_tokens` はラン内全 API コールの累積合計であり、実際のコンテキストウィンドウ使用率を反映していなかった
  - ツール呼び出しが多い操作（project-summary 等）で数値が膨張し、不要な auto-compaction が発動する問題を修正
  - ストリーミングモードでは `ModelRequestCompletedEvent.input_tokens` の最後の値を使用
  - 非ストリーミングモードではイベント取得不可のため累積値にフォールバック
  - `ctx %` 表示・auto-compact 判定・`/context` コマンドの 3 箇所に適用
  - `˄`/`˅` トークン表示と `SessionStats` の統計値は累積値のまま（コスト集計用）
  - 対象ファイル: `repl.py`, `commands/__init__.py`, `commands/session.py`

### Added

- **`apply_patch` ツール** — Claude Code 独自形式（`*** Begin Patch / *** End Patch`）のマルチファイルパッチを 1 回のツール呼び出しで適用
  - `*** Add File` / `*** Update File`（`@@ context` + `-/+` 行、`*** Move to:` リネーム対応）/ `*** Delete File` の 3 操作をサポート
  - ファジーコンテキストマッチング（完全一致 → 空白差異許容 → 部分一致の 3 段階フォールバック）
  - パス検証・スナップショット連携・Safe モード確認ダイアログ対応
  - `src/hooty/tools/apply_patch.py` 新規追加（パーサー + 適用エンジン）
  - `tests/test_apply_patch.py` 新規追加（パーサー 9 + 適用 11 = 20 テスト）

- **`move_file` / `create_directory` ツール** — `run_shell` を経由しない専用ファイル管理ツール
  - `move_file(src, dst)`: パス検証・親ディレクトリ自動作成・スナップショット連携。Safe モード確認ダイアログ対応
  - `create_directory(path)`: 非破壊操作のため確認ダイアログなし。Planning モードでも利用可能
  - 全サブクラス（`ConfirmableCodingTools` / `SelectiveCodingTools` / `PlanModeCodingTools`）にオーバーライド追加

- **`test-runner` サブエージェント** — テスト実行 → 失敗解析 → ソース修正 → 再実行のサイクルを自動化
  - 4 フェーズ: フレームワーク検出 → テスト実行 → 失敗解析（分類・優先度付け）→ 修正 & 再実行（最大 3 リトライ/問題）
  - Python pytest / JS jest・vitest / Go / Rust / Java JUnit を自動検出
  - 親エージェントは `run_agent("test-runner", "<test command>")` で委譲
  - `src/hooty/data/agents.yaml` に定義追加（`max_turns: 40`, `max_output_tokens: 3000`）

- **組み込み Skills 検出基盤** — スキルの 3 階層モデルに builtin 層を追加
  - `src/hooty/data/skills/` をビルトインスキルディレクトリとして検出（最低優先度）
  - 優先順: `builtin < global < extra_paths < project`（後勝ち）
  - `/skills list` で `source: "builtin"` として表示、個別 ON/OFF も可能
  - `pyproject.toml` にパッケージデータ追加

### Changed

- **コーディングツールの LLM 向けドキュメント改善** — 全 11 ツール（`read_file` / `write_file` / `edit_file` / `run_shell` / `grep` / `find` / `ls` / `tree` / `apply_patch` / `move_file` / `create_directory`）のドキュメンテーション文字列を LLM が正しく理解できる形式に統一
  - 実装詳細の記述を LLM 向けの利用ガイドに置換
  - 全パラメータに `:param str name:` 形式の型付きドキュメントと `:return:` を追加
- **サブエージェント委譲指示の強化** — Coding モードのシステムプロンプト（`prompts.yaml`）でサブエージェントへの委譲をデフォルト行動として明示。直接実行は「trivial single-file edits」等の例外に限定
  - `sub_agent_tools.py` の instructions にエージェント選択ガイド（4 エージェント分）を追加
- **`implement` / `test-runner` エージェント instructions 改善** — Tool Selection セクションを追加し、専用ツール（`read_file` / `edit_file` / `grep` / `move_file` 等）を `run_shell` の同等コマンド（`cat` / `sed` / `grep` / `mv` 等）より優先するよう明示。`run_shell` は検証コマンド（test/lint）やビルドツール等、専用ツールがない操作のみに限定。リトライ対象を「自分の変更に起因するもの」に限定する記述を追加。既存テスト失敗は test-runner への委譲を推奨
- **サブエージェントツール継承の拡張** — `_build_coding_tools()` の書き込みメソッド判定を 3 → 6 メソッドに拡張（`apply_patch` / `move_file` / `create_directory` 追加）。`explore` / `summarize` の `disallowed_tools` にも追加

### Fixed

- **`apply_patch` / `move_file` / `create_directory` のツールアイコンが `●` フォールバックになる問題を修正** — `repl.py` の `_tool_bullet()` に 3 ツールのアイコンマッピング（✏️ ファイル書込カテゴリ）を追加
- **サブエージェントのツリー表示で `apply_patch` のヒントにパッチテキスト断片が表示される問題を修正** — `_extract_patch_files()` を追加し、パッチ内の `*** Add/Update/Delete File:` からファイルパス一覧を抽出してカンマ区切りで表示するよう改善（例: `✏️ apply_patch  (src/models.py, tests/test_api.py)`）

### Changed

- **`/memory forget` → `/memory edit` に統合** — 削除とスコープ間移動（project ↔ global）を単一のピッカー UI に統合。`d` キーで削除、`m` キーで反対スコープへ移動。変更は次回セッション起動時から反映
  - `/memory promote`, `/memory demote` は不要となり削除
  - `/memory list` の表示を Rich Table に変更し、全角文字（日本語等）のカラム幅ずれを解消

### Fixed

- **`/memory search` の日本語テキスト検索が動作しない問題を修正** — SQLite の `ilike` が非 ASCII 文字で正しくマッチしないため、Python 側で部分一致検索するように変更

- **ツールアイコン表示の旧 Agno メソッド名との不一致を解消** — `_tool_bullet()` のマッピングが旧名（`save_file`, `replace_file_chunk`, `run_shell_command` 等）のみだったため、現在の Agno が報告するツール名（`write_file`, `edit_file`, `run_shell`, `ls`, `find`, `grep` 等）でアイコンがフォールバック `●` になっていた問題を修正
  - `repl.py`: 新ツール名を追加し、Web（🌐）・DB（🗄️）・GitHub（🐙）・Memory（📌）カテゴリのアイコンも新規追加。旧名は互換性のため保持
  - `sub_agent_runner.py`: `_HINT_KEY` に新ツール名を追加し、サブエージェントのヒント表示を修正
  - `cli_spec.md`: ツール種別アイコン表・確認対象表・表示例を最新のツール名に更新

### Added

- **`implement` サブエージェント** — edit-test-fix サイクルを隔離コンテキストで実行し、親エージェントのコンテキストウィンドウ肥大化を防止
  - `src/hooty/data/agents.yaml` に `implement` エージェント定義を追加（`disallowed_tools: []`, `max_turns: 30`, `max_output_tokens: 3000`）
  - 親エージェントは `run_agent("implement", "<task>")` で実装タスクを委譲し、構造化レポート（SUCCESS/PARTIAL/FAILED）のみ受信
  - 書き込み可能なサブエージェントに `compress_tool_results=True` + `CompressionManager`（ctx_limit × 0.5）を自動設定
  - 親エージェントの委譲ガイダンス（`sub_agent_tools.py`）と Coding モードプロンプト（`prompts.yaml`）に `implement` の使用指針を追加

### Changed

- **auto-compact しきい値を 0.8 → 0.7 に引き下げ** — `implement` 導入と独立した追加の安全マージンとしてコンテキスト圧縮の開始タイミングを早期化

### Added

- **セッション ↔ Working Directory バインディング** — セッションと作業ディレクトリの結びつきを明示化し、不一致時に警告を表示する仕組みを追加
  - `workspace.py` 新規追加 — セッションディレクトリに `workspace.yaml` を保存し、作業ディレクトリを記録
  - `--resume` / `--continue` / `/session resume` で異なるディレクトリからセッションを再開すると `⚠ Workspace mismatch` 警告を表示
  - リバインドは遅延実行（最初のメッセージ送信時に `workspace.yaml` を更新）。即終了すれば元のバインドを保持
  - セッションピッカー（`--resume`）と `/session list` に Project カラムを追加。現在のディレクトリと異なるセッションに `⚠` マーカーを表示
  - パス比較は `os.path.normcase` + `normpath` で Windows/Linux 両対応

### Changed

- **`--resume` と `--session` を統合** — `--session (-s)` を廃止し、`--resume (-r)` に統合。`--resume` は ID 省略でピッカー表示、ID 指定で直接復元
  - `--resume` / `--resume <id>` / `-r` / `-r <id>` の全パターンに対応
  - Typer のオプション値必須制約を `_preprocess_resume_argv()` で回避（ID 省略時にセンチネル値を注入）
  - CLI エントリポイントを `main:app` → `main:_cli_entry` に変更（前処理を挟むため）
- **`/quit` の resume ヒント表示位置を改善** — セッション復元コマンドを goodbye メッセージの前に表示するよう変更

### Fixed

- **Ctrl+C 即時中断の改善** — Thinking フェーズやネットワーク I/O 待ち中に Ctrl+C を押しても数秒〜十数秒遅延する問題を修正。POSIX 環境で `add_signal_handler(SIGINT)` により asyncio タスクを即座にキャンセルするようにした。サブエージェント実行中も `cancel_event` で停止シグナルを伝播し、次のイベント取得時に終了する
- **subprocess の cp932 デコードエラー** — Windows 環境で `subprocess.run(text=True)` がデフォルトエンコーディング (cp932) を使い、UTF-8 出力を含むコマンド結果で `UnicodeDecodeError` が発生する問題を修正。`shell_runner.py` と `coding_tools.py` の全 `subprocess.run` に `encoding="utf-8", errors="replace"` を追加

## [v0.5.3] — 2026-03-08

### Fixed

- **セッション一覧の preview 表示崩れ** — `--resume` / `/session list` / `/session purge` で表示されるプレビューに Hook が付与した `<hook_context>` ブロックが混入し、複数行に折り返される問題を修正。`<hook_context>` を除去し、改行・連続空白を1行に正規化するようにした
- **PyInstaller exe でデータファイルが欠落** — `prompts.yaml`, `agents.yaml`, `thinking_keywords.yaml` が `hooty.spec` の `datas` に含まれておらず、exe 実行時に `FileNotFoundError` が発生する問題を修正
- **Windows でファイル読み書きのエンコーディング不統一** — `open()` に `encoding="utf-8"` が未指定の箇所が12箇所あり、Windows のデフォルトエンコーディング (cp932) で非 ASCII 文字を含むファイルの読み書きに失敗する問題を修正。`config.py`, `agent_store.py`, `model_picker.py`, `model_catalog.py`, `mcp_cmd.py`, `hooks.py` の全テキストファイル I/O を UTF-8 に統一

### Refactored

- **repl.py スラッシュコマンド分割** — `repl.py`（4,188行）からスラッシュコマンドハンドラーを `commands/` パッケージに分離し、repl.py を ~1,690行に縮小
  - `commands/__init__.py` — `CommandContext` データクラス（REPLへの依存をコールバック経由に限定）
  - `commands/session.py` — /session, /new, /fork, /compact, /context
  - `commands/skills.py` — /skills とサブコマンド
  - `commands/files.py` — /diff, /rewind, /review, /add-dir, /list-dirs
  - `commands/memory.py` — /memory とサブコマンド
  - `commands/database.py` — /database とサブコマンド
  - `commands/hooks_cmd.py` — /hooks とサブコマンド
  - `commands/model.py` — /model, /reasoning
  - `commands/plans.py` — /plans とサブコマンド
  - `commands/agents.py` — /agents とサブコマンド
  - `commands/misc.py` — /help, /quit, /safe, /unsafe, /rescan
  - `commands/mode.py` — /plan, /code
  - `commands/mcp_cmd.py` — /mcp
  - `commands/web_cmd.py` — /web
  - `commands/github_cmd.py` — /github
  - `repl_ui.py` — UI コンポーネント（ThinkingIndicator, ScrollableMarkdown, テーマ等）
- **テストファイル構成見直し** — ソース構成に合わせてテストを再配置
  - `test_new_fork.py` → `test_commands/test_session.py`
  - `test_ask_user_tools.py` → `test_tools/test_ask_user_tools.py`
  - `test_sub_agent_tools.py` → `test_tools/test_sub_agent_tools.py`
  - `test_coding_tools.py` → `test_tools/test_selective_coding_tools.py`

### Fixed

- **/context 表示改善** — コンパクション後に「no runs yet」と表示される問題を修正。セッションサマリーが存在する場合は「compacted into summary」と表示

- **agent_factory.py のプロンプト外部化** — ハードコードされていたロール定義・モード別 instructions・MEMORY_POLICY を `src/hooty/data/prompts.yaml` に外部化し、プロンプト内容とアセンブリロジックを分離
  - `prompt_store.py` 新規追加 — YAML ローダー + `when` 条件評価 + テンプレート変数置換（`{reasoning_step}` 等）
  - `data/prompts.yaml` 新規追加 — planning/coding 両モードの role・instructions・memory_policy を YAML で管理
  - `agent_factory.py` から 3 定数（`MEMORY_POLICY`, `DEFAULT_PLANNING_ROLE`, `DEFAULT_CODING_ROLE`）と instructions ブロックを削除（-106 行）
  - ランタイム条件付き追加（working_directory, non_interactive, past_context 等）は Python 側に維持
  - `test_prompt_store.py` — 32 テスト追加（ロード・条件評価・テンプレート置換・回帰テスト）

## [v0.5.2] — 2026-03-07

### Performance

- **テスト実行時間を ~3分 → ~1分に短縮** — `_filter_available_commands()` の `shutil.which` 呼び出しがテストごとにキャッシュミスする問題を解消
  - コマンド検出が不要なテストクラスに `_fast_filter` autouse fixture を追加し、実 `shutil.which` をスキップ
  - 不要な `clear_command_cache()` 呼び出しをテスト setup から除去（`TestCreateCodingTools`, `TestCreatePowershellTools`, `TestPowerShellSecurity`）
  - `TestBedrockBearerToken` の `import agno.models.aws`（boto3 初回インポート ~13s）をクラスレベル fixture に移動し 1 回に集約

### Fixed

- **Hooks タイムアウト時のサブプロセスリーク修正** — `_execute_command_hook()` で `asyncio.TimeoutError` 発生時にプロセスを `kill()` / `wait()` せずリターンしていたため、タイムアウトしたフックのプロセスがゾンビとして残る問題を修正
- **`_switch_session()` テストの `AttributeError` 修正** — `_make_repl()` ヘルパーに `_hooks_config` と `_loop` 属性が未設定だったため、`_fire_session_end()` 呼び出し時にクラッシュしていた問題を修正

## [v0.5.1] — 2026-03-07

### Improved

- **`hooty setup generate` の有効期限表示** — 生成結果のサマリーに `Expires: N days (at YYYY-MM-DD HH:MM)` を表示するよう追加。`--expiry-days 0` の場合は `Expires: never` と表示

### Security

- **クレデンシャル環境変数の子プロセス漏洩防止** — `hooty setup` で登録したクレデンシャルの API キーが子プロセス（シェルコマンド、Hooks 等）に漏洩しないよう修正
  - クレデンシャル由来の環境変数（`ANTHROPIC_API_KEY`, `AZURE_API_KEY`, `AZURE_OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` 等）を `os.environ` に設定せず、プロセス内の専用シークレットストア（`_credential_secrets`）に保持
  - `get_secret(key)` ヘルパーでシークレットストア → `os.environ` の順にフォールバック参照。ユーザーが自身の環境変数で設定した API キーは従来どおり動作
  - `AWS_BEARER_TOKEN_BEDROCK` はユーザー側の一時トークンのため、`setup generate` のクレデンシャル対象から除外。ユーザー環境変数として設定された場合のみ botocore が自動解決

### Changed

- **シェル演算子制御の緩和** — `_check_command()` のシェル演算子ブロックをパイプ/チェーンのセグメント検証方式に刷新
  - パイプ（`|`）とチェーン（`&&`, `||`, `;`）をデフォルト許可に変更。各セグメントの先頭コマンドを許可リストで個別検証
  - コマンド置換（`$(`, `` ` ``）は許可リスト検証をバイパスするため常時ブロック（変更なし）
  - リダイレクト（`>`, `>>`, `<`）はデフォルトブロック。`2>&1` / `N>/dev/null` は安全パターンとして常時許可
  - `config.yaml` の `tools.shell_operators`（`pipe`, `chain`, `redirect`）で演算子ごとに許可/ブロックを制御可能
  - PowerShell ツールで既に実装済みのパイプセグメント検証パターンを bash にも適用

## [v0.5.0] — 2026-03-07

### Added

- **Hooks（ライフサイクルフック）** — セッション・LLM 会話・ツール利用のライフサイクルでシェルコマンドをトリガーし、ブロック/許可の判定や LLM へのコンテキスト注入を可能にする仕組みを追加
  - 11 イベント: `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `Stop`, `ResponseError`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `ModeSwitch`, `Notification`
  - 設定ファイル: グローバル（`~/.hooty/hooks.yaml`）+ プロジェクト（`<project>/.hooty/hooks.yaml`）の 2 スコープ、リスト連結マージ
  - 各エントリに `source` ラベル（`global` / `project`）を自動付与し、`/hooks list` やピッカーで表示
  - `matcher` フィールドで正規表現フィルタ（`tool_name` / `message` 対象）
  - `blocking: true` + exit 2 によるアクション阻止（`UserPromptSubmit`, `PermissionRequest` で有効）
  - `async: true` によるバックグラウンド実行（fire-and-forget）
  - `additionalContext` による LLM コンテキスト注入（`<hook_context>` ブロック）
  - `PermissionRequest` ゲート: `decision: "allow"` でユーザー確認スキップ（自動承認）、exit 2 でツール拒否
  - `/new` コマンドで `SessionEnd` → `SessionStart` のペア発火
  - Non-Interactive モード（`oneshot.py`）でも `SessionStart` / `Stop` / `SessionEnd` を発火
  - `hooks.py`, `hooks_picker.py`, `test_hooks.py`（31 tests）新規追加
- `--no-hooks` CLI オプション — Hooks 機能を無効にして起動
- `/hooks` スラッシュコマンド群
  - `/hooks` — インタラクティブピッカー（各フック ON/OFF 切替）
  - `/hooks list` — 登録済み全フック一覧表示（source ラベル・matcher・blocking・timeout 付き）
  - `/hooks on` / `/hooks off` — Hooks 機能の全体 ON/OFF
  - `/hooks reload` — hooks.yaml を再読込
- **ファイルスナップショット追跡** — セッション中に LLM が行ったファイル変更を追跡する `FileSnapshotStore` を追加
  - `--snapshot / --no-snapshot` CLI オプションで有効/無効を切替（`config.yaml` の `snapshot.enabled` でも設定可能）
  - LLM の `write_file` / `edit_file` 呼び出し時に、初回変更前のファイル内容を自動スナップショット
  - スナップショットはセッションディレクトリ（`sessions/{id}/snapshots/`）に永続化され、セッション再開時も復元
  - `last_hash`（SHA-256）による外部変更検知 — セッション外でファイルが変更された場合を検出
- `/diff` コマンド — セッション中のファイル変更を unified diff 形式で表示
  - `rich.syntax.Syntax` による diff シンタックスハイライト
  - created / modified / deleted のステータス別表示 + 件数サマリー
  - 外部変更ファイルに `⚠ externally modified` 警告を表示
  - 変更を元に戻した場合（original == current）は非表示
- `/rewind` コマンド — ファイル変更の巻き戻し + 会話履歴リセット
  - 全ファイル巻き戻し / 個別ファイル選択の UI（`hotkey_select` + `number_select`）
  - 外部変更ファイルの追加確認ダイアログ
  - 復元後に `SessionSummaryManager` で会話履歴をコンパクト化し Agent を再生成
  - 新規作成ファイルの巻き戻し時はファイル削除、削除ファイルの巻き戻し時はファイル再作成
- **Sub-agents（サブエージェント委譲）** — メインエージェントから `run_agent()` ツールで独立コンテキストのサブエージェントにタスクを委譲
  - エージェント定義 YAML: ビルトイン（`src/hooty/data/agents.yaml`）+ グローバル（`~/.hooty/agents.yaml`）+ プロジェクト（`.hooty/agents.yaml`）の 3 層後勝ちマージ
  - ビルトインエージェント: `explore`（コードベース探索・read-only）、`summarize`（要約生成・read-only）
  - ツール継承: 親のツールを継承し `disallowed_tools` で個別除外。`NEVER_INHERIT`（run_agent, ask_user, think, analyze, mode switch）は常に除外
  - `SelectiveCodingTools` — `disallowed_tools` で CodingTools の一部メソッドのみをブロックする粒度制御
  - エフェメラル実行（セッション DB/Skills/Memory なし）、ストリーミング対応、Reasoning 常時無効
  - REPL にツリー表示（ツール呼び出しをリアルタイム表示）
  - `agent_store.py`, `sub_agent_tools.py`, `sub_agent_runner.py`, `data/agents.yaml` 新規追加
  - `SelectiveCodingTools` を `coding_tools.py` に追加（`create_coding_tools()` に `blocked_tools` パラメータ追加）
  - `test_agent_store.py`, `test_sub_agent_tools.py`, `test_coding_tools.py` 新規追加
- **Hooks: SubagentStart / SubagentEnd イベント** — サブエージェント起動・終了時にフック発火
  - `SubagentStart`: `agent_name`, `task` を提供。`matcher` で `agent_name` フィルタ可能
  - `SubagentEnd`: `agent_name`, `task`, `tool_call_count`, `result_length`, `elapsed`, `error` を提供
  - いずれも非 blocking（サブエージェント実行の阻止不可）
- **サブエージェント統計** — `/session` にサブエージェント利用状況を表示
  - `/session`（引数なし）: Stats 行の後に合計行（runs, tools, time, in/out tokens）を追加
  - `/session agents`: エージェントごとの内訳テーブル（Runs, Tools, Time, In/Out tokens）を表示
  - `SubAgentRunStats` データクラス追加、`SessionStats` にサブエージェント蓄積 + properties
  - `PersistedStats` に 6 フィールド追加（`stats.json` で永続化）
  - `_arun_sub_agent` で `RunEvent.run_completed` からトークンメトリクスをキャプチャ
- `/agents` スラッシュコマンド群
  - `/agents` — 利用可能なサブエージェント一覧表示
  - `/agents info <name>` — エージェント詳細表示
  - `/agents reload` — agents.yaml 再読み込み
- `/session agents` サブコマンド — サブエージェント実行の内訳テーブル表示

## [v0.4.2] — 2026-03-06

### Added

- **Non-Interactive モード** — REPL を起動せず単発プロンプトを実行し、結果を stdout に出力する非対話モードを追加
  - `--prompt (-p) <text>` でプロンプトを直接指定、またはパイプ入力（`cat prompt.md | hooty`）に対応
  - stdout にレスポンス本文（Markdown）、stderr にメタ情報（モデル名・トークン数・実行時間）を出力
  - セッション・メモリ・スキル・MCP 等は REPL モードと同様に動作
- `--unsafe (-y)` オプション — 起動時から Safe モードを無効化（確認ダイアログをスキップ）。対話・非対話の両モードで有効
- `config.yaml` に `tools.ignore_dirs` 設定を追加 — `ls`/`find`/`grep` で追加除外するディレクトリ名をユーザーが指定可能
- Agent instructions にワーキングディレクトリ情報とアクセス範囲のガイダンスを追加 — LLM がプロジェクト外パス（`~/.m2` 等）へのアクセスを自主的に抑制

### Changed

- `--profile` の短縮オプションを `-p` から削除（`--prompt` に譲渡）。`--profile` はフルネームのみで使用
- ディレクトリ除外ルールを `.gitignore` ベースに刷新
  - `_DEFAULT_IGNORE_DIRS`（20+個のハードコード）を廃止し、`.gitignore` から単純ディレクトリ名を自動抽出する方式に変更
  - `.gitignore` あり: `{.git}` ∪ `.gitignore` 抽出 ∪ `config.yaml tools.ignore_dirs`
  - `.gitignore` なし: `{.git}` ∪ `{node_modules, __pycache__, .venv}` ∪ `config.yaml tools.ignore_dirs`
  - `grep` の全バックエンド（rg / grep cmd / Python）に除外ルールを統一適用
    - rg: `--glob !{dir}` オプションを追加
    - grep cmd: `--exclude-dir {dir}` オプションを追加
  - `grep` に `ignore: bool = True` パラメータを追加 — `ls`/`find` と対称的に除外の ON/OFF を LLM が制御可能に
- `_check_command` を `HootyCodingTools` で常時オーバーライドし、シェル演算子ブロック + コマンド許可リストのみ適用する方式に変更
  - Agno 親クラスのバグあるパスチェック（チルダ未展開・`\` 未検出・ドライブレター未検出）を回避
  - `run_shell` のパス制限を撤廃 — safe mode ON ではユーザー確認ダイアログがゲート、safe mode OFF（`/unsafe`）ではユーザーが意図的に制限解除

### Fixed

- `find` の add-dir パス相対化を修正 — `additional_base_dirs` 配下のファイルが結果から脱落する問題を解消
- `grep` 出力の add-dir パス相対化を改善 — `additional_base_dirs` の絶対パスプレフィックスも除去

## [v0.4.1] — 2026-03-05

### Added

- `grep` ツールの 4 段階フォールバック — ripgrep 優先、Windows でも動作保証
  - 優先順位: `~/.hooty/pkg/` の rg → PATH 上の rg → PATH 上の grep → Python 純正実装
  - Python フォールバックは外部コマンド不要（`pathlib.rglob` + `re` で実装）
- パッケージマネージャー（`pkg_manager.py`）— GitHub Releases からバイナリを自動ダウンロード
  - `~/.hooty/pkg/{arch}-{os}/` にキャッシュ（`x86_64-windows`, `x86_64-linux`, `aarch64-darwin` 等）
  - 初回起動時にダイアログで確認、結果を `config.yaml` の `pkg.auto_download` に保存
  - 汎用設計で将来 `fd`, `bat` 等の追加にも対応可能
- `reasoning_tokens` のフッター表示 — Azure OpenAI GPT-5.2+ の reasoning トークン数を `💭 N tokens` で表示
  - `reasoning_tokens > 0` の場合のみ表示（`reasoning_effort: low` ではモデルが reasoning をスキップすることがある）
  - Anthropic `reasoning_content` との共存: `💭 N chars (💭 M tokens)` 形式で両方表示
  - `SessionStats` / `PersistedStats` に `reasoning_tokens` を蓄積・永続化
- Azure OpenAI Reasoning インジケーター — `reasoning_effort` 設定時に ThinkingIndicator を `Reasoning...` に変更
  - コンテンツ受信開始で `Thinking...` に自動復帰
  - `auto` モードで reasoning 不要と判断された場合は `Thinking...` のまま
- REPL 起動時のパッケージチェック — 不足パッケージを `hotkey_select` ダイアログで一覧表示（パッケージ名 + GitHub リポジトリ URL）
- `enter_plan_mode()` ツール — Coding モードから LLM が自発的に Planning モードへ遷移可能に
  - 直前プランファイルがある場合: R: Revise / Y: Start new / N: Keep coding / C: Cancel の 4 択
  - 直前プランファイルがない場合: Y: Start new / N: Keep coding / C: Cancel の 3 択
  - LLM の `revise` パラメータでデフォルト選択を制御
  - Coding LLM の最終レスポンスを `<prior_coding_context>` として Planning Agent に引き継ぎ、未決定の質問は `ask_user()` で確認
- `--dir` オプションで指定された作業ディレクトリの存在チェック — 存在しない場合はエラー終了
- 追加作業ディレクトリ機能（`--add-dir` / `/add-dir`）— `base_dir` 以外のディレクトリに対する読み書きを許可
  - `--add-dir <dir>` CLI オプション（複数指定可）で起動時に追加ディレクトリを指定
  - `/add-dir [path]` スラッシュコマンドでセッション中に動的追加（引数省略時はディレクトリピッカー）
  - `/list-dirs` スラッシュコマンドで現在の許可ディレクトリ一覧を表示
  - `read_file`/`write_file`/`edit_file`/`grep`/`find`/`ls` が追加ディレクトリ配下にアクセス可能
  - `run_shell` 内の絶対パスチェック（`_check_command`）も追加ディレクトリを許可
  - Agent の instructions に追加ディレクトリ情報を含め LLM に明示的に通知
  - セッションスコープ（永続化しない）。`/new` で CLI 指定分は維持、スラッシュコマンド追加分はリセット
  - 危険パス（`/`、ホームディレクトリ全体）追加時は警告ダイアログを表示
- `file_picker.py` に `pick_directory()` 関数を追加 — ディレクトリのみ表示・ファイルシステムルートまでナビゲート可能なピッカー
- 会話履歴ログ機能 — ユーザー入力と LLM 最終回答（最後のツール呼び出し後のテキスト）のペアを JSONL 形式でリアルタイム保存
  - 保存先: `~/.hooty/projects/{name}-{hash}/history/{session-id}.jsonl`
  - `/compact` でセッション履歴がクリアされても JSONL ログは保持
  - LLM がシステムプロンプト経由でログの存在を把握し、ユーザーの明示的な要求時に過去の会話を参照可能
- `grep`/`find`/`ls` がプロジェクトディレクトリ（`~/.hooty/projects/<slug>/`）およびセッションディレクトリ配下を読み取り可能に — `_check_path` オーバーライドで `extra_read_dirs` を許可
  - `write_file`/`edit_file` には `base_dir` 制限ガードを追加し、読み取り拡張による書き込みを防止
  - `extra_read_dirs` はミュータブルリストで管理し、`/add-dir` で動的追加に対応
  - `read_file` の既存オーバーライドも `extra_read_dirs` ベースに統一

### Changed

- `propose_execution()` → `exit_plan_mode()` にリネーム（Claude Code の ExitPlanMode に倣った命名）
  - クラス: `ProposeExecutionTools` → `ExitPlanModeTools`
  - ファイル: `propose_tools.py` → `exit_plan_mode_tools.py`
  - Toolkit name: `"propose_execution_tools"` → `"exit_plan_mode_tools"`
- `exit_plan_mode()` の確認フローを簡素化 — ツール内の `_confirm_action()` を削除し、REPL 側の `● Switch to coding mode?` パネル 1 回のみに統一（従来は二重確認）
- REPL ループの pending フラグ処理を `while` ループに変更 — coding→plan→coding の連鎖遷移でも自動的に次のフェーズが開始されるよう修正
- `ask_user()` の選択肢ガイドラインを Planning / Coding 両モードの instructions に追加
  - 丸数字（①②③）等の非 ASCII シンボルを禁止し、プレーン ASCII ラベル（1, 2, A, B）のみ使用
  - 自由入力選択肢（例: "Other — please describe"）を常に末尾に含める
- `/plans` を統合ピッカーに変更 — 一覧表示の代わりにインタラクティブピッカーを直接表示し、`v` で閲覧・`d` で削除をワンストップ操作に統合。ビュー後は自動的にピッカーに戻り連続操作可能
- `/plans view <id>` と `/plans delete` サブコマンドを廃止（ピッカーの `v`/`d` キーで代替）
- `/plans search <keyword>` はそのまま維持
- プランの保存先をセッション単位（`sessions/{id}/plans/`）からプロジェクト単位（`projects/<slug>/plans/`）に変更 — セッションをまたいでプランを参照・管理可能に
- `read_file()` のディレクトリ許可をプロジェクトディレクトリにも拡張 — Coding Agent がプロジェクト配下のプランファイルを読み取れるよう対応

### Fixed

- Plan モードで Native Reasoning（Extended Thinking）と ReasoningTools（`think()`/`analyze()`）が二重に有効になる問題を修正 — Native Reasoning 対応モデルでは ReasoningTools を除外し、非対応モデルでのみ CoT フォールバックとして追加するよう排他制御を実装
- `/reasoning` トグル時に Plan モードのツール一覧が追従しない問題を修正 — `_reasoning_active` の変化を検出し Agent を再生成
- `/model` 切替時に Plan モードの ReasoningTools の有無が変わらない問題を修正 — Plan モード時はツールを再利用せず必ず再構築
- Plan モードの instructions が Native Reasoning 有効時にも `think()`/`analyze()` の使用を指示する問題を修正 — `_reasoning_active` に応じて「extended thinking」/「think()/analyze()」を条件分岐

## [v0.4.0] — 2026-03-04

### Added

- Anthropic プロバイダ追加（`provider: anthropic`）— `agno.models.anthropic.Claude` を使用
  - 直接 Anthropic API（`ANTHROPIC_API_KEY`）と Azure AI Foundry 経由（`base_url` 設定）の両方をサポート
  - ネイティブ `messages.count_tokens` API による正確なトークンカウント（tiktoken 補正ハック不要）
  - Azure 経由では `AZURE_API_KEY` / `ANTHROPIC_API_KEY` のいずれも使用可能
  - `anthropic` オプショナル依存追加（`pip install hooty[anthropic]`）
  - モデルカタログに `anthropic` セクション追加
- `hooty setup generate` で Anthropic プロバイダのクレデンシャル収集に対応
- プロファイルに `base_url` フィールド追加（Anthropic プロバイダ用）
- Agent Skills 統合 — [オープン標準](https://agentskills.io)準拠のスキルパッケージでエージェントの専門知識を拡張
  - Progressive Discovery: LLM はスキル概要のみをシステムプロンプトで把握し、必要時にオンデマンドで詳細をロード
  - スキルディレクトリ検出: グローバル（`~/.hooty/skills/`） + プロジェクト（`.github/skills/`, `.claude/skills/`, `.hooty/skills/`）
  - 個別 ON/OFF: `/skills` ピッカーで切替、状態は `.skills.json` に永続化
  - 手動呼び出し: `/skills invoke <name> [args]` で `$ARGUMENTS` 置換して LLM に送信
  - 外部スキルディレクトリ: `/skills add [--global] <path>` / `/skills remove [--global] <path>`
  - `--no-skills` CLI オプションで無効化起動、`/skills on|off` で実行中トグル
  - `config.yaml` の `skills.enabled` で全体制御

- `/reasoning` キーワード検出 + 動的 budget — メッセージ内のキーワードに応じてリクエスト単位で thinking budget を 3 段階で自動調整
  - `auto` モード: キーワード検出時のみ thinking 有効（コスト節約）、`on` モード: 常時有効 + キーワードで budget 上書き
  - 3 レベル: `think`/`考えて`（4,000）、`think hard`/`megathink`/`よく考えて`（10,000）、`ultrathink`/`熟考`（30,000）
  - `config.yaml` の `reasoning.keywords` でレベル毎のキーワードをカスタマイズ可能（デフォルトは `src/hooty/data/thinking_keywords.yaml`）
  - thinking パラメータをモデル作成時から per-request 適用に変更（`_apply_thinking()`）
  - `/reasoning` トグル順を `off → auto → on → off` に変更

### Changed

- Safe モードをデフォルト ON に変更 — 起動直後からファイル書き込み・シェル実行前に確認ダイアログを表示（`/unsafe` で無効化可能）

### Performance

- `/model` でのプロファイル切替を高速化 — モデル非依存コンポーネント（`storage`, `tools`, `skills`）を旧 Agent から再利用し、MCP 接続・Skills ディレクトリ走査・SqliteDb 初期化をスキップ

### Fixed

- インタラクティブピッカー UI 操作中にカーソルが点滅する問題を修正 — 選択中はカーソルを非表示にし、終了時に復元するよう全ピッカー（session / purge / project_purge / memory / skill）と共通 `ui.py` を修正
- 並列ツール呼び出し時に確認ダイアログが同時表示される問題を修正 — `_confirm_action()` に `threading.Lock` を追加し直列化。"A"（All）選択後の後続ダイアログも即承認されるよう double-checked locking を実装
- Anthropic プロバイダで Claude 4.6 以降のモデル ID が structured outputs 未対応と誤判定される問題を修正 — `_fix_structured_outputs_detection()` でモデル ID パターンマッチによるオーバーライドを追加
- `/model` でモデル切り替え時に SDK 未インストール等のエラーが発生すると REPL が終了する問題を修正 — 例外キャッチとプロファイルロールバックを追加
- `/model` のエラーメッセージで Rich マークアップが `[anthropic]` 等のブラケット文字列を消す問題を修正 — `rich.markup.escape()` を適用
- `config.yaml` の `providers.anthropic:` が値なし（`null`）の場合に `TypeError` が発生する問題を修正
- `/model` ピッカーで credentials 経由起動時に `(default)` ラベルが表示されない問題を修正 — `config.active_profile` へのフォールバックを追加

## [v0.3.1] — 2026-03-03

### Fixed

- `/model` でモデル切り替え後に `/new` で新セッションを開始すると aiohttp の "Unclosed client session" 警告が出る問題を修正 — Agent 差し替え時に旧モデルの aiohttp クライアント（`close()` / `aclose()`）を明示的にクローズする `_close_agent_model()` ヘルパーを追加し、`/new`, `/fork`, `/session resume`, `/model`, `/plan`, `/code` および DB 再接続時の全 Agent 再生成箇所で呼び出し

## [v0.3.0] — 2026-03-03

### Added

- Azure AI Foundry の対応モデルを拡充（Grok シリーズ、Llama 4 シリーズ）
  - モデルカタログに Grok 8 モデル + Llama 4 2 モデルを追加
  - `update_model_catalog.py` のフィルタを正規表現に統合（Claude / Grok / Llama 4+ を自動取り込み）
  - コード変更不要（`AzureAIFoundry` は汎用クライアント、`config.yaml` の profiles にプロファイル追加のみで利用可能）

- クレデンシャルプロビジョニング機能（`credentials.py` 新規追加）
  - セットアップコードによるクレデンシャル配布（`hooty setup` で対話的インポート）
  - `hooty setup generate` でセットアップコード生成（現在の config.yaml + 環境変数からバンドル）
  - `hooty setup generate --dump` で暗号化前の生 JSON ペイロードを出力
  - `hooty setup show` で保存済みクレデンシャルのステータス表示（シークレットはマスク）
  - `hooty setup clear` で保存済みクレデンシャルを削除
  - 暗号化：Fernet + PBKDF2（480,000 iterations）、マシンバインド（hostname + username）
  - セットアップコードはパスフレーズなし（simple mode）/ パスフレーズあり（secure mode）を選択可能
  - `.credentials` ファイルの優先度は最低（config.yaml・環境変数・CLI 引数で上書き可能）
  - 複数プロバイダの config + env を 1 つのセットアップコードにバンドル可能
- クレデンシャル有効期限機能
  - `hooty setup generate --expiry-days N` で有効期限付きクレデンシャルを生成（デフォルト 30 日、`0` で無期限）
  - 期限切れ時は起動時にエラーメッセージを表示して終了（`CredentialExpiredError`）
  - `hooty setup show` を簡素化（Default profile / Profiles / 有効期限の 3 行表示）
- セットアップ未完了時の起動メッセージ表示
  - `config.yaml` と `.credentials` の両方が存在しない場合、`hooty setup` の案内メッセージを表示して終了
  - 片方でも存在すれば従来どおり起動を続行
- バナーに credential 由来ラベル表示（`.credentials` 経由で起動時: `Hooty v0.3.0 (Caged)`）
- `enterprise` エクストラ追加（`cryptography>=43.0`）
- `ui.py` にパスワード入力（`password_input`）・ブラケットペーストモード対応を追加
- プロンプト入力のキーボードショートカット改善
  - `Esc` × 2 で入力内容をクリア
  - `\` + `Enter` でマルチライン入力（行末バックスラッシュで次の行に続ける）
  - `Ctrl+L` で画面クリア
  - `Ctrl+X` `Ctrl+E` で外部エディタ（`$EDITOR`）による入力編集
- ThinkingIndicator に経過時間表示を追加（`⠋ Thinking... 3s`、60秒以上は `1m 3s` 形式）
- セッション統計機能追加（`session_stats.py`）— `/session` コマンドで実行回数・累計 LLM 時間・平均応答時間・平均 TTFT を表示
- セッション統計の永続化（`stats.json`）— `--resume` でセッション再開時に累計統計を引き継ぎ、`/session` で現在値と累計値を並列表示（例: `runs:1 (20)  LLM:7.5s (3m 24s)`）
- `/review` コマンド追加 — インタラクティブなソースコードレビュー機能
  - ファイル/ディレクトリピッカーでレビュー対象を選択
  - 5 種類のレビュータイプ（General / Security / Performance / Architecture / Bug Hunt）＋ カスタム自由入力
  - エージェントがコードを分析し、構造化された指摘（Critical / Warning / Suggestion）を出力
  - 多選択ピッカーで修正対象を選択、個別にカスタム修正指示を追加可能
  - 選択した指摘に対してエージェントが自動修正を実装
  - Planning モードではレビューのみ実行し、修正時に Coding モードへの切り替えを確認
  - `file_picker.py`, `review.py`, `review_picker.py` 新規追加
- `/memory purge` コマンド追加（孤立プロジェクトディレクトリの検出・削除）
- プロジェクトメタデータファイル `.meta.json` 導入（プロジェクトディレクトリ作成時に自動生成、ワーキングディレクトリパスと作成日時を記録）
- `project_store.py` 新規追加（プロジェクト一覧取得・孤立検出・削除）
- `project_purge_picker.py` 新規追加（孤立プロジェクトのインタラクティブ複数選択 UI）
- `/fork` コマンド追加 — 現在のセッションをフォーク（サマリーを引き継いだ新セッションを作成、`metadata.forked_from` にフォーク元 ID を記録）
- `/new` コマンド追加 — 新しいセッションを開始（現在のセッションは DB に保持）
- `/session list` に Forked 列を追加（フォーク元セッション ID を `⑂ <短縮ID>` で表示）
- `/session resume` を ID 省略時にセッションピッカーを表示するよう拡張

### Changed

- バナー表示を `Profile: name (provider / model_id)` 形式に変更（プロファイル未設定時は従来の `Provider: ...` を維持）
- `/clear` コマンドを削除
- セッション切り替えロジックを `_switch_session()` ヘルパーに共通化（`/new`, `/fork`, `/session resume` で共有）

### Fixed

- Windows Terminal PowerShell 上でセットアップコードの貼り付けが途中で切れる問題を修正 — `_drain_printable()` が Windows で機能せず（`select`/`termios` の `ImportError`）、1文字ずつ処理されていたため、貼り付けテキスト末尾の `\r` が "Enter" として解釈され入力が途中で確定されていた。`msvcrt.kbhit()` + `msvcrt.getwch()` によるバッチ読み取りを追加し、`\r`/`\n` のスキップ処理も Unix/Windows 両方に適用
- `/session list` の Project カラムが常に `—` になるバグを修正 — `format_session_for_display()` が `session_state` をトップレベルから取得していたが、実際には `session_data["session_state"]` にネストされているため常に `None` が返っていた
- マークダウンストリーミング表示のフリッカー修正 — `ScrollableMarkdown` のレンダーキャッシュ導入（テキスト・幅が同一ならパース・レンダリングをスキップ）、単一インスタンス再利用、`render_lines(pad=True)` による行幅統一、DEC Synchronized Output (mode 2026) による WSL/ConPTY 環境でのアトミック描画

## [v0.2.0] — 2026-03-01

### Added

- Azure OpenAI Service プロバイダ追加（`--provider azure_openai`）— GPT シリーズを Azure OpenAI デプロイメント経由で利用可能に
- `/rescan` コマンド追加（PATH を再スキャンして利用可能コマンドを更新）
- シェル実行基盤の追加（shell_runner.py）・許可コマンド拡充（9→38）
- Windows 向け PowerShell ツール（powershell_tools.py）
- セッションピッカー（`--resume` でインタラクティブ選択、`--continue` で直近再開）
- PID ベースのセッションロック機構（同一セッション同時アクセス防止）
- セッションディレクトリの遅延作成（初回クエリー時のみ）
- `/session purge [days]` コマンド（インタラクティブ複数選択 UI）
- 確認ダイアログ拡張（`[y/N]` → `[y/N/a/q]`：自動承認・中断対応）
- Plan → Coding 自動遷移（承認後に履歴クリア → モード切替 → plan summary 付き自動実行）
- AskUserTools（LLM からユーザーへの質問：自由入力・選択肢対応）
- Plan → Coding 遷移時のプランファイル永続化・引き継ぎ
- 共通 UI プリミティブ（ui.py: hotkey_select / number_select / text_input）
- Rich Panel ベースのダイアログ UI 統一（タイトル・アイコン・操作種別表示）
- `/context` コマンドにコンテキストウィンドウ状態のビジュアライズを追加（トークン使用量プログレスバー、履歴 runs/messages 数、セッション要約有無、圧縮済みツール結果数）
- Auto-compact 機能（コンテキスト使用率が閾値を超えたとき自動でセッション履歴を圧縮、`session.auto_compact` / `session.auto_compact_threshold` で設定可能）

### Changed

- モデルカタログ更新スクリプト（`scripts/update_model_catalog.py`）を `azure` / `azure_openai` 分離に対応
- バナーの説明文を「AI terminal assistant」→「AI coding assistant」に修正
- グローバル指示ファイルを `~/.hooty/hooty.md` と `instructions.md` の 2 候補から探索し、サイズの大きい方を採用するように変更（同サイズ時は `hooty.md` 優先）
- Planning モードの instructions を調査分析タスクにも対応（`propose_execution()` 呼び出しを実装タスクのみに条件付き化）
- デフォルトモデルを Claude Sonnet 4.6 に変更（Bedrock: `global.anthropic.claude-sonnet-4-6`、Azure: `claude-sonnet-4-6`）
- `/session load` → `/session resume` にリネーム
- 許可コマンドリストを `shutil.which()` で PATH 上の存在確認によりフィルタ（結果はキャッシュ、`/rescan` でリフレッシュ可能）
- スラッシュコマンド一覧（補完・`/help`・仕様書）をアルファベット順に統一
- Planning モードでの write_file / edit_file を完全ブロック
- セッションサマリーをコンテキストに自動追加するよう変更（`add_session_summary_to_context: True`）

### Fixed

- Ctrl+C 後のターミナル状態破損・スピナー残留・Goodbye 後ハングを修正
- termios 復元・カーソルリセット・asyncio タスクの graceful シャットダウン追加

## [v0.1.0] — 2026-02-28

### Added

- 対話型 AI コーディングアシスタント CLI の初期リリース
- AWS Bedrock / Azure AI Foundry プロバイダ対応
- DuckDuckGo 検索・Web サイト読み取りツール（`/web` トグル）
- SQL ツール（databases.yaml による複数 DB 管理、`/database` コマンド）
- MCP サーバー接続管理（streamable-http / sse transport 対応）
- CodingTools 統合（ファイル操作・シェル実行・コード探索）
- コンテキスト管理（ユーザー指示ファイル読み込み、`/context` コマンド）
- モデルカタログ導入（LiteLLM ベース、`/model` で max_input_tokens 表示）
- Agno CompressionManager 連携（コンテキストサイズ自動管理）
- セッション永続化・会話履歴（SQLite）
- `--debug` トレースログ（トークン数・TTFT・経過時間）
- PyInstaller スタンドアロンビルド構成（onedir モード、WSL/Windows 対応）
- 確認ダイアログ（Safe モード用）
- GitHub ツール連携（`/github` トグル）
- ThinkingIndicator のモード別カラー（plan=シアン / execute=ゴールド）
- 起動スピナー・終了メッセージ（ランダム文言）

### Performance

- 起動時の import 遅延化（`--version` / `--help` 高速応答）
- 不要 LLM コール削減（session summaries デフォルト OFF）
- GitHub ツールのオンデマンド化

### Fixed

- `/compact` の read_session エラー修正
- スラッシュコマンド補完の重複修正
- confirm.py の termios インポートを Windows 対応に修正
- Bedrock bearer token 認証修正
