import html
import ipaddress
import logging
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from .schemas import EvidenceArgs, NoArgs, ReportDraft, ReportSubmission, SearchArgs

log = logging.getLogger("fieldwork.tools")


class CitationError(ValueError):
    """Safe, server-generated repair guidance with no source or model prose."""

    def __init__(self, message, source_id):
        super().__init__(message)
        self.source_id = source_id


def safe_url(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return False
        host = parsed.hostname.lower()
        if (
            host == "localhost"
            or host.endswith((".local", ".localhost", ".internal"))
            or "." not in host
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except (TypeError, ValueError):
        return False


def plain(value, limit):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value)))[:limit].strip()


def margin(costs):
    if costs is None:
        return {"error": "No user-supplied cost scenario. Do not estimate margins."}
    fee = costs.sale_price * costs.fee_percent / Decimal(100)
    contribution = costs.sale_price - costs.unit_cost - costs.shipping - costs.other_costs - fee

    def money(value):
        return str(value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))

    return {
        "currency": costs.currency,
        "inputs": costs.model_dump(mode="json"),
        "fees": money(fee),
        "contribution_per_unit": money(contribution),
        "contribution_margin_percent": money(contribution / costs.sale_price * 100),
        "basis": "User-supplied scenario; not a forecast. Excludes any taxes, returns, acquisition costs, and overhead not included in your inputs.",
    }


SPECS = {
    "search_web": (
        SearchArgs,
        "Search the web for market context. Results are snippets, not verified facts or full pages.",
    ),
    "search_competitors": (
        SearchArgs,
        "Search for competing products and retail listings using a product-specific query.",
    ),
    "inspect_evidence": (
        EvidenceArgs,
        "Retrieve a previously collected source snippet and its provenance by ID. Does not fetch a webpage.",
    ),
    "calculate_margin": (
        NoArgs,
        "Calculate contribution margin using ONLY the original user-supplied costs. No invented inputs.",
    ),
    "submit_report": (
        ReportSubmission,
        "Submit the final structured report with source_id and one-based excerpt references. Claims require citations; the server resolves exact quotes. Opportunities and risks are hypotheses with validation steps.",
    ),
}


def tool_schema(model):
    """Inline local Pydantic refs: Ollama's tool properties do not retain $ref.

    Keep every constraint; the original Pydantic models still validate calls.
    These server-owned schemas are non-recursive.
    """
    schema = model.model_json_schema()
    refs = schema.get("$defs", {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            name = value["$ref"].removeprefix("#/$defs/")
            value = {**refs[name], **{k: v for k, v in value.items() if k != "$ref"}}
        return {key: expand(item) for key, item in value.items() if key != "$defs"}

    return expand(schema)


def definitions(names=None):
    if names is None:
        names = SPECS.keys()
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": tool_schema(schema),
            },
        }
        for name, (schema, description) in SPECS.items()
        if name in names
    ]


def citation_view(source):
    """Present copyable spans, never generated summaries or repaired citations."""
    snippet = source["snippet"]
    excerpts = []
    start = 0
    while start < len(snippet):
        end = min(start + 240, len(snippet))
        if end < len(snippet):
            boundary = snippet.rfind(" ", start + 12, end)
            if boundary != -1:
                end = boundary
        excerpt = snippet[start:end].strip()
        if excerpt:
            excerpts.append(excerpt)
        start = end
    return {
        "id": source["id"],
        "title": source["title"],
        "excerpts": [{"index": i + 1, "text": text} for i, text in enumerate(excerpts)],
    }


