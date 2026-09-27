import html
import ipaddress
import logging
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from .schemas import EvidenceArgs, NoArgs, ReportDraft, ReportSubmission, SearchArgs

log = logging.getLogger("fieldwork.tools")


def evidence_text(source_id, quote):
    """Attribution is server-owned; the enclosed evidence is never rewritten."""
    return f"Source {source_id} states (unverified excerpt): “{quote}”"


class CitationError(ValueError):
    """Safe, server-generated repair guidance with no source or model prose."""

    def __init__(self, message, source_id, path="report"):
        super().__init__(message)
        self.source_id = source_id
        self.path = path


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


def price_mentions(sources):
    """Extract currency amounts, excluding obvious market-size figures."""
    mentions = []
    seen = set()
    for source in sources:
        snippet = source["snippet"]
        for match in re.finditer(
            r"(?:USD|EUR|GBP|CAD|AUD|[$€£])\s?\d+(?:,\d{3})*(?:\.\d{1,2})?", snippet
        ):
            if re.match(r"\s*(?:million|billion|trillion)\b", snippet[match.end() :], re.I):
                continue
            text = match.group(0)
            key = (source["id"], text.casefold())
            if key in seen:
                continue
            seen.add(key)
            mentions.append({"source_id": source["id"], "text": text})
            if len(mentions) == 30:
                return mentions
    return mentions


SPECS = {
    "finish_research": (
        NoArgs,
        "Finish research and request structured report generation. No report content belongs in this call.",
    ),
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
        names = [name for name in SPECS if name != "submit_report"]
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
    """Expose only conservative, contiguous evidence spans from the source snippet."""
    snippet = source["snippet"]
    # A complete sentence before an omission is still an exact usable span.
    # Keep the marker attached to the following fragment so that fragment is
    # discarded. Never join across a gap or reconstruct a table header.
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9“"]|\[\.\.\.\])|\n+', snippet)
    excerpts = []
    for part in parts:
        text = part.strip()
        lower = text.casefold()
        if not 12 <= len(text) <= 500 or "[...]" in text:
            continue
        # A pipe-delimited row without its headers has no safe value mapping.
        if text.startswith("|") and text.count("|") >= 2:
            continue
        # Transcript tails without terminal punctuation are visibly chopped.
        if re.match(r"^\[\d{1,2}:\d{2}\]", text) and not re.search(r'[.!?][”"]?$', text):
            continue
        if re.search(
            r"\b(?:a|an|the|and|or|but|for|to|of|with|without|from|in|on|at|by|"
            r"as|is|are|was|were|its|their|this|that|these|those|limited)\s*$",
            lower,
        ):
            continue
        if re.match(
            r"^(?:shop|buy|click|read|learn|see|view|visit|subscribe|sign up)\b",
            lower,
        ) or lower in {"from the crew", "what construction workers say"}:
            continue
        if (
            text.count("(") != text.count(")")
            or text.count("[") != text.count("]")
            or text.count("“") != text.count("”")
        ):
            continue
        excerpts.append(text)
    return {
        "id": source["id"],
        "title": source["title"],
        "excerpts": [{"index": i + 1, "text": text} for i, text in enumerate(excerpts[:100])],
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
        claims = [("overview", data["overview"]), ("rationale", data["rationale"])]
        claims += [
            (f"{section}[{index}]", claim)
            for section in ("observations", "competitors")
            for index, claim in enumerate(data[section])
        ]
        for path, claim in claims:
            claim["citations"] = [claim.pop("citation")]
            for citation in claim["citations"]:
                source_id = citation["source_id"]
                source = self.sources.get(source_id)
                excerpts = citation_view(source)["excerpts"] if source else []
                index = citation.pop("excerpt") - 1
                if index < 0 or index >= len(excerpts) or len(excerpts[index]["text"]) < 12:
                    raise CitationError(
                        f"Invalid excerpt reference for {source_id}. Select an available excerpt with at least 12 characters.",
                        source_id,
                        path,
                    )
                citation["quote"] = excerpts[index]["text"]
            claim["text"] = evidence_text(citation["source_id"], citation["quote"])
        data["limitations"] = self.process_limitations()
        return ReportDraft.model_validate(data)

    def process_limitations(self):
        """Disclose known execution boundaries, never infer absent market evidence."""
        limitations = [
            "This workflow does not perform independent product testing or independently verify market demand or sales. Factual sections contain attributed source excerpts, not verified product facts; ambiguous wording remains unresolved."
        ]
        if self.sources and all(s.get("kind") == "search_snippet" for s in self.sources.values()):
            limitations.append(
                "Evidence collection in this run was limited to search snippets; full source pages were not retrieved."
            )
        if any(
            re.search(r"(?:USD|EUR|GBP|CAD|AUD|[$€£])\s?\d", s["snippet"])
            for s in self.sources.values()
        ):
            limitations.append(
                "Price mentions were extracted from snippets without verifying current offers or whether each amount refers to the product, shipping, or accessories."
            )
        if self.costs is None:
            limitations.append(
                "No user-supplied cost scenario was provided for margin calculation."
            )
        elif self.calculation is None:
            limitations.append("A margin calculation was not performed in this run.")
        else:
            limitations.append(
                "Calculated margins use only the user-supplied cost scenario; they are not forecasts or verified business results."
            )
        if self.failures:
            limitations.append("One or more research or tool steps failed during this run.")
        return limitations

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
                        path,
                    )
            if len(claim.citations) != 1 or claim.text != evidence_text(
                claim.citations[0].source_id, claim.citations[0].quote
            ):
                raise ValueError("Factual report content must be server-resolved exact evidence.")
        if report.limitations != self.process_limitations():
            raise ValueError("Report limitations must be generated by the server from this run.")
        data = report.model_dump(mode="json")
        data["sources"] = list(self.sources.values())
        data["calculation"] = self.calculation
        # Numerical observations are extracted without letting the model invent a price.
        data["price_mentions"] = price_mentions(self.sources.values())
        data["data_quality"] = "limited"
        data["assessment"] = (
            report.assessment if len(self.sources) >= 2 else "insufficient_evidence"
        )
        return data
