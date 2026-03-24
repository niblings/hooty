# CLI UI 仕様書

## 概要

Hooty は対話型 REPL インターフェースを提供する。シンプルで視認性の高い UI を採用する。

## 起動

### コマンド

```bash
# 基本起動
hooty

# プロファイル指定で起動
hooty --profile opus --dir ~/my-project

# セッション復元（ピッカー / ID 指定）
hooty --resume
hooty --resume <session_id>
```

### CLI オプション

| オプション | 短縮 | 説明 | デフォルト |
|---|---|---|---|
| `--prompt` | `-p` | プロンプトテキスト（非対話モードで起動） | なし |
| `--unsafe` | `-y` | Safe モード無効化（確認ダイアログをスキップ） | `false` |
| `--profile` | | プロファイル名（config.yaml の profiles で定義） | config.yaml の `default.profile` |
| `--resume [id]` | `-r` | セッション復元（ID 省略でピッカー表示、ID 指定で直接復元）。復元時に過去の Q&A を再表示（件数は `session.resume_history` で設定、デフォルト 1） | なし（新規） |
| `--continue` | `-c` | 直近のセッションを復元（Q&A 再表示は `--resume` と同様） | `false` |
| `--dir` | `-d` | 作業ディレクトリ | カレントディレクトリ |
| `--add-dir` | | 追加作業ディレクトリ（読み書き可、複数指定可） | なし |
| `--debug` | | デバッグログ有効化 | `false` |
| `--no-stream` | | ストリーミング無効化 | `false` |
| `--attach` | `-a` | ファイルを最初のメッセージに添付（複数指定可）。相対パスは起動元の CWD 基準で解決される（`--dir` の影響を受けない） | なし |
| `--no-skills` | | Agent Skills を無効化して起動 | `false` |
| `--snapshot` / `--no-snapshot` | | ファイルスナップショット追跡の有効/無効 | config.yaml の `snapshot.enabled`（デフォルト `false`） |
| `--version` | `-v` | バージョン表示 | |
| `--help` | | ヘルプ表示 | |

### Non-Interactive モード

`--prompt (-p)` 指定時、または stdin がパイプの場合、REPL を起動せず単発で実行する。

```bash
# --prompt で直接指定
hooty -p "テストを全部通して"

# パイプ入力
cat prompt.md | hooty
echo "README を翻訳して" | hooty

# --unsafe で確認なし + stdout リダイレクト
hooty -y -p "構造を説明して" > result.md

# stderr も抑制
hooty -y -p "構造を説明して" > result.md 2>/dev/null

# ファイル添付付き（画像解析、テキスト分析）
hooty -p "このエラーを修正して" --attach error.png
hooty -p "ログを分析して" -a trace.log -a metrics.json
echo "説明して" | hooty --attach screenshot.png
```

- **stdout**: LLM レスポンス本文（プレーン Markdown）
- **stderr**: メタ情報（モデル名、トークン数、実行時間）、エラー
- **終了コード**: 0=成功、1=LLM エラー、2=設定エラー
- `--unsafe` なし + 非対話: 確認が必要な操作はデフォルト拒否
- `ask_user()`: 非対話モードでは即座に `"(no response)"` を返却

詳細は [Non-Interactive モード仕様書](non_interactive_spec.md) を参照。

## ウェルカムバナー

起動時に以下のバナーを表示する:

```
   ,___,
   (o,o)    Hooty v0.3.0
   /)  )    Profile: sonnet (bedrock / global.anthropic.claude-sonnet-4-6)
  --""--    Working directory: ~/my-project
            Type /help for commands, Ctrl+D to exit
```

- フクロウの ASCII Art マスコット
- バージョン、プロファイル名（プロバイダ / モデル ID）、作業ディレクトリを表示
- プロファイル未設定時は従来の `Provider: Bedrock (model_id)` 形式で表示
- `/help` と終了方法の案内

### フクロウの目（時間帯別）

| 時間帯 | 目の文字 | 色 | 状態 |
|---|---|---|---|
| 6:00–8:00 | `=` | `#9E8600`（暗いゴールド） | しょぼしょぼ（起床中） |
| 8:00–22:00 | `o` | `#E6C200`（ゴールド） | ぱっちり |
| 22:00–6:00 | `ᴗ` | `#9E8600`（暗いゴールド） | 半目（眠い） |

## プロンプト

```
❯
```

- `❯`（太字）に続けてユーザーが入力
- 入力が空の場合は Enter を無視して再度プロンプト表示
- プロンプト上部に `─` ルール線（`#444444`）、下部に `╌` セパレータ（`#444444`）を表示

## カラースキーム

### 基本テーマ

| 要素 | 色 | Rich スタイル | 用途 |
|---|---|---|---|
| バナー（マスコット本体） | 白 | `bright_white` | フクロウ ASCII Art |
| バナー（マスコットの目） | ゴールド | `bold #E6C200` | `o,o` 部分 |
| バージョン | シアン | `cyan` | `Hooty v0.3.0` |
| バナー情報 | 薄白 | `dim` | Provider, Working directory 等 |
| プロンプト | 太字白 | `bold white` | `❯` |
| エラー | 赤 | `bold red` | `✗ エラーメッセージ` |
| 警告 | 黄 | `yellow` | MCP 接続失敗等の警告 |
| 成功メッセージ | 緑 | `green` | `✓ 完了` 等 |
| スラッシュコマンド名 | シアン | `cyan` | `/help` 表示時のコマンド名 |
| スラッシュコマンド説明 | 薄白 | `dim` | `/help` 表示時の説明テキスト |
| セッション ID | マゼンタ | `magenta` | `/session` 表示時の ID |

