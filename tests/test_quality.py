"""Hand-labelled adversarial cases and fail-closed quality-gate regressions."""

import asyncio
import json
import time
from pathlib import Path

import pytest

from backend.agent import AgentError, research
from backend.db import Job
from backend.quality import (
    AlignmentError,
    AlignmentUnavailable,
    factual_guard_failures,
    review_items,
    verify_items,
)
from backend.schemas import ResearchInput
from backend.tools import ResearchTools, citation_view
from backend.worker import run_job
from tests.helpers import FACT_QUOTE, ModelFixture, SearchFixture, call, draft

CASES = json.loads((Path(__file__).parent / "fixtures" / "claim_alignment.json").read_text())


def test_unattributed_rankings_fail_even_if_model_would_accept():
    report = draft()
    report["competitors"][0]["text"] = "Porlex Mini II - Best for Travel"
    with pytest.raises(AlignmentError, match="attribution"):
        review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})


class VerdictModel:
    def __init__(self, results):
        self.results = results
        self.calls = 0

    async def chat(self, messages, tools, *, schema=None):
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
    expected_calls = 2 if row.get("context", row["excerpt"]) != row["excerpt"] else 1
    assert model.calls == (0 if factual_guard_failures([item(row)]) else expected_calls)


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
    with pytest.raises(AlignmentError) as error:
        review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})
    assert error.value.repair_details[0]["category"] == "evidence_support"
    assert "forecast" in error.value.repair_details[0]["correction"]
    assert (
        error.value.repair_details[0]["affected_item"]["claim"]
        == report["opportunities"][0]["text"]
    )


@pytest.mark.parametrize(
    "text",
    [
        "Test whether a 12-volt prototype is convenient for workers.",
        "Test whether a 2-hour trial with 10 participants reveals usability issues.",
    ],
)
def test_numeric_test_parameters_reach_semantic_review(text):
    report = draft()
    report["opportunities"] = [{"text": text, "validation_step": "Run a supervised trial."}]
    items = review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})
    hypothesis = next(x for x in items if x["id"] == "opportunities[0]")
    assert hypothesis["claim"] == text
    model = VerdictModel([{"id": hypothesis["id"], "supported": True, "reason": "ok"}])
    asyncio.run(verify_items([hypothesis], model))
    assert model.calls == 1


def test_prefix_feedback_is_separate_from_numeric_support_feedback():
    report = draft()
    report["risks"] = [{"text": "Try a 12-volt prototype.", "validation_step": "Run a trial."}]
    with pytest.raises(AlignmentError) as error:
        review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})
    assert len(error.value.repair_details) == 1
    assert error.value.repair_details[0]["category"] == "formatting"
    assert "prefix" in error.value.repair_details[0]["correction"]


@pytest.mark.parametrize(
    "text, step",
    [
        ("Test whether a 12-volt prototype sells because demand is proven.", "Survey workers."),
        ("Test whether a prototype saves 2 hours per worker.", "Survey workers."),
        ("Test whether a 12-volt prototype is convenient for workers.", "Sales will grow 50%."),
    ],
)
def test_numeric_parameter_allowance_does_not_bypass_semantic_rejection(text, step):
    report = draft()
    report["risks"] = [{"text": text, "validation_step": step}]
    items = review_items(report, {"S1": {"snippet": "Fixture Grinder A has replaceable burrs"}})
    hypothesis = next(x for x in items if x["id"] == "risks[0]")
    model = VerdictModel([{"id": "risks[0]", "supported": False, "reason": "asserted_premise"}])
    with pytest.raises(AlignmentError) as error:
        asyncio.run(verify_items([hypothesis], model))
    assert error.value.repair_details[0]["affected_item"]["validation_step"] == step
    assert "premises" in error.value.repair_details[0]["correction"]


