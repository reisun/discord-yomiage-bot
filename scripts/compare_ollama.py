"""Compare local Ollama classifiers using synthetic Japanese messages."""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from unittest.mock import patch

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.llm.ollama import OllamaClient


def target(value):
    mode, separator, model = value.partition("=")
    if not separator or mode not in {"generate", "systemone"} or not model:
        raise argparse.ArgumentTypeError("target must be generate=MODEL or systemone=MODEL")
    return mode, model


def summarize(rows):
    latencies = sorted(row["elapsed_seconds"] for row in rows)
    count = len(rows)
    return {
        "count": count,
        "agreement_rate": sum(row["agrees"] for row in rows) / count if count else None,
        "valid_rate": sum(row["selected"] is not None for row in rows) / count if count else None,
        "within_budget_rate": sum(row["selected"] is not None and row["elapsed_seconds"] < 2 for row in rows) / count if count else None,
        "latency_seconds": {
            "p50": statistics.median(latencies) if count else None,
            "p95": latencies[max(0, math.ceil(count * 0.95) - 1)] if count else None,
            "max": max(latencies) if count else None,
        },
    }


async def metadata(host):
    result = {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        for name, path in (("version", "/api/version"), ("tags", "/api/tags"), ("ps", "/api/ps")):
            try:
                async with session.get(host.rstrip("/") + path) as response:
                    response.raise_for_status()
                    result[name] = await response.json()
            except Exception as error:
                result[name] = {"error_type": type(error).__name__}
    return result


async def run(args):
    fixture_bytes = args.fixture.read_bytes()
    examples = json.loads(fixture_bytes)["examples"]
    schedule = []
    rng = random.Random(args.seed)
    for repeat in range(args.repeats):
        indices = list(range(len(examples)))
        rng.shuffle(indices)
        for index in indices:
            example = examples[index]
            choices = list(example["choices"])
            rng.shuffle(choices)
            schedule.append((repeat, example, choices))
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "seed": args.seed,
        "repeats": args.repeats,
        "host": args.host,
        "metadata_before": await metadata(args.host),
        "targets": [],
    }
    for mode, model in args.target:
        # Choices are already shuffled in the shared schedule. Avoid a second shuffle.
        random.seed(args.seed)
        client = OllamaClient(host=args.host, model=model, api_mode=mode)
        rows = []
        try:
            started = time.perf_counter()
            await client.warmup()
            warmup_seconds = time.perf_counter() - started
            for repeat, example, choices in schedule:
                started = time.perf_counter()
                with patch("bot.llm.ollama.random.shuffle", lambda names: None):
                    selected = await client.infer_style(example["text"], choices)
                elapsed = time.perf_counter() - started
                rows.append({
                    "id": example["id"], "group": example["group"],
                    "label": example["label"], "repeat": repeat + 1,
                    "text": example["text"], "choices": choices,
                    "acceptable": example["acceptable"], "selected": selected,
                    "agrees": selected in example["acceptable"],
                    "elapsed_seconds": elapsed,
                })
        finally:
            await client.close()
        result = {
            "model": model, "api_mode": mode, "warmup_seconds": warmup_seconds,
            "summary": summarize(rows),
            "groups": {group: summarize([row for row in rows if row["group"] == group])
                       for group in sorted({row["group"] for row in rows})},
            "labels": {group: {
                label: summarize([row for row in rows if row["group"] == group and row["label"] == label])
                for label in sorted({row["label"] for row in rows if row["group"] == group})
            } for group in sorted({row["group"] for row in rows})},
            "metadata_after": await metadata(args.host), "rows": rows,
        }
        report["targets"].append(result)
        summary = result["summary"]
        print(f"{mode}={model}: agreement={summary['agreement_rate']:.1%}, "
              f"valid={summary['valid_rate']:.1%}, p95={summary['latency_seconds']['p95']:.3f}s")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434"))
    parser.add_argument("--target", action="append", type=target)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[1] / "tests/fixtures/voice_styles.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.target = args.target or [("generate", "qwen3.5:2b")]
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
