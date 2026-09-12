# Fieldwork research diagnosis - 2026-09-12

Project: `C:\Users\josmn\Desktop\Projects\product-research-agent`. No project copy, WSL migration, or commit was made. Existing user changes (including Tavily, the research-call budget fixes, `num_ctx=8192`, and `num_predict=1500`) were retained.

## Findings

1. **The original failure was a real read timeout.** The instrumented unchanged 9B workflow failed at 226.995 seconds. Model calls lasted 23.721, 20.957, and 180.021 seconds. The third call raised `httpx.ReadTimeout`, before report validation. Because it timed out, there are no final generation counters or evidence of what its eventual parser output would have been.
2. **Hardware was a major bottleneck.** This laptop has a 6 GB RTX 3060 Laptop GPU. Ollama reported the 9B allocation as 6,277,551,877 bytes, with only 3,427,973,199 in VRAM. The two completed planning calls generated about 9 tokens/second. Later repeated experiments heated the GPU to 88 C and reduced its clock to 330 MHz; even the fully GPU-resident smaller model slowed. Under-60-second timing is not guaranteed under thermal throttling or competing workloads.
3. **The native schema was incompatible with the installed parser.** Pydantic emitted `$ref` for `overview` and `rationale`. Ollama 0.34.0's ToolProperty drops that field, and the Qwen parser defaults an untyped parameter to a string. A controlled native-tool probe returned `overview` as a JSON string with `$ref` (4.214 seconds), and as a proper object with the inline schema (3.771 seconds). This is separate from the original timeout. Sources: [Ollama type representation](https://github.com/ollama/ollama/blob/v0.34.0/api/types.go), [Qwen parser](https://github.com/ollama/ollama/blob/v0.34.0/model/parsers/qwen3coder.go).
4. **Redundant observations and repair drafts consumed context.** Baseline messages grew from 2 / 1,468 bytes to 5 / 10,737 bytes, then 11 / 20,191 bytes after five inspections repeated the same evidence. Tool-result sizes on turn 3 were 121, 8,438, 1,753, 1,728, 1,420, 1,884, and 1,524 bytes. The initial search already contained those snippets. A smaller-model repair run reached 8,128 prompt tokens with only 64 output tokens before `done_reason=length`. Increasing the timeout cannot fix that.
5. **Literal quote generation was unreliable on the smaller model.** It changed curly quotes and spliced nonadjacent passages with ellipses. Exact-substring validation correctly rejected those drafts. Stronger instructions and local evidence feedback did not reliably correct them. A controlled replay with the inherited presence penalty disabled still failed exact-quote validation after 21.605 seconds; that setting was not retained as a speculative fix.
6. **Zero-result search is a secondary provider outcome.** One instrumented request returned `provider_rows=0, accepted_sources=0`; another request for the baseline query returned five rows. There is no evidence of a normalization bug causing that observed empty list. Logging now separates provider rows from accepted sources. Instructions discourage invented year filters and allow one broader query when useful.

## Final scoped changes

- Inline native tool schemas without removing constraints. Keep the existing agent, registry, tools, provider abstraction, HTTP limits/retries, SQL worker, and UI.
- Use source IDs plus one-based excerpt numbers in the native `ReportSubmission` input. Excerpts are deterministic contiguous slices of the original snippet, never generated summaries. Reject unknown sources, unavailable excerpts, and undersized quotes. Resolve to the unchanged public `ReportDraft` with exact quotes, then run existing structural and substring validation. The model cannot supply a fabricated excerpt or output URL.
- Expose compact source observations once; keep URL/query/timestamp metadata in the authoritative ledger. Explicit inspection still refreshes the evidence. Do not replay repeated rejected standalone drafts; retain evidence and the latest repair guidance. Failed attempts remain disclosed in the report.
- Log model call duration, message/tool-result counts and byte sizes, offered schema names/sizes, Ollama timing/token counters, transient HTTP failure classes/statuses, and output/context truncation. Production diagnostics do not log prompts, provider bodies, credentials, or model prose.
- Select local `qwen3.5:4b` in Settings, `.env.example`, and this project's ignored `.env`. It loaded fully in VRAM (3,266,450,553 bytes). Keep context 8,192 and output limit 1,500. Restore the temporary 180-second timeout to 90 seconds; it is a failure ceiling, not a normal waiting target.
- Add an explicitly opt-in real diagnostic runner, regression tests, and documentation. No dependencies or frontend source files changed.

The schema is not simply smaller: the submission tool grew from 2,225 to 4,640 serialized bytes after inlining and explicit reference descriptions. Correct parameter types and removing long quote generation matter more than schema byte count alone. In the final report call, 5,885 prompt tokens plus 686 generated tokens fit inside 8,192.

## Local model comparison

