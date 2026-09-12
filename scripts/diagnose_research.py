"""Opt-in real API -> SQL worker -> Ollama/Tavily -> persisted report diagnosis.

Run with --live to authorize real search credits and local inference.
Stores private run artifacts under the ignored project work/diagnostics directory.
"""

import argparse
import json
import logging
import time
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.providers import Ollama


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--model")
    args = parser.parse_args()
    configured = Settings()
    model = args.model or configured.ollama_model
    with httpx.Client(timeout=10, trust_env=False) as http:
        models = http.get(configured.ollama_url.rstrip("/") + "/api/tags")
        models.raise_for_status()
        selected = next((m for m in models.json()["models"] if m["name"] == model), None)
        if not selected or selected.get("remote_host") or ":cloud" in model:
            parser.error(
                "Choose an installed local model; cloud inference is not supported by this diagnostic."
            )
    if not configured.tavily_api_key:
        parser.error("TAVILY_API_KEY is required.")
    folder = Path(__file__).resolve().parents[1] / "work" / "diagnostics" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(folder / "trace.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("fieldwork").addHandler(
        logging.FileHandler(folder / "trace.log", encoding="utf-8")
    )
    settings = Settings(
        environment="test",
        database_url="sqlite:///" + (folder / "run.db").as_posix(),
        app_origin="http://testserver",
        ollama_model=model,
        research_enabled=True,
        worker_enabled=True,
    )

    class RecordingModel:
        turn = 0

        async def chat(self, messages, tools):
            self.turn += 1
            async with httpx.AsyncClient(trust_env=False) as http:
                response = await Ollama(http, settings).chat(messages, tools)
            (folder / f"turn-{self.turn}.json").write_text(
                json.dumps({"messages": messages, "tools": tools, "response": response}),
                encoding="utf-8",
            )
            return response

    started = time.perf_counter()
    with TestClient(create_app(settings, model=RecordingModel())) as client:
        client.headers["origin"] = settings.app_origin
        client.get("/api/session").raise_for_status()
        response = client.post(
            "/api/research", json={"idea": "Reusable water bottle for college students"}
        )
        response.raise_for_status()
        job_id = response.json()["id"]
        while True:
            response = client.get("/api/research/" + job_id)
            response.raise_for_status()
            result = response.json()
            if result["status"] not in ("queued", "running"):
                break
            if time.perf_counter() - started > settings.job_timeout_seconds + 15:
                raise TimeoutError("Diagnostic deadline exceeded")
            time.sleep(0.25)
        elapsed = round(time.perf_counter() - started, 3)
        (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        summary = {
            "model": model,
            "status": result["status"],
            "elapsed_seconds": elapsed,
            "error": result.get("error"),
            "source_count": len((result.get("report") or {}).get("sources", [])),
            "artifact_directory": str(folder),
        }
        (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)
        if result["status"] not in ("completed", "partial"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
