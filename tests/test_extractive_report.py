"""Reference-only facts cannot introduce paraphrased identities or capabilities."""

import asyncio
import copy

import pytest
from pydantic import ValidationError

from backend.quality import AlignmentError, validate_report_quality
from backend.schemas import ReportSubmission, SearchArgs
from backend.tools import ResearchTools, citation_view, evidence_text
from tests.helpers import SearchFixture, call, draft


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
        "We offer construction workers a safe way to enjoy warm food anywhere.",
        "It's fully cordless — the rechargeable battery and charger are in the box.",
        "Cordless Heated Lunch Box for Work, 20000mAh Battery Powered Food Warmer",
        "The downside is that the 12V can take a while to heat a full meal.",
    ],
)
def test_exact_captured_evidence_is_preserved_without_added_identity(quote):
    tools, native, _ = resolved()
    tools.sources["S2"]["snippet"] = quote
    native["overview"]["citation"] = {"source_id": "S2", "excerpt": 1}
    report = tools.resolve_references(ReportSubmission.model_validate(native))
    assert report.overview.text == evidence_text("S2", quote)
    assert report.overview.citations[0].quote == quote
    validate_report_quality(report.model_dump(), tools.sources)


def test_resolved_text_cannot_be_tampered_with_even_if_citation_is_exact():
    tools, _, report = resolved()
    report.overview.text += " Demand is proven."
    with pytest.raises(ValueError, match="server-resolved"):
        tools.validate_report(report)
    with pytest.raises(AlignmentError, match="server-resolved exact excerpt"):
        validate_report_quality(report.model_dump(), tools.sources)


def test_duplicate_evidence_rejected_across_sections_even_from_different_sources():
    tools, native, _ = resolved()
    tools.sources["S2"]["snippet"] = tools.sources["S1"]["snippet"]
    native["rationale"]["citation"] = {"source_id": "S2", "excerpt": 1}
    report = tools.resolve_references(ReportSubmission.model_validate(native))
    with pytest.raises(AlignmentError, match="duplicate factual claim of overview"):
        validate_report_quality(report.model_dump(), tools.sources)


def test_same_source_distinct_excerpts_and_optional_empty_sections_work():
    tools, native, _ = resolved()
    native["observations"] = []
    native["competitors"] = []
    report = tools.resolve_references(ReportSubmission.model_validate(native))
    validate_report_quality(report.model_dump(), tools.sources)
    public = tools.validate_report(report)
    assert public["overview"]["citations"][0]["source_id"] == "S1"
    assert public["rationale"]["citations"][0]["source_id"] == "S1"
    assert public["overview"]["text"] != public["rationale"]["text"]


def test_gap_splicing_still_cannot_be_selected():
    tools, _, report = resolved()
    report = copy.deepcopy(report)
    report.overview.citations[0].quote = "Fixture Grinder A [...] steel housing."
    report.overview.text = evidence_text("S1", report.overview.citations[0].quote)
    assert report.overview.citations[0].quote not in [
        excerpt["text"] for excerpt in citation_view(tools.sources["S1"])["excerpts"]
    ]
    with pytest.raises(ValueError):
        tools.validate_report(report)