## 応答表示

### ストリーミング表示フロー

応答は Rich の `Live` コンポーネントでストリーミング表示する。

```
ユーザー入力
    │
    ▼
ThinkingIndicator 表示（スピナー＋経過秒数）
    │
    ├─ コンテンツ受信開始 → StreamingView に切替
    │   （ScrollableMarkdown + 下部 ThinkingIndicator）
    │
    ├─ ツールコール開始 → 推論テキストを ● メッセージとして永続表示
    ├─ ツールコール実行中 → Thinking... (tool_name) アニメーション
    ├─ ツールコール完了 → Thinking... に戻る
    │
    ▼
最終テキスト → Markdown レンダリングで表示
    │
    ▼
フッター表示（モデル名・時間・トークン・コンテキスト使用率）
```

### ThinkingIndicator

ツール実行中およびレスポンス待ち中に表示されるアニメーションインジケータ。

```
⠸ Thinking... 3s
⠸ Thinking... 12s (read_file)
⠸ Thinking... 1m 3s (run_shell)
⠸ Extended thinking... 5s          ← Anthropic Extended Thinking 中
⠸ Reasoning... 8s                  ← Azure OpenAI Reasoning 中
```

| 要素 | 説明 |
|---|---|
| スピナー | Rich の `dots` スピナー（色: `#E6C200`） |
| テキスト | "Thinking..." の各文字がゴールド系グラデーションで波のように明滅 |
| 経過時間 | リクエスト開始からの秒数をグレー（`#666666`）で表示。60秒以上は `Xm Ys` 形式 |
| ツール名 | `(tool_name)` がグレー（`#888888`）で末尾に表示 |

#### テキスト切り替え

| 条件 | 表示テキスト |
|---|---|
| デフォルト | `Thinking...` |
| Anthropic: `reasoning_content` ストリーム受信中 | `Extended thinking...` |
| Azure OpenAI: `reasoning_effort` 設定済み（TTFT 待機中） | `Reasoning...` |
| コンテンツ受信開始 | `Thinking...` に戻る |

- Anthropic は `reasoning_content` デルタをストリーミングで返すため、受信中にリアルタイムで切り替わる
- Azure OpenAI は reasoning テキストを返さないため、`reasoning_effort` 設定時に初期表示を `Reasoning...` にし、コンテンツ受信開始で `Thinking...` に戻す
- `auto` モードで reasoning 不要と判断された場合（`reasoning_effort = None`）は `Thinking...` のまま

#### ThinkingIndicator のカラーグラデーション

フクロウの目の色（ゴールド）を基調とした 10 段階の明度波:

```
#9E8600 → #a89000 → #b29a00 → #bca400 → #c6ae00
→ #E6C200 → #c6ae00 → #bca400 → #b29a00 → #a89000
```

### StreamingView（コンテンツ＋スピナー合成表示）

コンテンツ受信中は `StreamingView` が `ScrollableMarkdown`（`max_height - 1` 行）と `ThinkingIndicator`（1 行）を合成して表示する。

```
content line (trimmed)        ← オーバーフロー時: 古い行を静かにトリミング（装飾なし）
content line 2
content line 3
⠸ Thinking... 35s            ← ThinkingIndicator（常時表示）
```

- コンテンツが流れている間もスピナー＋経過秒数が下部に表示され続ける
- LLM がツール呼び出し引数を生成中（テキスト到着が止まる）でもスピナーが動き、処理中であることが視覚的に分かる
- オーバーフロー時は古い行を静かにトリミング。インジケータや装飾は一切付けない（ConPTY がリフレッシュフレームをスクロールバックに焼き付けるため、どんな装飾文字も残留アーティファクトになり得る）
- ツールコール開始時に `ThinkingIndicator` 単体に戻す

### 行単位バッファリング

`_async_stream_response()` は LLM からのトークンを即座に `set_text()` せず、行単位でバッファリングする。Rich Live の 4 Hz レンダーティックで毎回 Markdown 全文が再パースされるコストを削減するための最適化。

| フラッシュ条件 | 説明 |
|---|---|
| 初回トークン | スピナー → コンテンツ遷移を即時表示 |
| `\n` を含むチャンク | 行完成 — 即時フラッシュ |
| 500ms 経過 | 改行なしの長い行でもタイマーフォールバックで進捗表示 |
| ストリーム終了 | 未表示のバッファ残りをフラッシュ |
| エラーイベント | エラーメッセージは即時表示 |

いずれの条件にも該当しないトークン到着では `set_text()` をスキップするため、次の 4 Hz ティックで `ScrollableMarkdown` のキャッシュがヒットし、Markdown 再パースが発生しない。

ツールコール開始時は `_needs_first_flush` をリセットし、ツール後の次のコンテンツセグメントでも即時表示を保証する。

### アンチフリッカー（DEC Synchronized Output + カーソル制御）