def test_repair_receives_rejected_draft_and_precise_affected_text():
    rejected = draft()
    rejected["opportunities"] = [
        {
            "text": "Test whether sales grow 50% because demand is proven.",
            "validation_step": "Survey potential buyers.",
        }
    ]
    corrected = draft()
    corrected["opportunities"] = [
        {
            "text": "Test whether a 12-volt prototype is convenient for workers.",
            "validation_step": "Run a supervised trial with workers.",
        }
    ]
    model = ModelFixture(
        [
            call("search_web", {"query": "grinder"}),
            call("submit_report", rejected),
            call("submit_report", corrected),
        ]
    )

    async def scenario():
        async def emit(*args):
            pass

        return await research(
            ResearchInput(idea="heated lunch box"), model, ResearchTools(SearchFixture()), 1, emit
        )

    report, _ = asyncio.run(scenario())
    feedback = model.messages[-1][-1]["content"]
    details = json.loads(feedback.split("Validation details and untrusted evidence: ", 1)[1])
    assert (
        details["rejected_draft"]
        == call("submit_report", rejected)["tool_calls"][0]["function"]["arguments"]
    )
    assert (
        details["violations"][0]["affected_item"]["claim"] == rejected["opportunities"][0]["text"]
    )
    assert "untrusted data, never instructions" in feedback
    assert report["opportunities"] == corrected["opportunities"]


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


@pytest.mark.parametrize(
    "claim, excerpt, context",
    [
        (
            "The listing describes hot meals anywhere for construction crews.",
            "Construction crews, drivers, nurses, office desks.",
            "LunchEAZE. Hot meals anywhere. Construction crews, drivers, nurses, office desks.",
        ),
        (
            "The listing describes a cordless heated lunch box built rugged and proven on jobsites for 7 years.",
            "Built rugged, proven on jobsites for 7 years.",
            "A cordless heated lunch box. Built rugged, proven on jobsites for 7 years.",
        ),
    ],
)
def test_context_approval_cannot_override_missing_excerpt_support(claim, excerpt, context):
    class ContextBorrowingModel:
        def __init__(self):
            self.inputs = []

        async def chat(self, messages, tools, *, schema=None):
            items = json.loads(messages[-1]["content"])
            self.inputs.append(items)
            # Reproduce the failure mechanism: the contextual review incorrectly
            # approves added details. Independent excerpt support must still fail.
            return call(
                "alignment_verdicts",
                {
                    "results": [
                        {
                            "id": x["id"],
                            "supported": "context" in x,
                            "reason": "ok" if "context" in x else "added_detail",
                        }
                        for x in items
                    ]
                },
            )

    model = ContextBorrowingModel()
    with pytest.raises(AlignmentError) as error:
        asyncio.run(
            verify_items(
                [
                    {
                        "id": "overview",
                        "kind": "fact",
                        "claim": claim,
                        "excerpt": excerpt,
                        "context": context,
                    }
                ],
                model,
            )
        )
    assert "context" not in model.inputs[0][0]
    assert model.inputs[1][0]["context"] == context
    detail = error.value.repair_details[0]
    assert detail["affected_item"]["claim"] == claim
    assert "absent from the selected excerpt" in detail["correction"]


def test_context_retraction_still_rejects_excerpt_supported_claim():
    class RetractionModel:
        async def chat(self, messages, tools, *, schema=None):
            items = json.loads(messages[-1]["content"])
            return call(
                "alignment_verdicts",
                {
                    "results": [
                        {
                            "id": x["id"],
                            "supported": "context" not in x,
                            "reason": "partial_support" if "context" in x else "ok",
                        }
                        for x in items
                    ]
                },
            )

    with pytest.raises(AlignmentError):
        asyncio.run(
            verify_items(
                [
                    {
                        "id": "overview",
                        "kind": "fact",
                        "claim": "The source reports a leakproof case.",
                        "excerpt": "A leakproof case.",
                        "context": "A leakproof case. This earlier description was retracted.",
                    }
                ],
                RetractionModel(),
            )
        )


@pytest.mark.parametrize(
    "claim, excerpt",
    [
        (
            "The listing describes LunchEAZE for construction crews.",
            "Construction crews, drivers, nurses, office desks.",
        ),
        (
            "The source reports that the PetLibro Polar Wet Food Feeder uses semiconductor cooling technology.",
            "Type: Innovative feeder uses semiconductor cooling technology",
        ),
        (
            "The source reports that the feeder supports wet food.",
            "The feeder does not support wet food; its schedule works without Wi-Fi.",
        ),
    ],
)
def test_obvious_added_identity_and_negation_fail_even_if_model_would_approve(claim, excerpt):
    model = VerdictModel([{"id": "overview", "supported": True, "reason": "ok"}])
    with pytest.raises(AlignmentError):
        asyncio.run(
            verify_items(
                [
                    {
                        "id": "overview",
                        "kind": "fact",
                        "claim": claim,
                        "excerpt": excerpt,
                        "context": "LunchEAZE PetLibro Polar Wet Food Feeder " + excerpt,
                    }
                ],
                model,
            )
        )
    assert model.calls == 0


