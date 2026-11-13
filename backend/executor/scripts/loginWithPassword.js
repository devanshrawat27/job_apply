/**
 * Sign in to X and return the session cookies.
 *
 * X has more than one login screen. The classic flow used `input[name="text"]`;
 * the newer onboarding flow uses `input[name="username_or_email"]` and renders
 * the password field on the same page. This script waits for whichever is
 * actually visible instead of assuming one layout.
 *
 * The password arrives in SCRIPT_ARG_PASSWORD, is typed into X's own form, and
 * is never written to disk or printed. Only the resulting auth_token / ct0 /
 * twid are returned (the backend stores them encrypted).
 */

import { launchBrowser } from '../utils/browser.js'
import { humanClick, humanType, randomWait } from '../utils/humanize.js'
import { reportOk, reportFail } from '../utils/report.js'

const HANDLE = (process.env.SCRIPT_ARG_HANDLE || '').trim().replace(/^@/, '')
const PASSWORD = process.env.SCRIPT_ARG_PASSWORD || ''
const CODE = (process.env.SCRIPT_ARG_VERIFICATION_CODE || '').trim()

const HARD_DEADLINE_MS = 210000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'X login did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

const USER_SELECTORS = [
  'input[name="username_or_email"]',
  'input[autocomplete*="username"]',
  'input[name="text"]',
  'input[data-testid="ocfEnterTextTextInput"]',
]

const PASSWORD_SELECTORS = [
  'input[name="password"]',
  'input[autocomplete="current-password"]',
  'input[type="password"]',
]

const CODE_SELECTORS = [
  'input[data-testid="ocfEnterTextTextInput"]',
  'input[name="text"]',
]

async function findVisible(page, selectors, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const locator = page.locator(selector).first()
      const visible = await locator.isVisible().catch(() => false)
      if (visible) return locator
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  return null
}

async function submit(page, timeoutMs = 4000) {
  await page.keyboard.press('Enter')

  // Some builds need an explicit button press instead of Enter.
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const progressed = await page
      .locator(PASSWORD_SELECTORS.join(', '))
      .first()
      .isVisible()
      .catch(() => false)
    if (progressed) return

    const continueButton = page
      .locator('button, [role="button"]')
      .filter({ hasText: /^(continue|next|log in|sign in)$/i })
      .first()
    if (await continueButton.isVisible().catch(() => false)) {
      await humanClick(page, continueButton)
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 700))
  }
}

async function readSession(context) {
  const cookies = await context.cookies('https://x.com')
  const get = (name) => cookies.find((cookie) => cookie.name === name)?.value || ''
  return { auth_token: get('auth_token'), ct0: get('ct0'), twid: get('twid') }
}

