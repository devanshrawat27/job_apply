/**
 * Ask ChatGPT in the browser and return its JSON answer.
 *
 *   SCRIPT_ARG_SYSTEM   system instructions
 *   SCRIPT_ARG_PROMPT   the task / data
 *
 * Uses the dedicated ChatGPT profile (separate from the X browser). The window
 * stays visible while ChatGPT answers because Chromium throttles minimized
 * tabs; the chat is saved to the account history.
 */

import {
  CHATGPT_COMPOSER,
  isLoggedIn,
  launchChatgpt,
  markConnected,
} from '../utils/chatgptBrowser.js'
import { reportFail, reportOk } from '../utils/report.js'

const HARD_DEADLINE_MS = 180000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'ChatGPT did not answer in 3 minutes')
  process.exit(1)
}, HARD_DEADLINE_MS)

const SYSTEM = (process.env.SCRIPT_ARG_SYSTEM || '').trim()
const PROMPT = (process.env.SCRIPT_ARG_PROMPT || '').trim()

function extractJson(text) {
  const raw = String(text || '')
    .replace(/```(?:json)?/gi, '')
    .replace(/```/g, '')
    .trim()

  try {
    return JSON.parse(raw)
  } catch {
    // ChatGPT often wraps the object in a sentence or a list; take the widest
    // {...} block and try again.
  }

  const start = raw.indexOf('{')
  const end = raw.lastIndexOf('}')
  if (start === -1 || end === -1 || end <= start) return null
  try {
    return JSON.parse(raw.slice(start, end + 1))
  } catch {
    return null
  }
}

function cleanAnswer(text) {
  const marker = 'ChatGPT said:'
  const index = text.lastIndexOf(marker)
  if (index === -1) return ''
  let tail = text.slice(index + marker.length)
  for (const cut of ['ChatGPT can make mistakes', 'ChatGPT may make mistakes', 'Latest response']) {
    const at = tail.indexOf(cut)
    if (at !== -1) tail = tail.slice(0, at)
  }
  return tail.trim()
}

async function waitForAnswer(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let lastText = ''
  let stablePolls = 0

  while (Date.now() < deadline) {
    await page.waitForTimeout(2000)
    const main = await page.locator('main').innerText().catch(() => '')
    const current = cleanAnswer(main)
    const busy =
      (await page
        .locator('[data-testid="stop-button"], button:has-text("Stop")')
        .count()
        .catch(() => 0)) > 0

    if (current && current === lastText && !busy) {
      stablePolls += 1
      if (stablePolls >= 2) return current
    } else {
      stablePolls = 0
    }
    lastText = current
  }
  return lastText
}

async function main() {
  if (!PROMPT) {
    reportFail('VALIDATION', 'SCRIPT_ARG_PROMPT is required')
    return
  }

  const { context, page } = await launchChatgpt()

  try {
    await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(4000)

    if (!(await isLoggedIn(page))) {
      reportFail(
        'CHATGPT_LOGIN_REQUIRED',
        'ChatGPT is not logged in. Open Settings -> AI analyst and press "Connect ChatGPT".',
      )
      return
    }
    markConnected()

    const composer = page.locator(CHATGPT_COMPOSER).first()
    await composer.click({ timeout: 15000 })
    const fullText = SYSTEM ? `${SYSTEM}\n\nUSER TASK:\n${PROMPT}` : PROMPT
    await composer.fill(fullText).catch(async () => {
      await page.keyboard.type(fullText, { delay: 1 })
    })
    await page.waitForTimeout(600)

    await page.keyboard.press('Enter')
    await page.waitForTimeout(2500)

    // If Enter only added a newline, click the send button instead.
    if ((await composer.innerText().catch(() => '')).trim()) {
      const send = page.locator('[data-testid="send-button"]').first()
      if (await send.count()) {
        await send.click().catch(() => {})
        await page.waitForTimeout(2000)
      }
    }

    // Keep the window visible while ChatGPT answers: Chromium throttles a
    // minimized tab and the answer can arrive too late. The whole exchange is
    // short (under a minute) and the chat stays in the account history.
    const text = await waitForAnswer(page, 120000)
    if (!text) {
      reportFail('EMPTY_ANSWER', 'ChatGPT returned an empty answer')
      return
    }

    const data = extractJson(text)
    if (!data) {
      reportFail('BAD_JSON', `ChatGPT did not return JSON: ${text.slice(0, 200)}`)
      return
    }
    reportOk({ json: data, raw: text.slice(0, 4000) })
  } finally {
    clearTimeout(watchdog)
    await context.close().catch(() => {})
  }
}

main().catch((err) => {
  clearTimeout(watchdog)
  reportFail('ERROR', err.message)
  process.exitCode = 1
})
