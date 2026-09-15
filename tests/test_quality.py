"""Hand-labelled adversarial cases and fail-closed quality-gate regressions."""

import asyncio
import json
import time
from pathlib import Path

import pytest

from backend.agent import AgentError, coalesce_report, research
from backend.db import Job
from backend.quality import AlignmentError, AlignmentUnavailable, review_items, verify_items
from backend.schemas import ResearchInput
from backend.tools import ResearchTools, citation_view
from backend.worker import run_job
from tests.helpers import ModelFixture, SearchFixture, call, draft

CASES = json.loads((Path(__file__).parent / "fixtures" / "claim_alignment.json").read_text())


def test_disjoint_complete_sections_are_coalesced_without_changing_values():
    message = call("submit_report", draft())
    original = message["tool_calls"][0]["function"]["arguments"]
    message["tool_calls"] = [
        {"function": {"name": "submit_report", "arguments": {key: value}}}
        for key, value in original.items()
    ]
    assert coalesce_report(message)["tool_calls"][0]["function"]["arguments"] == original


@pytest.mark.parametrize("kind", ["overlap", "incomplete", "mixed"])
def test_ambiguous_report_batches_are_not_merged(kind):
    message = call("submit_report", draft())
    first = message["tool_calls"][0]
    if kind == "overlap":
        message["tool_calls"].append(first)
    elif kind == "incomplete":
        first["function"]["arguments"] = {"overview": {}}
        message["tool_calls"].append(
            {"function": {"name": "submit_report", "arguments": {"rationale": {}}}}
        )
    else:
        message["tool_calls"].append(
            {"function": {"name": "search_web", "arguments": {"query": "example"}}}
        )
    assert coalesce_report(message) is message


def test_unattributed_rankings_fail_even_if_model_would_accept():
    report = draft()
    report["competitors"][0]["text"] = "Porlex Mini II - Best for Travel"
    with pytest.raises(AlignmentError, match="attribution"):
        review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})


class VerdictModel:
    def __init__(self, results):
        self.results = results
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        return call("alignment_verdicts", {"results": self.results})


def item(row):
    return {
        "id": row["id"],
        "kind": row.get("kind", "fact"),
        "claim": row["claim"],
        "excerpt": row["excerpt"],
        "context": row.get("context", row["excerpt"]),
        **({"validation_step": row["validation_step"]} if "validation_step" in row else {}),
    }


@pytest.mark.parametrize("row", CASES, ids=lambda x: x["id"])
def test_adversarial_oracle_verdict_is_enforced(row):
    model = VerdictModel(
        [
            {
                "id": row["id"],
                "supported": row["supported"],
                "reason": "ok" if row["supported"] else "partial_support",
            }
        ]
    )
    if row["supported"]:
        asyncio.run(verify_items([item(row)], model))
    else:
        with pytest.raises(AlignmentError):
            asyncio.run(verify_items([item(row)], model))
    assert model.calls == 1


@pytest.mark.parametrize(
    "results",
    [
        [],
        [{"id": "wrong", "supported": True, "reason": "ok"}],
        [{"id": "x", "supported": "true", "reason": "ok"}],
        [{"id": "x", "supported": True, "reason": "ok"}] * 2,
        [{"id": "x", "supported": True, "reason": "partial_support"}],
        [{"id": "x", "supported": True, "reason": "ok", "extra": "private"}],
        [{"id": "x", "supported": False, "reason": "private model prose"}],
    ],
)
def test_incomplete_or_malformed_verdicts_never_pass(results):
    with pytest.raises(AlignmentUnavailable):
        asyncio.run(
            verify_items(
                [{"id": "x", "kind": "fact", "claim": "Example", "excerpt": "Example"}],
                VerdictModel(results),
            )
        )


def test_verification_timeout_fails_closed(monkeypatch):
    import backend.quality as quality

    monkeypatch.setattr(quality, "VERIFY_SECONDS", 0.001)

    class Slow:
        async def chat(self, *args):
            await asyncio.sleep(1)

    with pytest.raises(AlignmentUnavailable):
        asyncio.run(verify_items([{"id": "x"}], Slow()))


def test_obvious_numbers_and_compound_claims_rejected_before_model():
    report = draft()
    report["overview"]["text"] = "The grinder costs $199. It is the bestselling model."
    sources = {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}}
    with pytest.raises(AlignmentError) as error:
        review_items(report, sources)
    assert any("number" in reason for _, reason in error.value.failures)
    assert any("atomic" in reason for _, reason in error.value.failures)


def test_hypotheses_cannot_launder_a_numerical_forecast():
    report = draft()
    report["opportunities"] = [
        {
            "text": "Test whether sales grow 50% because demand is proven.",
            "validation_step": "Survey potential buyers.",
        }
    ]
    with pytest.raises(AlignmentError):
        review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})


def test_reference_must_be_one_excerpt_not_a_bag_of_partially_supporting_citations():
    report = draft()
    report["overview"]["citations"] *= 2
    with pytest.raises(AlignmentError):
        review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})


def test_context_preserves_retraction_but_is_not_extra_support():
    report = draft(quote="We previously called it leakproof.")
    report["overview"]["text"] = "The source reports leak resistance."
    source = "We previously called it leakproof. That claim was withdrawn after testing."
    items = review_items(report, {"S1": {"snippet": source}})
    assert "withdrawn" in items[0]["context"]
    assert items[0]["excerpt"] == "We previously called it leakproof."


def test_long_or_gapped_sentences_are_not_chopped_into_misleading_excerpts():
    source = {
        "id": "S1",
        "title": "Test",
        "snippet": "Long " * 120
        + "sentence. A full supported sentence remains. Missing [...] qualification.",
    }
    excerpts = citation_view(source)["excerpts"]
    assert [x["text"] for x in excerpts] == ["A full supported sentence remains."]


class RejectingModel(ModelFixture):
    def __init__(self):
        super().__init__(
            [
                call("search_web", {"query": "grinder"}),
                call("submit_report", draft()),
                call("submit_report", draft()),
            ]
        )
        self.reviews = 0

    async def chat(self, messages, tools):
        if tools[0]["function"]["name"] == "alignment_verdicts":
            self.reviews += 1
            items = json.loads(messages[-1]["content"])
            return call(
                "alignment_verdicts",
                {
                    "results": [
                        {"id": x["id"], "supported": False, "reason": "unsupported_inference"}
                        for x in items
                    ]
                },
            )
        return await super().chat(messages, tools)


def test_alignment_repair_is_bounded_and_does_not_spend_research_budget():
    model = RejectingModel()

    async def scenario():
        async def emit(*args):
            pass

        await research(
            ResearchInput(idea="compact grinder"), model, ResearchTools(SearchFixture()), 2, emit
        )

    with pytest.raises(AgentError, match="one repair"):
        asyncio.run(scenario())
    assert model.reviews == 2


def test_worker_never_persists_a_report_rejected_by_alignment(client, app):
    job_id = client.post("/api/research", json={"idea": "compact grinder"}).json()["id"]
    with app.state.sessions.begin() as db:
        job = db.get(Job, job_id)
        job.status = "running"
        job.started_at = time.time()
    asyncio.run(
        run_job(job_id, app.state.sessions, app.state.settings, RejectingModel(), SearchFixture())
    )
    result = client.get("/api/research/" + job_id).json()
    assert result["status"] == "failed"
    assert result["report"] is None
    assert "alignment" in result["error"]