| Model | Evidence | Decision |
| --- | --- | --- |
| qwen3.5:9b | Partly CPU-resident; about 9 output tokens/s; reproduced 180.021-second final-call timeout | Unsuitable for this laptop's sub-minute target in the original workflow |
| Installed qwen3.8:latest / 27B | About 17.7 GB on disk; larger than available VRAM; not benchmarked | Not a practical speed alternative on this GPU |
| Installed minimax-m3:cloud | Remote model | Not invoked; no cloud switch |
| qwen3:4b | Downloaded local comparison; 74.097-second failed run, hit 1,500 output tokens with lengthy planning | Not selected |
| qwen3.5:4b | Downloaded local comparison; fully GPU-resident; raw quote generation remained unreliable, but excerpt selection completed repeatedly | Selected with deterministic reference resolution |

Downloads were performed through the existing local Ollama service. Existing models were retained. Model catalog references: [Qwen 3.5 sizes](https://ollama.com/library/qwen3.5), [Qwen 3 4B](https://ollama.com/library/qwen3:4b). No paid cloud inference was used. Tavily live searches consumed the configured account's search allowance.

## Live runs

All used the exact idea **Reusable water bottle for college students**, with no cost scenario. The baseline called the real agent directly. Successful runs exercised real HTTP API routes via TestClient, session admission, an isolated SQLite queue, the background worker, Ollama, Tavily, validation, and persisted retrieval. The diagnostic model wrapper only records requests/responses; it delegates inference to the real provider.

| Run | Model call durations (s) | Total (s) | Outcome |
| --- | --- | --- | --- |
| Original 9B baseline | 23.721 / 20.957 / 180.021 | 226.995 | Read timeout |
| Inline-schema 4B, literal quotes | see private traces | 50.703 | Invalid citation then context exhaustion |
| Compact metadata 4B, literal quotes | see private traces | 47.799 | Repeated citation error then context/output limit |
| Local repair evidence, literal quotes | see private traces | 80.671 | Context/output limit |
| Bounded draft repair, literal quotes | see private traces | 181.158 | Planning limit; no accepted report |
| Copyable-text experiment | see private trace | Cancelled | Repeated citation errors; stopped during thermal throttling |
| qwen3:4b comparison | 23.012 / 9.914 / 37.648 | 74.097 | Output limit |
| Final references, model load included | 9.364 / 11.728 | **22.431** | **completed**, 10 sources, zero repairs |
| Final repeat 1, timeout restored to 90 s | 1.564 / 12.433 | **15.335** | **completed**, 10 sources, zero repairs |
| Final repeat 2 | 1.522 / 11.473 | **14.292** | **completed**, 10 sources, zero repairs |

The final model-load component was 7.539 seconds in the first successful run. Final repetitions used the same brief and stable search results; they are not a broad reliability benchmark. The job's normal `research.db` history was not modified by these diagnostic runs.

Private final artifacts are under ignored `work/diagnostics/`:

- `2b6c8b89a4fd40c69c915a0a89643c1b/` - first successful run
- `28d2db8f4378451487caa3e997de0979/` - repeat 1
- `5858e6a2dd374370ab3da7db67d38be2/` - repeat 2

Each contains the report, summary, trace, and isolated database. The opt-in runner also records private model-visible messages and responses. Do not publish those artifacts without review. Production logs contain metadata only.

## Checks

- 74 Python tests passed, including native schema compatibility, exact excerpt resolution, bad reference rejection, quote validation, repair-context bounds, truncation, metadata-only diagnostics, and existing API/worker reliability tests.
- 7 frontend tests passed; frontend typecheck and lint passed.
- Ruff lint and formatting checks passed for backend, tests, scripts, and migrations.
- The existing upstream Starlette/AnyIO deprecation warning remains.
- No browser interaction or production deployment verification was performed in this diagnosis; no UI changes were made. A frontend build was not needed for these backend-only changes.

## Reproduce and readiness

From this project, using its local virtual environment:

```powershell
.\.venv\Scripts\python.exe -m scripts.diagnose_research --live
```

Use `--model` to compare another already-installed local model. The runner rejects cloud aliases and missing local models. It deliberately requires `--live`; tests otherwise use explicit synthetic fixtures. Restart the normal backend to load the updated code/model setting.

**The execution bottleneck is fixed for this tested brief, but a V1 research-quality gate remains.** All three final reports passed exact-reference validation. Manual reading still found overbroad market conclusions and imperfect claim-to-selected-excerpt alignment. For example, a market-share statement in the overview was not supported by its specific selected excerpts. Exact provenance is not semantic entailment, and no semantic validator was removed or claimed here. I would not call this ready for a V1 checkpoint promising dependable research quality without a separate report-quality pass. It is a verified runtime/debugging milestone, not production-market validation. Cooling, different briefs, larger evidence sets, and provider variability remain practical limits.
