"""Regression coverage for the measured native-tool/schema/context failures."""

import asyncio
import json
import logging

import httpx
import pytest

from backend.agent import citation_view, research
from backend.config import Settings
from backend.providers import Ollama, ProviderError
from backend.schemas import ReportDraft, ResearchInput, SearchArgs
from backend.tools import CitationError, ResearchTools, definitions
from tests.helpers import ModelFixture, SearchFixture, call, draft


def test_native_schema_has_concrete_nested_types_and_keeps_constraints():
    schema = definitions(["submit_report"])[0]["function"]["parameters"]
    assert "$ref" not in json.dumps(schema)
    assert "$defs" not in schema
    claim = schema["properties"]["overview"]
    assert claim["type"] == "object"
    assert claim["additionalProperties"] is False
    citation = claim["properties"]["citation"]
    assert citation["type"] == "object"
    assert citation["properties"]["excerpt"]["minimum"] == 1
    assert citation["properties"]["excerpt"]["maximum"] == 100
    assert "quote" not in citation["properties"]
    assert schema["properties"]["competitors"]["maxItems"] == 8
    assert schema["required"] == ReportDraft.model_json_schema()["required"]
    assert definitions([]) == []


def test_submit_report_still_allowed_after_research_budget_exhausted():
    class Model(ModelFixture):
        async def chat(self, messages, tools):
            if len(self.messages) == 2:
                assert [t["function"]["name"] for t in tools] == ["submit_report"]
            return await super().chat(messages, tools)

    async def scenario():
        async def emit(*args):
            pass

        model = Model(
            [
                call("search_web", {"query": "grinder"}),
                call("search_competitors", {"query": "grinder"}),
                call("submit_report", draft()),
            ]
        )
        report, status = await research(
            ResearchInput(idea="compact coffee grinder"),
            model,
            ResearchTools(SearchFixture()),
            2,
            emit,
        )
        assert status == "completed"
        assert report["sources"]

    asyncio.run(scenario())


def test_repair_keeps_evidence_without_replaying_failed_drafts():
    async def scenario():
        async def emit(*args):
            pass

        bad = draft(quote="NONEXISTENT QUOTE SENTINEL")
        model = ModelFixture(
            [
                call("search_web", {"query": "grinder"}),
                call("submit_report", bad),
                call("submit_report", draft()),
            ]
        )
        report, status = await research(
            ResearchInput(idea="compact coffee grinder"),
            model,
            ResearchTools(SearchFixture()),
            2,
            emit,
        )
        assert status == "partial"
        final_context = model.messages[-1]
        assert len(final_context) == len(model.messages[-2]) + 1
        assert "NONEXISTENT QUOTE SENTINEL" not in json.dumps(final_context)
        assert "Fixture Grinder A has replaceable burrs" in json.dumps(final_context)
        assert "Invalid excerpt reference for S1" in final_context[-1]["content"]
        assert report["sources"][0]["url"] == "https://example.com/grinder-a"
        assert len(report["limitations"]) >= 3

    asyncio.run(scenario())


def test_search_metadata_is_not_repeated_but_inspection_refreshes_exact_snippet():
    async def scenario():
        async def emit(*args):
            pass

        model = ModelFixture(
            [
                call("search_web", {"query": "grinder"}),
                call("search_web", {"query": "grinder"}),
                call("inspect_evidence", {"source_id": "S1"}),
                call("submit_report", draft()),
            ]
        )
        tools = ResearchTools(SearchFixture())
        await research(ResearchInput(idea="compact coffee grinder"), model, tools, 4, emit)
        messages = model.messages[-1]
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        assert results[0]["sources"][0] == citation_view(tools.sources["S1"])
        assert results[1]["sources"][0] == {"id": "S1", "already_in_context": True}
        assert results[2] == citation_view(tools.sources["S1"])
        assert tools.sources["S1"]["retrieved_at"]

    asyncio.run(scenario())


def test_spliced_or_repunctuated_quotes_are_still_rejected():
    tools = ResearchTools(SearchFixture())
    asyncio.run(tools.execute("search_web", SearchArgs(query="grinder")))
    for quote in (
        "Fixture Grinder A ... is advertised at $80.00.",
        "Fixture Grinder A has replaceable burrs!",
    ):
        with pytest.raises(CitationError, match=r"overview.citations\[0\]") as error:
            tools.validate_report(ReportDraft.model_validate(draft(quote=quote)))
        assert quote not in str(error.value)


def test_truncated_generation_fails_closed(caplog):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "done_reason": "length",
                        "message": call("submit_report", draft()),
                        "eval_count": 1500,
                    },
                )
            )
        ) as client:
            with pytest.raises(ProviderError, match="context or output limit"):
                await Ollama(client, Settings()).chat([], [])

    with caplog.at_level(logging.INFO, logger="fieldwork.providers"):
        asyncio.run(scenario())
    assert "length_limit=True" in caplog.text


def test_model_diagnostics_do_not_log_private_content(caplog):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "PRIVATE_RESPONSE",
                            "thinking": "PRIVATE_THINKING",
                        },
                        "prompt_eval_count": 123,
                        "eval_count": 45,
                    },
                )
            )
        ) as client:
            await Ollama(client, Settings()).chat(
                [{"role": "user", "content": "PRIVATE_INPUT"}], []
            )

    with caplog.at_level(logging.INFO, logger="fieldwork.providers"):
        asyncio.run(scenario())
    assert "message_bytes=" in caplog.text
    assert "model_finished elapsed_seconds=" in caplog.text
    assert "prompt_eval_count" in caplog.text
    assert "PRIVATE_" not in caplog.text


def test_timeout_diagnostics_distinguish_transport_from_validation(caplog):
    def fail(request):
        raise httpx.ReadTimeout("PRIVATE_PROVIDER_DETAIL")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(ProviderError):
                await Ollama(client, Settings()).chat([], [])

    with caplog.at_level(logging.WARNING, logger="fieldwork.providers"):
        asyncio.run(scenario())
    assert "kind=ReadTimeout" in caplog.text
    assert "PRIVATE_PROVIDER_DETAIL" not in caplog.text


def test_copyable_excerpts_are_exact_original_spans():
    snippet = "Curly “quotes” must stay unchanged. " * 60
    view = citation_view({"id": "S1", "title": "Evidence", "snippet": snippet})
    assert len(view["excerpts"]) > 1
    assert all(0 < len(x["text"]) <= 500 and x["text"] in snippet for x in view["excerpts"])
    assert "".join(x["text"] for x in view["excerpts"]).replace(" ", "") == snippet.replace(" ", "")


def test_reference_resolution_preserves_exact_quotes_and_rejects_unknown_ids():
    from backend.schemas import ReportSubmission

    tools = ResearchTools(SearchFixture())
    asyncio.run(tools.execute("search_web", SearchArgs(query="grinder")))
    submitted = call("submit_report", draft())["tool_calls"][0]["function"]["arguments"]
    report = tools.validate_report(ReportSubmission.model_validate(submitted))
    quote = report["overview"]["citations"][0]["quote"]
    assert quote == tools.sources["S1"]["snippet"]
    assert "excerpt" not in report["overview"]["citations"][0]
    submitted["overview"]["citation"]["source_id"] = "S9"
    with pytest.raises(CitationError):
        tools.validate_report(ReportSubmission.model_validate(submitted))