class ResearchTools:
    def __init__(self, search, costs=None):
        self.search, self.costs = search, costs
        self.sources = {}
        self.calculation = None
        self.failures = []

    async def execute(self, name, args):
        if name in ("search_web", "search_competitors"):
            query = args.query + (
                " competing products retail price" if name == "search_competitors" else ""
            )
            rows = await self.search.search(query)
            found = []
            for row in rows:
                if not isinstance(row, dict) or not safe_url(row.get("url")):
                    continue
                url = row["url"][:2048]
                snippet = plain(row.get("description", ""), 1800)
                if not snippet:
                    continue
                existing = next((s for s in self.sources.values() if s["url"] == url), None)
                if existing:
                    found.append(existing)
                    continue
                if len(self.sources) >= 25:
                    break
                source_id = f"S{len(self.sources) + 1}"
                source = {
                    "id": source_id,
                    "title": plain(row.get("title", url), 250),
                    "url": url,
                    "snippet": snippet,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "query": query,
                    "kind": "search_snippet",
                }
                self.sources[source_id] = source
                found.append(source)
            log.info(
                "search_results tool=%s provider_rows=%s accepted_sources=%s",
                name,
                len(rows),
                len(found),
            )
            return {
                "sources": found,
                "limitation": "Search snippets may be outdated or incomplete. No sales volume or demand is established.",
            }
        if name == "inspect_evidence":
            if args.source_id not in self.sources:
                raise ValueError("Unknown source ID")
            return self.sources[args.source_id]
        if name == "calculate_margin":
            self.calculation = margin(self.costs)
            return self.calculation
        raise ValueError("Unknown tool")

    def resolve_references(self, submission):
        data = submission.model_dump(mode="json")
        claims = [data["overview"], data["rationale"], *data["observations"], *data["competitors"]]
        for claim in claims:
            for citation in claim["citations"]:
                source_id = citation["source_id"]
                source = self.sources.get(source_id)
                excerpts = citation_view(source)["excerpts"] if source else []
                index = citation.pop("excerpt") - 1
                if index < 0 or index >= len(excerpts) or len(excerpts[index]["text"]) < 12:
                    raise CitationError(
                        f"Invalid excerpt reference for {source_id}. Select an available excerpt with at least 12 characters.",
                        source_id,
                    )
                citation["quote"] = excerpts[index]["text"]
        return ReportDraft.model_validate(data)

    def validate_report(self, report):
        if isinstance(report, ReportSubmission):
            report = self.resolve_references(report)
        if not self.sources:
            raise ValueError("No retrieved evidence. Search before submitting a report.")
        claims = [("overview", report.overview), ("rationale", report.rationale)]
        claims += [(f"observations[{i}]", claim) for i, claim in enumerate(report.observations)]
        claims += [(f"competitors[{i}]", claim) for i, claim in enumerate(report.competitors)]
        for path, claim in claims:
            for index, citation in enumerate(claim.citations):
                source = self.sources.get(citation.source_id)
                if not source or citation.quote not in source["snippet"]:
                    raise CitationError(
                        f"{path}.citations[{index}] does not exactly quote {citation.source_id}. "
                        "Copy an exact substring from that source's snippet or correct the source ID. "
                        "Submit the complete report again with contiguous, verbatim quotes.",
                        citation.source_id,
                    )
        data = report.model_dump(mode="json")
        data["sources"] = list(self.sources.values())
        data["calculation"] = self.calculation
        # Numerical observations are extracted without letting the model invent a price.
        data["price_mentions"] = [
            {"source_id": s["id"], "text": match.group(0)}
            for s in self.sources.values()
            for match in re.finditer(
                r"(?:USD|EUR|GBP|CAD|AUD|[$€£])\s?\d[\d,]*(?:\.\d{1,2})?", s["snippet"]
            )
        ][:30]
        data["limitations"] += [
            "Evidence is limited to search snippets; citations are validated for existence, not semantic correctness.",
            "Price mentions may refer to shipping, accessories, or old offers. Verify listings before relying on them.",
        ]
        data["limitations"] += self.failures
        data["data_quality"] = "limited"
        data["assessment"] = (
            report.assessment if len(self.sources) >= 2 else "insufficient_evidence"
        )
        return data
