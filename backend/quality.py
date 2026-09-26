"""Deterministic report checks for server-resolved extractive evidence."""

import json
import re

from .tools import citation_view, evidence_text

MAX_ITEMS = 30
MAX_BYTES = 24_000

TEST_PARAMETER = re.compile(
    r"\b\d+(?:,\d{3})*(?:\.\d+)?[ -]*"
    r"(?:volts?|v|watts?|w|hours?|minutes?|seconds?|days?|weeks?|"
    r"degrees?(?:\s+(?:fahrenheit|celsius|kelvin))?|°\s?[fck]|"
    r"cups?|quarts?|gallons?|liters?|litres?|milliliters?|ml|"
    r"kilograms?|kg|grams?|ounces?|oz|pounds?|lbs?|"
    r"inches|centimeters?|cm|millimeters?|mm|"
    r"participants?|workers?|sites?|prototypes?|units?|models?)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
PERCENT_OR_CURRENCY = re.compile(
    r"(?:[$€£]\s*\d|\b(?:USD|EUR|GBP|CAD|AUD)\s*\d|\d+(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)
ASSERTED_PREMISE = re.compile(
    r"(?:\b(?:proven|established|confirmed)\s+(?:market\s+)?(?:demand|sales)\b|"
    r"\b(?:demand|sales)\s+(?:is|are|has\s+been|have\s+been)\s+"
    r"(?:proven|established|confirmed)\b)",
    re.IGNORECASE,
)

CORRECTIONS = {
    "asserted_premise": (
        "Remove claims that demand or sales are already proven, established, or confirmed. "
        "Describe only what the future test will evaluate."
    ),
    "numeric_forecast": (
        "Remove percentage or currency forecasts from the hypothesis. Numeric experimental "
        "parameters belong in physical/test units or in the validation step."
    ),
    "unbounded_number": (
        "Give numeric hypothesis parameters an explicit physical or test-setup unit, or move "
        "the setup detail to the validation step."
    ),
}


class AlignmentError(ValueError):
    """Only server-generated paths and deterministic reasons reach repair."""

    def __init__(self, failures, items=()):
        self.failures = failures
        by_id = {item["id"]: item for item in items}
        self.repair_details = [
            {
                "path": path,
                "category": (
                    "formatting"
                    if reason.startswith("start with")
                    else "redundancy"
                    if reason.startswith("duplicate factual claim")
                    else "evidence_support"
                ),
                "correction": CORRECTIONS.get(reason, reason),
                "affected_item": by_id.get(path),
            }
            for path, reason in failures
        ]
        super().__init__(
            "Report validation failed: "
            + "; ".join(f"{path}: {reason}" for path, reason in failures)
            + ". Correct only the rejected report sections."
        )


def _normalized(text):
    return " ".join(text.casefold().split())


def hypothesis_failures(path, hypothesis):
    text = hypothesis["text"]
    failures = []
    if not text.startswith("Test whether "):
        failures.append((path, 'start with the exact prefix "Test whether "'))
    if PERCENT_OR_CURRENCY.search(text):
        failures.append((path, "numeric_forecast"))
    elif NUMBER.search(TEST_PARAMETER.sub("", text)):
        failures.append((path, "unbounded_number"))
    if ASSERTED_PREMISE.search(text):
        failures.append((path, "asserted_premise"))
    return failures


def validate_report_quality(report, sources):
    """Validate only guarantees the server can establish deterministically."""
    items = []
    failures = []
    seen_quotes = {}
    claims = [("overview", report["overview"]), ("rationale", report["rationale"])]
    claims += [
        (f"{section}[{index}]", claim)
        for section in ("observations", "competitors")
        for index, claim in enumerate(report[section])
    ]

    for path, claim in claims:
        item = {"id": path, "kind": "selection", "claim": claim.get("text")}
        items.append(item)
        citations = claim.get("citations", [])
        if len(citations) != 1:
            failures.append((path, "use exactly one supporting excerpt"))
            continue
        citation = citations[0]
        source_id = citation.get("source_id")
        quote = citation.get("quote", "")
        source = sources.get(source_id)
        item["excerpt"] = quote
        if (
            source is None
            or quote not in {excerpt["text"] for excerpt in citation_view(source)["excerpts"]}
            or claim.get("text") != evidence_text(source_id, quote)
        ):
            failures.append(
                (path, "use only one server-resolved exact excerpt; do not supply factual prose")
            )
            continue
        key = _normalized(quote)
        if key in seen_quotes:
            remedy = "replace it with a distinct exact excerpt"
            if "[" in path:
                remedy += " or remove this optional entry"
            failures.append((path, f"duplicate factual claim of {seen_quotes[key]}; {remedy}"))
        else:
            seen_quotes[key] = path

    for section in ("opportunities", "risks"):
        for index, hypothesis in enumerate(report[section]):
            path = f"{section}[{index}]"
            items.append(
                {
                    "id": path,
                    "kind": "hypothesis",
                    "claim": hypothesis["text"],
                    "validation_step": hypothesis["validation_step"],
                }
            )
            failures.extend(hypothesis_failures(path, hypothesis))

    if len(items) > MAX_ITEMS or len(json.dumps(report).encode()) > MAX_BYTES:
        failures.append(("report", "reduce report length to fit the bounded report limits"))
    if failures:
        raise AlignmentError(list(dict.fromkeys(failures)), items)
