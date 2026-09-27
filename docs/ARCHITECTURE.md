# Architecture

## Boundaries

The web client only talks to same-origin `/api`. It never receives search credentials or the model endpoint. The REST layer validates requests, checks session ownership, and admits jobs. A worker owns execution. Provider adapters own HTTP protocol handling. Tool functions own source collection and arithmetic. The agent owns tool selection, observation, and final-report synthesis.

No LangChain, vector database, browser scraper, broker, or separate job service is required for this scope. The control loop is intentionally small enough to explain during a code review or interview. The UI scaffold is static at deployment; no Node inference/backend service is deployed.

## Agent loop

1. Load the original validated brief and optional cost scenario.
2. Send the system instructions, brief, and native research-tool definitions to Ollama `/api/chat` with `stream=false`.
3. Receive native `message.tool_calls`, then validate each tool name and its arguments against the registry's Pydantic model.
4. Execute the selected research tool and append a `role=tool`, `tool_name=...` observation to the conversation.
5. Allow additional model-selected calls until `finish_research`, eight planning turns, ten research calls by default, or the job deadline.
6. Build a bounded finalization context from the request, collected evidence, calculations, and server-owned process limitations. Request the report through a separate schema-constrained structured response rather than a native tool call.
7. Resolve every factual selection to the exact server-held source excerpt. The model selects evidence references; it does not author factual paraphrases.
8. Apply Pydantic validation and deterministic checks for references, excerpts, citations, duplicates, report limits, and hypothesis quality.
9. If validation fails, allow at most one model repair. Only affected top-level sections may be returned and replaced; unaffected sections remain frozen server-side.
10. If the repaired report fails only on known optional opportunity/risk hypothesis-quality rules, remove exactly those invalid entries without another model call.
11. Revalidate the complete report before persistence. No report is accepted through the repair or pruning paths unless it passes the same full validation.

Research-tool errors are returned as observations so the model can adapt. Failed report-validation attempts remain visible in activity history. A recovered report-validation failure does not by itself make an accepted report partial or add a limitation. Genuine research/provider/tool failures and an `insufficient_evidence` assessment still produce partial results. Search observations omit repeated metadata and expose deterministic numbered excerpts; the original source ledger is unchanged. Arbitrary code, shell commands, filesystem access, and arbitrary URL fetching are not agent capabilities. The app does not expose or persist model chain-of-thought.

## Every agent tool

- **`search_web(query)`**: Tavily web search, up to five results per call. Adds safe HTTP(S) source links, title, snippet, query, and retrieval timestamp to the task-local evidence ledger. No webpage fetching or scraping.
- **`search_competitors(query)`**: uses the same provider with a competitor/retail-oriented query suffix. A narrow product-focused affordance, not an independent dataset. Results do not establish competitor sales or demand.
- **`inspect_evidence(source_id)`**: returns the already-retrieved snippet and provenance. It cannot invent a source or retrieve a new arbitrary URL.
- **`calculate_margin()`**: no model-controlled numeric arguments. Reads the original validated cost inputs and calculates fees, contribution per unit, and contribution-margin percentage using Decimal and half-up rounding. Missing costs produce an explicit limitation.
- **`finish_research()`**: ends native evidence gathering and starts structured report finalization.

Report finalization is not a native research tool. It uses the bounded `ReportSubmission` schema in a separate schema-constrained response. The server rejects unavailable references, resolves exact original text, and applies the `ReportDraft` and report-quality validation before persistence. The public report still contains full quotes.

The optional browser `stage_research_idea` WebMCP affordance only fills the brief. It does not start research or spend provider resources. It is separate from the backend research agent. Unsupported browsers ignore it.

## Report contract

Structured report selections use one `citation: {source_id, excerpt}` per factual claim and a 300-character limit. The server resolves each selection to the exact excerpt, and the public report retains `citations: [{source_id, quote}]`, so saved reports and frontend types remain compatible. Overview and rationale follow the same rules as observations and competitors. Opportunities and risks start with `Test whether ` and include a future validation step. The assessment is one of `worth_further_research`, `mixed_signals`, or `insufficient_evidence`.

The server supplies source records, price mentions, calculations, and `data_quality=limited`. The model cannot supply arbitrary output source URLs or modify the original cost scenario. The UI renders text through React, never as raw model-generated HTML or Markdown.

`completed` means a report passed schema and all deterministic report validation. Genuine research/provider/tool failures, too few usable sources, and an insufficient-evidence assessment produce `partial`; recovered report-validation attempts alone do not. An invalid or absent report produces `failed`.

## SQL design

- `jobs`: UUID primary key; session owner; original idea and inputs; constrained state (`queued`, `running`, `completed`, `partial`, `failed`); timestamps; JSON report; sanitized error.
- `tool_events`: auto-increment key; indexed foreign key to job with cascade deletion; timestamp; tool name; execution status; bounded public detail.
- `admissions`: task UUID; session owner; HMAC of client IP; admission timestamp. Separate from job deletion so history deletion cannot bypass quotas. Removed after two days.
- `admission_lock`: one singleton row serializes admission transactions. Count checks and insertion occur inside the same transaction, making per-day and active-job limits atomic.

Source evidence is an immutable snapshot within the report JSON. This simplifies report retrieval and retention; a separate source table is unnecessary without cross-report querying or deduplication requirements. JSON is not used for ownership or queue-state queries.

Development can create the SQLite schema automatically. Production requires explicit Alembic migrations. Epoch-second timestamps avoid dialect timezone differences; the app formats them for the browser. SQLite foreign keys and WAL are enabled.

## Worker semantics

A conditional SQL update claims a queued job. Jobs survive process restarts. Stale running jobs are marked failed after their configured deadline plus a 60-second recovery allowance; they are never silently replayed. Shutdown cancellation also writes failure status when the database is reachable.

The worker is deliberately configured for one process/replica. SQL claims prevent duplicate claiming, but multi-worker throughput, connection-pressure tuning, leases, and replica rollout behavior have not been validated as a supported architecture. One executing task, a five-task active queue cap, per-day admissions, and bounded turns keep initial operation predictable.

## Deliberate limits

No account system: signed browser identity meets private browser history without password management. No full-page retrieval: avoiding arbitrary network fetching removes a major SSRF and scraping surface. No financial predictions: explicit cost scenarios are sufficient to demonstrate a deterministic tool. No auto-replay of crashed work: this avoids duplicate provider usage after uncertain failures.

Native research-tool schemas inline Pydantic references because Ollama 0.34.0 does not retain `$ref` in tool properties. All server-side constraints remain. See `RESEARCH_DIAGNOSIS.md` for historical context and generation measurements.
