/**
 * Sign in to LinkedIn and return the session cookies.
 *
 * The password arrives in SCRIPT_ARG_PASSWORD, is typed into LinkedIn's own
 * form and is never written to disk. Only the resulting cookies are returned;
 * the backend stores them encrypted.
 */

import { launchBrowser } from '../utils/browser.js'
import { humanClick, humanSettle, humanType, randomWait } from '../utils/humanize.js'
import { reportOk, reportFail } from '../utils/report.js'

const EMAIL = (process.env.SCRIPT_ARG_EMAIL || '').trim()
const PASSWORD = process.env.SCRIPT_ARG_PASSWORD || ''
const CODE = (process.env.SCRIPT_ARG_VERIFICATION_CODE || '').trim()

const HARD_DEADLINE_MS = 210000
const watchdog = setTimeout(() => {
  reportFail('TIMEOUT', 'LinkedIn login did not finish in time')
  process.exit(1)
}, HARD_DEADLINE_MS)

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

async function submit(page) {
  await page.keyboard.press('Enter')
  const button = page
    .locator('button[type="submit"], button')
    .filter({ hasText: /^(sign in|log in|submit|continue|verify)$/i })
    .first()
  if (await button.isVisible().catch(() => false)) {
    await humanClick(page, button)
  }
}

async function readSession(context) {
  const cookies = await context.cookies('https://www.linkedin.com')
  const values = {}
  for (const cookie of cookies) values[cookie.name] = cookie.value
  return values
}

async function signedInName(page) {
  const title = (await page.title().catch(() => '')).replace(/\s*\|\s*LinkedIn\s*$/i, '').trim()
  const vanity = page.url().match(/linkedin\.com\/in\/([^/?#]+)/)?.[1] || ''
  return { name: title, vanity }
}

async function login() {
  const { context, page } = await launchBrowser({ withSession: false })

  try {
    await page
      .goto('https://www.linkedin.com/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
      .catch(() => {})
    await randomWait(1500, 2500)

    const emailInput = await findVisible(
      page,
      ['input#username', 'input[autocomplete*="username"]', 'input[name="session_key"]'],
      25000,
    )
    if (!emailInput) {
      return reportFail('SELECTOR_MISS', 'Could not find the LinkedIn login form.')
    }
    await humanClick(page, emailInput)
    await humanType(page, EMAIL)
    await randomWait(400, 900)

    const passwordInput = await findVisible(
      page,
      ['input#password', 'input[autocomplete="current-password"]', 'input[name="session_password"]'],
      20000,
    )
    if (!passwordInput) {
      return reportFail('SELECTOR_MISS', 'The LinkedIn password field never appeared.')
    }
    await humanClick(page, passwordInput)
    await humanType(page, PASSWORD)
    await randomWait(400, 900)
    await submit(page)

    // LinkedIn sometimes asks for an email/SMS code on /checkpoint/challenge.
    const deadline = Date.now() + 120000
    let checkpoint = false
    while (Date.now() < deadline) {
      const url = page.url()
      if (/\/feed\/?|\/home\/?|\/mynetwork\/?/.test(url)) break
      if (/\/checkpoint\//.test(url)) {
        checkpoint = true
        const codeInput = await findVisible(
          page,
          [
            'input[autocomplete="one-time-code"]',
            'input[name="pin"]',
            'input[id*="verification" i][type="text"]',
          ],
          5000,
        )
        if (codeInput && CODE) {
          await humanClick(page, codeInput)
          await humanType(page, CODE)
          await submit(page)
          await randomWait(2000, 3000)
          continue
        }
        break
      }
      const body = (await page.locator('body').innerText().catch(() => '')).toLowerCase()
      if (/wrong password|incorrect password|password you entered|try again/.test(body)) {
        return reportFail('LOGIN_FAILED', 'LinkedIn says the password is wrong.')
      }
      if (/couldn'?t find your account|no account found|not found/.test(body)) {
        return reportFail('LOGIN_FAILED', 'LinkedIn could not find that email.')
      }
      await new Promise((resolve) => setTimeout(resolve, 800))
    }

    const cookies = await readSession(context)
    if (!cookies.li_at || !cookies.JSESSIONID) {
      if (checkpoint) {
        return reportFail(
          'LINKEDIN_CHALLENGE',
          'LinkedIn wants a verification code or manual check. Retry with the code LinkedIn sent you.',
        )
      }
      const body = (await page.locator('body').innerText().catch(() => ''))
        .replace(/\s+/g, ' ')
        .slice(0, 200)
      return reportFail(
        'LOGIN_TIMEOUT',
        `LinkedIn did not finish signing in.${body ? ` LinkedIn says: "${body}"` : ''}`,
      )
    }

    // Open the feed once so the session is fully established.
    await page
      .goto('https://www.linkedin.com/feed/', { waitUntil: 'domcontentloaded', timeout: 45000 })
      .catch(() => {})
    await randomWait(2000, 3500)
    const { name, vanity } = await signedInName(page)
    const finalCookies = await readSession(context)

    reportOk({
      name: name || '',
      vanity: vanity || '',
      credentials: {
        li_at: finalCookies.li_at || '',
        JSESSIONID: finalCookies.JSESSIONID || '',
        bcookie: finalCookies.bcookie || '',
        lidc: finalCookies.lidc || '',
        liap: finalCookies.liap || '',
      },
    })
  } catch (err) {
    reportFail(err.code || 'ERROR', err.message)
    process.exitCode = 1
  } finally {
    const browser = context.browser()
    if (browser) await browser.close().catch(() => {})
    clearTimeout(watchdog)
  }
}

if (!EMAIL || !PASSWORD) {
  reportFail('VALIDATION', 'email and password are required')
  process.exitCode = 1
  clearTimeout(watchdog)
} else {
  login().finally(() => clearTimeout(watchdog))
}
