# JobPilot — one flow, X job outreach agent

An agent that does exactly one job:

> finds **fresh** hiring posts on X (Twitter) that match your resume, writes a
> public reply and a personal DM, sends them when it is sure — and asks you
> first when it is not.

Built on the same patterns as the two reference repos
([`twitter-account-management`](https://github.com/Crux-Sphere/twitter-account-management)
+ its backend): FastAPI + SQLAlchemy, a Node/Playwright executor with the
`RESULT_JSON` script contract and cookie-based sessions, and a Next.js UI.
The difference is scope — no workflow builder, no action library, no n8n clone.
One pipeline, one screen, one decision point.

---

## The flow

```
  scan (every N min or "Scan now")
    │
    ├─ 1. build X search queries from your profile
    │       ("we're hiring" OR "job opening") (react developer OR backend engineer)
    │       -filter:replies lang:en since:<lookback>
    │
    ├─ 2. Playwright reads X's Latest tab  →  fresh posts only
    │
    ├─ 3. drop: duplicates, your own posts, replies, promoted, older than lookback
    │
    ├─ 4. LLM scores each post against your resume      (0-100)
    │       < threshold → skipped
    │
    ├─ 5. LLM drafts the public reply + the DM
    │       and returns a confidence + its own doubts
    │
    ├─ 6. DECISION
    │       relevance ≥ threshold
    │       AND confidence ≥ auto-send confidence
    │       AND no blockers / red flags / unresolved doubts
    │          → queued  (auto-send)
    │       else
    │          → pending_approval  (you decide)
    │
    ├─ 7. executor: reply → DM
    │       DM blocked? → follow → retry DM once (follow is never used otherwise)
    │       caps, cool-down, quiet hours, never retry an unknown write
    │
    └─ 8. every step is logged; the UI shows what happened and why
```

Fake postings are scored before drafting (`agents/spam.py`): money asked from
the candidate, off-platform contact, "no interview / direct joining", earnings
bait, missing role or company. Score ≥ 60 is rejected, 40-59 always needs a
human, and a post can never be auto-sent if it looks even slightly fake.

**Why the approval split matters:** X is hostile to bursts of identical
outreach. The agent is deliberately conservative — template drafts, low
confidence, red flags (`unpaid`, `commission-only`, …), or an application that
goes to an email/link instead of a DM all land in your approval queue.

### Messages are post-specific (and learn from you)

- Every draft must reference a concrete detail from the post: the role, the
  company, the stack they listed, or the problem. The composer checks this with
  `composer.is_generic()`; a draft that could be pasted anywhere is flagged
  “generic”, its confidence is capped, and it always waits for you.
- When you approve a post (usually after editing), that final reply + DM is
  stored as a style example. The next drafts get your last 3 approved examples
  as few-shot guidance, so the voice converges on yours.
- Every message includes your portfolio / GitHub link once.

### How a post is actually applied to

The agent reads the post and routes it:

| Post says | Method | What happens |
| --- | --- | --- |
| “DM me” | `dm` | public reply → DM (follow only if X blocks it) |
| “mail your resume to …” | `email` | application email with your resume attached |
| “apply here: <link>” / form | `link` | **never auto-sent** — waits in Approvals with the link |

Email needs SMTP configured in `backend/.env` (`SMTP_*`). Without it, email
posts simply wait in Approvals. Gmail uses an App Password.

### Targeting rules
- **Roles are not a hard limit.** You pick one or more roles; the first is the
  primary focus. The agent also searches *adjacent* roles inferred from your
  skills (React → React Developer, Node → Node.js Developer, …), so it never
  narrows itself to your exact title.
- **The agent learns search keywords.** Every scan it runs up to three
  keywords: the two with the best track record plus one it has not tried yet.
  A keyword is scored by *relevant posts / posts read*. Winners become `active`
  and are reused; weak ones are deleted after a few tries, so the list stays
  small. See it under Settings → Search keywords.
- **Domain gating.** The resume is classified as `tech` or `non-tech`. A tech
  resume never gets sales/marketing posts, and a non-tech resume never gets
  engineering posts.
- **Not a fit.** Anything you mark in “Which roles are not a fit?” is skipped
  before drafting (matched as a keyword in the post).
- **Experience gate.** The post’s stated requirement is parsed (`2-5 years`,
  `3+ yrs`, `fresher`). If it needs meaningfully more experience than you have,
  the post is rejected before any draft — no point applying.
- **Location is never used.** It is not a filter and it is not compared. The
  scoring prompt explicitly tells the model to ignore city, country and
  on-site requirements.
- **Two experience buckets only:** Fresher or Experienced.

---

## Repository layout

```
job_apply/
  backend/
    app/
      main.py                  FastAPI entry point
      models.py                profile, x_account, agent_settings, job_post, run, action_log
      llm.py                   OpenAI-compatible JSON client (works with OpenRouter, OpenAI, …)
      agents/
        resume.py              resume → structured profile (LLM + offline fallback)
        discovery.py           profile → search queries, relevance scoring
        composer.py            reply + DM drafts + confidence + blockers
      services/
        pipeline.py            THE flow: scan → rank → draft → decide → send
        executor.py            spawns Node scripts, parses RESULT_JSON
        accounts.py            password sign-in, encrypted cookie storage
        limits.py              daily caps, cool-down, quiet hours
        scheduler.py           background agent loop
        tasks.py               background runs so the API never blocks
      routers/                 health, profile, accounts, settings, jobs, runs
    executor/                  Node + Playwright scripts
      scripts/
        loginWithPassword.js   fill X's login form, return session cookies
        searchJobs.js          read X's Latest search tab
        replyToPost.js         post a public reply (CreateTweet = ground truth)
        sendDm.js              send a DM (composer clears + bubble appears = success)
      utils/                   browser, cookies, humanize, report, targetPost
    tests/                     offline API + flow + onboarding tests
    requirements.txt
  frontend/                    Next.js 15 + Tailwind v4 (X Pilot theme)
    app/onboarding/page.tsx    4-step wizard: resume → job search → connect X → review
    app/(workspace)/layout.tsx sidebar shell + onboarding guard
    app/(workspace)/dashboard   command center
    app/(workspace)/posts       every post the agent read
    app/(workspace)/approvals   drafts that need a human
    app/(workspace)/profile     resume + basic info + job preferences (editable)
    app/(workspace)/settings    agent behaviour, guard rails, X account
    app/(workspace)/activity    scan / send runs
    components/                 shadcn-style primitives, sidebar, job card, forms
```

---

## Setup

### 1. Backend

```powershell
cd job_apply/backend
py -3.11 -m venv .venv          # 3.11+ works; 3.14 tested
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Generate the cookie-encryption key and paste it into `.env`:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set `LLM_API_KEY` (any OpenAI-compatible provider; `LLM_BASE_URL` +
`LLM_MODEL` control which). Without a key the app still runs in offline mode:
keyword relevance scoring + template drafts, and **everything** goes to
approval because the template's confidence is deliberately low.

`LLM_API_KEYS` accepts a comma separated list of fallback keys, and `LLM_MODEL`
accepts a comma separated list of models. The client rotates keys on quota /
auth errors and falls through models that are retired or overloaded. Gemini
works through its OpenAI-compatible endpoint:

```env
LLM_API_KEYS=key1,key2,key3
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=gemini-3.1-flash-lite,gemini-flash-lite-latest,gemini-3.6-flash
```

```powershell
uvicorn app.main:app --reload --port 8000
```

### 2. Executor

```powershell
cd job_apply/backend/executor
npm install
npx playwright install chromium
```

Optional: `set BROWSER_CHANNEL=chrome` in the environment to drive your
installed Chrome instead of the bundled Chromium.

### 3. Frontend

```powershell
cd job_apply/frontend
npm install
npm run dev
```

Open <http://localhost:3000>. Point it elsewhere with
`NEXT_PUBLIC_API_URL=http://host:8000`.

---

## First run (onboarding)
Opening the app drops you into a 4-step wizard. One job per step, and nothing
you have to type twice.

1. **Resume.** Upload a PDF/DOCX/TXT. The extractor fills only what you need when
   applying: name, email, phone, location, links, current role/company, skills
   and total experience (in months, derived from the "Present" date range when
   the resume does not state it). PDF hyperlinks are read from the file's link
   annotations, so GitHub/LinkedIn/portfolio fill even when they are icons.
   (There is a "type it myself" escape hatch.)
2. **Job search.** Pick the job title the agent should hunt for — a tech title
   chip or anything you type. Then where you can work, seniority, salary floor,
   "not a fit", and optional extra keywords.
3. **Connect X.** Handle + password. A visible browser opens and fills X's own
   login form; only `auth_token` / `ct0` / `twid` are stored (encrypted) and the
   password is never written anywhere. Choose what the agent may do — find posts
   (always), public reply, send DM. If DMs are on, add your X chat passcode.
4. **Review.** One summary, then **Finish setup**.

After that the sidebar has Dashboard, Found posts, Approvals, Profile, Activity
and Settings.

- **Profile** — re-upload your resume or edit any extracted detail later.
- **Settings** — agent schedule, relevance threshold, auto-send confidence,
  caps, cool-down, quiet hours, reply/DM switches, and reconnect X.
- **Scan now** on the dashboard starts a run immediately; otherwise the agent
  scans on its schedule.

Want to see the UI without connecting X? Seed a labelled demo workspace:

```powershell
cd job_apply/backend
.\.venv\Scripts\python.exe -m scripts.seed_demo --ui
```

Remove the demo posts with `--clear`, and delete `backend/jobpilot.db` to start
from onboarding again.

---

## Safety rules baked into the code

| Rule | Where |
| --- | --- |
| Never retry a write whose outcome is `UNKNOWN` | `pipeline._apply_write_result`, `jobs.retry_dm` |
| A reply is confirmed from the `CreateTweet` response, not the UI | `executor/scripts/replyToPost.js` |
| A DM is confirmed only when the composer clears **and** a bubble appears | `executor/scripts/sendDm.js` |
| One browser action at a time (global script lock) | `services/executor.SCRIPT_LOCK` |
| Daily caps + minimum gap + quiet hours checked *before every write* | `services/limits.py` |
| Red-flag posts (`unpaid`, `commission-only`, …) always need a human | `agents/composer.BLOCKERS` |
| Fake/scam posts (fees, "earn per day", WhatsApp/Telegram, no role) are rejected by score | `agents/spam.py` |
| Follow happens **only** when X blocks the DM, then the DM is retried once | `pipeline._send_one` |
| "Report fake" blocks that author's future posts | `routers/jobs.report_fake` |
| Application goes to an email/link, not the author → approval | `agents/composer.blockers_for` |
| Session cookies encrypted at rest, never returned | `security.py`, `routers/accounts.py` |
| Password typed into X's form, never persisted or logged | `executor/scripts/loginWithPassword.js` |
| Dedupe by post id, skip own posts / replies / promoted | `services/pipeline.scan` |

---

## API

```
GET    /api/health
GET    /api/profile
PUT    /api/profile
POST   /api/profile/resume            (multipart: file)
GET    /api/accounts
POST   /api/accounts/connect          { username, password, verification_code?, dm_passcode? }
DELETE /api/accounts/{id}

GET    /api/settings
PUT    /api/settings
GET    /api/settings/status

POST   /api/runs/scan                 → { id, status: "running" }   (background)
POST   /api/runs/send                 → { id, status: "running" }   (background)
GET    /api/runs
GET    /api/runs/{id}

GET    /api/jobs?status=&q=
GET    /api/jobs/stats
GET    /api/jobs/{id}
POST   /api/jobs/{id}/decide          { approved, reply_text?, dm_text? }
POST   /api/jobs/{id}/send            { reply_text?, dm_text? }
POST   /api/jobs/{id}/retry-dm
DELETE /api/jobs/{id}

GET    /api/dashboard
```

---

## Tests

```powershell
cd job_apply/backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

They are fully offline: no X, no LLM provider.

---

## Deliberate limits of v1

- **One X account, one flow.** Multi-account and multiple workflows were in the
  reference product; they are out of scope here.
- **Scraping, not the X API.** Same posture as the reference repos: a real
  logged-in browser session. Expect X challenges; keep volumes low.
- **No auto-follow-up.** If the recruiter replies, you take over. That is the
  right default for a first version.
- **Approval is the safety valve, not decoration.** If you switch auto-send on,
  the caps and cool-down still apply.

---

## Auth, migrations and production notes

### First run / accounts
1. Start backend and frontend.
2. Open `http://localhost:3000` -> landing page.
3. **Get started** goes to `/signup`. Every signup creates its own workspace:
   profile, resumes, X account, jobs, runs and outreach are separate per user.
4. **Log in** goes to `/login`. Access tokens last 2 hours; refresh tokens 30 days
   and rotate on every refresh.
5. Existing data from before multi-user support (`user_id IS NULL`) is claimed by
   the first account that registers on that database.

Set these in `backend/.env` before deploying:

```
AUTH_ENABLED=true
JWT_SECRET_KEY=<long random string, keep it stable>
ACCESS_TOKEN_EXPIRE_MINUTES=120
REFRESH_TOKEN_EXPIRE_DAYS=30
CREDENTIALS_ENCRYPTION_KEY=<Fernet key, keep it stable>
```

`AUTH_ENABLED=false` disables the gate (local development / automated tests only).

### Database migrations (Alembic)
```bash
cd backend
.venv/Scripts/alembic upgrade head        # apply migrations
.venv/Scripts/alembic revision --autogenerate -m "describe change"
```
The existing SQLite database is stamped at the initial revision. New installs
should run `alembic upgrade head` instead of relying on `create_all`.

### Scheduler / worker rule
The scan + send loop runs inside the backend process. A file lock
(`backend/.scheduler.lock`, `filelock`) makes sure only **one** process owns it.
Still, run a single Uvicorn worker that is allowed to send:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

If you scale to multiple workers/replicas, only one may start the scheduler; the
others will log "agent loop already owned by another process" and stay API-only.

### Health
`GET /api/health` now checks the database, the executor, the LLM and reports
`auth_enabled`. Use it for uptime monitoring; also alert when the newest scan is
older than ~45 minutes.

### Still required before public hosting
- HTTPS reverse proxy and `CORS_ORIGINS` / `NEXT_PUBLIC_API_URL` set to real domains
- Database backup (SQLite file or move to PostgreSQL)
- Uptime + "agent stopped" alerting
- Playwright/Chromium installed on the host with a persistent disk for the browser profile
