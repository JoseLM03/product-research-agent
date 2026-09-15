# Claim alignment investigation — September 14, 2026

**NOT READY.** Uncommitted candidate on `105b2db2ff15e4c83d9588a236a01d9288fccb94` in `C:\Users\josmn\Desktop\Projects\product-research-agent`. No migration, model change, provider timeout increase, UI change, or commit.

## Cause and candidate change

Exact excerpt resolution proved provenance, not entailment. Generation combined attributes across excerpts, transferred product identity, repeated editorial judgments as facts, and promoted broad source prose into market conclusions. Arbitrary 240-character cuts could also separate qualifications and identity.

The candidate preserves the tool loop and public report contract. Native claims use one excerpt and at most 300 characters. Sentence/line excerpts preserve exact text, omit segments over 500 characters or containing `[...]`, and never manufacture evidence. Existing exact-source validation runs first. Deterministic checks reject missing attribution, obvious compound sentences, numbers absent from the excerpt, and hypotheses without prospective framing. These checks cannot establish meaning, units, entity identity, or true atomicity.

One local Ollama verification call per candidate checks facts, hypotheses, and model-authored limitations. Bounds: 20 items, 24,000 serialized input bytes, 20 seconds, complete unique verdict-ID coverage. The reviewer has no research/execution tools. At most two report attempts are allowed, including structural failures: initial submission plus one repair. Malformed/unavailable verification fails immediately. Safe repair feedback contains server-generated paths/codes, not raw model errors. Complete disjoint native section calls are combined without changing values; overlapping/incomplete/mixed calls are not merged.

One excerpt works only for a narrow statement. The generator still failed to decompose claims reliably; sentence boundaries sometimes leave product identity outside the excerpt. Nearby context (160 characters each side) is intended only to disqualify misleading claims, but the reviewer borrowed missing identity from it. Adding citations alone would not solve this.

An automatic attributed-quotation fallback was tried and removed. It produced a partial grinder report in 19.672 seconds but still accepted an unattributed ranking and anonymous price. Replacing failed prose with a quotation cannot bypass semantic review or restore omitted qualifications.

## Real API/worker runs

The diagnostic harness uses FastAPI routes through TestClient, an isolated real SQLite queue/worker, real Ollama/Tavily, and real persistence. No fake reports/providers. Each run had no cost scenario. Timings include admission, polling, searches, generation and validation. Runs were sequential; normal history was untouched.

| Idea | Seconds | Result | Private artifact folder |
| --- | ---: | --- | --- |
| Reusable water bottle for college students | 28.042 | Failed after one repair | `3ecba05412b04f879d4e2bf004b98bf7` |
| Automatic cat feeder for wet food | 43.820 | Failed after one repair | `91c2c183721e4e5095c01b7271a3d4bd` |
| Rechargeable desk lamp for dorm rooms | 37.240 | Failed after one repair | `d0f15d7c24a9423e93b6b975c8a921a8` |
| Compact manual coffee grinder for travel | 35.723 | Failed after one repair | `8c98862952654763ad662c582041fbe0` |

Ignored artifacts: `work/diagnostics/<folder>/` contains native requests/responses, source excerpts, results and timing logs. Failed results have `report: null`; summary source_count=0 means no persisted report sources, not empty searches. Water preceded the final verifier sentence about ambiguous identity; deterministic checks rejected it before review. Later edits removed a fixture-specific attribution phrase and updated disclosure text/formatting.

Discarded iterations failed in 68.241 and 25.745 seconds for water and 17.876 seconds for grinder. The discarded fallback returned a partial grinder report in 19.672 seconds. None establishes success for the final candidate.

## Manual review

Reviewed the final drafts' factual text against selected excerpts and read hypotheses, rather than treating an API status as proof.

- Water: initial overview asserted 42% share in 2026 against an excerpt missing those numbers. Repair copied broad source statements about all college students and market value without attribution. Exact copying still presents an unsupported independent assertion. A popularity-cycle risk presupposed trend-driven popularity.
- Feeder: reviewer approved `$169.99 on Amazon` against `$169.99 At Petlibro`. It approved a named PetLibro model's cooling capability when the excerpt only said `Type: Innovative feeder uses semiconductor cooling technology`; identity came from context. The report failed because hypotheses were rejected, not because every bad fact was caught. Some rejected hypotheses were reasonable prospective preference tests.
- Lamp: repaired NovoLido description added identity, USB charging, and touch controls to `List Price: $30`. Another claim added $17, freshmen suitability and compact-dorm suitability to `Tight budget, it gets the job done.` Missing $17 triggered deterministic rejection. Several narrow attributed observations aligned, but did not rescue these descriptions.
- Grinder: repair added compact size, ceramic burrs and causality to a bare Porlex travel ranking. It added AeroPress fit to a titanium-burr heading. Overview named Q2 where the excerpt only said `It`. A test-framed risk presupposed inherent particle-size spread. Narrow Q2/Q Air review attributions aligned better, but the report did not pass.

No report from the four final runs passed. Feeder false accepts show that the gate is not dependable even if generation begins complying more often.

## Evaluation and checks

`tests/fixtures/claim_alignment.json`: 26 hand-labelled cases across ten product ideas, including partial support, entity/vendor transfer, negation, numbers, population extrapolation, forecasts, causality, retractions, hedges, snippet instruction injection, rankings and hypothesis premises. Three factual cases are live-derived regressions. This is a diagnostic set, not a representative statistical benchmark.

`python -m scripts.evaluate_alignment --live`: two real local-model batches of 13, **13.695 seconds, 2 false accepts, 2 false rejects**, exit 1. False accepts: `feeder_vendor_swap`, `feeder_identity_from_context`. False rejects: `feeder_future_test`, `lamp_future_test`. Result: ignored `work/quality/adversarial-results.json`. This tests semantic review independently; deterministic guards have separate tests. Unit oracle-verdict tests verify enforcement, not model intelligence.

- Python: **120 passed**, 6.55 seconds; one upstream Starlette/AnyIO deprecation warning.
- Frontend: **7 passed**; lint and TypeScript typecheck passed.
- Ruff lint and format: passed across backend, tests, scripts and migrations (26 Python files).
- No new build/deployment/browser test; frontend code and public report types are unchanged.

Reproduce: `python -m scripts.diagnose_research --live --idea "Automatic cat feeder for wet food"`. Live tasks consume Tavily quota; the adversarial evaluation uses local Ollama only. Model/options remain `qwen3.5:4b`, context 8192, prediction limit 1500, provider timeout 90 seconds. Reviewer deadline is separately 20 seconds.

## Remaining V1 gate

This stricter candidate regresses completion rate and roughly doubles some runtimes relative to the earlier 14–22-second successes. Keep uncommitted for review; do not promote it as a production-quality fix. The same small local model confuses contextual identity with citation support and rejects valid hypotheses. A next candidate must reject these exact failures while repeatedly accepting useful reports across multiple ideas without a dramatic runtime regression. Larger budgets, relaxed validation, and automatic quote substitution would not establish that.
