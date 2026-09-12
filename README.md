# Fieldwork â€” AI-Powered E-Commerce Product Research Agent

Fieldwork is a full-stack research workspace for investigating product ideas. One AI agent chooses research tools, observes their results, makes follow-up calls, and submits a validated report with source quotes. Research runs as a durable SQL job; the browser shows its status, tool activity, findings, and limitations.

**Status:** locally tested; not deployed. The September 12 live diagnosis completed three real Ollama/Tavily API-to-worker-to-persisted-report runs in 22.431, 15.335, and 14.292 seconds on this laptop. Structural and citation-reference validation passed; human review still found overbroad claims and imperfect claim-to-excerpt alignment. This is not a verified market-intelligence service. See [research diagnosis](docs/RESEARCH_DIAGNOSIS.md) for reproducible commands, model selection, and limitations.

There are no sample market reports, fake users, invented metrics, or silent mock-provider fallbacks in the application. Without provider configuration, the UI clearly disables research. Existing research is private to a signed browser session.

## What it does

- Accepts a product idea and optional user-supplied cost scenario.
- Runs a single agent using native Ollama function/tool calls.
- Searches legitimate Tavily Search API results for market context and competitors.
- Requires factual report sections to cite collected source IDs and exact snippet quotes.
- Separates opportunity/risk hypotheses from observations and asks how to validate each hypothesis.
- Extracts price mentions from source text without allowing the model to invent numerical observations.
- Calculates contribution margin with decimal arithmetic using only the original cost inputs.
- Persists jobs and tool events; supports private history, JSON export, and deletion of finished tasks.
- Makes missing configuration, API failures, invalid output, timeouts, partial reports, and execution limits visible.

## Architecture and technology choices

React and TypeScript handle the form, polling, reports, and interaction states. The Sites-generated Vinext/Vite scaffold builds a static frontend. Shadcn/Base UI supplies accessible tabs, select, checkbox, and confirmation primitives. The scaffold includes additional unused components, but no additional product services depend on them.

FastAPI provides typed REST endpoints. Pydantic validates both user input and model tool arguments. SQLAlchemy provides one SQL model for SQLite development and PostgreSQL production. Alembic versions the schema. One worker coroutine in the API process consumes the SQL queue, avoiding a separate broker or microservice for a small portfolio product. HTTPX provides bounded provider requests. Ollama provides local tool-capable inference without an agent framework hiding the control loop.

The production deployment is one container serving both static React assets and the Python API, plus PostgreSQL and a private Ollama endpoint. This keeps cookies and API requests same-origin and avoids cross-site authentication configuration. See [architecture](docs/ARCHITECTURE.md) and [deployment](docs/DEPLOYMENT.md).

```mermaid
flowchart LR
  Browser[React workspace] --> API[FastAPI REST API]
  API --> SQL[(Jobs and events in SQL)]
  SQL --> Worker[Single queue worker]
  Worker --> Agent[Bounded agent loop]
  Agent --> Model[Ollama native tool calls]
  Model --> Agent
  Agent --> Tools[Validated tool registry]
  Tools --> Search[Tavily Search API]
  Tools --> Calc[Decimal cost calculation]
  Tools --> Agent
  Agent --> Report[Validate quotes and report]
  Report --> SQL
```

## Repository layout

```text
app/                         React workspace and shared styles
components/research-report.tsx Report, sources, activity, and export UI
components/ui/               Generated Shadcn/Base UI primitives
lib/api.ts                   Typed frontend API client
backend/
  main.py                    REST routes, sessions, request boundaries
  config.py                  Environment configuration and production checks
  db.py                      SQL models and connection setup
  worker.py                  Queue consumption, deadlines, retention, recovery
  agent.py                   Native tool-call / observation loop
  providers.py               Ollama and Tavily adapters
  schemas.py                 Strict domain and report contracts
  tools.py                   Tools, evidence ledger, decimal calculations
migrations/                  Alembic schema history
tests/                       Backend tests and explicit provider fixtures
tests/frontend/              Frontend interaction and API-client tests
scripts/live_ollama_smoke.py  Opt-in real-model test with synthetic search results
docs/                        Architecture, deployment, security, verification
Dockerfile / compose.yaml    Single app container and PostgreSQL setup
.github/workflows/ci.yml      Automated test/build and migration checks
```