WSL/ConPTY 環境では、Rich `Live` の cursor-up + erase-line + 新フレーム書き込みが個別のエスケープシーケンスとして処理されるため、スピナーのブレイユ文字（⠏ ⠙ ⠸ 等）がスクロールバックに焼き付く問題がある。

これを防ぐため、複数の防御レイヤーを重ねる:

| 要素 | 説明 |
|---|---|
| `_BSUWriter` | `Console._file` を差し替え、各 `write()` を `\033[?2026h` / `\033[?2026l` で包む |
| フレームバッチング | `begin_frame()` / `end_frame()` で複数 `write()` をバッファに蓄積し、1 つの BSU/ESU ペアとして一括出力。`_sync_output()` が `Console._write_buffer()` をラップして自動適用 |
| カーソル hide/show | `_sync_output()` コンテキスト全体でカーソルを非表示（`\033[?25l`）にし、終了時に復元（`\033[?25h`）。`atexit` ハンドラで異常終了時もカーソル復元を保証 |
| オーバーフロー装飾廃止 | `ScrollableMarkdown` のオーバーフロー表示からインジケータ行・プレフィックス装飾をすべて廃止。古い行を静かにトリミングするのみ（ConPTY がどんな装飾文字もスクロールバックに焼き付けるため） |
| `StreamingView` による高さ固定 | コンテンツ + インジケータの合計高さを常に `max_height` に保ち、高さ遷移に伴うスクロールバック焼き付きを防止 |
| Live 中断時の明示消去 | `confirm.py` / `ask_user_tools.py` の `live.stop()` 後に `_erase_live_area()` で残留行をゼロクリア |
| サブエージェント中のリフレッシュレート低減 | サブエージェント実行中は `refresh_per_second` を 4 → 2 に低減し、ConPTY のタイミング競合を軽減 |

非対応ターミナルはエスケープシーケンスを無視するため、副作用はない。

### 推論メッセージ（● メッセージ）

ツールコール開始時に、それまでに蓄積された LLM の推論テキストを永続表示する。ツールの種類に応じてアイコンと色を変える。

```
  🔍 samples ディレクトリの構造を確認します。
  ⚡ LoCを計算します。
  ✏️ ファイルを更新しました。

  📊 最終結果（Markdown）
  ...
```

#### ツール種別アイコン

| ツール名 | カテゴリ | アイコン | 色 |
|---|---|---|---|
| `read_file`, `ls`, `find`, `grep`, `tree` | ファイル読取 | 🔍 | `#80c8c8`（薄い水色） |
| `write_file`, `edit_file`, `apply_patch`, `move_file`, `create_directory` | ファイル書込 | ✏️ | `#80c880`（薄い緑） |
| `run_shell`, `run_powershell` | シェル実行 | ⚡ | `#c8c880`（薄い黄） |
| `web_search`, `search_news`, `web_fetch` | Web | 🌐 | `#80c8c8`（薄い水色） |
| `list_tables`, `describe_table`, `run_sql_query` | データベース | 🗄️ | `#c8a880`（薄いオレンジ） |
| GitHub 系ツール | GitHub | 🐙 | `#c0c0c0`（グレー） |
| `update_user_memory` | メモリ | 📌 | `#c0a0c0`（薄いピンク） |
| `think`, `analyze` | 推論 | 💭 | `#a0a0d0`（薄い紫） |
| `get_skill_instructions` 等 | スキル | 🧰 | `#a0c0e0`（薄い青） |
| `run_agent` | サブエージェント | 🤖 | `#c0a0e0`（薄いマゼンタ） |
| その他（MCP 等） | 不明 | ● | `#80c8c8`（薄い水色） |

推論メッセージの本文は Markdown としてレンダリングされる。

### 最終テキスト

最後のツールコール以降のテキストは Rich の `Markdown` でレンダリングされる。コードブロックはシンタックスハイライト付き。

### 表示例

```
❯ tool 利用して、samples の LoC を計算
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌

  🔍 samples ディレクトリの構成を確認します。
  ⠸ Thinking... 2s (ls)
  🔍 ファイルを確認しました。
  ⚡ LoC を計算します。
  ⠸ Thinking... 5s (run_shell)

  📊 samples ディレクトリの LoC 統計

  | ファイル | 行数 |
  |---|---|
  | banner_preview.py | 59 |

  ● global.anthropic.claude-sonnet-4-6 for 3.2s | ˄12,345 ˅1,234 »10,200 | ctx 6%
```

### フッター

各応答の末尾に表示する情報行:

```
  ● {model_id} for {elapsed}s | ˄{input_tokens} ˅{output_tokens} »{cache_read_tokens} | ctx {pct}%
  ● {model_id} for {elapsed}s | ˄{input_tokens} ˅{output_tokens} | ctx {pct}%
  ● {model_id} for {elapsed}s | ˄{input_tokens} ˅{output_tokens} »{cache_read} | ctx {pct}% | 💭 {N} chars
  ● {model_id} for {elapsed}s | ˄{input_tokens} ˅{output_tokens} »{cache_read} «{cache_write} | ctx {pct}%   ← debug モード
```

