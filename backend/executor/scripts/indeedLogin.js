/**
 * Sign in to Indeed and return the session cookies.
 *
 * Indeed blocks headless Chromium on its apply pages, so a real Chrome window is
 * opened and the human finishes the login. Only the resulting cookies are
 * returned; the password never reaches this script.
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const EMAIL = (process.env.SCRIPT_ARG_EMAIL || '').trim()
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const HARD_DEADLINE_MS = 340000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Indeed login did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

async function readCookies(context) {
  const cookies = await context.cookies('https://in.indeed.com')
  const values = {}
  for (const cookie of cookies) values[cookie.name] = cookie.value
  return values
}

async function confirmSession(context) {
  const probe = await context.newPage()
  try {
    await probe
      .goto('https://in.indeed.com/myjobs', {
        waitUntil: 'domcontentloaded',
        timeout: 45000,
      })
      .catch(() => {})
    await probe.waitForTimeout(4500)
    const url = probe.url()
    if (/secure\.indeed\.com\/(auth|account\/login)|\/auth\?/i.test(url)) {
      return { ok: false, name: '' }
    }
    const body = (await probe.locator('body').innerText().catch(() => '')).toLowerCase()
    if (/sign in to your account|forgot your password|continue with google/i.test(body)) {
      return { ok: false, name: '' }
    }
    const signIn = await probe
      .locator('a[href*="secure.indeed.com/auth"], a[href*="account/login"]')
      .count()
      .catch(() => 0)
    const profile = await probe
      .locator('a[href*="profile.indeed.com"], [data-testid="gnav-profile"], a[href*="account/logout"]')
      .count()
      .catch(() => 0)
    if (signIn > 0 && profile === 0) return { ok: false, name: '' }
    if (/my jobs|saved jobs|applied/i.test(body) && !/sign in/i.test(body)) {
      return { ok: true, name: '' }
    }
    return { ok: profile > 0, name: '' }
  } catch {
    return { ok: false, name: '' }
  } finally {
    await probe.close().catch(() => {})
  }
}

async function centerWindow(context, page) {
  try {
    await page.bringToFront()
    const session = await context.newCDPSession(page)
    const { windowId } = await session.send('Browser.getWindowForTarget')
    await session.send('Browser.setWindowBounds', {
      windowId,
      bounds: { left: 120, top: 80, width: 1280, height: 900, windowState: 'normal' },
    })
  } catch (err) {
    console.log(`could not center the Indeed window: ${err.message}`)
  }
}

async function login() {
  delete process.env.BROWSER_CDP_ENDPOINT
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-indeed`
  process.env.STEALTH_HEADLESS = '0'
  delete process.env.STEALTH_OFFSCREEN
  const { browser, context, page } = await launchBrowser({ withSession: false })
  await centerWindow(context, page)

  try {
    await page
      .goto('https://in.indeed.com/', { waitUntil: 'domcontentloaded', timeout: 60000 })
      .catch(() => {})
    await page.waitForTimeout(4000)

    const body = (await page.locator('body').innerText().catch(() => '')).toLowerCase()
    if (/just a moment|performing security verification|additional verification required/i.test(body)) {
      return reportFail(
        'INDEED_BLOCKED',
        'Indeed is showing a verification page. Complete it in the window and retry.',
      )
    }

    console.log('Indeed login window is open. Sign in there; waiting up to 5 minutes...')
    const deadline = Date.now() + 300000
    let lastCheck = 0
    while (Date.now() < deadline) {
      if (Date.now() - lastCheck >= 10000) {
        lastCheck = Date.now()
        const check = await confirmSession(context)
        if (check.ok) {
          await sleep(1500)
          const finalCookies = await readCookies(context)
          reportOk({ name: check.name, email: EMAIL, credentials: finalCookies })
          return
        }
      }
      await sleep(1500)
    }

    return reportFail(
      'LOGIN_TIMEOUT',
      'Indeed did not finish signing in. Complete the login in the window and retry.',
    )
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
    throw err
  } finally {
    await browser?.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

login()
  .then(() => {
    clearTimeout(watchdog)
    setTimeout(() => process.exit(0), 120)
  })
  .catch(() => process.exit(1))
