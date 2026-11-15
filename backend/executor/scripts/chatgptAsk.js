/**
 * Ask ChatGPT in the browser and return its JSON answer.
 *
 *   SCRIPT_ARG_SYSTEM        system instructions
 *   SCRIPT_ARG_PROMPT        the task / data
 *   SCRIPT_ARG_THREAD_URL    existing conversation to continue (optional)
 *   SCRIPT_ARG_THREAD_TITLE  title of a new conversation (optional)
 *   SCRIPT_ARG_PROJECT_URL   ChatGPT project that holds the chat (optional)
 *
 * Continuing the same conversation is what gives ChatGPT the context of what it
 * already checked or drafted for this user. The chat stays in the account
 * history, inside the JobPilot project.
 */

import {
  CHATGPT_COMPOSER,
  isLoggedIn,
  launchChatgpt,
  markConnected,
} from '../utils/chatgptBrowser.js'
import { reportFail, reportOk } from '../utils/report.js'

const HARD_DEADLINE_MS = 210000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'ChatGPT did not answer in 3.5 minutes')
  process.exit(1)
}, HARD_DEADLINE_MS)

const SYSTEM = (process.env.SCRIPT_ARG_SYSTEM || '').trim()
const PROMPT = (process.env.SCRIPT_ARG_PROMPT || '').trim()
const THREAD_URL = (process.env.SCRIPT_ARG_THREAD_URL || '').trim()
const THREAD_TITLE = (process.env.SCRIPT_ARG_THREAD_TITLE || '').trim()
const PROJECT_URL = (process.env.SCRIPT_ARG_PROJECT_URL || '').trim()

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

async function assistantCount(page) {
  return page
    .evaluate(() => document.querySelectorAll('[data-message-author-role="assistant"]').length)
    .catch(() => 0)
}

async function transcript(page) {
  return page.locator('main').innerText().catch(() => '')
}

/**
 * Wait for the answer to the message we just sent.
 *
 * An existing conversation already contains older answers, so a stable *old*
 * answer must never be mistaken for the new one. We snapshot the transcript
 * before sending and only accept text that changed.
 */
async function waitForAnswer(page, timeoutMs, priorCount, priorText) {
  const deadline = Date.now() + timeoutMs
  let lastText = ''
  let stablePolls = 0
  let started = false

  while (Date.now() < deadline) {
    await page.waitForTimeout(2000)

    const count = await assistantCount(page)
    const busy =
      (await page
        .locator('[data-testid="stop-button"], button:has-text("Stop")')
        .count()
        .catch(() => 0)) > 0

    let current = ''
    if (count > priorCount) {
      current = (
        await page
          .locator('[data-message-author-role="assistant"]')
          .last()
          .innerText()
          .catch(() => '')
      ).trim()
    } else {
      const text = cleanAnswer(await transcript(page))
      if (text && text !== priorText) current = text
    }

    if (current) started = true
    if (started && current && current === lastText && !busy) {
      stablePolls += 1
      if (stablePolls >= 2) return current
    } else {
      stablePolls = 0
    }
    lastText = current
  }
  return lastText
}

async function openTarget(page) {
  const target = THREAD_URL || PROJECT_URL || 'https://chatgpt.com/'
  await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(4500)

  if (!(await isLoggedIn(page))) {
    reportFail(
      'CHATGPT_LOGIN_REQUIRED',
      'ChatGPT is not logged in. Open Settings -> AI analyst and press "Connect ChatGPT".',
    )
    return false
  }
  markConnected()

  if ((await page.locator(CHATGPT_COMPOSER).count().catch(() => 0)) > 0) return true

  // A project landing page sometimes shows its own "New chat" action first.
  if (PROJECT_URL) {
    const newChat = page
      .locator('button:has-text("New chat"), a:has-text("New chat")')
      .first()
    if ((await newChat.count().catch(() => 0)) > 0) {
      await newChat.click().catch(() => {})
      await page.waitForTimeout(2500)
      if ((await page.locator(CHATGPT_COMPOSER).count().catch(() => 0)) > 0) return true
    }
  }
  return false
}

async function main() {
  if (!PROMPT) {
    reportFail('VALIDATION', 'SCRIPT_ARG_PROMPT is required')
    return
  }

  const { context, page } = await launchChatgpt()

  try {
    const ready = await openTarget(page)
    if (!ready) {
      if (THREAD_URL) {
        reportFail(
          'THREAD_MISSING',
          'The saved ChatGPT conversation no longer opens',
        )
      } else {
        reportFail('NO_COMPOSER', 'ChatGPT did not show the message box')
      }
      return
    }

    const priorCount = await assistantCount(page)
    const priorText = cleanAnswer(await transcript(page))

    const composer = page.locator(CHATGPT_COMPOSER).first()
    await composer.click({ timeout: 15000 })

    // A brand-new conversation gets a readable title so the human can find it
    // in the ChatGPT sidebar.
    let fullText = SYSTEM ? `${SYSTEM}\n\nUSER TASK:\n${PROMPT}` : PROMPT
    if (!THREAD_URL && THREAD_TITLE) fullText = `${THREAD_TITLE}\n\n${fullText}`

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
    // minimized tab and the answer can arrive too late.
    const text = await waitForAnswer(page, 150000, priorCount, priorText)
    if (!text) {
      reportFail('EMPTY_ANSWER', 'ChatGPT returned an empty answer')
      return
    }

    const data = extractJson(text)
    if (!data) {
      reportFail('BAD_JSON', `ChatGPT did not return JSON: ${text.slice(0, 200)}`)
      return
    }
    reportOk({
      json: data,
      raw: text.slice(0, 4000),
      thread_url: page.url(),
    })
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