| 要素 | 説明 |
|---|---|
| `●` | 応答完了マーカー |
| `model_id` | 使用したモデル ID |
| `for Xs` | 応答にかかった時間（秒） |
| `˄N` | 入力トークン数（`input_tokens` + `cache_read_tokens` + `cache_write_tokens`）。キャッシュトークンを含む合計値で、コンテキストウィンドウに送られた実際のトークン数を表す。プロバイダ間で統一された意味を持つ |
| `˅N` | 出力トークン数（ラン内全 API コールの累積合計） |
| `»N` | キャッシュ読み取りトークン数（`cache_read_tokens > 0` の場合のみ表示）。全プロバイダ共通で Agno メトリクスから取得。`˄` の内数 |
| `«N` | キャッシュ書き込みトークン数（debug モード時のみ、`cache_write_tokens > 0` の場合のみ表示）。`˄` の内数 |
| `ctx N%` | コンテキストウィンドウ使用率。最後の API コールの `input_tokens` + `cache_read_tokens` + `cache_write_tokens` を `context_limit` で除算。ストリーミング時は `ModelRequestCompletedEvent` の per-request 値を優先、非ストリーミング時は最後のアシスタントメッセージのメトリクスから取得。取得不可時は累積値にフォールバック |
| `💭 N chars` | Anthropic Extended Thinking のテキスト文字数（`reasoning_content` がある場合のみ） |
| `💭 N tokens` | OpenAI Reasoning トークン数（`reasoning_tokens > 0` の場合のみ） |

#### コンテキスト使用率の色分け

| 使用率 | 色 | 意味 |
|---|---|---|
| 0–49% | dim（デフォルト） | 余裕あり |
| 50–79% | 黄色 | 注意 |
| 80–100% | 赤太字 | 警告（`/compact` 推奨） |

#### モデル別コンテキストウィンドウ上限

| モデルプレフィックス | 上限トークン |
|---|---|
| `global.anthropic.claude-sonnet-4-6` | 200,000 |
| `anthropic.claude-3` | 200,000 |
| `anthropic.claude-4` | 200,000 |
| `claude-sonnet-4-6` | 200,000 |
| `Phi-4` | 16,384 |
| その他 | 200,000（デフォルト） |

## モードライン（ボトムツールバー）

プロンプト入力中にターミナル最下行に表示される状態表示。

```
 🚀 coding mode (shift+tab to switch) | safe mode: on
 💡 planning mode (shift+tab to switch) | safe mode: on
```

`/auto` が有効な場合、`mode` が `(auto)` に置換される:

```
 🚀 coding (auto) (shift+tab to switch) | safe mode: on
 💡 planning (auto) (shift+tab to switch)
```

| 要素 | coding mode | planning mode |
|---|---|---|
| アイコン | 🚀 | 💡 |
| 色 | `#00cc66`（グリーン） | `#00cccc`（シアン） |

| 要素 | safe mode: off | safe mode: on |
|---|---|---|
| 色 | `#E6C200`（ゴールド） | `#666666`（グレー） |

- `(shift+tab to switch)` は `#666666`（dim）
- ボトムツールバーの背景は `noreverse`（背景色なし）

## Planning / Coding モード

### 概要

Hooty は 2 つの動作モードを持つ:

| モード | 説明 |
|---|---|
| **Coding**（デフォルト） | 通常の対話モード。LLM が直接ツールを使用して応答 |
| **Planning** | 設計モード。コードベース調査と推論を行い、マークダウン形式の仕様・設計・実装計画を出力する。コードの実装は行わない |

### モード切替

| 方法 | 動作 |
|---|---|
| `Shift+Tab` | planning/coding をトグル（モードラインに即時反映、Agent は次回送信時に遅延再生成） |
| `/plan` | planning モードに切替（Agent を即時再生成） |
| `/code` | coding モードに切替（Agent を即時再生成） |
| `/auto` | 自動遷移トグル — ON 時は `exit_plan_mode()` / `enter_plan_mode()` の確認ダイアログをスキップ |

### 遅延 Agent 再生成

`Shift+Tab` はモードフラグの変更のみ行い、`console.print()` やAgent 再生成を行わない（prompt_toolkit のプロンプト表示中に Rich 出力すると表示が乱れるため）。実際の Agent 再生成は次のメッセージ送信時に `_agent_plan_mode` と `plan_mode` を比較して行う。

### スキル・インストラクション自動検出

メッセージ送信前（`_send_to_agent()`）にスキルディレクトリおよびインストラクションファイルの変更を自動検出し、変更があれば Agent を自動再生成する。plan mode チェックの前に実行される。

- **スキル:** SKILL.md 生コンテンツの SHA-256 ハッシュ（`skill_fingerprint()`）
- **インストラクション:** 対象ファイルの SHA-256 コンテンツハッシュ（`context_fingerprint()`）
- **表示:** `Instructions changed`, `Skills changed`, `Instructions & Skills changed` のいずれか + `— agent reloaded.`

### Plan モードの推論ツール

Plan モードでは、モデルの Native Reasoning（Extended Thinking）対応状況に応じて推論方式が切り替わる:

| 条件 | 推論方式 | 追加ツール |
|---|---|---|
| Anthropic 対応モデル + reasoning=on/auto | Extended Thinking（LLM 組み込み） | なし |
| Azure OpenAI GPT-5.2+ + reasoning=on/auto | Reasoning Effort（LLM 組み込み） | なし |
| 非対応モデル、または reasoning=off | ReasoningTools（CoT フォールバック） | `think()`, `analyze()` |

ReasoningTools が有効な場合:

