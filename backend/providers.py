import asyncio
import json
import logging
import time

import httpx

log = logging.getLogger("fieldwork.providers")


class ProviderError(Exception):
    """Safe public error; never propagate provider bodies or request headers."""


async def bounded_json(client, method, url, *, limit=500_000, retry=False, **kwargs):
    attempts = 2 if retry else 1
    for attempt in range(attempts):
        try:
            async with client.stream(method, url, **kwargs) as response:
                if response.status_code in (429, 502, 503, 504) and attempt + 1 < attempts:
                    await asyncio.sleep(0.5)
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ProviderError("Provider response exceeded the size limit.")
                return json.loads(data)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "provider_failure kind=%s status=%s attempt=%s",
                type(exc).__name__,
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None,
                attempt + 1,
            )
            # No retry for model POSTs: an ambiguous timeout may already have consumed compute.
            if (
                retry
                and isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                and attempt + 1 < attempts
            ):
                await asyncio.sleep(0.5)
                continue
            raise ProviderError(
                "Provider unavailable, timed out, or returned an invalid response."
            ) from None
    raise ProviderError("Provider is temporarily unavailable.")


class Ollama:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    async def chat(self, messages, tools):
        started = time.perf_counter()
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        log.info(
            "model_request messages=%s message_bytes=%s tool_results=%s tool_result_bytes=%s schemas=%s",
            len(messages),
            len(json.dumps(messages).encode()),
            len(tool_messages),
            [len(m.get("content", "").encode()) for m in tool_messages],
            {t["function"]["name"]: len(json.dumps(t).encode()) for t in tools},
        )
        try:
            return await self._chat(messages, tools)
        finally:
            log.info("model_finished elapsed_seconds=%.3f", time.perf_counter() - started)

    async def _chat(self, messages, tools):
        body = await bounded_json(
            self.client,
            "POST",
            self.settings.ollama_url.rstrip("/") + "/api/chat",
            json={
                "model": self.settings.ollama_model,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "think": False,
                "options": {"temperature": 0, "num_predict": 1500, "num_ctx": 8192},
            },
            timeout=90,
        )
        message = body.get("message") if isinstance(body, dict) else None
        if isinstance(body, dict):
            log.info(
                "model_metrics %s",
                json.dumps(
                    {
                        k: body[k]
                        for k in (
                            "total_duration",
                            "load_duration",
                            "prompt_eval_count",
                            "prompt_eval_duration",
                            "eval_count",
                            "eval_duration",
                        )
                        if isinstance(body.get(k), (int, float))
                    }
                ),
            )
            log.info("model_stop length_limit=%s", body.get("done_reason") == "length")
            if body.get("done_reason") == "length":
                raise ProviderError(
                    "Model reached its context or output limit before completing a response."
                )
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ProviderError("Model returned an invalid message.")
        calls = message.get("tool_calls", [])
        if not isinstance(calls, list) or len(calls) > 10:
            raise ProviderError("Model returned an invalid tool-call batch.")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                raise ProviderError("Model returned a malformed tool call.")
        # Deliberately do not persist or expose internal thinking.
        return {
            "role": "assistant",
            "content": str(message.get("content", ""))[:16000],
            "tool_calls": calls,
        }


class TavilySearch:
    def __init__(self, client, key):
        self.client, self.key = client, key

    async def search(self, query):
        if not self.key:
            raise ProviderError("Search provider is not configured.")
        body = await bounded_json(
            self.client,
            "POST",
            "https://api.tavily.com/search",
            retry=True,
            json={
                "query": query,
                "topic": "general",
                "search_depth": "basic",
                "max_results": 5,
                "auto_parameters": False,
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
                "safe_search": True,
            },
            headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"},
            timeout=15,
        )
        try:
            results = body["results"]
            if not isinstance(results, list):
                raise TypeError()
            normalized = []
            for row in results[:5]:
                if not isinstance(row, dict) or any(
                    not isinstance(row.get(field), str) for field in ("title", "url", "content")
                ):
                    raise TypeError()
                normalized.append(
                    {"title": row["title"], "url": row["url"], "description": row["content"]}
                )
            return normalized
        except (TypeError, KeyError, AttributeError):
            raise ProviderError("Search provider returned an invalid result list.") from None
