/**
 * Send a personal DM to an X user.
 *
 *   SCRIPT_ARG_USERNAME   handle without @
 *   SCRIPT_ARG_MESSAGE    the message text
 *   DM_PASSCODE           optional X chat passcode (injected by the backend)
 *
 * X's encrypted chat renders its shell before the conversation loads. Typing
 * into a half-loaded composer loses the message, so we wait for the composer
 * to be quiet and for the skeleton placeholders to disappear.
 */

import { launchBrowser } from '../utils/browser.js'
import handlePasskey from '../utils/handlePasskey.js'
import { humanClick, humanType, randomWait } from '../utils/humanize.js'
import { minimizeBrowserWindow, restoreBrowserWindow } from '../utils/minimize.js'
import { reportOk, reportFail } from '../utils/report.js'

const COMPOSER = '[data-testid="dm-composer-textarea"]'
const MESSAGE_ITEM = '[data-testid^="message-text-"]'
const PIN_CONTAINER = '[data-testid="pin-code-input-container"]'

const HARD_DEADLINE_MS = 240000
const watchdog = setTimeout(() => {
  reportFail('UNKNOWN', 'DM script timed out - the message may or may not have been sent')
  process.exit(1)
}, HARD_DEADLINE_MS)

const USERNAME = (process.env.SCRIPT_ARG_USERNAME || '').trim().replace(/^@/, '')
const MESSAGE = (process.env.SCRIPT_ARG_MESSAGE || '').trim()
const PASSCODE = (process.env.DM_PASSCODE || '').trim()

const isPinScreen = (url) => url.includes('/pin/')

async function waitForPinScreen(page, timeout) {
  return page
    .locator(PIN_CONTAINER)
    .first()
    .waitFor({ state: 'visible', timeout })
    .then(() => true)
    .catch(() => false)
}

async function enterPasscode(page) {
  if (!PASSCODE) {
    // Nothing has been typed or sent yet, so this is a safe, retryable stop.
    const error = new Error(
      'X asked for your chat passcode and none is saved. Add it in Settings â†’ X account, then retry this DM.',
    )
    error.code = 'PASSCODE_REQUIRED'
    throw error
  }
  const input = page.locator(`${PIN_CONTAINER} input`).first()
  await humanClick(page, input)
  await humanType(page, PASSCODE)
  await page.keyboard.press('Enter')
  await randomWait(1500, 2500)
}

async function waitForChatReady(page, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs
  let quietPolls = 0

  while (Date.now() < deadline) {
    if (isPinScreen(page.url())) return 'pin'

    const skeletons = await page.locator('[class*="skeleton" i]').count().catch(() => 999)
    const composer = await page.locator(COMPOSER).count().catch(() => 0)

    if (composer > 0 && skeletons === 0) {
      quietPolls += 1
      if (quietPolls >= 2) return 'ready'
    } else {
      quietPolls = 0
    }
    await page.waitForTimeout(1500)
  }
  return 'timeout'
}

async function composerText(page) {
  const value = await page.locator(COMPOSER).first().inputValue().catch(() => null)
  return (value ?? '').trim()
}

async function hasClosedInbox(page) {
  const body = await page.locator('body').innerText().catch(() => '')
  return /closed inbox|has a closed inbox/i.test(body)
}

async function confirmSent(page, beforeCount, attempts = 20) {
  for (let i = 0; i < attempts; i++) {
    await page.waitForTimeout(500)
    if (isPinScreen(page.url())) return false
    if ((await composerText(page)) !== '') continue

    const count = await page.locator(MESSAGE_ITEM).count()
    if (count > beforeCount) return true
  }
  return false
}

const normalize = (text) =>
  String(text || '')
    .replace(/[\u200b-\u200d\ufeff]/g, '')
    .replace(/\s+/g, ' ')
    .trim()

async function threadHasMessage(page, needle, message) {
  const texts = await page
    .locator(MESSAGE_ITEM)
    .allInnerTexts()
    .catch(() => [])
  return texts.some((text) => {
    const value = normalize(text)
    if (!value) return false
    return value.includes(needle) || normalize(message).includes(value.slice(0, 40))
  })
}

