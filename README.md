# JobPilot

An AI agent that finds fresh hiring posts on X (Twitter), filters them against
your profile, writes a post-specific reply and DM, and sends them when it is
confident. Anything unsure waits for your approval.

Multi-user: every account has its own profile, resumes, X session, jobs and
outreach history.

## What it does

- Scans the home feed and keyword searches, and keeps scrolling the feed when
  the queue is empty.
- Drops duplicates, job-seeker posts, fakes, non-tech roles and roles that need
  more experience than you have.
- Writes a reply and a DM for each post, using the role, your stack and your
  public GitHub projects.
- Sends when confidence is high; otherwise it asks you with the exact reason.
- Tracks keyword performance by real replies and keeps the winners.

External apply-link posts never get a reply or DM - they go to the **Apply
links** tab so you can apply yourself.

## Setup

### Backend

```powershell
cd job_apply/backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the generated key in `.env` as `CREDENTIALS_ENCRYPTION_KEY`, set
`JWT_SECRET_KEY`, then start:

```powershell
uvicorn app.main:app --reload --port 8000
```

A model API key is optional. Add any OpenAI-compatible provider to `.env`:

```env
LLM_API_KEYS=key1,key2
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=gemini-flash-lite-latest
```

No key? Connect ChatGPT in Settings and the agent uses that browser session for
analysis and draft fallback.

### Executor

```powershell
cd job_apply/backend/executor
npm install
npx playwright install chromium
```

### Frontend

```powershell
cd job_apply/frontend
npm install
npm run dev
```

Open <http://localhost:3000>. Set `NEXT_PUBLIC_API_URL` if the API is not on
`http://localhost:8000`.

## First run

1. Sign up and upload a resume (PDF/DOCX/TXT). Fields stay editable.
2. Pick target roles and seniority.
3. Connect X in the browser that opens. Cookies are stored encrypted; the
   password is never saved.
4. Press **Scan now** or leave the agent on its schedule.

Add a GitHub link on the profile and the agent pulls public repos, languages and
top projects automatically. Those details are used in messages but are not
shown in the UI.

## Tests

```powershell
cd job_apply/backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

The suite is fully offline: no X, no model provider.

## Notes

- Run a single Uvicorn worker. The scheduler uses a file lock so only one
  process scans and sends.
- The agent uses a logged-in browser session, not the official X API. Keep
  volumes low.
- `.env`, the database, resumes and browser profiles are not committed.
