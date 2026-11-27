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

async function looksLoggedIn(page, cookies) {
  const url = page.url()
  if (/nlogin|login/i.test(url)) return false
  if (/mnjuser|my-naukri|homepage/i.test(url)) return true
  if (cookies.naukri_user || cookies.NaukriUser || cookies.naukri_uid) return true
  const body = (await page.locator('body').innerText().catch(() => '')).toLowerCase()
  return /logout|my naukri|view profile/.test(body)
}

async function login() {
  delete process.env.BROWSER_CDP_ENDPOINT
  process.env.JOBPILOT_PROFILE_SUFFIX = `${process.env.JOBPILOT_PROFILE_SUFFIX || ''}-naukri`
  process.env.STEALTH_HEADLESS = '0'
  delete process.env.STEALTH_OFFSCREEN
  const { browser, context, page } = await launchBrowser({ withSession: false })

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
    while (Date.now() < deadline) {
      const cookies = await readCookies(context)
      if (looksLoggedIn(page, cookies)) {
        await page.waitForTimeout(2000)
        const finalCookies = await readCookies(context)
        const name = (await page.title().catch(() => ''))
          .replace(/\s*[-|].*$/, '')
          .trim()
        reportOk({ name, email: EMAIL, credentials: finalCookies })
        return
      }
      await page.waitForTimeout(2000)
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
