# Task API — with Supabase Auth

A CRUD task API built with **FastAPI**, **PostgreSQL**, and **Supabase Auth**. This assignment adds real user authentication on top of the containerized stack from the previous assignment — Supabase handles account storage, password hashing, and JWT signing; this API's job is to receive tokens, verify them with Supabase, and guard protected routes accordingly.

## What this is

- Sign up / log in / log out via **Supabase Auth** (no passwords stored or hashed by this app)
- JWT (access token) verification on protected routes via a reusable FastAPI dependency
- A public route open to anyone, and protected routes that require a valid bearer token
- Interactive API docs at `/docs` with a working "Authorize" flow (Swagger bearer auth)
- Same Postgres-backed task CRUD from the previous assignment, still running underneath

## Run it

Requires [Docker](https://www.docker.com/products/docker-desktop/) (or Podman) installed and running, and a free [Supabase](https://supabase.com) project.

```bash
git clone <your-repo-url>
cd <your-repo-folder>
cp .env.example .env
```

Then fill in `.env` with your own Supabase project values (see below), and start everything:

```bash
docker compose up
```

The API will be available at **http://localhost:8000**, with interactive docs at **http://localhost:8000/docs**.

## Environment variables

Copy `.env.example` to `.env` and fill in your own values — get `SUPABASE_URL` and `SUPABASE_KEY` from your Supabase project's **Settings → API** page (use the **anon** key, never the `service_role` key).

| Variable | Description |
|---|---|
| `DATABASE_URL` | Postgres connection string for the task store |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Your Supabase **anon** (public) key |
| `PORT` | Port the API listens on (default `8000`) |

**Note:** for signups to work, your Supabase project needs **"Confirm email" turned off** during testing — go to **Authentication → Sign In / Providers → Email** in your Supabase dashboard and disable it. (In production you'd leave this on.)

## Endpoints

| Method | Path | Description | Auth required | Success | Errors |
|---|---|---|---|---|---|
| `POST` | `/auth/signup` | Create a new user account | None | `201` | `400` missing/empty fields |
| `POST` | `/auth/login` | Log in, receive access + refresh tokens | None | `200` | `400` missing fields · `401` invalid credentials |
| `POST` | `/auth/logout` | End the current session | **Bearer token** | `204` | `401` missing/invalid/expired token |
| `GET` | `/protected/profile` | Read the logged-in user's profile | **Bearer token** | `200` | `401` missing/invalid/expired token |
| `GET` | `/public/info` | Open, unauthenticated info | None | `200` | — |
| `GET` | `/tasks` | List all tasks | None | `200` | — |
| `GET` | `/tasks/{id}` | Get a single task | None | `200` | `404` |
| `POST` | `/tasks/` | Create a task | None | `201` | `400` |
| `PUT` | `/tasks/{id}` | Update a task | None | `200` | `404` |
| `DELETE` | `/tasks/{id}` | Delete a task | None | `204` | `404` |

### Example: protected route without a token

```bash
curl -i http://localhost:8000/protected/profile
```

```
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Access token required"}
```

### Example: protected route with a valid token

```bash
curl -i http://localhost:8000/protected/profile \
  -H "Authorization: Bearer <your_access_token>"
```

```
HTTP/1.1 200 OK
content-type: application/json

{"id":"...","email":"you@example.com","created_at":"..."}
```

## Auth flow

1. `POST /auth/signup` — client sends `email` + `password`, Supabase creates the account.
2. `POST /auth/login` — client sends credentials, Supabase validates them and returns an `access_token` (JWT) and `refresh_token`.
3. The client attaches the access token to protected requests as `Authorization: Bearer <token>`.
4. This server verifies the token with Supabase (`get_user`) on every protected request — a real network call, so a forged or tampered token is always rejected, not just pattern-matched.
5. `POST /auth/logout` ends the session (also a protected route, using the same guard).

The token check lives in a single reusable FastAPI dependency (`get_current_user` in `auth.py`), applied to any route that needs protection — adding a new protected route requires no new auth code, just `Depends(auth.get_current_user)`.

## Swagger UI

FastAPI serves interactive docs at `/docs` with a working "Authorize" padlock. Paste an access token from `/auth/login` into the Authorize dialog once, and it's automatically attached to every subsequent "Try it out" call on protected routes.

![Swagger Authorize dialog](screenshots/swagger-authorize.png)
![Successful protected route call](screenshots/swagger-profile-response.png)

## Data persistence

Tasks are stored in Postgres and persist across `docker compose down` / `up` via a named volume (`taskdata`). User accounts and sessions are managed entirely by Supabase — nothing auth-related is stored in this app's own database.

## Notes / gotchas

- Supabase rejects signups using obviously fake domains (e.g. `example.com`, `test.com`) — use a real domain. Gmail's `+` addressing (`you+test1@gmail.com`) is useful for repeated test signups without burning real addresses.
- Supabase enforces an email-related rate limit on repeated signups even with email confirmation off; hitting it returns `{"detail":"email rate limit exceeded"}` and clears on its own after a short wait.
- The `postgres` image is pinned to `postgres:16` (see previous assignment's notes) to avoid a data-directory incompatibility introduced in Postgres 18.
- Locally (outside Docker Compose), Postgres runs on host port `5433` instead of `5432` to avoid conflicting with a native Postgres service already running on this machine. Inside the Compose network, the API reaches Postgres at `db:5432` — unaffected by the host-side remap.

## AI vs me

<!-- Fill in after Stage 7: your prompt, what the AI got right/wrong, and what your original prompt missed. -->

## Tech stack

- Python + FastAPI
- PostgreSQL 16
- `psycopg` (task storage)
- Supabase Auth + `supabase-py` (authentication)
- Docker & Docker Compose
- `uv` for Python dependency management
