import asyncio
import json

import httpx


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
                "options": {"temperature": 0, "num_predict": 2500, "num_ctx": 16384},
            },
            timeout=90,
        )
        message = body.get("message") if isinstance(body, dict) else None
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


class BraveSearch:
    def __init__(self, client, key):
        self.client, self.key = client, key

    async def search(self, query):
        if not self.key:
            raise ProviderError("Search provider is not configured.")
        body = await bounded_json(
            self.client,
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            retry=True,
            params={"q": query, "count": 5, "safesearch": "strict", "text_decorations": "false"},
            headers={"X-Subscription-Token": self.key, "Accept": "application/json"},
            timeout=15,
        )
        try:
            results = body.get("web", {}).get("results", [])
            if not isinstance(results, list):
                raise TypeError()
            return results[:5]
        except (TypeError, AttributeError):
            raise ProviderError("Search provider returned an invalid result list.") from None
