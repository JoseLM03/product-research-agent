import asyncio
import httpx
import pytest
from backend.config import Settings
from backend.providers import Ollama, BraveSearch, ProviderError, bounded_json


def test_ollama_native_protocol():
    def handler(request):
        import json
        body=json.loads(request.content)
        assert body['stream'] is False
        assert 'tools' in body
        return httpx.Response(200,json={'message':{'role':'assistant','content':'','thinking':'private','tool_calls':[]}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await Ollama(client,Settings()).chat([],[])
            assert 'thinking' not in result
    asyncio.run(scenario())


def test_search_retries_transient_status_and_uses_auth_header():
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.headers['X-Subscription-Token']=='test-only'
        return httpx.Response(503 if len(calls)==1 else 200,json={'web':{'results':[]}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await BraveSearch(client,'test-only').search('grinder')==[]
    asyncio.run(scenario())
    assert len(calls)==2


def test_provider_error_does_not_leak_body():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(401,text='secret-token'))) as client:
            with pytest.raises(ProviderError) as error:
                await bounded_json(client,'GET','https://example.com')
            assert 'secret-token' not in str(error.value)
    asyncio.run(scenario())


def test_oversized_provider_response_rejected():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'x'*50))) as client:
            with pytest.raises(ProviderError,match='size limit'):
                await bounded_json(client,'GET','https://example.com',limit=20)
    asyncio.run(scenario())
