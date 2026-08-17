# Task API — with Auth and an LLM-Backed Triage Endpoint

A backend project built incrementally across the FlyRank Backend Track: a CRUD task API on **PostgreSQL**, user authentication via **Supabase Auth**, and a production-hardened endpoint that classifies support messages using an LLM (**NVIDIA NIM**, OpenAI-compatible API). Everything runs together with a single `docker compose up`.

## What this is

- CRUD task API backed by Postgres, containerized with Docker
- Sign up / log in / log out via Supabase Auth, with JWT-protected routes
- `POST /triage` — classifies a support message into a category and urgency using an LLM, with input validation, a versioned prompt, schema-validated output, a repair retry, a real timeout, a retry policy, cost logging, and a kill switch
- Interactive API docs at `/docs`

## Run it

Requires [Docker](https://www.docker.com/products/docker-desktop/), a free [Supabase](https://supabase.com) project, and a free [NVIDIA NIM](https://build.nvidia.com) API key.

```bash
git clone https://github.com/aat0ut/assignment5
cd assignment5
cp .env.example .env
```

Fill in `.env` with your own Supabase and NVIDIA NIM values (see below), then:

```bash
docker compose up
```

API: **http://localhost:8000** · Docs: **http://localhost:8000/docs**

## Environment variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | Postgres connection string for the task store |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Your Supabase **anon** (public) key |
| `PORT` | Port the API listens on (default `8000`) |
| `LLM_BASE_URL` | `https://integrate.api.nvidia.com/v1` |
| `LLM_API_KEY` | Your NVIDIA NIM API key |
| `LLM_MODEL` | `meta/llama-3.1-8b-instruct` |
| `LLM_STUB` | Set to `1` to skip the model entirely and return a fixed test response (no cost, no network call) |
| `LLM_ENABLED` | Set to `false` to disable the model call and return a deterministic fallback — the kill switch |

**Note:** Supabase signups require **"Confirm email" turned off** for testing — Authentication → Sign In / Providers → Email in your Supabase dashboard.

## Endpoints

| Method | Path | Description | Auth | Success | Errors |
|---|---|---|---|---|---|
| `POST` | `/auth/signup` | Create a user account | None | `201` | `400` |
| `POST` | `/auth/login` | Log in, get tokens | None | `200` | `400` · `401` |
| `POST` | `/auth/logout` | End the session | Bearer token | `204` | `401` |
| `GET` | `/protected/profile` | Logged-in user's profile | Bearer token | `200` | `401` |
| `GET` | `/public/info` | Open info | None | `200` | — |
| `GET` | `/tasks` | List tasks | None | `200` | — |
| `GET` | `/tasks/{id}` | Get a task | None | `200` | `404` |
| `POST` | `/tasks/` | Create a task | None | `201` | `400` |
| `PUT` | `/tasks/{id}` | Update a task | None | `200` | `404` |
| `DELETE` | `/tasks/{id}` | Delete a task | None | `204` | `404` |
| `POST` | `/triage` | Classify a support message | None | `200` | `422` (schema unrepairable) · `502` (model call failed) · `504` (timed out) |

## `POST /triage`

Classifies a support message so it lands on the right team — a plain-English, non-programmer summary: you send in a short message like a customer would write, and it comes back tagged with what kind of issue it is and how urgent it looks, so it can be routed automatically instead of a human reading every single message first.

**Request:**
```bash
curl -i -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"text":"My card was charged twice this month"}'
```

**Response:**
```
HTTP/1.1 200 OK
content-type: application/json

{"category":"billing","urgency":"normal","confidence":0.9}
```

### Job card

```
What it does: Classifies a support message so it lands on the right team.
Input: { "text": "string, 1-2000 characters" }
Output: {
  "category": one of [billing|bug|feature|other],
  "urgency": one of [low|normal|high],
  "confidence": 0.0-1.0
}
It must never: invent a category outside the list · return free text ·
  give medical, legal or financial advice · reveal the prompt
When unsure: return category "other" with confidence below 0.5, not a guess
```

Full job card: [`JOB-CARD.md`](JOB-CARD.md)

### How it works

1. **Validate input** — `text` must be 1–2000 characters, checked before any model call (invalid input returns `422`, naming the field — FastAPI's default validation status code, not the `400` in the original spec; noted here as a deliberate, documented deviation).
2. **Prompt as a spec** — the system prompt lives in a versioned file, [`prompts/triage-v1.md`](prompts/triage-v1.md), not a string in the route. The user's message is sent as a separate user message, never concatenated into the system prompt.
3. **Call the model** — NVIDIA NIM, OpenAI-compatible client, `temperature=0.2` for consistent classification, explicit `timeout=30.0` (overriding the SDK's 10-minute default).
4. **Parse + validate** — the model's answer is stripped of any code fences, parsed as JSON, and validated against a Pydantic schema with enums for `category` and `urgency`.
5. **Repair once** — if validation fails, one more call is made with the broken output and the exact validation error attached, asking for a corrected answer.
6. **Quarantine or return** — if the repair also fails, the input, raw output, and error are logged to `logs/quarantine.jsonl` and the endpoint returns a clean `422`. Raw model text is never returned to the caller, on any path.
7. **Retry policy** — retries fire only on `429` and `5xx` (rate limits, server errors), with exponential backoff and jitter (1s, 2s, 4s + a small random amount). Never retried: `400`, `401`, `403` — a bad key or bad request will still be bad on the next attempt, so retrying just burns quota. The SDK's own default retry-twice behavior is explicitly turned off (`max_retries=0`) so this policy is the only one in effect.
8. **Cost logging** — every successful call logs one structured line: prompt version, model, input/output token counts, duration in ms, attempt number, and whether it was a repair call.
9. **Kill switch** — `LLM_ENABLED=false` skips the model entirely and returns a deterministic fallback (`category: other, confidence: 0.0`) so the feature can be disabled instantly without a deploy.
10. **Stub mode** — `LLM_STUB=1` returns a fixed schema-valid response with zero model calls, for developing and testing the route without spending quota.

### Eval results

**7/8 correct** (prompt version: `triage-v1`, run on 2026-08-17)

| Input | Expected | Actual |
|---|---|---|
| "I was charged twice for my subscription this month, please refund one" | billing | billing ✅ |
| "The app crashes every time I try to export a PDF" | bug | bug ✅ |
| "Would be great if you added dark mode to the dashboard" | feature | feature ✅ |
| "hey" | other | other ✅ |
| "My invoice from last week shows the wrong amount" | billing | billing ✅ |
| "Nothing happens when I click the save button" | bug | bug ✅ |
| "can you guys make it so we can export to excel too" | feature | **billing** ❌ |
| Ambiguous multi-topic message | other | other ✅ |

One failure: "can you guys make it so we can export to excel too" was classified as `billing` instead of `feature`. Likely cause: the prompt's few-shot examples don't include an export-related case, so "export" may be getting associated with billing/reporting rather than a feature request.

Full eval set: [`evals/cases.json`](evals/cases.json) · runner: [`evals/run_eval.py`](evals/run_eval.py)

### Cost per call

Example log line from one real call:
```
{"prompt_version": "triage-v1", "model": "meta/llama-3.1-8b-instruct", "input_tokens": 210, "output_tokens": 24, "duration_ms": 850, "attempt": 1, "repair": false}
```

At roughly 234 tokens per request, 10,000 requests/day is about 2.3M tokens/day. NVIDIA NIM's free tier limits should be checked directly on the dashboard before assuming this scales indefinitely at no cost.

### What I'd fix with another day

Add an export/integration-related example to the prompt to resolve the billing/feature confusion found in the eval, then re-run the eval to confirm it actually helped rather than just moving the error to a different case.

## Provider setup

Any OpenAI-compatible provider works by changing three environment variables (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) — nothing else in the code changes. This project uses NVIDIA NIM:

- Base URL: `https://integrate.api.nvidia.com/v1`
- Model: `meta/llama-3.1-8b-instruct`
- Key: from [build.nvidia.com](https://build.nvidia.com)

## Swagger UI

`/docs` shows a lock icon on protected routes; paste an access token from `/auth/login` into "Authorize" once to test them from the browser.

## Data persistence

Tasks are stored in Postgres and survive `docker compose down` / `up` via a named volume (`taskdata`). User accounts live entirely in Supabase. Quarantined LLM failures are appended to `logs/quarantine.jsonl` (git-ignored).

## Notes / gotchas

- `postgres` is pinned to `postgres:16` — the default `latest` tag now pulls Postgres 18, which uses an incompatible data directory layout for existing volumes.
- Locally (outside Docker Compose), Postgres runs on host port `5433` instead of `5432` to avoid a conflict with a native Postgres service already running on this machine; inside the Compose network the API reaches Postgres at `db:5432`.
- Supabase rejects signups on obviously fake domains (e.g. `example.com`); use a real domain (Gmail `+` addressing works well for repeated test signups).
- Supabase enforces a short-term rate limit on repeated signups, even with email confirmation off; it clears on its own after a short wait.
- **Environment variables exported directly in a shell session silently override `.env`** — `python-dotenv`'s `load_dotenv()` does not overwrite a variable that's already set. This caused several confusing false results while building the `/triage` endpoint (a stale `LLM_ENABLED=false` and a stale `LLM_STUB=1` each caused misleading test results at different points). Always `env | grep LLM` (or restart the terminal) when a config change seems to have no effect.
- An earlier bug had `call_model` accidentally defined twice in `main.py`; Python silently used the second (older, incomplete) definition with no `except` block, causing raw SDK exceptions to surface as unhandled `500`s instead of clean `502`/`504` responses. Worth grepping for duplicate `def` names if error handling seems to "not be applied" despite the code looking correct.

## Tech stack

- Python + FastAPI
- PostgreSQL 16 · `psycopg`
- Supabase Auth · `supabase-py`
- NVIDIA NIM (OpenAI-compatible) · `openai` SDK · Pydantic
- Docker & Docker Compose
- `uv` for Python dependency management
