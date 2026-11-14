# JobPilot

An AI agent that finds fresh hiring posts on X (Twitter), filters them against
your profile, writes a post-specific reply and DM, sends them when it is
confident, and asks you first when it is not.

JobPilot is multi-user: every account gets its own workspace, profile, resumes,
X session, jobs, keyword history and outreach log.

---

## Highlights

- **Finds jobs two ways** - a keyword search plus a deep scroll of your home
  feed. When the queue is empty it keeps scrolling the feed on a short timer.
- **Filters hard before spending money on a model** - job-seeker posts,
  duplicates (including the same job reposted by another account), fake/scam
  posts, non-tech roles and roles that demand more experience than you have.
- **Writes specific messages, not templates** - every draft must reference a
  concrete detail from the post. Generic drafts are rewritten once, then always
  wait for a human.
- **Two AI paths** - any OpenAI-compatible API key (OpenAI, Gemini, OpenRouter,
  ...) or, with no key at all, a logged-in ChatGPT session driven in Chromium.
- **Learns keywords** - scores them by real outcomes, ranks replies twice as
  highly as "looks relevant", and lets you pin keywords that must always run.
- **Background analyst and watcher** - ChatGPT grades the keywords and reports
  whether the outreach is healthy, what broke and what to do next.
- **GitHub aware** - pulls your public repos, languages and top projects so
  messages can cite real work instead of adjectives.
- **DM safeguards** - per-person limits, follow-ups, closed-inbox detection,
  transient-failure retries and daily caps.

---

## How it works

```
                     +---------------------------+
                     |  scan every N minutes     |
                     +-------------+-------------+
                                   |
              home feed + keyword searches on X
                                   |
                     +-------------v-------------+
                     | local filters (no LLM)    |
                     | seekers, fakes, dupes,    |
                     | domain, experience gate   |
                     +-------------+-------------+
                                   |
                    relevance score (deterministic)
                                   |
                     +-------------v-------------+
                     |  draft reply + DM (LLM)   |
                     |  + confidence + doubts    |
                     +-------------+-------------+
                                   |
                     +-------------v-------------+
                     | decide: queue or ask you  |
                     +-------------+-------------+
                                   |
                     +-------------v-------------+
                     | executor: reply, DM,      |
                     | follow, email, apply link |
                     +-------------+-------------+
                                   |
                     +-------------v-------------+
                     | log + keyword score +     |
                     | inbox + analyst + watcher |
                     +---------------------------+
```

Posts with an external apply link never get a reply or DM. They land in the
**Apply links** tab, where you apply yourself.

---

## Message rules

- A draft must mention the role, company, product, stack or problem from the
  post. `composer.is_generic()` checks this and caps the confidence if it fails.
- Approved (often edited) drafts are stored as style examples, so the voice
  converges on yours.
- One DM per person is not the rule: follow-ups are allowed up to a hard cap,
  with a minimum gap. After that the person gets public replies only.
- When X says the inbox is closed, the job is removed from the queue, the handle
  is remembered, and no future DM is attempted.
- Transient chat failures ("chat did not finish loading") are retried later with
  the reason attached, never blindly.

---

## Safety rails

| Rule | Where |
| --- | --- |
| Never retry a write with an unknown outcome | `pipeline._apply_write_result` |
| Reply confirmed from X's `CreateTweet` response | `executor/scripts/replyToPost.js` |
| DM confirmed only after it persists after a reload | `executor/scripts/sendDm.js` |
| One browser action at a time | `services/executor.SCRIPT_LOCK` |
| Daily caps, minimum gap, quiet hours before every write | `services/limits.py` |
| Red-flag posts (`unpaid`, `commission-only`, ...) always need a human | `agents/composer.BLOCKERS` |
| Fake/scam posts rejected by score | `agents/spam.py` |
| Closed inbox removed from the DM queue permanently | `pipeline._send_one` |
| Cookies encrypted at rest, never returned by the API | `security.py` |
| X password typed into X's own form and never stored | `executor/scripts/loginWithPassword.js` |
| External apply links never trigger a reply or DM | `pipeline.scan` |

---

## Repository layout

```
job_apply/
  backend/
    app/
      main.py                 FastAPI entry point
      models.py               users, profile, resumes, x_account, settings, jobs, runs, insights
      llm.py                  OpenAI-compatible JSON client (key + model rotation)
      agents/
        resume.py             resume -> structured profile
        discovery.py          queries, relevance scoring, domain/experience gates
        composer.py           reply + DM drafts, confidence, blockers
        keywords.py           search vocabulary and the X query formula
        query_lab.py          keyword testing, scoring, pinning
        spam.py               fake/scam post detection
        analyst.py            ChatGPT keyword review
        watcher.py            ChatGPT activity report
        job_filter.py         ChatGPT fit screen for Approvals / Apply links
        inbox.py              incoming reply tracking
      services/
        pipeline.py           the single flow: scan -> draft -> decide -> send
        executor.py           spawns Node scripts, parses RESULT_JSON
        scheduler.py          background loop (scan, send, idle feed, inbox)
        github_profile.py     public GitHub sync
        browser_chatgpt.py    ChatGPT in Chromium (no API key)
        limits.py, accounts.py, mailer.py, resume_store.py, tasks.py
      routers/                auth, profile, accounts, settings, jobs, runs, llm
    executor/                 Node + Playwright
      scripts/                search, feed, reply, dm, follow, login, chatgpt, inbox
      utils/                  browser, cookies, humanize, minimize, report
    tests/                    offline test suite
    alembic/                  migrations
  frontend/                   Next.js 15 + Tailwind (X Pilot theme)
    app/onboarding            4-step setup wizard
    app/(workspace)/          dashboard, posts, approvals, apply links,
                              outreach, profile, activity, settings
    components/               UI primitives, job card, forms
```

