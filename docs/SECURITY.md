# Security and reliability review

This is an implementation review, not a penetration test or security guarantee.

## Implemented controls

- Strict length/type/range validation for briefs, costs, tool arguments, and reports; unknown fields rejected. Mutation request bodies capped at 8 KiB.
- Server-generated 256-bit session owner in a Starlette/itsdangerous signed cookie. HttpOnly and SameSite=Strict; Secure in production. No password storage. Owner-filtered reads/deletes return 404 for another browser's jobs.
- Exact configured-origin checks and JSON-only mutation requests; same-origin API architecture; no permissive CORS.
- No raw model HTML rendering, arbitrary tool execution, dynamic imports from model input, or full-page URL fetching. Search credentials stay server-side.
- Sources are server-collected snippets with timestamps and queries. Citations require exact quote inclusion. Unsafe/non-HTTP source links are filtered. A bounded local support-screening candidate follows provenance validation, but demonstrated semantic false accepts mean it is not a security or truth guarantee. Missing, duplicate, malformed, or timed-out verdicts fail closed. See `CLAIM_ALIGNMENT.md`.
- One SQL admission transaction protects global, session, client-IP, active-job, and queue limits. IP identifiers are HMACs, not raw IPs. Quota records survive report deletion and expire after two days.
- Tool/turn/source-count bounds, limited response sizes, timeouts, and one retry only for selected search transport/status failures. Model POSTs are not retried automatically.
- Durable queue states, guarded claiming, graceful cancellation failure, stale-job recovery, and cascading retention cleanup. Production schema migrations are explicit.
- Application logs deliberately omit exception bodies and private payloads. API responses use no-store; security headers include nosniff, deny framing, no-referrer, and production HSTS.
- Pinned dependencies, Python formatting/linting, automated tests, and CI. Generated frontend dependencies were updated to remove reported npm advisories at the time of checking.

## Remaining risks and tradeoffs

1. **Prompt injection and hallucination:** snippets and user input are labeled untrusted and tool capabilities are restricted, but a model can still misunderstand evidence. Exact quotes do not establish entailment or truth. Human source verification is required.
2. **Anonymous abuse:** users can discard cookies or distribute requests across IPs. The global SQL cap is the final application admission bound; it is not an exact token/spend ledger. Add provider-side quotas and edge controls before opening public access.
3. **Browser capability identity:** possession of the signed cookie grants history access. Cookie loss is not recoverable, and shared browser profiles share history. Add established OIDC if accounts are required.
4. **Runtime topology:** one process/worker is the supported deployment. Horizontal worker orchestration, prolonged database outages, and PostgreSQL runtime behavior have not been load-tested here. Synchronous SQL calls can block the event loop during slow database operations.
5. **Content security policy:** the static React/Vinext artifact currently requires inline script/style allowances. There are no raw-HTML sinks, but a nonce/hash policy would strengthen XSS defense. Proxy error responses and all host headers/settings need deployment review.
6. **Input-read abuse:** the body size limit bounds bytes, not the time a slow client takes to upload them. Configure reverse-proxy read/header timeouts and request-rate controls.
7. **Data retention:** report JSON includes the original brief and financial scenario; exports are private data. The app does not encrypt SQL columns or provide user accounts. Use TLS, encrypted storage/backups, and restricted database roles at the host. Cleanup runs with the worker, not an independent scheduler.
8. **Evidence durability:** a failed job retains tool events but not a complete source snapshot unless a valid final report was submitted. No full-page archives are stored. Search-provider terms determine permissible storage and reuse.
9. **Unverified environments:** no live Tavily key, successful full live-model run, Docker execution, PostgreSQL execution, browser visual/accessibility audit, or public deployment was available for this handoff. These are release gates, not claimed successes.

## Review outcomes

The automated suite verifies authorization boundaries, forged-cookie rejection, exact-quote validation, cost arithmetic, bounded execution, atomic quotas, provider errors, worker recovery, and explicit UI error states. It cannot establish security against all attacks or factual accuracy of arbitrary model output. CI is configured but has not run on a remote repository in this session.
