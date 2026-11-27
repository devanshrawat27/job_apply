/**
 * Sign in to Naukri.com and return the session cookies.
 *
 * Naukri's edge blocks headless Chromium, so this opens a real Chrome window
 * and lets the human finish the login (password / OTP / captcha). Only the
 * resulting cookies are returned; the password never reaches this script.
 */

import { launchBrowser } from '../utils/browser.js'
import { reportFail, reportOk } from '../utils/report.js'

const EMAIL = (process.env.SCRIPT_ARG_EMAIL || '').trim()
const HARD_DEADLINE_MS = 330000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'Naukri login did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

async function readCookies(context) {
  const cookies = await context.cookies('https://www.naukri.com')
  const values = {}
  for (const cookie of cookies) values[cookie.name] = cookie.value
  return values
}

async function confirmSession(page) {
  // Check the session without touching the tab the human is using. Fetching
  // the authenticated homepage from inside naukri.com carries the live cookies;
  // a login redirect or the login form means the session is not ready yet.
  try {
    const result = await page.evaluate(async () => {
      try {
        const response = await fetch('https://www.naukri.com/mnjuser/homepage', {
          credentials: 'include',
          redirect: 'follow',
        })
        const text = await response.text()
        return { url: response.url, status: response.status, text: text.slice(0, 6000) }
      } catch (error) {
        return { error: String(error) }
      }
    })
    if (!result || result.error) return { ok: false, name: '' }
    if (/nlogin|login/i.test(result.url || '')) return { ok: false, name: '' }
    const body = (result.text || '').toLowerCase()
    if (/forgot password|use otp to login|new to naukri\?/.test(body)) {
      return { ok: false, name: '' }
    }
    return { ok: true, name: '' }
  } catch {
    return { ok: false, name: '' }
  }
}

async function centerWindow(context, page) {
  // The Naukri search profile remembers the off-screen search position. Bring
  // the one-time sign-in window back to the middle of the desktop.
  try {
    await page.bringToFront()
    const session = await context.newCDPSession(page)
    const { windowId } = await session.send('Browser.getWindowForTarget')
    await session.send('Browser.setWindowBounds', {
      windowId,
      bounds: { left: 120, top: 80, width: 1280, height: 900, windowState: 'normal' },
    })
  } catch (err) {
    console.log(`could not center the Naukri window: ${err.message}`)
  }
}

async function login() {
  delete process.env.BROWSER_CDP_ENDPOINT
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.STEALTH_HEADLESS = '0'
  delete process.env.STEALTH_OFFSCREEN
  const { browser, context, page } = await launchBrowser({ withSession: false })
  await centerWindow(context, page)

  try {
    await page
      .goto('https://www.naukri.com/nlogin/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
      .catch(() => {})
    await page.waitForTimeout(4000)

    const body = (await page.locator('body').innerText().catch(() => '')).toLowerCase()
    if (/access denied|errors\.edgesuite\.net/.test(body)) {
      return reportFail(
        'NAUKRI_BLOCKED',
        'Naukri blocked this browser session. Close other Naukri windows and retry.',
      )
    }

    console.log('Naukri login window is open. Sign in there; waiting up to 5 minutes...')
    const deadline = Date.now() + 280000
    let lastCheck = 0
    while (Date.now() < deadline) {
      if (Date.now() - lastCheck >= 5000) {
        lastCheck = Date.now()
        const check = await confirmSession(page)
        if (check.ok) {
          await page.waitForTimeout(1500)
          const finalCookies = await readCookies(context)
          reportOk({ name: check.name, email: EMAIL, credentials: finalCookies })
          return
        }
      }
      await page.waitForTimeout(1500)
    }

    return reportFail(
      'LOGIN_TIMEOUT',
      'Naukri did not finish signing in. Complete the login in the window and retry.',
    )
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    const browserHandle = context.browser()
    if (browserHandle) await browserHandle.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

login().finally(() => clearTimeout(watchdog))
