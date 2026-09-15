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
    text: str = Field(min_length=5, max_length=800)
    validation_step: str = Field(min_length=5, max_length=500)


class ReportDraft(StrictModel):
    overview: Claim
    observations: list[Claim] = Field(max_length=8)
    competitors: list[Claim] = Field(max_length=8)
    opportunities: list[Hypothesis] = Field(max_length=5)
    risks: list[Hypothesis] = Field(max_length=5)
    assessment: Literal["worth_further_research", "mixed_signals", "insufficient_evidence"]
    rationale: Claim
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
    text: str = Field(
        min_length=5,
        max_length=300,
        description="One atomic source-attributed observation, fully supported by this citation. No added product attributes, market conclusions, or second idea.",
    )


class ReportSubmission(ReportDraft):
    """Native tool input; the stored/public ReportDraft still contains exact quotes."""

    overview: ReferencedClaim
    observations: list[ReferencedClaim] = Field(max_length=8)
    competitors: list[ReferencedClaim] = Field(max_length=8)
    rationale: ReferencedClaim
