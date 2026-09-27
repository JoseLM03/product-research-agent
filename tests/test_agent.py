import asyncio

import pytest

from backend.agent import AgentError, research
from backend.providers import ProviderError
from backend.schemas import ResearchInput
from backend.tools import ResearchTools

from .helpers import ModelFixture, SearchFixture, call, draft


def run(model, search=None, limit=10):
    events = []

    async def emit(*args):
        events.append(args)

    result = asyncio.run(
        research(
            ResearchInput(idea="compact coffee grinder"),
            model,
            ResearchTools(search or SearchFixture()),
            limit,
            emit,
        )
    )
    return result, events


def test_native_tool_loop_observes_results_then_submits():
    model = ModelFixture()
    (report, status), events = run(model)
    assert status == "completed"
    assert len(report["sources"]) == 2
    assert any(m["role"] == "tool" and "Fixture Grinder" in m["content"] for m in model.messages[1])
    assert [e[0] for e in events if e[1] == "completed"] == [
        "search_competitors",
        "calculate_margin",
        "submit_report",
    ]


def test_invalid_citation_can_be_repaired_without_marking_report_partial():
    bad = call("submit_report", draft())
    bad["tool_calls"][0]["function"]["arguments"]["overview"]["citation"]["source_id"] = "S9"
    model = ModelFixture(
        [
            call("search_web", {"query": "grinder"}),
            bad,
            call("submit_report", draft()),
        ]
    )
    (report, status), events = run(model)
    assert status == "completed"
    assert not any("steps failed" in x for x in report["limitations"])
    assert any(event[:2] == ("submit_report", "failed") for event in events)
    assert any(event[:2] == ("submit_report", "completed") for event in events)


def test_tool_budget_stops_infinite_search():
    # Once the research budget is spent, no further search can execute.
    (report, status), events = run(
        ModelFixture(
            [
                call("search_web", {"query": "grinder"}),
                call("search_web", {"query": "grinder"}),
                call("submit_report", draft()),
            ]
        ),
        limit=2,
    )
    assert status == "completed"
    assert sum(e[0] == "search_web" and e[1] == "completed" for e in events) == 2


def test_unknown_tool_is_not_executed():
    with pytest.raises(AgentError, match="unsupported"):
        run(ModelFixture([call("run_shell", {"command": "anything"})]))


def test_prose_never_counts_as_a_report():
    with pytest.raises(AgentError, match="planning limit"):
        run(ModelFixture([{"role": "assistant", "content": "Looks profitable!"}] * 8))


def test_provider_failure_is_observed_and_disclosed():
    class Intermittent:
        count = 0

        async def search(self, query):
            self.count += 1
            if self.count == 1:
                raise ProviderError("Search unavailable.")
            return await SearchFixture().search(query)

    (report, status), _ = run(
        ModelFixture(
            [
                call("search_web", {"query": "grinder"}),
                call("search_competitors", {"query": "grinder"}),
                call("submit_report", draft()),
            ]
        ),
        Intermittent(),
    )
    assert status == "partial"
    assert any("steps failed" in x for x in report["limitations"])


def test_insufficient_evidence_assessment_remains_partial():
    insufficient = draft()
    insufficient["assessment"] = "insufficient_evidence"
    (report, status), _ = run(
        ModelFixture(
            [
                call("search_web", {"query": "grinder"}),
                call("submit_report", insufficient),
            ]
        )
    )
    assert status == "partial"
    assert report["assessment"] == "insufficient_evidence"
