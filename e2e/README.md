# End-to-end UI journey (sandbox)

Clicks through the real dashboard like a user — 25 checks covering login, provider accounts, domain
search + purchase with approval, an interrupted order + reset, publishing, all site tabs, redeploy +
rollback, archive/restore, delete, users, jobs, monitoring, audit log, notifications and sign-out.

It runs against a **sandbox** backend, so no real Cloudflare/OVH calls are made and nothing is charged.

```bash
# 1) sandbox backend on :8100 with a throwaway data dir
cd backend
DATA_DIR=/tmp/sf-sim SANDBOX_PROVIDERS=true PUBLIC_BASE_URL=http://localhost:8100 \
FRONTEND_ORIGIN=http://localhost:3000 SIMULATED_STEP_DELAY=0.12 RUN_MONITOR=false \
uvicorn app.main:app --port 8100

# 2) dashboard pointed at it
cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8100 npm run dev

# 3) the journey (needs `pip install playwright` and Microsoft Edge, or change channel= to use Chromium)
python e2e/journey.py ./e2e-screenshots
```

Use a fresh `DATA_DIR` for every run (the journey buys `candleglow.com` in the sandbox).