## Local setup

Use **Python 3.12** and **Node 22.23.2** (see `.nvmrc`). Node 24 produced a native libuv assertion at build exit on this Windows machine; Node 22 completed successfully. The prebuild check rejects unsupported Node majors. Do not copy virtual environments or `node_modules` between operating systems.

From the repository root, in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm ci
Copy-Item .env.example .env
```

On Linux/WSL, after you manually copy the finished source:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci
cp .env.example .env
```

The dependencies are pinned in `package-lock.json` and `requirements.lock`. The latter is a constraints file shared by production and development requirements; test tools are not installed in production simply because they appear in the constraints.

### Start development

In one terminal (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal with Node 22 active:

```bash
npm run dev
```

Open `http://127.0.0.1:3000`. Vite proxies `/api` to port 8000. Keep `APP_ORIGIN=http://127.0.0.1:3000` exactly; `localhost` and `127.0.0.1` are different origins. The local interactive API docs are at `http://127.0.0.1:8000/api/docs`.

To run the built app as a single service, run `npm run build`, set `APP_ORIGIN=http://127.0.0.1:8000`, then start the same Python command. FastAPI serves `dist/client` alongside `/api`. A Node server is not needed in production.

### Enable real research

1. Run a private Ollama server and choose a locally available model with native tool support. Set `OLLAMA_MODEL` to its exact model name; Fieldwork does not download models automatically. Avoid cloud-model aliases unless you intentionally authorize their account usage.
2. Configure your own `TAVILY_API_KEY` in the ignored `.env` file. Check the provider's plan, terms, and account-level limits before enabling requests. No key is supplied by this repository.
3. Set `RESEARCH_ENABLED=true` and restart the Python service. This authorizes provider requests within the app's configured limits. The UI checks configuration, not provider connectivity; a task exposes connectivity failures.
4. Start one focused research task, inspect its tool activity, and open the cited sources. Confirm that the report quotes match the evidence and that the observations follow from those quotes.

Native tool calling follows [Ollama's tool-calling interface](https://docs.ollama.com/capabilities/tool-calling). Search uses the [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search) directly through `httpx`. Requests use basic general search with up to five results, safe search enabled, automatic parameters disabled, and no generated answer, raw page content, or images. This works with free-tier credits; account credit limits still apply.

## Environment variables

All application settings live in `backend/config.py`; `.env.example` documents defaults. Secrets never belong in frontend code.

- `ENVIRONMENT`: `development`, `test`, or `production`. Production requires HTTPS, PostgreSQL, and a non-default session secret.
- `DATABASE_URL`: defaults to `sqlite:///./research.db`; production example is `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` with provider-required TLS settings.
- `SESSION_SECRET`: generate a stable random value of at least 32 characters for deployment. Rotating it invalidates browser access to old history.
- `APP_ORIGIN`: the exact public scheme/host/port, without a path. Used for mutation-origin checks.
- `OLLAMA_URL`: private backend-controlled inference endpoint; defaults to `http://127.0.0.1:11434`.
- `OLLAMA_MODEL`: exact model name, default `qwen3.5:4b`. This model was not installed or downloaded by the application.
- `TAVILY_API_KEY`: server-only search credential; empty by default.
- `RESEARCH_ENABLED`: defaults to `false`. Disables new admissions and new queue claims when false; an already-running request may finish.
- `DAILY_GLOBAL_LIMIT`, `DAILY_SESSION_LIMIT`, `DAILY_IP_LIMIT`: defaults `20`, `5`, `10`. UTC-day SQL admission quotas. Deleting reports does not refund quota.
- `MAX_TOOL_CALLS`: default `10`, including final report submission. The loop also has an eight-model-turn ceiling.
- `JOB_TIMEOUT_SECONDS`: default `300`; each model request has a 90-second timeout; search has 15 seconds per attempt.
- `WORKER_ENABLED`: default `true`. Disable only for isolated tests/maintenance; this architecture has no separately deployed worker.
- `STATIC_DIR`: defaults to `dist/client`, relative to the process working directory.
- `RETENTION_DAYS`: default `30`; the worker removes expired finished jobs and their events. Session access also expires.
- `POSTGRES_PASSWORD`: used only by the optional Compose PostgreSQL service; not an application setting.

## Tests and verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests scripts migrations
.\.venv\Scripts\python.exe -m ruff format --check backend tests scripts migrations
npm test
npm run typecheck
npm run lint
npm run build
npm audit --audit-level=high
```

On Linux use `.venv/bin/python` instead. In a restricted Windows sandbox, use a new workspace-local `--basetemp` and `-o cache_dir=...` if the shared system temp/cache directory is inaccessible. This changes storage locations, not test assertions.

The tests cover real domain functions, provider HTTP contracts, citations, malformed output, native tool observations, retries, rate limits, cross-session access, persistence, queue execution, timeouts, stale jobs, retention, and frontend failure states. Test fixtures are synthetic and explicitly labeled; production never imports them. See [actual verification results](docs/VERIFICATION.md).

Frontend lint targets authored application/test code. The generated `components/ui` catalog and its helper hook are retained as supplied, rather than rewritten to satisfy application-specific lint rules. The HTTP session-bootstrap effect has a documented, local React-compiler lint exception; updates occur after asynchronous API work.

Optional local-model smoke test (real inference, synthetic search fixture, no search API requests):

```powershell
.\.venv\Scripts\python.exe -m scripts.live_ollama_smoke --model YOUR_LOCAL_MODEL
```

## Privacy, scope, and limitations

History uses Starlette's signed, HttpOnly, SameSite=Strict browser session, with Secure cookies in production. Every history read and delete filters by session owner. There are no account passwords, login flow, or cross-device recovery. Clearing cookies or rotating the signing secret loses access; exported JSON contains the report and should be treated as private.

Search snippets are leads, not verified full-page evidence. Quote matching proves that a quote exists in a retrieved snippet, not that the model's interpretation is correct. The app cannot establish sales, demand, profitability, or future performance from snippets. Prices can refer to accessories, shipping, or outdated offers. Margins are user-input scenarios, not forecasts. All reports show limited evidence quality.

Other current constraints: one API process/worker; no automatic retry of crashed jobs; no report cancellation while running; no full-page retrieval; no factual entailment checker; no account recovery; no visual browser accessibility audit; Docker and PostgreSQL runtime checks require an external environment. Vinext remains a beta build dependency even though only static output is deployed. See [security and reliability review](docs/SECURITY.md).

## Deployment and next improvements

The repository includes a Dockerfile, PostgreSQL Compose example, migrations, CI, and [deployment instructions](docs/DEPLOYMENT.md). No deployment or public URL has been created. No external account credentials were used, no infrastructure was purchased, and the project has not been migrated to WSL.

Before inviting users: pass a real-provider acceptance run, test PostgreSQL and the container on the intended host, configure HTTPS/backups/provider spend caps, and perform keyboard/mobile/browser QA. Then prioritize claim-evidence evaluation, useful independent sources, cancellation, and established OIDC authentication if cross-device accounts become necessary. Keep the single-agent architecture until a specific product requirement justifies changing it.

### Diagnose real research

With a locally installed `qwen3.5:4b` (`ollama pull qwen3.5:4b`) and your Tavily key configured, run `python -m scripts.diagnose_research --live` from the project root. This explicitly uses real provider resources and records private diagnostic artifacts under ignored `work/diagnostics/`. It exercises the real API, isolated SQL queue, worker, model, search, validation, and persistence without modifying normal report history. Restart the backend after changing `OLLAMA_MODEL`.
