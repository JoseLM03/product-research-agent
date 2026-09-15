"""Opt-in local-model evaluation against a hand-labelled adversarial alignment set."""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from backend.config import Settings
from backend.providers import Ollama
from backend.quality import AlignmentError, verify_items


async def evaluate():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "tests/fixtures/claim_alignment.json").read_text())
    items = [
        {
            "id": r["id"],
            "kind": r.get("kind", "fact"),
            "claim": r["claim"],
            "excerpt": r["excerpt"],
            "context": r.get("context", r["excerpt"]),
            **({"validation_step": r["validation_step"]} if "validation_step" in r else {}),
        }
        for r in rows
    ]
    start = time.perf_counter()
    rejected = set()
    settings = Settings()
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(settings.ollama_url.rstrip("/") + "/api/tags", timeout=10)
        response.raise_for_status()
        selected = next(
            (m for m in response.json()["models"] if m["name"] == settings.ollama_model), None
        )
        if not selected or selected.get("remote_host") or ":cloud" in settings.ollama_model:
            raise ValueError("This evaluation requires an installed local model.")
        for offset in range(0, len(items), 13):
            try:
                await verify_items(items[offset : offset + 13], Ollama(client, settings))
            except AlignmentError as error:
                rejected.update(path for path, _ in error.failures)
    outcomes = [{**r, "predicted": r["id"] not in rejected} for r in rows]
    result = {
        "elapsed_seconds": round(time.perf_counter() - start, 3),
        "false_accepts": sum(not x["supported"] and x["predicted"] for x in outcomes),
        "false_rejects": sum(x["supported"] and not x["predicted"] for x in outcomes),
        "cases": outcomes,
    }
    folder = root / "work" / "quality"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "adversarial-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}))
    if result["false_accepts"] or result["false_rejects"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(evaluate())