async function openThreadFromProfile(page) {
  // A plain reload can land on the messages home instead of this conversation,
  // which made delivered DMs look missing. Re-open the exact thread instead.
  await page.goto(`https://x.com/${USERNAME}`, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await randomWait(2000, 3000)

  const button = page.locator('[data-testid="sendDMFromProfile"]').first()
  if ((await button.count()) === 0) return false

  await humanClick(page, button)
  await handlePasskey(page)

  for (let i = 0; i < 3; i++) {
    if (await waitForPinScreen(page, i === 0 ? 8000 : 3000)) {
      await enterPasscode(page).catch(() => {})
      continue
    }
    if ((await waitForChatReady(page, 10000)) === 'ready') return true
  }
  return false
}

async function verifyPersisted(page, message, dmPasscode) {
  // X renders sent messages optimistically. Re-open the thread and require the
  // text to still be there before calling it delivered.
  await page.waitForTimeout(5000)

  const needle = normalize(message).slice(0, 60)

  for (let attempt = 1; attempt <= 3; attempt++) {
    if (attempt < 3) {
      try {
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 })
      } catch {
        await page.waitForTimeout(3000)
        continue
      }
      // A reloaded thread needs real paint time; minimized Chromium throttles
      // rendering, so give it a longer, progressively increasing settle window.
      await page.waitForTimeout(5000 + attempt * 3000)
    } else {
      console.log('reopening the DM thread from the profile...')
      const opened = await openThreadFromProfile(page).catch(() => false)
      if (!opened) {
        console.log('could not reopen the DM thread')
        continue
      }
      await page.waitForTimeout(4000)
    }

    for (let i = 0; i < 3; i++) {
      if (!(await waitForPinScreen(page, i === 0 ? 8000 : 3000))) break
      await enterPasscode(page).catch(() => {})
      await page.waitForTimeout(2000)
    }

    const deadline = Date.now() + 30000
    while (Date.now() < deadline) {
      const skeletons = await page.locator('[class*="skeleton" i]').count().catch(() => 999)
      if (skeletons === 0 && !isPinScreen(page.url())) break
      await page.waitForTimeout(1500)
    }

    if (await threadHasMessage(page, needle, message)) return true
    console.log(`message not visible after reload (attempt ${attempt}/3)`)
  }

  return false
}