| ツール | 説明 |
|---|---|
| `think()` | アクション前に問題を分解し、アプローチを計画 |
| `analyze()` | アクション後に結果を評価し、次のステップを決定 |

`/reasoning` トグルや `/model` 切替時、Plan モードではツール一覧が自動的に追従する（Agent 再生成）。

### Plan モードのツール制限

| ツール | Plan モード | Coding モード |
|--------|------------|--------------|
| `read_file`, `grep`, `find`, `ls`, `tree` | 自由に使用可 | 自由に使用可 |
| `write_file`, `edit_file`, `apply_patch`, `move_file` | **完全ブロック** | Safe モード時のみ確認 |
| `create_directory` | 自由に使用可（非破壊） | 自由に使用可（非破壊） |
| `run_shell` | 確認付きで使用可（分析用途） | Safe モード時のみ確認 |
| `think()`, `analyze()` | Native Reasoning 非アクティブ時のみ | 無効 |
| `exit_plan_mode()` | 有効 | 無効 |
| `enter_plan_mode()` | 無効 | 有効 |

`write_file` / `edit_file` を Plan モードで呼ぶと、`exit_plan_mode()` でモード遷移するよう誘導メッセージが返される。

### exit_plan_mode() — Plan → Coding 自動遷移

LLM が計画完了時に `exit_plan_mode(plan_summary)` を呼ぶと、以下のフローで自動遷移する:

```
[planning] LLM: exit_plan_mode("ファイルを新規作成…")
           ↓
╭─ ● Switch to coding mode? ────╮   ← モード遷移確認
│    ❯ Yes, switch to coding     │
│    …                           │
╰────────────────────────────────╯
  ✓ Switched to Coding mode
           ↓ セッション履歴クリア（DB操作のみ、API呼び出しなし）
           ↓ 自動送信: "Implement the following plan...\n\n{plan_summary}"
[coding]   LLM: 計画に基づいて実装開始
```

1. `exit_plan_mode()` 内で `auto_execute_ref[0] = True` + `pending_plan_ref[0] = plan_summary` をセット
2. LLM レスポンス終了後、`_auto_transition_to_execute()` が呼ばれる
3. `● Switch to coding mode?` パネルでユーザーが `Y` → `_clear_session_runs()` で DB 内の planning 履歴をクリア
4. プランファイルを保存し、ステータスを `completed` にマーク（同セッション内の旧 `active` プランは `cancelled` に自動更新）
5. Coding モードのエージェントを新規作成し、plan summary を含むメッセージを自動送信
6. メインループの `_pending_execute` フラグ経由で送信（再帰呼び出しを回避）

`n` を選ぶとモード遷移せず planning に留まる。Ctrl+C でも同様。

`/auto` が ON の場合、確認ダイアログをスキップして即座に Coding モードに切り替わる（`Y` 選択と同等）。

#### plan_summary のフォーマット

Planning モードの LLM は `exit_plan_mode()` に渡す summary を以下の構造で記述するよう指示されている:

```
"Goal: <目的> | Changes: <変更対象ファイル/モジュール> | Verify: <検証コマンド>"
```

Coding エージェントはこの summary でプランの要点を把握し、必要に応じてプランファイル全文を `read_file()` で参照する。

### enter_plan_mode() — Coding → Planning 自動遷移

LLM が Coding モード中に `enter_plan_mode(reason, revise)` を呼ぶと、以下のフローで Planning モードへの遷移を開始する:

```
[coding] LLM: enter_plan_mode("エラー処理が不足", revise=True)
         ↓
╭─ ● Switch to Planning ──────────╮   ← 選択 UI
│    エラー処理が不足               │
│    ❯ R: Revise current plan      │   ← revise=True 時デフォルト
│      Y: Yes, start new plan      │
│      N: No, keep coding          │
│      C: Cancel                   │
╰──────────────────────────────────╯
```

直前のプランファイルがない場合は R 選択肢を省略した 3 択になる:

```
╭─ ● Switch to Planning ──────────╮
│    認証方式の設計が必要           │
│    ❯ Y: Yes, start new plan      │
│      N: No, keep coding          │
│      C: Cancel                   │
╰──────────────────────────────────╯
```

1. `enter_plan_mode()` 内で `enter_plan_ref[0] = True` をセット
2. LLM レスポンス終了後、`_auto_transition_to_plan()` が呼ばれ選択 UI を表示
3. Revise → 直前プランファイルパスと reason + coding コンテキストを Planning Agent に自動送信
4. Yes → reason + coding コンテキストを Planning Agent に自動送信
5. No/Cancel → Coding モード継続

coding コンテキスト（`_last_response_text`）は `<prior_coding_context>` ブロックとして Planning Agent に渡される。未決定の質問がある場合、Planning Agent は `ask_user()` で確認してからプランを確定する。

`/plan` コマンドは常に新規プランとして扱い、この分岐フローは経由しない。

`/auto` が ON の場合、確認ダイアログをスキップして即座に Planning モードに切り替わる。`revise=True` かつ直前のプランファイルがある場合は `R`（Revise）、それ以外は `Y`（新規プラン）として動作する。

### プラン保存とステータス管理

Planning モードの出力はプランファイルとして `~/.hooty/projects/{slug}/plans/{uuid}.md` に YAML フロントマター付きで保存される。

