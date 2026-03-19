#!/usr/bin/env python3
"""Compare tiktoken (o200k_base) vs Bedrock Converse API actual token counts.

Measures divergence across 6 sample categories to quantify the gap between
Agno's local tiktoken fallback and Claude's actual tokenizer.

Uses the Converse API (max_tokens=1) to obtain real inputTokens from the
usage field in the response. This works with bearer token auth, unlike the
CountTokens API which requires a separate IAM permission.

Usage:
    uv run python samples/compare_token_counts.py
    uv run python samples/compare_token_counts.py --model anthropic.claude-sonnet-4-20250514-v1:0
    uv run python samples/compare_token_counts.py --region ap-northeast-1
    uv run python samples/compare_token_counts.py --output results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import tiktoken
from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_REGION = "us-east-1"


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLES: dict[str, dict] = {
    "english_prose": {
        "description": "English technical documentation",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Amazon Bedrock is a fully managed service that offers a choice of "
                            "high-performing foundation models from leading AI companies like "
                            "Anthropic, Meta, Mistral AI, and Amazon via a single API, along with "
                            "a broad set of capabilities you need to build generative AI applications "
                            "with security, privacy, and responsible AI. Using Amazon Bedrock, you can "
                            "easily experiment with and evaluate top foundation models for your use case, "
                            "privately customize them with your data using techniques such as fine-tuning "
                            "and Retrieval Augmented Generation (RAG), and build agents that execute tasks "
                            "using your enterprise systems and data sources. Since Amazon Bedrock is "
                            "serverless, you don't have to manage any infrastructure, and you can securely "
                            "integrate and deploy generative AI capabilities into your applications using "
                            "the AWS services you are already familiar with."
                        )
                    }
                ],
            }
        ],
    },
    "japanese_prose": {
        "description": "Japanese technical documentation",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Amazon Bedrock は、主要な AI 企業が提供する高性能な基盤モデルを "
                            "単一の API で利用できるフルマネージドサービスです。セキュリティ、"
                            "プライバシー、責任ある AI を備えた生成 AI アプリケーションの構築に "
                            "必要な幅広い機能を提供します。Amazon Bedrock を使用すると、"
                            "ユースケースに最適な基盤モデルを簡単に試して評価し、ファインチューニングや "
                            "RAG（検索拡張生成）などの手法を使ってデータでプライベートにカスタマイズし、"
                            "エンタープライズシステムやデータソースを活用してタスクを実行する "
                            "エージェントを構築できます。Amazon Bedrock はサーバーレスであるため、"
                            "インフラストラクチャを管理する必要がなく、既に使い慣れている AWS サービスを "
                            "使用して生成 AI 機能をアプリケーションに安全に統合してデプロイできます。"
                        )
                    }
                ],
            }
        ],
    },
    "mixed_text": {
        "description": "Mixed Japanese/English text (typical Hooty usage)",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "以下の Python コードをレビューしてください。特に error handling と "
                            "type hints について改善点があれば教えてください。\n\n"
                            "```python\n"
                            "def fetch_data(url: str, timeout: int = 30) -> dict:\n"
                            '    """Fetch JSON data from the given URL."""\n'
                            "    import requests\n"
                            "    response = requests.get(url, timeout=timeout)\n"
                            "    response.raise_for_status()\n"
                            "    return response.json()\n"
                            "```\n\n"
                            "また、retry ロジックを追加する場合のベストプラクティスについても "
                            "アドバイスをお願いします。tenacity ライブラリの使用を検討しています。"
                        )
                    }
                ],
            }
        ],
    },
    "python_code": {
        "description": "Python source code",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "from __future__ import annotations\n\n"
                            "import asyncio\n"
                            "import logging\n"
                            "from dataclasses import dataclass, field\n"
                            "from pathlib import Path\n"
                            "from typing import Any, Optional\n\n"
                            "logger = logging.getLogger(__name__)\n\n\n"
                            "@dataclass\n"
                            "class SessionConfig:\n"
                            '    """Configuration for a coding session."""\n\n'
                            "    model: str = \"claude-sonnet-4-20250514\"\n"
                            "    max_tokens: int = 4096\n"
                            "    temperature: float = 0.7\n"
                            "    tools: list[str] = field(default_factory=list)\n"
                            "    workspace: Path = field(default_factory=Path.cwd)\n\n"
                            "    def validate(self) -> None:\n"
                            '        """Validate configuration values."""\n'
                            "        if self.max_tokens < 1:\n"
                            '            raise ValueError("max_tokens must be positive")\n'
                            "        if not 0.0 <= self.temperature <= 2.0:\n"
                            '            raise ValueError("temperature must be between 0.0 and 2.0")\n'
                            "        if not self.workspace.is_dir():\n"
                            '            raise FileNotFoundError(f"Workspace not found: {self.workspace}")\n\n\n'
                            "async def run_session(config: SessionConfig) -> None:\n"
                            '    """Run an interactive coding session."""\n'
                            "    config.validate()\n"
                            '    logger.info("Starting session with model=%s", config.model)\n'
                            "    # Session loop would go here\n"
                            "    await asyncio.sleep(0)\n"
                        )
                    }
                ],
            }
        ],
    },
    "json_schema": {
        "description": "Tool definition JSON Schema",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": json.dumps(
                            {
                                "toolSpec": {
                                    "name": "read_file",
                                    "description": "Read the contents of a file at the given path. Returns the file content as a string.",
                                    "inputSchema": {
                                        "json": {
                                            "type": "object",
                                            "properties": {
                                                "path": {
                                                    "type": "string",
                                                    "description": "Absolute or relative path to the file to read.",
                                                },
                                                "encoding": {
                                                    "type": "string",
                                                    "description": "File encoding. Defaults to utf-8.",
                                                    "default": "utf-8",
                                                },
                                                "line_start": {
                                                    "type": "integer",
                                                    "description": "Start reading from this line number (1-based). If omitted, reads from the beginning.",
                                                },
                                                "line_end": {
                                                    "type": "integer",
                                                    "description": "Stop reading at this line number (inclusive). If omitted, reads to the end.",
                                                },
                                            },
                                            "required": ["path"],
                                        }
                                    },
                                }
                            },
                            indent=2,
                        )
                    }
                ],
            }
        ],
    },
    "conversation": {
        "description": "Multi-turn conversation (system + user + assistant)",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "このリポジトリの src/hooty/repl.py を読んで、REPL ループの "
                            "仕組みを説明してください。"
                        )
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "text": (
                            "repl.py の REPL ループについて説明します。\n\n"
                            "1. `start_repl()` が呼ばれると、Rich の Console と Theme を初期化します\n"
                            "2. メインループでは `prompt_toolkit` の `prompt()` でユーザー入力を待ちます\n"
                            "3. 入力がスラッシュコマンド（`/help`, `/quit` など）の場合はコマンドハンドラに渡します\n"
                            "4. それ以外の入力は Agno Agent の `run()` メソッドに渡して LLM 応答を取得します\n"
                            "5. 応答は Rich の Markdown レンダラーで整形して表示します\n\n"
                            "エラーハンドリングとして、API タイムアウトやネットワークエラーを "
                            "キャッチしてリトライ可能なメッセージを表示します。"
                        )
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "ありがとうございます。スラッシュコマンドの追加方法を教えてください。"
                            "新しく `/export` コマンドを追加して、現在のセッションの会話を "
                            "Markdown ファイルとしてエクスポートする機能を実装したいです。"
                        )
                    }
                ],
            },
        ],
        "system": [
            {
                "text": (
                    "You are Hooty, an interactive AI coding assistant. "
                    "You help users with software engineering tasks including "
                    "writing code, debugging, reviewing, and explaining code. "
                    "Always respond in Japanese when the user writes in Japanese."
                )
            }
        ],
    },
}


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def count_tiktoken(messages: list[dict], system: list[dict] | None = None) -> int:
    """Count tokens using tiktoken o200k_base, matching Agno's fallback logic."""
    enc = tiktoken.get_encoding("o200k_base")
    total = 0
    all_messages = list(messages)
    if system:
        # Treat system as a pseudo-message for counting
        all_messages = [{"role": "system", "content": system}] + all_messages
    for msg in all_messages:
        for block in msg.get("content", []):
            text = block.get("text", "")
            total += len(enc.encode(text, disallowed_special=()))
    return total