async function signedInHandle(page) {
  const profileLink = await page
    .locator('a[data-testid="AppTabBar_Profile_Link"]')
    .first()
    .getAttribute('href')
    .catch(() => null)
  if (profileLink) return profileLink.replace(/^\//, '').split('/')[0]

  const navLink = await page
    .locator('[data-testid="SideNav_AccountSwitcher_Button"] a[href^="/"]')
    .first()
    .getAttribute('href')
    .catch(() => null)
  return navLink ? navLink.replace(/^\//, '').split('/')[0] : ''
}

const LOGIN_URLS = [
  'https://x.com/i/jl/onboarding/web?mode=login',
  'https://x.com/i/flow/login',
]

async function login() {
  const { context, page } = await launchBrowser({ withSession: false })

  try {
    // X serves login from more than one route. Try the current onboarding
    // route first, then the classic flow.
    let userInput = null
    for (const url of LOGIN_URLS) {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
      await randomWait(2000, 3000)
      userInput = await findVisible(page, USER_SELECTORS, 18000)
      if (userInput) break
    }

    if (!userInput) {
      return reportFail(
        'SELECTOR_MISS',
        `Could not find the X login form (page: ${page.url()}). X may have changed its login screen.`,
      )
    }

    await humanClick(page, userInput)
    await humanType(page, HANDLE)
    await randomWait(500, 1000)
    await submit(page)

    // ---- optional "confirm your phone or username" step --------------
    await randomWait(1500, 2500)
    const passwordVisible = await page
      .locator(PASSWORD_SELECTORS.join(', '))
      .first()
      .isVisible()
      .catch(() => false)

    if (!passwordVisible) {
      const body = await page.locator('body').innerText().catch(() => '')
      const extraInput = await findVisible(page, CODE_SELECTORS, 6000)
      if (extraInput) {
        if (/phone|email|username|verification|code/i.test(body)) {
          await humanClick(page, extraInput)
          await humanType(page, CODE || HANDLE)
          await submit(page)
          await randomWait(1500, 2500)
        }
      }
    }

    // ---- password ----------------------------------------------------
    const passwordInput = await findVisible(page, PASSWORD_SELECTORS, 45000)
    if (!passwordInput) {
      const body = await page.locator('body').innerText().catch(() => '')
      if (/code|verification|challenge|unusual/i.test(body)) {
        return reportFail(
          'LOGIN_CHALLENGE',
          'X asked for extra verification. Retry with the code X sent you.',
        )
      }
      return reportFail('SELECTOR_MISS', 'The X password field never appeared.')
    }

    await humanClick(page, passwordInput)
    await humanType(page, PASSWORD)
    await randomWait(500, 1000)
    await submit(page)

    // ---- one-time code, if X asks after the password -----------------
    if (CODE) {
      await randomWait(1500, 2500)
      const codeInput = await findVisible(page, CODE_SELECTORS, 5000)
      if (codeInput) {
        await humanClick(page, codeInput)
        await humanType(page, CODE)
        await submit(page)
      }
    }

    // ---- wait for the session cookies --------------------------------
    // X sets auth_token/ct0 within a few seconds of a successful login, so a
    // long wait only hurts when the password is wrong.
    const deadline = Date.now() + 75000
    let creds = { auth_token: '', ct0: '', twid: '' }
    let polls = 0
    let rejection = ''
    while (Date.now() < deadline) {
      creds = await readSession(context)
      if (creds.auth_token && creds.ct0) break

      if (polls % 2 === 0) {
        const body = (await page.locator('body').innerText().catch(() => '')).replace(
          /[\u2018\u2019]/g,
          "'",
        )
        if (/wrong password|incorrect password|invalid password/i.test(body)) {
          rejection = 'X says the password is wrong.'
          break
        }
        if (/couldn'?t (find|locate)[^.]*account|could not (find|locate)[^.]*account|no account found|not an active x account/i.test(body)) {
          rejection = 'X could not find that account. Check the handle.'
          break
        }
        if (/account has been locked|temporarily limited|suspicious/i.test(body)) {
          rejection = 'X locked or limited the account. Open X and check it.'
          break
        }
      }
      polls += 1
      await new Promise((resolve) => setTimeout(resolve, 2500))
    }

    if (rejection) return reportFail('LOGIN_FAILED', rejection)

    if (!creds.auth_token || !creds.ct0) {
      const body = (await page.locator('body').innerText().catch(() => ''))
        .replace(/\s+/g, ' ')
        .trim()
      if (/code|verification|challenge|unusual/i.test(body)) {
        return reportFail(
          'LOGIN_CHALLENGE',
          'X asked for extra verification. Retry with the code X sent you.',
        )
      }
      return reportFail(
        'LOGIN_TIMEOUT',
        `X did not finish signing in.${body ? ` X says: "${body.slice(0, 200)}"` : ''}`,
      )
    }

    await page
      .goto('https://x.com/home', { waitUntil: 'domcontentloaded', timeout: 45000 })
      .catch(() => {})
    await randomWait(2500, 4000)

    const handle = await signedInHandle(page)
    if (handle && HANDLE && handle.toLowerCase() !== HANDLE.toLowerCase()) {
      return reportFail(
        'HANDLE_MISMATCH',
        `Signed in as @${handle}, but you entered @${HANDLE}.`,
      )
    }

    reportOk({ handle: handle || HANDLE, credentials: creds, has_session: true })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    const browser = context.browser()
    if (browser) await browser.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!HANDLE || !PASSWORD) {
  reportFail('VALIDATION', 'handle and password are required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else {
  login().finally(() => clearTimeout(watchdog))
}
