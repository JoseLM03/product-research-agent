"""Deterministic report-quality and evidence preprocessing regressions."""

import asyncio
import copy
import time

import pytest

from backend.agent import AgentError, research
from backend.db import Job
from backend.quality import AlignmentError, validate_report_quality
from backend.schemas import ReportSubmission, ResearchInput, SearchArgs
from backend.tools import ResearchTools, citation_view, evidence_text
from backend.worker import run_job
from tests.helpers import ModelFixture, SearchFixture, call, draft


def resolved_report():
    tools = ResearchTools(SearchFixture())
    asyncio.run(tools.execute("search_web", SearchArgs(query="grinder")))
    native = call("submit_report", draft())["tool_calls"][0]["function"]["arguments"]
    report = tools.resolve_references(ReportSubmission.model_validate(native)).model_dump(
        mode="json"
    )
    return tools, report


@pytest.mark.parametrize(
    "text,step",
    [
        (
            "Test whether a 12-volt prototype is convenient for workers.",
            "Run a supervised trial with 20 workers.",
        ),
        (
            "Test whether a 170°F prototype heats a 6-cup meal within 30 minutes.",
            "Compare 10 prototypes across two controlled trials.",
        ),
        (
            "Test whether a 1.6-liter prototype fits a full meal.",
            "Run a capacity test with 25 participants.",
        ),
    ],
)
def test_numeric_experimental_parameters_are_allowed(text, step):
    tools, report = resolved_report()
    report["opportunities"] = [{"text": text, "validation_step": step}]
    validate_report_quality(report, tools.sources)


@pytest.mark.parametrize(
    "text,reason",
    [
        ("Test whether sales grow 50% next quarter.", "numeric_forecast"),
        ("Test whether buyers will pay $80 because demand is proven.", "numeric_forecast"),
        ("Test whether proven demand increases sales.", "asserted_premise"),
        ("Test whether sales are established before launch.", "asserted_premise"),
    ],
)
def test_clear_forecasts_and_asserted_premises_are_rejected(text, reason):
    tools, report = resolved_report()
    report["risks"] = [{"text": text, "validation_step": "Run a future buyer study."}]
    with pytest.raises(AlignmentError) as error:
        validate_report_quality(report, tools.sources)
    assert any(failure == ("risks[0]", reason) for failure in error.value.failures)


def test_validation_step_numeric_setup_is_allowed():
    tools, report = resolved_report()
    report["risks"] = [
        {
            "text": "Test whether workers prefer the cordless prototype.",
            "validation_step": "Test 40 workers, a $60 price point, and a 50% comparison threshold.",
        }
    ]
    validate_report_quality(report, tools.sources)


def test_exact_normalized_duplicate_factual_selection_is_rejected():
    tools, report = resolved_report()
    report["rationale"] = copy.deepcopy(report["overview"])
    with pytest.raises(AlignmentError) as error:
        validate_report_quality(report, tools.sources)
    assert error.value.failures[0][0] == "rationale"
    assert "duplicate factual claim of overview" in error.value.failures[0][1]


def test_same_source_can_support_distinct_exact_excerpts():
    tools, report = resolved_report()
    validate_report_quality(report, tools.sources)
    assert report["overview"]["citations"][0]["source_id"] == "S1"
    assert report["rationale"]["citations"][0]["source_id"] == "S1"
    assert report["overview"]["text"] != report["rationale"]["text"]


def test_server_resolved_text_and_one_citation_remain_mandatory():
    tools, report = resolved_report()
    report["overview"]["text"] += " Added prose."
    with pytest.raises(AlignmentError, match="server-resolved exact excerpt"):
        validate_report_quality(report, tools.sources)
    _, report = resolved_report()
    report["overview"]["citations"] *= 2
    with pytest.raises(AlignmentError, match="exactly one"):
        validate_report_quality(report, tools.sources)


def test_obvious_truncated_and_navigation_evidence_is_filtered():
    snippet = (
        "[4:15] this lunch box is an affordable choice for anyone looking for\n"
        "The battery works with\n"
        "See the honest comparison\n"
        "| Battery | 8,000mAh | 14,000mAh |\n"
        "A complete supported sentence remains."
    )
    excerpts = citation_view({"id": "S1", "title": "Test", "snippet": snippet})["excerpts"]
    assert [item["text"] for item in excerpts] == ["A complete supported sentence remains."]


def test_clearly_unbalanced_truncation_is_filtered():
    snippet = (
        "A complete sentence remains.\nThe listing says “battery included.\nCapacity (six cups."
    )
    excerpts = citation_view({"id": "S1", "title": "Test", "snippet": snippet})["excerpts"]
    assert [item["text"] for item in excerpts] == ["A complete sentence remains."]


def test_complete_evidence_adjacent_to_omission_gap_is_preserved():
    sentence = "Corded models are lighter, cost less, and require an outlet to power up."
    snippet = sentence + " [...] missing qualification. Another complete sentence remains."
    excerpts = citation_view({"id": "S1", "title": "Test", "snippet": snippet})["excerpts"]
    assert [item["text"] for item in excerpts] == [
        sentence,
        "Another complete sentence remains.",
    ]
    assert all(item["text"] in snippet for item in excerpts)


def test_gap_is_never_reconstructed_and_orphan_table_is_filtered():
    snippet = "Missing [...] qualification.\n| Capacity | 4 cups | 6 cups |"
    assert citation_view({"id": "S1", "title": "Test", "snippet": snippet})["excerpts"] == []


class DuplicateReportModel(ModelFixture):
    def __init__(self):
        duplicate = call("submit_report", draft())
        arguments = duplicate["tool_calls"][0]["function"]["arguments"]
        arguments["rationale"] = copy.deepcopy(arguments["overview"])
        super().__init__(
            [
                call("search_web", {"query": "grinder"}),
                duplicate,
                copy.deepcopy(duplicate),
            ]
        )


def test_deterministic_repair_is_bounded_to_one_attempt():
    model = DuplicateReportModel()

    async def emit(*args):
        pass

    with pytest.raises(AgentError, match="one repair"):
        asyncio.run(
            research(
                ResearchInput(idea="compact grinder"),
                model,
                ResearchTools(SearchFixture()),
                2,
                emit,
            )
        )
    assert len(model.messages) == 3


def test_worker_never_persists_a_deterministically_rejected_report(client, app):
    job_id = client.post("/api/research", json={"idea": "compact grinder"}).json()["id"]
    with app.state.sessions.begin() as db:
        job = db.get(Job, job_id)
        job.status = "running"
        job.started_at = time.time()
    asyncio.run(
        run_job(
            job_id, app.state.sessions, app.state.settings, DuplicateReportModel(), SearchFixture()
        )
    )
    result = client.get("/api/research/" + job_id).json()
    assert result["status"] == "failed"
    assert result["report"] is None


def test_resolved_exact_evidence_text_format_is_stable():
    tools, report = resolved_report()
    citation = report["overview"]["citations"][0]
    assert report["overview"]["text"] == evidence_text(citation["source_id"], citation["quote"])
    validate_report_quality(report, tools.sources)