async function send() {
  const { browser, page } = await launchBrowser()
  let windowRestored = false

  try {
    await page.goto(`https://x.com/${USERNAME}`, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await randomWait(2500, 4000)

    const body = await page.locator('body').innerText().catch(() => '')
    if (/this account doesn.?t exist|account not found/i.test(body)) {
      reportFail('TARGET_NOT_FOUND', `@${USERNAME} does not exist or was removed`)
      return
    }
    if (/rate limit|something went wrong\. try reloading/i.test(body)) {
      reportFail('RATE_LIMITED', 'X is rate-limiting this session')
      return
    }

    const messageButton = page.locator('[data-testid="sendDMFromProfile"]').first()
    if ((await messageButton.count()) === 0) {
      // X hides the Message button when the account only accepts DMs from
      // people it follows back / knows. Following is the documented fallback.
      reportFail(
        'DM_LOCKED',
        `@${USERNAME} does not accept DMs from this account until you follow`,
      )
      return
    }

    await humanClick(page, messageButton)
    await handlePasskey(page)
    await page.waitForTimeout(1500)

    if (await hasClosedInbox(page)) {
      reportFail(
        'DM_CLOSED',
        `@${USERNAME} has a closed inbox - they cannot receive DMs`,
      )
      return
    }

    // Fast path: a few short probes. If X's chat app does not render we stop
    // quickly and report why, instead of burning minutes on one account.
    async function waitUntilChatReady() {
      let ready = 'timeout'
      for (let attempt = 1; attempt <= 3; attempt++) {
        if (await waitForPinScreen(page, attempt === 1 ? 8000 : 3000)) {
          await enterPasscode(page)
          continue
        }
        if (isPinScreen(page.url())) {
          await page.waitForTimeout(1500)
          continue
        }
        ready = await waitForChatReady(page, 10000)
        if (ready === 'ready') break
      }
      return ready
    }

    let ready = await waitUntilChatReady()

    // One safe reload: nothing has been typed yet, and X's chat shell often
    // recovers on a fresh load when the SPA route renders empty.
    if (ready !== 'ready' && !isPinScreen(page.url())) {
      console.log('chat shell not ready - reloading once')
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {})
      await page.waitForTimeout(6000)
      ready = await waitUntilChatReady()
    }

    // Still not ready: a minimized Chromium throttles X's chat app. Restore the
    // window briefly, reload and try once more, then minimize again.
    if (ready !== 'ready' && !isPinScreen(page.url()) && process.env.STEALTH_HEADLESS !== '1') {
      console.log('chat still not ready - restoring the window for one more try')
      windowRestored = await restoreBrowserWindow()
      await page.bringToFront().catch(() => {})
      await page.waitForTimeout(1500)
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {})
      await page.waitForTimeout(6000)
      ready = await waitUntilChatReady()
      if (ready === 'ready') {
        await minimizeBrowserWindow().catch(() => {})
        windowRestored = false
      }
    }

    if (ready !== 'ready') {
      if (await hasClosedInbox(page)) {
        reportFail(
          'DM_CLOSED',
          `@${USERNAME} has a closed inbox - they cannot receive DMs`,
        )
        return
      }

      const body = (await page.locator('body').innerText().catch(() => ''))
        .replace(/\s+/g, ' ')
        .trim()
      const blank = body.length < 40

      if (blank) {
        reportFail(
          'CHAT_UNAVAILABLE',
          'X chat did not render in this browser. Open x.com/messages once, unlock the chat, then retry.',
        )
        return
      }

      reportFail(
        isPinScreen(page.url()) ? 'PASSCODE_INVALID' : 'CHAT_NOT_READY',
        isPinScreen(page.url())
          ? 'X did not accept the chat passcode - nothing was sent, safe to retry'
          : 'X chat did not finish loading - nothing was sent, safe to retry',
      )
      return
    }

    const blocked = await page
      .locator('text=/can.?t (send|message)|Message requests are limited/i')
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false)
    if (blocked) {
      reportFail('DM_LOCKED', `@${USERNAME} restricts messages from non-followers`)
      return
    }

    // X's chat lives in a shadow DOM; raw mouse coordinates can miss it, so
    // fill the composer directly and only fall back to keystrokes.
    const composer = page.locator(COMPOSER).first()
    await composer.click({ timeout: 5000 }).catch(() => {})
    await composer.fill(MESSAGE).catch(() => {})
    await randomWait(700, 1200)

    if ((await composerText(page)) === '') {
      await composer.click({ timeout: 5000 }).catch(() => {})
      await page.keyboard.type(MESSAGE, { delay: 25 })
      await randomWait(800, 1400)
    }

    if ((await composerText(page)) === '') {
      reportFail('ERROR', 'composer stayed empty after typing - nothing was sent')
      return
    }

    const beforeCount = await page.locator(MESSAGE_ITEM).count()
    await page.keyboard.press('Enter')

    let confirmed = await confirmSent(page, beforeCount)

    if (!confirmed && !isPinScreen(page.url()) && (await composerText(page)) !== '') {
      const sendButton = page
        .locator('[data-testid="dm-send-button"], button[aria-label="Send"], [role="button"][aria-label="Send"]')
        .first()
      if (await sendButton.count()) {
        await humanClick(page, sendButton)
        confirmed = await confirmSent(page, beforeCount)
      }
    }

    if (!confirmed) {
      reportFail(
        isPinScreen(page.url()) ? 'UNKNOWN' : 'ERROR',
        'message was typed but sending could not be confirmed',
      )
      return
    }

    console.log('verifying the message persisted...')
    // Minimized Chromium throttles rendering, so the thread can look empty
    // after a reload even though the message was delivered. Restore the window
    // for the verification, then put it back in the taskbar minimized.
    let restored = false
    if (process.env.STEALTH_HEADLESS !== '1') {
      restored = await restoreBrowserWindow()
      windowRestored = restored
      await page.bringToFront().catch(() => {})
      await page.waitForTimeout(1500)
    }
    const persisted = await verifyPersisted(page, MESSAGE, PASSCODE)
    if (restored) await minimizeBrowserWindow().catch(() => {})
    windowRestored = false
    if (!persisted) {
      reportFail(
        'DELIVERY_UNVERIFIED',
        'X showed the message but it did not persist after reloading, so it was NOT delivered',
      )
      return
    }

    reportOk({ username: USERNAME, message: MESSAGE, verified: 'persisted' })
  } catch (err) {
    // A failure after pressing Enter is genuinely unknown.
    reportFail(err.code || 'UNKNOWN', err.message)
    process.exitCode = 1
  } finally {
    if (windowRestored) await minimizeBrowserWindow().catch(() => {})
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!USERNAME) {
  reportFail('VALIDATION', 'SCRIPT_ARG_USERNAME is required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else if (!MESSAGE) {
  reportFail('VALIDATION', 'SCRIPT_ARG_MESSAGE is required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else {
  send().finally(() => clearTimeout(watchdog))
}