#### フロントマター構造

```yaml
---
session_id: <セッション UUID>
summary: <概要>
status: active
created_at: '<ISO 8601 タイムスタンプ>'
---
```

#### ステータスライフサイクル

| ステータス | アイコン | 色 | 意味 |
|---|---|---|---|
| `active` | ● | 緑（`#50fa7b`） | 現在有効なプラン |
| `completed` | ✓ | シアン | `exit_plan_mode()` で Coding モードに引き渡し済み |
| `pending` | ◷ | 黄（`yellow`） | 棚上げ（再開可能）。新プラン作成で自動キャンセルされない |
| `cancelled` | ✗ | 赤（`red`） | 放棄、または新プラン作成時に自動置換された |

**遷移ルール:**
- `save_plan()` 時、同セッション内の既存 `active` プランを自動的に `cancelled` に更新（`pending` は対象外）
- `exit_plan_mode()` → Coding 遷移成功時、保存されたプランを `completed` に更新
- 不明なステータス（レガシーの `superseded` 含む）は読み込み時に `cancelled` として扱われる

#### `/plans` コマンド

| コマンド | 動作 |
|---|---|
| `/plans` | インタラクティブピッカー（view + delete） |
| `/plans search <keyword>` | キーワード全文検索 |

ピッカーおよび検索結果にはステータスアイコンが表示される。

## Safe モード

危険な操作（ファイル書き込み、シェルコマンド実行）の前にユーザー確認を要求するモード。

| コマンド | 動作 |
|---|---|
| `/safe` | セーフモードを有効化（デフォルト） |
| `/unsafe` | セーフモードを無効化 |

### 確認対象

| 操作 | 確認メッセージ |
|---|---|
| `write_file` | `ファイル書き込み: {file_name}` |
| `edit_file` | `ファイル編集: {file_name} (L{start}-{end})` |
| `apply_patch` | `パッチ適用: {patch_preview}` |
| `move_file` | `ファイル移動: {src} → {dst}` |
| `run_shell` | `シェルコマンド: {command}` |

### 確認ダイアログ

Rich Panel ベースの hotkey セレクターで表示する。タイトルに `⚠  <操作種別>`、ボディに対象（ファイルパス・コマンド文字列）を表示する。

```
╭─ ⚠  Write File ─────────────────────────────────╮
│                                                   │
│    samples/demo.py                                │
│                                                   │
│    ❯ Yes, approve this action.                    │
│      No, reject this action.                      │
│      All, approve remaining actions.              │
│      Quit, cancel execution.                      │
│                                                   │
│    ↑↓ move  Enter select  y/n/a/q shortcut  Esc  │
╰───────────────────────────────────────────────────╯
```

| タイトル | 使用箇所 |
|---|---|
| `⚠  Write File` | ファイル書き込み |
| `⚠  Edit File` | ファイル編集 |
| `⚠  Shell` | シェル実行 |
| `⚠  Shell (Plan)` | シェル実行（Plan モード） |
| `⚠  PowerShell` | PowerShell 実行 |
| `⚠  PowerShell (Plan)` | PowerShell 実行（Plan モード） |
| `⚠  Execute Plan` | プラン実行承認 |

| キー | 動作 |
|------|------|
| `Y` / Enter（Yes 選択時） | この 1 回のみ承認 |
| `N` / Esc | 拒否 |
| `A` | 承認 + **このレスポンスターン内の以降の確認を自動承認** |
| `Q` | `KeyboardInterrupt` を送出 → レスポンス全体を中断 |
| Ctrl+C | Live を復帰してから中断（`q` と同等） |

自動承認フラグ（`_auto_approve`）は `_send_to_agent()` 冒頭で毎ターンリセットされる。

### 並列ツール呼び出し時の直列化

agno は並列ツール呼び出しを `asyncio.to_thread()` で別スレッドに dispatch する。`_confirm_action()` は `threading.Lock`（`_confirm_lock`）で全体を囲み、ダイアログが 1 つずつ表示されるよう直列化する。

- **`threading.Lock`**（`asyncio.Lock` ではない）— スレッド間の排他制御
- **double-checked locking** — ロック取得後に `_auto_approve` を再チェックし、先行スレッドが "A" を選んだ場合はダイアログを出さずに即承認
- **`live.stop()` / `live.start()` もロック内** — 複数スレッドが同時に Rich Live を操作する競合を防止

### 実装

`confirm_ref: list[bool]` を mutable 参照として REPL とツールインスタンス間で共有。Agent の再生成なしにモードを切替可能。

## セッション管理

### コンテキスト最適化

長い会話でトークン上限に達することを防ぐため、以下の 2 つの戦略を自動適用する:

#### 1. ツール結果圧縮

ツール呼び出しの結果（ファイル内容、コマンド出力等）を LLM で要約圧縮する。

| 設定 | 値 |
|---|---|
| `compress_tool_results` | `True` |
| `compress_tool_results_limit` | 3（未圧縮結果が 3 件で自動圧縮） |

圧縮時に保持される情報: 数値・統計、日時、エンティティ名、URL・ID、引用

#### 2. セッションサマリー

各 run 終了時にセッション全体の要約を生成し、次回以降はサマリーをコンテキストに含める。

| 設定 | 値 |
|---|---|
| `enable_session_summaries` | `True` |
| `add_session_summary_to_context` | `True` |

