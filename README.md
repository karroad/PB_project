# SiteForge AI — Automated Website Generation & Management Platform

One platform that turns a single instruction into a planned, designed, written, built, tested, deployed and monitored website, built to manage around 200 independent sites (and more).

```
1. BUILD     "A website about sustainable living" + chosen technology
             Requirements → Planning → Branding → Content → Images → SEO → Development → Testing
2. PREVIEW   private preview link (/preview/<slug>/, noindex): nothing published, no domain touched
3. CHANGES   "Change the headline to …", "use a dark green", "add an FAQ …"
             Revision Agent → rebuild → re-test → preview updated (repeat as often as needed)
4. PUBLISH   choose hosting + domain provider (buy a new domain or use one you own)
             Infrastructure → Development → Testing → Deployment → Verify → live + monitored
   Later changes go to the preview first; "Publish changes" makes them live as a new version.
```

| Layer | Tech |
|---|---|
| Dashboard | Next.js 15 (App Router) · TypeScript · Tailwind · Framer Motion |
| API | Python · FastAPI · SQLAlchemy 2 |
| Orchestration | Async orchestrator · job queue (memory or **Redis**) · dedicated workers |
| Database | SQLite (dev) / **PostgreSQL** (prod) |
| Live updates | Server-Sent Events · in-memory or **Redis pub/sub** event bus |
| AI text | Anthropic Claude (`claude-opus-5-5`), with a deterministic offline generator as fallback |
| AI images | Fal.ai (`flux/schnell`), with a generated SVG artwork fallback |
| Deploy | Local static hosting (+ custom-domain routing) · Docker + Traefik · Hetzner Cloud |
| Domains | Buy + manage domains via Cloudflare Registrar or OVH API · DNS · RDAP lookups |

---

## Quick start (local, no API keys needed)

**Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional: add ANTHROPIC_API_KEY / FAL_KEY
uvicorn app.main:app --port 8000
```

**Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                     # http://localhost:3000
```

For each website the user **must choose the technology and the domain provider** (Cloudflare, OVH, or "platform URL only"). The AI only shows a suggestion; it never overrides the user's choice.

Sign in with `admin@siteforge.local` / `admin123` and change it via `ADMIN_EMAIL` / `ADMIN_PASSWORD` before first start. Then type an instruction and watch the 11 agents work live.

Without an AI key the platform runs in **offline mode**: deterministic content and SVG artwork, with a small delay per log line (`SIMULATED_STEP_DELAY`) so the animation is visible. Add `ANTHROPIC_API_KEY` for real AI-written copy and `FAL_KEY` for Fal.ai images.

**Tests**

```bash
cd backend && python -m pytest tests -q
```

These run the whole pipeline end to end: generate → quality gate → deploy → verify → redeploy v2 → roll back to v1. They also cover validation errors, the approval gate, rejection, and resume.

---

## Production / scaling

```bash
cp backend/.env.example backend/.env       # set SECRET_KEY, ADMIN_PASSWORD, keys
docker compose up -d --build               # Postgres + Redis + API + 2 workers + dashboard
docker compose up -d --scale worker=6      # more parallel generation capacity
```

How it scales:

- **Stateless API replicas.** Live events go through Redis pub/sub, so any replica can stream any job.
- **Horizontal workers.** `python -m app.worker` pulls from a Redis queue. Each job is claimed atomically in the database, so it runs exactly once.
- **Configurable concurrency.** `MAX_CONCURRENT_JOBS` sets slots per worker, `AI_MAX_CONCURRENT_REQUESTS` caps AI calls, and `PROVIDER_CONCURRENCY` caps infra/deploy calls per hosting provider. Together they keep AI and provider rate limits respected.
- **Crash recovery.** Workers heartbeat. A reaper re-queues jobs whose worker stopped, and they resume from the last completed step.
- **Independent sites.** Each site has its own workspace, versioned and immutable deploy artefacts, deployment history, env vars and health record. One site failing never affects another.

> On a single host the API and workers share the `sitedata` volume. For multi-host deployments, move artefacts to object storage (S3/R2) or deploy straight to the hosting adapters.

Docker hosting adapter: `docker network create siteforge && docker compose -f infra/traefik/docker-compose.yml up -d`, then set `DOCKER_ENABLED=true`.

---

## How errors, persistence and notifications work

- **Every step is recorded.** `job_steps` holds status, progress, attempts, output and logs. `job_events` is an append-only history of every log line, transition, error (with traceback), retry, approval and rollback. The dashboard replays it on reconnect (`Last-Event-ID`).
- **Errors are classified.**
  - `RetryableError`: network, timeout, 429/5xx. Retried with exponential backoff and jitter.
  - `PipelineError`: permanent. Fails the step with an error code and a hint shown in the UI.
  - `QualityGateError`: blocks deployment.
  - Unknown exceptions are recorded as `internal_error`.
