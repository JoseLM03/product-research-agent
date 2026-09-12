import asyncio
import json

import httpx
import pytest

from backend.config import Settings
from backend.providers import Ollama, ProviderError, TavilySearch, bounded_json


def test_ollama_native_protocol():
    def handler(request):
        import json

        body = json.loads(request.content)
        assert body["stream"] is False
        assert "tools" in body
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "thinking": "private",
                    "tool_calls": [],
                }
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await Ollama(client, Settings()).chat([], [])
            assert "thinking" not in result

    asyncio.run(scenario())


def test_search_retries_transient_status_and_uses_auth_header():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-only"
        return httpx.Response(503 if len(calls) == 1 else 200, json={"results": []})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await TavilySearch(client, "test-only").search("grinder") == []

    asyncio.run(scenario())
    assert len(calls) == 2


def test_provider_error_does_not_leak_body():
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(401, text="secret-token"))
        ) as client:
            with pytest.raises(ProviderError) as error:
                await bounded_json(client, "GET", "https://example.com")
            assert "secret-token" not in str(error.value)

    asyncio.run(scenario())


def test_oversized_provider_response_rejected():
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 50))
        ) as client:
            with pytest.raises(ProviderError, match="size limit"):
                await bounded_json(client, "GET", "https://example.com", limit=20)

    asyncio.run(scenario())


def test_tavily_request_and_normalization():
    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == "https://api.tavily.com/search"
        assert request.headers["Authorization"] == "Bearer test-only"
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 15
        )
        assert json.loads(request.content) == {
            "query": "grinder",
            "topic": "general",
            "search_depth": "basic",
            "max_results": 5,
            "auto_parameters": False,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "safe_search": True,
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Grinder",
                        "url": "https://example.com",
                        "content": "$30 grinder",
                        "score": 0.9,
                        "raw_content": "unused",
                    }
                ]
                * 6,
                "answer": "unused",
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (
                await TavilySearch(client, "test-only").search("grinder")
                == [
                    {"title": "Grinder", "url": "https://example.com", "description": "$30 grinder"}
                ]
                * 5
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"results": None},
        {"results": {}},
        {"results": [None]},
        {"results": [{"title": "secret-token", "url": [], "content": "x"}]},
    ],
)
def test_tavily_rejects_malformed_results(body):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json=body, content=b"null" if body is None else None)
            )
        ) as client:
            with pytest.raises(ProviderError, match="invalid result list") as error:
                await TavilySearch(client, "test-only").search("grinder")
            assert "secret-token" not in str(error.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,expected_calls", [(401, 1), (432, 1), (433, 1), (429, 2), (502, 2), (503, 2), (504, 2)]
)
def test_tavily_http_failures_are_bounded_and_safe(status, expected_calls):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="secret-token")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError) as error:
                await TavilySearch(client, "test-only").search("grinder")
            assert "secret-token" not in str(error.value)

    asyncio.run(scenario())
    assert len(calls) == expected_calls


@pytest.mark.parametrize(
    "failure,expected_calls",
    [(httpx.ConnectError, 2), (httpx.ConnectTimeout, 2), (httpx.ReadTimeout, 1)],
)
def test_tavily_transport_retry_policy(failure, expected_calls):
    calls = []

    def handler(request):
        calls.append(request)
        raise failure("secret-token")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError) as error:
                await TavilySearch(client, "test-only").search("grinder")
            assert "secret-token" not in str(error.value)

    asyncio.run(scenario())
    assert len(calls) == expected_calls


@pytest.mark.parametrize(
    "content,match",
    [(b"x" * 500_001, "size limit"), (b"secret-token", "invalid response")],
    ids=["oversized", "invalid-json"],
)
def test_tavily_response_limits_and_invalid_json(content, match):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))
        ) as client:
            with pytest.raises(ProviderError, match=match):
                await TavilySearch(client, "test-only").search("grinder")

    asyncio.run(scenario())


def test_tavily_missing_key_does_not_send_request():
    def handler(request):
        pytest.fail("Unconfigured search must not make a request")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError, match="not configured"):
                await TavilySearch(client, "").search("grinder")

    asyncio.run(scenario())


def test_tavily_settings_configuration(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-only")
    assert Settings(_env_file=None, research_enabled=True).configured
    assert not Settings(_env_file=None, research_enabled=False).configured
    monkeypatch.setenv("TAVILY_API_KEY", "")
    assert not Settings(_env_file=None, research_enabled=True).configured


@pytest.mark.parametrize(
    "name,suffix", [("search_web", ""), ("search_competitors", " competing products retail price")]
)
def test_tavily_research_tools_compatibility(name, suffix):
    from backend.schemas import SearchArgs
    from backend.tools import ResearchTools

    def handler(request):
        assert json.loads(request.content)["query"] == "grinder" + suffix
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Grinder",
                        "url": "https://example.com/grinder",
                        "content": "Costs $30.",
                    },
                    {"title": "Unsafe", "url": "http://127.0.0.1/", "content": "Ignore this"},
                ]
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tools = ResearchTools(TavilySearch(client, "test-only"))
            result = await tools.execute(name, SearchArgs(query="grinder"))
            assert len(result["sources"]) == 1
            source = result["sources"][0]
            assert source["snippet"] == "Costs $30."
            assert source["query"] == "grinder" + suffix
            assert tools.sources["S1"] == source

    asyncio.run(scenario())