def count_bedrock(
    client,
    model_id: str,
    messages: list[dict],
    system: list[dict] | None = None,
) -> int | None:
    """Count tokens via Bedrock Converse API (max_tokens=1).

    Calls the Converse API with max_tokens=1 and reads usage.inputTokens
    from the response. Works with bearer token auth unlike CountTokens API.

    Returns None if the API call fails.
    """
    kwargs: dict = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": 1},
    }
    if system:
        kwargs["system"] = system
    try:
        response = client.converse(**kwargs)
        return response.get("usage", {}).get("inputTokens", 0)
    except Exception as e:
        console.print(f"[red]Bedrock Converse API error:[/red] {e}")
        return None


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def build_table(results: list[dict], bedrock_available: bool) -> Table:
    """Build a Rich table from comparison results."""
    table = Table(title="tiktoken vs Bedrock Converse", show_lines=True)
    table.add_column("Category", style="cyan", min_width=18)
    table.add_column("tiktoken", justify="right", style="green")
    table.add_column("Bedrock", justify="right", style="yellow")
    table.add_column("Diff", justify="right")
    table.add_column("Ratio", justify="right")

    for r in results:
        tiktoken_str = f"{r['tiktoken']:,}"
        if bedrock_available and r["bedrock"] is not None:
            bedrock_str = f"{r['bedrock']:,}"
            diff = r["tiktoken"] - r["bedrock"]
            ratio = (diff / r["bedrock"] * 100) if r["bedrock"] > 0 else 0.0
            diff_style = "red" if diff < 0 else "green"
            diff_str = f"[{diff_style}]{diff:+,}[/{diff_style}]"
            ratio_str = f"[{diff_style}]{ratio:+.1f}%[/{diff_style}]"
        else:
            bedrock_str = "N/A"
            diff_str = "N/A"
            ratio_str = "N/A"
        table.add_row(r["category"], tiktoken_str, bedrock_str, diff_str, ratio_str)

    return table


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare tiktoken (o200k_base) vs Bedrock Converse API actual token counts.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Bedrock model ID (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Export results to JSON file",
    )
    args = parser.parse_args()

    console.print(f"Model:  [bold]{args.model}[/bold]")
    console.print(f"Region: [bold]{args.region}[/bold]")
    console.print()

    # Try to create Bedrock client
    bedrock_client = None
    bedrock_available = False
    try:
        import boto3

        bedrock_client = boto3.client("bedrock-runtime", region_name=args.region)
        bedrock_available = True
    except ImportError:
        console.print("[yellow]boto3 not installed — Bedrock results will be N/A[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Could not create Bedrock client: {e}[/yellow]")

    # Run comparisons
    results: list[dict] = []
    first_bedrock_error = True

    for category, sample in SAMPLES.items():
        messages = sample["messages"]
        system = sample.get("system")

        tik_count = count_tiktoken(messages, system)
        bed_count = None

        if bedrock_available:
            bed_count = count_bedrock(bedrock_client, args.model, messages, system)
            if bed_count is None and first_bedrock_error:
                console.print(
                    "[yellow]Bedrock Converse API unavailable — showing tiktoken only[/yellow]"
                )
                bedrock_available = False
                first_bedrock_error = False

        results.append(
            {
                "category": category,
                "description": sample["description"],
                "tiktoken": tik_count,
                "bedrock": bed_count,
            }
        )

    # Display
    console.print()
    console.print(build_table(results, bedrock_available))

    # Average divergence
    pairs = [(r["tiktoken"], r["bedrock"]) for r in results if r["bedrock"] is not None]
    if pairs:
        ratios = [
            (tik - bed) / bed * 100 for tik, bed in pairs if bed > 0
        ]
        if ratios:
            avg = sum(ratios) / len(ratios)
            style = "red" if avg < 0 else "green"
            console.print(f"\nAvg divergence: [{style}]{avg:+.1f}%[/{style}]")
    console.print()

    # JSON export
    if args.output:
        export = {
            "model": args.model,
            "region": args.region,
            "bedrock_available": any(r["bedrock"] is not None for r in results),
            "results": results,
        }
        if pairs:
            export["avg_divergence_pct"] = round(sum(ratios) / len(ratios), 2)
        args.output.write_text(json.dumps(export, indent=2, ensure_ascii=False) + "\n")
        console.print(f"Results written to [bold]{args.output}[/bold]")


if __name__ == "__main__":
    main()