---

## Setup

### 1. Backend

```powershell
cd job_apply/backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Generate the cookie-encryption key and put it in `.env`:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Model access is optional. Set any OpenAI-compatible provider:

```env
LLM_API_KEYS=key1,key2
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=gemini-flash-lite-latest,gemini-3.6-flash
```

Without a key the app still runs: deterministic scoring, template drafts, and
everything waits in Approvals. You can also connect ChatGPT in the browser from
Settings, so no API key is required for analysis or drafts.

Start it:

```powershell
uvicorn app.main:app --reload --port 8000
```

### 2. Executor

```powershell
cd job_apply/backend/executor
npm install
npx playwright install chromium
```

Optional: set `BROWSER_CHANNEL=chrome` to drive installed Chrome.

### 3. Frontend

```powershell
cd job_apply/frontend
npm install
npm run dev
```

Open <http://localhost:3000>. Override the API with
`NEXT_PUBLIC_API_URL=http://host:8000`.

---

## First run

Opening the app starts a 4-step wizard:

1. **Resume** - upload PDF/DOCX/TXT. Name, contact, links, skills, roles and
   experience are extracted. GitHub/LinkedIn/portfolio are also read from PDF
   link annotations. Every field stays editable.
2. **Job search** - target roles, seniority, salary floor, "not a fit" roles and
   optional extra keywords.
3. **Connect X** - a visible browser fills X's own login form. Only cookies are
   stored (encrypted); the password is never saved or logged. Choose whether the
   agent may reply publicly and send DMs.
4. **Review** - summary, then finish.

After that: Dashboard, Found posts, Approvals, Apply links, Outreach, Profile,
Activity and Settings.

- **Profile** - edit extracted details, manage multiple resumes, see basic
  GitHub stats and refresh them.
- **Settings** - schedule, thresholds, caps, quiet hours, reply/DM switches,
  keyword pins, ChatGPT connection and analyst controls.
- **Scan now** starts a run immediately; otherwise the agent follows its own
  schedule.

---

## AI configuration

Two independent paths, tried in this order where configured:

1. **API keys** - any OpenAI-compatible endpoint. Multiple keys and models are
   rotated automatically; quota/auth errors put a key on cooldown and overloaded
   models are skipped.
2. **ChatGPT in Chromium** - open Settings, press **Connect ChatGPT**, log in
   once in the window that opens. The session is stored in its own browser
   profile. The analyst, watcher, job-fit screen and draft fallback can all use
   it, and it keeps working when API keys run out.

ChatGPT is an advisor only: it never finds posts and never sends anything. The
agent still owns discovery and delivery.

---

## Keyword lab

- Scans run up to four keywords: three pinned keywords (least recently used
  first) plus one exploration slot.
- Pinned keywords are never auto-retired or deleted.
- Score uses real outcomes: `(relevant + 2 * replies + 0.5) / (seen + 2)`.
- Weak unpinned keywords are retired after a few tries.
- Click any keyword chip in Settings to pin or unpin it.

---

## API (selected)

```
GET    /api/health
GET    /api/dashboard

GET/PUT /api/profile
POST   /api/profile/resume            multipart file
POST   /api/profile/github/sync

GET/POST /api/accounts
DELETE /api/accounts/{id}

GET/PUT /api/settings
GET    /api/settings/status

POST   /api/runs/scan
POST   /api/runs/send
GET    /api/runs

GET    /api/jobs?status=&q=&has_link=&sort=
POST   /api/jobs/{id}/decide
POST   /api/jobs/{id}/send
POST   /api/jobs/{id}/redraft
POST   /api/jobs/{id}/retry-dm
POST   /api/jobs/ai-filter
POST   /api/jobs/{id}/report-fake

GET    /api/keywords
POST   /api/keywords/pin

GET/POST /api/llm/keys
POST   /api/llm/chatgpt/connect
GET    /api/llm/insights/latest
GET    /api/llm/watcher/latest
```

---

## Tests

```powershell
cd job_apply/backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

The suite is fully offline: no X, no model provider, no network.

---

## Production notes

Set these in `backend/.env` before deploying:

```env
AUTH_ENABLED=true
JWT_SECRET_KEY=<long random string, keep it stable>
CREDENTIALS_ENCRYPTION_KEY=<Fernet key, keep it stable>
ACCESS_TOKEN_EXPIRE_MINUTES=120
REFRESH_TOKEN_EXPIRE_DAYS=30
CORS_ORIGINS=https://your-domain.example
```

- Access tokens last 2 hours. Refresh tokens last 30 days and rotate on every
  refresh.
- Existing pre-multi-user rows (`user_id IS NULL`) are claimed by the first
  account that registers on that database.
- Migrations: `alembic upgrade head` in `backend/`.
- Run a **single** Uvicorn worker. The scheduler uses a file lock so only one
  process scans and sends; additional workers stay API-only.
- Put HTTPS in front, back up the database, and alert when the newest scan is
  older than ~45 minutes.
- The Playwright browser profile is persistent and must live on a persistent
  disk.

---

## Deliberate limits

- **Scraping, not the official X API.** A real logged-in browser session is used.
  Keep volumes low; X can challenge or rate-limit any account.
- **One flow per user.** No workflow builder and no second pipeline - one scan,
  one decision point, one outreach path.
- **ChatGPT in the browser depends on its page markup.** It is slower than an API
  and can break when OpenAI changes the UI.
- **Approvals are the safety valve.** Auto-send never bypasses caps, cool-down or
  the fake-post checks.

---

## License

Private project. Add a license before distributing.