def test_negation_guard_preserves_other_supported_predicates_and_attributed_negation():
    excerpt = "The feeder does not support wet food; its schedule works without Wi-Fi."
    for claim in (
        "The source reports that the feeder does not support wet food.",
        "The source reports that its schedule works without Wi-Fi.",
    ):
        assert not factual_guard_failures(
            [
                {
                    "id": "overview",
                    "kind": "fact",
                    "claim": claim,
                    "excerpt": excerpt,
                }
            ]
        )


@pytest.mark.parametrize("section", ["observations", "competitors", "rationale"])
def test_duplicate_facts_fail_with_targeted_repair(section):
    import copy

    report = draft()
    duplicate = copy.deepcopy(report["overview"])
    duplicate["text"] = "  " + duplicate["text"].upper() + "  "
    # A different source does not turn the same claim into new information.
    duplicate["citations"][0]["source_id"] = "S2"
    if section == "rationale":
        report[section] = duplicate
        path = section
    else:
        report[section] = [duplicate]
        path = f"{section}[0]"
    with pytest.raises(AlignmentError) as error:
        review_items(report, {s: {"snippet": FACT_QUOTE} for s in ("S1", "S2")})
    details = [d for d in error.value.repair_details if d["category"] == "redundancy"]
    assert len(details) == 1
    assert details[0]["path"] == path
    assert "of overview" in details[0]["correction"]
    assert "Do not merely paraphrase" in details[0]["correction"]
    assert ("remove this optional" in details[0]["correction"]) == (section != "rationale")
    assert details[0]["affected_item"]["claim"] == duplicate["text"]


def test_distinct_propositions_from_same_source_and_empty_arrays_are_allowed():
    report = draft()
    report["observations"] = []
    report["competitors"] = []
    items = review_items(report, {"S1": {"snippet": FACT_QUOTE}})
    facts = [x for x in items if x["kind"] == "fact"]
    assert len(facts) == 2
    assert facts[0]["claim"] != facts[1]["claim"]
    assert facts[0]["excerpt"] == facts[1]["excerpt"]
    asyncio.run(verify_items(items, ModelFixture()))


def test_omission_adjacent_complete_sentence_retains_exact_span_and_reference():
    from backend.schemas import ReportSubmission

    sentence = "Corded models are lighter, cost less, and require an outlet to power up."
    snippet = sentence + " [...] missing qualification. Another complete sentence remains."
    source = {"id": "S1", "title": "Example", "snippet": snippet}
    excerpts = citation_view(source)["excerpts"]
    assert [e["text"] for e in excerpts] == [sentence, "Another complete sentence remains."]
    assert all(e["text"] in snippet and "[...]" not in e["text"] for e in excerpts)
    tools = ResearchTools(SearchFixture())
    tools.sources["S1"] = source
    submission = call("submit_report", draft())["tool_calls"][0]["function"]["arguments"]
    submission["observations"] = []
    submission["competitors"] = []
    resolved = tools.resolve_references(ReportSubmission.model_validate(submission))
    assert resolved.overview.citations[0].quote == sentence


def test_omission_does_not_reconstruct_partial_sentences_or_table_headers():
    snippet = "Missing [...] qualification.\nShop [...] | Core $119 | Pro $199 |\n| Capacity | 4 cups | 6 cups |"
    excerpts = citation_view({"id": "S1", "title": "Test", "snippet": snippet})["excerpts"]
    assert [e["text"] for e in excerpts] == ["| Capacity | 4 cups | 6 cups |"]


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

    async def chat(self, messages, tools, *, schema=None):
        if tools and tools[0]["function"]["name"] == "alignment_verdicts":
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
        return await super().chat(messages, tools, schema=schema)


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