- **Safety nets.** There are per-step and per-job timeouts, and the orchestrator never leaves a job stuck in `running`. A failed job never takes down a site that is already live.
- **Auto-rollback.** If live verification fails, traffic switches back to the previous version.
- **Notifications.** Users get persistent in-app notifications (bell), live toasts for every completed step, and an optional Slack/Teams/Discord webhook (`NOTIFY_WEBHOOK_URL`). Events covered: job started, approval needed, failure, site live, site down or recovered, auto-restart.
- **Approval gates.** Hosting provisioning, DNS changes and (optionally) publishing pause the job until a person approves. Infrastructure approvals require an admin.

## Requesting changes ("comments")

Open a website → **Changes** tab → describe what to change, e.g.

```
Change the headline to "Live lighter, waste less"
Make the primary colour dark green
Add FAQ "Do you ship abroad?" answer "Yes, to 30 countries."
Add an article about "composting in small apartments"
Remove the FAQ page from the menu
```

The Revision Agent applies it, the site is rebuilt and re-tested, and the **preview** updates. With an
Anthropic key any free-form request works; offline it understands common edits (colours, dark/light theme,
fonts, headline/subtitle/tagline/name/button/email, FAQs, articles, menu pages). Every request is kept in
the change history, and published changes become a new deployment version that can be rolled back.

## Client decisions (confirmed)

| Decision | How the platform behaves |
|---|---|
| The user selects the technology | Required choice on every website; the AI only shows a suggestion |
| Build → preview → changes → publish | Sites are built to a private preview first; hosting + domain are chosen when publishing |
| The user selects the domain provider | Chosen in the Publish dialog: Cloudflare, OVH, or "platform URL only" |
| Buy new domains via the Cloudflare or OVH API | Live search with prices → purchase during the infrastructure step → DNS record → site live on its domain |
| No Shopify | Removed |
| Sites go online when the user clicks Publish | No extra sign-off needed (a site can still opt into one) |

### How domain buying works (and why it is safe)

1. When the site is created, the platform checks availability and price with the provider and rejects anything above `DOMAIN_MAX_PRICE` (default 50).
2. In the infrastructure step it re-checks the price. If `APPROVAL_DOMAIN_PURCHASE=true` (the default), an admin approves the exact amount. Set it to `false` for fully hands-off buying.
3. The order state is written to the `domains` table **before** the billable call, so a domain is never bought twice: resuming a job continues the same order.
4. If an order's result is unclear (for example, the connection drops at checkout), the domain is marked "Needs check". An admin then uses **Domains → Sync** if it was bought, or **Reset** if it wasn't.
5. The platform waits for activation, creates the A record, and the site goes live on `http://<domain>/`.

Requirements: a provider account under **Providers**. Cloudflare needs an API token plus the account ID; billing and the default registrant contact are set in the Cloudflare dashboard. OVH needs the application key, secret and consumer key, and a preferred payment method on the OVH account. The server must also be public: set `SERVER_PUBLIC_IP` (the platform then serves each site on its own domain), or use Hetzner hosting.

## Security

- Credentials are Fernet-encrypted at rest and masked in the API and UI.
- Every build is scanned for leaked keys before deployment (critical quality-gate check).
- Role-based access: admin, operator, viewer, plus per-site members. Every authorization check runs on the server.
- The audit log covers logins, changes, approvals, deployments and deletions. Deletion requires typing the site slug.
- Served sites get security headers (CSP, nosniff, frame and referrer policies) and path-traversal protection. Contact forms have rate limiting and a honeypot.

## Project layout

```
backend/app/
  agents/          11 pipeline agents + quality gate
  orchestrator/    runner (retries, approvals, resume), queue (memory/redis), recorder (persistence)
  adapters/        stacks/ (nextjs, wordpress, laravel, static) · hosting/ · dns/ (domain purchase + DNS)
  ai/              llm.py (Claude + offline), images.py (Fal.ai + SVG), offline.py
  renderer/        static build renderer (Jinja2)
  monitoring/      uptime, SSL/domain expiry, resources, auto-restart
  api/             REST + SSE endpoints
frontend/
  app/(app)/       dashboard, new, sites/[id], jobs, approvals, monitoring, providers, users, audit
  components/pipeline/   animated live pipeline (orb, timeline, terminal, celebration)
docs/CLIENT_QUESTIONS.md   decisions to confirm with the client
```

## Status of integrations

| Integration | State |
|---|---|
| Local hosting, quality gate, deploy/rollback, monitoring | Working and covered by tests |
| Next.js / WordPress / Laravel / Static project generators | Generate complete source projects. Next.js builds for real when `BUILD_NEXTJS=true` |
| Docker + Traefik hosting | Implemented. Needs Docker on the host |
| Domain purchase (Cloudflare Registrar, OVH order cart), DNS, Hetzner | Written against the providers' current API docs and covered by tests with a fake registrar. Not yet run against real accounts |
| Shopify | Removed at the client's request |
| OVH / Hostinger hosting, Astro, Django | Planned adapters (shown as "planned" in the UI) |
