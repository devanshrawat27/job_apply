# JobPilot executor

Playwright scripts the Python backend spawns. Same contract as the reference
projects:

```
node scripts/<name>.js --agent-mode
SCRIPT_ARG_<NAME> environment variables
RESULT_JSON:{"success":true,"code":"OK","data":{...}}    # final stdout line
```

`stderr` is diagnostic only. `UNKNOWN` means a write may or may not have landed
and must never be retried automatically.

## Scripts

| Script | Called by | Args |
| --- | --- | --- |
| `scripts/loginWithPassword.js` | connect account | `HANDLE`, `PASSWORD`, `VERIFICATION_CODE` |
| `scripts/searchJobs.js` | scan | `QUERY`, `COUNT`, `TAB` |
| `scripts/replyToPost.js` | send reply | `POST_URL`, `REPLY_TEXT` |
| `scripts/sendDm.js` | send DM | `USERNAME`, `MESSAGE` + `DM_PASSCODE` |
| `scripts/followUser.js` | follow fallback | `USERNAME` |

## Setup

```powershell
cd backend/executor
npm install
npx playwright install chromium
```

Set `BROWSER_CHANNEL=chrome` to use an installed Chrome instead of the bundled
Chromium.

## Environment

| Variable | Purpose |
| --- | --- |
| `STEALTH_HEADLESS=1` | run without a window (expect more X challenges) |
| `BROWSER_CHANNEL=chrome` | use installed Chrome |
| `PROXY_SERVER` / `PROXY_USERNAME` / `PROXY_PASSWORD` | optional proxy |
| `STEALTH_LOCALE`, `STEALTH_TIMEZONE` | locale / timezone overrides |
| `TWITTER_AUTH_TOKEN` / `TWITTER_CT0` / `TWITTER_TWID` | injected session cookies |
| `DM_PASSCODE` | X encrypted-chat passcode (never logged) |

## Ground truth rules

- A reply is confirmed from the `CreateTweet` network response, not from the UI.
- A DM is confirmed only when the composer clears **and** a new message bubble
  appears. Anything else is `UNKNOWN`.
- Session cookies are read from the environment only. Nothing is written to disk.
