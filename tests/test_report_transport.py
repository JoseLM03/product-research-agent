"""Final reports never traverse Ollama native tool-call serialization."""

import asyncio
import json

import httpx
import pytest

from backend.agent import AgentError, research
from backend.config import Settings
from backend.providers import Ollama, ProviderError
from backend.schemas import ReportSubmission, ResearchInput
from backend.tools import ResearchTools, definitions, tool_schema
from tests.helpers import ModelFixture, SearchFixture, call, draft


def test_report_schema_is_not_exposed_as_native_tool():
    schemas = definitions()
    assert "submit_report" not in [t["function"]["name"] for t in schemas]
    finish = next(t for t in schemas if t["function"]["name"] == "finish_research")
    assert finish["function"]["parameters"]["properties"] == {}


@pytest.mark.parametrize(
    "content,tool_calls,stop,valid",
    [
        ('{"overview": {}}', [], "stop", True),
        ("<function=submit_report></parameter>", [], "stop", False),
        ("```json\n{}\n```", [], "stop", False),
        ("{} trailing", [], "stop", False),
        ("[]", [], "stop", False),
        ('{"overview":', [], "stop", False),
        ("{}", [], "length", False),
        ("{}", [{"function": {"name": "submit_report", "arguments": {}}}], "stop", False),
    ],
)
def test_structured_protocol_is_strict_and_never_retries(content, tool_calls, stop, valid):
    calls = []
    schema = tool_schema(ReportSubmission)

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert "tools" not in body
        assert body["format"] == schema
        assert body["think"] is False
        return httpx.Response(
            200,
            json={
                "done_reason": stop,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                },
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = Ollama(client, Settings())
            if valid:
                assert await model.chat([], [], schema=schema) == json.loads(content)
            else:
                with pytest.raises(ProviderError):
                    await model.chat([], [], schema=schema)

    asyncio.run(scenario())
    assert len(calls) == 1


def test_structured_repair_preserves_ledger_and_rejected_draft():
    bad = call("submit_report", draft())
    bad["tool_calls"][0]["function"]["arguments"]["overview"]["citation"]["source_id"] = "S9"

    class Model(ModelFixture):
        structured_calls = 0

        async def chat(self, messages, tools, *, schema=None):
            if schema is not None:
                self.structured_calls += 1
                assert tools == []
                assert all(m["role"] in {"system", "user"} for m in messages)
                ledger = json.loads(messages[1]["content"])
                assert {s["id"] for s in ledger["sources"]} == {"S1", "S2"}
                if self.structured_calls == 2:
                    assert schema["required"] == ["overview"]
                    assert "rejected_draft" in messages[-1]["content"]
                    assert "S9" in messages[-1]["content"]
            return await super().chat(messages, tools, schema=schema)

    model = Model([call("search_web", {"query": "grinder"}), bad, call("submit_report", draft())])

    async def emit(*args):
        pass

    report, status = asyncio.run(
        research(
            ResearchInput(idea="coffee grinder"), model, ResearchTools(SearchFixture()), 10, emit
        )
    )
    assert model.structured_calls == 2
    assert status == "partial"
    assert report["overview"]["citations"][0]["source_id"] == "S1"


def test_repair_freezes_every_unaffected_top_level_section():
    rejected = draft()
    rejected["risks"] = [
        {
            "text": "Test whether sales grow 50% next quarter.",
            "validation_step": "Run a buyer study.",
        }
    ]
    changed = draft()
    changed["overview"]["citations"][0]["source_id"] = "S2"
    changed["assessment"] = "worth_further_research"
    changed["risks"] = [
        {
            "text": "Test whether workers prefer the cordless prototype.",
            "validation_step": "Run a trial with 20 workers.",
        }
    ]

    class Model(ModelFixture):
        async def chat(self, messages, tools, *, schema=None):
            if schema is not None and schema.get("required") == ["risks"]:
                assert set(schema["properties"]) == {"risks"}
                # Simulate a provider that ignores its constrained schema. The
                # server must still merge only the rejected top-level section.
                return changed
            return await super().chat(messages, tools, schema=schema)

    model = Model(
        [
            call("search_web", {"query": "grinder"}),
            call("submit_report", rejected),
        ]
    )

    async def emit(*args):
        pass

    report, status = asyncio.run(
        research(
            ResearchInput(idea="coffee grinder"),
            model,
            ResearchTools(SearchFixture()),
            10,
            emit,
        )
    )
    assert status == "partial"
    assert report["assessment"] == rejected["assessment"]
    assert report["overview"]["citations"][0]["source_id"] == "S1"
    assert report["risks"] == changed["risks"]


def test_native_report_payload_is_rejected_instead_of_salvaged():
    class NativeModel:
        async def chat(self, *args, **kwargs):
            return call("submit_report", draft())

    async def emit(*args):
        pass

    with pytest.raises(AgentError, match="Native report"):
        asyncio.run(
            research(
                ResearchInput(idea="coffee grinder"),
                NativeModel(),
                ResearchTools(SearchFixture()),
                10,
                emit,
            )
        )


@pytest.mark.parametrize("raw,mixed", [({"overview": {}}, False), ({}, True)])
def test_finish_signal_cannot_smuggle_report_or_skip_batched_actions(raw, mixed):
    class Model:
        async def chat(self, *args, **kwargs):
            message = call("finish_research", raw)
            if mixed:
                message["tool_calls"] += call("search_web", {"query": "grinder"})["tool_calls"]
            return message

    async def emit(*args):
        pass

    with pytest.raises(AgentError, match="standalone"):
        asyncio.run(
            research(
                ResearchInput(idea="coffee grinder"),
                Model(),
                ResearchTools(SearchFixture()),
                10,
                emit,
            )
        )


def test_finish_on_last_planning_turn_still_gets_one_repair():
    bad = call("submit_report", draft())
    bad["tool_calls"][0]["function"]["arguments"]["overview"]["citation"]["source_id"] = "S9"
    model = ModelFixture(
        [
            *[call("search_web", {"query": "grinder"}) for _ in range(7)],
            bad,
            call("submit_report", draft()),
        ]
    )

    async def emit(*args):
        pass

    report, status = asyncio.run(
        research(
            ResearchInput(idea="coffee grinder"), model, ResearchTools(SearchFixture()), 10, emit
        )
    )
    assert status == "partial"
    assert not model.responses
    assert report["sources"]