### `/compact` コマンド

手動でセッション履歴を圧縮する。

```
❯ /compact

  Compacting session history...
  ✓ Compacted 12 runs (87 messages) into summary
```

動作:
1. `SessionSummaryManager` でセッション全体の要約を生成
2. 全 runs（メッセージ履歴）をクリア
3. サマリーのみ保持して DB に保存
4. Agent を再生成（クリーンなセッションを読み込み）

### Auto-compact

コンテキスト使用率が閾値を超えた場合、LLM 応答後に自動でセッション履歴を圧縮する。

| 設定 | デフォルト | 説明 |
|---|---|---|
| `session.auto_compact` | `true` | auto-compact の有効化 |
| `session.auto_compact_threshold` | `0.7` | 圧縮トリガーの使用率閾値（0.0–1.0） |

動作:
1. 各 LLM 応答後、最後の API コールの（`input_tokens` + `cache_read_tokens` + `cache_write_tokens`）/ `context_limit` を計算。ストリーミング時は `ModelRequestCompletedEvent` の per-request 値を優先、非ストリーミング時は最後のアシスタントメッセージのメトリクスから取得。取得不可時は累積値にフォールバック
2. 閾値を超えている場合 `Auto-compacting session (context usage N%)...` を表示
3. `/compact` と同じ処理を自動実行

```
  Auto-compacting session (context usage 82%)...
  ✓ Compacted 8 runs (52 messages) into summary
```

### トークン上限エラー

コンテキストがモデルの上限を超えた場合、専用のエラーメッセージを表示:

```
  ✗ セッション履歴が長すぎます
  新しいセッションで再試行してください: hooty を再起動
```

## スラッシュコマンド

| コマンド | 説明 |
|---|---|
| `/add-dir [path]` | 追加作業ディレクトリを登録（引数省略時はディレクトリピッカー） |
| `/attach [path...]` | ファイルを次のメッセージに添付（引数省略時はファイルピッカー、ディレクトリ指定時はそのディレクトリをルートにピッカー起動、複数パス・クォート対応） |
| `/attach paste` | クリップボードから画像・ファイルを添付（Windows / WSL2 / macOS） |
| `/attach capture [target]` | スクリーンキャプチャで画像を添付（Windows / WSL2 / macOS）。対象: active / monitor / process・app 名 / title。`--delay`, `--repeat`, `--interval` オプション対応 |
| `/attach list` | 添付ファイルをインタラクティブに管理（Space トグル、d で削除） |
| `/attach clear` | 全添付をクリア |
| `/code` | コーディングモードに切り替え |
| `/compact` | セッション履歴を圧縮 |
| `/context` | モデル情報・コンテキストファイル・コンテキストウィンドウ使用状況を表示 |
| `/database` | DB 接続管理（`list` / `connect` / `disconnect` / `add` / `remove`） |
| `/diff` | セッション中のファイル変更を unified diff 形式で表示（`--snapshot` 有効時） |
| `/exit` | Hooty を終了（`/quit` のエイリアス） |
| `/fork` | 現在のセッションをフォーク（サマリーを引き継いだ新セッションを作成） |
| `/github` | GitHub ツールの on/off をトグル |
| `/help` | コマンド一覧とヘルプを表示 |
| `/list-dirs` | 現在の許可ディレクトリ一覧（primary + additional）を表示 |
| `/mcp` | MCP サーバー管理（`add` / `remove` / `list` / `reload`） |
| `/model` | インタラクティブプロファイルピッカーでモデル切り替え |
| `/new` | 新しいセッションを開始（現在のセッションは DB に保持） |
| `/plan` | プランモードに切り替え |
| `/quit` | Hooty を終了 |
| `/rescan` | PATH を再スキャンして利用可能コマンドを更新 |
| `/review` | ソースコードレビュー（インタラクティブ） |
| `/rewind` | ファイル変更の巻き戻し + 会話履歴リセット（`--snapshot` 有効時） |
| `/safe` | セーフモードを有効化 |
| `/skills` | インタラクティブピッカーでスキルの個別 ON/OFF を切替 |
| `/skills list` | スキル一覧を表示（名前・ソース・状態） |
| `/skills info <name>` | スキル詳細を表示（instructions プレビュー・scripts・references） |
| `/skills invoke <name> [args]` | スキルを手動呼び出し（instructions を LLM に送信） |
| `/<skill-name> [args]` | `user-invocable` スキルのトップレベルショートカット（既存コマンド不一致時にフォールバック） |
| `/skills add [--global] <path>` | 外部スキルディレクトリを追加 |
| `/skills remove [--global] <path>` | 外部スキルディレクトリを削除 |
| `/skills reload` | ディスクからスキルを再読み込み → Agent 再生成 |
| `/skills on` | スキル機能を全体で有効化 |
| `/skills off` | スキル機能を全体で無効化 |
| `/session` | 現在のセッション ID・プロジェクトパス・セッション統計を表示（累計あり時は `値 (累計値)` 形式） |
| `/session list` | 保存済みセッション一覧を表示（Forked・Project 列付き、ディレクトリ不一致に 🚫 マーカー） |
| `/session purge [days]` | 古いセッションを一括削除（デフォルト 90 日、最小 0 日） |
| `/session resume [id]` | 指定セッションを復元（ID 省略時はセッションピッカーを表示、ディレクトリ不一致時は警告） |
| `/memory` | 現在の記憶状況サマリーを表示 |
| `/memory list` | プロジェクト記憶の一覧を表示（`--global` でグローバル） |
| `/memory search <keyword>` | プロジェクト＋グローバルを横断キーワード検索 |
| `/memory edit` | インタラクティブ picker でプロジェクト記憶を削除 / global へ移動（`--global` でグローバル対象） |
| `/project purge` | 孤立プロジェクトディレクトリを検出・削除 |
| `/unsafe` | セーフモードを無効化 |
| `/websearch` | Web 検索ツール（DuckDuckGo）の on/off をトグル |

