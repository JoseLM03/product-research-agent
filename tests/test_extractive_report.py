"""Reference-only facts cannot introduce paraphrased identities or capabilities."""

import asyncio
import copy
import json

import pytest
from pydantic import ValidationError

from backend.quality import AlignmentError, review_items, verify_extractive_items, verify_report
from backend.schemas import ReportSubmission, SearchArgs
from backend.tools import ResearchTools, citation_view, evidence_text
from tests.helpers import ModelFixture, SearchFixture, call, draft


def resolved():
    tools = ResearchTools(SearchFixture())
    asyncio.run(tools.execute("search_web", SearchArgs(query="grinder")))
    native = call("submit_report", draft())["tool_calls"][0]["function"]["arguments"]
    report = tools.resolve_references(ReportSubmission.model_validate(native))
    return tools, native, report


@pytest.mark.parametrize(
    "text",
    [
        "The source reports heated lunch boxes for workers who bring their lunch.",
        "The listing describes a cordless heated lunch box.",
    ],
)
def test_model_factual_prose_is_rejected_not_silently_rewritten(text):
    _, native, _ = resolved()
    native["overview"]["text"] = text
    with pytest.raises(ValidationError, match="Extra inputs"):
        ReportSubmission.model_validate(native)


@pytest.mark.parametrize(
    "quote",
    [
        "We offer individuals such as front-line workers, office workers, field drivers and construction workers a safe way to enjoy warm and healthy food anytime, anywhere.",
        "It's fully cordless — the rechargeable battery, charger, and insulated bag are all in the box.",
        "# Product Summary: Cordless Heated Lunch Box for Work, 20000mAh Battery Powered Self Heating Food Warmer, 1.6L Portable Heated Lunchbox, Fast Heating, Leakproof, Perfect for Truck Drivers, Construction & Outdoor Use",
        "The only downside of the 12V is that it can take a while to heat up depending on how much food you have.",
    ],
)
def test_captured_live_evidence_is_preserved_without_added_identity(quote):
    tools, native, _ = resolved()
    tools.sources["S2"]["snippet"] = quote
    native["overview"]["citation"] = {"source_id": "S2", "excerpt": 1}
    report = tools.resolve_references(ReportSubmission.model_validate(native))
    assert report.overview.text == evidence_text("S2", quote)
    assert report.overview.citations[0].quote == quote
    assert report.overview.text.endswith(f"“{quote}”")
    items = review_items(report.model_dump(), tools.sources, extractive=True)
    assert items[0]["kind"] == "selection"
    assert items[0]["excerpt"] == quote
    asyncio.run(verify_report(report.model_dump(), tools.sources, ModelFixture()))


def test_resolved_text_cannot_be_tampered_with_even_if_citation_is_exact():
    tools, _, report = resolved()
    report.overview.text += " Demand is proven."
    with pytest.raises(ValueError, match="server-resolved"):
        tools.validate_report(report)
    with pytest.raises(AlignmentError, match="server-resolved"):
        asyncio.run(verify_report(report.model_dump(), tools.sources, ModelFixture()))


def test_duplicate_evidence_rejected_across_sections_even_from_different_sources():
    tools, native, _ = resolved()
    tools.sources["S2"]["snippet"] = tools.sources["S1"]["snippet"]
    native["rationale"]["citation"] = {"source_id": "S2", "excerpt": 1}
    report = tools.resolve_references(ReportSubmission.model_validate(native))
    with pytest.raises(AlignmentError, match="duplicate factual claim of overview"):
        asyncio.run(verify_report(report.model_dump(), tools.sources, ModelFixture()))


def test_same_source_distinct_excerpts_and_optional_empty_sections_work():
    tools, native, _ = resolved()
    native["observations"] = []
    native["competitors"] = []
    report = tools.resolve_references(ReportSubmission.model_validate(native))
    asyncio.run(verify_report(report.model_dump(), tools.sources, ModelFixture()))
    public = tools.validate_report(report)
    assert isinstance(public["overview"]["text"], str)
    assert (
        public["overview"]["citations"][0]["source_id"]
        == public["rationale"]["citations"][0]["source_id"]
    )
    assert public["overview"]["text"] != public["rationale"]["text"]


def test_selection_review_retains_context_and_rejection_is_not_bypassed():
    tools, native, _ = resolved()
    tools.sources["S2"]["snippet"] = (
        "This case is leakproof. That description was retracted after testing."
    )
    native["overview"]["citation"] = {"source_id": "S2", "excerpt": 1}
    report = tools.resolve_references(ReportSubmission.model_validate(native))

    class RetractionModel:
        async def chat(self, messages, schema):
            items = json.loads(messages[-1]["content"])
            if items[0]["kind"] == "selection":
                assert "retracted" in items[0]["context"]
                assert "claim" not in items[0]
            return call(
                "alignment_verdicts",
                {
                    "results": [
                        {
                            "id": x["id"],
                            "supported": x["id"] != "overview",
                            "reason": "misleading_selection" if x["id"] == "overview" else "ok",
                        }
                        for x in items
                    ]
                },
            )

    with pytest.raises(AlignmentError, match="misleading_selection"):
        asyncio.run(verify_report(report.model_dump(), tools.sources, RetractionModel()))


def test_gap_splicing_still_cannot_be_selected():
    tools, _, report = resolved()
    report = copy.deepcopy(report)
    report.overview.citations[0].quote = "Fixture Grinder A [...] steel housing."
    report.overview.text = evidence_text("S1", report.overview.citations[0].quote)
    assert report.overview.citations[0].quote not in [
        e["text"] for e in citation_view(tools.sources["S1"])["excerpts"]
    ]
    with pytest.raises(ValueError):
        tools.validate_report(report)


def test_exact_excerpt_without_additional_context_does_not_need_entailment_review():
    class NoCalls:
        async def chat(self, *args):
            pytest.fail("No omitted context or model-authored factual claim to review")

    asyncio.run(
        verify_extractive_items(
            [
                {
                    "id": "overview",
                    "kind": "selection",
                    "excerpt": "The 12V heats slowly.",
                    "context": "The 12V heats slowly.",
                }
            ],
            NoCalls(),
        )
    )


def test_hypotheses_keep_existing_semantics_separate_from_selection_review():
    from backend.quality import VERIFY_SYSTEM

    class HypothesisModel(ModelFixture):
        async def chat(self, messages, schema):
            assert messages[0]["content"] == VERIFY_SYSTEM
            assert all(x["kind"] == "hypothesis" for x in json.loads(messages[-1]["content"]))
            return await super().chat(messages, schema)

    asyncio.run(
        verify_extractive_items(
            [
                {
                    "id": "risks[0]",
                    "kind": "hypothesis",
                    "claim": "Test whether workers prefer a 12-volt prototype.",
                    "validation_step": "Run a supervised prototype trial.",
                }
            ],
            HypothesisModel(),
        )
    )
