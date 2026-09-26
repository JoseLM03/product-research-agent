# Fieldwork V1 report validation

## Current architecture

Research remains a single-agent native tool loop. After research finishes, the model returns a schema-constrained JSON report. For factual sections it selects `{source_id, excerpt}` references; it does not author factual prose. The server resolves each reference to an exact excerpt and renders the public claim text.

The V1 acceptance gate is deterministic:

- Pydantic validates the report shape and section bounds.
- Each factual entry has exactly one valid source/excerpt reference.
- The server renders the exact selected evidence and rejects supplied factual prose.
- Exact normalized duplicate excerpts are rejected across overview, observations, competitors, and rationale.
- Hypotheses require the exact `Test whether ` prefix. Percentage and currency forecasts, unbounded numbers in hypothesis text, and explicit proven/established/confirmed demand or sales premises are rejected. Numeric experimental parameters with recognized units are allowed, and validation-step setup numbers are allowed.
- Process limitations come only from execution facts owned by the server.
- The serialized report and item count remain bounded.

No model judges semantic alignment. The earlier Qwen report-verifier request, verdict schema, timeout, retry path, and fail-open/fail-closed provider handling were removed from the production path. Exact extractive reporting makes that self-review unnecessary for factual claims and avoids using Qwen as a blocking judge of its own hypotheses.

Evidence preprocessing conservatively omits candidates with internal omission markers, visibly chopped transcript tails, dangling endings, navigation or call-to-action fragments, orphan pipe-table rows, or unbalanced delimiters. Complete sentences adjacent to an omitted gap remain selectable. Text is never joined across a gap, and missing table mappings are never inferred.

The report still receives at most one repair. A validation failure is mapped to affected top-level sections. The repair schema contains only those sections, the server freezes the initial values of every other section, and the merge copies only approved section keys even if a provider ignores the repair schema. The complete merged report then receives all validation again.

## Deterministic evaluation

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.evaluate_alignment
```

This is a no-network smoke evaluation for accepted test parameters, rejected percentage/currency forecasts, rejected asserted demand/sales premises, and conservative evidence filtering. Backend regression tests contain the broader deterministic coverage.

## Historical semantic-verifier result

The earlier Qwen verifier evaluation remains useful as historical diagnosis. On 26 hand-labelled cases it produced two false accepts and two false rejects, including rejection of legitimate future-test hypotheses. Those results motivated the extractive and deterministic V1 design. The historical fixture files are not release gates and no current production request calls the semantic verifier.

## Manual acceptance

With Ollama running, `qwen3.5:4b` installed, and Tavily configured, run:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.diagnose_research --live --idea "Portable heated lunch box for construction workers"
```

The harness exercises the real API, isolated SQLite queue and worker, Ollama, Tavily, validation, and persistence. It writes ignored artifacts under `work/diagnostics/<run-id>/` without changing normal report history. A passing status is not sufficient by itself: compare every factual report entry to its selected excerpt, inspect section redundancy and evidence usefulness, confirm hypotheses are prospective tests, confirm limitations reflect execution facts, and review provider/activity logs. Live runs consume Tavily quota.