- Tab キーでスラッシュコマンドの補完が可能

## Bang Command（シェルエスケープ）

`!` プレフィックスでシェルコマンドを直接実行する。LLM エージェントを介さずにターミナルコマンドを実行したい場合に使用する。

### 入力 UI

`!` を入力するとシェル入力モードに切り替わる:

- **プロンプト**: `❯` → `!`（オレンジ）に変化。先頭の `!` は表示上省略される（`! ls` のように表示）
- **テキスト色**: 入力テキスト全体がオレンジに変化
- **ステータスバー**: `⚡ shell mode (Esc×2 to cancel)` に切り替わる
- **モード切替抑止**: shell mode 中は `Shift+Tab`（planning/coding 切替）を無効化
- **Esc×2**: バッファクリアで通常モードに復帰
- **Ctrl+D twice**: shell mode 中でも終了可能

### 動作例

```
! git status
On branch main
...

! ls -la
total 48
...
```

### エッジケース

| 入力 | 挙動 |
|------|------|
| `!git status` | シェルコマンドとして `git status` を実行 |
| `!`（空） | Usage ヒント表示 |
| `!!` | シェルに `!` を渡す |
| `!false` | 実行後 `exit code: 1` を表示 |

### 仕様

- `subprocess.run(cmd, shell=True, cwd=working_directory)` で実行
- stdout/stderr は親プロセスのターミナルに直接出力（パイプしない）— Ctrl+C で中断可能
- stdin は `/dev/null` に接続（prompt_toolkit との競合防止）
- タイムアウトなし（ユーザー操作なので Ctrl+C で十分）
- REPL の CWD には影響しない（`!cd /tmp` は実行されるが作業ディレクトリは変わらない）
- Windows: `cmd.exe` 経由で実行。Git for Windows の `usr/bin` が PATH に含まれるため Unix コマンドも利用可能。出力は `locale.getpreferredencoding()` でデコード（CP932 対応）
- Hooks 連携なし（エージェントライフサイクル外）
- 会話ログ記録なし（LLM 会話の一部ではない）

## キーボード操作

| キー | 動作 |
|---|---|
| `Enter` | 入力を送信（空入力は無視） |
| `Shift+Tab` | planning/coding モードをトグル |
| `Tab` | スラッシュコマンド補完 |
| `Ctrl+C` | 現在のストリーミング応答を即座にキャンセルし、次の入力待ちに戻る（POSIX: SIGINT → asyncio タスク即時キャンセル。サブエージェント実行中も停止シグナルを伝播）。**Windows 制約**: ツール実行中および完了後 5 秒間は `Ctrl+C` が抑制される（stale `CTRL_C_EVENT` による誤キャンセル防止のため）。この間はキャンセル不可。キャンセル成功時は `ProactorEventLoop` を新規作成して差し替え、モデルの `async_client` および agno グローバル `httpx.AsyncClient` をリセットする（古いループに紐付いた HTTP/2 コネクションが新ループ上でハングするのを防止）。`CancelledError` 発生時も同様にループを再作成する（Windows では SIGINT ハンドラが未設定のため `CancelledError` 経由でキャンセルが伝播するケースがある） |
| `Ctrl+D` | Hooty を終了（確認なし） |
| `Esc` × 2 | 入力内容をクリア |
| `\` + `Enter` | マルチライン入力（次の行に続ける） |
| `Ctrl+L` | 画面クリア |
| `Ctrl+X` `Ctrl+E` | 外部エディタで入力を編集（$EDITOR） |

## エラー表示

エラーは赤色テキストで表示する:

```
❯ /session resume invalid-id

  ✗ セッション 'invalid-id' が見つかりません
```

- `✗` アイコン + エラーメッセージ
- 赤色（`bold red`）で表示

### セットアップ未完了メッセージ

`config.yaml` と `.credentials` の両方が存在しない場合、初期セットアップが必要であることを案内して終了する:

```
  ⚠ No configuration found.
  Run hooty setup to configure credentials,
  or create ~/.hooty/config.yaml manually.
```

- 片方でも存在すれば通常どおり起動を続行する
- `validate_config()` の前にチェックされる

### クレデンシャル期限切れエラー

`.credentials` ファイルの有効期限が切れている場合、起動時にエラーメッセージを表示して終了する:

```
  ✗ Credentials expired on 2026-03-01 10:00
  Run 'hooty setup' to apply new credentials, or 'hooty setup clear' to remove.
```

## 終了

```
❯ /quit

  Goodbye! 🦉
```

- `/quit`、`/exit` コマンドまたは `Ctrl+D` で終了
- 終了メッセージを表示
