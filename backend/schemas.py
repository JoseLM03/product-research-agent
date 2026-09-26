from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Costs(StrictModel):
    currency: Literal["USD", "EUR", "GBP", "CAD", "AUD"] = "USD"
    sale_price: Decimal = Field(gt=0, le=1000000, max_digits=12, decimal_places=2)
    unit_cost: Decimal = Field(ge=0, le=1000000, max_digits=12, decimal_places=2)
    shipping: Decimal = Field(ge=0, le=1000000, max_digits=12, decimal_places=2)
    other_costs: Decimal = Field(ge=0, le=1000000, max_digits=12, decimal_places=2)
    fee_percent: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class ResearchInput(StrictModel):
    idea: str = Field(min_length=5, max_length=500)
    costs: Costs | None = None


class SearchArgs(StrictModel):
    query: str = Field(min_length=3, max_length=250)


class EvidenceArgs(StrictModel):
    source_id: str = Field(pattern=r"^S[1-9][0-9]?$")


class NoArgs(StrictModel):
    pass


class Citation(StrictModel):
    source_id: str = Field(pattern=r"^S[1-9][0-9]?$")
    quote: str = Field(min_length=12, max_length=500)


class Claim(StrictModel):
    text: str = Field(min_length=5, max_length=800)
    citations: list[Citation] = Field(min_length=1, max_length=5)


class Hypothesis(StrictModel):
    text: str = Field(
        min_length=5,
        max_length=800,
        description=(
            'Start with "Test whether ". Propose a future test without asserting proven, '
            "established, or confirmed demand or sales. Percentage and currency forecasts "
            "are forbidden. Numeric test parameters with explicit units, such as a 12-volt "
            "prototype, are allowed."
        ),
    )
    validation_step: str = Field(
        min_length=5,
        max_length=500,
        description="Describe a concrete future test, without asserting results or factual premises.",
    )


class ReportContent(StrictModel):
    overview: Claim
    observations: list[Claim] = Field(max_length=8)
    competitors: list[Claim] = Field(max_length=8)
    opportunities: list[Hypothesis] = Field(max_length=5)
    risks: list[Hypothesis] = Field(max_length=5)
    assessment: Literal["worth_further_research", "mixed_signals", "insufficient_evidence"]
    rationale: Claim


class ReportDraft(ReportContent):
    """Resolved report with server-owned process disclosures."""

    limitations: list[str] = Field(min_length=1, max_length=10)

    @field_validator("limitations")
    @classmethod
    def bounded_limitations(cls, value):
        if any(not x.strip() or len(x) > 500 for x in value):
            raise ValueError("Limitations must contain 1–500 characters")
        return value


class CitationReference(StrictModel):
    source_id: str = Field(pattern=r"^S[1-9][0-9]?$")
    excerpt: int = Field(
        ge=1,
        le=100,
        strict=True,
        description="One-based excerpt number from this source. The server supplies the exact quote.",
    )


class ReferencedClaim(StrictModel):
    citation: CitationReference


class ReportSubmission(ReportContent):
    """Native tool input; the stored/public ReportDraft still contains exact quotes."""

    overview: ReferencedClaim = Field(
        description="Category or use context, supported by its excerpt. Do not repeat another report claim."
    )
    observations: list[ReferencedClaim] = Field(
        max_length=8,
        description="Distinct user needs or practical tradeoffs. Each entry adds a new supported proposition across the report. Use [] if none; no source quota.",
    )
    competitors: list[ReferencedClaim] = Field(
        max_length=8,
        description="Identifiable offering-specific details, not repeated category or audience claims. Reuse a source only for different facts. Use [] if no additional supported propositions.",
    )
    rationale: ReferencedClaim = Field(
        description="A distinct supported fact relevant to the next-research decision. Do not repeat overview or observations, or invent an inference to justify the assessment."
    )
